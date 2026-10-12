/* TR-606-style analog voice family. Included after the shared RBJ/noise
 * helpers and kit808_render in kit_engine.c. These are circuit-informed
 * abstractions, not a recovered/validated Roland ACB implementation. */
#include "kit606_source.inc"

/* v9.31 hats retained for the listening candidate: closer on all eight
 * selected The_Machine hat recordings. The cymbal keeps the v9.32 carrier.
 * This selection is based on comparisons, not a circuit-equivalence claim. */
static float kit606_hat_source_at(float ratio, u32 frame, float *ph) {
    static const float hz[6] = {208.0f, 311.0f, 421.0f, 557.0f, 680.0f, 917.0f};
    float x = 0;
    for (int j = 0; j < 6; ++j) {
        float dt = hz[j] * ratio / KIT_FS;
        u32 step = (u32)(dt * 4294967296.0f);
        u32 phase = step * frame;
        float p = (float)phase * 2.3283064365386963e-10f;
        if (p >= 1.0f) p = 0.0f;
        ph[j] = p;
        x += kit_pulse(p, dt, 0.47f);
    }
    return x * (1.0f/6.0f);
}

static void kit606_start(kit_voice *v, float pitch, float decay, float tone) {
    int j;
    for (j = 0; j < 5; ++j) v->q[j].z1 = v->q[j].z2 = 0;
    for (j = 0; j < 3; ++j) { v->e[j] = 0; v->ed[j] = 0; }
    v->f = v->fend = v->pe = v->pdec = 0;
    v->amp = 1; v->adec = 1; v->nmix = kit_exp2(1.2f * tone);
    v->ratio = pitch; v->group = 0;
    float k = kit_clampf(decay, 0.1f, 4.0f);
    float r = kit_clampf(pitch, 0.25f, 4.0f);
    switch (v->drum) {
    case T6_BD: { /* damped resonant kick: a fast trigger blip over a 56 Hz ring */
        /* Least-squares fit to the averaged recordings (0-60 ms): ring
         * 0.594 cos(2pi 56.2 t + 0.957) e^(-t/48 ms; 44 ms fits the full tail) plus blip
         * 1.347 sin(2pi 163 t - 0.185) e^(-t/2.7 ms), 0.53 ms rise. Both
         * resonators start from that state instead of being pulsed. */
        v->fend = 56.2f * r;
        kit_free_ring(&v->q[0], v->fend, kit_clampf(0.044f * k, 0.011f, 0.47f), 0.0686f, -0.0971f);
        kit_free_ring(&v->q[1], 163.0f * r, 0.0027f, -0.0496f, 0.2648f);
        v->e[0] = 1; v->ed[0] = KIT_TAU(0.00053f);
        v->lp = 0;
        v->bp = 1.0f - kit_exp2(-6.28318531f * 1.4427f * 2500.0f * v->nmix / KIT_FS);
        break;
    }
    case T6_SD: /* resonant body plus filtered noise representing the snare wires */
        bq_bp(&v->q[0], 225.0f*r, 12.0f); bq_bp(&v->q[1], 335.0f*r, 10.0f);
        bq_hp(&v->q[2], kit_clampf(1800.0f*v->nmix, 700, 9000), 0.72f);
        bq_lp(&v->q[3], 7000.0f, 0.7f);
        /* Empirical noise-tail calibration: 25 ms tracked the available
         * labeled references better than the original 120 ms prototype.
         * This is not a component-derived Roland time constant. */
        v->e[0] = 1; v->ed[0] = KIT_TAU(0.030f*k);
        break;
    case T6_LT: case T6_HT: { /* two RC-damped twin-T-like tom resonances */
        float base = v->drum == T6_LT ? 133.0f : 204.0f;
        v->f = base * r * 1.22f; v->fend = base * r;
        v->pe = v->drum == T6_LT ? 0.33f : 0.25f; v->pdec = KIT_TAU(v->drum == T6_LT ? 0.029f : 0.008f);
        v->qv = kit_clampf(12.0f*k, 2.0f, 60.0f);
        v->e[0] = 1; v->ed[0] = KIT_TAU((v->drum == T6_LT ? 0.055f : 0.031f)*k);
        break;
    }
    case T6_CY: /* shared Schmitt oscillator source into two modeled resonant bands */
        v->ratio = r;
        bq_bp(&v->q[0],3000,4);bq_bp(&v->q[1],7500,4);
        /* Shared IC15 pre-envelope carrier is maintained outside voices. */
        bq_hp(&v->q[2], 2300.0f, 0.8f); bq_hp(&v->q[3], 8700.0f, 1.0f);
        bq_bp(&v->q[4], 12500.0f, 1.2f);   /* recordings keep 12-16 kHz air */
        /* Recordings: 7.8 kHz centroid; a fast 20 dB drop (t20 115 ms), then a
         * tail with the same 6-8 kHz centre (t40 784 ms). */
        v->e[0] = 1; v->ed[0] = KIT_TAU(0.36f*k);
        v->e[1] = 1; v->ed[1] = KIT_TAU(0.050f*k);
        break;
    case T6_OH: case T6_CH: /* both envelopes feed the same Q37/IC12A audio path */
        v->ratio = r; v->group = 1;
        bq_bp(&v->q[1], 6900.0f, 4.2f);
        /* Nominal isolated IC12A high-pass core: 1 nF / 1 nF,
         * 18 kOhm feedback, 39 kOhm || 39 kOhm bias, gain 2.
         * Loading and transistor nonlinearity remain approximations. */
        /* Preserve the v9.31 CH-only recording correction and OH path. */
        bq_hp(&v->q[2], v->drum == T6_CH ? 10000.0f : 8495.0624f, 1.13545f);
        v->e[0] = 1;
        v->ed[0] = KIT_TAU((v->drum == T6_OH ? 0.45f : 0.018f)*k);
        break;
    }
}

static float kit606_render(kit_voice *v) {
    u32 n = v->n;
    float y = 0, lo, hi;
    switch (v->drum) {
    case T6_BD:
        y = bq_run(&v->q[0], 0.0f);
        if (n < 960) { y = (y + bq_run(&v->q[1], 0.0f)) * (1.0f - v->e[0]); v->e[0] *= v->ed[0]; }
        v->lp += v->bp * (y - v->lp); y = v->lp;
        if (n > 5000 && kit_absf(v->q[0].z1) + kit_absf(v->q[0].z2) < 1e-6f) v->live = 0;
        break;
    case T6_SD:
        y = 2.2f*bq_run(&v->q[0], n < 40 ? 1.0f : 0.0f)
          + 0.9f*bq_run(&v->q[1], n < 40 ? 1.0f : 0.0f);
        y += 0.30f*bq_run(&v->q[3], bq_run(&v->q[2], kit_noise(v)))*v->e[0]*kit_clampf(v->nmix, 0.5f, 1.7f);
        v->e[0] *= v->ed[0];
        if (n > 7000 && v->e[0] < KIT_SILENT) v->live = 0;
        break;
    case T6_LT: case T6_HT: {
        float f = v->fend * (1.0f + v->pe); v->pe *= v->pdec;
        v->ph[0] += f / KIT_FS; v->ph[0] -= (float)(int)v->ph[0];
        /* TONE is an exposed kit-engine control, not a TR-606 panel control:
         * use it for a restrained second-harmonic/body balance. */
        float h2 = kit_clampf(0.16f + (v->nmix - 1.0f)*0.14f, 0.04f, 0.34f);
        y = (kit_sin2pi(v->ph[0]) + h2*kit_sin2pi(v->ph[0]*2.0f) + 0.02f*kit_sin2pi(v->ph[0]*3.0f))*v->e[0]*0.85f;
        v->e[0] *= v->ed[0];
        if (n > 6000 && v->e[0] < KIT_SILENT) v->live = 0;
        break;
    }
    case T6_CY: {
        if(v->sweep_on||v->noise_on){
            static const float hz[6]={246.4162f,308.02025f,367.00285f,418.16083f,440.40342f,627.24123f};
            float x=0;for(int j=0;j<6;++j){float f=hz[j]*v->ratio;x+=kit_pulse(kit_parameter_phase(v,j,f),f/KIT_FS,.47980525f);}
            x=kit_parameter_metal(v,x*(1.0f/6));
            lo=bq_run(&v->q[0],x);hi=bq_run(&v->q[1],x);
        }else kit606_carrier(v, &lo, &hi);
        /* The envelope/VCA precedes each output high-pass in the circuit. */
        hi *= v->e[1] + 0.16f*v->e[0];
        y = 0.45f*bq_run(&v->q[2], lo*v->e[0])
          + (4.0f*bq_run(&v->q[3], hi) + 0.06f*bq_run(&v->q[4], kit_noise(v))*(v->e[1] + 0.16f*v->e[0]))*v->nmix;
        v->e[0] *= v->ed[0]; v->e[1] *= v->ed[1];
        if (n > 1000 && v->e[0] < KIT_SILENT && v->e[1] < KIT_SILENT) v->live = 0;
        break;
    }
    case T6_OH: case T6_CH:
        if(v->sweep_on){static const float hz[6]={208,311,421,557,680,917};y=0;for(int j=0;j<6;++j){float f=hz[j]*v->ratio;y+=kit_pulse(kit_parameter_phase(v,j,f),f/KIT_FS,.47f);}y*=1.0f/6;}
        else y=kit606_hat_source_at(v->ratio,v->source_frame,v->ph);
        y=kit_parameter_metal(v,y);
        y = bq_run(&v->q[2], (bq_run(&v->q[1], y) + 0.15f*y) * (v->drum == T6_OH ? (v->e[0] > 0.3f ? (v->e[0] - 0.3f) * (1.0f / 0.7f) : 0.0f) : v->e[0]))
          * (v->drum == T6_OH ? 2.5f : 2.75f) * kit_clampf(v->nmix, 0.55f, 1.55f);
        v->e[0] *= v->ed[0];
        if (n > 1000 && v->e[0] < KIT_SILENT) v->live = 0;
        break;
    }
    v->n = n + 1;
    /* Host raw renders advance here; kit_output supplies the common live
     * frame (or isolated export age) before each firmware sample. */
    v->source_frame += 1;
    return y * v->gain;
}
