"""Note repeat (hardware test build): ROLL as an MPC-style note repeat, on the published v9.46.

A stage on Sound Generator + Kits v9.46 (APP1 7b5fbcb4...684a; NOTE_REPEAT.md). Stock 5.52 rolls by looping a
slice of the pad's voice; here ROLL re-hits the pad through the stock pad note at the pad's Roll division:
ROLL + pad repeats until ROLL is released, a ROLL tap latches (pads then repeat while held, ROLL lit), VALUE
steps the division at once (six triplets too, test2: PADCONF reserved byte 0x70 bits 1-3), ROLL + VALUE press
makes the current pad follow or ignore ROLL (byte 0x70, bit 0), HOLD while rolling holds the rolls (test2).
LOOP pads without GATE keep the stock ring roll. DJ mode stays stock.

Five changes in 5.52 space, each a 10-byte movw ip / movt ip / bx ip at an entry (a nop after it where the
displaced instructions take 12 bytes); the module runs the displaced instructions and goes on:
- 0x8003b530 UI dispatcher (ldrsh.w / subs / cmp / bhi) -> nr_event, on at the tbb 0x8003b53a;
- 0x800cdbd0 stock pad note (push.w / sub sp / mov / mov) -> nr_pad, on at 0x800cdbda;
- 0x8003c5f0 UI tick, every ms (push / sub sp / mov / movw) -> nr_tick, on at 0x8003c5fa;
- 0x80135d40 ROLL let go (push / movw / mov / movt) -> nr_release, on at 0x80135d4c;
- 0x800d9f20 "key held?", the kits' jump to their gate 0x83fa5ae5 -> nr_key_gate, which goes on to that gate.
Stock code the module calls, reads or relies on is checked byte for byte (GUARDS), and so are the call sites
whose return addresses it recognises (CALLERS). The module (Zig 0.13.0, -Os) goes in a new boot copy row in an
8 KB slot at 0x83FDC000, below pad envelopes (0x83FDE000), taken from the top of the room pad FX was given
(0x83FC9000-0x83FDC000 stays its own); the builder checks that no row and no other fork module's slot overlaps
it and that nothing in the input refers to it.

usage: python synth/build_note_repeat.py IN_APP1 OUT_DIR --zig ZIG [--base 0x83FDC000] [--build-dir DIR]
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
REVISION = 'note-repeat-test4'
SLOT = 0x2000                       # reserved: [base, base + SLOT)
GAP = (0x83FC9000, 0x83FF0000)      # above the fork's rows (end 0x83FC8450), below the end of cacheable SDRAM
# Every other fork module's reserved RAM (branch, start, end).
KNOWN_SLOTS = [
    ('pad FX (planned)', 0x83FC9000, 0x83FDC000),
    ('claude/pad-env-amp (pad envelopes)', 0x83FDE000, 0x83FE2000),
    ('claude/fx-deep-edit (FX deep edit)', 0x83FE2000, 0x83FE6000),
    ('claude/fx-probe (FX probe)', 0x83FE6000, 0x83FE8000),
    ('claude/bounce-stage2, claude/bounce-stage3 (bounce)', 0x83FE8000, 0x83FED000),
    ('claude/cpu-meter (CPU meter test)', 0x83FED000, 0x83FEF000),
    ('claude/bounce-probe (bounce probe test)', 0x83FEE000, 0x83FEF000),
    ('main (RESAMPLE start fix)', 0x83FEF000, 0x83FF0000),
]
KIT_GATE = 0x83FA5AE5               # the kits' key-query gate (mov r1, lr; b.w kit_ui_key_query), Thumb
EXPORTS = ('nr_event', 'nr_pad', 'nr_pad_stock', 'nr_tick', 'nr_release', 'nr_key_gate', 'nr_event_c', 'nr_pad_c',
           'nr_tick_c', 'nr', 'nr_enabled', 'nr_rep', 'nr_phys_down', 'nr_phys_pad', 'nr_phys_vel', 'nr_text',
           'nr_div_names', 'nr_div_order', 'nr_trip_stock')
ENTRIES = ('nr_event', 'nr_pad', 'nr_pad_stock', 'nr_tick', 'nr_release', 'nr_key_gate')
# (address, the bytes there in the parent, what they are, the entry symbol, where the module's copy goes on)
SITES = [
    (0x8003B530, bytes.fromhex('b0f90010053920291cd8'),
     'UI dispatcher: ldrsh.w r1, [r0]; subs r1, #5; cmp r1, #0x20; bhi 0x8003b574 (bx lr)', 'nr_event', 0x8003B53A),
    (0x800CDBD0, bytes.fromhex('2de9f04186b00c460546'),
     'stock pad note: push.w {r4-r8, lr}; sub sp, #0x18; mov r4, r1; mov r5, r0', 'nr_pad', 0x800CDBDA),
    (0x8003C5F0, bytes.fromhex('f0b581b004464ef6bc60'),
     'UI tick: push {r4-r7, lr}; sub sp, #4; mov r4, r0; movw r0, #0xeebc', 'nr_tick', 0x8003C5FA),
    (0x80135D40, bytes.fromhex('70b540f6d0140546c8f2e024'),
     'ROLL let go: push {r4-r6, lr}; movw r4, #0x9d0; mov r5, r0; movt r4, #0x82e0', 'nr_release', 0x80135D4C),
    (0x800D9F20, bytes.fromhex('45f6e52cc8f2fa3c604700bf'),
     'key held? (the kits\' jump): movw ip / movt ip / bx ip to their gate 0x83fa5ae5; nop', 'nr_key_gate', None),
]
# Where each entry's own copy of the displaced instructions sits in the module, and what it must be.
DISPLACED = {
    'nr_event': ['ldrsh.w r1, [r0]', 'subs r1, #5', 'cmp r1, #0x20', 'it hi', 'bxhi lr', 'movw ip, #0xb53b',
                 'movt ip, #0x8003', 'bx ip'],
    'nr_pad_stock': ['push.w {r4, r5, r6, r7, r8, lr}', 'sub sp, #0x18', 'mov r4, r1', 'mov r5, r0',
                     'movw ip, #0xdbdb', 'movt ip, #0x800c', 'bx ip'],
    'nr_tick': ['push {r4, r5, r6, r7, lr}', 'sub sp, #4', 'mov r4, r0', 'movw r0, #0xeebc', 'movw ip, #0xc5fb',
                'movt ip, #0x8003', 'bx ip'],
    'nr_release': ['push {r4, r5, r6, lr}', 'movw r4, #0x9d0', 'mov r5, r0', 'movt r4, #0x82e0', 'movw ip, #0x5d4d',
                   'movt ip, #0x8013', 'bx ip'],
}
# Return addresses the module recognises, and the instructions at each call (their bytes are checked too).
CALLERS = {
    0x800AEE23: (0x800AEE1C, bytes.fromhex('21202bf07ff8'), 'movs r0, #0x21; bl 0x800d9f20: ROLL + pad starts a roll'),
    0x800AEF97: (0x800AEF90, bytes.fromhex('21202af0c5ff'), 'movs r0, #0x21; bl 0x800d9f20: a PAD LINK pad (no group)'),
    0x800AF06F: (0x800AF068, bytes.fromhex('21202af059ff'), 'movs r0, #0x21; bl 0x800d9f20: a PAD LINK pad (group)'),
    0x800C904F: (0x800C904A, bytes.fromhex('04f0c1fd'), 'bl 0x800cdbd0: the page pad handler plays a pressed pad'),
    0x800C8D41: (0x800C8D3C, bytes.fromhex('04f048ff'), 'bl 0x800cdbd0: SUB PAD plays the last pad, or lets it go'),
    0x80134193: (0x8013418E, bytes.fromhex('99f71ffd'), 'bl 0x800cdbd0: stock\'s HOLD lets a held GATE pad go'),
}

# Stock 5.52 code and data the module calls, reads or relies on, as in v9.46 (stock in DOOM OS ED5E and the
# fork but 0x8003a968, where DOOM OS points the page registry at its own table): (start, end, SHA-256, what).
GUARDS = [
    (0x8003B530, 0x8003B610, 'e830c8a76bbc2a7cb35d1df281fcdf9b170519dde74684fb7014b2c49e88819b',
     'UI dispatcher: by event type (key 5, key up 6, encoder 7, pad 0x10, pad up 0x11) to the handlers that set '
     'or clear a key\'s held bit and call the page\'s registry handler'),
    (0x800BA228, 0x800BA280, 'd92798f9741338cc84c65d120b0abaaa1ca095cc362d52dbdcd410e3a7d98c58',
     'UI drain: every queued event through 0x8003b530, its result unused'),
    (0x8003A968, 0x8003A9FA, '43e9e232d026400ac9a702a4145a055148c14d94ec4188eb448da05128132410',
     'periodic UI event (with DOOM OS ED5E\'s registry table): the page\'s tick, then the UI tick 0x8003c5f0(1)'),
    (0x8003B410, 0x8003B428, 'ccd58874996774fee3970c1d9b3bfc9e0bc5ca41f9dbd7f4b58f72b75cb4ad88',
     'the periodic event (type 8) to 0x8003a968'),
    (0x8003A678, 0x8003A690, 'f352653d562cad9ec31a2eb0693816a4b3824ab93025cf476a32798cd5c09976',
     'the UI task\'s periodic call: 0x8003b410, then the drain'),
    (0x8003C5F0, 0x8003C660, 'f1f0978e5266440c03405bde83689603ae1a29bc3867ec23a75b2a893131d71a',
     'UI tick (ms): tick listeners, timers, the popup'),
    (0x800CDBD0, 0x800CDE80, 'e54db5be9985d3a1a74b5a7499e219207f8faf3f4be9bb35fe099cb4aa8efc9d',
     'stock pad note (pad, velocity, mode): FIXED VELOCITY, chromatic and DJ routing, the type-4 pad event'),
    (0x800BEF10, 0x800BEF50, '99072d49e16428ff574c7e1b0a20362388553173e09004e699ea7786a0716c1f',
     'pad-event dispatcher: the event into SMPL TASK\'s ring'),
    (0x80050BE0, 0x80050F20, '7359620495ad74f140a6f37f4f71a3f3cd0d46cc2b5cacd481d99a0163eaf67b',
     'pad-event consumer: a type-4 note is given to the pattern recorder (0x800bd5a0), then played (0x800aec48) '
     'or let go (0x800c0a80)'),
    (0x800BD5A0, 0x800BD7A0, '141966bcd33c891fa176544c4bea243d089d6de94d7e1216f0d5cdd68d7ae72f',
     'pattern recorder, pad notes: 0x80030700 while the sequencer records'),
    (0x80030700, 0x80030788, 'd389bc33603b83c079682895806b34d513a9bbc316138005999e14e469623d6e',
     'pattern recorder: an event into the pattern while recording'),
    (0x800AEC48, 0x800AF0E8, 'c8d7dca46b854f752d3e437404f9c1807605129b1ca3a2afc6e781e695cf43b4',
     'note-on: with ROLL held (0x800d9f20(0x21)), a pad and its PAD LINK pads start the stock roll (0x8001a378); '
     'nothing else there asks for ROLL'),
    (0x800C7DB8, 0x800C9788, '605e47bd66fad7c0d1d86c271dd7f44bfce9e28b3f098c7a989613d127def4f1',
     'page pad handler: a press plays (abs pad, velocity, 1) from 0x800c904a, SUB PAD from 0x800c8d3c; first, '
     'without SHIFT, a pad goes by stock\'s HOLD (0x801340c8, from 0x800c829e)'),
    (0x800C9788, 0x800CC030, '7eec6950ceb91b89e1170d37f3a869d997c0e55f1c41a69941cf8421e7c4d0fe',
     'generic key handler: ROLL let go without SHIFT or EXIT calls 0x80135d40; VALUE with ROLL held halves or '
     'doubles the stock rolls; SHIFT + ROLL steps the current pad\'s Roll'),
    (0x80135D40, 0x80135E30, '67598817d5e9fe6fa56a63f6603d91dcfd51ac3b75944367ee244a472b3fe6f9',
     'ROLL let go: rolls the current pad if it sounds without rolling, turns the note-on\'s rolls off'),
    (0x800D9F2C, 0x800D9F48, '5e68a59ef7e026fd95f0c640c00ad0953b106bf14ec40f7c56406886326c55ab',
     'key held?: the held bit in 0x80592448 (the kits\' gate ends here)'),
    (0x83FA5AE4, 0x83FA5AEA, '46c95f67c1608a90f642f67722fa23f715431566667e5b2822f869232dfa6e39',
     'the kits\' gate: mov r1, lr; b.w kit_ui_key_query'),
    (0x800DA720, 0x800DC6B8, 'cc8e475b850943c9337a298e764a26c4a79e506de87dae933b3f4d42ddd12950',
     'pad setter: Roll (0x7b) clamped 0..10, the voices told, CSmplPrm::Edited set'),
    (0x800DC6B8, 0x800DCF08, '76d59a974bf02d89a2b46f14293ee991a737fc3f66453f2c7c952414e5cd4fc7',
     'pad getter: current bank (0) and pad (1), GATE 0x6a, LOOP 0x6b, Roll 0x7b'),
    (0x800DDA38, 0x800DE270, '838ed6e1682b3d6920a0cb718b831cf17f383309dc8f3278e053e7e922fa15b4',
     'project getter: DJ Mixer Mode 0xc2'),
    (0x800D3FF0, 0x800D4060, 'f376902897436ad648477d37af39f6faad37739487ab9a2930467f101b43978d',
     'popup(text, ms) and the time stock\'s popups stay (0x800d4028)'),
    (0x800D4910, 0x800D4960, 'b7c408906e2460a05df41460731fd5473b6c78e23b0022c77e32a3c9e24dc70a',
     'key light (key, mode, level): cached, sent only when it changes'),
    (0x800A7DB0, 0x800A80A8, '63b28a8a6b89b829df88a063e866d505478e9694d74a9404bc8ca2075eb6831d',
     'key light out'),
    (0x80047DD0, 0x80047E70, 'c08d9719c20f8b42fd09806a0b97ce1668589a6f8acbc0b5930fc611429e4f19',
     'the tempo BPM-synced samples on a pad follow (BPM x 100): project or bank, MIDI clock, a playing pattern'),
    (0x800D8C08, 0x800D8C20, '21d5eb5883245c7f0ffa6a9a9515f6969580311c5b5379d02a70bc80e0c77954',
     'a voice slot plays the pad (0x800beae8)'),
    (0x800BEAE8, 0x800BEC28, 'c06ceaf5663c67ce2ea56bcd9601235aaaa05e0ee51caef8e0699a698b919789',
     'the slot that plays a pad, and whether it sounds (0x800d63a8)'),
    (0x800D63A8, 0x800D63C0, 'd8b7383c5d2a6294fdf598fbfa0e7751bd530aabe80562ef51468d6c71db0233', 'slot sounds'),
    (0x800163A8, 0x800163C8, '77309187a6909b5d63db36ab7907d484f98a4bdb70ffe7584a5ed867c72bff5f',
     'stock roll (pad, 0x7f on / 0 off, 0, 0): what settings 0x91 does'),
    (0x8001A378, 0x8001A570, '252a2acfd946c0ab134843bd5f3ce6d715a400bafab29c03b7c2cfe738c6ba9e',
     'stock roll: one of four roll slots, the pad\'s voice'),
    (0x8008D9A0, 0x8008DAF0, 'bff0344987942b693051b7b902ca6e49ed70a274f9c0b1b793efcd5222cff185', 'stock roll: the voice'),
    (0x800202B8, 0x800202F8, '4a0a2cbd306571e2841e1ff83117e970a65bbfa9af1275285eb76e2281b8123a',
     'stock roll: off lets a GATE pad go that was let go while rolling'),
    (0x80024450, 0x80024580, 'f18d262e0281961ac37a8fa538e110ee019754e069946f6a427f07c389280521',
     'stock roll: the ring length from the pad\'s Roll and tempo, the stop at the end of a pass'),
    (0x800257B0, 0x80025838, '51599ebb92926a52686f1e3ef783ab70511cc55713168aec0658ead23ac6283c',
     'stock roll: RecordRollPending, the roll event a recording pattern takes'),
    (0x800E25C0, 0x800E26D0, 'c4a456143fe8201ffa722a3533cb40d3195e94b93472e9bafc9c24535d344027',
     'post a command to SMPL TASK (0xd: save the pad parameters)'),
    (0x801A9F18, 0x801A9F44, '2d24843801b4cb5ca08053c7c587d4171f7457fc688f497abd8a51ab8cbafc1d',
     'Roll value to beats: 2, 1, 1/2, 1/4, 1/8, 1/16, 3/2, 3/4, 3/8, 3/16'),
    (0x80003408, 0x80003420, '7665007d213fbc0e3d7bfd1ab803cc3058dcf2661730d1f6a3d67c78555cb786',
     'the audio DMA interrupt (every 64-frame block) calls the clock step 0x80004f70'),
    (0x80004F70, 0x80004FAE, 'acd6d5acdf0b4623f02909decb5047d875c0d041332b91135c7e475d412c75e1',
     'clock step: 0x8059226c += 32, then the cycle counter (0xe0001004) into 0x80592264'),
    (0x80009E02, 0x80009E36, '6d10b79f3985ea749951af6cdb2ddf2b67ef62d42d08b34db288878ced4bab6f',
     'the stock MIDI clock between blocks: 0x8059226c + (cycles since 0x80592264) x 32 / 798000'),
    (0x80009F04, 0x80009F0C, '5bc2cb4440d6b8eaec65fa278d1b88f6d9c9b46dcd091732105045248e96fb8c',
     'its constants 32.0 and 798000.0'),
    (0x801340C8, 0x80134218, 'fcf60ed49c31ec398f84933f5170fbdaf13bca8c1908387a7143adeef82a60d7',
     'a pad and HOLD (settings 10: 1 down, 2 held): a press on a held GATE pad lets it go without playing (its '
     'note-off from 0x8013418e); on any other held pad it goes on to play'),
    (0x80182BC8, 0x80182C38, 'b0d4c97cc8a0b8a4388300b168e501c4c7bef30c442ab807d64d523677529a0f',
     'the UI tick hands the light and draw requests (0x802496f0) to 0x800d5370'),
    (0x800D5370, 0x800D5430, '650eb5b983a8c4fd7d1a7c88f3a3fe6de2366c05c51fbb902ac9abc35ce03709',
     'the light updater (DOOM OS ED5E jumps in first): request bit 2 repaints the pads, 0x10 the keys'),
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
    """Runtime bytes of an APP1 image, as its scatter loader leaves them (COPY and DECOMPRESS rows; a later row
    over an earlier one wins)."""

    def __init__(self, img):
        self.img, self.rows, self.cache = bytes(img), scatter(img), {}

    def read(self, addr, n):
        hit = None
        for load, dst, size, fn in self.rows:
            if load and dst <= addr and addr + n <= dst + size and fn in (COPY, DECOMPRESS):
                hit = (load, dst, size, fn)
        if hit is None:
            raise ValueError(f'{addr:#x}+{n:#x} not in a copy or decompress row')
        load, dst, size, fn = hit
        if fn == COPY:
            return self.img[load - FLASH + addr - dst:load - FLASH + addr - dst + n]
        if dst not in self.cache:
            self.cache[dst] = decompress(self.img[load - FLASH:], size)
        return self.cache[dst][addr - dst:addr - dst + n]

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


def movw_movt_bx(rd, value):
    """movw rd, #lo; movt rd, #hi; bx rd (10 bytes)."""
    def t3(op, imm):
        h1 = op | ((imm >> 11) & 1) << 10 | (imm >> 12) & 0xF
        h2 = ((imm >> 8) & 7) << 12 | rd << 8 | imm & 0xFF
        return struct.pack('<2H', h1, h2)
    return t3(0xF240, value & 0xFFFF) + t3(0xF2C0, value >> 16) + struct.pack('<H', 0x4700 | rd << 3)


def listing(code, at):
    return [f'{i.mnemonic} {i.op_str}'.strip() for i in MD.disasm(code, at)]


def compile_module(folder: Path, zig: Path, link_base: int, limit: int):
    folder.mkdir(parents=True, exist_ok=True)
    if subprocess.check_output([str(zig), 'version'], text=True).strip() != '0.13.0':
        raise ValueError('needs Zig 0.13.0')
    keep = ' '.join(f'KEEP(*(.text.{n}))' for n in ENTRIES)
    (folder / 'note_repeat.ld').write_text(f'''ENTRY(nr_event)
SECTIONS {{
 . = {link_base:#x};
 .text : {{ {keep} *(.text*) }}
 .rodata : ALIGN(16) {{ *(.rodata*) }}
 .data : ALIGN(16) {{ *(.data*) }}
 .bss : ALIGN(16) {{ *(.bss*) *(COMMON) }}
 /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.note*) }}
}}
''', encoding='ascii', newline='\n')
    source = folder / 'note_repeat.c'             # compile LF-normalized source
    source.write_bytes((HERE / 'note_repeat.c').read_bytes().replace(b'\r\n', b'\n'))
    cache = folder / 'cache'
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache))
    # -g only keeps the symbol table: Zig's -Os (ReleaseSmall) strips it otherwise. Same code.
    subprocess.run([str(zig), 'cc', '-target', 'thumb-freestanding-eabihf', '-mcpu=cortex_m7+vfp4d16',
                    '-mfloat-abi=hard', '-Os', '-g', '-ffunction-sections', '-fdata-sections', '-nostdlib',
                    '-fno-builtin', '-Wall', '-Werror', '-Wl,--no-undefined', '-Wl,--build-id=none',
                    f'-DKIT_KEY_GATE={KIT_GATE:#x}', '-Wl,-e,nr_event', '-Wl,-T,' + str(folder / 'note_repeat.ld'),
                    str(source), '-o', str(folder / 'note_repeat.elf')], check=True, env=env)
    code, symbols = read_module((folder / 'note_repeat.elf').read_bytes(), link_base, limit)
    missing = [n for n in EXPORTS if n not in symbols]
    if missing:
        raise ValueError(f'module exports missing: {missing}')
    return code, {n: symbols[n] for n in EXPORTS}, sha(source.read_bytes())


def check_module(module, symbols, base):
    """The entries are Thumb functions; each copy of displaced instructions is exactly them, then the jump on."""
    for name in ENTRIES:
        if not symbols[name] & 1:
            raise ValueError(f'{name} is not a Thumb function symbol')
    for name, want in DISPLACED.items():
        at = symbols[name] & ~1
        got = listing(module[at - base:at - base + 64], at)
        if name == 'nr_event':
            got = got[6:6 + len(want)]           # after push / bl nr_event_c / cmp / pop / it ne / bxne lr
            head = listing(module[at - base:at - base + 16], at)
            if head != ['push {r0, lr}', f'bl #{symbols["nr_event_c"] & ~1:#x}', 'cmp r0, #0',
                        'pop.w {r0, lr}', 'it ne', 'bxne lr']:
                raise ValueError(f'nr_event: unexpected head {head}')
        elif name in ('nr_tick',):
            head = listing(module[at - base:at - base + 10], at)
            if head != ['push {r0, lr}', f'bl #{symbols["nr_tick_c"] & ~1:#x}', 'pop.w {r0, lr}']:
                raise ValueError(f'nr_tick: unexpected head {head}')
            got = got[3:3 + len(want)]
        elif name == 'nr_release':
            got = got[6:6 + len(want)]           # after the nr_enabled test
        else:
            got = got[:len(want)]
        if got != want:
            raise ValueError(f'{name}: the displaced instructions are not the stock ones: {got}')
    at = symbols['nr_pad'] & ~1
    pad = listing(module[at - base:at - base + 16], at)
    if pad != ['push {r0, r1, r2, r3, r4, lr}', 'mov r3, lr', f'bl #{symbols["nr_pad_c"] & ~1:#x}',
               'pop.w {r0, r1, r2, r3, r4, lr}', f'b.w #{symbols["nr_pad_stock"] & ~1:#x}']:
        raise ValueError(f'nr_pad: unexpected bridge {pad}')
    at = symbols['nr_key_gate'] & ~1
    gate = listing(module[at - base:at - base + 96], at)
    gate = gate[:gate.index('movt ip, #0x83fa') + 2] if 'movt ip, #0x83fa' in gate else gate
    lr_consts = [i for i in gate if i.startswith(('movw ip', 'movt ip'))]
    if gate[0] != 'cmp r0, #0x21' or gate[-3:] != ['movw ip, #0x5ae5', 'movt ip, #0x83fa', 'bx ip'] or \
            lr_consts[:6] != ['movw ip, #0xee23', 'movt ip, #0x800a', 'movw ip, #0xef97', 'movt ip, #0x800a',
                              'movw ip, #0xf06f', 'movt ip, #0x800a']:
        raise ValueError(f'nr_key_gate: unexpected code {gate}')
    return dict(gate=gate, pad=pad)


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
    for addr, original, what, entry, _ in SITES:
        if rt.read(addr, len(original)) != original:
            raise ValueError(f'{addr:#x}: expected {what}')
        # the entry itself (addr | 1 for code pointers) may be called; nothing may land inside
        inside = branches_into(rt, addr + 1, addr + len(original)) + refs_into(bytes(img), addr + 2, addr + len(original))
        if inside:
            raise ValueError(f'something reaches into {addr:#x}..{addr + len(original):#x}: {inside[:4]}')
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
    module, symbols, source_sha = compile_module(folder, zig, base, base + SLOT)
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
            raise ValueError(f'the new image does not hold the jump at {p["address"]:#x}')

    out.mkdir(parents=True, exist_ok=True)
    (out / 'SP404MKII_APP1.bin').write_bytes(img)
    shutil.copy2(app0, out / 'SP404MKII_APP0.bin')
    parent_manifest = inp.with_name('manifest.json')
    manifest = dict(
        revision=REVISION, status='hardware-unverified', published=False,
        description='ROLL as an MPC-style note repeat: ROLL + pad re-hits the pad through the stock pad note at the '
                    'pad\'s Roll division until ROLL is let go; a ROLL tap latches (pads repeat while held, ROLL '
                    'lit); VALUE steps the division at once, triplets included; ROLL + VALUE press: the current pad '
                    'follows or ignores '
                    'ROLL (saved with the pad); HOLD while rolling: held rolls, until the pad is hit again, HOLD '
                    'again or EXIT + ROLL; LOOP pads without GATE keep the stock roll; DJ mode stays stock; '
                    'chromatic pads (test4) roll at their own chromatic division, 1/16 until VALUE moves it, at '
                    'the sample\'s tempo, whatever else the pad under the finger holds',
        parent_app1=str(inp), parent_sha256=sha(inp.read_bytes()),
        parent_revision=json.loads(parent_manifest.read_text(encoding='utf-8')).get('revision')
        if parent_manifest.exists() else None,
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        slot=[base, base + SLOT], blob_base=base, blob_file_offset=file_at, blob_size=len(module),
        blob_sha256=sha(module), source='synth/note_repeat.c', source_sha256=source_sha,
        compiler='zig 0.13.0 cc -Os', entries=symbols, kit_key_gate=KIT_GATE,
        patches=patches, callers={f'{k:#x}': v[2] for k, v in CALLERS.items()},
        guards=[dict(start=s, end=e, sha256=d, establishes=w) for s, e, d, w in GUARDS],
        controls=dict(
            roll_pad='ROLL + pad: the pad re-hits at its Roll division until ROLL is let go (letting go of the pad '
                     'first does not stop it, as stock)',
            latch='a ROLL tap (nothing else touched while it was down) latches: pads repeat while they are held, '
                  'ROLL lit (LED key 0x21, page 0, 0xff); another tap unlatches',
            value='VALUE turned while ROLL is held, or while latched with a pad repeating: each repeating pad\'s '
                  'division moves along 1/2 3/8 1/2T 1/4 3/16 1/4T 1/8 3/32 1/8T 1/16 3/64 1/16T 1/32 1/32T 1/64 '
                  '1/64T at once (none repeating: the current pad\'s); popup "Roll 1/16T"; kept with the pad: Roll '
                  '(0x7b) gets it, or for a triplet its nearest stock division (1/2T 3/8, 1/4T 3/16, 1/8T 3/32, '
                  '1/16T 3/64, 1/32T and 1/64T 1/64), and the triplet goes in PADCONF reserved byte 0x70 bits 1-3 '
                  '(1..6), counted while Roll holds that neighbour; saved as the follow flag is',
            follow='ROLL + VALUE press: the current pad follows or ignores ROLL; PADCONF reserved byte 0x70 bit 0 '
                   '(set = ignores), saved with command 0xd a second after the last change once no pad repeats; '
                   'popup "A-01 IGNORES ROLL"',
            hold='HOLD (no SHIFT) while rolls go on: they become held rolls (popup "Roll Held") and go on whatever '
                 'ROLL does and whatever other pads do, until their pad is hit again (that press starts no roll), '
                 'HOLD is pressed again with only held rolls going on and no pad down (popup "Roll Hold Off"), or '
                 'EXIT + ROLL; a held roll\'s pad blinks white (light page 6) when its bank is the current one and '
                 'the page is not DOOM OS\'s (0x5f), HOLD is lit; stock repaints pads and keys after (0x802496f0 '
                 'bits 2, 0x10); stock\'s HOLD runs as well, every time',
            chromatic='(test4) in chromatic mode (project 0xBF, not the Sound Generator\'s page) a pad\'s roll '
                      'takes only its chromatic division from the pad under the finger: PADCONF reserved byte 0x70 '
                      'bits 4-7, steps along VALUE\'s order from 1/16 (0, the default); VALUE steps each repeating '
                      'chromatic pad\'s own (none repeating: ROLL + VALUE steps the last chromatic pad played), '
                      'popup "Roll 1/32", saved as the follow flag is; ROLL + VALUE press shows that pad\'s and '
                      'toggles no follow flag; at the tempo of the pad whose sample chromatic mode plays (project '
                      '0xC1), always by re-hits; the pad\'s Roll, LOOP, GATE and follow flag are not read or '
                      'written; latched with VALUE held, a VALUE turn goes on to the page',
            stock='SHIFT + ROLL (the Roll popup), EXIT + ROLL (all rolls off), DJ Mixer Mode (all of ROLL and HOLD), '
                  'HOLD with nothing rolling, SHIFT + HOLD, patterns\' recorded rolls, LOOP pads without GATE (the '
                  'stock ring roll, started by the module)'),
        timing='each repeat at last + beats x 288000000 / (BPM x 100) frames, the remainder carried, on the audio '
               'clock (0x8059226c, 64 frames a block, between blocks by the cycle counter at 798000 a block as the '
               'stock MIDI clock does), sent at the first UI tick at or after it; the tempo is 0x80047dd0(pad), '
               '120 BPM if it is not 20..300',
        tool='synth/build_note_repeat.py', bridges=bridges)
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
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0x83FDC000)
    ap.add_argument('--build-dir', type=Path)
    a = ap.parse_args()
    m = build(a.app1.resolve(), a.out.resolve(), a.zig.resolve(), a.base, a.build_dir.resolve() if a.build_dir else None)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size', 'blob_base', 'blob_size')}, indent=1))


if __name__ == '__main__':
    main()
