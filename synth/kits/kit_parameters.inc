/* Musical extensions, not claims about the original machines' panel controls.
 * 50 is the neutral starting point for Sweep/Noise/Attack. */
static int kit_role(int d) {
    if(d==CLAP||d==T8_CP||d==T9_CP||d==C8K_CP||d==DR_CP||d==KP_CP||d==DG_CP)return 3;
    if(d==SNARE||d==SNARE2||d==FM_SNARE||d==T8_SD||d==T9_SD||d==T6_SD||d==SDS_SD||d==C78_SD||d==C8K_SD||d==DR_SD||d==KP_SD||d==DG_SD)return 2;
    if(d==CHH||d==OHH||d==FM_HAT||d==T8_CH||d==T8_OH||d==T6_CH||d==T6_OH||d==C78_HH||d==C8K_CH||d==C8K_OH||d==DR_CH||d==DR_OH||d==KP_CH||d==KP_OH||d==DG_CH||d==DG_OH||d==M9_CH||d==M9_OH)return 4;
    if(d==CYM||d==T8_CY||d==T6_CY||d==C78_CY||d==C8K_CY||d==DR_CY||d==KP_CY||d==DG_CY||d==DG_RD||d==M9_CY||d==M9_RD)return 5;
    if(d==SHAKER||d==C78_MA||d==C78_TB||d==C78_MB||d==T8_MA||d==DG_SHAKE||d==DG_CLICK||d==SY_NOISE)return 6;
    return 1;
}
static void kit_parameters_init(kit_voice *v,const kit_pad *p) {
    v->role=(u8)kit_role(p->sound);
    v->ctrl_sweep=kit_clampf(p->sweep,0,100)*.02f;
    v->ctrl_noise=kit_clampf(p->noise,0,100)*.02f;
    v->ctrl_attack=kit_clampf(p->attack,0,100)*.02f;
    v->ctrl_tone=(kit_clampf(p->tone,0,100)-50)*.02f;
    if(p->sound==T8_BD)v->ctrl_tone=0; /* existing physical tone pot */
    v->ctrl_lp=v->noise_lp=0;v->sweep_env=1;
    v->clap_period=(u32)(480*kit_exp2((kit_clampf(p->sweep,0,100)-50)*.025f));
}
static float kit_parameter_noise(kit_voice *v,float x) {
    if(v->role==3 || v->role==6) {
        /* Predominantly noisy voices retain energy: change texture, not level. */
        v->noise_lp+=.10f*(x-v->noise_lp);
        float t=v->ctrl_noise-1;
        return t<0 ? x*(1+t)+v->noise_lp*(-t)*2.6f : x+t*(x-v->noise_lp)*.35f;
    }
    return x*v->ctrl_noise;
}
static float kit_parameter_metal(kit_voice *v,float x) {
    float t=kit_clampf(v->ctrl_noise*.5f,0,1);
    return x*(1-t)+kit_shared_noise(v->source_frame)*t*.7f;
}
static float kit_parameter_phase(kit_voice *v,int j,float hz) {
    float dt=kit_clampf(hz,1,19000)/KIT_FS;
    if(v->n==0){u32 step=(u32)(dt*4294967296.0f);v->ph[j]=(float)(step*v->source_frame)*2.3283064365386963e-10f;}
    else {v->ph[j]+=dt;v->ph[j]-=(float)(int)v->ph[j];}
    return v->ph[j]>=1?0:v->ph[j];
}
static void kit_parameters_start(kit_voice *v) {
    if(v->drum==T8_CY && (v->ctrl_sweep>0||v->ctrl_noise>0)){bq_bp(&v->q[0],3450,6);bq_bp(&v->q[1],7100,6);}
    for(int j=0;j<2;++j){v->sweep_a1[j]=v->q[j].a1;v->sweep_radius[j]=v->q[j].a2>0?__builtin_sqrtf(v->q[j].a2):0;}

    if(v->pe>0)v->pe*=v->ctrl_sweep;
    if(v->role==3) {
        if(v->drum==CLAP)v->clap_period=(u32)(528*kit_exp2((v->ctrl_sweep-1)*1.25f));
        if(v->drum==DR_CP||v->drum==KP_CP||v->drum==DG_CP)v->clap_period=(u32)(192*kit_exp2((v->ctrl_sweep-1)*1.25f));
        if(v->drum==C8K_CP)v->f/=kit_exp2((v->ctrl_sweep-1)*1.25f);
    }
    if(v->role==2 && v->ctrl_noise<1)v->amp*=1+.25f*(1-v->ctrl_noise);
}
static void kit_parameters_tick(kit_voice *v) {
    v->sweep_env*=.998562f; /* short pitch movement, ~100 ms to -60 dB */
}
static float kit_parameters_output(kit_voice *v,float y) {
    /* Attack changes only the opening 12 ms (each clap burst independently).
     * Tone is broadband colour independent of noise amount and transient. */
    u32 n=v->n?v->n-1:0;
    float phase=(float)(v->role==3 && n<4*v->clap_period ? n%v->clap_period : n);
    float transient=kit_clampf(1-phase/576,0,1),a=v->ctrl_attack-1;
    float cutoff=kit_clampf(6000*kit_exp2(2*v->ctrl_tone),250,20000);
    float pole=1-kit_exp2(-9.06472f*cutoff/KIT_FS);
    v->ctrl_lp+=pole*(y-v->ctrl_lp);
    float t=v->ctrl_tone;
    if(t<0)y=y*(1+t)+v->ctrl_lp*(-t);
    else y+=t*.7f*(y-v->ctrl_lp);
    if(v->role==1) {
        float mix=v->ctrl_noise-1;
        if(mix>0)y+=kit_shared_noise(v->source_frame)*v->gain*mix*.05f*transient;
        else y=y*(1+mix*transient)+v->ctrl_lp*(-mix)*transient;
    }
    if(a<0) y*=1+a*transient; /* soften stick/click without changing the tail */
    else y+=a*transient*(y-v->ctrl_lp)*.8f;
    return y;
}
