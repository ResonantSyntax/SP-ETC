"""Checks for the note repeat build (build_note_repeat.py).

usage: python synth/test_note_repeat.py OUT_DIR [SECTIONS]      (unicorn, keystone, capstone on PYTHONPATH)

SECTIONS: a comma list of static, names, timing, value, triplet, roll, ring, subpad, hold, gate, release, dj,
recorder, passthrough, chroma.

Reads OUT_DIR/manifest.json for the parent APP1. Static checks first: only the header's scatter pointer, the five
entry jumps and the appended tail differ from the parent; the guards and the recognised call sites hold on the
parent; nothing reaches into the displaced bytes; the module's copies of them; the division table and names
match the firmware's own. Then the parent and the new image are booted in Unicorn the way their scatter loader
does it, with the boot's static constructors run (the RTOS under them stubbed: its pool by a bump allocator,
object creation by an id), and the TOP page object made by its registry handler as on page entry. Real stock
code runs: the UI task's dispatcher (0x8003b530) with TOP's registry handler, DOOM OS ED5E's page filter, TOP's
key and pad handlers, the generic key handler (0x800c9788) and its ROLL cases, the page pad handler (0x800c7db8),
the stock pad note (0x800cdbd0), the UI tick (0x8003c5f0, once per simulated millisecond), the pad getter and
setter, the project getter, the popup, the key light (0x800d4910 and its output on the chip link), the key-held
query through the kits' gate, the pattern recorder's pad-note path (0x80050be0 -> 0x800bd5a0).
Modelled: SMPL TASK takes each pad event at the pad-event dispatcher (0x800bef10, logged with its millisecond);
the audio clock as the DMA interrupt leaves it (0x8059226c += 32 a 64-frame block, the cycle counter at 598500
a millisecond, both wrapping); the tempo function 0x80047dd0 answers the test's tempo; whether a voice plays a
pad (0x800d8c08); the stock roll (0x800163a8: logged, not run); the command post (0x800e25c0: logged); drawing;
the card (every file open fails). Not here: the voices, the SMPL and audio tasks, the UI task's real timing (its
tick runs every millisecond here unless a check makes it late), the screen, the effects chip.

Checks:
- timing: every division (stock's ten and the module's six triplets) at 60, 87.5, 120, 140, 174 and 300 BPM, 48
  repeats each: the k-th repeat comes
  at the first millisecond tick at or after the press + k x beats x 60 / BPM (to the frame), no drift; each
  repeat is a note-off then a note-on at the press's velocity; the first repeat comes a division after the
  press, and the pad's own hit is the stock one; 2000 repeats without drift; UI ticks late and bunched, and a
  300 ms stall (one repeat, then the grid again, no burst); a tempo change while rolling;
- VALUE while rolling: the division steps along the list at once (shorter: the next tick if already due),
  the popup names it with the firmware's own names, the pad's Roll setting follows; several pads at once;
  the ends of the list; SHIFT + ROLL's change of the pad's Roll is taken while rolling;
- triplets (test2): VALUE a step at a time through all sixteen divisions and back, the ends; what the pad keeps
  (Roll the nearest stock division, the triplet in PADCONF byte 0x70 bits 1-3, the follow bit untouched, the
  pads marked edited, the save a second after the last change once no pad repeats); a kept triplet rolls; Roll
  set elsewhere drops it (rolling or not); VALUE into a triplet mid-roll;
- ROLL + pad: goes on after the pad is let go until ROLL is let go (as stock), and a GATE pad gets its
  note-off then; pads held when ROLL goes down start at once; latch on a tap (popup, ROLL lit on the chip link),
  pads repeat only while held, a second tap unlatches (light back to stock's dim); a press with anything else
  touched is not a tap; EXIT + ROLL stops everything and unlatches;
- the follow flag: ROLL + VALUE press toggles the current pad's PADCONF byte 0x70 bit 0, marks the pads edited
  and posts the save (0xd) a second after the last change; an ignoring pad plays once, as without ROLL;
- LOOP pads without GATE: the stock roll asked for once the pad sounds (also when tapped again while it
  rolls), turned off at the end, no re-hits; with GATE they re-hit; SUB PAD repeats the last pad;
- HOLD while a pad rolls (test2): the roll goes on after the pad, ROLL, a ROLL tap and other pads; the pad
  blinks (not on DOOM OS's page) and HOLD is lit; hitting the pad again stops it (that press plays once,
  stock's way, and starts no roll), as do HOLD again with no pad down, and EXIT + ROLL; stock's own HOLD
  runs as well (the held pad's HOLD state as on the parent); a pad held without rolling keeps a held roll;
- the stock roll start in the note-on hears "ROLL not held" from its three call sites only while the module
  runs; every other key query is the kits' answer, as on the parent; ROLL's stock release handling
  (0x80135d40) does not run while the module runs, and does on the parent and in DJ mode;
- DJ Mixer Mode: ROLL, VALUE, HOLD and pads exactly as on the parent;
- the pattern recorder: each repeat reaches it (0x80030700) as a note-off and a note-on of that pad, the way a
  real tap of the pad does;
- every other key and pad path as on the parent: each key alone, with SHIFT, with EXIT and while ROLL is held,
  VALUE turns and presses, pads, SUB PAD, knobs, HOLD (pads held and let go by it), SHIFT + HOLD, SHIFT + ROLL,
  EXIT + ROLL; the same pad events, popups, chip bytes, DOOM OS calls, held keys and page;
- chromatic mode (test3, the chromatic page 0x18): every pad rolls at 1/16 of the sample's pad's tempo from
  power-on, whatever the pad under the finger holds (LOOP without GATE, set to ignore ROLL, Roll 1/64), its Roll
  and byte 0x70 untouched and no stock roll asked for; VALUE steps the one chromatic division for every
  chromatic pad at once and it is kept for the next roll; ROLL + VALUE press shows it and toggles no follow
  flag; with nothing repeating ROLL + VALUE steps it; latched with VALUE held, a turn is not taken.
"""
import hashlib
import json
import struct
import sys
from fractions import Fraction
from math import ceil, log
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_HOOK_CODE
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE
from unicorn import arm_const as ar

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_note_repeat import GUARDS, SITES, CALLERS, DISPLACED, KNOWN_SLOTS, Runtime, scatter, decompress, \
    branches_into, check_module  # noqa: E402

FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
HEAP = 0x32000000
KERNEL = {0x310C: 1, 0x22A4: 1, 0x32B8: 0}                 # RTOS object creation in the constructors: an id
SCREEN = (0x8006C088, 0x8006BD48, 0x8015F3A8, 0x800D8020, 0x800C1CC0)  # drawing: no display here
NOPS = (0xE668, 0x800D30A4)                              # debug prints, the SMPL TASK flag
FILE_OPEN = 0x800DEC60                                   # no card here: every file is missing
CTORS, NCTORS = 0x8383A30C, 70
STACK, RET, EVENT, SCRATCH = 0x30010000, 0x3001F000, 0x30095000, 0x30096000
UI_DISPATCH, UI_TICK, PAGE_ID, PAGE_LIVE, PREFILTER, KEY_PAIRS = (0x8003B530, 0x8003C5F0, 0x80245880, 0x8024587A,
                                                                  0x82DFD318, 0x80B119DC)
TOP_REGISTRY, TOP_PAGE, DOOM_FILTER = 0x8005EDA8, 0x80CFD350, 0x6031C8F8
POPUP, ROLL_POPUP, KEYS = 0x800D3FF0, 0x8006C048, 0x80592448
PAD_DISPATCH, TEMPO, SOUNDING, STOCK_ROLL, POST = 0x800BEF10, 0x80047DD0, 0x800D8C08, 0x800163A8, 0x800E25C0
PROJECT, PROJECT_GET, SMPL, PAD_GET, PAD_SET = 0x82E009D0, 0x800DDA38, 0x82E2CD08, 0x800DC6B8, 0x800DA720
LOADED, EXT = 0x82E495E4, 0x82E2CD08 + 0xF800
KEY_QUERY, RELEASE_BODY, NOTE_ON = 0x800D9F20, 0x80135D4C, 0x800AEC48
CONSUMER, RECORD, SEQ_STATE = 0x80050BE0, 0x80030700, 0x80591F20
CLOCK, CLOCK_CYCLES, CYCCNT = 0x8059226C, 0x80592264, 0xE0001004
EV_KEY, EV_KEY_UP, EV_ENCODER, EV_KNOB, EV_PAD, EV_PAD_UP = 5, 6, 7, 9, 0x10, 0x11
KEY_ROLL, KEY_EXIT, KEY_SHIFT, KEY_VALUE, KEY_HOLD = 0x21, 0x22, 0x2A, 0x31, 0x11
P_GATE, P_LOOP, P_ROLL = 0x6A, 0x6B, 0x7B
P_CHROMATIC, P_SOURCE, PROJECT_SET = 0xBF, 0xC1, 0x800DED18
CHROMA_PAGE, CHROMA_REGISTRY = 0x18, 0x80062A10       # the chromatic page and its registry handler
BEATS = {1: Fraction(2), 2: Fraction(1), 3: Fraction(1, 2), 4: Fraction(1, 4), 5: Fraction(1, 8), 6: Fraction(1, 16),
         7: Fraction(3, 2), 8: Fraction(3, 4), 9: Fraction(3, 8), 10: Fraction(3, 16),
         11: Fraction(4, 3), 12: Fraction(2, 3), 13: Fraction(1, 3), 14: Fraction(1, 6), 15: Fraction(1, 12),
         16: Fraction(1, 24)}                           # 11..16: the module's triplets (test2)
NAMES = ['Off', '1/2', '1/4', '1/8', '1/16', '1/32', '1/64', '3/8', '3/16', '3/32', '3/64']
TRIPLET_NAMES = ['1/2T', '1/4T', '1/8T', '1/16T', '1/32T', '1/64T']
ALL_NAMES = NAMES + TRIPLET_NAMES
ORDER = [1, 7, 11, 2, 8, 12, 3, 9, 13, 4, 10, 14, 5, 15, 6, 16]  # slowest first
TRIP_STOCK = {11: 7, 12: 8, 13: 9, 14: 10, 15: 6, 16: 6}  # a triplet's Roll: the nearest stock division
FOLLOW_BYTE, TRIP_MASK = 0x70, 0x0E
LED_LIT, LED_DIM = bytes.fromhex('010042ff'), bytes.fromhex('0101421f')
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


class Machine:
    def __init__(self, img, sym=None, tempo=12000):
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
        self.ms = 0
        self.tempo = tempo
        self.dj = None
        self.sounding = set()
        self.clear()
        uc.hook_add(UC_HOOK_CODE, self._malloc, None, begin=0x800E2C68, end=0x800E2C68)
        uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=0x800E2CA8, end=0x800E2CA8)
        for a, v in KERNEL.items():
            uc.hook_add(UC_HOOK_CODE, self._value, v, begin=a, end=a)
        for a in SCREEN + NOPS:
            uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=a, end=a)
        uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self._uart, None, begin=0x40184000, end=0x401A3FFF)
        uc.hook_add(UC_HOOK_CODE, self._open, None, begin=FILE_OPEN, end=FILE_OPEN)
        uc.hook_add(UC_HOOK_CODE, self._popup, None, begin=POPUP, end=POPUP)
        uc.hook_add(UC_HOOK_CODE, self._roll_popup, None, begin=ROLL_POPUP, end=ROLL_POPUP)
        uc.hook_add(UC_HOOK_CODE, self._doom, None, begin=DOOM_FILTER, end=DOOM_FILTER)
        for fn in struct.unpack(f'<{NCTORS}I', bytes(uc.mem_read(CTORS, 4 * NCTORS))):
            self.call(fn & ~1 | 1, count=50_000_000)
        # after the boot: SMPL TASK, the tempo, voices and the stock roll are the model's
        uc.hook_add(UC_HOOK_CODE, self._pad_event, None, begin=PAD_DISPATCH, end=PAD_DISPATCH)
        uc.hook_add(UC_HOOK_CODE, self._tempo, None, begin=TEMPO, end=TEMPO)
        uc.hook_add(UC_HOOK_CODE, self._sounding, None, begin=SOUNDING, end=SOUNDING)
        uc.hook_add(UC_HOOK_CODE, self._stock_roll, None, begin=STOCK_ROLL, end=STOCK_ROLL)
        uc.hook_add(UC_HOOK_CODE, self._post, None, begin=POST, end=POST)
        uc.hook_add(UC_HOOK_CODE, self._project_get, None, begin=PROJECT_GET, end=PROJECT_GET)
        uc.hook_add(UC_HOOK_CODE, self._seen, 'release body', begin=RELEASE_BODY, end=RELEASE_BODY)
        uc.hook_add(UC_HOOK_CODE, self._seen, 'generic key', begin=0x800C9788, end=0x800C9788)
        self.w32(PREFILTER, 0xFFFFFFFF)                 # no mode holds the keys
        uc.mem_write(KEY_PAIRS, b'\xff' * 0x80)         # no key pairs (memset -1 at boot)
        uc.mem_write(EVENT, struct.pack('<6h', 1, 0, 0, 0, 0, 0))
        self.call(TOP_REGISTRY, EVENT, count=20_000_000)  # the TOP page object, as on page entry
        self.page = self.r32(TOP_PAGE)
        uc.mem_write(PAGE_ID, struct.pack('<H', 1))
        uc.mem_write(PAGE_LIVE, struct.pack('<H', 1))
        for pad in list(range(16)) + list(range(32, 48)):
            self.load_pad(pad)
        self.clock()
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
        self.events, self.popups, self.uart, self.doom, self.rolls, self.posts, self.seen = [], [], [], [], [], [], []

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

    def _uart(self, uc, access, address, size, value, _):
        base, off = address & ~0x3FFF, address & 0x3FFF
        if access == UC_MEM_WRITE and off == 0x1C:
            self.uart.append(((base - 0x40184000) // 0x4000 + 1, value & 0xFF))
        elif off == 0x14:
            uc.mem_write(address, struct.pack('<I', 0x00C00000))    # transmit ready

    def _open(self, uc, a, size, _):
        self._ret(-1)

    def _popup(self, uc, a, size, _):
        text = bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R0), 64)).split(b'\0')[0].decode('latin-1')
        self.popups.append((self.ms, text))

    def _roll_popup(self, uc, a, size, _):
        text = bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R0), 64)).split(b'\0')[0].decode('latin-1')
        self.popups.append((self.ms, 'param ' + text))

    def _doom(self, uc, a, size, _):
        ev = uc.reg_read(ar.UC_ARM_REG_R1)
        self.doom.append(struct.unpack('<3h', bytes(uc.mem_read(ev, 6))))

    def _pad_event(self, uc, a, size, _):
        """SMPL TASK's ring: the event as the stock pad note built it (pad, type 4, vel or 0xff for a note-off)."""
        ev = bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R0), 16))
        self.events.append((self.ms, ev[0], ev[1], ev[3] if ev[3] < 0x80 else 0, ev))
        self._ret(0)

    def _tempo(self, uc, a, size, _):
        self._ret(self.tempo)

    def _sounding(self, uc, a, size, _):
        self._ret(1 if uc.reg_read(ar.UC_ARM_REG_R0) in self.sounding else 0)

    def _stock_roll(self, uc, a, size, _):
        r = self.regs()
        self.rolls.append((self.ms, s32(r[0]), r[1], r[2], r[3]))
        self._ret(0)

    def _post(self, uc, a, size, _):
        r = self.regs(3)
        self.posts.append((self.ms, r[0], r[1], r[2]))
        self._ret(0)

    def _project_get(self, uc, a, size, _):
        if self.dj is not None and uc.reg_read(ar.UC_ARM_REG_R1) == 0xC2:
            self._ret(self.dj)

    def _seen(self, uc, a, size, what):
        self.seen.append((self.ms, what) + tuple(self.regs(3)[1:]))

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack('<I', self.uc.mem_read(a, 4))[0]

    def r16(self, a):
        return struct.unpack('<H', self.uc.mem_read(a, 2))[0]

    def r8(self, a):
        return self.uc.mem_read(a, 1)[0]

    def call(self, fn, *args, count=5_000_000, until=RET, lr=RET | 1):
        uc = self.uc
        for k, v in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), v & 0xFFFFFFFF)
        uc.reg_write(ar.UC_ARM_REG_LR, lr)
        uc.reg_write(ar.UC_ARM_REG_SP, STACK)
        uc.emu_start(fn | 1, until, count=count)
        if uc.reg_read(ar.UC_ARM_REG_PC) != until:
            raise RuntimeError(f'{fn:#x} did not return (pc {uc.reg_read(ar.UC_ARM_REG_PC):#x})')
        return uc.reg_read(ar.UC_ARM_REG_R0)

    # ---- the panel ----
    def dispatch(self, kind, a1=0, a2=0):
        """An event through the UI task's own dispatcher (keys set and clear their held bits there)."""
        self.uc.mem_write(EVENT, struct.pack('<6h', kind, a1, a2, 0, 0, 0))
        return s32(self.call(UI_DISPATCH, EVENT, count=20_000_000))

    def press(self, key):
        self.dispatch(EV_KEY, key)

    def let_go(self, key):
        self.dispatch(EV_KEY_UP, key)

    def tap(self, key):
        self.press(key)
        self.let_go(key)

    def pad(self, index, vel=100):
        self.dispatch(EV_PAD, index, vel)

    def pad_up(self, index):
        self.dispatch(EV_PAD_UP, index, 0)

    def turn(self, n):
        self.dispatch(EV_ENCODER, 0, n)

    def clock(self):
        """The audio clock at self.ms, as the DMA interrupt leaves it: 32 a 64-frame block (4/3 ms) in 0x8059226c, the
        cycle counter at that block in 0x80592264; the cycle counter itself at 598500 a millisecond (798000 a block,
        the stock's own constant), all wrapping at 32 bits."""
        blocks = self.ms * 3 // 4
        self.w32(CLOCK, 32 * blocks)
        self.w32(CLOCK_CYCLES, blocks * 798000)
        self.w32(CYCCNT, self.ms * 598500)

    def run(self, ms):
        """The UI task's tick, once a millisecond here (0x8003a968 calls 0x8003c5f0(1))."""
        for _ in range(ms):
            self.ms += 1
            self.clock()
            self.call(UI_TICK, 1, count=5_000_000)

    # ---- pads ----
    def load_pad(self, pad):
        """The pad holds a sample: the loaded-sample table entry and the record's status word (the getter answers
        0 for parameters >= 0x3f without one, the setter refuses without a length)."""
        e = LOADED + pad * 36
        self.w32(e + 8, 2)
        self.w32(e + 0x18, 0)
        self.w32(e + 0x1C, 0x100000)
        self.w32(SMPL + 0xD0 + pad * 0xAC, 1)

    def get(self, param, pad):
        return s32(self.call(PAD_GET, SMPL, param, pad))

    def set(self, param, value, pad):
        self.call(PAD_SET, SMPL, param, value, pad)

    def ext(self, pad, byte):
        return self.r8(EXT + pad * 0x80 + byte)

    def notes(self, pad=None, since=None):
        return [(t, p, v) for t, p, k, v, _ in self.events if k == 4 and (pad is None or p == pad) and
                (since is None or t >= since)]

    def ons(self, pad=None, since=None):
        return [(t, p, v) for t, p, v in self.notes(pad, since) if v]

    def leds(self, key=0x21):
        b = bytes(v for p, v in self.uart if p == 3)
        pk = [b[i:i + 4] for i in range(0, len(b) - 3, 4)]
        return [q for q in pk if q[0] == 1 and q[2] == key + 0x21]

    def state(self):
        b = bytes(self.uc.mem_read(self.sym['nr'], 8))
        return dict(held=b[0], latched=b[1], tap=b[2], led=b[3], active=b[5])

    def roll(self, pad):
        return self.get(P_ROLL, pad)

    def set_div(self, div, pad):
        """A division kept with the pad the module's way: Roll (a triplet's nearest stock division), and the
        triplet (1..6) in byte 0x70's bits 1-3."""
        self.set(P_ROLL, TRIP_STOCK.get(div, div), pad)
        b = self.ext(pad, FOLLOW_BYTE) & ~TRIP_MASK & 0xFF
        self.uc.mem_write(EXT + pad * 0x80 + FOLLOW_BYTE, bytes([b | ((div - 10) << 1 if div > 10 else 0)]))

    def kept(self, pad):
        """What the pad keeps: (Roll, the triplet in byte 0x70 bits 1-3, the follow bit)."""
        b = self.ext(pad, FOLLOW_BYTE)
        return self.roll(pad), (b & TRIP_MASK) >> 1, b & 1

    def repeats(self):
        """The module's repeats in use: (pad, held by HOLD)."""
        b = bytes(self.uc.mem_read(self.sym['nr_rep'], 16 * 32))
        return [(b[32 * i + 1], b[32 * i + 8]) for i in range(16) if b[32 * i]]

    def hold_state(self, pad):
        """Stock's per-pad HOLD state (settings 10): 1 down, 2 held."""
        return s32(self.call(0x800D94D8, 0x82E01144, 10, pad))

    def lights(self):
        b = bytes(v for p, v in self.uart if p == 3)
        return [b[i:i + 4] for i in range(0, len(b) - 3, 4) if b[i] == 1]


def frames_period(div, bpm100):
    return Fraction(288000000) * BEATS[div] / bpm100


def expected_ticks(div, bpm100, n, start=0):
    """The tick (ms after the press) of each of the first n repeats: the first at or after its frame."""
    p = frames_period(div, bpm100)
    return [start + ceil(Fraction(int(i * p), 48)) for i in range(1, n + 1)]


# ---- static ----
def static_checks(out, man, img, parent):
    check(sha(img) == man['sha256'] and len(img) == man['size'], 'APP1 matches its manifest')
    check(sha((out / 'SP404MKII_APP0.bin').read_bytes()) == man['app0_sha256'] ==
          '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23', 'APP0 is stock 5.52')
    sums = (out / 'SHA256SUMS.txt').read_text(encoding='utf-8').split()
    check(dict(zip(sums[1::2], sums[0::2])) == {n: sha((out / n).read_bytes()) for n in (
        'SP404MKII_APP0.bin', 'SP404MKII_APP1.bin', 'manifest.json')}, 'SHA256SUMS.txt matches the files')
    check(sha(parent) == '7b5fbcb4c3ce1e8782fef4b5803be74c7d14eddf25a1b53682abe00c9ed3684a',
          'the parent is the published v9.46 APP1 (7b5fbcb4)')
    rows, prow = scatter(img), scatter(parent)
    blob_row = [FLASH + man['blob_file_offset'], man['blob_base'], man['blob_size'], COPY]
    check(rows == prow + [blob_row], 'scatter table: the parent\'s rows plus one copy row for the module')

    def file_off(addr):
        return [load - FLASH + addr - dst for load, dst, n, fn in prow if fn == COPY and load and dst <= addr < dst + n][0]
    allowed = set(range(0x80, 0x88))
    for addr, original, what, entry, back in SITES:
        allowed |= set(range(file_off(addr), file_off(addr) + len(original)))
    diff = [i for i in range(len(parent)) if img[i] != parent[i]]
    check(set(diff) <= allowed and len(diff) > 40, f'only the scatter pointer and the five entries change inside the '
                                                   f'parent ({len(diff)} bytes)')
    rt, nrt = Runtime(parent), Runtime(img)
    check(all(sha(rt.read(s, e - s)) == d for s, e, d, w in GUARDS), f'{len(GUARDS)} guards hold on the parent')
    check(all(rt.read(at, len(b)) == b and at + len(b) + 1 == lr for lr, (at, b, w) in CALLERS.items()),
          f'the {len(CALLERS)} call sites whose return addresses the module recognises hold on the parent')
    e = man['entries']
    jumps = []
    for addr, original, what, entry, back in SITES:
        got = nrt.read(addr, len(original))
        lo, hi = e[entry] & 0xFFFF, e[entry] >> 16
        want = struct.pack('<4HH', 0xF240 | (lo >> 12) | ((lo >> 11) & 1) << 10, ((lo >> 8) & 7) << 12 | 12 << 8 | lo & 0xFF,
                           0xF2C0 | (hi >> 12) | ((hi >> 11) & 1) << 10, ((hi >> 8) & 7) << 12 | 12 << 8 | hi & 0xFF,
                           0x4760)
        jumps.append(rt.read(addr, len(original)) == original and got[:10] == want and
                     got[10:] == b'\x00\xbf' * ((len(original) - 10) // 2))
    check(all(jumps), 'each entry: the parent\'s instructions there, movw ip / movt ip / bx ip to the module here')
    inside = [(hex(a), branches_into(rt, a + 1, a + len(o))) for a, o, *_ in SITES]
    check(not any(x for _, x in inside), f'nothing branches into the displaced bytes ({inside})')
    module = nrt.read(man['blob_base'], man['blob_size'])
    try:
        check_module(module, e, man['blob_base'])
        ok = True
    except ValueError as err:
        ok = str(err)
    check(ok is True, f'the module\'s copies of the displaced instructions and its bridges ({ok})')
    slot = man['slot']
    check(module == img[man['blob_file_offset']:man['blob_file_offset'] + man['blob_size']] and
          slot[0] == man['blob_base'] and man['blob_base'] + man['blob_size'] <= slot[1] and
          not any(max(lo, slot[0]) < min(hi, slot[1]) for _, lo, hi in KNOWN_SLOTS),
          f'the module ({man["blob_size"]} bytes) fits its slot {slot[0]:#x}..{slot[1]:#x}, clear of every other '
          f'fork module')
    table = [struct.unpack_from('<f', rt.read(0x801A9F18 + 4 * i, 4))[0] for i in range(11)]
    check(table[1:] == [float(BEATS[d]) for d in range(1, 11)], f'the firmware\'s Roll table (0x801a9f18) is the '
                                                                   f'test\'s beats per division ({table})')
    names = [nrt.read(e['nr_div_names'] + 6 * i, 6).split(b'\0')[0].decode() for i in range(17)]
    order = list(nrt.read(e['nr_div_order'], 16))
    check(names == ALL_NAMES and order == ORDER and sorted(ORDER, key=lambda d: -BEATS[d]) == ORDER and
          sorted(ORDER) == list(range(1, 17)),
          f'the module\'s names are the test\'s, stock\'s ten then six triplets; its VALUE order runs slowest to '
          f'fastest through all sixteen ({names}, {order})')
    near = {t: min(range(1, 11), key=lambda d: abs(log(BEATS[d] / BEATS[t]))) for t in range(11, 17)}
    stock = list(nrt.read(e['nr_trip_stock'], 6))
    check(near == TRIP_STOCK and stock == [TRIP_STOCK[t] for t in range(11, 17)],
          f'each triplet\'s Roll value is the nearest stock division ({stock})')


def firmware_names_check(parent):
    """The firmware's own value text for Roll (0x800bf788, what SHIFT + ROLL shows) is the module's list."""
    m = Machine(parent)
    got = []
    for v in range(11):
        m.uc.mem_write(SCRATCH, bytes(64))
        m.uc.mem_write(SCRATCH + 0x100, struct.pack('<IH', 0x7B0002, 0xFFFF))
        m.call(0x800BF788, 0x82E02518, SCRATCH, SCRATCH + 0x100, v)
        got.append(bytes(m.uc.mem_read(SCRATCH, 16)).split(b'\0')[0].decode('latin-1'))
    check(got == NAMES, f'the firmware names Roll 0..10 {got} (0x800bf788), the module\'s list')


# ---- timing ----
def timing_checks(img, man):
    bad, n_hits, worst = [], 0, Fraction(0)
    for bpm100 in (6000, 8750, 12000, 14000, 17400, 30000):
        for div in range(1, 17):
            m = Machine(img, man['entries'], tempo=bpm100)
            m.set_div(div, 3)
            m.run(5)
            m.press(KEY_ROLL)
            m.run(3)
            t0 = m.ms
            m.pad(3, 90)
            m.pad_up(3)                                 # as stock: the roll goes on while ROLL is held
            first = m.notes(3)
            n = 48
            p = frames_period(div, bpm100)
            m.run(int(ceil(n * p / 48)) + 2)
            ons = m.ons(3, since=t0 + 1)
            offs = [x for x in m.notes(3, since=t0 + 1) if not x[2]]
            want = expected_ticks(div, bpm100, n, t0)
            got = [t for t, _, _ in ons][:n]
            n_hits += len(got)
            for i, t in enumerate(got):
                worst = max(worst, abs(Fraction(t - t0) - (i + 1) * p / 48))
            if first != [(t0, 3, 90), (t0, 3, 0)] or got != want or [t for t, _, _ in offs][:n] != want or \
                    any(v != 90 for _, _, v in ons) or len(ons) < n:
                bad.append((bpm100, div, first, got[:4], want[:4]))
    check(not bad and worst < Fraction(49, 48), f'every division (stock\'s ten, the six triplets) at 60, 87.5, 120, '
                                                 f'140, 174 and 300 BPM: the pad\'s '
                                                 f'own hit and release (stock), then each repeat (a note-off and a note-on at its '
                                                 f'velocity) at the first tick at or after press + k x beats x 60 / BPM '
                                                 f'({n_hits} repeats; worst {float(worst):.3f} ms after its exact '
                                                 f'time, no drift) {bad[:3]}')
    # long run, odd tempo: no drift after 2000 repeats
    m = Machine(img, man['entries'], tempo=13337)
    m.set(P_ROLL, 6, 3)
    m.press(KEY_ROLL)
    t0 = m.ms
    m.pad(3)
    p = frames_period(6, 13337)
    m.run(int(ceil(2000 * p / 48)) + 2)
    got = [t for t, _, _ in m.ons(3, since=t0 + 1)][:2000]
    check(got == expected_ticks(6, 13337, 2000, t0), f'1/64 at 133.37 BPM for 2000 repeats: every one on its tick, '
                                                     f'none early or late ({len(got)})')
    # the UI task's ticks irregular (late, bunched): the repeats keep to the audio clock, no drift
    m = Machine(img, man['entries'], tempo=14000)
    m.set(P_ROLL, 5, 3)                                 # 1/32 at 140: 53.57 ms
    m.press(KEY_ROLL)
    t0 = m.ms
    m.pad(3)
    ticks, gaps = [], [1, 3, 1, 7, 2, 1, 1, 5, 9, 1, 2, 4]
    for i in range(1100):                               # about 3.4 s
        m.ms += gaps[i % len(gaps)] - 1
        m.run(1)
        ticks.append(m.ms - t0)
    p = frames_period(5, 14000)
    want = []
    for k in range(1, 60):
        due = int(k * p)
        want.append(next(t for t in ticks if 48 * t >= due))
    got = [t - t0 for t, _, _ in m.ons(3, since=t0 + 1)][:59]
    check(got == want, f'UI ticks late and bunched (gaps of 1 to 9 ms): each repeat at the first tick at or after its '
                       f'time on the audio clock, no drift ({got[:6]} .. {got[-2:]})')
    # a long stall of the UI task: one repeat when it comes back, then the grid from there (no burst)
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 6, 3)                                 # 1/64 at 120: 31.25 ms
    m.press(KEY_ROLL)
    t0 = m.ms
    m.pad(3)
    m.run(100)
    m.ms += 300                                          # no tick for 300 ms
    m.run(1)
    back = m.ms
    m.run(100)
    after = [t - back for t, _, _ in m.ons(3, since=back)]
    check(after[:4] == [0, 32, 63, 94], f'the UI task stalled 300 ms: one repeat when it comes back, then every 1/64 '
                                        f'from there, no burst ({after[:4]})')
    # tempo change while rolling: the next period at the new tempo
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.press(KEY_ROLL)
    t0 = m.ms
    m.pad(3)
    m.run(130)                                          # one 1/16 at 120 = 125 ms: a repeat at 125
    m.tempo = 6000
    m.run(600)
    got = [t - t0 for t, _, _ in m.ons(3, since=t0 + 1)]
    check(got[:3] == [125, 375, 625], f'tempo 120 -> 60 while rolling: at once, the next repeat a new period after the '
                                      f'last one (repeats at {got[:3]} ms)')


# ---- VALUE ----
def value_checks(img, man):
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)                                 # 1/16: 125 ms at 120
    m.press(KEY_ROLL)
    t0 = m.ms
    m.pad(3)
    m.run(260)                                          # repeats at 125, 250
    m.turn(1)                                           # 1/16 -> 3/64 (93.75 ms): next at 250 + 93.75
    m.run(200)
    got = [t - t0 for t, _, _ in m.ons(3, since=t0 + 1)]
    check(got[:4] == [125, 250, 344, 438] and m.popups[-1][1] == 'Roll 3/64' and m.roll(3) == 10,
          f'VALUE right while rolling: the next repeat a 3/64 after the last one, then every 3/64; popup '
          f'"{m.popups[-1][1]}", the pad\'s Roll {m.roll(3)} ({got[:5]})')
    m.run(5)
    t1 = m.ms
    last = [t for t, _, _ in m.ons(3)][-1]
    m.turn(-4)                                          # 3/64 -> 1/16 -> 1/8T -> 3/32 -> 1/8 (250 ms)
    m.run(600)
    got = [t for t, _, _ in m.ons(3, since=t1)]
    check(got[:2] == [last + 250, last + 500] and m.popups[-1][1] == 'Roll 1/8' and m.roll(3) == 3,
          f'VALUE four left at once: 1/8, the next repeat a 1/8 after the last ({got[:2]}, last {last})')
    t2 = m.ms
    last = [t for t, _, _ in m.ons(3)][-1]
    m.turn(8)                                           # 1/8 -> 1/64 (31.25): long past due -> the next tick
    m.run(100)
    got = [t for t, _, _ in m.ons(3, since=t2)]
    check(got[:3] == [t2 + 1, t2 + 32, t2 + 63], f'VALUE to 1/64 with the next one long due: a repeat at the next '
                                                f'tick, then every 1/64 from the turn ({[x - t2 for x in got[:3]]})')
    m.turn(5)
    check(m.popups[-1][1] == 'Roll 1/64T' and m.kept(3) == (6, 6, 0),
          f'the fast end stays at 1/64T (Roll 1/64, triplet 6) {m.kept(3)}')
    m.turn(-20)
    check(m.popups[-1][1] == 'Roll 1/2' and m.kept(3) == (1, 0, 0), f'the slow end stays at 1/2 {m.kept(3)}')
    # several pads: each steps its own division
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.set(P_ROLL, 3, 5)
    m.press(KEY_ROLL)
    m.pad(3)
    m.pad(5)
    m.run(10)
    m.turn(1)
    check(m.roll(3) == 10 and m.roll(5) == 9 and m.popups[-1][1] == 'Roll 3/32',
          f'two pads rolling, VALUE right: each pad one step faster (1/16 -> 3/64, 1/8 -> 3/32), the popup shows the '
          f'last pad pressed ({m.roll(3)}, {m.roll(5)}, "{m.popups[-1][1]}")')
    # nothing rolling, ROLL held: the current pad's division
    m = Machine(img, man['entries'], tempo=12000)
    m.pad(6)
    m.pad_up(6)                                         # A-07 current
    m.set(P_ROLL, 2, 6)
    m.press(KEY_ROLL)
    m.turn(1)
    m.let_go(KEY_ROLL)
    check(m.roll(6) == 8 and m.popups[-1][1] == 'Roll 3/16' and not m.state()['latched'],
          f'ROLL held, nothing rolling, VALUE right: the current pad\'s Roll 1/4 -> 3/16, and that hold was not a tap '
          f'({m.roll(6)}, {m.popups[-1:]})')
    # SHIFT + ROLL's change while rolling is taken (the stock popup cycle is not reachable here: set it as it does)
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 2, 3)
    m.press(KEY_ROLL)
    t0 = m.ms
    m.pad(3)
    m.run(510)                                          # 1/4: repeats at 500
    m.set(P_ROLL, 4, 3)                                 # what SHIFT + ROLL's cycle writes
    m.run(500)
    got = [t - t0 for t, _, _ in m.ons(3, since=t0 + 1)]
    check(got[:3] == [500, 625, 750], f'the pad\'s Roll changed while rolling (SHIFT + ROLL): taken at the next tick '
                                      f'({got[:3]})')


# ---- triplets (test2) ----
def triplet_checks(img, man):
    # VALUE one step at a time through the whole list while a pad rolls, and back
    m = Machine(img, man['entries'], tempo=12000)
    m.set_div(1, 3)
    m.press(KEY_ROLL)
    m.pad(3)
    m.run(5)
    up, down = [], []
    for _ in range(16):
        m.turn(1)
        up.append((m.popups[-1][1], m.kept(3)))
    for _ in range(16):
        m.turn(-1)
        down.append((m.popups[-1][1], m.kept(3)))
    want = [('Roll ' + ALL_NAMES[d], (TRIP_STOCK.get(d, d), d - 10 if d > 10 else 0, 0)) for d in ORDER]
    check(up == want[1:] + want[-1:] and down == want[-2::-1] + want[:1],
          f'VALUE a step at a time from 1/2: {" ".join(p[5:] for p, _ in up)}, staying at 1/64T; back down, staying '
          f'at 1/2; Roll holds each stock division or a triplet\'s nearest one, byte 0x70 bits 1-3 the triplet')
    m.run(1500)                                         # still rolling, well past a second
    saves = [p for p in m.posts if p[1] == 0xD]
    m.let_go(KEY_ROLL)
    t = m.ms
    m.run(1100)
    after = [p[0] - t for p in m.posts if p[1] == 0xD]
    check(not saves and after == [1000] and m.r8(SMPL + 0x1C) == 1,
          f'the pads are marked edited and saved (0xd) a second after the last change, not while a pad repeats '
          f'(1.5 s of rolling first: {saves}; {after})')
    # the current pad, nothing rolling: its follow bit stays, a triplet alone (Roll unchanged) marks the pads edited
    m = Machine(img, man['entries'], tempo=12000)
    m.pad(6)
    m.pad_up(6)                                         # A-07 current
    m.set_div(10, 6)                                    # 3/64
    m.uc.mem_write(EXT + 6 * 0x80 + FOLLOW_BYTE, bytes([m.ext(6, FOLLOW_BYTE) | 1]))   # A-07 ignores ROLL
    m.uc.mem_write(SMPL + 0x1C, b'\0')
    m.posts = []
    m.press(KEY_ROLL)
    m.turn(1)                                           # 3/64 -> 1/16T: Roll stays 3/64
    k1, edited = m.kept(6), m.r8(SMPL + 0x1C)
    m.press(KEY_VALUE)                                  # ROLL + VALUE press: A-07 follows again
    m.let_go(KEY_VALUE)
    k2 = m.kept(6)
    m.turn(1)                                           # 1/16T -> 1/32
    k3 = m.kept(6)
    m.let_go(KEY_ROLL)
    m.run(1100)
    check(k1 == (10, 4, 1) and edited == 1 and k2 == (10, 4, 0) and k3 == (5, 0, 0) and
          m.popups[-1][1] == 'Roll 1/32' and [p[1:] for p in m.posts] == [(0xD, 1, 0)],
          f'ROLL held, nothing rolling: the current pad steps 3/64 -> 1/16T (Roll stays 3/64, triplet 4, its follow '
          f'bit kept, marked edited) -> 1/32 (triplet gone); the follow toggle leaves the triplet; one save '
          f'({k1}, {k2}, {k3}, {m.posts})')
    # a triplet kept with the pad: ROLL + pad rolls at it; SHIFT + ROLL setting Roll drops it
    m = Machine(img, man['entries'], tempo=12000)
    m.set_div(14, 3)                                    # 1/16T (Roll 3/64)
    m.press(KEY_ROLL)
    t0 = m.ms
    m.pad(3)
    m.run(260)                                          # 1/16T at 120: 83.33 ms
    m.set(P_ROLL, 4, 3)                                 # what SHIFT + ROLL's cycle writes: 1/16
    m.run(300)
    got = [t - t0 for t, _, _ in m.ons(3, since=t0 + 1)]
    check(got[:5] == [84, 167, 250, 375, 500] and m.kept(3) == (4, 0, 0),
          f'a pad keeping 1/16T rolls at 1/16T; Roll changed while rolling (SHIFT + ROLL): 1/16 at the next tick and '
          f'the triplet dropped ({got[:5]}, {m.kept(3)})')
    m = Machine(img, man['entries'], tempo=12000)
    m.set_div(14, 3)
    m.set(P_ROLL, 5, 3)                                 # Roll set to 1/32 elsewhere, not rolling
    m.press(KEY_ROLL)
    t0 = m.ms
    m.pad(3)
    m.run(200)
    got = [t - t0 for t, _, _ in m.ons(3, since=t0 + 1)]
    check(got[:3] == [63, 125, 188] and m.kept(3) == (5, 0, 0),
          f'Roll no longer the triplet\'s neighbour (set elsewhere): the pad rolls at Roll, the triplet dropped '
          f'({got[:3]}, {m.kept(3)})')
    m = Machine(img, man['entries'], tempo=12000)
    m.pad(6)
    m.pad_up(6)                                         # A-07 current
    m.set_div(14, 6)
    m.set(P_ROLL, 5, 6)                                 # the same, nothing rolling: VALUE steps from Roll's 1/32
    m.press(KEY_ROLL)
    m.turn(1)
    m.let_go(KEY_ROLL)
    check(m.popups[-1][1] == 'Roll 1/32T' and m.kept(6) == (6, 5, 0),
          f'and VALUE on the current pad steps from Roll (1/32 -> 1/32T: Roll 1/64, triplet 5), not from the old '
          f'triplet ("{m.popups[-1][1]}", {m.kept(6)})')
    # VALUE into a triplet mid-roll
    m = Machine(img, man['entries'], tempo=12000)
    m.set_div(4, 3)                                     # 1/16: 125 ms
    m.press(KEY_ROLL)
    t0 = m.ms
    m.pad(3)
    m.run(130)                                          # a repeat at 125
    m.turn(2)                                           # 1/16 -> 3/64 -> 1/16T (83.33 ms)
    m.run(300)
    got = [t - t0 for t, _, _ in m.ons(3, since=t0 + 1)]
    check(got[:4] == [125, 209, 292, 375] and m.popups[-1][1] == 'Roll 1/16T' and m.kept(3) == (10, 4, 0),
          f'VALUE two right while rolling 1/16: 1/16T, the next repeat a 1/16T after the last, then every 1/16T '
          f'({got[:4]})')


# ---- ROLL, latch, follow ----
def roll_checks(img, man):
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.set(P_GATE, 1, 3)                                 # a GATE pad
    m.press(KEY_ROLL)
    t0 = m.ms
    m.pad(3)
    m.run(60)
    m.pad_up(3)
    m.run(400)
    n1 = len(m.ons(3))
    m.let_go(KEY_ROLL)
    t1 = m.ms
    tail = m.notes(3, since=t1)
    m.run(500)
    check(n1 == 4 and tail == [(t1, 3, 0)] and len(m.ons(3)) == 4 and m.state()['active'] == 0 and
          not m.state()['latched'],
          f'ROLL + pad, the pad let go first: repeats go on until ROLL is let go, then the GATE pad gets its note-off '
          f'and nothing more ({n1} hits, tail {tail})')
    check(not [s for s in m.seen if s[1] == 'release body'],
          'ROLL let go: stock\'s release handling (0x80135d40: roll the current pad if it sounds) does not run')
    # pads held when ROLL goes down start at once
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 3, 3)
    m.pad(3)
    m.run(50)
    m.press(KEY_ROLL)
    t0 = m.ms
    m.run(300)
    got = [t - t0 for t, _, _ in m.ons(3, since=t0)]
    check(got[:2] == [1, 250], f'a pad held when ROLL goes down: a repeat at the next tick, then every 1/8 from the '
                               f'press of ROLL ({got[:2]})')
    m.pad_up(3)
    m.run(300)
    check(len(m.ons(3, since=t0)) == 3 and m.state()['active'] == 1,
          'that pad let go while ROLL is held: it goes on (it started under ROLL)')
    m.let_go(KEY_ROLL)
    m.run(300)
    check(len(m.ons(3, since=t0)) == 3 and m.state()['active'] == 0 and m.state()['latched'] == 0,
          'ROLL let go: it stops, and that hold (a pad was held) was not a tap')
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 3, 3)
    m.pad(3)
    m.run(50)
    m.press(KEY_ROLL)
    m.run(300)
    m.let_go(KEY_ROLL)                                  # the pad still held
    t1 = m.ms
    m.run(300)
    check(m.state()['latched'] == 0 and not m.ons(3, since=t1 + 1) and not [p for p in m.popups if 'Latch' in p[1]],
          'a pad held, ROLL pressed and let go with nothing else touched: it repeated, so no latch; it stops')
    m.pad_up(3)
    # latch
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.uart = []
    m.tap(KEY_ROLL)
    m.run(3)
    lit = m.leds()
    check(m.state()['latched'] == 1 and m.popups[-1][1] == 'Roll Latch On' and lit == [LED_LIT],
          f'a ROLL tap latches: popup "{m.popups[-1][1]}", ROLL lit on the chip link ({[x.hex() for x in lit]})')
    m.pad(3)
    t0 = m.ms
    m.run(300)
    m.pad_up(3)
    t1 = m.ms
    m.run(400)
    got = [t - t0 for t, _, _ in m.ons(3, since=t0 + 1)]
    check(got == [125, 250] and m.state()['active'] == 0 and not m.notes(3, since=t1 + 1),
          f'latched: a pad repeats while held and stops when let go ({got})')
    m.pad(5)
    m.pad_up(5)
    m.run(400)
    check(m.ons(5) == [(m.ons(5)[0][0], 5, 100)] if m.ons(5) else False, 'latched: a tapped pad plays once')
    m.uart = []
    m.tap(KEY_ROLL)
    m.run(3)
    check(m.state()['latched'] == 0 and m.popups[-1][1] == 'Roll Latch Off' and m.leds() == [LED_DIM],
          f'another tap unlatches: popup "{m.popups[-1][1]}", ROLL back to stock\'s dim ({[x.hex() for x in m.leds()]})')
    m.pad(3)
    m.run(400)
    check(len(m.ons(3)) == 3 + 1, 'unlatched: a held pad plays once')
    m.pad_up(3)
    m = Machine(img, man['entries'])
    m.press(KEY_ROLL)
    m.dispatch(EV_KNOB, 1, 40)
    m.let_go(KEY_ROLL)
    m.press(KEY_ROLL)
    m.turn(1)
    m.let_go(KEY_ROLL)
    check(not m.state()['latched'] and not [p for p in m.popups if 'Latch' in p[1]],
          'a CTRL knob turned, or VALUE turned, while ROLL is down: no latch')
    # the light is kept while latched: something else writes ROLL's light, the next tick lights it again
    m = Machine(img, man['entries'])
    m.tap(KEY_ROLL)
    m.run(2)
    m.call(0x800D4910, 0x21, 0, 0x1F)                   # e.g. the stock LED update
    m.uart = []
    m.run(2)
    check(m.leds() == [LED_LIT], 'latched: ROLL\'s light written dim by something else is lit again at the next tick')
    # latched, ROLL held while a new pad is pressed: it goes on under ROLL, the release is no tap
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.tap(KEY_ROLL)
    m.press(KEY_ROLL)
    m.pad(3)
    m.pad_up(3)
    m.run(300)
    n = len(m.ons(3))
    m.let_go(KEY_ROLL)
    m.run(300)
    check(n == 3 and len(m.ons(3)) == 3 and m.state()['latched'] == 1,
          'latched, ROLL held, a pad tapped: repeats until ROLL is let go; still latched afterwards')
    # EXIT + ROLL: everything off, unlatched (and stock's all-off)
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.tap(KEY_ROLL)
    m.pad(3)
    m.run(200)
    m.press(KEY_ROLL)
    m.press(KEY_EXIT)
    m.let_go(KEY_ROLL)
    m.let_go(KEY_EXIT)
    m.run(400)
    check(m.state()['latched'] == 0 and m.state()['active'] == 0 and len(m.ons(3)) == 2 and
          [r[1:] for r in m.rolls] == [(-1, 0, 0, 0)],
          f'EXIT + ROLL let go: our repeats stop, the latch goes, stock\'s all rolls off (0x800163a8(-1, 0)) runs '
          f'({m.rolls})')
    m.pad_up(3)
    # the same with EXIT down first
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.tap(KEY_ROLL)
    m.pad(3)
    m.run(200)
    m.press(KEY_EXIT)
    m.tap(KEY_ROLL)
    m.let_go(KEY_EXIT)
    m.run(400)
    check(m.state()['latched'] == 0 and m.state()['active'] == 0 and len(m.ons(3)) == 2 and
          [r[1:] for r in m.rolls] == [(-1, 0, 0, 0)],
          f'EXIT held, then ROLL: the same (test2; on test1 our repeats and the latch went on) ({m.rolls})')
    m.pad_up(3)
    # follow
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.pad(3)
    m.pad_up(3)                                         # A-04 current
    m.posts = []
    m.uc.mem_write(SMPL + 0x1C, b'\x00')
    m.press(KEY_ROLL)
    m.press(KEY_VALUE)
    m.let_go(KEY_VALUE)
    m.let_go(KEY_ROLL)
    flag, edited, latched = m.ext(3, 0x70), m.r8(SMPL + 0x1C), m.state()['latched']
    m.run(999)
    early = list(m.posts)
    m.run(2)
    check(flag == 1 and edited == 1 and not latched and m.popups[-1][1] == 'A-04 IGNORES ROLL' and not early and
          [p[1:] for p in m.posts] == [(0xD, 1, 0)],
          f'ROLL + VALUE press: A-04 ignores ROLL (PADCONF 0x70 bit 0), pads edited, the save (0xd) a second later, '
          f'no latch ({flag}, {edited}, "{m.popups[-1][1]}", {m.posts})')
    m.press(KEY_ROLL)
    m.pad(3)
    m.run(400)
    check(len(m.ons(3)) == 2, 'an ignoring pad with ROLL held plays once, as without ROLL')
    m.pad_up(3)
    m.press(KEY_VALUE)
    m.let_go(KEY_VALUE)
    m.let_go(KEY_ROLL)
    check(m.ext(3, 0x70) == 0 and m.popups[-1][1] == 'A-04 FOLLOWS ROLL', 'again: A-04 follows ROLL (byte 0x70 zero)')
    m.run(5)
    check(m.doom.count((5, KEY_VALUE, 0)) == 0 and m.doom.count((6, KEY_VALUE, 0)) == 0,
          'ROLL + VALUE press and its release are the module\'s: neither reaches the page')
    # a repeating pad told to ignore ROLL stops
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.tap(KEY_ROLL)
    m.pad(3)
    m.run(200)
    m.press(KEY_ROLL)
    m.press(KEY_VALUE)
    m.let_go(KEY_VALUE)
    m.let_go(KEY_ROLL)
    m.run(400)
    check(len(m.ons(3)) == 2 and m.state()['active'] == 0 and m.state()['latched'] == 1,
          'latched, a pad repeating, ROLL + VALUE press on it: it stops (ignores ROLL now), still latched')


def ring_checks(img, man):
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_LOOP, 1, 3)                                 # LOOP on, GATE off: a hit while playing would stop it
    m.set(P_ROLL, 4, 3)
    m.press(KEY_ROLL)
    m.pad(3)
    m.run(5)
    before = list(m.rolls)
    m.sounding.add(3)                                   # the voice is there
    m.run(400)
    started = [r for r in m.rolls if r[1] == 3]
    m.let_go(KEY_ROLL)
    m.run(5)
    stopped = [r for r in m.rolls if r[1] == 3]
    check(not before and [r[1:] for r in started] == [(3, 0x7F, 0, 0)] and len(m.ons(3)) == 1 and
          [r[1:] for r in stopped] == [(3, 0x7F, 0, 0), (3, 0, 0, 0)],
          f'a LOOP pad without GATE: the stock roll asked for once the pad sounds (0x800163a8(pad, 0x7f)), no '
          f're-hits, turned off at the end (0x800163a8(pad, 0)) ({m.rolls})')
    # tapped again while its stock roll runs: the roll goes on, asked for once (four stock roll slots)
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_LOOP, 1, 3)
    m.press(KEY_ROLL)
    m.pad(3)
    m.pad_up(3)
    m.sounding.add(3)
    m.run(50)
    m.pad(3)
    m.pad_up(3)
    m.run(50)
    m.let_go(KEY_ROLL)
    m.run(5)
    check([r[1:] for r in m.rolls] == [(3, 0x7F, 0, 0), (3, 0, 0, 0)],
          f'a LOOP pad tapped again while its stock roll runs: asked for once, turned off once ({m.rolls})')
    # with GATE on it re-hits
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_GATE, 1, 3)
    m.set(P_LOOP, 1, 3)
    m.load_pad(3)                                       # the LOOP setter re-charges the pad: its sample again
    m.set(P_ROLL, 4, 3)
    m.press(KEY_ROLL)
    m.pad(3)
    m.sounding.add(3)
    m.run(300)
    check(m.get(P_GATE, 3) == 1 and m.get(P_LOOP, 3) == 1 and not m.rolls and len(m.ons(3)) == 3,
          f'a LOOP pad with GATE on re-hits like any other ({m.get(P_GATE, 3)}, {m.get(P_LOOP, 3)}, {m.rolls})')


HOLD_LIT = bytes.fromhex('010031ff')
REPAINT = 0x802496F0


def blink(pad_index):
    """The three light messages of a pad (0..15) blinking white: page 6, its R, G and B."""
    return [bytes([1, 6, 3 * pad_index + k, 0xFF]) for k in range(3)]


def hold_checks(img, parent, man):
    # latched, a hat held and rolling, HOLD: a held roll
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.tap(KEY_ROLL)
    m.pad(3)
    m.run(130)                                          # repeat at 125
    m.uart = []
    m.uc.mem_write(REPAINT, b'\0\0')
    m.tap(KEY_HOLD)
    m.run(2)
    lit = m.lights()
    m.pad_up(3)
    m.run(400)                                          # 250, 375, 500
    n1 = len(m.ons(3))
    check(m.repeats() == [(3, 1)] and m.popups[-1][1] == 'Roll Held' and n1 == 5 and m.hold_state(3) == 2 and
          blink(3) == [x for x in lit if x[1] == 6] and HOLD_LIT in lit,
          f'latched, a pad held and rolling, HOLD: a held roll (popup "Roll Held"), it goes on after the pad is let '
          f'go; its pad blinks white, HOLD lit; stock\'s HOLD held the pad as always ({m.repeats()}, {n1} hits, '
          f'{[x.hex() for x in lit]})')
    m.tap(KEY_ROLL)                                     # unlatch
    m.pad(5)
    m.pad_up(5)
    m.run(260)
    n2 = len(m.ons(3))
    check(not m.state()['latched'] and m.repeats() == [(3, 1)] and n2 == n1 + 2 and len(m.ons(5)) == 1,
          f'a held roll goes on when ROLL is unlatched and another pad is played ({n2 - n1} more repeats)')
    m.tap(KEY_ROLL)                                     # latched again: the next press would roll
    t = m.ms
    m.pad(3)                                            # hit it again
    m.uc.mem_write(REPAINT, b'\0\0')                    # (the press itself asks stock for a full repaint)
    m.run(1)
    asked = m.r16(REPAINT)
    m.run(299)
    m.pad_up(3)
    m.run(200)
    after = m.ons(3, since=t)
    check(not m.repeats() and after == [(t, 3, 100)] and asked == 0x12,
          f'hitting its pad again stops it: that press plays once (stock\'s press), starts no roll though ROLL is '
          f'latched; at the next tick stock is asked to repaint the pads and keys, nothing else ({after}, '
          f'{asked:#x})')
    m = Machine(img, man['entries'], tempo=12000)
    m.run(5)
    m.uc.mem_write(REPAINT, b'\0\0')
    m.run(5)
    check(m.r16(REPAINT) == 0, 'idle, the module asks stock for no repaint')
    # a GATE pad: stock's HOLD takes the press to let the pad go (its note-off, nothing played)
    out = []
    for image in (parent, img):
        m = Machine(image, man['entries'] if image is img else None, tempo=12000)
        m.set(P_GATE, 1, 3)
        m.set(P_ROLL, 4, 3)
        m.tap(KEY_ROLL)
        m.pad(3)
        m.run(130)
        m.tap(KEY_HOLD)
        m.pad_up(3)
        m.run(200)
        t = m.ms
        m.pad(3)
        m.run(300)
        m.pad_up(3)
        m.run(50)
        out.append((m.notes(3, since=t), m.hold_state(3), m.repeats() if image is img else []))
    check(out[0] == out[1] and out[1][0] == [(t, 3, 0)],
          f'a GATE pad\'s held roll: hitting the pad again (stock\'s HOLD lets it go) stops it with stock\'s one '
          f'note-off, as on the parent ({out})')
    # SHIFT + pad: TOP does not play the pad, the held roll goes on
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.tap(KEY_ROLL)
    m.pad(3)
    m.tap(KEY_HOLD)
    m.pad_up(3)
    m.tap(KEY_ROLL)
    m.run(10)
    t = m.ms
    m.press(KEY_SHIFT)
    m.pad(3)
    m.pad_up(3)
    m.let_go(KEY_SHIFT)
    m.run(300)
    check(m.repeats() == [(3, 1)] and m.ons(3, since=t) == [(125, 3, 100), (250, 3, 100)],
          f'a press the page does not play (SHIFT + pad on TOP) leaves the held roll alone ({m.ons(3, since=t)})')
    m.tap(KEY_ROLL)                                     # latched again
    t = m.ms
    m.pad(0x13, 70)                                     # SUB PAD plays the last pad, 3
    m.run(300)
    m.pad_up(0x13)
    m.run(50)
    check(not m.repeats() and m.ons(3, since=t) == [(t, 3, 70)],
          f'SUB PAD playing a held roll\'s pad stops it the same way: one hit, no roll ({m.ons(3, since=t)})')
    # ROLL held, a pad tapped, HOLD while ROLL is still down; ROLL let go; HOLD again stops it
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.press(KEY_ROLL)
    m.pad(3)
    m.pad_up(3)
    m.run(130)
    m.tap(KEY_HOLD)
    m.let_go(KEY_ROLL)
    m.run(260)
    n1 = len(m.ons(3))
    m.tap(KEY_HOLD)
    m.run(300)
    check(n1 == 4 and m.popups[-1][1] == 'Roll Hold Off' and not m.repeats() and len(m.ons(3)) == 4 and
          not m.state()['latched'],
          f'ROLL held, a pad tapped and rolling, HOLD, ROLL let go: it goes on (no latch from that ROLL press); HOLD '
          f'again with no pad down stops it ("Roll Hold Off") ({n1}, {m.popups[-1:]})')
    # two pads held, HOLD holds both; EXIT + ROLL stops held rolls
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.set(P_ROLL, 3, 5)
    m.tap(KEY_ROLL)
    m.pad(3)
    m.pad(5)
    m.run(50)
    m.tap(KEY_HOLD)
    m.pad_up(3)
    m.pad_up(5)
    m.tap(KEY_ROLL)                                     # unlatch
    m.run(300)
    both = sorted(m.repeats())
    m.press(KEY_ROLL)
    m.press(KEY_EXIT)
    m.let_go(KEY_ROLL)
    m.let_go(KEY_EXIT)
    m.run(300)
    check(both == [(3, 1), (5, 1)] and not m.repeats() and len(m.ons(3)) == 3 and len(m.ons(5)) == 2,
          f'two pads rolling, HOLD: both held, they go on unlatched; EXIT + ROLL stops them ({both})')
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.tap(KEY_ROLL)
    m.pad(3)
    m.tap(KEY_HOLD)
    m.pad_up(3)
    m.run(130)
    m.press(KEY_EXIT)
    m.tap(KEY_ROLL)
    m.let_go(KEY_EXIT)
    m.run(300)
    check(not m.repeats() and len(m.ons(3)) == 2 and not m.state()['latched'],
          f'EXIT held first, then ROLL, stops a held roll too ({m.ons(3)})')
    # a LOOP pad without GATE: its held stock roll goes on, a hit stops it (and stock's press stops the loop)
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_LOOP, 1, 3)
    m.set(P_ROLL, 4, 3)
    m.tap(KEY_ROLL)
    m.pad(3)
    m.sounding.add(3)
    m.run(5)
    m.tap(KEY_HOLD)
    m.pad_up(3)
    m.tap(KEY_ROLL)                                     # unlatch
    m.run(300)
    kept = [r[1:] for r in m.rolls]
    t = m.ms
    m.pad(3)
    m.pad_up(3)
    m.run(5)
    check(kept == [(3, 0x7F, 0, 0)] and [r[1:] for r in m.rolls] == [(3, 0x7F, 0, 0), (3, 0, 0, 0)] and
          not m.repeats() and m.ons(3, since=t) == [(t, 3, 100)],
          f'a LOOP pad\'s held stock roll goes on unlatched; hitting the pad turns it off, the press goes to stock '
          f'({m.rolls})')
    # HOLD with held rolls and a pad down that does not roll: the held rolls stay (stock's HOLD holds that pad)
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.tap(KEY_ROLL)
    m.pad(3)
    m.tap(KEY_HOLD)
    m.pad_up(3)
    m.tap(KEY_ROLL)                                     # unlatched: pad 6 plays plainly
    m.pad(6)
    m.tap(KEY_HOLD)
    m.run(10)
    check(m.repeats() == [(3, 1)] and m.hold_state(6) == 2,
          'held roll on, another pad down (not rolling), HOLD: the held roll stays, stock holds that pad')
    m.pad_up(6)
    # outside the bank, on DOOM OS's page: no blink, HOLD still lit
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.tap(KEY_ROLL)
    m.pad(3)
    m.tap(KEY_HOLD)
    m.pad_up(3)
    m.uc.mem_write(PAGE_ID, struct.pack('<H', 0x5F))
    m.run(2)
    m.uart = []
    m.call(0x800D4910, 3, 1, 0x00FF00)                  # something else lights pad 4
    m.call(0x800D4910, 0x11, 0, 0x1F)                   # and dims HOLD
    m.uart = []
    m.run(3)
    lit = m.lights()
    check(lit == [HOLD_LIT] and m.repeats() == [(3, 1)],
          f'on DOOM OS\'s page a held roll\'s pad does not blink; HOLD is lit again ({[x.hex() for x in lit]})')
    m.uc.mem_write(PAGE_ID, struct.pack('<H', 1))
    m.uart = []
    m.run(2)
    check([x for x in m.lights() if x[1] == 6] == blink(3), 'back on TOP the held roll\'s pad blinks again')
    # stock's HOLD itself: the same per-pad states as on the parent through a held roll
    states = []
    for image in (parent, img):
        m = Machine(image, man['entries'] if image is img else None, tempo=12000)
        m.set(P_ROLL, 4, 3)
        m.tap(KEY_ROLL)
        m.pad(3)
        m.pad(7)
        m.tap(KEY_HOLD)
        s1 = (m.hold_state(3), m.hold_state(7))
        m.pad_up(3)
        m.pad_up(7)
        m.run(300)
        s2 = (m.hold_state(3), m.hold_state(7))
        m.tap(KEY_HOLD)
        m.run(5)
        states.append((s1, s2, (m.hold_state(3), m.hold_state(7))))
    check(states[0] == states[1] and states[0][0] == (2, 2) and states[0][2] == (0, 0),
          f'stock\'s HOLD keeps its own meaning alongside: pads down held, let go still held, HOLD again lets them '
          f'go, as on the parent ({states})')


def gate_checks(img, parent, man):
    """The key-held query from the note-on's three roll starts, and from elsewhere."""
    out = {}
    for label, image, dj in (('parent', parent, None), ('image', img, None), ('image, DJ mode', img, 1)):
        m = Machine(image, man['entries'] if image is img else None)
        m.dj = dj
        m.press(KEY_ROLL)                               # ROLL held; the dispatcher also gets the module going
        res = {}
        for lr in list(CALLERS)[:3] + [0x8001E561, 0x800CA15B, 0x8003C601]:
            res[hex(lr)] = s32(m.call(KEY_QUERY, 0x21, until=lr & ~1, lr=lr))
        res['shift 0x2a'] = s32(m.call(KEY_QUERY, 0x2A, until=0x800AEE22, lr=0x800AEE23))
        m.let_go(KEY_ROLL)
        res['let go'] = s32(m.call(KEY_QUERY, 0x21, until=0x800AEE22, lr=0x800AEE23))
        out[label] = res
    p, i, d = out['parent'], out['image'], out['image, DJ mode']
    roll_sites = [hex(x) for x in list(CALLERS)[:3]]
    check(all(p[s] == 1 for s in roll_sites) and all(i[s] == 0 for s in roll_sites) and d == p,
          f'ROLL held: the note-on\'s three roll starts hear "held" on the parent, "not held" here, "held" here in DJ '
          f'mode ({p}, {i}, {d})')
    others = [k for k in p if k not in roll_sites]
    check(all(i[k] == p[k] for k in others) and p['0x8001e561'] == 1 and p['let go'] == 0,
          f'every other query (note-off, VALUE, a non-ROLL key, ROLL let go) answers as on the parent: the kits\' gate '
          f'({ {k: i[k] for k in others} })')


def release_checks(img, parent, man):
    """ROLL let go through the generic key handler: stock's release body runs on the parent and in DJ mode only."""
    res = []
    for image, dj in ((parent, None), (img, None), (img, 1)):
        m = Machine(image, man['entries'] if image is img else None)
        m.dj = dj
        m.tap(KEY_ROLL)
        res.append(len([s for s in m.seen if s[1] == 'release body']))
    check(res == [1, 0, 1], f'ROLL tapped: stock\'s release handling runs on the parent and in DJ mode, not here '
                            f'({res})')


def dj_checks(img, parent, man):
    """DJ Mixer Mode on: ROLL, VALUE and pads as on the parent."""
    script = [('k', KEY_ROLL), ('p', 3), ('r', 300), ('t', 1), ('t', -2), ('k', KEY_HOLD), ('K', KEY_HOLD),
              ('u', 3), ('K', KEY_ROLL), ('r', 300), ('k', KEY_ROLL), ('K', KEY_ROLL), ('p', 3), ('r', 500), ('u', 3),
              ('k', KEY_HOLD), ('K', KEY_HOLD), ('k', KEY_ROLL), ('k', KEY_VALUE), ('K', KEY_VALUE), ('K', KEY_ROLL)]
    out = []
    for image in (parent, img):
        m = Machine(image, man['entries'] if image is img else None, tempo=12000)
        m.dj = 1
        m.set(P_ROLL, 4, 3)
        run_steps(m, script)
        out.append(trace(m))
    events = len([s for s in script if s[0] != 'r'])
    keys = len([s for s in script if s[0] in 'kKt'])
    check(out[0] == out[1] and len(out[0]['doom']) == events and len(out[0]['seen']) == keys,
          f'DJ Mixer Mode: ROLL + pad, VALUE, HOLD, a ROLL tap, ROLL + VALUE press, exactly as on the parent (every '
          f'event to DOOM OS\'s filter, the keys and turns on to the generic key handler; the pads go to the DJ '
          f'handler, not to SMPL TASK)')


def run_steps(m, script):
    for op, *a in script:
        if op == 'k':
            m.press(a[0])
        elif op == 'K':
            m.let_go(a[0])
        elif op == 'p':
            m.pad(a[0], a[1] if len(a) > 1 else 100)
        elif op == 'u':
            m.pad_up(a[0])
        elif op == 't':
            m.turn(a[0])
        elif op == 'n':
            m.dispatch(EV_KNOB, a[0], a[1])
        elif op == 'r':
            m.run(a[0])


def trace(m):
    return dict(events=[e[:4] for e in m.events], popups=m.popups, uart=bytes(v for p, v in m.uart), doom=m.doom,
                rolls=m.rolls, posts=m.posts, keys=bytes(m.uc.mem_read(KEYS, 16)), page=m.r16(PAGE_ID),
                seen=[s for s in m.seen if s[1] != 'release body'], roll3=m.roll(3))


def recorder_checks(img, man):
    """The pad events of a tap and of repeats through the stock consumer, the sequencer recording: the pattern
    recorder (0x80030700) gets a note-off and a note-on of the pad for each repeat, as for the tap."""
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 3)
    m.pad(3, 77)
    m.run(50)
    m.pad_up(3)
    tap = list(m.events)
    m.press(KEY_ROLL)
    m.pad(3, 77)
    m.run(260)
    m.let_go(KEY_ROLL)
    m.pad_up(3)
    rolled = [e for e in m.events if e not in tap]
    recorded = []

    def record(uc, a, size, _):
        recorded.append(bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R0), 8)))
        m._ret(0)

    for a in (0x800AEC48, 0x800C0A80, 0x8004B438, 0x80047150):   # note-on / note-off / per-pad side work: not here
        m.uc.hook_add(UC_HOOK_CODE, m._value, 0, begin=a, end=a)
    m.uc.hook_add(UC_HOOK_CODE, record, None, begin=RECORD, end=RECORD)
    m.w32(SEQ_STATE, 1)                                 # the sequencer records

    def feed(events):
        recorded.clear()
        for _, _, _, _, ev in events:
            m.uc.mem_write(SCRATCH, ev)
            m.call(CONSUMER, SCRATCH, count=5_000_000)
        return list(recorded)

    tap_rec = feed(tap)
    roll_rec = feed(rolled)
    on, off = tap_rec[0], tap_rec[1]
    check(len(tap_rec) == 2 and len(rolled) == 1 + 2 * 2 + 1 and
          roll_rec == [on] + [off, on] * 2 + [off],
          f'the pattern recorder takes the tap as note-on {on.hex()} and note-off {off.hex()}, and the roll as the '
          f'pad\'s hit, two repeats (each a note-off and a note-on, the same bytes) and the closing note-off '
          f'({[r.hex() for r in roll_rec]})')


# ---- everything else as on the parent ----
SCRIPTS = (
    ('pads', [('p', 0, 127), ('u', 0), ('p', 15, 60), ('u', 15), ('p', 3), ('r', 300), ('u', 3)]),
    ('SUB PAD', [('p', 3), ('u', 3), ('p', 0x13, 80), ('r', 100), ('u', 0x13)]),
    ('VALUE turned', [('t', 1), ('t', -3), ('r', 10)]),
    ('VALUE pressed', [('k', KEY_VALUE), ('K', KEY_VALUE), ('r', 10)]),
    ('SHIFT + ROLL', [('k', KEY_SHIFT), ('k', KEY_ROLL), ('K', KEY_ROLL), ('k', KEY_ROLL), ('K', KEY_ROLL),
                      ('K', KEY_SHIFT), ('r', 10)]),
    ('SHIFT + ROLL, SHIFT let go first', [('k', KEY_SHIFT), ('k', KEY_ROLL), ('K', KEY_SHIFT), ('r', 5)]),
    ('EXIT + ROLL', [('k', KEY_EXIT), ('k', KEY_ROLL), ('K', KEY_ROLL), ('K', KEY_EXIT), ('r', 10)]),
    ('SHIFT + VALUE', [('k', KEY_SHIFT), ('t', 2), ('k', KEY_VALUE), ('K', KEY_VALUE), ('K', KEY_SHIFT)]),
    ('EXIT + VALUE', [('k', KEY_EXIT), ('k', KEY_VALUE), ('K', KEY_VALUE), ('K', KEY_EXIT), ('t', 1)]),
    ('HOLD + pads', [('k', KEY_HOLD), ('p', 3), ('u', 3), ('K', KEY_HOLD), ('k', KEY_HOLD), ('K', KEY_HOLD)]),
    ('a pad held by HOLD, let go by HOLD and by its pad', [('p', 3), ('p', 6), ('k', KEY_HOLD), ('K', KEY_HOLD),
                                                           ('u', 3), ('u', 6), ('r', 100), ('p', 6), ('u', 6),
                                                           ('k', KEY_HOLD), ('K', KEY_HOLD), ('r', 10)]),
    ('SHIFT + HOLD', [('k', KEY_SHIFT), ('k', KEY_HOLD), ('K', KEY_HOLD), ('K', KEY_SHIFT), ('r', 10)]),
    ('knobs', [('n', 1, 40), ('n', 2, 90), ('n', 3, 127)]),
    ('ROLL + pad, the stock hit', [('k', KEY_ROLL), ('p', 3, 90)]),
)
KEYS_ALONE = [k for k in range(0x10, 0x32) if k not in (KEY_ROLL, 0x13)]


def passthrough_checks(img, parent, man):
    for label, script in SCRIPTS:
        out = []
        for image in (parent, img):
            m = Machine(image, man['entries'] if image is img else None, tempo=12000)
            m.set(P_ROLL, 4, 3)
            run_steps(m, script)
            out.append(trace(m))
        diff = [k for k in out[0] if out[0][k] != out[1][k]]
        check(not diff, f'{label}: as on the parent (pad events, popups, chip bytes, DOOM OS, stock rolls, posts, '
                        f'held keys, page) {diff} {[(out[0][k], out[1][k]) for k in diff][:1]}')
    bad = []
    for k in KEYS_ALONE:
        for extra in ((), (KEY_SHIFT,), (KEY_EXIT,)):
            script = [('k', x) for x in extra] + [('k', k), ('K', k)] + [('K', x) for x in extra] + [('r', 3)]
            a, b = Machine(parent), Machine(img, man['entries'])
            run_steps(a, script)
            run_steps(b, script)
            if trace(a) != trace(b):
                bad.append((hex(k), extra))
    check(not bad, f'each of {len(KEYS_ALONE)} keys alone, with SHIFT and with EXIT: as on the parent ({bad[:4]})')
    bad = []
    for k in KEYS_ALONE + [0x13]:
        if k == KEY_VALUE:
            continue
        script = [('k', KEY_ROLL), ('k', k), ('K', k), ('K', KEY_ROLL), ('r', 3)]
        a, b = Machine(parent), Machine(img, man['entries'])
        run_steps(a, script)
        run_steps(b, script)
        if trace(a) != trace(b) or b.state()['latched']:
            bad.append(hex(k))
    check(not bad, f'each other key pressed and let go while ROLL is held: as on the parent, and no latch ({bad[:4]})')


def subpad_checks(img, man):
    m = Machine(img, man['entries'], tempo=12000)
    m.set(P_ROLL, 4, 5)
    m.pad(5)
    m.pad_up(5)                                         # A-06 the last pad
    m.run(10)
    m.tap(KEY_ROLL)
    t0 = m.ms
    m.pad(0x13, 70)                                     # SUB PAD plays it
    m.run(300)
    m.pad_up(0x13)
    m.run(300)
    got = [(t - t0, v) for t, _, v in m.ons(5, since=t0)]
    check(got == [(0, 70), (125, 70), (250, 70)] and m.state()['active'] == 0,
          f'latched: SUB PAD held repeats the last pad at SUB PAD\'s velocity, and stops when let go ({got})')


class ChromaMachine(Machine):
    """Chromatic mode on its page: the pads play A-04's sample (project 0xC1 = 3), whose pad follows 90 BPM; every
    other pad's tempo is 120 BPM."""
    SOURCE, SOURCE_TEMPO = 3, 9000

    def __init__(self, img, sym):
        super().__init__(img, sym, tempo=12000)
        self.uc.mem_write(EVENT, struct.pack('<6h', 1, 0, 0, 0, 0, 0))
        self.call(CHROMA_REGISTRY, EVENT, count=20_000_000)
        self.uc.mem_write(PAGE_ID, struct.pack('<H', CHROMA_PAGE))
        self.uc.mem_write(PAGE_LIVE, struct.pack('<H', CHROMA_PAGE))
        for param, value in ((P_CHROMATIC, 1), (P_SOURCE, self.SOURCE)):
            self.call(PROJECT_SET, PROJECT, param, value, 0xFFFFFFFF, count=20_000_000)
        self.clear()

    def _tempo(self, uc, a, size, _):
        self._ret(self.SOURCE_TEMPO if uc.reg_read(ar.UC_ARM_REG_R0) == self.SOURCE else self.tempo)

    def chroma_ons(self, pad, since):
        """The millisecond of each note-on of a chromatic pad (pad events of type 0xC)."""
        return [t for t, p, k, v, _ in self.events if k == 0xC and p == pad and v and t >= since]

    def chroma_div(self):
        return self.r8(self.sym['nr'] + 31)

    def roll_popups(self):
        return [t for _, t in self.popups if t in ['Roll ' + n for n in ALL_NAMES]]


def chroma_checks(img, man):
    def roll(m, pads, ms):
        m.press(KEY_ROLL)
        m.run(2)
        t0 = m.ms
        for i in pads:
            m.pad(i, 80)
        m.run(ms)
        for i in pads:
            m.pad_up(i)
        m.let_go(KEY_ROLL)
        m.run(5)
        return t0

    m = ChromaMachine(img, man['entries'])
    bad = []
    for i in range(16):
        t0 = roll(m, [i], 700)
        got = m.chroma_ons(i, t0 + 1)
        if got != expected_ticks(4, ChromaMachine.SOURCE_TEMPO, 4, t0) or m.kept(i) != (0, 0, 0):
            bad.append((i, [t - t0 for t in got], m.kept(i)))
    check(not bad and not m.rolls and m.chroma_div() == 0,
          f'chromatic mode: every pad, ROLL + pad repeats at 1/16 of the sample\'s pad\'s tempo (90 BPM: 167, 334, '
          f'500, 667 ms) from power-on; the pad\'s own Roll (Off) and byte 0x70 stay as they were ({bad[:2]})')
    m = ChromaMachine(img, man['entries'])
    m.set(P_ROLL, 6, 9)                                 # first: the setter keeps a LOOP pad's Roll
    m.set(P_LOOP, 1, 9)
    m.set(P_GATE, 0, 9)
    m.uc.mem_write(EXT + 9 * 0x80 + FOLLOW_BYTE, b'\x01')
    t0 = roll(m, [9], 700)
    got = m.chroma_ons(9, t0 + 1)
    check(got == expected_ticks(4, ChromaMachine.SOURCE_TEMPO, 4, t0) and not m.rolls and m.kept(9) == (6, 0, 1) and
          m.get(P_LOOP, 9) == 1,
          f'pad 10 holding a LOOP sample without GATE, set to ignore ROLL, its Roll at 1/64: in chromatic mode it '
          f'still rolls at 1/16, by re-hits, no stock roll asked for; its settings untouched ({[t - t0 for t in got]}, '
          f'{m.rolls}, {m.kept(9)})')
    # VALUE: one division for every chromatic pad, at once, kept for the next roll; the pads' Roll untouched
    m = ChromaMachine(img, man['entries'])
    m.press(KEY_ROLL)
    m.run(2)
    for i in (2, 9):
        m.pad(i, 80)
    m.run(200)
    m.turn(1)
    t1 = m.ms
    m.run(500)
    gaps = {i: [b - a for a, b in zip(m.chroma_ons(i, t1 + 1), m.chroma_ons(i, t1 + 1)[1:])] for i in (2, 9)}
    for i in (2, 9):
        m.pad_up(i)
    m.let_go(KEY_ROLL)
    m.run(5)
    p = frames_period(10, ChromaMachine.SOURCE_TEMPO) / 48       # 3/64 (3/16 beat) at 90 BPM: 125 ms
    steady = all(g and all(abs(x - p) <= 1 for x in g) for g in gaps.values())
    t0 = roll(m, [5], 700)
    later = m.chroma_ons(5, t0 + 1)
    check(steady and m.roll_popups() == ['Roll 3/64'] and m.chroma_div() == 10 and
          later == expected_ticks(10, ChromaMachine.SOURCE_TEMPO, 5, t0) and
          all(m.kept(i) == (0, 0, 0) for i in range(16)),
          f'VALUE while two chromatic pads roll: both go to the next division (3/64) at once, popup "Roll 3/64"; the '
          f'next roll starts there; no pad\'s Roll or byte 0x70 changes ({gaps}, {m.roll_popups()}, {later[:3]})')
    m.clear()
    m.press(KEY_ROLL)
    m.tap(KEY_VALUE)
    m.turn(-1)
    m.let_go(KEY_ROLL)
    check(m.roll_popups() == ['Roll 3/64', 'Roll 1/16'] and m.chroma_div() == 4 and
          all(m.kept(i) == (0, 0, 0) for i in range(160)) and not m.posts,
          f'ROLL + VALUE press shows the chromatic division and toggles no follow flag; with nothing repeating, ROLL + '
          f'VALUE steps it ({m.roll_popups()}, {m.posts})')
    m.clear()
    m.tap(KEY_ROLL)                                     # latch
    m.pad(4, 80)
    m.run(100)
    m.press(KEY_VALUE)
    m.turn(1)
    held = (m.chroma_div(), m.roll_popups())
    m.let_go(KEY_VALUE)
    m.turn(1)
    m.pad_up(4)
    m.tap(KEY_ROLL)                                     # unlatch
    m.run(5)
    check(held == (4, []) and m.chroma_div() == 10 and m.roll_popups()[-1] == 'Roll 3/64',
          f'latched with a chromatic pad repeating: a VALUE turn with VALUE held is not taken (the page\'s push-turn), '
          f'without it steps the division ({held}, {m.roll_popups()})')


def main():
    out = Path(sys.argv[1])
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    parent = Path(man['parent_app1']).read_bytes()
    only = sys.argv[2].split(',') if len(sys.argv) > 2 else None
    for name, fn, args in (('static', static_checks, (out, man, img, parent)), ('names', firmware_names_check, (parent,)),
                           ('timing', timing_checks, (img, man)), ('value', value_checks, (img, man)),
                           ('triplet', triplet_checks, (img, man)),
                           ('roll', roll_checks, (img, man)), ('ring', ring_checks, (img, man)),
                           ('subpad', subpad_checks, (img, man)), ('hold', hold_checks, (img, parent, man)),
                           ('gate', gate_checks, (img, parent, man)), ('release', release_checks, (img, parent, man)),
                           ('dj', dj_checks, (img, parent, man)), ('recorder', recorder_checks, (img, man)),
                           ('passthrough', passthrough_checks, (img, parent, man)),
                           ('chroma', chroma_checks, (img, man))):
        if only is None or name in only:
            fn(*args)
    print(json.dumps(dict(cases=cases[0])))
    print('ALL PASS' if not fails else f'{len(fails)} FAILED')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
