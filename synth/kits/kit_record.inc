/* ---- Drum export length: REC and BOUNC ring out, never PAD LENGTH ----
 * PAD LENGTH (+0x180, setting 0x7e) is a melodic setting that drum mode does
 * not show; in periods (<= 0) it gave a drum recording a few milliseconds. A
 * drum export ends where the last of its drums has fallen 60 dB below its own
 * peak, at most 10 s. kit_export_frames holds that length for the next export:
 * the stock exporter's length code takes it once (kit_export_length_gate at
 * 0x80132ac8) instead of PAD LENGTH. A melodic capture sets it to 0, so melodic
 * REC keeps PAD LENGTH as stock. */
#define KIT_EXPORT_CAP 480000u                       /* frames: 10 s */
#define KIT_EXPORT_FLOOR 1e-3f                       /* -60 dB of the drum's own peak */
#define KIT_EXPORT_SILENT 480u                       /* frames written for a silent capture */
EXPORT volatile u32 kit_export_frames;               /* nonzero: the next export's frame count */

/* An export voice cleared. kit_start leaves some filter state from the voice's
 * previous sound (the table voices' noise filters), so without this a drum's
 * first milliseconds would depend on what was exported before it. */
static void kit_export_clear(int j) {
    volatile u32 *w = (volatile u32 *)&kit_slot[4 + j];
    for (u32 k = 0; k < sizeof(kit_voice) / 4; ++k) w[k] = 0;
}

/* Pre-render export voice j alone, as the export renders it (its recipe, seed
 * and origin, kit_output_slot's per-sample steps), from a cleared voice. Returns
 * the frames up to its last sample at or above -60 dB of its own peak (0 =
 * silent), at most `cap`. The voice is cleared again afterwards: the export
 * starts it afresh and every shared source it uses from its origin, so this
 * leaves nothing that changes the file. */
static u32 kit_export_measure(int j, int pad, u32 cap) {
    kit_voice *v = &kit_slot[4 + j];
    kit_export_clear(j);
    kit_start(v, 4 + j, pad);
    float peak = 0;
    u32 end = 0;
    for (u32 n = 0; n < cap && v->live; ++n) {
        v->source_frame = v->n + kit_export_origin[j];
        float y = kit_absf(kit_limit(kit_render_slot(v, 4 + j)));
        if (y > peak) peak = y;
        if (y > 0 && y >= peak * KIT_EXPORT_FLOOR) end = n + 1;
    }
    kit_export_clear(j);
    return end;
}

/* Stock exporter, 0x80132ac8 (mov r4, r8; cmp.w fp, #1; mov.w r0, #0): fp
 * holds the frame count and [sp, #4] the loop's frame limit, both just
 * computed from PAD LENGTH. When kit_export_frames is set, both become it and
 * it is cleared (one export). r0 is free here: the displaced mov.w writes it.
 * The displaced instructions follow; the flags of their cmp reach the stock
 * blt.w at 0x80132ad6 after its str (which leaves them alone). */
__attribute__((naked, used)) EXPORT void kit_export_length_gate(void) {
    __asm__ volatile(
        "movw r12, #:lower16:kit_export_frames\n\tmovt r12, #:upper16:kit_export_frames\n\t"
        "ldr r0, [r12]\n\tcmp r0, #0\n\tbeq 1f\n\t"
        "mov r11, r0\n\tstr r0, [sp, #4]\n\tmovs r0, #0\n\tstr r0, [r12]\n"
        "1:\n\tmov r4, r8\n\tcmp.w r11, #1\n\tmov.w r0, #0\n\t"
        "movw r12, #0x2ad3\n\tmovt r12, #0x8013\n\tbx r12\n");                 /* 0x80132ad2 */
}

/* REC captures the last struck drum together with every other drum struck up
 * to 100 ms before it (a chord or flam), at most four, each at its own offset.
 * Each keeps its recipe, velocity, noise seed and shared-oscillator onset. The
 * recording ends where the last of them has rung out (kit_export_frames). */
#define KIT_CHORD_WINDOW 4800u      /* frames: strikes that land together record together */
EXPORT u32 kit_capture_count;
EXPORT int kit_capture_selected(void){
    if(!kit_mode){kit_export_active=0;kit_export_frames=0;return 0;}
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
    /* Each drum's own ring-out from its offset; the last one ends the recording. */
    u32 frames=0;
    for(int j=0;j<n;++j){
        u32 d=kit_export_delay[j];
        u32 e=d<KIT_EXPORT_CAP?kit_export_measure(j,pads[j],KIT_EXPORT_CAP-d):0;
        if(e&&d+e>frames)frames=d+e;
    }
    kit_export_frames=frames?frames:KIT_EXPORT_SILENT;
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
