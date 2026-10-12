/* TR-909-inspired analog voices. Included after kit808_render(), where the
 * kit_voice type, filters, oscillators, envelopes and noise helpers exist. */
static void kit909_start(kit_voice *v, float pitch, float decay, float tone) {
    int j;
    for (j = 0; j < 5; ++j) {
        v->q[j].z1 = 0; v->q[j].z2 = 0;
    }
    for (j = 0; j < 3; ++j) { v->e[j] = 0; v->ed[j] = 0; }
    for (j = 0; j < 6; ++j) v->ph[j] = 0;
    v->f = v->fend = v->pe = v->pdec = 0;
    v->amp = 1; v->namp = 0; v->ndec = 0; v->hp1 = v->xprev = 0;
    v->ratio = pitch;
    float d = kit_clampf(decay, 0.1f, 4.0f);
    float color = kit_clampf(tone, -1.0f, 1.0f);
    float bright = kit_exp2(0.8f * color);
    switch (v->drum) {
    case T9_BD: /* pitched VCO-like body, fast pitch sweep, click transient */
        v->f = 155.0f * pitch * kit_exp2(0.18f * color);
        v->fend = 47.0f * pitch;
        v->pe = 1.0f; v->pdec = kit_decay60(0.025f);
        v->adec = kit_decay60(0.34f * d);
        v->namp = 0.24f * bright; v->ndec = kit_decay60(0.0045f);
        break;
    case T9_SD: /* two phase-locked drum oscillators plus filtered snappy noise */
        v->f = 185.0f * pitch;
        v->fend = 205.0f * pitch;
        v->pe = 1.0f; v->pdec = kit_decay60(0.020f);
        v->adec = kit_decay60(0.19f * d);
        bq_bp(&v->q[0], 1800.0f * bright, 0.72f); /* snappy band */
        bq_hp(&v->q[1], 3300.0f * bright, 0.75f);
        v->e[0] = 1.0f; v->ed[0] = kit_decay60(0.23f * d);
        v->e[1] = 1.0f; v->ed[1] = kit_decay60(0.045f * d);
        v->nmix = 0.45f + (color + 1.0f) * 0.32f;
        break;
    case T9_LT: case T9_MT: case T9_HT: {
        /* Initial single-mode fit to saved TR-909 plug-in tom captures:
         * body floor, relative sweep depth, envelope T60 (seconds). */
        static const float hz[3] = {84.3f, 110.6f, 143.3f};
        static const float drop[3] = {0.43f, 0.33f, 0.34f};
        static const float ring[3] = {0.79f, 0.56f, 0.59f};
        static const float sweep_t60[3] = {0.29f, 0.31f, 0.29f};
        j = v->drum - T9_LT;
        v->fend = hz[j] * pitch;
        v->pe = drop[j]*bright; v->pdec = kit_decay60(sweep_t60[j]);
        v->adec = kit_decay60(ring[j] * d);
        v->namp = 0.12f * bright; v->ndec = kit_decay60(0.016f);
        break;
    }
    case T9_RS: /* two short resonant modes and asymmetric clipping */
        bq_bp(&v->q[0], 720.0f * pitch, 7.0f);
        bq_bp(&v->q[1], 1850.0f * pitch, 10.0f);
        v->f = 0; v->adec = kit_decay60(0.065f * d);
        v->namp = 0.10f * bright; v->ndec = kit_decay60(0.003f);
        break;
    case T9_CP: /* four compact noise bursts and a longer diffuse tail */
        bq_bp(&v->q[0], 1250.0f * bright * pitch, 0.62f);
        v->e[0] = 1.0f; v->ed[0] = kit_decay60(0.012f);
        v->e[1] = 1.0f; v->ed[1] = kit_decay60(0.11f * d);
        v->adec = kit_decay60(0.11f * d);
        break;
    }
}

static float kit909_render(kit_voice *v) {
    u32 n = v->n;
    float y = 0.0f, x, f;
    switch (v->drum) {
    case T9_BD:
        f = v->fend + (v->f - v->fend) * v->pe;
        v->pe *= v->pdec;
        v->ph[0] += f / KIT_FS; v->ph[0] -= (float)(int)v->ph[0];
        /* Mild symmetric saturation gives the body a denser analog-style hit. */
        y = kit_sin2pi(v->ph[0]) * v->amp;
        y = y / (1.0f + 0.32f * kit_absf(y));
        y += kit_noise(v) * v->namp; v->namp *= v->ndec;
        v->amp *= v->adec;
        if (n > 480 && v->amp < KIT_SILENT && v->namp < KIT_SILENT) v->live = 0;
        break;
    case T9_SD:
        f = v->fend + (v->f - v->fend) * v->pe;
        v->pe *= v->pdec;
        v->ph[0] += f / KIT_FS;
        v->ph[1] += (f * 1.47f) / KIT_FS;
        y = (0.58f * kit_sin2pi(v->ph[0]) + 0.42f * kit_sin2pi(v->ph[1])) * v->amp * 0.62f;
        x = kit_noise(v);
        y += 0.36f * bq_run(&v->q[0], x) * v->e[0] * v->nmix;
        y += 0.24f * bq_run(&v->q[1], x) * v->e[1] * v->nmix;
        v->e[0] *= v->ed[0]; v->e[1] *= v->ed[1]; v->amp *= v->adec;
        if (n > 480 && v->amp < KIT_SILENT && v->e[0] < KIT_SILENT && v->e[1] < KIT_SILENT) v->live = 0;
        break;
    case T9_LT: case T9_MT: case T9_HT:
        f = v->fend * (1.0f + v->pe); v->pe *= v->pdec;
        v->ph[0] += f / KIT_FS;
        y = kit_sin2pi(v->ph[0]) * v->amp * 0.82f;
        y += kit_noise(v) * v->namp; v->namp *= v->ndec;
        v->amp *= v->adec;
        if (n > 480 && v->amp < KIT_SILENT && v->namp < KIT_SILENT) v->live = 0;
        break;
    case T9_RS:
        x = (n < 2 ? 1.0f : 0.0f) + 0.15f * kit_noise(v);
        y = bq_run(&v->q[0], x) * 2.8f + bq_run(&v->q[1], x) * 1.8f;
        y = y > 0.0f ? y : 0.30f * y;
        y += kit_noise(v) * v->namp; v->namp *= v->ndec;
        v->amp *= v->adec;
        if (n > 480 && v->amp < KIT_SILENT) v->live = 0;
        y *= v->amp;
        break;
    case T9_CP: {
        /* Burst starts at 0, 10, 20 and 30 ms; tail continues under the last. */
        float burst = 0.0f;
        if (n < 4*v->clap_period) {
            u32 phase = n % v->clap_period;
            if (phase == 0) v->e[0] = 1.0f;
            burst = 1.0f - (float)phase / (float)v->clap_period;
        }
        x = kit_noise(v);
        y = bq_run(&v->q[0], x) * (0.82f * burst * v->e[0] + 0.38f * v->e[1]);
        v->e[0] *= v->ed[0]; v->e[1] *= v->ed[1];
        if (n > 4*v->clap_period && v->e[1] < KIT_SILENT) v->live = 0;
        break;
    }
    }
    v->n = n + 1;
    return y * v->gain;
}
