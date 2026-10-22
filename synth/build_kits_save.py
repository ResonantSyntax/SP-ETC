"""Kits save (hardware test build): the drum-mode kit edits saved with the project, on the published v9.46.

A stage on Sound Generator + Kits v9.46 (APP1 7b5fbcb4...684a; KITS_SAVE.md). The kit edits (every pad of the 13
kits, the current kit, M.CH, ARP / RATE / A.OCT / HOLD, ENV, SCALE) go into SG_KITS.BIN in the project's folder
beside PADCONF.BIN, are read when the project loads and written by the stock save path, so each project keeps its
own kits. Stock firmware never opens the file.

Two 5.52 entries jump to the module (movw ip / movt ip / bx ip, a nop after it where the displaced instructions
take 12 bytes); the module runs the displaced instructions and goes on:
- 0x800cf218 PADCONF save (push.w / sub sp / mov / mov) -> ks_save_entry, on at 0x800cf222;
- 0x8018ae68 PADCONF load (push.w / sub sp / str / movw) -> ks_load_entry, on at 0x8018ae74.
Two words of the Sound Generator page's vtable (0x802295a8) change:
- +0x04 (0x802295ac) the deleting destructor 0x8015cef9 -> ks_sg_leave, which goes on to it;
- +0xd0 (0x80229678) the screen update, the kits' kit_ui_poll 0x83fa7485 -> ks_sg_poll, which calls it first.
Stock code and data the module calls, reads or relies on are checked byte for byte (GUARDS), the kits module as a
whole (its addresses below, exported or not, are v9.46's). The module (Zig 0.13.0, -Os) goes in a new boot copy
row in an 8 KB slot at 0x83FD5000, below the planned chromatic-mode module (0x83FD7000) and pad envelopes stage 2
(0x83FD9000), taken from the top of the room pad FX was given (0x83FC9000-0x83FD5000 stays its own, 48 KB); the
builder checks that no row and no other fork module's slot overlaps it and that nothing in the input refers to it.

usage: python synth/build_kits_save.py IN_APP1 OUT_DIR --zig ZIG [--base 0x83FD5000] [--build-dir DIR]
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
FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
APP0_SHA = '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23'
REVISION = 'kits-save-test2'
SLOT = 0x2000                       # reserved: [base, base + SLOT)
GAP = (0x83FC9000, 0x83FF0000)      # above the fork's rows (end 0x83FC8450), below the end of cacheable SDRAM
# Every other fork module's reserved RAM (branch, start, end).
KNOWN_SLOTS = [
    ('pad FX (planned)', 0x83FC9000, 0x83FD5000),
    ('chromatic mode (planned, the pad envelopes session)', 0x83FD7000, 0x83FD9000),
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
# The kits module of v9.46 (arp + kits, 0x83fa2000-0x83fc8450; its runtime bytes are guarded below). Exported names
# are in v9.46's kits manifest; kit_last_mode and kit_init_pads are static, found in the code (KIT_STATICS).
KITS = dict(kit_pads=0x83FBFCC0, kit_pads_ready=0x83FC0340, kit_mode=0x83FC58E0, kit_last_mode=0x83FC58D1,
            kit_midi_channel=0x83FBFCBC, kit_edit_changed=0x83FC59A2, kit_bounce_state=0x83FC7E3A,
            arp_mode=0x83FC7B70, arp_rate=0x83FBFCB0, arp_oct=0x83FC7B74, arp_hold=0x83FC7B78, arp_dirty=0x83FC7B80,
            held_count=0x83FC7B84, down_count=0x83FC7B88, kit_init_pads=0x83FA7F85, kit_ui_poll=0x83FA7485)
# Where the statics are established: (address, listing, what).
KIT_STATICS = [
    (0x83FA8156, ['movw r7, #0x58e0', 'movw sb, #0x58d1', 'movt r7, #0x83fc', 'movt sb, #0x83fc', 'ldrb r0, [r7]',
                  'cbz r0, #0x83fa8170', 'ldrb r0, [r7]', 'strb.w r0, [sb]'],
     'kit_shortcut_select: if (kit_mode) kit_last_mode = kit_mode (kit_mode 0x83fc58e0, kit_last_mode 0x83fc58d1)'),
    (0x83FA7F50, ['push {r7, lr}', 'bl #0x83fa7f84'], 'kit_edit calls kit_init_pads (0x83fa7f84) first'),
    (0x83FA7F84, ['ldr r0, [pc, #0x16c]', 'ldrb r0, [r0]', 'cbz r0, #0x83fa7f8c', 'bx lr',
                  'push.w {r4, r5, r6, r7, r8, sb, sl, fp, lr}'],
     'kit_init_pads: returns at once while kit_pads_ready (its literal) is set'),
]
KIT_INIT_LITERAL = (0x83FA80F4, 0x83FC0340)     # kit_init_pads' literal: kit_pads_ready
# The power-on values a project without a file gets (file order: kit, M.CH, ARP, RATE, A.OCT, HOLD, ENV, SCALE),
# read from the parent's boot image: (address, size, what).
DEFAULTS = [(0x83FC58D1, 1, 'kit_last_mode'), (0x83FBFCBC, 1, 'kit_midi_channel'), (0x83FC7B70, 4, 'arp_mode'),
            (0x83FBFCB0, 4, 'arp_rate'), (0x83FC7B74, 4, 'arp_oct'), (0x83FC7B78, 4, 'arp_hold'),
            (0x80249810, 4, 'ENV: the SG singleton + 0x10'), (0x80591C54, 4, 'SCALE: the keyboard state + 0xc')]
EXPECTED_DEFAULTS = [1, 15, 0, 4, 0, 0, 4, 0]
EXPORTS = ('ks_save_entry', 'ks_load_entry', 'ks_save_c', 'ks_load_c', 'ks_sg_poll', 'ks_sg_leave', 'ks_path',
           'ks_seen', 'ks_file_ok', 'ks_buf', 'ks_busy', 'ks_pending', 'ks_pending_age', 'ks_quiet', 'ks_last_hash',
           'ks_loads', 'ks_defaults', 'ks_writes', 'ks_errors', 'ks_posts', 'ks_skips', 'ks_refused', 'ks_arp_other',
           'ks_arp_drum', 'ks_power_on', 'ks_power_on_taken')
ENTRIES = ('ks_save_entry', 'ks_load_entry', 'ks_sg_poll', 'ks_sg_leave')
# (address, the bytes there in the parent, what they are, the entry symbol, where the module's copy goes on)
SITES = [
    (0x800CF218, bytes.fromhex('2de9f04fe7b00c468146'),
     'PADCONF save (CSmplPrm, project or -1): push.w {r4-r11, lr}; sub sp, #0x19c; mov r4, r1; mov sb, r0',
     'ks_save_entry', 0x800CF222),
    (0x8018AE68, bytes.fromhex('2de9f04fd5b009914cf23142'),
     'PADCONF load (CSmplPrm, flag): push.w {r4-r11, lr}; sub sp, #0x154; str r1, [sp, #0x24]; movw r2, #0xc431',
     'ks_load_entry', 0x8018AE74),
]
# (address, the word there in the parent, the entry that replaces it, what)
VTABLE = [
    (0x802295AC, 0x8015CEF9, 'ks_sg_leave', 'SG page vtable 0x802295a8 +0x04: deleting destructor, the page closes'),
    (0x80229678, 0x83FA7485, 'ks_sg_poll', 'SG page vtable +0xd0: screen update, the kits\' kit_ui_poll (v9.46)'),
]
# Return addresses the module recognises, and the instruction at each call (its bytes are checked too).
CALLERS = {
    0x8004E2E9: (0x8004E2DE, bytes.fromhex('a168c8f2e22080f098ff'),
                 'ldr r1, [r4, #8]; movt r0, #0x82e2; bl 0x800cf218: SMPL TASK\'s command 0xd, r4 = the command'),
}
# Where each entry's own copy of the displaced instructions sits in the module, and what it must be.
DISPLACED = {
    'ks_save_entry': ['push.w {r4, r5, r6, r7, r8, sb, sl, fp, lr}', 'sub sp, #0x19c', 'mov r4, r1', 'mov sb, r0',
                      'movw ip, #0xf223', 'movt ip, #0x800c', 'bx ip'],
    'ks_load_entry': ['push.w {r4, r5, r6, r7, r8, sb, sl, fp, lr}', 'sub sp, #0x154', 'str r1, [sp, #0x24]',
                      'movw r2, #0xc431', 'movw ip, #0xae75', 'movt ip, #0x8018', 'bx ip'],
}

# Stock 5.52 code and data the module calls, reads or relies on, and the kits module, as in v9.46:
# (start, end, SHA-256, what).
GUARDS = [
    (0x800CF018, 0x800CF090, 'f49c3e794f954512757ad50cc970d022f197fc621481080b19928d4380f3a6d4',
     'PADCONF path (out, project; >= 0x80: pad parameter 0x81): "B:/ROLAND/SP-404MKII/PROJECT_%02d" (settings 0x84 '
     '= 0) or "A:/EXPORT/PROJECT/PROJECT_%02d", then "/PADCONF.BIN"'),
    (0x800CF218, 0x800CF7E8, 'b2eaacfc3635aa50fef60dd2d2c604a995232430968c5a0054aaf09f794eb501',
     'PADCONF save (CSmplPrm, project or -1 = the current one): nothing when the project has no PADCONF.BIN and no '
     'content (0x80188d08) and CSmplPrm +0x1c (Edited) is clear; else the file through 0x800cf018, Edited = 0, '
     '+0x20 = -1'),
    (0x8018AE68, 0x8018AEB4, 'f004af52c29baf0c061e16322950253420c0788e094cf7e59c3a70141bc0b3e2',
     'PADCONF load: the current project\'s file (0x800e1190 through 0x800cf018)'),
    (0x800E1190, 0x800E119C, '7192eb2e5832025b130a53e2243f2d0cce1450d90695112d8ba5618420a11e91',
     'the current project: [0x805923fc]'),
    (0x800DEC48, 0x800DEC74, '4c47643ec8919640e6d5e25d52995230bcb2544ac00915fb0b4f3a6c79718504',
     'file read (fd, buf, n) and open (path, flags: 0 read, 0x601 write, create, truncate) on the file table'),
    (0x800DEBD8, 0x800DEC48, '22abec76d1aba2f98baf9ba58a4383d2075417a6d981e86b791054dccef5d6bf', 'file close (fd)'),
    (0x800DD9B8, 0x800DD9F8, 'd204acf3596d8eab1eca7a6d4e1cf2aec6429890e0b05a88ed1357982cda0fb6',
     'file write (fd, buf, n): bytes written'),
    (0x800E25C0, 0x800E26D0, 'c4a456143fe8201ffa722a3533cb40d3195e94b93472e9bafc9c24535d344027',
     'post a command to SMPL TASK (0xd: a2 becomes the current project; the queue put)'),
    (0x8004D8B8, 0x8004D8DA, 'e3ebf0eb8af88ced3241a9bf2f7c19205bed5e72612afe1fbfdb2b1f3cea0bbf',
     'SMPL TASK\'s command dispatcher: r4 = the command, by its number through the table'),
    (0x8004D8DA, 0x8004E116, '8783619d571a4412cb7c170d8302e3cfb88acd46d742e240289140a6cafed10a',
     'the dispatcher\'s table (0xd -> 0x8004e2da)'),
    (0x8004E2DA, 0x8004E2F4, '8eb2648246523c32600a4fb97d9f90b1d7f78da08c45e7feb3bbff6ef546bedd',
     'command 0xd: the PADCONF save (CSmplPrm, a2) from 0x8004e2e4; a1 = 0 also tells the UI (event 9)'),
    (0x800D31EE, 0x800D31F6, 'f7e44370e66fb17d7783db4af3abbb79b146f19ae1628f5c78e2b1527451361b', 'task delay (ms)'),
    (0x800DED08, 0x800DED10, 'ffcbc8edad34b23182e990f8733592c4c95b2b0cf82eb7abc18d40bc6c08e42c', 'dispatch off'),
    (0x800DECF8, 0x800DED00, '65aeec5f117743c49a436e763383bdcba60386f460a6976da18c512c7c34eb8c', 'dispatch on'),
    (0x8015CEF8, 0x8015CF06, '43e82026d44db5972380f40357ec8230324211e916e48d38a7139bc31878510b',
     'the SG page\'s deleting destructor: the page object\'s destructor, then free'),
    (0x80019E30, 0x8001A010, '89c6ffbcb80faef2613f9ab62cc07e55c8497e5ec81dd58cd88bb373f4b260ca',
     'SG settings store: settings 0x82 (ENV) is the singleton\'s +0x10'),
    (0x80132658, 0x801326F8, 'd4c6206ca24415d905b1376630d2302f48691d45b71e953bf8f94cf1c80f5f04',
     'SG settings ranges: ENV 0..9'),
    (0x8015C80C, 0x8015C834, 'a1ad1822eb2fe451fa13a3fc080d74bb6703848a7b826b65b102599142acf309',
     'SG VALUE turned left on SCALE: keyboard +0xc down to the project parameter 0xf1\'s minimum'),
    (0x8015C874, 0x8015C89C, 'cb8801e684693e44e464a44715bb20cf61718f921bf264a6ac1bc860bc54196a',
     'SG VALUE turned right on SCALE: up to its maximum'),
    (0x83FA1000, 0x83FA17EC, '3c672952dc3b23c7a418b8344e790cfcfa3d9121847b148340ad54c9205457ec',
     'the scales module (v9.6): 34 scales, 0..33 on the SG page'),
    (0x83FA2000, 0x83FC8450, '666e86b2e139224bb9dfc3f8f343088ccc059a8c2b5a6d3588fb38430ef5b16a',
     'the kits module of v9.46 as booted (code, data, zeroed bss): every address in KITS'),
    # test2: the Sound Generator's own settings
    (0x800D94D8, 0x800D9500, '6b743b722b0f3cd7d65a7221a09cbd73b81c6ae7d60eeafadaad2b5fa3defd02',
     'the settings getter (settings, id, 0) and its switch'),
    (0x800DD0C0, 0x800DD0FE, '3c8032e5d7667f63a2cd8e9025fbcfb0bbfdb35bbfd74c20ca4707bbe141e46b',
     'the settings setter (settings, id, value, 0): clamped to the range (vtable +0x1c), then by id'),
    (0x800DD0FE, 0x800DD258, 'cdf07b82ec6fb6befe1e3b3d033104d8357a2226415a8b8b0ce5cc9be7b8d8e4',
     'the setter\'s switch table (ids 0x7b..0x82: the SG settings store, which gives the voices the value too)'),
    (0x8015CBCC, 0x8015CCF4, '7b2904394d773686b94866053bf280327f3ac9962baa89340bf782fc70526829',
     'SG VALUE menu: NOTE keyboard +0x10 within project parameter 0xf2\'s range, OCT +0x4 -3..4, OFST +0x8 -4..11, '
     'ENV and TUNE settings 0x82, 0x81'),
    (0x8015CE08, 0x8015CE9E, '2dd8c0925a24fc7c1fe22798cea4771c87285d494a45763b896026633a3a7616',
     'SG knobs: CTRL 1-3 TYPE 0x7b, FREQ 0x7c, LEVEL 0x7d; with SHIFT Pad Length 0x7e, DUTY 0x7f, BALANCE 0x80'),
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
    """Runtime bytes of an APP1 image, as its scatter loader leaves them (copy, decompress and zero rows; a later row
    over an earlier one wins)."""

    def __init__(self, img):
        self.img, self.rows, self.cache = bytes(img), scatter(img), {}

    def row(self, k):
        load, dst, size, fn = self.rows[k]
        if k not in self.cache:
            if fn == COPY:
                self.cache[k] = self.img[load - FLASH:load - FLASH + size]
            elif fn == DECOMPRESS:
                self.cache[k] = decompress(self.img[load - FLASH:], size)
            elif fn == ZERO:
                self.cache[k] = bytes(size)
            else:
                raise ValueError(f'unknown scatter handler {fn:#x}')
        return self.cache[k]

    def read(self, addr, n):
        out, have = bytearray(n), bytearray(n)
        for k in range(len(self.rows) - 1, -1, -1):
            load, dst, size, fn = self.rows[k]
            lo, hi = max(addr, dst), min(addr + n, dst + size)
            if lo >= hi:
                continue
            data = self.row(k)
            for a in range(lo, hi):
                if not have[a - addr]:
                    out[a - addr] = data[a - dst]
                    have[a - addr] = 1
        if not all(have):
            raise ValueError(f'{addr:#x}+{n:#x} is not all set by the scatter rows')
        return bytes(out)

    def code_rows(self):
        """(address, bytes) of every copy or decompress row in the SDRAM code space."""
        for k, (load, dst, size, fn) in enumerate(self.rows):
            if load and fn in (COPY, DECOMPRESS) and 0x80000000 <= dst < 0x84000000:
                yield dst, self.row(k)


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


def movw_movt_bx(rd, value):
    """movw rd, #lo; movt rd, #hi; bx rd (10 bytes)."""
    def t3(op, imm):
        h1 = op | ((imm >> 11) & 1) << 10 | (imm >> 12) & 0xF
        h2 = ((imm >> 8) & 7) << 12 | rd << 8 | imm & 0xFF
        return struct.pack('<2H', h1, h2)
    return t3(0xF240, value & 0xFFFF) + t3(0xF2C0, value >> 16) + struct.pack('<H', 0x4700 | rd << 3)


def listing(code, at):
    return [f'{i.mnemonic} {i.op_str}'.strip() for i in MD.disasm(code, at)]


def links_header(defaults):
    lines = [f'#define KS_{name.upper()} {value:#x}u' for name, value in KITS.items()]
    lines.append('#define KS_DEFAULT_TAIL {' + ', '.join(str(v & 0xFF) for v in defaults) + '}')
    lines.append('#define KS_DEFAULT_ARP ' + ', '.join(str(v) for v in defaults[2:6]))      # ARP, RATE, A.OCT, HOLD
    return '/* written by build_kits_save.py: the kits module of v9.46 */\n' + '\n'.join(lines) + '\n'


def compile_module(folder: Path, zig: Path, link_base: int, limit: int, defaults):
    folder.mkdir(parents=True, exist_ok=True)
    if subprocess.check_output([str(zig), 'version'], text=True).strip() != '0.13.0':
        raise ValueError('needs Zig 0.13.0')
    (folder / 'ks_links.h').write_text(links_header(defaults), encoding='ascii', newline='\n')
    keep = ' '.join(f'KEEP(*(.text.{n}))' for n in ENTRIES)
    (folder / 'kits_save.ld').write_text(f'''ENTRY(ks_save_entry)
SECTIONS {{
 . = {link_base:#x};
 .text : {{ {keep} *(.text*) }}
 .rodata : ALIGN(16) {{ *(.rodata*) }}
 .data : ALIGN(16) {{ *(.data*) }}
 .bss : ALIGN(16) {{ *(.bss*) *(COMMON) }}
 /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.note*) }}
}}
''', encoding='ascii', newline='\n')
    source = folder / 'kits_save.c'             # compile LF-normalized source
    source.write_bytes((HERE / 'kits_save.c').read_bytes().replace(b'\r\n', b'\n'))
    cache = folder / 'cache'
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache))
    # -g only keeps the symbol table: Zig's -Os (ReleaseSmall) strips it otherwise. Same code. --no-gc-sections
    # keeps every exported variable, also one only the tests read.
    subprocess.run([str(zig), 'cc', '-target', 'thumb-freestanding-eabihf', '-mcpu=cortex_m7+vfp4d16',
                    '-mfloat-abi=hard', '-Os', '-g', '-ffunction-sections', '-fdata-sections', '-nostdlib',
                    '-fno-builtin', '-Wall', '-Werror', '-Wl,--no-undefined', '-Wl,--build-id=none',
                    '-Wl,--no-gc-sections',
                    '-I', str(folder), '-Wl,-e,ks_save_entry', '-Wl,-T,' + str(folder / 'kits_save.ld'),
                    str(source), '-o', str(folder / 'kits_save.elf')], check=True, env=env)
    code, symbols = read_module((folder / 'kits_save.elf').read_bytes(), link_base, limit)
    missing = [n for n in EXPORTS if n not in symbols]
    if missing:
        raise ValueError(f'module exports missing: {missing}')
    return code, {n: symbols[n] for n in EXPORTS}, sha(source.read_bytes())


def check_module(module, symbols, base):
    """The entries are Thumb functions; each copy of displaced instructions is exactly them, then the jump on."""
    for name in ENTRIES:
        if not symbols[name] & 1:
            raise ValueError(f'{name} is not a Thumb function symbol')
    at = symbols['ks_save_entry'] & ~1
    ins = list(MD.disasm(module[at - base:at - base + 64], at))[:16]
    save = [f'{i.mnemonic} {i.op_str}'.strip() for i in ins]
    head = ['push {r0, r1, r2, r3, r4, lr}', 'mov r2, lr', 'mov r3, r4', f'bl #{symbols["ks_save_c"] & ~1:#x}',
            'cmp r0, #0', 'pop.w {r0, r1, r2, r3, r4, lr}', f'bne #{ins[14].address:#x}']
    if len(ins) < 16 or save[:7] != head or save[7:14] != DISPLACED['ks_save_entry'] or \
            save[14:16] != ['movs r0, #0', 'bx lr']:
        raise ValueError(f'ks_save_entry: unexpected code {save}')
    at = symbols['ks_load_entry'] & ~1
    load = listing(module[at - base:at - base + 48], at)
    if load[:3] != ['push {r0, r1, r2, r3, r4, lr}', f'bl #{symbols["ks_load_c"] & ~1:#x}',
                    'pop.w {r0, r1, r2, r3, r4, lr}'] or load[3:10] != DISPLACED['ks_load_entry']:
        raise ValueError(f'ks_load_entry: unexpected code {load[:10]}')
    return dict(ks_save_entry=save[:16], ks_load_entry=load[:10])


def parent_defaults(rt):
    values = []
    for (addr, size, what), want in zip(DEFAULTS, EXPECTED_DEFAULTS):
        v = int.from_bytes(rt.read(addr, size), 'little', signed=True)
        if v != want:
            raise ValueError(f'{what} at {addr:#x} is {v} at power-on, expected {want}')
        values.append(v)
    return values


def build(inp: Path, out: Path, zig: Path, base: int, build_dir: Path = None):
    img = bytearray(inp.read_bytes())
    app0 = inp.with_name('SP404MKII_APP0.bin')
    if sha(app0.read_bytes()) != APP0_SHA:
        raise ValueError('expected stock APP0 beside the input APP1')
    for name in ('SP404MKII_APP1.bin', 'SP404MKII_APP0.bin', 'manifest.json'):
        if (out / name).exists():
            raise ValueError(f'refusing to overwrite {out / name}')
    if base & 0xFFF or base < GAP[0] or base + SLOT > GAP[1]:
        raise ValueError(f'the slot must be 4 KB aligned inside {GAP[0]:#x}..{GAP[1]:#x}')
    for what, lo, hi in KNOWN_SLOTS:
        if max(lo, base) < min(hi, base + SLOT):
            raise ValueError(f'the slot {base:#x}..{base + SLOT:#x} overlaps {what} ({lo:#x}..{hi:#x})')
    rows = scatter(img)
    rt = Runtime(img)
    for start, end, digest, what in GUARDS:
        if sha(rt.read(start, end - start)) != digest:
            raise ValueError(f'{start:#x}..{end:#x} differs from what the module relies on ({what})')
    for at, want, what in KIT_STATICS:
        got = listing(rt.read(at, 4 * len(want) + 4), at)[:len(want)]
        if got != want:
            raise ValueError(f'{at:#x}: expected {what}: {got}')
    if struct.unpack('<I', rt.read(KIT_INIT_LITERAL[0], 4))[0] != KIT_INIT_LITERAL[1]:
        raise ValueError('kit_init_pads does not test kit_pads_ready')
    defaults = parent_defaults(rt)
    for addr, original, what, entry, _ in SITES:
        if rt.read(addr, len(original)) != original:
            raise ValueError(f'{addr:#x}: expected {what}')
        # the entry itself (addr | 1 for code pointers) may be called; nothing may land inside
        inside = branches_into(rt, addr + 1, addr + len(original)) + refs_into(bytes(img), addr + 2, addr + len(original))
        if inside:
            raise ValueError(f'something reaches into {addr:#x}..{addr + len(original):#x}: {inside[:4]}')
    for addr, old, entry, what in VTABLE:
        if struct.unpack('<I', rt.read(addr, 4))[0] != old:
            raise ValueError(f'{addr:#x}: expected {old:#x} ({what})')
    for lr, (at, original, what) in CALLERS.items():
        if rt.read(at, len(original)) != original or at + len(original) + 1 != lr:
            raise ValueError(f'{at:#x}: expected {what}')
    for load, dst, n, fn in rows:
        if max(dst, base) < min(dst + n, base + SLOT):
            raise ValueError(f'row {dst:#x}+{n:#x} overlaps the slot {base:#x}..{base + SLOT:#x}')
    hits = refs_into(bytes(img), base, base + SLOT)
    if hits:
        raise ValueError(f'input refers to the slot: {hits[:4]}')

    folder = build_dir or out / 'build'
    module, symbols, source_sha = compile_module(folder, zig, base, base + SLOT, defaults)
    if len(module) > SLOT:
        raise ValueError(f'module ({len(module)} bytes) exceeds the slot')
    bridges = check_module(module, symbols, base)

    patches = []
    for addr, original, what, entry, back in SITES:
        jump = movw_movt_bx(12, symbols[entry])
        new = jump + bytes.fromhex('00bf') * ((len(original) - len(jump)) // 2)
        off = file_offset(img, addr, len(original))
        img[off:off + len(original)] = new
        patches.append(dict(address=addr, size=len(original), original_hex=original.hex(), replacement_hex=new.hex(),
                            what=what, entry=entry, goes_on_at=back, listing=listing(new, addr)))
    for addr, old, entry, what in VTABLE:
        off = file_offset(img, addr, 4)
        new = struct.pack('<I', symbols[entry])
        img[off:off + 4] = new
        patches.append(dict(address=addr, size=4, original_hex=struct.pack('<I', old).hex(), replacement_hex=new.hex(),
                            what=what, entry=entry))
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
            raise ValueError(f'the new image does not hold the patch at {p["address"]:#x}')

    out.mkdir(parents=True, exist_ok=True)
    (out / 'SP404MKII_APP1.bin').write_bytes(img)
    shutil.copy2(app0, out / 'SP404MKII_APP0.bin')
    parent_manifest = inp.with_name('manifest.json')
    manifest = dict(
        revision=REVISION, status='hardware-unverified', published=False,
        description='The drum-mode kit edits saved with the project: every pad of the 13 kits (sound, Tune, Decay, '
                    'Tone, Level, Sweep, Noise, Attack), the current kit, M.CH, ARP, RATE, A.OCT, HOLD, ENV and '
                    'SCALE in SG_KITS.BIN beside PADCONF.BIN; read when the project loads (boot included), written '
                    'about 2 s after the last change on the Sound Generator page, when it closes, and with the '
                    'stock PADCONF save; a missing or bad file gives the power-on defaults. Test2 (file version 2): '
                    'the Sound Generator\'s NOTE, OCT, OFST, TYPE, FREQ, LEVEL, Pad Length, DUTY, BALANCE and TUNE '
                    'saved too, and drum and melodic mode each keep their own ARP, RATE, A.OCT and HOLD; version 1 '
                    'files still load',
        parent_app1=str(inp), parent_sha256=sha(inp.read_bytes()),
        parent_revision=json.loads(parent_manifest.read_text(encoding='utf-8')).get('revision')
        if parent_manifest.exists() else None,
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        slot=[base, base + SLOT], blob_base=base, blob_file_offset=file_at, blob_size=len(module),
        blob_sha256=sha(module), source='synth/kits_save.c', source_sha256=source_sha,
        compiler='zig 0.13.0 cc -Os', entries=symbols, kits=KITS, defaults=dict(zip(
            ('kit', 'midi_channel', 'arp_mode', 'arp_rate', 'arp_oct', 'arp_hold', 'env', 'scale'), defaults)),
        patches=patches, callers={f'{k:#x}': v[2] for k, v in CALLERS.items()},
        guards=[dict(start=s, end=e, sha256=d, establishes=w) for s, e, d, w in GUARDS],
        file=dict(
            name='SG_KITS.BIN', where='the project folder, beside PADCONF.BIN (the stock path builder 0x800cf018)',
            size=1688, layout='0x00 magic "SGKT", 0x04 version 1 (u16), 0x06 header size 16 (u16), '
                              '0x08 payload size 1672 (u32), 0x0c CRC-32 of the payload (u32); 0x10 kit_pads[13][16] '
                              '(sound, tune, decay, tone, level, sweep, noise, attack), then kit 1..13, M.CH 0..15, '
                              'ARP 0..6, RATE 0..6, A.OCT -3..3, HOLD 0..1, ENV 0..9, SCALE 0..33 (one byte each)',
            invalid='missing, short, long, another magic, version, header or payload size, a CRC mismatch or any '
                    'value out of range: the power-on defaults'),
        tool='synth/build_kits_save.py', bridges=bridges)
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
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0x83FD5000)
    ap.add_argument('--build-dir', type=Path)
    a = ap.parse_args()
    m = build(a.app1.resolve(), a.out.resolve(), a.zig.resolve(), a.base, a.build_dir.resolve() if a.build_dir else None)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size', 'blob_base', 'blob_size')}, indent=1))


if __name__ == '__main__':
    main()
