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
    case SDS_BD: /* deep tone with a sharp pitch fall, filtered attack click */
        v->f = (138.0f + 22.0f * (tone + 1.0f)) * pitch;
        v->fend = 48.0f * pitch;
        v->pe = 1.0f; v->pdec = kit_decay60(0.035f);
        v->adec = kit_decay60(0.44f * k);
        v->namp = (0.14f + 0.13f * (tone + 1.0f)) * bright;
        v->ndec = kit_decay60(0.0024f);
        break;
    case SDS_SD: /* two inharmonic head modes plus a tone-shaped noise snare */
        v->f = 190.0f * pitch; v->fend = 174.0f * pitch;
        v->adec = kit_decay60(0.16f * k);
        v->namp = (0.45f + 0.34f * (tone + 1.0f)) * bright;
        v->ndec = kit_decay60(0.20f * k);
        v->hp_a = 0.84f;
        break;
    case SDS_LT: case SDS_MT: case SDS_HT: {
        static const float start_hz[3] = {210.0f, 285.0f, 375.0f};
        static const float end_hz[3] = {72.0f, 105.0f, 145.0f};
        static const float bend_s[3] = {0.060f, 0.050f, 0.043f};
        j = (int)v->drum - (int)SDS_LT;
        /* Tone also varies the bend depth: useful with the shared TONE knob. */
        v->f = start_hz[j] * pitch * (1.0f + 0.17f * (tone + 1.0f));
        v->fend = end_hz[j] * pitch;
        v->pe = 1.0f; v->pdec = kit_decay60(bend_s[j]);
        v->adec = kit_decay60((0.40f - 0.045f*j) * k);
        v->namp = (0.025f + 0.045f * (tone + 1.0f)) * bright;
        v->ndec = kit_decay60(0.010f);
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
          + 0.55f * v->hp1 * v->namp;
    } else {
        /* A one-pole low pass makes the click/noise brightness tuneable. */
        float cutoff = v->drum == SDS_BD ? 5200.0f : 6800.0f;
        float a = kit_clampf(cutoff * v->nmix / KIT_FS, 0.015f, 0.45f);
        v->lp += a * (noise - v->lp);
        y += v->lp * v->namp;
    }
    v->namp *= v->ndec;
    v->amp *= v->adec;
    v->n += 1;
    if (v->n > 3200 && v->amp < KIT_SILENT && v->namp < KIT_SILENT) v->live = 0;
    return y * v->gain;
}
