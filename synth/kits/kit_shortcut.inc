/* SHIFT + PATTERN EDIT enters the shared generator with the last kit.
 * Handle release so the native press handler has finished before switching.
 * During a hot resample the native press would start or stop the take, so
 * kit_shortcut_press handles those presses (see below). */
static void stop(void);
static u8 kit_last_mode=1;
EXPORT u8 kit_ui_shift;
/* Counters: [4] stock SHIFT + RECORD SETTING from RESAMPLE, [5] SG presses
 * swallowed during a hot resample, [6] SHIFT + PATTERN EDIT from RESAMPLE,
 * [7] machine switches on release. */
EXPORT u32 kit_shortcut_trace[8];
static int kit_key_down(int key){return ((int(*)(int))0x800D9F21u)(key);}
/* Native handlers query SHIFT on press, before changing pages. Capture the
 * chord there as well as on the common release handler, so releasing SHIFT
 * first cannot retain the previous drum mode. Physical key state is read only. */
static u8 kit_shortcut_pending,kit_shortcut_chord;
/* Between the two REC presses the stock SG has an imprint armed: its keyboard
 * flag (0x80591c48) is off and pads pick the destination. Switching machines
 * there would stop every voice and move the VALUE cursor under that pending
 * state, so both shortcuts do nothing until the imprint finishes or cancels. */
static int kit_imprint_armed(int current){
    return current==0x1e && !*(volatile u8*)0x80591C48u;
}
/* Hot resample (stock: RESAMPLE, pick a pad, SHIFT + RECORD SETTING opens the
 * SG page; the first SG note starts the take). Recorder state 0x82e0e755:
 * 0 idle, 1 armed, 2 recording, 3 armed for sequencer START. */
#define KIT_REC_STATE (*(volatile u8*)0x82E0E755u)
#define KIT_PAGE_REQUEST ((void(*)(int))0x800DA599u)
/* A release whose press a hot-resample rule already handled: bit 1 PATTERN
 * EDIT, bit 2 RECORD SETTING. Cleared by that key's next press or release. */
static u8 kit_shortcut_swallow;
/* The stock RESAMPLE key handler (0x8012d6e0) opens the SG page on SHIFT +
 * RECORD SETTING while the recorder is not idle, or while idle with a
 * destination pad chosen (settings 0x1a; standby not yet started). */
static int kit_resample_armed(void){
    return KIT_REC_STATE!=0 || KIT_SETTING_GET(KIT_SETTINGS,0x1a,0)!=-1;
}
/* While settings 0x36 is 1 (resample), the stock SG key handler (0x8015c738)
 * starts the take on PATTERN EDIT or RECORD SETTING in state 1 and stops it in
 * state 2, without looking at SHIFT. */
static int kit_hot_resample_live(void){
    int state=KIT_REC_STATE;
    return (state==1||state==2) && KIT_SETTING_GET(KIT_SETTINGS,0x36,0)==1;
}
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
    if(kit_imprint_armed(current)){kit_shortcut_pending=0;kit_shortcut_chord=(u8)chord;return;}
    if(chord && chord!=kit_shortcut_chord){
        kit_shortcut_pending=(u8)chord;
        if(chord==2)kit_shortcut_select(0);
    }
    kit_shortcut_chord=(u8)chord;
}
/* Key presses (event type 5). RESAMPLE page, take armed or recording: SHIFT +
 * PATTERN EDIT opens the SG page with the last kit, the kit twin of the stock
 * SHIFT + RECORD SETTING jump; that stock chord keeps the current machine
 * instead of selecting melodic on arrival. SG page during a hot resample: the
 * native press of a SHIFT chord is swallowed so it neither starts nor stops
 * the take; its release switches machines as usual. 1 = handled. */
static int kit_shortcut_press(int current,int intent){
    u8 bit=(u8)intent;
    kit_shortcut_swallow&=(u8)~bit;
    if(current==0xe){
        if(!kit_key_down(42)||!kit_resample_armed())return 0;
        kit_shortcut_swallow|=bit;kit_shortcut_pending=0;kit_shortcut_chord=(u8)intent;
        if(intent==2){++kit_shortcut_trace[4];return 0;}   /* stock jump to the SG page */
        kit_shortcut_select(1);
        ++kit_shortcut_trace[6];
        KIT_PAGE_REQUEST(0x1e);
        return 1;
    }
    if(current==0x1e && kit_hot_resample_live() && kit_key_down(42)){++kit_shortcut_trace[5];return 1;}
    return 0;
}
EXPORT int kit_shortcut_event(void *page,const u16 *event){
    (void)page;int type=event[0],key=event[1];
    if((type!=5&&type!=6)||(key!=21&&key!=22))return 0;
    int current=*(volatile signed short*)0x80245880u;
    int intent=key==21?1:2;
    if(type==5)return kit_shortcut_press(current,intent);
    if(kit_shortcut_swallow&intent){
        kit_shortcut_swallow&=(u8)~intent;kit_shortcut_pending=0;
        return 1;
    }
    int selected=kit_shortcut_pending==intent || kit_key_down(42);
    if(current!=1&&current!=0x22&&current!=0x13&&current!=0x1e)return 0;
    if(!selected)return 0;
    if(kit_imprint_armed(current)){kit_shortcut_pending=0;kit_shortcut_chord=0;return 1;}
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
