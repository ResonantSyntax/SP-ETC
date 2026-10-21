"""Checks for the FX deep edit page (build_fx_deep_edit.py).

usage: python synth/test_fx_deep_edit.py OUT_DIR [FXMAP]     (unicorn, keystone, capstone on PYTHONPATH)

Reads OUT_DIR/manifest.json for the parent APP1 and DM-404's fxmap.json (or FXMAP). Static checks first:
only the header's scatter pointer, the TOP vtable slot, the DT1 builder's first ten bytes and the appended
tail differ from the parent, the guards hold on the parent, the settings are exactly the parameters stock
never sends, every popup line fits. Then the parent and the new image are booted in Unicorn the way their
scatter loader does it, with the boot's static constructors run (the RTOS under them stubbed: its pool by a
bump allocator, object creation by an id), the TOP page object made by its registry handler as on page
entry, and every byte to the chips' UARTs (LPUART1-8) logged. Real stock code runs: the UI task's dispatcher
(0x8003b530), TOP's registry handler, page dispatcher, EXIT and knob handlers, DOOM OS ED5E's page filter,
the system and settings getters and setters, the effect select, the chip reset, the DT1 builder 0x800d8118
(through the new jump) and its packet send, the popup. Modelled: the card (every file open fails: DOOM OS
looks for B:/DOOMOS.CFG on each key press), time between presses (the stock timer tick runs on TOP's 500 ms
EXIT window). Not here: the screen (draw calls stubbed), the effects chip itself.

Checks:
- the builder, entered through the jump, sends fxmap's address for every setting on every bus, and exactly
  the parent's bytes for every parameter on every slot and for the whole boot chip reset;
- the page through the dispatcher: the chord opens it on the bus the knobs drive and that bus's effect;
  turning, pressing and leaving send nothing; each change of value sends exactly one frame (the setting's
  address, the bus's slot, the value, the checksum) and nothing else; every setting of every effect stops
  at the firmware's own min and max; values are kept per bus and per effect; the popup says what it should;
  no effect, an effect without settings and the input FX say so;
- re-sending: after the firmware sends a bus's FxType (the effect select through the stock effect choice,
  the system setter, the bus swap), that bus's edited values for that effect follow it at once, and the
  rest of the traffic is the parent's byte for byte; a knob turn, another bus's FxType, the chip reset
  (FxType 0) and FxType for an effect without edits add nothing;
- every other event reaches DOOM OS's filter exactly as on the parent while the page is closed (keys alone
  and in pairs, EXIT and VALUE alone, VALUE before EXIT, knobs, the encoder, pads, four quick EXITs = STOP,
  a chord whose VALUE release never came back); while it is open, pads and knobs go on as on the parent, and
  EXIT or any other button closes the page and goes on as on the parent (four quick EXITs are still STOP).
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_HOOK_CODE
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE
from unicorn import arm_const as ar

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_fx_deep_edit import GUARDS, Runtime, scatter, decompress, branches_into, DT1, DT1_HEAD  # noqa: E402

FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
HEAP = 0x32000000
KERNEL = {0x310C: 1, 0x22A4: 1, 0x32B8: 0}                 # RTOS object creation in the constructors: an id
SCREEN = (0x8006C088, 0x8006BD48, 0x8015F3A8, 0x800D8020, 0x800C1CC0)  # drawing: no display here
NOPS = (0xE668, 0x800D30A4)                              # debug prints
FILE_OPEN = 0x800DEC60                                   # (path, ...): no card here, every file is missing
CTORS, NCTORS = 0x8383A30C, 70
STACK, RET, EVENT = 0x30010000, 0x3001F000, 0x30095000
SYSPRM, BMC, SYS_SET, SYS_GET = 0x82DFEED0, 0x80592500, 0x800DE270, 0x800DA010
SETTINGS, SET_SET = 0x82E01144, 0x800DD0C0
SELECT, CHIP_RESET, SYS_INIT = 0x800D0CF0, 0x801803B0, 0x8006C3C0
UI_DISPATCH, PAGE_ID, PAGE_LIVE, PREFILTER, KEY_PAIRS = 0x8003B530, 0x80245880, 0x8024587A, 0x82DFD318, 0x80B119DC
TOP_REGISTRY, TOP_PAGE, DOOM_FILTER, VTABLE_SLOT = 0x8005EDA8, 0x80CFD350, 0x6031C8F8, 0x8022CE64
POPUP, KEYS = 0x800D3FF0, 0x80592448
FALLBACKS = (0x8003C758, 0x8003C798)                     # the dispatcher's own handling of a key no page took
TIMER_TICK, EXIT_WINDOW = 0x80100728, 0x82DFD2FC          # stock timer tick (timer, ms); TOP's EXIT-press window
DEFAULTS, MINIMA, MAXIMA, RECORDS, NAMES = 0x801ABE64, 0x801AD1FC, 0x801AC830, 0x802E5B40, 0x80245EE4
FXTYPE_SENT = 0x80246F38
EV_KEY, EV_KEY_UP, EV_ENCODER, EV_KNOB, EV_PAD, EV_PAD_UP = 5, 6, 7, 9, 0x10, 0x11
KEY_EXIT, KEY_VALUE, KEY_SHIFT = 0x22, 0x31, 0x2A
HEADER = bytes([0xF0, 0x41, 0x10, 0x00, 0x00, 0x00, 0x00, 0x08, 0x12])
PAGE_MS, GONE_MS = 10000, 1
TAPE_ECHO, REVERB, CRUSHER, EQUALIZER = 9, 10, 4, 19
fails = []
cases = [0]


def check(cond, what):
    cases[0] += 1
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        fails.append(what)
    return cond


def sha(b):
    return hashlib.sha256(b).hexdigest()


def s32(v):
    return struct.unpack('<i', struct.pack('<I', v & 0xFFFFFFFF))[0]


def frame(addr, value):
    body = bytes(addr) + bytes([value >> 4 & 15, value & 15])
    return HEADER + body + bytes([-sum(body) & 0x7F, 0xF7])


def fx_frame(fx, slot, aa, value):
    block = (fx - 1) * 5 + slot
    return frame((3, block >> 7, block & 0x7F, aa), value)


def fxtype_frame(slot, fx):
    return frame((2, 2, 0, 8 + 2 * slot), fx)


class Machine:
    def __init__(self, img, symbols=None):
        self.sym = symbols or {}
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
        self.uart, self.popups, self.doom, self.fallback, self.opened = [], [], [], [], []
        uc.hook_add(UC_HOOK_CODE, self._malloc, None, begin=0x800E2C68, end=0x800E2C68)
        uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=0x800E2CA8, end=0x800E2CA8)
        for a, v in KERNEL.items():
            uc.hook_add(UC_HOOK_CODE, self._value, v, begin=a, end=a)
        for a in SCREEN + NOPS:
            uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=a, end=a)
        uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self._uart, None, begin=0x40184000, end=0x401A3FFF)
        uc.hook_add(UC_HOOK_CODE, self._popup, None, begin=POPUP, end=POPUP)
        uc.hook_add(UC_HOOK_CODE, self._doom, None, begin=DOOM_FILTER, end=DOOM_FILTER)
        uc.hook_add(UC_HOOK_CODE, self._open, None, begin=FILE_OPEN, end=FILE_OPEN)
        for a in FALLBACKS:
            uc.hook_add(UC_HOOK_CODE, self._fallback, None, begin=a, end=a)
        for fn in struct.unpack(f'<{NCTORS}I', bytes(uc.mem_read(CTORS, 4 * NCTORS))):
            self.call(fn & ~1 | 1, count=50_000_000)
        self.w32(PREFILTER, 0xFFFFFFFF)                 # no mode holds the keys
        uc.mem_write(KEY_PAIRS, b'\xff' * 0x80)         # no key pairs (memset -1 at boot)
        uc.mem_write(EVENT, struct.pack('<6h', 1, 0, 0, 0, 0, 0))
        self.call(TOP_REGISTRY, EVENT, count=20_000_000)  # the TOP page object, as on page entry
        self.page = self.r32(TOP_PAGE)
        uc.mem_write(PAGE_ID, struct.pack('<H', 1))
        uc.mem_write(PAGE_LIVE, struct.pack('<H', 1))
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

    def _uart(self, uc, access, address, size, value, _):
        base, off = address & ~0x3FFF, address & 0x3FFF
        if access == UC_MEM_WRITE and off == 0x1C:
            self.uart.append(((base - 0x40184000) // 0x4000 + 1, value & 0xFF))
        elif off == 0x14:
            uc.mem_write(address, struct.pack('<I', 0x00C00000))    # transmit ready

    def _popup(self, uc, a, size, _):
        text = bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R0), 64)).split(b'\0')[0].decode('latin-1')
        self.popups.append((text, uc.reg_read(ar.UC_ARM_REG_R1)))

    def _doom(self, uc, a, size, _):
        ev = uc.reg_read(ar.UC_ARM_REG_R1)
        self.doom.append((uc.reg_read(ar.UC_ARM_REG_R0), struct.unpack('<3h', bytes(uc.mem_read(ev, 6)))))

    def _open(self, uc, a, size, _):
        self.opened.append(bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R0), 96)).split(b'\0')[0].decode('latin-1'))
        self._ret(-1)

    def _fallback(self, uc, a, size, _):
        self.fallback.append(struct.unpack('<2h', bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R0), 4))))

    def clear(self):
        self.uart, self.popups, self.doom, self.fallback, self.opened = [], [], [], [], []

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack('<I', self.uc.mem_read(a, 4))[0]

    def r16(self, a):
        return struct.unpack('<H', self.uc.mem_read(a, 2))[0]

    def call(self, fn, *args, count=5_000_000):
        uc = self.uc
        for k, v in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), v & 0xFFFFFFFF)
        uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        uc.reg_write(ar.UC_ARM_REG_SP, STACK)
        uc.emu_start(fn | 1, RET, count=count)
        if uc.reg_read(ar.UC_ARM_REG_PC) != RET:
            raise RuntimeError(f'{fn:#x} did not return (pc {uc.reg_read(ar.UC_ARM_REG_PC):#x})')
        return uc.reg_read(ar.UC_ARM_REG_R0)

    def dispatch(self, kind, a1=0, a2=0):
        """An event through the UI task's own dispatcher (keys set and clear their held bits there)."""
        self.uc.mem_write(EVENT, struct.pack('<6h', kind, a1, a2, 0, 0, 0))
        return s32(self.call(UI_DISPATCH, EVENT, count=20_000_000))

    def pause(self, ms):
        """Time passing for TOP's EXIT handler (0x801349f8): four EXIT presses less than 500 ms apart are stock's
        STOP. The UI tick 0x8003c5f0 ages that window's timer 0x82dfd2fc through 0x80100728 once boot has set its
        ready flags, which the constructors don't; this runs that timer tick itself."""
        self.call(TIMER_TICK, EXIT_WINDOW, ms)

    def chord(self):
        """Hold EXIT, press and release VALUE, let go of EXIT; then the user's pace."""
        for kind, key in ((EV_KEY, KEY_EXIT), (EV_KEY, KEY_VALUE), (EV_KEY_UP, KEY_VALUE), (EV_KEY_UP, KEY_EXIT)):
            self.dispatch(kind, key)
        self.pause(600)

    def press(self, key=KEY_VALUE):
        self.dispatch(EV_KEY, key)
        self.dispatch(EV_KEY_UP, key)
        self.pause(600)

    def turn(self, n):
        self.dispatch(EV_ENCODER, 0, n)

    def packets(self, port=3):
        b = [v for p, v in self.uart if p == port]
        return [bytes(b[i:i + 4]) for i in range(0, len(b), 4)], len(b) % 4

    def frames(self):
        """The chip link's DT1 frames (04 x x x five times then 06 sum F7 and a filler byte), the other packets
        (e.g. MIDI out on cable 9), and whether the SysEx packets all formed such frames and nothing went to
        another UART."""
        pk, rest = self.packets()
        frames, other, cur = [], [], []
        ok = rest == 0 and not [p for p, v in self.uart if p != 3]
        for p in pk:
            cable, cin = p[0] >> 4, p[0] & 0xF
            if cable or cin not in (4, 5, 6, 7):
                other.append(p)
            elif cin == 4 and len(cur) < 5:
                cur.append(p)
            elif cin == 6 and len(cur) == 5:
                frames.append(b''.join(q[1:] for q in cur) + p[1:3])
                cur = []
            else:
                ok = False
        return frames, other, ok and not cur

    def set_bus(self, bus, fx, knobs=True):
        """The effect on a bus the way the stock MFX choice sets it (0x8006ccd6: 0x27b, 0x27c, the effect select,
        0x276 = 6), and the CTRL knobs on that bus (settings 0x3a)."""
        self.call(SYS_SET, SYSPRM, 0x27B, fx, bus)
        self.call(SYS_SET, SYSPRM, 0x27C, fx, bus)
        self.call(SELECT, SYSPRM, bus)
        self.call(SYS_SET, SYSPRM, 0x276, 6, bus)
        if knobs:
            self.call(SET_SET, SETTINGS, 0x3A, bus, 0)

    def knob_bus(self, bus):
        self.call(SET_SET, SETTINGS, 0x3A, bus, 0)

    def bus_effect(self, bus, fx):
        """0x27c[bus] written straight into the system object: the page's view, no frame sent."""
        self.uc.mem_write(SYSPRM + 0xC4 + 2 * bus, struct.pack('<h', fx))

    def state(self):
        b = bytes(self.uc.mem_read(self.sym['fde'], 16))
        return dict(open=b[0], edit=b[1], bus=b[4], effect=b[5], cursor=b[6],
                    sent=struct.unpack_from('<I', b, 8)[0], resent=struct.unpack_from('<I', b, 12)[0])


class Settings:
    """The settings as the test derives them, from the parent image and fxmap alone."""

    def __init__(self, rt, fxmap):
        self.names = [rt.cstr(p & 0xFFFFFFFF) for p in rt.words(NAMES, 627)]
        self.default, self.max, self.min = (rt.words(a, 627) for a in (DEFAULTS, MAXIMA, MINIMA))
        self.effect_names = [rt.cstr(p & 0xFFFFFFFF).upper() for p in rt.words(0x8020B3D8, 49)]
        self.by_fx = {}
        for e in fxmap.values():
            record = rt.words(RECORDS + 24 * e['id'], 6)
            first = [x for x in record if x >= 0][0]
            base = [first - p['addr'] // 2 for p in e['params'] if self.names[first] == p['name']]
            base = [b for b in base if self.names[b:b + len(e['params'])] == [p['name'] for p in e['params']]]
            assert len(base) == 1, e['name']
            self.by_fx[e['id']] = [dict(id=base[0] + i, name=p['name'], aa=p['addr'], min=self.min[base[0] + i],
                                        max=self.max[base[0] + i], default=self.default[base[0] + i])
                                   for i, p in enumerate(e['params'])
                                   if p['default'] is None and base[0] + i not in record]

    def text(self, bus, fx, cursor=0, value=None, edit=False):
        s = self.by_fx[fx][cursor]
        v = s['default'] if value is None else value
        return f'BUS{bus} {self.effect_names[fx]}\n{s["name"]} ' + (f'[{v}]' if edit else f'{v}')


def static_checks(out, man, img, parent, fxmap, st):
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
    vt, dt = file_off(VTABLE_SLOT), file_off(DT1)
    diff = [i for i in range(len(parent)) if img[i] != parent[i]]
    allowed = set(range(0x80, 0x88)) | set(range(vt, vt + 4)) | set(range(dt, dt + 10))
    check(set(diff) <= allowed and img[:len(parent)] != parent,
          f'only the scatter pointer, the TOP vtable slot and the DT1 builder\'s first ten bytes change inside the '
          f'parent ({len(diff)} bytes)')
    e = man['entries']
    check(parent[vt:vt + 4] == struct.pack('<I', DOOM_FILTER | 1) and img[vt:vt + 4] == struct.pack('<I', e['fde_filter']),
          'TOP vtable +8: DOOM OS\'s filter on the parent, fde_filter here')
    lo, hi = e['fde_dt1'] & 0xFFFF, e['fde_dt1'] >> 16
    want = struct.pack('<4HH', 0xF240 | (lo >> 12) | ((lo >> 11) & 1) << 10, ((lo >> 8) & 7) << 12 | 12 << 8 | lo & 0xFF,
                       0xF2C0 | (hi >> 12) | ((hi >> 11) & 1) << 10, ((hi >> 8) & 7) << 12 | 12 << 8 | hi & 0xFF, 0x4760)
    check(parent[dt:dt + 10] == DT1_HEAD and img[dt:dt + 10] == want,
          'DT1 builder entry: push.w / sub sp / movw sb on the parent, movw ip / movt ip / bx ip to fde_dt1 here')
    rt, nrt = Runtime(parent), Runtime(img)
    check(all(sha(rt.read(s, e2 - s)) == d for s, e2, d, w in GUARDS), f'{len(GUARDS)} guards hold on the parent')
    check(not branches_into(rt, DT1 + 1, DT1 + 10), 'nothing branches into the builder\'s first ten bytes')
    stock = nrt.read(e['fde_dt1_stock'] & ~1, 20)
    check(stock[:10] == DT1_HEAD and stock[10:] == struct.pack('<5H', 0xF248, 0x1C23, 0xF2C8, 0x0C0D, 0x4760),
          'fde_dt1_stock: the builder\'s first ten bytes, then movw ip / movt ip / bx ip to 0x800d8123')
    check(nrt.read(man['blob_base'], man['blob_size']) ==
          img[man['blob_file_offset']:man['blob_file_offset'] + man['blob_size']] and
          man['blob_base'] + man['blob_size'] <= man['slot'][1] <= 0x83FE6000, 'the module fits its slot')
    # the settings: compiled tables == the test's own derivation == the manifest
    n = man['settings_total']
    first = list(nrt.read(e['fde_first'], 49))
    count = list(nrt.read(e['fde_count'], 49))
    ids = list(struct.unpack(f'<{n}H', nrt.read(e['fde_ids'], 2 * n)))
    names = [nrt.read(e['fde_names'] + 10 * i, 10).split(b'\0')[0].decode() for i in range(n)]
    labels = [nrt.read(e['fde_effect_names'] + 13 * i, 13).split(b'\0')[0].decode() for i in range(49)]
    mine = [(p['id'], p['name']) for fx in range(1, 49) for p in st.by_fx[fx]]
    check(n == 142 and list(zip(ids, names)) == mine and
          all(count[fx] == len(st.by_fx[fx]) and first[fx] == sum(len(st.by_fx[k]) for k in range(1, fx))
              for fx in range(1, 49)) and count[0] == 0 and labels[1:] == st.effect_names[1:],
          f'the compiled settings are the {len(mine)} parameters with no boot value in fxmap and not in the knob '
          f'records, in fxmap order, with the firmware\'s names')
    check([(p['id'], p['name'], p['min'], p['max'], p['default']) for x in man['effects'] for p in x['settings']] ==
          [(p['id'], p['name'], p['min'], p['max'], p['default']) for fx in range(1, 49) for p in st.by_fx[fx]],
          'the manifest lists the same settings with the firmware\'s ranges and defaults')
    check(all(0 <= p['min'] <= p['default'] <= p['max'] <= 255 for fx in st.by_fx for p in st.by_fx[fx]),
          'every setting\'s range is inside 0..255 and holds its default')
    lines = [f'BUS4 {labels[fx]}' for fx in range(1, 49)] + \
            [f'{p["name"]} [{p["max"]}]' for fx in st.by_fx for p in st.by_fx[fx]] + \
            ['NO EXTRA SETTINGS', 'BUS 1-4 ONLY', 'INPUT FX', 'FX EDIT', 'NO EFFECT']
    check(all(len(x) <= 17 and x.isascii() for x in lines), 'every popup line is plain and at most 17 characters')


def builder_checks(img, parent, man, fxmap, st):
    """The builder through the jump: the parent's bytes for every parameter ID and slot and for the whole boot
    chip reset (fresh machines, the same history: even the stock packet buffer's leftover byte matches), and
    fxmap's addresses for every setting on every bus."""
    m, p = Machine(img, man['entries']), Machine(parent)
    bad, n = [], 0
    for pid in range(0, 627):
        for slot in ((0,) if pid < 0xA3 else range(5)):
            out = []
            for mm in (p, m):
                mm.clear()
                r = mm.call(DT1, BMC, pid, slot, 0x37)
                out.append((bytes(v for q, v in mm.uart), r))
            n += bool(out[0][0])
            if out[0] != out[1]:
                bad.append((pid, slot))
    check(not bad and n >= 104 + 464 * 5, f'through the jump, every parameter ID on every slot sends the parent\'s '
                                          f'bytes ({n} that send; {bad[:4]})')
    m, p = Machine(img, man['entries']), Machine(parent)
    out = []
    for mm in (p, m):
        mm.call(CHIP_RESET, 0x80591794, count=50_000_000)
        out.append(bytes(v for q, v in mm.uart))
    check(out[0] == out[1] and len(out[0]) > 15000, f'the boot chip reset sends the parent\'s {len(out[0])} bytes')
    bad, n = [], 0
    for fx in range(1, 49):
        for s in st.by_fx[fx]:
            for bus in range(1, 5):
                m.clear()
                m.call(DT1, BMC, s['id'], bus, 0x5A)
                got, other, ok = m.frames()
                n += 1
                if not ok or other or got != [fx_frame(fx, bus, s['aa'], 0x5A)] or \
                        [x['addr'] for x in fxmap[fx]['params'] if x['name'] == s['name'] and x['default'] is None] != [s['aa']]:
                    bad.append((fx, s['name'], bus))
    check(not bad and n == 568, f'through the jump, the builder sends fxmap\'s address for all {n} setting/bus pairs '
                                f'({bad[:4]})')


def page_checks(img, parent, man, st):
    m = Machine(img, man['entries'])
    check(m.r32(m.r32(m.page) + 8) == man['entries']['fde_filter'] and m.r32(m.page) == 0x8022CE5C,
          'the TOP page object made on page entry has vtable 0x8022ce5c, whose +8 is fde_filter')
    m.set_bus(1, TAPE_ECHO)
    te = st.by_fx[TAPE_ECHO]
    k_dist = [i for i, s in enumerate(te) if s['name'] == 'TAPE DIST'][0]
    dist = te[k_dist]
    m.clear()
    m.chord()
    check(not m.uart and m.popups == [(st.text(1, TAPE_ECHO), PAGE_MS)] and m.state()['open'] and
          [d[1][:2] for d in m.doom] == [(EV_KEY, KEY_EXIT), (EV_KEY_UP, KEY_EXIT)] and
          not [f for f in m.fallback if f[1] == KEY_VALUE],
          f'the chord opens the page on BUS 1 Tape Echo, first setting at its default, nothing sent; VALUE\'s press '
          f'and release are the page\'s, EXIT\'s go on to DOOM OS ({m.popups})')
    texts = []
    for k in range(1, len(te)):
        m.clear()
        m.turn(1)
        texts.append((m.popups, not m.uart and not m.doom))
    check(texts == [([(st.text(1, TAPE_ECHO, k), PAGE_MS)], True) for k in range(1, len(te))],
          f'turning VALUE right steps through all {len(te)} Tape Echo settings at their defaults, nothing sent')
    m.clear()
    m.turn(3)
    m.turn(1)
    check(m.popups == [(st.text(1, TAPE_ECHO, len(te) - 1), PAGE_MS)] * 2 and not m.uart,
          'past the last setting the cursor stays on it')
    m.clear()
    m.turn(-100)
    check(m.popups == [(st.text(1, TAPE_ECHO, 0), PAGE_MS)] and not m.uart and m.state()['cursor'] == 0,
          'a big left turn goes back to the first setting')
    m.turn(k_dist)
    m.clear()
    m.press()
    check(m.popups == [(st.text(1, TAPE_ECHO, k_dist, edit=True), PAGE_MS)] and not m.uart and m.state()['edit'],
          f'VALUE pressed on TAPE DIST: edit, "{st.text(1, TAPE_ECHO, k_dist, edit=True)}", nothing sent')
    seq, d = [], dist['default']
    for delta in (-1, -1, -10, -1, 3, 20, 1, -2):
        m.clear()
        m.turn(delta)
        v = max(dist['min'], min(dist['max'], d + delta))
        got, other, ok = m.frames()
        want = [fx_frame(TAPE_ECHO, 1, dist['aa'], v)] if v != d else []
        seq.append(ok and not other and got == want and m.popups == [(st.text(1, TAPE_ECHO, k_dist, v, True), PAGE_MS)])
        d = v
    check(all(seq), f'editing TAPE DIST: each change is exactly one frame (03 00 29 {dist["aa"]:02x}, the value, the '
                    f'checksum) and nothing else; it stops at the firmware\'s {dist["min"]} and {dist["max"]} and a '
                    f'turn past them sends nothing ({seq})')
    m.clear()
    m.press()
    check(m.popups == [(st.text(1, TAPE_ECHO, k_dist, d), PAGE_MS)] and not m.uart and not m.state()['edit'],
          'VALUE pressed again: editing stops, nothing sent')
    m.clear()
    m.dispatch(EV_KEY, KEY_EXIT)
    m.dispatch(EV_KEY_UP, KEY_EXIT)
    check(not m.uart and m.popups == [(st.text(1, TAPE_ECHO, k_dist, d), GONE_MS)] and not m.state()['open'] and
          [x[1][:2] for x in m.doom] == [(EV_KEY, KEY_EXIT), (EV_KEY_UP, KEY_EXIT)],
          'EXIT closes the page (the popup goes at the next tick) and goes on to DOOM OS as usual; nothing sent')
    m.clear()
    m.pause(600)
    m.turn(1)
    check(m.doom == [(m.page, (EV_ENCODER, 0, 1))] and not m.popups, 'closed: VALUE turns go on to DOOM OS again')
    m.clear()
    m.chord()
    m.turn(k_dist)
    check(m.popups[-1] == (st.text(1, TAPE_ECHO, k_dist, d), PAGE_MS) and not m.uart,
          'opened again: it starts at the first setting, and TAPE DIST still shows the edited value')
    m.press(KEY_EXIT)

    # per bus, per effect; other buses send to their own slot
    m.knob_bus(2)
    m.set_bus(2, TAPE_ECHO)
    m.clear()
    m.chord()
    m.turn(k_dist)
    check(m.popups[-1] == (st.text(2, TAPE_ECHO, k_dist), PAGE_MS), 'BUS 2 Tape Echo shows TAPE DIST at its default: '
                                                                    'values are per bus')
    m.press()
    m.clear()
    m.turn(-2)
    got, other, ok = m.frames()
    check(ok and got == [fx_frame(TAPE_ECHO, 2, dist['aa'], dist['default'] - 2)] and not other,
          'an edit on BUS 2 goes to slot 2 (03 00 2a ..)')
    m.press(KEY_EXIT)
    for bus in (3, 4):
        m.knob_bus(bus)
        m.bus_effect(bus, REVERB)
        m.clear()
        m.chord()
        m.press()
        m.turn(-3)
        rv = st.by_fx[REVERB][0]
        got, other, ok = m.frames()
        check(ok and got == [fx_frame(REVERB, bus, rv['aa'], rv['default'] - 3)] and not other and
              m.popups[-1] == (st.text(bus, REVERB, 0, rv['default'] - 3, True), PAGE_MS),
              f'BUS {bus} Reverb: DENSITY goes to slot {bus}')
        m.press(KEY_EXIT)
    m.knob_bus(1)
    m.bus_effect(1, REVERB)
    m.clear()
    m.chord()
    check(m.popups[-1] == (st.text(1, REVERB), PAGE_MS), 'BUS 1 Reverb shows DENSITY at its default: values are per '
                                                         'effect too')
    m.press(KEY_EXIT)
    for label, setup, text in (
            ('no effect on the bus', lambda mm: mm.bus_effect(1, 0), 'BUS1\nNO EFFECT'),
            ('an effect without settings', lambda mm: mm.bus_effect(1, CRUSHER), 'BUS1 CRUSHER\nNO EXTRA SETTINGS'),
            ('the knobs on the input FX', lambda mm: mm.knob_bus(0), 'INPUT FX\nBUS 1-4 ONLY')):
        setup(m)
        m.clear()
        m.chord()
        m.turn(2)
        m.press()
        m.turn(-1)
        check(not m.uart and m.popups == [(text, PAGE_MS)] * 4, f'{label}: "{text}", turning and pressing send nothing')
        m.press(KEY_EXIT)
    # the effect changes while the page is open: the next action starts over on it
    m.knob_bus(1)
    m.bus_effect(1, TAPE_ECHO)
    m.clear()
    m.chord()
    m.turn(2)
    m.press()
    m.bus_effect(1, EQUALIZER)
    m.clear()
    m.turn(1)
    check(not m.uart and m.popups == [(st.text(1, EQUALIZER), PAGE_MS)] and not m.state()['edit'],
          'the bus\'s effect changed while open: the next turn shows the new effect\'s first setting, not editing, '
          'nothing sent')
    m.press(KEY_EXIT)


def open_pair(img, parent, man):
    """The parent and the image with BUS 1 Tape Echo, the page open on the image; the parent got what DOOM OS
    got on the image (EXIT pressed and let go: the chord's VALUE was the page's)."""
    p, m = Machine(parent), Machine(img, man['entries'])
    for mm in (p, m):
        mm.set_bus(1, TAPE_ECHO)
    m.chord()
    p.dispatch(EV_KEY, KEY_EXIT)
    p.dispatch(EV_KEY_UP, KEY_EXIT)
    p.pause(600)
    return p, m


def snapshot(mm, r):
    return (r, mm.frames(), [(q, v) for q, v in mm.uart if q != 3], [x for x in mm.popups if x[1] != GONE_MS],
            mm.doom, mm.fallback, bytes(mm.uc.mem_read(KEYS, 16)), mm.r16(PAGE_ID))


def open_passthrough_checks(img, parent, man, st):
    """While the page is open: pads and knobs go on as on the parent and the page stays open; any other button
    closes it and goes on as on the parent."""
    p, m = open_pair(img, parent, man)
    out = []
    for mm in (p, m):
        mm.clear()
        r = [mm.dispatch(EV_PAD, 3, 100), mm.dispatch(EV_PAD_UP, 3, 0), mm.dispatch(EV_KNOB, 1, 40),
             mm.dispatch(EV_KNOB, 1, 100), mm.dispatch(EV_KNOB, 3, 127)]
        out.append(snapshot(mm, r))
    check(out[0] == out[1] and out[0][1][0] and m.state()['open'],
          f'open: pads and knobs go on exactly as on the parent (the same {len(out[0][1][0])} frame(s), '
          f'{len(out[0][1][1])} MIDI packets, {len(out[0][2])} bytes to other chips) and the page stays open')
    m.clear()
    m.turn(0)
    check(m.popups == [(st.text(1, TAPE_ECHO), PAGE_MS)], 'still open after them')
    p, m = open_pair(img, parent, man)
    out = []
    for mm in (p, m):
        mm.clear()
        for _ in range(4):
            mm.dispatch(EV_KEY, KEY_EXIT)
            mm.dispatch(EV_KEY_UP, KEY_EXIT)
        out.append(snapshot(mm, None))
    check(out[0] == out[1] and ('STOP', 1000) in out[0][3] and not m.state()['open'],
          'open: four quick EXITs close the page and are stock\'s STOP, byte for byte as on the parent')
    bad = []
    for k in [KEY_EXIT, KEY_SHIFT] + [k for k in KEYS_ALONE if k not in (KEY_EXIT, KEY_SHIFT)]:
        p, m = open_pair(img, parent, man)
        out = []
        for mm in (p, m):
            mm.clear()
            try:
                r = [mm.dispatch(EV_KEY, k), mm.dispatch(EV_KEY_UP, k)]
            except Exception as e:                      # stock paths the harness can't run end the same way
                r = f'{type(e).__name__}'
            out.append(snapshot(mm, r))
        if out[0] != out[1] or m.state()['open'] or (st.text(1, TAPE_ECHO), GONE_MS) not in m.popups:
            bad.append(hex(k))
    check(not bad, f'open: EXIT and each of the {len(KEYS_ALONE) - 1} other buttons close the page (its popup goes) '
                   f'and go on exactly as on the parent ({bad})')


def range_checks(img, man, st):
    """Every setting of every effect, on BUS 3: down past the firmware's min and up past its max."""
    m = Machine(img, man['entries'])
    m.knob_bus(3)
    bad, n = [], 0
    for fx in range(1, 49):
        if not st.by_fx[fx]:
            continue
        m.bus_effect(3, fx)
        m.chord()
        for k, s in enumerate(st.by_fx[fx]):
            if k:
                m.turn(1)
            m.press()
            m.clear()
            m.turn(-300)
            m.turn(-1)
            low = m.frames()
            m.clear()
            m.turn(300)
            m.turn(1)
            high, shown = m.frames(), m.popups[-1]
            m.press()
            n += 1
            want_low = [fx_frame(fx, 3, s['aa'], s['min'])] if s['min'] != s['default'] else []
            if low != (want_low, [], True) or high != ([fx_frame(fx, 3, s['aa'], s['max'])], [], True) or \
                    shown != (st.text(3, fx, k, s['max'], True), PAGE_MS):
                bad.append((fx, s['name'], low, high, shown))
        m.press(KEY_EXIT)
    check(not bad and n == 142, f'all {n} settings stop at the firmware\'s min and max, one frame each way '
                                f'({bad[:4]})')


def edit(m, bus, fx, name, delta):
    """Open the page on bus/fx, edit setting name by delta, close it; returns the value now held."""
    m.knob_bus(bus)
    m.chord()
    k = [i for i, s in enumerate(m.st.by_fx[fx]) if s['name'] == name][0]
    m.turn(k)
    m.press()
    m.turn(delta)
    m.press()
    m.press(KEY_EXIT)
    return m.st.by_fx[fx][k]['default'] + delta


def resend_checks(img, parent, man, st):
    m, p = Machine(img, man['entries']), Machine(parent)
    m.st = st
    for mm in (m, p):
        mm.set_bus(1, TAPE_ECHO)
        mm.set_bus(2, TAPE_ECHO, knobs=False)
    te = {s['name']: s for s in st.by_fx[TAPE_ECHO]}
    v_dist = edit(m, 1, TAPE_ECHO, 'TAPE DIST', -2)
    v_bass = edit(m, 1, TAPE_ECHO, 'BASS', -5)
    v_two = edit(m, 2, TAPE_ECHO, 'TREBLE', 4)
    ours1 = [fx_frame(TAPE_ECHO, 1, te['BASS']['aa'], v_bass), fx_frame(TAPE_ECHO, 1, te['TAPE DIST']['aa'], v_dist)]
    ours2 = [fx_frame(TAPE_ECHO, 2, te['TREBLE']['aa'], v_two)]

    def both(action, label, insert):
        """action on parent and image; the image must send the parent's frames with `insert` (FxType frame ->
        frames) right after each such FxType frame, and nothing else."""
        out = []
        for mm in (p, m):
            mm.clear()
            action(mm)
            out.append(mm.frames())
        (pf, po, pok), (mf, mo, mok) = out
        want = []
        for f in pf:
            want.append(f)
            want += insert.get(f, [])
        check(pok and mok and mo == po and mf == want and any(f in insert for f in pf) == bool(insert),
              f'{label}: the parent\'s {len(pf)} frames' + (f', and after the FxType frame the bus\'s edited values '
                                                             f'({sum(len(v) for v in insert.values())} frames)'
                                                             if insert else ', nothing added'))
        return pf

    both(lambda mm: mm.set_bus(1, REVERB), 'BUS 1 to Reverb (stock MFX choice)', {})
    pf = both(lambda mm: mm.set_bus(1, TAPE_ECHO), 'BUS 1 back to Tape Echo (stock MFX choice)',
              {fxtype_frame(1, TAPE_ECHO): ours1})
    check(fxtype_frame(1, TAPE_ECHO) in pf, 'the stock effect select did send FxType1 = 9 there')
    both(lambda mm: mm.set_bus(1, TAPE_ECHO), 'BUS 1 Tape Echo chosen again (stock sends no FxType: the chip still '
                                              'has it)', {})
    both(lambda mm: mm.dispatch(EV_KNOB, 1, 90), 'a CTRL knob on BUS 1 Tape Echo', {})
    both(lambda mm: mm.call(SYS_SET, SYSPRM, 0x7F, REVERB, 0), 'FxType1 = Reverb through the system setter', {})
    both(lambda mm: mm.call(SYS_SET, SYSPRM, 0x7F, TAPE_ECHO, 0), 'FxType1 = Tape Echo through the system setter',
         {fxtype_frame(1, TAPE_ECHO): ours1})
    both(lambda mm: mm.call(SYS_SET, SYSPRM, 0x80, REVERB, 0), 'FxType2 = Reverb through the system setter', {})
    both(lambda mm: mm.call(SYS_SET, SYSPRM, 0x80, TAPE_ECHO, 0), 'FxType2 = Tape Echo: BUS 2\'s values only',
         {fxtype_frame(2, TAPE_ECHO): ours2})
    both(lambda mm: mm.call(SYS_SET, SYSPRM, 0x81, TAPE_ECHO, 0), 'FxType3 = Tape Echo (no edits on BUS 3)', {})
    both(lambda mm: mm.call(DT1, 0x80B62F09, 0x7F, 0, TAPE_ECHO),
         'FxType1 = Tape Echo sent straight to the builder, as the BUS 1/2 swap 0x8001b8e2 sends it',
         {fxtype_frame(1, TAPE_ECHO): ours1})
    both(lambda mm: mm.call(DT1, 0x80B62F09, 0x7E, 0, TAPE_ECHO), 'FxType0 (the input FX) = Tape Echo: not a bus',
         {})
    # the stock reload of the system object and the chip (as at boot), then the effect chosen again
    both(lambda mm: (mm.call(SYS_INIT, SYSPRM), mm.call(CHIP_RESET, 0x80591794, count=50_000_000)),
         'system init and the chip reset (every effect\'s CTRL 1-3 again, FxType 0 everywhere)', {})
    for mm in (m, p):
        mm.w32(FXTYPE_SENT + 4, 0xFFFFFFFF)            # the select's cache as boot leaves it
    both(lambda mm: mm.set_bus(1, TAPE_ECHO), 'after it, BUS 1 Tape Echo chosen again', {fxtype_frame(1, TAPE_ECHO): ours1})
    st_ = m.state()
    check(st_['sent'] == 3 and st_['resent'] == 2 + 2 + 1 + 2 + 2, f'the module counted 3 edits and 9 values sent '
                                                                   f'again ({st_})')


def stop_and_stale_checks(img, parent, man):
    """Closed page: four quick EXITs are STOP as on the parent; a chord whose VALUE release never came back: the
    next plain VALUE press and release go on as on the parent."""
    out = []
    for image in (parent, img):
        m = Machine(image, man['entries'])
        for _ in range(4):
            m.dispatch(EV_KEY, KEY_EXIT)
            m.dispatch(EV_KEY_UP, KEY_EXIT)
        out.append((m.frames(), m.popups))
    check(out[0] == out[1] and out[0][1] == [('STOP', 1000)], 'page closed: four quick EXITs are stock\'s STOP, byte '
                                                               'for byte as on the parent')
    out = []
    for image in (parent, img):
        m = Machine(image, man['entries'])
        m.dispatch(EV_KEY, KEY_EXIT)
        m.dispatch(EV_KEY, KEY_VALUE)                   # the chord; its release is lost
        m.dispatch(EV_KEY_UP, KEY_EXIT)
        m.press(KEY_EXIT)                               # here: closes the page the chord opened
        held = m.uc.mem_read(KEYS + (KEY_VALUE >> 3), 1)[0]
        m.uc.mem_write(KEYS + (KEY_VALUE >> 3), bytes([held & ~(1 << (KEY_VALUE & 7))]))   # let go elsewhere
        m.pause(600)
        out.append(run_script(m, [(EV_KEY, KEY_VALUE), (EV_KEY_UP, KEY_VALUE)]))
    check(out[0] == out[1] and all(r[3] for r in out[1]),
          'a chord whose VALUE release never came back: the next plain VALUE press and release go on to DOOM OS as '
          'on the parent')


SCRIPTS = (
    ('EXIT alone', [(EV_KEY, KEY_EXIT), (EV_KEY_UP, KEY_EXIT)]),
    ('VALUE alone', [(EV_KEY, KEY_VALUE), (EV_KEY_UP, KEY_VALUE)]),
    ('VALUE held, then EXIT', [(EV_KEY, KEY_VALUE), (EV_KEY, KEY_EXIT), (EV_KEY_UP, KEY_EXIT),
                               (EV_KEY_UP, KEY_VALUE)]),
    ('EXIT held, a pad', [(EV_KEY, KEY_EXIT), (EV_PAD, 3, 100), (EV_PAD_UP, 3, 0), (EV_KEY_UP, KEY_EXIT)]),
    ('EXIT held, SHIFT', [(EV_KEY, KEY_EXIT), (EV_KEY, KEY_SHIFT), (EV_KEY_UP, KEY_SHIFT), (EV_KEY_UP, KEY_EXIT)]),
    ('SHIFT held, VALUE', [(EV_KEY, KEY_SHIFT), (EV_KEY, KEY_VALUE), (EV_KEY_UP, KEY_VALUE),
                           (EV_KEY_UP, KEY_SHIFT)]),
    ('EXIT held, VALUE turned', [(EV_KEY, KEY_EXIT), (EV_ENCODER, 0, 1), (EV_ENCODER, 0, -1), (EV_KEY_UP, KEY_EXIT)]),
    ('VALUE turned', [(EV_ENCODER, 0, 1), (EV_ENCODER, 0, -3)]),
    ('knobs', [(EV_KNOB, 1, 40), (EV_KNOB, 2, 90), (EV_KNOB, 3, 127), (EV_KNOB, 3, 3)]),
    ('pads', [(EV_PAD, 0, 127), (EV_PAD_UP, 0, 0), (EV_PAD, 15, 60), (EV_PAD_UP, 15, 0)]),
    ('a VALUE release alone', [(EV_KEY_UP, KEY_VALUE)]),
    ('an EXIT release alone', [(EV_KEY_UP, KEY_EXIT)]),
)
KEYS_ALONE = [k for k in range(0x10, 0x32) if k not in (0x13, KEY_VALUE)]


def run_script(m, script):
    out = []
    for kind, a1, *rest in script:
        m.clear()
        try:
            r = m.dispatch(kind, a1, rest[0] if rest else 0)
        except Exception as e:                          # stock paths the harness can't run end the same way
            r = f'{type(e).__name__}'
        out.append((r, bytes(v for p, v in m.uart), tuple(m.popups), tuple(m.doom), tuple(m.fallback),
                    bytes(m.uc.mem_read(KEYS, 16)), m.r16(PAGE_ID)))
    return out


def passthrough_checks(img, parent, man):
    """Every event but the chord, page closed, with edited values held: exactly as the parent."""
    e = man['entries']
    for label, script in SCRIPTS:
        a, b = Machine(parent), Machine(img, e)
        for m in (a, b):                                # BUS 1 with an effect on, so knobs reach the chip
            m.set_bus(1, REVERB)
        for bus in range(4):                            # an edited value held for every bus's Reverb and Tape Echo
            for fx in (REVERB, TAPE_ECHO):
                i = b.r32(e['fde_first'] + fx) & 0xFF
                b.uc.mem_write(e['fde_value'] + bus * 142 + i, bytes([3]))
                b.uc.mem_write(e['fde_edited'] + bus * 142 + i, bytes([1]))
        x, y = run_script(a, script), run_script(b, script)
        check(x == y and all(r[3] for r in y), f'{label}: as on the parent, every event through DOOM OS\'s filter '
                                               f'({sum(len(r[1]) for r in y)} chip bytes)')
    bad = []
    for k in KEYS_ALONE:
        script = [(EV_KEY, k), (EV_KEY_UP, k)]
        if run_script(Machine(parent), script) != run_script(Machine(img, man['entries']), script):
            bad.append(hex(k))
    check(not bad, f'each of {len(KEYS_ALONE)} keys pressed and released alone: as on the parent ({bad})')
    m = Machine(img, man['entries'])
    m.set_bus(1, REVERB)
    m.clear()
    m.dispatch(EV_KNOB, 3, 127)
    got, other, ok = m.frames()
    check(ok and got == [frame((3, 0, 0x2E, 4), 255)], f'TOP knob 3 with Reverb on BUS 1 still sends LEVEL 255 '
                                                       f'(03 00 2e 04 = 0f 0f) through the stock knob path (and '
                                                       f'{[q.hex() for q in other]} on MIDI out)')


def main():
    out = Path(sys.argv[1])
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    parent = Path(man['parent_app1']).read_bytes()
    fxmap_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(man['fxmap']['path'])
    fxmap_bytes = fxmap_path.read_bytes()
    if sha(fxmap_bytes) != man['fxmap']['sha256']:
        raise ValueError('fxmap.json differs from the one the build used')
    fxmap = {e['id']: e for e in json.loads(fxmap_bytes)}
    st = Settings(Runtime(parent), fxmap)
    static_checks(out, man, img, parent, fxmap, st)
    builder_checks(img, parent, man, fxmap, st)
    page_checks(img, parent, man, st)
    open_passthrough_checks(img, parent, man, st)
    range_checks(img, man, st)
    resend_checks(img, parent, man, st)
    stop_and_stale_checks(img, parent, man)
    passthrough_checks(img, parent, man)
    print(json.dumps(dict(cases=cases[0])))
    print('ALL PASS' if not fails else f'{len(fails)} FAILED')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
