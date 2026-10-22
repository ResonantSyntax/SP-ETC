"""Checks for the pad envelopes, stage 1 (build_pad_env.py).

usage: python synth/test_pad_env.py OUT_DIR [N]          (unicorn, capstone on PYTHONPATH; N random cases, default 60)

Reads OUT_DIR/manifest.json for the parent APP1. Static checks first: only the header's scatter pointer, the five
code sites, the five ENVELOPE vtable words and the appended tail differ from the parent; the guards and the
displaced bytes hold on the parent and nothing reaches into those bytes; the module's copies of them are exact; the
slot overlaps no row and no other fork module; the tables are the documented formulas. Then the parent and the new
image are booted in Unicorn the way their scatter loader does it, with the boot's static constructors run (the RTOS
under them stubbed: its pool by a bump allocator, object creation by an id). Real stock code runs: the recompute
0x800a2d98 (through the new jump and the dispatcher), the applicators 0x16f50 / 0x17196 (through theirs), the
note-off 0x80023118, the pad parameter getter and setter, the fan-out, the UI dispatcher, the ENVELOPE page's
registry handler, DOOM OS ED5E's filter, the page's knob, key, tick, redraw, pad-change and destructor methods, and,
with boot's three 128 x 64 surfaces made (0x8006fcb8), every drawing call down to the pixels.

Checks:
- neutral pads (all zero, version byte 0 with anything else, version 1 with every setting at stock, an unknown
  version, a voice with no pad, a block that is not a voice's): the recompute (block and r0), the note-off (result
  and release counters) and both applicators (every frame, mono and stereo, slot state 7, before START, overlap,
  reverse) are bit-identical to the parent;
- shaped pads (FINE times, curves, decay and sustain, attack/decay/release overlap, REV-TIME, LOOP-ONCE with wraps,
  turns and an Init reset): the published shape and every frame of both applicators match a Python model;
- the note-off sizes a FINE release from the fine time (every index, short and long releases);
- the re-hit: the stop 0x80094168, called as each of its callers calls it, on every kind of pad and voice: a FADE
  pad's sounding voice, stopped for a new hit with free slots, gets the key-up release over the fade, a releasing
  one goes on; everything else is the parent's, byte for byte. Through the voice manager 0x800d63c8 (on Unicorn's
  ARM_MAX CPU, the voice start only noted): chromatic mono, poly, a panel pad hit again and every slot busy;
  the old voice keeps its slot and the new one takes a free slot;
- the dispatcher: the stock body first, then every env_stages entry with the call (voice, pad, return address) from
  each of the five recompute callers;
- the ENVELOPE page: tapping SHIFT steps the pages (not while held at entry, nor with a key pressed or let go, a
  knob or a pad change in between, nor held over a second; a key held throughout or a stuck key bit doesn't
  matter); page 1 is stock (the parent's setter calls) until FINE, then a knob writes the fine index and the
  nearest stock value and calls the fan-out; pages 2-4 write their bytes; COPY / REMAIN reach the mute group / bank
  as stock's apply does (protected banks skipped); the knobs driving the effect go to stock; the save goes out
  once, 1 s after the last change or when the page closes; a later stage's page in env_more_pages comes after MODE;
- the screen, byte for byte, and the static layer: page 1 with stock settings is the parent's; every page for every
  kind of settings, after every turn and a pad change, is the reference drawn on the parent with stock's own calls
  from the settings alone (the labels, the values, the pad's real envelope from a Python model of the graph,
  "A-6 SHAPE 2/4"); the module shows no popups.
"""
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_HOOK_CODE
from unicorn import arm_const as ar

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pad_env import (GUARDS, SITES, CALL_SITES, STOCK_COPIES, VTABLE, VTABLE_SLOTS, VTABLE_KEEP,  # noqa: E402
                           KNOWN_SLOTS, SLOT, Runtime, scatter, decompress, branches_into, movw_movt_bx,
                           fine_frames, curve_tables, stock_frames, sha)
from build_pad_env import call as call_code  # noqa: E402
from build_start_fix import refs_into  # noqa: E402

FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
HEAP = 0x32000000
KERNEL = {0x310C: 1, 0x22A4: 1, 0x32B8: 0}                 # RTOS object creation in the constructors: an id
SCREEN = (0x8006C088, 0x8006BD48, 0x8015F3A8, 0x800D8020, 0x800C1CC0,   # drawing: no display here
          0x800C1C78, 0x80195760)                        # (the tick's child-widget update draws)
SCREEN_ON = (0x8006C088, 0x8006BD48, 0x8015F3A8)         # with the surfaces: only the popup window's own draws
SURFACES = 0x8006FCB8                                    # boot: [0x80591b40] the screen, [0x80591b44] the layer
SCREEN_PIX = 0x82E0371C                                  # 128 x 64, a byte per pixel (0 or 255)
COLOR, FILL_FG, FONT, TEXT, LINE = 0x800D8018, 0x800CE510, 0x800D80D8, 0x800D4FA0, 0x800C0660
CTX_INIT, CTX_FREE, STOCK_DRAW, STOCK_PAD = 0x800D88E0, 0x800D8920, 0x800F5F00, 0x800F5A60
WHITE, FONT_ID = 0xFFFFFF, 0x1D
SAMPLE_GET = 0x800DDA38                                  # (0x82e009d0, 0x67 START / 0x68 END, pad): the page reads these
COLUMNS, LABEL_Y, VALUE_Y, NAME_Y = (22, 63, 105), 2, 10, 53
GRAPH_TOP, GRAPH_ZERO = 17, 32
NOPS = (0xE668, 0x800D30A4)                              # debug prints
FILE_OPEN = 0x800DEC60
CTORS, NCTORS = 0x8383A30C, 70
STACK, RET, EVENT, SCRATCH = 0x30010000, 0x3001F000, 0x30095000, 0x30060000
UI_DISPATCH, PAGE_ID, PAGE_LIVE, PREFILTER, KEY_PAIRS = 0x8003B530, 0x80245880, 0x8024587A, 0x82DFD318, 0x80B119DC
POPUP, POST, FANOUT, SETTER, GETTER = 0x800D3FF0, 0x800E25C0, 0x800D7A80, 0x800DA720, 0x800DC6B8
APPLY_SET = 0x800DED18                                   # stock's apply writes a pad's param through this (queued)
KEYS = 0x80592448                                        # held keys, one bit each
PAGE_TIMER = 0x80592438 + 0xA                            # the periodic page event: countdown, reload (UI ticks)
REGISTRY, PAGE_PTR, APPLY_MODE, FX_KNOBS, STOCK_KNOB = 0x800608D0, 0x80591B58, 0x80591B54, 0x800CE420, 0x800F5D10
FX_KNOB_PATH = 0x800CC030                                 # the knobs on the effect (stubbed: no effects chip here)
CSMPLPRM, EXT, LOADED, PROJECT = 0x82E2CD08, 0x82E2CD08 + 0xF800, 0x82E495E4, 0x82E009D0
RECOMPUTE, NOTE_OFF, FWD, REV, FWD_WRAP, REV_WRAP = 0x800A2D98, 0x80023118, 0x16F50, 0x17196, 0x1717A, 0x17386
VOICES, VOICE_SIZE = 0x805F8834, 0x28820
CALLERS = {0x80023B05: 'Init', 0x8001FF39: 'A/H/R edit', 0x80022DAF: 'START edit', 0x80024A8F: 'END edit',
           0x8002310F: 'loop-point edit'}
INIT_RET = 0x80023B05
EV_KEY, EV_KEY_UP, EV_TICK, EV_KNOB = 5, 6, 8, 9
KEY_SHIFT, KEY_COPY = 42, 0x23                           # the ENVELOPE page: COPY 0x23 (REMAIN 0x24)
KEY_DEL, KEY_EXIT, KEY_VALUE = 0x1A, 0x22, 0x31           # DOOM OS's button table 0x60331134 agrees (DEL 0x1a)
PAGE_REQUEST = 0x8024587C                                # 0x800da598(n), EXIT's page change, stores n here
INIT_PARAM, INIT_PARAM_OK, CMD_DISPATCH = 0x8018C220, 0x80051DB8, 0x8004D8B8
ONE, M32 = 32768, 0xFFFFFFFF
FALL = [0, 2, 1, 3]
fails = []
cases = [0]


def check(cond, what):
    cases[0] += 1
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        fails.append(what)
    return cond


def s32(v):
    return struct.unpack('<i', struct.pack('<I', v & M32))[0]


class Machine:
    def __init__(self, img, symbols=None, screen=False, arm_max=False):
        """screen: boot's three 128 x 64 surfaces made (0x8006fcb8) and the drawing code run for real;
        arm_max: Unicorn's ARM_MAX CPU (the voice code after a voice start uses VFP instructions the default lacks)"""
        self.sym = symbols or {}
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        if arm_max:
            uc.ctl_set_cpu_model(ar.UC_CPU_ARM_MAX)
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
        self.popups, self.posts, self.fanouts, self.setters, self.stock_knobs, self.stage_calls = [], [], [], [], [], []
        self.applied, self.texts, self.popup_log = [], [], []
        self.protected, self.fx_knobs = set(), 0
        uc.hook_add(UC_HOOK_CODE, self._malloc, None, begin=0x800E2C68, end=0x800E2C68)
        uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=0x800E2CA8, end=0x800E2CA8)
        for a, v in KERNEL.items():
            uc.hook_add(UC_HOOK_CODE, self._value, v, begin=a, end=a)
        for a in (SCREEN_ON if screen else SCREEN) + NOPS:
            uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=a, end=a)
        uc.hook_add(UC_HOOK_CODE, self._text, None, begin=TEXT, end=TEXT)
        self.samples = {}                                # pad -> (START, END): no samples here
        uc.hook_add(UC_HOOK_CODE, self._sample, None, begin=SAMPLE_GET, end=SAMPLE_GET)
        uc.hook_add(UC_HOOK_CODE, self._value, -1, begin=FILE_OPEN, end=FILE_OPEN)
        uc.hook_add(UC_HOOK_CODE, self._popup, None, begin=POPUP, end=POPUP)
        uc.hook_add(UC_HOOK_CODE, self._log, self.posts, begin=POST, end=POST)
        uc.hook_add(UC_HOOK_CODE, self._log, self.fanouts, begin=FANOUT, end=FANOUT)
        uc.hook_add(UC_HOOK_CODE, self._log, self.setters, begin=SETTER, end=SETTER)
        uc.hook_add(UC_HOOK_CODE, self._log, self.stock_knobs, begin=STOCK_KNOB, end=STOCK_KNOB)
        uc.hook_add(UC_HOOK_CODE, self._log, self.applied, begin=APPLY_SET, end=APPLY_SET)
        uc.hook_add(UC_HOOK_CODE, self._fx_knobs, None, begin=FX_KNOBS, end=FX_KNOBS)
        uc.hook_add(UC_HOOK_CODE, self._fx_knobs, None, begin=FX_KNOB_PATH, end=FX_KNOB_PATH)
        for fn in struct.unpack(f'<{NCTORS}I', bytes(uc.mem_read(CTORS, 4 * NCTORS))):
            self.call(fn & ~1 | 1, count=50_000_000)
        self.w32(PREFILTER, 0xFFFFFFFF)                 # no mode holds the keys
        uc.mem_write(KEY_PAIRS, b'\xff' * 0x80)         # no key pairs (memset -1 at boot)
        project_get = self.r32(self.r32(PROJECT) + 8) & ~1
        uc.hook_add(UC_HOOK_CODE, self._project, None, begin=project_get, end=project_get)
        # a stand-in voice class: slot 0 turns bytes into frames (stereo: >> 2), as the voice classes' slot 0 does
        uc.mem_write(SCRATCH, bytes.fromhex('8808') + bytes.fromhex('7047'))      # lsrs r0, r1, #2; bx lr
        self.w32(SCRATCH + 0x10, SCRATCH | 1)
        uc.mem_write(SCRATCH + 0x20, bytes.fromhex('7047'))                        # a stage: bx lr
        uc.hook_add(UC_HOOK_CODE, self._stage, None, begin=SCRATCH + 0x20, end=SCRATCH + 0x20)
        if screen:
            self.call(SURFACES | 1, count=50_000_000)
        self.page = None

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
        self.uc.reg_write(ar.UC_ARM_REG_R0, value & M32)
        self.uc.reg_write(ar.UC_ARM_REG_PC, self.uc.reg_read(ar.UC_ARM_REG_LR))

    def _malloc(self, uc, a, size, _):
        n = (uc.reg_read(ar.UC_ARM_REG_R0) + 15) & ~7
        at = self.heap
        self.heap += n + 8
        uc.mem_write(at, bytes(n + 8))
        self._ret(at + 8)

    def _value(self, uc, a, size, value):
        self._ret(value)

    def regs(self, n=4):
        return tuple(self.uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}')) for k in range(n))

    def _log(self, uc, a, size, log):
        log.append(self.regs())

    def _popup(self, uc, a, size, _):
        text = bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R0), 64)).split(b'\0')[0].decode('latin-1')
        self.popups.append((text, s32(uc.reg_read(ar.UC_ARM_REG_R1))))
        self.popup_log.append((text, uc.reg_read(ar.UC_ARM_REG_LR)))

    def _sample(self, uc, a, size, _):
        param, pad = uc.reg_read(ar.UC_ARM_REG_R1), s32(uc.reg_read(ar.UC_ARM_REG_R2))
        if param in (0x67, 0x68) and pad in self.samples:
            self._ret(self.samples[pad][param - 0x67])

    def _text(self, uc, a, size, _):
        s = bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R3), 40)).split(b'\0')[0].decode('latin-1')
        self.texts.append((s32(uc.reg_read(ar.UC_ARM_REG_R1)), s32(uc.reg_read(ar.UC_ARM_REG_R2)), s))

    def _fx_knobs(self, uc, a, size, _):
        if self.fx_knobs:
            self._ret(1)

    def _project(self, uc, a, size, _):
        r1 = uc.reg_read(ar.UC_ARM_REG_R1)
        if 0x17 <= r1 < 0x17 + 10 and r1 - 0x17 in self.protected:
            self._ret(1)

    def _stage(self, uc, a, size, _):
        c = struct.unpack('<10I', bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_R0), 40)))
        self.stage_calls.append(dict(env=c[0], start=c[1], length=c[2], a=s32(c[3]), h=s32(c[4]), r=s32(c[5]),
                                     ch=s32(c[6]), lr=c[7], voice=s32(c[8]), pad=s32(c[9])))

    def clear(self):
        for log in (self.popups, self.posts, self.fanouts, self.setters, self.stock_knobs, self.stage_calls,
                    self.applied, self.texts):
            log.clear()

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack('<I', v & M32))

    def r32(self, a):
        return struct.unpack('<I', self.uc.mem_read(a, 4))[0]

    def r16(self, a):
        return struct.unpack('<H', self.uc.mem_read(a, 2))[0]

    def call(self, fn, *args, lr=RET, until=RET, count=5_000_000, stack=()):
        uc = self.uc
        for k, v in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), v & M32)
        sp = STACK - 0x200
        uc.mem_write(sp, b''.join(struct.pack('<I', v & M32) for v in stack) + bytes(16))
        uc.reg_write(ar.UC_ARM_REG_LR, lr | 1)
        uc.reg_write(ar.UC_ARM_REG_SP, sp)
        uc.emu_start(fn | 1, until, count=count)
        if uc.reg_read(ar.UC_ARM_REG_PC) != until:
            raise RuntimeError(f'{fn:#x} did not return (pc {uc.reg_read(ar.UC_ARM_REG_PC):#x})')
        if uc.reg_read(ar.UC_ARM_REG_SP) != sp:
            raise RuntimeError(f'{fn:#x} returned with sp {uc.reg_read(ar.UC_ARM_REG_SP):#x}, not {sp:#x}')
        return uc.reg_read(ar.UC_ARM_REG_R0)

    # ---- pads and voices
    def ext(self, pad):
        return bytes(self.uc.mem_read(EXT + pad * 0x80 + 0x64, 12))

    def set_ext(self, pad, b):
        self.uc.mem_write(EXT + pad * 0x80 + 0x64, bytes(b))

    def load_pad(self, pad):
        """the pad holds a sample: its record's status word (the getter answers 0 without one) and a length
        the setter takes Attack/Hold/Release for (0x800d9e30)"""
        e = LOADED + pad * 36
        self.w32(e + 8, 2)
        self.w32(e + 0x18, 0)
        self.w32(e + 0x1C, 0x100000)
        self.w32(CSMPLPRM + 0xD0 + pad * 0xAC, 1)

    def unload_pad(self, pad):
        self.w32(LOADED + pad * 36 + 0x1C, 0)
        self.w32(CSMPLPRM + 0xD0 + pad * 0xAC, 0)

    def get(self, param, pad):
        return s32(self.call(GETTER | 1, CSMPLPRM, param, pad))

    def set(self, param, value, pad):
        self.call(SETTER | 1, CSMPLPRM, param, value, pad)

    def voice(self, i, pad, loop=0):
        v = VOICES + i * VOICE_SIZE
        self.w32(v + 0x14274, pad)
        self.w32(v + 0x24, loop)
        return v

    def recompute(self, env, start, length, a, h, r, ch, lr=RET):
        return self.call(RECOMPUTE | 1, env, start, length, a, lr=lr, until=lr & ~1, stack=(h, r, ch))

    def block(self, env):
        return bytes(self.uc.mem_read(env, 0x44))

    def apply(self, fn, env, L, R, pos, n, state):
        uc = self.uc
        uc.mem_write(SCRATCH + 0x1000, struct.pack(f'<{len(L)}h', *L))
        uc.mem_write(SCRATCH + 0x5000, struct.pack(f'<{len(R)}h', *R))
        self.call(fn | 1, env, SCRATCH + 0x1000, SCRATCH + 0x5000, pos, stack=(n, 0, state), count=20_000_000)
        return (list(struct.unpack(f'<{len(L)}h', uc.mem_read(SCRATCH + 0x1000, 2 * len(L)))),
                list(struct.unpack(f'<{len(R)}h', uc.mem_read(SCRATCH + 0x5000, 2 * len(R)))))

    def note_off(self, voice, r, pos_bytes, end_bytes, played, counter=0):
        """0x80023118 on a prepared voice: Release r, the position (pos_bytes - 0x200) / 4 frames, END at end_bytes
        / 4, played frames already counted. Returns (result, +0x143ac, +0x143b0)."""
        info = SCRATCH + 0x100
        self.w32(voice, SCRATCH + 0x10)                  # vtable: slot 0 = bytes -> frames
        self.w32(voice + 0x100, r)
        self.w32(voice + 0x143AC, counter)
        self.w32(voice + 0x143B0, counter)
        r5 = voice + 0x14264
        self.w32(r5, info)
        self.w32(r5 + 4, 0)
        self.w32(r5 + 0x154, played)
        self.w32(info + 8, pos_bytes)
        self.w32(info + 0x18, end_bytes)
        self.w32(info + 0x54, 0)
        res = self.call(NOTE_OFF | 1, voice)
        return res, self.r32(voice + 0x143AC), self.r32(voice + 0x143B0)

    # ---- the ENVELOPE page
    def open_page(self, tick=True):
        """the ENVELOPE page made as on entry and (unless tick is False) its first 50 ms tick (the page's child
        copies the static layer over the screen) and a refresh (event 4: the layer again, then the redraw)"""
        self.uc.mem_write(EVENT, struct.pack('<6h', 1, 0, 0, 0, 0, 0))
        self.call(REGISTRY | 1, EVENT, count=20_000_000)
        self.page = self.r32(PAGE_PTR)
        self.uc.mem_write(PAGE_ID, struct.pack('<H', 0x10))
        self.uc.mem_write(PAGE_LIVE, struct.pack('<H', 0x10))
        if tick:
            self.tick()
            self.refresh()
        return self.page

    def refresh(self):
        """event 4 to the page (base +0x58): the static layer copied over the screen, then the redraw (+0xCC)"""
        self.uc.mem_write(EVENT, struct.pack('<6h', 4, 0, 0, 0, 0, 0))
        self.call(REGISTRY | 1, EVENT, count=50_000_000)

    def leave(self):
        self.uc.mem_write(EVENT, struct.pack('<6h', 2, 0, 0, 0, 0, 0))
        self.call(REGISTRY | 1, EVENT, count=20_000_000)
        self.page = None

    def tick(self, n=1):
        """the page's periodic event (type 8): base method +0x5c -> vtable +0xD0 (page, 50)"""
        for _ in range(n):
            self.uc.mem_write(EVENT, struct.pack('<6h', EV_TICK, 0, 0, 0, 0, 0))
            self.call(REGISTRY | 1, EVENT, count=20_000_000)

    def dispatch(self, kind, a1=0, a2=0):
        self.uc.mem_write(EVENT, struct.pack('<6h', kind, a1, a2, 0, 0, 0))
        return s32(self.call(UI_DISPATCH | 1, EVENT, count=20_000_000))

    def knob(self, ctrl, raw):
        return self.dispatch(EV_KNOB, ctrl, raw)

    def tap(self, key=KEY_SHIFT, ticks_down=1):
        self.dispatch(EV_KEY, key)
        self.tick(ticks_down)
        self.dispatch(EV_KEY_UP, key)
        self.tick()

    def ui(self):
        b = bytes(self.uc.mem_read(self.sym['env_ui'], 41))
        return dict(page=b[0], shift=b[1], used=b[2], dirty=b[3], saves=struct.unpack_from('<I', b, 16)[0],
                    labels=b[31], bottom=b[32], draws=struct.unpack_from('<I', b, 36)[0], asking=b[40])

    def screen(self):
        """(the screen, the page's static layer): 8192 bytes each"""
        layer = self.r32(self.r32(self.page + 0xC00) + 4)
        return bytes(self.uc.mem_read(SCREEN_PIX, 8192)), bytes(self.uc.mem_read(layer, 8192))

    def span(self, start, end):
        """the page's START/END as it read them (no sample in this machine)"""
        self.w32(self.page + 0x1A70, start)
        self.w32(self.page + 0x1A74, end)

    def draw(self):
        """the page's redraw, through its vtable (+0xCC)"""
        self.call(self.r32(self.r32(self.page) + 0xCC), self.page, count=50_000_000)

    def current_pad(self, pad):
        self.set(0, pad >> 4, 0)
        self.set(1, pad & 15, 0)


# ---------------------------------------------------------------- the model
class Model:
    """What pad_env.c computes, written out per frame (no incremental phases)."""

    def __init__(self, curves, frames):
        self.T, self.F = curves, frames

    def curve(self, t, ph):
        c = self.T[t]
        i, f = ph >> 24, (ph >> 8) & 0xFFFF
        return c[i] + (((c[i + 1] - c[i]) * f) >> 16)

    @staticmethod
    def frac(a, b):
        return (a << 32) // b

    def shape(self, b, pad, blk):
        """b: bytes 0x64-0x6F; blk: the stock block's (s, length, ae, he, rl) low words. None: stock."""
        if not 0 <= pad < 160 or b[9] != 1:
            return None
        flags, curves, sus = b[0], b[3], min(b[5], 100)
        ca, cd, cr = curves & 3, curves >> 2 & 3, curves >> 4 & 3
        fine, once, rev = flags & 1, flags & 4, flags & 8
        adsr = bool(flags & 2 and b[4] & 127 and sus < 100)
        if not (fine or adsr or once or rev or ca or cr):
            return None
        s, length, ae0, he, rl = blk
        atk = self.F[b[1] & 127] if fine else (ae0 - s) & M32
        rel = self.F[b[2] & 127] if fine else rl
        dec = self.F[b[4] & 127] if adsr else 0
        span = (he - s) & M32
        sh = dict(on=1, fine=int(bool(fine)), once=int(bool(once)), rev=int(bool(rev)), adsr=int(adsr), ta=ca,
                  td=FALL[cd], tr=FALL[cr], sus=(sus * ONE + 50) // 100 if adsr else ONE, s=s,
                  e=(s + length) & M32, he=he, atk=atk, dec=dec, rel=rel)
        if atk + rel > span:
            x = (span * self.frac(atk, atk + rel)) >> 32 if rel else span
            sh['ae'] = sh['de'] = sh['rs'] = (s + x) & M32
            sh['peak'] = self.curve(ca, self.frac(span, atk + rel))
            sh['rlen'] = (he - sh['rs']) & M32
        else:
            sh['ae'] = (s + atk) & M32
            sh['de'] = (sh['ae'] + dec) & M32
            sh['rs'] = (he - rel) & M32
            sh['rlen'] = rel
            sh['peak'] = ONE
            if adsr:
                sh['peak'] = sh['sus'] if sh['de'] <= sh['rs'] else \
                    ONE - (((ONE - sh['sus']) * self.curve(sh['td'], self.frac(sh['rs'] - sh['ae'], dec))) >> 15)
        return sh

    def ramp(self, t, base, scale, length, off):
        ph = self.frac(off, length) if length > 1 else 0
        return base + ((scale * self.curve(t, ph)) >> 15)

    def level(self, sh, mode, q):
        s, hold = sh['s'], sh['sus'] if sh['adsr'] else ONE
        if q < s:
            return 0
        if mode == 2:
            return hold
        if mode == 1:
            ae = s + sh['atk']
            if q < ae:
                return self.ramp(sh['ta'], 0, ONE, sh['atk'], q - s)
            if sh['adsr'] and q < ae + sh['dec']:
                return self.ramp(sh['td'], ONE, -(ONE - sh['sus']), sh['dec'], q - ae)
            return hold
        if q < sh['ae']:
            return self.ramp(sh['ta'], 0, ONE, sh['atk'], q - s)
        if q < sh['rs']:
            if sh['adsr'] and q < sh['de']:
                return self.ramp(sh['td'], ONE, -(ONE - sh['sus']), sh['dec'], q - sh['ae'])
            return hold
        if q < sh['he']:
            return self.ramp(sh['tr'], sh['peak'], -sh['peak'], sh['rlen'], q - sh['rs'])
        return 0

    @staticmethod
    def gain(x, lvl):
        v = x * lvl
        return (v + 0x7FFF if v < 0 else v) >> 15

    def apply(self, sh, mode, L, R, pos, n, state, stereo, reverse):
        L, R = list(L), list(R)
        for i in range(n):
            p = pos + n - i if reverse else pos + i
            if p < sh['s']:
                L[i] = R[i] = 0
                continue
            if state == 7:
                continue
            if reverse and sh['rev']:
                mirror = sh['s'] + sh['e']
                lvl = 0 if p > mirror else self.level(sh, mode, mirror - p)
            else:
                lvl = self.level(sh, mode, p)
            L[i] = self.gain(L[i], lvl)
            if stereo:
                R[i] = self.gain(R[i], lvl)
        return L, R


class LoopState:
    def __init__(self):
        self.passed, self.dir, self.last = 0, 0, 0

    def mode(self, sh, looping, pos, n, direction):
        if not sh['once'] or not looping:
            return 0
        if self.dir and (self.dir != direction or (pos < self.last if direction == 1 else pos > self.last)):
            self.passed = 1
        self.dir = direction
        self.last = (pos + n) & M32 if direction == 1 else pos
        return 2 if self.passed else 1


def published(m, i):
    """voice i's published shape, as the module holds it"""
    at = m.sym['env_voices'] + i * 112
    cur = m.uc.mem_read(at + 104, 1)[0]
    b = bytes(m.uc.mem_read(at + cur * 52, 52))
    keys = ('s', 'e', 'atk', 'ae', 'dec', 'de', 'rs', 'rlen', 'he', 'rel')
    sh = dict(on=b[0], fine=b[1], once=b[2], rev=b[3], ta=b[4], td=b[5], tr=b[6], adsr=b[7],
              sus=struct.unpack_from('<H', b, 8)[0], peak=struct.unpack_from('<H', b, 10)[0])
    sh.update(zip(keys, struct.unpack_from('<10I', b, 12)))
    return sh


def stock_block(m, env):
    b = m.block(env)
    return (struct.unpack_from('<I', b, 8)[0], struct.unpack_from('<I', b, 0)[0], struct.unpack_from('<I', b, 0x10)[0],
            struct.unpack_from('<I', b, 0x18)[0], struct.unpack_from('<I', b, 0x28)[0])


def ext_bytes(flags=0, atk=0, rel=0, curves=0, dec=0, sus=0, version=None, rest=b'\0\0\0'):
    b = bytes([flags, atk, rel, curves, dec, sus]) + rest
    v = (1 if any(b) else 0) if version is None else version
    return b + bytes([v, 0, 0])


# ---------------------------------------------------------------- static
def static_checks(out, man, img, parent):
    check(sha(img) == man['sha256'] and len(img) == man['size'], 'APP1 matches its manifest')
    check(sha((out / 'SP404MKII_APP0.bin').read_bytes()) == man['app0_sha256'] ==
          '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23', 'APP0 is stock 5.52')
    sums = (out / 'SHA256SUMS.txt').read_text(encoding='utf-8').split()
    check(dict(zip(sums[1::2], sums[0::2])) == {n: sha((out / n).read_bytes()) for n in (
        'SP404MKII_APP0.bin', 'SP404MKII_APP1.bin', 'manifest.json')}, 'SHA256SUMS.txt matches the files')
    rows, prow = scatter(img), scatter(parent)
    base, size = man['blob_base'], man['blob_size']
    check(rows == prow + [[FLASH + man['blob_file_offset'], base, size, COPY]],
          'scatter table: the parent\'s rows plus one copy row for the module')

    def file_off(addr):
        return [load - FLASH + addr - dst for load, dst, n, fn in prow
                if fn == COPY and load and dst <= addr < dst + n][0]
    allowed = set(range(0x80, 0x88))
    for at, original, _, _, _ in SITES + CALL_SITES:
        allowed |= set(range(file_off(at), file_off(at) + len(original)))
    for off, _, _, _ in VTABLE_SLOTS:
        allowed |= set(range(file_off(VTABLE + off), file_off(VTABLE + off) + 4))
    diff = [i for i in range(len(parent)) if img[i] != parent[i]]
    check(set(diff) <= allowed and img[:len(parent)] != parent,
          f'only the scatter pointer, the five code sites and five ENVELOPE vtable words change inside the parent '
          f'({len(diff)} bytes)')
    e = man['entries']
    rt, nrt = Runtime(parent), Runtime(img)
    ok = []
    for at, original, what, back, entry in SITES:
        jump = movw_movt_bx(12, e[entry]) + bytes.fromhex('00bf') * ((len(original) - 10) // 2)
        ok.append(rt.read(at, len(original)) == original and nrt.read(at, len(original)) == jump)
    for at, original, what, back, entry in CALL_SITES:
        ok.append(rt.read(at, len(original)) == original and nrt.read(at, len(original)) == call_code(e[entry]) and
                  back == at + len(original))
    check(all(ok), 'each code site: the stock instructions on the parent, movw ip / movt ip / bx ip to its entry (and '
                   f'never-run nops) here; at 0x8009424e movw ip / movt ip / blx ip, back right after ({ok})')
    ok = [rt.word(VTABLE + off) == old and nrt.word(VTABLE + off) == e[entry] for off, old, entry, _ in VTABLE_SLOTS]
    ok += [rt.word(VTABLE + off) == want == nrt.word(VTABLE + off) for off, want, _ in VTABLE_KEEP]
    check(all(ok), 'ENVELOPE vtable: +0x04 / +0xC8 / +0xCC / +0xD0 / +0xE4 stock on the parent and the module\'s '
                   'here; DOOM OS\'s +0x08 and the current-pad +0x14C untouched')
    check(all(sha(rt.read(s, en - s)) == d for s, en, d, w in GUARDS), f'{len(GUARDS)} guards hold on the parent')
    inside = []
    for at, original, _, _, _ in SITES + CALL_SITES:
        inside += branches_into(rt, at + 1, at + len(original))
        inside += [h for h in refs_into(parent, at + 1, at + len(original)) if h[2] & ~1 != at]
    check(not inside, f'nothing branches or points into the displaced bytes but their entries ({inside[:4]})')
    ok = []
    for name, at in STOCK_COPIES.items():
        site = [s for s in SITES if s[0] == at][0]
        ok.append(nrt.read(e[name] & ~1, len(site[1]) + 10) == site[1] + movw_movt_bx(12, site[3] | 1))
    rel = nrt.read(e['env_release'] & ~1, 22)
    ok.append(rel[-10:] == movw_movt_bx(12, 0x8002316B))
    check(all(ok), 'the module\'s copies of the displaced instructions are exact and go on where the stock code does; '
                   'env_release goes on at 0x8002316a')
    check(nrt.read(base, size) == img[man['blob_file_offset']:man['blob_file_offset'] + size] and
          base + size <= man['slot'][1] and man['slot'] == [base, base + SLOT] and
          not any(max(lo, base) < min(hi, base + SLOT) for _, lo, hi in KNOWN_SLOTS) and
          not any(max(dst, base) < min(dst + n, base + SLOT) for load, dst, n, fn in prow),
          f'the module ({size} bytes) fits its slot {base:#x}..{base + SLOT:#x}, which overlaps no row of the parent '
          f'and no other fork module ({", ".join(n.split(" ")[0] for n, _, _ in KNOWN_SLOTS)})')
    check(not refs_into(parent, base, base + SLOT), 'nothing in the parent refers to the slot')
    frames = fine_frames()
    flt = [0] + [round(24 * 16000 ** ((i - 1) / 126)) for i in range(1, 128)]
    curves = curve_tables()
    got_f = list(struct.unpack('<128I', nrt.read(e['env_fine_frames'], 512)))
    got_c = [list(struct.unpack('<258H', nrt.read(e['env_curve'] + 516 * k, 516))) for k in range(4)]
    stock = [stock_frames(v) for v in range(128)]
    got_fs = list(nrt.read(e['env_fine_stock'], 128))
    got_sf = list(nrt.read(e['env_stock_fine'], 128))
    near_s = [min(range(128), key=lambda v: (abs(stock[v] - f), v)) for f in frames]
    near_f = [min(range(128), key=lambda i: (abs(frames[i] - f), i)) for f in stock]
    check(got_f == frames == flt and frames[1] == 24 and frames[127] == 384000 and got_fs == near_s and
          got_sf == near_f and got_fs[[i for i in range(128) if abs(frames[i] - 10368) < 400][0]] == 9,
          'the FINE map is 0, then 0.5 ms * 16000^((i - 1) / 126) (24 frames .. 8 s = 384000), with the nearest stock '
          'value of each (216 ms -> 9) and the nearest index of each stock value')
    exp = [round((2 ** (6 * i / 256) - 1) / 63 * ONE) for i in range(257)]
    sm = [round((3 * (i / 256) ** 2 - 2 * (i / 256) ** 3) * ONE) for i in range(257)]
    check(got_c == curves and got_c[0][:257] == [i * 128 for i in range(257)] and
          all(abs(a - b) <= 1 for a, b in zip(got_c[1], exp)) and
          got_c[2][:257] == [ONE - got_c[1][256 - i] for i in range(257)] and
          all(abs(a - b) <= 1 for a, b in zip(got_c[3], sm)) and
          all(t[257] == t[256] == ONE and t[0] == 0 for t in got_c) and
          all(t[i] <= t[i + 1] for t in got_c for i in range(257)),
          'the curves: LIN, EXP (2^(6x) - 1) / 63, LOG = 1 - EXP mirrored, S 3x^2 - 2x^3; Q15, rising from 0 to 1')
    return frames, curves


# ---------------------------------------------------------------- neutral: the parent's bytes
NEUTRAL = [('all zero', ext_bytes()),
           ('version 0, everything else set', ext_bytes(0x0F, 40, 50, 0x3F, 60, 50, version=0)),
           ('version 1, every setting stock (fine indices, decay off, sustain kept)',
            ext_bytes(0x00, 40, 50, 0x00, 0, 70)),
           ('version 1, ADSR flag with decay 0', ext_bytes(0x02, 0, 0, 0x0C, 0, 30)),
           ('version 1, ADSR with sustain 100 % (decay curve set)', ext_bytes(0x02, 0, 0, 0x08, 60, 100)),
           ('an unknown version, everything set', ext_bytes(0x0F, 40, 50, 0x3F, 60, 50, version=2)),
           ('E3a bytes only', ext_bytes(rest=b'\x01\x20\x30'))]
SHAPED = ext_bytes(0x0F, 30, 70, 0x39, 50, 40)


def neutral_checks(img, parent, man, n):
    rnd = random.Random(7)
    p, m = Machine(parent), Machine(img, man['entries'])
    bad_r, bad_a, bad_n, total = [], [], [], 0
    for k in range(n * 3):
        label, b = NEUTRAL[k % len(NEUTRAL)]
        i, pad = rnd.randrange(32), rnd.randrange(160)
        kind = k // len(NEUTRAL) % 4
        if kind == 3:                                     # a voice whose pad index isn't a pad, shaped bytes
            label, b = 'a voice with no pad (index 160 / -1), shaped settings on pad 0', SHAPED
            vpad = rnd.choice((160, -1))
        else:
            vpad = pad
        for mm in (p, m):
            mm.set_ext(max(vpad, 0) if vpad < 160 else 0, b)
            v = mm.voice(i, vpad)
        env = v + 0x60
        start, length = rnd.randrange(0, 300000), rnd.randrange(64, 500000)
        args = (start, length, rnd.randrange(128), rnd.randrange(1, 101), rnd.randrange(128), rnd.choice((1, 2)))
        lr = rnd.choice(list(CALLERS) + [RET])
        res = [(mm.recompute(env, *args, lr=lr), mm.block(env)) for mm in (p, m)]
        total += 1
        if res[0] != res[1]:
            bad_r.append((label, args))
        for fn in (FWD, REV, FWD_WRAP, REV_WRAP):
            pos = max(0, start + rnd.randrange(-600, length + 600))
            cnt = rnd.choice((1, 7, 64, 300, 2048))
            state = rnd.choice((0, 0, 0, 7))
            L = [rnd.randrange(-32768, 32768) for _ in range(cnt)]
            R = [rnd.randrange(-32768, 32768) for _ in range(cnt)]
            if fn in (FWD_WRAP, REV_WRAP):                # the wrappers take (env, L, R, pos, n, x, state, y)
                outs = []
                for mm in (p, m):
                    mm.uc.mem_write(SCRATCH + 0x1000, struct.pack(f'<{cnt}h', *L))
                    mm.uc.mem_write(SCRATCH + 0x5000, struct.pack(f'<{cnt}h', *R))
                    mm.call(fn | 1, env, SCRATCH + 0x1000, SCRATCH + 0x5000, pos, stack=(cnt, 0, state, 0),
                            count=20_000_000)
                    outs.append(bytes(mm.uc.mem_read(SCRATCH + 0x1000, 2 * cnt)) +
                                bytes(mm.uc.mem_read(SCRATCH + 0x5000, 2 * cnt)))
            else:
                outs = [mm.apply(fn, env, L, R, pos, cnt, state) for mm in (p, m)]
            if outs[0] != outs[1]:
                bad_a.append((label, hex(fn), args, pos, cnt, state))
        rr = rnd.randrange(128)
        pos_b, end_b = rnd.randrange(0x200, 0x400000), rnd.randrange(0x400000, 0x800000)
        played = rnd.randrange(0, 1000)
        no = [mm.note_off(v, rr, pos_b, end_b, played) for mm in (p, m)]
        if no[0] != no[1]:
            bad_n.append((label, rr, no))
    check(not bad_r, f'neutral pads: the recompute through the dispatcher leaves the parent\'s block and r0, from '
                     f'every caller ({total} cases: {len(NEUTRAL)} kinds of neutral settings, voices without a pad; '
                     f'{bad_r[:2]})')
    check(not bad_a, f'neutral pads: forward and reverse applicators and their wrappers give the parent\'s frames '
                     f'({4 * total} blocks of 1-2048 frames, mono and stereo, slot state 7, before START; {bad_a[:2]})')
    check(not bad_n, f'neutral pads: the note-off gives the parent\'s result and release counters ({total} cases; '
                     f'{bad_n[:2]})')
    # a block that is not a voice's: stock, whatever the pad bytes say
    bad = []
    for k in range(n):
        env = SCRATCH + 0x800
        for mm in (p, m):
            mm.set_ext(0, SHAPED)
        args = (rnd.randrange(0, 300000), rnd.randrange(64, 500000), rnd.randrange(128), rnd.randrange(1, 101),
                rnd.randrange(128), rnd.choice((1, 2)))
        res = [(mm.recompute(env, *args), mm.block(env)) for mm in (p, m)]
        pos, cnt, fn = rnd.randrange(0, 600000), rnd.choice((16, 512)), rnd.choice((FWD, REV))
        L = [rnd.randrange(-32768, 32768) for _ in range(cnt)]
        outs = [mm.apply(fn, env, L, L, pos, cnt, 0) for mm in (p, m)]
        if res[0] != res[1] or outs[0] != outs[1]:
            bad.append(args)
    check(not bad, f'a block that is not a voice\'s (scratch memory): recompute and applicators as the parent '
                   f'({bad[:2]})')
    # the stock path within an edit: the envelope off and on again on a sounding voice
    v_p, v_m = p.voice(3, 9), m.voice(3, 9)
    for mm in (p, m):
        mm.set_ext(9, SHAPED)
    m.recompute(v_m + 0x60, 1000, 200000, 20, 100, 30, 2)
    for mm in (p, m):
        mm.set_ext(9, ext_bytes())
    outs = []
    for mm, v in ((p, v_p), (m, v_m)):
        mm.recompute(v + 0x60, 1000, 200000, 20, 100, 30, 2, lr=0x8001FF39)
        L = list(range(-1000, 1000))
        outs.append(mm.apply(FWD, v + 0x60, L, L, 1500, 2000, 0))
    check(outs[0] == outs[1], 'a voice shaped, then its pad set back to stock and recomputed (an edit): the parent\'s '
                              'frames again')


# ---------------------------------------------------------------- shaped: the model
def random_settings(rnd):
    flags = rnd.choice((1, 1, 3, 2, 0, 9, 3 | 8, 4, 5, 7))
    b = ext_bytes(flags, rnd.choice((0, 1, 5, 16, 32, 48, 64, 80, 96, 112, 127, rnd.randrange(128))),
                  rnd.choice((0, 1, 8, 24, 40, 64, 90, 127, rnd.randrange(128))), rnd.randrange(64),
                  rnd.choice((0, 1, 20, 50, 70, 100, 127)), rnd.choice((0, 0, 10, 50, 99, 100, 120)))
    return b[:9] + b'\x01' + b[10:]


def time_text(f):
    """the popup's time: 0ms; under 10 ms in tenths; under 1 s in ms; else seconds with two decimals"""
    t = (f * 10 + 24) // 48
    if not f:
        return '0ms'
    if t < 100:
        return f'{t // 10}.{t % 10}ms'
    ms = (t + 5) // 10
    if ms < 1000:
        return f'{ms}ms'
    cs = (ms + 5) // 10
    return f'{cs // 100}.{cs // 10 % 10}{cs % 10}s'


def shaped_checks(img, man, frames, curves, n):
    rnd = random.Random(11)
    m = Machine(img, man['entries'])
    model = Model(curves, frames)
    bad_shape, bad_frames, kinds, total = [], [], set(), 0
    for k in range(n * 4):
        i, pad = rnd.randrange(32), rnd.randrange(160)
        b = random_settings(rnd)
        m.set_ext(pad, b)
        v = m.voice(i, pad)
        env = v + 0x60
        start = rnd.choice((0, rnd.randrange(0, 400000)))
        length = rnd.choice((rnd.randrange(64, 3000), rnd.randrange(3000, 800000)))
        args = (start, length, rnd.randrange(128), rnd.choice((100, rnd.randrange(1, 101))), rnd.randrange(128),
                rnd.choice((1, 2)))
        m.recompute(env, *args, lr=rnd.choice(list(CALLERS)))
        want = model.shape(b, pad, stock_block(m, env))
        got = published(m, i)
        if want is None:
            if got['on']:
                bad_shape.append(('should be stock', b.hex(), args))
            continue
        if any(got[key] != want[key] for key in want):
            bad_shape.append((b.hex(), args, {key: (got[key], want[key]) for key in want if got[key] != want[key]}))
            continue
        kinds.add(('overlap' if want['ae'] == want['rs'] and want['rs'] != want['he'] - want['rel'] else 'apart') +
                  ('+adsr' if want['adsr'] else '') + ('+rev' if want['rev'] else ''))
        stereo = args[5] != 1
        for fn in (FWD, REV, FWD, REV):
            total += 1
            pos = max(0, start + rnd.choice((rnd.randrange(-300, 300), rnd.randrange(-600, length + 600),
                                             length - rnd.randrange(0, 600))))
            cnt = rnd.choice((1, 5, 64, 333, 1024, 2048))
            state = rnd.choice((0, 0, 0, 0, 7))
            L = [rnd.randrange(-32768, 32768) for _ in range(cnt)]
            R = [rnd.randrange(-32768, 32768) for _ in range(cnt)]
            got_lr = m.apply(fn, env, L, R, pos, cnt, state)
            want_lr = model.apply(want, 0, L, R, pos, cnt, state, stereo, fn == REV)
            if got_lr != want_lr:
                bad = [j for j in range(cnt) if got_lr[0][j] != want_lr[0][j] or got_lr[1][j] != want_lr[1][j]]
                bad_frames.append((b.hex(), args, hex(fn), pos, cnt, state, len(bad), bad[:3]))
    check(not bad_shape, f'shaped pads: the published shape is the model\'s for every setting and caller '
                         f'({n * 4} recomputes; {bad_shape[:2]})')
    check(not bad_frames and {'apart', 'overlap', 'apart+adsr', 'apart+rev'} <= kinds,
          f'shaped pads: every frame of both applicators is the model\'s ({total} blocks; FINE and stock times, the '
          f'four curves, decay and sustain, attack/decay/release overlapping, REV-TIME, mono and stereo, state 7, '
          f'before START and past the HOLD point; {sorted(kinds)}; {bad_frames[:2]})')

    # FINE edges: the shortest and longest times, an exactly fitting ADSR, a decay cut by the release
    edge = []
    for b, args in ((ext_bytes(1, 1, 1), (0, 100000, 0, 100, 0, 2)),
                    (ext_bytes(1, 127, 127), (500, 900000, 0, 100, 0, 2)),
                    (ext_bytes(3, 16, 16, 0x15, 40, 30), (0, frames[16] * 2 + frames[40], 0, 100, 0, 2)),
                    (ext_bytes(3, 16, 64, 0x15, 100, 30), (0, 50000, 0, 100, 0, 1)),
                    (ext_bytes(1, 60, 60, 0x10), (0, 1000, 0, 100, 0, 2)),
                    (ext_bytes(1, 0, 90), (0, 100, 0, 1, 0, 2))):
        m.set_ext(5, b)
        v = m.voice(0, 5)
        m.recompute(v + 0x60, *args)
        want = model.shape(b, 5, stock_block(m, v + 0x60))
        ok = all(published(m, 0)[key] == want[key] for key in want)
        span = args[1] * args[3] // 100
        for pos in range(0, min(span + 200, 4000), 397) if span < 4000 else (0, span // 3, span - 1000, span - 10):
            L = [rnd.randrange(-32768, 32768) for _ in range(1000)]
            ok = ok and m.apply(FWD, v + 0x60, L, L, pos, 1000, 0) == model.apply(want, 0, L, L, pos, 1000, 0,
                                                                                    args[5] != 1, False)
        edge.append(ok)
    check(all(edge), f'FINE edges: 0.5 ms and 8 s, A + D + R filling the HOLD span exactly, a decay cut by the '
                     f'release, overlapping FINE times, a HOLD span of 0 ({edge})')

    # LOOP-ONCE: wraps, turns, an Init reset; a one-shot is positional
    bad, seen = [], set()
    for k in range(n):
        i, pad = rnd.randrange(32), rnd.randrange(160)
        b = ext_bytes(rnd.choice((4, 5, 7, 6, 4 | 8)), rnd.randrange(1, 90), rnd.randrange(128), rnd.randrange(64),
                      rnd.randrange(1, 80), rnd.choice((0, 30, 60)))
        looping = rnd.choice((1, 1, 0))
        m.set_ext(pad, b)
        v = m.voice(i, pad, looping)
        start, length = rnd.randrange(0, 1000), rnd.randrange(20000, 300000)
        args = (start, length, rnd.randrange(128), 100, rnd.randrange(128), 2)
        m.recompute(v + 0x60, *args, lr=INIT_RET)
        want = model.shape(b, pad, stock_block(m, v + 0x60))
        state, pos, direction = LoopState(), start, 1
        for step in range(12):
            r = rnd.random()
            if r < 0.15:
                pos = start + rnd.randrange(0, 2000)          # a wrap back to the loop point
            elif r < 0.25:
                direction = 3 - direction                     # a ping-pong turn
            elif r < 0.3:                                     # a new start (Init): the first pass again
                m.recompute(v + 0x60, *args, lr=INIT_RET)
                state = LoopState()
                pos, direction = start, 1
            elif r < 0.35:                                    # an edit (A/H/R): the pass goes on
                m.recompute(v + 0x60, *args, lr=0x8001FF39)
            cnt = rnd.choice((256, 1024, 2048))
            L = [rnd.randrange(-32768, 32768) for _ in range(cnt)]
            mode = state.mode(want, looping, pos, cnt, direction)
            seen.add(mode)
            got = m.apply(FWD if direction == 1 else REV, v + 0x60, L, L, pos, cnt, 0)
            if got != model.apply(want, mode, L, L, pos, cnt, 0, True, direction == 2):
                bad.append((b.hex(), looping, step, pos, cnt, direction, mode))
                break
            pos = pos + cnt if direction == 1 else max(start, pos - cnt)
        lp = struct.unpack_from('<BBBBI', bytes(m.uc.mem_read(m.sym['env_voices'] + i * 112 + 104, 8)))
        if want['once'] and looping and (lp[1], lp[2]) != (state.passed, state.dir):
            bad.append(('state', b.hex(), lp, state.passed, state.dir))
    check(not bad and seen == {0, 1, 2}, f'LOOP-ONCE: a looping voice is shaped on its first pass only (attack, decay, '
                                         f'then the sustain level, no release, no HOLD point), until a wrap or a turn; '
                                         f'Init starts a new first pass; a one-shot stays positional ({n} sequences; '
                                         f'{bad[:2]})')
    return m


# ---------------------------------------------------------------- note-off
def note_off_checks(img, parent, man, frames):
    m, p = Machine(img, man['entries']), Machine(parent)
    bad, got_short, got_long = [], 0, 0
    for idx in range(128):
        m.set_ext(12, ext_bytes(1, 10, idx))
        v = m.voice(4, 12)
        m.recompute(v + 0x60, 0, 400000, 10, 100, 9, 2)
        f = frames[idx]
        for end_bytes, played in ((0x200 + 4 * 1000000, 0), (0x200 + 4 * 30, 0), (0x200 + 4 * (f + 7), 3),
                                  (0x200 + 4 * 5000, 100)):
            res, c1, c2 = m.note_off(v, 9, 0x200, end_bytes, played)
            left = (end_bytes >> 2) + ((0x200 - 0x200) >> 2) - played
            if f >= 64:
                want = (1, -(-min(f, left) // 64), -(-min(f, left) // 64))
                got_long += 1
            else:
                want = (0, 0, 0)
                got_short += 1
            if (res, c1, c2) != want:
                bad.append((idx, f, end_bytes, played, (res, c1, c2), want))
    check(not bad, f'note-off, FINE release: every fine index (shorter than 64 frames: the stock declick, result 0; '
                   f'else ceil(min(release, frames left) / 64) blocks, result 1) ({got_short} + {got_long} cases; '
                   f'{bad[:3]})')
    # a shaped pad without FINE keeps stock's key-up release
    bad = []
    for r in (0, 1, 5, 40, 127):
        for mm in (m, p):
            mm.set_ext(13, ext_bytes(0, 0, 0, 0x30))
            v = mm.voice(6, 13)
            mm.recompute(v + 0x60, 0, 400000, 10, 100, r, 2)
        outs = [mm.note_off(VOICES + 6 * VOICE_SIZE, r, 0x200, 0x200 + 4 * 300000, 0) for mm in (m, p)]
        if outs[0] != outs[1]:
            bad.append((r, outs))
    check(not bad, f'note-off, a shaped pad with stock times (curves only): the parent\'s release ({bad})')
    m.set_ext(14, ext_bytes(1, 10, 100))
    v = m.voice(7, 14)
    m.recompute(v + 0x60, 0, 400000, 10, 100, 9, 2)
    check(m.note_off(v, 9, 0x200, 0x200 + 4 * 300000, 0, counter=5) == (1, 5, 5),
          'note-off with a release already running: left alone (result 1), as stock')


# ---------------------------------------------------------------- the re-hit
SLOTS, SLOT_SIZE, SLOT_STATES = 0x202AE1A0, 0x58, SCRATCH + 0x8000  # 32 slots; their state words made here (0 free)
STOP, STOP_DECLICK, STOP_SPIN, SLOT_NOTE_OFF = 0x80094168, 0x80024580, 0x800942B0, 0x800D5E78
VMAN, VMAN_OBJ, VSTART = 0x800D63C8, 0x80D4E630, 0x800200E0
NOW, TICK = 0x3FFA, 0x202BCF20                           # the RTOS time (0x800d3194): a tick later at every read here
STOP_FLAG, STOP_COUNT, STOP_TIME = 0x82E4EA50, 0x82E4E9D0, 0x833B8608
NOTES, NOTE_BASE = 0x801AA0A0, PROJECT + 0x2C            # chromatic: pad -> note offset, minus the project's base
INFO, SEG, SEGREC = SCRATCH + 0x8400, SCRATCH + 0x9000, SCRATCH + 0xA000
REHITS = {0x800D6C0D: 'a new hit (0x800d6c08)', 0x800D6959: 'a looping chromatic note again with HOLD (0x800d6954)'}
NOT_REHITS = {0x800D6A35: 'stop-all while recording (0x800d6a30)', 0x800D6FFF: 'the steal (0x800d6ffa)',
              0x800D67DD: 'the MIDI chromatic loop (0x800d67d8)'}
FADE48 = ext_bytes(rest=b'\x01\x30\x00')                 # FADE, fine index 48: 888 frames (19 ms), 14 blocks
RETRIG_PADS = [('CUT', ext_bytes()), ('FADE 19 ms', FADE48),
               ('FADE 0.5 ms (under 64 frames)', ext_bytes(rest=b'\x01\x01\x00')),
               ('FADE 8 s', ext_bytes(rest=b'\x01\x7f\x00')),
               ('FADE bytes, layout version 0', ext_bytes(rest=b'\x01\x30\x00', version=0)),
               ('FADE bytes, unknown layout 2', ext_bytes(rest=b'\x01\x30\x00', version=2)),
               ('retrigger 2 (unknown)', ext_bytes(rest=b'\x02\x30\x00')),
               ('FINE, curves and decay, CUT', ext_bytes(3, 32, 90, 0x19, 70, 40))]
VOICE_STATES = [('sounding (chromatic slot)', dict()), ('sounding (panel-pad slot)', dict(typ=4)),
                ('sounding, 100 frames left', dict(played=200900)), ('releasing', dict(rel=5)),
                ('releasing (panel-pad slot)', dict(rel=5, typ=4)), ('nothing left to play', dict(pos=0, end=0))]


def rehit_machine(img, symbols=None):
    """a machine for the stop and the voice manager: the project's chromatic settings from m.params, time going on,
    the audio task running a declick the stop waits for, and the voice start (Init) only noted"""
    m = Machine(img, symbols, arm_max=True)
    m.params, m.calls = {}, []
    for pad in range(32):
        m.load_pad(pad)

    def project(uc, a, size, _):
        r1 = uc.reg_read(ar.UC_ARM_REG_R1)
        if uc.reg_read(ar.UC_ARM_REG_R0) == PROJECT and r1 in m.params:
            m._ret(m.params[r1])

    def tick(uc, a, size, _):
        uc.mem_write(TICK, struct.pack('<Q', struct.unpack('<Q', bytes(uc.mem_read(TICK, 8)))[0] + 1))

    def spin(uc, a, size, _):
        m.w32(uc.reg_read(ar.UC_ARM_REG_R7) + 0x1439C, 0)

    def start(uc, a, size, _):
        m.calls.append(('start',) + m.regs(3))
        m._ret(0)

    def log(name, n):
        def f(uc, a, size, _):
            m.calls.append((name,) + m.regs(n) + ((uc.reg_read(ar.UC_ARM_REG_LR),) if name == 'stop' else ()))
        return f
    for a, fn in ((SAMPLE_GET, project), (NOW, tick), (STOP_SPIN, spin), (VSTART, start), (STOP, log('stop', 2)),
                  (STOP_DECLICK, log('declick', 2)), (NOTE_OFF, log('note-off', 1)),
                  (SLOT_NOTE_OFF, log('slot note-off', 2))):
        m.uc.hook_add(UC_HOOK_CODE, fn, None, begin=a, end=a)
    return m


def free_slots(m):
    for k in range(32):
        s = SLOTS + k * SLOT_SIZE
        m.uc.mem_write(s, bytes(SLOT_SIZE))
        m.w32(s + 4, SLOT_STATES + 16 * k)
        m.uc.mem_write(SLOT_STATES + 16 * k, bytes(16))
        m.w32(s + 0x28, k)
        m.w32(s + 0x2C, M32)
    m.w32(SEGREC + 0x2080, M32)                         # no loop record: the release counts from the played frames
    m.uc.mem_write(TICK, bytes(8))
    m.uc.mem_write(STOP_FLAG, b'\0')
    m.uc.mem_write(STOP_COUNT, bytes(4 * 32))
    m.uc.mem_write(STOP_TIME, bytes(8 * 32))


def sounding(m, k, i, pad, typ=0xC, note=0, pos=1000, end=200000, played=0, rel=0):
    """slot k, busy, holds voice i of pad (the stand-in voice class): at pos frames of END end, played frames counted,
    rel release blocks left (0 none); a playing voice's segment table (byte 1 not 0xff)"""
    s, v = SLOTS + k * SLOT_SIZE, VOICES + i * VOICE_SIZE
    m.w32(s, v)
    m.w32(SLOT_STATES + 16 * k, 1)
    m.w32(s + 0x14, 100 + k)                            # start serial: the oldest is stolen first
    m.w32(s + 0x2C, typ)
    m.w32(s + 0x4C, note)
    info, seg = INFO + 0x40 * i, SEG + 0x40 * i
    m.w32(v, SCRATCH + 0x10)
    m.w32(v + 0x100, 40)
    m.w32(v + 0x14264, info)
    m.w32(v + 0x14268, seg)
    m.uc.mem_write(seg, bytes(0x40))
    m.w32(seg + 0x20, SEGREC)
    m.w32(v + 0x14274, pad)
    m.w32(v + 0x14278, k)
    m.w32(v + 0x143B8, played)
    m.w32(info + 8, 0x200 + 4 * pos)
    m.w32(info + 0x18, 4 * end)
    m.w32(info + 0x54, 0)
    m.uc.mem_write(v + 0x14260, b'\0\0')
    m.w32(v + 0x1439C, 0)
    m.uc.mem_write(v + 0x143A0, b'\0')
    m.w32(v + 0x143AC, rel)
    m.w32(v + 0x143B0, rel)
    return s, v


def stop_state(m, k, v):
    """what a stop may change: the voice's play state, its slot, the stop's flag, count and time"""
    return dict(voice=bytes(m.uc.mem_read(v + 0x14200, 0x200)), slot=bytes(m.uc.mem_read(SLOTS + k * SLOT_SIZE,
                                                                                         SLOT_SIZE)),
                flag=bytes(m.uc.mem_read(STOP_FLAG, 1)), count=m.r32(STOP_COUNT + 4 * k),
                time=bytes(m.uc.mem_read(STOP_TIME + 8 * k, 8)), tick=bytes(m.uc.mem_read(TICK, 8)))


def with_release(st, blocks):
    """stop state st with the voice's release blocks set and no declick"""
    b = bytearray(st['voice'])
    struct.pack_into('<I', b, 0x19C, 0)
    struct.pack_into('<2I', b, 0x1AC, blocks, blocks)
    return dict(st, voice=bytes(b))


def retrig_checks(img, parent, man, frames):
    m, p = rehit_machine(img, man['entries']), rehit_machine(parent)
    # the stop, called as its callers do, on every kind of pad and voice
    bad, faded, alone, kinds = [], 0, 0, set()
    for what, b in RETRIG_PADS:
        on = b[9] == 1 and b[6] == 1
        f = frames[b[7] & 127]
        for lr in list(REHITS) + list(NOT_REHITS):
            for wait in (0, 1):
                for sname, st in VOICE_STATES:
                    res = []
                    for mm in (m, p):
                        free_slots(mm)
                        mm.set_ext(3, b)
                        s, v = sounding(mm, 6, 6, 3, **st)
                        before = stop_state(mm, 6, v)
                        mm.calls.clear()
                        mm.call(STOP | 1, s, wait, lr=lr, until=lr & ~1, count=5_000_000)
                        res.append((before, stop_state(mm, 6, v), [c for c in mm.calls if c[0] != 'stop']))
                    (b0, after, calls), (_, want, stock) = res
                    left = st.get('end', 200000) + st.get('pos', 1000) - st.get('played', 0)
                    blocks = -(-min(f, left) // 64) if f >= 64 else 0
                    eligible = on and lr in REHITS and not wait
                    if eligible and st.get('rel'):
                        ok = calls == [] and after['voice'] == b0['voice'] and after['slot'] == b0['slot'] and \
                            after['flag'] == b'\0' and after['count'] == 0
                        alone += ok
                        kinds.add('releasing')
                    elif eligible and blocks >= 1:
                        ok = calls == [('note-off', v)] and after['voice'] == with_release(b0, blocks)['voice'] and \
                            after['slot'] == b0['slot'] and after['flag'] == b'\0' and after['count'] == 0
                        faded += ok
                        kinds.add('faded')
                    else:                               # stock's declick (a fade it can't give: note-off tried first)
                        ok = after == want and [c for c in calls if c[0] != 'note-off'] == stock and \
                            [c for c in calls if c[0] == 'note-off'] == ([('note-off', v)] if eligible else [])
                        kinds.add('stock')
                    if not ok:
                        bad.append((what, hex(lr), wait, sname))
    total = len(RETRIG_PADS) * (len(REHITS) + len(NOT_REHITS)) * 2 * len(VOICE_STATES)
    check(not bad and faded and alone and kinds == {'faded', 'releasing', 'stock'},
          f'the stop 0x80094168 as its callers call it ({total} cases): for a new hit ({", ".join(REHITS.values())}) '
          f'with free slots (wait 0) on a FADE pad, a sounding voice gets the key-up release over the fade, '
          f'ceil(min(fade, frames left) / 64) blocks, and no declick ({faded} cases), and a releasing one goes on '
          f'untouched ({alone}); the slot, the stop\'s flag and count as stock leaves them; everything else is the '
          f'parent\'s, byte for byte: CUT pads, a fade under 64 frames or with nothing left to play (the declick), '
          f'other layouts and retrigger values, wait 1 (the new voice needs this slot), and the other callers '
          f'({", ".join(NOT_REHITS.values())}) ({bad[:4]})')

    # through the voice manager: where the new voice goes and what happens to the old one
    table = struct.unpack('<16i', bytes(p.uc.mem_read(NOTES, 64)))
    base = s32(p.r32(NOTE_BASE))
    bad, seen = [], []
    cases = [('chromatic, mono: another note while one rings', 1, 1, 5, 0xC, 2, True),
             ('chromatic, poly: the ringing note again', 1, 0, 2, 0xC, 2, True),
             ('chromatic, poly: another note (both ring)', 1, 0, 5, 0xC, 2, False),
             ('a pad hit again while it rings', 0, 1, 3, 4, 0, True),
             ('chromatic, mono, every slot busy (the new voice needs the old slot)', 1, 1, 5, 0xC, 2, None)]
    for what, chrom, mono, pressed, typ, ringing, stops in cases:
        for pname, b in (('CUT', ext_bytes()), ('FADE 19 ms', FADE48)):
            res = []
            for mm in (m, p):
                free_slots(mm)
                mm.params = {0xBF: chrom, 0xC1: 3, 0xF3: 0 if mono else 2}
                mm.set_ext(3, b)
                s, v = sounding(mm, 7, 7, 3, typ, table[ringing] - base if chrom else 0)
                if stops is None:
                    for k in range(32):
                        if k != 7:
                            sounding(mm, k, k, 8 + k % 8, 4)
                mm.calls.clear()
                r = mm.call(VMAN | 1, VMAN_OBJ, 0xC if chrom else 4, pressed if chrom else 3, 100, stack=(0, 0, 0),
                            count=50_000_000)
                res.append((r, list(mm.calls), [stop_state(mm, k, VOICES + k * VOICE_SIZE) for k in range(32)],
                            mm.r32(SLOT_STATES + 16 * 7), mm.r32(SLOTS + 7 * SLOT_SIZE)))
            (r, calls, states, busy, held), (pr, pcalls, pstates, _, _) = res
            starts = [c[1] for c in pcalls if c[0] == 'start']
            stop = [c for c in pcalls if c[0] == 'stop' and c[1] == s]
            if pname == 'CUT' or not stops:
                ok = (r, [c[:3] if c[0] == 'declick' else c for c in calls], states) == \
                    (pr, [c[:3] if c[0] == 'declick' else c for c in pcalls], pstates)
            else:
                want = [('note-off', v) if c[:2] == ('declick', v) else c for c in pcalls]
                pstates[7] = with_release(pstates[7], 14)
                ok = r == pr and calls == want and stop == [('stop', s, 0, 0x800D6C0D)] and \
                    [k for k in range(32) if states[k]['voice'] != pstates[k]['voice']] == [] and \
                    [st['slot'] for st in states] == [st['slot'] for st in pstates] and busy == 1 and held == v and \
                    starts and starts[0] != s
            seen.append((what, pname, bool(stop), starts[:1] and (starts[0] - SLOTS) // SLOT_SIZE))
            if not ok:
                bad.append((what, pname))
    check(not bad and [x[2] for x in seen] == [True, True, True, True, False, False, True, True, True, True],
          f'through the voice manager 0x800d63c8 (the new voice\'s start only noted): chromatic mono (project 0xf3 '
          f'not 2) stops the ringing note for any new one, poly only for the same note, a panel pad hit again stops '
          f'its voice, all from 0x800d6c08 with wait 0; on a FADE pad the old voice fades out over 14 blocks instead '
          f'of the declick and keeps its slot (busy) while the new voice starts in a free one; CUT pads, and every '
          f'slot busy (wait 1), are the parent\'s ({bad}; {seen})')


# ---------------------------------------------------------------- the dispatcher
def dispatcher_checks(img, parent, man):
    m, p = Machine(img, man['entries']), Machine(parent)
    m.w32(m.sym['env_stages'] + 4, SCRATCH + 0x21)
    ok = []
    for lr, what in CALLERS.items():
        for mm in (m, p):
            mm.set_ext(20, SHAPED)
            v = mm.voice(9, 20)
        m.clear()
        res = [(mm.recompute(v + 0x60, 777, 90000, 33, 80, 44, 1, lr=lr), mm.block(v + 0x60)) for mm in (m, p)]
        want = dict(env=v + 0x60, start=777, length=90000, a=33, h=80, r=44, ch=1, lr=lr | 1, voice=9, pad=20)
        ok.append(res[0] == res[1] and m.stage_calls == [want] and published(m, 9)['on'])
    m.clear()
    m.recompute(SCRATCH + 0x800, 5, 6000, 1, 2, 3, 2)
    ok.append(m.stage_calls == [dict(env=SCRATCH + 0x800, start=5, length=6000, a=1, h=2, r=3, ch=2, lr=RET | 1,
                                     voice=-1, pad=-1)])
    check(all(ok), f'the dispatcher: the stock block first, then each env_stages entry gets the call (block, '
                   f'arguments, return address, voice, pad) once, from all five callers '
                   f'({", ".join(CALLERS.values())}) and for a block that is not a voice\'s ({ok})')
    m.w32(m.sym['env_stages'] + 4, 0)


# ---------------------------------------------------------------- the ENVELOPE page
# ---------------------------------------------------------------- the ENVELOPE page and its screen
PAGE_LABELS = [['C1:ATTACK', 'C2:HOLD', 'C3:RELEASE'], ['C1:ATTACK', 'C2:TIME', 'C3:RELEASE'],
               ['C1:DECAY', 'C2:SUSTAIN', 'C3:CURVE'], ['C1:LOOP', 'C2:RETRIG', 'C3:REVERSE']]
PAGE_NAMES = ['', 'SHAPE', 'DECAY', 'MODE']
CURVE_NAMES = ['LIN', 'EXP', 'LOG', 'S']
SPAN = (0, 288000)                                       # every test pad's START and END: 6 s
R_LOOP, R_PLAY = 0x14, 0x3C                              # pad record: LOOP; PLAY (bit 0 reverse)


def pad_label(pad):
    return f'{"ABCDEFGHIJ"[pad // 16]}-{pad % 16 + 1}'


def record(pad):
    return CSMPLPRM + 0xD0 + pad * 0xAC


class Screens:
    """The ENVELOPE screen as it should be, worked out from the settings alone, then drawn with stock's own calls on
    the parent from a freshly opened page: the labels on the screen and in the static layer, stock's redraw, then the
    graph, the values and the bottom line."""

    def __init__(self, model, frames, parent):
        self.model, self.F = model, frames
        self.p = Machine(parent, screen=True)
        for pad in range(32):
            self.p.load_pad(pad)
            self.p.samples[pad] = SPAN

    def shape(self, b, pad, a, h, r):
        s, e = SPAN
        length = e - s
        blk = (s, length, s + a * 144000 // 127, s + h * (length // 100) + h * (length % 100) // 100,
               r * 144000 // 127)
        return self.model.shape(b, pad, blk)

    def points(self, sh, loop, play):
        s, e = SPAN
        step, rem = (e - s) // 127, (e - s) % 127
        mode = 1 if sh['once'] and loop else 0
        mirror = sh['rev'] and play & 1
        pts = []
        for x in range(128):
            q = s + x * step + x * rem // 127
            pts.append((127 - x if mirror else x, GRAPH_ZERO - ((self.model.level(sh, mode, q) * 15 + 16384) >> 15)))
            if not mode and q >= sh['he']:
                break
        return pts

    def view(self, n, pad, b, a, h, r, loop=0, play=0, count=4, extra=None):
        eff = b if b[9] == 1 else bytes(12)
        sh = self.shape(b, pad, a, h, r)
        v = dict(labels=None, values=None, graph=None, bottom=None)
        if extra:
            v['graph'] = []                               # its own graph: the stub draws nothing
        elif sh:
            v['graph'] = self.points(sh, loop, play)
        if n == 0:
            if sh and sh['fine']:
                v['values'] = [time_text(sh['atk']), str(h), time_text(sh['rel'])]
            return v
        if extra:
            v['labels'], v['values'], name = extra['labels'], extra['values'], extra['name']
        else:
            v['labels'], name = PAGE_LABELS[n], PAGE_NAMES[n]
            if n == 1:
                v['values'] = [CURVE_NAMES[eff[3] & 3], 'FINE' if eff[0] & 1 else 'STOCK', CURVE_NAMES[eff[3] >> 4 & 3]]
            elif n == 2:
                dec = eff[4] & 127 if eff[0] & 2 else 0
                v['values'] = [time_text(self.F[dec]) if dec else 'OFF', f'{min(eff[5], 100)}%',
                               CURVE_NAMES[eff[3] >> 2 & 3]]
            else:
                fade = eff[7] & 127 if eff[6] == 1 else 0
                v['values'] = ['FIRST' if eff[0] & 4 else 'EVERY', time_text(self.F[fade]) if fade else 'CUT',
                               'TIME' if eff[0] & 8 else 'MIRROR']
        v['bottom'] = f'{pad_label(pad)} {name} {n + 1}/{count}'
        return v

    def fill(self, ctx, x0, y0, x1, y1):
        p = self.p
        p.uc.mem_write(SCRATCH + 0x7800, struct.pack('<4i', x0, y0, x1, y1))
        p.call(COLOR | 1, ctx, 0, WHITE)
        p.call(FILL_FG | 1, ctx, SCRATCH + 0x7800, count=20_000_000)
        p.call(COLOR | 1, ctx, WHITE, 0)

    def text(self, ctx, x, y, s):
        if s:
            p = self.p
            p.uc.mem_write(SCRATCH + 0x7840, s.encode('ascii') + b'\0')
            p.call(FONT | 1, ctx, FONT_ID)
            p.call(TEXT | 1, ctx, x, y, SCRATCH + 0x7840, count=20_000_000)

    def labels(self, ctx, labels):
        self.fill(ctx, 0, 0, 127, 7)
        for k in range(3):
            self.text(ctx, COLUMNS[k], LABEL_Y, labels[k])

    def draw(self, v, pad, a, h, r, loop=0, play=0):
        """(screen, static layer) of view v for pad, drawn on the parent"""
        p = self.p
        if p.page:
            p.leave()
        p.current_pad(pad)
        for param, value in ((0x7D, a), (0x7E, h), (0x7F, r)):
            p.set(param, value, pad)
        p.w32(record(pad) + R_LOOP, loop)
        p.w32(record(pad) + R_PLAY, play)
        p.open_page()
        ctx = p.r32(p.page + 0x34)
        if v['labels'] is not None:
            self.labels(ctx, v['labels'])
            local = SCRATCH + 0x7000
            p.call(CTX_INIT | 1, local, p.r32(p.page + 0xC00), count=20_000_000)
            self.labels(local, v['labels'])
            p.call(CTX_FREE | 1, local, count=20_000_000)
        p.call(STOCK_DRAW | 1, p.page, count=50_000_000)
        if v['graph'] is not None:
            self.fill(ctx, 0, GRAPH_TOP, 127, GRAPH_ZERO)
            for (x0, y0), (x1, y1) in zip(v['graph'], v['graph'][1:]):
                p.uc.mem_write(SCRATCH + 0x7880, struct.pack('<4i', x0, y0, x1, y1))
                p.call(LINE | 1, ctx, SCRATCH + 0x7880, SCRATCH + 0x7888, count=20_000_000)
        if v['values'] is not None:
            self.fill(ctx, 0, 8, 127, 16)
            for k in range(3):
                self.text(ctx, COLUMNS[k], VALUE_Y, v['values'][k])
        if v['bottom'] is not None:
            self.fill(ctx, 12, 48, 115, 63)
            self.text(ctx, 64, NAME_Y, v['bottom'])
        return p.screen()


def go_to(m, n):
    """tap SHIFT until the page shows page n"""
    for _ in range(8):
        if m.ui()['page'] == n:
            return
        m.tap()


def pad_state(m, pad):
    return dict(b=m.ext(pad), a=m.get(0x7D, pad), h=m.get(0x7E, pad), r=m.get(0x7F, pad),
                loop=m.r32(record(pad) + R_LOOP), play=m.r32(record(pad) + R_PLAY))


def matches(m, screens, n, pad, count=4, extra=None):
    """the image's screen and static layer are the reference's for page n of pad (as the image has it now)"""
    st = pad_state(m, pad)
    v = screens.view(n, pad, st['b'], st['a'], st['h'], st['r'], st['loop'], st['play'], count, extra)
    return m.screen() == screens.draw(v, pad, st['a'], st['h'], st['r'], st['loop'], st['play'])


CONFIGS = [  # (what, settings bytes, A, H, R, LOOP, PLAY)
    ('stock settings', ext_bytes(), 20, 80, 40, 0, 0),
    ('FINE 5.4 ms / 466 ms, EXP / LOG / EXP, decay 100 ms to 40 %', ext_bytes(3, 32, 90, 0x19, 70, 40), 20, 80, 40,
     0, 0),
    ('curves only (stock times), EXP attack, LOG release', ext_bytes(0, 0, 0, 0x21), 60, 90, 70, 0, 0),
    ('LOOP-ONCE on a looping pad', ext_bytes(7, 64, 100, 0x05, 90, 50), 20, 80, 40, 1, 0),
    ('REV-TIME on a reverse pad', ext_bytes(9, 100, 40, 0x01), 20, 80, 40, 0, 1),
    ('FINE times overlapping on HOLD 10 %', ext_bytes(1, 120, 120, 0x30), 20, 10, 40, 0, 0),
    ('S curves, decay cut by the release', ext_bytes(3, 80, 100, 0x3F, 127, 20), 20, 60, 40, 0, 0),
    ('an unknown layout version', ext_bytes(0x0F, 40, 50, 0x3F, 60, 50, version=2), 20, 80, 40, 0, 0),
    ('a re-hit fade of 19 ms, the envelope stock', ext_bytes(rest=b'\x01\x30\x00'), 20, 80, 40, 0, 0),
]


def setup(mm, pad, b, a, h, r, loop, play):
    mm.set_ext(pad, b)
    for param, value in ((0x7D, a), (0x7E, h), (0x7F, r)):
        mm.set(param, value, pad)
    mm.w32(record(pad) + R_LOOP, loop)
    mm.w32(record(pad) + R_PLAY, play)


def ui_checks(img, parent, man, frames, curves):
    screens = Screens(Model(curves, frames), frames, parent)
    m, p = Machine(img, man['entries'], screen=True), Machine(parent, screen=True)
    for mm in (m, p):
        for pad in range(32):
            mm.load_pad(pad)
            mm.samples[pad] = SPAN
        setup(mm, 5, ext_bytes(), 20, 80, 40, 0, 0)
        mm.current_pad(5)
        mm.dispatch(EV_KEY, KEY_SHIFT)           # SHIFT + PITCH/SPEED opens the page; SHIFT is still down
        mm.open_page()
    e = man['entries']
    check(m.r32(m.page) == VTABLE and m.r32(VTABLE + 0xE4) == e['env_ui_knob'] and
          m.r32(VTABLE + 0xCC) == e['env_ui_draw'] and m.r32(VTABLE + 0xC8) == e['env_ui_pad'] and
          m.ui()['page'] == 0 and m.ui()['shift'] == 0 and m.r16(PAGE_TIMER) == m.r16(PAGE_TIMER + 2) == 50,
          'the ENVELOPE page made on entry has vtable 0x8021ec14 (knob, redraw and pad change are the module\'s) and '
          'arms the stock 50-tick page timer (+0x10 -> 0x800738a8) that drives its tick; it starts on page 1, and '
          'SHIFT, down since the opening chord, is not armed')
    check(m.screen() == p.screen() and m.screen()[0] != bytes(8192),
          'opened on a pad with stock settings: the screen and its static layer are the parent\'s, byte for byte')
    # page 1 with stock settings is stock
    seq = []
    for ctrl, raw in ((1, 40), (2, 64), (3, 100), (1, 0), (3, 127)):
        for mm in (m, p):
            mm.clear()
            mm.knob(ctrl, raw)
        seq.append((m.setters, m.ext(5), m.screen()) == (p.setters, p.ext(5), p.screen()) and
                   [m.get(x, 5) for x in (0x7D, 0x7E, 0x7F)] == [p.get(x, 5) for x in (0x7D, 0x7E, 0x7F)])
    check(all(seq), f'page 1, stock settings: the knobs are stock\'s (the same setter calls and values, no bytes) and '
                    f'the screen is the parent\'s after each turn ({seq})')
    # SHIFT taps: each page on the screen
    m.clear()
    m.tick(2)                            # SHIFT still down from the opening chord: never a tap
    for mm in (m, p):
        mm.dispatch(EV_KEY_UP, KEY_SHIFT)
    m.tick()
    first = m.ui()['page'] == 0 and m.ui()['shift'] == 1 and m.screen() == p.screen()
    pages = []
    for k in (1, 2, 3, 0):
        m.clear()
        m.tap()
        pages.append((m.ui()['page'], matches(m, screens, m.ui()['page'], 5)))
    check(first and pages == [(1, True), (2, True), (3, True), (0, True)] and m.screen() == p.screen(),
          f'SHIFT held when the page opens is no tap; each tap shows the next page on the screen, labels, values and '
          f'"A-6 SHAPE 2/4" at the bottom, then page 1 is the parent\'s screen again ({pages})')
    not_taps = []
    m.clear()
    m.dispatch(EV_KEY, KEY_SHIFT)
    m.tick()
    m.knob(1, 10)
    p.knob(1, 10)
    m.dispatch(EV_KEY_UP, KEY_SHIFT)
    m.tick()
    not_taps.append(m.ui()['page'])
    m.dispatch(EV_KEY, KEY_SHIFT)
    m.tick()
    m.dispatch(EV_KEY, KEY_COPY)
    m.tick()
    m.dispatch(EV_KEY_UP, KEY_COPY)
    m.dispatch(EV_KEY_UP, KEY_SHIFT)
    m.tick()
    not_taps.append(m.ui()['page'])
    m.tap(ticks_down=21)                 # 1.05 s
    not_taps.append(m.ui()['page'])
    m.dispatch(EV_KEY, KEY_SHIFT)
    m.tick()
    m.current_pad(6)
    m.tick()
    m.dispatch(EV_KEY_UP, KEY_SHIFT)
    m.tick()
    not_taps.append(m.ui()['page'])
    m.current_pad(5)
    m.tap(ticks_down=19)
    not_taps.append(m.ui()['page'])
    check(not_taps == [0, 0, 0, 0, 1], f'not a tap: SHIFT with a knob turned, with another key pressed and let go, '
                                       f'held over a second, with the pad changed; a 0.95 s press still is '
                                       f'({not_taps})')
    held = []
    m.dispatch(EV_KEY, KEY_COPY)         # held from before SHIFT until after it
    m.tick()
    m.tap()
    m.dispatch(EV_KEY_UP, KEY_COPY)
    m.tick()
    held.append(m.ui()['page'])
    m.uc.mem_write(KEYS + 8, b'\x01')    # a key bit set without its event, and never cleared
    m.tick()
    m.tap()
    held.append(m.ui()['page'])
    m.uc.mem_write(KEYS + 8, b'\x00')
    m.tick()
    check(held == [2, 3], f'still a tap: with a key held from before SHIFT until after it, and with a key bit that '
                          f'never changes ({held})')
    go_to(m, 0)

    # every page of every kind of settings, on the screen
    bad = []
    for what, b, a, h, r, loop, play in CONFIGS:
        setup(m, 5, b, a, h, r, loop, play)
        for n in (0, 1, 2, 3):
            go_to(m, n)
            m.draw()
            if not matches(m, screens, n, 5):
                bad.append((what, n))
    check(not bad, f'every page for {len(CONFIGS)} kinds of settings (stock; FINE, curves, decay and sustain; curves '
                   f'with stock times; LOOP-ONCE on a looping pad; REV-TIME on a reverse pad; overlapping times; a '
                   f'decay cut by the release; an unknown layout; a re-hit fade): the screen and static layer are the '
                   f'reference\'s, byte for byte: the page\'s labels and values, the pad\'s real envelope in the graph '
                   f'(stock\'s for stock settings), "A-6 DECAY 3/4" ({bad})')
    # a refresh (stock copies the static layer over the screen, then redraws) keeps each page
    setup(m, 5, *CONFIGS[1][1:])
    seq = []
    for n in (1, 2, 3, 0):
        go_to(m, n)
        m.refresh()
        seq.append(matches(m, screens, n, 5))
    check(all(seq), f'a refresh (event 4: the static layer copied over the screen, then the redraw) shows each page as '
                    f'it was: the labels are in the static layer too ({seq})')
    for mm in (m, p):
        setup(mm, 5, ext_bytes(), 20, 80, 40, 0, 0)
    go_to(m, 0)
    m.draw()
    p.draw()
    check(m.screen() == p.screen(), 'back on page 1 with stock settings: the parent\'s screen and layer again')

    # turning the knobs updates the screen (pages 2-4), every turn checked against the reference
    seq = []
    go_to(m, 2)
    for ctrl, raw in ((1, 50), (2, 64), (3, 70), (1, 0), (1, 90)):
        m.knob(ctrl, raw)
        seq.append(matches(m, screens, 2, 5))
    go_to(m, 1)
    for ctrl, raw in ((1, 40), (3, 127), (2, 100), (1, 100)):
        m.knob(ctrl, raw)
        seq.append(matches(m, screens, 1, 5))
    go_to(m, 3)
    fades = []
    for ctrl, raw in ((1, 100), (3, 90), (2, 30), (3, 10), (2, 0), (2, 48)):
        m.knob(ctrl, raw)
        seq.append(matches(m, screens, 3, 5))
        if ctrl == 2:
            fades.append(m.ext(5)[6:8])
    b = m.ext(5)
    check(all(seq) and b[0] & 3 == 3 and b[4] == 90 and b[5] == 50 and b[3] == (3 | 2 << 2 | 3 << 4) and
          b[0] & 12 == 4 and fades == [b'\x01\x1e', b'\x00\x00', b'\x01\x30'],
          f'pages 2-4: each turn writes its setting and the screen shows it at once; MODE CTRL 2 writes the re-hit '
          f'fade (bytes 0x6a 1, 0x6b the fine index; far left 0 0, CUT) ({seq}, {fades}, {b.hex()})')
    # page 1 with FINE: the times on the screen
    go_to(m, 0)
    seq, times = [], []
    for ctrl, raw in ((1, 1), (1, 8), (1, 32), (3, 64), (3, 80), (1, 112), (3, 127)):
        m.clear()
        m.knob(ctrl, raw)
        seq.append(matches(m, screens, 0, 5) and m.ext(5)[1 if ctrl == 1 else 2] == raw)
    for raw in range(128):
        m.clear()
        m.knob(3, raw)
        times.append([s for x, y, s in m.texts if (x, y) == (COLUMNS[2], VALUE_Y)][-1:])
    check(all(seq) and times == [[time_text(f)] for f in frames],
          f'page 1 with FINE: the screen shows the times (0.5ms .. 8.00s; the graph follows), every fine index drawn '
          f'as its time ({seq})')
    # a pad change redraws (stock reads the new pad's START/END first)
    go_to(m, 1)
    setup(m, 7, ext_bytes(3, 16, 64, 0x2A, 40, 70), 30, 50, 60, 0, 0)
    m.samples[7] = SPAN
    m.clear()
    m.current_pad(7)
    m.call(m.r32(m.r32(m.page) + 0xC8), m.page, count=50_000_000)
    check(matches(m, screens, 1, 7) and m.r32(m.page + 0x1A78) == 7,
          'a pad change on page 2: stock reads the new pad, then the screen shows its settings and envelope')
    m.current_pad(5)
    m.call(m.r32(m.r32(m.page) + 0xC8), m.page, count=50_000_000)
    # the knobs on the effect: stock draws nothing, nor do we
    before = m.screen()
    m.fx_knobs = 1
    m.clear()
    m.draw()
    for ctrl in (1, 2, 3):
        m.knob(ctrl, 77)
    fx = (m.screen() == before, len(m.stock_knobs), m.ext(5))
    m.fx_knobs = 0
    check(fx[0] and fx[1] == 3, f'while the knobs drive the effect: no drawing, every knob to stock\'s handler '
                                f'({fx[:2]})')
    # more pages: a later stage's page after MODE
    page_at = SCRATCH + 0x7A00
    strs = SCRATCH + 0x7B00
    m.uc.mem_write(SCRATCH + 0x40, bytes.fromhex('5623' '1370' '3031' '5170' '0023' '9370' '7047'))  # "V" + ctrl
    m.uc.mem_write(SCRATCH + 0x60, bytes.fromhex('7047' '7047'))                                       # turn, graph
    turns, graphs = [], []
    m.uc.hook_add(UC_HOOK_CODE, lambda u, a, s, d: turns.append(m.regs(3)), None, begin=SCRATCH + 0x60,
                  end=SCRATCH + 0x60)
    m.uc.hook_add(UC_HOOK_CODE, lambda u, a, s, d: graphs.append(m.regs(4)), None, begin=SCRATCH + 0x62,
                  end=SCRATCH + 0x62)
    names = [b'TEST\0', b'C1:ONE\0', b'C2:TWO\0', b'C3:THREE\0']
    ptrs = []
    for k, s in enumerate(names):
        m.uc.mem_write(strs + 16 * k, s)
        ptrs.append(strs + 16 * k)
    m.uc.mem_write(page_at, struct.pack('<7I', *ptrs, SCRATCH + 0x41, SCRATCH + 0x61, SCRATCH + 0x63))
    go_to(m, 0)
    m.w32(e['env_more_pages'] + 4, page_at)
    extra = dict(name='TEST', labels=['C1:ONE', 'C2:TWO', 'C3:THREE'], values=['V1', 'V2', 'V3'])
    seq = []
    for n in (1, 2, 3, 4, 0):
        m.tap()
        seq.append((m.ui()['page'], matches(m, screens, n, 5, count=5, extra=extra if n == 4 else None)))
    go_to(m, 4)
    m.knob(2, 55)
    seq.append(turns[-1:] == [(5, 2, 55)] and graphs and graphs[-1][1:] == (5, SPAN[0], SPAN[1]))
    m.w32(e['env_more_pages'] + 4, 0)
    m.draw()
    seq.append(m.ui()['page'] == 4 and matches(m, screens, 0, 5))
    check(seq == [(1, True), (2, True), (3, True), (4, True), (0, True), True, True],
          f'a later stage\'s page in env_more_pages: the taps reach it after MODE ("A-6 TEST 5/5", its labels and '
          f'values, its own graph called with the pad and START/END, its turn called), the others show "n/5"; '
          f'taken away again, the page shown falls back to stock\'s ({seq})')
    m.tap()
    go_to(m, 0)

    # save: once, 1 s after the last change; and when the page closes
    m.clear()
    saves = m.ui()['saves']
    m.knob(1, 33)
    m.tick(19)
    early = list(m.posts)
    m.tick(1)
    once = list(m.posts)
    m.tick(40)
    check(not early and once == [(0xD, 1, 0, once[0][3])] and m.posts == once and m.ui()['saves'] == saves + 1,
          f'command 0xD (1, 0) goes out once, 1 s (20 ticks of 50 ms) after the last change ({early}, {m.posts})')
    m.clear()
    m.knob(1, 34)
    m.tick(3)
    m.tap()
    m.leave()
    p.clear()
    p.leave()
    stock_posts = [x[:3] for x in p.posts]
    check([x[:3] for x in m.posts] == [(0xD, 1, 0)] + stock_posts and m.ui()['page'] == 0 and
          m.ui()['shift'] == 0 and m.ui()['labels'] == 0 and m.ui()['bottom'] == 0,
          f'closing the page with a change not yet saved posts 0xD, then what stock posts on leaving '
          f'{stock_posts}; the next opening starts on page 1 with stock\'s labels ({m.posts})')
    for mm in (m, p):
        mm.clear()
        mm.open_page()
    posts = [x[:3] for x in m.posts] == [x[:3] for x in p.posts]
    check(posts and m.screen() != p.screen() and matches(m, screens, 0, 5),
          'opened again on page 1: what stock posts, and page 1 with the pad\'s FINE times and envelope (its settings '
          'changed)')
    for mm in (m, p):
        mm.clear()
        mm.leave()
    check([x[:3] for x in m.posts] == [x[:3] for x in p.posts], 'closing without a change posts only what stock does')

    # COPY / REMAIN: mute group and bank, protected banks skipped
    m.open_page()
    for pad in range(32):
        m.set_ext(pad, ext_bytes())
    for pad, group in ((5, 2), (7, 2), (12, 2), (18, 2), (3, 1), (21, 0)):
        m.set(0x6D, group, pad)
    m.protected = {1}
    m.tap()
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 1))
    m.knob(1, 40)                        # page 2: attack curve EXP to the mute group
    group = [pad for pad in range(32) if m.ext(pad)[3] & 3 == 1]
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 2))
    m.unload_pad(9)
    m.knob(3, 64)                        # release curve LOG to the bank (pad 9 holds no sample)
    m.load_pad(9)
    bank = [pad for pad in range(32) if m.ext(pad)[3] >> 4 & 3 == 2]
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 0))
    m.current_pad(20)
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 2))
    m.knob(3, 127)
    protected = [pad for pad in range(32) if m.ext(pad)[3] >> 4 & 3 == 3]
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 0))
    check(group == [5, 7, 12] and bank == [pad for pad in range(16) if pad != 9] and protected == [20],
          f'COPY held: the pad\'s mute group (2: pads 5, 7, 12; pad 18 is in protected bank B); REMAIN held: its bank '
          f'but pad 9, which holds no sample; in a protected bank only the current pad ({group}, {bank}, {protected})')
    m.current_pad(5)
    # FINE through COPY on page 1: FINE pads of the group get the index, others only the stock value
    m.set_ext(5, ext_bytes(1, 20, 20))
    m.set_ext(7, ext_bytes(1, 20, 20))
    m.set_ext(12, ext_bytes())
    go_to(m, 0)
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 1))
    m.clear()
    m.knob(1, 70)
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 0))
    nearest = min(range(128), key=lambda v: (abs(stock_frames(v) - frames[70]), v))
    check(m.ext(5)[1] == 70 and m.ext(7)[1] == 70 and m.ext(12) == ext_bytes() and m.get(0x7D, 5) == nearest and
          sorted(a[1:4] for a in m.applied) == [(0x7D, nearest, 7), (0x7D, nearest, 12)] and
          {f[1] for f in m.fanouts} == {5, 7},
          f'page 1 FINE with COPY held: the group\'s FINE pads (5, 7) take the index and their voices are recomputed; '
          f'pad 5 gets the nearest stock value {nearest} and stock\'s apply sends it to 7 and 12 ({m.applied})')
    # a pad without a sample: pages 2-4 write nothing, page 1 is stock's
    m.unload_pad(5)
    m.set_ext(5, ext_bytes(1, 20, 20))
    m.clear()
    for k in range(4):
        m.knob(1, 99)
        m.knob(3, 99)
        m.tap()
    check(m.ext(5) == ext_bytes(1, 20, 20) and len(m.stock_knobs) == 2 and not m.fanouts,
          'a pad holding no sample: pages 2-4 write nothing; page 1 goes to stock\'s knob even with FINE set')
    m.load_pad(5)
    texts = [t for _, _, t in m.texts] + [x for row in PAGE_LABELS for x in row] + ['A-16 SHAPE 2/4', 'J-16 MODE 4/4']
    mine = [t for t, lr in m.popup_log if man['blob_base'] <= lr < man['blob_base'] + man['blob_size']]
    stock = sorted({t for t, lr in m.popup_log})
    check(not mine and stock == ['to Current PAD', 'to MUTE GROUP'] and
          all(len(t) <= 10 for row in PAGE_LABELS for t in row) and all(len(t) <= 16 and t.isascii() for t in texts),
          f'the module shows no popups (only stock\'s own COPY ones: {stock}); every label is at most 10 characters, '
          f'every value and bottom line at most 16')
    reset_checks(m, p, screens, man)


def all_bytes(mm, pad):
    """bytes 0x64-0x7F of the pad's extended block"""
    return bytes(mm.uc.mem_read(EXT + pad * 0x80 + 0x64, 0x1C))


def full_settings(pad):
    """envelope settings in every byte 0x64-0x7F (0x70, note repeat's, too)"""
    return ext_bytes(3, 32, 90, 0x19, 70, 40, rest=b'\x01\x30\x00') + bytes((pad + 0x41 + i) & 0x7F | 1 for i in range(16))


def press(mm, key):
    """a key pressed and let go: the key-down event, then its held bit cleared (the key-up path of DEL and
    the pads waits on the panel's serial port, which this machine does not have)"""
    mm.dispatch(EV_KEY, key)
    b = mm.uc.mem_read(KEYS + (key >> 3), 1)[0]
    mm.uc.mem_write(KEYS + (key >> 3), bytes([b & ~(1 << (key & 7)) & 0xFF]))


def reset_checks(m, p, screens, man):
    """DEL on the ENVELOPE page: the pad's envelope settings back to stock, after VALUE"""
    def asked(n, pad, text):
        st = pad_state(m, pad)
        v = screens.view(n, pad, st['b'], st['a'], st['h'], st['r'], st['loop'], st['play'])
        v['bottom'] = text
        return m.screen() == screens.draw(v, pad, st['a'], st['h'], st['r'], st['loop'], st['play'])

    def is_reset(pad, before):
        now = all_bytes(m, pad)
        return now[:12] == bytes(12) and now[12] == before[12] and now[13:] == bytes(15)

    m.protected = set()
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 0))
    m.current_pad(5)
    m.load_pad(5)
    # stock's page does nothing with DEL
    p.open_page()
    p.current_pad(5)
    p.draw()
    p.clear()
    before = p.screen()
    press(p, KEY_DEL)
    check(p.screen() == before and not p.posts and not p.setters and not p.popups and not p.fanouts,
          'stock\'s ENVELOPE page: DEL does nothing (its key handler 0x800f5ad8 returns 1 for key 0x1a)')
    # DEL asks, VALUE resets
    go_to(m, 1)
    m.uc.mem_write(EXT + 5 * 0x80 + 0x64, full_settings(5))
    b5 = all_bytes(m, 5)
    m.draw()
    m.clear()
    edge = m.screen()[0]
    press(m, KEY_DEL)
    q = 'RESET A-6? press VALUE'
    after = m.screen()[0]
    outside = all(edge[y * 128 + x] == after[y * 128 + x] for y in range(48, 64) for x in list(range(12)) + list(range(116, 128)))
    check(m.ui()['asking'] == 1 and all_bytes(m, 5) == b5 and asked(1, 5, q) and outside and not m.fanouts and
          not m.setters and not m.posts and not m.popups and (64, NAME_Y, q) in m.texts,
          f'DEL on page 2: "{q}" in the bottom line (inside x 12-115: the S and E marks stay), nothing written yet')
    m.clear()
    saves = m.ui()['saves']
    press(m, KEY_VALUE)
    reset_now = is_reset(5, b5)
    m.tick(20)
    check(reset_now and m.ui()['asking'] == 0 and {f[1] for f in m.fanouts} == {5} and matches(m, screens, 1, 5) and
          [x[:3] for x in m.posts] == [(0xD, 1, 0)] and m.ui()['saves'] == saves + 1,
          f'VALUE: bytes 0x64-0x6F and 0x71-0x7F of the pad are 0 (0x70, note repeat\'s, stays {all_bytes(m, 5)[12]:#x}), '
          f'its voices recompute, the page shows stock settings, and the save goes out 1 s later ({all_bytes(m, 5).hex()})')
    # cancelled: EXIT (stays on the page), a knob, a pad change, another key
    seq = []
    m.uc.mem_write(EXT + 5 * 0x80 + 0x64, full_settings(5))
    m.draw()
    req = m.r16(PAGE_REQUEST)
    press(m, KEY_DEL)
    m.clear()
    press(m, KEY_EXIT)
    seq.append(('EXIT', m.ui()['asking'] == 0 and all_bytes(m, 5) == b5 and m.r16(PAGE_REQUEST) == req and
                m.r32(PAGE_PTR) == m.page and matches(m, screens, 1, 5) and not m.posts))
    press(m, KEY_DEL)
    m.knob(1, 64)                        # page 2 CTRL 1: attack curve LOG
    seq.append(('knob', m.ui()['asking'] == 0 and all_bytes(m, 5) == b5[:3] + bytes([b5[3] & ~3 | 2]) + b5[4:] and
                matches(m, screens, 1, 5)))
    m.uc.mem_write(EXT + 5 * 0x80 + 0x64, full_settings(5))
    m.draw()
    press(m, KEY_DEL)
    m.load_pad(7)
    m.samples[7] = SPAN
    m.current_pad(7)
    m.call(m.r32(m.r32(m.page) + 0xC8), m.page, count=50_000_000)
    seq.append(('pad change', m.ui()['asking'] == 0 and all_bytes(m, 5) == b5 and matches(m, screens, 1, 7)))
    m.current_pad(5)
    m.call(m.r32(m.r32(m.page) + 0xC8), m.page, count=50_000_000)
    press(m, KEY_DEL)
    m.clear()
    m.dispatch(EV_KEY, KEY_COPY)
    asked_after = m.ui()['asking']
    m.dispatch(EV_KEY_UP, KEY_COPY)
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 0))
    seq.append(('COPY', asked_after == 0 and all_bytes(m, 5) == b5 and
                [t for t, _ in m.popups] == ['to MUTE GROUP', 'to Current PAD']))
    m.draw()
    press(m, KEY_DEL)
    press(m, KEY_DEL)
    seq.append(('DEL again', m.ui()['asking'] == 0 and all_bytes(m, 5) == b5 and matches(m, screens, 1, 5)))
    check(all(ok for _, ok in seq), f'cancelled, nothing written: EXIT (the page stays, no page change), a knob (which '
                                    f'then turns), a pad change, another key (COPY, which then does its stock '
                                    f'thing), DEL again ({seq})')
    # not asked: SHIFT held, an empty pad
    m.dispatch(EV_KEY, KEY_SHIFT)
    press(m, KEY_DEL)
    shift_held = m.ui()['asking']
    m.dispatch(EV_KEY_UP, KEY_SHIFT)
    m.tick()
    page_after = m.ui()['page']
    m.unload_pad(5)
    press(m, KEY_DEL)
    empty = m.ui()['asking']
    m.load_pad(5)
    check(shift_held == 0 and page_after == 1 and empty == 0 and all_bytes(m, 5) == b5,
          'DEL with SHIFT held goes to stock (and makes that SHIFT press no tap); on a pad without a sample, nothing')
    # COPY held: the mute group; REMAIN held: the bank
    for pad, group in ((5, 2), (7, 2), (12, 2), (18, 2), (3, 1), (21, 0)):
        m.load_pad(pad)
        m.set(0x6D, group, pad)
    pads = (3, 5, 7, 9, 12, 18, 21)
    for pad in pads:
        m.uc.mem_write(EXT + pad * 0x80 + 0x64, full_settings(pad))
    want = {pad: all_bytes(m, pad) for pad in pads}
    m.protected = {1}
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 1))
    m.clear()
    press(m, KEY_DEL)
    q_group = asked(1, 5, 'RESET GROUP? press VALUE')
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 0))         # COPY let go before VALUE
    press(m, KEY_VALUE)
    group = [pad for pad in pads if is_reset(pad, want[pad])]
    kept = [pad for pad in pads if all_bytes(m, pad) == want[pad]]
    check(q_group and group == [5, 7, 12] and kept == [3, 9, 18, 21] and {f[1] for f in m.fanouts} == {5, 7, 12},
          f'COPY held at DEL: "RESET GROUP? press VALUE", and VALUE resets the mute group (2: pads 5, 7, 12; pad 18 '
          f'is in protected bank B), the mode taken at DEL ({group}, kept {kept})')
    for pad in pads:
        m.uc.mem_write(EXT + pad * 0x80 + 0x64, full_settings(pad))
    m.unload_pad(9)
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 2))
    m.clear()
    press(m, KEY_DEL)
    q_bank = asked(1, 5, 'RESET BANK A? press VALUE')
    press(m, KEY_VALUE)
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 0))
    m.load_pad(9)
    bank = [pad for pad in pads if is_reset(pad, want[pad])]
    kept = [pad for pad in pads if all_bytes(m, pad) == want[pad]]
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 1))
    m.set(0x6D, 0, 5)
    press(m, KEY_DEL)
    no_group = m.ui()['asking']
    press(m, KEY_EXIT)
    m.uc.mem_write(APPLY_MODE, struct.pack('<i', 0))
    m.set(0x6D, 2, 5)
    check(q_bank and bank == [3, 5, 7, 12] and kept == [9, 18, 21] and no_group == 1,
          f'REMAIN held: "RESET BANK A? press VALUE", and VALUE resets bank A but pad 9, which holds no sample; COPY '
          f'held on a pad in no mute group asks for the pad alone ({bank}, kept {kept})')
    # page 1 (stock's screen)
    m.protected = set()
    go_to(m, 0)
    m.set_ext(5, ext_bytes())
    m.draw()
    press(m, KEY_DEL)
    q1 = asked(0, 5, 'RESET A-6? press VALUE')
    press(m, KEY_EXIT)
    check(q1 and matches(m, screens, 0, 5),
          'page 1 (stock\'s screen): DEL asks in the bottom line; EXIT gives stock\'s screen back')
    # the question's width: every pad name, group and bank
    widths = []
    for text in ['RESET J-16? press VALUE', 'RESET GROUP? press VALUE', 'RESET BANK J? press VALUE']:
        p.uc.mem_write(SCREEN_PIX, bytes(8192))
        ctx = p.r32(p.page + 0x34)
        p.uc.mem_write(SCRATCH + 0x7840, text.encode() + b'\0')
        p.call(FONT | 1, ctx, FONT_ID)
        p.call(TEXT | 1, ctx, 64, NAME_Y, SCRATCH + 0x7840, count=20_000_000)
        pix = bytes(p.uc.mem_read(SCREEN_PIX, 8192))
        xs = [x for y in range(48, 64) for x in range(128) if pix[y * 128 + x]]
        widths.append((min(xs), max(xs)))
    p.leave()
    check(all(12 <= a and b <= 115 for a, b in widths),
          f'the longest questions stay inside the bottom line\'s box (x 12-115) ({widths})')
    # stock's INIT PARAM (SHIFT + pad 6, then OK) on the parent: command 0x40a; its handler clears 0x40-0x7F
    q = Machine(m_parent_img(man), arm_max=True)
    q.load_pad(5)
    blk = EXT + 5 * 0x80
    q.uc.mem_write(blk, bytes(range(0x80, 0x100)))
    q.call(INIT_PARAM_OK | 1, 5, count=50_000_000)
    posted = [x[:3] for x in q.posts]
    q.call(INIT_PARAM | 1, CSMPLPRM, 5, count=50_000_000)
    after = bytes(q.uc.mem_read(blk, 0x80))
    case = struct.unpack('<H', bytes(q.uc.mem_read(CMD_DISPATCH + 0x22 + 2 * 0x40A, 2)))[0] * 2 + CMD_DISPATCH + 0x22
    chain = (bl_target(q, case + 10), bl_target(q, 0x8018523C))
    check(posted == [(0x40A, 5, 0)] and after[:0x40] == bytes(range(0x80, 0xC0)) and after[0x40:] == bytes(0x40) and
          case == 0x8004F848 and chain == (0x80185208, INIT_PARAM),
          f'stock\'s INIT PARAM (its OK 0x80051db8 posts command 0x40a; the command task\'s case 0x8004f848 -> '
          f'0x80185208 -> 0x8018c220) clears bytes 0x40-0x7F of the pad\'s extended block: these settings, note '
          f'repeat\'s 0x70 and the pad FX bytes; 0x00-0x3F stay ({posted}, {after[0x3C:0x48].hex()})')


def m_parent_img(man):
    return Path(man['parent_app1']).read_bytes()


def bl_target(mm, at):
    """where the BL at `at` goes"""
    h1, h2 = struct.unpack('<HH', bytes(mm.uc.mem_read(at, 4)))
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xD000) != 0xD000:
        return None
    sgn, j1, j2 = h1 >> 10 & 1, h2 >> 13 & 1, h2 >> 11 & 1
    off = sgn << 24 | (~(j1 ^ sgn) & 1) << 23 | (~(j2 ^ sgn) & 1) << 22 | (h1 & 0x3FF) << 12 | (h2 & 0x7FF) << 1
    return at + 4 + off - (sgn << 25)


def main():
    out = Path(sys.argv[1]).resolve()
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    parent = Path(man['parent_app1']).read_bytes()
    check(sha(parent) == man['parent_sha256'], 'the parent APP1 is the manifest\'s')
    frames, curves = static_checks(out, man, img, parent)
    neutral_checks(img, parent, man, n)
    shaped_checks(img, man, frames, curves, n)
    note_off_checks(img, parent, man, frames)
    retrig_checks(img, parent, man, frames)
    dispatcher_checks(img, parent, man)
    ui_checks(img, parent, man, frames, curves)
    print(f'\n{cases[0] - len(fails)}/{cases[0]} checks pass')
    if fails:
        print('FAILED:')
        for f in fails:
            print('  ' + f[:300])
        sys.exit(1)


if __name__ == '__main__':
    main()
