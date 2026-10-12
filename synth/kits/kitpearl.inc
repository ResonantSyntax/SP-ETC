/* Pearl Syncussion SY-1-inspired oscillator-source modes.
 * Original DSP implementation, not recovered Pearl firmware or an exact
 * circuit replica. kit_voice and the kit_* helpers come from kit_engine.c.
 */
static void kitpearl_start(kit_voice *v, float pitch, float decay, float tone) {
    float k = kit_clampf(decay, 0.1f, 4.0f);
    float t = kit_clampf(tone, -1.0f, 1.0f);
    float sweep = 0.25f + 2.25f * (t + 1.0f) * 0.5f;

    v->ph[0] = v->ph[1] = 0.0f;
    v->pe = 1.0f;
    v->pdec = kit_decay60(0.075f + 0.09f * (1.0f - (t + 1.0f)*0.5f));
    v->amp = 1.0f;
    v->adec = kit_decay60(0.30f * k);
    v->namp = 0.0f;
    v->ndec = kit_decay60(0.045f * k);
    v->lp = 0.0f;
    v->svf_f = kit_clampf((0.025f + 0.30f * (t + 1.0f)*0.5f), 0.025f, 0.34f);
    v->nmix = sweep;                 /* modeled sweep range */
    v->f = 220.0f * pitch;           /* estimated nominal pitch, not a spec */
    v->fend = v->f / (1.0f + sweep); /* downward pitch transient */
    v->mi = 0.0f;
    v->mr = 1.61f;                    /* estimated second-oscillator ratio */
    v->mdec = kit_decay60(0.035f);    /* short FM index decay */

    switch (v->drum) {
    case SY_TONE:                    /* Pearl source mode A: one oscillator */
        v->f = 155.0f * pitch;
        v->fend = v->f / (1.0f + sweep);
        v->adec = kit_decay60(0.38f * k);
        break;
    case SY_DUAL:                    /* mode C: two oscillators mixed */
        v->f = 245.0f * pitch;
        v->fend = v->f / (1.0f + 0.75f*sweep);
        v->mr = 1.47f;
        v->adec = kit_decay60(0.52f * k);
        break;
    case SY_FM:                      /* mode B: one oscillator modulates the other */
        v->f = 185.0f * pitch;
        v->fend = v->f / (1.0f + 0.55f*sweep);
        v->mr = 2.13f;
        v->mi = 0.22f + 0.25f * (t + 1.0f);
        v->adec = kit_decay60(0.34f * k);
        break;
    case SY_NOISE:                   /* mode F: noise source only */
    default:
        v->f = v->fend = 0.0f;
        v->svf_f=kit_clampf(v->svf_f*pitch,.012f,.65f);
        v->pe = 0.0f;
        v->namp = 0.75f;
        v->amp = 0.0f;
        v->adec = 1.0f;
        v->ndec = kit_decay60(0.24f * k);
        break;
    }
}

static float kitpearl_render(kit_voice *v) {
    float y = 0.0f, f, x;
    v->pe *= v->pdec;
    f = v->fend + (v->f - v->fend) * v->pe;

    if (v->drum == SY_NOISE) {
        x = kit_noise(v);
        v->lp += v->svf_f * (x - v->lp);
        y = v->lp * v->namp;
        v->namp *= v->ndec;
    } else {
        v->ph[0] += f / KIT_FS;
        v->ph[0] -= (float)(int)v->ph[0];
        if (v->drum == SY_TONE) {
            y = kit_sin2pi(v->ph[0]) * v->amp;
        } else if (v->drum == SY_DUAL) {
            float f2 = kit_clampf(f * v->mr, 20.0f, 16000.0f);
            v->ph[1] += f2 / KIT_FS;
            v->ph[1] -= (float)(int)v->ph[1];
            /* Slightly unequal levels preserve the characteristic beating. */
            y = (0.57f * kit_sin2pi(v->ph[0]) + 0.43f * kit_sin2pi(v->ph[1])) * v->amp;
        } else {                       /* phase modulation approximation to the FM source */
            float f2 = kit_clampf(f * v->mr, 20.0f, 16000.0f);
            v->ph[1] += f2 / KIT_FS;
            v->ph[1] -= (float)(int)v->ph[1];
            y = kit_sin2pi(v->ph[0] + v->mi * kit_sin2pi(v->ph[1])) * v->amp;
            v->mi *= v->mdec;
        }
        v->lp += v->svf_f * (y - v->lp); /* WIDTH-inspired low-pass */
        y = v->lp;
        v->amp *= v->adec;
    }
    ++v->n;
    if (v->n > 2400 && v->amp < KIT_SILENT && v->namp < KIT_SILENT) v->live = 0;
    return y * v->gain;
}
