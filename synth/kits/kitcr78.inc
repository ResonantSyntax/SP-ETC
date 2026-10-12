/* CR-78-inspired 14-voice synthesis family.
 * Include after kit808_render(), with kit_voice and helpers in scope.
 * Targets follow Roland CR-78 Service Notes (1979); uncertain circuit details
 * use conservative digital resonators/noise rather than claiming a clone. */
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
    v->n = 0; v->amp = 1.0f; v->namp = 0.0f; v->ndec = 0.0f;
    v->f = v->fend = v->pe = v->pdec = 0.0f;
    v->lp = v->bp = v->hp1 = v->xprev = 0.0f;
    v->svf_f = v->svf_q = v->mi = v->mdec = v->mr = 0.0f;
    v->qv = 0.0f;
    float p = kit_clampf(pitch, 0.25f, 4.0f);
    float k = kit_clampf(decay, 0.1f, 4.0f);
    float c = kit_clampf(tone, -1.0f, 1.0f);
    float bright = kit_exp2(0.75f * c);
    switch (v->drum) {
    case C78_BD: /* falling-pitch body plus a short attack click */
        v->f = 84.0f * p * kit_exp2(0.22f*c); v->fend = 62.5f * p;
        v->pe = 1.0f; v->pdec = kit_decay60(0.035f);
        v->adec = kitcr78_t10(0.100f*k); v->gain *= 0.68f; break;
    case C78_SD: /* tuned drum mode with an independently decaying noise path */
        bq_bp(&v->q[0], 340.0f*p*bright, 2.1f);
        bq_bp(&v->q[1], 1750.0f*bright, 0.75f);
        v->adec = kitcr78_t10(0.060f*k); v->e[0] = 1.0f;
        v->ed[0] = kitcr78_t10(0.060f*k); v->e[1] = 1.0f;
        v->ed[1] = kitcr78_t10(0.012f*k); v->nmix = 0.44f+0.16f*c;
        v->gain *= 0.52f; break;
    case C78_RS: /* one struck mode, with the listed 5-ms T10 in its pole */
        kitcr78_ring(&v->q[0], 1480.0f*p*bright, 0.005f*k);
        v->adec = kitcr78_t10(0.005f*k); v->gain *= 0.26f; break;
    case C78_HH: /* short, bright noise with a little inharmonic metal ring */
        bq_hp(&v->q[0], 5600.0f*p*bright, 0.72f);
        bq_bp(&v->q[1], 7900.0f*p*bright, 0.8f);
        v->adec = kitcr78_t10(0.060f*k); v->e[0] = 1.0f;
        v->ed[0] = kitcr78_t10(0.060f*k); v->gain *= 0.30f; break;
    case C78_CY: /* broader, lower metallic wash and substantially longer tail */
        bq_hp(&v->q[0], 2700.0f*p*bright, 0.65f);
        bq_bp(&v->q[1], 5200.0f*p*bright, 0.62f);
        bq_bp(&v->q[2], 8400.0f*p*bright, 0.70f);
        v->adec = kitcr78_t10(0.350f*k); v->e[0] = 1.0f;
        v->ed[0] = kitcr78_t10(0.350f*k); v->gain *= 0.24f; break;
    case C78_MA: /* maraca: short, high-passed shared-noise envelope */
        bq_hp(&v->q[0], 4100.0f*p*bright, 0.62f);
        bq_bp(&v->q[1], 7600.0f*p*bright, 0.72f);
        v->adec = kitcr78_t10(0.020f*k); v->e[0] = 1.0f;
        v->ed[0] = kitcr78_t10(0.020f*k); v->gain *= 0.27f; break;
    case C78_CL: /* one struck mode at the printed frequency and 18-ms T10 */
        kitcr78_ring(&v->q[0], 2630.0f*p*bright, 0.018f*k);
        v->adec = kitcr78_t10(0.018f*k); v->gain *= 0.18f; break;
    case C78_HB: /* separate high-bongo pitched shell */
        v->f = 760.0f*p*bright; v->fend = 600.0f*p;
        v->pe = 0.24f; v->pdec = kit_decay60(0.018f);
        v->adec = kitcr78_t10(0.040f*k); v->gain *= 0.20f; break;
    case C78_LB: /* lower bongo with distinct pitch and resonance */
        v->f = 510.0f*p*bright; v->fend = 400.0f*p;
        v->pe = 0.20f; v->pdec = kit_decay60(0.020f);
        v->adec = kitcr78_t10(0.040f*k); v->gain *= 0.20f; break;
    case C78_LC: /* low conga: deeper body with a small noisy slap */
        v->f = 290.0f*p*bright; v->fend = 208.0f*p;
        v->pe = 0.38f; v->pdec = kit_decay60(0.030f);
        v->adec = kitcr78_t10(0.150f*k); v->namp = 0.08f*bright;
        v->ndec = kitcr78_t10(0.006f); v->gain *= 0.25f; break;
    case C78_CB: /* two resonant sine modes at the service H/L targets */
        v->f = 800.0f*p*bright; v->fend = 555.0f*p;
        v->adec = kitcr78_t10(0.060f*k); v->ph[0] = 0.0f;
        v->gain *= 0.20f; break;
    case C78_TB: /* brighter two-band noise under the longer tambourine decay */
        bq_hp(&v->q[0], 3200.0f*p*bright, 0.68f);
        bq_bp(&v->q[1], 6100.0f*p*bright, 0.75f);
        v->adec = kitcr78_t10(0.220f*k); v->e[0] = 1.0f;
        v->ed[0] = kitcr78_t10(0.220f*k); v->gain *= 0.20f; break;
    case C78_GU: /* coupled RC rate oscillator; H/L are cycle-rate targets */
        bq_hp(&v->q[0], 1100.0f*bright, 0.68f);
        bq_bp(&v->q[1], 2350.0f*bright, 0.72f);
        v->f = 125.0f*p; v->fend = 77.0f*p; v->mi = c;
        v->adec = kitcr78_t10(0.32f*k); v->e[0] = 1.0f;
        v->ed[0] = kitcr78_t10(0.32f*k); v->gain *= 0.22f; break;
    case C78_MB: /* three measured CMOS-derived components, bounded for tuning */
        v->f = kitcr78_limit_hz(6170.0f*p*bright);
        v->fend = kitcr78_limit_hz(5620.0f*p);
        v->ratio = kitcr78_limit_hz(4080.0f*p) / KIT_FS;
        v->adec = kitcr78_t10(0.050f*k); v->gain *= 0.22f; break;
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
        y = 0.58f*bq_run(&v->q[0], x)*v->e[0];
        y += 0.38f*bq_run(&v->q[1], x)*v->e[1]*v->nmix;
        y += 0.35f*kit_sin2pi(v->ph[0])*v->amp;
        v->ph[0] += (340.0f*v->ratio)/KIT_FS;
        v->ph[0] -= (float)(int)v->ph[0];
        v->e[0] *= v->ed[0]; v->e[1] *= v->ed[1]; v->amp *= v->adec; break;
    case C78_RS:
        y = bq_run(&v->q[0], n == 0 ? 1.0f : 0.0f);
        v->amp *= v->adec; break;
    case C78_HH:
        x = kit_parameter_noise(v,kit_shared_noise(v->source_frame));
        y = 0.60f*bq_run(&v->q[0], x)+0.20f*bq_run(&v->q[1], x);
        y *= v->e[0]; v->e[0] *= v->ed[0]; v->amp *= v->adec; break;
    case C78_CY:
        x = kit_parameter_noise(v,kit_shared_noise(v->source_frame));
        y = 0.30f*bq_run(&v->q[0], x)+0.30f*bq_run(&v->q[1], x)+0.24f*bq_run(&v->q[2], x);
        y *= v->e[0]; v->e[0] *= v->ed[0]; v->amp *= v->adec; break;
    case C78_MA:
        x = kit_parameter_noise(v,kit_shared_noise(v->source_frame));
        y = 0.62f*bq_run(&v->q[0], x)+0.18f*bq_run(&v->q[1], x);
        y *= v->e[0]; v->e[0] *= v->ed[0]; v->amp *= v->adec; break;
    case C78_CL:
        y = bq_run(&v->q[0], n == 0 ? 1.0f : 0.0f);
        v->amp *= v->adec; break;
    case C78_HB: case C78_LB:
        f = v->fend+(v->f-v->fend)*v->pe; v->pe *= v->pdec;
        v->ph[0] += f/KIT_FS; v->ph[0] -= (float)(int)v->ph[0];
        y = kit_sin2pi(v->ph[0])*v->amp*0.76f;
        y += 0.025f*kit_parameter_noise(v,kit_shared_noise(v->source_frame))*v->amp;
        v->amp *= v->adec; break;
    case C78_LC:
        f = v->fend+(v->f-v->fend)*v->pe; v->pe *= v->pdec;
        v->ph[0] += f/KIT_FS; v->ph[0] -= (float)(int)v->ph[0];
        y = 0.72f*kit_sin2pi(v->ph[0])*v->amp;
        y += v->namp*kit_parameter_noise(v,kit_shared_noise(v->source_frame));
        v->namp *= v->ndec; v->amp *= v->adec; break;
    case C78_CB:
        v->ph[0] += v->f/KIT_FS; v->ph[0] -= (float)(int)v->ph[0];
        v->ph[1] += v->fend/KIT_FS; v->ph[1] -= (float)(int)v->ph[1];
        y = (0.56f*kit_sin2pi(v->ph[0])+0.44f*kit_sin2pi(v->ph[1]))*v->amp;
        v->amp *= v->adec; break;
    case C78_TB:
        x = kit_parameter_noise(v,kit_shared_noise(v->source_frame));
        y = 0.44f*bq_run(&v->q[0], x)+0.28f*bq_run(&v->q[1], x);
        y *= v->e[0]; v->e[0] *= v->ed[0]; v->amp *= v->adec; break;
    case C78_GU: {
        float hi_dt = v->f/KIT_FS, lo_dt = v->fend/KIT_FS;
        float hi_gate, lo_gate, hi_mix;
        v->ph[0] += hi_dt; v->ph[0] -= (float)(int)v->ph[0];
        v->ph[1] += lo_dt; v->ph[1] -= (float)(int)v->ph[1];
        hi_gate = kit_pulse(v->ph[0], hi_dt, 0.43f);
        lo_gate = kit_pulse(v->ph[1], lo_dt, 0.50f);
        hi_mix = 0.34f + 0.16f*v->mi;
        x = kit_parameter_noise(v,kit_shared_noise(v->source_frame));
        y = 0.34f*(hi_mix*hi_gate+(1.0f-hi_mix)*lo_gate);
        y += 0.14f*bq_run(&v->q[0], x)+0.18f*bq_run(&v->q[1], x);
        y *= v->e[0]; v->e[0] *= v->ed[0]; v->amp *= v->adec; break;
    }
    case C78_MB: {
        float f0 = v->f, f1 = v->fend, f2 = v->ratio* KIT_FS;
        float dt0 = f0/KIT_FS, dt1 = f1/KIT_FS, dt2 = f2/KIT_FS;
        v->ph[0] += dt0; v->ph[0] -= (float)(int)v->ph[0];
        v->ph[1] += dt1; v->ph[1] -= (float)(int)v->ph[1];
        v->ph[2] += dt2; v->ph[2] -= (float)(int)v->ph[2];
        y = (0.38f*kit_pulse(v->ph[0],dt0,0.5f)+
             0.34f*kit_pulse(v->ph[1],dt1,0.5f)+
             0.28f*kit_pulse(v->ph[2],dt2,0.5f));
        y=kit_parameter_metal(v,y)*v->amp;
        v->amp *= v->adec; break;
    }
    }
    ++v->n; ++v->source_frame;
    if (v->n > 480 && v->amp < KIT_SILENT && v->e[0] < KIT_SILENT &&
        v->namp < KIT_SILENT) v->live = 0;
    return y*v->gain;
}
