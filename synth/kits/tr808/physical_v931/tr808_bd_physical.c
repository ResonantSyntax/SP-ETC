#include "../physical_v930/tr808_bd_physical.h"

#ifndef T8P_USE_LIBM
#define T8P_USE_LIBM 1
#endif
#if T8P_USE_LIBM
#include <math.h>
#else
#include "../physical_v930/portable_math_tables.h"
#endif

#define T8P_HALF_STEP (1.0f / 96000.0f)
#define T8P_ALPHA 14.3150f
#define T8P_KNEE (-0.5560f)
/* v931: empirical 2.8x leakage coefficient calibration to recorded TR-808
 * attack pitch. This is not a recovered Roland model or measured transistor law. */
#define T8P_SLOPE 4.1342000000e-5f

static float t8p_bound(float x, float low, float high) {
    if (!(x >= low)) return low;
    return x > high ? high : x;
}

/* Published current law, numerically stable. Exactly two Newton iterations
 * and one final current evaluation per rest-state sample; no data-dependent
 * convergence loop and no unbounded exponential argument. */
static float t8p_leakage(float volts, float *slope) {
    float q = -T8P_ALPHA * (volts - T8P_KNEE);
    float u = q < 0 ? -q : q;
    float soft, tail;
#if T8P_USE_LIBM
    float e = expf(-u);
    soft = log1pf(e);
    tail = e / (1.0f + e);
#else
    if (u >= 16.0f) { soft = 0; tail = 0; }
    else {
        float location = u * 4.0f;
        unsigned index = (unsigned)location;
        float t = location - (float)index;
        const float *c = t8p_softplus_cubic[index];
        soft = c[0] + t * (c[1] + t * (c[2] + t * c[3]));
        tail = -4.0f * (c[1] + t * (2.0f*c[2] + t * 3.0f*c[3]));
    }
#endif
    *slope = T8P_SLOPE * (q >= 0 ? 1.0f - tail : tail);
    return -(T8P_SLOPE / T8P_ALPHA) * ((q > 0 ? q : 0) + soft);
}

static float t8p_negative_expm1(float x) {
#if T8P_USE_LIBM
    return expm1f(x);
#else
    float u = -x;
    if (u >= 16.0f) return -1.0f;
    unsigned index = (unsigned)(u * 4.0f);
    float f = u - 0.25f * (float)index;
    float em1 = -f * (1.0f - f * (0.5f - f * (1.0f/6.0f - f * (1.0f/24.0f - f/120.0f))));
    float e = t8p_exp_negative_grid[index];
    /* Avoid cancellation near zero; this is expm1(-f) when index==0. */
    return (e - 1.0f) + e * em1;
#endif
}

T8P_API void t8p_configure(t8p_state *s, float decay, float tone, float pitch) {
    decay = t8p_bound(decay, 0, 1);
    tone = t8p_bound(tone, 0, 1);
    pitch = t8p_bound(pitch, 0.25f, 4.0f);
    float rd = 500000.0f * decay;
    float gh = rd / (47000.0f + rd);
    float gr_c = (1.0f / 1000000.0f) / 15.0e-9f;
    float gf_c = (1.0f / 470000.0f) / 15.0e-9f;
    s->core_a = -pitch / (1000000.0f * 15.0e-9f);
    s->damping = pitch * (-2.0f / (1000000.0f * 15.0e-9f) + gf_c * gh);
    s->feedback = pitch * gf_c * (1.0f - gh);
    s->shelf_rate = pitch / ((47000.0f + rd) * 33.0e-6f);
    s->feedback_input = pitch * gf_c * gh;
    s->retrigger_input = -pitch * gr_c;
    s->leakage_gain = pitch * (47000.0f / 53800.0f) / 15.0e-9f;
    s->conductance[0] = pitch * ((1.0f/53800.0f) + (1.0f/1000000.0f) + (1.0f/470000.0f)) / 15.0e-9f;
    s->conductance[1] = pitch * ((1.0f/6800.0f) + (1.0f/1000000.0f) + (1.0f/470000.0f)) / 15.0e-9f;
    s->solve_a = T8P_HALF_STEP * s->core_a;
    s->solve_z0 = 1.0f / (1.0f + T8P_HALF_STEP * s->shelf_rate);
    s->solve_z = T8P_HALF_STEP * s->shelf_rate * s->solve_z0;
    s->solve_feedback = T8P_HALF_STEP * s->feedback * s->solve_z0;
    for (unsigned gate = 0; gate < 2; ++gate) {
        float denominator = 1.0f - T8P_HALF_STEP * s->damping
            - T8P_HALF_STEP * s->conductance[gate] * s->solve_a
            - T8P_HALF_STEP * s->feedback * s->solve_z;
        s->inverse_denominator[gate] = 1.0f / denominator;
        float saturated_damping = s->damping - (s->conductance[gate] + s->feedback_input);
        s->inverse_saturated_denominator[gate] = 1.0f / (1.0f - T8P_HALF_STEP * saturated_damping
            - T8P_HALF_STEP * s->conductance[gate] * s->solve_a);
    }
    s->correction_b = s->inverse_denominator[0] * T8P_HALF_STEP * s->leakage_gain;
    s->correction_a = s->solve_a * s->correction_b;
    s->correction_z = s->solve_z * s->correction_b;
    float rt = 10000.0f * tone;
    float req = 220.0f + 10000.0f * rt / (10000.0f + rt);
    s->tone_w = T8P_HALF_STEP / (req * 100.0e-9f);
    s->tone_inverse = 1.0f / (1.0f + s->tone_w);
}

T8P_API void t8p_init(t8p_state *s, float decay, float tone, float pitch) {
    s->a = s->b = s->z = s->da = s->db = s->dz = 0;
    s->shaper_z = s->tone_history = s->level_z = s->output_z = 0;
    s->rp_voltage = s->previous_envelope = s->trigger_volts = s->last_plus = 0;
    s->last_body = s->last_common = 0;
    s->trigger_left = s->envelope_left = 0;
    float tau = 4700.0f * 100000.0f * 15.0e-9f / 104700.0f;
    float shelf = 4700.0f / 104700.0f;
    float w = 96000.0f * tau;
    s->shaper_b0 = (w + shelf) / (w + 1.0f);
    s->shaper_b1 = (shelf - w) / (w + 1.0f);
    s->shaper_a1 = (1.0f - w) / (w + 1.0f);
    w = 96000.0f * (100000.0f * 0.47e-6f);
    s->level_b0 = 0.5f * w / (1.0f + w);
    s->level_a1 = (1.0f - w) / (1.0f + w);
    s->output_b0 = 0.82f * w / (1.0f + w);
    s->output_a1 = s->level_a1;
    /* exp(-1/(48000 * 1M * 33nF)), evaluated once offline. */
    s->rp_decay = 0.9993688861007690f;
    t8p_configure(s, decay, tone, pitch);
}

T8P_API void t8p_trigger(t8p_state *s, float volts) {
    s->trigger_volts = t8p_bound(volts, 4.0f, 14.0f);
    s->trigger_left = 48;
    s->envelope_left = 288;
}

/* Capacitor coordinates: a=Vcomm-Vminus and a-b=Vcomm-Vbody. For the
 * unsaturated op-amp Vminus=Vplus; for a saturated region Vbody=rail and
 * Vminus=rail-b, Vcomm=rail+a-b. Changing regions never clips these states.
 * A nonzero rail selects a saturated region; zero means virtual-short region.
 * This analytically solves the same simultaneous trapezoidal nodal system. */
static float t8p_solve_region(const t8p_state *s, unsigned attack, float plus,
                             float rp, float rail, float *a, float *b, float *z) {
    float g = s->conductance[attack];
    float source = rail != 0 ? rail : plus;
    float force_b = (g + s->feedback_input) * source + s->retrigger_input * rp;
    float force_z = s->shelf_rate * source;
    float r0 = s->a + T8P_HALF_STEP * s->da;
    float r1 = s->b + T8P_HALF_STEP * (s->db + force_b);
    float r2 = s->z + T8P_HALF_STEP * (s->dz + force_z);
    float inverse = rail != 0 ? s->inverse_saturated_denominator[attack] : s->inverse_denominator[attack];
    float base_b = (r1 + T8P_HALF_STEP * g * r0 + s->solve_feedback * r2) * inverse;
    float base_a = r0 + s->solve_a * base_b;
    float base_z = s->solve_z0 * r2 + (rail != 0 ? 0 : s->solve_z * base_b);
    float current = 0;
    if (!attack) {
        float cb = rail != 0 ? inverse * T8P_HALF_STEP * s->leakage_gain : s->correction_b;
        float ca = rail != 0 ? s->solve_a * cb : s->correction_a;
        float cz = rail != 0 ? 0 : s->correction_z;
        float base_m = base_a + source - (rail != 0 ? base_b : 0);
        float cm = ca - (rail != 0 ? cb : 0);
        float m = base_m, slope;
        for (unsigned iteration = 0; iteration < 2; ++iteration) {
            current = t8p_leakage(m, &slope);
            float residual = (m - base_m) - cm * current;
            m -= residual / (1.0f - cm * slope);
        }
        current = t8p_leakage(m, &slope);
        base_a += ca * current;
        base_b += cb * current;
        base_z += cz * current;
    }
    *a = base_a; *b = base_b; *z = base_z;
    return current;
}

T8P_API float t8p_next(t8p_state *s) {
    float trigger = s->trigger_left ? s->trigger_volts : 0;
    if (s->trigger_left) --s->trigger_left;
    unsigned attack = s->envelope_left != 0;
    float envelope = attack ? 15.0f : 0;
    if (s->envelope_left) --s->envelope_left;
    float linear = s->shaper_b0 * trigger + s->shaper_z;
    s->shaper_z = s->shaper_b1 * trigger - s->shaper_a1 * linear;
    float plus = linear >= 0 ? linear : 0.71f * t8p_negative_expm1(linear);
    s->last_plus = plus;
    float rp = s->rp_voltage * s->rp_decay + envelope - s->previous_envelope;
    if (rp > 0.71f) rp = 0.71f;
    s->rp_voltage = rp;
    s->previous_envelope = envelope;

    float base_a, base_b, base_z;
    float current = t8p_solve_region(s, attack, plus, rp, 0, &base_a, &base_b, &base_z);
    float body = base_b + plus;
    float common = base_a + plus;
    if (body > 15.0f || body < -15.0f) {
        float rail = body > 0 ? 15.0f : -15.0f;
        current = t8p_solve_region(s, attack, plus, rp, rail, &base_a, &base_b, &base_z);
        body = rail;
        common = body + base_a - base_b;
    }
    s->a = base_a; s->b = base_b; s->z = base_z;
    s->da = s->core_a * base_b;
    s->db = s->conductance[attack] * common + 2.0f * s->core_a * base_b
          + s->feedback_input * body + s->feedback * base_z + s->retrigger_input * rp;
    if (!attack) s->db += s->leakage_gain * current;
    s->dz = s->shelf_rate * (body - base_z);
    s->last_body = body; s->last_common = common;
    float tone = (s->tone_history + s->tone_w * body) * s->tone_inverse;
    s->tone_history = tone + s->tone_w * (body - tone);
    float level = s->level_b0 * tone + s->level_z;
    s->level_z = -s->level_b0 * tone - s->level_a1 * level;
    float output = s->output_b0 * level + s->output_z;
    s->output_z = -s->output_b0 * level - s->output_a1 * output;
    return output;
}
