#ifndef TR808_BD_PHYSICAL_H
#define TR808_BD_PHYSICAL_H
#include <stdint.h>
#ifndef T8P_API
#define T8P_API
#endif

/* Fixed 48 kHz. All dynamic state and coefficients belong to this instance.
 * Decay/tone are physical resistance fractions, not existing engine knobs.
 * Pitch time-scales the complete core (including its feedback shelf), so
 * resonant decay time scales inversely with pitch. Excitation timers and
 * pulse-shaper/output filters remain at their original real-time rates. */
typedef struct t8p_state {
    float a, b, z, da, db, dz;
    float core_a, damping, feedback, shelf_rate;
    float feedback_input, retrigger_input, leakage_gain;
    float conductance[2], inverse_denominator[2];
    float solve_a, solve_feedback, solve_z, solve_z0;
    float correction_a, correction_b, correction_z;
    float shaper_b0, shaper_b1, shaper_a1, shaper_z;
    float tone_w, tone_inverse, tone_history;
    float level_b0, level_a1, level_z;
    float output_b0, output_a1, output_z;
    float rp_decay, rp_voltage, previous_envelope, trigger_volts, last_plus;
    float inverse_saturated_denominator[2], last_body, last_common;
    uint16_t trigger_left, envelope_left;
} t8p_state;

/* init clears state. configure changes coefficients without clearing any
 * capacitor/filter/previous-derivative history or active trigger timer.
 * Ranges clamp to decay/tone [0,1], pitch [0.25,4]. NaN uses lower endpoint. */
T8P_API void t8p_init(t8p_state *s, float decay_fraction, float tone_fraction, float pitch_ratio);
T8P_API void t8p_configure(t8p_state *s, float decay_fraction, float tone_fraction, float pitch_ratio);
/* Trigger voltage clamps to [4,14]. Timers restart at 1/6 ms. If the envelope
 * is already high it stays high; no false falling/rising edge is fabricated.
 * This envelope retrigger convention is an explicit model approximation. */
T8P_API void t8p_trigger(t8p_state *s, float trigger_volts);
/* Output is circuit volts through the fixed half-level/output approximations;
 * no normalized output gain, output limiter, allocator or silent-state reset.
 * The core op-amp has ideal +/-15V rails, solved with capacitor states intact. */
T8P_API float t8p_next(t8p_state *s);

#endif
