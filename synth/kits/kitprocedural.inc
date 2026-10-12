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
    else if(v->drum>=DG_BD){family=2;role=v->drum-DG_BD;}
    else if(v->drum>=KP_BD){family=1;role=v->drum==KP_BD ? 0 : v->drum==KP_SD ? 2 : v->drum==KP_CH ? 4 : v->drum==KP_OH ? 5 : v->drum==KP_LT ? 10 : v->drum==KP_HT ? 12 : v->drum==KP_CP ? 3 : 6;}
    else {family=0;role=v->drum==DR_BD ? 0 : v->drum==DR_SD ? 2 : v->drum==DR_CH ? 4 : v->drum==DR_OH ? 5 : v->drum==DR_CP ? 3 : 6;}
    v->source_pad_[0]=(u8)family;v->source_pad_[1]=(u8)role;
    for(int i=0;i<5;++i)v->q[i]=(kit_bq){0};
    v->seed^=v->source_frame*0x85ebca6bu;
    v->ratio=pitch;v->amp=1;v->e[0]=1;v->e[1]=1;v->e[2]=1;
    v->mi=kit_exp2(1.6f*tone);v->mr=1.0f;
    v->nmix=kit_exp2(0.65f*tone);v->group=(role==4 || role==5) ? 1 : 0;
    float k=kit_clampf(decay,0.1f,4.0f),base=family==0 ? 50.5f : family==1 ? 64.6f : 43.0f;
    float seconds=.22f;
    if(role==0 || role==1){
        if(role==1)base=35.0f;
        v->fend=base*pitch;v->f=(base+(role==1 ? 32 : family==0 ? 65 : 125))*pitch;
        v->pe=1;v->pdec=kit_decay60(role==1 ? .045f : family==0 ? .012f : .030f);
        seconds=role==1 ? 1.65f : family==0 ? .20f : family==1 ? .42f : .65f;
        v->namp=(role==1 ? .018f : .12f)*v->nmix;v->ndec=kit_decay60(.004f);
        v->mr=role==1 ? .03f+.10f*(tone+1) : .03f+.13f*(tone+1);
    } else if(role==2){
        v->f=family==0 ? 195 : family==1 ? 165 : 183;v->f*=pitch;
        v->fend=v->f*(family==0 ? 1.87f : family==1 ? 1.53f : 2.41f);
        bq_hp(&v->q[0],kit_clampf((family==1 ? 950 : 1600)*v->nmix,400,6000),.71f);
        kitproc_lp(&v->q[1],kit_clampf((family==0 ? 10500 : 8500)*v->nmix,2000,16000),.72f);
        seconds=family==0 ? .17f : family==1 ? .26f : .34f;
        v->ed[0]=kit_decay60(.07f*k);v->nmix=.28f+.35f*(tone+1);
    } else if(role==3){
        bq_bp(&v->q[0],kit_clampf((family==0 ? 1300 : family==1 ? 980 : 1700)*v->nmix*pitch,250,14000),.75f);
        bq_hp(&v->q[1],600,.71f);seconds=family==0 ? .20f : family==1 ? .32f : .26f;
        v->ed[0]=kit_decay60(.018f*k);
    } else if(role>=4 && role<=7){
        float cutoff=(family==0 ? 7200 : family==1 ? 5900 : family==3 ? 8100 : 6400)*v->nmix;
        bq_hp(&v->q[0],kit_clampf(cutoff,2500,13000),.72f);
        bq_bp(&v->q[1],kit_clampf(cutoff*.83f,2000,11500),1.6f);
        seconds=role==4 ? (family==0 ? .045f : .075f) : role==5 ? (family==0 ? .42f : .65f) : role==6 ? .95f : 1.45f;
        v->ed[0]=kit_decay60((role==6 ? .09f : .12f)*k);
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
        base=(role==10 ? 91.0f : role==11 ? 137.0f : 205.0f)*pitch;
        v->fend=base;v->f=base*1.7f;v->pe=1;v->pdec=kit_decay60(.024f);
        seconds=family==1 ? .38f : .62f;v->mr=.16f*v->mi;
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
        y=(kit_sin2pi(v->ph[0]+mod)+((role<2) ? v->mr*kit_sin2pi(2*v->ph[0]) : .13f*kit_sin2pi(2.71f*v->ph[0])))*v->amp;
        y+=noise*v->namp;v->namp*=v->ndec;
    } else if(role==2) {
        v->ph[0]+=v->f/KIT_FS;v->ph[0]-=(float)(int)v->ph[0];v->ph[1]+=v->fend/KIT_FS;v->ph[1]-=(float)(int)v->ph[1];
        float body=(kit_sin2pi(v->ph[0])+.45f*kit_sin2pi(v->ph[1]))*.38f*v->e[0];
        float wire=bq_run(&v->q[1],bq_run(&v->q[0],noise))*v->nmix*v->amp;
        y=body+wire;v->e[0]*=v->ed[0];
    } else if(role==3) {
        float burst=v->n<3*v->clap_period ? ((v->n%v->clap_period)<v->clap_period/2 ? 1.0f : .12f) : .30f;
        y=bq_run(&v->q[1],bq_run(&v->q[0],noise))*v->amp*burst*1.25f;
    } else if(role>=4 && role<=7) {
        float metal=0;
        for(int i=0;i<6;++i){
            float hz=(family==0 ? 291.0f : family==1 ? 397.0f : family==3 ? 421.0f : 353.0f)*(1+i*.47f+i*i*.071f)*v->ratio;
            float dt=hz/KIT_FS;v->ph[i]+=dt;v->ph[i]-=(float)(int)v->ph[i];metal+=kit_pulse(v->ph[i],dt,.47f);
        }
        metal*=1.0f/6.0f;
        if(family==2 || family==3){
            metal=.55f*metal+.32f*kit_sin2pi(v->ph[0]+.65f*kit_sin2pi(v->ph[3]))+.13f*noise;
        } else metal=.85f*metal+.15f*noise;
        metal=kit_parameter_metal(v,metal);
        float high=bq_run(&v->q[0],metal);float band=bq_run(&v->q[1],metal);
        y=(high+(role==7 ? .85f : .35f)*band)*v->amp*1.7f;
        if(role==6)y+=.18f*noise*v->e[0];v->e[0]*=v->ed[0];
    } else if(role==8 || role==9) {
        v->ph[0]+=v->f/KIT_FS;v->ph[0]-=(float)(int)v->ph[0];v->ph[1]+=v->fend/KIT_FS;v->ph[1]-=(float)(int)v->ph[1];
        float x=role==8 ? kit_sin2pi(v->ph[0])+kit_sin2pi(v->ph[1]) : kit_pulse(v->ph[0],v->f/KIT_FS,.5f)+kit_pulse(v->ph[1],v->fend/KIT_FS,.5f);
        y=bq_run(&v->q[0],x)*v->amp*.7f;
    } else y=bq_run(&v->q[0],noise)*v->amp*.65f;
    v->amp*=v->adec;++v->n;++v->source_frame;
    if(v->n>960 && v->amp<KIT_SILENT && v->namp<KIT_SILENT)v->live=0;
    return y*v->gain;
}
