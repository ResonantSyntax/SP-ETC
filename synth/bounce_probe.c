/* Bounce in place, stage 1: measure the round trip L through the effects chip (BMC).
 *
 * The audio task (0x1cf78) renders each TX block of 64 frames (mixer 0x1c2d0) and hands
 * each received RX block to the recorder feed (0x1ca80). Two bridges call probe_tx after
 * the mixer and probe_rx after the feed, so both counters advance in the same task:
 *
 *   TX frame = 64 * TX blocks rendered since boot + frame within the block
 *   RX frame = 64 * RX blocks received since boot + frame within the block
 *   L        = RX frame of the return's first captured frame above -48 dBFS
 *            - TX frame of the sound's first rendered frame above -48 dBFS
 *
 * It measures only while the RESAMPLE page's recorder is in standby or recording
 * (settings param 0x36 == 1, recorder state 1 or 2). Every sound that starts after at
 * least TX_QUIET frames of TX silence is measured, so one take can hold many runs. The
 * result goes up in a popup raised from the UI's popup tick (probe_ui). Measurement only:
 * no audio, take, setting or file is changed.
 *
 * Popup, valid run:      L=<L> #<run> W<words 2/3>
 *                        <lowest L>-<highest L> P<DMA phase> D<block offset> V<lead>
 * Popup, no valid L:     L=?? #<run> / RX not quiet   or   L=-- #<run> / no return
 *
 *   run    measurements in this take (a take = recorder standby to idle)
 *   lo-hi  the range of the take's valid L values
 *   W      the same onset measured on RX words 2/3 ("--" silent, "??" not quiet first)
 *   P      eDMA phase: TX line 3 read position minus RX write position, frames mod 128
 *   D      RX blocks minus TX blocks counted since boot
 *   V      TX frames from the start of the block in which a pad voice started to the
 *          TX onset ("-" when no voice started for it, e.g. a Sound Generator note)
 */
typedef unsigned int u32;
typedef int s32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define EXPORT __attribute__((used))

#define FRAMES 64
#define STEM_SLOTS 14                                  /* mixer stem buffer: 14 int32 per frame */
#define VOICE_SLOTS 32
#define STEMS ((const volatile s32 *)0x202AD3A0u)       /* clipped to 20 bits by the mixer */
#define CAPTURE ((const volatile s16 *)0x202AD0A0u)     /* the 64 stereo frames the recorder gets */
#define SLOT_TABLE 0x202AE1A0u                          /* 32 voice slots, word 0 = voice object */
#define SLOT_BYTES 0x58u
#define VOICE_STREAM 0x14268u                           /* the renderer's stream pointer */
#define REC_STATE (*(const volatile u8 *)0x82E0E755u)   /* CSampleRec +0x39: 1 standby, 2 recording */
#define REC_MODE (*(const volatile s32 *)0x82E011CCu)   /* settings param 0x36: 1 = RESAMPLE page */
#define TX3_SADDR (*(const volatile u32 *)0x400E9060u)  /* eDMA TCD3 source: TX line 3 (the stems) */
#define RX_DADDR (*(const volatile u32 *)0x400E9090u)   /* eDMA TCD4 destination: RX */
#define TX3_BUFFER 0x20006000u                          /* 2 x 64 frames of 64 bytes */
#define RX_BUFFER 0x20008000u                           /* 2 x 64 frames of 32 bytes */
#define POPUP ((void (*)(const char *, int))0x800D3FF1u)
#define POPUP_TIMER (*(const volatile s32 *)0x805922B4u) /* ms left of the popup on screen */

#define TX_THRESHOLD 2048          /* about -48 dBFS of the 20-bit stems */
#define RX_THRESHOLD 128           /* about -48 dBFS of the 16-bit capture */
#define TX_QUIET 1024              /* TX frames below the threshold before an onset counts */
#define RX_QUIET 256               /* RX frames below the threshold before the return's onset */
#define WORDS23_WAIT 4800          /* frames to keep watching words 2/3 after the return */
#define RX_TIMEOUT 48000           /* 1 s without a return */
#define LEAD_LIMIT 24000           /* a voice start more than 0.5 s before the onset is not its own */
#define POPUP_MS 3000
#define SATURATE 0x40000000u

enum { OFF, WAIT_TX, WAIT_RX };
enum { OK, NOT_QUIET, NO_RETURN };
enum { FOUND = 1, BUSY = 2 };

struct probe {
    u32 tx_blocks, rx_blocks;       /* blocks seen since boot */
    u32 phase;
    u32 tx_quiet, rx_quiet, w_quiet;
    u32 voices;                     /* voice slots playing after the last TX block */
    s32 voice_block;                /* TX block in which a voice last started, -1 none */
    u32 tx_onset;
    s32 lead;
    u32 rx_onset, rx_flags, rx_at;  /* rx_at = RX frames seen at the return */
    u32 w_onset, w_flags;
    u32 rx_seen;                    /* RX frames seen since the TX onset */
    u32 runs, valid;
    s32 lo, hi;
    /* the last result, published by bumping seq */
    u32 r_status, r_run, r_w_flags;
    s32 r_l, r_lo, r_hi, r_w, r_lead, r_d, r_p;
    u32 seq, shown;
};

EXPORT volatile struct probe probe;
EXPORT char probe_text[64];
EXPORT const volatile u16 *volatile probe_rx_buffer;  /* the rx bridge keeps the RX half here */

/* |x| > t, for |x| < 2^31 - t */
#define LOUD(x, t) ((u32)((s32)(x) + (t)) > 2u * (t))

static u32 count(u32 v) { return v < SATURATE ? v + 1 : v; }

/* Same test as the renderer (0x14b88) makes before it renders a voice, on the same slots. */
static u32 active_voices(void) {
    u32 mask = 0;
    for (u32 i = 0; i < VOICE_SLOTS; i++) {
        u32 voice = *(const volatile u32 *)(SLOT_TABLE + i * SLOT_BYTES);
        if (!voice)
            continue;
        u32 stream = *(const volatile u32 *)(voice + VOICE_STREAM);
        if (stream && *(const volatile u8 *)(stream + 1) != 0xFF)
            mask |= 1u << i;
    }
    return mask;
}

/* After the mixer has rendered TX block tx_blocks into the stem buffer. */
EXPORT void probe_tx(void) {
    u32 block = probe.tx_blocks;
    probe.tx_blocks = block + 1;
    u32 state = REC_STATE;
    if (REC_MODE != 1 || (state != 1 && state != 2)) {
        probe.phase = OFF;
        return;
    }
    if (probe.phase == OFF) {                   /* a take begins: fresh run count and range */
        probe.phase = WAIT_TX;
        probe.tx_quiet = probe.rx_quiet = probe.w_quiet = 0;
        probe.runs = probe.valid = 0;
        probe.lo = probe.hi = 0;
        probe.voices = active_voices();         /* voices already playing are not starts */
        probe.voice_block = -1;
        return;
    }
    u32 now = active_voices();
    if (now & ~probe.voices)
        probe.voice_block = (s32)block;
    probe.voices = now;
    u32 quiet = probe.tx_quiet;
    u32 waiting = probe.phase == WAIT_TX;
    const volatile s32 *frame = STEMS;
    for (u32 f = 0; f < FRAMES; f++, frame += STEM_SLOTS) {
        u32 s = 0;
        while (s < STEM_SLOTS && !LOUD(frame[s], TX_THRESHOLD))
            s++;
        if (s == STEM_SLOTS) {
            quiet = count(quiet);
            continue;
        }
        if (waiting && quiet >= TX_QUIET) {
            u32 onset = block * FRAMES + f;
            s32 vb = probe.voice_block;
            u32 lead = onset - (u32)vb * FRAMES;
            probe.tx_onset = onset;
            probe.lead = vb >= 0 && lead < LEAD_LIMIT ? (s32)lead : -1;
            probe.voice_block = -1;
            probe.rx_flags = probe.w_flags = 0;
            probe.rx_seen = 0;
            probe.phase = WAIT_RX;
            waiting = 0;
        }
        quiet = 0;
    }
    probe.tx_quiet = quiet;
}

static void publish(u32 status) {
    u32 run = probe.runs + 1;
    s32 l = (s32)(probe.rx_onset - probe.tx_onset);
    probe.runs = run;
    if (status == OK) {
        if (!probe.valid || l < probe.lo)
            probe.lo = l;
        if (!probe.valid || l > probe.hi)
            probe.hi = l;
        probe.valid++;
    }
    /* D and P, read at the same point of the task's cycle every time (the RX block) */
    u32 t1, r, t2, tries = 0;
    do {
        t1 = (TX3_SADDR - TX3_BUFFER) >> 6;
        r = (RX_DADDR - RX_BUFFER) >> 5;
        t2 = (TX3_SADDR - TX3_BUFFER) >> 6;
    } while (t1 != t2 && ++tries < 4);
    probe.r_status = status;
    probe.r_run = run;
    probe.r_l = l;
    probe.r_lo = probe.lo;
    probe.r_hi = probe.hi;
    probe.r_w_flags = probe.w_flags;
    probe.r_w = (s32)(probe.w_onset - probe.tx_onset);
    probe.r_lead = probe.lead;
    probe.r_d = (s32)(probe.rx_blocks - probe.tx_blocks);
    probe.r_p = (s32)((t1 - r) & 127);
    __asm__ volatile("" ::: "memory");
    probe.seq = probe.seq + 1;
    probe.phase = WAIT_TX;
}

/* After the recorder feed has copied RX block rx_blocks. probe_rx_buffer = the RX DMA half
 * it read: 64 frames of 16 halfwords; the feed copies words 1/0 of the pair into CAPTURE. */
EXPORT void probe_rx(void) {
    const volatile u16 *raw = probe_rx_buffer;
    u32 block = probe.rx_blocks;
    probe.rx_blocks = block + 1;
    u32 phase = probe.phase;
    if (phase == OFF)
        return;
    u32 rq = probe.rx_quiet, wq = probe.w_quiet;
    u32 rx_flags = probe.rx_flags, w_flags = probe.w_flags;
    u32 waiting = phase == WAIT_RX;
    const volatile s16 *cap = CAPTURE;
    const volatile s16 *w23 = (const volatile s16 *)raw + 2;
    for (u32 f = 0; f < FRAMES; f++, cap += 2, w23 += 16) {
        u32 a = LOUD(cap[0], RX_THRESHOLD) | LOUD(cap[1], RX_THRESHOLD);
        u32 w = LOUD(w23[0], RX_THRESHOLD) | LOUD(w23[1], RX_THRESHOLD);
        if (waiting) {
            if (a && !(rx_flags & FOUND)) {
                probe.rx_onset = block * FRAMES + f;
                probe.rx_at = probe.rx_seen + f;
                rx_flags = FOUND | (rq < RX_QUIET ? BUSY : 0);
            }
            if (w && !(w_flags & FOUND)) {
                probe.w_onset = block * FRAMES + f;
                w_flags = FOUND | (wq < RX_QUIET ? BUSY : 0);
            }
        }
        rq = a ? 0 : count(rq);
        wq = w ? 0 : count(wq);
    }
    probe.rx_quiet = rq;
    probe.w_quiet = wq;
    if (!waiting)
        return;
    probe.rx_flags = rx_flags;
    probe.w_flags = w_flags;
    u32 seen = probe.rx_seen + FRAMES;
    probe.rx_seen = seen;
    if (probe.rx_flags & FOUND) {
        if ((probe.w_flags & FOUND) || seen >= probe.rx_at + WORDS23_WAIT)
            publish(probe.rx_flags & BUSY ? NOT_QUIET : OK);
    } else if (seen >= RX_TIMEOUT) {
        publish(NO_RETURN);
    }
}

static char *put(char *o, const char *s) {
    while (*s)
        *o++ = *s++;
    return o;
}

/* At most 6 characters: the stock popup buffer (0x802468d8) holds 64 bytes. */
static char *put_int(char *o, s32 v) {
    char digits[12];
    if (v > 99999)
        v = 99999;
    if (v < -99999)
        v = -99999;
    u32 n = 0, u = v < 0 ? 0u - (u32)v : (u32)v;
    if (v < 0)
        *o++ = '-';
    do {
        digits[n++] = (char)('0' + u % 10);
        u /= 10;
    } while (u);
    while (n)
        *o++ = digits[--n];
    return o;
}

/* From the UI's popup tick (0x8006b950, elapsed ms), before the tick runs: show a new result.
 * A popup whose time runs out in this tick is closed by the tick, and closing clears any
 * pending popup, so wait one tick then. */
EXPORT void probe_ui(u32 elapsed) {
    u32 seq = probe.seq;
    if (seq == probe.shown)
        return;
    s32 left = POPUP_TIMER;
    if (left >= 1 && (u32)left <= elapsed)
        return;
    char *o = probe_text;
    u32 status = probe.r_status;
    if (status == OK) {
        u32 wf = probe.r_w_flags;
        o = put_int(put(o, "L="), probe.r_l);
        o = put_int(put(o, " #"), (s32)probe.r_run);
        o = put(o, " W");
        o = !(wf & FOUND) ? put(o, "--") : (wf & BUSY) ? put(o, "??") : put_int(o, probe.r_w);
        o = put_int(put(o, "\n"), probe.r_lo);
        o = put_int(put(o, "-"), probe.r_hi);
        o = put_int(put(o, " P"), probe.r_p);
        o = put_int(put(o, " D"), probe.r_d);
        o = put(o, " V");
        o = probe.r_lead < 0 ? put(o, "-") : put_int(o, probe.r_lead);
    } else {
        o = put(o, status == NOT_QUIET ? "L=?? #" : "L=-- #");
        o = put_int(o, (s32)probe.r_run);
        o = put(o, status == NOT_QUIET ? "\nRX not quiet" : "\nno return");
    }
    *o = 0;
    __asm__ volatile("" ::: "memory");
    if (probe.seq != seq)                       /* a newer result arrived meanwhile: next tick */
        return;
    probe.shown = seq;
    POPUP(probe_text, POPUP_MS);
}
