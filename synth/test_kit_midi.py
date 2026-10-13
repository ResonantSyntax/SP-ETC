"""External MIDI for the kits build, fed through the real stock MIDI dispatcher.

The built APP1 is booted into Unicorn the way its scatter loader does it (copy,
decompress and zero rows, in order). MIDI messages go to the stock dispatcher at
0x80066278, which reaches the note-off, note-on and CC handlers through the stock
table at 0x802091ec. Sound Generator code runs for real: the voice allocator, the
stock note starts, the kit engine and the render loop. Stock functions outside
the Sound Generator are stopped at their entry and logged: control-channel
functions, the chromatic pad, the sample-pad path and the CC queue signal. The
RTOS dispatch-off/on and task-delay calls are stubbed. There is no screen, no
peripheral and no real timing. This is not a hardware test.

1. Drum note map: notes 36..51 strike pads 1..16 through the pad path. They
   produce the same voice state as a pad strike and, through the real render
   loop, the same audio sample for sample. Every other note does nothing, ARP
   on or off. A pad note outside the playable range (OCT +4) falls back to the
   MIDI pitch. Melodic MIDI is unchanged.
2. M.CH routing for every channel, note and page against a model of the stock
   dispatcher. M.CH 16 is stock. Another channel plays the SG only on its page.
   Channel 16 keeps its control functions and its chromatic pad note-offs and
   never plays the SG. With a second build folder (the v9.43 kits build), M.CH
   16 must also take exactly the v9.43 path for every message.
3. The M.CH item: name, text, bounds, the stock VALUE-cursor range, and a
   change stops held notes and clears the arp.
4. CCs through the stock CC handler. Drum: all 48 pad CCs and the four
   last-pad CCs at 0, 64 and 127 set exactly the knobs' values at once and
   select the pad. A CC sent just before a note shapes that hit, sample for
   sample. Melodic: all seven CCs, after the next screen update, through the
   stock setter, at the knobs' scaling. Arp: 33-36 in both modes, with A.OCT
   melodic only. Every other CC number, another channel or another page
   changes nothing, and every CC still reaches the stock CC queue unchanged.
   CC 123 and CC 120 let go of MIDI notes and stop the arp; 120 also fades out
   every voice.

Usage: python synth/test_kit_midi.py out/kits-v944 [out/kits-v943]
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_HOOK_CODE
from unicorn import arm_const as ar

FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
RET, STACK, MSG, BUS, BUF = 0x3001F000, 0x30010000, 0x30015000, 0x30004000, 0x30016000
FRAMES, CHANNELS = 64, 14
DISPATCH = 0x80066278                     # stock MIDI dispatcher (handler table 0x802091ec)
SG_HANDLER, SG_PAGE_BODY = 0x8005A680, 0x8005A6A6
CHROMATIC = 0x8005A6B4                    # stock chromatic pad, notes 36..60 (non-SG half)
CTRL_A, CTRL_B = 0x8005A358, 0x80058570   # channel-16 control functions
PAD_PATHS = {0x80066E78: 0x80066D0C, 0x800670CC: 0x80067054}   # sample-pad path -> handler epilogue
QUEUE_SIGNAL = 0x8004C1E0
PAGE, KB, SETTINGS, SETTINGS_VTABLE = 0x80245880, 0x80591C48, 0x82E01144, 0x8021CD10
SG = 0x1E
VOICES = (0x80249800, 0x8353A310, 0x8353A4C0, 0x8353A670)
STOCK_RESET, NOTE_ENGINE, RENDER, RELEASE_ALL = 0x80132340, 0x8353B000, 0x1FD80, 0x1FE00
KB_PAD_NOTE_PARENT = 'kb_pad_note'
CC_QUEUE = 0x80D3D96C                     # stock CC queue: flag, read, write, 64 four-byte entries
SETTING_GET, SETTING_RANGE = 0x800D94D8, 0x800C1780
# The approved chart.
PAD_CC = [20 + 3 * k for k in range(4)] + [40 + 3 * k for k in range(8)] + [102 + 3 * k for k in range(4)]
LAST_PAD_CC = {114: 3, 115: 5, 116: 6, 117: 7}            # Tone, Sweep, Noise, Attack (kit_pad offsets)
MELODIC_CC = {70: 0x7B, 71: 0x7C, 72: 0x7D, 73: 0x7F, 74: 0x80, 75: 0x82, 76: 0x81}
ARP_CC = {33: 'arp_mode', 34: 'arp_rate', 35: 'arp_oct', 36: 'arp_hold'}
# Stock control-channel codes: notes 12..19 and 24..31 (12 and 24 use CTRL_B).
CONTROL = {12: ('B', 8), 13: ('A', 1), 14: ('A', 4), 15: ('A', 5), 16: ('A', 8), 17: ('A', 9), 18: ('A', 12),
           19: ('A', 13), 24: ('B', 10), 25: ('A', 3), 26: ('A', 6), 27: ('A', 7), 28: ('A', 10), 29: ('A', 11),
           30: ('A', 14), 31: ('A', 15)}


def decompress(src, size):
    """armlink's LZ77 variant for RW data (format as in dm-404's tools/unpack.py)."""
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


class Machine:
    """The built image after its boot copy, on the SG page with four idle voices."""

    def __init__(self, folder: Path, parent_symbols):
        self.folder = folder
        self.man = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        image = (folder / 'SP404MKII_APP1.bin').read_bytes()
        if hashlib.sha256(image).hexdigest() != self.man['sha256']:
            raise ValueError('APP1/manifest hash mismatch')
        self.S = self.man['arp_symbols']
        self.kb_pad_note = parent_symbols[KB_PAD_NOTE_PARENT] | 1
        uc = self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for base, size in ((0x0, 0x20000), (0x20000000, 0x80000), (0x20200000, 0x100000),
                           (0x80000000, 0x4000000), (0x30000000, 0x20000), (0x60000000, 0x400000)):
            uc.mem_map(base, size, UC_PROT_ALL)
        uc.mem_write(FLASH, image)
        a, b = struct.unpack_from('<2I', image, 0x80)
        for load, dst, size, handler in (struct.unpack_from('<4I', image, i) for i in range(a + 0x80, b + 0x80, 16)):
            if handler == COPY:
                uc.mem_write(dst, image[load - FLASH:load - FLASH + size])
            elif handler == DECOMPRESS:
                uc.mem_write(dst, decompress(image[load - FLASH:], size))
            elif handler == ZERO:
                uc.mem_write(dst, bytes(size))
            else:
                raise ValueError(f'unknown scatter handler {handler:#x}')
        uc.reg_write(ar.UC_ARM_REG_C1_C0_2, uc.reg_read(ar.UC_ARM_REG_C1_C0_2) | (0xF << 20))
        uc.reg_write(ar.UC_ARM_REG_FPEXC, 0x40000000)
        uc.mem_write(RET, b'\x00\xbf\x00\xbf')
        self.trace = []
        for address in (0x800DED08, 0x800DECF8, 0x800D31EE):      # dispatch off/on, task delay
            self.stub(address)
        self.stub(0x800D314E, value=0x1234567)                     # random(): fixed
        # The arp asks the project which bank is active and that bank's tempo.
        self.stub(0x800DDA38, value=0)                             # project parameter: bank A
        self.stub(0x80047DD0, value=12000)                         # pad tempo: 120 BPM
        self.stub(0x800D5640, value=12000)                         # current tempo: 120 BPM
        self.stub(QUEUE_SIGNAL, log='queue')
        self.stub(CTRL_A, log='ctrl')
        self.stub(CTRL_B, log='ctrl')
        self.mark(SG_HANDLER, 'h680')
        self.mark(self.S['arp_midi_event'] & ~1, 'sg')
        uc.hook_add(UC_HOOK_CODE, self._chromatic, begin=CHROMATIC, end=CHROMATIC)
        for site, epilogue in PAD_PATHS.items():
            uc.hook_add(UC_HOOK_CODE, self._pad_path, epilogue, begin=site, end=site)
        self.put(SETTINGS, SETTINGS_VTABLE, '<I')                  # set by the SP's constructors
        self.put(CC_QUEUE + 4, CC_QUEUE + 0xC, '<I')               # empty queue, as at boot (0x80045b52)
        self.put(CC_QUEUE + 8, CC_QUEUE + 0xC, '<I')
        self.page(SG)
        for off, value in ((0, 1), (4, 0), (8, 0), (0xC, 0), (0x10, 0), (0x14, 0)):
            self.put(KB + off, value)                              # keyboard on, OCT 0, OFST 0, Chrom
        self.idle()

    # -- emulator plumbing --
    def stub(self, address, value=0, log=None):
        def hook(uc, a, size, _):
            if log:
                self.trace.append((log, uc.reg_read(ar.UC_ARM_REG_R0), uc.reg_read(ar.UC_ARM_REG_R1),
                                   uc.reg_read(ar.UC_ARM_REG_R2)) if log == 'ctrl' else (log,))
            uc.reg_write(ar.UC_ARM_REG_R0, value)
            uc.reg_write(ar.UC_ARM_REG_PC, uc.reg_read(ar.UC_ARM_REG_LR))
        self.uc.hook_add(UC_HOOK_CODE, hook, begin=address, end=address)

    def mark(self, address, label):
        self.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: self.trace.append((label,)), begin=address, end=address)

    def _chromatic(self, uc, address, size, _):
        self.trace.append(('chromatic',))
        uc.reg_write(ar.UC_ARM_REG_PC, 0x8005A6AF)                 # the handler's own epilogue

    def _pad_path(self, uc, address, size, epilogue):
        self.trace.append(('pad',))
        uc.reg_write(ar.UC_ARM_REG_PC, epilogue | 1)

    def call(self, fn, *args, stack0=0):
        uc = self.uc
        uc.reg_write(ar.UC_ARM_REG_SP, STACK)
        uc.mem_write(STACK, struct.pack('<I', stack0 & 0xFFFFFFFF))
        for k, value in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), value & 0xFFFFFFFF)
        uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        uc.emu_start(fn | 1, RET, count=5_000_000)
        if uc.reg_read(ar.UC_ARM_REG_PC) != RET or uc.reg_read(ar.UC_ARM_REG_SP) != STACK:
            raise RuntimeError(('did not return cleanly', hex(fn), hex(uc.reg_read(ar.UC_ARM_REG_PC))))
        return uc.reg_read(ar.UC_ARM_REG_R0)

    def put(self, address, value, fmt='<i'):
        self.uc.mem_write(address, struct.pack(fmt, value))

    def get(self, address, fmt='<i'):
        return struct.unpack(fmt, bytes(self.uc.mem_read(address, struct.calcsize(fmt))))[0]

    def sym(self, name, fmt='<B'):
        return self.get(self.S[name], fmt)

    def setsym(self, name, value, fmt='<B'):
        self.put(self.S[name], value, fmt)

    # -- the SP --
    def page(self, value):
        self.put(PAGE, value, '<h')

    def idle(self):
        """Four idle voices, as after an all-stop."""
        for v in VOICES:
            self.uc.mem_write(v, b'\0\0\0\0')
        self.call(STOCK_RESET, VOICES[0])

    def send(self, status, d1, d2=0):
        self.uc.mem_write(MSG, bytes([0, status, d1, d2]))
        self.trace = []
        self.call(DISPATCH, MSG)
        return self.trace

    def voices(self):
        out = []
        for v in VOICES:
            raw = bytes(self.uc.mem_read(v, 0x1B0))
            out.append(dict(active=raw[0], released=raw[1], note=struct.unpack_from('<i', raw, 0x19C)[0],
                            source=struct.unpack_from('<i', raw, 0x1AC)[0], midi=raw[0x194],
                            vel=struct.unpack_from('<i', raw, 0x198)[0]))
        return out

    def pad_note(self, pad):
        return struct.unpack('<i', struct.pack('<I', self.call(self.kb_pad_note, pad)))[0]

    def render(self, blocks):
        """The real render loop (arp clock, voices, kit engine): every bus channel, every frame."""
        out = []
        for _ in range(blocks):
            self.uc.mem_write(BUS, bytes(FRAMES * CHANNELS * 4))
            self.call(RENDER, 0, BUS, FRAMES, CHANNELS)
            out += struct.unpack(f'<{FRAMES * CHANNELS}i', bytes(self.uc.mem_read(BUS, FRAMES * CHANNELS * 4)))
        return out

    def text(self, fn, item):
        self.uc.mem_write(BUF, bytes(16))
        self.call(self.S[fn], item, BUF)
        return bytes(self.uc.mem_read(BUF, 16)).split(b'\0')[0].decode('latin-1')

    def cc(self, ch, number, value):
        """A CC through the dispatcher; it must still reach the stock CC queue unchanged."""
        at = self.get(CC_QUEUE + 8, '<I')
        trace = kinds(self.send(0xB0 | (ch - 1), number, value))
        entry = bytes(self.uc.mem_read(at, 4))
        if entry != bytes([0xB0 | (ch - 1), number, value, 2]) or 'queue' not in [t[0] for t in self.trace]:
            raise AssertionError(('stock CC queue', ch, number, value, entry.hex()))
        if self.get(CC_QUEUE + 8, '<I') == CC_QUEUE + 0x10C:     # keep the ring from wrapping onto itself
            self.put(CC_QUEUE + 8, CC_QUEUE + 0xC, '<I')
        return trace

    def pads(self, kit):
        return bytes(self.uc.mem_read(self.S['kit_pads'] + (kit - 1) * 16 * 8, 16 * 8))

    def setting(self, sid):
        return struct.unpack('<i', struct.pack('<I', self.call(SETTING_GET, SETTINGS, sid, 0)))[0]

    def setting_range(self, sid):
        self.uc.mem_write(BUF, bytes(8))
        self.call(SETTING_RANGE, SETTINGS, sid, BUF, BUF + 4, stack0=0)
        return self.get(BUF), self.get(BUF + 4)

    def poll(self):
        """The SG screen update (UI task): applies waiting CCs; 1 = redraw."""
        return self.call(self.S['arp_poll'])

    def state(self):
        """Everything a CC may change: the pads of every kit, the melodic settings, the arp."""
        return (bytes(self.uc.mem_read(self.S['kit_pads'], 13 * 16 * 8)),
                tuple(self.setting(s) for s in MELODIC_CC.values()),
                tuple(self.sym(n, '<i') for n in ARP_CC.values()), self.sym('kit_midi_channel'))


def kinds(trace):
    return [t[0] for t in trace if t[0] != 'queue']


def stock_model(mch, page, on, ch, note):
    """The path a note takes: the stock dispatcher for M.CH 16, and the M.CH rules otherwise.
    ch and mch are 1..16. Returns the landmark labels in order."""
    sg_page = page == SG
    if mch == 16:
        if on and ch == 16 and not sg_page and note in CONTROL:
            return ['ctrl']
        if ch != 16:
            return ['pad']
        path = ['h680']
        if sg_page:
            path.append('sg')
        if (not on or not sg_page) and 36 <= note <= 60:
            path.append('chromatic')
        return path
    if on and ch == 16 and note in CONTROL:
        return ['ctrl']
    if ch == mch:
        return ['sg'] if sg_page else ['pad']
    if ch == 16:
        if sg_page:
            return [] if on or not 36 <= note <= 60 else ['chromatic']
        return ['h680'] + (['chromatic'] if 36 <= note <= 60 else [])
    return ['pad']


def main():
    out = Path(sys.argv[1]).resolve()
    baseline = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
    parent = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))['symbols']
    fresh = lambda folder=out: Machine(folder, parent)
    report = {}

    # 1. Drum note map -----------------------------------------------------------------------------
    m = fresh()
    m.setsym('kit_mode', 1)
    played = {}
    for note in range(128):
        m.idle()
        before = (m.sym('kit_record_pad'), m.sym('kit_last_hit'), m.sym('kit_edit_pad'))
        path = kinds(m.send(0x9F, note, 100))
        live = [v for v in m.voices() if v['active']]
        if 36 <= note <= 51:
            pad = note - 36
            want = dict(active=1, released=0, note=m.pad_note(pad), source=pad, midi=0xFF, vel=100 * 100)
            if path != ['h680', 'sg'] or live != [want]:
                raise AssertionError(('drum note', note, path, live, want))
            if (m.sym('kit_record_pad'), m.sym('kit_last_hit'), m.sym('kit_edit_pad')) != (pad, pad, pad):
                raise AssertionError(('drum note selects its pad', note))
            if m.sym('kit_pads_down', '<H') != 0:
                raise AssertionError(('MIDI must not hold a pad down', note))
            m.send(0x8F, note, 0)
            if [v['released'] for v in m.voices() if v['active']] != [1]:
                raise AssertionError(('drum note-off releases', note))
            played[note] = pad
        elif live or (m.sym('kit_record_pad'), m.sym('kit_last_hit'), m.sym('kit_edit_pad')) != before:
            raise AssertionError(('note outside 36..51 played', note, live))
    report['drum_notes'] = dict(pads={str(k): v + 1 for k, v in played.items()}, ignored=128 - len(played))

    # Same audio as striking the pad, through the real render loop, for every pad.
    exact = []
    for pad in range(16):
        renders = []
        for how in ('midi', 'pad'):
            m = fresh()
            m.setsym('kit_mode', 1)
            if how == 'midi':
                m.send(0x9F, 36 + pad, 100)
            else:
                m.call(NOTE_ENGINE, 0, m.pad_note(pad), 100, 0, stack0=pad)
            renders.append(m.render(12))
        if renders[0] != renders[1] or not any(renders[0]):
            raise AssertionError(('MIDI hit differs from the pad', pad))
        exact.append(max(abs(x) for x in renders[0]))
    report['drum_audio'] = dict(pads_sample_exact=16, frames=12 * FRAMES, peaks=exact)

    # ARP on: MIDI drum notes enter the held list as their pads.
    m = fresh()
    m.setsym('kit_mode', 1)
    m.setsym('arp_mode', 1, '<i')
    m.send(0x9F, 40, 90)
    held = (m.sym('held_count', '<i'), m.get(m.S['held_src'], '<H'), m.get(m.S['held_note'], '<b'))
    if held != (1, 4, m.pad_note(4)):
        raise AssertionError(('arp held list', held))
    m.render(4)
    if m.sym('kit_last_hit') != 4 or m.sym('arp_steps', '<I') < 1:
        raise AssertionError(('arp step plays pad 5', m.sym('kit_last_hit')))
    m.send(0x9F, 30, 90)                                         # outside the map: ignored
    if m.sym('held_count', '<i') != 1:
        raise AssertionError('arp took a note outside 36..51')
    m.send(0x8F, 40, 0)
    if m.sym('held_count', '<i') != 0:
        raise AssertionError('arp note-off')
    report['drum_arp'] = dict(held_source=4, held_note='pad note', note_off_clears=True)

    # A pad note outside the playable range (OCT +4) falls back to the MIDI pitch and still sounds.
    m = fresh()
    m.setsym('kit_mode', 1)
    m.put(KB + 4, 4)
    if 0 <= m.pad_note(0) + 36 <= 84:
        raise AssertionError('OCT +4 should put pad 1 out of range')
    m.send(0x9F, 36, 100)
    live = [v for v in m.voices() if v['active']]
    if [(v['source'], v['note']) for v in live] != [(0, -12)] or not any(m.render(12)):
        raise AssertionError(('out-of-range fallback', live))
    report['drum_out_of_range_pad'] = 'MIDI pitch used; the hit sounds'

    # Melodic MIDI is unchanged: every voice field as v9.43 (pad lights by pitch).
    m = fresh()
    m.send(0x9F, 60, 80)
    live = [v for v in m.voices() if v['active']]
    if [(v['source'], v['note'], v['midi']) for v in live] != [(-1, 12, 60)]:
        raise AssertionError(('melodic MIDI', live))
    report['melodic_note'] = dict(source=-1, note=12, midi=60)

    # 2. M.CH routing --------------------------------------------------------------------------------
    notes_on = (5, 12, 13, 19, 20, 24, 25, 31, 36, 40, 51, 60, 61, 72)
    notes_off = (12, 36, 40, 60, 72)
    checked = 0
    for mch in (16, 10, 1):
        m = fresh()
        m.setsym('kit_midi_channel', mch - 1)
        for page in (SG, 0x01, 0x22):
            m.page(page)
            for ch in range(1, 17):
                for on, notes in ((True, notes_on), (False, notes_off)):
                    for note in notes:
                        m.idle()
                        got = kinds(m.send((0x90 if on else 0x80) | (ch - 1), note, 100 if on else 0))
                        want = stock_model(mch, page, on, ch, note)
                        if got != want:
                            raise AssertionError(('routing', mch, hex(page), ch, on, note, got, want))
                        if got == ['ctrl']:
                            code = CONTROL[note]
                            call = m.trace[-1]
                            if (('A' if call[1] == code[1] and call[2] == 0x7F else '?') if code[0] == 'A'
                                    else ('B' if (call[1], call[2], call[3]) == (code[1], 0x7F, 1) else '?')) != code[0]:
                                raise AssertionError(('control code', note, call))
                        checked += 1
    report['routing'] = dict(messages=checked, m_ch=[16, 10, 1], pages=['SG', '0x01', '0x22'])

    if baseline is not None:
        same = 0
        a, b = fresh(), fresh(baseline)
        for page in (SG, 0x01):
            a.page(page); b.page(page)
            for ch in range(1, 17):
                for status in (0x90, 0x80):
                    for note in range(0, 128, 1):
                        a.idle(); b.idle()
                        ta = kinds(a.send(status | (ch - 1), note, 100 if status == 0x90 else 0))
                        tb = kinds(b.send(status | (ch - 1), note, 100 if status == 0x90 else 0))
                        if ta != tb:
                            raise AssertionError(('M.CH 16 differs from the baseline', hex(page), ch, hex(status), note, ta, tb))
                        same += 1
        report['baseline'] = dict(build=b.man['revision'], identical_paths=same)

    # 3. The M.CH item -------------------------------------------------------------------------------
    m = fresh()
    if (m.text('arp_item_name', 21), m.text('arp_item_text', 21)) != ('M.CH', '16'):
        raise AssertionError('M.CH name/text')
    stops = []
    m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: stops.append(a), begin=RELEASE_ALL, end=RELEASE_ALL)
    m.setsym('arp_mode', 1, '<i')
    m.send(0x9F, 60, 90)                                         # a melodic note held in the arp
    if m.sym('held_count', '<i') != 1:
        raise AssertionError('arp did not take the MIDI note')
    seen, changes = [], 0
    for direction in [1] * 3 + [-1] * 20 + [1] * 30:
        before = m.text('arp_item_text', 21)
        m.call(m.S['arp_item_step'], 21, direction)
        seen.append(int(m.text('arp_item_text', 21)))
        changes += m.text('arp_item_text', 21) != before
    if min(seen) != 1 or max(seen) != 16 or seen[-1] != 16 or seen[:3] != [16, 16, 16]:
        raise AssertionError(('M.CH bounds', seen))
    if len(stops) != changes or changes != 30 or m.sym('held_count', '<i') != 0:
        raise AssertionError(('M.CH change: all-stop and arp notes forgotten', len(stops), changes))
    m.uc.mem_write(BUF, bytes(8))
    m.call(0x800C1780, SETTINGS, 0x83, BUF, BUF + 4, stack0=0)
    if (m.get(BUF), m.get(BUF + 4)) != (0, 22):                 # 22 = BOUNC (v9.45), drum mode only
        raise AssertionError(('VALUE cursor range', m.get(BUF), m.get(BUF + 4)))
    report['m_ch_item'] = dict(name='M.CH', default=16, range=[1, 16], value_cursor=[0, 22],
                               change_stops_voices_and_clears_arp=True)

    # 4. CCs -----------------------------------------------------------------------------------------
    tune = lambda v: -12 + ((v * 25) >> 7)
    percent = lambda v: (v * 101) >> 7
    drum_cases = 0
    for kit in (1, 12):
        m = fresh()
        m.setsym('kit_mode', kit)
        m.text('arp_item_text', 11)                                # the kit's pads, initialised
        for pad, first in enumerate(PAD_CC):
            for field, offset in ((0, 1), (1, 2), (2, 4)):          # Tune, Decay, Level
                for v in (0, 64, 127):
                    want = bytearray(m.pads(kit))
                    want[pad * 8 + offset] = (tune(v) if field == 0 else percent(v) if field == 1 else v) & 0xFF
                    m.setsym('kit_edit_pad', (pad + 1) % 16)
                    m.setsym('kit_edit_changed', 0)
                    m.cc(16, first + field, v)
                    if m.pads(kit) != bytes(want) or m.sym('kit_edit_pad') != pad or m.sym('kit_edit_changed') != 1:
                        raise AssertionError(('drum pad CC', kit, pad, first + field, v))
                    drum_cases += 1
        if m.poll() != 1 or m.sym('kit_edit_changed') != 0:
            raise AssertionError('a drum CC must redraw the screen')
        for hit in (2, 9):                                         # the last pad heard: a MIDI hit
            m.idle()
            m.send(0x9F, 36 + hit, 100)
            for number, offset in LAST_PAD_CC.items():
                for v in (0, 64, 127):
                    want = bytearray(m.pads(kit))
                    want[hit * 8 + offset] = percent(v)
                    m.setsym('kit_edit_pad', (hit + 5) % 16)
                    m.cc(16, number, v)
                    if m.pads(kit) != bytes(want) or m.sym('kit_edit_pad') != hit:
                        raise AssertionError(('last-pad CC', kit, hit, number, v))
                    drum_cases += 1
    # A CC sent just before a note shapes that hit, exactly as the same setting made by hand.
    renders = []
    for how in ('cc', 'by hand', 'factory'):
        m = fresh()
        m.setsym('kit_mode', 12)
        m.text('arp_item_text', 11)
        if how == 'cc':
            m.cc(16, 22, 40)                                       # pad 1 Level 40
            m.cc(16, 20, 100)                                      # pad 1 Tune +7
        elif how == 'by hand':
            at = m.S['kit_pads'] + 11 * 16 * 8
            m.uc.mem_write(at + 4, bytes([40]))
            m.uc.mem_write(at + 1, bytes([tune(100) & 0xFF]))
        m.send(0x9F, 36, 100)
        renders.append(m.render(12))
    if renders[0] != renders[1] or renders[0] == renders[2]:
        raise AssertionError('a CC before a note must shape that hit')
    report['drum_cc'] = dict(cases=drum_cases, kits=[1, 12], pad_selected=True, redraw=True,
                             cc_then_note_sample_exact=True)

    # Melodic: the knobs' scaling through the stock setter, on the next screen update.
    m = fresh()
    melodic_cases = 0
    for number, sid in MELODIC_CC.items():
        if number == 73:                                           # DUTY: a type that has it (Pulse)
            m.cc(16, 70, 44)
            m.poll()
            if m.setting(0x7B) != 11:
                raise AssertionError('TYPE CC 44 should be Pulse')
        lo, hi = m.setting_range(sid)
        for v in (0, 64, 127, 100, 1):
            want = lo + (((hi - lo + 1) * v) >> 7)
            before = m.setting(sid)
            m.cc(16, number, v)
            if m.setting(sid) != before:
                raise AssertionError(('melodic CC applied outside the UI task', number))
            if m.poll() != 1 or m.setting(sid) != want:
                raise AssertionError(('melodic CC', number, v, m.setting(sid), want))
            melodic_cases += 1
    if m.get(VOICES[0] + 0x70, '<B') != m.setting(0x7B):
        raise AssertionError('TYPE did not reach the voice')
    report['melodic_cc'] = dict(cases=melodic_cases, ccs=sorted(MELODIC_CC), applied_on_screen_update=True)

    # Arp CCs: both modes, A.OCT melodic only; switching ARP on is the VALUE menu's all-stop.
    arp_cases = 0
    for mode in (0, 1):
        m = fresh()
        m.setsym('kit_mode', mode)
        stops = []
        m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: stops.append(a), begin=RELEASE_ALL, end=RELEASE_ALL)
        for number, name in ARP_CC.items():
            for v in (127, 0, 64, 20):
                before = m.sym(name, '<i')
                m.cc(16, number, v)
                m.poll()
                want = {33: (7 * v) >> 7, 34: (7 * v) >> 7, 35: ((7 * v) >> 7) - 3, 36: int(v >= 64)}[number]
                if mode and number == 35:
                    want = before
                if m.sym(name, '<i') != want:
                    raise AssertionError(('arp CC', mode, number, v, m.sym(name, '<i'), want))
                arp_cases += 1
        if not stops:
            raise AssertionError('switching ARP on by CC must all-stop as the menu does')
    report['arp_cc'] = dict(cases=arp_cases, a_oct_melodic_only=True)

    # Everything else changes nothing: other CC numbers, the other mode's CCs, other channels, other pages.
    chart = {c + j for c in PAD_CC for j in range(3)} | set(LAST_PAD_CC) | set(MELODIC_CC) | set(ARP_CC)
    ignored = 0
    for mode in (0, 1):
        m = fresh()
        m.setsym('kit_mode', mode)
        m.text('arp_item_text', 11)
        m.send(0x9F, 40, 100)                                      # a last pad heard, for 114..117
        m.idle()
        base_state = m.state()
        others = [c for c in range(128) if c not in chart | {120, 123}]
        cross = sorted(set(MELODIC_CC) if mode else chart - set(MELODIC_CC) - set(ARP_CC))
        for number in others + cross:
            for v in (0, 127):
                m.cc(16, number, v)
                ignored += 1
        for ch, page in ((1, SG), (10, SG), (15, SG), (16, 0x01), (16, 0x22)):
            m.page(page)
            for number in sorted(chart):
                for v in (0, 127):
                    m.cc(ch, number, v)
                    ignored += 1
        m.page(SG)
        m.poll()
        if m.state() != base_state:
            raise AssertionError(('a CC outside the chart, channel or page changed something', mode))
    report['cc_ignored'] = dict(messages=ignored, every_cc_reached_the_stock_queue=True)

    # CC 123 and 120.
    held = lambda mm: [(v['source'], v['midi'], v['released']) for v in mm.voices() if v['active']]
    m = fresh()                                                    # melodic, ARP off
    m.send(0x9F, 60, 90)
    m.send(0x9F, 64, 90)
    m.call(NOTE_ENGINE, 0, m.pad_note(3), 100, 0, stack0=3)       # a pad held by hand
    if sorted(held(m)) != sorted([(-1, 60, 0), (-1, 64, 0), (3, 0xFF, 0)]):
        raise AssertionError(('setup', held(m)))
    m.cc(15, 123, 0)                                               # another channel: nothing
    m.page(0x01)
    m.cc(16, 123, 0)                                               # another page: nothing
    m.page(SG)
    if any(r for _, _, r in held(m)):
        raise AssertionError('CC 123 off the SG channel or page')
    m.cc(16, 123, 0)
    if sorted((s, r) for s, _, r in held(m)) != [(-1, 1), (-1, 1), (3, 0)]:
        raise AssertionError(('CC 123 melodic', held(m)))
    m = fresh()                                                    # melodic, ARP on
    m.setsym('arp_mode', 1, '<i')
    m.send(0x9F, 60, 90)
    m.send(0x9F, 67, 90)
    m.render(2)
    if m.sym('held_count', '<i') != 2 or m.sym('arp_run', '<i') != 1:
        raise AssertionError('arp setup')
    m.cc(16, 123, 0)
    m.render(2)
    if m.sym('held_count', '<i') != 0 or m.sym('arp_run', '<i') != 0:
        raise AssertionError('CC 123 must stop the arp')
    m = fresh()                                                    # drum mode
    m.setsym('kit_mode', 1)
    m.send(0x9F, 36, 100)
    m.send(0x9F, 40, 100)
    m.call(NOTE_ENGINE, 0, m.pad_note(7), 100, 0, stack0=7)
    if m.sym('kit_midi_down', '<H') != 0b10001:
        raise AssertionError(('MIDI-held pads', m.sym('kit_midi_down', '<H')))
    m.cc(16, 123, 0)
    if sorted((s, r) for s, _, r in held(m)) != [(0, 1), (4, 1), (7, 0)] or m.sym('kit_midi_down', '<H'):
        raise AssertionError(('CC 123 drums', held(m)))
    m = fresh()                                                    # 120: every voice fades out
    stops = []
    m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: stops.append(a), begin=RELEASE_ALL, end=RELEASE_ALL)
    m.send(0x9F, 60, 90)
    m.call(NOTE_ENGINE, 0, m.pad_note(3), 100, 0, stack0=3)
    m.cc(16, 120, 0)
    if [r for _, _, r in held(m)] != [1, 1] or len(stops) != 1:
        raise AssertionError(('CC 120', held(m), stops))
    report['all_off'] = dict(cc123='MIDI notes released, pad notes kept, arp stopped (melodic and drum)',
                             cc120='every voice fades out (all-stop)', other_channel_or_page='ignored')

    report.update(passed=True, app1_sha256=m.man['sha256'], revision=m.man['revision'])
    print(json.dumps(report))


if __name__ == '__main__':
    main()
