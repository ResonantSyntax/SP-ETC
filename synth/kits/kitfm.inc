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
    /* KICK: 230 Hz sweeping to 52 Hz, a 1:1 click that dies in 8 ms */
    {230, 52, .011f,  1.0f, 1.10f, 0.00f, .008f, .18f,  .19f, .0003f,  0, 0, 0,  .95f},
    /* SNARE: 1.57 ratio with heavy feedback for the rattle, plus bright noise */
    {205, 182, .020f, 1.57f, 1.40f, 0.30f, .045f, .62f, .080f, .0002f, .55f, 1800, .075f, .62f},
    /* TOM: soft 1:1 body gliding down a fifth */
    {168, 112, .060f, 1.0f, 0.55f, 0.05f, .030f, .10f,  .19f, .0004f,  0, 0, 0,  .90f},
    /* HAT: sqrt(2) ratio, high index and feedback: dense metallic noise */
    {2650, 2650, 1.0f, 1.4142f, 2.20f, 1.30f, .060f, .55f, .045f, .0001f, .35f, 6500, .040f, .80f},
    /* BELL: 3.5 ratio, the index fading slowly to a pure partial */
    {620, 620, 1.0f, 3.5f, 1.10f, 0.10f, .55f, 0,    .90f, .0002f,  0, 0, 0,  .70f},
    /* PERC: woody 2.76 ratio rim/block */
    {880, 805, .005f, 2.76f, 0.85f, 0.00f, .014f, .05f, .034f, .0001f, 0, 0, 0,  .85f},
    /* LOG: hollow 1:1 log drum with a downward slide and a little growl */
    {232, 176, .045f, 1.0f, 0.70f, 0.14f, .060f, .16f, .13f,  .0008f, 0, 0, 0,  .90f},
    /* COW: 1.43 ratio clang held by the index floor */
    {565, 565, 1.0f, 1.4286f, 0.95f, 0.45f, .090f, .10f, .085f, .0002f, 0, 0, 0,  .75f},
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
