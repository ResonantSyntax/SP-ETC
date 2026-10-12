/* Original procedural percussion. DR110/KPR77 are reference-inspired
 * abstractions, not component-exact clones or recovered ACB. Every output
 * sample is computed here: oscillators, filtered noise and envelopes. */
static void kitproc_lp(kit_bq *q,float f,float Q) {
    float sn,cs;kit_sincos(f,&sn,&cs);float a=sn/(2*Q),n=1/(1+a);
    q->b0=(1-cs)*.5f*n;q->b1=(1-cs)*n;q->b2=q->b0;q->a1=-2*cs*n;q->a2=(1-a)*n;
}
static void kitprocedural_start(kit_voice *v,float pitch,float decay,float tone) {
    int family,role;
    if(v->drum>=M9_CH){family=3;role=(v->drum==M9_CH ? 4 : v->drum==M9_OH ? 5 : v->drum==M9_CY ? 6 : 7);}
    else if(v->drum>=KP_BD){family=1;role=v->drum==KP_BD ? 0 : v->drum==KP_SD ? 2 : v->drum==KP_CH ? 4 : v->drum==KP_OH ? 5 : v->drum==KP_LT ? 10 : v->drum==KP_HT ? 12 : v->drum==KP_CP ? 3 : 6;}
    else {family=0;role=v->drum==DR_BD ? 0 : v->drum==DR_SD ? 2 : v->drum==DR_CH ? 4 : v->drum==DR_OH ? 5 : v->drum==DR_CP ? 3 : 6;}
    v->source_pad_[0]=(u8)family;v->source_pad_[1]=(u8)role;
    for(int i=0;i<5;++i)v->q[i]=(kit_bq){0};
    v->seed^=v->source_frame*0x85ebca6bu;
    v->ratio=pitch;v->amp=1;v->e[0]=1;v->e[1]=1;v->e[2]=1;
    v->mi=kit_exp2(1.6f*tone);v->mr=1.0f;
    v->nmix=kit_exp2(0.65f*tone);v->group=(role==4 || role==5) ? 1 : 0;
    float k=kit_clampf(decay,0.1f,4.0f),base=family==0 ? 50.5f : family==1 ? 65.0f : 43.0f;
    float seconds=.22f;
    if(role==0 || role==1){
        if(role==1)base=35.0f;
        v->fend=base*pitch;v->f=(base+(role==1 ? 32 : family==0 ? 284 : family==1 ? 12 : 125))*pitch;
        /* Recordings: DR-110 ~120 Hz over the first half cycle, 56 Hz by
         * 11 ms, then 48-52 Hz (a 2.85 ms glide from ~335 Hz), tau ~23 ms;
         * KPR-77 ~71 Hz for the first half cycle, then 65 Hz, tau ~40 ms. */
        v->pe=1;v->pdec=role==1 ? kit_decay60(.045f) : family==0 ? KIT_TAU(.00285f) : family==1 ? KIT_TAU(.008f) : kit_decay60(.030f);
        seconds=role==1 ? 1.65f : family==0 ? .13f : family==1 ? .22f : .65f;
        v->namp=(role==1 ? .018f : family==1 ? .25f : .12f)*v->nmix;v->ndec=kit_decay60(role==0 && family==1 ? .012f : .004f);
        v->mr=role==1 ? .03f+.10f*(tone+1) : family<2 ? .03f+.03f*(tone+1) : .03f+.13f*(tone+1);
    } else if(role==2){
        v->f=family==0 ? 245 : family==1 ? 226 : 183;v->f*=pitch;
        v->fend=v->f*(family==0 ? 1.87f : family==1 ? 1.53f : 2.41f);
        bq_hp(&v->q[0],kit_clampf((family==1 ? 950 : 1600)*v->nmix,400,6000),.71f);
        kitproc_lp(&v->q[1],kit_clampf((family==0 ? 10500 : 8500)*v->nmix,2000,16000),.72f);
        seconds=family==0 ? .20f : family==1 ? .22f : .34f;
        v->ed[0]=kit_decay60((family==1 ? .16f : .07f)*k);v->nmix=(.28f+.35f*(tone+1))*(family==0 ? .63f : family==1 ? .20f : 1.0f);
        v->mr=family==2 ? .45f : .15f;                 /* second body oscillator */
    } else if(role==3){
        /* DR-110 recordings: three ~1.7 ms bursts 12 ms apart, then a tail
         * from 36 ms held ~30 ms (tau 33 ms), band ~1 kHz rolling off above.
         * KPR-77: continuous noise held ~65 ms (tau 22 ms) over a -30 dB tail. */
        bq_bp(&v->q[0],kit_clampf((family==0 ? 1000 : family==1 ? 980 : 1700)*v->nmix*pitch,250,14000),family==0 ? .9f : .75f);
        bq_hp(&v->q[1],600,.71f);seconds=family==0 ? .20f : family==1 ? .70f : .26f;
        if(family==0)bq_lp(&v->q[2],9000,.7f);
        v->ed[0]=kit_decay60(.018f*k);
        v->e[1]=0;v->ed[1]=KIT_TAU(.0017f);v->mi=0;
        if(family==0)kit_hold(v,1.0f,1.0f,.045f*k);   /* hold set when the tail starts */
        else kit_hold(v,.5f,family==1 ? .065f*k : .03f*k,family==1 ? .028f*k : .03f*k);
    } else if(role>=4 && role<=7){
        /* Families: 0 DR-110, 1 KPR-77, 3 TR-909 (stand-ins for its sampled
         * cymbals). Band centre/Q, low-mid share and top low-pass are fitted to
         * the recordings' 1/3-octave balance; T60 per role (CH, OH, CY, RD)
         * to their -20/-40 dB times (909: the ACB plug-in capture). */
        static const float centre[4]={6300,6100,6400,7400},bandq[4]={1.25f,1.5f,1.2f,.55f};
        static const float top[4]={16000,16000,12000,13000},hpf[4]={4300,4000,3000,3300};
        static const float t60[4][4]={{.14f,.85f,1.4f,1.45f},{.45f,2.0f,.75f,1.45f},{.075f,.65f,.95f,1.45f},{.22f,.56f,1.3f,1.4f}};
        bq_bp(&v->q[0],kit_clampf(centre[family]*v->nmix,2000,14000),bandq[family]);
        bq_hp(&v->q[1],family==3 ? 240.0f : 380.0f,.7f);
        bq_lp(&v->q[2],top[family],.7f);
        if(family==1)bq_bp(&v->q[3],13000,1.5f);   /* KPR-77's 12-16 kHz shimmer */
        bq_hp(&v->q[4],hpf[family],.6f);          /* steep lower edge of the metal band */
        seconds=t60[family][role-4];
        v->ed[0]=kit_decay60((role==6 ? .09f : .12f)*k);
        v->mr=0;v->e[1]=1;v->ed[1]=1;v->qv=0;
        if(family==0 && role==5){seconds=2.42f;v->qv=.25f*k*KIT_FS;v->mdec=KIT_TAU(.12f*k);}  /* -3 dB at 100 ms, -30 at 800 */
        if(family==0 && role==6){seconds=.104f;v->mr=.28f;v->ed[1]=KIT_TAU(.30f*k);}      /* -12 dB at 40 ms, -26 at 600 */
        if(family==1 && role==5)seconds=3.0f;                                            /* -13 dB at 800 ms */
        for(int i=0;i<6;++i){
            float hz=(family==0 ? 291.0f : family==1 ? 397.0f : family==3 ? 421.0f : 353.0f)*(1+i*.47f+i*i*.071f)*pitch;
            u32 step=(u32)(hz/KIT_FS*4294967296.0f);
            v->ph[i]=(float)(step*v->source_frame)*2.3283064365386963e-10f;
            if(v->ph[i]>=1)v->ph[i]=0;
        }
    } else if(role==8 || role==9){
        v->f=(role==8 ? 430.0f : 557.0f)*pitch;v->fend=(role==8 ? 1480.0f : 845.0f)*pitch;
        seconds=role==8 ? .065f : .27f;
        bq_bp(&v->q[0],role==8 ? 1300.0f : 820.0f,1.0f);
    } else if(role>=10 && role<=12){
        /* KPR-77 recordings: LT 162/140/130 Hz at 5/20/80 ms, HT ~199 Hz steady. */
        base=(role==10 ? 130.0f : role==11 ? 160.0f : 199.0f)*pitch;
        v->fend=base;v->f=base*(role==12 ? 1.0f : 1.36f);v->pe=1;v->pdec=KIT_TAU(.0129f);
        seconds=family==1 ? .50f : .62f;v->mr=.04f*v->mi;
    } else if(role==13){
        v->f=1450*pitch;v->fend=65*pitch;v->pe=1;v->pdec=kit_decay60(.30f*k);seconds=.50f;v->mr=.8f*v->mi;
    } else {
        bq_hp(&v->q[0],(role==14 ? 4700 : 2200)*pitch,.72f);seconds=role==14 ? .12f : .018f;
    }
    v->adec=kit_decay60(seconds*k);
}

static float kitprocedural_render(kit_voice *v) {
    int role=v->source_pad_[1],family=v->source_pad_[0];float y=0,noise=kit_noise(v),f;
    if(role==0 || role==1 || (role>=10 && role<=13)) {
        f=v->fend+(v->f-v->fend)*v->pe;v->pe*=v->pdec;
        v->ph[0]+=f/KIT_FS;v->ph[0]-=(float)(int)v->ph[0];
        v->ph[1]+=f*(role==13 ? 2.37f : 2.0f)/KIT_FS;v->ph[1]-=(float)(int)v->ph[1];
        float mod=role>=10 ? v->mr*v->amp*kit_sin2pi(v->ph[1]) : 0;
        y=(kit_sin2pi(v->ph[0]+mod)+((role<2) ? v->mr*kit_sin2pi(2*v->ph[0]) : (role==13 ? .13f : .03f)*kit_sin2pi(2.71f*v->ph[0])))*v->amp;
        y+=noise*v->namp;v->namp*=v->ndec;
    } else if(role==2) {
        v->ph[0]+=v->f/KIT_FS;v->ph[0]-=(float)(int)v->ph[0];v->ph[1]+=v->fend/KIT_FS;v->ph[1]-=(float)(int)v->ph[1];
        float body=(kit_sin2pi(v->ph[0])+v->mr*kit_sin2pi(v->ph[1]))*.38f*v->e[0];
        float wire=bq_run(&v->q[1],bq_run(&v->q[0],noise))*v->nmix*v->amp;
        y=body+wire;v->e[0]*=v->ed[0];
    } else if(role==3) {
        u32 P=v->clap_period;float g;
        y=bq_run(&v->q[1],bq_run(&v->q[0],noise));
        if(family==0){
            if(v->n<3*P){ if(v->n%P==0)v->e[1]=1; g=1.5f*v->e[1]; v->e[1]*=v->ed[1]; }
            else { u32 m=v->n-3*P; if(m==0)v->qv=(float)v->n+.030f*KIT_FS*v->ratio; g=(m<96 ? (float)m*(1.0f/96) : 1.0f)*kit_vca(v); }
            y=bq_run(&v->q[2],y)*g*2.0f;
        } else {
            g=((v->n%P)<P/2 ? 1.0f : family==1 ? .6f : .12f)*kit_vca(v);
            y*=(g+(family==1 ? .035f*v->amp : 0))*1.25f;
        }
    } else if(role>=4 && role<=7) {
        float metal=0;
        for(int i=0;i<6;++i){
            float hz=(family==0 ? 291.0f : family==1 ? 397.0f : family==3 ? 421.0f : 353.0f)*(1+i*.47f+i*i*.071f)*v->ratio;
            float dt=hz/KIT_FS;v->ph[i]+=dt;v->ph[i]-=(float)(int)v->ph[i];metal+=kit_pulse(v->ph[i],dt,.47f);
        }
        metal*=1.0f/6.0f;
        static const float lowmix[4]={.03f,.04f,.05f,.75f},noisemix[4]={.30f,.25f,.15f,.45f};
        if(family==2 || family==3)metal=.62f*metal+.38f*kit_sin2pi(v->ph[0]+.65f*kit_sin2pi(v->ph[3]));
        metal+=noisemix[family]*(noise-metal);
        metal=kit_parameter_metal(v,metal);
        float band=bq_run(&v->q[0],bq_run(&v->q[4],metal)),low=bq_run(&v->q[1],metal)*lowmix[family];
        y=bq_run(&v->q[2],band+low);
        if(family==1)y+=.45f*bq_run(&v->q[3],metal);
        y*=(v->amp*(1-v->mr)+v->mr*v->e[1])*2.2f;v->e[1]*=v->ed[1];
        if(v->qv>0 && (float)v->n>=v->qv){v->adec=v->mdec;v->qv=0;}
        if(role==6)y+=.18f*noise*v->e[0];v->e[0]*=v->ed[0];
        if(role==6 && family==3 && v->n<1400)y*=.25f+.75f*(float)v->n*(1.0f/1400);   /* ACB crash swells ~30 ms */
    } else if(role==8 || role==9) {
        v->ph[0]+=v->f/KIT_FS;v->ph[0]-=(float)(int)v->ph[0];v->ph[1]+=v->fend/KIT_FS;v->ph[1]-=(float)(int)v->ph[1];
        float x=role==8 ? kit_sin2pi(v->ph[0])+kit_sin2pi(v->ph[1]) : kit_pulse(v->ph[0],v->f/KIT_FS,.5f)+kit_pulse(v->ph[1],v->fend/KIT_FS,.5f);
        y=bq_run(&v->q[0],x)*v->amp*.7f;
    } else y=bq_run(&v->q[0],noise)*v->amp*.65f;
    v->amp*=v->adec;++v->n;++v->source_frame;
    if(v->n>960 && v->amp<KIT_SILENT && v->namp<KIT_SILENT && v->mr*v->e[1]<KIT_SILENT && (role!=3 || v->e[2]<KIT_SILENT))v->live=0;
    return y*v->gain;
}
