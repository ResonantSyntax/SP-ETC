/* CR-78-inspired 14-voice synthesis family.
 * Include after kit808_render(), with kit_voice and helpers in scope.
 * Pitches follow Roland CR-78 Service Notes (1979) and recordings; envelopes,
 * bands and rates are fitted to 4-14 recordings per voice (The_Machine CR-78
 * folders, several units): -20/-40 dB times, 4 ms envelopes, spectral peaks.
 * Uncertain circuit details use digital resonators/noise, not a clone. */
static float kitcr78_t10(float seconds) {
    /* The service waveform marks 1/10 amplitude. Approximate it with an
     * exponential; this is not a Roland-specified pole or envelope shape. */
    if (seconds < 0.0001f) return 0.0f;
    return kit_exp2(-3.321928095f / (seconds * KIT_FS));
}

static float kitcr78_limit_hz(float hz) {
    /* Keep the MB oscillator bank and its tune range below Nyquist. */
    return kit_clampf(hz, 25.0f, 18000.0f);
}

static void kitcr78_ring(kit_bq *q, float hz, float t10) {
    /* Normalized impulse resonator. Its pole radius is chosen so the mode's
     * amplitude envelope falls by 20 dB in the service-listed T10. */
    float s, c, r = kitcr78_t10(t10);
    kit_sincos(kit_clampf(hz, 20.0f, 18000.0f), &s, &c);
    q->b0 = s; q->b1 = q->b2 = 0.0f;
    q->a1 = -2.0f*r*c; q->a2 = r*r;
}

static void kitcr78_start(kit_voice *v, float pitch, float decay, float tone) {
    int j;
    for (j = 0; j < 5; ++j) {
        v->q[j].z1 = v->q[j].z2 = 0.0f;
        v->q[j].b0 = v->q[j].b1 = v->q[j].b2 = 0.0f;
        v->q[j].a1 = v->q[j].a2 = 0.0f;
    }
    for (j = 0; j < 3; ++j) v->e[j] = v->ed[j] = 0.0f;
    for (j = 0; j < 6; ++j) v->ph[j] = 0.0f;
    v->n = 0; v->amp = 1.0f; v->adec = 1.0f; v->namp = 0.0f; v->ndec = 0.0f;
    v->f = v->fend = v->pe = v->pdec = 0.0f;
    v->lp = v->bp = v->hp1 = v->xprev = 0.0f;
    v->svf_f = v->svf_q = v->mi = v->mdec = v->mr = 0.0f;
    v->qv = 0.0f;
    float p = kit_clampf(pitch, 0.25f, 4.0f);
    float k = kit_clampf(decay, 0.1f, 4.0f);
    float c = kit_clampf(tone, -1.0f, 1.0f);
    float bright = kit_exp2(0.75f * c);
    switch (v->drum) {
    case C78_BD: /* recordings: 78 Hz at 5 ms settling to 62 Hz; -15 dB at 60 ms */
        v->f = 105.0f * p * kit_exp2(0.22f*c); v->fend = 62.5f * p;
        v->pe = 1.0f; v->pdec = KIT_TAU(0.005f);
        v->adec = KIT_TAU(0.030f*k); v->gain *= 0.68f; break;
    case C78_SD: /* 328 Hz body (6.7 ms) under bright wires held ~45 ms */
        v->f = 328.0f * p;
        v->adec = KIT_TAU(0.0067f*k);
        bq_hp(&v->q[0], 2000.0f*bright, 0.7f);
        bq_lp(&v->q[1], 12000.0f, 0.7f);
        kit_hold(v, 0.15f, 0.045f*k, 0.0087f);
        v->e[0] = 1.0f; v->ed[0] = KIT_TAU(0.060f*k);    /* wire tail: -21 dB at 60 ms */
        v->nmix = 0.64f*kit_exp2(0.5f*c);
        v->gain *= 0.52f; break;
    case C78_RS: /* one struck mode, with the listed 5-ms T10 in its pole */
        kitcr78_ring(&v->q[0], 1480.0f*p*bright, 0.005f*k);
        v->adec = kitcr78_t10(0.005f*k); v->gain *= 0.26f; break;
    case C78_HH: /* recordings: one band at 8.4 kHz, held ~42 ms, then cut */
        bq_hp(&v->q[0], 6000.0f*p*bright, 0.9f);
        bq_bp(&v->q[1], 8400.0f*p*bright, 3.0f);
        kit_hold(v, 0.060f, 0.040f*k, 0.0045f);
        v->mi = 1.0f/96;                                   /* 2 ms rise */
        v->gain *= 0.45f; break;
    case C78_CY: /* same band as the hat; t20 ~170 ms, t40 ~370 ms */
        bq_hp(&v->q[0], 6000.0f*p*bright, 0.9f);
        bq_bp(&v->q[1], 8200.0f*p*bright, 3.0f);
        kit_hold(v, 0.088f*k, 0.0f, 0.088f*k);
        v->mi = 1.0f/96;
        v->gain *= 0.40f; break;
    case C78_MA: /* recording: 8.4 kHz band (-9 dB at 6.3k, -13 at 12.5k), 6 ms swell, cut ~20 ms */
        bq_bp(&v->q[0], 8400.0f*p*bright, 2.5f);
        bq_bp(&v->q[1], 8400.0f*p*bright, 2.5f);
        kit_hold(v, 0.030f, 0.016f*k, 0.004f);
        v->gain *= 0.40f; break;
    case C78_CL: /* recordings ring at 2562 Hz; 18-ms T10 */
        kitcr78_ring(&v->q[0], 2562.0f*p*bright, 0.018f*k);
        v->adec = kitcr78_t10(0.018f*k); v->gain *= 0.18f; break;
    case C78_HB: case C78_LB: /* steady 616/400 Hz sines, held ~40 ms */
        v->f = (v->drum == C78_HB ? 616.0f : 400.0f)*p;
        kit_hold(v, 0.0155f*k, 0.040f*k, 0.009f);
        v->gain *= 0.20f; break;
    case C78_LC: /* steady 207 Hz, tau 37 ms; a slight odd harmonic */
        v->f = 207.0f*p;
        v->adec = KIT_TAU(0.037f*k); v->namp = 0.05f*bright;
        v->ndec = kitcr78_t10(0.004f); v->gain *= 0.25f; break;
    case C78_CB: /* recordings: 791 and 533 Hz, each with a weak 2nd harmonic,
                  * held ~40 ms then cut (-29 dB at 60 ms) */
        v->f = 791.0f*p*bright; v->fend = 533.0f*p;
        kit_hold(v, 0.15f, 0.038f*k, 0.005f);
        v->mi = 1.0f/96;
        v->gain *= 0.20f; break;
    case C78_TB: /* 4.7 kHz band, jingles ~290 per second, tau 85 ms, cut ~190 ms */
        bq_bp(&v->q[0], 4700.0f*p*bright, 7.0f);
        bq_bp(&v->q[1], 4700.0f*p*bright, 2.5f);
        v->f = 290.0f*p; v->hp1 = 1.0f;                    /* jingle level */
        kit_hold(v, 0.085f*k, 0.190f*k, 0.010f);
        v->mi = 1.0f/144;                                  /* 3 ms rise */
        v->gain *= 0.60f; break;
    case C78_GU: /* recordings: ~4 ms scrapes every 13.3 ms through a 5.9 kHz band */
        bq_bp(&v->q[0], 5900.0f*bright, 6.0f);
        bq_bp(&v->q[1], 5900.0f*bright, 2.5f);
        v->f = 75.0f*p; v->ph[0] = 0.999f;
        v->e[1] = 0.0f; v->ed[1] = KIT_TAU(0.0012f);
        kit_hold(v, 1.0f, 0.150f*k, 0.015f);
        v->gain *= 0.70f; break;
    case C78_MB: /* three measured CMOS-derived components, bounded for tuning;
                  * recordings: the lowest is ~11 dB down; held ~25 ms */
        v->f = kitcr78_limit_hz(6170.0f*p*bright);
        v->fend = kitcr78_limit_hz(5620.0f*p);
        v->ratio = kitcr78_limit_hz(4080.0f*p) / KIT_FS;
        kit_hold(v, 0.10f, 0.025f*k, 0.010f);
        v->mi = 1.0f/192;                                  /* 4 ms rise */
        v->bp = 1.0f - kit_exp2(-6.28318531f * 1.4427f * 7000.0f / KIT_FS);
        bq_hp(&v->q[0], 3500.0f, 0.7f);   /* keeps the sum products (9.7/11.8 kHz), not differences */
        v->gain *= 0.22f; break;
    default:
        v->live = 0; v->gain = 0.0f; break;
    }
}

static float kitcr78_render(kit_voice *v) {
    u32 n = v->n;
    float y = 0.0f, x, f;
    switch (v->drum) {
    case C78_BD:
        f = v->fend + (v->f-v->fend)*v->pe; v->pe *= v->pdec;
        v->ph[0] += f/KIT_FS; v->ph[0] -= (float)(int)v->ph[0];
        y = 0.70f*kit_sin2pi(v->ph[0])*v->amp;
        y += (n < 5 ? 0.10f*(5.0f-(float)n)/5.0f : 0.0f)*kit_parameter_noise(v,kit_shared_noise(v->source_frame));
        v->amp *= v->adec; break;
    case C78_SD:
        x = kit_parameter_noise(v,kit_shared_noise(v->source_frame));
        v->ph[0] += v->f/KIT_FS; v->ph[0] -= (float)(int)v->ph[0];
        y = 0.70f*kit_sin2pi(v->ph[0])*v->amp;
        y += v->nmix*0.70f*bq_run(&v->q[1], bq_run(&v->q[0], x))*(0.77f*kit_vca(v) + 0.23f*v->e[0]);
        v->e[0] *= v->ed[0]; v->amp *= v->adec; break;
    case C78_RS:
        y = bq_run(&v->q[0], n == 0 ? 1.0f : 0.0f);
        if (n == 0) y += 0.16f;                            /* stick click */
        v->amp *= v->adec; break;
    case C78_HH: case C78_CY: case C78_MA:
        x = kit_parameter_noise(v,kit_shared_noise(v->source_frame));
        y = bq_run(&v->q[1], bq_run(&v->q[0], x));
        if (v->drum == C78_MA) { float r = (float)n*(1.0f/288); if (r < 1.0f) y *= r*r; }   /* 6 ms swell */
        y *= kit_vca(v); v->amp = v->e[2]; break;
    case C78_CL:
        y = bq_run(&v->q[0], n == 0 ? 1.0f : 0.0f);
        v->amp *= v->adec; break;
    case C78_HB: case C78_LB:
        v->ph[0] += v->f/KIT_FS; v->ph[0] -= (float)(int)v->ph[0];
        y = kit_sin2pi(v->ph[0])*kit_vca(v)*0.76f;
        v->amp = v->e[2]; break;
    case C78_LC:
        v->ph[0] += v->f/KIT_FS; v->ph[0] -= (float)(int)v->ph[0];
        y = 0.72f*(kit_sin2pi(v->ph[0]) + 0.016f*kit_sin2pi(3.0f*v->ph[0]))*v->amp;
        y += v->namp*kit_parameter_noise(v,kit_shared_noise(v->source_frame));
        v->namp *= v->ndec; v->amp *= v->adec; break;
    case C78_CB:
        v->ph[0] += v->f/KIT_FS; v->ph[0] -= (float)(int)v->ph[0];
        v->ph[1] += v->fend/KIT_FS; v->ph[1] -= (float)(int)v->ph[1];
        y = (0.64f*(kit_sin2pi(v->ph[0]) + 0.13f*kit_sin2pi(2.0f*v->ph[0]))
           + 0.36f*(kit_sin2pi(v->ph[1]) + 0.35f*kit_sin2pi(2.0f*v->ph[1])))*kit_vca(v);
        v->amp = v->e[2]; break;
    case C78_TB:
        /* Each jingle cycle restarts at a random level and decays across it. */
        v->ph[0] += v->f/KIT_FS;
        if (v->ph[0] >= 1.0f) { v->ph[0] -= 1.0f; v->hp1 = 0.45f + 0.55f*kit_absf(kit_noise(v)); }
        x = kit_parameter_noise(v,kit_shared_noise(v->source_frame));
        y = bq_run(&v->q[1], bq_run(&v->q[0], x))*v->hp1*(1.0f - 0.7f*v->ph[0])*kit_vca(v);
        v->amp = v->e[2]; break;
    case C78_GU:
        /* A scrape restarts each 13.3 ms cycle at a random level. */
        v->ph[0] += v->f/KIT_FS;
        if (v->ph[0] >= 1.0f) { v->ph[0] -= 1.0f; v->e[1] = 0.6f + 0.4f*kit_absf(kit_noise(v)); }
        x = kit_parameter_noise(v,kit_shared_noise(v->source_frame));
        y = bq_run(&v->q[1], bq_run(&v->q[0], x))*v->e[1]*kit_vca(v);
        v->e[1] *= v->ed[1]; v->amp = v->e[2]; break;
    case C78_MB: {
        float f0 = v->f, f1 = v->fend, f2 = v->ratio* KIT_FS;
        float dt0 = f0/KIT_FS, dt1 = f1/KIT_FS, dt2 = f2/KIT_FS;
        v->ph[0] += dt0; v->ph[0] -= (float)(int)v->ph[0];
        v->ph[1] += dt1; v->ph[1] -= (float)(int)v->ph[1];
        v->ph[2] += dt2; v->ph[2] -= (float)(int)v->ph[2];
        float s0 = kit_pulse(v->ph[0],dt0,0.5f), s1 = kit_pulse(v->ph[1],dt1,0.5f), s2 = kit_pulse(v->ph[2],dt2,0.5f);
        y = 0.42f*s0 + 0.44f*s1 + 0.14f*s2 + 0.10f*s1*s2 + 0.07f*s0*s1;
        y = kit_parameter_metal(v,y);
        v->lp += v->bp*(y - v->lp);                        /* tames the 3rd harmonics */
        y = bq_run(&v->q[0], v->lp)*kit_vca(v);
        v->amp = v->e[2]; break;
    }
    }
    ++v->n; ++v->source_frame;
    if (v->n > 480 && v->amp < KIT_SILENT && v->e[0] < KIT_SILENT &&
        v->namp < KIT_SILENT) v->live = 0;
    return y*v->gain;
}
