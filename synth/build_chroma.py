"""Chromatic mode scales and range (hardware test build): in chromatic mode VALUE press steps through the
Sound Generator's 34 scales, the pads walk the scale (the Sound Generator's fold), and the pads reach from
3 octaves down to +18 semitones (stock: -12 to +15). CHROMA.md has the design.

A stage on the published Sound Generator + Kits v9.46 APP1. Thirteen changes in 5.52 space, each checked byte
for byte against what it replaces:
- code: the project setter's SHIFT, SCALE and ROOT cases (0x800df714, 0x800dfc00, 0x800dfc14) -> jumps to
  chroma_set_shift / _scale / _root: stock's compare and store, then the five chromatic pad tables again;
- code: the project range method's SHIFT case (0x800d39e4) -> chroma_shift_range_case;
- code: the range method's case for 0x73 / 0x9b (0x800d38c8) -> chroma_note_range_case: the window in which
  the chromatic page plays a pad, the pad lights light it and the display shows its note becomes -36..+18
  (stock -12..12); every other caller (pattern step entry) keeps -12..12;
- code: the fork's SCALE range and label jumps (0x800d39fc, 0x800c5ca4; build_scales.py) -> chroma's bridges,
  which in chromatic mode answer 0-33 and the names and otherwise go on to the scale module's bridges;
- code: VALUE press, next scale (0x8011247e, 0x80083992; ten bytes each) -> movw ip / movt ip / blx ip to
  chroma_next_scale_stub (stock's 0-6 outside chromatic mode);
- code: SMPL TASK's MIDI note-off (0x80050e78): sub.w r1, r0, #13 -> sxtb r1, r0; subs r1, #13;
- code: the pattern recorder's pad-note case (0x800bd644) -> chroma_record (chromatic notes outside the
  pattern's 5 bits are not recorded);
- data: the scale mask lists of the pad lights (0x801ab4bc) and the chromatic key handler (0x801ab3b0) ->
  chroma_masks (the same masks, a period before each).
At run time the module rewrites the five copies of the chromatic pad table (0x80028f64, 0x80050ee0,
0x801aa0a0, 0x801aa0e0, 0x801aa120); with Chrom and a stock shift they keep stock's values.
Nothing branches into the displaced bytes but their entries (every BL, B, B<cond>, CB(N)Z, B.W, literal and
MOVW/MOVT pair in the image is checked). Stock code the module calls, reads or relies on is checked byte
for byte (GUARDS). The module (Zig 0.13.0, -Os) goes in a new boot copy row in an 8 KB slot at 0x83FD7000,
below every other fork module (KNOWN_SLOTS); the builder checks that no row of the input and no known slot
overlaps it and that nothing in the input refers to it.

usage: python synth/build_chroma.py IN_APP1 OUT_DIR --zig ZIG [--base 0x83FD7000] [--build-dir DIR]
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

import capstone

from build_arp import file_offset, read_module, scatter
from build_start_fix import refs_into

HERE = Path(__file__).resolve().parent
FLASH, COPY, DECOMPRESS = 0x60080000, 0x600800E4, 0x60080088
APP0_SHA = '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23'
REVISION = 'chroma-test1'
SLOT = 0x2000                       # reserved: [base, base + SLOT)
GAP = (0x83FC9000, 0x83FF0000)      # above the fork's rows (end 0x83FC8450), below the end of cacheable SDRAM
# Every other fork module's reserved RAM (branch, start, end).
KNOWN_SLOTS = [
    ('claude/kits-save (kit edits saved with the project)', 0x83FD5000, 0x83FD7000),
    ('claude/pad-env-pitchfilter (pad envelopes stage 2)', 0x83FD9000, 0x83FDC000),
    ('claude/note-repeat (note repeat)', 0x83FDC000, 0x83FDE000),
    ('claude/pad-env-amp (pad envelopes)', 0x83FDE000, 0x83FE2000),
    ('claude/fx-deep-edit (FX deep edit)', 0x83FE2000, 0x83FE6000),
    ('claude/fx-probe (FX probe)', 0x83FE6000, 0x83FE8000),
    ('claude/bounce-stage2, claude/bounce-stage3 (bounce)', 0x83FE8000, 0x83FED000),
    ('claude/cpu-meter (CPU meter test)', 0x83FED000, 0x83FEF000),
    ('claude/bounce-probe (bounce probe test)', 0x83FEE000, 0x83FEF000),
    ('main (RESAMPLE start fix)', 0x83FEF000, 0x83FF0000),
]
EXPORTS = ('chroma_update', 'chroma_shift_range', 'chroma_scale_range', 'chroma_name', 'chroma_next_scale',
           'chroma_set_shift', 'chroma_set_scale', 'chroma_set_root', 'chroma_shift_range_case', 'chroma_note_range_case',
           'chroma_scale_range_case', 'chroma_name_case', 'chroma_next_scale_stub', 'chroma_record', 'chroma_masks',
           'chroma_updates')
LO, HI = -36, 18
STOCK_T = (4, 5, 6, 7, 0, 1, 2, 3, -4, -3, -2, -1, -8, -7, -6, -5)
TABLES = (0x80028F64, 0x80050EE0, 0x801AA0A0, 0x801AA0E0, 0x801AA120)
MASK_LISTS = ((0x801AB4BC, 'the pad lights'), (0x801AB3B0, 'the chromatic key handler'))
SCALE_BRIDGES = (0x83FA1001, 0x83FA1081)   # the scale module's label and range bridges (build_scales.py)

# (address, displaced bytes, what they are, kind, entry): kind 'jump' = movw ip / movt ip / bx ip, 'call' =
# movw ip / movt ip / blx ip, 'bytes' = the replacement given as entry
SITES = [
    (0x800DF714, bytes.fromhex('e86a504501f0f382c5f82ca001f0efba'),
     'setter SHIFT (0xC0): ldr r0, [r5, #0x2c]; cmp r0, sl; beq.w end; str.w sl, [r5, #0x2c]; b.w end', 'jump',
     'chroma_set_shift'),
    (0x800DFC00, bytes.fromhex('d5f81801504501f07c80c5f818a101f078b800bf'),
     'setter SCALE (0xF1): ldr.w r0, [r5, #0x118]; cmp r0, sl; beq.w end; str.w sl, [r5, #0x118]; b.w end; nop',
     'jump', 'chroma_set_scale'),
    (0x800DFC14, bytes.fromhex('d5f81c01504501f07280c5f81ca101f06eb800bf'),
     'setter ROOT (0xF2): ldr.w r0, [r5, #0x11c]; cmp r0, sl; beq.w end; str.w sl, [r5, #0x11c]; b.w end; nop',
     'jump', 'chroma_set_root'),
    (0x800D39E4, bytes.fromhex('6ff0070028600420206070bd'),
     'range SHIFT (0xC0): mvn r0, #7; str r0, [r5]; movs r0, #4; str r0, [r4]; pop {r4, r5, r6, pc}', 'jump',
     'chroma_shift_range_case'),
    (0x800D38C8, bytes.fromhex('6ff00b0028600c20206070bd'),
     'range 0x73 / 0x9b: mvn r0, #11; str r0, [r5]; movs r0, #12; str r0, [r4]; pop {r4, r5, r6, pc}', 'jump',
     'chroma_note_range_case'),
    (0x800D39FC, bytes.fromhex('41f2810cc8f2fa3c604700bf'),
     'range SCALE (0xF1), the fork\'s jump: movw ip / movt ip / bx ip to the scale module\'s 0x83fa1081; nop',
     'jump', 'chroma_scale_range_case'),
    (0x800C5CA4, bytes.fromhex('41f2010cc8f2fa3c604700bf'),
     'SCALE label, the fork\'s jump: movw ip / movt ip / bx ip to the scale module\'s 0x83fa1001; nop', 'jump',
     'chroma_name_case'),
    (0x8011247E, bytes.fromhex('821f4ff0f10118bf421c'),
     'VALUE press: subs r2, r0, #6; mov.w r1, #0xf1; it ne; addne r2, r0, #1 (the next scale, 0-6)', 'call',
     'chroma_next_scale_stub'),
    (0x80083992, bytes.fromhex('821f4ff0f10118bf421c'),
     'VALUE press (second handler): subs r2, r0, #6; mov.w r1, #0xf1; it ne; addne r2, r0, #1', 'call',
     'chroma_next_scale_stub'),
    (0x80050E78, bytes.fromhex('a0f10d01'),
     'SMPL TASK MIDI note-off: sub.w r1, r0, #13 (the stored note + 13, read unsigned)', 'bytes',
     bytes.fromhex('41b20d39')),
    (0x800BD644, bytes.fromhex('617945f0400202284fea0240'),
     'recorder pad note: ldrb r1, [r4, #5]; orr r2, r5, #0x40; cmp r0, #2; lsl.w r0, r2, #16', 'jump',
     'chroma_record'),
]
GUARDS = [
    (0x800DED18, 0x800DEE7E, '9c5e6c640f11d2a272d7bf489276366056e429f055a5a1efad0b6f95857ce9a2',
     'the project setter up to its switch: the range clamp (vtable +0x1c) first'),
    (0x800DEE7E, 0x800DEF82, '120387c1500a335717aa98c5e277b4eea84441be482d345142cabf9f5ce6fed6',
     'the setter switch table (params 0x80-0x101): SHIFT, SCALE, ROOT cases'),
    (0x800E0D02, 0x800E0D60, '29bd75528b8e8760cd51eb89a838a7b346f990432e8ca8f9ff353bf86f4a2130',
     'the setter common end: listeners told'),
    (0x800D35F0, 0x800D3816, '9305263145affe5d9041eff48520df521d8e9e617b5433b6d394984e8a65ab09',
     'the project range method: frame push {r4-r6, lr}, r5 = &min, r4 = &max, its switch table'),
    (0x800DDA38, 0x800DE130, '08ba1ba87cc179ed6d922df403f8cbb9a92ac9163f1ccbaa480cf0045cb57dc1',
     'the project getter: 0xBF [0x805923f8 + 0xc], 0xC0 +0x2c, 0xF1 +0x118, 0xF2 +0x11c'),
    (0x800D6440, 0x800D64B0, '8e2c4c4c516cd4aa55c9c28bb8224ddd4f722f4a9947b11709f18335be664c61',
     'voice manager: chromatic note-on note = T[pad % 16] - shift (0x801aa0a0)'),
    (0x800D7110, 0x800D71BC, '1ede998f4c11878d171dd3d0ef3f5157b39f4087d23cfbf8926f92c636b595b5',
     'voice manager: chromatic note (0x801aa0a0, two sites)'),
    (0x800D7288, 0x800D72B4, 'a1607db7b43c3f81b23fb3fe56f0c6ac0d3b49620904b7ad7c0605b4943ec2db',
     'voice manager: chromatic note (0x801aa0a0)'),
    (0x800D73E8, 0x800D743C, '008408ebc05e39a60ded1a13978ba4a4ca606d9f760c18a48959d386d9ea01d0',
     'voice manager: chromatic note (0x801aa0a0)'),
    (0x8001E3E8, 0x8001E436, '03da28bbf1ce0bc550613a7c9e5097ad4f39a171fb622d67553507bf8af59cae',
     'voice note-off: a chromatic slot is found by its pad (+0x48), not its note'),
    (0x80028224, 0x80028600, '04d9ae407cec877c6122a15c3fbffa0c09d7e891800b2a5dcc1842f055155c33',
     'pad lights, chromatic: T (0x80028f64) - shift, scale masks 0x801ab4bc'),
    (0x80028F64, 0x80028FA4, '57b44170fcdf99e7b672726b93de49a90d28c931fe91c3871858fb18bf181734',
     'pad lights: T'),
    (0x80050D48, 0x80050EE0, '6fb30b8d2ff0ee2c18d24b03066dee49bd7a06346b97503b5b1a08d7b23cb58f',
     'SMPL TASK chromatic pad event: T - shift, MIDI out, the stored note + 13'),
    (0x80050EE0, 0x80050F20, '57b44170fcdf99e7b672726b93de49a90d28c931fe91c3871858fb18bf181734',
     'SMPL TASK: T'),
    (0x80111B80, 0x80111C94, 'a1d84bc0efe1f725e228800eeddebf00032d1362eda4629ca899a14301861d21',
     'chromatic key handler: T (0x801aa120), scale masks 0x801ab3b0, range 0x9b'),
    (0x80111C94, 0x80111DF4, 'b4524a61c87b5f05e625c4701e7cce879db57f849fcbd1dde804f18ebc6580bf',
     'the chromatic page pad handler: step entry within 0x9b (0x80111cdc), the scale masks, the live pad on to '
     '0x800c7db8'),
    (0x80111EC4, 0x80111F7A, 'b5b66aeee474325a36ea45653cc640d3a1ba6bc471c273a03bf14a3f1477272e',
     'pattern step entry: T (0x801aa120) - shift'),
    (0x8008D210, 0x8008D250, '59160892283677a392a6ec86a5f17b474fa84f55db65cad055deadfd5a91877c',
     'roll entry: T (0x801aa120) - shift within 0x9b'),
    (0x800F7D90, 0x800F7DC0, 'bb4896ae275d3b42aa0175e8a99be0953aaef08a02e2f4d7536855abcd9c212c',
     'last pad note: T (0x801aa0e0) - shift'),
    (0x800F8050, 0x800F808C, 'c7995411aceaf330c016fae4764aa57f2425aad37dbeb3cc0161168bed07a0f4',
     'last pad note: T (0x801aa0e0) - shift'),
    (0x801AA010, 0x801AA0A0, 'f2ffc15dd9e5ef2f8e493d109979bde273b4c1bd05a983aea92727be12b6f874',
     'stock scale masks (scales 1-6)'),
    (0x801AA0A0, 0x801AA160, '6c73aa7ab3b70ce2dfcbb854dd0a086498b2ed5f6f78d141a1befbf3321abd36',
     'T, three copies'),
    (0x80112460, 0x801124A4, 'a0e667ee3efa4baed4bf24bc95f1191c83b4908cb1b8e98e63db4f2a69b02c64',
     'VALUE press: the next scale (0-6), set through 0x800ded18'),
    (0x8008397E, 0x800839B6, '508c91d1f26557a21cf12b41e72ed0c7eeabee8915e22c5f4fdbcff97724cd42',
     'VALUE press (second handler): the next scale (0-6)'),
    (0x800BD5A0, 0x800BD670, '28fc672160c3a6ef4767ca4a5c3b309e5490ba582f3d7fb817d4f5bdcef4d596',
     'the pattern recorder: pad notes (types 0xC, 0x16) recorded with the note byte'),
    (0x800BD78A, 0x800BD792, '07133e8c237abf68a4a9977e50a9bae19f6daeea4f4ad20a2b8b035fde76622b',
     'the pattern recorder: its end'),
    (0x800C6758, 0x800C6760, '17a9684bb02e737f9a102c41394e9b952f81351383badd83ef459114b4bc53b1',
     'the SCALE label code: where a label ends'),
    (0x83FA1000, 0x83FA1090, '5fd499ec26de4a3fccd0c9ed3725c88d5f7819b21412931a3eb5b85f9ab70d1f',
     'the fork scale module: its SCALE label and range bridges'),
]

MD = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def scales():
    rows = json.loads((HERE / 'scales.json').read_text(encoding='utf-8'))
    if len(rows) != 34 or rows[0]['label'] != 'Chrom' or any(len(r['label']) > 8 for r in rows):
        raise ValueError('scales.json: expected the 34 Sound Generator scales')
    return rows


def mask(row):
    return sum(1 << n for n in row['notes'])


def header(rows):
    lines = ['/* generated by build_chroma.py from synth/scales.json */',
             f'#define SCALE_COUNT {len(rows)}',
             'static const u16 scale_masks[SCALE_COUNT] = {' + ', '.join(f'{mask(r):#05x}' for r in rows) + '};',
             'static const char scale_labels[SCALE_COUNT][9] = {' + ', '.join(json.dumps(r['label']) for r in rows)
             + '};',
             '/* scales 1-6 as the stock mask lists hold them (a byte a semitone), twice: the lists point at the',
             ' * second period, so the stock lookups index -11..11 right */',
             'EXPORT const u8 chroma_masks[6][24] = {']
    for r in rows[1:7]:
        b = [1 if n in r['notes'] else 0 for n in range(12)]
        lines.append('    {' + ', '.join(str(x) for x in b + b) + '},')
    lines.append('};')
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------- image access (as build_pad_env.py)
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


def movw_movt(rd, value):
    def t3(op, imm):
        h1 = op | ((imm >> 11) & 1) << 10 | (imm >> 12) & 0xF
        h2 = ((imm >> 8) & 7) << 12 | rd << 8 | imm & 0xFF
        return struct.pack('<2H', h1, h2)
    return t3(0xF240, value & 0xFFFF) + t3(0xF2C0, value >> 16)


def jump(target, size):
    """movw ip / movt ip / bx ip to target, then nops to size (never executed)."""
    return movw_movt(12, target | 1) + struct.pack('<H', 0x4760) + bytes.fromhex('00bf') * ((size - 10) // 2)


def call(target, size):
    """movw ip / movt ip / blx ip to target (10 bytes): the code goes on after it."""
    if size != 10:
        raise ValueError('a call site is ten bytes')
    return movw_movt(12, target | 1) + struct.pack('<H', 0x47E0)


def listing(code, at):
    return [f'{i.mnemonic} {i.op_str}'.strip() for i in MD.disasm(code, at)]


# ---------------------------------------------------------------- build
def compile_module(folder: Path, zig: Path, link_base: int, limit: int, tables_h: str):
    folder.mkdir(parents=True, exist_ok=True)
    if subprocess.check_output([str(zig), 'version'], text=True).strip() != '0.13.0':
        raise ValueError('needs Zig 0.13.0')
    keep = ' '.join(f'KEEP(*(.text.{n}))' for n in EXPORTS if not n.startswith(('chroma_masks', 'chroma_updates')))
    (folder / 'chroma.ld').write_text(f'''ENTRY(chroma_update)
SECTIONS {{
 . = {link_base:#x};
 .text : {{ {keep} *(.text*) }}
 .rodata : ALIGN(16) {{ KEEP(*(.rodata.chroma_masks)) *(.rodata*) }}
 .data : ALIGN(16) {{ *(.data*) }}
 .bss : ALIGN(16) {{ KEEP(*(.bss.chroma_*)) *(.bss*) *(COMMON) }}
 /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.note*) }}
}}
''', encoding='ascii', newline='\n')
    source = folder / 'chroma.c'                   # compile LF-normalized source
    source.write_bytes((HERE / 'chroma.c').read_bytes().replace(b'\r\n', b'\n'))
    (folder / 'chroma_tables.h').write_text(tables_h, encoding='ascii', newline='\n')
    cache = folder / 'cache'
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache))
    # -g only keeps the symbol table: Zig's -Os (ReleaseSmall) strips it otherwise. Same code.
    subprocess.run([str(zig), 'cc', '-target', 'thumb-freestanding-eabihf', '-mcpu=cortex_m7+vfp4d16',
                    '-mfloat-abi=hard', '-Os', '-g', '-ffunction-sections', '-fdata-sections', '-nostdlib',
                    '-fno-builtin', '-Wall', '-Werror', '-Wl,--no-undefined', '-Wl,--build-id=none',
                    '-Wl,-e,chroma_update', '-Wl,-T,' + str(folder / 'chroma.ld'), '-I', str(folder),
                    str(source), '-o', str(folder / 'chroma.elf')], check=True, env=env)
    code, symbols = read_module((folder / 'chroma.elf').read_bytes(), link_base, limit)
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


def check_parent(rt, img, rows):
    for start, end, digest, what in GUARDS:
        if sha(rt.read(start, end - start)) != digest:
            raise ValueError(f'{start:#x}..{end:#x} differs from what was checked ({what})')
    for at, want, what, _, _ in SITES:
        if rt.read(at, len(want)) != want:
            raise ValueError(f'{at:#x}: expected the {what}')
        inside = branches_into(rt, at + 1, at + len(want)) + \
            [h for h in refs_into(bytes(img), at + 1, at + len(want)) if h[2] & ~1 != at]   # the entry | 1 is fine
        if inside:
            raise ValueError(f'something reaches into the bytes displaced at {at:#x}: {inside[:4]}')
    for at in TABLES:
        if struct.unpack('<16i', rt.read(at, 64)) != STOCK_T:
            raise ValueError(f'{at:#x}: expected the chromatic pad table')
    for at, what in MASK_LISTS:
        for k, p in enumerate(struct.unpack('<6I', rt.read(at, 24))):
            want = bytes(1 if n in rows[k + 1]['notes'] else 0 for n in range(12))
            if rt.read(p, 12) != want:
                raise ValueError(f'{what}\'s mask for scale {k + 1} ({p:#x}) is not scales.json\'s {rows[k + 1]["label"]}')
    names = b''.join(r['label'].encode('ascii').ljust(9, b'\0') for r in rows)
    masks = struct.pack('<34H', *[mask(r) for r in rows])
    if img.count(names) != 1 or img.count(masks) != 1:
        raise ValueError('the scale module\'s names and masks are not scales.json\'s')


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
    table_rows = scales()
    check_parent(rt, img, table_rows)
    check_slot(img, rows, base)

    tables_h = header(table_rows)
    module, symbols, source_sha, tables_sha = compile_module(build_dir or (out / 'build'), zig, base,
                                                             base + SLOT, tables_h)
    if len(module) > SLOT:
        raise ValueError(f'module is {len(module)} bytes, the slot {SLOT}')
    for name in EXPORTS:
        thumb = name not in ('chroma_masks', 'chroma_updates')
        if (symbols[name] & 1) != thumb:
            raise ValueError(f'{name}: unexpected symbol {symbols[name]:#x}')

    patches = []
    for at, original, what, kind, entry in SITES:
        off = file_offset(img, at, len(original))
        if kind == 'jump':
            code = jump(symbols[entry], len(original))
            how = f'movw ip / movt ip / bx ip to {entry}'
        elif kind == 'call':
            code = call(symbols[entry], len(original))
            how = f'movw ip / movt ip / blx ip to {entry} (r1 = 0xF1, r2 = the next scale on return)'
        else:
            code = entry
            how = ' / '.join(listing(code, at))
        if len(code) != len(original):
            raise ValueError(f'{at:#x}: the replacement is {len(code)} bytes, not {len(original)}')
        img[off:off + len(original)] = code
        patches.append(dict(address=at, size=len(original), original_hex=original.hex(), replacement_hex=code.hex(),
                            what=f'{what} -> {how}', listing=listing(code, at)))
    for at, what in MASK_LISTS:
        off = file_offset(img, at, 24)
        old = bytes(img[off:off + 24])
        new = struct.pack('<6I', *[symbols['chroma_masks'] + 24 * k + 12 for k in range(6)])
        img[off:off + 24] = new
        patches.append(dict(address=at, size=24, original_hex=old.hex(), replacement_hex=new.hex(),
                            what=f'{what}\'s scale mask list (scales 1-6) -> chroma_masks[k] + 12 (the same masks, '
                                 f'a period before each)'))
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
        description='chromatic mode: VALUE press steps through the Sound Generator\'s 34 scales, the pads walk the '
                    'scale (the Sound Generator\'s fold); the pads reach 3 octaves down (to -36) and up to +18; '
                    'Chrom with a stock shift is stock',
        parent_app1=str(inp), parent_sha256=sha(inp.read_bytes()),
        parent_revision=json.loads(parent_manifest.read_text(encoding='utf-8')).get('revision')
        if parent_manifest.exists() else None,
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        slot=[base, base + SLOT], known_slots=[dict(what=n, start=lo, end=hi) for n, lo, hi in KNOWN_SLOTS],
        blob_base=base, blob_file_offset=file_at, blob_size=len(module), blob_sha256=sha(module),
        source='synth/chroma.c', source_sha256=source_sha, tables_header_sha256=tables_sha,
        compiler='zig 0.13.0 cc -Os', entries=symbols, patches=patches,
        guards=[dict(start=s, end=e, sha256=d, establishes=w) for s, e, d, w in GUARDS],
        tables=[f'{t:#x}' for t in TABLES], notes=dict(lo=LO, hi=HI, stock_t=list(STOCK_T)),
        scales=[r['label'] for r in table_rows],
        ui=dict(scale='VALUE press in chromatic mode: the next of the 34 scales (stock 0-6); the screen names it',
                root='ROLL + VALUE turn, as stock', shift='VALUE turn: 4 pads, SHIFT + VALUE turn: 1 pad (with a '
                'scale a pad is a scale note), within a range that keeps every pad in -36..+18',
                record='chromatic notes outside -13..+18 play but are not recorded into patterns',
                lights='every pad that plays lights (stock lights only -12..+12)'),
        tool='synth/build_chroma.py')
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
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0x83FD7000)
    ap.add_argument('--build-dir', type=Path)
    a = ap.parse_args()
    m = build(a.app1.resolve(), a.out.resolve(), a.zig.resolve(), a.base,
              a.build_dir.resolve() if a.build_dir else None)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size', 'blob_base', 'blob_size')}, indent=1))


if __name__ == '__main__':
    main()
