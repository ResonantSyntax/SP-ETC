"""Pad envelopes, stage 2 (hardware test build): a pitch envelope and a resonant filter with a cutoff envelope
per pad, in the sample fill (PAD_ENV.md, "Stage 2").

A stage on a pad envelopes stage 1 build (build_pad_env.py; its manifest names the module). These changes in
5.52 space and the stage 1 module, each checked against what it replaces:
- code: the resampler veneers 0x800d2e2e (stereo, -> 0x140c4) and 0x800d2e38 (mono, -> 0x1409a), each
  movw ip / movt ip / bx ip, get a new target: pf_stereo_entry / pf_mono_entry, which go on to the stock
  resampler for a voice whose pad has neither stage on;
- data: stage 1's env_stages[0] (zero in the parent) -> pf_stage, so every envelope recompute reaches it;
- data: stage 1's env_more_pages[0..3] (zero in the parent) -> the four ENVELOPE pages PITCH, FILTER, F-ENV and
  CURVES (pf_pages), which stage 1 draws after its own.
Only the chunk worker 0x800e3f78 calls the veneers (four BLs to their entries; nothing else branches or points
into them). Stock code the module calls, reads or relies on is checked byte for byte (GUARDS). The module
(Zig 0.13.0, -Os, no fused multiply-add) links stage 1's env_fine_frames, env_curve, env_targets and env_touched by
address and goes in a new boot copy row in a 12 KB slot at 0x83FD9000, taken from the top of pad FX's planned room;
the builder checks that no row of the input and no other fork module's slot overlaps it and that nothing in the
input refers to it.

usage: python synth/build_pad_pitch_filter.py IN_APP1 OUT_DIR --zig ZIG [--base 0x83FD9000] [--build-dir DIR]
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
from pathlib import Path

from build_arp import file_offset, read_module, scatter
from build_pad_env import Runtime, branches_into, movw_movt_bx, listing, sha, fine_frames, curve_tables
from build_start_fix import refs_into

HERE = Path(__file__).resolve().parent
FLASH, COPY = 0x60080000, 0x600800E4
APP0_SHA = '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23'
REVISION = 'pad-env-test6'
SLOT = 0x3000                       # reserved: [base, base + SLOT)
GAP = (0x83FC9000, 0x83FF0000)      # above the fork's rows (end 0x83FC8450), below the end of cacheable SDRAM
# Every other fork module's reserved RAM (branch, start, end).
KNOWN_SLOTS = [
    ('pad FX (planned; pad_fx/REPORT.md)', 0x83FC9000, 0x83FD7000),
    ('chromatic mode module (planned, its own branch)', 0x83FD7000, 0x83FD9000),
    ('claude/note-repeat (note repeat)', 0x83FDC000, 0x83FDE000),
    ('claude/pad-env-amp (pad envelopes stage 1)', 0x83FDE000, 0x83FE2000),
    ('claude/fx-deep-edit (FX deep edit)', 0x83FE2000, 0x83FE6000),
    ('claude/fx-probe (FX probe)', 0x83FE6000, 0x83FE8000),
    ('claude/bounce-stage2, claude/bounce-stage3 (bounce)', 0x83FE8000, 0x83FED000),
    ('claude/cpu-meter (CPU meter test)', 0x83FED000, 0x83FEF000),
    ('claude/bounce-probe (bounce probe test)', 0x83FEE000, 0x83FEF000),
    ('main (RESAMPLE start fix)', 0x83FEF000, 0x83FF0000),
]
EXPORTS = ('pf_mono_entry', 'pf_stereo_entry', 'pf_active', 'pf_mono', 'pf_stereo', 'pf_stage', 'pf_voices', 'pf_gen',
           'pf_pages', 'pf_pow2', 'pf_g', 'pf_k', 'pf_k30', 'pf_comp15', 'pf_hz', 'pf_q10')
# stage 1's tables and its two helpers for later stages' pages, linked by address
STAGE1_LINKS = ('env_fine_frames', 'env_curve', 'env_targets', 'env_touched')
STAGE1_NEEDS = ('env_recompute', 'env_dispatch', 'env_stages', 'env_more_pages', 'env_ui_knob', 'env_ui_draw') + \
    STAGE1_LINKS
PAGES = 4                           # pf_pages[0..3] -> env_more_pages[0..3]
PAGE_SIZE = 28                      # struct env_page: name, label[3], value, turn, graph

# (address, stock bytes, what they are, the stock target, entry symbol)
VENEERS = [
    (0x800D2E2E, bytes.fromhex('44f2c50cc0f2010c6047'), 'stereo resampler veneer: movw ip, #0x40c5; movt ip, #1; bx ip',
     0x000140C5, 'pf_stereo_entry'),
    (0x800D2E38, bytes.fromhex('44f29b0cc0f2010c6047'), 'mono resampler veneer: movw ip, #0x409b; movt ip, #1; bx ip',
     0x0001409B, 'pf_mono_entry'),
]
# Their callers in the chunk worker (BL return addresses minus 4): stereo, then mono.
CALLERS = {0x800D2E2E: (0x800E443E, 0x800E4872), 0x800D2E38: (0x800E4470, 0x800E48B6)}
# The module's tail jumps to the stock resampler: symbol -> target.
STOCK_TAILS = {'pf_mono_entry': 0x0001409B, 'pf_stereo_entry': 0x000140C5}

# Stock 5.52 code the module calls, reads or relies on, unchanged in DOOM OS ED5E and the fork up to v9.46:
# (start, end, SHA-256 of the runtime bytes, what it establishes).
GUARDS = [
    (0x0001409A, 0x000140F0, 'e7ace48967f28b1018a38b1c21b82f1f0af8d289df1c9c6aca06ae58285241ce',
     'resampler wrappers (obj, L, [R,] n, pos): mono 0x1409a and stereo 0x140c4 call the kernel 0x12dc0 with the '
     'engine [obj + 0x14100] and return n minus what the kernel left'),
    (0x00012DC0, 0x0001409A, '6b8013cb1c77adef645da62a0269f92e6b7a316cd83996d96cd5b4232f70a729',
     'the resampler kernel: reads the step obj + 0x20 for every output frame; mode obj + 0x1c; in mode 2 the '
     'splice search every 25 or 35 frames of a call (frame index % period); the position tag at the last frame of '
     'a call; on a source failure the tag -1 and a short return'),
    (0x800E3F78, 0x800E4BC0, 'ec045fbaac7db67c1694c3e6d8e227986f9f61662aa35c4dcd8ec63815e58097',
     'the chunk worker: sets the step (voice + 0x160) in every branch before it calls the resampler veneers '
     '(0x800e443e / 0x800e4872 stereo, 0x800e4470 / 0x800e48b6 mono) with voice + 0x140, the scratch output '
     'buffers and 2048, then copies what they produced'),
    (0x800D2E2E, 0x800D2E42, 'dd623232ab22f0f94645dc50589b80417a018e043f9888748875fc4b37ce483e',
     'the two resampler veneers'),
    (0x80025858, 0x80025A5E, 'c48c0b59b5d3a14e4f00b8009699cac50559dfdc22ccb103952760bc9244c35c',
     'the engine init Init calls (0x800259e0: window 600, mode at obj + 0x1c; 0x80025858: the window\'s tables); '
     'the tests set voices up with them'),
    (0x800231F8, 0x80024138, '1135dece22519c09fb3f965c93d6339088346b9f7d0eebd455d98db26a5a1f8d',
     'CSmplCharge::Init: voice + 0x14274 = pad, the engine init (voice + 0x15c = stretch mode), then the '
     'recompute call at 0x80023b00 (return address 0x80023b05)'),
    (0x8001FA20, 0x800200D0, '347562c70223ae1893bff6a75da02c53e04c6959406132bd2e9809a64567da5f',
     'voice param setter: PITCH/FINE store voice + 0xd4/+0xd8 and set the step voice + 0x160 directly'),
    (0x800C0660, 0x800C06C8, '8fc9e8cc40a884facd9598e2733b99a3527deb4befa73c822c843cc4e266fd77',
     'line (context, {x, y}, {x, y}): the pages\' graphs'),
]

# ---------------------------------------------------------------- tables
FS = 48000
CUT_LO, CUT_RATIO = 20.0, 1000.0    # 20 Hz * 1000^(i / 127): 20 Hz .. 20 kHz
Q_LO, Q_OCT = 0.7071067811865476, 4.5   # Q = 0.707 * 2^(r * 4.5 / 127): 0.707 .. 16
FILTERS = ('OFF', 'LP', 'BP', 'HP')
CURVES = ('LIN', 'EXP', 'LOG', 'S')


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def pow2_table():
    """2^(i / 96) in Q16, i = 0..96 (1/8 semitone steps over one octave)."""
    return [int(round(2 ** (i / 96) * 65536)) for i in range(97)]


def cutoff_hz(i):
    return CUT_LO * CUT_RATIO ** (i / 127)


def g_table():
    g = [f32(math.tan(math.pi * cutoff_hz(i) / FS)) for i in range(128)]
    return g + [g[127]]


def q_of(r):
    return Q_LO * 2 ** (r * Q_OCT / 127)


def k_table():
    return [f32(1 / q_of(r)) for r in range(128)]


def k30_table():
    """k = 1 / Q in Q30 (the frame loop's)"""
    return [int(round(1 / q_of(r) * 2 ** 30)) for r in range(128)]


def comp15_table():
    """LP / HP input gain 1 / sqrt(Q / 0.7071) in Q15: 32768 at RESO 0"""
    return [int(round(2 ** (-r * Q_OCT / 2 / 127) * 32768)) for r in range(128)]


def hz_table():
    return [int(round(cutoff_hz(i))) for i in range(128)]


def q10_table():
    return [int(round(q_of(r) * 10)) for r in range(128)]


def tables():
    return pow2_table(), g_table(), k_table(), k30_table(), comp15_table(), hz_table(), q10_table()


def header(pow2, g, k, k30, comp, hz, q10):
    def rows(values, per, fmt):
        return [', '.join(fmt(v) for v in values[i:i + per]) + ',' for i in range(0, len(values), per)]

    def hexf(v):
        return float.hex(v) + 'f'
    lines = ['/* Generated by build_pad_pitch_filter.py. */',
             '/* 2^(i / 96) in Q16: one octave in 1/8 semitones */',
             'EXPORT const u32 pf_pow2[97] = {', *rows(pow2, 12, str), '};',
             '/* g = tan(pi * fc / 48000), fc = 20 Hz * 1000^(i / 127); a guard entry */',
             'EXPORT const float pf_g[129] = {', *rows(g, 6, hexf), '};',
             '/* k = 1 / Q, Q = 0.7071 * 2^(r * 4.5 / 127): float for the coefficients, Q30 for the frame loop */',
             'EXPORT const float pf_k[128] = {', *rows(k, 6, hexf), '};',
             'EXPORT const s32 pf_k30[128] = {', *rows(k30, 8, str), '};',
             '/* LP / HP input gain 1 / sqrt(Q / 0.7071), Q15 */',
             'EXPORT const u16 pf_comp15[128] = {', *rows(comp, 16, str), '};',
             '/* the screen: cutoff in Hz, Q x 10 */',
             'EXPORT const u16 pf_hz[128] = {', *rows(hz, 16, str), '};',
             'EXPORT const u8 pf_q10[128] = {', *rows(q10, 16, str), '};']
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------- build
def compile_module(folder: Path, zig: Path, link_base: int, limit: int, tables_h: str, links: dict):
    folder.mkdir(parents=True, exist_ok=True)
    if subprocess.check_output([str(zig), 'version'], text=True).strip() != '0.13.0':
        raise ValueError('needs Zig 0.13.0')
    symbols_ld = ''.join(f'{name} = {addr:#x};\n' for name, addr in sorted(links.items()))
    (folder / 'pad_pitch_filter.ld').write_text(f'''ENTRY(pf_mono_entry)
{symbols_ld}SECTIONS {{
 . = {link_base:#x};
 .text : {{ KEEP(*(.text.pf_mono_entry)) KEEP(*(.text.pf_stereo_entry)) KEEP(*(.text.pf_stage)) *(.text*) }}
 .rodata : ALIGN(16) {{ KEEP(*(.rodata.pf_*)) *(.rodata*) }}
 .data : ALIGN(16) {{ *(.data*) }}
 .bss : ALIGN(16) {{ KEEP(*(.bss.pf_*)) *(.bss*) *(COMMON) }}
 /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.note*) }}
}}
''', encoding='ascii', newline='\n')
    source = folder / 'pad_pitch_filter.c'           # compile LF-normalized source
    source.write_bytes((HERE / 'pad_pitch_filter.c').read_bytes().replace(b'\r\n', b'\n'))
    (folder / 'pad_pitch_filter_tables.h').write_text(tables_h, encoding='ascii', newline='\n')
    cache = folder / 'cache'
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache))
    # -g only keeps the symbol table: Zig's -Os (ReleaseSmall) strips it otherwise. Same code.
    subprocess.run([str(zig), 'cc', '-target', 'thumb-freestanding-eabihf', '-mcpu=cortex_m7+vfp4d16',
                    '-mfloat-abi=hard', '-Os', '-g', '-ffp-contract=off', '-ffunction-sections', '-fdata-sections',
                    '-nostdlib', '-fno-builtin', '-Wall', '-Werror', '-Wdouble-promotion', '-Wl,--no-undefined',
                    '-Wl,--build-id=none', '-Wl,-e,pf_mono_entry', '-Wl,-T,' + str(folder / 'pad_pitch_filter.ld'), '-I', str(folder), str(source),
                    '-o', str(folder / 'pad_pitch_filter.elf')], check=True, env=env)
    code, symbols = read_module((folder / 'pad_pitch_filter.elf').read_bytes(), link_base, limit)
    missing = [n for n in EXPORTS if n not in symbols]
    if missing:
        raise ValueError(f'module exports missing: {missing}')
    return code, {n: symbols[n] for n in EXPORTS}, sha(source.read_bytes()), sha(tables_h.encode('ascii'))


def check_slot(img, rows, base, parent_man):
    if base & 0xFFF or base < GAP[0] or base + SLOT > GAP[1]:
        raise ValueError(f'the slot must be 4 KB aligned in the free SDRAM gap {GAP[0]:#x}..{GAP[1]:#x}')
    for name, lo, hi in KNOWN_SLOTS:
        if max(lo, base) < min(hi, base + SLOT):
            raise ValueError(f'the slot {base:#x}..{base + SLOT:#x} overlaps {name} at {lo:#x}..{hi:#x}')
    lo, hi = parent_man['slot']
    if max(lo, base) < min(hi, base + SLOT):
        raise ValueError(f'the slot overlaps the parent\'s stage 1 slot {lo:#x}..{hi:#x}')
    for load, dst, n, fn in rows:
        if max(dst, base) < min(dst + n, base + SLOT):
            raise ValueError(f'row {dst:#x}+{n:#x} overlaps the slot {base:#x}..{base + SLOT:#x}')
    hits = refs_into(bytes(img), base, base + SLOT)
    if hits:
        raise ValueError(f'input refers to the slot: {hits[:4]}')


def check_parent(rt, img, man):
    for start, end, digest, what in GUARDS:
        got = sha(rt.read(start, end - start))
        if got != digest:
            raise ValueError(f'{start:#x}..{end:#x} differs from stock 5.52 ({what}): {got}')
    for at, want, what, _, _ in VENEERS:
        if rt.read(at, len(want)) != want:
            raise ValueError(f'{at:#x}: expected the stock {what}')
        inside = branches_into(rt, at + 1, at + len(want)) + \
            [h for h in refs_into(bytes(img), at + 1, at + len(want)) if h[2] & ~1 != at]
        if inside:
            raise ValueError(f'something reaches into the veneer at {at:#x}: {inside[:4]}')
        callers = sorted(a for k, a in branches_into(rt, at, at + 1) if k == 'branch')
        words = [a for k, a in branches_into(rt, at, at + 1) if k == 'word']
        if callers != sorted(CALLERS[at]) or words or [h for h in refs_into(bytes(img), at, at + 1)]:
            raise ValueError(f'the veneer at {at:#x} has other callers or references: {callers} {words}')
    e = man.get('entries', {})
    missing = [n for n in STAGE1_NEEDS if n not in e]
    if missing:
        raise ValueError(f'the parent manifest names no stage 1 module ({missing} missing)')
    blob = rt.read(man['blob_base'], man['blob_size'])
    if sha(blob) != man['blob_sha256'] or img[man['blob_file_offset']:man['blob_file_offset'] + man['blob_size']] != blob:
        raise ValueError('the parent\'s stage 1 module is not the one its manifest describes')
    if rt.read(e['env_stages'], 16) != bytes(16):
        raise ValueError('the parent\'s env_stages are not empty')
    if rt.read(e['env_more_pages'], 4 * PAGES) != bytes(4 * PAGES):
        raise ValueError('the parent\'s env_more_pages are not empty')
    if rt.read(0x800A2D98, 10) != movw_movt_bx(12, e['env_recompute']):
        raise ValueError('the recompute entry 0x800a2d98 does not jump to the parent\'s env_recompute')


def build(inp: Path, out: Path, zig: Path, base: int, build_dir: Path = None):
    img = bytearray(inp.read_bytes())
    app0 = inp.with_name('SP404MKII_APP0.bin')
    if sha(app0.read_bytes()) != APP0_SHA:
        raise ValueError('expected stock APP0 beside the input APP1')
    parent_manifest = inp.with_name('manifest.json')
    man = json.loads(parent_manifest.read_text(encoding='utf-8'))
    for name in ('SP404MKII_APP1.bin', 'SP404MKII_APP0.bin', 'manifest.json'):
        if (out / name).exists():
            raise ValueError(f'refusing to overwrite {out / name}')
    rows = scatter(img)
    rt = Runtime(img)
    check_parent(rt, img, man)
    check_slot(img, rows, base, man)
    if list(fine_frames()) != list(struct.unpack('<128I', rt.read(man['entries']['env_fine_frames'], 512))) or \
            [list(struct.unpack('<258H', rt.read(man['entries']['env_curve'] + 516 * k, 516))) for k in range(4)] \
            != curve_tables():
        raise ValueError('the parent\'s env_fine_frames / env_curve are not stage 1\'s tables')

    pow2, g, k, k30, comp, hz, q10 = tables()
    tables_h = header(pow2, g, k, k30, comp, hz, q10)
    folder = build_dir or out / 'build'
    links = {n: man['entries'][n] for n in STAGE1_LINKS}
    module, symbols, source_sha, tables_sha = compile_module(folder, zig, base, base + SLOT, tables_h, links)
    if len(module) > SLOT:
        raise ValueError(f'module ({len(module)} bytes) exceeds the slot')
    for name in ('pf_mono_entry', 'pf_stereo_entry', 'pf_stage', 'pf_mono', 'pf_stereo', 'pf_active'):
        if not symbols[name] & 1:
            raise ValueError(f'{name} is not a Thumb function symbol')
    for name, target in STOCK_TAILS.items():
        at = symbols[name] & ~1
        code = module[at - base:at - base + 28]
        got = listing(code, at)
        want = ['push.w {r0, r1, r2, r3, ip, lr}', 'cmp r0, #0', 'pop.w {r0, r1, r2, r3, ip, lr}']
        if [got[0], got[2], got[3]] != want or not got[1].startswith('bl ') or not got[4].startswith('bne.w ') or \
                code[18:28] != movw_movt_bx(12, target):
            raise ValueError(f'{name} is not the check, then the stock resampler {target:#x}: {got}')

    patches = []
    for at, original, what, target, entry in VENEERS:
        off = file_offset(img, at, len(original))
        code = movw_movt_bx(12, symbols[entry])
        img[off:off + len(original)] = code
        patches.append(dict(address=at, size=len(original), original_hex=original.hex(), replacement_hex=code.hex(),
                            what=f'{what} -> movw ip / movt ip / bx ip to {entry} (which goes on to {target:#x} '
                                 f'for a pad without pitch or filter)', listing=listing(code, at)))
    at = man['entries']['env_stages']
    off = file_offset(img, at, 4)
    new = struct.pack('<I', symbols['pf_stage'])
    img[off:off + 4] = new
    patches.append(dict(address=at, size=4, original_hex='00000000', replacement_hex=new.hex(),
                        what='stage 1\'s env_stages[0] (in its copy row) -> pf_stage'))
    for k in range(PAGES):
        at = man['entries']['env_more_pages'] + 4 * k
        off = file_offset(img, at, 4)
        new = struct.pack('<I', symbols['pf_pages'] + PAGE_SIZE * k)
        img[off:off + 4] = new
        patches.append(dict(address=at, size=4, original_hex='00000000', replacement_hex=new.hex(),
                            what=f'stage 1\'s env_more_pages[{k}] (in its copy row) -> pf_pages[{k}]'))
    file_at = (len(img) + 15) & ~15
    img += bytes(file_at - len(img)) + module
    table = (len(img) + 15) & ~15
    img += bytes(table - len(img))
    for row in rows + [[FLASH + file_at, base, len(module), COPY]]:
        img += struct.pack('<4I', *row)
    struct.pack_into('<2I', img, 0x80, table - 0x80, len(img) - 0x80)
    after = Runtime(img)
    if after.read(base, len(module)) != module:
        raise ValueError('the new image does not reproduce the module')
    for p in patches:
        if after.read(p['address'], p['size']).hex() != p['replacement_hex']:
            raise ValueError(f'the new image does not reproduce the patch at {p["address"]:#x}')

    out.mkdir(parents=True, exist_ok=True)
    (out / 'SP404MKII_APP1.bin').write_bytes(img)
    shutil.copy2(app0, out / 'SP404MKII_APP0.bin')
    manifest = dict(
        revision=REVISION, status='hardware-unverified', published=False,
        description='pad envelopes stage 2: per pad, opt-in on the ENVELOPE page (SHIFT + PITCH/SPEED, tap SHIFT): '
                    'a pitch envelope (depth +-24 semitones, attack, decay or hold, curve) and a resonant LP/BP/HP '
                    'filter with a cutoff envelope, in the sample fill; saved in PADCONF bytes 0x71-0x7F; untouched '
                    'pads run the stock resampler',
        parent_app1=str(inp), parent_sha256=sha(inp.read_bytes()), parent_revision=man.get('revision'),
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        slot=[base, base + SLOT], known_slots=[dict(what=n, start=lo, end=hi) for n, lo, hi in KNOWN_SLOTS],
        blob_base=base, blob_file_offset=file_at, blob_size=len(module), blob_sha256=sha(module),
        source='synth/pad_pitch_filter.c', source_sha256=source_sha, tables_header_sha256=tables_sha,
        compiler='zig 0.13.0 cc -Os -ffp-contract=off', entries=symbols, stage1_links=links,
        stage1=dict(revision=man.get('revision'), blob_base=man['blob_base'], blob_sha256=man['blob_sha256'],
                    entries=man['entries']),
        patches=patches, guards=[dict(start=s, end=e, sha256=d, establishes=w) for s, e, d, w in GUARDS],
        settings=dict(where='PADCONF extended block of pad p: CSmplPrm 0x82e2cd08 + 0xF800 + p * 0x80, bytes 0x71-0x7F',
                      bytes={'0x71': 'pitch depth, semitones, signed -24..24 (0 = off)',
                             '0x72': 'pitch attack, fine index', '0x73': 'pitch decay, fine index (0 = hold)',
                             '0x74': 'filter type: 0 off, 1 LP, 2 BP, 3 HP', '0x75': 'cutoff 0-127',
                             '0x76': 'resonance 0-127', '0x77': 'cutoff envelope amount, signed -63..63 (x 2 steps)',
                             '0x78': 'filter attack, fine index', '0x79': 'filter decay, fine index (0 = hold)',
                             '0x7a': 'curves: b0-1 pitch, b2-3 filter (LIN, EXP, LOG, S)', '0x7b-0x7e': 'reserved',
                             '0x7f': 'layout version: 1 whenever any of 0x71-0x7e is not 0; anything else = stock'}),
        pitch=dict(step='base x 2^(depth x env / 12) per 64 output frames (175 in stretch mode 2), clamped to '
                        f'{4096}..{34716} (-24..+13 semitones) unless the base is already outside',
                   pow2_q16=pow2),
        filter=dict(kind='TPT state-variable (Zavalishin/Simper): coefficients per 32 frames in float32, then Q31; '
                         'the frame loop in fixed point (the signal x 2^9, SMMULR / SMMLAR)',
                    cutoff=f'{CUT_LO} Hz * {CUT_RATIO}^(i / 127)', q=f'{Q_LO:.4f} * 2^(r * {Q_OCT} / 127)',
                    gain='LP and HP input x 1 / sqrt(Q / 0.7071) (Q15); BP = k * v1 (unity peak)',
                    clip='soft knee above 24576, saturating at 32767',
                    bypass='a block where an LP is at 127 or an HP at 0 without resonance passes as it is'),
        ui=dict(page='ENVELOPE (0x10), SHIFT + PITCH/SPEED, turn VALUE or tap SHIFT: pages 5-8 after stage 1\'s four',
                pages=['5 PITCH: DEPTH -24..+24 st (OFF), ATTACK, DECAY (or HOLD); graph: the pitch envelope',
                       '6 FILTER: TYPE OFF/LPF/BPF/HPF, CUTOFF 20 Hz - 20 kHz, RESO Q 0.7 - 16; graph: stage 1\'s',
                       '7 F-ENV: AMOUNT -63..+63 (+-9.9 octaves), ATTACK, DECAY (or HOLD); graph: the cutoff envelope',
                       '8 CURVES: PITCH and FILTER envelope curves LIN/EXP/LOG/S; graph: stage 1\'s'],
                apply='COPY held: the mute group; REMAIN held: the bank (stage 1\'s env_targets); Edited and the save '
                      'timer through env_touched'),
        tool='synth/build_pad_pitch_filter.py')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    sums = ''.join(f'{sha((out / n).read_bytes())}  {n}\n' for n in ('SP404MKII_APP0.bin', 'SP404MKII_APP1.bin',
                                                                       'manifest.json'))
    (out / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8', newline='\n')
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('app1', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--zig', type=Path, required=True)
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0x83FD9000)
    ap.add_argument('--build-dir', type=Path)
    a = ap.parse_args()
    m = build(a.app1.resolve(), a.out.resolve(), a.zig.resolve(), a.base,
              a.build_dir.resolve() if a.build_dir else None)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size', 'blob_base', 'blob_size')}, indent=1))


if __name__ == '__main__':
    main()
