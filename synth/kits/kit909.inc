/* TR-909 analog voices. Included after kit808_render(), where the kit_voice
 * type, filters, oscillators, envelopes and noise helpers exist.
 * Calibrated against the TR-909 ACB plug-in captured at its default knobs and
 * against 5-29 recordings per voice (The_Machine TR-909 folders): pitch at
 * 5/20/80 ms, decay to -20/-40 dB and 1/3-octave band balance. The 909's hats
 * and cymbals were 6-bit samples; their synthetic stand-ins are procedural. */
static void kit909_start(kit_voice *v, float pitch, float decay, float tone) {
    int j;
    for (j = 0; j < 5; ++j) {
        v->q[j].z1 = 0; v->q[j].z2 = 0;
    }
    for (j = 0; j < 3; ++j) { v->e[j] = 0; v->ed[j] = 0; }
    for (j = 0; j < 6; ++j) v->ph[j] = 0;
    v->f = v->fend = v->pe = v->pdec = 0;
    v->amp = 1; v->namp = 0; v->ndec = 0; v->hp1 = v->xprev = 0; v->lp = 0;
    v->ratio = pitch;
    float d = kit_clampf(decay, 0.1f, 4.0f);
    float color = kit_clampf(tone, -1.0f, 1.0f);
    float bright = kit_exp2(0.8f * color);
    switch (v->drum) {
    case T9_BD:
        /* ACB pitch 211/118/54 Hz at 5/20/80 ms: an exponential glide from
         * 265 Hz to a 50 Hz floor with a 17.4 ms time constant fits all three. */
        v->f = 265.0f * pitch * kit_exp2(0.18f * color);
        v->fend = 50.0f * pitch;
        v->pe = 1.0f; v->pdec = KIT_TAU(0.0174f);
        v->adec = kit_decay60(0.34f * d);
        v->namp = 0.80f * bright; v->ndec = kit_decay60(0.008f);   /* attack click */
        bq_lp(&v->q[0], 6000.0f * bright, 0.7f);
        v->bp = 1.0f - kit_exp2(-6.28318531f * 1.4427f * 95.0f / KIT_FS);    /* body low-pass, 95 Hz */
        break;
    case T9_SD:
        /* ACB body falls from about 231 to 166 Hz with an upper partial near
         * x1.86; the snappy noise peaks near 8 kHz about 9 dB under the body. */
        v->f = 232.0f * pitch; v->fend = 167.0f * pitch;
        v->pe = 1.0f; v->pdec = KIT_TAU(0.008f);
        v->adec = kit_decay60(0.20f * d);
        bq_bp(&v->q[0], 7400.0f * bright, 1.15f);
        bq_hp(&v->q[1], 950.0f, 0.70f);
        bq_lp(&v->q[2], 12000.0f, 0.70f);
        v->e[0] = 1.0f; v->ed[0] = kit_decay60(0.36f * d);
        v->nmix = 1.0f;
        break;
    case T9_LT: case T9_MT: case T9_HT: {
        /* ACB toms at default tune/decay: LT 112->98 Hz, MT 126->119 Hz,
         * HT 161->162 Hz (20/80 ms); t40 360/206/168 ms. A short filtered
         * noise attack gives the quick first 20 dB of decay. */
        static const float hz[3] = {93.0f, 116.0f, 160.0f};
        static const float drop[3] = {0.30f, 0.16f, 0.04f};
        static const float ring[3] = {0.68f, 0.40f, 0.31f};
        static const float sweep_tau[3] = {0.045f, 0.040f, 0.030f};
        j = v->drum - T9_LT;
        v->fend = hz[j] * pitch;
        v->pe = drop[j]*bright; v->pdec = KIT_TAU(sweep_tau[j]);
        v->adec = kit_decay60(ring[j] * d);
        v->namp = 2.0f * bright; v->ndec = kit_decay60(0.035f);
        bq_lp(&v->q[0], 2000.0f, 0.7f);
        break;
    }
    case T9_RS: /* ACB/recordings: modes near 220 and 480 Hz, about 40 ms */
        bq_bp(&v->q[0], 222.0f * pitch, 13.0f);
        bq_bp(&v->q[1], 484.0f * pitch, 15.0f);
        bq_bp(&v->q[2], 1020.0f * pitch, 6.0f);
        bq_bp(&v->q[3], 2400.0f * pitch, 3.0f);
        v->f = 0; v->adec = kit_decay60(0.095f * d);
        break;
    case T9_CP:
        /* ACB: bursts at about 0/11/24/38 ms, then a tail still near -5 dB at
         * 50 ms falling about 9 dB per 20 ms; t40 170 ms. */
        bq_bp(&v->q[0], 1150.0f * bright * pitch, 0.85f);
        v->e[0] = 1.0f; v->ed[0] = kit_decay60(0.012f);
        v->e[1] = 1.0f; v->ed[1] = kit_decay60(0.24f * d);
        v->adec = kit_decay60(0.24f * d);
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
        v->lp += v->bp * (y - v->lp); y = 0.18f * y + 1.45f * v->lp;
        y += bq_run(&v->q[0], kit_noise(v)) * v->namp; v->namp *= v->ndec;
        v->amp *= v->adec;
        if (n > 480 && v->amp < KIT_SILENT && v->namp < KIT_SILENT) v->live = 0;
        break;
    case T9_SD:
        f = v->fend + (v->f - v->fend) * v->pe;
        v->pe *= v->pdec;
        v->ph[0] += f / KIT_FS; v->ph[0] -= (float)(int)v->ph[0];
        v->ph[1] += (f * 1.86f) / KIT_FS; v->ph[1] -= (float)(int)v->ph[1];
        y = (0.56f * kit_sin2pi(v->ph[0]) + 0.44f * kit_sin2pi(v->ph[1])) * v->amp * 0.72f;
        x = kit_noise(v);
        y += 0.42f * bq_run(&v->q[2], bq_run(&v->q[1], bq_run(&v->q[0], x))) * v->e[0] * v->nmix;
        v->e[0] *= v->ed[0]; v->amp *= v->adec;
        if (n > 480 && v->amp < KIT_SILENT && v->e[0] < KIT_SILENT) v->live = 0;
        break;
    case T9_LT: case T9_MT: case T9_HT: {
        f = v->fend * (1.0f + v->pe); v->pe *= v->pdec;
        v->ph[0] += f / KIT_FS; v->ph[0] -= (float)(int)v->ph[0];
        float s = kit_sin2pi(v->ph[0]);
        /* Rounded-triangle VCO: a little 2nd and 3rd harmonic over the sine. */
        float tri = 4.0f * kit_absf(v->ph[0] - 0.5f) - 1.0f;   /* rounded triangle: sine plus triangle overtones */
        y = (0.62f * s - 0.38f * tri + 0.16f * kit_sin2pi(2.0f * v->ph[0])) * v->amp * 0.74f;
        y += bq_run(&v->q[0], kit_noise(v)) * v->namp; v->namp *= v->ndec;
        v->amp *= v->adec;
        if (n > 480 && v->amp < KIT_SILENT && v->namp < KIT_SILENT) v->live = 0;
        break;
    }
    case T9_RS:
        x = n < 2 ? 1.0f : 0.0f;
        y = bq_run(&v->q[0], x) * 4.0f + bq_run(&v->q[1], x) * 2.6f + bq_run(&v->q[2], x) * 0.35f + bq_run(&v->q[3], x) * 0.22f;
        y = y > 0.0f ? y : 0.55f * y;          /* asymmetric transistor clip */
        y *= v->amp; v->amp *= v->adec;
        if (n > 480 && v->amp < KIT_SILENT) v->live = 0;
        break;
    case T9_CP: {
        /* Four sawtooth bursts one clap period apart, then the reverb tail. */
        float burst = 0.0f;
        if (n < 4*v->clap_period) {
            u32 phase = n % v->clap_period;
            if (phase == 0) v->e[0] = 1.0f;
            burst = 1.0f - (float)phase / (float)v->clap_period;
        }
        float tail = n >= 3*v->clap_period ? 0.50f * v->e[1] : 0.20f * v->e[1];
        x = kit_noise(v);
        y = bq_run(&v->q[0], x) * (0.82f * burst * v->e[0] + tail);
        v->e[0] *= v->ed[0]; if (n >= 3*v->clap_period) v->e[1] *= v->ed[1];
        if (n > 4*v->clap_period && v->e[1] < KIT_SILENT) v->live = 0;
        break;
    }
    }
    v->n = n + 1;
    v->source_frame += 1;          /* host renders; kit_output sets it on ARM */
    return y * v->gain;
}
