"""Checks for the chromatic scales build (build_chroma.py).

usage: python synth/test_chroma.py OUT_DIR [SECTIONS]      (unicorn, keystone, capstone on PYTHONPATH)

SECTIONS: a comma list of static, tables, ranges, value, names, pads, record, lights, push (default: all).

Reads OUT_DIR/manifest.json for the parent APP1. Static checks first: only the header's scatter pointer, the
eleven code sites, the two mask lists and the appended tail differ from the parent; the guards and the
displaced bytes hold on the parent; nothing reaches into them. Then the parent and the new image are booted in Unicorn the way their
scatter loader does it, with the boot's static constructors run (the RTOS under them stubbed: its pool by a
bump allocator, object creation by an id), and the TOP page object made by its registry handler as on page
entry. Real stock code runs: the project setter (0x800ded18) with its range method and listeners, the getter,
the SCALE label formatter (0x800c5168), the UI task's dispatcher (0x8003b530) with TOP's registry handler and
DOOM OS ED5E's page filter, the page pad handler and the stock pad note, SMPL TASK's pad events (0x80050be0)
with MIDI out (0x800549e0, logged as it is called) and the pattern recorder (0x800bd5a0 -> 0x80030700,
logged), the pad lights (0x80025ea8 -> 0x800d4910, logged). Modelled: the voices (note-on 0x800aec48 and
note-off 0x800c0a80 are logged, not run), the pad-event ring (0x800bef10: each event is taken from there and
handed to SMPL TASK's handler), drawing, the card.

Checks:
- tables: after every SHIFT, SCALE and ROOT change through the setter, all five chromatic pad tables hold
  note(T[p] - shift) + shift, note() an independent model of the Sound Generator's fold; with Chrom and a
  stock shift they hold stock's T, as on the parent;
- ranges: SHIFT's range keeps every pad within -12..+27 for every scale and root; the setter clamps to it;
  SCALE's range is 0-33 in chromatic mode and the parent's elsewhere;
- value: VALUE press in chromatic mode steps 0-33 and round; outside it, as the parent (0-6);
- names: the SCALE label in chromatic mode is stock's for 0-6 and the 34 scales' labels for 7-33; outside it,
  as the parent;
- pads (the chromatic page 0x18): every pad through the page and SMPL TASK: MIDI out sends 48 + the model's
  note, the note-off sends the same note (also below -13), one voice note-on and note-off each; with Chrom
  and a stock shift the pads within -12..+12 are the parent's, and the pads above +12, which the parent's page
  leaves silent, play;
- record: while recording, chromatic notes within -13..+18 are recorded with the note byte (note + 13), as
  the parent does; notes outside are not recorded;
- lights (the chromatic page 0x18): with Chrom and a stock shift the pads within -12..+12 light as on the
  parent, and the pads above +12, which the parent leaves dark, light like the others above the pitch; with
  scales, roots and shifts every pad lights as the parent lights a scale note there (above, at or below the
  sample's pitch), none dark;
- push (test2, the chromatic page): VALUE tapped steps the next scale at its release; VALUE held and turned
  moves the scale one a turn, round, and steps nothing at the release; with SHIFT held too, the key, round; the
  popups name them and the pads follow; a turn without VALUE held, ROLL + VALUE and VALUE outside chromatic
  mode are the parent's.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_HOOK_CODE
from unicorn import arm_const as ar

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_chroma import (GUARDS, SITES, TABLES, MASK_LISTS, VTABLE, KNOWN_SLOTS, STOCK_T, LO, HI, Runtime,  # noqa
                          scatter, decompress, branches_into, scales, mask)

FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
HEAP = 0x32000000
KERNEL = {0x310C: 1, 0x22A4: 1, 0x32B8: 0}                 # RTOS object creation in the constructors: an id
SCREEN = (0x8006C088, 0x8006BD48, 0x8015F3A8, 0x800D8020, 0x800C1CC0)  # drawing: no display here
NOPS = (0xE668, 0x800D30A4)                              # debug prints, the SMPL TASK flag
FILE_OPEN = 0x800DEC60                                   # no card here: every file is missing
CTORS, NCTORS = 0x8383A30C, 70
STACK, RET, EVENT, SCRATCH = 0x30010000, 0x3001F000, 0x30095000, 0x30096000
UI_DISPATCH, PAGE_ID, PAGE_LIVE, PREFILTER, KEY_PAIRS = 0x8003B530, 0x80245880, 0x8024587A, 0x82DFD318, 0x80B119DC
TOP_REGISTRY, TOP_PAGE, DOOM_FILTER = 0x8005EDA8, 0x80CFD350, 0x6031C8F8
CHROMA_PAGE, CHROMA_REGISTRY = 0x18, 0x80062A10           # the page whose VALUE press steps the scale (0x8011247e)
POPUP = 0x800D3FF0
PAD_DISPATCH, SOUNDING, POST = 0x800BEF10, 0x800D8C08, 0x800E25C0
PROJECT, SETTER, RANGE, LABEL = 0x82E009D0, 0x800DED18, 0x800D35F0, 0x800C5168
SMPL, LOADED = 0x82E2CD08, 0x82E495E4
CONSUMER, NOTE_ON, NOTE_OFF, MIDI_OUT, RECORD, SEQ_STATE = (0x80050BE0, 0x800AEC48, 0x800C0A80, 0x800549E0,
                                                             0x80030700, 0x80591F20)
LIGHTS, LIGHT, LIGHT_REQ = 0x80025EA8, 0x800D4910, 0x802496F0
EV_KEY, EV_KEY_UP, EV_ENCODER, EV_PAD, EV_PAD_UP = 5, 6, 7, 0x10, 0x11
KEY_SHIFT, KEY_ROLL, KEY_VALUE = 0x2A, 0x21, 0x31
UI_HELD = 0x80592598 + 8
ROOTS = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'G#', 'A', 'Bb', 'B']
P_CHROMATIC, P_SHIFT, P_SOURCE, P_SCALE, P_ROOT = 0xBF, 0xC0, 0xC1, 0xF1, 0xF2
F_SHIFT, F_SCALE, F_ROOT = PROJECT + 0x2C, PROJECT + 0x118, PROJECT + 0x11C
SG_PAGE = 0x1E
ROWS = scales()
fails = []
cases = [0]


def check(cond, what):
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        fails.append(what)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


# ---------------------------------------------------------------- the model
def scale_notes(scale, root):
    """Every note of the scale from -96 to +96 (the sample's own pitch is 0)."""
    m = mask(ROWS[scale]) if 0 < scale < len(ROWS) else 0xFFF
    return [n for n in range(-96, 97) if m >> ((n - root) % 12) & 1]


def model(scale, root, shift):
    """(T' for the 16 pads, the pads' notes, SHIFT's range): the Sound Generator's fold, written apart from it."""
    notes = scale_notes(scale, root)
    a = notes.index(min(n for n in notes if n >= 0))
    top = len([n for n in notes if notes[a] < n <= HI])
    bottom = -len([n for n in notes if LO <= n < notes[a]])
    played = []
    for t in STOCK_T:
        k = max(bottom, min(top, t - shift))
        played.append(notes[a + k])
    return [n + shift for n in played], played, (7 - top, -8 - bottom)


# ---------------------------------------------------------------- the machine
class Machine:
    def __init__(self, img, sym=None):
        self.sym = sym or {}
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for base, size in ((0x0, 0x20000), (0x20000000, 0x80000), (0x20200000, 0x100000), (0x80000000, 0x4000000),
                           (0x30000000, 0x100000), (0x60000000, 0x400000), (0x400E8000, 0x2000),
                           (0xE0000000, 0x100000), (0x40000000, 0xE8000), (0x400EA000, 0x316000),
                           (HEAP, 0x1000000)):
            uc.mem_map(base, size, UC_PROT_ALL)
        uc.mem_write(FLASH, img)
        for load, dst, size, handler in scatter(img):
            if handler == COPY:
                uc.mem_write(dst, img[load - FLASH:load - FLASH + size])
            elif handler == DECOMPRESS:
                uc.mem_write(dst, decompress(img[load - FLASH:], size))
            elif handler == ZERO:
                uc.mem_write(dst, bytes(size))
        uc.reg_write(ar.UC_ARM_REG_C1_C0_2, uc.reg_read(ar.UC_ARM_REG_C1_C0_2) | (0xF << 20))
        uc.reg_write(ar.UC_ARM_REG_FPEXC, 0x40000000)
        uc.mem_write(RET, b'\x00\xbf\x00\xbf')
        self.mprofile()
        self.heap = HEAP
        self.clear()
        uc.hook_add(UC_HOOK_CODE, self._malloc, None, begin=0x800E2C68, end=0x800E2C68)
        uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=0x800E2CA8, end=0x800E2CA8)
        for a, v in KERNEL.items():
            uc.hook_add(UC_HOOK_CODE, self._value, v, begin=a, end=a)
        for a in SCREEN + NOPS:
            uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=a, end=a)
        uc.hook_add(UC_HOOK_CODE, self._value, -1, begin=FILE_OPEN, end=FILE_OPEN)
        uc.hook_add(UC_HOOK_CODE, self._popup, None, begin=POPUP, end=POPUP)
        for fn in struct.unpack(f'<{NCTORS}I', bytes(uc.mem_read(CTORS, 4 * NCTORS))):
            self.call(fn & ~1 | 1, count=50_000_000)
        uc.hook_add(UC_HOOK_CODE, self._pad_event, None, begin=PAD_DISPATCH, end=PAD_DISPATCH)
        uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=SOUNDING, end=SOUNDING)
        uc.hook_add(UC_HOOK_CODE, self._log, 'post', begin=POST, end=POST)
        uc.hook_add(UC_HOOK_CODE, self._log, 'on', begin=NOTE_ON, end=NOTE_ON)
        uc.hook_add(UC_HOOK_CODE, self._log, 'off', begin=NOTE_OFF, end=NOTE_OFF)
        uc.hook_add(UC_HOOK_CODE, self._midi, None, begin=MIDI_OUT, end=MIDI_OUT)
        uc.hook_add(UC_HOOK_CODE, self._record, None, begin=RECORD, end=RECORD)
        uc.hook_add(UC_HOOK_CODE, self._light, None, begin=LIGHT, end=LIGHT)
        self.w32(PREFILTER, 0xFFFFFFFF)                 # no mode holds the keys
        uc.mem_write(KEY_PAIRS, b'\xff' * 0x80)         # no key pairs (memset -1 at boot)
        uc.mem_write(EVENT, struct.pack('<6h', 1, 0, 0, 0, 0, 0))
        self.call(TOP_REGISTRY, EVENT, count=20_000_000)  # the TOP page object, as on page entry
        uc.mem_write(PAGE_ID, struct.pack('<H', 1))
        uc.mem_write(PAGE_LIVE, struct.pack('<H', 1))
        for pad in range(160):
            self.load_pad(pad)
        self.clear()

    def mprofile(self):
        """M-profile special registers (the RTOS's critical sections): MSR -> nop.w, MRS -> mov.w rd, #0."""
        for base, size in ((0x400, 0x1F800), (0x80000000, 0x240000)):
            code = bytearray(self.uc.mem_read(base, size))
            for i in range(0, size - 4, 2):
                h1, h2 = code[i] | code[i + 1] << 8, code[i + 2] | code[i + 3] << 8
                if (h1 & 0xFFF0) == 0xF380 and (h2 & 0xFF00) == 0x8800 and 0x10 <= (h2 & 0xFF) <= 0x14:
                    code[i:i + 4] = bytes.fromhex('aff30080')
                elif h1 == 0xF3EF and (h2 & 0xF000) == 0x8000 and 0x10 <= (h2 & 0xFF) <= 0x14:
                    code[i:i + 4] = bytes([0x4F, 0xF0, 0x00, (h2 >> 8) & 15])
            self.uc.mem_write(base, bytes(code))

    def clear(self):
        self.events, self.popups, self.log, self.midi, self.records, self.lights = [], [], [], [], [], []

    # ---- plumbing ----
    def regs(self, n=4):
        return [self.uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}')) for k in range(n)]

    def _ret(self, value=0):
        self.uc.reg_write(ar.UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.uc.reg_write(ar.UC_ARM_REG_PC, self.uc.reg_read(ar.UC_ARM_REG_LR))

    def _malloc(self, uc, a, size, _):
        n = (uc.reg_read(ar.UC_ARM_REG_R0) + 15) & ~7
        at = self.heap
        self.heap += n + 8
        uc.mem_write(at, bytes(n + 8))
        self._ret(at + 8)

    def _value(self, uc, a, size, value):
        self._ret(value)

    def _popup(self, uc, a, size, _):
        text = bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R0), 64)).split(b'\0')[0].decode('latin-1')
        self.popups.append(text)

    def _pad_event(self, uc, a, size, _):
        """The pad-event ring: SMPL TASK takes the event (6 bytes) from here."""
        self.events.append(bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R0), 8)))
        self._ret(0)

    def _log(self, uc, a, size, what):
        sp = uc.reg_read(ar.UC_ARM_REG_SP)
        self.log.append((what,) + tuple(s32(r) for r in self.regs(4)) +
                        tuple(s32(x) for x in struct.unpack('<3I', bytes(uc.mem_read(sp, 12)))))
        self._ret(0)

    def _midi(self, uc, a, size, _):
        r = self.regs(3)
        self.midi.append((s32(r[0]), s32(r[1]), s32(r[2])))
        self._ret(0)

    def _record(self, uc, a, size, _):
        self.records.append(struct.unpack('<2I', bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R0), 8))))
        self._ret(0)

    def _light(self, uc, a, size, _):
        r = self.regs(3)
        self.lights.append((s32(r[0]), s32(r[1]), r[2]))
        self._ret(0)

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack('<I', self.uc.mem_read(a, 4))[0]

    def call(self, fn, *args, count=5_000_000, stack=()):
        uc = self.uc
        for k, v in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), v & 0xFFFFFFFF)
        sp = STACK - 4 * len(stack) - 0x40
        for k, v in enumerate(stack):
            self.w32(sp + 4 * k, v)
        uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        uc.reg_write(ar.UC_ARM_REG_SP, sp)
        uc.emu_start(fn | 1, RET, count=count)
        if uc.reg_read(ar.UC_ARM_REG_PC) != RET:
            raise RuntimeError(f'{fn:#x} did not return (pc {uc.reg_read(ar.UC_ARM_REG_PC):#x})')
        return uc.reg_read(ar.UC_ARM_REG_R0)

    def load_pad(self, pad):
        e = LOADED + pad * 36
        self.w32(e + 8, 2)
        self.w32(e + 0x18, 0)
        self.w32(e + 0x1C, 0x100000)
        self.w32(SMPL + 0xD0 + pad * 0xAC, 1)

    # ---- the project ----
    def set(self, param, value):
        self.call(SETTER, PROJECT, param, value, 0xFFFFFFFF, count=20_000_000)

    def get(self, param):
        return s32(self.call(0x800DDA38, PROJECT, param, 0xFFFFFFFF))

    def range(self, param):
        self.call(RANGE, PROJECT, param, SCRATCH, SCRATCH + 4, stack=(0xFFFFFFFF,))
        return s32(self.r32(SCRATCH)), s32(self.r32(SCRATCH + 4))

    def label(self, value):
        self.uc.mem_write(SCRATCH + 0x40, bytes(64))
        self.call(LABEL, PROJECT, SCRATCH + 0x40, P_SCALE, value, stack=(0xFFFFFFFF,))
        return bytes(self.uc.mem_read(SCRATCH + 0x40, 32)).split(b'\0')[0].decode('latin-1')

    def tables(self):
        return [list(struct.unpack('<16i', bytes(self.uc.mem_read(t, 64)))) for t in TABLES]

    def chromatic(self, on, source=0):
        self.set(P_CHROMATIC, 1 if on else 0)
        if on:
            self.set(P_SOURCE, source)

    # ---- the panel ----
    def dispatch(self, kind, a1=0, a2=0):
        self.uc.mem_write(EVENT, struct.pack('<6h', kind, a1, a2, 0, 0, 0))
        return s32(self.call(UI_DISPATCH, EVENT, count=20_000_000))

    def open_page(self, pid, registry):
        """A page made by its registry handler as on page entry, then the current page."""
        self.uc.mem_write(EVENT, struct.pack('<6h', 1, 0, 0, 0, 0, 0))
        self.call(registry, EVENT, count=20_000_000)
        self.uc.mem_write(PAGE_ID, struct.pack('<H', pid))
        self.uc.mem_write(PAGE_LIVE, struct.pack('<H', pid))

    def tap(self, key):
        self.dispatch(EV_KEY, key)
        self.dispatch(EV_KEY_UP, key)

    def pad(self, index, vel=100):
        """A pad pressed (vel) or let go (0) through the UI, then each event it posts through SMPL TASK."""
        start = len(self.events)
        self.dispatch(EV_PAD if vel else EV_PAD_UP, index, vel)
        for ev in self.events[start:]:
            self.uc.mem_write(SCRATCH + 0x100, ev)
            self.call(CONSUMER, SCRATCH + 0x100, count=20_000_000)
        return self.events[start:]

    def paint(self):
        self.lights = []
        self.uc.mem_write(LIGHT_REQ, struct.pack('<H', 2))
        self.call(LIGHTS, LIGHT_REQ, count=20_000_000)
        return list(self.lights)


# ---------------------------------------------------------------- checks
def static_checks(out, man, img, parent):
    check(sha(img) == man['sha256'] and len(img) == man['size'], 'APP1 matches its manifest')
    check(sha((out / 'SP404MKII_APP0.bin').read_bytes()) == man['app0_sha256'] ==
          '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23', 'APP0 is stock 5.52')
    sums = (out / 'SHA256SUMS.txt').read_text(encoding='utf-8').split()
    check(dict(zip(sums[1::2], sums[0::2])) == {n: sha((out / n).read_bytes()) for n in (
        'SP404MKII_APP0.bin', 'SP404MKII_APP1.bin', 'manifest.json')}, 'SHA256SUMS.txt matches the files')
    rows, prow = scatter(img), scatter(parent)
    blob_row = [FLASH + man['blob_file_offset'], man['blob_base'], man['blob_size'], COPY]
    check(rows == prow + [blob_row], 'scatter table: the parent\'s rows plus one copy row for the module')

    def file_off(addr):
        return [load - FLASH + addr - dst for load, dst, n, fn in prow if fn == COPY and load and dst <= addr < dst + n][0]
    allowed = set(range(0x80, 0x88))
    for at, original, *_ in SITES:
        allowed |= set(range(file_off(at), file_off(at) + len(original)))
    for at, _ in MASK_LISTS:
        allowed |= set(range(file_off(at), file_off(at) + 24))
    for at, *_ in VTABLE:
        allowed |= set(range(file_off(at), file_off(at) + 4))
    diff = [i for i in range(len(parent)) if img[i] != parent[i]]
    check(set(diff) <= allowed, f'only the scatter pointer, the {len(SITES)} code sites, the two mask lists and the '
                                f'chromatic page\'s two vtable slots change inside the parent ({len(diff)} bytes)')
    rt, nrt = Runtime(parent), Runtime(img)
    check(all(sha(rt.read(s, e - s)) == d for s, e, d, w in GUARDS), f'{len(GUARDS)} guards hold on the parent')
    e = man['entries']
    ok = []
    for p, (at, original, what, kind, entry) in zip(man['patches'], SITES):
        got = nrt.read(at, len(original))
        ok.append(rt.read(at, len(original)) == original and got.hex() == p['replacement_hex'] and p['address'] == at)
        if kind in ('jump', 'call'):
            lo, hi = e[entry] & 0xFFFF, e[entry] >> 16
            want = struct.pack('<4H', 0xF240 | (lo >> 12) | ((lo >> 11) & 1) << 10,
                               ((lo >> 8) & 7) << 12 | 12 << 8 | lo & 0xFF,
                               0xF2C0 | (hi >> 12) | ((hi >> 11) & 1) << 10,
                               ((hi >> 8) & 7) << 12 | 12 << 8 | hi & 0xFF)
            ok[-1] = ok[-1] and got[:8] == want and got[8:10] == (b'\x60\x47' if kind == 'jump' else b'\xe0\x47') \
                and got[10:] == b'\x00\xbf' * ((len(original) - 10) // 2)
    check(all(ok), f'each site: the parent\'s instructions there, the module\'s jump or call (or the two '
                   f'instructions) here ({ok})')
    inside = [(hex(a), branches_into(rt, a + 1, a + len(o))) for a, o, *_ in SITES]
    check(not any(x for _, x in inside), f'nothing branches into the displaced bytes ({inside})')
    masks = []
    for at, _ in MASK_LISTS:
        for k, p in enumerate(struct.unpack('<6I', nrt.read(at, 24))):
            want = [1 if n in ROWS[k + 1]['notes'] else 0 for n in range(12)]
            masks.append(list(nrt.read(p - 12, 24)) == want + want and p == e['chroma_masks'] + 24 * k + 12)
    check(all(masks), 'the two mask lists point at the module\'s masks: scales 1-6 of scales.json (= stock\'s), a '
                      'period before each')
    check(all(rt.word(at) == stock and nrt.word(at) == e[entry] for at, stock, entry, _ in VTABLE),
          'the chromatic page\'s key press and release slots: stock\'s on the parent, chroma_key and chroma_key_up here')
    module = nrt.read(man['blob_base'], man['blob_size'])
    slot = man['slot']
    check(module == img[man['blob_file_offset']:man['blob_file_offset'] + man['blob_size']] and
          slot[0] == man['blob_base'] and man['blob_base'] + man['blob_size'] <= slot[1] and
          not any(max(lo, slot[0]) < min(hi, slot[1]) for _, lo, hi in KNOWN_SLOTS),
          f'the module ({man["blob_size"]} bytes) fits its slot {slot[0]:#x}..{slot[1]:#x}, clear of every other '
          f'fork module')
    check(all(struct.unpack('<16i', rt.read(t, 64)) == STOCK_T for t in TABLES),
          'the five chromatic pad tables are stock\'s on the parent')


def table_checks(img, parent, man):
    m, p = Machine(img, man['entries']), Machine(parent)
    stock = [list(STOCK_T)] * 5
    for x in (m, p):
        x.chromatic(True)
    same = []
    for s in range(-8, 5):
        for x in (m, p):
            x.set(P_SHIFT, s)
        same.append(m.tables() == stock == p.tables() and m.get(P_SHIFT) == s == p.get(P_SHIFT))
    check(all(same), 'Chrom, every stock shift (-8..4): the five tables hold stock\'s T, as on the parent')
    bad = []
    n = 0
    for scale in range(34):
        m.set(P_SCALE, scale)
        for root in (0, 2, 5, 7, 11):
            m.set(P_ROOT, root)
            lo, hi = model(scale, root, 0)[2]
            for shift in sorted({lo, hi, 0, (lo + hi) // 2, lo + 1, hi - 1}):
                m.set(P_SHIFT, shift)
                got = m.get(P_SHIFT)
                want = model(scale, root, got)[0]
                n += 1
                if got != shift and lo <= shift <= hi or any(t != want for t in m.tables()):
                    bad.append((scale, root, shift, got, m.tables()[0], want))
    check(not bad, f'every scale x roots 0, 2, 5, 7, 11 x shifts across the range ({n} settings): after each change '
                   f'through the setter all five tables hold the model\'s fold ({bad[:2]})')
    # a scale or root change brings a shift outside the new range back to its end: 16 notes within LO..HI
    ends = []
    for start, scale, root in ((4, 6, 0), (-20, 6, 0), (4, 29, 5), (-20, 17, 11)):
        m.set(P_SCALE, 0)
        m.set(P_ROOT, 0)
        m.set(P_SHIFT, start)
        m.set(P_SCALE, scale)
        m.set(P_ROOT, root)
        lo, hi = model(scale, root, 0)[2]
        got = m.get(P_SHIFT)
        notes = model(scale, root, got)[1]
        ends.append(got == min(max(start, lo), hi) and m.tables()[0] == model(scale, root, got)[0] and
                    len(set(notes)) == 16 and min(notes) >= LO and max(notes) <= HI)
    check(all(ends), f'Chrom at shift 4 or -20, then a sparser scale or another root: the shift comes back to the '
                     f'new range\'s end, 16 notes within {LO}..{HI} ({ends})')
    # the parent: tables never change
    p.set(P_SCALE, 5)
    p.set(P_ROOT, 3)
    p.set(P_SHIFT, 2)
    check(p.tables() == stock, 'on the parent the tables stay stock\'s whatever the settings')


def range_checks(img, parent, man):
    m, p = Machine(img, man['entries']), Machine(parent)
    bad = []
    for scale in range(34):
        m.set(P_SCALE, scale)
        for root in range(12):
            m.set(P_ROOT, root)
            want = model(scale, root, 0)[2]
            got = m.range(P_SHIFT)
            notes = scale_notes(scale, root)
            a = notes.index(min(n for n in notes if n >= 0))
            top = [notes[a + 7 - s] for s in (want[0], want[0] - 1)]       # the top pad at the low end, one past
            bottom = [notes[a - 8 - s] for s in (want[1], want[1] + 1)]    # the bottom pad at the high end, one past
            if got != want or not (top[0] <= HI < top[1]) or not (bottom[1] < LO <= bottom[0]):
                bad.append((scale, root, got, want, top, bottom))
    check(not bad, f'SHIFT\'s range for every scale and root keeps every pad within {LO}..{HI} ({bad[:3]})')
    m.set(P_SCALE, 0)
    m.set(P_ROOT, 0)
    clamp = []
    for v, want in ((-40, -20), (-20, -20), (4, 4), (40, 4)):
        m.set(P_SHIFT, v)
        clamp.append(m.get(P_SHIFT) == want)
    check(all(clamp) and m.range(P_SHIFT) == (-20, 4) and p.range(P_SHIFT) == (-8, 4),
          f'Chrom: SHIFT\'s range is -20..4 (stock -8..4); a shift set outside it comes back to its end ({clamp})')
    turns = []
    for x in (m, p):
        x.open_page(CHROMA_PAGE, CHROMA_REGISTRY)
        x.chromatic(True)
        x.set(P_SCALE, 0)
        x.set(P_SHIFT, 0)
        up, down = [], []
        for _ in range(9):
            x.dispatch(EV_ENCODER, 0, 1)
            up.append(x.get(P_SHIFT))
        for _ in range(12):
            x.dispatch(EV_ENCODER, 0, -1)
            down.append(x.get(P_SHIFT))
        x.dispatch(EV_KEY, KEY_SHIFT)
        x.dispatch(EV_ENCODER, 0, 1)
        fine = x.get(P_SHIFT)
        x.dispatch(EV_KEY_UP, KEY_SHIFT)
        turns.append((up, down, fine))
    (mu, md, mf), (pu, pd, pf) = turns
    check(mu == pu == [4] * 9 and md == [0, -4, -8, -12, -16, -20, -20, -20, -20, -20, -20, -20] and mf == -19 and
          pd[-1] == -8 and pf == -7 and md[:3] == pd[:3],
          f'VALUE turns move the pads a row (4), SHIFT + VALUE one, now from -20 to 4 (stock -8 to 4) '
          f'({mu}, {md}; parent {pu}, {pd})')
    for x in (m, p):
        x.chromatic(False)
    off = m.range(P_SCALE) == p.range(P_SCALE)
    for x in (m, p):
        x.chromatic(True)
    on = m.range(P_SCALE) == (0, 33)
    for x in (m, p):
        x.uc.mem_write(PAGE_ID, struct.pack('<H', SG_PAGE))
    sg = m.range(P_SCALE) == p.range(P_SCALE) == (0, 33)
    check(off and on and sg, f'SCALE\'s range: 0-33 in chromatic mode; the parent\'s outside it '
                             f'({p.range(P_SCALE)} on the Sound Generator page)')


def value_checks(img, parent, man):
    m, p = Machine(img, man['entries']), Machine(parent)
    for x in (m, p):
        x.open_page(CHROMA_PAGE, CHROMA_REGISTRY)
        x.chromatic(False)
    seq_m, seq_p = [], []
    for _ in range(9):
        m.tap(KEY_VALUE)
        p.tap(KEY_VALUE)
        seq_m.append(m.get(P_SCALE))
        seq_p.append(p.get(P_SCALE))
    check(seq_m == seq_p and len(set(seq_p)) > 1, f'VALUE press outside chromatic mode: as the parent ({seq_m})')
    for x in (m, p):
        x.chromatic(True)
        x.set(P_SCALE, 0)
    seq = []
    for _ in range(35):
        m.tap(KEY_VALUE)
        seq.append(m.get(P_SCALE))
    check(seq == list(range(1, 34)) + [0, 1] and m.tables()[0] == model(1, m.get(P_ROOT), m.get(P_SHIFT))[0],
          f'VALUE press in chromatic mode: 1, 2 .. 33, 0, 1, and the pads follow ({seq})')


def name_checks(img, parent, man):
    m, p = Machine(img, man['entries']), Machine(parent)
    for x in (m, p):
        x.chromatic(False)
    off = [m.label(v) for v in range(34)] == [p.label(v) for v in range(34)]
    for x in (m, p):
        x.chromatic(True)
    got = [m.label(v) for v in range(34)]
    stock = [p.label(v) for v in range(7)]
    want = stock + [r['label'] for r in ROWS[7:]]
    check(off and got == want, f'the SCALE label: in chromatic mode stock\'s 0-6, then the scales\' ({got[5:10]}); '
                               f'outside it the parent\'s')


def pad_events(x, pads):
    out = []
    for i in pads:
        x.clear()
        x.pad(i, 100)
        on = (list(x.midi), [l for l in x.log if l[0] == 'on'])
        x.clear()
        x.pad(i, 0)
        out.append((i, on, (list(x.midi), [l for l in x.log if l[0] == 'off'])))
    return out


def midi_note(side):
    """The note of a press's or release's only MIDI out call, or None."""
    return side[0][0][1] if len(side[0]) == 1 else None


def pad_checks(img, parent, man):
    m, p = Machine(img, man['entries']), Machine(parent)
    for x in (m, p):
        x.open_page(CHROMA_PAGE, CHROMA_REGISTRY)
        x.chromatic(True, source=3)
    same = []
    for s in (-8, -5, 0, 4):
        for x in (m, p):
            x.set(P_SHIFT, s)
        a, b = pad_events(m, range(16)), pad_events(p, range(16))
        notes = [t - s for t in STOCK_T]
        same.append(all(a[i] == b[i] and a[i][1][0] for i in range(16) if -12 <= notes[i] <= 12) and
                    all(not b[i][1][0] and not b[i][1][1] and midi_note(a[i][1]) == notes[i] == midi_note(a[i][2])
                        for i in range(16) if notes[i] > 12))
    check(all(same), 'Chrom at shifts -8, -5, 0, 4: every pad within -12..+12 sends the parent\'s MIDI out, note-on '
                     'and note-off; the pads above +12, which the parent\'s chromatic page leaves silent, play '
                     f'their notes ({same})')
    m.set(P_SHIFT, 0)
    got = pad_events(m, range(16))
    sample = [midi_note(on) for _, on, _ in got]
    bad = []
    for scale, root, shift in ((1, 0, 0), (6, 9, 0), (5, 2, -3), (17, 0, -10), (33, 4, 0), (12, 7, -20), (0, 0, 4),
                               (0, 0, -20)):
        m.set(P_SCALE, scale)
        m.set(P_ROOT, root)
        m.set(P_SHIFT, shift)
        shift = m.get(P_SHIFT)
        want = model(scale, root, shift)[1]
        for (i, on, off), note in zip(pad_events(m, range(16)), [want[k] for k in range(16)]):
            ok = len(on[0]) == 1 and on[0][0][1] == note and len(off[0]) == 1 and off[0][0][1] == note and \
                off[0][0][2] == 0 and len(on[1]) == 1 and len(off[1]) == 1
            if not ok:
                bad.append((scale, root, shift, i, note, on, off))
    check(not bad and sample == list(STOCK_T),
          f'scales, roots and shifts (to -12 and +27): every pad\'s MIDI out note-on and note-off carry the model\'s '
          f'note, one voice note-on and note-off each ({bad[:2]})')
    m.set(P_SCALE, 0)
    m.set(P_SHIFT, -20)
    top = pad_events(m, [3])[0]
    m.set(P_SHIFT, 4)
    low = pad_events(m, [12])[0]
    check(midi_note(top[1]) == 27 == midi_note(top[2]) and midi_note(low[1]) == -12 == midi_note(low[2]),
          f'pad 4 at shift -20 plays +27, pad 13 at shift 4 plays -12: MIDI out\'s note-on and note-off carry them '
          f'({top[1][0]}, {top[2][0]}, {low[1][0]}, {low[2][0]})')


def record_checks(img, parent, man):
    m, p = Machine(img, man['entries']), Machine(parent)
    for x in (m, p):
        x.open_page(CHROMA_PAGE, CHROMA_REGISTRY)
        x.chromatic(True, source=3)
        x.w32(SEQ_STATE, 1)
    same = []
    for s in (-8, 0, 4):
        got = {}
        for x in (m, p):
            x.set(P_SHIFT, s)
            got[x] = []
            for i in range(16):
                x.records = []
                x.pad(i, 100)
                x.pad(i, 0)
                got[x].append(list(x.records))
        notes = [t - s for t in STOCK_T]
        same.append(all(got[m][i] == got[p][i] and len(got[m][i]) == 2 for i in range(16) if notes[i] <= 12) and
                    all(not got[p][i] and len(got[m][i]) == 2 and (got[m][i][0][0] >> 24 & 0x7F) == notes[i] + 13
                        for i in range(16) if notes[i] > 12))
    check(all(same), f'recording, Chrom at shifts -8, 0, 4: every pad within -12..+12 is recorded as on the parent; '
                     f'the pads above +12 (silent on the parent\'s page) are recorded with their note byte ({same})')
    m.set(P_SCALE, 0)
    m.set(P_SHIFT, -20)
    m.records = []
    kept, notes = [], model(0, 0, -20)[1]
    for i in range(16):
        before = len(m.records)
        m.pad(i, 100)
        m.pad(i, 0)
        kept.append(len(m.records) - before)
    want = [2 if -13 <= n <= 18 else 0 for n in notes]
    bytes_ = [w[0] >> 24 & 0x7F for w in m.records]
    check(kept == want and all((b - 13) in notes for b in bytes_),
          f'recording at shift -20 (notes {min(notes)}..{max(notes)}): pads within -13..+18 recorded with their '
          f'note byte, the rest not ({kept})')


def light_checks(img, parent, man):
    m, p = Machine(img, man['entries']), Machine(parent)
    for x in (m, p):
        x.open_page(CHROMA_PAGE, CHROMA_REGISTRY)      # the chromatic page: its pads light the chromatic way
        x.chromatic(True, source=3)
    def last(lights):
        return [dict((pad, c) for pad, mode, c in lights if 0 <= pad < 16).get(i) for i in range(16)]
    a, b = m.paint(), p.paint()
    check(a == b and len(a) >= 16, f'Chrom at shift 0: the pad lights are the parent\'s ({len(a)} light calls)')
    stock = last(b)
    up, home, down = stock[0], stock[4], stock[8]          # the parent's lights for +4, 0 and -4
    check(len({up, home, down, 0}) == 4, f'the parent lights a chromatic pad above, at and below the sample\'s pitch '
                                         f'differently ({up:#x}, {home:#x}, {down:#x})')

    def want(notes):
        return [home if n == 0 else up if 0 < n <= HI else down if LO <= n < 0 else 0 for n in notes]
    same, bad = [], []
    for s in range(-8, 5):
        for x in (m, p):
            x.set(P_SHIFT, s)
        lm, lp = last(m.paint()), last(p.paint())
        notes = [t - s for t in STOCK_T]
        same.append(all(lm[i] == lp[i] for i in range(16) if -12 <= notes[i] <= 12) and
                    all(lp[i] == 0 and lm[i] == up for i in range(16) if notes[i] > 12))
    check(all(same), 'Chrom, every stock shift: the pads within -12..+12 light as on the parent; the parent leaves '
                     'the pads above +12 dark, here they light like the others above the pitch')
    for scale, root, shift in ((0, 0, 4), (0, 0, -20), (1, 0, 0), (2, 9, 0), (5, 2, -3), (6, 4, 0), (6, 0, -12),
                               (17, 0, 0), (31, 7, -5)):
        m.set(P_SCALE, scale)
        m.set(P_ROOT, root)
        m.set(P_SHIFT, shift)
        notes = model(scale, root, m.get(P_SHIFT))[1]
        got = last(m.paint())
        if got != want(notes):
            bad.append((scale, root, shift, notes, got))
    check(not bad, f'scales, roots and shifts (to -12 and +27): every pad lights as the parent lights a pad in the '
                   f'scale at that note (none dark) ({bad[:1]})')


def push_checks(img, parent, man):
    m, p = Machine(img, man['entries']), Machine(parent)
    for x in (m, p):
        x.open_page(CHROMA_PAGE, CHROMA_REGISTRY)
        x.chromatic(True, source=3)
        x.set(P_SCALE, 0)
        x.set(P_ROOT, 0)
        x.set(P_SHIFT, 0)
    m.clear()
    m.dispatch(EV_KEY, KEY_VALUE)
    pressed = m.get(P_SCALE)
    m.dispatch(EV_KEY_UP, KEY_VALUE)
    check(pressed == 0 and m.get(P_SCALE) == 1 and m.popups == ['Scale Maj'] and
          m.tables()[0] == model(1, 0, m.get(P_SHIFT))[0],
          f'VALUE tapped: nothing at the press, the next scale at the release, popup "Scale Maj", the pads follow '
          f'({pressed}, {m.get(P_SCALE)}, {m.popups})')
    m.set(P_SCALE, 0)
    m.set(P_SHIFT, -8)
    m.clear()
    m.dispatch(EV_KEY, KEY_VALUE)
    seq = []
    for d in (1, 1, 1, -1, -1, -1, -1, -1):
        m.dispatch(EV_ENCODER, 0, d)
        seq.append(m.get(P_SCALE))
    m.dispatch(EV_KEY_UP, KEY_VALUE)
    shift = m.get(P_SHIFT)
    names = ['Scale ' + m.label(v) for v in seq]
    check(seq == [1, 2, 3, 2, 1, 0, 33, 32] and m.get(P_SCALE) == 32 and m.popups == names and
          m.get(P_ROOT) == 0 and m.tables()[0] == model(32, 0, shift)[0],
          f'VALUE held and turned: the scale one a turn, round (0 back to 33), the shift left alone (but for the new '
          f'range\'s end), nothing more at the release; popups name each ({seq}, {m.popups[-2:]})')
    m.clear()
    m.dispatch(EV_KEY, KEY_SHIFT)
    m.dispatch(EV_KEY, KEY_VALUE)
    keys = []
    for d in (-1, -1, 1, 1, 1):
        m.dispatch(EV_ENCODER, 0, d)
        keys.append(m.get(P_ROOT))
    m.dispatch(EV_KEY_UP, KEY_VALUE)
    m.dispatch(EV_KEY_UP, KEY_SHIFT)
    check(keys == [11, 10, 11, 0, 1] and m.get(P_SCALE) == 32 and
          m.popups == ['Key ' + ROOTS[k] for k in keys] and m.tables()[0] == model(32, 1, m.get(P_SHIFT))[0],
          f'SHIFT and VALUE held, VALUE turned: the key one a turn, round (C back to B), the scale left alone; popups '
          f'"Key B" ..; the pads follow ({keys}, {m.popups})')
    m.clear()
    m.dispatch(EV_KEY, KEY_VALUE)
    m.dispatch(EV_KEY, KEY_SHIFT)
    m.dispatch(EV_ENCODER, 0, 1)
    m.dispatch(EV_KEY_UP, KEY_SHIFT)
    m.dispatch(EV_ENCODER, 0, 1)
    m.dispatch(EV_KEY_UP, KEY_VALUE)
    check(m.get(P_ROOT) == 2 and m.get(P_SCALE) == 33,
          f'VALUE first, then SHIFT: the key; SHIFT let go with VALUE still held: the scale again '
          f'({m.get(P_ROOT)}, {m.get(P_SCALE)})')
    same = []
    for scale in (0, 5):
        got = []
        for x in (m, p):
            x.set(P_SCALE, scale)
            x.set(P_ROOT, 3)
            x.set(P_SHIFT, 0)
            x.dispatch(EV_ENCODER, 0, -1)
            a = x.get(P_SHIFT)
            x.dispatch(EV_KEY, KEY_SHIFT)
            x.dispatch(EV_ENCODER, 0, -1)
            x.dispatch(EV_KEY_UP, KEY_SHIFT)
            b = x.get(P_SHIFT)
            x.dispatch(EV_KEY, KEY_ROLL)
            x.dispatch(EV_ENCODER, 0, 1)
            x.dispatch(EV_KEY_UP, KEY_ROLL)
            got.append((a, b, x.get(P_ROOT), x.get(P_SCALE)))
        # with a scale the shift counts scale notes in its own range (the fold): only the key is stock's
        same.append(got[0] == got[1] if scale == 0 else got[0][2:] == got[1][2:] == (4, scale))
    check(all(same), f'without VALUE held: Chrom, a turn moves the pads 4 and SHIFT + turn 1, as on the parent; with a '
                     f'scale ROLL + turn moves the key, as on the parent ({same})')
    for x in (m, p):
        x.w32(UI_HELD, 1)
        x.set(P_SCALE, 2)
        x.tap(KEY_VALUE)
    held = m.get(P_SCALE) == p.get(P_SCALE)
    for x in (m, p):
        x.w32(UI_HELD, 0)
        x.chromatic(False)
        x.set(P_SCALE, 2)
        x.clear()
        x.dispatch(EV_KEY, KEY_VALUE)
    pressed = m.get(P_SCALE) == p.get(P_SCALE)
    for x in (m, p):
        x.dispatch(EV_KEY_UP, KEY_VALUE)
    check(held and pressed and m.get(P_SCALE) == p.get(P_SCALE) and not m.popups,
          f'VALUE while the page\'s press is the base class\'s, and outside chromatic mode: as the parent (at the '
          f'press) ({m.get(P_SCALE)}, {p.get(P_SCALE)})')


def main():
    out = Path(sys.argv[1])
    sections = set(sys.argv[2].split(',')) if len(sys.argv) > 2 else None
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    parent = Path(man['parent_app1']).read_bytes()
    for name, fn in (('static', lambda: static_checks(out, man, img, parent)),
                     ('tables', lambda: table_checks(img, parent, man)),
                     ('ranges', lambda: range_checks(img, parent, man)),
                     ('value', lambda: value_checks(img, parent, man)),
                     ('names', lambda: name_checks(img, parent, man)),
                     ('pads', lambda: pad_checks(img, parent, man)),
                     ('record', lambda: record_checks(img, parent, man)),
                     ('lights', lambda: light_checks(img, parent, man)),
                     ('push', lambda: push_checks(img, parent, man))):
        if sections is None or name in sections:
            fn()
    print(f'\n{"ALL PASS" if not fails else f"{len(fails)} FAILED"}')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
