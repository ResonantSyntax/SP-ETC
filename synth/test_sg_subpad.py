"""Test sg-subpad-test1 (SG_SUBPAD.md) in Unicorn: SUB PAD on the Sound Generator page plays the last pad played.

usage: python synth/test_sg_subpad.py OUT_DIR

Reads OUT_DIR/manifest.json for the parent APP1. Static checks first:
- only the header's scatter pointer and the two vtable words change inside the parent;
- the parent's rows plus one copy row for the module;
- the guards hold on the parent, and the module fits its slot.

Then the parent and the built image run in Unicorn. The setup:
- the boot's constructors run, with no card and no display;
- the TOP page is made, then the Sound Generator page (0x1e) by its registry handler (0x80065448), as on page entry;
- panel events go through the UI task's dispatcher (0x8003b530).

The SG note event (0x1fc00) and the two calls of v9.46's SUB PAD job (the voice check 0x8353bbc0, the tone toggle
0x801326f8) are logged and return 0. The checks cover:
- pads, and SUB PAD after one, in melodic and drum mode; SUB PAD before any pad;
- SHIFT + pad, SHIFT + SUB PAD, the last pad changing while SUB PAD is held;
- every pad's press and release as on the parent.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_HOOK_CODE
from unicorn import arm_const as ar

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sg_subpad import GUARDS, KNOWN_SLOTS, VTABLE, Runtime, decompress, scatter  # noqa: E402

FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
HEAP = 0x32000000
KERNEL = {0x310C: 1, 0x22A4: 1, 0x32B8: 0}                 # RTOS object creation in the constructors: an id
SCREEN = (0x8006C088, 0x8006BD48, 0x8015F3A8, 0x800D8020, 0x800C1CC0)  # drawing: no display here
NOPS = (0xE668, 0x800D30A4)                              # debug prints, the SMPL TASK flag
FILE_OPEN = 0x800DEC60                                   # no card here: every file is missing
CTORS, NCTORS = 0x8383A30C, 70
STACK, RET, EVENT = 0x30010000, 0x3001F000, 0x30095000
UI_DISPATCH, PAGE_ID, PAGE_LIVE, PREFILTER, KEY_PAIRS = 0x8003B530, 0x80245880, 0x8024587A, 0x82DFD318, 0x80B119DC
TOP_REGISTRY, SG_REGISTRY, SG_PAGE = 0x8005EDA8, 0x80065448, 0x1E
POPUP, PAD_DISPATCH, SOUNDING, POST = 0x800D3FF0, 0x800BEF10, 0x800D8C08, 0x800E25C0
SMPL, LOADED = 0x82E2CD08, 0x82E495E4
SG_NOTE, SG_ON, POLY_CHECK, TONE = 0x1FC00, 0x80591C48, 0x8353BBC0, 0x801326F8
KIT_MODE = 0x83FC58E0                                    # v9.46's kits module: 0 melodic, 1..13 a kit
EV_KEY, EV_KEY_UP, EV_PAD, EV_PAD_UP = 5, 6, 0x10, 0x11
KEY_SHIFT, SUB_PAD = 0x2A, 0x13
fails = []
cases = [0]


def check(cond, what):
    cases[0] += 1
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        fails.append(what)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


class Machine:
    def __init__(self, img):
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.ctl_set_cpu_model(ar.UC_CPU_ARM_MAX)          # the tone toggle uses VSEL, which the default model lacks
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
        self.log = []
        uc.hook_add(UC_HOOK_CODE, self._malloc, None, begin=0x800E2C68, end=0x800E2C68)
        uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=0x800E2CA8, end=0x800E2CA8)
        for a, v in KERNEL.items():
            uc.hook_add(UC_HOOK_CODE, self._value, v, begin=a, end=a)
        for a in SCREEN + NOPS:
            uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=a, end=a)
        uc.hook_add(UC_HOOK_CODE, self._value, -1, begin=FILE_OPEN, end=FILE_OPEN)
        uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=POPUP, end=POPUP)
        for fn in struct.unpack(f'<{NCTORS}I', bytes(uc.mem_read(CTORS, 4 * NCTORS))):
            self.call(fn & ~1 | 1, count=50_000_000)
        uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=PAD_DISPATCH, end=PAD_DISPATCH)
        uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=SOUNDING, end=SOUNDING)
        uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=POST, end=POST)
        uc.hook_add(UC_HOOK_CODE, self._note, None, begin=SG_NOTE, end=SG_NOTE)
        uc.hook_add(UC_HOOK_CODE, self._mark, 'voices', begin=POLY_CHECK, end=POLY_CHECK)
        uc.hook_add(UC_HOOK_CODE, self._mark, 'tone', begin=TONE, end=TONE)
        self.w32(PREFILTER, 0xFFFFFFFF)                 # no mode holds the keys
        uc.mem_write(KEY_PAIRS, b'\xff' * 0x80)         # no key pairs (memset -1 at boot)
        for pad in range(160):
            e = LOADED + pad * 36
            self.w32(e + 8, 2)
            self.w32(e + 0x18, 0)
            self.w32(e + 0x1C, 0x100000)
            self.w32(SMPL + 0xD0 + pad * 0xAC, 1)
        self.open_page(1, TOP_REGISTRY)
        self.open_page(SG_PAGE, SG_REGISTRY)
        self.log = []

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

    def _note(self, uc, a, size, _):
        """The SG note event (self, note, velocity, r3, [sp] the source pad)."""
        r = [uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}')) for k in range(4)]
        source = struct.unpack('<I', bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_SP), 4)))[0]
        self.log.append(('note', s32(r[1]), s32(r[2]), s32(source)))
        self._ret(0)

    def _mark(self, uc, a, size, what):
        self.log.append((what,))
        self._ret(0)

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))

    def r8(self, a):
        return self.uc.mem_read(a, 1)[0]

    def call(self, fn, *args, count=5_000_000):
        uc = self.uc
        for k, v in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), v & 0xFFFFFFFF)
        uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        uc.reg_write(ar.UC_ARM_REG_SP, STACK - 0x40)
        uc.emu_start(fn | 1, RET, count=count)
        if uc.reg_read(ar.UC_ARM_REG_PC) != RET:
            raise RuntimeError(f'{fn:#x} did not return (pc {uc.reg_read(ar.UC_ARM_REG_PC):#x})')
        return uc.reg_read(ar.UC_ARM_REG_R0)

    def open_page(self, pid, registry):
        """A page made by its registry handler as on page entry, then the current page."""
        self.uc.mem_write(EVENT, struct.pack('<6h', 1, 0, 0, 0, 0, 0))
        self.call(registry, EVENT, count=20_000_000)
        self.uc.mem_write(PAGE_ID, struct.pack('<H', pid))
        self.uc.mem_write(PAGE_LIVE, struct.pack('<H', pid))

    def dispatch(self, kind, a1=0, a2=0):
        self.uc.mem_write(EVENT, struct.pack('<6h', kind, a1, a2, 0, 0, 0))
        return self.call(UI_DISPATCH, EVENT, count=20_000_000)

    def pad(self, index, vel=100):
        """A pad (or SUB PAD) pressed at vel, or let go (vel 0); what it logged."""
        start = len(self.log)
        self.dispatch(EV_PAD if vel else EV_PAD_UP, index, vel)
        return self.log[start:]

    def key(self, k, down):
        self.dispatch(EV_KEY if down else EV_KEY_UP, k)


def file_offset(img, addr):
    for load, dst, n, fn in scatter(img):
        if fn == COPY and load and dst <= addr < dst + n:
            return load - FLASH + addr - dst
    raise ValueError(f'{addr:#x} not in a copy row')


# ---- static ----
def static_checks(out, man, img, parent):
    check(sha(img) == man['sha256'] and len(img) == man['size'], 'APP1 matches its manifest')
    check(sha((out / 'SP404MKII_APP0.bin').read_bytes()) == man['app0_sha256'] ==
          '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23', 'APP0 is stock 5.52')
    sums = (out / 'SHA256SUMS.txt').read_text(encoding='utf-8').split()
    check(dict(zip(sums[1::2], sums[0::2])) == {n: sha((out / n).read_bytes()) for n in (
        'SP404MKII_APP0.bin', 'SP404MKII_APP1.bin', 'manifest.json')}, 'SHA256SUMS.txt matches the files')
    check(sha(parent) == man['parent_sha256'], 'the parent APP1 is the manifest\'s')
    rows, prow = scatter(img), scatter(parent)
    check(rows == prow + [[FLASH + man['blob_file_offset'], man['blob_base'], man['blob_size'], COPY]],
          'scatter table: the parent\'s rows plus one copy row for the module')
    allowed = set(range(0x80, 0x88))
    for addr, *_ in VTABLE:
        off = file_offset(parent, addr)
        allowed |= set(range(off, off + 4))
    diff = [i for i in range(len(parent)) if img[i] != parent[i]]
    check(set(diff) <= allowed, f'only the scatter pointer and the two vtable words change inside the parent '
                                f'({len(diff)} bytes)')
    rt, nrt = Runtime(parent), Runtime(img)
    check(all(sha(rt.read(s, e - s)) == d for s, e, d, w in GUARDS), f'{len(GUARDS)} guards hold on the parent')
    e = man['entries']
    check(all(struct.unpack('<I', rt.read(a, 4))[0] == old and struct.unpack('<I', nrt.read(a, 4))[0] == e[entry]
              for a, old, entry, w in VTABLE), 'the vtable words: the page\'s pad press and release before, '
                                               'sp_press and sp_release after')
    slot = man['slot']
    module = img[man['blob_file_offset']:man['blob_file_offset'] + man['blob_size']]
    check(sha(module) == man['blob_sha256'] and nrt.read(man['blob_base'], man['blob_size']) == module and
          slot[0] == man['blob_base'] and man['blob_base'] + man['blob_size'] <= slot[1] and
          not any(max(lo, slot[0]) < min(hi, slot[1]) for _, lo, hi in KNOWN_SLOTS),
          f'the module ({man["blob_size"]} bytes) is loaded at its slot {slot[0]:#x}..{slot[1]:#x}, clear of every '
          f'other fork module')


# ---- behaviour ----
def notes(log):
    return [x for x in log if x[0] == 'note']


def behaviour_checks(img, parent, man):
    for mode, label in ((0, 'melodic'), (1, 'drum mode (TR808)')):
        m, p = Machine(img), Machine(parent)
        for x in (m, p):
            x.uc.mem_write(KIT_MODE, bytes([mode]))
        check(m.r8(SG_ON) == 1 and p.r8(SG_ON) == 1, f'{label}: the SG page is open, its pads on the SG note path')
        first, stock = m.pad(SUB_PAD, 70), p.pad(SUB_PAD, 70)
        m.pad(SUB_PAD, 0)
        p.pad(SUB_PAD, 0)
        check(first == [] and stock == [('voices',), ('tone',)],
              f'{label}: SUB PAD before any pad does nothing (the parent: its voice check and tone toggle) '
              f'({first}, {stock})')
        hit = m.pad(5, 100) + m.pad(5, 0)
        check(hit == p.pad(5, 100) + p.pad(5, 0) and [x[3] for x in notes(hit)] == [5, 5],
              f'{label}: pad 6 as on the parent ({hit})')
        down, up = m.pad(SUB_PAD, 70), m.pad(SUB_PAD, 0)
        check(down == [('note', hit[0][1], 70, 5)] and up == [('note', hit[0][1], 0, 5)],
              f'{label}: SUB PAD plays pad 6 at its own velocity, its release lets pad 6 go ({down}, {up})')
        stock = p.pad(SUB_PAD, 70) + p.pad(SUB_PAD, 0)
        check(not notes(stock) and ('tone',) in stock or ('voices',) in stock,
              f'{label}: the parent\'s SUB PAD toggles instead ({stock})')
        m.pad(9, 90)
        m.pad(9, 0)
        for x in (m, p):
            x.key(KEY_SHIFT, True)
        shifted = m.pad(12, 100) + m.pad(12, 0)
        both = m.pad(SUB_PAD, 70) + m.pad(SUB_PAD, 0)
        stock = p.pad(12, 100) + p.pad(12, 0)
        for x in (m, p):
            x.key(KEY_SHIFT, False)
        again = m.pad(SUB_PAD, 60)
        m.pad(SUB_PAD, 0)
        check(shifted == stock and not [x for x in shifted if x[0] != 'note' or x[2]] and both == [] and
              [x[2:] for x in again] == [(60, 9)],
              f'{label}: SHIFT + pad plays nothing (its release sends the stock note-off, as on the parent) and '
              f'leaves the last pad (pad 10); SHIFT + SUB PAD does nothing ({shifted}, {both}, {again})')
        held = m.pad(SUB_PAD, 80)
        m.pad(3, 100)
        m.pad(3, 0)
        let_go = m.pad(SUB_PAD, 0)
        then = m.pad(SUB_PAD, 70)
        m.pad(SUB_PAD, 0)
        check([x[2:] for x in held] == [(80, 9)] and [x[2:] for x in let_go] == [(0, 9)] and
              [x[2:] for x in then] == [(70, 3)],
              f'{label}: another pad while SUB PAD is held: its release lets go of the pad it played, the next SUB '
              f'PAD plays the new last pad ({held}, {let_go}, {then})')
    m, p = Machine(img), Machine(parent)
    same = [(pad, m.pad(pad, 100) + m.pad(pad, 0)) for pad in range(16)]
    check(all(log == p.pad(pad, 100) + p.pad(pad, 0) and [x[3] for x in notes(log)] == [pad, pad]
              for pad, log in same), 'every pad\'s press and release as on the parent (16 pads)')
    plays = struct.unpack('<I', bytes(m.uc.mem_read(man['entries']['sp_plays'], 4)))[0]
    check(plays == 0 and m.r8(man['entries']['sp_last']) == 16, f'the module counts no SUB PAD play there and keeps '
                                                                  f'pad 16 as the last ({plays})')


def main():
    out = Path(sys.argv[1])
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    parent = Path(man['parent_app1']).read_bytes()
    static_checks(out, man, img, parent)
    behaviour_checks(img, parent, man)
    print(json.dumps(dict(cases=cases[0])))
    print('ALL PASS' if not fails else f'{len(fails)} FAILED')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
