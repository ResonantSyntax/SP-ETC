/* REC captures one selected drum, independent of held synth chord snapshots.
 * Preserve its recipe, velocity, noise seed and shared-oscillator onset. */
EXPORT u32 kit_capture_count;
EXPORT int kit_capture_selected(void){
    if(!kit_mode){kit_export_active=0;return 0;}
    kit_init_pads();
    DISPATCH_OFF();
    int pad=kit_record_pad&15;
    volatile u32 *from=(volatile u32*)KIT_SINGLETON;
    volatile u32 *to=(volatile u32*)KIT_EXPORT_BASE;
    for(int n=0;n<108;++n)to[n]=from[n];
    kit_export_mode=kit_mode;
    kit_export_recipe=kit_pads[kit_export_mode-1][pad];
    int hit=kit_hit_mode[pad]==kit_export_mode;
    int same=hit;
    const u8 *heard=(const u8*)&kit_hit_recipe[pad],*now=(const u8*)&kit_export_recipe;
    for(int n=0;n<(int)sizeof(kit_pad);++n)if(heard[n]!=now[n])same=0;
    kit_export_bd_ready=kit_record_bd_valid&&same&&kit_export_recipe.sound==T8_BD;
    if(kit_export_bd_ready)kit_export_bd_initial=kit_record_bd_initial;
    kit_export_origin=hit?kit_hit_origin[pad]:0;
    kit_export_seed=hit?kit_hit_seed[pad]:0x9E3779B9u^((u32)pad*0xC2B2AE35u);
    to[0x1ac/4]=(u32)pad;
    to[0x10/4]=0; /* drum's own envelope; no inherited melodic ENV */
    ((volatile u8*)to)[4]=0; /* one-shot, never trim to a melodic oscillator cycle */
    to[0x198/4]=(kit_record_velocity?kit_record_velocity:127)*100u;
    to[0x74/4]=to[0x198/4];
    for(int i=4;i<8;++i)kit_slot[i].live=0;
    kit_export_active=1;++kit_capture_count;
    *(volatile u32*)0x8353c700u=1;
    DISPATCH_ON();
    return 1;
}
__attribute__((naked,used)) EXPORT void kit_capture_gate(void){
    __asm__ volatile(
        "push {r0,r1,r2,lr}\nbl kit_capture_selected\ncmp r0,#0\nbeq 1f\n"
        "pop {r0,r1,r2,lr}\nmovs r0,#1\nbx lr\n"
        "1: pop {r0,r1,r2,lr}\npush.w {r4,r5,r6,r7,r8,lr}\n"
        "movw r4,#0x9800\nmovt r4,#0x8024\n"
        "movw r12,#0xb60d\nmovt r12,#0x8353\nbx r12\n");
}
