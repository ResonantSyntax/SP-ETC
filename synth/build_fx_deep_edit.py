"""FX deep edit (hardware test build): extra screens on the FX screen for the bus effects' parameters stock
never sends.

A stage on the published Sound Generator + Kits v9.46 APP1 (FX_DEEP_EDIT.md). On the FX screen REMAIN + FX
opens (stock's screen that stays until EXIT, REMAIN or that FX button again), VALUE press steps screen 1,
screen 2 (where the effect has CTRL 4-6), then the effect's extra screens, three of its settings that stock
5.52 never sends to the effects chip (BMC) a screen on CTRL 1-3, shown in the stock popup, then screen 1 again.
Each change is one DT1 through the stock builder 0x800d8118, inside the firmware's own min/max for the ID.
Values live in RAM per bus and effect, and go to the chip again whenever the firmware selects that effect on
that bus (an FxType write). (Test 1's TOP page, EXIT + VALUE, is gone; test 3 drops test 2's FX button hold,
which kept MFX's effect choice away: an FX button alone is stock again.)

The settings of an effect are the parameters that are not in its six-ID knob record (0x802e5b40) and that
DM-404's fxmap.json (MIT, bases from a boot capture) gives no boot value. IDs come from the firmware's name
table (0x80245ee4) joined with fxmap; the builder insists the firmware's name for every ID is fxmap's name at
that address, and that every range is the firmware's own (0x801ad1fc/0x801ac830, inside 0..255).

Three changes in 5.52 space:
- data: TOP's page vtable 0x8022ce5c, slot +0x08 (0x8022ce64), DOOM OS ED5E's page filter 0x6031c8f9 ->
  fde_filter, which hands every event the page doesn't take on to that filter;
- code: the DT1 builder's first ten bytes (0x800d8118: push.w, sub sp, movw sb) -> movw ip / movt ip / bx ip
  to fde_dt1. Its four instructions send anything but an FxType for BUS 1-4 straight to fde_dt1_stock (those
  three instructions, then on at 0x800d8122) with the caller's stack and return address, so the builder runs
  exactly as stock; an FxType for BUS 1-4 goes to fde_dt1_fxtype, which sends it and then that bus's edited
  values for the effect. Nothing branches into the ten bytes but the entry;
- code: the FX screen's VALUE toggle (0x801479a0, ten bytes: movw r1, #0x1b3f; ldrb r2, [r0, r1]; cmp r2, #0;
  it eq) -> movw ip / movt ip / bx ip to fde_value (the screens, then the extra screens). Its one caller is the
  generic key handler (0x800cba46); nothing branches into the bytes but the entry.
Stock code the module calls, reads or relies on is checked byte for byte (GUARDS). The module (Zig 0.13.0,
-Os) goes in a new boot copy row in a 16 KB slot at 0x83FE2000, below the FX probe (0x83FE6000), bounce
stage 3 (0x83FE8000), the CPU meter, the bounce probe and the start fix; the builder checks that no row
overlaps the slot and that nothing in the input refers to it.

usage: python synth/build_fx_deep_edit.py IN_APP1 OUT_DIR --zig ZIG --fxmap DM404/core/fx/fxmap.json
       [--base 0x83FE2000] [--build-dir DIR]
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
REVISION = 'fx-deep-edit-test3'
SLOT = 0x4000                       # reserved: [base, base + SLOT)
SLOT_CEILING = 0x83FE6000           # the FX probe's slot starts here
EXPORTS = ('fde_filter', 'fde_dt1', 'fde_dt1_stock', 'fde_dt1_fxtype', 'fde_value', 'fde', 'fde_values',
           'fde_edited', 'fde_text', 'fde_effect_names', 'fde_first', 'fde_count', 'fde_ids', 'fde_names')
VTABLE_SLOT, DOOM_FILTER = 0x8022CE64, 0x6031C8F9     # TOP page vtable 0x8022ce5c, +8
DT1, DT1_BODY = 0x800D8118, 0x800D8122                # the builder; where its body goes on after 10 bytes
DT1_HEAD = bytes.fromhex('2de9f04f83b04ef2c819')      # push.w {r4-r11, lr}; sub sp, #12; movw sb, #0xe1c8
TOGGLE, TOGGLE_HEAD = 0x801479A0, bytes.fromhex('41f63f31425c002a08bf')   # movw r1, #0x1b3f; ldrb; cmp; it eq
PARAMS, EFFECTS = 627, 49
NAMES, RECORDS, DEFAULTS, MAXIMA, MINIMA = 0x80245EE4, 0x802E5B40, 0x801ABE64, 0x801AC830, 0x801AD1FC
EFFECT_NAMES = 0x8020B3D8           # by effect number, 0 Bypass
TEXT_LINE = 17                      # popup: lines of about 18 characters
NAME_LEN = 9                        # a setting's name; "C3 M D LEVEL 255" is 16
EFFECT_LEN = 12                     # "WRMSATURATOR 8/8" is 16

# Stock 5.52 code and data the module calls, reads or relies on, unchanged in DOOM OS ED5E and the
# fork up to v9.46: (start, end, SHA-256 of the runtime bytes, what it establishes).
GUARDS = [
    (0x800D8118, 0x800D84F0, '8fc9de77c2021dd062835c2d99d9b11db4a5074353db378182af4e280f086e28',
     'DT1 builder (link 0x80592500, parameter ID, index, value): the ID\'s address from the tables below, the '
     'value as two nibbles, the Roland checksum, six USB-MIDI packets through 0x800d93f0; its first ten bytes '
     'are the three instructions fde_dt1_stock runs before going on at 0x800d8122'),
    (0x800D93F0, 0x800D943A, '8ad9e33e20c74bf7fa3a35cdb2def8027db57a771aa89a8bda31f15ee6de1e72',
     'packet send: n bytes to LPUART3 0x4018c000, polled, under the link semaphore'),
    (0x8022E1C8, 0x8022EDA8, '7064898b21461367b5303598e6d959ddc5d260fb30edb8d6a90448f8193de817',
     'DT1 builder: ID ranges and per-range address data (every byte it reads for IDs 0..0x88, 0xa3..626)'),
    (0x8022EFD6, 0x80233194, 'c0db912123544ca7cb294ec0b4496699d18dea9163bddb0adcc321427a908a49',
     'DT1 builder: the address table'),
    (0x800D3FF0, 0x800D4026, '7399e6400e3ea2ddd99ad6a9f4de1469abffae638c380038c1d7aedbee61886b',
     'popup(text, ms): copies the text and arms the stock type-3 popup for ms'),
    (0x8003B530, 0x8003B714, '4abe415721f0186324dfbe5201197b0a3fbb6c3a247b56d96625f8c107a7659d',
     'UI dispatcher: a key press sets its bit in 0x80592448 (release clears it) before the page\'s registry '
     'handler gets the event record (press type 5, release type 6, VALUE turned type 7)'),
    (0x80072D10, 0x80072D24, '3c984cc11cf0b51133b6995d60d2562b8aa13f89016de0bc8c4244ddb02c8244',
     'VALUE encoder: posts event 7 with encoder 0 and the turn as a signed count'),
    (0x8003B480, 0x8003B4D4, '7bab556d7f43470f51c1a0cfb5d3e4f6de8afadc6d211c228e4a9c93ffcd7247',
     'event 7 post: (type, encoder, turn) into the UI queue'),
    (0x8005EDA8, 0x8005EE4A, 'c20fec979fc3f36e617c845a861d61a6201739654a997ff567b796b9c1dc2a3a',
     'TOP\'s registry handler: the page object [0x80cfd350] with vtable 0x8022ce5c; every event after the '
     'first goes to vtable +8 (page, event) and its result is the page\'s'),
    (0x800DA010, 0x800DA4E2, '4ade62998f0faff5561aa6443774325237b5b6ef8c1a7c3b5127acc9f376a3c7',
     'system GetParam: 0x27c[slot] is the halfword at +0xc4 + 2 * slot, the effect on that slot'),
    (0x800D94D8, 0x800D9CBA, 'e229d3d211477713ff1384a696de5e77bccf9765558efa7f0bbbd7a551610bfe',
     'settings GetParam: 0x3a is the word at +0x4a8'),
    (0x800CC030, 0x800CC11E, 'f4f074036b49bc54c43eb72a6a2e62503e5d578d2e1e4866ad370de4182acc14',
     'TOP\'s CTRL 1-3 on the bus effect: settings 0x3a picks the slot (0 input FX, 1-4 BUS 1-4); nothing '
     'happens while system 0x27c[slot] is 0'),
    (0x800D0CF0, 0x800D112C, '759f4ec385208b66e29e71de52b962cd760da1d1d88137052c4d9c6839031f71',
     'effect select: FxType 0x7e + slot = 0x27c[slot] is sent when it differs from the cache 0x80246f38; the '
     'effect\'s knob parameters are not sent'),
    (0x800DE270, 0x800DE8A0, 'd2222dc0a7ff44654b8462ce32f0b1cf6bb6253605a4088942f505a00212a4e1',
     'system SetParam: IDs 0x21..0xa1 (FxType 0x7e.. among them) are sent as set; 0x27c selects for slots 0, 3, 4; '
     'CTRL k (0x27f + k) stores and sends one knob parameter'),
    (0x8001B8D0, 0x8001B964, 'b735738c911aa8c1e5e9b9737192edb9d2ad480ef071808022e573bc64ad25d8',
     'BUS 1/2 effect swap: sets 0x27c[1], [2] and sends FxType 0x7f, 0x80 itself'),
    (0x80018A98, 0x80018BF0, 'ec9f5ffa5afe058a9f0772678f0724e7901e357a3fe9fc2ffec3b1dfd198715b',
     'CTRL k of an effect on a bus: stored at [system + 0xac + 4k] + (bus * 49 + effect) * 2, then sent as '
     'record 0x802e5b40[effect * 6 + k]'),
    (0x801803B0, 0x801806FC, 'e8c81d1b94c1b8a51d63b25e17389bdb734b146525c0729ee2c756a759f05856',
     'chip reset at boot: system parameters from the default table, FxType 0 for every slot, each effect\'s '
     'CTRL 1-3 defaults'),
    (0x801ABE64, 0x801ADBC8, '2552b412419b05a029ac3c34a3445c2151e213a1c90af5c038b81ecb0e4e1624',
     'per parameter ID: default, max, min (627 words each)'),
    (0x802E5B40, 0x802E5FD8, '15360131e5ea6b1f910b395eee676d0dc4f5e29e9f0f2ad0ff55d9fae6df4b08',
     'per effect: the six parameter IDs CTRL 1-6 send (-1 none)'),
    (0x80245EE4, 0x802468B0, 'bf077dd46127fc7cae924bd7ffaa07f38476802e390b2faf8b339c3c09170ea5',
     'parameter names by ID'),
    (0x8020B3D8, 0x8020B49C, '56261328da29b6e4674efa0dff96044c30839471a2c84790092652c04c6d77cd',
     'effect names by effect number (0 Bypass)'),
    # test2: the FX screen (its constructor 0x80147ba0, vtable 0x802269c0)
    (0x80147BA0, 0x80147CB4, 'c3ea681f79754525b0f4be57b4f5c139194807ce47cbbb8740b5d9f7bf529249',
     'the FX screen\'s constructor: vtable 0x802269c0, a 2000 ms timer at +0x1b10, the lit FX button at +0x1b28'),
    (0x80146E78, 0x80146FA2, 'cf449ad207f5603eb2cdb709ac64c820e8dc3d6b70e613c1835edd571c054641',
     'the FX screen\'s show method: +0x1b3f = REMAIN (0x24) held (0x80146f66), and then 0x80592320 = 1'),
    (0x80146598, 0x80146898, 'c1663cd75d50fa8ff43309fafe4176e50860188e33264345805b3cb789aec031',
     'the FX screen\'s update (every 50 ms): with +0x1b3f set, screen 2 when +0x1b40 is and the effect has CTRL '
     '4-6, and the timer is re-armed while the bus has an effect; it closes when its FX button goes off'),
    (0x801479A0, 0x801479B8, '497e921eab0fd241bcf9ccc2641abb8bc8d2501cdcd4426a6ca542aca6499251',
     'the FX screen\'s VALUE toggle: +0x1b40 ^= 1 when +0x1b3f is set'),
    (0x800CBA44, 0x800CBA4C, '24272b06222e9725f38e6ef83ce1b8b360a167ab2a56344b31a9539ed146fdd8',
     'the generic key handler\'s VALUE on the FX screen: mov r0, r1 (the screen); bl 0x801479a0'),
    (0x80183C48, 0x80183C9C, '3de29a45ebc4155e97be64b625fff9fd3ce52a7bb0eb0b4073e9b2629dce42e6',
     'TOP\'s knob handler (vtable +0xe4): CTRL k (event 9, k, position) to the bus effect path 0x800cc030'),
]
MD = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)


def sha(b):
    return hashlib.sha256(b).hexdigest()


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

    def words(self, addr, n):
        return list(struct.unpack(f'<{n}i', self.read(addr, 4 * n)))

    def cstr(self, addr):
        out = bytearray()
        while (b := self.read(addr, 1)) != b'\0':
            out += b
            addr += 1
        return out.decode('latin-1')

    def code_rows(self):
        """(address, bytes) of every copy or decompress row in the SDRAM code space."""
        for load, dst, size, fn in self.rows:
            if load and fn in (COPY, DECOMPRESS) and 0x80000000 <= dst < 0x84000000:
                yield dst, self.read(dst, size)


def bl_target(h1, h2, at):
    s = (h1 >> 10) & 1
    i1, i2 = 1 - (((h2 >> 13) & 1) ^ s), 1 - (((h2 >> 11) & 1) ^ s)
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    return at + 4 + off - ((1 << 25) if s else 0)


def branches_into(rt, lo, hi):
    """BL, B.W and literal words in the runtime code that reach [lo, hi) (Thumb bit ignored)."""
    hits = []
    for dst, b in rt.code_rows():
        for i in range(0, len(b) - 3, 2):
            h1, h2 = b[i] | b[i + 1] << 8, b[i + 2] | b[i + 3] << 8
            if (h1 & 0xF800) == 0xF000 and (h2 & 0xD000) in (0xD000, 0x9000) and \
                    lo <= bl_target(h1, h2, dst + i) < hi:
                hits.append(('bl/b.w', dst + i))
            if not i % 4 and lo <= struct.unpack_from('<I', b, i)[0] & ~1 < hi:
                hits.append(('word', dst + i))
    return hits


class Tables:
    """The firmware's parameter tables joined with fxmap.json."""

    def __init__(self, rt, fxmap):
        self.names = [rt.cstr(p & 0xFFFFFFFF) for p in rt.words(NAMES, PARAMS)]
        self.default, self.max, self.min = (rt.words(a, PARAMS) for a in (DEFAULTS, MAXIMA, MINIMA))
        self.records = {fx: rt.words(RECORDS + 24 * fx, 6) for fx in range(EFFECTS)}
        self.effect_names = [rt.cstr(p & 0xFFFFFFFF) for p in rt.words(EFFECT_NAMES, EFFECTS)]
        self.fx = {e['id']: e for e in fxmap}
        if sorted(self.fx) != list(range(1, EFFECTS)):
            raise ValueError('fxmap.json: expected effects 1..48')
        self.base = {}
        for fx, e in self.fx.items():           # the first ID of each effect's contiguous run
            first = [x for x in self.records[fx] if x >= 0][0]
            want = [p['name'] for p in e['params']]
            bases = [first - p['addr'] // 2 for p in e['params'] if p['name'] == self.names[first]]
            bases = [b for b in bases if self.names[b:b + len(want)] == want]
            if len(bases) != 1:
                raise ValueError(f'effect {fx}: no unique run of fxmap\'s names in the firmware ({bases})')
            self.base[fx] = bases[0]

    def settings(self, fx):
        """fx's parameters stock never sends: not in its knob record, no boot value in fxmap."""
        e, base, record = self.fx[fx], self.base[fx], self.records[fx]
        out = []
        for i, p in enumerate(e['params']):
            pid = base + i
            if p['addr'] != 2 * i or self.names[pid] != p['name']:
                raise ValueError(f'{e["name"]}: {p["name"]} ID {pid} does not match fxmap at {p["addr"]}')
            if (pid in record) != (p['default'] is not None):
                raise ValueError(f'{e["name"]}: {p["name"]} is in the knob record xor in the boot capture')
            if pid in record:
                continue
            lo, hi, d = self.min[pid], self.max[pid], self.default[pid]
            if not 0 <= lo <= d <= hi <= 255:
                raise ValueError(f'{e["name"]}: {p["name"]} range {lo}..{hi} default {d} is not inside 0..255')
            if len(p['name']) > NAME_LEN or not p['name'].isascii() or '"' in p['name'] or '\\' in p['name']:
                raise ValueError(f'{e["name"]}: setting name {p["name"]!r} too long or not plain')
            block = (fx - 1) * 5 + 1                 # BUS 1; BUS n is block + n - 1
            out.append(dict(id=pid, name=p['name'], aa=p['addr'], min=lo, max=hi, default=d,
                            address_bus1=f'03 {block >> 7:02x} {block & 0x7F:02x} {p["addr"]:02x}'))
        return out


def effect_label(name):
    label = name.upper()
    if len(label) > EFFECT_LEN or not label.isascii() or '"' in label or '\\' in label:
        raise ValueError(f'effect name {name!r} too long or not plain')
    return label


def header(t):
    """fx_deep_edit_tables.h: the effect and setting tables fx_deep_edit.c compiles in."""
    first, count, ids, names, rows = [], [], [], [], []
    for fx in range(EFFECTS):
        s = t.settings(fx) if fx else []
        first.append(len(ids))
        count.append(len(s))
        for p in s:
            ids.append(p['id'])
            names.append(p['name'])
        rows.append(s)
    if len(ids) > 255 or max(count) > 255:
        raise ValueError('too many settings for the u8 tables')
    labels = [''] + [effect_label(t.effect_names[fx]) for fx in range(1, EFFECTS)]
    lines = ['/* Generated by build_fx_deep_edit.py. */',
             f'#define FDE_PARAMS {len(ids)}',
             f'EXPORT const char fde_effect_names[{EFFECTS}][{EFFECT_LEN + 1}] = {{',
             *[f'    "{n}",   /* {fx} */' for fx, n in enumerate(labels)],
             '};',
             f'EXPORT const u8 fde_first[{EFFECTS}] = {{{", ".join(map(str, first))}}};',
             f'EXPORT const u8 fde_count[{EFFECTS}] = {{{", ".join(map(str, count))}}};',
             f'EXPORT const u16 fde_ids[{len(ids)}] = {{']
    for fx in range(1, EFFECTS):
        if count[fx]:
            lines.append(f'    /* {fx} {labels[fx]} */ ' + ', '.join(str(p['id']) for p in rows[fx]) + ',')
    lines.append('};')
    lines.append(f'EXPORT const char fde_names[{len(ids)}][{NAME_LEN + 1}] = {{')
    for fx in range(1, EFFECTS):
        if count[fx]:
            lines.append(f'    /* {fx} */ ' + ', '.join(f'"{p["name"]}"' for p in rows[fx]) + ',')
    lines.append('};')
    return '\n'.join(lines) + '\n', labels, rows


def movw_movt_bx(rd, value):
    """movw rd, #lo; movt rd, #hi; bx rd (10 bytes)."""
    def t3(op, imm):
        h1 = op | ((imm >> 11) & 1) << 10 | (imm >> 12) & 0xF
        h2 = ((imm >> 8) & 7) << 12 | rd << 8 | imm & 0xFF
        return struct.pack('<2H', h1, h2)
    return t3(0xF240, value & 0xFFFF) + t3(0xF2C0, value >> 16) + struct.pack('<H', 0x4700 | rd << 3)


def listing(code, at):
    return [f'{i.mnemonic} {i.op_str}' for i in MD.disasm(code, at)]


def compile_module(folder: Path, zig: Path, link_base: int, limit: int, tables_h: str):
    folder.mkdir(parents=True, exist_ok=True)
    if subprocess.check_output([str(zig), 'version'], text=True).strip() != '0.13.0':
        raise ValueError('needs Zig 0.13.0')
    (folder / 'fx_deep_edit.ld').write_text(f'''ENTRY(fde_filter)
SECTIONS {{
 . = {link_base:#x};
 .text : {{ KEEP(*(.text.fde_filter)) KEEP(*(.text.fde_dt1)) KEEP(*(.text.fde_value)) *(.text*) }}
 .rodata : ALIGN(16) {{ *(.rodata*) }}
 .data : ALIGN(16) {{ *(.data*) }}
 .bss : ALIGN(16) {{ *(.bss*) *(COMMON) }}
 /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.note*) }}
}}
''', encoding='ascii', newline='\n')
    source = folder / 'fx_deep_edit.c'             # compile LF-normalized source
    source.write_bytes((HERE / 'fx_deep_edit.c').read_bytes().replace(b'\r\n', b'\n'))
    (folder / 'fx_deep_edit_tables.h').write_text(tables_h, encoding='ascii', newline='\n')
    cache = folder / 'cache'
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache))
    # -g only keeps the symbol table: Zig's -Os (ReleaseSmall) strips it otherwise. Same code.
    subprocess.run([str(zig), 'cc', '-target', 'thumb-freestanding-eabihf', '-mcpu=cortex_m7+vfp4d16',
                    '-mfloat-abi=hard', '-Os', '-g', '-ffunction-sections', '-fdata-sections', '-nostdlib',
                    '-fno-builtin', '-Wall', '-Werror', '-Wl,--no-undefined', '-Wl,--build-id=none',
                    '-Wl,-e,fde_filter', '-Wl,-T,' + str(folder / 'fx_deep_edit.ld'), '-I', str(folder),
                    str(source), '-o', str(folder / 'fx_deep_edit.elf')], check=True, env=env)
    code, symbols = read_module((folder / 'fx_deep_edit.elf').read_bytes(), link_base, limit)
    missing = [n for n in EXPORTS if n not in symbols]
    if missing:
        raise ValueError(f'module exports missing: {missing}')
    return code, {n: symbols[n] for n in EXPORTS}, sha(source.read_bytes()), sha(tables_h.encode('ascii'))


def build(inp: Path, out: Path, zig: Path, fxmap_path: Path, base: int, build_dir: Path = None):
    img = bytearray(inp.read_bytes())
    app0 = inp.with_name('SP404MKII_APP0.bin')
    if sha(app0.read_bytes()) != APP0_SHA:
        raise ValueError('expected stock APP0 beside the input APP1')
    for name in ('SP404MKII_APP1.bin', 'SP404MKII_APP0.bin', 'manifest.json'):
        if (out / name).exists():
            raise ValueError(f'refusing to overwrite {out / name}')
    if base & 0xFFF or base < 0x83FC9000 or base + SLOT > SLOT_CEILING:
        raise ValueError(f'the slot must be 4 KB aligned in the free SDRAM gap, below {SLOT_CEILING:#x}')
    rows = scatter(img)
    rt = Runtime(img)
    for start, end, digest, what in GUARDS:
        if sha(rt.read(start, end - start)) != digest:
            raise ValueError(f'{start:#x}..{end:#x} differs from stock 5.52 ({what})')
    if struct.unpack('<I', rt.read(VTABLE_SLOT, 4))[0] != DOOM_FILTER:
        raise ValueError(f'{VTABLE_SLOT:#x}: expected DOOM OS\'s page filter {DOOM_FILTER:#x}')
    if rt.read(DT1, len(DT1_HEAD)) != DT1_HEAD:
        raise ValueError(f'{DT1:#x}: expected the stock builder\'s first ten bytes')
    inside = branches_into(rt, DT1 + 1, DT1 + len(DT1_HEAD)) + refs_into(bytes(img), DT1 + 1, DT1 + len(DT1_HEAD))
    if inside:
        raise ValueError(f'something reaches into the builder\'s first ten bytes: {inside[:4]}')
    if rt.read(TOGGLE, len(TOGGLE_HEAD)) != TOGGLE_HEAD:
        raise ValueError('expected the FX screen\'s VALUE toggle')
    inside = branches_into(rt, TOGGLE + 1, TOGGLE + len(TOGGLE_HEAD)) + \
        [h for h in refs_into(bytes(img), TOGGLE + 1, TOGGLE + len(TOGGLE_HEAD))]
    if inside:
        raise ValueError(f'something reaches into the VALUE toggle\'s first ten bytes: {inside[:4]}')
    for load, dst, n, fn in rows:
        if max(dst, base) < min(dst + n, base + SLOT):
            raise ValueError(f'row {dst:#x}+{n:#x} overlaps the slot {base:#x}..{base + SLOT:#x}')
    hits = refs_into(bytes(img), base, base + SLOT)
    if hits:
        raise ValueError(f'input refers to the slot: {hits[:4]}')

    fxmap_bytes = fxmap_path.read_bytes()
    tables = Tables(rt, json.loads(fxmap_bytes))
    tables_h, labels, settings = header(tables)
    folder = build_dir or out / 'build'
    module, symbols, source_sha, tables_sha = compile_module(folder, zig, base, base + SLOT, tables_h)
    if len(module) > SLOT:
        raise ValueError(f'module ({len(module)} bytes) exceeds the slot')
    for name in ('fde_filter', 'fde_dt1', 'fde_dt1_stock', 'fde_dt1_fxtype', 'fde_value'):
        if not symbols[name] & 1:
            raise ValueError(f'{name} is not a Thumb function symbol')
    stock = module[(symbols['fde_dt1_stock'] & ~1) - base:][:len(DT1_HEAD) + 10]
    if stock != DT1_HEAD + movw_movt_bx(12, DT1_BODY | 1):
        raise ValueError(f'fde_dt1_stock is not the builder\'s first ten bytes and a jump to {DT1_BODY:#x}: '
                         f'{listing(stock, symbols["fde_dt1_stock"] & ~1)}')
    at = symbols['fde_dt1'] & ~1
    entry = listing(module[at - base:at - base + 16], at)
    if entry != ['sub.w ip, r1, #0x7f', 'cmp.w ip, #3', f'bhi.w #{symbols["fde_dt1_stock"] & ~1:#x}',
                 f'b.w #{symbols["fde_dt1_fxtype"] & ~1:#x}']:
        raise ValueError(f'fde_dt1 is not the four-instruction switch: {entry}')

    patches = []
    off = file_offset(img, VTABLE_SLOT, 4)
    original = bytes(img[off:off + 4])
    replacement = struct.pack('<I', symbols['fde_filter'])
    img[off:off + 4] = replacement
    patches.append(dict(address=VTABLE_SLOT, size=4, original_hex=original.hex(), replacement_hex=replacement.hex(),
                        what='TOP page vtable 0x8022ce5c +8: DOOM OS\'s filter -> fde_filter (which passes on to it)'))
    off = file_offset(img, DT1, len(DT1_HEAD))
    jump = movw_movt_bx(12, symbols['fde_dt1'])
    img[off:off + len(DT1_HEAD)] = jump
    patches.append(dict(address=DT1, size=len(DT1_HEAD), original_hex=DT1_HEAD.hex(), replacement_hex=jump.hex(),
                        what='DT1 builder entry: push.w / sub sp / movw sb -> movw ip / movt ip / bx ip to fde_dt1 '
                             '(fde_dt1_stock runs the three and goes on at 0x800d8122)',
                        listing=listing(jump, DT1)))
    off = file_offset(img, TOGGLE, len(TOGGLE_HEAD))
    toggle = movw_movt_bx(12, symbols['fde_value'])
    img[off:off + len(TOGGLE_HEAD)] = toggle
    patches.append(dict(address=TOGGLE, size=len(TOGGLE_HEAD), original_hex=TOGGLE_HEAD.hex(),
                        replacement_hex=toggle.hex(), what='the FX screen\'s VALUE toggle: movw / ldrb / cmp / it -> '
                        'movw ip / movt ip / bx ip to fde_value', listing=listing(toggle, TOGGLE)))
    file_at = (len(img) + 15) & ~15
    img += bytes(file_at - len(img)) + module
    table = (len(img) + 15) & ~15
    img += bytes(table - len(img))
    for row in rows + [[FLASH + file_at, base, len(module), COPY]]:
        img += struct.pack('<4I', *row)
    struct.pack_into('<2I', img, 0x80, table - 0x80, len(img) - 0x80)
    after = Runtime(img)
    if after.read(base, len(module)) != module or after.read(DT1, len(jump)) != jump or \
            after.read(TOGGLE, len(toggle)) != toggle:
        raise ValueError('the new image does not reproduce the module and the patches')

    out.mkdir(parents=True, exist_ok=True)
    (out / 'SP404MKII_APP1.bin').write_bytes(img)
    shutil.copy2(app0, out / 'SP404MKII_APP0.bin')
    parent_manifest = inp.with_name('manifest.json')
    effects = [dict(effect=fx, name=labels[fx], fxmap_name=tables.fx[fx]['name'],
                    first=sum(len(settings[k]) for k in range(1, fx)), settings=settings[fx])
               for fx in range(1, EFFECTS)]
    manifest = dict(
        revision=REVISION, status='hardware-unverified', published=False,
        description='on the FX screen REMAIN + FX opens (stock\'s screen that stays), VALUE steps its screens: 1, 2 '
                    '(CTRL 4-6), then extra screens with three each of the effect\'s parameters stock never sends to '
                    'the effects chip (BMC) on CTRL 1-3, for the bus the CTRL knobs drive; values live in RAM per bus '
                    'and effect and are sent again after every FxType write for that bus; an FX button alone is '
                    'stock (test3: test2\'s hold kept MFX\'s effect choice away)',
        parent_app1=str(inp), parent_sha256=sha(inp.read_bytes()),
        parent_revision=json.loads(parent_manifest.read_text(encoding='utf-8')).get('revision')
        if parent_manifest.exists() else None,
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        slot=[base, base + SLOT], blob_base=base, blob_file_offset=file_at, blob_size=len(module),
        blob_sha256=sha(module), source='synth/fx_deep_edit.c', source_sha256=source_sha,
        tables_header_sha256=tables_sha, compiler='zig 0.13.0 cc -Os', entries=symbols,
        patches=patches,
        guards=[dict(start=s, end=e, sha256=d, establishes=w) for s, e, d, w in GUARDS],
        fxmap=dict(path=str(fxmap_path), sha256=sha(fxmap_bytes),
                   note='DM-404 core/fx/fxmap.json (MIT): bases from a boot capture, knob ranges from a sweep'),
        screens=dict(fx_button='an FX button alone is stock (the screen closes after 2 s); REMAIN + FX shows the '
                                'screen that stays (+0x1b3f set) while the bus has an effect, until EXIT, REMAIN or '
                                'that FX button again: the screen the extra screens are on',
                     value='VALUE press: screen 1, screen 2 where the effect has CTRL 4-6 (stock\'s +0x1b40), the '
                           'extra screens, screen 1 again',
                     bus='settings 0x3a (0 input FX, 1-4 BUS 1-4), what TOP\'s knob path 0x800cc030 uses; extra '
                         'screens on BUS 1-4 only',
                     effect='system 0x27c[bus] (0 none), what the knob path checks',
                     knobs='on an extra screen CTRL k (event 9, k, 0..127) sets its setting across the firmware\'s '
                           'min/max (min + ((max - min) x position + 63) / 127); a change is one DT1 (ID, slot = bus)',
                     leave='on an extra screen any button but VALUE and SHIFT leaves it (the popup goes) and goes on '
                           'as usual; pads go on as usual',
                     popup='"TAPE ECHO 3/5\nC1 SYNC 0\nC2 BASS 15\nC3 TREBLE 15" for 600 s, gone at once on leaving'),
        resend='after the firmware sends FxType 0x7f..0x82 (BUS 1-4) = fx, the edited values of that bus for fx go '
               'out again, in table order; nothing else adds a frame',
        settings_total=sum(len(s) for s in settings), effects=effects,
        dt1='F0 41 10 00 00 00 00 08 12 a1 a2 a3 a4 hi lo sum F7 via the stock builder 0x800d8118 (link '
            '0x80592500, ID, slot, value): packets 04 F0 41 10 / 04 00 00 00 / 04 00 08 12 / 04 a1 a2 a3 / '
            '04 a4 hi lo / 06 sum F7 xx (xx: whatever the stock packet buffer held)',
        tool='synth/build_fx_deep_edit.py')
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
    ap.add_argument('--fxmap', type=Path, required=True)
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0x83FE2000)
    ap.add_argument('--build-dir', type=Path)
    a = ap.parse_args()
    m = build(a.app1.resolve(), a.out.resolve(), a.zig.resolve(), a.fxmap.resolve(), a.base,
              a.build_dir.resolve() if a.build_dir else None)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size', 'blob_base', 'blob_size', 'settings_total')},
                     indent=1))


if __name__ == '__main__':
    main()
