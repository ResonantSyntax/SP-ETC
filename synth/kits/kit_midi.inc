/* External MIDI for the Sound Generator (Kits build). Included last under
 * KIT_IN_ARP; build_arp_kit.py routes the stock note dispatcher here behind
 * exact-instruction guards.
 *
 * M.CH (VALUE item 21, 1..16, default 16) is the channel the SG plays while
 * its page is open. Stock sends notes to the SG only on channel 16, which is
 * otherwise the SP's control channel: notes 12..19 and 24..31 run functions
 * (0x80066d24) and, off the SG page, notes reach the stock handler 0x8005a680,
 * whose non-SG half is the chromatic pad (notes 36..60). Only the SG routing
 * follows M.CH. With M.CH 16 every path is stock. With another channel,
 * channel 16 is the control channel on every page and never plays the SG; on
 * the SG page its other note-ons do nothing and its note-offs still reach the
 * chromatic half, as stock does there. The chosen channel plays the SG on its
 * page and keeps its stock pad routing elsewhere.
 *
 * Drum mode: notes 36..51 play pads 1..16 (the 4x4 layout, GM kick on pad 1)
 * exactly as struck pads, ARP on or off; other notes do nothing.
 *
 * CCs on M.CH while the SG page is open (0x80066174, then on to the stock CC
 * queue unchanged; the chart avoids every CC the SP uses):
 *   drum     pad n Tune/Decay/Level: pads 1-4 CC 20-31, 5-12 CC 40-63,
 *            13-16 CC 102-113 (three each); last pad heard Tone 114,
 *            Sweep 115, Noise 116, Attack 117. Applied at once (a CC just
 *            before a note shapes that hit) and the pad is selected on screen.
 *   melodic  TYPE 70, FREQ 71, LEVEL 72, DUTY 73, BALANCE 74, ENV 75, TUNE 76,
 *            set on the next screen update through the knobs' own setter.
 *   arp      ARP 33, RATE 34, A.OCT 35 (melodic only), HOLD 36, both modes,
 *            stepped on the next screen update like the VALUE menu.
 *   123      All Notes Off: let go of every note MIDI holds; the arp stops.
 *   120      All Sound Off: the same, then the SG all-stop (every voice
 *            fades out at once, as switching ARP on does). */
#define KIT_MIDI_PAGE (*(volatile signed short *)0x80245880u)
#define KIT_MIDI_SG 0x1E
typedef int (*kit_pad_note_fn)(int pad);
#define KIT_PAD_NOTE ((kit_pad_note_fn)(KIT_PAD_NOTE_ADDR | 1u))   /* v9.6's pad note (OCT, OFST, scale) */

/* M.CH changed (VALUE menu, UI task): notes held on the old channel would
 * never get their note-offs, so stop the voices and forget the arp's held
 * notes, as switching ARP on does. */
static void kit_midi_channel_changed(void) {
    RELEASE_ALL();
    DISPATCH_OFF();
    held_count = 0;
    down_count = 0;
    DISPATCH_ON();
}

/* Note-on, 0x80066d18: does this channel run the control-channel functions? */
EXPORT int kit_midi_control(int ch) {
    if (ch != 15) return 0;
    return !(KIT_MIDI_PAGE == KIT_MIDI_SG && (kit_midi_channel & 15) == 15);
}

/* Note-on/off, 0x80066e64 / 0x800670b8: 0 the stock pad path, 1 the stock
 * channel-16 handler 0x8005a680, 2 the Sound Generator, 3 the SG page without
 * the SG (stock's SG-page path for channel 16 minus the SG call). */
EXPORT int kit_midi_route(int ch) {
    int n = kit_midi_channel & 15, sg = KIT_MIDI_PAGE == KIT_MIDI_SG;
    if (n == 15) return ch == 15;
    if (ch == n) return sg ? 2 : 0;
    if (ch == 15) return sg ? 3 : 1;
    return 0;
}

/* r0 = channel, r4 = message; the dispatcher's own frame is live. */
__attribute__((naked, used)) EXPORT void kit_midi_control_gate(void) {
    __asm__ volatile(
        "bl kit_midi_control\n\t"
        "cbz r0, 1f\n\t"
        "movw r12, #0x6d25\n\tmovt r12, #0x8006\n\tbx r12\n"          /* functions: 0x80066d24 */
        "1:\n\tmovw r12, #0x6d51\n\tmovt r12, #0x8006\n\tbx r12\n");  /* notes: 0x80066d50 */
}

/* r0 = the pad lookup, r4 = message, r5 = channel. r6 is free: the pad path
 * sets it from r0 and every other exit pops it. */
__attribute__((naked, used)) EXPORT void kit_midi_on_gate(void) {
    __asm__ volatile(
        "mov r6, r0\n\tmov r0, r5\n\tbl kit_midi_route\n\t"
        "cmp r0, #1\n\tbeq 1f\n\tcmp r0, #2\n\tbeq 2f\n\tcmp r0, #3\n\tbeq 3f\n\t"
        "mov r0, r6\n\tmovw r12, #0x6e79\n\tmovt r12, #0x8006\n\tbx r12\n"   /* pad path: 0x80066e78 */
        "1:\n\tldrb r0, [r4, #2]\n\tmovs r2, #0\n\tldrb r1, [r4, #3]\n\t"
        "movw r12, #0x6e6f\n\tmovt r12, #0x8006\n\tbx r12\n"                  /* stock tail to 0x8005a680 */
        "2:\n\tldrb r1, [r4, #2]\n\tldrb r2, [r4, #3]\n\tmovs r3, #0\n\t"
        "add sp, #4\n\tpop.w {r4, r5, r6, r7, lr}\n\tb.w arp_midi_event\n"   /* the SG */
        "3:\n\tadd sp, #4\n\tpop {r4, r5, r6, r7, pc}\n");                      /* nothing */
}

__attribute__((naked, used)) EXPORT void kit_midi_off_gate(void) {
    __asm__ volatile(
        "mov r6, r0\n\tmov r0, r5\n\tbl kit_midi_route\n\t"
        "cmp r0, #1\n\tbeq 1f\n\tcmp r0, #2\n\tbeq 2f\n\tcmp r0, #3\n\tbeq 3f\n\t"
        "mov r0, r6\n\tmovw r12, #0x70cd\n\tmovt r12, #0x8006\n\tbx r12\n"   /* pad path: 0x800670cc */
        "1:\n\tldrb r0, [r4, #2]\n\tmovs r1, #0\n\tmovs r2, #1\n\t"
        "movw r12, #0x70c3\n\tmovt r12, #0x8006\n\tbx r12\n"                  /* stock tail to 0x8005a680 */
        "2:\n\tldrb r1, [r4, #2]\n\tmovs r2, #0\n\tmovs r3, #1\n\t"
        "add sp, #4\n\tpop.w {r4, r5, r6, r7, lr}\n\tb.w arp_midi_event\n"   /* the SG */
        /* 0x8005a680 entered as stock does on the SG page, past its SG call:
         * its own frame, r4 note, r5 velocity, r6 = 1 (note-off), then the
         * chromatic note-off at 0x8005a6a6. */
        "3:\n\tldrb r0, [r4, #2]\n\tmovs r1, #0\n\tmovs r2, #1\n\t"
        "add sp, #4\n\tpop.w {r4, r5, r6, r7, lr}\n\t"
        "push {r4, r5, r6, r7, lr}\n\tsub sp, #0x14\n\tmov r6, r2\n\tmov r5, r1\n\tmov r4, r0\n\t"
        "movw r12, #0xa6a7\n\tmovt r12, #0x8005\n\tbx r12\n");
}

/* Drum mode (from arp_midi_event): notes 36..51 strike pads 1..16 through the
 * pad path, with the pad as the source and the pad's own note, so the voice,
 * its light, REC, PAD and the arp's held list treat it as that pad. A pad whose
 * note an extreme OCT/OFST carried over from melodic mode puts outside the
 * playable range takes the MIDI pitch instead, so the hit still sounds. Other
 * notes do nothing, as on a drum machine. */
EXPORT volatile u16 kit_midi_down;              /* pads MIDI holds (bit = pad), for CC 123 */
static void kit_midi_drum(u32 self, int note, int vel, int r3) {
    int pad = note - 36;
    if ((u32)pad > 15) return;
    int n = KIT_PAD_NOTE(pad);
    if ((u32)(n + 36) > 84) n = note - 48;
    if (vel) { kit_strike(pad, vel); kit_midi_down = (u16)(kit_midi_down | (1u << pad)); }
    else kit_midi_down = (u16)(kit_midi_down & ~(1u << pad));
    arp_note_event_body(self, n, vel, r3, pad);
}

/* ---- CCs ---- */
#define KIT_SETTING_RANGE ((void (*)(u32, int, int *, int *, int))0x800C1781u)   /* (min, max) */
#define KIT_SETTING_SET ((void (*)(u32, int, int, int))0x800DD0C1u)
void arp_item_step(int item, int dir);

/* Drum CCs, applied at once in the MIDI task: one byte per parameter, as the
 * knobs write them (kit_ui_knob), so a hit that starts next reads it. */
static int kit_cc_drum(int cc, int v) {
    int t = cc >= 20 && cc <= 31 ? cc - 20 : cc >= 40 && cc <= 63 ? cc - 28 :
            cc >= 102 && cc <= 113 ? cc - 66 : -1, pad, field;
    if (t >= 0) { pad = t / 3; field = t % 3; }          /* Tune, Decay, Level */
    else if (cc >= 114 && cc <= 117) { pad = kit_last_hit & 15; field = 3 + cc - 114; }
    else return 0;
    kit_init_pads();
    kit_pad *p = &kit_pads[(kit_mode > KIT_KITS ? KIT_KITS : kit_mode) - 1][pad];
    u8 percent = (u8)((v * 101) >> 7);                   /* CC 64 = 50 %, the authentic setting */
    switch (field) {
    case 0: p->tune = (signed char)(-12 + ((v * 25) >> 7)); break;
    case 1: p->decay = percent; break;
    case 2: p->level = (u8)v; break;
    case 3: p->tone = (signed char)percent; break;
    case 4: p->sweep = percent; break;
    case 5: p->noise = percent; break;
    default: p->attack = percent; break;
    }
    kit_edit_pad = (u8)pad;                              /* the screen shows the pad it changed */
    kit_edit_changed = 1;
    return 1;
}

/* Melodic (0..6: TYPE FREQ LEVEL DUTY BALANCE ENV TUNE) and arp (7..10: ARP
 * RATE A.OCT HOLD) CCs wait for the UI task: the MIDI task stores the value
 * and bumps a sequence number, the screen update applies the newest value. */
#define KIT_CC_QUEUE 11
static volatile u8 kit_cc_value[KIT_CC_QUEUE];
static volatile u32 kit_cc_sequence[KIT_CC_QUEUE];
static u32 kit_cc_applied[KIT_CC_QUEUE];
static const u8 kit_cc_setting[7] = {0x7B, 0x7C, 0x7D, 0x7F, 0x80, 0x82, 0x81};

/* SG screen update (UI task, from arp_poll): the knobs' own range and setter,
 * min + (max - min + 1) * CC / 128 as at 0x8015ce62, and the VALUE menu's own
 * steps for the arp. */
static void kit_cc_apply(void) {
    for (int q = 0; q < KIT_CC_QUEUE; ++q) {
        u32 s = kit_cc_sequence[q];
        if (s == kit_cc_applied[q]) continue;
        kit_cc_applied[q] = s;
        int v = kit_cc_value[q];
        if (q < 7) {
            int lo = 0, hi = 0, id = kit_cc_setting[q];
            KIT_SETTING_RANGE(KIT_SETTINGS, id, &lo, &hi, 0);
            KIT_SETTING_SET(KIT_SETTINGS, id, lo + (((hi - lo + 1) * v) >> 7), 0);
        } else {
            int item = q - 1;                                /* 6 ARP, 7 RATE, 8 A.OCT, 9 HOLD */
            int target = item == 9 ? v >= 64 : item == 8 ? ((7 * v) >> 7) - 3 : (7 * v) >> 7;
            for (int k = 0; k < 8; ++k) {
                int cur = item == 6 ? arp_mode : item == 7 ? arp_rate : item == 8 ? arp_oct : arp_hold;
                if (cur == target) break;
                arp_item_step(item, target > cur ? 1 : -1);
            }
        }
        arp_dirty = 1;
    }
}

/* CC 123 / 120 (MIDI task): let go of every note MIDI holds and stop the arp;
 * 120 then fades every SG voice out at once. */
static void kit_midi_all_off(int sound_off) {
    if (kit_mode) {
        u16 down = kit_midi_down;
        for (int p = 0; p < 16; ++p)
            if (down & (1u << p)) kit_midi_drum(0, 36 + p, 0, 1);
    } else if (!arp_mode) {
        for (int i = 0; i < NV; ++i) {
            volatile u8 *v = voice(i);
            if (v[0] && !v[1] && v[0x194] != 0xFF) MIDI_EVENT(0, v[0x194], 0, 1);
        }
    }
    kit_midi_down = 0;
    DISPATCH_OFF();
    held_count = 0;
    down_count = 0;
    DISPATCH_ON();
    if (sound_off) RELEASE_ALL();
}

/* Every CC (stock handler 0x80066130, the MIDI task), before the stock queue. */
EXPORT void kit_midi_cc(const u8 *msg) {
    int ch = msg[1] & 15, cc = msg[2] & 127, v = msg[3] & 127;
    if (ch != (kit_midi_channel & 15) || KIT_MIDI_PAGE != KIT_MIDI_SG) return;
    if (cc == 123 || cc == 120) { kit_midi_all_off(cc == 120); return; }
    if (kit_mode && kit_cc_drum(cc, v)) return;
    int q = cc >= 70 && cc <= 76 && !kit_mode ? cc - 70 : cc >= 33 && cc <= 36 ? cc - 26 : -1;
    if (q < 0 || (q == 9 && kit_mode)) return;          /* A.OCT is melodic only */
    kit_cc_value[q] = (u8)v;
    kit_cc_sequence[q] = kit_cc_sequence[q] + 1;
}

/* r1 = status, r4 = message: the stock queue write below needs both. */
__attribute__((naked, used)) EXPORT void kit_midi_cc_gate(void) {
    __asm__ volatile(
        "push {r1, r4}\n\tmov r0, r4\n\tbl kit_midi_cc\n\tpop {r1, r4}\n\t"
        "movw r0, #0xd96c\n\tldrh r3, [r4, #2]\n\tmovt r0, #0x80d3\n\t"        /* the displaced instructions */
        "movw r12, #0x617f\n\tmovt r12, #0x8006\n\tbx r12\n");                 /* 0x8006617e */
}
