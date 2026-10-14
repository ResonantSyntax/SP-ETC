/* Bounce in place, stage 2: record a sample pad through its effects into an empty pad, frame-exact.
 *
 * Gesture (RESAMPLE page, recorder idle): hold RESAMPLE and tap a pad that holds a sample. A setup
 * popup names the source, the destination (the first empty pad after the source in its bank, then
 * the other banks A..J) and the mode; VALUE picks NO TAIL / TAIL / LOOP, REC starts, EXIT backs out.
 *
 * The run (UI task, from the popup tick, bnc_ui):
 *   1. pin REC length (settings 0x24) to FREE and END Snap (0x59) off, set the destination as the
 *      stock pad handler does, post ALL SOUND OFF and SEQ SOUND OFF, post standby (0x14);
 *   2. own the take: from then on the RX bridge clears the feed's enable word (0x805917c4) before
 *      each feed call, so the stock recorder gate never runs and only this module writes the take
 *      (every stock standby sets the word back to 1);
 *   3. wait for silence: RX and TX below about -72 dBFS for 200 ms, at most 10 s;
 *   4. post REC_START (0x17), then trigger the source pad;
 *   5. the audio side (bnc_tx after the mixer, bnc_rx after the recorder feed) finds T0, the TX frame
 *      that starts the source voice's first block, and writes RX frames from F0 = T0 (+ one pass in
 *      LOOP mode) to the engine's stereo writer: file frame k is RX frame F0 + k;
 *   6. the round trip L is the onset-measured value when it lies within 6 frames of the estimate
 *      (modulo 64), else the estimate: this boot's last onset-calibrated L, else 138.5 minus the
 *      eDMA phase averaged over the silence wait, the candidate nearest 75 (bounce probe T1);
 *   7. post REC_STOP (0x18); after the stock finalize, set START = F0 + L, END = START + length and
 *      the loop point = START through the stock pad setter (the stock finalize snaps START), name the
 *      pad with the run's numbers, save, and restore everything pinned.
 *
 * Windows, RX frames from F0: NO TAIL [L, L + one pass), LOOP [L, L + loop pass) with F0 one pass
 * after T0, TAIL [L, last frame above -72 dBFS], ended once the voice has stopped and 250 ms are
 * quiet (at most 30 s). The file holds L silent frames before START and a few frames after END.
 */
typedef unsigned int u32;
typedef int s32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define EXPORT __attribute__((used))
#define V8(a) (*(volatile u8 *)(a))
#define V16(a) (*(volatile u16 *)(a))
#define V32(a) (*(volatile u32 *)(a))
#define BARRIER() __asm__ volatile("" ::: "memory")

/* --- stock 5.52 (unchanged in DOOM OS ED5E and the fork's v9.46) --- */
#define FRAMES 64
#define STEM_SLOTS 14
#define VOICE_SLOTS 32
#define STEMS ((const volatile s32 *)0x202AD3A0u)       /* TX stems after the mixer, 20-bit */
#define CAPTURE ((const volatile s16 *)0x202AD0A0u)     /* the RX pair the recorder gets, 64 frames x 2 */
#define SLOT_TABLE 0x202AE1A0u
#define SLOT_BYTES 0x58u
#define VOICE_STREAM 0x14268u
#define VOICE_PAD 0x14274u
#define REC 0x82E0E71Cu                                 /* CSampleRec */
#define REC_STATE (REC + 0x39u)
#define REC_ENGINE (REC + 0x254u)
#define FEED_ON 0x805917C4u                             /* the feed calls the recorder gate when set */
#define SETTINGS 0x82E01144u
#define PROJECT 0x82E009D0u
#define SMPL 0x82E2CD08u                                /* CSmplPrm: pad parameters */
#define FILE_INFO 0x82E495E4u                           /* per pad, 36 bytes: +8 channels, +0xc data offset */
#define TARGET 0x82E0EBBCu                              /* recorder target settings */
#define TARGET_VALUES 0x80246E14u                       /* their values: +4 destination pad, +0xc stereo */
#define SYSPRM 0x82DFEED0u                              /* system parameters (Resample_Routing 0x5c) */
#define SEQ_PLAY (0x82E0D660u + 0xA5u)                  /* the two flags "Pattern is Running" tests */
#define SEQ_RUN (0x82DFFC88u + 0x2C0u)
#define LOOPER_ON (0x82E0B71Cu + 0x39u)
#define PAGE_ID 0x80245880u
#define KEY_BITS 0x80592448u                            /* key held: bit (key & 7) of [KEY_BITS + key / 8] */
#define POPUP_TIMER 0x805922B4u
#define TX3_SADDR 0x400E9060u
#define RX_DADDR 0x400E9090u
#define TX3_BUFFER 0x20006000u
#define RX_BUFFER 0x20008000u
#define DOOM_FILTER 0x6031C8F9u                         /* page 0xe's event filter before this module */

#define F_GET 0x800D94D9u       /* settings get (obj, id, idx) */
#define F_SET 0x800DD0C1u       /* settings set (obj, id, value, flag) */
#define F_PGET 0x800DDA39u      /* project get (obj, id, idx) */
#define F_PSET 0x800DED19u      /* project set (obj, id, value, idx) */
#define F_PADGET 0x800DC6B9u    /* pad get (obj, id, pad) */
#define F_PADSET 0x800DA721u    /* pad set (obj, id, value, pad) */
#define F_PADNAME 0x800CFA29u   /* pad name (obj, pad, text): 23 characters */
#define F_TSET 0x800D48E9u      /* recorder target set (obj, id, value, 0), through the command ring */
#define F_SYSGET 0x800DA011u    /* system parameter get (obj, id, -1) */
#define F_POST 0x800E25C1u      /* post a SMPL TASK command (cmd, a1, a2) */
#define F_TRIGGER 0x800CDBD1u   /* pad note (global pad, velocity, 1) */
#define F_MODAL 0x800CE421u     /* page modal state */
#define F_POPUP 0x800D3FF1u     /* popup (text, ms) */

typedef s32 (*fn1_t)(u32);
typedef s32 (*fn2_t)(u32, u32);
typedef s32 (*fn3_t)(u32, u32, u32);
typedef s32 (*fn4_t)(u32, u32, u32, u32);
#define CALL1(f, a) ((fn1_t)(f))((u32)(a))
#define CALL2(f, a, b) ((fn2_t)(f))((u32)(a), (u32)(b))
#define CALL3(f, a, b, c) ((fn3_t)(f))((u32)(a), (u32)(b), (u32)(c))
#define CALL4(f, a, b, c, d) ((fn4_t)(f))((u32)(a), (u32)(b), (u32)(c), (u32)(d))

#define KEY_REC 0x1B
#define KEY_RESAMPLE 0x1C
#define KEY_EXIT 0x22
#define KEY_SHIFT 0x2A
#define CMD_ALL_SOUND_OFF 5
#define CMD_SAVE 0xD
#define CMD_STANDBY 0x14
#define CMD_START 0x17
#define CMD_STOP 0x18
#define CMD_CANCEL 0x1A
#define CMD_SEQ_SOUND_OFF 0x2A
#define EV_KEY 5
#define EV_KEY_UP 6
#define EV_ENCODER 7
#define EV_KNOB 9
#define EV_PAD 0x10
#define EV_PAD_UP 0x11
#define EV_PAD_MORE 0x12
#define PAGE_RESAMPLE 0x0E
#define NONE 0xFFFFFFFFu

/* pad parameters; START, END and the loop point in frames of the file's data */
#define P_STATUS 0x64
#define P_START 0x67
#define P_END 0x68
#define P_LOOP 0x6B
#define P_SYNC 0x6E
#define P_LOOPPOINT 0x71
#define P_PITCH 0x73
#define P_FINE 0x74
#define P_REVERSE 0x75
#define P_SPEED 0x76
#define SPEED_100 10000

/* --- tuning --- */
#define TX_ONSET 2048           /* about -48 dBFS of the 20-bit stems (bounce probe, T1) */
#define RX_ONSET 128            /* about -48 dBFS of the 16-bit capture (bounce probe, T1) */
#define TX_QUIET 128            /* about -72 dBFS */
#define RX_QUIET 8              /* about -72 dBFS */
#define SILENCE_FRAMES 9600     /* 200 ms */
#define TAIL_QUIET 12000        /* 250 ms */
#define TAIL_CAP 1440000        /* 30 s */
#define ONSET_SEARCH 4800       /* the TX onset within 100 ms of the voice start */
#define L_MIN 8
#define L_MAX 300
#define L_ACCEPT 6              /* an onset L within this of the estimate is used */
#define L_CACHE 3               /* and within this it becomes the boot's estimate */
#define K16 2216                /* 16 x 138.5: bounce probe T1 read L - 64 D + (P mod 64) = 138 and 139 */
#define L_CENTER 75             /* T1: L was 73..78; the estimate is the candidate nearest this */
#define END_MARGIN 32
#define MIN_FILE 1000           /* the stock pad loader refuses shorter samples */
#define HIST_BLOCKS 4
#define BANKS 10
#define WAIT_STATE_MS 3000
#define WAIT_SILENCE_MS 10000
#define WAIT_VOICE_MS 1000
#define WAIT_FINAL_MS 20000
#define REFRESH_MS 250
#define POPUP_MS 1000
#define DONE_MS 2500

enum { NO_TAIL, TAIL, LOOP, MODES };
enum { A_IDLE, A_SILENCE, A_ARMED, A_RUN, A_DONE };
enum { U_IDLE, U_SETUP, U_STANDBY, U_SILENCE, U_RECSTART, U_VOICE, U_RUN, U_FINAL, U_CANCEL };
enum { M_NONE, M_DONE, M_NO_EMPTY, M_PATTERN, M_LOOPER, M_RINGING, M_FAILED, M_CANCELLED };

struct aud {
    u32 tx_blocks, rx_blocks;   /* blocks since boot */
    u32 phase;
    u32 quiet_rx, quiet_tx;
    u32 pad, mode, skip;        /* skip: frames from T0 to F0 (one pass in LOOP mode) */
    u32 measure;                /* the window is the voice's own length (NO TAIL, not at its own rate) */
    u32 armed_voices;
    u32 slot, voice;
    u32 t0, f0, fed;            /* RX frames F0 .. F0 + fed - 1 are in the take */
    u32 stop;                   /* the RX frame to stop before, 0 = not known yet */
    u32 have_l, cached;         /* L known; the estimate was this boot's calibration */
    s32 l, l_est, l_meas;
    u32 p_n;                    /* eDMA phase reads: count, first, sum of differences from the first */
    s32 p0, p_sum;
    s32 p16, d;                 /* the mean phase x 16; RX minus TX blocks */
    u32 tx_onset;               /* TX frame + 1 of the first frame above TX_ONSET, 0 = none */
    u32 scan;                   /* the next RX frame to look at for the return's onset, 0 = not started */
    u32 last_nz;                /* TX frame after the last non-silent frame while the voice played */
    u32 voice_end;              /* TX frame after the voice's last frame, 0 = still playing */
    u32 last_loud;              /* RX frame + 1 of the last frame above RX_QUIET (TAIL) */
    u32 win;                    /* the window's length, 0 = not known yet */
    u32 rx_now;                 /* RX frames seen */
    u32 fail;
    s16 hist[HIST_BLOCKS * FRAMES * 2];
};

struct ui {
    u32 state;
    u32 ms, since, shown, refresh;
    u32 src, dst, mode, modes;  /* global pads (bank * 16 + pad); modes: one bit per mode offered */
    u32 loop_src, loop_pin;     /* the source's LOOP, and whether the run changed it */
    u32 len1, len2;             /* frames: one pass, a loop pass (from the loop point) */
    u32 native;
    s32 saved_len, saved_snap, saved_bpm;
    u32 pinned;
    u32 msg;                    /* a popup to show when idle */
    u32 waits;                  /* a recorder command is pending (cancel) */
    u32 last_mode;              /* remembered for the next setup (RAM) */
    s32 cal_l;                  /* this boot's last onset-calibrated L */
    u32 cal_valid;
    u32 runs;
    /* the last finished run */
    s32 r_l, r_est, r_meas, r_p16, r_d;
    u32 r_start, r_end, r_len, r_mode, r_exact;
};

EXPORT volatile struct aud bnc_aud;
EXPORT volatile u32 bnc_own;    /* the recorder is this module's: the RX bridge clears the feed enable first */
EXPORT volatile struct ui bnc_ui_state;
EXPORT char bnc_text[64];

#define A bnc_aud
#define U bnc_ui_state

/* |x| > t, and either channel of a stereo frame */
#define LOUD(x, t) ((u32)((s32)(x) + (t)) > 2u * (t))
#define LOUD2(p, t) (LOUD((p)[0], t) || LOUD((p)[1], t))

static s32 get_setting(u32 id) { return CALL3(F_GET, SETTINGS, id, 0); }
static void set_setting(u32 id, s32 v, s32 flag) { CALL4(F_SET, SETTINGS, id, v, flag); }
static s32 pad_get(u32 id, u32 pad) { return CALL3(F_PADGET, SMPL, id, pad); }
static void pad_set(u32 id, s32 v, u32 pad) { CALL4(F_PADSET, SMPL, id, v, pad); }
static void post(u32 cmd) { CALL3(F_POST, cmd, 0, 0); }
static u32 occupied(u32 pad) { return CALL3(F_PGET, PROJECT, P_STATUS, pad) != 0; }
/* the stock key getter's own test (0x800d9f2c), read directly: the kits route the getter itself */
static u32 key_held(u32 key) { return (V8(KEY_BITS + (key >> 3)) >> (key & 7)) & 1; }

/* ---------------------------------------------------------------------------------------------
 * Audio task
 * ------------------------------------------------------------------------------------------- */

/* The renderer's own test (0x14b88), on one slot, for one pad's voice. */
static u32 voice_active(u32 slot, u32 voice, u32 pad) {
    if (!voice || V32(SLOT_TABLE + slot * SLOT_BYTES) != voice)
        return 0;
    u32 stream = V32(voice + VOICE_STREAM);
    return stream && V8(stream + 1) != 0xFF && V32(voice + VOICE_PAD) == pad;
}

static u32 active_slots(u32 pad) {
    u32 mask = 0;
    for (u32 i = 0; i < VOICE_SLOTS; i++)
        if (voice_active(i, V32(SLOT_TABLE + i * SLOT_BYTES), pad))
            mask |= 1u << i;
    return mask;
}

/* After the mixer has rendered TX block tx_blocks into the stems. */
EXPORT void bnc_tx(void) {
    u32 block = A.tx_blocks;
    A.tx_blocks = block + 1;
    u32 phase = A.phase;
    if (phase == A_IDLE || phase == A_DONE)
        return;
    const volatile s32 *frame = STEMS;
    if (phase == A_SILENCE) {
        u32 q = A.quiet_tx;
        for (u32 f = 0; f < FRAMES; f++, frame += STEM_SLOTS) {
            u32 s = 0;
            while (s < STEM_SLOTS && !LOUD(frame[s], TX_QUIET))
                s++;
            q = s == STEM_SLOTS ? q + 1 : 0;
        }
        A.quiet_tx = q;
        return;
    }
    if (phase == A_ARMED) {         /* the first block in which the source's new voice renders */
        u32 now = active_slots(A.pad) & ~A.armed_voices;
        if (!now)
            return;
        u32 slot = 0;
        while (!(now & (1u << slot)))
            slot++;
        A.slot = slot;
        A.voice = V32(SLOT_TABLE + slot * SLOT_BYTES);
        A.t0 = block * FRAMES;
        A.f0 = A.t0 + A.skip;
        A.last_nz = A.t0;
        BARRIER();
        A.phase = A_RUN;
    }
    u32 base = block * FRAMES;
    u32 live = A.voice_end == 0;
    if (!A.tx_onset && base < A.t0 + ONSET_SEARCH) {       /* the sound's first frame above -48 dBFS */
        const volatile s32 *x = STEMS;
        for (u32 i = 0; i < FRAMES * STEM_SLOTS; i++)
            if (LOUD(x[i], TX_ONSET)) {
                A.tx_onset = base + i / STEM_SLOTS + 1;
                break;
            }
    }
    if (live && A.measure) {                /* the voice's own end (NO TAIL, not at its own rate) */
        for (u32 f = 0; f < FRAMES; f++, frame += STEM_SLOTS)
            for (u32 s = 0; s < STEM_SLOTS; s++)
                if (frame[s]) {
                    A.last_nz = base + f + 1;
                    break;
                }
    }
    if (live && !voice_active(A.slot, A.voice, A.pad))     /* it rendered its last frames in this block */
        A.voice_end = !A.measure ? base + FRAMES : A.last_nz > A.t0 ? A.last_nz : A.t0 + 1;
    if (A.measure && !A.win && A.voice_end)
        A.win = A.voice_end - A.t0;
}

/* The DMA phase the bounce probe read: TX line 3 read position minus RX write position, mod 128. */
static s32 dma_phase(void) {
    u32 t1, r, t2, tries = 0;
    do {
        t1 = (V32(TX3_SADDR) - TX3_BUFFER) >> 6;
        r = (V32(RX_DADDR) - RX_BUFFER) >> 5;
        t2 = (V32(TX3_SADDR) - TX3_BUFFER) >> 6;
    } while (t1 != t2 && ++tries < 4);
    return (s32)((t1 - r) & 127);
}

/* One eDMA phase read, kept as a running mean (as differences from the first read, so the mod-128
 * wrap cannot split the mean). */
static void read_phase(void) {
    s32 p = dma_phase();
    if (!A.p_n)
        A.p0 = p;
    A.p_sum += ((p - A.p0 + 64) & 127) - 64;
    A.p_n++;
}

/* L = 138.5 - (P mod 64) + 64 n, rounded, the candidate nearest L_CENTER; p16 = 16 x the mean P. */
EXPORT s32 bnc_estimate(s32 p16) {
    s32 x16 = (K16 - p16) & 1023;
    s32 v = (x16 + 8) >> 4;
    while (v + 32 <= L_CENTER)
        v += 64;
    while (v - 32 > L_CENTER)
        v -= 64;
    return v;
}

/* meas - est reduced modulo 64 into -32..31 */
static s32 off64(s32 meas, s32 est) {
    return ((meas - est + 32) & 63) - 32;
}

static void decide(s32 l) {
    A.l = l;
    BARRIER();
    A.have_l = 1;
}

static void write_frames(const volatile s16 *src, u32 n) {
    u32 engine = V32(REC_ENGINE);
    void (*writer)(u32, const s16 *, u32) = (void (*)(u32, const s16 *, u32))V32(V32(engine) + 0x2C);
    writer(engine, (const s16 *)src, n);
    A.fed += n;
}

#define HIST_FRAMES (HIST_BLOCKS * FRAMES)
#define HIST(fr) (&A.hist[((fr) % HIST_FRAMES) * 2])

/* After the recorder feed has copied RX block rx_blocks into CAPTURE. */
EXPORT void bnc_rx(void) {
    u32 block = A.rx_blocks;
    A.rx_blocks = block + 1;
    u32 phase = A.phase;
    if (phase == A_IDLE || phase == A_DONE)
        return;
    const volatile s16 *cap = CAPTURE;
    u32 base = block * FRAMES, top = base + FRAMES;
    if (phase == A_SILENCE) {
        u32 q = A.quiet_rx;
        for (u32 f = 0; f < FRAMES; f++)
            q = LOUD2(cap + 2 * f, RX_QUIET) ? 0 : q + 1;
        A.quiet_rx = q;
        read_phase();
        return;
    }
    volatile s16 *h = HIST(base);           /* keep the last blocks: T0 may lie behind */
    for (u32 i = 0; i < 2 * FRAMES; i++)
        h[i] = cap[i];
    A.rx_now = top;
    if (phase != A_RUN) {
        read_phase();
        return;
    }
    if (!A.l_est) {                         /* the first RX block after T0 */
        if (!A.p_n)
            read_phase();
        A.p16 = A.p0 * 16 + (A.p_sum * 16 + (s32)A.p_n / 2) / (s32)A.p_n;
        A.d = (s32)(A.rx_blocks - A.tx_blocks);
        A.cached = U.cal_valid;
        A.l_est = U.cal_valid ? U.cal_l : bnc_estimate(A.p16);
    }
    if (!A.have_l) {                        /* L: the RX onset of the TX onset, near the estimate */
        u32 oldest = top > HIST_FRAMES ? top - HIST_FRAMES : 0;
        if (A.tx_onset) {
            u32 txo = A.tx_onset - 1, to = txo + L_MAX, found = 0;
            if (!A.scan)
                A.scan = txo + L_MIN;
            if (A.scan < oldest) {          /* the return's start is no longer kept */
                decide(A.l_est);
            } else {
                u32 fr = A.scan;
                for (; fr < top && fr < to && !found; fr++) {
                    volatile s16 *x = HIST(fr);
                    if (LOUD2(x, RX_ONSET))
                        found = fr + 1;
                }
                A.scan = fr;
                if (found) {
                    s32 meas = (s32)(found - 1 - txo), diff = off64(meas, A.l_est);
                    A.l_meas = meas;
                    decide(diff <= L_ACCEPT && diff >= -L_ACCEPT ? meas : A.l_est);
                } else if (fr >= to) {
                    decide(A.l_est);
                }
            }
        } else if (top >= A.t0 + ONSET_SEARCH + L_MAX) {
            decide(A.l_est);
        }
    }
    if (A.mode == TAIL && !A.win) {         /* TAIL: to the last loud frame, after 250 ms quiet */
        for (u32 f = 0; f < FRAMES; f++)
            if (LOUD2(cap + 2 * f, RX_QUIET))
                A.last_loud = base + f + 1;
        if (A.have_l) {
            u32 start = A.f0 + (u32)A.l, last = A.last_loud > start ? A.last_loud : start + 1;
            if ((A.voice_end && top >= last + TAIL_QUIET && top >= A.voice_end + (u32)A.l + TAIL_QUIET) ||
                top >= start + TAIL_CAP)
                A.win = last - start;
        }
    }
    if (!A.stop && A.have_l && A.win) {
        u32 stop = A.f0 + (u32)A.l + A.win + END_MARGIN;
        A.stop = stop > A.f0 + MIN_FILE ? stop : A.f0 + MIN_FILE;
    }
    /* write the take: RX frames from F0, the history first */
    u32 next = A.f0 + A.fed, end = A.stop && A.stop < top ? A.stop : top;
    if (next < base && next < end) {
        if (next + HIST_FRAMES < top) {     /* already overwritten: cannot happen with D < 3 */
            A.fail = 1;
            BARRIER();
            A.phase = A_DONE;
            return;
        }
        while (next < base && next < end) {
            u32 at = next % HIST_FRAMES, n = HIST_FRAMES - at;
            if (n > base - next)
                n = base - next;
            if (n > end - next)
                n = end - next;
            write_frames(&A.hist[at * 2], n);
            next += n;
        }
    }
    if (next >= base && next < end)
        write_frames(cap + 2 * (next - base), end - next);
    if (A.stop && A.f0 + A.fed >= A.stop) {
        u32 engine = V32(REC_ENGINE);
        V32(engine + 0x208) = NONE;         /* "no first sound": the stock trims leave START */
        V32(engine + 0x20C) = NONE;
        BARRIER();
        A.phase = A_DONE;
    }
}

/* ---------------------------------------------------------------------------------------------
 * UI task
 * ------------------------------------------------------------------------------------------- */

static char *put(char *o, const char *s) {
    while (*s)
        *o++ = *s++;
    return o;
}

static char *put_uint(char *o, u32 u) {
    char digits[12];
    u32 n = 0;
    if (u > 99999)
        u = 99999;
    do {
        digits[n++] = (char)('0' + u % 10);
        u /= 10;
    } while (u);
    while (n)
        *o++ = digits[--n];
    return o;
}

static char *put_int(char *o, s32 v) {
    if (v >= 0)
        return put_uint(o, (u32)v);
    *o++ = '-';
    return put_uint(o, 0u - (u32)v);
}

static char *put_pad(char *o, u32 pad) {        /* A-1 .. J-16 */
    *o++ = (char)('A' + pad / 16);
    *o++ = '-';
    return put_uint(o, pad % 16 + 1);
}

static const char *const MODE_TEXT[MODES] = {"NO TAIL", "TAIL", "LOOP"};

static void final_text(u32 msg) {
    char *o = bnc_text;
    switch (msg) {
    case M_DONE:
        o = put_pad(put(o, "BOUNCED "), U.src);
        o = put_pad(put(o, "\nON "), U.dst);
        break;
    case M_NO_EMPTY: o = put(o, "NO EMPTY PAD"); break;
    case M_PATTERN: o = put(o, "STOP PATTERN FIRST"); break;
    case M_LOOPER: o = put(o, "STOP LOOPER FIRST"); break;
    case M_RINGING: o = put(o, "FX STILL RINGING"); break;
    case M_CANCELLED: o = put(o, "BOUNCE CANCELLED\nNOTHING CHANGED"); break;
    default: o = put(o, "BOUNCE FAILED"); break;
    }
    *o = 0;
}

static void progress_text(void) {
    char *o = put(bnc_text, "BOUNCE ");
    o = put_pad(o, U.src);
    *o++ = '>';
    o = put_pad(o, U.dst);
    *o++ = '\n';
    if (U.state == U_SETUP) {
        o = put(o, U.modes == 1u << TAIL ? "TAIL ONLY" : MODE_TEXT[U.mode]);
    } else if (U.state <= U_SILENCE) {
        o = put(o, "WAIT SILENCE");
    } else {
        o = put(o, MODE_TEXT[U.mode]);
        *o++ = ' ';
        u32 done = 0, finished = U.state >= U_FINAL || A.phase == A_DONE;
        if (A.phase == A_RUN) {
            u32 start = A.t0 + (u32)(A.have_l ? A.l : A.l_est);
            done = A.rx_now > start ? A.rx_now - start : 0;
        }
        if (U.mode == TAIL) {
            u32 tenths = (finished ? A.win : done) / 4800;
            o = put_uint(o, tenths / 10);
            *o++ = '.';
            o = put_uint(o, tenths % 10);
            *o++ = 's';
        } else {
            u32 total = U.mode == LOOP ? U.len1 + U.len2 : A.win ? A.win : U.len1;
            u32 pct = finished ? 100 : total ? (u32)((unsigned long long)done * 100 / total) : 0;
            o = put_uint(o, pct > 100 ? 100 : pct);
            *o++ = '%';
        }
    }
    *o = 0;
}

static void show(u32 ms) {
    U.shown = U.ms;
    CALL2(F_POPUP, bnc_text, ms);
}

static u32 pattern_running(void) { return V8(SEQ_PLAY) != 0 || V32(SEQ_RUN) != 0; }
static u32 looper_running(void) { return V8(LOOPER_ON) != 0; }
static u32 target_pad(void) { return V32(TARGET_VALUES + 4); }

/* The first empty pad after the source in its bank, then banks A..J. */
static u32 find_empty(u32 src) {
    u32 bank = src / 16;
    for (u32 i = 1; i < 16; i++) {
        u32 p = bank * 16 + (src + i) % 16;
        if (!occupied(p))
            return p;
    }
    for (u32 p = 0; p < BANKS * 16; p++)
        if (p / 16 != bank && !occupied(p))
            return p;
    return NONE;
}

/* What the source allows: NO TAIL and LOOP need an exact length. */
static void study(u32 pad) {
    s32 start = pad_get(P_START, pad), end = pad_get(P_END, pad), lp = pad_get(P_LOOPPOINT, pad);
    U.loop_src = pad_get(P_LOOP, pad) != 0;
    U.native = end > start && pad_get(P_PITCH, pad) == 0 && pad_get(P_FINE, pad) == 0 &&
               pad_get(P_SPEED, pad) == SPEED_100 && pad_get(P_SYNC, pad) == 0 && pad_get(P_REVERSE, pad) == 0;
    if (lp < start || lp >= end)
        lp = start;
    U.len1 = end > start ? (u32)(end - start) : 0;
    U.len2 = end > lp ? (u32)(end - lp) : 0;
    U.modes = U.native ? 7u : U.loop_src ? 1u << TAIL : (1u << NO_TAIL) | (1u << TAIL);
    u32 m = U.last_mode;
    if (m >= MODES || !(U.modes & (1u << m)))
        for (m = 0; !(U.modes & (1u << m)); m++)
            ;
    U.mode = m;
}

static void enter(u32 state) {
    U.state = state;
    U.since = U.ms;
    U.refresh = 1;
}

/* Undo whatever the run pinned; then the popup. */
static void finish(u32 msg) {
    A.phase = A_IDLE;
    bnc_own = 0;
    V32(FEED_ON) = 1;
    if (U.loop_pin) {
        pad_set(P_LOOP, (s32)U.loop_src, U.src);
        U.loop_pin = 0;
    }
    if (U.pinned) {
        set_setting(0x24, U.saved_len, 0);
        set_setting(0x59, U.saved_snap, 0);
        set_setting(0x1B, U.saved_bpm, -1);
        set_setting(0x1A, -1, 0);
        U.pinned = 0;
    }
    U.msg = msg;
    enter(U_IDLE);
}

/* EXIT or a failure while the recorder may hold a take: discard it, never finalize it. */
static void abandon(u32 msg) {
    u32 state = V8(REC_STATE);
    A.phase = A_IDLE;
    post(CMD_ALL_SOUND_OFF);
    U.waits = state == 1 || state == 2;
    if (state == 2)
        post(CMD_CANCEL);
    else if (state == 1)
        post(CMD_STOP);                     /* in standby: closes and deletes the temp file */
    U.msg = msg;
    enter(U_CANCEL);
}

/* REC in the setup popup: check, pin, standby into the destination. */
static void start_run(void) {
    if (pattern_running()) {
        finish(M_PATTERN);
        return;
    }
    if (looper_running()) {
        finish(M_LOOPER);
        return;
    }
    if (V8(REC_STATE) != 0 || CALL3(F_SYSGET, SYSPRM, 0x5C, NONE) != 0 || V32(TARGET_VALUES + 0xC) == 0 ||
        !occupied(U.src) || occupied(U.dst)) {
        finish(M_FAILED);                   /* busy, ROUTING not Mix, a mono recorder, pads changed */
        return;
    }
    U.last_mode = U.mode;
    U.saved_len = get_setting(0x24);
    U.saved_snap = get_setting(0x59);
    U.saved_bpm = get_setting(0x1B);
    U.pinned = 1;
    set_setting(0x24, 6, 0);                                     /* REC length FREE: no bar limit */
    set_setting(0x59, 0, 0);                                     /* END Snap off */
    set_setting(0x1B, CALL3(F_PGET, PROJECT, 0x21 + U.src / 16, NONE), -1);   /* REC BPM: the bank's */
    set_setting(0x1A, (s32)U.dst, 0);
    CALL4(F_TSET, TARGET, 7, 0, 0);
    CALL4(F_TSET, TARGET, 1, U.dst % 16, 0);
    CALL4(F_TSET, TARGET, 0, U.dst / 16, 0);
    u32 want = U.mode == LOOP ? 1 : U.mode == TAIL ? 0 : U.loop_src;   /* LOOP: two passes; TAIL: one */
    if (want != U.loop_src) {
        U.loop_pin = 1;
        pad_set(P_LOOP, (s32)want, U.src);
    }
    A.phase = A_IDLE;
    bnc_own = 1;                            /* from here on only this module writes the take */
    post(CMD_ALL_SOUND_OFF);
    post(CMD_SEQ_SOUND_OFF);
    post(CMD_STANDBY);
    enter(U_STANDBY);
}

static void arm(void) {
    A.pad = U.src;
    A.mode = U.mode;
    A.skip = U.mode == LOOP ? U.len1 : 0;
    A.measure = U.mode == NO_TAIL && !U.native;
    A.win = U.mode == LOOP ? U.len2 : U.mode == NO_TAIL && U.native ? U.len1 : 0;
    A.armed_voices = active_slots(U.src);
    A.have_l = A.cached = 0;
    A.l = A.l_est = A.l_meas = 0;
    A.p16 = A.d = 0;
    A.tx_onset = A.scan = A.voice_end = A.last_loud = 0;
    A.stop = A.fed = A.fail = 0;
    A.rx_now = 0;
    BARRIER();
    A.phase = A_ARMED;
    CALL3(F_TRIGGER, U.src, 127, 1);
}

/* After the stock finalize: the exact window, the pad's name, a save. */
static u32 settle(void) {
    u32 dst = U.dst, info = FILE_INFO + dst * 36, engine = V32(REC_ENGINE);
    s32 channels = (s32)V32(info + 8), offset = (s32)V32(info + 0xC), data = (s32)V32(engine + 0x1C0);
    U.r_l = A.l;
    U.r_est = A.l_est;
    U.r_meas = A.l_meas;
    U.r_p16 = A.p16;
    U.r_d = A.d;
    U.r_mode = U.mode;
    U.r_len = A.win;
    if (channels != 2 || data < offset)
        return 0;
    u32 start = (u32)(data - offset) / 4 + (u32)A.l, end = start + A.win;
    s32 zero_cross = CALL3(F_PGET, PROJECT, 0xFB, NONE);
    if (zero_cross)                         /* the setter would move START to a zero crossing */
        CALL4(F_PSET, PROJECT, 0xFB, 0, NONE);
    pad_set(P_START, (s32)start, dst);
    pad_set(P_END, (s32)end, dst);
    pad_set(P_LOOPPOINT, (s32)start, dst);
    if (U.mode == LOOP || (U.mode == NO_TAIL && U.loop_src))
        pad_set(P_LOOP, 1, dst);
    if (zero_cross)
        CALL4(F_PSET, PROJECT, 0xFB, zero_cross, NONE);
    U.r_start = start;
    U.r_end = end;
    U.r_exact = (u32)pad_get(P_START, dst) == start && (u32)pad_get(P_END, dst) == end;
    char name[48], *o = name;                        /* the run's numbers, for the hardware test */
    *o++ = (char)('A' + U.src / 16);
    o = put_uint(o, U.src % 16 + 1);
    o = put_int(put(o, " L"), A.l);
    if (A.cached)
        *o++ = 'C';
    o = A.l_meas ? put_int(put(o, " M"), A.l_meas) : put(o, " M--");
    o = put_uint(put(o, " P"), (u32)A.p16 >> 4);
    *o++ = '.';
    o = put_uint(o, (((u32)A.p16 & 15) * 10 + 8) >> 4);
    o = put_int(put(o, " D"), A.d);
    *o = 0;
    CALL3(F_PADNAME, SMPL, dst, name);
    V32(SMPL + 0x1C) = 1;
    CALL3(F_POST, CMD_SAVE, 1, 0);
    return U.r_exact;
}

static void tick(void) {
    u32 state = V8(REC_STATE), in_state = U.ms - U.since;
    switch (U.state) {
    case U_SETUP:
        if (V16(PAGE_ID) != PAGE_RESAMPLE)
            enter(U_IDLE);
        break;
    case U_STANDBY:
        if (state == 1) {
            A.quiet_rx = A.quiet_tx = 0;
            A.p_n = 0;
            A.p0 = A.p_sum = 0;
            BARRIER();
            A.phase = A_SILENCE;
            enter(U_SILENCE);
        } else if (state != 0 || in_state > WAIT_STATE_MS) {
            abandon(M_FAILED);
        }
        break;
    case U_SILENCE:
        if (state != 1) {
            abandon(M_FAILED);
        } else if (A.quiet_rx >= SILENCE_FRAMES && A.quiet_tx >= SILENCE_FRAMES) {
            A.phase = A_IDLE;
            post(CMD_START);
            enter(U_RECSTART);
        } else if (in_state > WAIT_SILENCE_MS) {
            abandon(M_RINGING);
        }
        break;
    case U_RECSTART:
        if (state == 2) {
            arm();
            enter(U_VOICE);
        } else if (state != 1 || in_state > WAIT_STATE_MS) {
            abandon(M_FAILED);
        }
        break;
    case U_VOICE:
        if (state != 2 || (A.phase == A_ARMED && in_state > WAIT_VOICE_MS))
            abandon(M_FAILED);
        else if (A.phase != A_ARMED)
            enter(U_RUN);
        break;
    case U_RUN:
        if (state != 2 || A.fail) {
            abandon(M_FAILED);
        } else if (A.phase == A_DONE) {
            post(CMD_ALL_SOUND_OFF);
            if (U.loop_pin) {               /* the source's LOOP back before the project is saved */
                pad_set(P_LOOP, (s32)U.loop_src, U.src);
                U.loop_pin = 0;
            }
            set_setting(0x59, 0, 0);
            post(CMD_STOP);
            s32 diff = off64(A.l_meas, A.l_est);
            if (A.l_meas && A.l == A.l_meas && diff <= L_CACHE && diff >= -L_CACHE) {
                U.cal_l = A.l_meas;
                U.cal_valid = 1;
            }
            enter(U_FINAL);
        }
        break;
    case U_FINAL:                           /* the finalize ends by clearing the target pad */
        if (state == 0 && target_pad() == NONE) {
            u32 ok = occupied(U.dst) && settle();
            U.runs++;
            finish(ok ? M_DONE : M_FAILED);
        } else if (in_state > WAIT_FINAL_MS) {
            finish(M_FAILED);
        }
        break;
    case U_CANCEL:
        if ((state == 0 && (!U.waits || target_pad() == NONE)) || in_state > WAIT_FINAL_MS)
            finish(U.msg);
        break;
    default:
        break;
    }
}

/* The popup tick (UI task, every millisecond, before the stock tick). */
EXPORT void bnc_ui(u32 elapsed) {
    U.ms += elapsed;
    if (U.state != U_IDLE)
        tick();
    s32 left = (s32)V32(POPUP_TIMER);
    if (left >= 1 && (u32)left <= elapsed)  /* a popup closing in this tick would drop a new one */
        return;
    if (U.state == U_IDLE) {
        if (U.msg != M_NONE) {
            final_text(U.msg);
            U.msg = M_NONE;
            show(DONE_MS);
        }
    } else if (U.state != U_CANCEL && (U.refresh || U.ms - U.shown >= REFRESH_MS)) {
        U.refresh = 0;
        progress_text();
        show(POPUP_MS);
    }
}

/* Page 0xe's event filter (UI task), ahead of DOOM OS's. */
EXPORT s32 bnc_event(u32 page, const volatile s16 *ev) {
    s32 type = ev[0], a1 = ev[1], a2 = ev[2];
    if (U.state == U_IDLE) {
        if (type != EV_PAD || a1 < 0 || a1 >= 16 || V8(REC_STATE) != 0 || !key_held(KEY_RESAMPLE) ||
            key_held(KEY_SHIFT) || get_setting(0x36) != 1 || CALL1(F_MODAL, page) ||
            CALL3(F_PGET, PROJECT, 0xBF, NONE) == 1 || CALL3(F_PGET, PROJECT, 0xDD, NONE) == 1)
            return CALL2(DOOM_FILTER, page, ev);
        u32 src = (u32)CALL3(F_PGET, PROJECT, 0, NONE) * 16 + (u32)a1;
        if (src >= BANKS * 16 || !occupied(src))
            return CALL2(DOOM_FILTER, page, ev);        /* an empty pad: the stock destination pick */
        U.src = src;
        if (pattern_running()) {
            U.msg = M_PATTERN;
        } else if (looper_running()) {
            U.msg = M_LOOPER;
        } else if ((U.dst = find_empty(src)) == NONE) {
            U.msg = M_NO_EMPTY;
        } else {
            U.msg = M_NONE;
            study(src);
            enter(U_SETUP);
        }
        return 1;
    }
    /* set up or running: VALUE, REC and EXIT; every other key, knob and pad is swallowed */
    if (type == EV_KEY) {
        if (a1 == KEY_EXIT) {
            if (U.state == U_SETUP)
                finish(M_CANCELLED);
            else if (U.state < U_FINAL)
                abandon(M_CANCELLED);
        } else if (a1 == KEY_REC && U.state == U_SETUP) {
            start_run();
        }
        return 1;
    }
    if (type == EV_ENCODER) {
        if (U.state == U_SETUP && a1 == 0 && a2) {
            u32 m = U.mode;
            for (;;) {
                if (a2 > 0 ? m + 1 >= MODES : m == 0)
                    break;
                m = a2 > 0 ? m + 1 : m - 1;
                if (U.modes & (1u << m)) {
                    U.mode = m;
                    break;
                }
            }
            U.refresh = 1;
        }
        return 1;
    }
    if (type == EV_KEY_UP || type == EV_KNOB || type == EV_PAD || type == EV_PAD_UP || type == EV_PAD_MORE)
        return 1;
    return CALL2(DOOM_FILTER, page, ev);
}
