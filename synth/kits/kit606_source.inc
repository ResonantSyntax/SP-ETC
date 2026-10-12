/* TR606 IC15 source network, ideal op-amps and printed nominal passives.
 * Shared loaded input bus (two states), two feedback bridges (two each).
 * All sections use one Tustin K=192000 at 96 kHz. Oscillator-mean units
 * are normalized; gains are NOT calibrated physical line-output voltages.
 * 2x PolyBLEP source, two-sample mean decimation, fixed 48 kHz voice path.
 * Output VCA/coupling/loading/nonlinearity remain separate approximations.
 */
#define KIT_606_BLOCK 64u
#define KIT_606_HISTORY 512u
typedef struct { float w1, w2, h1, h2, l1, l2; u32 next_frame, ready; } kit_606_state;
typedef struct { float lo[64], hi[64]; u32 origin, tune_key, valid; } kit_606_cache;
EXPORT kit_606_state kit_606_states[2][49] __attribute__((section(".data"))) = {{{0}}};
EXPORT kit_606_cache kit_606_caches[2][4] __attribute__((section(".data"))) = {{{0}}};
EXPORT u32 kit_606_cache_next[2] __attribute__((section(".data"))) = {0};

#include "kit606_jump.inc"

/* Constant-input warmup spans use powers of the SAME six-state recurrence.
 * Only PolyBLEP plateaus can jump; every edge sample advances normally.
 * This changes summation order, with a separately measured error bound. */
static void kit606_constant_advance(kit_606_state *s, float x, u32 frames) {
    float z0=s->w1-kit606_dc_state[0]*x, z1=s->w2-kit606_dc_state[1]*x;
    float z2=s->h1-kit606_dc_state[2]*x, z3=s->h2-kit606_dc_state[3]*x;
    float z4=s->l1-kit606_dc_state[4]*x, z5=s->l2-kit606_dc_state[5]*x;
    for (u32 bit=0;frames;++bit,frames>>=1) if (frames&1u) {
        const float *p=kit606_jump_power[bit];
        float a=p[0]*z0+p[1]*z1, b=p[2]*z0+p[3]*z1;
        float c=p[4]*z0+p[5]*z1+p[6]*z2+p[7]*z3;
        float d=p[8]*z0+p[9]*z1+p[10]*z2+p[11]*z3;
        float e=p[12]*z0+p[13]*z1+p[14]*z4+p[15]*z5;
        float f=p[16]*z0+p[17]*z1+p[18]*z4+p[19]*z5;
        z0=a;z1=b;z2=c;z3=d;z4=e;z5=f;
    }
    s->w1=z0+kit606_dc_state[0]*x; s->w2=z1+kit606_dc_state[1]*x;
    s->h1=z2+kit606_dc_state[2]*x; s->h2=z3+kit606_dc_state[3]*x;
    s->l1=z4+kit606_dc_state[4]*x; s->l2=z5+kit606_dc_state[5]*x;
}

static float kit606_network_step(kit_606_state *s, float x, float *lo) {
    float w = x + 1.49943475721336f*s->w1 - 0.547672782163741f*s->w2;
    float ja = 0.109093431123278f*w - 0.203581872538503f*s->w1 + 0.0944884414152244f*s->w2;
    float jb = 0.08392611285836f*w - 0.135721248359002f*s->w1 + 0.0517951355006418f*s->w2;
    s->w2 = s->w1; s->w1 = w;
    float hi = -0.084869823333466f*ja + s->h1;
    s->h1 = -0.0992843177168724f*ja + 1.73097603561620f*hi + s->h2;
    s->h2 = -0.0144144943834064f*ja - 0.929544671049940f*hi;
    *lo = -0.0304974017998818f*jb + s->l1;
    s->l1 = -0.0247717569788243f*jb + 1.91423343942141f*(*lo) + s->l2;
    s->l2 = 0.00572564482105753f*jb - 0.963776953379061f*(*lo);
    return hi;
}

static void kit606_carrier(kit_voice *v, float *lo, float *hi) {
    u32 bank = v->source_bank & 1u;
    int tune = v->source_tune;
    if (tune < -24) tune = -24;
    if (tune > 24) tune = 24;
    u32 key = (u32)(tune + 24), origin = v->source_frame & ~(KIT_606_BLOCK - 1u);
    kit_606_cache *cache = 0;
    for (int j = 0; j < 4; ++j) {
        kit_606_cache *c = &kit_606_caches[bank][j];
        if (c->valid && c->origin == origin && c->tune_key == key) { cache = c; break; }
    }
    if (!cache) {
        cache = &kit_606_caches[bank][kit_606_cache_next[bank]++ & 3u];
        cache->valid = 0;
        kit_606_state *s = &kit_606_states[bank][key];
        if (!s->ready || origin - s->next_frame > KIT_606_HISTORY) {
            s->w1=s->w2=s->h1=s->h2=s->l1=s->l2=0;
            s->next_frame = origin - KIT_606_HISTORY;
        }
        /* IC16 nominal RC values, typical HD14584B thresholds. R226 uses
         * 330k revision; 680k production-lot alternative is not selected.
         * These are a nominal circuit scenario, not measured chip thresholds. */
        static const float hz[6] = {246.41619945f,308.02024932f,367.00285025f,418.16082331f,440.40342030f,627.24123497f};
        float dt[6]; u32 step[6], phase[6];
        float ratio = kit_exp2((float)tune / 12);
        for (int j = 0; j < 6; ++j) {
            dt[j] = hz[j]*ratio/96000.0f;
            step[j] = (u32)(dt[j]*4294967296.0f);
            phase[j] = step[j]*(2u*s->next_frame);
        }
        u32 pending=2u*(origin-s->next_frame);
        while (pending) {
            float x=0; u32 skip=pending;
            for (int j=0;j<6;++j) {
                float p=(float)phase[j]*2.3283064365386963e-10f;
                if (p>=1.0f) p=0;
                x+=kit_pulse(p,dt[j],0.4798052512f);
                float end=0;
                if (p>dt[j]+1e-6f && p<0.4798052512f-dt[j]-1e-6f)
                    end=0.4798052512f-dt[j]-1e-6f;
                else if (p>0.4798052512f+dt[j]+1e-6f && p<1-dt[j]-1e-6f)
                    end=1-dt[j]-1e-6f;
                u32 n=1;
                if (end>0) {
                    u32 target=(u32)(end*4294967296.0f);
                    if (target>phase[j]) n=(target-phase[j])/step[j];
                    if (n<1) n=1;
                }
                if (n<skip) skip=n;
            }
            if (skip>1) kit606_constant_advance(s,x*(1.0f/6),skip);
            else { float unused; (void)kit606_network_step(s,x*(1.0f/6),&unused); }
            for (int j=0;j<6;++j) phase[j]+=step[j]*skip;
            pending-=skip;
        }
        s->next_frame=origin;
        u32 stop = origin + KIT_606_BLOCK;
        while (s->next_frame != stop) {
            u32 offset = s->next_frame++ - origin;
            float low = 0, high = 0;
            for (int sub = 0; sub < 2; ++sub) {
                float x = 0, a;
                for (int j = 0; j < 6; ++j) {
                    float p = (float)phase[j]*2.3283064365386963e-10f;
                    if (p >= 1.0f) p = 0;
                    x += kit_pulse(p, dt[j], 0.4798052512f);
                    phase[j] += step[j];
                }
                high += kit606_network_step(s, x*(1.0f/6), &a);
                low += a;
            }
            if (offset < KIT_606_BLOCK) { cache->lo[offset]=low*0.5f; cache->hi[offset]=high*0.5f; }
        }
        s->ready=1; cache->origin=origin; cache->tune_key=key; cache->valid=1;
    }
    u32 offset = v->source_frame - origin;
    *lo=cache->lo[offset]; *hi=cache->hi[offset];
}

#ifdef KIT_HOST
/* Validation only: isolated shared carrier, without trigger/envelope/output
 * gain. Requests deliberately preserve the same cache/state as real voices. */
EXPORT void kit606_host_carrier_reset(void) {
    u8 *p=(u8 *)kit_606_states;
    for (u32 i=0;i<sizeof(kit_606_states);++i) p[i]=0;
    p=(u8 *)kit_606_caches;
    for (u32 i=0;i<sizeof(kit_606_caches);++i) p[i]=0;
    kit_606_cache_next[0]=kit_606_cache_next[1]=0;
}
EXPORT void kit606_host_carrier_render(int tune, int bank, u32 origin, int count, float *lo, float *hi) {
    kit_voice v;
    v.source_tune=(signed char)tune; v.source_bank=(u8)bank; v.source_frame=origin;
    for (int i=0;i<count;++i) {
        kit606_carrier(&v,&lo[i],&hi[i]); ++v.source_frame;
    }
}
#endif
