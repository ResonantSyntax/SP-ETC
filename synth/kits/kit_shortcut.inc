/* SHIFT + PATTERN EDIT enters the shared generator with the last kit.
 * Handle release so the native press handler has finished before switching. */
static void stop(void);
static u8 kit_last_mode=1;
EXPORT u8 kit_ui_shift;
EXPORT u32 kit_shortcut_trace[8];
static int kit_key_down(int key){return ((int(*)(int))0x800D9F21u)(key);}
/* Native handlers query SHIFT on press, before changing pages. Capture the
 * chord there as well as on the common release handler, so releasing SHIFT
 * first cannot retain the previous drum mode. Physical key state is read only. */
static u8 kit_shortcut_pending,kit_shortcut_chord;
static void kit_shortcut_select(int kits){
    if(kit_mode)kit_last_mode=kit_mode;
    RELEASE_ALL();held_count=0;stop();kit_pads_down=0;
    for(int i=0;i<8;++i)kit_slot[i].live=0;
    kit_mode=kits?(kit_last_mode?kit_last_mode:1):0;
    kit_ui_shift=0;kit_ui_shift_down=1;kit_ui_shift_used=1;
    kit_edit_changed=1;kit_ui_invalidate();
    int cursor=KIT_SETTING_GET(KIT_SETTINGS,0x83,0),next=kits?11:0;
    if(cursor!=next)KIT_SETTING_STEP(KIT_SETTINGS,0x83,next-cursor,0,0);
}
static void kit_shortcut_observe(void){
    volatile u8 *flags=(volatile u8*)0x80592448u;
    int current=*(volatile signed short*)0x80245880u;
    if(current!=1&&current!=0x22&&current!=0x13&&current!=0x1e)return;
    int shift=(flags[42>>3]>>(42&7))&1;
    int record=(flags[22>>3]>>(22&7))&1;
    int pattern=(flags[21>>3]>>(21&7))&1;
    int chord=shift?(record?2:pattern?1:0):0;
    if(chord && chord!=kit_shortcut_chord){
        kit_shortcut_pending=(u8)chord;
        if(chord==2)kit_shortcut_select(0);
    }
    kit_shortcut_chord=(u8)chord;
}
EXPORT int kit_shortcut_event(void *page,const u16 *event){
    (void)page;int type=event[0],key=event[1];
    if(type!=6||(key!=21&&key!=22))return 0;
    int current=*(volatile signed short*)0x80245880u;
    int intent=key==21?1:2;
    int selected=kit_shortcut_pending==intent || kit_key_down(42);
    if(current!=1&&current!=0x22&&current!=0x13&&current!=0x1e)return 0;
    if(!selected)return 0;
    kit_shortcut_select(intent==1);
    kit_shortcut_pending=0;kit_shortcut_chord=0;
    ++kit_shortcut_trace[7];
    if(current!=0x1e)((void(*)(int))0x6031C9A9u)(0x1e);
    return 1;
}
__attribute__((naked,used)) EXPORT void kit_shortcut_gate(void){
    __asm__ volatile(
        "push {r0,r1,r2,lr}\nbl kit_shortcut_event\ncmp r0,#0\nbeq 1f\n"
        "pop {r0,r1,r2,lr}\nmovs r0,#1\nbx lr\n"
        "1: pop {r0,r1,r2,lr}\n"
        "push {r4,r5,r6,lr}\nsub sp,#8\nmov r6,r1\nldrsh.w r1,[r1]\nmovs r5,#0\n"
        "movw r12,#0x80b5\nmovt r12,#0x800a\nbx r12\n");
}
