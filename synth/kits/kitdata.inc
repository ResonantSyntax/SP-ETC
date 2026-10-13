/* Table-driven voices for the Lel' UDS, Korg Mini Pops 7, TR-707 and TR-727
 * kits. Each recipe was fitted to recordings (The_Machine Lel' UDS and Mini
 * Pops folders) or to TR-707/TR-727 plug-in captures: pitch tracks, mode
 * fits, 1/3-octave balance and envelopes. Every sample is synthesized here
 * (sines, filtered noise, envelopes); no sample data is used.
 *
 * A recipe is a tone (bent from f0 towards fe with 1/e time tb, shaped with
 * 2nd/3rd harmonics), two partials at fixed ratios to the bent tone, a noise
 * path with up to two filter stages, a fast noise spike, and a gate: after
 * `hold` seconds everything falls with 1/e time `rel` (the end of a ROM
 * sample, or a trigger-length envelope). Modes add claps, click trains,
 * whistle trills and a bell-tree sweep. */
enum { DV_PLAIN, DV_CLAP, DV_TRAIN, DV_TRILL, DV_CHIME };
typedef struct {
    float f0, fe, tb, h2, h3, a0, t0;   /* tone Hz, floor Hz, bend s, harmonics, level, decay s */
    float r1, a1, t1, r2, a2, t2;       /* partials: ratio to the tone, level, decay s */
    float n1, q1, n2, q2;               /* noise stage 1: q>0 band-pass, q<0 high-pass; stage 2: q<0 low-pass */
    float na, nt, sk, st;               /* noise level and decay; spike level and decay */
    float atk, hold, rel;               /* rise s; gate hold s (0 = none) and release s */
    float m1, m2, m3;                   /* mode parameters */
    u8 mode, role, group, pad_;
} kit_dv;

#define R(...) {__VA_ARGS__}
static const kit_dv kit_dvs[T27_CHM - U_BD + 1] = {
    /* ---- Lel' UDS (Soviet analog drum synthesizer): bending tones, long noise ---- */
    /* U_BD   Kick 2: 164 Hz bending (1/e 290 ms), 2nd/3rd harmonics -11/-16 dB */
    {.f0=160,.fe=18,.tb=.29f,.h2=.35f,.h3=.25f,.a0=1,.t0=.17f,.n1=3000,.q1=.6f,.na=.05f,.nt=.01f,.atk=.0006f,.role=1},
    /* U_BD2  Kick 1: 228 Hz bending (217 ms) with a 1.66x partial and noise */
    {.f0=228,.fe=20,.tb=.22f,.h2=.35f,.h3=.20f,.a0=1,.t0=.11f,.r1=1.66f,.a1=.6f,.t1=.03f,
     .n1=2600,.q1=.7f,.na=1.2f,.nt=.05f,.atk=.0008f,.role=1},
    /* U_SD   Snare 1: 146 Hz bending (160 ms) under 2-6 kHz noise */
    {.f0=146,.fe=15,.tb=.16f,.h2=.28f,.h3=.16f,.a0=1,.t0=.22f,.n1=3500,.q1=.8f,.n2=9000,.q2=-.7f,
     .na=2.7f,.nt=.20f,.atk=.0008f,.role=2},
    /* U_SD2  Snare 3: 390 Hz bending fast (75 ms), louder 1-3.4 kHz noise */
    {.f0=390,.fe=25,.tb=.075f,.h2=.20f,.h3=.10f,.a0=.9f,.t0=.28f,.n1=2200,.q1=.8f,.na=2.5f,.nt=.28f,
     .atk=.0008f,.role=2},
    /* U_TOM  Snare 4: ringing 445 Hz bending (190 ms), long */
    {.f0=445,.fe=30,.tb=.19f,.h2=.25f,.a0=1,.t0=.40f,.n1=3000,.q1=.5f,.na=.6f,.nt=.15f,.atk=.0008f,.role=1},
    /* U_CP   Clap: one long 2 kHz noise burst, held ~300 ms */
    {.n1=1800,.q1=.9f,.n2=6000,.q2=-.7f,.na=1,.nt=.35f,.atk=.002f,.hold=.30f,.rel=.07f,.role=3},
    /* U_CH   closed hat: flat 2.5-17 kHz, held 35 ms */
    {.n1=2000,.q1=-.7f,.n2=12000,.q2=-.7f,.na=1,.nt=.10f,.atk=.0008f,.hold=.035f,.rel=.006f,.role=4,.group=1},
    /* U_OH   open hat */
    {.n1=3000,.q1=-.7f,.n2=14000,.q2=-.7f,.na=1,.nt=.30f,.atk=.003f,.hold=.17f,.rel=.05f,.role=5,.group=1},

    /* ---- Korg Mini Pops 7 ---- */
    /* MP_BD  62 Hz sine, held 20 ms then 1/e ~23 ms */
    {.f0=62,.fe=62,.a0=1,.t0=.10f,.atk=.0015f,.hold=.02f,.rel=.030f,.role=1},
    /* MP_SD1 noise above 2.5 kHz, a 3 ms spike over a 65 ms body */
    {.n1=2500,.q1=-.7f,.n2=12000,.q2=-.7f,.na=.5f,.nt=.065f,.sk=1,.st=.003f,.role=2},
    /* MP_SD2 */
    {.n1=2500,.q1=-.7f,.n2=12000,.q2=-.7f,.na=.55f,.nt=.065f,.sk=.8f,.st=.015f,.role=2},
    /* MP_RS  1617 Hz click ringing ~1 ms */
    {.f0=1617,.fe=1617,.a0=1,.t0=.0008f,.r1=.2f,.a1=.1f,.t1=.004f,.r2=.5f,.a2=.1f,.t2=.004f,
     .n1=2000,.q1=.7f,.na=.3f,.nt=.0015f,.role=1},
    /* MP_CY1 noise band 4-8 kHz */
    {.n1=3000,.q1=-.7f,.n2=6000,.q2=1,.na=1,.nt=.055f,.role=5},
    /* MP_CY2 */
    {.n1=3000,.q1=-.7f,.n2=6000,.q2=1,.na=1,.nt=.14f,.role=5},
    /* MP_CL  404 Hz plus a 2174 Hz partial that dies first */
    {.f0=404,.fe=404,.a0=1,.t0=.015f,.r1=5.38f,.a1=1.4f,.t1=.010f,.role=1},
    /* MP_CB  845 Hz plus 4717 Hz (-18 dB) */
    {.f0=845,.fe=845,.a0=1,.t0=.033f,.r1=5.58f,.a1=.6f,.t1=.012f,.role=1},
    /* MP_BGH / BGM / BGL bongos: 592, 396, 188 Hz sines */
    {.f0=592,.fe=592,.a0=1,.t0=.0115f,.atk=.0003f,.role=1},
    {.f0=396,.fe=396,.a0=1,.t0=.017f,.atk=.0003f,.role=1},
    {.f0=188,.fe=188,.a0=1,.t0=.030f,.atk=.0005f,.role=1},
    /* MP_MA  maracas: 4-9 kHz, held 8 ms */
    {.n1=4000,.q1=-.7f,.n2=9000,.q2=.7f,.na=1,.nt=.03f,.atk=.001f,.hold=.012f,.rel=.009f,.role=6},
    /* MP_GU  guiro: scrapes every 15 ms through a 4 kHz band, swelling over 0.3 s */
    {.n1=4000,.q1=4,.na=1,.nt=2.0f,.atk=.30f,.hold=.90f,.rel=.02f,.m1=66.7f,.m2=.0015f,.m3=.3f,.mode=DV_TRAIN,.role=6},
    /* MP_QJ  quijada: rattles ~45 ms apart through 2.5 kHz */
    {.n1=2500,.q1=3,.na=1,.nt=.15f,.m1=22,.m2=.003f,.m3=.6f,.mode=DV_TRAIN,.role=6},
    /* MP_TB  tambourine: narrow 4.6 kHz band, held 25 ms */
    {.n1=4600,.q1=7.5f,.na=1,.nt=.10f,.atk=.002f,.hold=.025f,.rel=.012f,.role=6},

    /* ---- TR-707 (plug-in captures; ROM-sample lengths as gates) ---- */
    /* T7_BD1 click, then 212 Hz bending to 62 Hz (9 ms); flat for 60 ms */
    {.f0=260,.fe=62,.tb=.009f,.h3=.15f,.a0=1,.t0=.5f,.n1=1000,.q1=-.7f,.na=2.0f,.nt=.0025f,
     .atk=.0005f,.hold=.05f,.rel=.008f,.role=1},
    /* T7_BD2 softer attack, a little longer */
    {.f0=250,.fe=62,.tb=.010f,.h3=.15f,.a0=1,.t0=.5f,.n1=1000,.q1=-.7f,.na=1.4f,.nt=.0025f,
     .atk=.0025f,.hold=.058f,.rel=.009f,.role=1},
    /* T7_SD1 152->130 Hz body, 2.97x partial, 3-6 kHz noise */
    {.f0=152,.fe=130,.tb=.08f,.a0=1,.t0=.3f,.r1=2.97f,.a1=.16f,.t1=.02f,.n1=5000,.q1=.8f,.n2=9000,.q2=-.7f,
     .na=.9f,.nt=.3f,.atk=.001f,.hold=.045f,.rel=.025f,.role=2},
    /* T7_SD2 145 Hz body, louder noise */
    {.f0=145,.fe=145,.a0=1,.t0=.3f,.r1=3.07f,.a1=.2f,.t1=.02f,.n1=4000,.q1=.7f,.n2=10000,.q2=-.7f,
     .na=.9f,.nt=.3f,.atk=.001f,.hold=.04f,.rel=.025f,.role=2},
    /* T7_LT/MT/HT 132->98, 164->120, 208->155 Hz; fast upper partials; 650 ms samples */
    {.f0=132,.fe=98,.tb=.08f,.a0=1,.t0=.20f,.r1=1.86f,.a1=.45f,.t1=.02f,.r2=2.9f,.a2=.5f,.t2=.015f,
     .n1=1500,.q1=.5f,.na=.5f,.nt=.05f,.atk=.001f,.hold=.6f,.rel=.01f,.role=1},
    {.f0=164,.fe=120,.tb=.075f,.a0=1,.t0=.20f,.r1=1.76f,.a1=.4f,.t1=.02f,.r2=2.82f,.a2=.5f,.t2=.015f,
     .n1=1500,.q1=.5f,.na=.5f,.nt=.05f,.atk=.001f,.hold=.6f,.rel=.01f,.role=1},
    {.f0=208,.fe=155,.tb=.06f,.a0=1,.t0=.16f,.r1=1.78f,.a1=.35f,.t1=.02f,.r2=2.86f,.a2=.35f,.t2=.015f,
     .n1=1500,.q1=.5f,.na=.5f,.nt=.05f,.atk=.001f,.hold=.6f,.rel=.01f,.role=1},
    /* T7_RS  870 Hz with 1.79x and 0.29x partials, ~13 ms */
    {.f0=870,.fe=870,.a0=1,.t0=.014f,.r1=1.79f,.a1=.7f,.t1=.01f,.r2=.29f,.a2=.4f,.t2=.01f,
     .n1=3500,.q1=.6f,.na=1.2f,.nt=.015f,.atk=.0008f,.hold=.1f,.rel=.01f,.role=1},
    /* T7_CP  four bursts 11 ms apart, then a 25 ms tail; 1.2 kHz band */
    {.n1=1200,.q1=.8f,.n2=9000,.q2=-.7f,.na=.5f,.nt=.025f,.hold=.14f,.rel=.01f,
     .m1=4,.m2=.011f,.m3=.003f,.mode=DV_CLAP,.role=3},
    /* T7_CB  546 Hz with 1.16x and 1.92x partials, held 30 ms */
    {.f0=546,.fe=546,.a0=1,.t0=.2f,.r1=1.16f,.a1=1,.t1=.02f,.r2=1.92f,.a2=.3f,.t2=.03f,
     .n1=2500,.q1=.5f,.na=.3f,.nt=.04f,.atk=.0005f,.hold=.03f,.rel=.029f,.role=1},
    /* T7_TB  tambourine: 4.7 kHz band */
    {.n1=4400,.q1=-.7f,.n2=10000,.q2=-.7f,.na=1,.nt=.027f,.atk=.004f,.hold=.15f,.rel=.01f,.role=6},
    /* T7_CH / T7_OH: 4-14 kHz, 150 ms and 330 ms samples */
    {.n1=3500,.q1=-.7f,.n2=14000,.q2=-.7f,.na=1,.nt=.035f,.atk=.0015f,.hold=.13f,.rel=.008f,.role=4,.group=1},
    {.n1=3500,.q1=-.7f,.n2=14000,.q2=-.7f,.na=1,.nt=.22f,.atk=.0015f,.hold=.31f,.rel=.01f,.role=5,.group=1},
    /* T7_CR  crash: 10 ms swell, low clang partials, long 3-8 kHz wash */
    {.f0=492,.fe=492,.a0=.25f,.t0=.08f,.r1=1.215f,.a1=.25f,.t1=.08f,.r2=1.715f,.a2=.2f,.t2=.06f,
     .n1=4500,.q1=.6f,.n2=11000,.q2=-.7f,.na=1,.nt=.6f,.atk=.008f,.hold=1.25f,.rel=.03f,.role=5},
    /* T7_RD  ride: bright wash with a 3.49 kHz bell partial */
    {.f0=3490,.fe=3490,.a0=.3f,.t0=.4f,.n1=5000,.q1=-.7f,.n2=15000,.q2=-.7f,.na=1,.nt=.2f,
     .atk=.002f,.hold=.50f,.rel=.10f,.role=5},

    /* ---- TR-727 (plug-in captures) ---- */
    /* T27_HB high bongo: 732 Hz, 1088 Hz ringing longer, 369 Hz */
    {.f0=732,.fe=732,.a0=1,.t0=.006f,.r1=1.486f,.a1=.15f,.t1=.02f,.r2=.504f,.a2=.25f,.t2=.02f,
     .n1=2500,.q1=.5f,.na=1.0f,.nt=.010f,.atk=.0005f,.role=1},
    /* T27_LB low bongo: 264 Hz, 511 Hz partial */
    {.f0=264,.fe=264,.a0=1,.t0=.012f,.r1=1.935f,.a1=.5f,.t1=.04f,.r2=1.66f,.a2=.4f,.t2=.01f,
     .n1=2000,.q1=.5f,.na=.6f,.nt=.010f,.atk=.0005f,.role=1},
    /* T27_MHC mute high conga: a 4 ms slap cluster 540-850 Hz */
    {.f0=773,.fe=773,.a0=1,.t0=.005f,.r1=.697f,.a1=.6f,.t1=.005f,.r2=1.092f,.a2=.25f,.t2=.03f,
     .n1=1200,.q1=.6f,.na=1.0f,.nt=.008f,.atk=.0005f,.role=1},
    /* T27_OHC open high conga: 325 Hz, 45 ms */
    {.f0=325,.fe=325,.a0=1,.t0=.045f,.r1=2.33f,.a1=.2f,.t1=.02f,.r2=1.55f,.a2=.12f,.t2=.03f,
     .n1=1500,.q1=.5f,.na=.3f,.nt=.010f,.atk=.0005f,.hold=.15f,.rel=.01f,.role=1},
    /* T27_LC low conga: 183 Hz, 90 ms */
    {.f0=183,.fe=183,.a0=1,.t0=.09f,.r1=1.70f,.a1=.22f,.t1=.03f,.r2=2.5f,.a2=.09f,.t2=.02f,
     .n1=800,.q1=.7f,.na=.2f,.nt=.010f,.atk=.0008f,.hold=.37f,.rel=.01f,.role=1},
    /* T27_HTI high timbale: shell modes 188/360/902 Hz plus a bright strike */
    {.f0=360,.fe=360,.a0=1,.t0=.11f,.r1=2.505f,.a1=1.5f,.t1=.06f,.r2=.522f,.a2=.6f,.t2=.08f,
     .n1=1500,.q1=.8f,.na=1.2f,.nt=.04f,.atk=.0003f,.hold=.64f,.rel=.01f,.role=1},
    /* T27_LTI low timbale: 152/287/561 Hz */
    {.f0=287,.fe=287,.a0=1,.t0=.13f,.r1=1.955f,.a1=1,.t1=.13f,.r2=.53f,.a2=.6f,.t2=.1f,
     .n1=1000,.q1=.8f,.na=1.0f,.nt=.04f,.atk=.0003f,.hold=.64f,.rel=.01f,.role=1},
    /* T27_HAG / LAG agogo bells: 1420 Hz (+5275, 2625) and 1047 Hz (+4010, 2015) */
    {.f0=1420,.fe=1420,.a0=1,.t0=.03f,.r1=3.715f,.a1=.5f,.t1=.012f,.r2=1.85f,.a2=.3f,.t2=.04f,
     .n1=5000,.q1=.5f,.na=.8f,.nt=.01f,.atk=.0003f,.hold=.14f,.rel=.01f,.role=1},
    {.f0=1047,.fe=1047,.a0=1,.t0=.04f,.r1=3.83f,.a1=.7f,.t1=.04f,.r2=1.925f,.a2=.4f,.t2=.05f,
     .n1=6000,.q1=.6f,.na=.8f,.nt=.02f,.atk=.0003f,.hold=.16f,.rel=.01f,.role=1},
    /* T27_CAB cabasa: 30 ms swell of 4-10 kHz noise */
    {.n1=4000,.q1=-.7f,.n2=7500,.q2=.7f,.na=1,.nt=.2f,.atk=.03f,.hold=.055f,.rel=.009f,.role=6},
    /* T27_MAR maracas: a 5 ms burst over a quiet 27 ms tail */
    {.n1=6000,.q1=-.7f,.n2=14000,.q2=-.7f,.na=.12f,.nt=.027f,.sk=1,.st=.005f,.atk=.0005f,.hold=.09f,.rel=.01f,.role=6},
    /* T27_SWH / LWH whistles: 2750 Hz, trilled at 113 Hz (FM +-7%, AM) */
    {.f0=2750,.fe=2750,.a0=1,.t0=1.0f,.n1=3000,.q1=-.7f,.na=.03f,.nt=1.0f,.atk=.003f,.hold=.06f,.rel=.02f,.m1=113,.m2=.07f,.m3=.7f,.mode=DV_TRILL,.role=1},
    {.f0=2750,.fe=2750,.a0=1,.t0=1.0f,.n1=3000,.q1=-.7f,.na=.03f,.nt=1.0f,.atk=.003f,.hold=.26f,.rel=.01f,.m1=113,.m2=.07f,.m3=.7f,.mode=DV_TRILL,.role=1},
    /* T27_QUI quijada: a 50 Hz rattle of 1-6 kHz clicks fading over 1.3 s */
    {.n1=2500,.q1=.5f,.na=1,.nt=.6f,.hold=1.3f,.rel=.05f,.m1=50,.m2=.004f,.m3=.5f,.mode=DV_TRAIN,.role=6},
    /* T27_CHM star chime: ten bells struck high to low, 35 ms apart, over a shimmer */
    {.a0=1,.t0=.3f,.n1=10000,.q1=.8f,.na=.4f,.nt=.3f,.m1=.035f,.mode=DV_CHIME,.role=5},
};
#undef R
static const float kit_dv_bells[10] = {16805, 14029, 10972, 8196, 6164, 4737, 4053, 3366, 2241, 1800};

static void kitdata_start(kit_voice *v, float r, float k) {
    const kit_dv *D = &kit_dvs[v->drum - U_BD];
    int j;
    /* Every hit starts its noise filters at rest, as the other engines do.
     * bq_bp/bq_hp/bq_lp set coefficients only, so before v9.45 a hit began
     * with the filter memory of whatever this voice played last. */
    for (j = 0; j < 5; ++j) v->q[j].z1 = v->q[j].z2 = 0;
    v->f = D->f0 * r; v->fend = D->fe * r;
    v->pe = D->tb > 0 ? 1.0f : 0.0f; v->pdec = D->tb > 0 ? KIT_TAU(D->tb) : 0.0f;
    if (D->tb <= 0) v->fend = v->f;
    v->e[0] = D->a0; v->ed[0] = D->t0 > 0 ? KIT_TAU(D->t0 * k) : 0;
    v->e[1] = D->a1; v->ed[1] = D->t1 > 0 ? KIT_TAU(D->t1 * k) : 0;
    v->e[2] = D->a2; v->ed[2] = D->t2 > 0 ? KIT_TAU(D->t2 * k) : 0;
    v->namp = D->na; v->ndec = D->nt > 0 ? KIT_TAU(D->nt * k) : 0;
    v->hp1 = D->sk; v->xprev = D->st > 0 ? KIT_TAU(D->st) : 0;          /* spike level and decay */
    if (D->q1 > 0) bq_bp(&v->q[0], D->n1 * r, D->q1); else if (D->q1 < 0) bq_hp(&v->q[0], D->n1 * r, -D->q1);
    if (D->q2 > 0) bq_bp(&v->q[1], D->n2 * r, D->q2); else if (D->q2 < 0) bq_lp(&v->q[1], D->n2 * r, -D->q2);
    v->amp = 1.0f; v->qv = D->hold > 0 ? D->hold * k * KIT_FS : 0; v->adec = D->rel > 0 ? KIT_TAU(D->rel) : 0;
    v->mi = D->atk > 0 ? 1.0f / (D->atk * KIT_FS) : 0;
    v->lp = 0; v->bp = 0;                       /* mode clock and per-click level */
    v->hp_a = 0;                                /* click / burst envelope (svf_f is saved/restored by SWEEP) */
    v->svf_q = D->mode == DV_CLAP ? KIT_TAU(D->m3) : D->mode == DV_TRAIN ? KIT_TAU(D->m2) : 0;
    for (j = 0; j < 6; ++j) v->ph[j] = 0;
    if (D->mode == DV_TRAIN) { v->lp = 0.9999f; v->bp = 1.0f; }
    if (D->mode == DV_CHIME) { v->e[0] = v->e[1] = v->e[2] = 0; v->ed[1] = v->ed[2] = v->ed[0]; v->lp = 0; v->bp = 0; }
    v->group = D->group;
}

static float kitdata_render(kit_voice *v) {
    const kit_dv *D = &kit_dvs[v->drum - U_BD];
    u32 n = v->n;
    int j;
    float y = 0, f, s, x;
    f = v->fend + (v->f - v->fend) * v->pe; v->pe *= v->pdec;
    if (D->mode == DV_TRILL) {                                  /* pea-whistle trill: FM and AM */
        v->ph[3] += D->m1 * (1.0f / KIT_FS); v->ph[3] -= (float)(int)v->ph[3];
        s = kit_sin2pi(v->ph[3]);
        f *= 1.0f + D->m2 * s;
        y = 1.0f - D->m3 * (0.5f - 0.5f * s);
    } else y = 1.0f;
    if (D->mode == DV_CHIME) {
        /* Strike the next bell every m1 seconds on the oldest oscillator. */
        if (v->bp < 10.0f && (float)n >= v->lp) {
            j = (int)v->bp % 3;
            v->ph[3 + j] = kit_dv_bells[(int)v->bp] * v->ratio;
            v->e[j] = 1.0f - 0.075f * v->bp; v->ph[j] = 0;     /* lower bells struck softer */
            v->bp += 1.0f; v->lp += D->m1 * KIT_FS;
        }
        float b = 0;
        for (j = 0; j < 3; ++j) {
            v->ph[j] += v->ph[3 + j] * (1.0f / KIT_FS); v->ph[j] -= (float)(int)v->ph[j];
            b += kit_sin2pi(v->ph[j]) * v->e[j]; v->e[j] *= v->ed[j];
        }
        y = b * 0.45f;
    } else {
        float t = 0;
        if (v->e[0] > KIT_SILENT) {
            v->ph[0] += f * (1.0f / KIT_FS); v->ph[0] -= (float)(int)v->ph[0];
            s = kit_sin2pi(v->ph[0]);
            t = (s + D->h2 * (2 * s * s - 1) + D->h3 * (3 * s - 4 * s * s * s)) * v->e[0];
        }
        if (v->e[1] > KIT_SILENT) { v->ph[1] += f * D->r1 * (1.0f / KIT_FS); v->ph[1] -= (float)(int)v->ph[1]; t += kit_sin2pi(v->ph[1]) * v->e[1]; }
        if (v->e[2] > KIT_SILENT) { v->ph[2] += f * D->r2 * (1.0f / KIT_FS); v->ph[2] -= (float)(int)v->ph[2]; t += kit_sin2pi(v->ph[2]) * v->e[2]; }
        y *= t;
        v->e[0] *= v->ed[0]; v->e[1] *= v->ed[1]; v->e[2] *= v->ed[2];
    }
    if (v->namp > KIT_SILENT || v->hp1 > KIT_SILENT) {
        float g = v->namp;
        if (D->mode == DV_CLAP) {
            /* m1 bursts m2 apart, each falling with 1/e m3, then the tail. */
            u32 P = (u32)(D->m2 * KIT_FS);
            if (n < (u32)D->m1 * P) { if (n % P == 0) v->hp_a = 1.0f; g = v->hp_a; v->hp_a *= v->svf_q; v->namp = D->na; }
            else v->namp *= v->ndec;
        } else if (D->mode == DV_TRAIN) {
            /* Click train: each click restarts at a jittered level. */
            v->lp += D->m1 * (1.0f / KIT_FS);
            if (v->lp >= 1.0f) { v->lp -= 1.0f; v->bp = 1.0f - D->m3 * kit_absf(kit_noise(v)); v->hp_a = 1.0f; }
            g *= v->bp * v->hp_a; v->hp_a *= v->svf_q;
            v->namp *= v->ndec;
        } else v->namp *= v->ndec;
        x = kit_noise(v);
        if (D->q1 != 0) x = bq_run(&v->q[0], x);
        if (D->q2 != 0) x = bq_run(&v->q[1], x);
        y += x * (g + v->hp1); v->hp1 *= v->xprev;
    }
    if ((float)n >= v->qv && v->qv > 0) v->amp *= v->adec;
    y *= v->amp;
    if (v->mi > 0 && (float)n * v->mi < 1.0f) y *= (float)n * v->mi;
    v->n = n + 1;
    v->source_frame += 1;          /* host renders; kit_output sets it on ARM */
    if (n > 480 && (v->amp < KIT_SILENT || (v->e[0] < KIT_SILENT && v->e[1] < KIT_SILENT && v->e[2] < KIT_SILENT
                                           && v->namp < KIT_SILENT && v->hp1 < KIT_SILENT && (D->mode != DV_CHIME || v->bp >= 10.0f))))
        v->live = 0;
    return y * v->gain;
}
