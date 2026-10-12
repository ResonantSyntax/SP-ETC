/* CR-8000-inspired analog voice models; include after kit808_render().
 * The synthesis topology is informed by Roland CR-5000/8000 Service Notes.
 * Pitches, modes, bands and envelopes are fitted to 3-12 recordings per voice
 * (The_Machine CR-8000 folders): least-squares mode fits of the waveform,
 * 4 ms envelopes and spectral peaks. A digital approximation, not a clone. */

static float kitcr8000_tune(float hz) {
    return kit_clampf(hz, 24.0f, 18000.0f);
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
    /* amp is a retirement clock; e[] carries the audible envelope. */
    v->adec=kit_decay60(0.400f*kit_clampf(decay,0.1f,4.0f));
    v->f=v->fend=v->pe=v->pdec=0.0f;
    v->lp=v->bp=v->hp1=v->xprev=0.0f;
    v->svf_f=v->svf_q=v->mi=v->mdec=v->mr=0.0f;
    v->qv=0.0f;
    float p=kit_clampf(pitch,0.25f,4.0f);
    float k=kit_clampf(decay,0.1f,4.0f);
    float t=kit_clampf(tone,-1.0f,1.0f);
    float bright=kit_exp2(0.55f*t);
    float timbre=kit_clampf(1.0f+0.30f*t,0.55f,1.45f);
    switch (v->drum) {
    case C8K_BD: /* fit to 9 recordings: 58.5 Hz, tau 30-36 ms, plus 126 Hz, tau 4.6 ms */
        kit_free_ring(&v->q[0],58.5f*p,0.036f*k,-0.883f,0.414f);
        kit_free_ring(&v->q[1],125.6f*p*bright,0.0046f*k,0.598f*timbre,-0.676f*timbre);
        v->e[0]=1.0f; v->ed[0]=KIT_TAU(0.036f*k);
        v->gain*=0.16f; break;
    case C8K_SD: /* 232 Hz body, tau 11.6 ms; wires high-passed near 3.5 kHz */
        kit_free_ring(&v->q[0],232.0f*p,0.0116f*k,-1.017f,-0.951f);
        bq_hp(&v->q[1],3500.0f*bright,0.7f);
        v->e[0]=1.0f; v->ed[0]=KIT_TAU(0.0116f*k);
        v->e[1]=1.0f; v->ed[1]=KIT_TAU(0.016f*k);
        v->nmix=kit_clampf(0.4f+0.3f*t,0.1f,0.9f); v->gain*=0.14f; break;
    case C8K_LT: case C8K_HT:
        /* Each tom carries the other's mode (LT 105 Hz with 141 Hz at -17 dB;
         * HT 142 Hz with 102 Hz at -15 dB, longer). LT glides 108->101 Hz,
         * HT 148->139 Hz; the first 20 ms lose ~4 dB. */
        if (v->drum==C8K_LT) {
            v->fend=101.0f*p; v->pe=0.069f; v->pdec=KIT_TAU(0.040f);
            v->f=141.0f*p; v->mr=0.14f*timbre;
            v->e[0]=1.0f; v->ed[0]=KIT_TAU(0.080f*k);
            v->e[2]=1.0f; v->ed[2]=v->ed[0];
        } else {
            v->fend=139.0f*p; v->pe=0.065f; v->pdec=KIT_TAU(0.030f);
            v->f=102.0f*p; v->mr=0.18f*timbre;
            v->e[0]=1.0f; v->ed[0]=KIT_TAU(0.068f*k);
            v->e[2]=1.0f; v->ed[2]=KIT_TAU(0.110f*k);
        }
        v->e[1]=1.0f; v->ed[1]=KIT_TAU(0.010f);
        bq_lp(&v->q[0],400.0f,0.7f);
        v->gain*=0.22f; break;
    case C8K_LC: /* fit: 196.5 Hz; tau 61-69 ms (t20 152 ms, t40 318 ms) */
        kit_free_ring(&v->q[0],196.5f*p*bright,0.068f*k,0.698f,-0.739f);
        v->e[0]=1.0f; v->ed[0]=KIT_TAU(0.068f*k);
        v->gain*=0.20f; break;
    case C8K_MC: /* fit: 304 Hz, tau 40-46 ms */
        kit_free_ring(&v->q[0],304.0f*p*bright,0.045f*k,-0.726f,0.602f);
        v->e[0]=1.0f; v->ed[0]=KIT_TAU(0.045f*k);
        v->gain*=0.20f; break;
    case C8K_HC: /* fit: 739 Hz, tau 7.5 ms; clipped (3rd harmonic -12 dB) */
        kit_free_ring(&v->q[0],738.7f*p*bright,0.0075f*k,0.260f,0.739f);
        v->e[0]=1.0f; v->ed[0]=KIT_TAU(0.0075f*k);
        v->gain*=0.20f; break;
    case C8K_CY: case C8K_OH: case C8K_CH:
        /* Six Schmitt-trigger square sources at service CP checkpoints; the
         * recordings cut everything under ~5 kHz steeply and stay nearly flat
         * to 16 kHz (hats) or 13 kHz (cymbal). Phase follows the shared frame
         * clock, so a hit does not restart the source bank. */
        bq_hp(&v->q[0],5000.0f*bright,0.75f);
        bq_hp(&v->q[1],5000.0f*bright,0.75f);
        if (v->drum==C8K_CY) {
            bq_bp(&v->q[2],10000.0f*bright,1.2f);
            bq_lp(&v->q[3],13000.0f,0.7f);
            v->mi=1.0f/384;                           /* 8 ms rise */
            v->e[0]=1.0f; v->ed[0]=KIT_TAU(0.050f*k);  /* -12 dB at 100 ms ... */
            v->e[1]=1.0f; v->ed[1]=KIT_TAU(0.160f*k);  /* ... -26 dB at 400 ms */
            v->gain*=0.20f;
        } else {
            bq_bp(&v->q[2],12500.0f*bright,1.2f);
            if (v->drum==C8K_CH) { v->mi=1.0f/384; kit_hold(v,0.055f*k,0.035f*k,0.018f); }
            else { v->mi=1.0f/576; kit_hold(v,0.22f*k,0.25f*k,0.045f); }
            v->group=1; /* closed/open hats mutually choke */
            v->gain*=0.24f;
        }
        break;
    case C8K_RS:
        /* CP5/CP6 squares (Q37/D46/D47 reset) into a ~1.26 kHz band, plus the
         * broadband edge the recordings keep up to 16 kHz. */
        v->e[0]=1.0f; v->ed[0]=KIT_TAU(0.010f*k);
        bq_bp(&v->q[0],1260.0f*bright,3.0f);
        bq_bp(&v->q[1],3500.0f,0.5f);
        v->nmix=0.25f+0.30f*t;
        v->gain*=0.28f; break;
    case C8K_CB:
        /* Recordings: squares at 814 Hz and 551 Hz (-16 dB), odd partials
         * only; a fast 9 ms decay over a quiet 80 ms tail. */
        bq_bp(&v->q[0],814.0f*bright,1.5f);
        v->mi=1.0f/96;
        v->e[0]=1.0f; v->ed[0]=KIT_TAU(0.009f*k);
        v->e[1]=1.0f; v->ed[1]=KIT_TAU(0.080f*k);
        v->gain*=0.20f; break;
    case C8K_CL:
        v->f=2330.0f*p*bright;
        v->e[0]=1.0f; v->ed[0]=KIT_TAU(0.0063f*k);
        v->gain*=0.14f; break;
    case C8K_CP:
        /* Early saw bursts give way to a continuous tail, as in the service
         * adjustment waveform; band and high-pass fitted to the recordings
         * (peak near 1.3 kHz, little under 800 Hz). */
        v->f=90.0f*p; v->e[0]=1.0f; v->ed[0]=KIT_TAU(0.036f*k);
        v->e[1]=1.0f; v->ed[1]=KIT_TAU(0.065f*k);
        bq_bp(&v->q[0],1700.0f*bright,1.0f);
        bq_hp(&v->q[1],800.0f,0.7f);
        v->nmix=timbre; v->gain*=0.28f; break;
    default:
        v->live=0; v->gain=0.0f; break;
    }
}

static __attribute__((noinline)) float kitcr8000_render(kit_voice *v) {
    static const float metal_hz[6]={794.0f,647.0f,524.0f,444.0f,368.0f,283.0f};
    u32 n=v->n, frame=v->source_frame;
    float y=0.0f,x,f,env=v->e[0];
    switch (v->drum) {
    case C8K_BD:
        y=bq_run(&v->q[0],0.0f);
        if (n<1200) y+=bq_run(&v->q[1],0.0f);
        if (n<9) y*=(float)n*(1.0f/9);
        v->e[0]*=v->ed[0]; break;
    case C8K_SD:
        y=bq_run(&v->q[0],0.0f);
        y+=v->nmix*bq_run(&v->q[1],kit_parameter_noise(v,kit_shared_noise(frame)))*v->e[1];
        if (n<96) y*=(float)n*(1.0f/96);
        v->e[0]*=v->ed[0]; v->e[1]*=v->ed[1]; break;
    case C8K_LT: case C8K_HT:
        f=v->fend*(1.0f+v->pe); v->pe*=v->pdec;
        v->ph[0]+=f/KIT_FS; v->ph[0]-=(float)(int)v->ph[0];
        v->ph[1]+=v->f/KIT_FS; v->ph[1]-=(float)(int)v->ph[1];
        y=(kit_sin2pi(v->ph[0])*v->e[0] + v->mr*kit_sin2pi(v->ph[1])*v->e[2])*(1.0f+0.8f*v->e[1])*0.54f;
        y+=0.5f*bq_run(&v->q[0],kit_parameter_noise(v,kit_shared_noise(frame)))*v->e[0];
        v->e[0]*=v->ed[0]; v->e[1]*=v->ed[1]; v->e[2]*=v->ed[2]; break;
    case C8K_LC: case C8K_MC: case C8K_HC:
        y=bq_run(&v->q[0],0.0f);
        if (v->drum==C8K_HC) y=kit_clampf(2.3f*y,-0.42f,0.42f);
        if (n<48) y*=(float)n*(1.0f/48);
        v->e[0]*=v->ed[0]; break;
    case C8K_CY: case C8K_OH: case C8K_CH: {
        float metal=0.0f,a;
        for(int j=0;j<6;++j) {
            float hz=metal_hz[j]*v->ratio;
            float dt=kitcr8000_tune(hz)/KIT_FS;
            float ph=(v->sweep_on && (v->role==4||v->role==5))?kit_parameter_phase(v,j,hz):kitcr8000_phase(frame,hz);
            metal+=kit_pulse(ph,dt,0.47f);
        }
        metal=kit_parameter_metal(v,metal/6)*6;
        if (v->drum==C8K_CY) {
            a=0.8f*v->e[0]+0.2f*v->e[1];
            if ((float)n*v->mi<1.0f) a*=(float)n*v->mi;
            x=bq_run(&v->q[1],bq_run(&v->q[0],metal));
            y=bq_run(&v->q[3],x+0.8f*bq_run(&v->q[2],x))*a;
            v->e[0]*=v->ed[0]; v->e[1]*=v->ed[1];
        } else {
            a=kit_vca(v);
            x=bq_run(&v->q[1],bq_run(&v->q[0],metal));
            y=(x+1.5f*bq_run(&v->q[2],x))*a;
            v->e[0]=v->e[2];
        }
        break;
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
        y+=0.45f*(0.5f+v->nmix)*bq_run(&v->q[1],kit_parameter_noise(v,kit_shared_noise(frame)))*env;
        v->e[0]*=v->ed[0]; break;
    }
    case C8K_CB: {
        float hi=kit_pulse(kitcr8000_phase(frame,814.0f*v->ratio),814.0f*v->ratio/KIT_FS,0.5f);
        float lo=kit_pulse(kitcr8000_phase(frame,551.0f*v->ratio),551.0f*v->ratio/KIT_FS,0.5f);
        float a=0.9f*v->e[0]+0.1f*v->e[1];
        if ((float)n*v->mi<1.0f) a*=(float)n*v->mi;
        y=bq_run(&v->q[0],hi+0.25f*lo)*a;
        v->e[0]*=v->ed[0]; v->e[1]*=v->ed[1]; break;
    }
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
        y=bq_run(&v->q[1],bq_run(&v->q[0],kit_parameter_noise(v,kit_shared_noise(frame))))*(0.70f*env+0.30f*v->e[1])*gate*attack*v->nmix;
        v->e[0]*=v->ed[0]; v->e[1]*=v->ed[1]; break;
    }
    }
    ++v->n; ++v->source_frame;
    v->amp*=v->adec;
    if(v->n>480 && v->e[0]<KIT_SILENT && v->e[1]<KIT_SILENT && v->amp<KIT_SILENT)
        v->live=0;
    return y*v->gain;
}
