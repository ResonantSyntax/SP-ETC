/* SDS-V-inspired analog drum voices.
 * This is an original synthesis model, not a circuit netlist or recovered
 * Simmons code. It follows the SDS-V module concept: separately shaped tone,
 * noise and attack/click sources, with falling pitch on the resonant drums.
 * Helpers and kit_voice are defined by kit_engine.c before this include.
 */
static void kitsds_start(kit_voice *v, float pitch, float decay, float tone) {
    int j;
    float k = kit_clampf(decay, 0.1f, 4.0f);
    float bright = kit_exp2(1.2f * kit_clampf(tone, -1.0f, 1.0f));
    for (j = 0; j < 6; ++j) v->ph[j] = 0.0f;
    v->f = v->fend = v->pe = v->pdec = 0.0f;
    v->amp = 1.0f; v->adec = 1.0f;
    v->namp = 0.0f; v->ndec = 1.0f;
    v->lp = v->bp = v->hp1 = v->xprev = 0.0f;
    v->nmix = bright;

    switch (v->drum) {
    case SDS_BD: /* recordings: ~145 Hz bending down (pitch tau ~200 ms),
                  * level tau ~68 ms, bright noise ~27-33 dB under the body */
        v->f = 145.0f * pitch * kit_exp2(0.25f * kit_clampf(tone, -1.0f, 1.0f));
        v->fend = 20.0f * pitch;
        v->pe = 1.0f; v->pdec = KIT_TAU(0.200f);
        v->adec = KIT_TAU(0.068f * k);
        v->namp = 0.42f * bright; v->ndec = KIT_TAU(0.030f);
        break;
    case SDS_SD: /* recordings: ~280 Hz bending (tau ~190 ms), tau ~75 ms; noise band 1.3-4.4 kHz */
        v->f = 280.0f * pitch; v->fend = 20.0f * pitch;
        v->pe = 1.0f; v->pdec = KIT_TAU(0.190f);
        v->adec = KIT_TAU(0.075f * k);
        v->namp = (0.45f + 0.34f * (tone + 1.0f)) * bright;
        v->ndec = KIT_TAU(0.070f * k);
        v->hp_a = 0.84f;
        break;
    case SDS_LT: case SDS_MT: case SDS_HT: {
        /* Recordings (17 toms in three pitch clusters): ~140/205/400 Hz,
         * bending with tau 0.3-0.55 s; level tau ~0.13-0.15 s; noise ~-20..-30 dB. */
        static const float start_hz[3] = {140.0f, 205.0f, 400.0f};
        static const float bend_s[3] = {0.40f, 0.30f, 0.55f};
        static const float level_s[3] = {0.135f, 0.125f, 0.145f};
        j = (int)v->drum - (int)SDS_LT;
        /* Tone also varies the bend depth: useful with the shared TONE knob. */
        v->f = start_hz[j] * pitch * (1.0f + 0.17f * (tone + 1.0f)) * (1.0f/1.17f);
        v->fend = 0.15f * start_hz[j] * pitch;
        v->pe = 1.0f; v->pdec = KIT_TAU(bend_s[j]);
        v->adec = KIT_TAU(level_s[j] * k);
        v->namp = (0.60f + 0.50f * (tone + 1.0f)) * bright;
        v->ndec = KIT_TAU(0.040f);
        break;
    }
    case SDS_ZAP: /* high resonant tom sweep, SDS-like synthetic accent */
    default:
        v->f = 1250.0f * pitch; v->fend = 90.0f * pitch;
        v->pe = 1.0f; v->pdec = kit_decay60(0.075f);
        v->adec = kit_decay60(0.26f * k);
        v->namp = (0.02f + 0.025f * (tone + 1.0f)) * bright;
        v->ndec = kit_decay60(0.003f);
        break;
    }
}

static float kitsds_render(kit_voice *v) {
    float f = v->fend + (v->f - v->fend) * v->pe;
    float y, noise;
    v->pe *= v->pdec;
    v->ph[0] += f / KIT_FS;
    v->ph[0] -= (float)(int)v->ph[0];
    y = kit_sin2pi(v->ph[0]) * v->amp;

    /* Separate decaying noise VCA gives the SDS-style bright transient/body. */
    noise = kit_noise(v);
    if (v->drum == SDS_SD) {
        float cutoff = 2100.0f + 6500.0f * (v->nmix - 0.3f) / 2.0f;
        float a = kit_clampf(cutoff / KIT_FS, 0.035f, 0.40f);
        v->lp += a * (noise - v->lp);
        v->hp1 = v->hp_a * (v->hp1 + v->lp - v->xprev);
        v->xprev = v->lp;
        v->ph[1] += (f * 1.47f) / KIT_FS;
        v->ph[1] -= (float)(int)v->ph[1];
        y = 0.35f * y + 0.24f * kit_sin2pi(v->ph[1]) * v->amp
          + 2.2f * v->hp1 * v->namp;
    } else {
        /* A one-pole low pass makes the click/noise brightness tuneable. */
        float cutoff = v->drum == SDS_BD ? 9000.0f : 6800.0f;
        float a = kit_clampf(cutoff * v->nmix / KIT_FS, 0.015f, 0.45f);
        v->lp += a * (noise - v->lp);
        y += v->lp * v->namp;
    }
    v->namp *= v->ndec;
    v->amp *= v->adec;
    v->n += 1;
    v->source_frame += 1;          /* host renders; kit_output sets it on ARM */
    if (v->n > 3200 && v->amp < KIT_SILENT && v->namp < KIT_SILENT) v->live = 0;
    return y * v->gain;
}
