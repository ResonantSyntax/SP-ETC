/* Pad envelopes, stage 1: a better amplitude envelope per pad (analysis/pad_envelope/REPORT.md, E1 + E2).
 *
 * Stock 5.52 applies a pad's ATTACK / HOLD / RELEASE to the sample data by source position while each
 * voice's stream is filled: the recompute 0x800a2d98 turns them into an envelope block (voice + 0x60), the
 * applicators 0x16f50 (forward) and 0x17196 (reverse) scale every frame by it, and the note-off 0x80023118
 * sizes the GATE key-up release from RELEASE. This module adds, per pad and opt-in:
 *
 *   FINE      attack and release from a 0.5 ms - 8 s map (fine index 1-127, 8 % steps; 0 = none)
 *   curves    LIN (stock), EXP, LOG or S, per segment (attack, decay, release)
 *   ADSR      decay (fine index, 0 = off) to a sustain level (0-100 %), still positional: the release
 *             ends at the HOLD point, as stock's does
 *   LOOP-ONCE a looping voice shapes only its first pass (attack, decay), then holds the sustain level;
 *             it fades only at key-up or stop
 *   REV-TIME  reverse reads are evaluated at START + END - position, so the attack is heard first
 *   RETRIG    CUT (stock: a new hit stops the pad's sounding voice with a 1.3 ms declick) or a FADE time:
 *             the old voice fades out over it as a key-up release while the new one starts (chromatic
 *             notes too)
 *
 * The settings live in the pad's PADCONF reserved bytes 0x64-0x6F (B_* below), which stock saves,
 * loads, copies, moves and exchanges, and resets for a new sample. Byte 0x6D must be 1 (layout version)
 * for any of them to count. A pad whose settings are all stock (FINE off, LIN curves, no decay, no
 * LOOP-ONCE / REV-TIME) runs the stock code, bit for bit.
 *
 * The hooks (build_pad_env.py writes them, every displaced instruction checked byte for byte):
 *   0x800a2d98 (12 bytes) -> env_recompute: the shared recompute dispatcher. It runs the stock body
 *              first (env_recompute_stock: the displaced instructions, then on at 0x800a2da4), so the
 *              stock block is always stock's; then this stage, then every non-zero env_stages[] entry
 *              (stage 2, the pitch envelope, goes there) with the caller's return address
 *   0x16f50, 0x17196 (10 bytes each) -> env_fwd / env_rev: a voice whose envelope is this module's gets
 *              env_fwd_apply / env_rev_apply; anything else runs the displaced instructions and goes on
 *              in ITCM
 *   0x8002315a (16 bytes) -> env_release: r6 = release frames x 127 for a FINE voice, else R x 144000
 *   0x8009424e (10 bytes, a call) -> env_retrig: the stop 0x80094168 calling the re-hit / steal stop
 *              0x80024580; for the voice manager's re-hits of a FADE pad, the key-up release instead
 *   ENVELOPE page vtable 0x8021ec14: +0x04 (leave) env_ui_leave, +0xC8 (pad change) env_ui_pad,
 *              +0xCC (redraw) env_ui_draw, +0xD0 (tick) env_ui_poll, +0xD8 (key press) env_ui_key,
 *              +0xE0 (encoder) env_ui_turn, +0xE4 (knob) env_ui_knob
 *
 * The ENVELOPE page (SHIFT + PITCH/SPEED) gets four pages. A VALUE turn goes to the next or previous page
 * (round), and so does a SHIFT tap (press and release, nothing else touched) to the next. The screen shows
 * them, no popups: the CTRL 1-3 labels on top, their values under them, the pad's real envelope in the
 * graph, and the pad, the page and its number at the bottom ("A-1 AMP 1/4", "A-1 SHAPE 2/4"):
 *   1 AMP    stock's page: CTRL 1-3 ATTACK / HOLD / RELEASE. VALUE press switches TIME between STOCK and
 *            FINE ("A-1 AMP FINE 1/4"); with FINE on, ATTACK and RELEASE are fine indices (the stock
 *            fields get the nearest stock value) and the screen shows the times
 *   2 SHAPE  CTRL 1 attack curve, CTRL 3 release curve
 *   3 DECAY  CTRL 1 decay (OFF, 0.5 ms - 8 s), CTRL 2 sustain 0-100 %, CTRL 3 decay curve
 *   4 MODE   CTRL 1 LOOP: EVERY / FIRST (pass), CTRL 2 RETRIG: CUT / the fade (0.5 ms - 8 s), CTRL 3
 *            REVERSE: MIRROR / TIME
 * Later stages add pages through env_more_pages[]. A pad with stock settings keeps stock's graph, and on
 * page 1 the whole stock screen but its bottom line.
 * Holding COPY or REMAIN applies a turn to the mute group or bank, as stock's apply 0x800f5df0 does.
 * DEL (stock's page ignores it) asks "RESET A-1? press VALUE": VALUE puts every envelope setting of the pad
 * back to stock (0x64-0x6F, and the later stages' 0x71-0x7F; note repeat's 0x70 stays, as do stock's own
 * ATTACK / HOLD / RELEASE); with COPY or REMAIN held at DEL, its mute group or bank ("RESET GROUP?",
 * "RESET BANK A?"). Any other key, a knob or a pad change cancels; EXIT then stays on the page.
 * Stock's INIT PARAM (SHIFT + pad 6, command 0x40a -> 0x8018c220) clears bytes 0x40-0x7F of the pad's
 * extended block itself: these settings, note repeat's byte and the pad FX bytes, with the rest of the pad.
 * Like stock's setter, nothing is written for a pad without a sample it edits (0x800d9e30).
 * A change sets the stock Edited flag; command 0xD (save) goes out 1 s after the last turn, or when
 * the page closes.
 *
 * The tables (pad_env_tables.h) are generated by build_pad_env.py.
 */
typedef unsigned int u32;
typedef int s32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;
typedef unsigned long long u64;

#define EXPORT __attribute__((used))

/* stock 5.52 */
#define VOICES 0x805F8834u            /* 32 voice objects of 0x28820 bytes; voice i = VOICES + i * SIZE */
#define VOICE_SIZE 0x28820u
#define NVOICES 32
#define ENV_AT 0x60                   /* the envelope block: voice + 0x60 */
#define V_LOOP 0x24                   /* voice: LOOP, from the pad record (allocator 0x800241c8) */
#define V_R 0x100                     /* voice: RELEASE 0-127 */
#define V_PAD 0x14274                 /* voice: its pad, stored by Init before it calls the recompute */
#define INIT_RET 0x80023B05u          /* the recompute's return address in CSmplCharge::Init */
#define CSMPLPRM 0x82E2CD08u          /* pad parameters; extended block of pad p at + 0xF800 + p * 0x80 */
#define EDITED (*(volatile u8 *)(CSMPLPRM + 0x1C))
#define PADS 160
#define SMPLMGR 0x80591800u
#define PROJECT 0x82E009D0u           /* project parameters: 0x17 + bank = the bank is protected */
#define APPLY_MODE (*(volatile s32 *)0x80591B54u)  /* ENVELOPE page: 1 COPY (mute group), 2 REMAIN (bank) */
#define KEYS ((const volatile u8 *)0x80592448u)    /* held keys, set and cleared by the UI dispatcher */
#define KEY_BYTES 11
#define KEY_SHIFT 42
#define KEY_DEL 0x1A
#define KEY_EXIT 0x22
#define KEY_VALUE 0x31

#define STOCK_KNOB ((s32 (*)(void *, s32, s32))0x800F5D11u)   /* ENVELOPE page knob */
#define STOCK_LEAVE ((void *(*)(void *))0x800F6239u)          /* ENVELOPE page deleting destructor */
#define STOCK_KEY ((s32 (*)(void *, s32))0x800F5AD9u)            /* ENVELOPE page key press */
#define FX_KNOBS ((s32 (*)(void *))0x800CE421u)               /* non-zero: the knobs drive the effect */
#define UI_HELD ((s32 (*)(void))0x800C3F19u)                  /* non-zero: stock's VALUE press is the base
                                                                 class's (0x800c9788); else it does nothing */
#define EDITABLE ((s32 (*)(s32))0x800D9E31u)                  /* the pad holds a sample the setter edits */
#define GETTER ((s32 (*)(u32, s32, s32))0x800DC6B9u)          /* (CSmplPrm, param, pad) */
#define SETTER ((void (*)(u32, s32, s32, s32))0x800DA721u)    /* (CSmplPrm, param, value, pad) */
#define FANOUT ((void (*)(u32, s32, s32, s32))0x800D7A81u)    /* (SmplMgr, pad, param, value): every
                                                                 voice of the pad gets the param again */
#define POST ((void (*)(s32, s32, s32))0x800E25C1u)           /* (command, a, b); 0xD 1 0 = save */
#define P_ATK 0x7D
#define P_REL 0x7F
#define P_MUTE 0x6D

/* the settings: PADCONF extended block bytes */
#define B_FLAGS 0x64                  /* F_* */
#define B_ATK 0x65                    /* attack, fine index */
#define B_REL 0x66                    /* release, fine index */
#define B_CURVES 0x67                 /* b0-1 attack, b2-3 decay, b4-5 release: LIN EXP LOG S */
#define B_DEC 0x68                    /* decay, fine index, 0 = off */
#define B_SUS 0x69                    /* sustain 0-100 % */
#define B_RETRIG 0x6A                 /* 0 CUT (stock), 1 FADE */
#define B_FADE 0x6B                   /* the re-hit fade, fine index */
#define B_VERSION 0x6D                /* 1 whenever any of 0x64-0x6C is not 0 */
#define B_REPEAT 0x70                 /* note repeat's (its own module): the reset leaves it */
#define B_END 0x80                    /* the later stages' bytes run up to here (0x71-0x7F) */
#define F_FINE 1
#define F_ADSR 2
#define F_ONCE 4
#define F_REV 8
#define ONE 32768                     /* level 1.0 */

#include "pad_env_tables.h"

static u8 *ext(u32 pad) {
    return (u8 *)(CSMPLPRM + 0xF800u + pad * 0x80u);
}

/* a setting as it counts: 0 unless the layout version is 1 */
static u32 setting(u32 pad, u32 byte) {
    const u8 *b = ext(pad);
    return b[B_VERSION] == 1 ? b[byte] : 0;
}

/* ---------------------------------------------------------------- per voice */

struct env_shape {      /* what the applicators use; the recompute publishes a new one per call */
    u8 on;              /* the module shapes this voice; else stock does */
    u8 fine;            /* the key-up release is rel frames */
    u8 once, rev;       /* LOOP-ONCE, REV-TIME */
    u8 ta, td, tr;      /* env_curve tables: attack (rising), decay and release (falling) */
    u8 adsr;
    u16 sus;            /* sustain level */
    u16 peak;           /* where the release starts from */
    u32 s, e;           /* START, END */
    u32 atk, ae;        /* attack length; attack end (the crossover when attack and release overlap) */
    u32 dec, de;        /* decay length; decay end (past rs: the release cuts it) */
    u32 rs, rlen, he;   /* release start and length; the HOLD point, silent from there */
    u32 rel;            /* release frames for the key-up release (FINE) */
};

struct env_voice {
    struct env_shape sh[2];
    volatile u8 cur;    /* the published shape */
    u8 passed;          /* LOOP-ONCE: the first pass is over */
    u8 dir;             /* LOOP-ONCE: direction of the last read, 1 forward, 2 reverse, 0 none yet */
    u8 spare;
    u32 last;           /* LOOP-ONCE: forward, where the last read ended; reverse, where it stopped */
};

EXPORT struct env_voice env_voices[NVOICES];

/* The recompute call, for this stage and the later ones (env_stages). */
struct env_call {
    u8 *env;            /* the block the stock body just wrote */
    u32 start, length;  /* the arguments as passed */
    s32 a, h, r, ch;
    u32 lr;             /* return address: 0x80023b05 Init, 0x8001ff39 A/H/R, 0x80022daf START,
                           0x80024a8f END, 0x8002310f loop point */
    s32 voice;          /* 0-31, or -1 when env is not a voice's block */
    s32 pad;            /* the voice's pad, or -1 */
};

/* Later stages register here (a pointer to a function taking the call); 0 = empty. */
EXPORT void (*volatile env_stages[4])(const struct env_call *);

/* env (a block pointer) -> its voice index, or -1 */
static s32 voice_of(u32 env) {
    u32 off = env - (VOICES + ENV_AT);
    u32 i = (u32)(((u64)off * 25886u) >> 32);   /* off / 0x28820 for off < 32 * 0x28820 */
    return i < NVOICES && off == i * VOICE_SIZE ? (s32)i : -1;
}

/* ---------------------------------------------------------------- the stock code, displaced */

/* The recompute's first twelve bytes, then on at 0x800a2da4. Called as the recompute itself. */
__attribute__((naked, noinline)) EXPORT u32 env_recompute_stock(u8 *env, u32 start, u32 length, s32 a,
                                                                 s32 h, s32 r, s32 ch) {
    __asm__ volatile(
        "push.w {r4, r5, r6, r7, r8, r9, r10, r11, lr}\n\t"
        "sub sp, #4\n\t"
        "mov r4, r0\n\t"
        "movw r9, #0x3280\n\t"
        "movw r12, #0x2da5\n\t"
        "movt r12, #0x800a\n\t"
        "bx r12\n\t");
}

/* The forward applicator's first ten bytes, then on at 0x16f5a (ITCM). */
__attribute__((naked, noinline)) EXPORT void env_fwd_stock(void) {
    __asm__ volatile(
        "push.w {r4, r5, r6, r7, r8, r9, r10, r11, lr}\n\t"
        "sub sp, #0x24\n\t"
        "ldr r7, [sp, #0x48]\n\t"
        "cmp r7, #1\n\t"
        "movw r12, #0x6f5b\n\t"
        "movt r12, #0x1\n\t"
        "bx r12\n\t");
}

/* The reverse applicator's first ten bytes, then on at 0x171a0 (ITCM). */
__attribute__((naked, noinline)) EXPORT void env_rev_stock(void) {
    __asm__ volatile(
        "push.w {r4, r5, r6, r7, r8, r9, r10, r11, lr}\n\t"
        "sub sp, #0x24\n\t"
        "ldr r7, [sp, #0x48]\n\t"
        "str r0, [sp, #0x20]\n\t"
        "movw r12, #0x71a1\n\t"
        "movt r12, #0x1\n\t"
        "bx r12\n\t");
}

/* ---------------------------------------------------------------- the shape */

/* (a << 32) / b for a < b, and its remainder */
static u32 frac(u32 a, u32 b, u32 *rem) {
    u32 q = 0, r = a;
    for (u32 i = 0; i < 32; i++) {
        u32 top = r >> 31;
        r <<= 1;
        q <<= 1;
        if (top || r >= b) {
            r -= b;
            q |= 1;
        }
    }
    *rem = r;
    return q;
}

/* a curve at phase ph (fraction of 2^32), Q15 */
static u32 curve(u32 t, u32 ph) {
    const u16 *c = env_curve[t];
    u32 i = ph >> 24, f = (ph >> 8) & 0xFFFF;
    return c[i] + (((u32)(c[i + 1] - c[i]) * f) >> 16);
}

static const u8 fall_of[4] = {0, 2, 1, 3};   /* a falling EXP is the LOG table read upward, and back */

static void shape(struct env_shape *sh, const struct env_call *c) {
    u8 *env = c->env;
    sh->on = 0;
    if ((u32)c->pad >= PADS)
        return;
    const u8 *b = ext((u32)c->pad);
    if (b[B_VERSION] != 1)
        return;
    u32 flags = b[B_FLAGS], curves = b[B_CURVES], sus = b[B_SUS];
    u32 ca = curves & 3, cd = curves >> 2 & 3, cr = curves >> 4 & 3;
    if (sus > 100)
        sus = 100;
    u32 fine = flags & F_FINE;
    u32 adsr = (flags & F_ADSR) && (b[B_DEC] & 127) && sus < 100;
    u32 once = flags & F_ONCE, rev = flags & F_REV;
    if (!(fine || adsr || once || rev || ca || cr))
        return;
    u32 s = *(u32 *)(env + 0x08);
    u32 he = *(u32 *)(env + 0x18);
    u32 atk = fine ? env_fine_frames[b[B_ATK] & 127] : *(u32 *)(env + 0x10) - s;
    u32 rel = fine ? env_fine_frames[b[B_REL] & 127] : *(u32 *)(env + 0x28);
    u32 dec = adsr ? env_fine_frames[b[B_DEC] & 127] : 0;
    u32 span = he - s;
    sh->fine = (u8)fine;
    sh->once = (u8)!!once;
    sh->rev = (u8)!!rev;
    sh->adsr = (u8)adsr;
    sh->ta = (u8)ca;
    sh->td = fall_of[cd];
    sh->tr = fall_of[cr];
    sh->sus = (u16)(adsr ? (sus * ONE + 50) / 100 : ONE);
    sh->s = s;
    sh->e = s + *(u32 *)(env + 0x00);
    sh->he = he;
    sh->atk = atk;
    sh->dec = dec;
    sh->rel = rel;
    if ((u64)atk + rel > span) {
        /* attack and release overlap: they cross where stock's lines do, the release falls from there */
        u32 r, x = rel ? (u32)(((u64)span * frac(atk, atk + rel, &r)) >> 32) : span;
        sh->ae = sh->de = sh->rs = s + x;
        sh->peak = (u16)curve(sh->ta, frac(span, atk + rel, &r));
        sh->rlen = he - sh->rs;
    } else {
        sh->ae = s + atk;
        sh->de = sh->ae + dec;
        sh->rs = he - rel;
        sh->rlen = rel;
        sh->peak = ONE;
        if (adsr) {
            u32 r;
            sh->peak = sh->de <= sh->rs ? sh->sus :
                (u16)(ONE - (((ONE - sh->sus) * curve(sh->td, frac(sh->rs - sh->ae, dec, &r))) >> 15));
        }
    }
    sh->on = 1;
}

static void amp_stage(const struct env_call *c) {
    if (c->voice < 0)
        return;
    struct env_voice *v = &env_voices[c->voice];
    if (c->lr == INIT_RET) {          /* a voice start: a new first pass */
        v->passed = 0;
        v->dir = 0;
        v->last = 0;
    }
    u32 n = v->cur ^ 1u;
    shape(&v->sh[n], c);
    __asm__ volatile("dmb" ::: "memory");
    v->cur = (u8)n;
}

/* Every recompute comes here, through the jump at 0x800a2d98 and env_recompute, with its caller's
 * return address. The stock body runs first and its result is what the caller gets back. */
EXPORT u32 env_dispatch(u8 *env, u32 start, u32 length, s32 a, s32 h, s32 r, s32 ch, u32 lr) {
    u32 result = env_recompute_stock(env, start, length, a, h, r, ch);
    s32 voice = voice_of((u32)env);
    struct env_call c = {env, start, length, a, h, r, ch, lr, voice,
                         voice < 0 ? -1 : *(s32 *)(env - ENV_AT + V_PAD)};
    amp_stage(&c);
    for (u32 i = 0; i < 4; i++) {
        void (*stage)(const struct env_call *) = env_stages[i];
        if (stage)
            stage(&c);
    }
    return result;
}

__attribute__((naked)) EXPORT void env_recompute(void) {
    __asm__ volatile(
        "push {r4, r5, r6, lr}\n\t"
        "ldr r4, [sp, #16]\n\t"           /* H, R, channels: the caller's stack arguments */
        "ldr r5, [sp, #20]\n\t"
        "ldr r6, [sp, #24]\n\t"
        "sub sp, #16\n\t"
        "str r4, [sp]\n\t"
        "str r5, [sp, #4]\n\t"
        "str r6, [sp, #8]\n\t"
        "str lr, [sp, #12]\n\t"
        "bl env_dispatch\n\t"
        "add sp, #16\n\t"
        "pop {r4, r5, r6, pc}\n\t");
}

/* ---------------------------------------------------------------- the applicators */

enum { K_ZERO, K_UNITY, K_CONST, K_RAMP };
#define END_OF_ALL 0xFFFFFFFFu

struct run {
    u32 lo, hi;         /* [lo, hi) in evaluated positions; a ramp's phase counts from lo */
    u32 kind, t;
    s32 base, scale;    /* level = base + (scale * curve >> 15); K_CONST: base */
    u32 len;            /* ramp: phase = (q - lo) / len */
};

static void set(struct run *g, u32 lo, u32 hi, u32 kind) {
    g->lo = lo;
    g->hi = hi;
    g->kind = kind;
}

static void ramp(struct run *g, u32 lo, u32 hi, u32 t, s32 base, s32 scale, u32 len) {
    set(g, lo, hi, K_RAMP);
    g->t = t;
    g->base = base;
    g->scale = scale;
    g->len = len;
}

static void level(struct run *g, u32 lo, u32 hi, u32 l) {
    set(g, lo, hi, l >= ONE ? K_UNITY : K_CONST);
    g->base = (s32)l;
}

/* The segment holding evaluated position q. mode 0: positional; 1: LOOP-ONCE, first pass (no release,
 * no HOLD point); 2: LOOP-ONCE, later passes (the sustain level from START on). */
static void segment(const struct env_shape *sh, u32 mode, u32 q, struct run *g) {
    u32 s = sh->s, hold = sh->adsr ? sh->sus : ONE;
    if (q < s) {
        set(g, 0, s, K_ZERO);
        return;
    }
    if (mode == 2) {
        level(g, s, END_OF_ALL, hold);
        return;
    }
    if (mode == 1) {
        u32 ae = s + sh->atk, de = ae + sh->dec;
        if (q < ae)
            ramp(g, s, ae, sh->ta, 0, ONE, sh->atk);
        else if (sh->adsr && q < de)
            ramp(g, ae, de, sh->td, ONE, -(s32)(ONE - sh->sus), sh->dec);
        else
            level(g, sh->adsr ? de : ae, END_OF_ALL, hold);
        return;
    }
    if (q < sh->ae) {
        ramp(g, s, sh->ae, sh->ta, 0, ONE, sh->atk);
    } else if (q < sh->rs) {
        if (sh->adsr && q < sh->de)
            ramp(g, sh->ae, sh->de < sh->rs ? sh->de : sh->rs, sh->td, ONE, -(s32)(ONE - sh->sus), sh->dec);
        else
            level(g, sh->adsr ? sh->de : sh->ae, sh->rs, hold);
    } else if (q < sh->he) {
        ramp(g, sh->rs, sh->he, sh->tr, sh->peak, -(s32)sh->peak, sh->rlen);
    } else {
        set(g, sh->he, END_OF_ALL, K_ZERO);
    }
}

static s16 gain(s32 x, s32 l) {
    s32 v = x * l;
    return (s16)((v + ((v >> 31) & 0x7FFF)) >> 15);
}

/* m frames of one run: element k is evaluated at q + k * dq (dq = 1 or -1) */
static void run_frames(const struct run *g, s16 *L, s16 *R, u32 m, u32 q, s32 dq, u32 stereo) {
    if (g->kind == K_UNITY)
        return;
    if (g->kind == K_ZERO || g->kind == K_CONST) {
        s32 l = g->kind == K_ZERO ? 0 : g->base;
        for (u32 k = 0; k < m; k++) {
            L[k] = gain(L[k], l);
            if (stereo)
                R[k] = gain(R[k], l);
        }
        return;
    }
    u32 len = g->len, r = 0, sq = 0, sr = 0, ph = 0;
    if (len > 1) {
        ph = frac(q - g->lo, len, &r);
        sq = frac(1, len, &sr);
    }
    for (u32 k = 0; k < m; k++) {
        s32 l = g->base + ((g->scale * (s32)curve(g->t, ph)) >> 15);
        L[k] = gain(L[k], l);
        if (stereo)
            R[k] = gain(R[k], l);
        if (dq > 0) {
            ph += sq;
            r += sr;
            if (r >= len) {
                r -= len;
                ph++;
            }
        } else {
            ph -= sq;
            if (r < sr) {
                r += len - sr;
                ph--;
            } else {
                r -= sr;
            }
        }
    }
}

/* n elements from evaluated position q, stepping dq */
static void frames(const struct env_shape *sh, u32 mode, s16 *L, s16 *R, u32 n, u32 q, s32 dq, u32 stereo) {
    struct run g;
    while (n) {
        segment(sh, mode, q, &g);
        u32 m = dq > 0 ? (g.hi == END_OF_ALL ? n : g.hi - q) : q - g.lo + 1;
        if (!m)
            m = 1;
        if (m > n)
            m = n;
        run_frames(&g, L, R, m, q, dq, stereo);
        L += m;
        R += m;
        n -= m;
        q += dq > 0 ? m : -m;
    }
}

/* LOOP-ONCE: which mode this read is in. A wrap (a read that jumps back against its direction) or a
 * change of direction ends the first pass. */
static u32 loop_mode(struct env_voice *v, const struct env_shape *sh, const u8 *env, u32 pos, u32 n, u32 dir) {
    if (!sh->once || !*(const u32 *)(env - ENV_AT + V_LOOP))
        return 0;
    if (v->dir && (v->dir != dir || (dir == 1 ? pos < v->last : pos > v->last)))
        v->passed = 1;
    v->dir = (u8)dir;
    v->last = dir == 1 ? pos + n : pos;
    return v->passed ? 2 : 1;
}

static void zero(s16 *L, s16 *R, u32 n) {
    for (u32 k = 0; k < n; k++)
        L[k] = R[k] = 0;
}

/* forward: element i is position pos + i */
EXPORT void env_fwd_apply(u8 *env, s16 *L, s16 *R, u32 pos, s32 n, s32 unused, s32 state) {
    (void)unused;
    if (n < 1)
        return;
    struct env_voice *v = &env_voices[voice_of((u32)env)];
    const struct env_shape *sh = &v->sh[v->cur];
    u32 stereo = *(s32 *)(env + 0x40) != 1, mode = loop_mode(v, sh, env, pos, (u32)n, 1);
    u32 z = pos < sh->s ? sh->s - pos : 0;      /* before START: both channels 0, as stock */
    if (z > (u32)n)
        z = (u32)n;
    zero(L, R, z);
    if (state == 7)                              /* the envelope is bypassed in this slot state */
        return;
    frames(sh, mode, L + z, R + z, (u32)n - z, pos + z, 1, stereo);
}

/* reverse: element i is position pos + n - i */
EXPORT void env_rev_apply(u8 *env, s16 *L, s16 *R, u32 pos, s32 n, s32 unused, s32 state) {
    (void)unused;
    if (n < 1)
        return;
    struct env_voice *v = &env_voices[voice_of((u32)env)];
    const struct env_shape *sh = &v->sh[v->cur];
    u32 stereo = *(s32 *)(env + 0x40) != 1, mode = loop_mode(v, sh, env, pos, (u32)n, 2);
    u32 top = pos + (u32)n;                     /* element 0's position */
    u32 keep = top >= sh->s ? top - sh->s + 1 : 0;   /* elements at or after START */
    if (keep > (u32)n)
        keep = (u32)n;
    zero(L + keep, R + keep, (u32)n - keep);
    if (state == 7)
        return;
    if (!sh->rev) {
        frames(sh, mode, L, R, keep, top, -1, stereo);
        return;
    }
    /* REV-TIME: evaluated at START + END - position, which rises with i; past START + END it is 0 */
    u32 mirror = sh->s + sh->e, out = top > mirror ? top - mirror : 0;
    if (out > keep)
        out = keep;
    struct run g;
    set(&g, 0, 0, K_ZERO);
    run_frames(&g, L, R, out, 0, 1, stereo);
    frames(sh, mode, L + out, R + out, keep - out, mirror - (top - out), 1, stereo);
}

EXPORT u32 env_shaped(u32 env) {
    s32 i = voice_of(env);
    return i >= 0 && env_voices[i].sh[env_voices[i].cur].on;
}

/* The jump at 0x16f50 lands here with the applicator's own arguments, stack and return address. */
__attribute__((naked)) EXPORT void env_fwd(void) {
    __asm__ volatile(
        "push {r0, r1, r2, r3, r12, lr}\n\t"
        "bl env_shaped\n\t"
        "cmp r0, #0\n\t"
        "pop {r0, r1, r2, r3, r12, lr}\n\t"
        "bne.w env_fwd_apply\n\t"
        "b.w env_fwd_stock\n\t");
}

__attribute__((naked)) EXPORT void env_rev(void) {
    __asm__ volatile(
        "push {r0, r1, r2, r3, r12, lr}\n\t"
        "bl env_shaped\n\t"
        "cmp r0, #0\n\t"
        "pop {r0, r1, r2, r3, r12, lr}\n\t"
        "bne.w env_rev_apply\n\t"
        "b.w env_rev_stock\n\t");
}

/* ---------------------------------------------------------------- the note-off */

/* env_retrig_c's note-off: this voice's release is env_fade_frames (0 = none) */
EXPORT volatile u32 env_fade_voice;
EXPORT volatile u32 env_fade_frames;

/* What 0x8002315a..0x8002316a leaves in r6: stock's R x 144000, or the FINE release x 127 (the code
 * after it divides by 127 and sizes the key-up release from that, a FINE release under 64 frames being
 * stock's 1.3 ms declick), or a re-hit's fade x 127. */
EXPORT u32 env_release_r6(const u8 *voice) {
    if ((u32)voice == env_fade_voice)
        return env_fade_frames * 127u;
    u32 r6 = *(const u32 *)(voice + V_R) * 144000u;
    s32 i = voice_of((u32)voice + ENV_AT);
    if (i >= 0) {
        const struct env_shape *sh = &env_voices[i].sh[env_voices[i].cur];
        if (sh->on && sh->fine)
            r6 = sh->rel * 127u;
    }
    return r6;
}

/* The jump at 0x8002315a: r4 is the voice, r0 the position just returned (kept), r1 and r2 free. */
__attribute__((naked)) EXPORT void env_release(void) {
    __asm__ volatile(
        "push {r0, r3}\n\t"
        "mov r0, r4\n\t"
        "bl env_release_r6\n\t"
        "mov r6, r0\n\t"
        "pop {r0, r3}\n\t"
        "movw r12, #0x316b\n\t"
        "movt r12, #0x8002\n\t"
        "bx r12\n\t");
}

/* ---------------------------------------------------------------- the re-hit */

#define V_DECLICK 0x1439C            /* voice: a declick pending (the stop's) */
#define V_REL 0x143AC                /* voice: the release, in 64-frame blocks: total, then left (+0x143b0) */
#define STOP_DECLICK ((s32 (*)(u32, s32))0x80024581u)  /* the re-hit / steal stop: 1 = it started the declick */
#define NOTE_OFF ((s32 (*)(u32))0x80023119u)           /* the key-up release: 1 = started (env_release sizes it) */
#define REHIT_RET 0x800D6C0Du        /* the voice manager stopping a pad's voices for a new hit (chromatic: the
                                        same note, or every note when chromatic is mono) */
#define REHIT_LOOP_RET 0x800D6959u   /* the same, for a looping chromatic note hit again with HOLD down */

/* 0x80024580 for the stop 0x80094168 (lr: who asked it to stop the voice; wait: the new voice needs this slot,
 * so stock waits for the declick). A re-hit of a FADE pad's sounding voice, with free slots for the new one,
 * gets the key-up release over the fade instead of the 1.3 ms declick: the voice keeps its slot until the
 * release ends it, and the new voice takes a free one. A voice already releasing goes on, as stock lets a
 * panel pad's. Anything else, a fade under 64 frames, or nothing left to play: stock's declick. Returns what
 * 0x80024580 does: 1 when it started the declick, 0 when the voice is left alone. */
EXPORT s32 env_retrig_c(u32 voice, u32 wait, u32 lr) {
    u32 pad = *(const u32 *)(voice + V_PAD);
    if (!wait && (lr == REHIT_RET || lr == REHIT_LOOP_RET) && pad < PADS && setting(pad, B_RETRIG) == 1 &&
        !*(volatile s32 *)(voice + V_DECLICK)) {
        volatile s32 *rel = (volatile s32 *)(voice + V_REL);
        if (rel[1] >= 1)
            return 0;
        s32 total = rel[0], left = rel[1];
        env_fade_frames = env_fine_frames[setting(pad, B_FADE) & 127];
        env_fade_voice = voice;
        s32 started = NOTE_OFF(voice);
        env_fade_voice = 0;
        if (started && rel[1] >= 1)
            return 0;
        rel[0] = total;
        rel[1] = left;
    }
    return STOP_DECLICK(voice, 0);
}

/* The call at 0x8009424e (movs r1, #0; bl 0x80024580; eor r7, r0, #1 displaced): r0 is the voice, r4 the slot,
 * r5 the stop's wait flag, and its caller's return address is at sp + 0x24 (push of five, sub sp, #0x14). Back
 * with r7 = result ^ 1, as the eor leaves it; r0-r3 and r12 are free (the unlock comes next). */
__attribute__((naked)) EXPORT void env_retrig(void) {
    __asm__ volatile(
        "ldr r2, [sp, #0x24]\n\t"
        "mov r1, r5\n\t"
        "push {r3, lr}\n\t"
        "bl env_retrig_c\n\t"
        "pop {r3, lr}\n\t"
        "eor r7, r0, #1\n\t"
        "bx lr\n\t");
}

/* ---------------------------------------------------------------- the ENVELOPE page */

#define TAP_MS 1000          /* a longer SHIFT hold is not a tap */
#define SAVE_MS 1000         /* quiet time before command 0xD */
#define BUILT_IN 3           /* pages 2-4; page 1 is stock's */
#define MORE_PAGES 4         /* room for later stages' pages */

/* The screen (128 x 64), laid out as stock's ENVELOPE page draws it: rows 0-7 the CTRL 1-3 labels (drawn in
 * the static layer too, which stock copies back over the screen), 8-16 their values, 17-32 the graph (y 32 =
 * silent, y 17 = full level, x 0-127 = START-END), 49-57 the static S and E marks (x 4-10, 117-123) around the
 * pad name at (64, 53). */
#define LABEL_Y 2
#define VALUE_Y 10
#define GRAPH_TOP 17
#define GRAPH_ZERO 32
#define NAME_Y 53
#define WHITE 0xFFFFFFu
#define FONT_ID 0x1D

#define STOCK_DRAW ((void (*)(void *))0x800F5F01u)       /* ENVELOPE redraw: values, graph, pad name */
#define STOCK_PAD ((void (*)(void *))0x800F5A61u)        /* ENVELOPE pad change: START/END again, redraw */
#define CTX_INIT ((void (*)(void *, u32))0x800D88E1u)    /* (context memory, surface): a context on it */
#define CTX_FREE ((void (*)(void *))0x800D8921u)
#define COLOR ((void (*)(u32, u32, u32))0x800D8019u)     /* (context, foreground, background) */
#define FILL ((void (*)(u32, const s32 *))0x800CE511u)   /* (context, x0 y0 x1 y1 inclusive) in the foreground */
#define FONT ((void (*)(u32, s32))0x800D80D9u)
#define TEXT ((void (*)(u32, s32, s32, const char *))0x800D4FA1u)   /* centered on x, top at y */
#define LINE ((void (*)(u32, const s32 *, const s32 *))0x800C0661u)  /* (context, {x, y}, {x, y}) */
#define PAGE_CTX(page) (*(u32 *)((u8 *)(page) + 0x34))       /* the page's context on the screen */
#define PAGE_LAYER(page) (*(u32 *)((u8 *)(page) + 0xC00))    /* its static layer's surface */
#define PAGE_START(page) (*(s32 *)((u8 *)(page) + 0x1A70))   /* START and END as the page read them */
#define PAGE_END(page) (*(s32 *)((u8 *)(page) + 0x1A74))
#define PAGE_LAST_PAD(page) (*(s32 *)((u8 *)(page) + 0x1A78))
#define RECORD(pad) ((const u32 *)(CSMPLPRM + 0xD0u + (pad) * 0xACu))  /* the pad record */
#define R_LOOP (0x14 / 4)    /* LOOP */
#define R_PLAY (0x3C / 4)    /* PLAY: bit 0 reverse (the fill takes the reverse charge for 1 and 3) */
#define P_HOLD 0x7E

enum { SH_ARMING, SH_UP, SH_DOWN };

/* A page after the stock one: its name, its CTRL 1-3 labels, and what a turn does and shows. Later stages
 * add theirs to env_more_pages[] (a pointer each, 0 = none); they come after MODE, in order. */
struct env_page {
    const char *name;                                    /* the bottom line: "A-1 SHAPE 2/4" */
    const char *label[3];                                /* the top line ("" none) */
    void (*value)(u32 pad, u32 ctrl, char *out);         /* CTRL ctrl's value as text, out[16] */
    void (*turn)(u32 pad, u32 ctrl, s32 raw);            /* CTRL ctrl turned to raw (0-127) */
    void (*graph)(u32 ctx, u32 pad, s32 start, s32 end); /* its own graph in rows 17-32; 0: the amplitude */
};

EXPORT const struct env_page *volatile env_more_pages[MORE_PAGES];

struct env_ui_state {
    u8 page;             /* 0 stock A-H-R, 1 SHAPE, 2 DECAY, 3 MODE, then env_more_pages */
    u8 shift;            /* SH_*: ARMING until SHIFT has been seen up on this page */
    u8 used;             /* this SHIFT press touched something else */
    u8 dirty;            /* a change not yet saved */
    s32 shift_pad;
    u32 held_ms, quiet_ms;
    u32 saves;           /* command 0xD posts, since boot */
    u8 keys[KEY_BYTES];  /* the other keys at the last tick SHIFT was up */
    u8 labels;           /* the page whose labels are on the screen */
    u8 bottom;           /* the screen shows our bottom line */
    u32 draws;           /* screens drawn, since boot */
    u8 asking;           /* DEL pressed: 1 + the apply mode it reaches (pad, group, bank) until the next key */
};

EXPORT struct env_ui_state env_ui;
EXPORT char env_text[48];

static const char *const curve_names[4] = {"LIN", "EXP", "LOG", "S"};
static const char *const stock_labels[3] = {"C1:ATTACK", "C2:HOLD", "C3:RELEASE"};
static const s32 column[3] = {22, 63, 105};

static char *put(char *p, const char *s) {
    while (*s)
        *p++ = *s++;
    return p;
}

static void put0(char *p, const char *s) {
    *put(p, s) = 0;
}

static char *number(char *p, u32 v) {
    char d[10];
    u32 n = 0;
    do {
        d[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v);
    while (n)
        *p++ = d[--n];
    return p;
}

static char *time_text(char *p, u32 f) {
    u32 t = (f * 10 + 24) / 48;                 /* tenths of a ms */
    if (!f)
        return put(p, "0ms");
    if (t < 100) {
        p = number(p, t / 10);
        *p++ = '.';
        *p++ = (char)('0' + t % 10);
        return put(p, "ms");
    }
    u32 ms = (t + 5) / 10;
    if (ms < 1000)
        return put(number(p, ms), "ms");
    u32 cs = (ms + 5) / 10;                     /* hundredths of a second */
    p = number(p, cs / 100);
    *p++ = '.';
    *p++ = (char)('0' + cs / 10 % 10);
    *p++ = (char)('0' + cs % 10);
    return put(p, "s");
}

static char *pad_name(char *p, u32 pad) {       /* as stock's screen: A-1 .. J-16 */
    *p++ = (char)('A' + pad / 16);
    *p++ = '-';
    return number(p, pad % 16 + 1);
}

static s32 page_pad(void *page) {
    return ((s32 (*)(void *))((*(u32 **)page)[0x14C / 4]))(page);
}

static u32 protected(u32 pad) {
    return ((s32 (*)(u32, s32, s32))((*(u32 **)PROJECT)[2]))(PROJECT, 0x17 + (s32)(pad >> 4), -1) != 0;
}

/* the current pad, then the pads stock's apply 0x800f5df0 reaches: COPY held, the other pads of its
 * (non-zero) mute group; REMAIN held, the rest of its bank; protected banks never; and, as for stock's
 * setter, only pads holding a sample it edits */
static u32 targets_in(u32 pad, u8 *out, u32 mode) {
    u32 n = 0;
    out[n++] = (u8)pad;
    if (mode == 1) {
        s32 group = GETTER(CSMPLPRM, P_MUTE, (s32)pad);
        if (group)
            for (u32 p = 0; p < PADS; p++)
                if (p != pad && !protected(p) && GETTER(CSMPLPRM, P_MUTE, (s32)p) == group && EDITABLE((s32)p))
                    out[n++] = (u8)p;
    } else if (mode == 2) {
        for (u32 p = pad & ~15u; p < (pad & ~15u) + 16; p++)
            if (p != pad && !protected(p) && EDITABLE((s32)p))
                out[n++] = (u8)p;
    }
    return n;
}

static u32 targets(u32 pad, u8 *out) {
    return targets_in(pad, out, (u32)APPLY_MODE);
}

static void changed(u32 pad) {
    u8 *b = ext(pad);
    u32 any = 0;
    for (u32 i = B_FLAGS; i < B_VERSION; i++)
        any |= b[i];
    b[B_VERSION] = any ? 1 : 0;
    FANOUT(SMPLMGR, (s32)pad, P_ATK, GETTER(CSMPLPRM, P_ATK, (s32)pad));
    EDITED = 1;
    env_ui.dirty = 1;
    env_ui.quiet_ms = 0;
}

static void save(void) {
    env_ui.dirty = 0;
    env_ui.saves++;
    POST(0xD, 1, 0);
}

/* For later stages' pages (env_more_pages), which keep their own bytes: the pads a turn reaches (out[160]), and
 * a change made (stock's Edited flag; the save 1 s after the last change, or when the page closes). */
EXPORT u32 env_targets(u32 pad, u8 *out) {
    return targets(pad, out);
}

EXPORT void env_touched(void) {
    EDITED = 1;
    env_ui.dirty = 1;
    env_ui.quiet_ms = 0;
}

/* DEL, then VALUE: every envelope byte of the pad and of the pads mode reaches back to 0 (stock), but note
 * repeat's; the pads' voices recompute (stage 2's settings go with them) and the save follows */
static void reset(u32 pad, u32 mode) {
    u8 list[PADS];
    u32 n = targets_in(pad, list, mode);
    for (u32 k = 0; k < n; k++) {
        u8 *b = ext(list[k]);
        u32 any = 0;
        for (u32 i = B_FLAGS; i < B_END; i++)
            if (i != B_REPEAT) {
                any |= b[i];
                b[i] = 0;
            }
        if (any)
            changed(list[k]);
    }
}

/* FINE on for a pad: keep its fine index while the stock field still holds that index's nearest stock
 * value, else take the one nearest the stock time; the stock field then holds the index's nearest value */
static void fine_on(u32 pad, u32 byte, s32 param) {
    u8 *b = ext(pad);
    s32 stock = GETTER(CSMPLPRM, param, (s32)pad);
    u32 i = b[byte] & 127;
    if ((u32)stock > 127)
        stock = 0;
    if (env_fine_stock[i] != stock)
        i = env_stock_fine[stock];
    b[byte] = (u8)i;
    if (env_fine_stock[i] != stock)
        SETTER(CSMPLPRM, param, env_fine_stock[i], (s32)pad);
}

/* a turn on pages 2-4: (byte, mask, value) for the current pad and its targets */
static void store(u32 pad, u32 byte, u32 mask, u32 value) {
    u8 list[PADS];
    u32 n = targets(pad, list);
    for (u32 k = 0; k < n; k++) {
        u32 p = list[k];
        u8 *b = ext(p);
        u32 old = b[byte], now = (old & ~mask) | (value & mask);
        if (now == old)
            continue;
        if (byte == B_FLAGS && (now & ~old & F_FINE)) {
            fine_on(p, B_ATK, P_ATK);
            fine_on(p, B_REL, P_REL);
        }
        b[byte] = (u8)now;
        changed(p);
    }
}

static u32 zone(s32 raw, u32 n) {
    u32 v = (u32)(raw < 0 ? 0 : raw > 127 ? 127 : raw);
    return v * n >> 7;
}

/* ---- the pages after the stock one */

static void shape_value(u32 pad, u32 ctrl, char *out) {
    if (ctrl == 2)                       /* TIME is VALUE press on page 1 */
        *out = 0;
    else
        put0(out, curve_names[setting(pad, B_CURVES) >> (ctrl == 1 ? 0 : 4) & 3]);
}

static void shape_turn(u32 pad, u32 ctrl, s32 raw) {
    if (ctrl != 2)
        store(pad, B_CURVES, 3u << (ctrl == 1 ? 0 : 4), zone(raw, 4) << (ctrl == 1 ? 0 : 4));
}

static void decay_value(u32 pad, u32 ctrl, char *out) {
    u32 dec = setting(pad, B_FLAGS) & F_ADSR ? setting(pad, B_DEC) & 127 : 0, sus = setting(pad, B_SUS);
    if (ctrl == 1) {
        if (dec)
            *time_text(out, env_fine_frames[dec]) = 0;
        else
            put0(out, "OFF");
    } else if (ctrl == 2) {
        *put(number(out, sus > 100 ? 100 : sus), "%") = 0;
    } else {
        put0(out, curve_names[setting(pad, B_CURVES) >> 2 & 3]);
    }
}

static void decay_turn(u32 pad, u32 ctrl, s32 raw) {
    if (ctrl == 1) {
        u32 v = zone(raw, 128);
        store(pad, B_DEC, 0xFF, v);
        store(pad, B_FLAGS, F_ADSR, v ? F_ADSR : 0);
    } else if (ctrl == 2) {
        store(pad, B_SUS, 0xFF, zone(raw, 101));
    } else {
        store(pad, B_CURVES, 3u << 2, zone(raw, 4) << 2);
    }
}

static void mode_value(u32 pad, u32 ctrl, char *out) {
    u32 f = setting(pad, B_FLAGS), fade = setting(pad, B_RETRIG) == 1 ? setting(pad, B_FADE) & 127 : 0;
    if (ctrl == 2) {
        if (fade)
            *time_text(out, env_fine_frames[fade]) = 0;
        else
            put0(out, "CUT");
    } else {
        put0(out, ctrl == 1 ? (f & F_ONCE ? "FIRST" : "EVERY") : f & F_REV ? "TIME" : "MIRROR");
    }
}

static void mode_turn(u32 pad, u32 ctrl, s32 raw) {
    if (ctrl == 1) {
        store(pad, B_FLAGS, F_ONCE, zone(raw, 2) ? F_ONCE : 0);
    } else if (ctrl == 2) {
        u32 v = zone(raw, 128);
        store(pad, B_FADE, 0xFF, v);
        store(pad, B_RETRIG, 0xFF, v ? 1 : 0);
    } else {
        store(pad, B_FLAGS, F_REV, zone(raw, 2) ? F_REV : 0);
    }
}

static const struct env_page built_in[BUILT_IN] = {
    {"SHAPE", {"C1:ATTACK", "", "C3:RELEASE"}, shape_value, shape_turn, 0},
    {"DECAY", {"C1:DECAY", "C2:SUSTAIN", "C3:CURVE"}, decay_value, decay_turn, 0},
    {"MODE", {"C1:LOOP", "C2:RETRIG", "C3:REVERSE"}, mode_value, mode_turn, 0},
};

static u32 page_count(void) {
    u32 n = 1 + BUILT_IN;
    for (u32 i = 0; i < MORE_PAGES; i++)
        if (env_more_pages[i])
            n++;
    return n;
}

static u32 page_now(void) {
    return env_ui.page < page_count() ? env_ui.page : 0;
}

/* page n's description; 0 for the stock page */
static const struct env_page *page_at(u32 n) {
    if (!n)
        return 0;
    if (n <= BUILT_IN)
        return &built_in[n - 1];
    n -= BUILT_IN + 1;
    for (u32 i = 0; i < MORE_PAGES; i++)
        if (env_more_pages[i] && !n--)
            return env_more_pages[i];
    return 0;
}

/* ---- drawing, with stock's own calls on the page's context */

static void fill(u32 ctx, s32 x0, s32 y0, s32 x1, s32 y1) {
    s32 r[4] = {x0, y0, x1, y1};
    COLOR(ctx, 0, WHITE);
    FILL(ctx, r);
    COLOR(ctx, WHITE, 0);
}

static void text(u32 ctx, s32 x, s32 y, const char *s) {
    if (*s) {
        FONT(ctx, FONT_ID);
        TEXT(ctx, x, y, s);
    }
}

static void label_row(u32 ctx, const char *const *label) {
    fill(ctx, 0, 0, 127, 7);
    for (u32 k = 0; k < 3; k++)
        text(ctx, column[k], LABEL_Y, label[k]);
}

/* the labels on the screen and in the static layer (stock copies that back over the screen) */
static void labels(void *page, const char *const *label) {
    u32 local[0x30] __attribute__((aligned(8)));     /* a context: stock's own label pass gives it 0xb4 */
    label_row(PAGE_CTX(page), label);
    CTX_INIT(local, PAGE_LAYER(page));
    label_row((u32)local, label);
    CTX_FREE(local);
}

/* the level at evaluated position q, as the applicators compute it for that frame */
static s32 level_at(const struct env_shape *sh, u32 mode, u32 q) {
    struct run g;
    segment(sh, mode, q, &g);
    if (g.kind == K_ZERO)
        return 0;
    if (g.kind == K_UNITY)
        return ONE;
    if (g.kind == K_CONST)
        return g.base;
    u32 r, ph = g.len > 1 ? frac(q - g.lo, g.len, &r) : 0;
    return g.base + ((g.scale * (s32)curve(g.t, ph)) >> 15);
}

/* The pad's envelope as the voices will play it, from the page's START/END and the pad's settings; 0 if
 * it is stock's (then stock's graph stays). */
static u32 graph_shape(void *page, u32 pad, struct env_shape *sh) {
    s32 s = PAGE_START(page), len = PAGE_END(page) - s;
    u32 a = (u32)GETTER(CSMPLPRM, P_ATK, (s32)pad), h = (u32)GETTER(CSMPLPRM, P_HOLD, (s32)pad);
    u32 r = (u32)GETTER(CSMPLPRM, P_REL, (s32)pad), blk[11];
    sh->on = 0;
    if (len <= 0 || a > 127 || r > 127 || h > 100)
        return 0;
    blk[0] = (u32)len;                                  /* the block the recompute would write */
    blk[2] = (u32)s;
    blk[4] = (u32)s + a * 144000u / 127;
    blk[6] = (u32)s + h * ((u32)len / 100) + h * ((u32)len % 100) / 100;
    blk[10] = r * 144000u / 127;
    struct env_call c = {(u8 *)blk, (u32)s, (u32)len, (s32)a, (s32)h, (s32)r, 2, 0, -1, (s32)pad};
    shape(sh, &c);
    return sh->on;
}

/* x 0-127 = START + x * length / 127; y = 32 - level * 15, up to the HOLD point (to END for a looping pad on
 * FIRST PASS); mirrored for a reverse pad on REV-TIME */
static void amp_graph(u32 ctx, void *page, u32 pad, const struct env_shape *sh) {
    u32 len = (u32)(PAGE_END(page) - PAGE_START(page)), step = len / 127, rem = len % 127;
    u32 mode = sh->once && RECORD(pad)[R_LOOP] ? 1 : 0, mirror = sh->rev && (RECORD(pad)[R_PLAY] & 1);
    s32 a[2] = {0, 0}, b[2];
    for (u32 x = 0; x < 128; x++) {
        u32 q = sh->s + x * step + x * rem / 127;
        b[0] = mirror ? 127 - (s32)x : (s32)x;
        b[1] = GRAPH_ZERO - ((level_at(sh, mode, q) * 15 + 16384) >> 15);
        if (x)
            LINE(ctx, a, b);
        a[0] = b[0];
        a[1] = b[1];
        if (!mode && q >= sh->he)
            break;
    }
}

static void value_row(u32 ctx, char v[3][16]) {
    fill(ctx, 0, 8, 127, 16);
    for (u32 k = 0; k < 3; k++)
        text(ctx, column[k], VALUE_Y, v[k]);
}

/* "A-1 SHAPE 2/4"; page 1 "A-1 AMP 1/4", or "A-1 AMP FINE 1/4" with TIME on FINE */
static void bottom_line(u32 ctx, u32 pad, const struct env_page *pg, u32 n) {
    char *p = pad_name(env_text, pad);
    const char *s = pg ? pg->name : setting(pad, B_FLAGS) & F_FINE ? "AMP FINE" : "AMP";
    *p++ = ' ';
    for (u32 k = 0; k < 12 && s[k]; k++)
        *p++ = s[k];
    *p++ = ' ';
    p = number(p, n + 1);
    *p++ = '/';
    *number(p, page_count()) = 0;
    fill(ctx, 12, 48, 115, 63);
    text(ctx, 64, NAME_Y, env_text);
}

/* the reset's question in the bottom line: "RESET A-1? press VALUE", "RESET GROUP? ...", "RESET BANK A? ..." */
static void question(u32 ctx, u32 pad) {
    char *p = put(env_text, "RESET ");
    if (env_ui.asking == 2) {
        p = put(p, "GROUP");
    } else if (env_ui.asking == 3) {
        p = put(p, "BANK ");
        *p++ = (char)('A' + pad / 16);
    } else {
        p = pad_name(p, pad);
    }
    put0(p, "? press VALUE");
    fill(ctx, 12, 48, 115, 63);
    text(ctx, 64, NAME_Y, env_text);
    env_ui.bottom = 1;
}

/* ENVELOPE page redraw (vtable + 0xCC; stock's knob, the page's first draw and env_ui_pad come here). Stock
 * draws first; page 1 with a stock pad is stock's alone. Otherwise the labels, values and bottom line are the
 * page's, and the graph is the pad's real envelope. The reset's question goes over the bottom line. */
static void draw(void *page);

EXPORT void env_ui_draw(void *page) {
    if (FX_KNOBS(page))                  /* stock draws nothing while the knobs drive the effect */
        return;
    draw(page);
    s32 pad = page_pad(page);
    if (env_ui.asking && (u32)pad < PADS)
        question(PAGE_CTX(page), (u32)pad);
}

static void draw(void *page) {
    u32 n = page_now(), ctx = PAGE_CTX(page);
    const struct env_page *pg = page_at(n);
    s32 pad = page_pad(page);
    if (env_ui.labels != n) {
        labels(page, pg ? pg->label : stock_labels);
        env_ui.labels = (u8)n;
    }
    if (env_ui.bottom) {
        fill(ctx, 12, 48, 115, 63);
        env_ui.bottom = 0;
    }
    STOCK_DRAW(page);
    env_ui.draws++;
    if ((u32)pad >= PADS)
        return;
    struct env_shape sh;
    u32 shaped = graph_shape(page, (u32)pad, &sh);
    if (pg && pg->graph) {
        fill(ctx, 0, GRAPH_TOP, 127, GRAPH_ZERO);
        pg->graph(ctx, (u32)pad, PAGE_START(page), PAGE_END(page));
    } else if (shaped) {
        fill(ctx, 0, GRAPH_TOP, 127, GRAPH_ZERO);
        amp_graph(ctx, page, (u32)pad, &sh);
    }
    char v[3][16];
    if (!pg) {                           /* page 1: stock's, with FINE times in place of the steps */
        if (shaped && sh.fine) {
            *time_text(v[0], sh.atk) = 0;
            *number(v[1], (u32)GETTER(CSMPLPRM, P_HOLD, pad)) = 0;
            *time_text(v[2], sh.rel) = 0;
            value_row(ctx, v);
        }
        bottom_line(ctx, (u32)pad, 0, 0);
        env_ui.bottom = 1;
        return;
    }
    for (u32 k = 0; k < 3; k++) {
        v[k][0] = 0;
        if (pg->value)
            pg->value((u32)pad, k + 1, v[k]);
        v[k][15] = 0;
    }
    value_row(ctx, v);
    bottom_line(ctx, (u32)pad, pg, n);
    env_ui.bottom = 1;
}

/* ENVELOPE page pad change (vtable + 0xC8): stock reads the new pad's START/END and draws; then ours */
EXPORT void env_ui_pad(void *page) {
    s32 before = PAGE_LAST_PAD(page);
    u32 asked = env_ui.asking;
    env_ui.asking = 0;
    STOCK_PAD(page);
    if (PAGE_LAST_PAD(page) != before || asked)
        env_ui_draw(page);
}

static s32 knob_stock_page(void *page, u32 pad, s32 ctrl, s32 raw) {
    if ((ctrl != 1 && ctrl != 3) || !(setting(pad, B_FLAGS) & F_FINE) || !EDITABLE((s32)pad))
        return STOCK_KNOB(page, ctrl, raw);
    u32 i = zone(raw, 128), byte = ctrl == 1 ? B_ATK : B_REL;
    u8 list[PADS];
    u32 n = targets(pad, list);
    for (u32 k = 0; k < n; k++)
        if (setting(list[k], B_FLAGS) & F_FINE)
            ext(list[k])[byte] = (u8)i;
    s32 result = STOCK_KNOB(page, ctrl, env_fine_stock[i]);   /* the stock field, apply and redraw */
    for (u32 k = 0; k < n; k++)
        if (setting(list[k], B_FLAGS) & F_FINE)
            changed(list[k]);
    return result;
}

/* ENVELOPE page knob (vtable 0x8021ec14 + 0xE4): page 1 is stock's (plus FINE); the others are the table's */
EXPORT s32 env_ui_knob(void *page, s32 ctrl, s32 raw) {
    if (env_ui.shift == SH_DOWN)
        env_ui.used = 1;
    if (env_ui.asking) {                 /* a turn cancels the reset's question, then turns */
        env_ui.asking = 0;
        env_ui_draw(page);
    }
    if ((u32)(ctrl - 1) > 2 || FX_KNOBS(page))
        return STOCK_KNOB(page, ctrl, raw);
    s32 pad = page_pad(page);
    if ((u32)pad >= PADS)
        return STOCK_KNOB(page, ctrl, raw);
    const struct env_page *pg = page_at(page_now());
    if (!pg)
        return knob_stock_page(page, (u32)pad, ctrl, raw);
    if (EDITABLE(pad) && pg->turn)       /* an empty pad: nothing, as stock's setter */
        pg->turn((u32)pad, (u32)ctrl, raw);
    env_ui_draw(page);
    return 1;
}

/* ENVELOPE page encoder turned (vtable + 0xE0; stock returns 0): VALUE (encoder 0) goes to the next page (a
 * turn right) or the previous one, round; it cancels the reset's question and is no SHIFT tap. Not while the
 * knobs drive the effect. */
EXPORT s32 env_ui_turn(void *page, s32 which, s32 delta) {
    if (which || !delta || FX_KNOBS(page))
        return 0;
    u32 count = page_count(), now = page_now();
    if (env_ui.shift == SH_DOWN)
        env_ui.used = 1;
    env_ui.asking = 0;
    env_ui.page = (u8)(delta > 0 ? (now + 1) % count : (now + count - 1) % count);
    env_ui_draw(page);
    return 1;
}

/* ENVELOPE page key press (vtable + 0xD8). DEL (stock's: nothing) asks for the reset, for the pads COPY or
 * REMAIN reach when it is pressed; VALUE then resets, any other key cancels and does what it does (EXIT only
 * cancels: the page stays). On page 1 VALUE press switches TIME (STOCK / FINE) for the pads a turn reaches, when
 * stock's press does nothing (UI_HELD clear). DEL with SHIFT held, on an empty pad or while the knobs drive the
 * effect: stock. */
EXPORT s32 env_ui_key(void *page, s32 key) {
    s32 pad = page_pad(page);
    if (env_ui.asking) {
        u32 mode = env_ui.asking - 1u;
        env_ui.asking = 0;
        if (key == KEY_VALUE && (u32)pad < PADS && EDITABLE(pad))
            reset((u32)pad, mode);
        env_ui_draw(page);
        if (key == KEY_VALUE || key == KEY_EXIT || key == KEY_DEL)
            return 1;
        return STOCK_KEY(page, key);
    }
    if (key == KEY_DEL && !(KEYS[KEY_SHIFT >> 3] >> (KEY_SHIFT & 7) & 1) && (u32)pad < PADS && EDITABLE(pad) &&
        !FX_KNOBS(page)) {
        u32 mode = (u32)APPLY_MODE;
        if (mode > 2 || (mode == 1 && !GETTER(CSMPLPRM, P_MUTE, pad)))
            mode = 0;
        env_ui.asking = (u8)(1 + mode);
        env_ui_draw(page);
        return 1;
    }
    if (key == KEY_VALUE && !page_now() && (u32)pad < PADS && EDITABLE(pad) && !FX_KNOBS(page) && !UI_HELD()) {
        store((u32)pad, B_FLAGS, F_FINE, setting((u32)pad, B_FLAGS) & F_FINE ? 0 : F_FINE);
        env_ui_draw(page);
        return 1;
    }
    return STOCK_KEY(page, key);
}

/* ENVELOPE page tick (vtable + 0xD0, stock an empty function), every 50 ms with ms = 50. A SHIFT tap is a
 * press and release within TAP_MS with no other key pressed or let go, no knob turned and no pad change in
 * between (a key bit that never changes, held or stuck, doesn't count). */
EXPORT void env_ui_poll(void *page, s32 ms) {
    if ((u32)(ms - 1) >= 1000)
        ms = 50;
    u32 down = KEYS[KEY_SHIFT >> 3] >> (KEY_SHIFT & 7) & 1, others = 0;
    u8 now[KEY_BYTES];
    for (u32 i = 0; i < KEY_BYTES; i++) {
        now[i] = KEYS[i] & (i == KEY_SHIFT >> 3 ? (u8)~(1u << (KEY_SHIFT & 7)) : 0xFFu);
        others |= now[i] ^ env_ui.keys[i];
    }
    if (env_ui.shift == SH_ARMING) {
        if (!down)
            env_ui.shift = SH_UP;
    } else if (env_ui.shift == SH_UP) {
        if (down) {
            env_ui.shift = SH_DOWN;
            env_ui.used = others != 0;
            env_ui.held_ms = 0;
            env_ui.shift_pad = page_pad(page);
        }
    } else {
        env_ui.held_ms += (u32)ms;
        if (others || env_ui.held_ms > TAP_MS || page_pad(page) != env_ui.shift_pad)
            env_ui.used = 1;
        if (!down) {
            env_ui.shift = SH_UP;
            if (!env_ui.used) {
                env_ui.page = (u8)((page_now() + 1) % page_count());
                env_ui_draw(page);
            }
        }
    }
    if (env_ui.shift != SH_DOWN)
        for (u32 i = 0; i < KEY_BYTES; i++)
            env_ui.keys[i] = now[i];
    if (env_ui.dirty && (env_ui.quiet_ms += (u32)ms) >= SAVE_MS)
        save();
}

/* ENVELOPE page deleting destructor (vtable + 0x04): the page is closing */
EXPORT void *env_ui_leave(void *page) {
    if (env_ui.dirty)
        save();
    env_ui.page = 0;
    env_ui.labels = 0;
    env_ui.bottom = 0;
    env_ui.asking = 0;
    env_ui.shift = SH_ARMING;
    return STOCK_LEAVE(page);
}
