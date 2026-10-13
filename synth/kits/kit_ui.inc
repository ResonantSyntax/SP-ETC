/* SG-page-only kit controls. Included after kit_item_* under KIT_IN_ARP.
 * See ui_v934/UI_HOOKS.md for the stock ABI and exact-byte patch guards.
 * The normal VALUE menu is retained. SHIFT shows Sweep/Noise/Attack;
 * modal page handling and KIT OFF delegate to the original SG callback.
 */
#define KIT_UI_SMALL __attribute__((noinline, minsize))
#ifndef KIT_UI_FN
#define KIT_UI_FN(type, address) ((type)(address))
#endif
typedef void (*kit_ui_one_fn)(void *);
typedef int (*kit_ui_knob_fn)(void *, int, int);
typedef int (*kit_ui_modal_fn)(void *);
typedef void (*kit_ui_color_fn)(void *, int, int);
typedef void (*kit_ui_rect_fn)(void *, const int *);
typedef void (*kit_ui_text_fn)(void *, int, int, const char *);

static int kit_key_down(int key);
extern u8 kit_ui_shift;
static void kit_shortcut_observe(void);
EXPORT u32 kit_menu_cursor;
static u8 kit_ui_shift_down,kit_ui_shift_used;
EXPORT int kit_ui_key_query(int key,u32 caller){
    unsigned k=(u16)key;
    if(k>84)return 0;
    kit_shortcut_observe();
    if(k==42 && (caller==0x8015ce3bu||caller==0x8015ce4bu||caller==0x8015ce5bu))return kit_ui_shift;
    return (((volatile u8*)0x80592448u)[k>>3]>>(k&7))&1;
}
__attribute__((naked,used)) EXPORT void kit_ui_key_gate(void){
    __asm__ volatile("mov r1,lr\nb kit_ui_key_query\n");
}
/* VALUE pressed outside edit mode (stock 0x8015cb34, r0 = keyboard state):
 * BPM (item 10) is a readout, so pressing on it never enters edit mode. Every
 * other item sets the stock edit flag (+0x14) as before. */
EXPORT int kit_value_edit_allowed(void){
    return KIT_SETTING_GET(KIT_SETTINGS,0x83,0)!=10;
}
__attribute__((naked,used)) EXPORT void kit_value_push_gate(void){
    __asm__ volatile(
        "push {r0,lr}\nbl kit_value_edit_allowed\npop {r1,lr}\n"
        "cbz r0,1f\nmovs r0,#1\nstr r0,[r1,#0x14]\n"
        "1: movs r0,#1\nadd sp,#0x14\npop {r4,r5,r6,r7,pc}\n");
}
static u32 kit_ui_revision, kit_ui_drawn_revision;
static void kit_ui_invalidate(void) { ++kit_ui_revision; }

EXPORT KIT_UI_SMALL int kit_ui_knob(void *page, int knob, int raw) {
    if (!kit_mode || (u32)(knob - 1) > 2 ||
        KIT_UI_FN(kit_ui_modal_fn, 0x800CE421u)(page))
        return KIT_UI_FN(kit_ui_knob_fn, 0x8015CE09u)(page, knob, raw);
    kit_pad *p = kit_edit();
    raw = raw < 0 ? 0 : raw > 127 ? 127 : raw;
    /* Match stock inclusive-range /128 ADC bins; every setting is reachable. */
    if(kit_ui_shift){
        u8 *v=knob==1?&p->sweep:knob==2?&p->noise:&p->attack;
        *v=(u8)((raw*101)>>7);
    } else if (knob == 1) p->tune = (signed char)(-12 + ((raw * 25) >> 7));
    else if (knob == 2) p->decay = (u8)(((raw * 101) >> 7));
    else p->tone = (signed char)(((raw * 101) >> 7));
    kit_edit_changed = 1;
    kit_ui_invalidate();
    return 1;
}

EXPORT KIT_UI_SMALL void kit_ui_poll(void *page) {
    int physical=kit_key_down(42)!=0;
    if(physical&&!kit_ui_shift_down){kit_ui_shift_down=1;kit_ui_shift_used=0;}
    if(!physical&&kit_ui_shift_down){
        kit_ui_shift_down=0;
        if(!kit_ui_shift_used){kit_ui_shift^=1;kit_ui_invalidate();}
        kit_ui_shift_used=0;
    }
    KIT_UI_FN(kit_ui_one_fn, 0x8015BF19u)(page);
    int cur=KIT_SETTING_GET(KIT_SETTINGS,0x83,0);
    int valid=kit_mode?((cur>=6&&cur<=13)||cur==17):(cur>=0&&cur<=10);
    if(!valid){int next=kit_mode?11:0;KIT_SETTING_STEP(KIT_SETTINGS,0x83,next-cur,0,0);cur=next;}
    kit_menu_cursor=(u32)cur;
    if (kit_ui_drawn_revision != kit_ui_revision) {
        kit_ui_drawn_revision = kit_ui_revision;
        /* Current page children, never cached heap-widget pointers. */
        void **children = (void **)((u8 *)page + 0x1A6C);
        for (int i = 0; i != 3; ++i)
            if (children[i]) KIT_UI_FN(kit_ui_one_fn, 0x800D0019u)(children[i]);
    }
}

EXPORT KIT_UI_SMALL void kit_ui_draw(void *widget) {
    int *w = (int *)widget;
    int col = w[0x310 / 4] - 0x7B;
    if(col>=3 && col<=5)col-=3;
    if((u32)col<=2 && !w[0x308/4])w[0x310/4]=0x7B+col+(kit_ui_shift?3:0);
    if (!kit_mode || w[0x308 / 4] || (u32)col > 2) {
        KIT_UI_FN(kit_ui_one_fn, 0x801707C1u)(widget);
        return;
    }
    void *fb = *(void **)((u8 *)widget + 0x84);
    int x = (w[1] + w[3]) / 2, y = w[2];
    char text[16];
    KIT_UI_FN(kit_ui_color_fn, 0x800D8019u)(fb, 0xFFFFFF, 0);
    KIT_UI_FN(kit_ui_rect_fn, 0x800CE581u)(fb, w + 1);
    if (col == 0) {
        kit_item_text(11, text);
    } else if (col == 1) {
        text[0] = 'P'; kit_item_text(12, text + 1);
        if(kit_variants[kit_mode-1]&(1u<<kit_edit_pad)){int n=0;while(text[n])++n;text[n++]='+';text[n]=0;}
    } else kit_item_text(13, text);
    KIT_UI_FN(kit_ui_text_fn, 0x800D4FA1u)(fb, x, y + 1, text);
    int item=kit_ui_shift?18+col:14+col;
    kit_item_name(item, text);
    KIT_UI_FN(kit_ui_text_fn, 0x800D4FA1u)(fb, x, y + 12, text);
    kit_item_text(item, text);
    KIT_UI_FN(kit_ui_text_fn, 0x800D4FA1u)(fb, x, y + 22, text);
    if (col == 1) kit_item_text(17, text);
    else kit_copy(text, col == 0 ? "LEVEL" : "MENU");
    KIT_UI_FN(kit_ui_text_fn, 0x800D4FA1u)(fb, x, y + 32, text);
}

EXPORT KIT_UI_SMALL void kit_ui_footer_draw(void *widget){
    if(!kit_mode || *(volatile signed short*)0x80245880u!=0x1e){
        KIT_UI_FN(kit_ui_one_fn,0x80140069u)(widget);return;
    }
    int *w=(int*)widget;void *fb=*(void**)((u8*)widget+0x84);
    KIT_UI_FN(kit_ui_color_fn,0x800D8019u)(fb,0xFFFFFF,0);
    KIT_UI_FN(kit_ui_rect_fn,0x800CE581u)(fb,w+1);
    KIT_UI_FN(kit_ui_text_fn,0x800D4FA1u)(fb,(w[1]+w[3])/2,w[2]+1,"SHIFT: PAGE");
}
