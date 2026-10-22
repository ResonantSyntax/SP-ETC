/* SUB PAD on the Sound Generator page (hardware test build): the last pad played, again, in melodic and drum
 * mode. A stage on Sound Generator + Kits v9.46 (SG_SUBPAD.md).
 *
 * In v9.46, SUB PAD on the Sound Generator page has a job of its own. The page's pad press (0x8015bf90) sends
 * pad event 0x13 to 0x8015bfac. There a press stops every voice if one sounds (the fork's poly hook), else it
 * toggles the generator's tone. Its release (0x8015c4b0) ignores SUB PAD.
 *
 * Here SUB PAD plays the last pad played on the page: a press of that pad at SUB PAD's velocity, and its
 * release lets that pad go. The page's own pad press and release run, so the note, the scale, FIXED VELOCITY,
 * the arpeggiator, drum mode, REC and the first-hit start all work as for that pad.
 *
 * Two words of the page's vtable (0x802295a8) change (build_sg_subpad.py):
 *   +0xfc  pad press   (page, pad, velocity)  0x8015bf91 -> sp_press
 *   +0x100 pad release (page, pad, velocity)  0x8015c4b1 -> sp_release
 *
 * The last pad is the last of pads 1-16 pressed on the page without SHIFT; SHIFT + pad plays nothing there. MIDI
 * notes and the arpeggiator's steps don't count. Before any pad, SUB PAD does nothing. SHIFT + SUB PAD stays
 * stock: nothing. */
typedef unsigned int u32;
typedef unsigned char u8;

#define EXPORT __attribute__((used))

/* stock 5.52 (unchanged in DOOM OS ED5E and v9.46; the builder checks the bytes) */
#define KEYS ((const volatile u8 *)0x80592448u)   /* held keys: the UI dispatcher sets and clears them */
#define KEY_SHIFT 0x2A
#define SUB_PAD 0x13                               /* SUB PAD's pad event */
typedef int (*pad_fn)(void *page, int pad, int velocity);
#define PRESS ((pad_fn)0x8015BF91u)               /* the page's pad press, vtable +0xfc */
#define RELEASE ((pad_fn)0x8015C4B1u)             /* its pad release, vtable +0x100 */

EXPORT u8 sp_last;      /* the last pad played on the page, plus 1 (0: none since power-on) */
EXPORT u8 sp_held;      /* the pad SUB PAD is playing, plus 1 (0: none) */
EXPORT u32 sp_plays;    /* SUB PAD presses that played a pad (the tests read it) */

static int shift_down(void) {
    return KEYS[KEY_SHIFT >> 3] >> (KEY_SHIFT & 7) & 1;
}

EXPORT int sp_press(void *page, int pad, int velocity) {
    if (pad == SUB_PAD && !shift_down()) {
        if (!sp_last)
            return 0;
        sp_held = sp_last;
        sp_plays++;
        return PRESS(page, sp_last - 1, velocity);
    }
    if ((u32)pad < 16 && !shift_down())
        sp_last = (u8)(pad + 1);
    return PRESS(page, pad, velocity);
}

EXPORT int sp_release(void *page, int pad, int velocity) {
    if (pad == SUB_PAD && sp_held) {
        int held = sp_held - 1;
        sp_held = 0;
        return RELEASE(page, held, velocity);
    }
    return RELEASE(page, pad, velocity);
}
