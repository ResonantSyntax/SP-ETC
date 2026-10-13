"""Build the synthesis-only v9.41 module on the exact v9.6 parent.

Use synth/build_kits.py for the public command-line interface. Local includes
are restricted to this directory and hashed. No donor plugins, samples, PCM
banks or external research tree are required. Existing patch sites retain
exact-byte guards; sparse scatter packing verifies module reconstruction.
"""
from __future__ import annotations
import hashlib, importlib, json, os, re, shutil, struct, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REVISION = "v9.43-test4"
PCM_BANK_ADDRESS = 0x60376000
PCM_FLASH_PLANNING_LIMIT = 0x60400000
FLASH_BASE = 0x60080000
ZERO_HANDLER = 0x60080100
SPARSE_MODULE_ZERO_THRESHOLD = 128
GATE_SITE = 0x80007700
V9_GATE = 0x83F80001
# VALUE turned outside edit mode: (site, size, exact v9.6 instructions, direction set before the jump)
TURN_SITES = [
    (0x8015CB08, 16, ["movw r0, #0x1144", "movs r1, #0x83", "movt r0, #0x82e0", "mov.w r2, #-1", "b #0x8015cb24"],
     "mov.w r2, #-1\n", "nop\n"),
    (0x8015CB18, 12, ["movw r0, #0x1144", "movs r1, #0x83", "movt r0, #0x82e0", "movs r2, #1"], "movs r2, #1\n", ""),
]
# Hot resample (kit_shortcut.inc) mirrors or calls this stock code; nothing here
# is patched. Exact v9.6 instructions (= stock 5.52): (address, size, listing).
HOT_RESAMPLE_GUARDS = [
    # RESAMPLE key handler: recorder state in r7, table on key - 0x11.
    (0x8012D5F0, 44, ["push.w {r4, r5, r6, r7, r8, sb, lr}", "sub sp, #4", "mov r6, r1", "subs r1, #0x11",
                      "cmp r1, #0x20", "mov r4, r0", "bhi.w #0x8012d6cc", "movw r8, #0xe71c", "movw r2, #0x1a6c",
                      "movt r8, #0x82e0", "add.w sb, r4, r2", "movs r5, #1", "ldrb.w r7, [r8, #0x39]",
                      "tbh [pc, r1, lsl #1]"]),
    # Its default (PATTERN EDIT): the generic key handler, which does nothing there.
    (0x8012D6CC, 16, ["movs r1, #1", "mov r0, r4", "mov r2, r6", "movs r5, #1", "bl #0x800c9788", "mov r0, r5",
                      "add sp, #4"]),
    # RECORD SETTING: with SHIFT and the recorder not idle, the SG page.
    (0x8012D6E0, 22, ["movs r0, #0x2a", "bl #0x800d9f20", "cmp r7, #0", "beq.w #0x8012d7fc", "cmp r0, #0",
                      "bne.w #0x8012d818", "movs r5, #0", "b #0x8012d8b6"]),
    # Idle: with SHIFT and a destination chosen (settings 0x1a), the SG page.
    (0x8012D7FC, 44, ["cmp r0, #0", "beq.w #0x8012d92c", "movw r0, #0x1144", "movs r1, #0x1a", "movt r0, #0x82e0",
                      "movs r2, #0", "bl #0x800d94d8", "adds r0, #1", "beq.w #0x8012d9f4", "movs r0, #0x1e",
                      "bl #0x800da598", "movs r5, #1", "mov r0, r5", "add sp, #4", "pop.w {r4, r5, r6, r7, r8, sb, pc}"]),
    # SG key handler: table on key - 0x10.
    (0x8015C550, 24, ["push {r4, r5, r6, r7, lr}", "sub sp, #0x14", "mov r2, r1", "subs r1, #0x10", "cmp r1, #0x30",
                      "mov r4, r0", "bhi #0x8015c5cc", "movw r3, #0x1a6c", "adds r6, r4, r3", "tbh [pc, r1, lsl #1]"]),
    # Settings 0x36 = 1: start the take in state 1, stop it in state 2 (no SHIFT test).
    (0x8015C738, 62, ["movw r0, #0x1144", "movs r1, #0x36", "movt r0, #0x82e0", "movs r2, #0", "bl #0x800d94d8",
                      "cmp r0, #1", "bne.w #0x8015c5d8", "movw r0, #0xe71c", "movt r0, #0x82e0",
                      "ldrb.w r0, [r0, #0x39]", "cmp r0, #2", "beq.w #0x8015c89c", "cmp r0, #1", "bne.w #0x8015c5d8",
                      "movs r0, #0x17", "movs r1, #0", "movs r2, #0", "bl #0x800e25c0", "movs r0, #1", "add sp, #0x14",
                      "pop {r4, r5, r6, r7, pc}"]),
    # SG pad: the first note of a hot resample starts the take (kit hits too).
    (0x8015C0F2, 46, ["movw r0, #0x1144", "movs r1, #0x36", "movt r0, #0x82e0", "movs r2, #0", "bl #0x800d94d8",
                      "cmp r0, #1", "bne #0x8015c120", "movw r0, #0xe71c", "movt r0, #0x82e0", "ldrb.w r0, [r0, #0x39]",
                      "cmp r0, #1", "bne #0x8015c120", "movs r0, #0x17", "movs r1, #0", "movs r2, #0",
                      "bl #0x800e25c0"]),
    # Page request (called by the RESAMPLE twin, as the stock jump does).
    (0x800DA598, 24, ["push {r4, lr}", "mov r4, r0", "cmp r0, #1", "bne #0x800da5b0", "bl #0x800d4a60", "cmp r0, #0",
                      "it ne", "popne {r4, pc}", "adr r0, #0x6c", "bl #0x800d31c6"]),
]
# Jump-table halfwords: RESAMPLE PATTERN EDIT -> default, RECORD SETTING -> 0x8012d6e0;
# SG PATTERN SELECT, PATTERN EDIT, RECORD SETTING, PITCH/SPEED -> 0x8015c738.
HOT_RESAMPLE_TABLE_GUARDS = [(0x8012D624, 0x58), (0x8012D626, 0x62), (0x8015C570, 0xE8), (0x8015C572, 0xE8),
                             (0x8015C574, 0xE8), (0x8015C578, 0xE8)]

def sha(b): return hashlib.sha256(b).hexdigest()

def aligned_zero_runs(data: bytes):
    """Return aligned zero-only spans large enough to save one scatter row."""
    runs, pos = [], 0
    while pos < len(data):
        if data[pos] != 0:
            pos += 1
            continue
        end = pos + 1
        while end < len(data) and data[end] == 0:
            end += 1
        start_aligned = (pos + 3) & ~3
        end_aligned = end & ~3
        if end_aligned - start_aligned >= SPARSE_MODULE_ZERO_THRESHOLD:
            runs.append((start_aligned, end_aligned - start_aligned))
        pos = end
    return runs

def sparsify_module(image: bytes, info: dict, builder):
    """Replace aligned zero spans in the dense module COPY row with ZERO rows.

    Runtime addresses, dense size/hash, and all nonmodule scatter rows stay
    fixed. Compact COPY bytes begin at the original module file offset.
    """
    base = int(info["arp_code_base"])
    if builder.FLASH != FLASH_BASE or builder.COPY != 0x600800E4:
        raise ValueError("sparse module handler addresses differ from validated APP1 handlers")
    file_offset = int(info["arp_code_file"])
    dense_size = int(info["arp_code_size"])
    dense = image[file_offset:file_offset + dense_size]
    if len(dense) != dense_size or sha(dense) != info["arp_module_sha256"]:
        raise ValueError("dense module bytes do not match builder manifest")
    rows = builder.scatter(image)
    original_module_rows = [r for r in rows
                            if r[1] == base and r[2] == dense_size and r[3] == builder.COPY]
    if len(original_module_rows) != 1:
        raise ValueError("expected exactly one dense module COPY row")
    if original_module_rows[0][0] != FLASH_BASE + file_offset:
        raise ValueError("dense module COPY source differs from its manifest offset")
    module_row_index = next(i for i, row in enumerate(rows)
                            if row is original_module_rows[0])
    for i, (src, dst, size, handler) in enumerate(rows):
        if i == module_row_index:
            continue
        if handler == builder.COPY and size:
            source_file = src - FLASH_BASE
            if max(source_file, file_offset) < min(source_file + size, PCM_BANK_ADDRESS - FLASH_BASE):
                raise ValueError("nonmodule COPY source overlaps sparse module payload area")

    zero_spans = aligned_zero_runs(dense)
    if not zero_spans:
        raise ValueError("no aligned zero spans meet the sparse threshold")
    payload = bytearray()
    copy_spans, pos = [], 0
    for target_offset, size in zero_spans:
        if pos < target_offset:
            n = target_offset - pos
            copy_spans.append({"target_offset": pos, "size": n,
                               "payload_offset": len(payload)})
            payload.extend(dense[pos:target_offset])
        pos = target_offset + size
    if pos < dense_size:
        copy_spans.append({"target_offset": pos, "size": dense_size - pos,
                           "payload_offset": len(payload)})
        payload.extend(dense[pos:])
    if not payload:
        raise ValueError("sparse module unexpectedly has no COPY bytes")

    table_start = (file_offset + len(payload) + 15) & ~15
    if table_start > len(image):
        raise ValueError("sparse table would move past original APP1 image")
    nonmodule_rows = [r for i, r in enumerate(rows) if i != module_row_index]
    module_zero_rows = [[0, base + start, size, ZERO_HANDLER]
                        for start, size in zero_spans]
    module_copy_rows = [[FLASH_BASE + file_offset + c["payload_offset"],
                         base + c["target_offset"], c["size"], builder.COPY]
                        for c in copy_spans]
    sparse_rows = nonmodule_rows + module_zero_rows + module_copy_rows
    table_end = table_start + len(sparse_rows) * 16
    bank_file_offset = PCM_BANK_ADDRESS - FLASH_BASE
    if table_end > bank_file_offset:
        raise ValueError("sparse scatter table reaches the fixed PCM bank")

    sparse = bytearray(image[:file_offset])
    sparse.extend(payload)
    sparse.extend(bytes(table_start - len(sparse)))
    for i, row in enumerate(sparse_rows):
        sparse.extend(struct.pack("<4I", *row))
    struct.pack_into("<2I", sparse, 0x80, table_start - 0x80, table_end - 0x80)
    out = bytes(sparse)
    final_rows = builder.scatter(out)
    final_nonmodule = [r for r in final_rows if not (base <= r[1] < base + dense_size)]
    if final_nonmodule != nonmodule_rows:
        raise AssertionError("sparse transformation changed original nonmodule scatter rows/order")
    info.update(
        arp_module_storage="aligned-zero COPY/ZERO sparse v1",
        arp_code_stored_bytes=len(payload),
        arp_code_stored_sha256=sha(payload),
        arp_module_bytes_omitted=dense_size - len(payload),
        arp_module_zero_threshold_bytes=SPARSE_MODULE_ZERO_THRESHOLD,
        arp_module_zero_spans=[{"target_offset": start, "size": size}
                                for start, size in zero_spans],
        arp_module_copy_spans=copy_spans,
        arp_scatter_rows_before=len(rows),
        arp_scatter_rows_after=len(sparse_rows),
        arp_nonmodule_scatter_rows_sha256=sha(b"".join(struct.pack("<4I", *r)
                                                            for r in nonmodule_rows)),
        arp_module_scatter_rows=len(module_zero_rows) + len(module_copy_rows),
        arp_sparse_scatter_table_file_start=table_start,
        arp_sparse_scatter_table_file_end=table_end,
        arp_sparse_scatter_table_growth_bytes=(len(sparse_rows) - len(rows)) * 16,
    )
    # Keep every original nonmodule row exactly, and prove the helper can
    # recover the original runtime image before touching the PCM-bank append.
    from sparse_module import reconstruct_module
    if reconstruct_module(out, info) != dense:
        raise AssertionError("production sparse module helper failed reconstruction")
    return out, info

def expand_kit_sources(path: Path):
    """Inline local includes for the existing single-file ARM builder.

    System includes remain for the compiler. Every expanded file is hashed;
    relative includes resolve from their owning source, including pcm_core.h.
    """
    hashes = {}
    root = HERE.resolve()
    def expand(current, stack):
        current = current.resolve()
        name = os.path.relpath(current, root).replace("\\", "/")
        if current in stack:
            raise ValueError("recursive kit include: " + name)
        body = current.read_text(encoding="utf-8")
        hashes[name] = sha(body.encode())
        def replace(match):
            child = (current.parent / match.group(1)).resolve()
            if not child.is_relative_to(root):
                raise ValueError("kit include escapes source folder")
            return expand(child, stack + [current])
        return re.sub(r'^\s*#include\s+"([^"\n]+)"[^\n]*$', replace, body, flags=re.M)
    return expand(path, []), hashes

KIT_GATE = r'''
/* Oscillator gate entry (from 0x80007700): Kit when KIT is not OFF, else v9's gate. */
__attribute__((naked, used, section(".text.kit_gate"))) void kit_gate(void) {
    __asm__ volatile(
        "movw r12, #0x2af3\n\tmovt r12, #0x8013\n\tcmp lr, r12\n\tbeq 1f\n\t"
        "movw r12, #:lower16:kit_mode\n\tmovt r12, #:upper16:kit_mode\n\t"
        "ldrb r12, [r12]\n\tcmp r12, #0\n\tbeq 1f\n\t"
        "push {r4, r5, r6, lr}\n\tvpush {d8, d9, d10, d11, d12}\n\tmov r4, r0\n\t"
        "bl kit_output\n\t"
        "movw r12, #0x7775\n\tmovt r12, #0x8000\n\tbx r12\n"
        "1:\n\tmovw r12, #0x0001\n\tmovt r12, #0x83f8\n\tbx r12\n");
}

/* VALUE turned outside edit mode, r2 = -1 / +1: kit_turn takes it when a pad
 * is held in KIT mode (back at 0x8015cb2e: handled), else the stock cursor
 * step at 0x8015cb24 with its arguments rebuilt. */
__attribute__((naked, used, section(".text.kit_turn_gate"))) void kit_turn_gate(void) {
    __asm__ volatile(
        "push {r2, r3}\n\tmov r0, r2\n\tbl kit_turn\n\tmov r3, r0\n\tpop {r0, r1}\n\tmov r2, r0\n\t"
        "cmp r3, #0\n\tbne 1f\n\t"
        "movw r0, #0x1144\n\tmovt r0, #0x82e0\n\tmovs r1, #0x83\n\t"
        "movw r12, #0xcb25\n\tmovt r12, #0x8015\n\tbx r12\n"
        "1:\n\tmovw r12, #0xcb2f\n\tmovt r12, #0x8015\n\tbx r12\n");
}
'''

def generate(arp_source: str, engine: str, symbols: dict) -> str:
    src = arp_source.replace("\r\n", "\n")
    anchor = "EXPORT void arp_item_name(int item, char *out) {"
    if src.count(anchor) != 1: raise ValueError("arp_item_name anchor not found once")
    defs = "".join(f"#define {k} {symbols[v] & ~1:#x}u\n" for k, v in
                   (("KIT_ENV_RESTART_ADDR", "env_restart"), ("KIT_ENV_QUICK_ADDR", "env_quick"),
                    ("KIT_ENV_FAST_ADDR", "env_fast"), ("KIT_ENV_SLOT_ADDR", "env_slot"),
                    ("KIT_ORIGINAL_EXPORT_MIX", "export_mix"), ("KIT_ENV_AGE_ADDR", "env_age")))
    # The kit engine is compiled without multiply-add contraction (as its host
    # reference is); the arp code after it returns to clang's default (on).
    block = ("/* ==== Kit mode (kit_engine.c), inserted by build_arp_kit.py ==== */\n#define KIT_IN_ARP\n"
             "#pragma clang fp contract(off)\n" + defs + engine + KIT_GATE +
             "#pragma clang fp contract(on)\n/* ==== end Kit ==== */\n\n")
    src = src.replace(anchor, block + anchor, 1)
    edits = [
        ("EXPORT void arp_tick(int frames) {\n",
         "static void arp_tick_body(int frames) {\n"),
        ("EXPORT void arp_note_event(u32 self, int note, int vel, int r3, int source) {\n",
         "static void arp_note_event_body(u32 self, int note, int vel, int r3, int source) {\n"),
        ("EXPORT void arp_midi_event(u32 self, int note, int vel, int r3) {\n",
         "static void arp_midi_event_body(u32 self, int note, int vel, int r3) {\n"),
        ("    arp_age[i] = ++arp_serial;\n",
         "    arp_age[i] = ++arp_serial;\n    kit_voice_started(i); /* shared direct/MIDI/ARP event order */\n"),
        ("EXPORT void arp_item_name(int item, char *out) {\n",
         "EXPORT void arp_item_name(int item, char *out) {\n    if (item >= 11) { kit_item_name(item, out); return; }\n"),
        ("EXPORT void arp_item_text(int item, char *out) {\n",
         "EXPORT void arp_item_text(int item, char *out) {\n    if (item >= 11) { kit_item_text(item, out); return; }\n"),
        ("EXPORT void arp_item_step(int item, int dir) {\n",
         "EXPORT void arp_item_step(int item, int dir) {\n    if (item >= 11) { kit_item_step(item, dir); arp_dirty = 1; return; }\n"),
        ("    refresh_tempo();\n    if (!arp_dirty) return 0;",
         "    refresh_tempo();\n    if (kit_edit_changed) { kit_ui_invalidate(); kit_edit_changed = 0; arp_dirty = 1; }\n    if (!arp_dirty) return 0;"),
        # A.OCT is a melodic control: hidden from the drum menu, and ignored
        # there so an octave set in melodic mode cannot double drum hits.
        ("    int lo = arp_oct < 0 ? arp_oct : 0, hi = arp_oct > 0 ? arp_oct : 0, count = 0;\n",
         "    int oct = kit_mode ? 0 : arp_oct;\n    int lo = oct < 0 ? oct : 0, hi = oct > 0 ? oct : 0, count = 0;\n"),
        ("        int lo = arp_oct < 0 ? arp_oct : 0, hi = arp_oct > 0 ? arp_oct : 0;\n",
         "        int oct = kit_mode ? 0 : arp_oct;\n        int lo = oct < 0 ? oct : 0, hi = oct > 0 ? oct : 0;\n"),
    ]
    for old, new in edits:
        if src.count(old) != 1: raise ValueError("generator anchor not found once: " + old.strip())
        src = src.replace(old, new, 1)
    src += '''
/* All original early returns remain inside the body. The physical BD owner
 * is chosen after ARP starts and before the first voice-major render call. */
EXPORT void arp_tick(int frames) {
    kit_begin_block(frames);
    arp_tick_body(frames);
    DISPATCH_OFF();
    kit_finish_begin_block(frames);
    DISPATCH_ON();
}
EXPORT void arp_note_event(u32 self, int note, int vel, int r3, int source) {
    kit_note_seen(source & 0xFF, vel);
    arp_note_event_body(self, note, vel, r3, source);
}
EXPORT void arp_midi_event(u32 self, int note, int vel, int r3) {
    arp_midi_event_body(self, note, vel, r3);
}
/* Only the two exact parent note-on call sites target these ABI-compatible
 * wrappers. A yielding allocator cannot accidentally publish another task's
 * unfinished note. The ordinary note-off call sites remain untouched. */
EXPORT void kit_stock_note_started(volatile u8 *state, int note, int vel, int r3, int source) {
    int slot = kit_slot_of((u32)(__UINTPTR_TYPE__)state);
    ((void (*)(volatile u8 *, int, int, int, int))0x80132429u)(state, note, vel, r3, source);
    DISPATCH_OFF();
    state[0x194] = 0xFF; /* same completed-pad metadata as the parent */
    kit_publish_event(slot);
    DISPATCH_ON();
}
EXPORT void kit_stock_midi_started(volatile u8 *state, int note, int vel, int r3) {
    int slot = kit_slot_of((u32)(__UINTPTR_TYPE__)state);
    ((void (*)(volatile u8 *, int, int, int))0x80132119u)(state, note, vel, r3);
    DISPATCH_OFF();
    *(volatile int *)(state + 0x1AC) = -1;
    *(volatile int *)(state + 0x19C) = note - 48;
    kit_publish_event(slot);
    DISPATCH_ON();
}
'''
    return src

def main():
    fork, v96, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    zig = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else HERE.parents[1] / ".wave_toolchain/ziglang/zig"
    sys.path.insert(0, str(fork))
    builder = importlib.import_module("build_arp")
    if any((out / n).exists() for n in ("SP404MKII_APP1.bin", "manifest.json")): raise ValueError("refusing to overwrite")
    parent = json.loads(v96.with_name("manifest.json").read_text(encoding="utf-8"))
    base = v96.read_bytes(); app0 = v96.with_name("SP404MKII_APP0.bin").read_bytes()
    if builder.sha(app0) != builder.APP0_SHA: raise ValueError("expected stock APP0 beside the input")
    arp_source = (fork / "arp_v9_9_3.c").read_text(encoding="utf-8")
    engine, source_hashes = expand_kit_sources(HERE / "kit_engine.c")
    required = {"kit_output.inc", "kit_parameters.inc", "kit_shortcut.inc", "kit_level_trims.inc", "kit_ui.inc", "kit909.inc", "kit606.inc", "kitprocedural.inc", "kitfm.inc", "kitdata.inc", "tr808/lifecycle_v930/kit_bd_lifecycle.inc"}
    if not required <= source_hashes.keys():
        raise ValueError("missing kit source includes: " + str(required-source_hashes.keys()))
    out.mkdir(parents=True, exist_ok=True)
    gen = out / "arp_kit.c"
    gen.write_text(generate(arp_source, engine, parent["symbols"]), encoding="utf-8", newline="\n")
    # The fork's builder, unchanged apart from its menu constants.
    builder.LAST_ITEM = 20
    builder.EXPORTS = builder.EXPORTS + ("kit_capture_gate", "kit_capture_selected", "kit_mix_capture", "kit_mix_gate", "kit_mix_finish", "kit_export_mix", "kit_ui_key_gate", "kit_ui_key_query", "kit_shortcut_gate", "kit_shortcut_event","kit_output", "kit_gate", "kit_begin_block", "kit_finish_begin_block", "kit_voice_started",
                                         "kit_stock_note_started", "kit_stock_midi_started", "kit_item_name", "kit_item_text", "kit_item_step",
                                         "kit_turn_gate", "kit_turn", "kit_note_seen", "kit_value_push_gate", "kit_value_edit_allowed")
    from apply_kit_ui import apply_kit_ui, EXPORTS as UI_EXPORTS
    builder.EXPORTS += UI_EXPORTS
    builder.STATE = builder.STATE + ("kit_capture_count", "kit_record_pad", "kit_record_velocity", "kit_menu_cursor", "kit_variants", "kit_master_limited", "kit_shortcut_trace", "kit_ui_shift", "kit_mode", "kit_edit_pad", "kit_pads", "kit_pads_ready", "kit_slot", "kit_pads_down",
                                     "kit_clock_next", "kit_live_cursor", "kit_voice_stride", "kit_cy_envelope_version",
                                     "kit_cy_states", "kit_cy_caches", "kit_cy_cache_next",
                                     "kit_606_states", "kit_606_caches", "kit_606_cache_next")
    builder.STATE = builder.STATE + ("kit_bd_circuit", "kit_bd_manager", "kit_bd_state_stride")
    sound_names = re.findall(r'"([^"]+)"', engine[engine.index("kit_sound_names[KIT_SOUNDS][6] = {"):].split("};")[0])
    kit_names = re.findall(r'"([^"]+)"', engine[engine.index("kit_kit_names[KIT_KITS + 1][6] = {"):].split("};")[0])
    builder.MENU = dict(builder.MENU, items=builder.MENU["items"] + ["KIT", "PAD", "SOUND", "TUNE", "DECAY", "TONE", "LEVEL", "SWEEP", "NOISE", "ATTACK"],
                        KIT=kit_names, SOUND=sound_names, PAD=[1, 16], LIVE_VOICES=4,
                        TUNE=[-12, 12], DECAY="0%..100% knob position in 1% steps; non-808 engines map to 0.354..2.828 baseline decay",
                        TR808_BD_DECAY="Physical decay pot position 0..100%; factory 50% (stock 808 and ACB default).",
                        TR808_BD_LIFECYCLE="One persistent live circuit, newest completed event per block owns output; four independent export circuits; selected-hit capacitor snapshot when controls match, otherwise cold; SG suspension pauses circuit time.",
                        TONE=[0, 100], LEVEL=[0, 127], SWEEP=[0,100], NOISE=[0,100], ATTACK=[0,100],
                        HOLD_PAD="hold a pad and turn VALUE (not in edit mode): that pad's SOUND")
    original_bridges=builder.bridges
    def capture_bridges(symbols):
        blob,at=original_bridges(symbols);blob=bytearray(blob)
        code=builder.checked_asm('push {r0,r1,r2,r3,r12,lr}\nmov r0,r1\nmov r1,r2\nmov r2,r3\n'+
            builder.call(symbols['kit_mix_capture'])+'ldr r0,[sp,#8]\n'+builder.call(symbols['arp_tick'])+
            'pop {r0,r1,r2,r3,r12,lr}\nmov r4,r1\nmov r5,r2\nmov r6,r3\nmovw r7,#0x9800\nbx lr\n',at['tick'])
        start=at['tick']-builder.MODULE_BASE
        if start+len(code)>len(blob):raise ValueError('mix capture bridge exceeds region')
        blob[start:start+len(code)]=code
        return bytes(blob),at
    builder.bridges=capture_bridges
    image, info = builder.build(base, parent, (out / "build").resolve(), zig, source_path=gen, revision=REVISION)
    # Kit gate at the oscillator gate entry (checked against v9.6).
    image = bytearray(image)
    # Fixed v9.6 parent env module, note-on calls only. Verify both target
    # halves and their BLX instruction before retargeting; note-off paths use
    # different loads. No stock function entry or allocator body is replaced.
    completed_note_hooks = []
    for lo, hi, call, old_lo, name in (
        (0x83F80CEA, 0x83F80CF8, 0x83F80D02, "42f22947", "kit_stock_note_started"),
        (0x83F81388, 0x83F81392, 0x83F813A4, "42f21917", "kit_stock_midi_started"),
    ):
        target = info["arp_symbols"][name] | 1
        for address, expected in ((lo, bytes.fromhex(old_lo)), (hi, bytes.fromhex("c8f21307")),
                                  (call, bytes.fromhex("b847"))):
            offset = builder.file_offset(bytes(image), address, len(expected))
            if image[offset:offset + len(expected)] != expected:
                raise ValueError(f"completed-note parent instruction differs at {address:#x}")
        for address, opcode, value in ((lo, "movw", target & 0xFFFF), (hi, "movt", target >> 16)):
            offset = builder.file_offset(bytes(image), address, 4)
            previous = bytes(image[offset:offset + 4])
            replacement = builder.checked_asm(f"{opcode} r7, #{value}\n", address)
            if len(replacement) != 4: raise ValueError("completed-note target patch width")
            image[offset:offset + 4] = replacement
            completed_note_hooks.append(dict(address=address, bytes=4, original_hex=previous.hex(),
                                             replacement_hex=replacement.hex(), target_symbol=name,
                                             target=target, call_site=call))
    kit_gate = info["arp_symbols"]["kit_gate"]
    off = builder.file_offset(bytes(image), GATE_SITE, 12)
    found = builder.listing(bytes(image[off:off + 12]), GATE_SITE)
    expected = ["movw ip, #1", "movt ip, #0x83f8", "bx ip", "nop"]
    if found != expected: raise ValueError(f"gate entry: expected {expected}, found {found}")
    new = builder.checked_asm(builder.jump(kit_gate) + "nop\n", GATE_SITE)
    if len(new) != 12: raise ValueError("gate patch size")
    image[off:off + 12] = new
    # VALUE turns outside edit mode to kit_turn_gate (checked against v9.6).
    turn_gate = info["arp_symbols"]["kit_turn_gate"]
    for site, size, expected, prefix, pad in TURN_SITES:
        off = builder.file_offset(bytes(image), site, size)
        found = builder.listing(bytes(image[off:off + size]), site)
        if found != expected: raise ValueError(f"turn site {site:#x}: expected {expected}, found {found}")
        new = builder.checked_asm(prefix + builder.jump(turn_gate) + pad, site)
        if len(new) != size: raise ValueError(f"turn patch size at {site:#x}: {len(new)}")
        image[off:off + size] = new
    # These exported scalar checks address the still-dense module in this
    # stage; after sparse packing its bytes are represented by scatter rows.
    shortcut_site=0x800a80a8
    off=builder.file_offset(bytes(image),shortcut_site,12)
    expected=builder.checked_asm("push {r4,r5,r6,lr}\nsub sp,#8\nmov r6,r1\nldrsh.w r1,[r1]\nmovs r5,#0\n",shortcut_site)
    if image[off:off+12]!=expected: raise ValueError("shortcut prologue changed: "+image[off:off+12].hex())
    replacement=builder.checked_asm(builder.jump(info['arp_symbols']['kit_shortcut_gate'])+"nop\n",shortcut_site)
    if len(replacement)!=12:raise ValueError("shortcut jump width")
    image[off:off+12]=replacement
    info['kit_shortcut_patch']={'address':shortcut_site,'original_hex':expected.hex(),'replacement_hex':replacement.hex()}
    info['kit_shortcut']='SHIFT + PATTERN EDIT: last kit; SHIFT + RECORD SETTING: melodic SG. Chord captured on press; either release order.'
    # The hot-resample rules run in the same gate; check the stock code they rely on.
    hot_guards=[]
    for site,size,expected_listing in HOT_RESAMPLE_GUARDS:
        off=builder.file_offset(bytes(image),site,size)
        found=builder.listing(bytes(image[off:off+size]),site)
        if found!=expected_listing:raise ValueError(f'hot resample guard {site:#x}: expected {expected_listing}, found {found}')
        hot_guards.append({'address':site,'bytes':size,'sha256':sha(bytes(image[off:off+size]))})
    for site,half in HOT_RESAMPLE_TABLE_GUARDS:
        off=builder.file_offset(bytes(image),site,2)
        if struct.unpack_from('<H',image,off)[0]!=half:raise ValueError(f'hot resample table guard {site:#x}')
        hot_guards.append({'address':site,'bytes':2,'halfword':half})
    info['kit_hot_resample']={'guards':hot_guards,'patches':'none beyond kit_shortcut_patch',
        'resample_page':'Take armed or recording (the stock SHIFT + RECORD SETTING condition): SHIFT + PATTERN EDIT selects the last kit and requests the SG page (0x800da598), handled on press; its release is swallowed.',
        'stock_entry':'SHIFT + RECORD SETTING from the RESAMPLE page keeps the current machine (kit or melodic); its release is swallowed.',
        'sg_page':'Settings 0x36 = 1 and recorder state 1 or 2: the native press of SHIFT + PATTERN EDIT or SHIFT + RECORD SETTING is swallowed (no start or stop); the release switches machines. Unshifted presses keep the stock start/stop.',
        'first_hit':'Unchanged stock: the first SG pad note in state 1 posts the start (0x8015c11c), in drum or melodic mode.'}
    # Override SHIFT only for the three stock SG knob-query callers.
    site=0x800d9f20;off=builder.file_offset(bytes(image),site,12)
    expected=bytes.fromhex('81b2542902d90020704700bf')
    if image[off:off+12]!=expected:raise ValueError('key getter changed')
    image[off:off+12]=builder.checked_asm(builder.jump(info['arp_symbols']['kit_ui_key_gate'])+'nop\n',site)
    site=0x1fdd4;off=builder.file_offset(bytes(image),site,10)
    expected=builder.checked_asm('pop.w {r4,r5,r6,r7,r8,pc}\n',site)
    if image[off:off+4]!=expected or image[off+4:off+10]!=bytes(6):raise ValueError('SG mix epilogue changed')
    image[off:off+10]=builder.checked_asm(builder.jump(info['arp_symbols']['kit_mix_gate']),site)
    site=0x8353ba06;off=builder.file_offset(bytes(image),site,10)
    expected=builder.checked_asm(builder.jump(parent['symbols']['export_mix']),site)
    if image[off:off+10]!=expected:raise ValueError('SG export bridge changed')
    image[off:off+10]=builder.checked_asm(builder.jump(info['arp_symbols']['kit_export_mix']),site)
    site=0x8353b600;off=builder.file_offset(bytes(image),site,12)
    expected=builder.checked_asm('push.w {r4,r5,r6,r7,r8,lr}\nmovw r4,#0x9800\nmovt r4,#0x8024\n',site)
    if image[off:off+12]!=expected:raise ValueError('capture prologue changed')
    image[off:off+12]=builder.checked_asm(builder.jump(info['arp_symbols']['kit_capture_gate'])+'nop\n',site)
    info['kit_capture_patch']={'address':site,'original_hex':expected.hex(),'last_pressed_pad':True}
    # Stock SG pad events end in one shared UI redraw request at 0x8015c01c
    # (*(u16*)0x802496f0 = -1). The poly v2 all-notes-off hook moved that
    # store into its own wrapper and NOPed the block, so the imprint
    # destination select and preview start stopped redrawing the pads and
    # the chosen REC pad never blinked. Put the stock instructions back.
    site=0x8015c01c;off=builder.file_offset(bytes(image),site,14)
    if image[off:off+14]!=b'\x00\xbf'*7:raise ValueError('SG redraw block changed: '+image[off:off+14].hex())
    restored=bytes.fromhex('49f2f0604ff0ff31c8f224000180')
    if builder.listing(restored,site)!=['movw r0, #0x96f0','mov.w r1, #-1','movt r0, #0x8024','strh r1, [r0]']:
        raise ValueError('redraw block encoding')
    image[off:off+14]=restored
    info['sg_redraw_restore']={'address':site,'bytes':14,'replacement_hex':restored.hex(),
        'branches_in':['0x8015c13c','0x8015c192','0x8015c1a2','0x8015c1b6','0x8015c222'],
        'effect':'REC destination pad blinks again; identical to stock 5.52 bytes'}
    # VALUE pressed outside edit mode sets the stock edit flag here. Only the
    # push handler (0x8015ca28) branches in; route it through the BPM gate.
    site=0x8015cb34;off=builder.file_offset(bytes(image),site,10)
    found=builder.listing(bytes(image[off:off+10]),site)
    if found!=['movs r1, #1','str r1, [r0, #0x14]','movs r0, #1','add sp, #0x14','pop {r4, r5, r6, r7, pc}']:
        raise ValueError(f'VALUE push site changed: {found}')
    original=bytes(image[off:off+10])
    new=builder.checked_asm(builder.jump(info['arp_symbols']['kit_value_push_gate']),site)
    if len(new)!=10:raise ValueError('VALUE push jump width')
    image[off:off+10]=new
    info['kit_value_push_patch']={'address':site,'original_hex':original.hex(),'replacement_hex':new.hex(),
        'bpm_item':10,'effect':'BPM is a readout: pressing VALUE on it does not enter edit mode'}
    info['kit_master_gain_db']=6.0206
    info['kit_master_soft_knee']={'start_s16':24576,'ceiling_s16':32000,'live_and_export':True}
    info['kit_parameter_page']='Tap and release SHIFT toggles page, also in melodic SG; opening chords do not toggle.'
    image, ui_patches = apply_kit_ui(image, info['arp_symbols'], builder)
    info['kit_ui_patches'] = ui_patches
    info['kit_selector_range'] = [1,13]
    info['kit_ui'] = 'CTRL1 Tune, CTRL2 Decay, CTRL3 Tone; tap SHIFT: Sweep/Noise/Attack; LEVEL readout; drum VALUE menu ARP/RATE/HOLD/BPM/KIT/PAD/SOUND/LEVEL (A.OCT melodic only, BPM a readout); one 16-pad page per kit; kit selector stays within machines 1-13; melodic entry uses SHIFT+RECORD SETTING.'
    info['kit_pad_assignments'] = 16
    image, info = sparsify_module(bytes(image), info, builder)
    pcm_info = None # Synthesis-only: no external audio bank is appended.
    info.update(sha256=sha(image), size=len(image), kit_gate_site=[GATE_SITE, 12], kit_gate=kit_gate,
                kit_turn_sites=[[s, n] for s, n, *_ in TURN_SITES], kit_turn_gate=turn_gate,
                kit_engine_sha256=sha(engine.encode()), kit_source_sha256=source_hashes, generated_source_sha256=sha(gen.read_bytes()),
                kit_completed_note_hooks=completed_note_hooks, synthesis_only=True,
                kit=f"Synthesis-only kit mode: {len(kit_names)-1} kits, {len(sound_names)} synthesized drums; no PCM playback or external audio bank; 808/909/606/SDS/CR78/CR8K/DR110/KPR77 models calibrated to recordings and ACB captures, Lel' UDS and Mini Pops 7 fitted to recordings, TR-707/727 synthesized from plug-in captures, DX-style FM; four voices, main-display Tune/Decay/Tone; edits RAM-only; no ACB-equivalence claim",
                tests="Reproduce using synth/test_kits.py. Archived v9.41 emulator checks are summarized in synth/KITS.md; hardware confirmation remains outstanding.")
    (out / "SP404MKII_APP1.bin").write_bytes(image); (out / "SP404MKII_APP0.bin").write_bytes(app0)
    (out / "manifest.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="ascii", newline="\n")
    print(f"{REVISION} APP1: {len(image)} bytes; SHA-256 {info['sha256']}; kit_gate {kit_gate:#x}")

if __name__ == "__main__":
    main()
