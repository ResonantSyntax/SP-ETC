/* REC captures the last struck drum together with every other drum struck up
 * to 100 ms before it (a chord or flam), at most four, each at its own offset.
 * Each keeps its recipe, velocity, noise seed and shared-oscillator onset. */
#define KIT_CHORD_WINDOW 4800u      /* frames: strikes that land together record together */
EXPORT u32 kit_capture_count;
EXPORT int kit_capture_selected(void){
    if(!kit_mode){kit_export_active=0;return 0;}
    kit_init_pads();
    DISPATCH_OFF();
    int mode=kit_mode,anchor=kit_record_pad&15,n=1;
    u8 pads[4];pads[0]=(u8)anchor;
    if(kit_hit_mode[anchor]==mode){
        /* Add the newest other strikes that started within the window before the
         * anchor's strike; later strikes and other kits' strikes are left out. */
        u32 t=kit_hit_origin[anchor];
        while(n<4){
            int best=-1;u32 best_age=0;
            for(int p=0;p<16;++p){
                int taken=0;for(int q=0;q<n;++q)if(pads[q]==p)taken=1;
                if(taken||kit_hit_mode[p]!=mode)continue;
                u32 age=t-kit_hit_origin[p];
                if(age>KIT_CHORD_WINDOW)continue;
                if(best<0||age<best_age){best=p;best_age=age;}
            }
            if(best<0)break;
            pads[n++]=(u8)best;
        }
    }
    u32 first=kit_hit_origin[anchor];
    for(int j=1;j<n;++j)if((int)(kit_hit_origin[pads[j]]-first)<0)first=kit_hit_origin[pads[j]];
    kit_export_mode=(u8)mode;kit_export_bd_ready=0;kit_export_bd_slot=0;
    for(int j=0;j<n;++j){
        int pad=pads[j];
        volatile u32 *from=(volatile u32*)KIT_SINGLETON;
        volatile u32 *to=(volatile u32*)(KIT_EXPORT_BASE+(u32)j*KIT_VOICE_SIZE);
        for(int w=0;w<108;++w)to[w]=from[w];
        kit_export_recipe[j]=kit_pads[mode-1][pad];
        int hit=kit_hit_mode[pad]==mode;
        if(j==0){
            int same=hit;
            const u8 *heard=(const u8*)&kit_hit_recipe[pad],*now=(const u8*)&kit_export_recipe[0];
            for(int b=0;b<(int)sizeof(kit_pad);++b)if(heard[b]!=now[b])same=0;
            kit_export_bd_ready=kit_record_bd_valid&&same&&kit_export_recipe[0].sound==T8_BD;
            if(kit_export_bd_ready)kit_export_bd_initial=kit_record_bd_initial;
        }
        kit_export_origin[j]=hit?kit_hit_origin[pad]:0;
        kit_export_seed[j]=hit?kit_hit_seed[pad]:0x9E3779B9u^((u32)pad*0xC2B2AE35u);
        kit_export_delay[j]=hit&&n>1?kit_hit_origin[pad]-first:0;
        kit_export_frame[j]=0;
        int vel=j==0?kit_record_velocity:kit_hit_velocity[pad];
        to[0x1ac/4]=(u32)pad;
        to[0x10/4]=0; /* drum's own envelope; no inherited melodic ENV */
        ((volatile u8*)to)[4]=0; /* one-shot, never trim to a melodic oscillator cycle */
        to[0x198/4]=(vel?vel:127)*100u;
        to[0x74/4]=to[0x198/4];
    }
    for(int i=4;i<8;++i)kit_slot[i].live=0;
    kit_export_count=(u8)n;kit_export_active=1;++kit_capture_count;
    *(volatile u32*)0x8353c700u=(u32)n;
    DISPATCH_ON();
    return n;
}
__attribute__((naked,used)) EXPORT void kit_capture_gate(void){
    /* Returns the captured voice count, as the parent's chord snapshot does. */
    __asm__ volatile(
        "push {r0,r1,r2,lr}\nbl kit_capture_selected\ncmp r0,#0\nbeq 1f\n"
        "mov r3,r0\npop {r0,r1,r2,lr}\nmov r0,r3\nbx lr\n"
        "1: pop {r0,r1,r2,lr}\npush.w {r4,r5,r6,r7,r8,lr}\n"
        "movw r4,#0x9800\nmovt r4,#0x8024\n"
        "movw r12,#0xb60d\nmovt r12,#0x8353\nbx r12\n");
}
