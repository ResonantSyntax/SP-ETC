/* Note repeat (test build): ROLL as an MPC-style note repeat, on the published v9.46.
 *
 * Stock 5.52 rolls by capturing the first slice of the pad's voice into a ring and looping it (the
 * renderer, 0x14b88 / 0x8001c2c8); VALUE only halves or doubles that loop at the end of a pass. Here a
 * roll re-hits the pad through the stock pad note (0x800cdbd0) at the pad's Roll division (pad parameter
 * 0x7b, the list SHIFT + ROLL steps through), at the tempo BPM-synced samples on the pad follow
 * (0x80047dd0). Every repeat is a real pad note: it plays the whole sample, and the stock pattern
 * recorder records it like a tap.
 *
 *   ROLL + pad          the pad repeats until ROLL is released (as stock: letting go of the pad first
 *                       doesn't stop it); pads already held when ROLL goes down start at once
 *   tap ROLL            latch (a press with nothing else touched): pads repeat while they are held; tap
 *                       again to unlatch. ROLL is lit while latched
 *   turn VALUE          while ROLL is held, or while latched and a pad repeats: the next or previous
 *                       division for every repeating pad (or for the current pad if none), at once, along
 *                       stock's ten and six triplets (1/2T .. 1/64T); the popup names it ("Roll 1/16T").
 *                       It is kept with the pad: Roll gets it, or a triplet's nearest stock division (what
 *                       stock rolls and SHIFT + ROLL show), and the triplet goes in PADCONF byte 0x70, bits
 *                       1-3, counted only while Roll still holds that neighbour
 *   ROLL + VALUE press  the current pad follows ROLL or ignores it (saved with the pad: PADCONF reserved
 *                       byte 0x70, bit 0 set = ignores; zero, the default, follows)
 *   HOLD while rolling  held rolls: every roll going on keeps going until its pad is hit again (a press the
 *                       page plays, or stock's HOLD lets the pad go on), HOLD is pressed again with no pad
 *                       down, or EXIT + ROLL; ROLL let go, tapped or unlatched and other pads leave it alone.
 *                       Its pad blinks (in the pad's bank, outside DOOM OS) and HOLD is lit. HOLD with
 *                       nothing rolling, and SHIFT + HOLD, are stock's
 *   EXIT + pad          (test6) that pad's rolls stop, held ones too (stock's EXIT + pad stops its sound): the
 *                       rolls that pad started, or of the pad it plays in this bank; the others go on
 *   chromatic mode     (test4) the pads play notes of one sample, so a chromatic roll takes only its division
 *                       from the pad under the finger: each pad has its own chromatic division (1/16 until
 *                       VALUE moves it, kept with the pad: PADCONF byte 0x70, bits 4-7) and repeats at the
 *                       tempo the sample's pad follows, always by re-hitting. The pad's Roll, LOOP, GATE and
 *                       follow flag are not read or written. VALUE steps the chromatic pads repeating; with
 *                       none, ROLL + VALUE steps the last chromatic pad played (ROLL + VALUE press shows
 *                       its division). With ROLL latched and VALUE held, a turn is the page's (its scale or
 *                       key)
 *
 * Each repeat is a note-off then a note-on at the press's velocity, at the last repeat + one division
 * (288000000 x beats / BPMx100 frames, the remainder carried) on the audio clock, sent at the first UI
 * tick (every millisecond, from the UI task, like a pad press) at or after that time; the UI task being
 * late or bunching its ticks delays a repeat but never moves the next. A new division or tempo applies
 * at once. A LOOP pad without GATE toggles off when hit again, so it keeps the
 * stock ring roll: the module asks for it (0x800163a8, what 0x91 does) once the pad sounds and stops it as
 * stock does. SHIFT + ROLL (the division popup), EXIT + ROLL (all rolls off) and patterns' own rolls stay
 * stock. While DJ Mixer Mode is on everything is stock. On the screens where ROLL is the screen's own (test6:
 * START/END, page 5, where ROLL held previews the sample's end; PITCH/SPEED, page 4, where ROLL opens and closes
 * Groove) the module steps aside (rolls stop, ROLL shows stock's light) and keeps a latch for afterwards; a ROLL
 * press from before the screen opened stays the module's until it is let go. (Test5 had page 0x16 for START/END:
 * it is a recording screen, and the START/END screen never matched.)
 *
 * Bridges (build_note_repeat.py writes a 10-byte movw/movt/bx ip at each entry):
 *   0x8003b530 UI dispatcher   -> nr_event: pads and SUB PAD down/up (whatever the page), ROLL down/up,
 *                                 HOLD down, VALUE turns and VALUE + ROLL; the rest goes on
 *   0x800cdbd0 stock pad note  -> nr_pad: which pad a page plays for the pad event; then the stock body
 *   0x8003c5f0 UI tick (1 ms)  -> nr_tick: the repeats, the lights, the save
 *   0x80135d40 ROLL let go     -> nr_release: stock's release handling only while the module is off
 *   0x800d9f20 key held?       -> nr_key_gate: "ROLL held" is no for the note-on's three roll starts
 *                                 (0x800aec48) while the module runs; everything else goes on to the
 *                                 kits' query gate, as before
 */
typedef unsigned int u32;
typedef int s32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define EXPORT __attribute__((used))

#ifndef KIT_KEY_GATE
#error "build_note_repeat.py passes the kits' key-query gate address"
#endif

/* stock 5.52 (unchanged in DOOM OS ED5E and v9.46; the builder checks the bytes) */
#define KEYS ((const volatile u8 *)0x80592448u)            /* held keys: the UI dispatcher sets them */
#define POPUP ((void (*)(const char *, s32))0x800D3FF1u)    /* popup(text, ms) */
#define POPUP_TIME ((s32 (*)(s32))0x800D4029u)             /* the time stock's popups stay */
#define LED ((void (*)(s32, s32, s32))0x800D4911u)          /* key light (key, 1 lit / 0 dim, level) */
#define PROJECT 0x82E009D0u
#define PROJECT_GET ((s32 (*)(u32, s32, s32))0x800DDA39u)  /* (object, id, pad or -1) */
#define SMPL 0x82E2CD08u                                    /* CSmplPrm */
#define PAD_GET ((s32 (*)(u32, s32, s32))0x800DC6B9u)      /* (CSmplPrm, id, pad) */
#define PAD_SET ((void (*)(u32, s32, s32, s32))0x800DA721u) /* (CSmplPrm, id, value, pad) */
#define EDITED ((volatile u8 *)(SMPL + 0x1C))              /* CSmplPrm::Edited */
#define PAD_TEMPO ((s32 (*)(s32))0x80047DD1u)              /* BPM x 100 BPM-synced samples on the pad follow */
#define SOUNDING ((s32 (*)(s32))0x800D8C09u)               /* a voice slot plays the pad */
#define RING_ROLL ((void (*)(s32, s32, s32, s32))0x800163A9u)  /* (pad, 0x7f on / 0 off, 0, 0): stock roll */
#define POST ((void (*)(s32, s32, s32))0x800E25C1u)        /* SMPL TASK command; 0xd saves the pads */
#define REPAINT ((volatile u16 *)0x802496F0u)              /* stock's light and draw requests: 2 pads, 0x10 keys */
#define PAGE ((const volatile u16 *)0x80245880u)            /* the current page; DOOM OS's own is 0x5f */
#define DOOM_PAGE 0x5F
#define EXT(pad) ((volatile u8 *)(SMPL + 0xF800u + (u32)(pad) * 0x80u))    /* PADCONF.BIN's 128 bytes */
/* The audio clock: the DMA interrupt (0x80003408 -> 0x80004f70) adds 32 to it every 64-frame block and notes
 * the cycle counter; the stock MIDI clock (0x80009de0) interpolates between blocks at 32 per 798000 cycles. */
#define CLOCK ((const volatile u32 *)0x8059226Cu)
#define CLOCK_CYCLES ((const volatile u32 *)0x80592264u)
#define CYCCNT ((const volatile u32 *)0xE0001004u)
#define BLOCK_CYCLES 798000u

#define PRESS_PAD 0x800C904Fu       /* the stock pad note's callers in the page pad handler 0x800c7db8: */
#define PRESS_SUBPAD 0x800C8D41u    /* a pad pressed, and SUB PAD (the last pad) pressed or let go */
#define HOLD_LET_GO 0x80134193u     /* stock's HOLD (0x801340c8, from that handler) ends a held GATE pad on its press */

#define KEY_HOLD 0x11
#define KEY_ROLL 0x21
#define KEY_EXIT 0x22
#define KEY_SHIFT 0x2A
#define KEY_VALUE 0x31
#define EV_KEY 5
#define EV_KEY_UP 6
#define EV_ENCODER 7
#define EV_KNOB 9
#define EV_PAD 0x10
#define EV_PAD_UP 0x11
#define SUB_PAD 0x13                /* SUB PAD's pad event; the module counts it as pad 16 */
#define PHYS 17
#define NONE 0xFF
#define DJ_MODE 0xC2                /* project: DJ Mixer Mode */
#define P_CHROMATIC 0xBF            /* project: chromatic mode (the stock pad note then sends notes, type 0xC) */
#define P_SOURCE 0xC1               /* project: the pad whose sample chromatic mode plays */
#define SG_PAGE 0x1E                /* the Sound Generator's page: its pads are its own */
#define START_END_PAGE 0x05         /* the START/END screen (what START/END asks for): ROLL held previews the end */
#define PITCH_PAGE 0x04             /* PITCH/SPEED (what PITCH/SPEED asks for): ROLL opens and closes Groove */
#define CHROMA_SHIFT 4              /* byte 0x70 bits 4-7: a pad's chromatic division, along VALUE's order */
#define CHROMA_FIRST 9              /* ... counted from nr_div_order[9], 1/16 (0, the default) */
#define P_CUR_BANK 0
#define P_CUR_PAD 1
#define P_GATE 0x6A
#define P_LOOP 0x6B
#define P_ROLL 0x7B                 /* pad: Roll, 0 Off, 1..10 */
#define FOLLOW_BYTE 0x70            /* PADCONF reserved byte: bit 0 set = the pad ignores ROLL; bits 1-3 a triplet;
                                       bits 4-7 the chromatic division */
#define TRIP_MASK 0x0E              /* 1..6: division 11..16 while Roll holds nr_trip_stock[n - 1] */
#define PADS 160
#define REPEATS 16
#define KIND_HIT 1
#define KIND_RING 2
#define TEMPO_DEFAULT 12000
#define SAVE_MS 1000

/* Division -> beats as NUM / DEN: Roll's values 0..10 (0x801a9f18: 2, 1, 1/2 .. 1/16, 3/2 .. 3/16), then the
 * module's triplets 11..16 (4/3, 2/3, 1/3, 1/6, 1/12, 1/24); the names (0..10 as stock shows them,
 * 0x800bf788); the order VALUE steps through, slowest first; each triplet's nearest stock division. */
static const u8 div_num[17] = {0, 2, 1, 1, 1, 1, 1, 3, 3, 3, 3, 4, 2, 1, 1, 1, 1};
static const u8 div_den[17] = {1, 1, 1, 2, 4, 8, 16, 2, 4, 8, 16, 3, 3, 3, 6, 12, 24};
EXPORT const char nr_div_names[17][6] = {"Off", "1/2", "1/4", "1/8", "1/16", "1/32", "1/64", "3/8", "3/16",
                                         "3/32", "3/64", "1/2T", "1/4T", "1/8T", "1/16T", "1/32T", "1/64T"};
EXPORT const u8 nr_div_order[16] = {1, 7, 11, 2, 8, 12, 3, 9, 13, 4, 10, 14, 5, 15, 6, 16};
EXPORT const u8 nr_trip_stock[6] = {7, 8, 9, 10, 6, 6};

struct nr_repeat {
    u8 kind;         /* 0 free, KIND_HIT, KIND_RING */
    u8 pad;
    u8 vel;
    u8 div;          /* 1..16 */
    u8 hold;         /* started while ROLL was held: goes on while ROLL is held */
    u8 ring;         /* KIND_RING: the stock roll was asked for */
    u8 seen;         /* the pad's Roll as last read or written: a change from elsewhere (SHIFT + ROLL) is taken */
    u8 phys;         /* the pad (0..15) or SUB PAD (16) whose press started it */
    u8 stick;        /* held by HOLD: goes on until stopped */
    u8 chroma;       /* a chromatic pad: its chromatic division, the sample's tempo, nothing else of the pad's */
    u8 spare[2];
    u32 last;        /* the last hit (frames) */
    u32 next;        /* the next hit */
    u32 frac;        /* what a period leaves over, in 1/den frames */
    u32 key;         /* what the period was worked out from: den << 3 | num (0: work it out again) */
    u32 hits;
};

struct nr_state {
    u8 held;         /* ROLL down, as the dispatcher saw it */
    u8 latched;
    u8 tap;          /* this ROLL press has touched nothing else yet */
    u8 led;          /* the latch light is on */
    u8 ate_value;    /* VALUE's press was taken (ROLL + VALUE): its release is too */
    u8 active;       /* repeats in use */
    u8 last_pad;     /* the pad VALUE's popup shows */
    u8 cur_phys;     /* the pad event being dispatched: 0..16, NONE */
    s32 save_ms;     /* a follow or division change waits this long, with no pad repeating, for the save */
    u32 now;         /* the audio clock in frames, as last read */
    u32 hits;        /* re-hits since boot */
    u32 steps;       /* VALUE steps since boot */
    u32 latches;     /* latch toggles since boot */
    u16 blink;       /* the pad lights (0..15) blinking for held rolls */
    u8 hold_led;     /* HOLD lit for held rolls */
};

EXPORT volatile u8 nr_enabled;     /* not DJ mode, not ROLL's own screens; read from other tasks by the gates */
EXPORT volatile struct nr_state nr;
EXPORT struct nr_repeat nr_rep[REPEATS];
EXPORT u8 nr_phys_down[PHYS];     /* pads 1-16 and SUB PAD, down as the UI dispatcher saw them */
EXPORT u8 nr_phys_pad[PHYS];      /* the pad each one played on its press (NONE: none) */
EXPORT u8 nr_phys_vel[PHYS];
EXPORT char nr_text[24];

/* The stock pad note's first instructions (displaced by the jump to nr_pad), then on at 0x800cdbda:
 * the module's own notes go straight here, past the observer. */
__attribute__((naked, noinline)) EXPORT void nr_pad_stock(s32 pad, s32 vel, s32 mode) {
    __asm__ volatile(
        "push.w {r4, r5, r6, r7, r8, lr}\n\t"
        "sub sp, #0x18\n\t"
        "mov r4, r1\n\t"
        "mov r5, r0\n\t"
        "movw r12, #0xdbdb\n\t"
        "movt r12, #0x800c\n\t"
        "bx r12\n\t");
}

static u32 key_down(u32 k) {
    return KEYS[k >> 3] >> (k & 7) & 1;
}

/* Frames played: 64 a block, between blocks by the cycle counter (as the stock MIDI clock does). Read again
 * if a block ended while reading. */
static u32 clock_frames(void) {
    u32 c, d;
    do {
        c = *CLOCK;
        d = *CYCCNT - *CLOCK_CYCLES;
    } while (c != *CLOCK);
    if (d > BLOCK_CYCLES)
        d = BLOCK_CYCLES;
    return nr.now = c * 2 + d * 64 / BLOCK_CYCLES;
}

/* The screens where ROLL is the screen's own: START/END's preview, PITCH/SPEED's Groove screen. */
static u32 roll_page(void) {
    return *PAGE == START_END_PAGE || *PAGE == PITCH_PAGE;
}

/* Off in DJ mode, and on ROLL's own screens (but for a ROLL press the module took before the screen opened, until
 * it is let go). */
static void update_enabled(void) {
    nr_enabled = PROJECT_GET(PROJECT, DJ_MODE, -1) == 0 && (!roll_page() || nr.held);
}

static u32 follows(u32 pad) {
    return !(EXT(pad)[FOLLOW_BYTE] & 1);
}

/* Chromatic mode, as the stock pad note sees it (not on the Sound Generator's page, whose pads are its own). */
static u32 chroma_mode(void) {
    return *PAGE != SG_PAGE && PROJECT_GET(PROJECT, P_CHROMATIC, -1) != 0;
}

/* What Roll holds for a division: itself, or a triplet's nearest stock division. */
static u32 stock_div(u32 div) {
    return div > 10 ? nr_trip_stock[div - 11] : div;
}

/* The pad's division: its triplet while Roll still holds that triplet's stock neighbour (a triplet Roll no
 * longer matches, set elsewhere since, is dropped), else Roll; 0 for Off. */
static u32 pad_div(u32 pad) {
    volatile u8 *b = &EXT(pad)[FOLLOW_BYTE];
    s32 roll = PAD_GET(SMPL, P_ROLL, (s32)pad);
    u32 t = (*b & TRIP_MASK) >> 1;
    if (t - 1 < 6 && (s32)nr_trip_stock[t - 1] == roll)
        return 10 + t;
    if (t)
        *b &= (u8)~TRIP_MASK;
    return (u32)(roll - 1) <= 9 ? (u32)roll : 0;
}

/* A division kept with the pad: Roll gets it or its stock neighbour (stock's setter marks the pads edited
 * when Roll changes), the triplet goes in byte 0x70; saved like the follow flag. Returns Roll's value. */
static u32 keep_div(u32 pad, u32 div) {
    volatile u8 *b = &EXT(pad)[FOLLOW_BYTE];
    u32 roll = stock_div(div);
    u8 v = (u8)((*b & ~TRIP_MASK) | (div > 10 ? (div - 10) << 1 : 0));
    if (PAD_GET(SMPL, P_ROLL, (s32)pad) != (s32)roll || *b != v)
        nr.save_ms = SAVE_MS;
    PAD_SET(SMPL, P_ROLL, (s32)roll, (s32)pad);
    if (*b != v) {
        *b = v;
        *EDITED = 1;
    }
    return roll;
}

/* A pad's chromatic division: byte 0x70 bits 4-7, steps along VALUE's order from 1/16. */
static u32 chroma_div(u32 pad) {
    return nr_div_order[(((u32)EXT(pad)[FOLLOW_BYTE] >> CHROMA_SHIFT) + CHROMA_FIRST) & 15];
}

/* Kept with the pad, saved like the follow flag. */
static void keep_chroma_div(u32 pad, u32 div) {
    volatile u8 *b = &EXT(pad)[FOLLOW_BYTE];
    u32 i = 0;
    while (i < 15 && nr_div_order[i] != div)
        i++;
    u8 v = (u8)((*b & 0x0F) | ((i - CHROMA_FIRST) & 15) << CHROMA_SHIFT);
    if (*b != v) {
        *b = v;
        *EDITED = 1;
        nr.save_ms = SAVE_MS;
    }
}

static u32 current_pad(void) {
    return (u32)(PAD_GET(SMPL, P_CUR_BANK, 0) * 16 + PAD_GET(SMPL, P_CUR_PAD, 0));
}

static char *put(char *p, const char *s) {
    while (*s)
        *p++ = *s++;
    return p;
}

static char *pad_name(char *p, u32 pad) {
    u32 n = pad % 16 + 1;
    *p++ = (char)('A' + pad / 16);
    *p++ = '-';
    *p++ = (char)('0' + n / 10);
    *p++ = (char)('0' + n % 10);
    return p;
}

static void say(const char *a, const char *b) {
    char *p = put(nr_text, a);
    p = put(p, b);
    *p = 0;
    POPUP(nr_text, POPUP_TIME(0));
}

/* A period is NUM / DEN beats at the pad's tempo (a chromatic pad: the sample's pad's): key = DEN x BPMx100 << 3
 * | NUM. */
static u32 period_key(const struct nr_repeat *r) {
    s32 pad = r->pad;
    if (r->chroma) {
        s32 source = PROJECT_GET(PROJECT, P_SOURCE, -1);
        if ((u32)source < PADS)
            pad = source;
    }
    s32 t = PAD_TEMPO(pad);
    if (t < 2000 || t > 30000)
        t = TEMPO_DEFAULT;
    return (div_den[r->div] * (u32)t) << 3 | div_num[r->div];
}

/* One period of r's division at the pad's tempo, carried exactly: 288000000 / BPMx100 frames a beat. */
static void schedule(struct nr_repeat *r) {
    u32 key = period_key(r), den = key >> 3, num = 288000000u * (key & 7);
    if (key != r->key) {
        r->key = key;
        r->frac = 0;
    }
    u32 q = num / den;
    r->frac += num % den;
    if (r->frac >= den) {
        r->frac -= den;
        q++;
    }
    r->next = r->last + q;
}

static struct nr_repeat *find(u32 pad) {
    for (u32 i = 0; i < REPEATS; i++)
        if (nr_rep[i].kind && nr_rep[i].pad == pad)
            return &nr_rep[i];
    return 0;
}

static u32 held(const struct nr_repeat *r) {
    return nr_phys_down[r->phys] && nr_phys_pad[r->phys] == r->pad;
}

/* A pad starts repeating: its first repeat a division after now, or at the next tick. A chromatic pad (chroma)
 * at its chromatic division, by re-hits; any other at its own division, by re-hits or its stock roll. */
static void start(u32 pad, u32 vel, u32 phys, u32 hit_now, u32 chroma) {
    struct nr_repeat *r = find(pad);
    if (r && r->kind == KIND_RING) {               /* its stock roll runs (or is asked for): keep it going */
        r->hold |= nr.held;
        r->phys = (u8)phys;
        return;
    }
    if (!r) {
        for (u32 i = 0; i < REPEATS && !r; i++)
            if (!nr_rep[i].kind)
                r = &nr_rep[i];
        if (!r)
            return;
        nr.active++;
    }
    u32 div;
    if (chroma) {
        div = chroma_div(pad);
        r->kind = KIND_HIT;
    } else {
        div = pad_div(pad);
        if (!div) {
            div = 2;                               /* as stock's ROLL + pad: Off becomes 1/4 */
            PAD_SET(SMPL, P_ROLL, (s32)div, (s32)pad);
        }
        r->kind = PAD_GET(SMPL, P_LOOP, (s32)pad) && !PAD_GET(SMPL, P_GATE, (s32)pad) ? KIND_RING : KIND_HIT;
    }
    r->chroma = (u8)chroma;
    r->pad = (u8)pad;
    r->vel = (u8)vel;
    r->div = (u8)div;
    r->seen = (u8)stock_div(div);
    r->hold = nr.held;
    r->phys = (u8)phys;
    r->stick = 0;
    r->ring = 0;
    r->hits = 0;
    r->key = 0;
    r->frac = 0;
    r->last = clock_frames();
    schedule(r);
    if (hit_now)
        r->next = r->last;
    nr.last_pad = (u8)pad;
}

static void stop(struct nr_repeat *r) {
    if (r->kind == KIND_RING) {
        if (r->ring)
            RING_ROLL(r->pad, 0, 0, 0);
    } else if (r->hits && !held(r)) {
        nr_pad_stock(r->pad, 0, 1);                /* the last repeat of a GATE pad no one holds ends */
    }
    r->kind = 0;
    nr.active--;
}

static void stop_all(void) {
    for (u32 i = 0; i < REPEATS; i++)
        if (nr_rep[i].kind)
            stop(&nr_rep[i]);
}

/* A pad held repeats while ROLL is held or latched; one let go, while ROLL is still held from its start; a held
 * roll until it is stopped. */
static u32 alive(const struct nr_repeat *r) {
    if (!nr_enabled || (!r->chroma && !follows(r->pad)))
        return 0;
    if (r->stick)
        return 1;
    return held(r) ? nr.held || nr.latched : nr.held && r->hold;
}

/* HOLD pressed (no SHIFT): rolls going on become held rolls; with only held rolls going on and no pad down,
 * they stop. Stock's HOLD runs as well, whatever this does. */
static void hold_key(void) {
    u32 loose = 0, down = 0, any = 0;
    for (u32 i = 0; i < REPEATS; i++) {
        if (nr_rep[i].kind) {
            any = 1;
            loose |= !nr_rep[i].stick;
        }
    }
    if (!any)
        return;
    if (loose) {
        for (u32 i = 0; i < REPEATS; i++)
            if (nr_rep[i].kind)
                nr_rep[i].stick = 1;
        say("Roll Held", "");
        return;
    }
    for (u32 i = 0; i < PHYS; i++)
        down |= nr_phys_down[i];
    if (down)
        return;
    stop_all();
    say("Roll Hold Off", "");
}

static u32 sticky(void) {
    for (u32 i = 0; i < REPEATS; i++)
        if (nr_rep[i].kind && nr_rep[i].stick)
            return 1;
    return 0;
}

/* Held rolls show: their pads blink white (page 6; stock blinks a pad the same way) when their bank is the
 * current one and DOOM OS's page isn't up, and HOLD is lit. Written again after anything else writes those
 * lights (the writer keeps the last value); when a held roll ends stock repaints the pads and keys. */
static void held_lights(void) {
    u32 blink = 0, any = sticky();
    if (any && *PAGE != DOOM_PAGE) {
        s32 bank = PAD_GET(SMPL, P_CUR_BANK, 0);
        for (u32 i = 0; i < REPEATS; i++)
            if (nr_rep[i].kind && nr_rep[i].stick && nr_rep[i].pad / 16 == (u32)bank)
                blink |= 1u << (nr_rep[i].pad % 16);
    }
    for (u32 k = 0; k < 16; k++)
        if (blink >> k & 1)
            LED((s32)k, 2, 0xFFFFFF);
    if (nr.blink & ~blink)
        *REPAINT |= 2;
    nr.blink = (u16)blink;
    if (any) {
        LED(KEY_HOLD, 1, 0xFF);
        nr.hold_led = 1;
    } else if (nr.hold_led) {
        *REPAINT |= 0x10;
        nr.hold_led = 0;
    }
}

static void hit(struct nr_repeat *r) {
    nr_pad_stock(r->pad, 0, 1);                    /* the note before ends: its length for the recorder, */
    nr_pad_stock(r->pad, r->vel, 1);               /* a GATE pad's release */
    r->hits++;
    nr.hits++;
}

/* The division or the tempo changed: the next repeat a new period after the last one, or at the next tick if
 * that is already past. */
static void retime(struct nr_repeat *r) {
    u32 now = clock_frames();
    r->key = 0;
    schedule(r);
    if ((s32)(now - r->next) >= 0)
        r->next = now;
}

static u32 step_div(u32 div, s32 delta) {
    s32 i = 0;
    while (i < 15 && nr_div_order[i] != div)
        i++;
    i += delta;
    return nr_div_order[i < 0 ? 0 : i > 15 ? 15 : i];
}

/* VALUE turned: every repeating pad's division moves along the list at once, a chromatic pad's chromatic one;
 * with none repeating, the current pad's (in chromatic mode the last chromatic pad played). */
static void step(s32 delta) {
    u32 shown = 0, any = 0;
    nr.steps++;
    for (u32 i = 0; i < REPEATS; i++) {
        struct nr_repeat *r = &nr_rep[i];
        if (r->kind != KIND_HIT)
            continue;
        r->div = (u8)step_div(r->div, delta);
        if (r->chroma)
            keep_chroma_div(r->pad, r->div);
        else
            r->seen = (u8)keep_div(r->pad, r->div);
        retime(r);
        if (!any || r->pad == nr.last_pad)
            shown = r->div;
        any = 1;
    }
    if (!any && chroma_mode()) {
        shown = step_div(chroma_div(nr.last_pad), delta);
        keep_chroma_div(nr.last_pad, shown);
    } else if (!any) {
        u32 pad = current_pad();
        if (pad >= PADS)
            return;
        u32 div = pad_div(pad);
        shown = step_div(div ? div : 2, delta);
        keep_div(pad, shown);
    }
    say("Roll ", nr_div_names[shown]);
}

static void follow_toggle(void) {
    u32 pad = current_pad();
    if (pad >= PADS)
        return;
    EXT(pad)[FOLLOW_BYTE] ^= 1;
    *EDITED = 1;
    nr.save_ms = SAVE_MS;
    char name[6];
    *pad_name(name, pad) = 0;
    say(name, follows(pad) ? " FOLLOWS ROLL" : " IGNORES ROLL");
}

/* ROLL went down: pads already held start at once (and then this press is no tap). */
static void roll_down(void) {
    u32 chroma = chroma_mode();
    nr.held = 1;
    nr.tap = 1;
    for (u32 i = 0; i < PHYS; i++) {
        u32 pad = nr_phys_pad[i];
        if (nr_phys_down[i] && pad < PADS && (chroma || follows(pad)) && !find(pad)) {
            start(pad, nr_phys_vel[i], i, 1, chroma);
            nr.tap = 0;
        }
    }
}

static void stop_released(void) {
    for (u32 i = 0; i < REPEATS; i++)
        if (nr_rep[i].kind && !alive(&nr_rep[i]))
            stop(&nr_rep[i]);
}

/* EXIT + pad (stock stops the pad's sound): the rolls pad i (0..15) started, or of the pad it plays in this bank. */
static void exit_pad(u32 i) {
    u32 pad = (u32)PAD_GET(SMPL, P_CUR_BANK, 0) * 16 + i;
    for (u32 k = 0; k < REPEATS; k++)
        if (nr_rep[k].kind && (nr_rep[k].phys == i || nr_rep[k].pad == pad))
            stop(&nr_rep[k]);
}

/* Every UI event, before the stock dispatcher (0x8003b530); 1: the module took it. */
EXPORT s32 nr_event_c(const s16 *ev) {
    s32 type = ev[0], what = ev[1];
    if (type == EV_PAD || type == EV_PAD_UP) {
        u32 i = (u32)what < 16 ? (u32)what : what == SUB_PAD ? 16 : NONE;
        if (i == NONE)
            return 0;
        if (nr.held)
            nr.tap = 0;                            /* a pad touched while ROLL is down: no tap */
        if (type == EV_PAD) {
            if (i < 16 && key_down(KEY_EXIT))
                exit_pad(i);                       /* and on to stock's EXIT + pad */
            nr_phys_down[i] = 1;
            nr_phys_pad[i] = NONE;                 /* the stock pad note says which pad it plays */
            nr.cur_phys = (u8)i;
        } else {
            nr_phys_down[i] = 0;
            nr.cur_phys = NONE;
            stop_released();
        }
        return 0;
    }
    nr.cur_phys = NONE;
    if (type == EV_KNOB && nr.held)
        nr.tap = 0;                                /* a CTRL knob turned while ROLL is down: no tap */
    if (type != EV_KEY && type != EV_KEY_UP && type != EV_ENCODER)
        return 0;
    update_enabled();
    if (!nr_enabled)
        return 0;
    if (type == EV_KEY) {
        if (what == KEY_ROLL) {
            if (key_down(KEY_SHIFT) || key_down(KEY_EXIT)) {
                nr.tap = 0;                        /* SHIFT + ROLL, EXIT + ROLL: stock */
                return 0;
            }
            roll_down();
            return 0;                              /* the key goes on: its light, its held bit */
        }
        if (nr.held)
            nr.tap = 0;
        nr.ate_value = 0;
        if (what == KEY_VALUE && nr.held) {
            nr.ate_value = 1;
            if (chroma_mode())
                say("Roll ", nr_div_names[chroma_div(nr.last_pad)]);  /* the last chromatic pad's; all follow */
            else
                follow_toggle();
            return 1;
        }
        if (what == KEY_HOLD && !key_down(KEY_SHIFT))
            hold_key();                            /* and on to stock's HOLD */
        return 0;
    }
    if (type == EV_KEY_UP) {
        if (what == KEY_VALUE && nr.ate_value) {
            nr.ate_value = 0;
            return 1;
        }
        if (what == KEY_ROLL && key_down(KEY_EXIT)) {   /* EXIT + ROLL, whichever went down first: stock's */
            nr.held = 0;                                /* all rolls off, and these */
            nr.tap = 0;
            nr.latched = 0;
            stop_all();
            return 0;
        }
        if (what == KEY_ROLL && nr.held) {
            nr.held = 0;
            if (nr.tap) {
                nr.latched ^= 1;
                nr.latches++;
                say("Roll Latch ", nr.latched ? "On" : "Off");
            }
            nr.tap = 0;
            stop_released();
        }
        return 0;
    }
    if (what != 0 || !ev[2])
        return 0;
    if (nr.held) {
        nr.tap = 0;
    } else {
        u32 hits = 0;
        for (u32 i = 0; i < REPEATS; i++)
            hits |= nr_rep[i].kind == KIND_HIT;
        if (!nr.latched || !hits)
            return 0;
        if (key_down(KEY_VALUE) && chroma_mode())
            return 0;                              /* VALUE held: the chromatic page's push-turn (scale, key) */
    }
    step(ev[2]);
    return 1;
}

/* The stock pad note (0x800cdbd0), before its body: the pad a page plays for the pad (or SUB PAD) event
 * being dispatched. A press that plays a held roll's pad, or that stock's HOLD takes to let that pad go,
 * stops the roll and starts nothing (stock then plays the press, or ends the pad, its own way). */
EXPORT void nr_pad_c(s32 pad, s32 vel, s32 mode, u32 caller) {
    (void)mode;
    u32 i = nr.cur_phys;
    u32 press = vel > 0 && (caller == PRESS_PAD || caller == PRESS_SUBPAD);
    if ((u32)pad >= PADS || i >= PHYS || !(press || caller == HOLD_LET_GO))
        return;
    struct nr_repeat *r = find((u32)pad);
    if (r && r->stick) {
        if (caller == HOLD_LET_GO)
            r->hits = 0;                           /* this call is the pad's note-off */
        stop(r);
        return;
    }
    if (!press)
        return;
    nr_phys_pad[i] = (u8)pad;
    nr_phys_vel[i] = (u8)(vel > 127 ? 127 : vel);
    update_enabled();
    u32 chroma = chroma_mode();
    if (chroma)
        nr.last_pad = (u8)pad;                     /* the one ROLL + VALUE steps with nothing repeating */
    if (nr_enabled && (nr.held || nr.latched) && (chroma || follows((u32)pad)))
        start((u32)pad, nr_phys_vel[i], i, 0, chroma);
}

/* The UI tick, every millisecond (0x8003c5f0(1)). */
EXPORT void nr_tick_c(s32 ms) {
    if (!nr.active && !nr.held && !nr.latched && !nr.led && !nr.save_ms && !nr.blink && !nr.hold_led)
        return;
    clock_frames();
    if (nr.save_ms > 0 && !nr.active && (nr.save_ms -= ms) <= 0) {     /* not while pads repeat */
        nr.save_ms = 0;
        POST(0xD, 1, 0);
    }
    update_enabled();
    if (!nr_enabled) {
        nr.held = nr.tap = 0;
        if (!roll_page())
            nr.latched = 0;                        /* DJ mode ends the latch; ROLL's screens keep it for afterwards */
        stop_all();
    }
    for (u32 i = 0; i < REPEATS; i++) {
        struct nr_repeat *r = &nr_rep[i];
        if (!r->kind)
            continue;
        if (!alive(r)) {
            stop(r);
            continue;
        }
        s32 div = r->chroma ? r->seen : PAD_GET(SMPL, P_ROLL, r->pad);
        if (div != r->seen) {                      /* SHIFT + ROLL changed it: that division, no triplet */
            r->seen = (u8)div;
            if ((u32)(div - 1) <= 9) {
                r->div = (u8)div;
                EXT(r->pad)[FOLLOW_BYTE] &= (u8)~TRIP_MASK;
            }
        }
        if (r->kind == KIND_RING) {
            if (!r->ring && SOUNDING(r->pad)) {
                RING_ROLL(r->pad, 0x7F, 0, 0);
                r->ring = 1;
            }
            continue;
        }
        if (period_key(r) != r->key)               /* a new division or tempo: at once */
            retime(r);
        if ((s32)(nr.now - r->next) >= 0) {
            hit(r);
            r->last = r->next;
            schedule(r);
            if ((s32)(nr.now - r->next) >= 0) {    /* fell behind by a whole period: start again from now */
                r->last = nr.now;
                schedule(r);
            }
        }
    }
    if (nr.latched && nr_enabled) {
        LED(KEY_ROLL, 1, 0xFF);                    /* cached: sent again only after something else wrote it */
        nr.led = 1;
    } else if (nr.led) {
        if (nr.latched)
            *REPAINT |= 0x10;                      /* latched on ROLL's screens: stock's key lights there */
        else
            LED(KEY_ROLL, 0, 0x1F);
        nr.led = 0;
    }
    held_lights();
}

__attribute__((naked)) EXPORT void nr_event(void) {
    __asm__ volatile(
        "push {r0, lr}\n\t"
        "bl nr_event_c\n\t"
        "cmp r0, #0\n\t"
        "pop {r0, lr}\n\t"
        "it ne\n\t"
        "bxne lr\n\t"                              /* taken: the UI drain ignores the result */
        "ldrsh.w r1, [r0]\n\t"                     /* the four displaced instructions */
        "subs r1, #5\n\t"
        "cmp r1, #0x20\n\t"
        "it hi\n\t"
        "bxhi lr\n\t"                              /* stock: bhi 0x8003b574, bx lr */
        "movw r12, #0xb53b\n\t"                    /* on at the tbb 0x8003b53a, r1 = type - 5 */
        "movt r12, #0x8003\n\t"
        "bx r12\n\t");
}

__attribute__((naked)) EXPORT void nr_pad(void) {
    __asm__ volatile(
        "push {r0, r1, r2, r3, r4, lr}\n\t"
        "mov r3, lr\n\t"
        "bl nr_pad_c\n\t"
        "pop {r0, r1, r2, r3, r4, lr}\n\t"
        "b nr_pad_stock\n\t");
}

__attribute__((naked)) EXPORT void nr_tick(void) {
    __asm__ volatile(
        "push {r0, lr}\n\t"
        "bl nr_tick_c\n\t"
        "pop {r0, lr}\n\t"
        "push {r4, r5, r6, r7, lr}\n\t"            /* the four displaced instructions */
        "sub sp, #4\n\t"
        "mov r4, r0\n\t"
        "movw r0, #0xeebc\n\t"
        "movw r12, #0xc5fb\n\t"                    /* on at 0x8003c5fa */
        "movt r12, #0x8003\n\t"
        "bx r12\n\t");
}

/* 0x80135d40, ROLL let go (the generic key handler, no SHIFT, no EXIT): stock rolls the current pad on
 * if it sounds without rolling, and turns the note-on's rolls off; the module does ROLL's release itself. */
__attribute__((naked)) EXPORT void nr_release(void) {
    __asm__ volatile(
        "movw r12, #:lower16:nr_enabled\n\t"
        "movt r12, #:upper16:nr_enabled\n\t"
        "ldrb r12, [r12]\n\t"
        "cmp r12, #0\n\t"
        "it ne\n\t"
        "bxne lr\n\t"
        "push {r4, r5, r6, lr}\n\t"                /* the four displaced instructions */
        "movw r4, #0x9d0\n\t"
        "mov r5, r0\n\t"
        "movt r4, #0x82e0\n\t"
        "movw r12, #0x5d4d\n\t"                    /* on at 0x80135d4c */
        "movt r12, #0x8013\n\t"
        "bx r12\n\t");
}

/* 0x800d9f20, "is key r0 held": the note-on's three roll starts (0x800aec48, return addresses below) hear
 * no while the module runs; every other query goes to the kits' gate with the caller's own lr. */
#define STR2(x) #x
#define STR(x) STR2(x)
__attribute__((naked)) EXPORT void nr_key_gate(void) {
    __asm__ volatile(
        "cmp r0, #0x21\n\t"
        "bne 2f\n\t"
        "movw r12, #0xee23\n\t"
        "movt r12, #0x800a\n\t"
        "cmp lr, r12\n\t"
        "beq 1f\n\t"
        "movw r12, #0xef97\n\t"
        "movt r12, #0x800a\n\t"
        "cmp lr, r12\n\t"
        "beq 1f\n\t"
        "movw r12, #0xf06f\n\t"
        "movt r12, #0x800a\n\t"
        "cmp lr, r12\n\t"
        "bne 2f\n\t"
        "1:\n\t"
        "movw r12, #:lower16:nr_enabled\n\t"
        "movt r12, #:upper16:nr_enabled\n\t"
        "ldrb r12, [r12]\n\t"
        "cmp r12, #0\n\t"
        "beq 2f\n\t"
        "movs r0, #0\n\t"
        "bx lr\n\t"
        "2:\n\t"
        "movw r12, #(" STR(KIT_KEY_GATE) " & 0xffff)\n\t"
        "movt r12, #(" STR(KIT_KEY_GATE) " >> 16)\n\t"
        "bx r12\n\t");
}
