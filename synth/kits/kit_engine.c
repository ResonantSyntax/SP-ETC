/* Sound Generator Kit engine: circuit-informed and synthetic drum kits,
 * per-pad SOUND/TUNE/DECAY/TONE/LEVEL, hold a pad and turn VALUE for that
 * pad's SOUND, for the doom-os-etc. v9 Sound
 * Generator. Included into the arp module (KIT_IN_ARP) or built alone for
 * host previews (KIT_HOST). All arithmetic is single precision.
 *
 * KIT (VALUE item 11) OFF leaves every voice to v9. Any other KIT plays the
 * kit on every TYPE: the drum is the pad that started the voice
 * (state+0x1AC); an arp step uses the pad its note came from (the arp's held
 * list, octaves allowed); MIDI uses note % 16. ENV is bypassed for kit voices
 * (their v9 envelope slot is set to OFF from the second sample) and a
 * released kit voice holds the stock fade counter (+0x4C) at its start while
 * its drum rings, except during stealing or all-stop. The stock LEVEL and
 * velocity scaling after the oscillator still apply. Edits are RAM-only.
 */
#ifndef KIT_IN_ARP
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#if defined(KIT_HOST) && defined(_WIN32)
#define EXPORT __declspec(dllexport) __attribute__((used))
#else
#define EXPORT __attribute__((used))
#endif
#endif

#define KIT_SINGLETON 0x80249800u
#define KIT_CLONE_BASE 0x8353A310u
#define KIT_EXPORT_BASE 0x8353C000u
#define KIT_VOICE_SIZE 0x1B0u
#define KIT_FS 48000.0f
#define KIT_SILENT 1e-4f
#define KIT_BUILTIN 13                  /* 808 DR110 KPR77 UDS FM 909 606 SDS MP-7 CR78 CR8K 707 727 */
#define KIT_SOUNDS 143
#define KIT_PADS 16
#define KIT_OFF_SOUND 255

#ifdef KIT_HOST
static volatile u8 kit_host_flags[3][8];
static volatile u8 kit_host_env[8 * 40];
#define KIT_ENV_RESTART (kit_host_flags[0])
#define KIT_ENV_QUICK (kit_host_flags[1])
#define KIT_ENV_FAST (kit_host_flags[2])
#define KIT_ENV_PRESET(i) (kit_host_env[40u*(u32)(i) + 38u])
#else
#define KIT_ENV_RESTART ((volatile u8 *)KIT_ENV_RESTART_ADDR)
#define KIT_ENV_QUICK ((volatile u8 *)KIT_ENV_QUICK_ADDR)
#define KIT_ENV_FAST ((volatile u8 *)KIT_ENV_FAST_ADDR)
/* v9 env_t: nine floats, then stage, fstage, preset, tick (40 bytes). */
#define KIT_ENV_PRESET(i) (*(volatile u8 *)(KIT_ENV_SLOT_ADDR + 40u*(u32)(i) + 38u))
#endif

enum { FM_KICK, FM_SNARE, FM_TOM, FM_HAT, FM_BELL, FM_PERC, FM_LOG, FM_COW,   /* FM_*: DX-style operator pairs */
       T8_BD, T8_SD, T8_LT, T8_MT, T8_HT, T8_LC, T8_MC, T8_HC,   /* T8_*: the TR-808's 16 voices */
       T8_RS, T8_CL, T8_CP, T8_MA, T8_CB, T8_CY, T8_OH, T8_CH,
       T9_BD, T9_SD, T9_LT, T9_MT, T9_HT, T9_RS, T9_CP,         /* 909 analog voices only */
       T6_BD, T6_SD, T6_LT, T6_HT, T6_CY, T6_OH, T6_CH,
       SDS_BD, SDS_SD, SDS_LT, SDS_MT, SDS_HT, SDS_ZAP,
       C78_BD, C78_SD, C78_RS, C78_HH, C78_CY, C78_MA, C78_CL,
       C78_HB, C78_LB, C78_LC, C78_CB, C78_TB, C78_GU, C78_MB,
       C8K_BD, C8K_SD, C8K_LT, C8K_HT, C8K_LC, C8K_MC, C8K_HC,
       C8K_CY, C8K_OH, C8K_CH, C8K_RS, C8K_CB, C8K_CL, C8K_CP,
       DR_BD, DR_SD, DR_CH, DR_OH, DR_CP, DR_CY,                /* procedural: DR-110, KPR-77, 909 metal */
       KP_BD, KP_SD, KP_CH, KP_OH, KP_LT, KP_HT, KP_CP, KP_CY,
       M9_CH, M9_OH, M9_CY, M9_RD,
       U_BD, U_BD2, U_SD, U_SD2, U_TOM, U_CP, U_CH, U_OH,       /* table voices: Lel' UDS */
       MP_BD, MP_SD1, MP_SD2, MP_RS, MP_CY1, MP_CY2, MP_CL, MP_CB, /* Korg Mini Pops 7 */
       MP_BGH, MP_BGM, MP_BGL, MP_MA, MP_GU, MP_QJ, MP_TB,
       T7_BD1, T7_BD2, T7_SD1, T7_SD2, T7_LT, T7_MT, T7_HT, T7_RS, /* TR-707 */
       T7_CP, T7_CB, T7_TB, T7_CH, T7_OH, T7_CR, T7_RD,
       T27_HB, T27_LB, T27_MHC, T27_OHC, T27_LC, T27_HTI, T27_LTI, T27_HAG, /* TR-727 */
       T27_LAG, T27_CAB, T27_MAR, T27_SWH, T27_LWH, T27_QUI, T27_CHM };
#define KIT_PROCEDURAL_FIRST DR_BD
#define KIT_DATA_FIRST U_BD

typedef struct { u8 sound; signed char tune; u8 decay; signed char tone; u8 level; u8 sweep, noise, attack; } kit_pad;
/* Runtime decay/tone: 0..100 knob positions; tune in semitones, level 0..127.
 * Factory table below retains old recipe units, converted once at initialization. */
typedef struct { u8 sound; signed char tune; u8 decay; signed char tone; u8 level; } kit_factory_pad;
#define P(s, t, d, o, l) {s, t, d, o, l}
/* GEN marks a pad outside the kit's active mask: kit_init_pads writes a generated
 * tune/decay/tone/attack variant of the kit's own voices there. */
#define GEN P(0, 0, 10, 0, 110)
static const kit_factory_pad kit_factory[KIT_BUILTIN][16] = {
    { /* TR-808 */ P(T8_BD,0,12,9,110), P(T8_SD,0,10,0,105), P(T8_CH,0,10,0,100), P(T8_OH,0,10,0,100),
      P(T8_LT,0,10,0,105), P(T8_MT,0,10,0,105), P(T8_HT,0,10,0,105), P(T8_CY,0,10,0,100),
      P(T8_RS,0,10,0,100), P(T8_CP,0,10,0,105), P(T8_CB,0,10,0,100), P(T8_MA,0,10,0,100),
      P(T8_LC,0,10,0,105), P(T8_MC,0,10,0,105), P(T8_HC,0,10,0,105), P(T8_CL,0,10,0,100) },
    { /* DR110: its six voices; the other pads are generated variants. */
      P(DR_BD,0,10,0,110), P(DR_SD,0,10,0,110), P(DR_CH,0,10,0,110), P(DR_OH,0,10,0,110),
      GEN, GEN, GEN, P(DR_CY,0,10,0,110),
      GEN, P(DR_CP,0,10,0,110), GEN, GEN,
      GEN, GEN, GEN, GEN },
    { /* KPR77: its eight voices; the other pads are generated variants. */
      P(KP_BD,0,10,0,110), P(KP_SD,0,10,0,110), P(KP_CH,0,10,0,110), P(KP_OH,0,10,0,110),
      P(KP_LT,0,10,0,110), P(KP_HT,0,10,0,110), GEN, P(KP_CY,0,10,0,110),
      GEN, P(KP_CP,0,10,0,110), GEN, GEN,
      GEN, GEN, GEN, GEN },
    { /* Lel' UDS (Soviet drum synthesizer): eight voices and variants. */
      P(U_BD,0,10,0,110), P(U_SD,0,10,0,105), P(U_CH,0,10,0,100), P(U_OH,0,10,0,100),
      P(U_TOM,0,10,0,105), P(U_SD2,0,10,0,105), P(U_BD2,0,10,0,110), P(U_CP,0,10,0,105),
      GEN, GEN, GEN, GEN,
      GEN, GEN, GEN, GEN },
    { /* FM: eight operator voices, then tuned variants. */
      P(FM_KICK,0,10,0,105), P(FM_SNARE,0,10,0,100), P(FM_HAT,0,10,0,95), P(FM_HAT,0,40,0,90),
      P(FM_TOM,-5,10,0,105), P(FM_TOM,0,10,0,105), P(FM_TOM,5,10,0,105), P(FM_BELL,0,10,0,95),
      P(FM_PERC,0,10,0,100), P(FM_LOG,0,10,0,105), P(FM_COW,0,10,0,95), P(FM_LOG,5,10,0,105),
      P(FM_KICK,7,5,6,100), P(FM_SNARE,5,6,6,95), P(FM_BELL,-12,14,-3,95), P(FM_LOG,-7,12,0,105) },
    { /* TR909: analog models plus procedural hat/crash/ride stand-ins. */
      P(T9_BD,0,10,0,105), P(T9_SD,0,10,0,100), P(M9_CH,0,10,0,100), P(M9_OH,0,10,0,100),
      P(T9_LT,0,10,0,105), P(T9_MT,0,10,0,105), P(T9_HT,0,10,0,105), P(M9_CY,0,10,0,100),
      P(T9_RS,0,10,0,100), P(T9_CP,0,10,0,100), P(M9_RD,0,10,0,100), GEN,
      GEN, GEN, GEN, GEN },
    { /* TR606: seven voices followed by per-pad variations. */
      P(T6_BD,0,10,0,110), P(T6_SD,0,10,0,100), P(T6_CH,0,10,0,100), P(T6_OH,0,10,0,100),
      P(T6_LT,0,10,0,105), P(T6_HT,0,10,0,105), P(T6_CY,0,10,0,100), GEN,
      GEN, GEN, GEN, GEN,
      GEN, GEN, GEN, GEN },
    { /* SDS-V inspired: drum modules and playable tuned/swept variants. */
      P(SDS_BD,0,10,0,105), P(SDS_SD,0,10,0,100), P(SDS_ZAP,0,8,0,100), GEN,
      P(SDS_LT,0,10,0,105), P(SDS_MT,0,10,0,105), P(SDS_HT,0,10,0,105), GEN,
      GEN, GEN, GEN, GEN,
      GEN, GEN, GEN, GEN },
    { /* Korg Mini Pops 7: fifteen voices. */
      P(MP_BD,0,10,0,110), P(MP_SD1,0,10,0,100), P(MP_CY1,0,10,0,95), P(MP_CY2,0,10,0,95),
      P(MP_BGL,0,10,0,105), P(MP_BGM,0,10,0,105), P(MP_BGH,0,10,0,105), P(MP_SD2,0,10,0,100),
      P(MP_RS,0,10,0,100), P(MP_CL,0,10,0,100), P(MP_CB,0,10,0,100), P(MP_MA,0,10,0,95),
      P(MP_TB,0,10,0,95), P(MP_GU,0,10,0,95), P(MP_QJ,0,10,0,95), GEN },
    { /* CR-78: fourteen sources, followed by low guiro and long cymbal variants. */
      P(C78_BD,0,10,0,105), P(C78_SD,0,10,0,100), P(C78_HH,0,10,0,95), P(C78_CY,0,10,0,95),
      P(C78_HB,0,10,0,100), P(C78_LB,0,10,0,100), P(C78_LC,0,10,0,105), P(C78_MB,0,10,0,90),
      P(C78_RS,0,10,0,95), P(C78_CL,0,10,0,95), P(C78_CB,0,10,0,95), P(C78_MA,0,10,0,95),
      P(C78_TB,0,10,0,95), P(C78_GU,0,10,0,100), GEN, GEN },
    { /* CR-8000 later-revision model: fourteen voices and two variants. */
      P(C8K_BD,0,10,0,105), P(C8K_SD,0,10,0,100), P(C8K_CH,0,10,0,100), P(C8K_OH,0,10,0,100),
      P(C8K_LT,0,10,0,105), P(C8K_HT,0,10,0,105), P(C8K_LC,0,10,0,105), P(C8K_CY,0,10,0,100),
      P(C8K_RS,0,10,0,100), P(C8K_CP,0,10,0,100), P(C8K_CB,0,10,0,100), P(C8K_CL,0,10,0,100),
      P(C8K_MC,0,10,0,105), P(C8K_HC,0,10,0,105), GEN, GEN },
    { /* TR-707: fifteen voices in the 707's own order, then a variant. */
      P(T7_BD1,0,10,0,110), P(T7_SD1,0,10,0,105), P(T7_CH,0,10,0,100), P(T7_OH,0,10,0,100),
      P(T7_LT,0,10,0,105), P(T7_MT,0,10,0,105), P(T7_HT,0,10,0,105), P(T7_CR,0,10,0,95),
      P(T7_RS,0,10,0,100), P(T7_CP,0,10,0,105), P(T7_CB,0,10,0,100), P(T7_TB,0,10,0,95),
      P(T7_BD2,0,10,0,110), P(T7_SD2,0,10,0,105), P(T7_RD,0,10,0,95), GEN },
    { /* TR-727: fifteen Latin percussion voices, then a variant. */
      P(T27_HB,0,10,0,105), P(T27_LB,0,10,0,105), P(T27_MHC,0,10,0,105), P(T27_OHC,0,10,0,105),
      P(T27_LC,0,10,0,105), P(T27_HTI,0,10,0,100), P(T27_LTI,0,10,0,100), P(T27_HAG,0,10,0,95),
      P(T27_LAG,0,10,0,95), P(T27_CAB,0,10,0,95), P(T27_MAR,0,10,0,95), P(T27_SWH,0,10,0,90),
      P(T27_LWH,0,10,0,90), P(T27_QUI,0,10,0,95), P(T27_CHM,0,10,0,90), GEN },
};
#undef GEN
#undef P
#define KIT_KITS KIT_BUILTIN

EXPORT volatile u8 kit_mode;                 /* 0 OFF, 1..KIT_KITS = kit */
EXPORT volatile u8 kit_edit_pad;             /* 0..15: physical pad */
EXPORT volatile u8 kit_record_pad,kit_record_velocity;
static u32 kit_hit_origin[16],kit_hit_seed[16];
static u8 kit_hit_mode[16],kit_hit_velocity[16];
static u8 kit_export_active,kit_export_mode,kit_export_count,kit_export_bd_slot;
/* REC renders up to four captured hits, each from its own recipe, seed and
 * live origin, starting kit_export_delay frames into the recording. */
static u32 kit_export_origin[4],kit_export_seed[4],kit_export_delay[4],kit_export_frame[4];
static kit_pad kit_export_recipe[4],kit_hit_recipe[16];
EXPORT volatile u8 kit_edit_changed;         /* the edit pad followed a hit: redraw */
EXPORT kit_pad kit_pads[KIT_KITS][KIT_PADS] __attribute__((section(".data"))) = {{{0}}};
EXPORT const u32 kit_pad_count = KIT_PADS;
EXPORT volatile u8 kit_pads_ready __attribute__((section(".data"))) = 0;

typedef struct { float b0, b1, b2, a1, a2, z1, z2; } kit_bq;

typedef struct {
    u32 n, seed;
    float ph[6], f, fend, pe, pdec, ratio;
    float amp, adec, namp, ndec, gain, nmix;
    float lp, bp, hp1, xprev, svf_f, svf_q, hp_a;
    float mi, mdec, mr;                  /* FM: index (cycles), its per-sample decay, modulator ratio */
    kit_bq q[5]; float e[3], ed[3], qv;  /* TR-808: filters, envelopes, resonator Q */
    u8 drum, live, group, pad;
    u32 source_frame;                  /* shared-source time, independent of hit age */
    u8 source_bank; signed char source_tune; u8 source_pad_[2];
    float ctrl_sweep, ctrl_noise, ctrl_attack, ctrl_lp, noise_lp, ctrl_tone, sweep_env;
    float tone_pole;                     /* per-hit TONE low-pass coefficient */
    u8 sweep_on, noise_on, post_on;      /* SWEEP/NOISE/output controls away from the authentic 50 */
    float sweep_a1[2],sweep_radius[2];
    u32 clap_period; u8 role;
    float cy_smooth, cy_hold, cy_slow;   /* CY trigger, C41, loaded C45 voltages */
} kit_voice;
EXPORT kit_voice kit_slot[8] __attribute__((section(".data"))) = {{0}};
EXPORT volatile u32 kit_voice_stride __attribute__((section(".data"))) = sizeof(kit_voice);
EXPORT volatile u32 kit_cy_envelope_version __attribute__((section(".data"))) = 1;

/* Live render blocks own the source clock, including silent blocks and KIT OFF.
 * Each live voice consumes the same frame coordinates independently: adding a
 * voice cannot speed up or reseed the source. Export voices have a separate
 * deterministic timeline (their snapshot sample age), so offline rendering
 * cannot move the live clock. The u32 timeline wraps continuously with Q32
 * phase arithmetic after about 24.9 hours at 48 kHz. */
EXPORT u32 kit_clock_next __attribute__((section(".data"))) = 0;
EXPORT u16 kit_variants[KIT_KITS];
EXPORT u32 kit_live_cursor[4] __attribute__((section(".data"))) = {0};
static void kit_bd_begin(int frames);
EXPORT void kit_begin_block(int frames) {
    if (frames <= 0) return;
    kit_bd_begin(frames);
    for (int i = 0; i < 4; ++i) kit_live_cursor[i] = kit_clock_next;
    kit_clock_next += (u32)frames;
}

static float kit_shared_noise(u32 frame) {
    /* Stateless avalanche PRNG: identical source sample for every 808 voice
     * at a given frame. This models source sharing, not the analog transistor
     * noise spectrum or the separate 909 shift-register generator. */
    u32 x = frame + 0x9E3779B9u;
    x ^= x >> 16; x *= 0x85EBCA6Bu;
    x ^= x >> 13; x *= 0xC2B2AE35u; x ^= x >> 16;
    return (float)(int)x * 4.65661287e-10f;
}

static float kit_absf(float x) { return x < 0 ? -x : x; }
static float kit_clampf(float x, float a, float b) { return x < a ? a : x > b ? b : x; }
/* Shared preview/firmware guard; normal samples below .8 pass unchanged.
 * The stock downstream voice sum remains outside this per-voice guard. */
static float kit_limit(float y) {
    float a=kit_absf(y);
    if (a > 0.8f) { a=0.8f+0.2f*(a-0.8f)/(0.2f+a-0.8f); y=y<0 ? -a : a; }
    return y;
}
static float kit_exp2(float x) {                     /* 2^x for |x| <= 100 */
    if (x < -100) return 0;
    if (x > 100) x = 100;
    int n = (int)x;
    float t = x - n;
    /* Center the residual at zero. Flooring a tiny negative x put t near 1,
     * where the old fifth-order polynomial's bias shortened every decay.
     * Seventh-order Taylor on [-.5,.5] keeps error near float rounding, and
     * small negative decay exponents are evaluated directly next to zero. */
    if (t > 0.5f) { ++n; t -= 1; }
    else if (t < -0.5f) { --n; t += 1; }
    float p = 1 + t*(0.6931471805599453f + t*(0.2402265069591007f +
              t*(0.05550410866482158f + t*(0.009618129107628477f +
              t*(0.001333355814642844f + t*(0.000154035303933816f +
              t*0.00001525273380405984f))))));
    union { u32 bits; float value; } scale;
    scale.bits = (u32)(n + 127) << 23;
    return p * scale.value;
}
static float kit_decay60(float seconds) {             /* per-sample, -60 dB in `seconds` */
    if (seconds < 1e-4f) return 0;
    return kit_exp2(-9.96578428f / (seconds * KIT_FS));
}
static float kit_sin2pi(float p) {
    p -= (float)(int)p;
    if (p < 0) p += 1;
    if (p > 0.75f) p -= 1;
    else if (p > 0.25f) p = 0.5f - p;
    float x = 6.28318531f * p, x2 = x*x;
    return x*(1 - x2*(0.166666667f - x2*(0.00833333333f - x2*0.000198412698f)));
}
static float kit_parameter_noise(kit_voice *v,float x);
static float kit_parameter_metal(kit_voice *v,float x);
static float kit_parameter_phase(kit_voice *v,int j,float hz);
static float kit_noise(kit_voice *v) {
    if (v->drum >= T8_BD && v->drum <= T8_CH)
        return kit_parameter_noise(v,kit_shared_noise(v->source_frame));
    u32 x = v->seed;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    v->seed = x;
    return kit_parameter_noise(v,(float)(int)x * 4.65661287e-10f);
}

static int kit_slot_of(u32 a) {
    if (a == KIT_SINGLETON) return 0;
    u32 d = a - KIT_CLONE_BASE;
    if (d < 3*KIT_VOICE_SIZE && d % KIT_VOICE_SIZE == 0) return 1 + (int)(d/KIT_VOICE_SIZE);
    d = a - KIT_EXPORT_BASE;
    if (d < 4*KIT_VOICE_SIZE && d % KIT_VOICE_SIZE == 0) return 4 + (int)(d/KIT_VOICE_SIZE);
    return -1;
}

static __attribute__((noinline, minsize)) void kit_init_pads(void) {
    static const u8 decay_position[40] = {0,0,0,6,17,25,33,39,45,50,55,59,63,66,69,73,76,78,81,83,86,88,90,92,94,96,98,100,100,100,100,100,100,100,100,100,100,100,100,100};
    if (kit_pads_ready) return;
    for (int k=0; k<KIT_KITS; ++k) {
        for (int j=0; j<16; ++j) {
            const kit_factory_pad *f = &kit_factory[k][j];
            kit_pad p = {f->sound,f->tune,decay_position[f->decay-1],
                         (signed char)(50+5*f->tone),f->level,50,50,50};
            if (p.tune < -12) p.tune=-12;
            if (p.tune > 12) p.tune=12;
            /* 808 BD: decay and tone pots at their centre, as a stock 808 and
             * the ACB plug-in default (t40 about 420 ms). Sweep/noise/attack 50
             * are the authentic voice for every sound (kit_parameters.inc). */
            if (p.sound == T8_BD) { p.decay=50; p.tone=50; }
            kit_pads[k][j]=p;
        }
    }
    static const u16 active[KIT_KITS] = {0xffff,0x028f,0x02bf,0x00ff,0xffff,0x07ff,0x007f,0x0077,0x7fff,0x3fff,0x3fff,0x7fff,0x7fff};
    for(int k=0;k<KIT_KITS;++k){
        u8 source[16];int n=0,variant=0;
        for(int j=0;j<16;++j)if(active[k]&(1u<<j))source[n++]=(u8)j;
        kit_variants[k]=(u16)~active[k];
        for(int j=0;j<16;++j)if(!(active[k]&(1u<<j))){
            kit_pad p=kit_pads[k][source[variant%n]];
            static const signed char tuning[8]={-5,3,0,-2,7,-7,5,-3};
            p.tune=tuning[variant&7];p.decay=(u8)(variant&1?32:82);
            p.tone=(signed char)(variant&1?68:38);p.attack=(u8)(variant&1?75:35);
            kit_pads[k][j]=p;++variant;
        }
    }
    kit_pads_ready=1;
}

/* Which pad a voice plays: its own pad, an arp step's source pad, or note % 16. */
static int kit_pad_of(const u8 *s) {
    int src = *(const int *)(s + 0x1AC), note = *(const int *)(s + 0x19C);
    if (src >= 0 && src < 16) return src;
#ifdef KIT_IN_ARP
    for (int k = 0; k < held_count && k < MAXN; k++) {
        int d = note - held_note[k];
        if (held_src[k] < 16 && d % 12 == 0) return held_src[k];
    }
#endif
    return ((note % 16) + 16) % 16;
}

/* ---- TR-808 voices (T8_*): circuit-informed models ----
 * Values from Roland's TR-808 Service Notes (1981) and Werner, Abel & Smith's
 * circuit analyses (DAFx-14 bass drum, ICMC-14 cymbal), as collected in
 * 2AMLogic/gf180-monosynth docs/tr808-reference.md. Bridged-T voices are
 * band-pass resonators rung by the 808's 1 ms trigger pulse; hats, cymbal and
 * cowbell use the six Schmitt-trigger squares (band-limited here) through
 * the 808's band-pass/high-pass filters and VCA envelopes.
 * Controls: TUNE moves every frequency; DECAY scales the decay time; TONE is
 * the 808's own knob for BD (tone), SD (snappy) and CY (tone); on every other
 * voice it is the broadband tilt in kit_parameters_output. */
#define KIT_TAU(s) kit_exp2(-1.44269504f / ((s) * KIT_FS))          /* per-sample, 1/e in s seconds */

/* CY slow envelope: Werner/Abel/Smith ICMC 2014, Fig.1 and sections 6-7.
 * This implements their separated envelope approximation, not the coupled
 * transistor/diode VCA. R93 and VR2 are SERIES in Fig.1: the printed product
 * in Eq.9 is dimensionally inconsistent. Eq.10 is a one-pole low-pass despite
 * the prose calling it a high shelf. R104 is its approximate 22k load.
 * The other two bands retain approximate decay laws pending coupled VCA work.
 * DECAY 100% maps to 25% of the 2M pot; 400% reaches its maximum resistance. */
static float kit_cy_rc_alpha(float tau) {
    /* 1-exp(-x), avoiding cancellation for slow RC stages (x < .001 here). */
    float x = 1.0f / (KIT_FS * tau);
    return x * (1 - x * (0.5f - x * (1.0f / 6)));
}
static void kit_cy_envelope_start(kit_voice *v, float k) {
    v->cy_smooth = v->cy_hold = v->cy_slow = 0;
    v->e[0] = v->e[1] = v->e[2] = 0;
    float pot = kit_clampf(k * 0.25f, 0, 1);
    v->ed[0] = kit_cy_rc_alpha((470000.0f + 2000000.0f * pot) * 1e-6f);
    /* All three CY ed[] entries store a release fraction, not a pole near 1.
     * Subtracting alpha*state avoids quantizing long decay times to that pole. */
    v->ed[1] = kit_cy_rc_alpha(0.19f * (0.65f + 0.35f * kit_clampf(k, 0.1f, 4)));
    v->ed[2] = kit_cy_rc_alpha(0.035f);
}
static void kit_cy_envelope_tick(kit_voice *v, float trigger_volts) {
    const float trigger_drop = 0.7258f, diode_drop = 0.5899f, follower_drop = 0.6195f;
    const float attack_alpha = 0.1840246061f; /* 1-exp(-1/(48000 * 102.44e-6)) */
    const float slow_alpha = kit_cy_rc_alpha(0.02904f); /* (33k || 22k) * 2.2u */
    float target = trigger_volts > trigger_drop ? trigger_volts - trigger_drop : 0;
    v->cy_smooth += attack_alpha * (target - v->cy_smooth);
    float charge = v->cy_smooth > diode_drop ? v->cy_smooth - diode_drop : 0;
    v->cy_hold -= v->cy_hold * v->ed[0];
    if (charge > v->cy_hold) v->cy_hold = charge;
    float follower = v->cy_hold > follower_drop ? v->cy_hold - follower_drop : 0;
    v->cy_slow += slow_alpha * (0.4f * follower - v->cy_slow);
    v->e[0] = v->cy_slow / (0.4f * (7 - trigger_drop - diode_drop - follower_drop));
    float peak = charge / (7 - trigger_drop - diode_drop);
    v->e[1] -= v->e[1] * v->ed[1]; v->e[2] -= v->e[2] * v->ed[2];
    if (peak > v->e[1]) v->e[1] = peak;
    if (peak > v->e[2]) v->e[2] = peak;
}

static float kit_sqrtf(float x) { return __builtin_sqrtf(x); }
/* sin and cos of 2*pi*f/fs, accurate for low f (cos from the half angle). */
static void kit_sincos(float f, float *s, float *c) {
    float h = kit_sin2pi(kit_clampf(f / KIT_FS, 0, 0.49f) * 0.5f);
    *c = 1 - 2*h*h; *s = 2*h*kit_sqrtf(1 - h*h);
}
/* Keep coefficient builders out of line: duplicated call-site code consumes
 * scarce stored-module space. Measured ARM instruction cost is recorded in
 * layout_v929; arithmetic and persistent filter state are unchanged. */
static __attribute__((noinline)) void bq_bp(kit_bq *q, float f, float Q) { /* RBJ band-pass, 0 dB peak */
    float s, c; kit_sincos(f, &s, &c);
    float a = s / (2*Q), n = 1 / (1 + a);
    q->b0 = a*n; q->b1 = 0; q->b2 = -a*n; q->a1 = -2*c*n; q->a2 = (1 - a)*n;
}
static __attribute__((noinline)) void bq_hp(kit_bq *q, float f, float Q) { /* RBJ high-pass */
    float s, c; kit_sincos(f, &s, &c);
    float a = s / (2*Q), n = 1 / (1 + a);
    q->b0 = (1 + c)*0.5f*n; q->b1 = -(1 + c)*n; q->b2 = q->b0; q->a1 = -2*c*n; q->a2 = (1 - a)*n;
}
static __attribute__((noinline)) void bq_lp(kit_bq *q, float f, float Q) { /* RBJ low-pass */
    float s, c; kit_sincos(f, &s, &c);
    float a = s / (2*Q), n = 1 / (1 + a);
    q->b0 = (1 - c)*0.5f*n; q->b1 = (1 - c)*n; q->b2 = q->b0; q->a1 = -2*c*n; q->a2 = (1 - a)*n;
}
static float bq_run(kit_bq *q, float x) {                    /* transposed direct form II */
    float y = q->b0*x + q->z1;
    q->z1 = q->b1*x - q->a1*y + q->z2;
    q->z2 = q->b2*x - q->a2*y;
    return y;
}
/* A free-ringing mode A e^(-t/tau) sin(2 pi hz t + phi), started from its
 * state instead of a pulse, so a least-squares fit to recordings sets A, phi
 * and tau directly. as = A sin(phi), ac = A cos(phi); run with bq_run(q, 0). */
static __attribute__((noinline)) void kit_free_ring(kit_bq *q, float hz, float tau, float as, float ac) {
    float s, c, r = KIT_TAU(tau);
    kit_sincos(hz, &s, &c);
    q->b0 = q->b1 = q->b2 = 0;
    q->a1 = -2*r*c; q->a2 = r*r;
    q->z1 = as; q->z2 = r*(s*ac + c*as) + q->a1*as;
}
/* Hold-then-release VCA (CR-78/CR-8000 trigger envelopes): the level e[2]
 * falls with time constant tau_hold for `hold` seconds, then tau_release.
 * A voice that sets mi > 0 also gets a linear rise over 1/mi samples. */
static __attribute__((noinline)) void kit_hold(kit_voice *v, float tau_hold, float hold, float tau_release) {
    v->e[2] = 1.0f; v->ed[2] = KIT_TAU(tau_hold);
    v->qv = hold * KIT_FS; v->mdec = KIT_TAU(tau_release);
}
static float kit_vca(kit_voice *v) {
    float a = v->e[2];
    v->e[2] *= (float)v->n < v->qv ? v->ed[2] : v->mdec;
    if (v->mi > 0.0f && (float)v->n * v->mi < 1.0f) a *= (float)v->n * v->mi;
    return a;
}
/* Band-limited square (PolyBLEP), duty d; phase p in [0,1), increment dt. */
static float kit_blep(float t, float dt) {
    if (t < dt) { t /= dt; return t + t - t*t - 1; }
    if (t > 1 - dt) { t = (t - 1) / dt; return t*t + t + t + 1; }
    return 0;
}
static float kit_pulse(float p, float dt, float d) {
    float y = p < d ? 1.0f : -1.0f, t = p - d;
    if (t < 0) t += 1;
    return y + kit_blep(p, dt) - kit_blep(t, dt);
}
static float kit_squares_at(float ratio, u32 frame, int first, int count, float *ph) {
    static const float hz[6] = {205.3f, 304.4f, 369.6f, 522.7f, 540.0f, 800.0f};
    float x = 0;
    for (int j = first; j < first + count; ++j) {
        float dt = hz[j] * ratio / KIT_FS;
        /* Integer phase removes long-running float-time precision loss. All
         * voices at the same TUNE read the same six oscillators; a note never
         * resets them. Nonzero TUNE extends the model with a virtual oscillator
         * bank at that tuning, rather than changing the other pads' source. */
        u32 step = (u32)(dt * 4294967296.0f);
        u32 phase = step * frame;
        float p = (float)phase * 2.3283064365386963e-10f;
        if (p >= 1.0f) p = 0.0f;
        if (ph) ph[j] = p;
        x += kit_pulse(p, dt, 0.4798f);
    }
    return x;
}
static float kit_squares(kit_voice *v, int first, int count) {
    if(v->sweep_on && (v->role==1||v->role==4||v->role==5)) {
        static const float hz[6]={205.3f,304.4f,369.6f,522.7f,540.0f,800.0f};float x=0;
        for(int j=first;j<first+count;++j){float f=hz[j]*v->ratio;x+=kit_pulse(kit_parameter_phase(v,j,f),f/KIT_FS,.4798f);}
        return kit_parameter_metal(v,x);
    }
    return kit_parameter_metal(v,kit_squares_at(v->ratio, v->source_frame, first, count, v->ph));
}

/* CY's two BPFs precede its envelopes and HPFs. They belong to its source
 * path, not to a hit. Each tuning is a virtual circuit; live/export have
 * independent caches. A cache holds a whole block because live voices are
 * rendered voice-major. Missed short spans are advanced exactly. For a long
 * silent gap, 512 prior input samples reconstruct the state: the omitted
 * IIR tail is bounded and checked separately against a long-run reference.
 * This avoids rendering all 49 possible tunings throughout silence. */
#define KIT_CY_BLOCK 64u
#define KIT_CY_HISTORY 512u
typedef struct { kit_bq q[2]; u32 next_frame, ready; } kit_cy_state;
typedef struct { float lo[64], hi[64]; u32 origin, tune_key, valid; } kit_cy_cache;
EXPORT kit_cy_state kit_cy_states[2][49] __attribute__((section(".data"))) = {{{{0}}}};
EXPORT kit_cy_cache kit_cy_caches[2][4] __attribute__((section(".data"))) = {{{{0}}}};
EXPORT u32 kit_cy_cache_next[2] __attribute__((section(".data"))) = {0};

#include "kitcy_history.inc"

static void kit_cy_reconstruct(kit_cy_state *s, float ratio, u32 origin) {
    /* A linear filter's final state is sum(delta x[n] * S(H-n)), where
     * S(m) is its state after m unit inputs. Oscillator plateaus therefore
     * need only one update. Evaluate every PolyBLEP edge sample with the
     * same Q32 phase conversion as normal rendering; skip only safely
     * inside constant plateaus. All 512 history samples remain represented.
     * The table uses the fixed 3450/7100 Hz, Q=6 coefficients checked by the
     * generator regression. Summation order differs from sample recurrence. */
    static const float hz[6] = {205.3f, 304.4f, 369.6f, 522.7f, 540.0f, 800.0f};
    float z0 = 0, z1 = 0, z2 = 0, z3 = 0;
    for (int j = 0; j < 6; ++j) {
        float dt = hz[j] * ratio / KIT_FS, prev = 0;
        u32 step = (u32)(dt * 4294967296.0f);
        u32 phase = step * (origin - KIT_CY_HISTORY), n = 0;
        while (n < KIT_CY_HISTORY) {
            float p = (float)phase * 2.3283064365386963e-10f;
            if (p >= 1.0f) p = 0;
            float x = kit_pulse(p, dt, 0.4798f), dx = x - prev;
            if (dx != 0) {
                const float *h = kit_cy_step_state[KIT_CY_HISTORY - n];
                z0 += dx*h[0]; z1 += dx*h[1];
                z2 += dx*h[2]; z3 += dx*h[3];
            }
            prev = x;
            u32 skip = 1;
            /* The guard exceeds float phase/duty-subtraction rounding.
             * Floor distance/step stops at or before the guarded edge. */
            float end = 0;
            if (p > dt + 1e-6f && p < 0.4798f - dt - 1e-6f)
                end = 0.4798f - dt - 1e-6f;
            else if (p > 0.4798f + dt + 1e-6f && p < 1 - dt - 1e-6f)
                end = 1 - dt - 1e-6f;
            if (end > 0) {
                u32 target = (u32)(end * 4294967296.0f);
                if (target > phase) skip = (target - phase) / step;
                if (skip < 1) skip = 1;
            }
            if (skip > KIT_CY_HISTORY - n) skip = KIT_CY_HISTORY - n;
            phase += step * skip;
            n += skip;
        }
    }
    s->q[0].z1 = z0*(1.0f/6); s->q[0].z2 = z1*(1.0f/6);
    s->q[1].z1 = z2*(1.0f/6); s->q[1].z2 = z3*(1.0f/6);
    s->next_frame = origin;
    s->ready = 1;
}

static void kit808_cymbal_source(kit_voice *v, float *lo, float *hi) {
    if(v->sweep_on || v->noise_on){
        float x=kit_parameter_metal(v,kit_squares(v,0,6)*(1.0f/6));
        *lo=bq_run(&v->q[0],x);*hi=bq_run(&v->q[1],x);return;
    }
    u32 bank = v->source_bank & 1u;
    int tune = v->source_tune;
    if (tune < -24) tune = -24;
    if (tune > 24) tune = 24;
    u32 key = (u32)(tune + 24), origin = v->source_frame & ~(KIT_CY_BLOCK - 1u);
    kit_cy_cache *cache = 0;
    for (int i = 0; i < 4; ++i) {
        kit_cy_cache *c = &kit_cy_caches[bank][i];
        if (c->valid && c->origin == origin && c->tune_key == key) { cache = c; break; }
    }
    if (!cache) {
        cache = &kit_cy_caches[bank][kit_cy_cache_next[bank]++ & 3u];
        cache->valid = 0;
        kit_cy_state *s = &kit_cy_states[bank][key];
        if (!s->ready) {
            bq_bp(&s->q[0], 3450, 6); bq_bp(&s->q[1], 7100, 6);
        }
        /* Compute ratio from the cache key: cache identity must determine its
         * source even if a diagnostic caller supplies inconsistent fields. */
        float ratio = kit_exp2((float)tune / 12);
        if (!s->ready || origin - s->next_frame > KIT_CY_HISTORY)
            kit_cy_reconstruct(s, ratio, origin);
        static const float hz[6] = {205.3f, 304.4f, 369.6f, 522.7f, 540.0f, 800.0f};
        float dt[6]; u32 step[6], phase[6];
        for (int j = 0; j < 6; ++j) {
            dt[j] = hz[j] * ratio / KIT_FS;
            step[j] = (u32)(dt[j] * 4294967296.0f);
            phase[j] = step[j] * s->next_frame;
        }
        u32 stop = origin + KIT_CY_BLOCK;
        while (s->next_frame != stop) {
            u32 frame = s->next_frame++;
            float x = 0;
            for (int j = 0; j < 6; ++j) {
                float ph = (float)phase[j] * 2.3283064365386963e-10f;
                if (ph >= 1.0f) ph = 0;
                x += kit_pulse(ph, dt[j], 0.4798f);
                phase[j] += step[j];
            }
            x *= 1.0f / 6;
            float a = bq_run(&s->q[0], x), b = bq_run(&s->q[1], x);
            u32 offset = frame - origin;
            if (offset < KIT_CY_BLOCK) { cache->lo[offset] = a; cache->hi[offset] = b; }
        }
        s->ready = 1;
        cache->origin = origin; cache->tune_key = key; cache->valid = 1;
    }
    u32 offset = v->source_frame - origin;
    *lo = cache->lo[offset]; *hi = cache->hi[offset];
}

static void kit808_start(kit_voice *v, float r, float k, float t) {
    int j;
    for (j = 0; j < 5; ++j) { v->q[j].z1 = v->q[j].z2 = 0; }
    for (j = 0; j < 3; ++j) { v->e[j] = 0; v->ed[j] = 0; }
    v->f = 0; v->fend = 0; v->pe = 0; v->pdec = 0; v->qv = 1;
    float kk = kit_clampf(k, 0.1f, 4.0f), s = kit_exp2(1.2f * t);   /* strike / knob, x0.44..x2.3 */
    switch (v->drum) {
    case T8_BD:                       /* 49.4 Hz bridged-T; attack ~130 Hz, Q 6 for ~5 ms */
        v->fend = 49.4f*r; v->qv = kit_clampf(3.14159265f*v->fend*0.11f*kk, 2.3f, 120);   /* tau 15..544 ms */
        bq_bp(&v->q[0], 130*r, 6);
        v->lp = 0; v->bp = 1 - kit_exp2(-6.28318531f*1.4427f*305*kit_exp2(4.56f*(t + 1)*0.5f)/KIT_FS); /* tone LP 305 Hz..7.2 kHz */
        break;
    case T8_SD:
        /* Native dry TR-808 reference, neutral TONE: damped modes near
         * 168.10 / 325.68 Hz, tau 31.65 / 9.07 ms. RBJ center/Q values
         * compensate the small damped-pole frequency shift. The old
         * 238 / 476 Hz values came from the earlier service-note table.
         * See kit_native_reference_validation/808_SNARE_CALIBRATION.md.
         * Excitation phase and noise-source calibration remain separate. */
        bq_bp(&v->q[0], 168.17f*r, kit_clampf(16.72f*kk, 2, 80));
        bq_bp(&v->q[1], 326.15f*r, kit_clampf(9.29f*kk, 2, 60));
        bq_bp(&v->q[2], 2750, 0.7f);
        /* Default-reference residual envelope and relative spectral balance;
         * keep the source/filter topology pending independent validation. */
        v->e[0] = 1; v->ed[0] = KIT_TAU(0.024f*kk); v->nmix = 0.65f*s;
        break;
    case T8_LT: case T8_MT: case T8_HT: case T8_LC: case T8_MC: case T8_HC: {
        static const float hz[6] = {90, 135, 185, 199, 280, 412}, qs[6] = {25, 25, 25, 43, 33, 42};   /* Fischer knob-centre pitches */
        static const float drop[6] = {0.015f, 0.013f, 0.011f, 0.009f, 0.008f, 0.007f};
        j = v->drum - T8_LT;
        v->fend = hz[j]*r; v->qv = qs[j]*kk;                     /* Q scales the ring time */
        /* Short DECAY widens this 0-dB-peak band-pass and increases the
         * trigger response. Compensate its numerator's approximate 1/Q
         * scaling, retaining the original gain at 100% and longer decay.
         * This affects the resonant body only, not the tom noise path. */
        v->amp = kk < 1.0f ? kk : 1.0f;
        /* Fischer's 808 grid shows no audible onset glide: keep only a trace. */
        v->pe = (j < 3 ? 0.025f : 0.012f)*s; v->pdec = KIT_TAU(drop[j]);
        if (j < 3) { v->e[0] = 1; v->ed[0] = KIT_TAU(0.085f*kk); v->hp1 = 0; v->lp = 0; }   /* tom noise */
        break;
    }
    case T8_RS:                       /* 455 Hz + 1667 Hz, through the swing VCA */
        bq_bp(&v->q[0], 455*r, 6.7f); bq_bp(&v->q[1], 1667*r, 13.5f);
        v->hp1 = v->xprev = 0;
        v->e[0] = 0.022f*kk*KIT_FS; break;
    case T8_CL:                       /* 2.5 kHz, high Q, gated ~22 ms */
        bq_bp(&v->q[0], 2440*r, 60); v->e[0] = 0.022f*kk*KIT_FS; break;   /* recordings: 2420-2450 Hz */
    case T8_CP:                       /* noise, BP 1.07 kHz Q 1.6: three 10 ms bursts, then a 47 ms tail */
        bq_bp(&v->q[0], 1250*r, 0.9f); v->e[1] = 1; v->ed[1] = KIT_TAU(0.060f*kk); break;
    case T8_MA:                       /* noise, HP 10.6 kHz Q 2.3, ~15 ms */
        bq_hp(&v->q[0], kit_clampf(7600*r, 2000, 20000), 1.0f); bq_lp(&v->q[1], 12500, 0.7f); v->ed[0] = KIT_TAU(0.0025f*kk); break;
    case T8_CB:                       /* 540 + 800 Hz squares, BP 1.1 kHz Q 2.8, two-slope decay */
        v->ratio = r; bq_bp(&v->q[0], 1400*r, 2.0f);
        v->e[0] = 0.88f; v->ed[0] = KIT_TAU(0.006f*kk); v->e[1] = 0.12f; v->ed[1] = KIT_TAU(0.123f*kk); break;
    case T8_CY:                       /* BP 3.45k / 7.1k, three high-passed bands, own envelopes */
        v->ratio = r;
        /* The two pre-envelope BPFs live in kit_cy_states, across hits. */
        bq_hp(&v->q[2], 2500, 0.97f); bq_hp(&v->q[3], 8840, 1.0f); bq_hp(&v->q[4], 10320, 5.64f);
        kit_cy_envelope_start(v, kk);
        v->nmix = s; break;                                         /* TONE: low vs high bands */
    case T8_OH: case T8_CH:           /* 7.1 kHz band; HP 7.8k (open) / 11.7k (closed) */
        v->ratio = r; v->group = 1;
        bq_bp(&v->q[1], v->drum == T8_OH ? 8500.0f : 11000.0f, v->drum == T8_OH ? 1.0f : 0.8f);
        bq_hp(&v->q[2], v->drum == T8_OH ? 6200 : 7000, 0.8f);
        if (v->drum == T8_OH) {
            /* Fischer OH grid: -20 dB at 72/188/326/436/466 ms for DECAY 0..10, the
             * level holding and then cutting off (t40 only 5-30% later). Model it
             * as an exponential over a 30% floor that the VCA ignores. */
            static const float kn[5] = {0.354f, 0.595f, 1.0f, 1.682f, 2.828f}, tau[5] = {0.072f, 0.189f, 0.328f, 0.439f, 0.469f};
            float kq = kit_clampf(k, kn[0], kn[4]), tt = tau[4];
            for (j = 0; j < 4; ++j) if (kq <= kn[j + 1]) { tt = tau[j] + (tau[j + 1] - tau[j]) * (kq - kn[j]) / (kn[j + 1] - kn[j]); break; }
            v->e[0] = 1; v->ed[0] = KIT_TAU(tt);
        } else { v->e[0] = 1; v->ed[0] = KIT_TAU(0.019f*kk); }
        v->nmix = s; break;
    }
}

static float kit808_render(kit_voice *v) {
    u32 n = v->n;
    float pulse = n < 48 ? 1.0f : 0.0f, y = 0, x, f;            /* the 1 ms trigger pulse */
    switch (v->drum) {
    case T8_BD:
        if (n == 240) bq_bp(&v->q[0], v->fend, v->qv);              /* after ~5 ms: the resting resonance */
        y = bq_run(&v->q[0], pulse) * (n < 240 ? 2.2f : 6.0f);
        v->lp += v->bp * (y - v->lp); y = v->lp;
        if (n > 4800 && kit_absf(v->q[0].z1) + kit_absf(v->q[0].z2) < 1e-6f) v->live = 0;
        break;
    case T8_SD:
        /* Relative body-mode balance from the neutral native dry hit.
         * This preserves the existing pulse convention and output gain. */
        y = 2.9f*bq_run(&v->q[0], pulse) + 2.18f*bq_run(&v->q[1], pulse);
        y += bq_run(&v->q[2], kit_noise(v)) * v->e[0] * v->nmix * 0.8f; v->e[0] *= v->ed[0];
        if (n > 2400 && v->e[0] < KIT_SILENT && kit_absf(v->q[0].z1) + kit_absf(v->q[1].z1) < 1e-6f) v->live = 0;
        break;
    case T8_LT: case T8_MT: case T8_HT: case T8_LC: case T8_MC: case T8_HC:
        f = v->fend * (1 + v->pe); v->pe *= v->pdec;
        if (n == 0 || v->pe > 1e-4f) {                              /* the pitch falls as the diode stops conducting */
            float z1 = v->q[0].z1, z2 = v->q[0].z2;
            bq_bp(&v->q[0], f, v->qv); v->q[0].z1 = z1; v->q[0].z2 = z2;
        }
        { static const float g[6] = {24.5f, 21.0f, 13.9f, 40.5f, 20.7f, 25.2f};
          y = bq_run(&v->q[0], pulse) * g[v->drum - T8_LT] * v->amp; }
        if (v->drum <= T8_HT) {                                     /* faint noise, two-pole LP ~400 Hz */
            v->hp1 += 0.051f * (kit_noise(v) - v->hp1);
            v->lp += 0.051f * (v->hp1 - v->lp);
            y += v->lp * v->e[0] * 0.30f; v->e[0] *= v->ed[0];
        }
        if (n > 4800 && kit_absf(v->q[0].z1) + kit_absf(v->q[0].z2) < 1e-6f) v->live = 0;
        break;
    case T8_RS:
        /* The trigger reaches the bridged-T pair through a coupling capacitor:
         * its two edges, not the 1 ms plateau, excite them. That is what lets the
         * 1.67 kHz mode ring as loudly as the recordings show. */
        x = n == 0 ? 1.0f : n == 48 ? -1.0f : 0.0f;
        y = 2.6f*bq_run(&v->q[0], x) + 7.5f*bq_run(&v->q[1], x);
        y = y > 0 ? y : 0.25f*y;                                    /* swing VCA: mostly one polarity */
        v->hp1 = 0.975f*(v->hp1 + y - v->xprev); v->xprev = y; y = v->hp1 + 0.25f*x;   /* coupling: no DC thump; edge click */
        if (n > (u32)v->e[0]) { v->e[1] = v->e[1] == 0 ? 1 : v->e[1] * 0.96f; y *= v->e[1]; if (v->e[1] < 1e-4f) v->live = 0; }
        else v->e[1] = 0;
        y *= 0.55f; break;
    case T8_CL:
        y = 30.0f*bq_run(&v->q[0], pulse);
        if (n > (u32)v->e[0]) { v->e[1] = v->e[1] == 0 ? 1 : v->e[1] * 0.96f; y *= v->e[1]; if (v->e[1] < 1e-4f) v->live = 0; }
        else v->e[1] = 0;
        break;
    case T8_CP: {
        u32 m = n % v->clap_period;                                            /* 10 ms sawtooth bursts */
        /* Recordings: bursts at 0, 12 and 24 ms, each down ~20 dB within 9 ms;
         * the reverb tail enters at full level near 36 ms. */
        float burst = n < 3*v->clap_period ? kit_exp2(-(float)m * (3.32f / 432.0f)) : 0;
        float tail = n >= 3*v->clap_period ? v->e[1] : 0;
        x = bq_run(&v->q[0], kit_noise(v));
        y = x * (burst + tail) * 1.75f; if (n >= 3*v->clap_period) v->e[1] *= v->ed[1];
        if (n > 1440 && v->e[1] < KIT_SILENT) v->live = 0;
        break;
    }
    case T8_MA:
        /* Recordings swell for ~16 ms, then fall 40 dB within ~9 ms. */
        if (n < 768) { float a = (float)(n + 1) / 768; v->e[0] = a*a*(3 - 2*a); } else v->e[0] *= v->ed[0];
        y = bq_run(&v->q[1], bq_run(&v->q[0], kit_noise(v))) * v->e[0] * 0.6f;
        if (n > 768 && v->e[0] < KIT_SILENT) v->live = 0;
        break;
    case T8_CB:
        x = 0.45f*kit_squares(v, 4, 1) + kit_squares(v, 5, 1);    /* 540 Hz ~7 dB under 800 Hz */
        y = bq_run(&v->q[0], x) * (v->e[0] + v->e[1]) * 1.25f;
        v->e[0] *= v->ed[0]; v->e[1] *= v->ed[1];
        if (n > 480 && v->e[1] < KIT_SILENT) v->live = 0;
        break;
    case T8_CY: {
        float lo, hi; kit808_cymbal_source(v, &lo, &hi);
        kit_cy_envelope_tick(v, n < 48 ? 7.0f : 0.0f); /* normal-strength 1 ms trigger */
        /* Documented order: source BPF -> envelope/VCA -> HPF -> tone/level.
         * Multiplication still approximates the nonlinear swing VCA. */
        /* Recordings and ACB: the 6-12 kHz bands lead (-20 dB within ~300 ms
         * at centre DECAY) over a quieter, long 3 kHz tail. TONE is the 808's
         * own low/high balance (Fischer grid: 7.1 kHz centroid at TONE 0, 8.9 kHz
         * at 10). */
        y = bq_run(&v->q[2], lo * v->e[0]) * 0.95f * (1.6f - 0.6f * v->nmix)
          + (bq_run(&v->q[3], hi * v->e[1]) * 2.0f + bq_run(&v->q[4], hi * v->e[2]) * 1.6f) * 4.0f * v->nmix;
        y *= 1.4f;
        if (n > 480 && v->e[0] < KIT_SILENT && v->e[1] < KIT_SILENT && v->e[2] < KIT_SILENT) v->live = 0;
        break;
    }
    case T8_OH: case T8_CH:
        x = kit_squares(v, 0, 6) * (1.0f / 6);
        f = v->drum == T8_OH ? (v->e[0] > 0.3f ? (v->e[0] - 0.3f) * (1.0f / 0.7f) : 0.0f) : v->e[0];
        y = bq_run(&v->q[2], bq_run(&v->q[1], x)) * f * (v->drum == T8_OH ? 4.6f : 6.0f) * kit_clampf(v->nmix, 0.5f, 1.6f);
        v->e[0] *= v->ed[0];
        if (n > 480 && v->e[0] < KIT_SILENT) v->live = 0;
        break;
    }
    v->n = n + 1;
    v->source_frame += 1;
    /* Headroom for arbitrary source phase: phase-zero-only previews miss the
     * larger peaks produced by other oscillator/noise alignments. This is an
     * output-level calibration, not an analog VCA/saturation model. */
    if (v->drum >= T8_CB && v->drum <= T8_CH) y *= 0.6f;
    else if (v->drum == T8_MA) y *= 0.8f;
    return y * v->gain;
}

#include "kit909.inc"
#include "kit606.inc"
#include "kitsds.inc"
#include "kitcr78.inc"
#include "kitcr8000.inc"
#include "kitprocedural.inc"
#include "kitfm.inc"
#include "kitdata.inc"
#include "tr808/lifecycle_v930/kit_bd_lifecycle.inc"
#include "kit_level_trims.inc"

#include "kit_parameters.inc"

static void kit_start(kit_voice *v, int i, int pad) {
    kit_init_pads();
    int kit = kit_mode < 1 ? 1 : kit_mode > KIT_KITS ? KIT_KITS : kit_mode;
    const kit_pad *P = i>=4&&kit_export_active?&kit_export_recipe[(i-4)&3]:&kit_pads[kit - 1][pad & 15];
    if(P->sound==KIT_OFF_SOUND){v->live=0;v->n=0;v->drum=KIT_OFF_SOUND;return;}
    float k = kit_exp2((kit_clampf((float)P->decay, 0, 100)-50) * 0.03f);         /* decay scale */
    float r = kit_exp2((float)P->tune / 12);                     /* pitch ratio */
    /* Internal colour -1..1: the 808 cymbal's TONE and snare's SNAPPY knobs;
     * other voices use TONE as the generic tilt in kit_parameters_output. */
    float t = (P->sound == T8_CY || P->sound == T8_SD) ? (kit_clampf((float)P->tone, 0, 100) - 50) * 0.02f : 0;
    float c = kit_exp2(1.2f * t);                                /* brightness */
    int j, first = i < 4 ? 0 : 4;
    kit_parameters_init(v,P);
    v->drum = (u8)(P->sound % KIT_SOUNDS); v->pad = (u8)pad; v->n = 0; v->live = 1;
    v->source_frame = i < 4 ? kit_live_cursor[i] : kit_export_active?kit_export_origin[(i-4)&3]:0;
    v->source_bank = i < 4 ? 0 : 1;
    v->source_tune = P->tune < -24 ? -24 : P->tune > 24 ? 24 : P->tune;
    /* The hit clock makes every hit's noise differ, as analog noise does. */
    v->seed = 0x9E3779B9u ^ ((u32)i * 0x85EBCA6Bu) ^ ((u32)pad * 0xC2B2AE35u) ^ (v->source_frame * 0x27D4EB2Du);
    if(i<4){kit_hit_origin[pad&15]=v->source_frame;kit_hit_seed[pad&15]=v->seed;kit_hit_mode[pad&15]=(u8)kit;kit_hit_recipe[pad&15]=*P;}
    else if(kit_export_active)v->seed=kit_export_seed[(i-4)&3];
    for (j = 0; j < 6; ++j) v->ph[j] = 0;
    v->lp = v->bp = v->hp1 = v->xprev = 0;
    v->amp = 1; v->namp = 0; v->ndec = 0; v->pe = 0; v->pdec = 0;
    v->f = v->fend = 0; v->group = 0; v->svf_q = 1; v->svf_f = 0; v->hp_a = 0;
    v->mi = 0; v->mdec = 0; v->mr = 1;
    v->ratio = r; v->nmix = c;
    v->gain = (float)P->level * (1.0f / 110) * ((float)kit_level_trims[v->drum] * (1.0f/4096));
    if (v->drum >= KIT_DATA_FIRST) kitdata_start(v, r, k);
    else if (v->drum >= KIT_PROCEDURAL_FIRST) kitprocedural_start(v,r,k,t);
    else if (v->drum >= C8K_BD) kitcr8000_start(v, r, k, t);
    else if (v->drum >= C78_BD) kitcr78_start(v, r, k, t);
    else if (v->drum >= SDS_BD) kitsds_start(v, r, k, t);
    else if (v->drum >= T6_BD) kit606_start(v, r, k, t);
    else if (v->drum >= T9_BD) kit909_start(v, r, k, t);
    else if (v->drum == T8_BD) kit_bd_start(v, i, P);
    else if (v->drum > T8_BD) kit808_start(v, r, k, t);
    else kitfm_start(v, r, k);
    kit_parameters_start(v);
    if (v->group)                                    /* hats choke each other */
        for (j = first; j < first + 4; ++j)
            if (j != i && kit_slot[j].live && kit_slot[j].group == v->group) {
                /* The 606's Q24/Q25 shutoff is directed: CH shortens an
                 * existing OH envelope. An OH trigger does not shut off CH. */
                if ((v->drum == T6_CH || v->drum == T6_OH) &&
                    (kit_slot[j].drum == T6_CH || kit_slot[j].drum == T6_OH) &&
                    !(v->drum == T6_CH && kit_slot[j].drum == T6_OH))
                    continue;
                kit_slot[j].adec = kit_decay60(0.006f); kit_slot[j].ndec = kit_slot[j].adec;
                /* Circuit hats use e/ed, while legacy and FM hats use amp/adec.
                 * Shorten the current tail; never restart its amplitude. */
                kit_slot[j].ed[0] = kit_slot[j].adec;
                /* CR8K hats retire only after both envelopes finish. */
                if (kit_slot[j].drum >= C8K_BD && kit_slot[j].drum < KIT_PROCEDURAL_FIRST) {
                    kit_slot[j].ed[1] = kit_slot[j].adec;
                    kit_slot[j].ed[2] = kit_slot[j].mdec = kit_slot[j].adec;   /* hold-release VCA */
                }
                /* Table voices: release the gate now. */
                if (kit_slot[j].drum >= KIT_DATA_FIRST) kit_slot[j].qv = 1;

            }
}

static float kit_render_source(kit_voice *v, int slot) {
    if (v->drum >= KIT_DATA_FIRST) return kitdata_render(v);
    if (v->drum >= KIT_PROCEDURAL_FIRST) return kitprocedural_render(v);
    if (v->drum >= C8K_BD) return kitcr8000_render(v);
    if (v->drum >= C78_BD) return kitcr78_render(v);
    if (v->drum >= SDS_BD) return kitsds_render(v);
    if (v->drum >= T6_BD) return kit606_render(v);
    if (v->drum >= T9_BD) return kit909_render(v);
    if (v->drum == T8_BD) return kit_bd_render(v, slot);
    if (v->drum > T8_BD) return kit808_render(v);
    return kitfm_render(v);
}

static float kit_render_slot(kit_voice *v,int slot) {
    if(!v->live || v->drum==KIT_OFF_SOUND)return 0;
    /* SWEEP 50 is the authentic voice: no added movement at all. */
    if(!v->sweep_on)return kit_parameters_output(v,kit_render_source(v,slot));
    kit_parameters_tick(v);
    float f=v->f,fe=v->fend,r=v->ratio,svf=v->svf_f;
    /* Bipolar around 50: above it the pitch starts up to 44% high and falls,
     * below it the pitch starts up to 30% low and rises. */
    float movement=1+(v->ctrl_sweep-1)*(v->ctrl_sweep>1?.44f:.3f)*v->sweep_env;
    if(v->role==1||v->role==4||v->role==5||v->drum==C78_MB)v->ratio*=movement;
    if((v->role==1||v->role==2||v->drum==FM_HAT||v->drum==C78_MB) && v->pe==0){v->f*=movement;v->fend*=movement;}
    if(v->role==6 || v->drum==C78_HH || v->drum==C78_CY || v->drum>=KIT_DATA_FIRST || (v->role==1 && (v->drum==C8K_BD||v->drum==C78_BD||v->drum==T6_BD||v->drum==T8_RS||v->drum==T8_CL||v->drum==C8K_CL||v->drum==C78_CL||v->drum==T9_RS||v->drum==C78_RS||v->drum==C8K_LC||v->drum==C8K_MC||v->drum==C8K_HC)) || (v->role==2 && (v->drum==T8_SD||v->drum==T6_SD||v->drum==C8K_SD||v->drum==C78_SD)))
        for(int j=0;j<2;++j){float a=v->sweep_a1[j],r0=v->sweep_radius[j];v->q[j].a1=kit_clampf(a+(movement*movement-1)*(2*r0+a),-1.999999f*r0,1.999999f*r0);}
    float y=kit_render_source(v,slot);
    v->f=f;v->fend=fe;v->ratio=r;v->svf_f=svf;
    return kit_parameters_output(v,y);
}

/* One kit sample for voice state s (any TYPE, kit_mode != 0). */
static float kit_output_slot(const u8 *s, int i) {
    kit_voice *v = &kit_slot[i];
    if (i < 4 && (kit_bd_manager.prepared_epoch[i] != kit_bd_manager.event_epoch[i] ||
                  kit_bd_manager.prepared_parent_age[i] != KIT_PARENT_AGE[i])) {
        int pad = kit_pad_of(s);
        kit_init_pads();
        int mode = kit_mode < 1 ? 1 : kit_mode > KIT_KITS ? KIT_KITS : kit_mode;
        if (kit_pads[mode - 1][pad & 15].sound % KIT_SOUNDS == T8_BD) {
            /* The stock envelope can consume the fresh mark during a late
             * event's deferred block. Keep suppressing its entire block,
             * including an old non-BD kit_slot left behind by the takeover. */
            ++kit_bd_manager.deferred; return 0;
        }
    }
    int fresh = *(const volatile u32 *)(s + 0x18C) == 0 || KIT_ENV_RESTART[i];
    if (i >= 4 && kit_export_active) {
        /* A chord capture starts each hit at its own offset into the recording. */
        int j = (i - 4) & 3;
        if (fresh) { kit_export_frame[j] = 0; v->live = 0; }
        u32 f = kit_export_frame[j]++;
        KIT_ENV_PRESET(i) = 0;
        if (f < kit_export_delay[j]) return 0;
        fresh = f == kit_export_delay[j];
    }
    if (fresh) {
        int pad = kit_pad_of(s);
        kit_init_pads();
        int mode = kit_mode < 1 ? 1 : kit_mode > KIT_KITS ? KIT_KITS : kit_mode;
        int bd = kit_pads[mode - 1][pad & 15].sound % KIT_SOUNDS == T8_BD;
        if (i < 4 && bd) {
            kit_bd_manager_t *m = &kit_bd_manager;
            if (m->prepared_epoch[i] != m->event_epoch[i] ||
                m->prepared_parent_age[i] != KIT_PARENT_AGE[i] ||
                !m->pending_latched[i]) { ++m->deferred; return 0; }
            /* Both selected and suppressed BD slots were prepared before any
             * voice rendered. Never trigger or transfer ownership here. */
        } else kit_start(v, i, pad);
        if (i < 4 && kit_edit_pad != (u8)pad) { kit_edit_pad = (u8)pad; kit_edit_changed = 1; }
    }
    v->source_frame = i < 4 ? kit_live_cursor[i]++ : v->n+(kit_export_active?kit_export_origin[(i-4)&3]:0);
    if (!v->live) return 0;
    if (v->n >= 1) KIT_ENV_PRESET(i) = 0;    /* v9 read the ENV preset on the first sample */
    float y = kit_render_slot(v, i);
    if (v->live && s[0] && s[1] && !KIT_ENV_QUICK[i] && !KIT_ENV_FAST[i])
        *(volatile int *)(s + 0x4C) = -200;
    return kit_limit(y);
}
EXPORT float kit_output(const u8 *s) {
    int i = kit_slot_of((u32)(__UINTPTR_TYPE__)s);
    return i < 0 ? 0 : kit_output_slot(s, i);
}

/* Host diagnostics call the historical one-argument renderer directly. */
static float kit_render(kit_voice *v) {
    int i;
    if (v->drum == T8_BD) {
        for (i = 0; i < 8; ++i) if (&kit_slot[i] == v) return kit_render_slot(v, i);
        return 0.0f;
    }
    return kit_render_slot(v,0);
}

/* ---- VALUE menu items 11..17 ---- */
static const char kit_item_names[10][6] = {"KIT", "PAD", "SOUND", "TUNE", "DECAY", "TONE", "LEVEL", "SWEEP", "NOISE", "ATTCK"};
static const char kit_kit_names[KIT_KITS + 1][6] = {"OFF", "TR808", "DR110", "KPR77", "UDS", "FM", "TR909", "TR606", "SDS-V", "MP-7", "CR78", "CR8K", "TR707", "TR727"};
static const char kit_sound_names[KIT_SOUNDS][6] = {
    "FMKik", "FMSnr", "FMTom", "FMHat", "FMBel", "FMPrc", "FMLog", "FMCow",
    "8BD", "8SD", "8LT", "8MT", "8HT", "8LC", "8MC", "8HC",
    "8RS", "8CL", "8CP", "8MA", "8CB", "8CY", "8OH", "8CH",
    "9BD", "9SD", "9LT", "9MT", "9HT", "9RS", "9CP",
    "6BD", "6SD", "6LT", "6HT", "6CY", "6OH", "6CH",
    "S-BD", "S-SD", "S-LT", "S-MT", "S-HT", "S-Zap",
    "CBD", "CSD", "CRS", "CHH", "CCY", "CMA", "CCL", "CHB", "CLB", "CLC", "CCB", "CTB", "CGU", "CMB",
    "C8BD", "C8SD", "C8LT", "C8HT", "C8LC", "C8MC", "C8HC", "C8CY", "C8OH", "C8CH", "C8RS", "C8CB", "C8CL", "C8CP",
    "d-BD", "d-SD", "d-CH", "d-OH", "d-CP", "d-CY", "k-BD", "k-SD", "k-CH", "k-OH", "k-LT", "k-HT", "k-CP", "k-CY",
    "s9CH", "s9OH", "s9CY", "s9RD",
    "U-BD", "U-BD2", "U-SD", "U-SD2", "U-Tom", "U-CP", "U-CH", "U-OH",
    "M-BD", "M-SD1", "M-SD2", "M-RS", "M-CY1", "M-CY2", "M-CL", "M-CB", "M-BgH", "M-BgM", "M-BgL", "M-MA", "M-GU", "M-QJ", "M-TB",
    "7BD1", "7BD2", "7SD1", "7SD2", "7LT", "7MT", "7HT", "7RS", "7CP", "7CB", "7TB", "7CH", "7OH", "7CR", "7RD",
    "27HB", "27LB", "27MHC", "27OHC", "27LC", "27HTi", "27LTi", "27HAg", "27LAg", "27Cab", "27Mar", "27SWh", "27LWh", "27Qui", "27Chm"};

static __attribute__((noinline, minsize)) void kit_copy(char *out, const char *s) { do { *out++ = *s; } while (*s++); }
static __attribute__((noinline, minsize)) char *kit_num(char *out, int v, int sign) {
    char tmp[8]; int n = 0; u32 a = v < 0 ? (u32)-v : (u32)v;
    if (v < 0) *out++ = '-'; else if (sign && v > 0) *out++ = '+';
    do { tmp[n++] = (char)('0' + a % 10); a /= 10; } while (a);
    while (n) *out++ = tmp[--n];
    *out = 0;
    return out;
}
static __attribute__((noinline, minsize)) kit_pad *kit_edit(void) {
    kit_init_pads();
    int k = kit_mode ? kit_mode : 1;
    return &kit_pads[k - 1][kit_edit_pad & 15];
}
EXPORT __attribute__((noinline, minsize)) void kit_item_name(int item, char *out) {
    int k = item - 11;
    kit_copy(out, kit_item_names[k < 0 ? 0 : k > 9 ? 9 : k]);
}
EXPORT __attribute__((noinline, minsize)) void kit_item_text(int item, char *out) {
    kit_pad *P = kit_edit();
    switch (item) {
    case 11: kit_copy(out, kit_kit_names[kit_mode <= KIT_KITS ? kit_mode : 0]); break;
    case 12: kit_num(out, (kit_edit_pad & 15) + 1, 0); break;
    case 13: kit_copy(out, P->sound==KIT_OFF_SOUND ? "--" : kit_sound_names[P->sound % KIT_SOUNDS]); break;
    case 14: kit_num(out, P->tune, 1); break;
    case 15: { char *e = kit_num(out, P->decay, 0); e[0] = '%'; e[1] = 0; break; }
    case 16: { char *e=kit_num(out,P->tone,0); e[0]='%'; e[1]=0; break; }
    case 18: case 19: case 20: { int v=item==18?P->sweep:item==19?P->noise:P->attack; char *e=kit_num(out,v,0);e[0]='%';e[1]=0;break; }
    default: kit_num(out, P->level, 0); break;
    }
}
EXPORT __attribute__((noinline, minsize)) void kit_item_step(int item, int dir) {
    kit_pad *P = kit_edit();
    kit_edit_changed = 1;
    switch (item) {
    case 11: { /* Only entry shortcuts change between melodic and drum modes. */
        if(!kit_mode)break;
        int m = (int)kit_mode + dir; kit_mode = (u8)(m < 1 ? 1 : m > KIT_KITS ? KIT_KITS : m); break; }
    case 12: { int p = (int)(kit_edit_pad & 15) + dir; kit_edit_pad = (u8)(p < 0 ? 0 : p > 15 ? 15 : p); break; }
    case 13: { /* Restrict named machines to their modeled source inventory. */
        if(P->sound==KIT_OFF_SOUND) break;
        int k=kit_mode?kit_mode:1,lo=0,hi=KIT_SOUNDS-1;
        if(k==1){lo=T8_BD;hi=T8_CH;} else if(k==2){lo=DR_BD;hi=DR_CY;}
        else if(k==3){lo=KP_BD;hi=KP_CY;} else if(k==4){lo=U_BD;hi=U_OH;}
        else if(k==5){lo=FM_KICK;hi=FM_COW;} else if(k==7){lo=T6_BD;hi=T6_CH;}
        else if(k==8){lo=SDS_BD;hi=SDS_ZAP;} else if(k==9){lo=MP_BD;hi=MP_TB;}
        else if(k==10){lo=C78_BD;hi=C78_MB;} else if(k==11){lo=C8K_BD;hi=C8K_CP;}
        else if(k==12){lo=T7_BD1;hi=T7_RD;} else if(k==13){lo=T27_HB;hi=T27_CHM;}
        if(k==6){static const u8 ids[11]={T9_BD,T9_SD,M9_CH,M9_OH,T9_LT,T9_MT,T9_HT,M9_CY,T9_RS,T9_CP,M9_RD};int q=0;for(int n=0;n<11;++n)if(ids[n]==P->sound)q=n;P->sound=ids[(q+11+(dir<0?-1:1))%11];}
        else {int n=P->sound+dir;P->sound=(u8)(n<lo?hi:n>hi?lo:n);} break;
    }
    case 14: { int t = P->tune + dir; P->tune = (signed char)(t < -12 ? -12 : t > 12 ? 12 : t); break; }
    case 15: { int d = P->decay + dir; P->decay = (u8)(d < 0 ? 0 : d > 100 ? 100 : d); break; }
    case 16: { int t = P->tone + dir; P->tone = (signed char)(t < 0 ? 0 : t > 100 ? 100 : t); break; }
    case 18: case 19: case 20: {u8 *v=item==18?&P->sweep:item==19?&P->noise:&P->attack;int n=*v+dir;*v=(u8)(n<0?0:n>100?100:n);break;}
    default: { int l = P->level + dir; P->level = (u8)(l < 0 ? 0 : l > 127 ? 127 : l); break; }
    }
}

/* ---- hold a pad and turn VALUE: that pad's SOUND ---- */
EXPORT volatile u16 kit_pads_down;           /* pads physically held (bit = pad) */

/* Every pad note event (ARP on or off): which pads are down, and PAD follows a press. */
EXPORT void kit_note_seen(int src, int vel) {
    if ((u32)src >= 16) return;
    if (vel) {
        if(kit_mode){kit_record_bd_valid=0;kit_record_pad=(u8)src;kit_record_velocity=(u8)(vel>127?127:vel);kit_hit_velocity[src]=kit_record_velocity;}
        kit_pads_down = (u16)(kit_pads_down | (1u << src));
        int logical = src;
        if (kit_mode && kit_edit_pad != (u8)logical) { kit_edit_pad = (u8)logical; kit_edit_changed = 1; }
    } else kit_pads_down = (u16)(kit_pads_down & ~(1u << src));
}

#ifndef KIT_HOST
#define KIT_SETTINGS 0x82E01144u                                         /* setting 0x83 = VALUE cursor */
#define KIT_SETTING_GET ((int (*)(u32, int, int))0x800D94D9u)
#define KIT_SETTING_STEP ((void (*)(u32, int, int, int, int))0x800BF8C9u)
#endif

/* VALUE turned outside edit mode (0x8015cb08 / 0x8015cb18): with KIT on and a
 * pad held, step that pad's SOUND and put the cursor on SOUND. 0 = not ours. */
EXPORT int kit_turn(int dir) {
    if(!kit_mode || !kit_pads_down || !(kit_pads_down & (1u<<(kit_edit_pad&15)))){
#ifndef KIT_HOST
        int cur=KIT_SETTING_GET(KIT_SETTINGS,0x83,0);
        int next=cur+(dir<0?-1:1);
        if(kit_mode){
            if(dir<0 && next>13)next=13;
            if(dir>=0 && next>13)next=17;
            if(next<6)next=6;if(next>17)next=17;
        }else{if(next<0)next=0;if(next>10)next=10;}
        if(next!=cur)KIT_SETTING_STEP(KIT_SETTINGS,0x83,next-cur,0,0);
#endif
        return 1;
    }
    kit_item_step(13, dir < 0 ? -1 : 1);
#ifndef KIT_HOST
    int cur = KIT_SETTING_GET(KIT_SETTINGS, 0x83, 0);
    if (cur != 13) KIT_SETTING_STEP(KIT_SETTINGS, 0x83, 13 - cur, 0, 0);
#endif
    kit_edit_changed = 1;
    return 1;
}

#ifdef KIT_IN_ARP
#include "kit_ui.inc"
#include "kit_shortcut.inc"
#include "kit_output.inc"
#include "kit_record.inc"
#endif

#ifdef KIT_HOST
static int kit_host_render_from(u32 kit, u32 pad, u32 frame, int count, float *out, int clipped) {
    u8 saved_mode = kit_mode;
    u32 saved_clock = kit_clock_next, saved_cursor[4];
    kit_voice saved_voice = kit_slot[0];
    t8p_state saved_export = kit_bd_circuit[1];
    u32 saved_ready = kit_bd_manager.ready, saved_quiet = kit_bd_manager.quiet[1];
    for (int i = 0; i < 4; ++i) saved_cursor[i] = kit_live_cursor[i];
    kit_mode = (u8)kit; kit_init_pads();
    /* Standalone previews begin at a reproducible clock origin. Real repeated
     * hits use kit_begin_block/kit_output and never perform this reset. */
    kit_clock_next = frame;
    for (int i = 0; i < 4; ++i) kit_live_cursor[i] = frame;
    kit_voice *v = &kit_slot[0];
    kit_bd_preview = 1; /* cold export circuit: previews cannot reset live BD */
    kit_start(v, 0, (int)pad);
    for (int j = 0; j < count; ++j) {
        float y = v->live ? kit_render_slot(v, 0) : 0;
        out[j] = clipped ? kit_limit(y) : y;
    }
    kit_bd_preview = 0;
    int rendered = (int)v->n;
    kit_slot[0] = saved_voice;
    kit_clock_next = saved_clock; kit_mode = saved_mode;
    for (int i = 0; i < 4; ++i) kit_live_cursor[i] = saved_cursor[i];
    kit_bd_circuit[1] = saved_export;
    kit_bd_manager.ready = (kit_bd_manager.ready & ~2u) | (saved_ready & 2u);
    kit_bd_manager.quiet[1] = saved_quiet;
    return rendered;
}
/* Standalone previews start at a reproducible clock origin. */
EXPORT int kit_host_render(u32 kit, u32 pad, int count, float *out) {
    return kit_host_render_from(kit, pad, 0, count, out, 1);
}
/* Validation only: inspect the model before the firmware's final per-voice knee. */
EXPORT int kit_host_render_raw(u32 kit, u32 pad, int count, float *out) {
    return kit_host_render_from(kit, pad, 0, count, out, 0);
}
EXPORT int kit_host_render_raw_at(u32 kit, u32 pad, u32 frame, int count, float *out) {
    return kit_host_render_from(kit, pad, frame, count, out, 0);
}
EXPORT void kit_host_step(int item, int dir) { kit_item_step(item, dir); }
EXPORT void kit_host_text(int item, char *out) { kit_item_text(item, out); }
EXPORT void kit_host_name(int item, char *out) { kit_item_name(item, out); }

/* Narrow stock-wrapper lifecycle test interface. sample() mirrors only the
 * parent's fresh/restart bookkeeping, not its downstream gain/ENV/fades. */
EXPORT void kit_host_bd_reset(void) {
    u8 *p = (u8 *)&kit_bd_manager;
    for (u32 i = 0; i < sizeof(kit_bd_manager); ++i) p[i] = 0;
    kit_bd_manager.owner = -1;
    p = (u8 *)kit_bd_circuit;
    for (u32 i = 0; i < sizeof(kit_bd_circuit); ++i) p[i] = 0;
    p = (u8 *)kit_host_stock_words;
    for (u32 i = 0; i < sizeof(kit_host_stock_words); ++i) p[i] = 0;
    for (int i = 0; i < 8; ++i) {
        KIT_ENV_RESTART[i] = KIT_ENV_QUICK[i] = KIT_ENV_FAST[i] = 0;
        KIT_ENV_PRESET(i) = 0; kit_slot[i].live = 0;
    }
    for (int i = 0; i < 4; ++i) kit_host_parent_age[i] = kit_live_cursor[i] = 0;
    kit_clock_next = 0; kit_bd_preview = 0;
}
EXPORT void kit_host_bd_publish(int slot) { kit_voice_started(slot); }
EXPORT void kit_host_bd_note(int slot, int pad, int publish) {
    if ((u32)slot >= 8) return;
    u8 *s = kit_stock_voice(slot);
    s[0] = 1; s[1] = 0;
    *(u32 *)(s + 0x18C) = 0;
    *(int *)(s + 0x1AC) = pad; *(int *)(s + 0x19C) = pad;
    KIT_ENV_QUICK[slot] = KIT_ENV_FAST[slot] = KIT_ENV_RESTART[slot] = 0;
    if (slot < 4) {
        ++kit_host_parent_age[slot];
        if (publish) kit_voice_started(slot);
    }
}
EXPORT void kit_host_bd_flags(int slot, int active, int released, int quick, int fast, int restart) {
    if ((u32)slot >= 8) return;
    u8 *s = kit_stock_voice(slot);
    s[0] = (u8)active; s[1] = (u8)released;
    KIT_ENV_QUICK[slot] = (u8)quick; KIT_ENV_FAST[slot] = (u8)fast; KIT_ENV_RESTART[slot] = (u8)restart;
}
EXPORT float kit_host_bd_sample(int slot) {
    if ((u32)slot >= 8) return 0;
    u8 *s = kit_stock_voice(slot);
    float y = kit_output_slot(s, slot);
    if (*(u32 *)(s + 0x18C) == 0 || KIT_ENV_RESTART[slot]) {
        *(u32 *)(s + 0x18C) = 0x3F800000u;
        KIT_ENV_RESTART[slot] = KIT_ENV_QUICK[slot] = KIT_ENV_FAST[slot] = 0;
    }
    return y;
}
#endif
