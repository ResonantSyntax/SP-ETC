/* BOUNC (VALUE item 22, drum mode only): render the kit's sixteen pads, each
 * with its current Tune/Decay/Tone/Sweep/Noise/Attack/Level, into the sixteen
 * pads of one sample bank. Included last under KIT_IN_ARP.
 *
 *   Cursor on BOUNC (it shows --), press VALUE, turn to a bank A..J, press
 *   VALUE. Empty pads are filled. Pads that already hold a sample are asked
 *   about first, one at a time: the item shows the pad ("B-3") and KEEP or
 *   OVER (KEEP until VALUE is turned right); press VALUE for the next. EXIT
 *   cancels: during the questions nothing has been written, during the run
 *   the pads already written stay. REC does nothing until the bounce ends.
 *
 * The pad settings are copied when the bank is chosen, so edits during the
 * bounce do not reach it. One pad is written per Sound Generator screen
 * update (arp_poll, UI task) through the stock REC exporter (0x801327b8, the
 * v4 export engine), so each file, its header, its registration and its name
 * are exactly what a drum REC of that pad writes. Each pad plays at velocity
 * 127 with the noise seed and shared-source origin 0 REC uses for a pad not
 * struck in this kit, on a cleared export voice (so the same kit always
 * bounces the same files), and ends where it has decayed 60 dB below its own peak,
 * at most 10 s: a pre-render on the export voice finds that frame and the
 * exporter's length code (hook at 0x80132ac8) takes it instead of PAD LENGTH.
 * v9's export mix fades the last 10 ms, as on every REC. Pads whose sound is
 * off, or whose LEVEL is 0, are left out. Just before each write the bank is
 * checked again: a pad that holds a sample by then is only replaced if OVER
 * was chosen for it. */
#define KIT_BOUNCE_ITEM 22
#define KIT_BOUNCE_CAP 480000u                       /* frames: 10 s */
#define KIT_BOUNCE_FLOOR 1e-3f                       /* -60 dB of the pad's own peak */
#define KIT_BOUNCE_PAGE (*(volatile signed short *)0x80245880u)
#define KIT_BOUNCE_KB ((volatile u8 *)0x80591C48u)   /* stock keyboard: [0] on (no imprint armed) */
#define KIT_BOUNCE_EDIT (*(volatile int *)0x80591C5Cu)   /* +0x14: VALUE edit mode */
#define KIT_BOUNCE_COUNT (*(volatile u32 *)0x8353C700u)  /* export voices the v4 engine renders */
typedef int (*kit_pad_used_fn)(int abs_pad);
typedef void (*kit_export_fn)(volatile u8 *state);
#define KIT_PAD_USED ((kit_pad_used_fn)0x800D8B01u)  /* nonzero: that pad holds a sample */
#define KIT_EXPORT ((kit_export_fn)0x801327B9u)       /* stock REC exporter */
enum { KIT_BOUNCE_IDLE, KIT_BOUNCE_ASK, KIT_BOUNCE_RUN, KIT_BOUNCE_DONE, KIT_BOUNCE_STOP, KIT_BOUNCE_FAIL };

EXPORT volatile u8 kit_bounce_state;
EXPORT volatile signed char kit_bounce_bank = -1;    /* -1 = --, 0..9 = A..J */
EXPORT volatile u8 kit_bounce_mode, kit_bounce_ask, kit_bounce_next, kit_bounce_done, kit_bounce_total;
EXPORT volatile u16 kit_bounce_want;                 /* pads that sound */
EXPORT volatile u16 kit_bounce_used;                 /* of those, pads whose bank pad held a sample */
EXPORT volatile u16 kit_bounce_over;                 /* used pads to replace (OVER) */
EXPORT volatile u16 kit_bounce_write, kit_bounce_wrote;
EXPORT volatile u32 kit_bounce_frames;               /* nonzero: the exporter writes this many frames */
EXPORT volatile u32 kit_bounce_length[16];           /* frames per pad, 0 = not written */
static kit_pad kit_bounce_recipe[16];

static int kit_bounce_first(u32 mask) {
    for (int p = 0; p < 16; ++p) if (mask & (1u << p)) return p;
    return -1;
}
static int kit_bounce_cursor(void) { return KIT_SETTING_GET(KIT_SETTINGS, 0x83, 0); }

static void kit_bounce_set(int state) { kit_bounce_state = (u8)state; kit_edit_changed = 1; }

/* Item name: BOUNC, or the pad being asked about (B-3). */
static void kit_bounce_name(char *out) {
    if (kit_bounce_state != KIT_BOUNCE_ASK) { kit_copy(out, "BOUNC"); return; }
    out[0] = (char)('A' + kit_bounce_bank); out[1] = '-';
    kit_num(out + 2, kit_bounce_ask + 1, 0);
}

static void kit_bounce_text(char *out) {
    switch (kit_bounce_state) {
    case KIT_BOUNCE_ASK: kit_copy(out, kit_bounce_over & (1u << kit_bounce_ask) ? "OVER" : "KEEP"); return;
    case KIT_BOUNCE_RUN: { char *e = kit_num(out, kit_bounce_done, 0); *e++ = '/'; kit_num(e, kit_bounce_total, 0); return; }
    case KIT_BOUNCE_DONE: kit_copy(out, "DONE"); return;
    case KIT_BOUNCE_STOP: kit_copy(out, "STOP"); return;
    case KIT_BOUNCE_FAIL: kit_copy(out, "ERROR"); return;
    }
    if (kit_bounce_bank < 0) kit_copy(out, "--");
    else { out[0] = (char)('A' + kit_bounce_bank); out[1] = 0; }
}

/* VALUE turned in edit mode: the bank, or KEEP (left) / OVER (right). */
static void kit_bounce_turn(int dir) {
    if (kit_bounce_state == KIT_BOUNCE_ASK) {
        u16 bit = (u16)(1u << kit_bounce_ask);
        kit_bounce_over = (u16)(dir > 0 ? kit_bounce_over | bit : kit_bounce_over & ~bit);
        return;
    }
    if (kit_bounce_state == KIT_BOUNCE_RUN) return;
    kit_bounce_state = KIT_BOUNCE_IDLE;
    int b = kit_bounce_bank + (dir < 0 ? -1 : 1);
    kit_bounce_bank = (signed char)(b < -1 ? -1 : b > 9 ? 9 : b);
}

static void kit_bounce_run(void) {
    u16 write = (u16)(kit_bounce_want & ~(kit_bounce_used & ~kit_bounce_over));
    int n = 0;
    for (int p = 0; p < 16; ++p) n += (write >> p) & 1;
    kit_bounce_write = write; kit_bounce_total = (u8)n;
    kit_bounce_set(KIT_BOUNCE_RUN);
}

/* The bank was chosen: copy the pads and see which bank pads hold samples. */
static void kit_bounce_begin(void) {
    kit_init_pads();
    int mode = kit_mode < 1 ? 1 : kit_mode > KIT_KITS ? KIT_KITS : kit_mode;
    DISPATCH_OFF();
    for (int p = 0; p < 16; ++p) kit_bounce_recipe[p] = kit_pads[mode - 1][p];
    DISPATCH_ON();
    u16 want = 0, used = 0;
    for (int p = 0; p < 16; ++p) {
        kit_bounce_length[p] = 0;
        const kit_pad *P = &kit_bounce_recipe[p];
        if (P->sound == KIT_OFF_SOUND || !P->level) continue;
        want = (u16)(want | (1u << p));
        if (KIT_PAD_USED(kit_bounce_bank * 16 + p)) used = (u16)(used | (1u << p));
    }
    kit_bounce_mode = (u8)mode; kit_bounce_want = want; kit_bounce_used = used;
    kit_bounce_over = 0; kit_bounce_wrote = 0; kit_bounce_next = 0; kit_bounce_done = 0;
    if (used) { kit_bounce_ask = (u8)kit_bounce_first(used); kit_bounce_set(KIT_BOUNCE_ASK); }
    else kit_bounce_run();
}

/* A machine switch, leaving the page or EXIT: no more questions or writes. */
static void kit_bounce_cancel(void) {
    if (kit_bounce_state == KIT_BOUNCE_ASK) { KIT_BOUNCE_EDIT = 0; kit_bounce_bank = -1; kit_bounce_set(KIT_BOUNCE_IDLE); }
    else if (kit_bounce_state == KIT_BOUNCE_RUN) kit_bounce_set(KIT_BOUNCE_STOP);
}

/* Every page event (kit_shortcut_event, before the page sees it); 1 = consumed. */
static int kit_bounce_event(int type, int key) {
    int s = kit_bounce_state, open = s == KIT_BOUNCE_ASK || s == KIT_BOUNCE_RUN;
    if (KIT_BOUNCE_PAGE != 0x1E || !kit_mode) {
        if (open) kit_bounce_cancel();
        if (kit_bounce_state == KIT_BOUNCE_IDLE) kit_bounce_bank = -1;
        return 0;
    }
    if (type != 5) return 0;                          /* key presses */
    if (open && key == 0x22) {                        /* EXIT: cancel, stay on the page */
        kit_bounce_cancel();
        return 1;
    }
    if (open && key == 0x1B) return 1;                /* REC: no imprint during a bounce */
    if (key != 0x31 || kit_bounce_cursor() != KIT_BOUNCE_ITEM || kit_key_down(42)) return 0;
    if (!KIT_BOUNCE_EDIT) {                           /* VALUE into edit mode: always from --, */
        if (!open) { kit_bounce_bank = -1; kit_bounce_set(KIT_BOUNCE_IDLE); }   /* so a bank must be turned to */
        return 0;
    }
    if (s == KIT_BOUNCE_ASK) {                        /* answered: the next used pad, or go */
        int next = kit_bounce_first(kit_bounce_used & ~((2u << kit_bounce_ask) - 1u));
        if (next >= 0) { kit_bounce_ask = (u8)next; kit_edit_changed = 1; return 1; }
        kit_bounce_run();
        return 0;                                     /* the stock press leaves edit mode */
    }
    if (s == KIT_BOUNCE_IDLE && kit_bounce_bank >= 0 && KIT_BOUNCE_KB[0]) {
        kit_bounce_begin();
        return kit_bounce_state == KIT_BOUNCE_ASK;    /* questions keep edit mode on */
    }
    return 0;
}

/* Export voice 4 cleared. kit_start leaves some filter state from the voice's
 * previous sound (the table voices' noise filters), so without this a pad's
 * first milliseconds would depend on what was exported before it. */
static void kit_bounce_clear(void) {
    volatile u32 *w = (volatile u32 *)&kit_slot[4];
    for (u32 k = 0; k < sizeof(kit_voice) / 4; ++k) w[k] = 0;
}

/* Pre-render the pad on export voice 4 as the export will (same recipe, seed
 * and origin, same per-sample steps as kit_output_slot) and return the frames
 * up to its last sample at or above -60 dB of its own peak (0 = silent), at
 * most KIT_BOUNCE_CAP. The export starts again from a cleared voice and every
 * shared source it uses from frame 0, so this leaves nothing that changes the
 * file. */
static u32 kit_bounce_measure(int pad) {
    kit_voice *v = &kit_slot[4];
    kit_bounce_clear();
    kit_start(v, 4, pad);
    float peak = 0;
    u32 end = 0;
    for (u32 n = 0; n < KIT_BOUNCE_CAP && v->live; ++n) {
        v->source_frame = v->n + kit_export_origin[0];
        float y = kit_absf(kit_limit(kit_render_slot(v, 4)));
        if (y > peak) peak = y;
        if (y > 0 && y >= peak * KIT_BOUNCE_FLOOR) end = n + 1;
    }
    v->live = 0;
    return end;
}

/* One pad through the stock exporter, as a drum REC of that pad when it was
 * not struck in this kit: 1 written, 0 left out (silent, or the bank pad holds
 * a sample that is not to be replaced), -1 the exporter wrote no file. */
static int kit_bounce_pad(int p) {
    int abs = kit_bounce_bank * 16 + p;
    if (!(kit_bounce_over & (1u << p)) && KIT_PAD_USED(abs)) return 0;
    volatile u32 *v0 = (volatile u32 *)KIT_SINGLETON, *to = (volatile u32 *)KIT_EXPORT_BASE;
    DISPATCH_OFF();
    for (int w = 0; w < 108; ++w) to[w] = v0[w];
    kit_export_recipe[0] = kit_bounce_recipe[p];
    kit_export_mode = kit_bounce_mode; kit_export_bd_ready = 0; kit_export_bd_slot = 0;
    kit_export_origin[0] = 0; kit_export_seed[0] = 0x9E3779B9u ^ ((u32)p * 0xC2B2AE35u);
    kit_export_delay[0] = 0; kit_export_frame[0] = 0;
    to[0x1ac/4] = (u32)p;
    to[0x10/4] = 0;                                   /* the drum's own envelope */
    ((volatile u8 *)to)[4] = 0;                       /* one-shot */
    to[0x198/4] = 127 * 100u;                         /* velocity 127 */
    to[0x74/4] = to[0x198/4];
    for (int i = 4; i < 8; ++i) kit_slot[i].live = 0;
    kit_export_count = 1; kit_export_active = 1;
    KIT_BOUNCE_COUNT = 1;                             /* the engine renders this voice, no capture */
    DISPATCH_ON();
    u32 frames = kit_bounce_measure(p);
    kit_bounce_length[p] = frames;
    kit_bounce_clear();
    if (!frames) { KIT_BOUNCE_COUNT = 0; return 0; }
    v0[0x17c/4] = (u32)abs;                           /* REC's destination: bank * 16 + pad */
    kit_bounce_frames = frames;
    KIT_EXPORT((volatile u8 *)KIT_SINGLETON);
    kit_bounce_frames = 0;
    *(volatile u16 *)0x802496F0u = 0xFFFF;            /* the redraw stock REC requests */
    if (v0[0x17c/4] != 0xFFFFFFFFu) {                 /* not written: the exporter keeps the target */
        v0[0x17c/4] = 0xFFFFFFFFu;
        kit_bounce_length[p] = 0;
        return -1;
    }
    return 1;
}

/* SG screen update (arp_poll, UI task): one pad per update. A screen update
 * that came in while a pad is being written (if a storage call ever ran the
 * UI) does nothing. */
static u8 kit_bounce_busy;
static void kit_bounce_step(void) {
    int s = kit_bounce_state;
    if (s != KIT_BOUNCE_ASK && s != KIT_BOUNCE_RUN) return;
    if (kit_bounce_busy) return;
    if (KIT_BOUNCE_PAGE != 0x1E || kit_mode != kit_bounce_mode) { kit_bounce_cancel(); return; }
    if (s == KIT_BOUNCE_ASK) {                        /* edit mode left some other way */
        if (kit_bounce_cursor() != KIT_BOUNCE_ITEM || !KIT_BOUNCE_EDIT) kit_bounce_cancel();
        return;
    }
    if (!KIT_BOUNCE_KB[0]) return;                    /* an imprint is armed: wait */
    int p = kit_bounce_first(kit_bounce_write & ~((1u << kit_bounce_next) - 1u));
    if (p < 0) { kit_bounce_set(KIT_BOUNCE_DONE); return; }
    kit_bounce_next = (u8)(p + 1);
    kit_bounce_busy = 1;
    int r = kit_bounce_pad(p);
    kit_bounce_busy = 0;
    if (r < 0) { kit_bounce_set(KIT_BOUNCE_FAIL); return; }
    if (r) kit_bounce_wrote = (u16)(kit_bounce_wrote | (1u << p));
    ++kit_bounce_done;
    if (kit_bounce_state != KIT_BOUNCE_RUN) { kit_edit_changed = 1; return; }   /* cancelled meanwhile */
    kit_bounce_set(kit_bounce_first(kit_bounce_write & ~((1u << kit_bounce_next) - 1u)) < 0 ?
                   KIT_BOUNCE_DONE : KIT_BOUNCE_RUN);
}

/* Stock exporter, 0x80132ac8 (mov r4, r8; cmp.w fp, #1; mov.w r0, #0): fp
 * holds the frame count and [sp, #4] the loop's frame limit, both just
 * computed from PAD LENGTH. While a bounce writes, both become its length.
 * The displaced instructions follow; the flags of their cmp reach the stock
 * blt.w at 0x80132ad6 after its str (which leaves them alone). */
__attribute__((naked, used)) EXPORT void kit_bounce_length_gate(void) {
    __asm__ volatile(
        "movw r12, #:lower16:kit_bounce_frames\n\tmovt r12, #:upper16:kit_bounce_frames\n\t"
        "ldr r12, [r12]\n\tcmp r12, #0\n\tbeq 1f\n\t"
        "mov r11, r12\n\tstr r12, [sp, #4]\n"
        "1:\n\tmov r4, r8\n\tcmp.w r11, #1\n\tmov.w r0, #0\n\t"
        "movw r12, #0x2ad3\n\tmovt r12, #0x8013\n\tbx r12\n");                 /* 0x80132ad2 */
}
