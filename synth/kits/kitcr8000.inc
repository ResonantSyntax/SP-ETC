/* CR-8000-inspired analog voice models; include after kit808_render().
 * The synthesis topology is informed by Roland CR-5000/8000 Service Notes.
 * This is a portable digital approximation, not an exact circuit emulation. */

static float kitcr8000_tune(float hz) {
    return kit_clampf(hz, 24.0f, 18000.0f);
}

static float kitcr8000_t60(float seconds) {
    /* Per-sample pole multiplier reaching -60 dB in `seconds`. This is an
     * internal envelope convention, not Roland's undefined chart endpoint. */
    return kit_decay60(seconds);
}

static __attribute__((noinline)) float kitcr8000_tau(float seconds) {
    return kit_exp2(-1.44269504f / (seconds * KIT_FS));
}

static __attribute__((noinline)) void kitcr8000_ring(kit_bq *q, float hz, float seconds) {
    float s, c;
    float r = kitcr8000_t60(seconds);
    kit_sincos(kitcr8000_tune(hz), &s, &c);
    /* Impulse-normalized damped mode. The b0 factor keeps peaks controlled
     * across frequency, while the selected pole radius sets a provisional
     * decay envelope rather than asserting Roland's undocumented endpoint. */
    q->b0 = s; q->b1 = q->b2 = 0.0f;
    q->a1 = -2.0f*r*c; q->a2 = r*r;
    q->z1 = q->z2 = 0.0f;
}

static __attribute__((noinline)) float kitcr8000_phase(u32 frame, float hz) {
    u32 step = (u32)((kit_clampf(hz,1.0f,18000.0f) / KIT_FS) * 4294967296.0f);
    float p=(float)(step * frame) * 2.3283064365386963e-10f;
    return p>=1.0f?0.0f:p;
}

static __attribute__((noinline)) void kitcr8000_start(kit_voice *v, float pitch, float decay, float tone) {
    for (int j=0; j<5; ++j) {
        v->q[j].z1=v->q[j].z2=0.0f;
        v->q[j].b0=v->q[j].b1=v->q[j].b2=v->q[j].a1=v->q[j].a2=0.0f;
    }
    for (int j=0; j<3; ++j) v->e[j]=v->ed[j]=0.0f;
    for (int j=0; j<6; ++j) v->ph[j]=0.0f;
    v->n=0; v->amp=1.0f; v->namp=0.0f; v->ndec=0.0f;
    /* amp is a bounded service-time retirement clock; e[] carries the audible
     * envelope. The service chart's endpoint is not specified. */
    v->adec=kitcr8000_t60(0.400f*kit_clampf(decay,0.1f,4.0f));
    v->f=v->fend=v->pe=v->pdec=0.0f;
    v->lp=v->bp=v->hp1=v->xprev=0.0f;
    v->svf_f=v->svf_q=v->mi=v->mdec=v->mr=0.0f;
    v->qv=0.0f;
    float p=kit_clampf(pitch,0.25f,4.0f);
    float k=kit_clampf(decay,0.1f,4.0f);
    float t=kit_clampf(tone,-1.0f,1.0f);
    float bright=kit_exp2(0.55f*t);
    float timbre=kit_clampf(1.0f+0.30f*t,0.55f,1.45f);
    float mainsec;
    switch (v->drum) {
    case C8K_BD:
        kitcr8000_ring(&v->q[0],88.0f*p*bright,0.018f*k*6.90775528f);
        kitcr8000_ring(&v->q[1],57.0f*p,0.033f*k*6.90775528f);
        v->e[0]=1.0f; v->ed[0]=kitcr8000_tau(0.033f*k);
        v->gain*=0.24f; break;
    case C8K_SD:
        kitcr8000_ring(&v->q[0],333.0f*p*bright,0.008f*k*6.90775528f);
        kitcr8000_ring(&v->q[1],227.0f*p,0.015f*k*6.90775528f);
        v->e[0]=1.0f; v->ed[0]=kitcr8000_tau(0.015f*k);
        v->e[1]=1.0f; v->ed[1]=kitcr8000_tau(0.015f*k);
        bq_bp(&v->q[2],2100.0f*bright,0.65f); /* approximate noise coloration */
        v->nmix=kit_clampf(0.25f+0.30f*t,0.0f,0.60f); v->gain*=0.20f; break;
    case C8K_LT: case C8K_HT: {
        float nominal=v->drum==C8K_LT?106.0f:152.0f;
        v->f=nominal*p*(1.28f+0.18f*t); v->fend=nominal*p;
        v->pe=0.48f; v->pdec=kit_decay60(0.022f);
        mainsec=v->drum==C8K_LT?0.102f:0.082f; /* local-file RMS tau prior */
        v->e[0]=1.0f; v->ed[0]=kitcr8000_tau(mainsec*k);
        v->lp=0.0f;
        v->gain*=0.22f; break;
    }
    case C8K_LC: case C8K_MC: case C8K_HC: {
        float hz=v->drum==C8K_LC?200.0f:v->drum==C8K_MC?294.0f:690.0f;
        mainsec=v->drum==C8K_LC?0.083f:v->drum==C8K_MC?0.052f:0.015f;
        kitcr8000_ring(&v->q[0],hz*p*bright,mainsec*k*6.90775528f);
        v->e[0]=1.0f; v->ed[0]=kitcr8000_tau(mainsec*k);
        v->gain*=v->drum==C8K_HC?0.15f:0.20f; break;
    }
    case C8K_CY: case C8K_OH: case C8K_CH: {
        /* Six Schmitt-trigger square sources at service CP checkpoints.
         * Their phase comes from the shared frame clock, so a hit does not
         * restart the source bank. */
        mainsec=v->drum==C8K_CY?0.174f:v->drum==C8K_OH?0.123f:0.022f;
        v->e[0]=1.0f; v->ed[0]=kitcr8000_tau(mainsec*k);
        v->e[1]=1.0f; v->ed[1]=kitcr8000_tau(mainsec*k);
        if(v->drum==C8K_CY) {
            bq_hp(&v->q[0],7234.0f*bright,0.72f);
            bq_bp(&v->q[1],8987.0f*bright,1.58f);
            bq_bp(&v->q[2],6460.0f*bright,5.49f);
        } else {
            bq_hp(&v->q[0],5895.0f*bright,0.72f);
            bq_bp(&v->q[1],6459.0f*bright,5.49f);
            bq_bp(&v->q[2],9300.0f*bright,1.15f);
        }
        if(v->drum!=C8K_CY) v->group=1; /* closed/open hats mutually choke */
        v->nmix=bright; v->gain*=v->drum==C8K_CY?0.090f:0.12f; break;
    }
    case C8K_RS:
        /* The later schematic resets CP5/CP6 via Q37 and D46/D47, then
         * mixes their outputs into the rim path. CP1/CP2 are not this pair.
         * This compact model resets only the rim's local edge sources. */
        v->e[0]=1.0f; v->ed[0]=kitcr8000_tau(0.011f*k);
        bq_bp(&v->q[0],2300.0f*bright,1.0f);
        v->nmix=0.25f+0.30f*t;
        v->gain*=0.11f; break;
    case C8K_CB:
        v->e[0]=1.0f; v->ed[0]=kitcr8000_tau(0.036f*k);
        bq_bp(&v->q[0],690.0f*bright,0.8f);
        v->nmix=bright; v->gain*=0.16f; break;
    case C8K_CL:
        v->f=2330.0f*p*bright;
        v->e[0]=1.0f; v->ed[0]=kitcr8000_tau(0.0063f*k);
        v->gain*=0.14f; break;
    case C8K_CP:
        /* Early saw bursts give way to a continuous tail, as in the service
         * adjustment waveform. Timing/gain remain reference-informed
         * approximations, not recovered IC6 component dynamics. */
        v->f=90.0f*p; v->e[0]=1.0f; v->ed[0]=kitcr8000_tau(0.036f*k);
        v->e[1]=1.0f; v->ed[1]=kitcr8000_tau(0.065f*k);
        bq_bp(&v->q[0],1500.0f*bright,0.8f);
        v->nmix=timbre; v->gain*=0.28f; break;
    default:
        v->live=0; v->gain=0.0f; break;
    }
}

static __attribute__((noinline)) float kitcr8000_render(kit_voice *v) {
    static const float metal_hz[6]={794.0f,647.0f,524.0f,444.0f,368.0f,283.0f};
    u32 n=v->n, frame=v->source_frame;
    float y=0.0f,x,f,env=v->e[0],body;
    switch (v->drum) {
    case C8K_BD:
        x=(n==0?1.0f:0.0f);
        y=0.62f*bq_run(&v->q[0],x)+0.38f*bq_run(&v->q[1],x);
        v->e[0]*=v->ed[0]; break;
    case C8K_SD:
        x=(n==0?1.0f:0.0f);
        body=0.62f*bq_run(&v->q[0],x)+0.38f*bq_run(&v->q[1],x);
        y=body+0.70f*bq_run(&v->q[2],kit_parameter_noise(v,kit_shared_noise(frame)))*v->e[1]*v->nmix;
        v->e[0]*=v->ed[0]; v->e[1]*=v->ed[1]; break;
    case C8K_LT: case C8K_HT:
        f=v->fend+(v->f-v->fend)*v->pe;
        /* A mild amplitude-dependent pitch trajectory stands in for the
         * documented diode-shifted bridged-T RC response. */
        v->pe*=v->pdec;
        v->ph[0]+=f/KIT_FS; v->ph[0]-=(float)(int)v->ph[0];
        x=kit_parameter_noise(v,kit_shared_noise(frame)); v->lp+=0.035f*(x-v->lp);
        y=0.54f*kit_sin2pi(v->ph[0])*env+0.28f*v->lp*v->e[0];
        v->e[0]*=v->ed[0]; break;
    case C8K_LC: case C8K_MC:
        y=bq_run(&v->q[0],n==0?1.0f:0.0f);
        v->e[0]*=v->ed[0]; break;
    case C8K_HC:
        y=bq_run(&v->q[0],n==0?1.0f:0.0f);
        y=kit_clampf(2.3f*y,-0.42f,0.42f);
        v->e[0]*=v->ed[0]; break;
    case C8K_CY: case C8K_OH: case C8K_CH: {
        float metal=0.0f;
        for(int j=0;j<6;++j) {
            float hz=metal_hz[j]*v->ratio;
            float dt=kitcr8000_tune(hz)/KIT_FS;
            float ph=(v->ctrl_sweep>0 && (v->role==4||v->role==5))?kit_parameter_phase(v,j,hz):kitcr8000_phase(frame,hz);
            metal+=kit_pulse(ph,dt,0.47f);
        }
        metal=kit_parameter_metal(v,metal/6)*6;
        y=0.27f*bq_run(&v->q[0],metal)+0.53f*bq_run(&v->q[1],metal)+0.20f*bq_run(&v->q[2],metal);
        y*=env*v->nmix*(v->drum==C8K_OH?(0.62f+0.38f*v->e[1]):1.0f);
        v->e[0]*=v->ed[0]; v->e[1]*=v->ed[1]; break;
    }
    case C8K_RS: {
        float hz0=368.0f*v->ratio*(1.0f+0.12f*(v->nmix-0.25f));
        float hz1=283.0f*v->ratio*(1.0f+0.12f*(v->nmix-0.25f));
        float dt0=hz0/KIT_FS,dt1=hz1/KIT_FS;
        float p0=(float)n*dt0,p1=(float)n*dt1;
        p0-=(float)(int)p0; p1-=(float)(int)p1;
        /* Equal 100 kOhm mixing resistors R233/R229; retain total scale. */
        x=0.45f*kit_pulse(p0,dt0,0.5f)+0.45f*kit_pulse(p1,dt1,0.5f);
        y=bq_run(&v->q[0],x)*env;
        y+=0.05f*(0.5f+v->nmix)*kit_parameter_noise(v,kit_shared_noise(frame))*env;
        v->e[0]*=v->ed[0]; break;
    }
    case C8K_CB:
        x=kit_pulse(kitcr8000_phase(frame,800.0f*v->ratio),800.0f*v->ratio/KIT_FS,0.5f);
        body=kit_pulse(kitcr8000_phase(frame,555.0f*v->ratio),555.0f*v->ratio/KIT_FS,0.5f);
        y=bq_run(&v->q[0],0.54f*x+0.46f*body)*env*(0.82f+0.18f*v->nmix);
        v->e[0]*=v->ed[0]; break;
    case C8K_CL:
        y=kit_sin2pi(kitcr8000_phase(frame,v->f))*env;
        v->e[0]*=v->ed[0]; break;
    case C8K_CP: {
        /* Falling early bursts and a smooth late tail follow the service
         * waveform. Fade out modulation over one cycle after 30 ms; retaining
         * it for the entire tail gave a periodic flutter absent in references.
         * The initial half-level attack retains the first audible bursts. */
        float saw=(float)n*(v->f/KIT_FS); saw-=(float)(int)saw;
        float gate=1.0f-0.88f*saw;
        float fade=kit_clampf(((float)n-1440.0f)*(v->f/KIT_FS),0.0f,1.0f);
        gate+=(1.0f-gate)*fade;
        float attack=0.5f+0.5f*kit_clampf((float)(n+1u)*(1.0f/1440.0f),0.0f,1.0f);
        y=bq_run(&v->q[0],kit_parameter_noise(v,kit_shared_noise(frame)))*(0.70f*env+0.30f*v->e[1])*gate*attack*v->nmix;
        v->e[0]*=v->ed[0]; v->e[1]*=v->ed[1]; break;
    }
    }
    ++v->n; ++v->source_frame;
    v->amp*=v->adec;
    if(v->n>480 && v->e[0]<KIT_SILENT && v->e[1]<KIT_SILENT && v->amp<KIT_SILENT)
        v->live=0;
    return y*v->gain;
}
