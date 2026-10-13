/* One continuously advancing live BD circuit, independent of rotating stock
 * slots; four independent export circuits. No event clears live capacitors.
 * Events published after finish_begin_block wait until the next block. Several
 * events at one block boundary coalesce to the newest published event (one
 * trigger, its controls); this is an explicit SP scheduling policy.
 * KIT changes detach the output but preserve the circuit. When the SG render
 * callback is suspended, circuit time pauses: no wall-clock catch-up/reset. */
#define T8P_USE_LIBM 0
#define T8P_API static __attribute__((noinline))
#include "../physical_v931/tr808_bd_physical.c"
#undef T8P_API

typedef struct {
    int owner;
    u32 ready, remaining, consumed, block_frames, mode, serial;
    u32 triggers, advanced, idle_advanced, deferred, overruns, blocks;
    u32 owner_epoch, owner_parent_age;
    u32 event_epoch[4], handled_epoch[4], prepared_epoch[4];
    u32 published_parent_age[4], prepared_parent_age[4], pending_latched[4];
    u32 quiet[5];
} kit_bd_manager_t;
EXPORT t8p_state kit_bd_circuit[5] __attribute__((section(".data"))) = {{0}};
EXPORT kit_bd_manager_t kit_bd_manager __attribute__((section(".data"))) = {.owner = -1};
EXPORT u32 kit_bd_state_stride __attribute__((section(".data"))) = sizeof(t8p_state);
static t8p_state kit_record_bd_initial,kit_export_bd_initial;
static u8 kit_record_bd_valid,kit_export_bd_ready;
static void kit_start(kit_voice *v, int i, int pad);

#ifdef KIT_HOST
static u32 kit_host_parent_age[4];
static u32 kit_host_stock_words[8][KIT_VOICE_SIZE / 4];
static int kit_bd_preview;
#define KIT_PARENT_AGE (kit_host_parent_age)
#else
#define KIT_PARENT_AGE ((volatile u32 *)KIT_ENV_AGE_ADDR)
#endif

static u8 *kit_stock_voice(int i) {
#ifdef KIT_HOST
    return (u8 *)kit_host_stock_words[i];
#else
    return (u8 *)(__UINTPTR_TYPE__)(i == 0 ? KIT_SINGLETON :
        i < 4 ? KIT_CLONE_BASE + (u32)(i - 1) * KIT_VOICE_SIZE :
        KIT_EXPORT_BASE + (u32)(i - 4) * KIT_VOICE_SIZE);
#endif
}

/* DECAY is the physical pot position, 0..100%. */
static void kit_bd_configure(int circuit, const kit_pad *p, int cold) {
    float decay=kit_clampf((float)p->decay,0,100)*0.01f;
    float tone = 1.0f-kit_clampf((float)p->tone,0,100)*0.01f;
    float pitch = kit_exp2(kit_clampf((float)p->tune, -24, 24) / 12.0f);
    if (cold || !(kit_bd_manager.ready & (1u << circuit))) {
        t8p_init(&kit_bd_circuit[circuit], decay, tone, pitch);
        kit_bd_manager.ready |= 1u << circuit;
    } else t8p_configure(&kit_bd_circuit[circuit], decay, tone, pitch);
    kit_bd_circuit[circuit].retrigger_input *= kit_clampf(p->sweep,0,100)*.02f;
    t8p_trigger(&kit_bd_circuit[circuit], 4.0f);
    kit_bd_manager.quiet[circuit] = 0;
}

/* Called after the exact direct/MIDI note-on stock call, with dispatch disabled,
 * and immediately after ARP start_voice publishes arp_age. Commit epoch last.
 * These stamps order events, unlike the unrelated env_age/arp_age counters. */
static void kit_publish_event(int i) {
    if ((u32)i >= 4) return;
    kit_bd_manager.published_parent_age[i] = KIT_PARENT_AGE[i];
    kit_bd_manager.event_epoch[i] = ++kit_bd_manager.serial;
}

EXPORT void kit_voice_started(int i) { kit_publish_event(i); }

static void kit_bd_begin(int frames) {
    kit_bd_manager_t *m = &kit_bd_manager;
    if (m->ready & 1u) while (m->remaining) {
        (void)t8p_next(&kit_bd_circuit[0]);
        --m->remaining; ++m->advanced; ++m->idle_advanced;
    }
    m->remaining = (m->ready & 1u) ? (u32)frames : 0;
    m->block_frames = (u32)frames; m->consumed = 0; ++m->blocks;
}

EXPORT void kit_finish_begin_block(int frames) {
    if (frames <= 0) return;
    kit_bd_manager_t *m = &kit_bd_manager;
    kit_init_pads();
    if (m->mode != kit_mode) {
        if (m->owner >= 0) kit_slot[m->owner].live = 0;
        m->owner = -1; m->mode = kit_mode;
    }
    if (m->owner >= 0) {
        int i = m->owner;
        if (!kit_stock_voice(i)[0] || !kit_slot[i].live ||
            m->owner_epoch != m->event_epoch[i] || m->owner_parent_age != KIT_PARENT_AGE[i])
            m->owner = -1;
    }
    int newest = -1;
    u32 pending = 0;
    for (int i = 0; i < 4; ++i) {
        const u8 *s = kit_stock_voice(i);
        int fresh = *(const volatile u32 *)(s + 0x18C) == 0 || KIT_ENV_RESTART[i];
        if (!fresh) m->pending_latched[i] = 0;
        /* An allocator may yield before returning to its wrapper. Never infer
         * its completed note from the early env_age write; wait for publish. */
        if (KIT_PARENT_AGE[i] != m->published_parent_age[i]) continue;
        int unstamped = fresh && s[0] && !m->pending_latched[i] &&
                        m->event_epoch[i] == m->handled_epoch[i];
        if (unstamped) kit_voice_started(i); /* direct checker/legacy caller */
        if (m->event_epoch[i] == m->handled_epoch[i]) continue;
        m->handled_epoch[i] = m->event_epoch[i];
        m->prepared_epoch[i] = m->event_epoch[i];
        m->prepared_parent_age[i] = KIT_PARENT_AGE[i];
        m->pending_latched[i] = (u32)fresh;
        if (!kit_mode || !s[0] || (s[1] && (KIT_ENV_QUICK[i] || KIT_ENV_FAST[i]))) continue;
        int pad = kit_pad_of(s);
        const kit_pad *p = &kit_pads[(kit_mode > KIT_KITS ? KIT_KITS : kit_mode) - 1][pad & 15];
        if (p->sound % KIT_SOUNDS != T8_BD) continue;
        pending |= 1u << i;
        if (newest < 0 || (int)(m->event_epoch[i] - m->event_epoch[newest]) > 0) newest = i;
    }
    if (newest < 0) return;
    /* Retire older output owners before voice-major rendering starts. Stock
     * marks/quick/fast/restart remain entirely owned by the parent envelope. */
    for (int i = 0; i < 4; ++i) {
        if (pending & (1u << i)) kit_start(&kit_slot[i], i, kit_pad_of(kit_stock_voice(i)));
        if (kit_slot[i].drum == T8_BD) kit_slot[i].live = (u8)(i == newest);
    }
    int pad = kit_slot[newest].pad;
    const kit_pad *p = &kit_pads[(kit_mode > KIT_KITS ? KIT_KITS : kit_mode) - 1][pad & 15];
    kit_bd_configure(0, p, 0);
    if(pad==(kit_record_pad&15)){kit_record_bd_initial=kit_bd_circuit[0];kit_record_bd_valid=1;}
    m->owner = newest; m->owner_epoch = m->event_epoch[newest];
    m->owner_parent_age = KIT_PARENT_AGE[newest];
    m->remaining = (u32)frames; ++m->triggers;
    kit_last_hit = (u8)(pad & 15);
    if (kit_edit_pad != (u8)pad) { kit_edit_pad = (u8)pad; kit_edit_changed = 1; }
}

static void kit_bd_start(kit_voice *v, int slot, const kit_pad *p) {
    (void)v;
    if (slot >= 4) {
        kit_bd_configure(slot - 3, p, 1);
        if(kit_export_active&&kit_export_bd_ready&&slot-4==kit_export_bd_slot)kit_bd_circuit[slot-3]=kit_export_bd_initial;
    }
#ifdef KIT_HOST
    else if (kit_bd_preview) kit_bd_configure(1, p, 1);
#endif
    /* Live preparation/configure/trigger occurs only in the post-ARP hook. */
}

static float kit_bd_render(kit_voice *v, int slot) {
    kit_bd_manager_t *m = &kit_bd_manager;
    int circuit = slot >= 4 ? slot - 3 : 0;
#ifdef KIT_HOST
    if (kit_bd_preview) circuit = 1;
#endif
    if (circuit == 0) {
        if (m->owner != slot || m->owner_epoch != m->event_epoch[slot] ||
            m->owner_parent_age != KIT_PARENT_AGE[slot]) { ++m->deferred; return 0; }
        if (!m->remaining) { ++m->overruns; return 0; }
        --m->remaining; ++m->consumed; ++m->advanced;
    }
    float y = t8p_next(&kit_bd_circuit[circuit]) * 0.1f;
    ++v->n; ++v->source_frame;
    /* Output retirement never clears physical state: the live circuit keeps
     * advancing silently. Require a sustained quiet interval, not one zero. */
    m->quiet[circuit] = kit_absf(y) < 1e-5f ? m->quiet[circuit] + 1 : 0;
    if (v->n > 4800 && m->quiet[circuit] >= 2048) v->live = 0;
    return y * v->gain;
}
