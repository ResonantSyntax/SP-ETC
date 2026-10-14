"""Checks for bounce in place, stage 2 (build_bounce.py).

usage: python synth/test_bounce.py OUT_DIR      (unicorn and keystone on PYTHONPATH)

Reads OUT_DIR/manifest.json for the parent APP1. Static image checks first. Then the built image
is booted in Unicorn the way its scatter loader does it, and the stock code runs for real: the
recorder feed behind the RX bridge, the pad parameter getter and setter, the pad name, the popup
function and the page's vtable. Modelled: SMPL TASK (the recorder commands, standby, REC_START, the
finalize and cancel, ALL SOUND OFF), the source pad's voice (it renders the pad's PCM into the
stems from the first block after its trigger), the effects chip (RX = the record mix L frames
later, optionally with gain, an echo or noise), the eDMA positions, the recorder engine's writer
(it keeps the frames it is given: the take), and the settings, project and system parameter
stores. No screen, no SD card, no real timing: those need the unit.

Checks:
- static: only the header, the four sites and the appended tail differ from the parent; the rows;
  the guards hold on the parent;
- bridges against the parent's own instructions (mixer arguments and stack depth, the feed's
  capture, meter and gate call, the popup tick's registers);
- the page filter: every event reaches DOOM OS's filter unless it is the gesture, or a bounce is
  set up or running; the gesture's conditions; the setup popup and VALUE;
- whole runs through the bridges (NO TAIL, TAIL, LOOP; one-shots and loops; at their own rate and
  not; sharp and soft starts; D = -1, 0, +1; an extra frame of latency; the boot's calibration):
  the take holds exactly the RX frames from T0 through the window, START and END land on the
  window, the take is the source's own frames when the effect is dry, the environment comes back;
- refusals, EXIT at every phase and failures: nothing changes, everything pinned comes back.
"""
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_HOOK_CODE  # noqa: E402
from unicorn import arm_const as ar  # noqa: E402

FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
TX_SITE, TX_BACK, RX_SITE, LOOP_HEAD = 0x1D090, 0x1D09A, 0x1D0C2, 0x1D05C
UI_SITE, UI_REST = 0x8006B950, 0x8006B95C
MIXER, FEED, GATE = 0x1C2D0, 0x1CA80, 0x1BAA4
VTABLE_SLOT = 0x80223474
STEMS, CAPTURE, SLOTS = 0x202AD3A0, 0x202AD0A0, 0x202AE1A0
TX3, RXBUF, TCD3_SADDR, TCD4_DADDR = 0x20006000, 0x20008000, 0x400E9060, 0x400E9090
REC = 0x82E0E71C
REC_STATE, REC_ENGINE = REC + 0x39, REC + 0x254
FEED_ON = 0x805917C4
POPUP_STATE, POPUP_TEXT, POPUP_TIMER = 0x8024589C, 0x802468D8, 0x805922B4
KEYS, PAGE_ID = 0x80592448, 0x80245880
SEQ_PLAY, SEQ_RUN, LOOPER_ON = 0x82E0D660 + 0xA5, 0x82DFFC88 + 0x2C0, 0x82E0B71C + 0x39
TARGET_VALUES = 0x80246E14
SMPL, FILE_INFO = 0x82E2CD08, 0x82E495E4
PADGET, PADSET, PADINIT, PADNAME = 0x800DC6B8, 0x800DA720, 0x800CFA68, 0x800CFA28
STACK, AUDIO_SP, RET = 0x30010000, 0x300F0000, 0x3001F000
PAGE_OBJ, EVENT = 0x30090000, 0x30091000
ENGINE, ENGINE_VT, WRITER = 0x30080000, 0x30081000, 0x30082000
VOICES, STREAMS = 0x31000000, 0x31400000
TEXT = 0x30092000
STUBS = {
    0x800E25C0: 'post', 0x800D48E8: 'target', 0x800CDBD0: 'trigger', 0x6031C8F8: 'doom',
    0x800D94D8: 'get', 0x800DD0C0: 'set', 0x800DDA38: 'pget', 0x800DED18: 'pset', 0x800DA010: 'sysget',
    0x800CE420: 'modal', 0x101BA: 'zero', 0x1BB6A: 'nop', 0x1D634: 'nop', GATE: 'gate', WRITER: 'writer',
    0x800D8B90: 'nop',               # the project's change broadcast (its listeners are not built here)
}
KEY_REC, KEY_RESAMPLE, KEY_EXIT, KEY_SHIFT = 0x1B, 0x1C, 0x22, 0x2A
EV_KEY, EV_KEY_UP, EV_ENCODER, EV_KNOB, EV_PAD, EV_PAD_UP = 5, 6, 7, 9, 0x10, 0x11
FIELDS_A = ('tx_blocks rx_blocks phase quiet_rx quiet_tx pad mode skip measure armed_voices slot voice t0 f0 fed '
            'stop have_l cached l l_est l_meas p_n p0 p_sum p16 d tx_onset scan last_nz voice_end last_loud win '
            'rx_now fail').split()
FIELDS_U = ('state ms since shown refresh src dst mode modes loop_src loop_pin len1 len2 native saved_len saved_snap '
            'saved_bpm pinned msg waits last_mode cal_l cal_valid runs r_l r_est r_meas r_p16 r_d r_start r_end r_len '
            'r_mode r_exact').split()
SIGNED = {'l', 'l_est', 'l_meas', 'p0', 'p_sum', 'p16', 'd', 'saved_len', 'saved_snap', 'saved_bpm', 'cal_l', 'r_l',
          'r_est', 'r_meas', 'r_p16', 'r_d'}
U_IDLE, U_SETUP, U_STANDBY, U_SILENCE, U_RECSTART, U_VOICE, U_RUN, U_FINAL, U_CANCEL = range(9)
NO_TAIL, TAIL, LOOP = range(3)
fails = []
cases = [0]


def check(cond, what):
    cases[0] += 1
    if not cond:
        print('FAIL ' + what)
        fails.append(what)
    return cond


def note(what):
    print('PASS ' + what)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def scatter(img):
    a, b = struct.unpack_from('<2I', img, 0x80)
    return [list(struct.unpack_from('<4I', img, i)) for i in range(a + 0x80, b + 0x80, 16)]


def file_offset(img, addr, size):
    for load, dst, n, fn in scatter(img):
        if fn == COPY and load and dst <= addr and addr + size <= dst + n:
            return load - FLASH + addr - dst
    raise ValueError(hex(addr))


def decompress(src, size):
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


def s16(v):
    return max(-32768, min(32767, int(v)))


class Voice:
    """The source pad's voice: renders the pad's PCM (stereo, 16-bit) into DRY stems from its first block."""

    def __init__(self, m, pad, pcm, start, end, lp, delay):
        self.m, self.pad, self.pcm, self.start, self.end, self.lp = m, pad, pcm, start, end, lp
        self.delay, self.slot, self.pos, self.block = delay, 7, start, None
        self.loop = False
        self.trigger_block = None
        self.active = False

    def trigger(self, n):
        """The pad's LOOP as it stands at the trigger (the run may have changed it)."""
        self.trigger_block = n
        self.loop = self.m.r32(SMPL + self.pad * 0xAC + 0xE4) != 0

    def tick(self, n):
        """Stems for TX block n (list of 64 (l, r)), and the slot's state after the renderer."""
        m = self.m
        if self.block is None and self.trigger_block is not None and n >= self.trigger_block + self.delay:
            self.block = n
            self.active = True
            m.slot_voice(self.slot, self.pad, True)
        out = [(0, 0)] * 64
        if not self.active:
            return out
        for f in range(64):
            if self.pos >= self.end:
                if self.loop:
                    self.pos = self.lp
                else:
                    break
            out[f] = self.pcm[self.pos]
            self.pos += 1
        if self.pos >= self.end and not self.loop:
            self.active = False
            m.slot_voice(self.slot, self.pad, False)
        return out

    def stop(self):
        if self.active:
            self.active = False
            self.m.slot_voice(self.slot, self.pad, False)


class Machine:
    def __init__(self, img, man=None):
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for base, size in ((0x0, 0x20000), (0x20000000, 0x80000), (0x20200000, 0x100000), (0x80000000, 0x4000000),
                           (0x30000000, 0x100000), (0x31000000, 0x800000), (0x60000000, 0x400000),
                           (0x400E8000, 0x2000)):
            uc.mem_map(base, size, UC_PROT_ALL)
        uc.mem_write(FLASH, img)
        for load, dst, size, handler in scatter(img):
            if handler == COPY:
                uc.mem_write(dst, img[load - FLASH:load - FLASH + size])
            elif handler == DECOMPRESS:
                uc.mem_write(dst, decompress(img[load - FLASH:], size))
        uc.reg_write(ar.UC_ARM_REG_C1_C0_2, uc.reg_read(ar.UC_ARM_REG_C1_C0_2) | (0xF << 20))
        uc.reg_write(ar.UC_ARM_REG_FPEXC, 0x40000000)
        uc.mem_write(RET, b'\x00\xbf\x00\xbf')
        self.sym = man['entries'] if man else {}
        self.log, self.queue, self.take = [], [], []
        self.settings = {0x36: 1, 0x24: 3, 0x59: 0, 0x1B: 12000, 0x1A: -1}
        self.project = {0: 0, 0xBF: 0, 0xDD: 0, 0xFB: 0}
        self.status = [0] * 160
        self.routing = 0
        self.modal = 0
        self.dest = None
        self.final_due = None
        self.voice = None
        self.trigger_ignored = False
        self.fx = dict(L=77, gain=1.0, echo=None, noise=0)
        self.tx_mix = {}
        self.tx_n = self.rx_n = 0
        self.gate_calls = []
        self.post_times = []
        self.mixer_calls = []
        self.finalized = []
        self.saves = 0
        self.texts = []
        self.ui_ms = 0
        for addr, name in STUBS.items():
            uc.hook_add(UC_HOOK_CODE, self._stub, name, begin=addr, end=addr)
        uc.hook_add(UC_HOOK_CODE, self._mixer, None, begin=MIXER, end=MIXER)
        uc.hook_add(UC_HOOK_CODE, self._popup, None, begin=0x800D3FF0, end=0x800D3FF0)
        uc.mem_write(POPUP_STATE, b'\x01')
        self.w32(FEED_ON, 1)
        self.w32(0x82E011A8, 0)                        # settings 0x27 = 0: RX pair 0
        self.w32(REC_ENGINE, ENGINE)
        self.w32(ENGINE, ENGINE_VT)
        self.w32(ENGINE_VT + 0x2C, WRITER | 1)
        uc.mem_write(WRITER, b'\x70\x47')
        self.w32(TARGET_VALUES + 0xC, 1)                # stereo
        self.w32(TARGET_VALUES + 4, 0xFFFFFFFF)
        uc.mem_write(PAGE_ID, struct.pack('<H', 0x0E))
        for slot in range(32):                          # the slots always hold voice objects; all idle
            voice = VOICES + slot * 0x18000
            self.w32(SLOTS + slot * 0x58, voice)
            self.w32(voice + 0x14268, 0)
        self.rng = random.Random(0)
        self.dma(61)
        self.keys = set()

    # ---- plumbing ----
    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack('<I', self.uc.mem_read(a, 4))[0]

    def r8(self, a):
        return self.uc.mem_read(a, 1)[0]

    def regs(self, n=4):
        return [self.uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}')) for k in range(n)]

    def _ret(self, value=0):
        self.uc.reg_write(ar.UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.uc.reg_write(ar.UC_ARM_REG_PC, self.uc.reg_read(ar.UC_ARM_REG_LR))

    def _stub(self, uc, address, size, name):
        r0, r1, r2, r3 = self.regs()
        sr = [struct.unpack('<i', struct.pack('<I', x))[0] for x in (r0, r1, r2, r3)]
        value = 0
        if name == 'post':
            self.queue.append(('cmd', r0, sr[1], sr[2]))
            self.log.append(('post', r0))
            self.post_times.append((self.ui_ms, r0))
        elif name == 'target':
            self.queue.append(('target', r1, sr[2]))
            self.log.append(('target', r1, sr[2]))
        elif name == 'trigger':
            self.log.append(('trigger', r0, r1, r2))
            if self.voice and not self.trigger_ignored and r1:
                self.voice.trigger(self.tx_n)
        elif name == 'doom':
            self.log.append(('doom', struct.unpack('<h', bytes(uc.mem_read(r1, 2)))[0]))
            value = 0x55
        elif name == 'get':
            value = self.settings.get(r1, 0)
        elif name == 'set':
            self.settings[r1] = sr[2]
            self.log.append(('set', r1, sr[2], sr[3]))
        elif name == 'pget':
            if r1 == 0x64:
                value = self.status[sr[2]] if 0 <= sr[2] < 160 else 0
            elif 0x21 <= r1 < 0x21 + 10:
                value = 9000 + 100 * (r1 - 0x21)
            else:
                value = self.project.get(r1, 0)
        elif name == 'pset':
            self.project[r1] = sr[2]
            self.log.append(('pset', r1, sr[2]))
        elif name == 'sysget':
            value = self.routing if r1 == 0x5C else 0
        elif name == 'modal':
            value = self.modal
        elif name == 'zero':
            value = 0
        elif name == 'gate':
            self.gate_calls.append((self.r8(REC_STATE), r0, r1, r2))
        elif name == 'writer':
            data = bytes(uc.mem_read(r1, 4 * r2))
            self.take += [struct.unpack_from('<2h', data, 4 * i) for i in range(r2)]
            frames = struct.unpack('<Q', bytes(uc.mem_read(ENGINE + 0x200, 8)))[0] + r2
            uc.mem_write(ENGINE + 0x200, struct.pack('<Q', frames))
        self._ret(value)

    def _mixer(self, uc, address, size, _):
        """The stub mixer: this block's stems from the voice model (DRY, 20-bit = 16-bit << 4)."""
        self.mixer_calls.append([uc.reg_read(ar.UC_ARM_REG_R0), uc.reg_read(ar.UC_ARM_REG_R1),
                                 uc.reg_read(ar.UC_ARM_REG_SP)])
        n = self.tx_n
        frames = self.voice.tick(n) if self.voice else [(0, 0)] * 64
        buf = bytearray(64 * 14 * 4)
        for f, (l, r) in enumerate(frames):
            struct.pack_into('<2i', buf, f * 56, l << 4, r << 4)
            self.tx_mix[64 * n + f] = (l, r)
        uc.mem_write(STEMS, bytes(buf))
        self._ret(1)

    def _popup(self, uc, address, size, _):
        text = bytes(uc.mem_read(self.uc.reg_read(ar.UC_ARM_REG_R0), 64)).split(b'\0')[0].decode('ascii')
        self.texts.append((self.ui_ms, text, self.uc.reg_read(ar.UC_ARM_REG_R1)))

    def run(self, start, until, sp=STACK, count=3_000_000):
        self.uc.reg_write(ar.UC_ARM_REG_SP, sp)
        self.uc.emu_start(start | 1, until, count=count)
        if self.uc.reg_read(ar.UC_ARM_REG_PC) != until:
            raise RuntimeError(f'did not reach {until:#x} from {start:#x} (pc {self.uc.reg_read(ar.UC_ARM_REG_PC):#x})')

    def call(self, fn, *args):
        uc = self.uc
        for k, v in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), v & 0xFFFFFFFF)
        uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        self.run(fn, RET)
        return uc.reg_read(ar.UC_ARM_REG_R0)

    def field(self, which, name):
        names, base = (FIELDS_A, self.sym['bnc_aud']) if which == 'a' else (FIELDS_U, self.sym['bnc_ui_state'])
        v = self.r32(base + 4 * names.index(name))
        return v - (1 << 32) if name in SIGNED and v & 0x80000000 else v

    def a(self, name):
        return self.field('a', name)

    def u(self, name):
        return self.field('u', name)

    # ---- the SP's state ----
    def dma(self, p):
        """eDMA positions: (TX line 3 frame - RX frame) mod 128 reads p or p + 1 (the FIFOs' jitter)."""
        self.p_true = p
        self.set_dma(p)

    def set_dma(self, p):
        t = (40 + p) % 128
        self.w32(TCD3_SADDR, TX3 + t * 64 + 8)
        self.w32(TCD4_DADDR, RXBUF + 40 * 32 + 4)

    def slot_voice(self, slot, pad, on):
        voice, stream = VOICES + slot * 0x18000, STREAMS + slot * 0x100
        self.w32(voice + 0x14268, stream)
        self.w32(voice + 0x14274, pad)
        self.uc.mem_write(stream, b'\x01\x00' if on else b'\x00\xff')

    def pad_get(self, pid, pad):
        return self.call(PADGET, SMPL, pid, pad)

    def pad_set(self, pid, value, pad):
        return self.call(PADSET, SMPL, pid, value, pad)

    def load_pad(self, pad, frames, start=0, end=None, loop=0, lp=None, **params):
        end = frames if end is None else end
        self.call(PADINIT, SMPL, pad, 0x200 + 4 * start, 0x200 + 4 * end)
        info = FILE_INFO + pad * 36
        self.w32(info + 8, 2)
        self.w32(info + 0xC, 0x200)
        self.w32(info + 0x10, 0x200 + 4 * frames)
        self.status[pad] = 1
        if loop:
            self.pad_set(0x6B, 1, pad)
        if lp is not None:
            self.pad_set(0x71, lp, pad)
        for pid, v in params.items():             # PITCH 0x73 .. Release 0x7f live at +0xdc + 4 (id - 0x69)
            self.w32(SMPL + pad * 0xAC + 0xDC + 4 * (int(pid[1:], 16) - 0x69), v)

    def press_keys(self):
        bits = bytearray(16)
        for k in self.keys:
            bits[k >> 3] |= 1 << (k & 7)
        self.uc.mem_write(KEYS, bytes(bits))

    def event(self, kind, a1=0, a2=0):
        self.uc.mem_write(EVENT, struct.pack('<4h', kind, a1, a2, 0))
        before = len([x for x in self.log if x[0] == 'doom'])
        r = self.call(self.r32(VTABLE_SLOT) & ~1 | 1, PAGE_OBJ, EVENT)
        passed = len([x for x in self.log if x[0] == 'doom']) > before
        return r, passed

    def key(self, k, down=True):
        (self.keys.add if down else self.keys.discard)(k)
        self.press_keys()
        return self.event(EV_KEY if down else EV_KEY_UP, k)

    def tap(self, k):
        self.key(k)
        self.key(k, False)

    def gesture(self, pad):
        self.keys.add(KEY_RESAMPLE)
        self.press_keys()
        r = self.event(EV_PAD, pad, 100)
        self.event(EV_PAD_UP, pad, 0)
        self.keys.discard(KEY_RESAMPLE)
        self.press_keys()
        return r

    def turn(self, delta):
        return self.event(EV_ENCODER, 0, delta)

    # ---- SMPL TASK ----
    def settle(self):
        for item in self.queue:
            state = self.r8(REC_STATE)
            if item[0] == 'target':
                if state != 2:
                    self.w32(TARGET_VALUES + 4 * item[1], item[2])
                continue
            cmd = item[1]
            if cmd == 5 and self.voice:
                self.voice.stop()
            elif cmd == 0x14 and state == 0:
                self.uc.mem_write(REC_STATE, b'\x01')
                self.w32(FEED_ON, 1)                      # as the stock standby does
                self.uc.mem_write(ENGINE + 0x1C0, struct.pack('<Q', 0x800))
                self.uc.mem_write(ENGINE + 0x200, struct.pack('<Q', 0))
                self.uc.mem_write(ENGINE + 0x208, struct.pack('<q', -1))
                self.take = []
            elif cmd == 0x17 and state in (1, 3):
                self.uc.mem_write(REC_STATE, b'\x02')
                self.dest = self.r32(TARGET_VALUES) * 16 + self.r32(TARGET_VALUES + 4)
            elif cmd == 0x18 and state == 1:
                self.uc.mem_write(REC_STATE, b'\x00')
                self.w32(TARGET_VALUES + 4, 0xFFFFFFFF)
            elif cmd == 0x18 and state == 2:
                self.uc.mem_write(REC_STATE, b'\x00')     # state 0 comes before the 500 ms wait
                self.finalized.append(dict(first_sound=struct.unpack('<q', bytes(self.uc.mem_read(ENGINE + 0x208,
                                                                                                   8)))[0],
                                           frames=len(self.take), snap=self.settings.get(0x59),
                                           length=self.settings.get(0x24)))
                self.final_due = self.ui_ms + 600
            elif cmd == 0x1A and state == 2:
                self.uc.mem_write(REC_STATE, b'\x00')
                self.take = []
                self.w32(TARGET_VALUES + 4, 0xFFFFFFFF)
            elif cmd == 0xD:
                self.saves += 1
        self.queue = []
        if self.final_due is not None and self.ui_ms >= self.final_due:
            self.final_due = None
            d, n = self.dest, len(self.take)
            if self.load_ok:
                self.load_pad(d, n + 384, start=384, end=384 + n)
                self.uc.mem_write(TEXT, b'New Sample\0')
                self.call(PADNAME, SMPL, d, TEXT)
                base = SMPL + d * 0xAC
                self.w32(base + 0xD4, self.r32(base + 0xD4) + 12)    # the stock zero-cross adjust moves START
            self.settings[0x59] = 0
            self.w32(TARGET_VALUES + 4, 0xFFFFFFFF)

    # ---- the audio task ----
    def rx_value(self, R):
        fx = self.fx
        t = R - fx['L']
        l, r = self.tx_mix.get(t, (0, 0))
        g = fx['gain']
        l, r = l * g, r * g
        if fx['echo']:
            d, eg = fx['echo']
            el, er = self.tx_mix.get(t - d, (0, 0))
            l, r = l + el * eg, r + er * eg
        if fx['noise']:
            l, r = l + self.rng.choice((-1, 1)) * fx['noise'], r + self.rng.choice((-1, 1)) * fx['noise']
        return s16(l), s16(r)

    def tx(self):
        self.uc.reg_write(ar.UC_ARM_REG_R5, 0x30EF0004)
        self.run(TX_SITE, TX_BACK, sp=AUDIO_SP)
        self.tx_n += 1

    def rx(self):
        m = self.rx_n
        raw = bytearray(0x800)
        for f in range(64):
            l, r = self.rx_value(64 * m + f)
            struct.pack_into('<2h', raw, f * 32, r, l)     # the feed stores word 1 then word 0
        at = RXBUF + (m & 1) * 0x800
        self.uc.mem_write(at, bytes(raw))
        self.set_dma(self.p_true + self.rng.randint(0, 1))
        self.uc.reg_write(ar.UC_ARM_REG_R0, at)
        self.run(RX_SITE, LOOP_HEAD, sp=AUDIO_SP)
        self.rx_n += 1

    def ui(self, ms=1):
        self.ui_ms += ms
        self.uc.reg_write(ar.UC_ARM_REG_R0, ms)
        self.uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        self.run(UI_SITE, UI_REST)
        self.settle()

    def period(self):
        """One audio wake (TX then RX), and the UI task's 1 or 2 ms ticks (4 ms per 3 blocks)."""
        self.tx()
        self.rx()
        self.ui(2 if self.tx_n % 3 == 0 else 1)

    def popup(self):
        return bytes(self.uc.mem_read(POPUP_TEXT, 64)).split(b'\0')[0].decode('ascii')


def pcm_burst(n, seed, attack=0, silence=0):
    """Stereo 16-bit test audio: silence, then noise with an attack ramp of `attack` frames."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        if i < silence:
            out.append((0, 0))
            continue
        k = i - silence
        env = 1.0 if attack == 0 or k >= attack else k / attack
        decay = max(0.05, 1.0 - k / (2 * n))
        out.append((s16(rng.randint(-20000, 20000) * env * decay), s16(rng.randint(-20000, 20000) * env * decay)))
    return out


def boot(img, man, d=0, p=61, L=77, seed=1):
    m = Machine(img, man)
    m.rng = random.Random(seed)
    m.load_ok = True
    m.dma(p)
    m.fx['L'] = L
    if d < 0:
        for _ in range(-d):
            m.tx()
    for _ in range(max(d, 0)):
        m.rx()
    return m


def run_bounce(m, src_pad, mode_turns=0, budget=4000, exit_at=None, during=None):
    """The gesture, VALUE turns, REC, then audio periods until the controller is idle again."""
    r = m.gesture(src_pad)
    m.ui(1)
    for _ in range(abs(mode_turns)):
        m.turn(1 if mode_turns > 0 else -1)
        m.ui(1)
    if m.u('state') != U_SETUP:
        return dict(gesture=r, setup=False)
    m.key(KEY_REC)
    m.key(KEY_REC, False)
    states = []
    for i in range(budget):
        if during:
            during(m, i)
        m.period()
        st = m.u('state')
        if not states or states[-1] != st:
            states.append(st)
        if exit_at is not None and st == exit_at[0] and (len(exit_at) == 1 or i >= exit_at[1]):
            m.key(KEY_EXIT)
            m.key(KEY_EXIT, False)
            exit_at = None
        if st == U_IDLE:
            break
    for _ in range(4):
        m.ui(1)
    return dict(gesture=r, setup=True, states=states, popup=m.popup())


def expected_rx(m, first, n):
    return [m.rx_value(first + i) for i in range(n)]


def check_take(m, label, src_frames, L, mode, win, lp_frames=None):
    """The take = RX frames from F0; START/END on [F0 + L, F0 + L + win); dry: the source's own frames."""
    f0, t0 = m.a('f0'), m.a('t0')
    take = m.take
    start, end = m.u('r_start'), m.u('r_end')
    d = m.u('dst')
    check(m.u('r_l') == L, f'{label}: L used = {m.u("r_l")} (true {L})')
    check(len(m.finalized) == 1 and m.finalized[0]['first_sound'] == -1 and m.finalized[0]['snap'] == 0 and
          m.finalized[0]['length'] == 6,
          f'{label}: at REC_STOP the take has no first sound, END Snap off and REC length FREE ({m.finalized})')
    check(take == expected_rx(m, f0, len(take)), f'{label}: the take is the RX stream from F0, frame for frame')
    check(start == 384 + L and end == start + win and m.pad_get(0x67, d) == start and m.pad_get(0x68, d) == end,
          f'{label}: START/END = file frames {start}..{end} (384 pre-roll + L, + {win}), as the pad reads them '
          f'({m.pad_get(0x67, d)}..{m.pad_get(0x68, d)})')
    check(m.pad_get(0x71, d) == start, f'{label}: loop point = START')
    window = take[L:L + win]
    check(len(window) == win, f'{label}: the take covers the window ({len(take)} frames)')
    if src_frames is not None:
        check(window == src_frames, f'{label}: dry, the window is the source\'s own frames')
    return window


def static_checks(out, man, img, parent):
    check(sha(img) == man['sha256'], 'APP1 matches manifest SHA-256')
    check(sha(parent) == man['parent_sha256'], 'parent APP1 matches manifest')
    check(sha((out / 'SP404MKII_APP0.bin').read_bytes()) == man['app0_sha256'], 'APP0 is stock 5.52')
    allowed = set(range(0x80, 0x88))
    for p in man['patches'] + man['data_patches']:
        o = file_offset(parent, p['address'], p['size'])
        allowed |= set(range(o, o + p['size']))
        check(parent[o:o + p['size']].hex() == p['original_hex'] and img[o:o + p['size']].hex() == p['replacement_hex'],
              f"site {p['address']:#x}: parent bytes and replacement as in the manifest")
    diff = [i for i in range(len(parent)) if img[i] != parent[i] and i not in allowed]
    check(not diff, f'no other byte of the parent changed ({len(diff)} found)')
    rows_in, rows_out = scatter(parent), scatter(img)
    check(rows_out[:-1] == rows_in, 'scatter table = parent rows (start fix included) + one row')
    load, dst, n, fn = rows_out[-1]
    check((dst, n, fn) == (man['blob_base'], man['blob_size'], COPY), 'added row copies the blob to its base')
    check(sha(img[load - FLASH:load - FLASH + n]) == man['blob_sha256'], 'blob bytes match manifest')
    lo, hi = man['slot']
    check(dst == lo and dst + n <= hi <= 0x83FED000, 'blob inside its slot, below 0x83FED000 (CPU meter, start fix)')
    check(all(not (max(d_, lo) < min(d_ + k, hi)) for _, d_, k, _f in rows_in), 'no parent row overlaps the slot')
    for g in man['guards']:
        a, e = g['start'], g['end']
        o = a - FLASH if FLASH <= a < FLASH + len(parent) else file_offset(parent, a, e - a)
        if not check(sha(parent[o:o + e - a]) == g['sha256'], f'guard {a:#x}..{e:#x} holds on the parent'):
            break
    vt = man['data_patches'][0]
    check(struct.unpack('<I', bytes.fromhex(vt['original_hex']))[0] == 0x6031C8F9 and
          struct.unpack('<I', bytes.fromhex(vt['replacement_hex']))[0] == man['entries']['bnc_event'] | 1,
          'page 0xe vtable +8: DOOM OS filter -> bnc_event')
    note('static image checks')


def bridge_checks(img, parent, man):
    old, new = Machine(parent), Machine(img, man)
    res = []
    for m in (old, new):
        m.log = []
        regs = [0x44, 0x30EF0004, 0x66, 0x77, 0x88, 0x99, 0xAA, 0xBB]
        for k, v in enumerate(regs):
            m.uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k + 4}'), v)
        m.run(TX_SITE, TX_BACK, sp=AUDIO_SP)
        res.append((m.mixer_calls, [m.uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}')) for k in range(4, 12)],
                    m.uc.reg_read(ar.UC_ARM_REG_SP)))
    check(res[0][0] == res[1][0] == [[0x30EF0004, 0x1000, AUDIO_SP]],
          'TX bridge: the mixer is called once with (r5, 0x1000) at the stock stack depth')
    check(res[0][1:] == res[1][1:], 'TX bridge: r4-r11 and sp come back as stock leaves them')
    check(new.a('tx_blocks') == 1, 'TX bridge: bnc_tx ran once')
    rx_cmp = []
    for m in (old, new):
        m.gate_calls = []
        m.w32(0x8059179C, 0)
        raw = bytearray(0x800)
        for f in range(64):
            for w in range(16):
                struct.pack_into('<h', raw, f * 32 + w * 2, (f * 97 + w * 1000) - 3000)
        m.uc.mem_write(RXBUF + 0x800, bytes(raw))
        m.uc.reg_write(ar.UC_ARM_REG_R0, RXBUF + 0x800)
        for k in range(4, 12):
            m.uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), 0x1000 + k)
        m.run(RX_SITE, LOOP_HEAD, sp=AUDIO_SP)
        rx_cmp.append((bytes(m.uc.mem_read(CAPTURE, 256)), bytes(m.uc.mem_read(0x8059179C, 4)),
                       [g[1:] for g in m.gate_calls], [m.uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}'))
                                                       for k in range(4, 12)], m.uc.reg_read(ar.UC_ARM_REG_SP)))
    check(rx_cmp[0][:2] == rx_cmp[1][:2], 'RX bridge: the stock feed fills the capture buffer and the meter as stock')
    check(rx_cmp[0][2] == rx_cmp[1][2] == [(REC, CAPTURE, 64)], 'RX bridge: the recorder gate is called once, as stock')
    check(rx_cmp[0][3:] == rx_cmp[1][3:], 'RX bridge: r4-r11 and sp come back as stock leaves them')
    check(new.a('rx_blocks') == 1 and new.r32(FEED_ON) == 1, 'RX bridge: bnc_rx ran once and left the gate on (idle)')
    new.gate_calls = []
    new.w32(new.sym['bnc_own'], 1)
    new.w32(FEED_ON, 1)                             # as a stock standby leaves it
    new.uc.mem_write(CAPTURE, bytes(256))
    new.uc.reg_write(ar.UC_ARM_REG_R0, RXBUF + 0x800)
    new.run(RX_SITE, LOOP_HEAD, sp=AUDIO_SP)
    check(new.gate_calls == [] and new.r32(FEED_ON) == 0 and bytes(new.uc.mem_read(CAPTURE, 256)) == rx_cmp[0][0],
          'RX bridge, a bounce owning the recorder: the feed enable is cleared before the feed, the gate is not '
          'called, the capture is still filled')
    new.w32(new.sym['bnc_own'], 0)
    ui = []
    for m in (old, new):
        m.w32(0x805922AC + 8, 1234)
        for k in range(4, 12):
            m.uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), 0x2000 + k)
        m.uc.reg_write(ar.UC_ARM_REG_R0, 7)
        m.uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        m.run(UI_SITE, UI_REST, sp=STACK - 0x400)
        sp = m.uc.reg_read(ar.UC_ARM_REG_SP)
        ui.append(([m.uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}')) for k in (0, 1, 4, 5, 6, 7, 8)], sp,
                   bytes(m.uc.mem_read(sp, 16)), list(m.texts)))
    check(ui[0][:3] == ui[1][:3], 'UI bridge: r0, r1, r4-r8, sp and the pushed frame at 0x8006b95c as stock')
    check(ui[1][3] == [] and new.u('ms') == 7, 'UI bridge: bnc_ui ran (7 ms) and raised no popup while idle')
    note('bridges against the parent')


def filter_checks(img, man):
    m = boot(img, man)
    m.load_pad(0, 4800)
    for kind, a1, a2 in ((EV_KEY, KEY_REC, 0), (EV_KEY_UP, KEY_REC, 0), (EV_ENCODER, 0, 1), (EV_KNOB, 1, 64),
                         (EV_PAD, 0, 100), (EV_PAD_UP, 0, 0), (0x13, 0, 0), (0x23, 0xD, 0), (8, 0, 0)):
        r, passed = m.event(kind, a1, a2)
        check(passed and r == 0x55, f'idle: event type {kind:#x} goes to DOOM OS\'s filter and its result comes back')
    cond = []
    for name, setup in (('RESAMPLE not held', lambda mm: None),
                        ('SHIFT held', lambda mm: mm.keys.add(KEY_SHIFT)),
                        ('recorder in standby', lambda mm: mm.uc.mem_write(REC_STATE, b'\x01')),
                        ('not the RESAMPLE mode', lambda mm: mm.settings.__setitem__(0x36, 0)),
                        ('page modal', lambda mm: setattr(mm, 'modal', 1)),
                        ('project 0xbf', lambda mm: mm.project.__setitem__(0xBF, 1)),
                        ('project 0xdd', lambda mm: mm.project.__setitem__(0xDD, 1)),
                        ('empty pad', lambda mm: mm.status.__setitem__(0, 0)),
                        ('pad 16', None)):
        mm = boot(img, man)
        mm.load_pad(0, 4800)
        pad = 16 if setup is None else 0
        if setup:
            setup(mm)
        held = name != 'RESAMPLE not held'
        if held:
            mm.keys.add(KEY_RESAMPLE)
        mm.press_keys()
        r, passed = mm.event(EV_PAD, pad, 100)
        cond.append(name)
        check(passed and r == 0x55 and mm.u('state') == U_IDLE, f'no gesture when {name}: the pad goes on to DOOM OS')
    mg = boot(img, man)
    mg.load_pad(0, 4800)
    r, passed = mg.gesture(0)
    mg.ui(1)
    check(r == 1 and not passed and mg.u('state') == U_SETUP and mg.popup() == 'BOUNCE A-1>A-2\nNO TAIL',
          f'gesture: RESAMPLE held + sample pad: setup popup, the pad is not played ({mg.popup()!r})')
    for kind, a1, a2 in ((EV_KEY, 0x16, 0), (EV_KEY_UP, 0x16, 0), (EV_KNOB, 3, 30), (EV_PAD, 3, 90), (EV_PAD_UP, 3, 0),
                         (0x12, 3, 50), (EV_ENCODER, 1, 1)):
        r, passed = mg.event(kind, a1, a2)
        check(r == 1 and not passed and mg.u('state') == U_SETUP and not [x for x in mg.log if x[0] == 'post'],
              f'setup: event {kind:#x}/{a1:#x} is swallowed and changes nothing')
    for kind in (0x13, 0x23, 8):
        r, passed = mg.event(kind, 0, 0)
        check(passed, f'setup: non-input event {kind:#x} still reaches DOOM OS\'s filter')
    seen = []
    for d in (1, 1, 1, -1, -1, -1):
        mg.turn(d)
        mg.ui(1)
        seen.append(mg.popup().split('\n')[1])
    check(seen == ['TAIL', 'LOOP', 'LOOP', 'TAIL', 'NO TAIL', 'NO TAIL'], f'VALUE: NO TAIL / TAIL / LOOP, clamped ({seen})')
    mg.tap(KEY_EXIT)
    mg.ui(1)
    check(mg.u('state') == U_IDLE and mg.popup() == 'BOUNCE CANCELLED\nNOTHING CHANGED' and
          not [x for x in mg.log if x[0] in ('post', 'set', 'target')],
          'EXIT in setup: cancelled, nothing posted or set')
    mg.ui(300)
    r, passed = mg.event(EV_PAD, 0, 100)
    check(passed, 'after EXIT a sample pad plays again (DOOM OS gets the event)')
    # the modes each source offers
    mr = boot(img, man)
    mr.load_pad(1, 4800, loop=1)
    mr.load_pad(2, 4800, p73=3)                      # pitched one-shot
    mr.load_pad(3, 4800, loop=1, p76=12000)          # varispeed loop
    texts = []
    for pad in (1, 2, 3):
        mr.gesture(pad)
        mr.ui(1)
        texts.append(mr.popup())
        mr.turn(1)
        mr.turn(1)
        mr.ui(1)
        texts.append(mr.popup().split('\n')[1])
        mr.tap(KEY_EXIT)
        mr.ui(1)
    check(texts == ['BOUNCE A-2>A-5\nNO TAIL', 'LOOP', 'BOUNCE A-3>A-5\nNO TAIL', 'TAIL', 'BOUNCE A-4>A-5\nTAIL ONLY',
                    'TAIL ONLY'],
          f'modes: a pad at its own rate offers all three; a pitched one-shot NO TAIL and TAIL; '
          f'a varispeed loop TAIL ONLY ({texts})')
    # refusals at the gesture
    for name, setup, text in (('no empty pad', lambda mm: [mm.status.__setitem__(p, 1) for p in range(160)],
                               'NO EMPTY PAD'),
                              ('pattern running', lambda mm: mm.uc.mem_write(SEQ_PLAY, b'\x01'), 'STOP PATTERN FIRST'),
                              ('pattern running (system flag)', lambda mm: mm.w32(SEQ_RUN, 1), 'STOP PATTERN FIRST'),
                              ('looper running', lambda mm: mm.uc.mem_write(LOOPER_ON, b'\x01'), 'STOP LOOPER FIRST')):
        mm = boot(img, man)
        mm.load_pad(0, 4800)
        setup(mm)
        r, passed = mm.gesture(0)
        mm.ui(1)
        check(r == 1 and mm.u('state') == U_IDLE and mm.popup() == text and
              not [x for x in mm.log if x[0] in ('post', 'set')], f'{name}: popup {text!r}, nothing changes')
    # destination search
    md = boot(img, man)
    for p in list(range(0, 16)) + [16, 17]:
        md.status[p] = 1
    md.load_pad(5, 4800)
    md.status[5] = 1
    md.gesture(5)
    md.ui(1)
    check(md.popup() == 'BOUNCE A-6>B-3\nNO TAIL', f'a full bank: the first empty pad of the other banks ({md.popup()!r})')
    me = boot(img, man)
    for p in (13, 14, 15, 1, 2):
        me.status[p] = 1
    me.load_pad(13, 4800)
    me.gesture(13)
    me.ui(1)
    check(me.popup() == 'BOUNCE A-14>A-1\nNO TAIL', f'after the source, wrapping inside its bank ({me.popup()!r})')
    mp = boot(img, man)
    mp.load_pad(0, 4800)
    mp.gesture(0)
    mp.ui(1)
    mp.uc.mem_write(PAGE_ID, struct.pack('<H', 1))
    mp.ui(1)
    check(mp.u('state') == U_IDLE, 'setup ends quietly when the page changes')
    note('page filter and setup')


def runs(img, man):
    rng = random.Random(7)
    results = []

    def native_case(label, mode, turns, n=6000, loop=0, lp=None, d=0, p=61, L=77, attack=0, silence=0, echo=None,
                    gain=1.0, start=0, end=None, delay=1):
        m = boot(img, man, d=d, p=p, L=L, seed=rng.randint(0, 1 << 30))
        pcm = pcm_burst(n, rng.randint(0, 1 << 30), attack=attack, silence=silence)
        end = n if end is None else end
        m.load_pad(0, n, start=start, end=end, loop=loop, lp=lp)
        m.voice = Voice(m, 0, pcm, start, end, lp if lp is not None else start, delay)
        m.fx.update(echo=echo, gain=gain)
        res = run_bounce(m, 0, turns)
        return m, pcm, res

    # NO TAIL, one-shot, sharp attack
    m, pcm, res = native_case('NO TAIL one-shot', NO_TAIL, 0)
    check(res['popup'] == 'BOUNCED A-1\nON A-2', f'NO TAIL one-shot: done popup ({res["popup"]!r})')
    win = check_take(m, 'NO TAIL one-shot', pcm, 77, NO_TAIL, 6000)
    check(m.u('r_meas') == 77 and m.u('r_est') == 77, 'NO TAIL one-shot: onset L 77 = the estimate (P61 D0)')
    check(m.gate_calls == [], f'the stock gate never ran from REC to the end of the run ({m.gate_calls[:3]})')
    check(m.r32(FEED_ON) == 1 and m.settings[0x24] == 3 and m.settings[0x59] == 0 and m.settings[0x1A] == -1 and
          m.settings[0x1B] == 12000, 'after the run: feed enable, REC length, END Snap, destination, REC BPM restored')
    name = bytes(m.uc.mem_read(SMPL + 1 * 24 + 0x6CFC, 24)).split(b'\0')[0].decode('ascii')
    check(m.saves == 1 and name.startswith('A1 L77 M77 P61.') and name.endswith(' D0') and len(name) <= 23,
          f'the pad is named with the run ({name}) and saved')
    sets = [x for x in m.log if x[0] == 'set']
    check(sets[:4] == [('set', 0x24, 6, 0), ('set', 0x59, 0, 0), ('set', 0x1B, 9000, -1), ('set', 0x1A, 1, 0)],
          f'pinned before standby: REC length FREE, END Snap off, REC BPM = the bank, destination A-2 ({sets[:4]})')
    posts = [x[1] for x in m.log if x[0] == 'post']
    check(posts == [5, 0x2A, 0x14, 0x17, 5, 0x18, 0xD],
          f'commands: sound off, seq sound off, standby, start, sound off, stop, save ({[hex(x) for x in posts]})')
    trig = [x for x in m.log if x[0] == 'trigger']
    check(trig == [('trigger', 0, 127, 1)], 'the source is triggered once at velocity 127, mode 1')
    results.append(('NO TAIL one-shot', m.u('r_l'), m.u('r_est'), m.u('r_meas')))

    # the same with an echo on the return: the window is still the RX stream, the tail is cut
    m, pcm, res = native_case('NO TAIL + echo', NO_TAIL, 0, echo=(1500, 0.5))
    check_take(m, 'NO TAIL with an echo', None, 77, NO_TAIL, 6000)

    # soft start: no TX onset within 100 ms: the estimate
    m, pcm, res = native_case('soft start', NO_TAIL, 0, silence=6000, n=12000)
    check_take(m, 'NO TAIL, 125 ms of silence first', pcm, 77, NO_TAIL, 12000)
    check(m.u('r_meas') == 0, 'soft start: no onset measured, the estimate is used')

    # BUS 3/4 adds a frame: onset 78, estimate 77
    m, pcm, res = native_case('L+1', NO_TAIL, 0, L=78)
    check_take(m, 'NO TAIL, latency one frame above the estimate', pcm, 78, NO_TAIL, 6000)

    # the second boot of T1: phase 65..66, D -1, L 73
    m, pcm, res = native_case('P66 D-1', NO_TAIL, 0, d=-1, p=65, L=73)
    check_take(m, 'NO TAIL, D -1, P65.5', pcm, 73, NO_TAIL, 6000)
    check(m.u('r_est') == 73 and m.u('r_d') == -1, f'P65.5 D-1: estimate 73 ({m.u("r_est")}), D -1')

    # the onset decides a wrong estimate within 6 frames (here the estimate says 77, the onset 72)
    m, pcm, res = native_case('L-5', NO_TAIL, 0, L=72)
    check_take(m, 'NO TAIL, latency 5 frames below the estimate', pcm, 72, NO_TAIL, 6000)
    # ... and not beyond: an onset 20 frames late (a slow effect) keeps the estimate
    m, pcm, res = native_case('L+20', NO_TAIL, 0, L=97)
    check(m.u('r_l') == 77 and m.u('r_meas') == 97, f'an onset 20 frames from the estimate is not used ({m.u("r_l")})')

    # D +1: T0's RX block came a wake earlier; the take starts from the kept blocks
    m, pcm, res = native_case('D+1', NO_TAIL, 0, d=1, p=61, L=77 + 64)
    check_take(m, 'NO TAIL, D +1 (history)', pcm, 141, NO_TAIL, 6000) if m.u('r_l') == 141 else \
        check(False, f'D +1: L {m.u("r_l")}')

    # a sample with START/END inside its file
    m, pcm, res = native_case('START/END', NO_TAIL, 0, n=9000, start=1000, end=7000)
    check_take(m, 'NO TAIL, START 1000 END 7000', pcm[1000:7000], 77, NO_TAIL, 6000)

    # TAIL: an echo rings after the one-shot; END at the last frame above -72 dBFS
    m, pcm, res = native_case('TAIL', TAIL, 1, n=4000, echo=(3000, 0.25))
    last = max(i for i in range(len(m.take)) if max(abs(m.take[i][0]), abs(m.take[i][1])) > 8)
    win = last + 1 - 77
    check_take(m, 'TAIL with an echo', None, 77, TAIL, win)
    check(win > 4000 + 2900, f'TAIL: the window runs into the echo ({win} frames)')
    check(res['popup'] == 'BOUNCED A-1\nON A-2', 'TAIL: done popup')

    # LOOP, a looped pad with a loop point: pass 2 from the loop point, including pass 1's echo
    m, pcm, res = native_case('LOOP', LOOP, 2, n=5000, loop=1, lp=1200, echo=(700, 0.5))
    w = check_take(m, 'LOOP, loop point 1200', None, 77, LOOP, 3800)
    check(m.a('f0') == m.a('t0') + 5000, 'LOOP: F0 = T0 + one pass')
    check(m.pad_get(0x6B, 1) != 0 and m.pad_get(0x6B, 0) != 0, 'LOOP: the bounced pad loops; the source still loops')
    m.gesture(0)
    m.ui(1)
    check(m.popup() == 'BOUNCE A-1>A-3\nLOOP', f'the mode used last (LOOP) is offered first next time ({m.popup()!r})')
    m.tap(KEY_EXIT)

    # LOOP of a one-shot: LOOP on for the run, back off before the stop
    m, pcm, res = native_case('LOOP one-shot', LOOP, 2, n=5000, echo=(1000, 0.4))
    check_take(m, 'LOOP of a one-shot', None, 77, LOOP, 5000)
    loops = [x for x in m.log if x[0] == 'trigger']
    check(m.pad_get(0x6B, 0) == 0 and m.pad_get(0x6B, 1) != 0,
          'LOOP of a one-shot: the source is a one-shot again, the bounce loops')

    # TAIL of a looped pad: plays once (LOOP off for the run)
    m, pcm, res = native_case('TAIL loop', TAIL, 1, n=4000, loop=1, echo=(2000, 0.3))
    last = max(i for i in range(len(m.take)) if max(abs(m.take[i][0]), abs(m.take[i][1])) > 8)
    check_take(m, 'TAIL of a looped pad', None, 77, TAIL, last + 1 - 77)
    check(m.pad_get(0x6B, 0) != 0 and m.pad_get(0x6B, 1) == 0, 'TAIL of a looped pad: the source loops again')

    # NO TAIL of a pitched one-shot: the window is the voice's own length
    m = boot(img, man, seed=3)
    pcm = pcm_burst(5000, 11)
    played = pcm_burst(4321, 12)                     # what the pitched voice delivers
    m.load_pad(0, 5000, p73=5)
    m.voice = Voice(m, 0, played, 0, 4321, 0, 1)
    res = run_bounce(m, 0, 0)
    check_take(m, 'NO TAIL, pitched one-shot', played, 77, NO_TAIL, 4321)

    # the boot's calibration: a soft start after a calibrated run uses the onset L
    m = boot(img, man, d=-1, p=66, L=73, seed=5)
    pcm = pcm_burst(3000, 21)
    m.load_pad(0, 3000)
    m.voice = Voice(m, 0, pcm, 0, 3000, 0, 1)
    run_bounce(m, 0, 0)
    check(m.u('cal_valid') == 1 and m.u('cal_l') == 73, 'calibration: the first run\'s onset L 73 is kept')
    soft = pcm_burst(9000, 22, silence=6000)
    m.load_pad(2, 9000)
    m.voice = Voice(m, 2, soft, 0, 9000, 0, 2)
    m.take, m.finalized = [], []
    run_bounce(m, 2, 0)
    check(m.u('r_est') == 73 and m.u('r_l') == 73, f'calibration: a later soft start uses 73 (est {m.u("r_est")})')
    check(m.take[73:73 + 9000] == soft, 'calibration: that take is frame-exact')
    name = bytes(m.uc.mem_read(SMPL + 3 * 24 + 0x6CFC, 24)).split(b'\0')[0].decode('ascii')
    check(name.startswith('A3 L73C M-- P'), f'calibration: the name marks the boot\'s L and no onset ({name})')

    # NO TAIL of a looped pad at its own rate: exactly one pass; the bounce loops too
    m, pcm, res = native_case('NO TAIL loop', NO_TAIL, 0, n=5000, loop=1, lp=1000)
    check_take(m, 'NO TAIL, a looped pad', pcm[:5000], 77, NO_TAIL, 5000)
    check(m.pad_get(0x6B, 1) != 0 and m.pad_get(0x6B, 0) != 0, 'NO TAIL of a loop: both pads loop')

    # a source in bank B (the current bank)
    m = boot(img, man, seed=13)
    pcm = pcm_burst(3000, 51)
    m.project[0] = 1
    m.load_pad(19, 3000)
    m.voice = Voice(m, 19, pcm, 0, 3000, 0, 1)
    texts_before = len(m.texts)
    res = run_bounce(m, 3, 0)
    check(res['popup'] == 'BOUNCED B-4\nON B-5' and [x for x in m.log if x[0] == 'trigger'] == [('trigger', 19, 127, 1)]
          and m.u('dst') == 20 and m.r32(TARGET_VALUES) == 1, 'bank B: pad B-4 (19) into B-5, target bank 1 pad 4')
    check(m.take[77:77 + 3000] == pcm, 'bank B: frame-exact')
    seen = [t for _, t, ms in m.texts[texts_before:]]
    steps = [t.split('\n')[1] for t in seen if t.startswith('BOUNCE B-4>B-5\n')]
    pcts = [int(s.split(' ')[-1][:-1]) for s in steps if s.startswith('NO TAIL ') and s.endswith('%')]
    check(steps[0] == 'NO TAIL' and 'WAIT SILENCE' in steps and pcts and pcts == sorted(pcts) and pcts[-1] == 100 and
          seen[-1] == 'BOUNCED B-4\nON B-5',
          f'popups: setup, WAIT SILENCE, NO TAIL 0..100% rising, then BOUNCED ({steps[:3]}..{pcts[-3:]})')

    # the TAIL popup counts seconds
    m, pcm, res = native_case('TAIL popup', TAIL, 1, n=30000)
    steps = [t.split('\n')[1] for _, t, _ms in m.texts if t.startswith('BOUNCE A-1>A-2\nTAIL ')]
    check(any(s.endswith('s') and '.' in s for s in steps), f'TAIL popup: seconds ({steps[-2:]})')

    # an effect still ringing at REC: the run waits for 200 ms of silence first
    m = boot(img, man, seed=14)
    pcm = pcm_burst(3000, 61)
    m.load_pad(0, 3000)
    m.voice = Voice(m, 0, pcm, 0, 3000, 0, 1)
    m.fx['noise'] = 30
    quiet_at = []

    def fade(mm, i):
        if i == 300:                                  # 0.4 s after REC the tail has died away
            mm.fx['noise'] = 0
            quiet_at.append(mm.ui_ms)
    res = run_bounce(m, 0, 0, during=fade)
    started = [ms for ms, cmd in m.post_times if cmd == 0x17]
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and m.take[77:77 + 3000] == pcm and len(started) == 1 and
          started[0] - quiet_at[0] >= 200, f'a tail still ringing at REC: REC_START {started[0] - quiet_at[0]} ms '
          f'after it died away (200 ms of silence), then a frame-exact bounce')

    # END Snap armed by the user before: off for the take, armed again afterwards
    m = boot(img, man, seed=15)
    pcm = pcm_burst(3000, 71)
    m.load_pad(0, 3000)
    m.voice = Voice(m, 0, pcm, 0, 3000, 0, 1)
    m.settings[0x59] = 1
    res = run_bounce(m, 0, 0)
    check(m.finalized[0]['snap'] == 0 and m.settings[0x59] == 1, 'END Snap: off at REC_STOP, the user\'s 1 restored')

    # TAIL that never falls quiet stops at 30 s
    m = boot(img, man, seed=16)
    pcm = pcm_burst(2000, 81)
    m.load_pad(0, 2000)
    m.voice = Voice(m, 0, pcm, 0, 2000, 0, 1)

    def hum(mm, i):
        if mm.u('state') == U_RUN:
            mm.fx['noise'] = 30
    res = run_bounce(m, 0, 1, budget=30000, during=hum)
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and 1440000 - 64 <= m.u('r_len') <= 1440000 + 64,
          f'TAIL never quiet: ends at the 30 s cap ({m.u("r_len")} frames)')
    note('whole runs')
    return results


def failure_checks(img, man):
    def setup(**kw):
        m = boot(img, man, seed=9)
        pcm = pcm_burst(3000, 31)
        m.load_pad(0, 3000, loop=kw.get('loop', 0))
        m.voice = Voice(m, 0, pcm, 0, 3000, 0, 1)
        return m

    def restored(m, label):
        check(m.r8(REC_STATE) == 0 and m.r32(FEED_ON) == 1 and m.settings[0x24] == 3 and m.settings[0x59] == 0 and
              m.settings[0x1B] == 12000 and m.settings[0x1A] == -1 and m.status[1] == 0 and m.u('pinned') == 0,
              f'{label}: recorder idle, feed enable and settings restored, the destination stays empty')

    for state, label in ((U_STANDBY, 'standby'), (U_SILENCE, 'silence wait'), (U_RUN, 'recording')):
        m = setup()
        res = run_bounce(m, 0, 0, exit_at=(state,))
        posts = [x[1] for x in m.log if x[0] == 'post']
        check(res['popup'] == 'BOUNCE CANCELLED\nNOTHING CHANGED',
              f'EXIT during {label}: cancelled popup ({res["popup"]!r}, {[hex(x) for x in posts]})')
        restored(m, f'EXIT during {label}')
        check(0x18 not in posts[posts.index(0x14) + 1:] if state == U_RUN else True,
              f'EXIT during {label}: the take is discarded (0x1a), never finalized')
    m = setup()
    res = run_bounce(m, 0, 2, exit_at=(U_RUN,))
    check(m.pad_get(0x6B, 0) == 0, 'EXIT during a LOOP run of a one-shot: the source\'s LOOP is back off')
    m = setup()
    m.fx['noise'] = 40
    res = run_bounce(m, 0, 0, budget=9000)
    check(res['popup'] == 'FX STILL RINGING', f'RX never quiet: FX STILL RINGING after 10 s ({res["popup"]!r})')
    restored(m, 'ringing')
    for name, change in (('ROUTING not Mix', lambda mm: setattr(mm, 'routing', 1)),
                         ('mono recorder', lambda mm: mm.w32(TARGET_VALUES + 0xC, 0))):
        m = setup()
        change(m)
        res = run_bounce(m, 0, 0)
        check(res['popup'] == 'BOUNCE FAILED' and not [x for x in m.log if x[0] == 'post'],
              f'{name}: BOUNCE FAILED, nothing posted ({res["popup"]!r})')
        restored(m, name)
    m = setup()
    res = run_bounce(m, 0, 0, exit_at=(U_FINAL,))
    check(res['popup'] == 'BOUNCED A-1\nON A-2', 'EXIT while the take is being saved: ignored, the bounce completes')
    m2 = setup()
    m2.gesture(0)
    m2.ui(1)
    m2.uc.mem_write(SEQ_PLAY, b'\x01')
    m2.tap(KEY_REC)
    m2.ui(1)
    check(m2.popup() == 'STOP PATTERN FIRST' and not [x for x in m2.log if x[0] == 'post'],
          'pattern started during setup: STOP PATTERN FIRST at REC, nothing posted')
    m = setup()
    m.trigger_ignored = True
    res = run_bounce(m, 0, 0)
    check(res['popup'] == 'BOUNCE FAILED' and 0x1A in [x[1] for x in m.log if x[0] == 'post'],
          'the source never sounds: BOUNCE FAILED after 1 s, the take discarded')
    restored(m, 'no voice')
    m = setup()
    m.load_ok = False
    res = run_bounce(m, 0, 0)
    check(res['popup'] == 'BOUNCE FAILED', 'the finalize leaves the pad empty: BOUNCE FAILED')
    m = setup()
    m.project[0xFB] = 1
    res = run_bounce(m, 0, 0)
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and m.project[0xFB] == 1 and
          ('pset', 0xFB, 0) in m.log and m.pad_get(0x67, 1) == 384 + 77,
          'zero-cross snapping on: off while START is set, back on afterwards; START exact')
    note('refusals, EXIT and failures')


def cost_checks(img, man):
    m = boot(img, man, seed=12)
    pcm = pcm_burst(4000, 41)
    m.load_pad(0, 4000)
    m.voice = Voice(m, 0, pcm, 0, 4000, 0, 1)
    lo, hi = man['blob_base'], man['blob_base'] + man['blob_size']
    count = [0]

    def tick(uc, address, size, data):
        if lo <= address < hi:
            count[0] += 1
    idle = []
    h = m.uc.hook_add(UC_HOOK_CODE, tick)
    for _ in range(8):
        count[0] = 0
        m.tx(); m.rx()
        idle.append(count[0])
    m.uc.hook_del(h)
    m.gesture(0)
    m.ui(1)
    m.tap(KEY_REC)
    busy = []
    while m.u('state') not in (U_RECSTART, U_VOICE, U_RUN):
        m.period()
    h = m.uc.hook_add(UC_HOOK_CODE, tick)
    while m.u('state') in (U_RECSTART, U_VOICE, U_RUN):
        count[0] = 0
        m.tx(); m.rx()
        busy.append(count[0])
        m.ui(1)
    m.uc.hook_del(h)
    busy = busy[:-1]                                # the last block pair includes the UI tick that stops
    soft = boot(img, man, seed=13)
    pcm = pcm_burst(12000, 42, silence=8000)
    soft.load_pad(0, 12000)
    soft.voice = Voice(soft, 0, pcm, 0, 12000, 0, 1)
    soft.gesture(0)
    soft.ui(1)
    soft.tap(KEY_REC)
    while soft.u('state') not in (U_RECSTART, U_VOICE, U_RUN):
        soft.period()
    slow = []
    h = soft.uc.hook_add(UC_HOOK_CODE, tick)
    while soft.u('state') in (U_RECSTART, U_VOICE, U_RUN):
        count[0] = 0
        soft.tx(); soft.rx()
        slow.append(count[0])
        soft.ui(1)
    soft.uc.hook_del(h)
    print(f'  module cost per TX+RX block pair: idle {max(idle)}, bouncing up to {max(busy)} instructions, '
          f'{max(slow)} with no onset in the first 100 ms (a block is 1.33 ms, about 800,000 cycles at 600 MHz; '
          f'the engine writer is stubbed)')
    check(max(idle) < 60, 'idle: under 60 instructions per block pair')
    check(max(busy) < 4000 and max(slow) < 10000,
          'bouncing: under 4,000 instructions per block pair, 10,000 while looking for a late onset (about 1% of a '
          'block)')


def main():
    out = Path(sys.argv[1])
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    parent = Path(man['parent_app1']).read_bytes()
    static_checks(out, man, img, parent)
    bridge_checks(img, parent, man)
    filter_checks(img, man)
    r = runs(img, man)
    failure_checks(img, man)
    cost_checks(img, man)
    print(json.dumps(dict(runs=r, cases=cases[0])))
    print('ALL PASS' if not fails else f'{len(fails)} FAILED')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
