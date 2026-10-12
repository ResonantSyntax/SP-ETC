/* FM percussion in the DX/TX style: one modulator with self-feedback into a
 * sine carrier. Each voice has a carrier pitch envelope, a decaying index
 * over a floor, and an optional high-passed noise layer. Original sounds,
 * not copies of factory patches. Index and feedback are in cycles. */
typedef struct {
    float f0, fe, tp;        /* carrier Hz at the hit, settled Hz, pitch 1/e (s) */
    float ratio, i0, i1, ti; /* modulator ratio; index at the hit, floor, index 1/e (s) */
    float fb;                /* modulator self-feedback */
    float ta, atk;           /* level 1/e (s), linear rise (s) */
    float na, nhp, nt;       /* noise level, one-pole high-pass Hz, noise 1/e (s) */
    float out;               /* output scale */
} kit_fm_patch;
static const kit_fm_patch kit_fm_patches[FM_COW - FM_KICK + 1] = {
    /* Index and feedback are in cycles: 0.16 cycles is 1 radian, a modest
     * DX output level. */
    /* KICK: 220 Hz dropping to 48 Hz in 9 ms; a short 1:1 click over a clean, long body */
    {220, 48, .009f,  1.0f, 0.30f, 0.00f, .006f, 0,    .24f, .0003f, .15f, 2000, .002f, 1.0f},
    /* SNARE: 1.57 ratio with feedback for the rattle, plus bright noise */
    {200, 175, .020f, 1.57f, 0.45f, 0.08f, .030f, .30f, .090f, .0002f, .55f, 1800, .075f, .62f},
    /* TOM: soft 1:1 body gliding down a fifth */
    {170, 115, .060f, 1.0f, 0.18f, 0.02f, .040f, 0,    .19f, .0004f, 0, 0, 0,  .90f},
    /* HAT: sqrt(2) ratio, high index and feedback: dense metallic noise */
    {2650, 2650, 1.0f, 1.4142f, 0.90f, 0.55f, .060f, .80f, .045f, .0001f, .35f, 6500, .040f, .80f},
    /* BELL: 3.5 ratio, the index fading slowly to a pure partial */
    {620, 620, 1.0f, 3.5f, 0.35f, 0.03f, .50f, 0,    .90f, .0002f, 0, 0, 0,  .70f},
    /* PERC: woody 2.76 ratio rim/block */
    {880, 805, .005f, 2.76f, 0.30f, 0.00f, .014f, 0,    .034f, .0001f, 0, 0, 0,  .85f},
    /* LOG: hollow 1:1 log drum with a downward slide and a little growl */
    {232, 176, .045f, 1.0f, 0.22f, 0.04f, .060f, .08f, .13f,  .0008f, 0, 0, 0,  .90f},
    /* COW: 1.43 ratio clang held by the index floor */
    {565, 565, 1.0f, 1.4286f, 0.35f, 0.18f, .090f, 0,    .085f, .0002f, 0, 0, 0,  .75f},
};

static void kitfm_start(kit_voice *v, float r, float k) {
    const kit_fm_patch *P = &kit_fm_patches[v->drum - FM_KICK];
    v->f = P->f0 * r; v->fend = P->fe * r;
    v->pe = 1.0f; v->pdec = KIT_TAU(P->tp);
    v->mr = P->ratio;
    v->mi = P->i0 - P->i1; v->mdec = KIT_TAU(P->ti * k); v->svf_q = P->i1;
    v->adec = KIT_TAU(P->ta * k);
    v->namp = P->na; v->ndec = P->nt > 0 ? KIT_TAU(P->nt * k) : 0;
    v->hp_a = P->nhp > 0 ? kit_exp2(-9.06472f * P->nhp * (1.0f / KIT_FS)) : 0;   /* one-pole HP pole */
    v->qv = P->atk > 0 ? 1.0f / (P->atk * KIT_FS) : 0;
    v->xprev = v->hp1 = v->lp = 0;
    if (v->drum == FM_HAT) v->group = 1;
}

static float kitfm_render(kit_voice *v) {
    const kit_fm_patch *P = &kit_fm_patches[v->drum - FM_KICK];
    float f = v->fend + (v->f - v->fend) * v->pe, y, x;
    v->pe *= v->pdec;
    v->ph[0] += f * (1.0f / KIT_FS); v->ph[0] -= (float)(int)v->ph[0];
    v->ph[1] += f * v->mr * (1.0f / KIT_FS); v->ph[1] -= (float)(int)v->ph[1];
    float m = kit_sin2pi(v->ph[1] + P->fb * v->lp);          /* self-feedback modulator */
    v->lp = m;
    y = kit_sin2pi(v->ph[0] + (v->svf_q + v->mi) * m) * v->amp;
    v->mi *= v->mdec;
    if (v->namp > KIT_SILENT) {                               /* one-pole high-passed noise */
        x = kit_noise(v);
        v->hp1 = v->hp_a * (v->hp1 + x - v->xprev); v->xprev = x;
        y += v->hp1 * v->namp; v->namp *= v->ndec;
    }
    if (v->qv > 0 && (float)v->n * v->qv < 1.0f) y *= (float)v->n * v->qv;
    v->amp *= v->adec;
    v->n += 1;
    v->source_frame += 1;          /* host renders; kit_output sets it on ARM */
    if (v->n > 480 && v->amp < KIT_SILENT && v->namp < KIT_SILENT) v->live = 0;
    return y * P->out * v->gain;
}
