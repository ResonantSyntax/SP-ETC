"""Pad envelopes, stage 1 (hardware test build): FINE attack/release, curves, decay/sustain, LOOP-ONCE and
REV-TIME per pad, on the ENVELOPE page (PAD_ENV.md; analysis/pad_envelope/REPORT.md stages E1 and E2).

A stage on the published Sound Generator + Kits v9.46 APP1. Seven changes in 5.52 space, each checked byte
for byte against what it replaces:
- code: the envelope recompute's first twelve bytes (0x800a2d98) -> a jump to env_recompute, the shared
  dispatcher (the stock body first, then this stage, then env_stages[] for later ones);
- code: the note-off's sixteen bytes at 0x8002315a (ldr r1 R / movw / movt 144000 / mul r6) -> a jump to
  env_release, which sets r6 and goes on at 0x8002316a;
- code: the ITCM applicators' first ten bytes (0x16f50 forward, 0x17196 reverse) -> jumps to env_fwd /
  env_rev, which run the module's applicator for a shaped voice and otherwise the displaced instructions,
  then on in ITCM;
- data: the ENVELOPE page vtable 0x8021ec14, slots +0x04 (deleting destructor), +0xD0 (tick, stock empty)
  and +0xE4 (knob) -> env_ui_leave, env_ui_poll, env_ui_knob, which go on to the stock methods.
Nothing branches into the displaced bytes but their entries (every BL, B, B<cond>, CB(N)Z, B.W, literal and
MOVW/MOVT pair in the image is checked). Stock code the module calls, reads or relies on is checked byte
for byte (GUARDS). The module (Zig 0.13.0, -Os) goes in a new boot copy row in a 16 KB slot at 0x83FDE000,
below every other fork module (KNOWN_SLOTS: FX deep edit 0x83FE2000, FX probe 0x83FE6000, bounce stage 3
0x83FE8000, CPU meter 0x83FED000, bounce probe 0x83FEE000, the start fix 0x83FEF000); the builder checks
that no row of the input and no known slot overlaps it and that nothing in the input refers to it.

usage: python synth/build_pad_env.py IN_APP1 OUT_DIR --zig ZIG [--base 0x83FDE000] [--build-dir DIR]
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
from decimal import Decimal, getcontext, ROUND_HALF_EVEN
from fractions import Fraction
from pathlib import Path

import capstone

from build_arp import file_offset, read_module, scatter
from build_start_fix import refs_into

HERE = Path(__file__).resolve().parent
FLASH, COPY, DECOMPRESS = 0x60080000, 0x600800E4, 0x60080088
APP0_SHA = '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23'
REVISION = 'pad-env-test1'
SLOT = 0x4000                       # reserved: [base, base + SLOT)
GAP = (0x83FC9000, 0x83FF0000)      # above the fork's rows (end 0x83FC8450), below the end of cacheable SDRAM
# Every other fork module's reserved RAM (branch, start, end).
KNOWN_SLOTS = [
    ('claude/fx-deep-edit (FX deep edit)', 0x83FE2000, 0x83FE6000),
    ('claude/fx-probe (FX probe)', 0x83FE6000, 0x83FE8000),
    ('claude/bounce-stage2, claude/bounce-stage3 (bounce)', 0x83FE8000, 0x83FED000),
    ('claude/cpu-meter (CPU meter test)', 0x83FED000, 0x83FEF000),
    ('claude/bounce-probe (bounce probe test)', 0x83FEE000, 0x83FEF000),
    ('main (RESAMPLE start fix)', 0x83FEF000, 0x83FF0000),
]
EXPORTS = ('env_recompute', 'env_recompute_stock', 'env_dispatch', 'env_fwd', 'env_fwd_stock', 'env_fwd_apply',
           'env_rev', 'env_rev_stock', 'env_rev_apply', 'env_shaped', 'env_release', 'env_release_r6',
           'env_ui_knob', 'env_ui_poll', 'env_ui_leave', 'env_voices', 'env_stages', 'env_ui', 'env_text',
           'env_fine_frames', 'env_fine_stock', 'env_stock_fine', 'env_curve')

# (address, displaced bytes, what they are, where the stock code goes on, entry symbol)
SITES = [
    (0x800A2D98, bytes.fromhex('2de9f04f81b0044643f28029'),
     'recompute: push.w {r4-r11, lr}; sub sp, #4; mov r4, r0; movw sb, #0x3280', 0x800A2DA4, 'env_recompute'),
    (0x8002315A, bytes.fromhex('d4f8001143f28022c0f2020201fb02f6'),
     'note-off: ldr.w r1, [r4, #0x100]; movw r2, #0x3280; movt r2, #2; mul r6, r1, r2', 0x8002316A, 'env_release'),
    (0x00016F50, bytes.fromhex('2de9f04f89b0129f012f'),
     'forward applicator: push.w {r4-r11, lr}; sub sp, #0x24; ldr r7, [sp, #0x48]; cmp r7, #1', 0x00016F5A,
     'env_fwd'),
    (0x00017196, bytes.fromhex('2de9f04f89b0129f0890'),
     'reverse applicator: push.w {r4-r11, lr}; sub sp, #0x24; ldr r7, [sp, #0x48]; str r0, [sp, #0x20]',
     0x000171A0, 'env_rev'),
]
# The module's copies of the displaced instructions: symbol -> site address.
STOCK_COPIES = {'env_recompute_stock': 0x800A2D98, 'env_fwd_stock': 0x00016F50, 'env_rev_stock': 0x00017196}
VTABLE = 0x8021EC14                 # ENVELOPE page (0x10)
VTABLE_SLOTS = [(0x04, 0x800F6239, 'env_ui_leave', 'deleting destructor (the page closes)'),
                (0xD0, 0x800F5751, 'env_ui_poll', 'tick: stock bx lr; the base class calls it with 50 (ms)'),
                (0xE4, 0x800F5D11, 'env_ui_knob', 'knob: CTRL 1-3 -> Attack, Hold, Release')]
VTABLE_KEEP = [(0x08, 0x6031C8F9, 'DOOM OS ED5E\'s event filter'),
               (0x14C, 0x80133B31, 'current pad')]

# Stock 5.52 code the module calls, reads or relies on, unchanged in DOOM OS ED5E and the fork up to v9.46:
# (start, end, SHA-256 of the runtime bytes, what it establishes).
GUARDS = [
    (0x800A2D98, 0x800A2E84, 'a090f9b0995f59dfdfcb30b57e16bcc07118b9b0db8bdb02d17d1a4cb206c39e',
     'recompute (env, start, length, A, H, R, channels; H, R, channels on the stack): the block at env, S +8, '
     'attack end +0x10, HOLD point +0x18, release length +0x28, channels +0x40; its first twelve bytes are four '
     'whole instructions, the body goes on at 0x800a2da4'),
    (0x80023118, 0x800231F8, '986df71e7863e82504f70cdc7760fa85ca3a5a0f86b817eaf511f1c1d7561335',
     'note-off release start: r4 voice, r0 position, r5 and r8 live across 0x8002315a..0x8002316a; flags set again '
     'at 0x8002316a; r6 / 127 frames, < 64 frames -> return 0 (declick), else ceil(min(frames, left) / 64) blocks'),
    (0x00016F50, 0x000173A2, '19f66098c5a55c9bd0f2526f6dd238b9db852354c6659dc575d784c6be20e092',
     'applicators (env, L, R, pos, n, unused, slot state) forward / reverse, and their wrappers; before START '
     'both channels 0; state 7 bypasses; channels +0x40 == 1 leaves R alone'),
    (0x800231F8, 0x80024138, '1135dece22519c09fb3f965c93d6339088346b9f7d0eebd455d98db26a5a1f8d',
     'CSmplCharge::Init: voice + 0x14274 = pad (0x8002332e) before the recompute call at 0x80023b00 (env = voice + '
     '0x60, A/H/R from voice +0xf8/+0xfc/+0x100, channels +0x1c)'),
    (0x8001FA20, 0x800200D0, '347562c70223ae1893bff6a75da02c53e04c6959406132bd2e9809a64567da5f',
     'voice param setter: Attack/Hold/Release store voice +0xf8/+0xfc/+0x100 and recompute (call at 0x8001ff34)'),
    (0x80022A40, 0x80022DB8, 'c714bdf2ccc7aa3d4ca707f0ca02051d24a151c7a4717e5f74e258acb987c3ec',
     'START edit: recompute call at 0x80022daa, env = voice + 0x60'),
    (0x80022DB8, 0x80023118, 'da73ecccafaba4b72d5bdd58f22a251100b83510c487ff106f56e98f1614180c',
     'loop-point edit: recompute call at 0x8002310a, env = voice + 0x60'),
    (0x80024748, 0x80024A98, '6060c0f7482a84c0ae5fa91ed1238756b6eec8062890dc51f29adb118c0ac0c3',
     'END edit: recompute call at 0x80024a8a, env = voice + 0x60'),
    (0x800241C8, 0x800243E0, '24bbb46eb74d141a0f78a06f20db96df132a22dc0cdb3d7f370df8f4b7efdba2',
     'voice allocator: voice i at 0x805f8834 + i * 0x28820; +0x24 LOOP, +0xf8/+0xfc/+0x100 A/H/R from the pad record'),
    (0x800200E0, 0x800202F8, '57b5fd1e534d7531a2306c238e108a474e80ec04b50b8a83388b0f95ce1d1788',
     'slot start: allocator, then Init (voice, index, pad, ...)'),
    (0x800F5710, 0x800F6300, '6dfd9270b015989a30be46aba62a1f6c61e0289da6cca53f7b261b9f1bbdbd14',
     'ENVELOPE page methods: knob 0x800f5d10 (FX-knob check, setter, apply 0x800f5df0 with mode 0x80591b54, redraw), '
     'tick 0x800f5750 (empty), deleting destructor 0x800f6238'),
    (0x800608D0, 0x800609C0, '9f28c52279fdca61df4135974d916133c4b37da3ec2bfb3c9cec746a3be74d49',
     'ENVELOPE page registry handler: a new object per entry; leaving sends the event, then vtable +4'),
    (0x800735B0, 0x800735E0, 'fb5fa2d3a81b637ed3c6967cb740fca12a90fb41612a6c810d39978a0467505b',
     'page base method +0x5c: calls vtable +0xD0 (page, 50)'),
    (0x80133B30, 0x80133B58, 'b985fa28fc4d618d4e4e3fba3f8977898ce4bf2c030da7f3628d16ce3f319469',
     'vtable +0x14c: the current pad (bank * 16 + pad)'),
    (0x800CE420, 0x800CE478, '4f15482478e1c72e4527cd6b21aa9e33f2577f1c9e7ef92b4f83a1e4e767bc17',
     'non-zero while the CTRL knobs drive the effect'),
    (0x800D3FF0, 0x800D4026, '7399e6400e3ea2ddd99ad6a9f4de1469abffae638c380038c1d7aedbee61886b',
     'popup(text, ms)'),
    (0x800E25C0, 0x800E2644, '704e01fc45d7c7b8beabf5a94f4aebbf066036b65b31fb80e88b160c0a629e76',
     'post command (cmd, a, b): 0xD 1 0 is what the pad setter posts to save'),
    (0x800DC6B8, 0x800DCF08, '76d59a974bf02d89a2b46f14293ee991a737fc3f66453f2c7c952414e5cd4fc7',
     'pad param getter (CSmplPrm, param, pad): 0x6d mute group, 0x7d attack, 0x7f release'),
    (0x800DA720, 0x800DC6B8, 'cc8e475b850943c9337a298e764a26c4a79e506de87dae933b3f4d42ddd12950',
     'pad param setter: Attack/Release unchanged -> nothing; else store, fan-out, Edited (+0x1c)'),
    (0x800D9E30, 0x800D9E68, '5059b42abed775f6b593f90f6aa7c322142c1c5e9bd3d3b7a82cbe48f882d720',
     'the setter\'s test that a pad holds a sample it edits (pad, from the loaded-sample table 0x82e495e4)'),
    (0x800D7A80, 0x800D7E04, '7ec61dd4e3513d3f32b352e73d53540bc3e8a220d7c482ad1af2f90bddacc488',
     'fan-out (0x80591800, pad, param, value): every voice playing the pad gets the param again'),
    (0x800A2C98, 0x800A2CD6, '885f685ca7a8da62c0d6d1ff81c8d3d6d6758a55f8ee52c9a982e17c81940979',
     'slot param update: Attack -> the voice param setter'),
    (0x8003B530, 0x8003B714, '4abe415721f0186324dfbe5201197b0a3fbb6c3a247b56d96625f8c107a7659d',
     'UI dispatcher: a key press sets its bit in 0x80592448, a release clears it'),
    (0x800E5E88, 0x800E8AC0, 'aa6c85b87a623960da16cc5eb997b6607cf7d807e12a93b26cf3bb2f61812874',
     'the charges: every applicator call passes voice + 0x60, or goes through the ITCM helpers'),
    (0x800D2E60, 0x800D2ED0, 'af7710ab37ae1445f292ed8abf9763b1e1d958ee278aaf3f216adf11cdba3613',
     'the veneers to the applicators, their wrappers and the ITCM helpers'),
]
MD = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)

# ---------------------------------------------------------------- tables
FINE_RATIO_BASE = 16000             # index 127 is 0.5 ms * 16000 = 8 s
CURVES = ('LIN', 'EXP', 'LOG', 'S')
EXP_K = 6                           # EXP: (2^(k x) - 1) / (2^k - 1), 36 dB of travel


def sha(b):
    return hashlib.sha256(b).hexdigest()


def div127(x):
    return x // 127


def stock_frames(v):
    """stock Attack/Release value -> frames (the recompute's v * 144000 / 127)."""
    return div127(v * 144000)


def fine_frames():
    """index 0 = 0, 1-127 = 0.5 ms * 16000^((i - 1) / 126) at 48 kHz, rounded (decimal: the same everywhere)."""
    getcontext().prec = 60
    ratio = Decimal(FINE_RATIO_BASE) ** (Decimal(1) / Decimal(126))
    return [0] + [int((Decimal(24) * ratio ** (i - 1)).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
                  for i in range(1, 128)]


def nearest(values, target):
    """the index of the value nearest target (the lower on a tie)."""
    return min(range(len(values)), key=lambda i: (abs(values[i] - target), i))


def curve_tables():
    """Q15 values at i / 256, i = 0..256, plus a guard entry: LIN, EXP, LOG (= 1 - EXP mirrored), S."""
    getcontext().prec = 60
    one = 32768
    lin = [i * 128 for i in range(257)]
    den = Decimal(2) ** EXP_K - 1
    exp = [int(((Decimal(2) ** (Decimal(EXP_K * i) / 256) - 1) / den * one).quantize(Decimal(1), ROUND_HALF_EVEN))
           for i in range(257)]
    log = [one - exp[256 - i] for i in range(257)]
    half = [round(Fraction(3 * i * i * 256 - 2 * i ** 3, 256 ** 3) * one) for i in range(129)]
    s = half + [one - half[256 - i] for i in range(129, 257)]
    return [t + [t[256]] for t in (lin, exp, log, s)]


def tables():
    frames = fine_frames()
    stock = [stock_frames(v) for v in range(128)]
    fine_stock = [nearest(stock, f) for f in frames]
    stock_fine = [nearest(frames, f) for f in stock]
    return frames, fine_stock, stock_fine, curve_tables()


def header(frames, fine_stock, stock_fine, curves):
    def rows(values, per):
        return [', '.join(str(v) for v in values[i:i + per]) + ',' for i in range(0, len(values), per)]
    lines = ['/* Generated by build_pad_env.py. */',
             '/* fine index -> frames at 48 kHz: 0, then 0.5 ms * 16000^((i - 1) / 126) */',
             'EXPORT const u32 env_fine_frames[128] = {', *rows(frames, 12), '};',
             '/* fine index -> the nearest stock Attack/Release value (v * 144000 / 127 frames) */',
             'EXPORT const u8 env_fine_stock[128] = {', *rows(fine_stock, 16), '};',
             '/* stock value -> the nearest fine index */',
             'EXPORT const u8 env_stock_fine[128] = {', *rows(stock_fine, 16), '};',
             '/* LIN, EXP, LOG, S: Q15 at i / 256, and a guard entry */',
             'EXPORT const u16 env_curve[4][258] = {']
    for name, t in zip(CURVES, curves):
        lines += [f'    {{ /* {name} */'] + ['     ' + r for r in rows(t, 16)] + ['    },']
    lines.append('};')
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------- image access
def decompress(src, size):
    """The scatter loader's decompressing handler (0x60080088)."""
    out, i = bytearray(), 0
    while len(out) < size:
        token = src[i]; i += 1
        literal = token & 7
        if literal == 0:
            literal = src[i]; i += 1
        count = token >> 4
        if count == 0:
            count = src[i]; i += 1
        out += src[i:i + literal - 1]; i += max(literal - 1, 0)
        if token & 8:
            start = len(out) - src[i]; i += 1
            for k in range(count + 2):
                out.append(out[start + k])
        else:
            out += bytes(count)
    return bytes(out[:size])


class Runtime:
    """Runtime bytes of an APP1 image, as its scatter loader leaves them (COPY and DECOMPRESS rows)."""

    def __init__(self, img):
        self.img, self.rows, self.cache = bytes(img), scatter(img), {}

    def read(self, addr, n):
        for load, dst, size, fn in self.rows:
            if load and dst <= addr and addr + n <= dst + size:
                if fn == COPY:
                    return self.img[load - FLASH + addr - dst:load - FLASH + addr - dst + n]
                if fn == DECOMPRESS:
                    if dst not in self.cache:
                        self.cache[dst] = decompress(self.img[load - FLASH:], size)
                    return self.cache[dst][addr - dst:addr - dst + n]
        raise ValueError(f'{addr:#x}+{n:#x} not in a copy or decompress row')

    def word(self, addr):
        return struct.unpack('<I', self.read(addr, 4))[0]

    def code_rows(self):
        """(address, bytes) of every copy row in the ITCM and SDRAM code spaces."""
        for load, dst, size, fn in self.rows:
            if load and fn == COPY and (0x400 <= dst < 0x20000 or 0x80000000 <= dst < 0x84000000):
                yield dst, self.img[load - FLASH:load - FLASH + size]


def sx(v, bits):
    return v - (1 << bits) if v >> (bits - 1) & 1 else v


def branch_target(b, i, at):
    """The target of a Thumb branch at b[i] (address at), or None: B<cond>, B, CB(N)Z, B<cond>.W, B.W, BL."""
    h1 = b[i] | b[i + 1] << 8
    if (h1 & 0xF000) == 0xD000 and (h1 >> 8 & 0xF) < 0xE:
        return at + 4 + sx((h1 & 0xFF) << 1, 9)
    if (h1 & 0xF800) == 0xE000:
        return at + 4 + sx((h1 & 0x7FF) << 1, 12)
    if (h1 & 0xF500) == 0xB100:
        return at + 4 + (((h1 >> 9 & 1) << 6) | ((h1 >> 3 & 0x1F) << 1))
    if i + 3 >= len(b) or (h1 & 0xF800) != 0xF000:
        return None
    h2 = b[i + 2] | b[i + 3] << 8
    s = h1 >> 10 & 1
    if (h2 & 0xD000) == 0x8000 and (h1 >> 6 & 0xF) < 0xE:         # B<cond>.W
        off = s << 20 | (h2 >> 11 & 1) << 19 | (h2 >> 13 & 1) << 18 | (h1 & 0x3F) << 12 | (h2 & 0x7FF) << 1
        return at + 4 + sx(off, 21)
    if (h2 & 0xD000) in (0x9000, 0xD000):                           # B.W, BL
        i1, i2 = 1 - ((h2 >> 13 & 1) ^ s), 1 - ((h2 >> 11 & 1) ^ s)
        off = s << 24 | i1 << 23 | i2 << 22 | (h1 & 0x3FF) << 12 | (h2 & 0x7FF) << 1
        return at + 4 + sx(off, 25)
    return None


def branches_into(rt, lo, hi):
    """Every halfword of the code rows read as a Thumb branch, and every word, that reaches [lo, hi)
    (Thumb bit ignored). Data read as code can only add hits, never hide one."""
    hits = []
    for dst, b in rt.code_rows():
        for i in range(0, len(b) - 1, 2):
            t = branch_target(b, i, dst + i)
            if t is not None and lo <= t < hi:
                hits.append(('branch', dst + i))
            if not i % 4 and i + 3 < len(b) and lo <= (struct.unpack_from('<I', b, i)[0] & ~1) < hi:
                hits.append(('word', dst + i))
    return hits


def movw_movt_bx(rd, value):
    """movw rd, #lo; movt rd, #hi; bx rd (10 bytes)."""
    def t3(op, imm):
        h1 = op | ((imm >> 11) & 1) << 10 | (imm >> 12) & 0xF
        h2 = ((imm >> 8) & 7) << 12 | rd << 8 | imm & 0xFF
        return struct.pack('<2H', h1, h2)
    return t3(0xF240, value & 0xFFFF) + t3(0xF2C0, value >> 16) + struct.pack('<H', 0x4700 | rd << 3)


def jump(target, size):
    """movw ip / movt ip / bx ip to target, then nops to size (never executed)."""
    return movw_movt_bx(12, target | 1) + bytes.fromhex('00bf') * ((size - 10) // 2)


def listing(code, at):
    return [f'{i.mnemonic} {i.op_str}'.strip() for i in MD.disasm(code, at)]


# ---------------------------------------------------------------- build
def compile_module(folder: Path, zig: Path, link_base: int, limit: int, tables_h: str):
    folder.mkdir(parents=True, exist_ok=True)
    if subprocess.check_output([str(zig), 'version'], text=True).strip() != '0.13.0':
        raise ValueError('needs Zig 0.13.0')
    (folder / 'pad_env.ld').write_text(f'''ENTRY(env_recompute)
SECTIONS {{
 . = {link_base:#x};
 .text : {{ KEEP(*(.text.env_recompute)) KEEP(*(.text.env_release)) KEEP(*(.text.env_fwd))
            KEEP(*(.text.env_rev)) KEEP(*(.text.env_ui_knob)) KEEP(*(.text.env_ui_poll))
            KEEP(*(.text.env_ui_leave)) *(.text*) }}
 .rodata : ALIGN(16) {{ KEEP(*(.rodata.env_*)) *(.rodata*) }}
 .data : ALIGN(16) {{ *(.data*) }}
 .bss : ALIGN(16) {{ KEEP(*(.bss.env_*)) *(.bss*) *(COMMON) }}
 /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.note*) }}
}}
''', encoding='ascii', newline='\n')
    source = folder / 'pad_env.c'                  # compile LF-normalized source
    source.write_bytes((HERE / 'pad_env.c').read_bytes().replace(b'\r\n', b'\n'))
    (folder / 'pad_env_tables.h').write_text(tables_h, encoding='ascii', newline='\n')
    cache = folder / 'cache'
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache))
    # -g only keeps the symbol table: Zig's -Os (ReleaseSmall) strips it otherwise. Same code.
    subprocess.run([str(zig), 'cc', '-target', 'thumb-freestanding-eabihf', '-mcpu=cortex_m7+vfp4d16',
                    '-mfloat-abi=hard', '-Os', '-g', '-ffunction-sections', '-fdata-sections', '-nostdlib',
                    '-fno-builtin', '-Wall', '-Werror', '-Wl,--no-undefined', '-Wl,--build-id=none',
                    '-Wl,-e,env_recompute', '-Wl,-T,' + str(folder / 'pad_env.ld'), '-I', str(folder),
                    str(source), '-o', str(folder / 'pad_env.elf')], check=True, env=env)
    code, symbols = read_module((folder / 'pad_env.elf').read_bytes(), link_base, limit)
    missing = [n for n in EXPORTS if n not in symbols]
    if missing:
        raise ValueError(f'module exports missing: {missing}')
    return code, {n: symbols[n] for n in EXPORTS}, sha(source.read_bytes()), sha(tables_h.encode('ascii'))


def check_slot(img, rows, base):
    if base & 0xFFF or base < GAP[0] or base + SLOT > GAP[1]:
        raise ValueError(f'the slot must be 4 KB aligned in the free SDRAM gap {GAP[0]:#x}..{GAP[1]:#x}')
    for name, lo, hi in KNOWN_SLOTS:
        if max(lo, base) < min(hi, base + SLOT):
            raise ValueError(f'the slot {base:#x}..{base + SLOT:#x} overlaps {name} at {lo:#x}..{hi:#x}')
    for load, dst, n, fn in rows:
        if max(dst, base) < min(dst + n, base + SLOT):
            raise ValueError(f'row {dst:#x}+{n:#x} overlaps the slot {base:#x}..{base + SLOT:#x}')
    hits = refs_into(bytes(img), base, base + SLOT)
    if hits:
        raise ValueError(f'input refers to the slot: {hits[:4]}')


def check_parent(rt, img):
    for start, end, digest, what in GUARDS:
        if sha(rt.read(start, end - start)) != digest:
            raise ValueError(f'{start:#x}..{end:#x} differs from stock 5.52 ({what})')
    for at, want, what, _, _ in SITES:
        if rt.read(at, len(want)) != want:
            raise ValueError(f'{at:#x}: expected the stock {what}')
        inside = branches_into(rt, at + 1, at + len(want)) + \
            [h for h in refs_into(bytes(img), at + 1, at + len(want)) if h[2] & ~1 != at]   # the entry | 1 is fine
        if inside:
            raise ValueError(f'something reaches into the bytes displaced at {at:#x}: {inside[:4]}')
    for off, want, _, what in VTABLE_SLOTS:
        if rt.word(VTABLE + off) != want:
            raise ValueError(f'ENVELOPE vtable +{off:#x}: expected the stock {what} {want:#x}')
    for off, want, what in VTABLE_KEEP:
        if rt.word(VTABLE + off) != want:
            raise ValueError(f'ENVELOPE vtable +{off:#x}: expected {what} {want:#x}')


def build(inp: Path, out: Path, zig: Path, base: int, build_dir: Path = None):
    img = bytearray(inp.read_bytes())
    app0 = inp.with_name('SP404MKII_APP0.bin')
    if sha(app0.read_bytes()) != APP0_SHA:
        raise ValueError('expected stock APP0 beside the input APP1')
    for name in ('SP404MKII_APP1.bin', 'SP404MKII_APP0.bin', 'manifest.json'):
        if (out / name).exists():
            raise ValueError(f'refusing to overwrite {out / name}')
    rows = scatter(img)
    rt = Runtime(img)
    check_parent(rt, img)
    check_slot(img, rows, base)

    frames, fine_stock, stock_fine, curves = tables()
    tables_h = header(frames, fine_stock, stock_fine, curves)
    folder = build_dir or out / 'build'
    module, symbols, source_sha, tables_sha = compile_module(folder, zig, base, base + SLOT, tables_h)
    if len(module) > SLOT:
        raise ValueError(f'module ({len(module)} bytes) exceeds the slot')
    for name in ('env_recompute', 'env_recompute_stock', 'env_dispatch', 'env_fwd', 'env_fwd_stock', 'env_rev',
                 'env_rev_stock', 'env_release', 'env_ui_knob', 'env_ui_poll', 'env_ui_leave'):
        if not symbols[name] & 1:
            raise ValueError(f'{name} is not a Thumb function symbol')
    resume = {at: back for at, _, _, back, _ in SITES}
    for name, at in STOCK_COPIES.items():
        want = [s[1] for s in SITES if s[0] == at][0] + movw_movt_bx(12, resume[at] | 1)
        got = module[(symbols[name] & ~1) - base:][:len(want)]
        if got != want:
            raise ValueError(f'{name} is not the displaced bytes at {at:#x} and a jump to {resume[at]:#x}: '
                             f'{listing(got, symbols[name] & ~1)}')
    at = symbols['env_release'] & ~1
    tail = listing(module[at - base:at - base + 22], at)
    if tail[-3:] != ['movw ip, #0x316b', 'movt ip, #0x8002', 'bx ip'] or 'r6' not in tail[3]:
        raise ValueError(f'env_release does not set r6 and go on at 0x8002316a: {tail}')

    patches = []
    for at, original, what, back, entry in SITES:
        off = file_offset(img, at, len(original))
        code = jump(symbols[entry], len(original))
        img[off:off + len(original)] = code
        patches.append(dict(address=at, size=len(original), original_hex=original.hex(), replacement_hex=code.hex(),
                            what=f'{what} -> movw ip / movt ip / bx ip to {entry}' +
                                 (f' (the stock path goes on at {back:#x})' if entry != 'env_release' else
                                  f' (it sets r6 and goes on at {back:#x})'),
                            listing=listing(code, at)))
    for off_, old, entry, what in VTABLE_SLOTS:
        off = file_offset(img, VTABLE + off_, 4)
        new = struct.pack('<I', symbols[entry])
        img[off:off + 4] = new
        patches.append(dict(address=VTABLE + off_, size=4, original_hex=struct.pack('<I', old).hex(),
                            replacement_hex=new.hex(), what=f'ENVELOPE page vtable +{off_:#x} {what} -> {entry} '
                                                            f'(which goes on to {old:#x})'))
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
    parent_manifest = inp.with_name('manifest.json')
    manifest = dict(
        revision=REVISION, status='hardware-unverified', published=False,
        description='pad envelopes stage 1: per pad, opt-in on the ENVELOPE page (SHIFT + PITCH/SPEED, tap SHIFT for '
                    'pages 2-4): FINE attack/release 0.5 ms - 8 s, LIN/EXP/LOG/S curves, decay and sustain, '
                    'LOOP-ONCE, REV-TIME; saved in PADCONF bytes 0x64-0x6F; untouched pads run the stock code',
        parent_app1=str(inp), parent_sha256=sha(inp.read_bytes()),
        parent_revision=json.loads(parent_manifest.read_text(encoding='utf-8')).get('revision')
        if parent_manifest.exists() else None,
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        slot=[base, base + SLOT], known_slots=[dict(what=n, start=lo, end=hi) for n, lo, hi in KNOWN_SLOTS],
        blob_base=base, blob_file_offset=file_at, blob_size=len(module), blob_sha256=sha(module),
        source='synth/pad_env.c', source_sha256=source_sha, tables_header_sha256=tables_sha,
        compiler='zig 0.13.0 cc -Os', entries=symbols, patches=patches,
        guards=[dict(start=s, end=e, sha256=d, establishes=w) for s, e, d, w in GUARDS],
        settings=dict(where='PADCONF extended block of pad p: CSmplPrm 0x82e2cd08 + 0xF800 + p * 0x80, bytes 0x64-0x6F',
                      bytes={'0x64': 'flags: b0 FINE, b1 ADSR, b2 LOOP-ONCE, b3 REV-TIME',
                             '0x65': 'attack, fine index', '0x66': 'release, fine index',
                             '0x67': 'curves: b0-1 attack, b2-3 decay, b4-5 release (LIN, EXP, LOG, S)',
                             '0x68': 'decay, fine index (0 off)', '0x69': 'sustain 0-100 %',
                             '0x6a-0x6c': 'reserved for stage E3a (retrigger, overlap fade, choke)',
                             '0x6d': 'layout version: 1 whenever any of 0x64-0x6c is not 0; anything else = stock',
                             '0x6e-0x6f': 'reserved'},
                      save='Edited flag (CSmplPrm + 0x1c) on every change; command 0xD (0x800e25c0(0xd, 1, 0)) 1 s '
                           'after the last change, or when the page closes'),
        fine_map=dict(formula='index 0 = 0; 1-127 = 0.5 ms * 16000^((i - 1) / 126), 48 kHz frames, rounded',
                      frames=frames, nearest_stock=fine_stock, stock_to_fine=stock_fine),
        curves=dict(names=list(CURVES), exp=f'(2^({EXP_K} x) - 1) / (2^{EXP_K} - 1)', log='1 - EXP(1 - x)',
                    s='3x^2 - 2x^3', rising='attack: level = curve(x)',
                    falling='decay, release: level = lo + (hi - lo) * curve(1 - x)'),
        ui=dict(page='ENVELOPE (0x10), SHIFT + PITCH/SPEED',
                pages=['1 A-H-R (stock; FINE: attack/release fine index)',
                       '2 SHAPE: attack curve, TIME STOCK/FINE, release curve',
                       '3 DECAY: decay, sustain, decay curve',
                       '4 MODE: LOOP every/first pass, -, REVERSE mirror/time'],
                next_page='tap SHIFT (press and release within 1 s; no other key pressed or let go, no knob turned, '
                          'no pad change in between)',
                apply='COPY held: the mute group; REMAIN held: the bank (as stock\'s apply 0x800f5df0)'),
        tool='synth/build_pad_env.py')
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
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0x83FDE000)
    ap.add_argument('--build-dir', type=Path)
    a = ap.parse_args()
    m = build(a.app1.resolve(), a.out.resolve(), a.zig.resolve(), a.base,
              a.build_dir.resolve() if a.build_dir else None)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size', 'blob_base', 'blob_size')}, indent=1))


if __name__ == '__main__':
    main()
