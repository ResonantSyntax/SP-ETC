/* Kits save (hardware test build): the drum-mode kit edits, saved with the project. A stage on Sound
 * Generator + Kits v9.46 (KITS_SAVE.md).
 *
 * What is saved, per project, in SG_KITS.BIN next to the stock PADCONF.BIN (the stock path builder 0x800cf018,
 * its file name swapped): every pad of all 13 kits (sound, Tune, Decay, Tone, Level, Sweep, Noise, Attack), the
 * current kit, M.CH, the arpeggiator (ARP, RATE, A.OCT, HOLD), ENV and SCALE. Stock firmware never opens the file.
 * Test 2 (file version 2) adds the Sound Generator's own settings: NOTE, OCT, OFST and the knobs (TYPE, FREQ,
 * LEVEL, Pad Length, DUTY, BALANCE, TUNE); and drum mode and melodic mode each keep their own arp (ARP, RATE,
 * A.OCT, HOLD): when kit mode changes, the screen update puts the arp settings away for the mode left and brings
 * back the other mode's. A version 1 file still loads (its arp for both modes, the Sound Generator's power-on
 * settings); the next save writes version 2.
 *
 * When it is read: the stock PADCONF load (0x8018ae68, its entry patched), whenever it loads a project other than
 * the one whose kits are in RAM (the project current at boot included), and when the same project's file changed
 * under it (a project import or delete). A missing, short, long or bad file (magic, version, size, CRC-32, any
 * value out of range) gives the power-on defaults. Before another project's file is read, unsaved edits of the
 * project in RAM are written to its own file.
 *
 * When it is written, only if the kits differ from what the card holds and never while the recorder is armed or
 * recording (sampling, RESAMPLE) or a BOUNC runs, and never from the audio task:
 * - in the stock PADCONF save (0x800cf218, its entry patched) for that project, in the stock's own task;
 * - SMPL TASK, after a command 0xd the module posts (0x800e25c0(0xd, KS_MAGIC, 0)): about 2 s (40 screen updates)
 *   after the last change while the Sound Generator page is open, and when the page closes (SG vtable +0x04).
 *   The stock body is skipped for that post unless CSmplPrm is edited, so the module's own posts never rewrite
 *   PADCONF.BIN. The screen updates come from the SG vtable +0xd0 (the kits' kit_ui_poll, then ks_tick). */
#include "ks_links.h"      /* the kits module's addresses in v9.46 (written and checked by the builder) */

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef signed char s8;

#define EXPORT __attribute__((used))
#define NAKED __attribute__((naked, used))

/* The kits module (v9.46). */
#define KIT_PADS ((volatile u8 *)KS_KIT_PADS)             /* kit_pad kit_pads[13][16]: 8 bytes each */
#define KIT_PADS_READY (*(volatile u8 *)KS_KIT_PADS_READY)
#define KIT_MODE (*(volatile u8 *)KS_KIT_MODE)              /* 0 melodic, 1..13 the kit on the SG page */
#define KIT_LAST_MODE (*(volatile u8 *)KS_KIT_LAST_MODE)    /* the kit SHIFT + PATTERN EDIT restores */
#define KIT_MIDI_CHANNEL (*(volatile u8 *)KS_KIT_MIDI_CHANNEL)
#define KIT_EDIT_CHANGED (*(volatile u8 *)KS_KIT_EDIT_CHANGED)
#define KIT_BOUNCE_STATE (*(volatile u8 *)KS_KIT_BOUNCE_STATE)
#define ARP_MODE (*(volatile int *)KS_ARP_MODE)
#define ARP_RATE (*(volatile int *)KS_ARP_RATE)
#define ARP_OCT (*(volatile int *)KS_ARP_OCT)
#define ARP_HOLD (*(volatile int *)KS_ARP_HOLD)
#define ARP_DIRTY (*(volatile u8 *)KS_ARP_DIRTY)
#define HELD_COUNT (*(volatile int *)KS_HELD_COUNT)
#define DOWN_COUNT (*(volatile int *)KS_DOWN_COUNT)
typedef void (*void_fn)(void);
typedef void (*poll_fn)(void *page, int ms);
#define KIT_INIT_PADS ((void_fn)KS_KIT_INIT_PADS)          /* factory pads and variants, once kit_pads_ready is 0 */
#define KIT_UI_POLL ((poll_fn)KS_KIT_UI_POLL)               /* the kits' SG screen update */
#define KIT_BOUNCE_RUN 2

/* Stock 5.52 (unchanged in DOOM OS ED5E and v9.46; the builder checks every one). */
typedef int (*path_fn)(char *out, int project);
typedef int (*open_fn)(const char *path, int flags);
typedef int (*io_fn)(int fd, void *buf, int n);
typedef int (*close_fn)(int fd);
typedef int (*int_fn)(void);
typedef void (*post_fn)(int cmd, int a1, int a2);
typedef void (*delay_fn)(int ms);
typedef void *(*delete_fn)(void *page);
#define PADCONF_PATH ((path_fn)0x800CF019u)    /* "<base>/PROJECT_nn/PADCONF.BIN", base by settings 0x84 */
#define FILE_OPEN ((open_fn)0x800DEC61u)       /* 0 read, 0x601 write (create, truncate); < 0 fails */
#define FILE_READ ((io_fn)0x800DEC49u)
#define FILE_WRITE ((io_fn)0x800DD9B9u)
#define FILE_CLOSE ((close_fn)0x800DEBD9u)
#define CURRENT_PROJECT ((int_fn)0x800E1191u)  /* [0x805923fc] */
#define POST ((post_fn)0x800E25C1u)            /* to SMPL TASK; for 0xd, a2 becomes the current project */
#define DELAY ((delay_fn)0x800D31EFu)          /* task delay, ms */
#define DISPATCH_OFF ((void_fn)0x800DED09u)
#define DISPATCH_ON ((void_fn)0x800DECF9u)
#define SG_DELETE ((delete_fn)0x8015CEF9u)     /* the SG page's deleting destructor */
#define REC_STATE (*(volatile u8 *)0x82E0E755u)   /* recorder: 0 idle, 1 armed, 2 recording, 3 armed for START */
#define SG_ENV (*(volatile int *)0x80249810u)     /* settings 0x82 (ENV) is the SG singleton's +0x10 */
#define KB_SCALE (*(volatile int *)0x80591C54u)   /* SCALE: the stock keyboard state 0x80591c48 + 0xc */
#define KB_OCT (*(volatile int *)0x80591C4Cu)     /* OCT: + 0x4, -3..4 (the VALUE menu's steps, 0x8015cbf4) */
#define KB_OFST (*(volatile int *)0x80591C50u)    /* OFST: + 0x8, -4..11 */
#define KB_NOTE (*(volatile int *)0x80591C58u)    /* NOTE: + 0x10, project parameter 0xf2's range, 0..11 */
typedef int (*setting_get_fn)(u32 settings, int id, int a);
typedef void (*setting_set_fn)(u32 settings, int id, int value, int a);
#define SETTINGS 0x82E01144u
#define SETTING_GET ((setting_get_fn)0x800D94D9u)
#define SETTING_SET ((setting_set_fn)0x800DD0C1u) /* clamps to the range, then the voices get it too */
#define SG_FIRST 0x7B                             /* the knobs: TYPE, FREQ, LEVEL, Pad Length (SHIFT + CTRL 1), DUTY,
                                                     BALANCE, and TUNE (VALUE menu), settings 0x7b..0x81 */
#define SG_SETTINGS 7
#define CSMPL_EDITED 0x1C                          /* CSmplPrm::Edited (0x82e2cd08 + 0x1c) */
#define CMD_D_RETURN 0x8004E2E9u                   /* SMPL TASK's command 0xd calls the save from 0x8004e2e4 */

#define KS_MAGIC 0x544B4753u          /* the file starts "SGKT"; also the a1 of the module's own command 0xd */
#define KS_VERSION 2
#define KS_KITS 13
#define KS_PADS_BYTES (KS_KITS * 16 * 8)
#define KS_TAIL 32
#define KS_PAYLOAD (KS_PADS_BYTES + KS_TAIL)
#define KS_HEADER 16
#define KS_FILE (KS_HEADER + KS_PAYLOAD)
#define KS_PAYLOAD_V1 (KS_PADS_BYTES + 8)  /* version 1 (kits-save-test1): the tail's first 8 bytes */
#define KS_FILE_V1 (KS_HEADER + KS_PAYLOAD_V1)
/* The tail, after the pads: */
#define T_KIT 0                       /* the kit, 1..13 */
#define T_MCH 1                       /* M.CH, 0..15 */
#define T_ARP 2                       /* melodic mode's ARP, RATE, A.OCT, HOLD (version 1: both modes') */
#define T_ENV 6
#define T_SCALE 7
#define T_DRUM_ARP 8                  /* drum mode's ARP, RATE, A.OCT, HOLD */
#define T_NOTE 12
#define T_OCT 13
#define T_OFST 14
#define T_SG 16                       /* settings 0x7b..0x81, signed 16 bits each, little-endian; 30, 31 zero */
#define KS_SOUNDS 143
#define KS_OFF_SOUND 255
#define KS_ENVS 10                    /* settings 0x82: 0..9 */
#define KS_SCALES 34                  /* v9.6: 34 scales on the SG page */
#define KS_QUIET 40                   /* screen updates without a change before a save (the page asks for 50 ms) */
#define KS_PENDING_MAX 400            /* a post not seen by the save after this many updates is given up */
#define KS_PATH 64

/* What the card holds for the project in RAM, and the power-on values a project without a file gets. */
EXPORT char ks_path[KS_PATH];         /* that project's SG_KITS.BIN; empty until the first load */
EXPORT u8 ks_seen[KS_PAYLOAD] __attribute__((aligned(4)));   /* the kits as last read or written */
EXPORT u8 ks_file_ok;                 /* the card holds ks_seen as a valid file (0: no file, or a bad one) */
EXPORT u8 ks_buf[KS_FILE + 4] __attribute__((aligned(8)));   /* the file, read or to be written */
EXPORT volatile u8 ks_busy;           /* a save or load holds ks_buf, ks_seen and ks_path */
EXPORT volatile u8 ks_pending;        /* a command 0xd of ours is queued */
EXPORT volatile u32 ks_pending_age, ks_quiet, ks_last_hash;
/* counters, for the tests and a look on the unit: loads that read a file / gave defaults, writes, write errors,
 * own posts, own posts whose stock body was skipped, saves refused as unsafe */
EXPORT volatile u32 ks_loads, ks_defaults, ks_writes, ks_errors, ks_posts, ks_skips, ks_refused;
/* kit, M.CH, ARP, RATE, A.OCT, HOLD, ENV, SCALE at power-on (v9.46: 1, 15, 0, 4, 0, 0, 4, 0; the builder reads them) */
static const u8 ks_default_tail[8] = KS_DEFAULT_TAIL;
/* The arp settings of the mode not on now: ARP, RATE, A.OCT, HOLD (ks_arp_drum: the arp's own variables hold drum
 * mode's). Their power-on values are the arp's. */
EXPORT int ks_arp_other[4] = {KS_DEFAULT_ARP};
EXPORT volatile u8 ks_arp_drum;
/* The Sound Generator's settings at power-on, the tail from T_NOTE on, as the first load (the boot's) finds them. */
EXPORT u8 ks_power_on[KS_TAIL - T_NOTE];
EXPORT u8 ks_power_on_taken;

static void ks_copy(volatile u8 *d, const volatile u8 *s, u32 n) { while (n--) *d++ = *s++; }
static int ks_same(const volatile u8 *a, const volatile u8 *b, u32 n) {
    while (n--) if (*a++ != *b++) return 0;
    return 1;
}
static u32 ks_len(const char *s) { u32 n = 0; while (s[n]) ++n; return n; }

static u32 ks_crc(const u8 *p, u32 n) {   /* CRC-32 (IEEE 802.3, reflected 0xedb88320) */
    u32 c = 0xFFFFFFFFu;
    while (n--) {
        c ^= *p++;
        for (int k = 0; k < 8; ++k) c = c & 1 ? (c >> 1) ^ 0xEDB88320u : c >> 1;
    }
    return ~c;
}
static void ks_put32(u8 *p, u32 v) { p[0] = (u8)v; p[1] = (u8)(v >> 8); p[2] = (u8)(v >> 16); p[3] = (u8)(v >> 24); }
static u32 ks_get32(const u8 *p) { return p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }

static int ks_try_lock(void) { return !__atomic_exchange_n(&ks_busy, 1, __ATOMIC_ACQUIRE); }
static void ks_unlock(void) { __atomic_store_n(&ks_busy, 0, __ATOMIC_RELEASE); }

/* No write while the recorder is armed or recording (sampling, RESAMPLE, a hot resample) or a BOUNC runs. */
static int ks_safe(void) { return REC_STATE == 0 && KIT_BOUNCE_STATE != KIT_BOUNCE_RUN; }

/* The project's SG_KITS.BIN, as the stock builds its PADCONF.BIN path (empty if that is not what it built). */
static void ks_path_of(char *out, int project) {
    char tmp[128];
    tmp[0] = 0;
    PADCONF_PATH(tmp, project);
    u32 n = ks_len(tmp);
    static const char stock[] = "PADCONF.BIN", ours[] = "SG_KITS.BIN";
    out[0] = 0;
    if (n < 11 || n >= KS_PATH || !ks_same((const u8 *)tmp + n - 11, (const u8 *)stock, 11)) return;
    ks_copy((u8 *)out, (const u8 *)tmp, n - 11);
    ks_copy((u8 *)out + n - 11, (const u8 *)ours, 12);
}
static int ks_path_is(const char *a, const char *b) { return a[0] && ks_same((const u8 *)a, (const u8 *)b, ks_len(a) + 1); }

/* The arp's own settings: ARP, RATE, A.OCT, HOLD. */
static void ks_arp_get(int *a) { a[0] = ARP_MODE; a[1] = ARP_RATE; a[2] = ARP_OCT; a[3] = ARP_HOLD; }

/* Into the arp; its held notes go with an ARP or HOLD change, as the VALUE menu does it. */
static void ks_arp_set(const int *a) {
    if (a[0] != ARP_MODE || a[3] != ARP_HOLD) {
        DISPATCH_OFF();
        HELD_COUNT = 0;
        DOWN_COUNT = 0;
        ARP_MODE = a[0];
        ARP_HOLD = a[3];
        DISPATCH_ON();
    }
    ARP_RATE = a[1];
    ARP_OCT = a[2];
    ARP_DIRTY = 1;
}

/* Kit mode changed since the arp's settings were last placed: they go to the mode left, the other mode's come back. */
static void ks_arp_follow(void) {
    u8 drum = KIT_MODE != 0;
    if (drum == ks_arp_drum) return;
    int live[4];
    ks_arp_get(live);
    ks_arp_set(ks_arp_other);
    for (int i = 0; i < 4; ++i) ks_arp_other[i] = live[i];
    ks_arp_drum = drum;
}

/* The Sound Generator's settings as they are now, in file order: NOTE, OCT, OFST, 0, then settings 0x7b..0x81. */
static void ks_sg_capture(u8 *t) {
    t[0] = (u8)KB_NOTE; t[1] = (u8)(s8)KB_OCT; t[2] = (u8)(s8)KB_OFST; t[3] = 0;
    for (int i = 0; i < SG_SETTINGS; ++i) {
        int v = SETTING_GET(SETTINGS, SG_FIRST + i, 0);
        t[4 + 2 * i] = (u8)v;
        t[5 + 2 * i] = (u8)(v >> 8);
    }
    t[4 + 2 * SG_SETTINGS] = t[5 + 2 * SG_SETTINGS] = 0;
}

/* The tail as RAM holds it now. */
static void ks_tail(u8 *t) {
    u8 kit = KIT_MODE;
    int live[4];
    ks_arp_get(live);
    const int *mel = ks_arp_drum ? ks_arp_other : live, *drum = ks_arp_drum ? live : ks_arp_other;
    t[T_KIT] = kit ? kit : KIT_LAST_MODE;
    t[T_MCH] = KIT_MIDI_CHANNEL;
    for (int i = 0; i < 4; ++i) {
        t[T_ARP + i] = (u8)mel[i];
        t[T_DRUM_ARP + i] = (u8)drum[i];
    }
    t[T_ENV] = (u8)SG_ENV;
    t[T_SCALE] = (u8)KB_SCALE;
    ks_sg_capture(t + T_NOTE);
}

/* The kits as they are now, in file order. */
static void ks_capture(u8 *p) {
    ks_copy(p, KIT_PADS, KS_PADS_BYTES);
    ks_tail(p + KS_PADS_BYTES);
}

static int ks_s16(const u8 *b) { return (int)(short)(b[0] | b[1] << 8); }

/* An arp's ARP, RATE, A.OCT, HOLD as the VALUE menu can set them. */
static int ks_arp_valid(const u8 *a) {
    int oct = (s8)a[2];
    return a[0] <= 6 && a[1] <= 6 && oct >= -3 && oct <= 3 && a[3] <= 1;
}

/* Every value as the menus and knobs can set it (settings 0x7b..0x81: their widest ranges; DUTY's is 0..0 on some
 * TYPEs and the setter clamps it then). */
static int ks_valid(const u8 *p) {
    static const short sg_lo[SG_SETTINGS] = {0, -36, 0, -8, 0, -51, 4160};
    static const short sg_hi[SG_SETTINGS] = {31, 48, 127, 20, 100, 51, 4640};
    for (u32 i = 0; i < KS_PADS_BYTES; i += 8) {
        const u8 *q = p + i;
        int tune = (s8)q[1];
        if ((q[0] >= KS_SOUNDS && q[0] != KS_OFF_SOUND) || tune < -12 || tune > 12 || q[2] > 100 || q[3] > 100 ||
            q[4] > 127 || q[5] > 100 || q[6] > 100 || q[7] > 100) return 0;
    }
    const u8 *t = p + KS_PADS_BYTES;
    int oct = (s8)t[T_OCT], ofst = (s8)t[T_OFST];
    if (!(t[T_KIT] >= 1 && t[T_KIT] <= KS_KITS && t[T_MCH] <= 15 && ks_arp_valid(t + T_ARP) &&
          ks_arp_valid(t + T_DRUM_ARP) && t[T_ENV] < KS_ENVS && t[T_SCALE] < KS_SCALES && t[T_NOTE] <= 11 &&
          oct >= -3 && oct <= 4 && ofst >= -4 && ofst <= 11 && !t[15] && !t[30] && !t[31])) return 0;
    for (int i = 0; i < SG_SETTINGS; ++i) {
        int v = ks_s16(t + T_SG + 2 * i);
        if (v < sg_lo[i] || v > sg_hi[i]) return 0;
    }
    return 1;
}

/* Into RAM: the file's kits, or (p = 0) the power-on defaults. The SG page is not open while a project loads. */
static void ks_apply(const u8 *p) {
    u8 t[KS_TAIL];
    if (p) {
        ks_copy(t, p + KS_PADS_BYTES, KS_TAIL);
    } else {
        ks_copy(t, ks_default_tail, 8);
        ks_copy(t + T_DRUM_ARP, ks_default_tail + T_ARP, 4);
        ks_copy(t + T_NOTE, ks_power_on, KS_TAIL - T_NOTE);
    }
    KIT_PADS_READY = 0;
    KIT_INIT_PADS();
    if (p) ks_copy(KIT_PADS, p, KS_PADS_BYTES);
    KIT_LAST_MODE = t[T_KIT];
    if (KIT_MODE) KIT_MODE = t[T_KIT];
    KIT_MIDI_CHANNEL = t[T_MCH];
    int mel[4], drum[4];
    for (int i = 0; i < 4; ++i) {
        mel[i] = i == 2 ? (s8)t[T_ARP + i] : t[T_ARP + i];
        drum[i] = i == 2 ? (s8)t[T_DRUM_ARP + i] : t[T_DRUM_ARP + i];
    }
    ks_arp_drum = KIT_MODE != 0;
    ks_arp_set(ks_arp_drum ? drum : mel);
    for (int i = 0; i < 4; ++i) ks_arp_other[i] = ks_arp_drum ? mel[i] : drum[i];
    SG_ENV = t[T_ENV];
    KB_SCALE = t[T_SCALE];
    KB_NOTE = t[T_NOTE];
    KB_OCT = (s8)t[T_OCT];
    KB_OFST = (s8)t[T_OFST];
    for (int i = 0; i < SG_SETTINGS; ++i)            /* TYPE first: DUTY's range follows it */
        SETTING_SET(SETTINGS, SG_FIRST + i, ks_s16(t + T_SG + 2 * i), 0);
    KIT_EDIT_CHANGED = 1;
}

/* 1 = the file is there and valid (its payload in ks_buf + 16, in version 2's layout), 0 = no file, -1 = short,
 * long or bad. A version 1 file gets its arp for both modes and the Sound Generator's power-on settings. */
static int ks_read(const char *path) {
    int fd = FILE_OPEN(path, 0);
    if (fd < 0) return 0;
    int n = FILE_READ(fd, ks_buf, KS_FILE + 1);
    FILE_CLOSE(fd);
    u8 *p = ks_buf + KS_HEADER;
    int v1 = n == KS_FILE_V1 && ks_buf[4] == 1;
    u32 payload = v1 ? KS_PAYLOAD_V1 : KS_PAYLOAD;
    if ((n != KS_FILE && !v1) || ks_get32(ks_buf) != KS_MAGIC || ks_buf[4] != (v1 ? 1 : KS_VERSION) || ks_buf[5] ||
        ks_buf[6] != KS_HEADER || ks_buf[7] || ks_get32(ks_buf + 8) != payload ||
        ks_get32(ks_buf + 12) != ks_crc(p, payload)) return -1;
    if (v1) {
        u8 *t = p + KS_PADS_BYTES;
        ks_copy(t + T_DRUM_ARP, t + T_ARP, 4);
        ks_copy(t + T_NOTE, ks_power_on, KS_TAIL - T_NOTE);
    }
    return ks_valid(p) ? 1 : -1;
}

static int ks_write(const char *path) {
    ks_put32(ks_buf, KS_MAGIC);
    ks_buf[4] = KS_VERSION; ks_buf[5] = 0; ks_buf[6] = KS_HEADER; ks_buf[7] = 0;
    ks_put32(ks_buf + 8, KS_PAYLOAD);
    ks_put32(ks_buf + 12, ks_crc(ks_buf + KS_HEADER, KS_PAYLOAD));
    int fd = FILE_OPEN(path, 0x601);
    if (fd < 0) return 0;
    int n = FILE_WRITE(fd, ks_buf, KS_FILE);
    FILE_CLOSE(fd);
    return n == KS_FILE;
}

/* The kits in RAM to their own file if they differ from it. Holds the lock. */
static void ks_flush_locked(void) {
    if (!ks_path[0]) return;
    if (!ks_safe()) { ++ks_refused; return; }
    ks_capture(ks_buf + KS_HEADER);
    if (ks_same(ks_buf + KS_HEADER, ks_seen, KS_PAYLOAD)) return;
    if (ks_write(ks_path)) { ks_copy(ks_seen, ks_buf + KS_HEADER, KS_PAYLOAD); ks_file_ok = 1; ++ks_writes; }
    else ++ks_errors;
}

/* The stock PADCONF save (CSmplPrm, project or -1 = current), from its entry; lr and r4 are the caller's. Returns 1
 * to leave the stock body out: only for the module's own command 0xd, and only if CSmplPrm is not edited. */
EXPORT int ks_save_c(u32 smpl, int project, u32 lr, u32 r4) {
    int ours = lr == CMD_D_RETURN && *(volatile u16 *)(r4 + 2) == 0xD && *(volatile u32 *)(r4 + 4) == KS_MAGIC;
    if (ours) ks_pending = 0;
    if (ks_try_lock()) {
        char path[KS_PATH];
        ks_path_of(path, project == -1 ? CURRENT_PROJECT() : project);
        if (ks_path_is(path, ks_path)) ks_flush_locked();
        ks_unlock();
    }
    if (ours && !*(volatile u8 *)(smpl + CSMPL_EDITED)) { ++ks_skips; return 1; }
    return 0;
}

/* The stock PADCONF load (CSmplPrm, flag), from its entry: it loads the current project. */
EXPORT void ks_load_c(u32 smpl, int flag) {
    (void)smpl; (void)flag;
    char path[KS_PATH];
    ks_path_of(path, CURRENT_PROJECT());
    if (!path[0]) return;
    for (int i = 0; i < 1000 && !ks_try_lock(); ++i) DELAY(1);   /* a save holds it for one write */
    if (!ks_power_on_taken) {                                    /* the boot's load: before any file is applied */
        ks_sg_capture(ks_power_on);
        ks_power_on_taken = 1;
    }
    int same = ks_path_is(path, ks_path);
    if (!same) ks_flush_locked();                                /* the project in RAM keeps its edits */
    int got = ks_read(path);
    /* The same project again (a pad reload, a reload of the project): RAM stays unless the card changed. */
    if (!same || (got == 1 ? !ks_file_ok || !ks_same(ks_buf + KS_HEADER, ks_seen, KS_PAYLOAD) : ks_file_ok)) {
        ks_apply(got == 1 ? ks_buf + KS_HEADER : 0);
        ks_capture(ks_seen);
        ks_file_ok = got == 1;
        ks_copy((u8 *)ks_path, (const u8 *)path, ks_len(path) + 1);
        if (got == 1) ++ks_loads; else ++ks_defaults;
        ks_quiet = 0;
    }
    ks_unlock();
}

static u32 ks_hash(void) {
    u32 h = 0x811C9DC5u;
    const volatile u32 *w = (const volatile u32 *)KIT_PADS;
    for (u32 i = 0; i < KS_PADS_BYTES / 4; ++i) h = (h ^ w[i]) * 0x01000193u;
    u8 t[KS_TAIL];
    ks_tail(t);
    for (int i = 0; i < KS_TAIL; ++i) h = (h ^ t[i]) * 0x01000193u;
    return h;
}

static int ks_dirty(void) {
    u8 now[KS_TAIL];
    if (!ks_same(KIT_PADS, ks_seen, KS_PADS_BYTES)) return 1;
    ks_tail(now);
    return !ks_same(now, ks_seen + KS_PADS_BYTES, sizeof now);
}

static void ks_post(void) {
    ks_pending = 1;
    ks_pending_age = 0;
    ++ks_posts;
    POST(0xD, (int)KS_MAGIC, 0);
}

/* One SG screen update (UI task): a save once nothing changed for KS_QUIET updates. */
static void ks_tick(void) {
    if (!ks_path[0]) return;
    u32 h = ks_hash();
    if (h != ks_last_hash) { ks_last_hash = h; ks_quiet = 0; return; }
    if (ks_pending) {
        if (++ks_pending_age < KS_PENDING_MAX) return;
        ks_pending = 0;
    }
    if (++ks_quiet < KS_QUIET) return;
    ks_quiet = 0;
    if (ks_dirty() && ks_safe()) ks_post();
}

/* SG vtable +0xd0: each mode's arp, the kits' screen update, then ours. */
EXPORT void ks_sg_poll(void *page, int ms) {
    ks_arp_follow();
    KIT_UI_POLL(page, ms);
    ks_tick();
}

/* SG vtable +0x04: the page closes (UI task). */
EXPORT void *ks_sg_leave(void *page) {
    if (ks_path[0] && !ks_pending && ks_dirty() && ks_safe()) ks_post();
    return SG_DELETE(page);
}

/* 0x800cf218 (10 bytes: push.w {r4-r11, lr}; sub sp, #0x19c; mov r4, r1; mov sb, r0) jumps here. */
NAKED EXPORT void ks_save_entry(void) {
    __asm__ volatile(
        "push {r0, r1, r2, r3, r4, lr}\n"
        "mov r2, lr\n"
        "mov r3, r4\n"
        "bl ks_save_c\n"
        "cmp r0, #0\n"
        "pop {r0, r1, r2, r3, r4, lr}\n"
        "bne 1f\n"
        "push.w {r4, r5, r6, r7, r8, r9, r10, r11, lr}\n"
        "sub sp, #0x19c\n"
        "mov r4, r1\n"
        "mov r9, r0\n"
        "movw ip, #0xf223\n"
        "movt ip, #0x800c\n"
        "bx ip\n"
        "1: movs r0, #0\n"
        "bx lr\n");
}

/* 0x8018ae68 (12 bytes: push.w {r4-r11, lr}; sub sp, #0x154; str r1, [sp, #0x24]; movw r2, #0xc431) jumps here. */
NAKED EXPORT void ks_load_entry(void) {
    __asm__ volatile(
        "push {r0, r1, r2, r3, r4, lr}\n"
        "bl ks_load_c\n"
        "pop {r0, r1, r2, r3, r4, lr}\n"
        "push.w {r4, r5, r6, r7, r8, r9, r10, r11, lr}\n"
        "sub sp, #0x154\n"
        "str r1, [sp, #0x24]\n"
        "movw r2, #0xc431\n"
        "movw ip, #0xae75\n"
        "movt ip, #0x8018\n"
        "bx ip\n");
}
