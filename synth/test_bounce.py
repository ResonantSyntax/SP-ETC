"""Checks for bounce in place, stage 3 (build_bounce.py).

usage: python synth/test_bounce.py OUT_DIR      (unicorn and keystone on PYTHONPATH)

Reads OUT_DIR/manifest.json for the parent APP1. Static image checks first. Then the built image
is booted in Unicorn the way its scatter loader does it, and the stock code runs for real: the
recorder feed behind the RX bridge, the pad note (0x800cdbd0) and the pad-event dispatcher behind
the gate bridge, the pad parameter getter and setter (with its conversions, protect test and
side effects), the pad name, SMPL TASK's command queue (the posts 0x800e25c0 / 0x800d48e8, the put
and pop, the task's loop 0x80194738, the target store 0x800fb000) and its command dispatcher for
0x40d with the stock exchange (0x800a6c30), its file swap (0x80051040) and path builder, and its
parameter swap, the settings setter for EXT SOURCE, the popup function, the page's vtable, the UI
task's event dispatcher (0x8003b530) where a check drives keys through it, the looper (the MARK
Function setter, its init, the LOOPER TASK's commands, its audio input), and for the MIDI checks
the stock MIDI dispatcher. Modelled: SMPL TASK's recorder commands at the dispatcher's entry
(standby, REC_START, the finalize and cancel, ALL SOUND OFF; a busy task holds the exchange at
the queue's pop), the pad-event ring (a note-on there starts the source's voice), the card under
the file swap at its file calls (unlink, rename, open; by path), the pad loader and save, the
RTOS (locks, waits, task creation, event flags), the source pad's voice (it renders the pad's PCM
into the stems from the first block after its trigger), the effects chip (RX = the record mix L
frames later, optionally with gain, an echo, noise, or the input while EXT SOURCE is on), the eDMA
positions, the recorder engine's writer (it keeps the frames it is given: the take), and the
settings, project and system parameter stores. No screen, no SD card, no real timing: those need
the unit.

Checks:
- static: only the header, the six sites and the appended tail differ from the parent; the
  rows (a copy row and a zero-fill row added); the guards hold on the parent;
- bridges against the parent's own instructions (mixer arguments and stack depth, the feed's
  capture, meter and gate call, the popup tick's registers, the pad-event dispatcher's paths);
- the page filter: every event reaches DOOM OS's filter unless it is the gesture, or a bounce is
  set up or running; the gesture's conditions; the setup popup, VALUE, VALUE pressed, SHIFT+VALUE;
  the target and mode kept once picked;
- the same keys through the UI task's own dispatcher, and a whole REPLACE that way;
- the looper through its stock code: refused only while it plays, records, overdubs or is armed;
- whole runs through the bridges (NO TAIL, TAIL, LOOP; one-shots and loops; at their own rate and
  not; sharp and soft starts; D = -1, 0, +1; an extra frame of latency; the boot's calibration):
  the take holds exactly the RX frames from T0 through the window, START and END land on the
  window, the take is the source's own frames when the effect is dry, the environment comes back;
- the bounced pad's settings: performance settings copied, printed ones neutral, as the stock
  getter reads them back;
- REPLACE and UNDO through the real exchange: the swap, PAD LINK, bit-exact undo, the records, a
  changed pad, protected banks, a failed swap, a stalled command ring; the fence stored only after
  the exchange returned, in the same pass of SMPL TASK's loop;
- leaks: EXT SOURCE, MIDI notes through the stock MIDI dispatcher, the run's own trigger under
  FIXED VELOCITY, a pattern or the looper starting, PAD LINK;
- refusals, EXIT at every phase and failures (the stock recorder ending a take itself included):
  nothing changes, everything pinned comes back;
- on the image's own global objects (the boot's 70 static constructors run; RealMachine): the tick
  bridge against the parent, and a whole-state audit of TO PAD, REPLACE, EXIT during the take and
  EXIT in the silence wait, with the RESAMPLE page's tick running: every write, page request, bank
  or pad change and byte to the effects chip logged, every parameter read before and after, the
  objects diffed byte for byte, each difference on an allowlist with its reason; a stock RESAMPLE
  of the same pad alongside.
"""
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_HOOK_CODE  # noqa: E402
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE  # noqa: E402
from unicorn import arm_const as ar  # noqa: E402

FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
TX_SITE, TX_BACK, RX_SITE, LOOP_HEAD = 0x1D090, 0x1D09A, 0x1D0C2, 0x1D05C
UI_SITE, UI_REST = 0x8006B950, 0x8006B95C
GATE_SITE, RING, DISPATCH_A, DISPATCH_B = 0x800BEF10, 0x80018590, 0x80018400, 0x800DA528
MIXER, FEED, GATE = 0x1C2D0, 0x1CA80, 0x1BAA4
VTABLE_SLOT = 0x80223474
STEMS, CAPTURE, SLOTS = 0x202AD3A0, 0x202AD0A0, 0x202AE1A0
TX3, RXBUF, TCD3_SADDR, TCD4_DADDR = 0x20006000, 0x20008000, 0x400E9060, 0x400E9090
REC = 0x82E0E71C
REC_STATE, REC_SUB, REC_ERR, REC_ENGINE = REC + 0x39, REC + 0x24E, REC + 0x250, REC + 0x254
FEED_ON = 0x805917C4
POPUP_STATE, POPUP_TEXT, POPUP_TIMER = 0x8024589C, 0x802468D8, 0x805922B4
KEYS, PAGE_ID = 0x80592448, 0x80245880
SEQ_PLAY, SEQ_RUN = 0x82E0D660 + 0xA5, 0x82DFFC88 + 0x2C0
LOOPER = 0x82E0B71C
LOOPER_ON, LOOPER_PHASE, LOOPER_GO, LOOPER_TRIG = LOOPER + 0x39, LOOPER + 0x101, LOOPER + 0x102, LOOPER + 0x80
LOOPER_INIT, LOOPER_CMD, LOOPER_IN, SYS_SET, SYS_OBJ = 0x80045968, 0x80070280, 0x1D634, 0x80018D28, 0x80591ADC
LOOPER_AUTO = 0x80019780                # the looper's level-trigger option (from the settings setter): +0x80
TARGET_VALUES = 0x80246E14
SMPL, FILE_INFO = 0x82E2CD08, 0x82E495E4
PADGET, PADSET, PADINIT, PADNAME = 0x800DC6B8, 0x800DA720, 0x800CFA68, 0x800CFA28
EXCHANGE, SMPL_MGR, DISPATCHER = 0x800A6C30, 0x80591800, 0x8004D8B8
MIDI_DISPATCH = 0x80066278
# SMPL TASK's command queue: put 0x800da528, pop 0x8004c230, the task's loop 0x80194738 (case 2)
QBASE, QWRITE, QREAD, QWRAP, SMPL_LOOP, QPOP = 0x80B4C924, 0x805917E0, 0x805917E4, 0xFFE, 0x80194738, 0x8004C230
# the UI task's event dispatcher and what it finds at run time on the RESAMPLE page
UI_DISPATCH, PAGE_PTR, PAGE_VTABLE, PREFILTER, KEY_PAIRS, PAGE_LIVE = (0x8003B530, 0x80592368, 0x8022346C,
                                                                       0x82DFD318, 0x80B119DC, 0x8024587A)
STACK, AUDIO_SP, RET = 0x30010000, 0x300F0000, 0x3001F000
PAGE_OBJ, EVENT, MSG, CMD_MSG, EVENT2 = 0x30090000, 0x30091000, 0x30093000, 0x30094000, 0x30095000
ENGINE, ENGINE_VT, WRITER = 0x30080000, 0x30081000, 0x30082000
VOICES, STREAMS = 0x31000000, 0x31400000
TEXT = 0x30092000
STUBS = {
    0x800E25C0: 'post', 0x800D48E8: 'target', 0x800DA528: 'qput', QPOP: 'qpop', 0x6031C8F8: 'doom',
    0x800D94D8: 'get', 0x800DD0C0: 'set', 0x800DDA38: 'pget', 0x800DED18: 'pset', 0x800DA010: 'sysget',
    0x800CE420: 'modal', 0x101BA: 'zero', 0x1BB6A: 'nop', LOOPER_IN: 'looper_in', GATE: 'gate', WRITER: 'writer',
    0x800D8B90: 'nop',               # the project's change broadcast (its listeners are not built here)
    0x800E11D0: 'nop',               # the sequencer's notice after a TEMPO SYNC change (its object is not built)
    # around the exchange in command 0x40d's case: preview files closed, a debug line, the remote's notice
    0x800DEBD8: 'nop', 0x8003A7A0: 'zero', 0x800D31C6: 'nop', 0x800D9F58: 'nop', 0x800E1190: 'one',
    RING: 'ring', DISPATCH_A: 'other',
    # SMPL TASK's queue runs for real (the posts, the put, the task's loop, the target store); not here: the
    # task's event flag (RTOS) and the debug line the post prints. The recorder commands are modelled at the
    # command dispatcher's entry; 0x40d runs the real dispatcher.
    0x800D30A4: 'nop', 0xE668: 'nop', DISPATCHER: 'command',
    # the exchange's card and voice side: the real file swap (0x80051040) and path builder run, the file calls
    # under them go to a card model keyed by path; the loader, the save, SMPL CHARGE TASK and voices are not here
    0x800DECD8: 'unlink', 0x800100D0: 'rename', 0x800DEC60: 'open',
    0x800CFB20: 'loadpad', 0x800CF218: 'savepads', 0x800D7478: 'nop', 0x800D8998: 'zero',
    0x800D8A70: 'nop', 0x800D8960: 'nop', 0x80095BD0: 'nop', 0x800D8628: 'zero', 0x800D84F0: 'nop',
    0x800D88C8: 'charged',          # a pad's mark cleared: its range charged (0x800d7508 clears it after the charge)
    # the looper's tasks (RTOS): locks, 10 ms waits, task creation and wake-ups; the recorder's MARK mode
    0x800DED08: 'nop', 0x800DECF8: 'nop', 0x408C: 'nop', 0x80097490: 'nop', 0xF38C: 'nop', 0x800C2638: 'nop',
    0x8001D938: 'nop',
}
KEY_REC, KEY_RESAMPLE, KEY_EXIT, KEY_SHIFT, KEY_VALUE = 0x1B, 0x1C, 0x22, 0x2A, 0x31
EV_KEY, EV_KEY_UP, EV_ENCODER, EV_KNOB, EV_PAD, EV_PAD_UP = 5, 6, 7, 9, 0x10, 0x11
FIELDS_A = ('tx_blocks rx_blocks phase quiet_rx quiet_tx pad mode skip measure armed_voices slot voice t0 f0 fed '
            'stop have_l cached l l_est l_meas p_n p0 p_sum p16 d tx_onset scan last_nz voice_end last_loud win '
            'rx_now fail rx_onset l_win departed').split()
FIELDS_U = ('state ms since shown refresh src dst mode modes loop_src loop_pin len1 len2 native saved_len saved_snap '
            'pinned msg waits last_mode cal_off cal_valid runs r_l r_est r_meas r_p16 r_d r_start r_end r_len '
            'r_mode r_exact target targets last_target scratch lp_off ext_pin saved_ext link_pin link_src swap_kind '
            'swap_a swap_b want_len_a want_ch_a want_len_b want_ch_b fence undo_slot undo_next partial err dropped').split()
UNDO_FIELDS = 'used pad keep len_pad ch_pad len_keep ch_keep link'.split()
UNDOS = 8
SIGNED = {'l', 'l_est', 'l_meas', 'p0', 'p_sum', 'p16', 'd', 'saved_len', 'saved_snap', 'cal_off', 'r_l',
          'r_est', 'r_meas', 'r_p16', 'r_d', 'saved_ext', 'link_src', 'err'}
(U_IDLE, U_SETUP, U_STANDBY, U_SILENCE, U_RECSTART, U_VOICE, U_RUN, U_FINAL, U_CANCEL, U_SWAP,
 U_STOCKSTOP) = range(11)
NO_TAIL, TAIL, LOOP = range(3)
T_PAD, T_REPLACE, T_UNDO = range(3)
# pad parameters
P_LENGTH, P_START, P_END, P_VOLUME, P_GATE, P_LOOP, P_MUTE, P_SYNC, P_OBPM, P_POLY, P_LP, P_TOP = (
    0x66, 0x67, 0x68, 0x69, 0x6A, 0x6B, 0x6D, 0x6E, 0x6F, 0x70, 0x71, 0x72)
P_PITCH, P_FINE, P_PLAY, P_SPEED, P_VINYL, P_PAN, P_LINK, P_BUS, P_ROLL, P_ATTACK, P_HOLD, P_RELEASE = (
    0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7A, 0x7B, 0x7D, 0x7E, 0x7F)
NEUTRAL = {P_VOLUME: 127, P_PAN: 64, P_PITCH: 0, P_FINE: 0, P_SPEED: 10000, P_PLAY: 0, P_BUS: 0, P_ATTACK: 0,
           P_HOLD: 100, P_RELEASE: 0}
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


def s32(v):
    return struct.unpack('<i', struct.pack('<I', v & 0xFFFFFFFF))[0]


class Voice:
    """The source pad's voice: renders the pad's PCM (stereo, 16-bit) into DRY stems from its first block."""

    def __init__(self, m, pad, pcm, start, end, lp, delay):
        self.m, self.pad, self.pcm, self.start, self.end, self.lp = m, pad, pcm, start, end, lp
        self.delay, self.slot, self.pos, self.block = delay, 7, start, None
        self.loop = False
        self.trigger_block = None
        self.active = False
        self.link_at_trigger = None

    def trigger(self, n):
        """The pad's LOOP and PAD LINK as they stand at the trigger (the run may have changed them)."""
        self.trigger_block = n
        self.loop = self.m.r32(SMPL + self.pad * 0xAC + 0xE4) != 0
        self.link_at_trigger = self.m.r32(SMPL + self.pad * 0xAC + 0x11C)

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
    def __init__(self, img, man=None, skip=()):
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
            elif handler == ZERO:
                uc.mem_write(dst, bytes(size))
        uc.reg_write(ar.UC_ARM_REG_C1_C0_2, uc.reg_read(ar.UC_ARM_REG_C1_C0_2) | (0xF << 20))
        uc.reg_write(ar.UC_ARM_REG_FPEXC, 0x40000000)
        uc.mem_write(RET, b'\x00\xbf\x00\xbf')
        self.sym = man['entries'] if man else {}
        self.log, self.take = [], []
        self.settings = {0x36: 1, 0x24: 3, 0x59: 0, 0x1B: 12000, 0x1A: -1, 0x25: 0}
        self.project = {0: 0, 0xBF: 0, 0xDD: 0, 0xFB: 0}
        self.status = [0] * 160
        self.files = {}
        self.routing = 0
        self.modal = 0
        self.dest = None
        self.final_due = None
        self.voice = None
        self.trigger_ignored = False
        self.fx = dict(L=77, gain=1.0, echo=None, noise=0, input=0)
        self.stem_floor = 0         # stem samples this small read 0 to the module but still reach the return
        self.tx_mix = {}
        self.tx_n = self.rx_n = 0
        self.gate_calls = []
        self.post_times = []
        self.mixer_calls = []
        self.finalized = []
        self.charges = []                               # (pad, START, END, loop point) at each charge request
        self.saves = 0
        self.param_saves = 0
        self.ring = []
        self.texts = []
        self.ui_ms = 0
        self.swap_fail = None
        self.stall = False
        self.ignore = set()                             # recorder commands the model drops (no standby, ...)
        self.fs_log = []
        self.looper_in_real = False
        self.project_no = 1                             # 0x800e1190 (stubbed 'one'): PROJECT_02
        self.overrun_at = None
        self.pending_overrun = False
        self.input_calls = []
        self.sysprm = {0x22: 77}                         # system parameter 0x22: the input level
        for addr, name in STUBS.items():
            if name not in skip and addr not in skip:
                uc.hook_add(UC_HOOK_CODE, self._stub, name, begin=addr, end=addr)
        uc.hook_add(UC_HOOK_CODE, self._mixer, None, begin=MIXER, end=MIXER)
        uc.hook_add(UC_HOOK_CODE, self._popup, None, begin=0x800D3FF0, end=0x800D3FF0)
        uc.hook_add(UC_HOOK_CODE, self._trigger, None, begin=0x800CDBD0, end=0x800CDBD0)
        uc.hook_add(UC_HOOK_CODE, self._unload, None, begin=0x800D9440, end=0x800D9440)
        self.models()
        self.rng = random.Random(0)
        self.dma(61)
        self.keys = set()

    def models(self):
        """The modelled side's state: the recorder engine and its writer, the feed enable, the recorder target,
        the voice slots, the popup and the page."""
        uc = self.uc
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

    # ---- plumbing ----
    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack('<I', self.uc.mem_read(a, 4))[0]

    def r8(self, a):
        return self.uc.mem_read(a, 1)[0]

    def r16(self, a):
        return struct.unpack('<H', self.uc.mem_read(a, 2))[0]

    def regs(self, n=4):
        return [self.uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}')) for k in range(n)]

    def _ret(self, value=0):
        self.uc.reg_write(ar.UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.uc.reg_write(ar.UC_ARM_REG_PC, self.uc.reg_read(ar.UC_ARM_REG_LR))

    def _stub(self, uc, address, size, name):
        r0, r1, r2, r3 = self.regs()
        sr = [s32(x) for x in (r0, r1, r2, r3)]
        value = 0
        if name == 'post':                              # observed; the real post queues the command
            self.log.append(('post', r0))
            self.post_times.append((self.ui_ms, r0))
            return
        elif name == 'target':                          # observed; the real 0x800d48e8 queues it
            self.log.append(('target', r1, sr[2]))
            return
        elif name == 'qput':                            # SMPL TASK's queue: commands and target sets are real
            if self.r8(r0) in (0xA4, 0xA8):
                return
            self.log.append(('other', address, bytes(uc.mem_read(r0, 6))))   # the pad-event dispatcher's others
        elif name == 'qpop':                            # a stalled task takes nothing from the exchange on
            if self.stall:
                head = self.pending()[:1]
                if head and head[0][:2] == ('cmd', 0x40D):
                    self._ret(0)
                    return
            return
        elif name == 'command':                         # SMPL TASK's command dispatcher: 0x40d runs for real
            typ, _, cmd, a1, a2 = struct.unpack('<BBHii', bytes(uc.mem_read(r0, 12)))
            if cmd == 0x40D:
                self.log.append(('exchange', a1, a2))
                return
            self._command(cmd)
        elif name == 'looper_in':                       # the feed's looper input: real only where a check asks
            if self.looper_in_real:
                return
        elif name == 'unlink':
            path = self.cstr(r0)
            self.fs_log.append(('unlink', path))
            value = 0 if self.files.pop(path, None) is not None else -1
        elif name == 'rename':                          # as FatFs: no rename onto an existing name
            a, b = self.cstr(r0), self.cstr(r1)
            self.fs_log.append(('rename', a, b))
            if self.swap_fail != 'rename' and a in self.files and b not in self.files:
                self.files[b] = self.files.pop(a)
        elif name == 'open':
            path = self.cstr(r0)
            self.fs_log.append(('open', path))
            value = 1 if path in self.files else -1
        elif name == 'doom':
            self.log.append(('doom', struct.unpack('<h', bytes(uc.mem_read(r1, 2)))[0]))
            value = 0x55
        elif name == 'get':
            value = self.settings.get(r1, 0)
        elif name == 'set':
            if r1 == 0x25 and self.settings.get(0x25, 0) != sr[2]:
                self.input_calls.append((self.ui_ms, sr[2]))   # the stock setter sends the input volume
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
            value = self.routing if r1 == 0x5C else self.sysprm.get(r1, 0)
        elif name == 'modal':
            value = self.modal
        elif name == 'zero':
            value = 0
        elif name == 'one':
            value = 1
        elif name == 'gate':
            self.gate_calls.append((self.r8(REC_STATE), r0, r1, r2))
        elif name == 'writer':
            data = bytes(uc.mem_read(r1, 4 * r2))
            self.take += [struct.unpack_from('<2h', data, 4 * i) for i in range(r2)]
            frames = struct.unpack('<Q', bytes(uc.mem_read(ENGINE + 0x200, 8)))[0] + r2
            uc.mem_write(ENGINE + 0x200, struct.pack('<Q', frames))
            if self.overrun_at is not None and len(self.take) >= self.overrun_at:   # 0x8017e5b0: the ring full
                self.overrun_at = None
                self.w32(REC_ERR, -0x79)
                self.pending_overrun = True
        elif name == 'ring':                            # SMPL TASK takes the event: a note-on starts the voice
            ev = bytes(uc.mem_read(r0, 6))
            self.ring.append((self.ui_ms, ev[0], ev[1], ev[3]))
            self.log.append(('ring', ev[0], ev[1], ev[3]))
            if self.voice and not self.trigger_ignored and ev[0] == self.voice.pad and 1 <= ev[3] <= 127:
                self.voice.trigger(self.tx_n)
        elif name == 'other':
            self.log.append(('other', address, bytes(uc.mem_read(r0, 6))))
        elif name == 'loadpad':                         # the pad loader: the file's size into the file info
            value = self._load(r0)
        elif name == 'savepads':
            self.param_saves += 1
        elif name == 'charged':                         # 0x800d88c8(pad): the mark cleared, the range now charged
            if r0 < 161:
                info = FILE_INFO + r0 * 36
                self.charges.append((r0, self.r32(info + 0x18), self.r32(info + 0x1C), self.r32(info + 0x20)))
                self.uc.mem_write(info + 0x14, b'\x00')
        self._ret(value)

    def _trigger(self, uc, address, size, _):
        self.log.append(('trigger',) + tuple(self.regs(3)))

    def _unload(self, uc, address, size, _):
        pad = self.uc.reg_read(ar.UC_ARM_REG_R0)
        if pad < 160:
            self.status[pad] = 0

    def path(self, pad):
        """A pad's file, as 0x800d60c8 builds it (internal storage; settings 0x84 = 0)."""
        return f'B:/ROLAND/SP-404MKII/PROJECT_{self.project_no + 1:02d}/SMPL/BANK{pad // 16 + 1}-{pad % 16 + 1:02d}.SMP'

    def file(self, pad):
        return self.files.get(self.path(pad))

    def cstr(self, a):
        return bytes(self.uc.mem_read(a, 256)).split(b'\0')[0].decode('latin-1')

    def _load(self, pad):
        f = self.file(pad)
        info = FILE_INFO + pad * 36
        if f is None:
            self.status[pad] = 0
            return 0
        frames, ch = f['frames'], f['ch']
        for off, v in ((8, ch), (0xC, 0x200), (0x10, 0x200 + 2 * ch * frames), (0x18, 0x200),
                       (0x1C, 0x200 + 2 * ch * frames), (0x20, 0x200)):
            self.w32(info + off, v)
        self.status[pad] = 1
        return 1

    def _mixer(self, uc, address, size, _):
        """The stub mixer: this block's stems from the voice model (DRY: 16-bit samples in the 20-bit stem slots, at
        the capture's scale, as dm-404 reads them)."""
        self.mixer_calls.append([uc.reg_read(ar.UC_ARM_REG_R0), uc.reg_read(ar.UC_ARM_REG_R1),
                                 uc.reg_read(ar.UC_ARM_REG_SP)])
        n = self.tx_n
        frames = self.voice.tick(n) if self.voice else [(0, 0)] * 64
        buf = bytearray(64 * 14 * 4)
        fl = self.stem_floor
        for f, (l, r) in enumerate(frames):
            struct.pack_into('<2i', buf, f * 56, l if abs(l) > fl else 0, r if abs(r) > fl else 0)
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

    def call(self, fn, *args, count=3_000_000):
        uc = self.uc
        for k, v in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), v & 0xFFFFFFFF)
        uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        self.run(fn, RET, count=count)
        return uc.reg_read(ar.UC_ARM_REG_R0)

    def field(self, which, name):
        names, base = (FIELDS_A, self.sym['bnc_aud']) if which == 'a' else (FIELDS_U, self.sym['bnc_ui_state'])
        v = self.r32(base + 4 * names.index(name))
        return v - (1 << 32) if name in SIGNED and v & 0x80000000 else v

    def a(self, name):
        return self.field('a', name)

    def u(self, name):
        return self.field('u', name)

    def undo(self, i):
        base = self.sym['bnc_ui_state'] + 4 * len(FIELDS_U) + 4 * len(UNDO_FIELDS) * i
        r = {k: self.r32(base + 4 * j) for j, k in enumerate(UNDO_FIELDS)}
        r['link'] = s32(r['link'])
        return r

    def undos(self):
        return [self.undo(i) for i in range(UNDOS) if self.undo(i)['used']]

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
        return s32(self.call(PADGET, SMPL, pid, pad))

    def pad_set(self, pid, value, pad):
        return self.call(PADSET, SMPL, pid, value, pad)

    def load_pad(self, pad, frames, start=0, end=None, loop=0, lp=None, tag=None, **params):
        end = frames if end is None else end
        self.files[self.path(pad)] = dict(frames=frames, ch=2, tag=tag or ('pad', pad, frames))
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

    def record(self, pad):
        """Everything the exchange moves with a pad: its parameter record, name and block, and its file."""
        return (bytes(self.uc.mem_read(SMPL + 0xD0 + pad * 0xAC, 0xAC)),
                bytes(self.uc.mem_read(SMPL + 0x6CFC + pad * 24, 24)),
                bytes(self.uc.mem_read(SMPL + 0xF800 + pad * 0x80, 0x80)), repr(self.file(pad)))

    def name(self, pad):
        return bytes(self.uc.mem_read(SMPL + 0x6CFC + pad * 24, 24)).split(b'\0')[0].decode('ascii').rstrip()

    def protect(self, bank, on=True):
        self.uc.mem_write(SMPL + 0x19900, b'\x01')
        self.w32(SMPL + 0x58 + 4 * bank, 1 if on else 0)

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

    def turn(self, delta, shift=False):
        if shift:
            self.keys.add(KEY_SHIFT)
            self.press_keys()
        r = self.event(EV_ENCODER, 0, delta)
        if shift:
            self.keys.discard(KEY_SHIFT)
            self.press_keys()
        return r

    def real_ui(self):
        """The UI dispatcher's state on the RESAMPLE page at run time: no mode holds the keys (0x82dfd314 + 4 < 0),
        no key pairs (0x80b119dc memset to -1 at boot, 0x8003b27e), the page live, its object (0x80053cb8 makes
        it on page entry) with the vtable whose +8 is the patched filter slot."""
        self.w32(PREFILTER, 0xFFFFFFFF)
        self.uc.mem_write(KEY_PAIRS, b'\xff' * 0x80)
        self.uc.mem_write(PAGE_LIVE, struct.pack('<H', 0x0E))
        self.w32(PAGE_PTR, PAGE_OBJ)
        self.w32(PAGE_OBJ, PAGE_VTABLE)

    def dispatch(self, kind, a1=0, a2=0):
        """An event through the UI task's real dispatcher (0x8003b530); keys set their held bits there."""
        self.uc.mem_write(EVENT2, struct.pack('<6h', kind, a1, a2, 0, 0, 0))
        before = len([x for x in self.log if x[0] == 'doom'])
        self.call(UI_DISPATCH, EVENT2)
        return len([x for x in self.log if x[0] == 'doom']) > before

    def pad_event(self, pad, vel, mode=2):
        """A pad event through the (patched) pad-event dispatcher, as the MIDI note-on builds it."""
        ev = bytes([pad, mode, 0, vel if vel else 0xFF, 0xFF if vel else 0x40, 0])
        self.uc.mem_write(MSG, ev + bytes(2))
        before = len(self.ring)
        self.call(GATE_SITE, MSG)
        return len(self.ring) > before

    # ---- SMPL TASK ----
    def pending(self):
        """SMPL TASK's queue, oldest first: ('cmd', cmd, a1, a2), ('target', id, value), ('other', type)."""
        out, i, w = [], self.r32(QREAD), self.r32(QWRITE)
        while i != w:
            b = bytes(self.uc.mem_read(QBASE + 16 * i, 16))
            if b[0] == 0xA4:
                out.append(('cmd',) + struct.unpack_from('<Hii', b, 2))
            elif b[0] == 0xA8:
                out.append(('target',) + struct.unpack_from('<Hi', b, 2))
            else:
                out.append(('other', b[0]))
            i = 0 if i >= QWRAP else i + 1
        return out

    def settle(self):
        if self.pending_overrun and self.r8(REC_STATE) == 2:       # REC TASK, flag 0x20: the stock finalize
            self.pending_overrun = False
            self.finalize()
        if self.r32(QREAD) != self.r32(QWRITE):
            self.call(SMPL_LOOP, 0, 2)                  # the task's loop: every message, in order
        if self.final_due is not None and self.ui_ms >= self.final_due:
            self.final_due = None
            d, n = self.dest, len(self.take)
            if self.load_ok:
                self.load_pad(d, n + 384, start=384, end=384 + n, tag=('take', len(self.finalized)))
                self.uc.mem_write(TEXT, b'New Sample\0')
                self.call(PADNAME, SMPL, d, TEXT)
                base = SMPL + d * 0xAC
                self.w32(base + 0xD4, self.r32(base + 0xD4) + 12)    # the stock zero-cross adjust moves START
                rng = (self.r32(base + 0xD4), self.r32(base + 0xD8), self.r32(base + 0xD4))
                info = FILE_INFO + d * 36
                for k, v in enumerate(rng):                 # the finalize's end: 0x800d8b40(pad, START, END, START),
                    self.w32(info + 0x18 + 4 * k, v)        # 0x800d6390, 0x800d7508: the take charged with its range
                self.charges.append((d,) + rng)
            self.settings[0x59] = 0
            self.w32(TARGET_VALUES + 4, 0xFFFFFFFF)

    def _command(self, cmd):
        """The recorder commands as SMPL TASK runs them (modelled), at the moment the task takes them."""
        if cmd in self.ignore:
            return
        state = self.r8(REC_STATE)
        if cmd == 5 and self.voice:
            self.voice.stop()
        elif cmd == 0x14 and state == 0:
            self.uc.mem_write(REC_STATE, b'\x01')
            self.uc.mem_write(REC_SUB, b'\x01')
            self.w32(REC_ERR, 0)                        # the stock standby clears the error word
            self.w32(FEED_ON, 1)                        # as the stock standby does
            self.uc.mem_write(ENGINE + 0x1C0, struct.pack('<Q', 0x800))
            self.uc.mem_write(ENGINE + 0x200, struct.pack('<Q', 0))
            self.uc.mem_write(ENGINE + 0x208, struct.pack('<q', -1))
            self.take = []
        elif cmd == 0x17 and state in (1, 3):
            self.uc.mem_write(REC_STATE, b'\x02')
            self.uc.mem_write(REC_SUB, b'\x02')
            self.dest = self.r32(TARGET_VALUES) * 16 + self.r32(TARGET_VALUES + 4)
        elif cmd == 0x18 and state == 1:
            self.uc.mem_write(REC_STATE, b'\x00')
            self.uc.mem_write(REC_SUB, b'\x00')
            self.w32(TARGET_VALUES + 4, 0xFFFFFFFF)
        elif cmd == 0x18 and state == 2:
            self.finalize()
        elif cmd == 0x1A and state == 2:
            self.uc.mem_write(REC_STATE, b'\x00')
            self.uc.mem_write(REC_SUB, b'\x00')
            self.take = []
            self.w32(TARGET_VALUES + 4, 0xFFFFFFFF)
        elif cmd == 0xD:
            self.saves += 1

    def finalize(self):
        """REC_STOP in state 2, or the stock recorder ending the take itself: state 0 before the 500 ms wait."""
        self.uc.mem_write(REC_STATE, b'\x00')
        self.uc.mem_write(REC_SUB, b'\x00')
        self.finalized.append(dict(first_sound=struct.unpack('<q', bytes(self.uc.mem_read(ENGINE + 0x208, 8)))[0],
                                   frames=len(self.take), snap=self.settings.get(0x59),
                                   length=self.settings.get(0x24), err=s32(self.r32(REC_ERR))))
        self.final_due = self.ui_ms + 600

    def stock_stop(self, err, partial=True):
        """The stock recorder ends the take itself (a full ring, the card full): it finalizes what it has."""
        self.w32(REC_ERR, err)
        if partial:
            self.finalize()
        else:
            self.uc.mem_write(REC_STATE, b'\x00')
            self.uc.mem_write(REC_SUB, b'\x00')
            self.take = []
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
        for k, gk in fx.get('ring', ()):              # a symmetric low ring around the main delay (both sides)
            for tt in (t - k, t + k):
                a, b = self.tx_mix.get(tt, (0, 0))
                l, r = l + a * gk, r + b * gk
        if fx['noise']:
            l, r = l + self.rng.choice((-1, 1)) * fx['noise'], r + self.rng.choice((-1, 1)) * fx['noise']
        if fx['input'] and self.settings.get(0x25):     # music on the input, heard while EXT SOURCE is on
            l, r = l + fx['input'] * ((R * 7) % 5 - 2), r + fx['input'] * ((R * 3) % 5 - 2)
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
        return bytes(self.uc.mem_read(POPUP_TEXT, 64)).split(b'\0')[0].decode('latin-1')


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


def run_bounce(m, src_pad, mode_turns=0, budget=4000, exit_at=None, during=None, target=None):
    """The gesture, VALUE turns, the target (VALUE pressed until it shows), REC, then audio periods until the
    controller is idle again."""
    r = m.gesture(src_pad)
    m.ui(1)
    for _ in range(abs(mode_turns)):
        m.turn(1 if mode_turns > 0 else -1)
        m.ui(1)
    if m.u('state') != U_SETUP:
        return dict(gesture=r, setup=False)
    if target is not None:
        for _ in range(3):
            if m.u('target') == target:
                break
            m.tap(KEY_VALUE)
            m.ui(1)
    setup_text = m.popup()
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
    return dict(gesture=r, setup=True, states=states, popup=m.popup(), setup_text=setup_text)


def expected_rx(m, first, n):
    return [m.rx_value(first + i) for i in range(n)]


def check_take(m, label, src_frames, L, mode, win, lp_frames=None):
    """The take = RX frames from F0; START/END on [F0 + L, F0 + L + win); dry: the source's own frames."""
    f0 = m.a('f0')
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
    want_lp = start + (lp_frames or 0)
    check(m.pad_get(0x71, d) == want_lp, f'{label}: loop point = START + {lp_frames or 0} ({m.pad_get(0x71, d)})')
    check_charge(m, label, d)
    window = take[L:L + win]
    check(len(window) == win, f'{label}: the take covers the window ({len(take)} frames)')
    if src_frames is not None:
        check(window == src_frames, f'{label}: dry, the window is the source\'s own frames')
    return window


def check_charge(m, label, pad):
    """Playback reads the pad's charge, made from its range when it was charged: the finalize charges the take with
    its own range; the setters only store a new range and mark it; 0x800d7508 charges marked pads again. The
    bounce's last charge must hold its final START, END and loop point."""
    base = SMPL + pad * 0xAC
    final = (m.r32(base + 0xD4), m.r32(base + 0xD8), m.r32(base + 0xFC))
    info = FILE_INFO + pad * 36
    charged = [c[1:] for c in m.charges if c[0] == pad]
    check(charged and charged[-1] == final == (m.r32(info + 0x18), m.r32(info + 0x1C), m.r32(info + 0x20)),
          f'{label}: the pad was last charged with its final START, END and loop point, so it plays START..END and '
          f'loops at END (charged {charged[-1] if charged else None}, final {final})')


def neutral_ok(m, pad):
    got = {pid: m.pad_get(pid, pad) for pid in NEUTRAL}
    return got == NEUTRAL, got


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
    check(sorted(p['address'] for p in man['patches']) == [0x1D090, 0x1D0C2, 0x8006B950, 0x800BEF10, 0x8012DB58],
          "the code sites: TX, RX, popup tick, pad-event dispatcher, the RESAMPLE page's tick")
    diff = [i for i in range(len(parent)) if img[i] != parent[i] and i not in allowed]
    check(not diff, f'no other byte of the parent changed ({len(diff)} found)')
    rows_in, rows_out = scatter(parent), scatter(img)
    check(rows_out[:-2] == rows_in, 'scatter table = parent rows (start fix included) + two rows')
    load, dst, n, fn = rows_out[-2]
    check((dst, n, fn) == (man['blob_base'], man['blob_size'], COPY), 'a copy row puts the blob at its base')
    bss_at, bss_n = man['bss']
    check(rows_out[-1] == [0, bss_at, bss_n, ZERO] and bss_at >= dst + n and
          bss_at <= man['entries']['bnc_aud'] < bss_at + bss_n and bss_at <= man['entries']['bnc_ui_state'] < bss_at + bss_n,
          'a zero-fill row clears the module\'s state (.bss) at boot')
    check(sha(img[load - FLASH:load - FLASH + n]) == man['blob_sha256'], 'blob bytes match manifest')
    lo, hi = man['slot']
    check(dst == lo and bss_at + bss_n <= hi <= 0x83FED000,
          'blob and state inside their slot, below 0x83FED000 (CPU meter, start fix)')
    check(all(not (max(d_, lo) < min(d_ + k, hi)) for _, d_, k, _f in rows_in), 'no parent row overlaps the slot')
    check(FLASH + len(img) <= 0x60376000, f'APP1 ends below the kit PCM planning boundary ({0x60376000 - FLASH - len(img)} '
                                          f'bytes to spare)')
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
    # the pad-event dispatcher, idle: every kind of event takes the parent's own path with the same event
    paths = []
    for m in (old, new):
        seen = []
        for ev in ([3, 4, 0, 100, 0xFF, 0], [3, 4, 0, 0xFF, 0x40, 0], [0xA0, 2, 0, 90, 0xFF, 0], [0xA1, 4, 0, 1, 0xFF, 1],
                   [0xA4, 0x40D, 0, 0, 0, 0], [0xA8, 0, 1, 0, 0, 0], [0xA5, 0, 0, 0, 0, 0], [0xAB, 0, 0, 0, 0, 0]):
            m.ring, m.log = [], []
            m.uc.mem_write(MSG, bytes(b & 0xFF for b in ev) + bytes(2))
            for k in range(4, 12):
                m.uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), 0x3000 + k)
            m.uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
            m.uc.reg_write(ar.UC_ARM_REG_R0, MSG)
            m.run(GATE_SITE, RET, sp=STACK - 0x200)
            seen.append(([x for x in m.log if x[0] in ('ring', 'other')],
                         [m.uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}')) for k in range(4, 12)],
                         m.uc.reg_read(ar.UC_ARM_REG_SP)))
        paths.append(seen)
    check(paths[0] == paths[1], 'gate bridge, idle: pads, 0xa1, commands and the other events take the parent\'s own '
                                'paths with the same bytes; r4-r11 and sp as stock')
    note('bridges against the parent')


def interface_checks(img, man):
    """The stock interfaces the run relies on, with the stock code itself running."""
    m = Machine(img, man, skip=('get', 'set'))
    m.w32(0x82E01144, 0x8021CD10)                      # the settings object's vtable, set by its constructor
    sent = []
    m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: (sent.append(tuple(m.regs(4)[1:])), m._ret(0)), None,
                  begin=0x800D8118, end=0x800D8118)
    out = []
    for v in (1, 0, 0, 1):
        sent.clear()
        m.call(0x800DD0C0, 0x82E01144, 0x25, v, 0)
        out.append((v, s32(m.call(0x800D94D8, 0x82E01144, 0x25, 0)), list(sent)))
    check(out == [(1, 1, [(0x22, 0, 77)]), (0, 0, [(0x22, 0, 0)]), (0, 0, []), (1, 1, [(0x22, 0, 77)])],
          f'EXT SOURCE through the stock settings setter: off sends input volume 0 (effects-chip parameter 0x22), '
          f'on sends the input level, an unchanged value sends nothing ({out})')
    note('stock interfaces: EXT SOURCE')


def gate_checks(img, man):
    m = boot(img, man)
    m.w32(m.sym['bnc_own'], 1)
    m.w32(m.sym['bnc_aud'] + 4 * FIELDS_A.index('pad'), 5)
    passed = [m.pad_event(3, 100), m.pad_event(5, 100), m.pad_event(3, 0), m.pad_event(0xA1, 64, mode=4),
              m.pad_event(5, 127, mode=4)]
    check(passed == [False, False, True, False, False] and m.u('dropped') == 4,
          f'gate, a bounce owning the recorder: every note-on is dropped (MIDI, the current pad), note-offs pass '
          f'({passed}, {m.u("dropped")} dropped)')
    m.w32(m.sym['bnc_expect'], 1)
    passed = [m.pad_event(3, 100), m.pad_event(5, 90, mode=4), m.pad_event(5, 90, mode=4)]
    check(passed == [False, True, False] and m.r32(m.sym['bnc_expect']) == 0,
          'gate: the run\'s own trigger passes once, by its pad, whatever its velocity; then the gate closes again')
    m.w32(m.sym['bnc_own'], 0)
    check(m.pad_event(3, 100) and m.pad_event(0xA1, 20, mode=4), 'gate, idle: note-ons pass')
    note('the pad-event gate')


def filter_checks(img, man):
    m = boot(img, man)
    m.load_pad(0, 4800)
    for kind, a1, a2 in ((EV_KEY, KEY_REC, 0), (EV_KEY_UP, KEY_REC, 0), (EV_ENCODER, 0, 1), (EV_KNOB, 1, 64),
                         (EV_PAD, 0, 100), (EV_PAD_UP, 0, 0), (0x13, 0, 0), (0x23, 0xD, 0), (8, 0, 0),
                         (EV_KEY, KEY_VALUE, 0)):
        r, passed = m.event(kind, a1, a2)
        check(passed and r == 0x55, f'idle: event type {kind:#x} goes to DOOM OS\'s filter and its result comes back')
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
        check(passed and r == 0x55 and mm.u('state') == U_IDLE, f'no gesture when {name}: the pad goes on to DOOM OS')
    mg = boot(img, man)
    mg.load_pad(0, 4800)
    r, passed = mg.gesture(0)
    mg.ui(1)
    check(r == 1 and not passed and mg.u('state') == U_SETUP and mg.popup() == 'BOUNCE A-1>A-2\nNO TAIL',
          f'gesture: RESAMPLE held + sample pad: setup popup, the pad is not played ({mg.popup()!r})')
    for kind, a1, a2 in ((EV_KEY, 0x16, 0), (EV_KEY_UP, 0x16, 0), (EV_KNOB, 3, 30), (EV_PAD, 3, 90), (EV_PAD_UP, 3, 0),
                         (0x12, 3, 50), (EV_ENCODER, 1, 1), (EV_KEY_UP, KEY_VALUE, 0)):
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
    # the target: VALUE pressed steps TO PAD -> REPLACE -> TO PAD; SHIFT + VALUE steps, clamped; the mode stays
    mg.turn(1)
    seen = []
    for act in ('press', 'press', 'shift+', 'shift+', 'shift-', 'shift-', 'turn+'):
        if act == 'press':
            mg.tap(KEY_VALUE)
        else:
            mg.turn(1 if act[-1] == '+' else -1, shift=act.startswith('shift'))
        mg.ui(1)
        seen.append(mg.popup())
    check(seen == ['REPLACE A-1\nTAIL', 'BOUNCE A-1>A-2\nTAIL', 'REPLACE A-1\nTAIL', 'REPLACE A-1\nTAIL',
                   'BOUNCE A-1>A-2\nTAIL', 'BOUNCE A-1>A-2\nTAIL', 'BOUNCE A-1>A-2\nLOOP'],
          f'target: VALUE pressed toggles TO PAD / REPLACE, SHIFT + VALUE steps and stops at the ends, VALUE alone the '
          f'mode ({seen})')
    mg.tap(KEY_EXIT)
    mg.ui(1)
    check(mg.u('state') == U_IDLE and mg.popup() == 'BOUNCE CANCELLED\nNOTHING CHANGED' and
          not [x for x in mg.log if x[0] in ('post', 'set', 'target')],
          'EXIT in setup: cancelled, nothing posted or set')
    mg.ui(300)
    r, passed = mg.event(EV_PAD, 0, 100)
    check(passed, 'after EXIT a sample pad plays again (DOOM OS gets the event)')
    # the choice is kept as soon as it is made: EXIT (or a refusal) does not lose it
    mg.gesture(0)
    mg.ui(1)
    first = mg.popup()
    mg.tap(KEY_VALUE)
    mg.ui(1)
    mg.tap(KEY_EXIT)
    mg.ui(300)
    mg.gesture(0)
    mg.ui(1)
    again = mg.popup()
    mg.tap(KEY_EXIT)
    mg.ui(300)
    check(first == 'BOUNCE A-1>A-2\nLOOP' and again == 'REPLACE A-1\nLOOP',
          f'the target and the mode are kept once picked, not only once a run starts: after EXIT the gesture offers '
          f'them again ({first!r}, {again!r})')
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
                              ('pattern running (system flag)', lambda mm: mm.w32(SEQ_RUN, 1), 'STOP PATTERN FIRST')):
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
    # protected banks are never a destination: the source's own bank, then bank B, skipped
    mq = boot(img, man)
    mq.load_pad(0, 4800)
    mq.protect(0)
    mq.protect(1)
    mq.gesture(0)
    mq.ui(1)
    check(mq.popup() == 'BOUNCE A-1>C-1\nNO TAIL', f'protected banks A and B: the destination is C-1 ({mq.popup()!r})')
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
          m.settings[0x1B] == 12000 and not [x for x in m.log if x[0] == 'set' and x[1] == 0x1B],
          'after the run: feed enable, REC length, END Snap, destination restored; REC BPM never written')
    name = m.name(1)
    check(m.saves >= 1 and name.startswith('A1 L77 M77 P61.') and name.endswith(' D0') and len(name) <= 23,
          f'the pad is named with the run ({name}) and saved')
    sets = [x for x in m.log if x[0] == 'set']
    check(sets[:3] == [('set', 0x24, 6, 0), ('set', 0x59, 0, 0), ('set', 0x1A, 1, 0)],
          f'pinned before standby: REC length FREE, END Snap off, destination A-2; REC BPM left alone ({sets[:3]})')
    posts = [x[1] for x in m.log if x[0] == 'post']
    check(posts == [5, 0x2A, 0x14, 0x17, 5, 0x18, 0xD],
          f'commands: sound off, seq sound off, standby, start, sound off, stop, save ({[hex(x) for x in posts]})')
    trig = [x for x in m.log if x[0] == 'trigger']
    rings = [x for x in m.log if x[0] == 'ring']
    check(trig == [('trigger', 0, 127, 1)] and rings == [('ring', 0, 4, 127)],
          f'the source is triggered once at velocity 127, mode 1: the stock pad note posts it through the gate '
          f'({rings})')
    ok, got = neutral_ok(m, 1)
    check(ok, f'the bounced pad: printed settings neutral, BUS FX Assign DRY ({got})')
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

    # onsets a threshold crossing gets wrong: the true L is the estimate's, 77 (P61 D0); the onset moves with the
    # attack's shape and with a level step between the stems and the return (bounce-3-test2 on the unit: an onset 3
    # frames early from a loop's attack, L69 M69 against L72 M72 at the same P66)
    onsets = []
    for label, attack, gain, echo in (('a 32-frame attack', 32, 1.0, None), ('a 20 ms attack, RX +6 dB', 960, 2.0, None),
                                      ('a 20 ms attack, RX -6 dB', 960, 0.5, None),
                                      ('a 10 ms attack, an echo and RX +3.5 dB', 480, 1.5, (1500, 0.5))):
        m, pcm, res = native_case(label, NO_TAIL, 0, attack=attack, gain=gain, echo=echo)
        onsets.append((label, m.u('r_meas'), m.u('r_l')))
        # the same levels: the matched thresholds cross together, L is exact; a level step can still move the onset
        # by a frame, which the rule cannot tell from T1's one-frame spread (138 or 139), so L is right to a frame
        exact = gain == 1.0 and echo is None
        check(res['popup'] == 'BOUNCED A-1\nON A-2' and (m.u('r_l') == 77 if exact else abs(m.u('r_l') - 77) <= 1),
              f'{label}: L = the true 77{"" if exact else " to a frame"} (onset {m.u("r_meas")}, estimate '
              f'{m.u("r_est")}, used {m.u("r_l")})')
        if exact:
            check_take(m, label, pcm, 77, NO_TAIL, 6000)
    check(any(meas not in (0, 77) for _, meas, _ in onsets),
          f'those onsets are off the true L, so the rule, not the onset, keeps L exact ({onsets})')
    # LOOP of a loop whose pass starts softly: the window is the second pass, frame for frame
    m, pcm, res = native_case('LOOP soft start', LOOP, 2, n=5000, loop=1, attack=32)
    check(m.u('r_l') == 77, f'LOOP, a 32-frame attack: L = the true 77 (onset {m.u("r_meas")}, used {m.u("r_l")})')
    check_take(m, 'LOOP, a 32-frame attack', pcm[:5000], 77, LOOP, 5000)
    # the unit's return departs from silence 7 frames before its main delay (bounce-3-test3: START 457, the first
    # non-zero frame 450, L 73 at P66 D-1): a low symmetric ring around L. The take starts where the return departs,
    # so it holds the whole attack; L stays the main delay (the name reads L73-7)
    ring = [(k, 0.0005 * (8 - k)) for k in range(1, 8)]

    def ring_case(n, loop, turns):
        mm = boot(img, man, d=-1, p=65, L=73, seed=rng.randint(0, 1 << 30))
        mm.fx['ring'] = ring
        src = pcm_burst(n, rng.randint(0, 1 << 30))
        mm.load_pad(0, n, loop=loop)
        mm.voice = Voice(mm, 0, src, 0, n, 0, 1)
        return mm, run_bounce(mm, 0, turns)

    m, res = ring_case(6000, 0, 0)
    first = next((i for i, f in enumerate(m.take) if f != (0, 0)), None)
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and m.u('r_l') == 73 and first == 66 and
          m.u('r_start') == 384 + 66 and m.u('r_end') == 384 + 66 + 6000 and m.name(1).startswith('A1 L73-7 M73'),
          f'NO TAIL, a return departing 7 frames before L 73: START on its first frame 66 (first non-zero {first}, '
          f'START {m.u("r_start") - 384}, L {m.u("r_l")}, {m.name(1)!r})')
    # LOOP of a loop through the same return: one pass from the departure, so the take's last 7 frames hold nothing
    # of the next pass (its ring starts right after the window); with LOOP off the bounce ends clean
    m, res = ring_case(5000, 1, 2)
    f0, lw = m.a('f0'), m.u('r_start') - 384
    kept = m.tx_mix
    m.tx_mix = {t: v for t, v in kept.items() if t < f0 + 5000}         # the next pass off
    alone = [m.rx_value(f0 + lw + 5000 - 7 + i) for i in range(7)]
    m.tx_mix = kept
    tail = m.take[lw + 5000 - 7:lw + 5000]
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and lw == 66 and tail == alone,
          f'LOOP through a return departing 7 frames early: the window starts on the departure ({lw}) and its last 7 '
          f'frames hold nothing of the next pass ({tail == alone})')
    # The take's start is found in the return alone (bounce-3-test5 on the unit: D1 L72-3 M69 P66.1 D-1, START 453, the
    # take's first non-zero sample at 450). A sharp attack after three +-1 samples that the stems do not show (they
    # still reach the return), through a 6-frame pre-ring whose last 3 frames pass -48 dB, so the onset reads 69 against
    # the estimate 72: the take starts on the return's first non-zero frame, no silence in front, nothing cut
    ring6 = [(1, 0.06), (2, 0.03), (3, 0.017), (4, 0.004), (5, 0.0012), (6, 0.0002)]

    def unit_source(n, lead, zeros=0):
        rr = random.Random(77)
        body = [(rr.randint(-3000, 3000), rr.randint(-3000, 3000)) for _ in range(n)]
        return ([(0, 0)] * zeros + [(v, v) for v in lead] + [(8000, -8000)] + body)[:n]

    def unit_case(src, n, loop, turns, rings, floor=0):
        mm = boot(img, man, d=-1, p=66, L=72, seed=rng.randint(0, 1 << 30))
        mm.fx['ring'] = rings
        mm.stem_floor = floor
        mm.load_pad(0, n, loop=loop)
        mm.voice = Voice(mm, 0, src, 0, n, 0, 1)
        return mm, run_bounce(mm, 0, turns)

    def first_nz(take):
        return next((i for i, f in enumerate(take) if f != (0, 0)), None)

    m, res = unit_case(unit_source(6000, (1, -1, 1)), 6000, 0, 0, ring6, floor=1)
    first, st = first_nz(m.take), m.u('r_start') - 384
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and m.u('r_l') == 72 and m.u('r_meas') == 69 and first == 69 and
          st == first and m.u('r_end') - 384 == st + 6000,
          f'three +-1 samples the stems do not show, then an attack through a 6-frame pre-ring: START on the return\'s '
          f'first non-zero frame (first {first}, START {st}, {m.name(1)!r})')
    # the unit's own numbers: on test5 this reads L72-3 M69 with START 3 frames after the take's first non-zero sample.
    # The source's sound begins 19 frames into its first block; the return's main part passes -48 dB from its first
    # frame, 3 before L; one isolated low sample 25 frames ahead of the main delay (a far tap of the pre-ring) is the
    # take's first non-zero frame, 22 frames before the main part
    ring_far = [(1, 0.06), (2, 0.03), (3, 0.017), (25, 0.00015)]
    m, res = unit_case(unit_source(6000, (), zeros=19), 6000, 0, 0, ring_far)
    first, st = first_nz(m.take), m.u('r_start') - 384
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and m.u('r_l') == 72 and m.u('r_meas') == 69 and first == 66 and
          st == first,
          f'the unit\'s L72-3 M69 (a source 19 frames into its block, an isolated sample 22 frames before the return\'s '
          f'main part): START on the take\'s first non-zero frame (first {first}, START {st}, {m.name(1)!r})')
    # LOOP through the first return: one pass from the departure, so the window ends exactly where the next pass's
    # return departs (its pre-ring begins on the frame after the window)
    n = 5000
    m, res = unit_case(unit_source(n, (1, -1, 1)), n, 1, 2, ring6, floor=1)
    t0, f0, st, end = m.a('t0'), m.a('f0'), m.u('r_start') - 384, m.u('r_end') - 384
    kept = m.tx_mix
    m.tx_mix = {t: v for t, v in kept.items() if t < t0 + 2 * n}           # the next pass off
    alone = [m.rx_value(f0 + end - 6 + i) for i in range(7)]
    m.tx_mix = kept
    window_end, after = m.take[end - 6:end], m.take[end] if end < len(m.take) else None
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and st == 69 and end == st + n and window_end == alone[:6] and
          after is not None and after != alone[6],
          f'LOOP through the same return: the window starts on its departure ({st}) and ends on the frame before the next '
          f'pass\'s return departs ({end}: last 6 frames without it {window_end == alone[:6]}, the next frame with it '
          f'{after != alone[6]})')
    # the name with all its fields: from A-12, after a take that calibrated the boot, it reads 24 characters
    # (as 'A12 L73-7C M73 P65.5 D-1') and the stock name keeps 23. P's tenth goes, so D stays
    m, res = ring_case(3000, 0, 0)
    src = pcm_burst(3000, rng.randint(0, 1 << 30))
    m.load_pad(11, 3000)
    m.voice = Voice(m, 11, src, 0, 3000, 0, 1)
    m.take, m.finalized = [], []
    run_bounce(m, 11, 0)
    name = m.name(m.u('dst'))
    full = f'A12 L{m.u("r_l")}-{m.u("r_l") - (m.u("r_start") - 384)}C M{m.u("r_meas")} P'
    check(m.u('cal_valid') == 1 and name.startswith(full) and name.endswith(' D-1') and '.' not in name and
          len(full) + len('65.5 D-1') > 23 and len(name) <= 23,
          f'a name longer than the stock 23 characters keeps D ({name!r})')
    # the other reading of the unit: a pure 66-frame return at P65.5 D-1, the estimate 73 seven frames long. The
    # departure finds the return's first frame there too (L stays the estimate; the window starts at 66)
    m, pcm, res = native_case('pure 66', NO_TAIL, 0, d=-1, p=65, L=66)
    check(m.u('r_start') == 384 + 66 and m.take[66:66 + 6000] == pcm,
          f'a pure 66-frame return under an estimate of 73: START on its first frame, the take the source frame for '
          f'frame (START {m.u("r_start") - 384}, L {m.u("r_l")}, {m.name(1)!r})')
    # an onset 5 frames below the estimate is not used, nor one 20 frames late (a slow effect): the estimate is
    m, pcm, res = native_case('L-5', NO_TAIL, 0, L=72)
    check(m.u('r_meas') == 72 and m.u('r_l') == 77, f'an onset 5 frames from the estimate is not used ({m.u("r_l")})')
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
    check_take(m, 'LOOP, loop point 1200', None, 77, LOOP, 3800)
    check(m.a('f0') == m.a('t0') + 5000, 'LOOP: F0 = T0 + one pass')
    check(m.pad_get(0x6B, 1) != 0 and m.pad_get(0x6B, 0) != 0, 'LOOP: the bounced pad loops; the source still loops')
    m.gesture(0)
    m.ui(1)
    check(m.popup() == 'BOUNCE A-1>A-3\nLOOP', f'the mode used last (LOOP) is offered first next time ({m.popup()!r})')
    m.tap(KEY_EXIT)

    # LOOP of a one-shot: LOOP on for the run, back off before the stop
    m, pcm, res = native_case('LOOP one-shot', LOOP, 2, n=5000, echo=(1000, 0.4))
    check_take(m, 'LOOP of a one-shot', None, 77, LOOP, 5000)
    check(m.pad_get(0x6B, 0) == 0 and m.pad_get(0x6B, 1) != 0,
          'LOOP of a one-shot: the source is a one-shot again, the bounce loops')

    # TAIL of a looped pad: plays once (LOOP off for the run)
    m, pcm, res = native_case('TAIL loop', TAIL, 1, n=4000, loop=1, echo=(2000, 0.3))
    last = max(i for i in range(len(m.take)) if max(abs(m.take[i][0]), abs(m.take[i][1])) > 8)
    check_take(m, 'TAIL of a looped pad', None, 77, TAIL, last + 1 - 77)
    check(m.pad_get(0x6B, 0) != 0 and m.pad_get(0x6B, 1) == 0, 'TAIL of a looped pad: the source loops again')

    # NO TAIL of a pitched one-shot: the window is the voice's own length
    m = boot(img, man, seed=3)
    played = pcm_burst(4321, 12)                     # what the pitched voice delivers
    m.load_pad(0, 5000, p73=5)
    m.voice = Voice(m, 0, played, 0, 4321, 0, 1)
    res = run_bounce(m, 0, 0)
    check_take(m, 'NO TAIL, pitched one-shot', played, 77, NO_TAIL, 4321)
    check(m.pad_get(P_PITCH, 1) == 0 and m.pad_get(P_PITCH, 0) == 5, 'pitched one-shot: the bounce is at PITCH 0, '
                                                                       'the source keeps +5')

    # the boot's calibration: a soft start after a calibrated run uses the onset L
    m = boot(img, man, d=-1, p=66, L=73, seed=5)
    pcm = pcm_burst(3000, 21)
    m.load_pad(0, 3000)
    m.voice = Voice(m, 0, pcm, 0, 3000, 0, 1)
    run_bounce(m, 0, 0)
    e16 = 2216 - (m.u('r_p16') & 1023) + 1024 * m.u('r_d')        # T1's relation at this take's P and D, x 16
    check(m.u('cal_valid') == 1 and m.u('r_l') == 73 and m.u('cal_off') == 16 * 73 - e16,
          f'calibration: the first run\'s onset L 73 is kept, as an offset on T1\'s relation ({m.u("cal_off")}/16)')
    soft = pcm_burst(9000, 22, silence=6000)
    m.load_pad(2, 9000)
    m.voice = Voice(m, 2, soft, 0, 9000, 0, 2)
    m.take, m.finalized = [], []
    run_bounce(m, 2, 0)
    check(m.u('r_est') == 73 and m.u('r_l') == 73, f'calibration: a later soft start uses 73 (est {m.u("r_est")})')
    check(m.take[73:73 + 9000] == soft, 'calibration: that take is frame-exact')
    name = m.name(3)
    check(name.startswith('A3 L73C M-- P'), f'calibration: the name marks the boot\'s L and no onset ({name})')
    # P moves within a boot (bounce-3-test3 on the unit: P65.1 for NO TAIL, then P62.0 for LOOP in one session; the
    # LOOP take used the boot's L73 although its own phase and its onset M76 both said 76): the calibration is an
    # offset on each take's own P and D, so the next take follows the new phase
    m = boot(img, man, d=-1, p=65, L=73, seed=6)
    first = pcm_burst(3000, 24)
    m.load_pad(0, 3000)
    m.voice = Voice(m, 0, first, 0, 3000, 0, 1)
    run_bounce(m, 0, 0)
    calibrated = (m.u('cal_valid'), m.u('r_l'), m.u('cal_off'))
    m.dma(62)                                           # the eDMA phase moves by 3 frames ...
    m.rx()                                              # ... D from -1 to 0 (one RX block more) ...
    m.fx['L'] = 76                                      # ... and the round trip follows T1's relation: 138.5 - 62.5
    sharp = pcm_burst(3000, 25)
    m.load_pad(2, 3000)
    m.voice = Voice(m, 2, sharp, 0, 3000, 0, 1)
    m.take, m.finalized = [], []
    run_bounce(m, 2, 0)
    check(calibrated[:2] == (1, 73) and m.u('r_d') == 0 and m.u('r_l') == 76 and m.u('r_start') == 384 + 76 and
          m.take[76:76 + 3000] == sharp,
          f'P moves within the boot ({calibrated} -> P{m.u("r_p16") / 16:.1f} D{m.u("r_d")}): L 76 from this take\'s '
          f'own phase, not the boot\'s 73 (est {m.u("r_est")}, onset {m.u("r_meas")}, used {m.u("r_l")})')

    # NO TAIL of a looped pad at its own rate: exactly one pass; the bounce loops from the source's own loop point
    m, pcm, res = native_case('NO TAIL loop', NO_TAIL, 0, n=5000, loop=1, lp=1000)
    check_take(m, 'NO TAIL, a looped pad', pcm[:5000], 77, NO_TAIL, 5000, lp_frames=1000)
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


def settings_checks(img, man):
    """The bounced pad's settings, read back through the stock getter."""
    def source(**kw):
        m = boot(img, man, seed=kw.pop('seed', 31))
        pcm = pcm_burst(3000, 41)
        loop = kw.pop('loop', 0)
        lp = kw.pop('lp', None)
        m.load_pad(0, 3000, loop=loop, lp=lp)
        for pid, v in kw.items():
            m.pad_set(int(pid[1:], 16), v, 0)
        m.voice = Voice(m, 0, pcm, 0, 3000, lp or 0, 1)
        return m, pcm

    perf = dict(p6d=3, p7b=6, p70=0x26, p6a=0)          # MUTE GROUP 3, Roll 6, Polyphonic (bit 5 + stretch 3), GATE off
    printed = dict(p69=90, p78=30, p7a=2, p7d=40, p7e=55, p7f=20, p77=0)
    m, pcm = source(**perf, **printed)
    src_before = {pid: m.pad_get(pid, 0) for pid in range(0x69, 0x80)}
    res = run_bounce(m, 0, 1)                            # TAIL (a printed source at its own rate)
    got = {pid: m.pad_get(pid, 1) for pid in (P_MUTE, P_ROLL, P_POLY, P_GATE)}
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and got == {P_MUTE: 3, P_ROLL: 6, P_POLY: 0x26, P_GATE: 0},
          f'performance settings copied: MUTE GROUP 3, Roll 6, Polyphonic 0x26, GATE off ({got})')
    ok, neutral = neutral_ok(m, 1)
    check(ok, f'printed settings neutral: VOLUME 127, PAN 64, BUS FX DRY, envelope 0/100/0 ... ({neutral})')
    check(m.pad_get(P_VINYL, 1) == 1 and m.pad_get(P_SYNC, 1) == 0 and m.pad_get(P_LINK, 1) == 0,
          'no TEMPO SYNC: VINYL MODE the stock default (on), PAD LINK off')
    check({pid: m.pad_get(pid, 0) for pid in range(0x69, 0x80)} == src_before, 'the source\'s settings are untouched')
    # GATE switched on clears the poly bit (the stock setter's rule); the bounce gets what the source has
    m, pcm = source(p6a=0, p70=0x20, seed=32)
    m.pad_set(P_GATE, 1, 0)
    run_bounce(m, 0, 1)
    check(m.pad_get(P_POLY, 0) == 0 and m.pad_get(P_POLY, 1) == 0 and m.pad_get(P_GATE, 1) == 1,
          'GATE switched on cleared the source\'s poly bit (stock); the bounce: GATE on, poly off, as the source')
    # TEMPO SYNC: copied with its VINYL MODE (sync needs VINYL off)
    m, pcm = source(p6e=1, p77=0, seed=33)
    res = run_bounce(m, 0, 1)
    check(m.pad_get(P_SYNC, 1) == 1 and m.pad_get(P_VINYL, 1) == 0 and res['setup_text'] == 'BOUNCE A-1>A-2\nTAIL',
          f'TEMPO SYNC copied with VINYL MODE off ({m.pad_get(P_SYNC, 1)}, {m.pad_get(P_VINYL, 1)})')
    # NO TAIL of a loop with its loop-point flag: the bounce keeps both
    m, pcm = source(loop=1, lp=500, p72=1, seed=34)
    res = run_bounce(m, 0, 0)
    check(m.pad_get(P_LOOP, 1) == 1 and m.pad_get(P_TOP, 1) == 1 and m.pad_get(P_LP, 1) == m.u('r_start') + 500,
          'NO TAIL of a loop: LOOP on, the source\'s loop flag (0x72) and loop point offset kept')
    # TAIL of a loop: one pass, no loop
    m, pcm = source(loop=1, lp=500, p72=1, seed=35)
    run_bounce(m, 0, 1)
    check(m.pad_get(P_LOOP, 1) == 0 and m.pad_get(P_TOP, 1) == 0 and m.pad_get(P_LP, 1) == m.u('r_start'),
          'TAIL of a loop: the bounce plays once (LOOP off, loop point = START)')
    note('the bounced pad\'s settings')


def replace_checks(img, man):
    def setup(seed=41, n=3000, **kw):
        m = boot(img, man, seed=seed)
        pcm = pcm_burst(n, seed)
        m.load_pad(0, n, **kw)
        m.voice = Voice(m, 0, pcm, 0, n, 0, 1)
        return m, pcm

    # REPLACE: the bounce on the source pad, the original on the scratch pad
    m, pcm = setup()
    m.pad_set(P_LINK, 4, 0)
    m.load_pad(9, 4000, tag='linked')
    m.pad_set(P_LINK, 4, 9)
    orig = m.record(0)
    res = run_bounce(m, 0, 0, target=T_REPLACE)
    posts = [x[1] for x in m.log if x[0] == 'post']
    check(res['setup_text'] == 'REPLACE A-1\nNO TAIL' and res['popup'] == 'REPLACED A-1\nORIG ON A-2',
          f'REPLACE: setup and done popups ({res["setup_text"]!r}, {res["popup"]!r})')
    check(posts == [5, 0x2A, 0x14, 0x17, 5, 0xD, 0x18, 0xD, 0x40D, 0xD] and ('exchange', 0, 1) in m.log,
          f'REPLACE: standby .. stop, save, then the stock exchange 0x40d(A-1, A-2), save ({[hex(p) for p in posts]})')
    check(m.voice.link_at_trigger == 0, 'during the run the source is out of its PAD LINK group: the pad alone plays')
    check(m.record(1)[1:] == orig[1:] and m.file(1)['tag'] == ('pad', 0, 3000),
          'after the exchange the scratch pad holds the original: its file, name and block')
    check(m.pad_get(P_LINK, 1) == 0 and m.pad_get(P_LINK, 0) == 4,
          'PAD LINK: the bounce takes the source\'s group 4, the parked original leaves it')
    a1 = m.record(1)[0]
    o1 = bytearray(orig[0])
    o1[0x11C - 0xD0:0x11C - 0xD0 + 4] = struct.pack('<I', 0)
    check(a1 == bytes(o1), 'the original\'s parameter record moved whole, PAD LINK aside')
    check(m.file(0)['tag'][0] == 'take' and m.pad_get(0x67, 0) == 384 + 77 and m.name(0).startswith('A1 L77'),
          'the source pad plays the bounce: its file, exact START, the run\'s name')
    ok, got = neutral_ok(m, 0)
    check(ok and m.pad_get(0x6A, 0) == 1, f'the bounce on the source pad: printed settings neutral ({got})')
    check(m.r32(TARGET_VALUES + 4) == 0xFFFFFFFF and m.param_saves >= 1,
          'the fence: the recorder target is none again; the exchange saved the pads')
    recs = m.undos()
    check(len(recs) == 1 and recs[0]['pad'] == 0 and recs[0]['keep'] == 1 and recs[0]['link'] == 4 and
          recs[0]['len_keep'] == 3000, f'an UNDO record: bounce on A-1, original on A-2, PAD LINK 4 ({recs})')
    # UNDO: the gesture on the bounced pad offers it first
    m.ui(300)
    m.gesture(0)
    m.ui(1)
    check(m.popup() == 'UNDO BOUNCE?\nORIG ON A-2' and m.u('target') == T_UNDO,
          f'the gesture on the bounced pad: UNDO BOUNCE? first ({m.popup()!r})')
    seen = []
    for d in (1, -1):
        m.turn(d)
        m.ui(1)
        seen.append(m.popup())
    m.tap(KEY_VALUE)
    m.ui(1)
    seen.append(m.popup())
    m.tap(KEY_VALUE)
    m.ui(1)
    seen.append(m.popup())
    m.tap(KEY_VALUE)
    m.ui(1)
    seen.append(m.popup())
    check(seen == ['UNDO BOUNCE?\nORIG ON A-2', 'UNDO BOUNCE?\nORIG ON A-2', 'BOUNCE A-1>A-3\nNO TAIL',
                   'REPLACE A-1\nNO TAIL', 'UNDO BOUNCE?\nORIG ON A-2'],
          f'in UNDO VALUE alone changes nothing; VALUE pressed: a new bounce of it (A-3 free), REPLACE, UNDO ({seen})')
    m.log = []
    m.tap(KEY_REC)
    for _ in range(40):
        m.ui(1)
    posts = [x[1] for x in m.log if x[0] == 'post']
    check(m.popup() == 'UNDONE A-1\nBOUNCE ON A-2' and posts == [5, 0x40D, 0xD],
          f'UNDO: sound off, the exchange again, save ({m.popup()!r}, {[hex(p) for p in posts]})')
    check(m.record(0) == orig, 'UNDO is bit-exact: the original\'s file, parameter record (PAD LINK 4 again), name and '
                               'block are back on A-1')
    check(m.file(1)['tag'][0] == 'take' and m.pad_get(P_LINK, 1) == 0 and m.undos() == [],
          'after UNDO the bounce stays on A-2, unlinked; the record is gone')
    m.gesture(0)
    m.ui(1)
    check(m.popup() == 'BOUNCE A-1>A-3\nNO TAIL', f'no second UNDO: the gesture is a new bounce again ({m.popup()!r})')
    m.tap(KEY_EXIT)
    m.ui(300)

    # a record that no longer fits: the scratch pad was replaced since
    m, pcm = setup(seed=42)
    run_bounce(m, 0, 0, target=T_REPLACE)
    m.load_pad(1, 2222, tag='another')
    m.ui(300)
    m.gesture(0)
    m.ui(1)
    check(m.popup() == 'REPLACE A-1\nNO TAIL' and m.u('targets') == 3 and m.u('dst') == 2 and m.undos() == [],
          f'the pad holding the original changed: no UNDO, the record is dropped; the setup starts on the target '
          f'used last ({m.popup()!r})')
    m.tap(KEY_EXIT)
    # ... or changes between the gesture and REC
    m, pcm = setup(seed=43)
    run_bounce(m, 0, 0, target=T_REPLACE)
    m.ui(300)
    m.gesture(0)
    m.ui(1)
    m.load_pad(1, 2222, tag='another')
    m.log = []
    m.tap(KEY_REC)
    m.ui(5)
    check(m.popup() == 'CANNOT UNDO\nPADS CHANGED' and not [x for x in m.log if x[0] == 'post'],
          f'a pad changed before REC: CANNOT UNDO, nothing posted ({m.popup()!r})')
    # the recorder target already holds the fence's value (a stock standby that never started on pad 16)
    m, pcm = setup(seed=40)
    orig = m.record(0)
    run_bounce(m, 0, 0, target=T_REPLACE)
    m.ui(300)
    m.w32(TARGET_VALUES + 4, 15)
    m.gesture(0)
    m.ui(1)
    m.tap(KEY_REC)
    for _ in range(40):
        m.ui(1)
    check(m.popup() == 'UNDONE A-1\nBOUNCE ON A-2' and m.u('fence') == 14 and m.record(0) == orig and
          m.r32(TARGET_VALUES + 4) == 0xFFFFFFFF,
          f'a stale target value 15: the fence writes 14, the UNDO completes ({m.popup()!r})')

    # a source in a protected bank: no REPLACE
    m, pcm = setup(seed=44)
    m.protect(0)
    res = run_bounce(m, 0, 0, target=T_REPLACE)
    check(res['popup'] == 'BANK PROTECTED\nNOTHING CHANGED' and not [x for x in m.log if x[0] == 'post'] and
          res['setup_text'] == 'REPLACE A-1\nNO TAIL' and m.u('dst') == 16,
          f'REPLACE from a protected bank: BANK PROTECTED, nothing posted ({res["popup"]!r})')
    # TO PAD from a protected bank works when the source needs no change
    m, pcm = setup(seed=45)
    m.protect(0)
    res = run_bounce(m, 0, 0)
    check(res['popup'] == 'BOUNCED A-1\nON B-1', f'TO PAD from a protected bank: into bank B ({res["popup"]!r})')
    # ... and refuses when the run would have to change it (LOOP for a one-shot)
    m, pcm = setup(seed=46)
    m.protect(0)
    res = run_bounce(m, 0, 2)
    check(res['popup'] == 'BANK PROTECTED\nNOTHING CHANGED' and m.pad_get(P_LOOP, 0) == 0,
          'LOOP of a one-shot in a protected bank: BANK PROTECTED, the source unchanged')

    # the exchange fails (the renames do not happen): no UNDO record, the failure shown
    m, pcm = setup(seed=47)
    orig = m.record(0)
    m.swap_fail = 'rename'
    res = run_bounce(m, 0, 0, target=T_REPLACE)
    check(res['popup'] == 'SWAP FAILED\nCHECK A-1 A-2' and m.undos() == [] and m.file(0)['tag'] == ('pad', 0, 3000),
          f'the files did not move: SWAP FAILED, no UNDO record ({res["popup"]!r})')
    # SMPL TASK stalls before the exchange: the fence never lands, 10 s
    m, pcm = setup(seed=48)
    m.stall = True
    res = run_bounce(m, 0, 0, target=T_REPLACE, budget=12000)
    check(res['popup'] == 'SWAP FAILED\nCHECK A-1 A-2' and m.undos() == [] and m.u('state') == U_IDLE and
          ('cmd', 0x40D, 0, 1) in m.pending(),
          f'the exchange never confirmed within 10 s: SWAP FAILED, the pads to be checked ({res["popup"]!r})')
    # EXIT while swapping is ignored
    m, pcm = setup(seed=49)
    res = run_bounce(m, 0, 0, target=T_REPLACE, exit_at=(U_SWAP,))
    check(res['popup'] == 'REPLACED A-1\nORIG ON A-2', 'EXIT while the pads are swapped: ignored, the replace completes')
    # eight records at most; a REPLACE of a replaced pad keeps the newest
    m = boot(img, man, seed=50)
    for p in range(0, 10):
        pcm = pcm_burst(2000 + p, 60 + p)
        m.load_pad(16 + p, 2000 + p)
    for p in range(0, 10):
        pcm = pcm_burst(2000 + p, 60 + p)
        m.voice = Voice(m, 16 + p, pcm, 0, 2000 + p, 0, 1)
        m.take, m.finalized = [], []
        m.project[0] = 1
        run_bounce(m, p, 0, target=T_REPLACE)
        m.ui(300)
    recs = m.undos()
    check(len(recs) == 8 and sorted(r['pad'] for r in recs) == list(range(18, 26)),
          f'ten REPLACEs: the last eight can be undone ({sorted(r["pad"] for r in recs)})')
    note('REPLACE and UNDO')


def leak_checks(img, man):
    def setup(seed=61):
        m = boot(img, man, seed=seed)
        pcm = pcm_burst(3000, seed)
        m.load_pad(0, 3000)
        m.voice = Voice(m, 0, pcm, 0, 3000, 0, 1)
        return m, pcm

    # EXT SOURCE on with music on the input: off for the run, the take clean, on again afterwards
    m, pcm = setup()
    m.settings[0x25] = 1
    m.fx['input'] = 3000
    res = run_bounce(m, 0, 0)
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and m.take[77:77 + 3000] == pcm and m.settings[0x25] == 1,
          'EXT SOURCE on, music on the input: muted for the run, the take frame-exact, EXT SOURCE back on')
    sets = [(x[2]) for x in m.log if x[0] == 'set' and x[1] == 0x25]
    check(sets == [0, 1], f'EXT SOURCE through the stock setter: off at REC, on at the end ({sets})')
    # switched on during the take (a MIDI note, the remote): the take is discarded
    m, pcm = setup(seed=62)

    def ext_on(mm, i):
        if mm.u('state') == U_RUN and mm.a('fed') > 500 and not mm.settings.get(0x25):
            mm.settings[0x25] = 1
    res = run_bounce(m, 0, 0, during=ext_on)
    posts = [x[1] for x in m.log if x[0] == 'post']
    check(res['popup'] == 'INPUT TURNED ON\nNOTHING CHANGED' and 0x1A in posts and 0x18 not in posts and
          m.settings[0x25] == 1 and m.status[1] == 0,
          f'EXT SOURCE switched on during the take: muted again, the take discarded, EXT SOURCE left on '
          f'({res["popup"]!r})')
    # ... during the silence wait: muted again, the bounce goes on
    m, pcm = setup(seed=63)

    def ext_on_wait(mm, i):
        if mm.u('state') == U_SILENCE and i == 40:
            mm.settings[0x25] = 1
    res = run_bounce(m, 0, 0, during=ext_on_wait)
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and m.take[77:77 + 3000] == pcm and m.settings[0x25] == 1,
          'EXT SOURCE switched on during the silence wait: muted again, a clean bounce, on afterwards')
    # MIDI notes through the stock MIDI dispatcher during the take: dropped; the same note when idle plays
    m, pcm = setup(seed=64)
    m.load_pad(5, 2000, tag='midi')
    midi = []

    def send(mm, status, d1, d2):
        mm.uc.mem_write(MSG, bytes([0, status, d1, d2]) + bytes(4))
        before = len(mm.ring)
        mm.call(MIDI_DISPATCH, MSG)
        return mm.ring[before:]

    def notes(mm, i):
        if mm.u('state') == U_RUN and not midi:
            midi.append(send(mm, 0x90, 36 + 5, 100))     # channel 1, the note of pad A-6
            midi.append(send(mm, 0x80, 36 + 5, 0))
    prep = midi_prep(m)
    res = run_bounce(m, 0, 0, during=notes)
    check(prep and res['popup'] == 'BOUNCED A-1\nON A-2' and midi and midi[0] == [] and m.take[77:77 + 3000] == pcm and
          m.u('dropped') >= 1,
          f'MIDI note-on during the take (stock dispatcher, channel 1): dropped at the gate, the take clean '
          f'({midi}, {m.u("dropped")} dropped)')
    after = send(m, 0x90, 36 + 5, 100)
    check(prep and len(after) == 1 and after[0][1] == 5 and after[0][3] == 100,
          f'the same MIDI note when idle: through the gate onto the pad-event ring ({after})')
    # FIXED VELOCITY: the run's own trigger carries another velocity and still passes
    m, pcm = setup(seed=65)
    m.project[0xF5] = 1
    m.project[0xDC] = 90
    res = run_bounce(m, 0, 0)
    rings = [x for x in m.log if x[0] == 'ring']
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and rings == [('ring', 0, 4, 90)] and m.take[77:77 + 3000] == pcm,
          f'FIXED VELOCITY 90: the trigger passes the gate with velocity 90 ({rings})')
    # a pattern or the looper starting during the run: the take is discarded
    for name, start, text in (('pattern', lambda mm: mm.uc.mem_write(SEQ_PLAY, b'\x01'), 'STOP PATTERN FIRST'),
                              ('looper', lambda mm: looper_cmd(mm, 0), 'STOP LOOPER FIRST')):
        m, pcm = setup(seed=66)
        if name == 'looper':                    # MARK Function = LOOPER, a loop recorded and stopped
            looper_ready(m, phase=6)

        def go(mm, i, start=start):
            if mm.u('state') == U_RUN and mm.a('fed') > 200:
                start(mm)
        res = run_bounce(m, 0, 0, during=go)
        posts = [x[1] for x in m.log if x[0] == 'post']
        check(res['popup'] == text and 0x1A in posts and 0x18 not in posts and m.status[1] == 0,
              f'a {name} starting during the take: {text}, the take discarded')
    # PAD LINK: the source alone is recorded, its group back afterwards (and saved)
    m, pcm = setup(seed=67)
    m.pad_set(P_LINK, 2, 0)
    res = run_bounce(m, 0, 0)
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and m.voice.link_at_trigger == 0 and m.pad_get(P_LINK, 0) == 2 and
          m.pad_get(P_LINK, 1) == 0,
          'PAD LINK 2: out of the group while the pad is triggered, back to 2 after; TO PAD leaves the bounce unlinked')
    note('the input, MIDI and other sounds kept out of the take')


def midi_prep(m):
    """What the stock MIDI note-on path needs for a sample-pad note: page RESAMPLE, no MIDI clock wait."""
    m.w32(0x80245B18, 0xFFFFFFFF)                    # the note-on handler runs only while this is negative
    m.uc.mem_write(0x82E10370 + 0x685, b'\x00')      # MIDI thru level below 6
    for addr, value in ((0x800D6380, 0x0E), (0x8004CC78, 0), (0x800D9360, 0), (0x800D61F0, 0), (0x800C06E0, 1)):
        m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, v: m._ret(v), value, begin=addr, end=addr)
    # the pad of a note: the stock note map (0x8005ec50), here note 36 + k -> pad k of bank A
    m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: m._ret(uc.reg_read(ar.UC_ARM_REG_R1) - 36), None,
                  begin=0x8005EC50, end=0x8005EC50)
    return True


def failure_checks(img, man):
    def setup(**kw):
        m = boot(img, man, seed=9)
        pcm = pcm_burst(3000, 31)
        m.load_pad(0, 3000, loop=kw.get('loop', 0))
        m.voice = Voice(m, 0, pcm, 0, 3000, 0, 1)
        return m

    def restored(m, label, dst_empty=True):
        check(m.r8(REC_STATE) == 0 and m.r32(FEED_ON) == 1 and m.settings[0x24] == 3 and m.settings[0x59] == 0 and
              m.settings[0x1B] == 12000 and not [x for x in m.log if x[0] == 'set' and x[1] == 0x1B] and
              m.settings[0x1A] == -1 and (m.status[1] == 0 or not dst_empty) and
              m.u('pinned') == 0 and m.u('ext_pin') == 0 and m.r32(m.sym['bnc_own']) == 0,
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
    res = run_bounce(m, 0, 0, exit_at=(U_RUN,), target=T_REPLACE)
    check(res['popup'] == 'BOUNCE CANCELLED\nNOTHING CHANGED' and not [x for x in m.log if x[0] == 'exchange'],
          'EXIT during a REPLACE take: cancelled, no exchange')
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
    m.load_ok = False
    res = run_bounce(m, 0, 0, target=T_REPLACE)
    check(res['popup'] == 'BOUNCE FAILED' and not [x for x in m.log if x[0] == 'exchange'],
          'REPLACE whose take did not load: BOUNCE FAILED, no exchange')
    m = setup()
    m.project[0xFB] = 1
    res = run_bounce(m, 0, 0)
    check(res['popup'] == 'BOUNCED A-1\nON A-2' and m.project[0xFB] == 1 and
          ('pset', 0xFB, 0) in m.log and m.pad_get(0x67, 1) == 384 + 77,
          'zero-cross snapping on: off while START is set, back on afterwards; START exact')
    # the standby cannot open its temp file (no card, card full): state stays idle
    m = setup()

    def no_standby(mm, i):
        if mm.u('state') == U_STANDBY:
            mm.ignore.add(0x14)
    res = run_bounce(m, 0, 0, during=no_standby)
    check(res['popup'] == 'BOUNCE FAILED', f'standby never starts (no temp file): BOUNCE FAILED after 3 s')
    restored(m, 'no standby')
    # the stock recorder ends the take itself
    for err, partial, text, label in ((-0x3E, True, 'STORAGE FULL\nPART ON A-2', 'the card full (drain -0x3e)'),
                                      (-0x79, True, 'BOUNCE FAILED\nPART ON A-2', 'a full ring (-0x79)'),
                                      (-0x80, False, 'STORAGE FULL\nNOTHING CHANGED', 'no space, nothing kept')):
        for target in (T_PAD, T_REPLACE):
            m = setup()
            m.load_pad(0, 3000, loop=1)
            orig = m.record(0)
            m.pad_set(P_LINK, 3, 0)
            orig = m.record(0)
            hit = []

            def stop(mm, i, err=err, partial=partial):
                if mm.u('state') == U_RUN and mm.a('fed') > 600 and not hit:
                    hit.append(mm.a('fed'))
                    mm.stock_stop(err, partial)
            res = run_bounce(m, 0, 1, during=stop, target=target)
            posts = [x[1] for x in m.log if x[0] == 'post']
            fed_after = m.a('fed')
            check(res['popup'] == text and 0x18 not in posts and 0x1A not in posts and
                  not [x for x in m.log if x[0] == 'exchange'],
                  f'{label}, {"REPLACE" if target else "TO PAD"}: {text!r}, no stop or cancel posted, no exchange '
                  f'({res["popup"]!r})')
            check(fed_after <= hit[0] + 64 and m.record(0) == orig and m.u('loop_pin') == 0 and m.u('link_pin') == 0,
                  f'{label}: the module stops writing at once; the source as it was (LOOP, PAD LINK 3 back)')
            restored(m, label, dst_empty=not partial)
    # the ring full while the module writes the take's very last frames: the stock stop wins, no REC_STOP on top
    m = setup()
    m.overrun_at = 77 + 3000 + 32
    res = run_bounce(m, 0, 0)
    posts = [x[1] for x in m.log if x[0] == 'post']
    check(res['popup'] == 'BOUNCE FAILED\nPART ON A-2' and 0x18 not in posts and m.finalized and
          m.finalized[0]['err'] == -0x79,
          f'the writer fills its ring on the last frames: the stock finalize keeps the take, no REC_STOP on top '
          f'({res["popup"]!r})')
    note('refusals, EXIT and failures')


def cost_checks(img, man):
    m = boot(img, man, seed=12)
    pcm = pcm_burst(4000, 41)
    m.load_pad(0, 4000)
    m.voice = Voice(m, 0, pcm, 0, 4000, 0, 1)
    lo, hi = man['blob_base'], man['bss'][0]
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
    count[0] = 0
    m.pad_event(3, 100)
    gate_idle = count[0]
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
          f'the engine writer is stubbed); the gate adds {gate_idle} per pad event when idle')
    check(max(idle) < 60, 'idle: under 60 instructions per block pair')
    check(gate_idle < 40, 'idle: the gate adds under 40 instructions per pad event')
    check(max(busy) < 4000 and max(slow) < 10000,
          'bouncing: under 4,000 instructions per block pair, 10,000 while looking for a late onset (about 1% of a '
          'block)')


# ---- the looper, through its own stock code ----
def looper_init(m):
    """The looper as the boot leaves it (0x80045968, for real): disabled, phase 0."""
    m.call(LOOPER_INIT)


def mark_function(m, value):
    """MARK Function (system parameter 0x141) through the real setter 0x80018d28: 2 = LOOPER enables the looper."""
    m.call(SYS_SET, SYS_OBJ, 0x141, value, 0, count=20_000_000)   # the enable clears both loop buffers


def looper_auto(m, on):
    """The looper's level trigger (the settings setter's 0x80019780, for real): on, MARK from empty or stopped
    arms it (phase 1 or 7) and the input level starts the take; off, MARK records at once. On after the boot."""
    m.call(LOOPER_AUTO, LOOPER, on)


def looper_cmd(m, cmd):
    """A looper command as the LOOPER TASK runs it (0x80070280, for real): 0 = MARK, 1 = overdub, 4 = erase."""
    m.call(LOOPER_CMD, LOOPER, cmd, count=20_000_000)           # erase clears both loop buffers


def looper_block(m):
    """One audio block through the looper's real input (0x1d634), as the feed calls it while it is enabled."""
    m.looper_in_real = True
    m.call(LOOPER_IN, LOOPER, CAPTURE, 64)
    m.looper_in_real = False


def looper_state(m):
    return m.r8(LOOPER_ON), m.r8(LOOPER_PHASE), m.r8(LOOPER_GO)


def looper_ready(m, phase=0):
    """MARK Function = LOOPER; phase 0 (empty) or 6 (a loop recorded, then stopped), by the stock commands."""
    looper_init(m)
    mark_function(m, 2)
    looper_auto(m, 0)
    if phase == 6:
        looper_cmd(m, 0)                        # record
        looper_cmd(m, 0)                        # close the loop: play
        looper_cmd(m, 0)                        # stop
    if looper_state(m)[:2] != (1, phase):
        raise RuntimeError(f'looper not ready: {looper_state(m)}')


def looper_checks(img, man):
    """The looper refuses a bounce only while it plays, records, overdubs or waits for a level: the stock
    setter, the LOOPER TASK's commands and its audio input run for real."""
    m = boot(img, man)
    m.load_pad(0, 4800)

    def gesture_text():
        m.gesture(0)
        m.ui(1)
        text, state = m.popup(), m.u('state')
        if state == U_SETUP:
            m.tap(KEY_EXIT)
            m.ui(1)
        return text, state

    looper_init(m)
    check(looper_state(m) == (0, 0, 0) and m.r8(LOOPER_TRIG) == 1,
          f'the looper after the boot: disabled, empty, level trigger on ({looper_state(m)})')
    text, state = gesture_text()
    check(state == U_SETUP, f'MARK Function not LOOPER: the bounce is set up ({text!r})')
    mark_function(m, 2)
    check(looper_state(m) == (1, 0, 0),
          f'MARK Function = LOOPER through the stock setter: +0x39 = 1, phase 0 ({looper_state(m)})')
    text, state = gesture_text()
    check(state == U_SETUP and text.startswith('BOUNCE A-1>A-2'),
          f'MARK Function = LOOPER, the looper empty: the bounce is set up, not refused ({text!r})')
    looper_cmd(m, 0)
    text, state = gesture_text()
    check(looper_state(m)[1] == 1 and state == U_IDLE and text == 'STOP LOOPER FIRST',
          f'MARK with the level trigger on: armed (phase 1), refused: the bounce itself would start it '
          f'({looper_state(m)}, {text!r})')
    looper_cmd(m, 0)                            # MARK again: disarmed
    looper_auto(m, 0)
    text, state = gesture_text()
    check(looper_state(m) == (1, 0, 0) and state == U_SETUP, f'disarmed, level trigger off: set up ({text!r})')
    steps = [(lambda: looper_cmd(m, 0), 2, 'MARK: the first pass records', True),
             (lambda: looper_cmd(m, 0), 5, 'MARK again: the loop closed, playing', True),
             (lambda: looper_cmd(m, 0), 6, 'MARK again: stopped', False),
             (lambda: looper_cmd(m, 1), 6, 'overdub from stop: queued for the next block (+0x102)', True),
             (lambda: looper_block(m), 8, 'the next audio block: overdubbing (plays and records)', True),
             (lambda: looper_cmd(m, 1), 9, 'overdub off: ending at the loop\'s end', True),
             (lambda: looper_cmd(m, 0), 6, 'MARK: stopped', False),
             (lambda: looper_cmd(m, 4), 0, 'erase: empty', False)]
    for do, phase, what, refused in steps:
        do()
        st = looper_state(m)
        text, state = gesture_text()
        ok = (state == U_IDLE and text == 'STOP LOOPER FIRST') if refused else state == U_SETUP
        check(st[1] == phase and ok, f'looper {what} (phase {st[1]}, go {st[2]}): '
              f'{"refused" if refused else "set up"} ({text!r})')
    looper_auto(m, 1)
    looper_cmd(m, 0)
    text, state = gesture_text()
    check(looper_state(m)[1] == 1 and state == U_IDLE and text == 'STOP LOOPER FIRST',
          f'armed again for a level: refused ({looper_state(m)}, {text!r})')
    mark_function(m, 0)
    text, state = gesture_text()
    check(looper_state(m)[:2] == (0, 1) and state == U_SETUP,
          f'MARK Function back to MARK while armed: disabled, the feed no longer reaches it: set up ({text!r})')
    mark_function(m, 2)                         # enabled again: empty
    looper_auto(m, 0)
    looper_cmd(m, 0)
    looper_cmd(m, 0)                            # playing
    mark_function(m, 0)                         # the stock disable stops it first
    text, state = gesture_text()
    check(looper_state(m)[:2] == (0, 6) and state == U_SETUP,
          f'MARK Function back to MARK while playing: the stock disable stops it (phase 6): set up ({text!r})')
    # REC in the setup popup checks again
    m2 = boot(img, man, seed=3)
    m2.load_pad(0, 4800)
    looper_ready(m2, phase=6)
    m2.gesture(0)
    m2.ui(1)
    looper_cmd(m2, 0)                           # the looper plays before REC is pressed
    m2.tap(KEY_REC)
    m2.ui(1)
    check(m2.u('state') == U_IDLE and m2.popup() == 'STOP LOOPER FIRST' and
          not [x for x in m2.log if x[0] == 'post'],
          f'the looper started between the gesture and REC: refused at REC, nothing posted ({m2.popup()!r})')
    # a whole bounce with MARK Function = LOOPER and a loop stopped
    m3 = boot(img, man, seed=4)
    pcm = pcm_burst(3000, 4)
    m3.load_pad(0, 3000)
    m3.voice = Voice(m3, 0, pcm, 0, 3000, 0, 1)
    looper_ready(m3, phase=6)
    res = run_bounce(m3, 0, 0)
    check(res.get('popup') == 'BOUNCED A-1\nON A-2' and m3.take[77:77 + 3000] == pcm and looper_state(m3)[:2] == (1, 6),
          f'a bounce with MARK Function = LOOPER, the loop stopped: done, the looper left as it was '
          f'({res.get("popup")!r})')
    note('the looper: refused only while it plays, records, overdubs or waits for a level')


# ---- events through the UI task's real dispatcher ----
def dispatcher_checks(img, man):
    """The gesture, VALUE pressed, SHIFT + VALUE, REC and EXIT reach the module through the UI task's own
    dispatcher (0x8003b530) and page 0xe's registry handler (0x80053cb8), as on the unit."""
    m = boot(img, man)
    m.real_ui()
    m.load_pad(0, 4800)
    m.dispatch(EV_KEY, KEY_RESAMPLE)
    held = m.r8(KEYS + (KEY_RESAMPLE >> 3)) >> (KEY_RESAMPLE & 7) & 1
    m.dispatch(EV_PAD, 0, 100)
    m.dispatch(EV_PAD_UP, 0, 0)
    m.dispatch(EV_KEY_UP, KEY_RESAMPLE)
    m.ui(1)
    check(held and m.u('state') == U_SETUP and m.popup() == 'BOUNCE A-1>A-2\nNO TAIL',
          f'the gesture through the stock dispatcher: the setup popup ({m.popup()!r})')
    m.dispatch(EV_KEY, KEY_VALUE)
    m.dispatch(EV_KEY_UP, KEY_VALUE)
    m.ui(1)
    check(m.u('target') == T_REPLACE and m.popup() == 'REPLACE A-1\nNO TAIL',
          f'VALUE pressed (key 0x31, as the stock SG page takes it) through the stock dispatcher: REPLACE '
          f'({m.popup()!r})')
    m.dispatch(EV_KEY, KEY_VALUE)
    m.dispatch(EV_KEY_UP, KEY_VALUE)
    m.ui(1)
    check(m.u('target') == T_PAD and m.popup() == 'BOUNCE A-1>A-2\nNO TAIL', 'VALUE pressed again: TO PAD')
    m.dispatch(EV_KEY, KEY_SHIFT)
    m.dispatch(EV_ENCODER, 0, 1)
    m.dispatch(EV_KEY_UP, KEY_SHIFT)
    m.ui(1)
    check(m.u('target') == T_REPLACE, 'SHIFT + VALUE right through the stock dispatcher: REPLACE')
    m.dispatch(EV_ENCODER, 0, 1)
    m.ui(1)
    check(m.u('target') == T_REPLACE and m.u('mode') == TAIL and m.popup() == 'REPLACE A-1\nTAIL',
          f'VALUE turned: the mode; the target stays ({m.popup()!r})')
    m.dispatch(EV_KEY, KEY_EXIT)
    m.dispatch(EV_KEY_UP, KEY_EXIT)
    m.ui(1)
    check(m.u('state') == U_IDLE and m.popup() == 'BOUNCE CANCELLED\nNOTHING CHANGED',
          'EXIT through the stock dispatcher: cancelled')
    # a whole REPLACE, every key through the stock dispatcher
    m = boot(img, man, seed=5)
    m.real_ui()
    pcm = pcm_burst(3000, 5)
    m.load_pad(0, 3000)
    m.voice = Voice(m, 0, pcm, 0, 3000, 0, 1)
    orig = m.record(0)
    m.dispatch(EV_KEY, KEY_RESAMPLE)
    m.dispatch(EV_PAD, 0, 100)
    m.dispatch(EV_PAD_UP, 0, 0)
    m.dispatch(EV_KEY_UP, KEY_RESAMPLE)
    m.ui(1)
    m.dispatch(EV_KEY, KEY_VALUE)
    m.dispatch(EV_KEY_UP, KEY_VALUE)
    m.ui(1)
    setup_text = m.popup()
    m.dispatch(EV_KEY, KEY_REC)
    m.dispatch(EV_KEY_UP, KEY_REC)
    texts = set()
    for _ in range(4000):
        m.period()
        texts.add(m.popup().split('\n')[0])
        if m.u('state') == U_IDLE:
            break
    for _ in range(4):
        m.ui(1)
    swaps = [x for x in m.fs_log if x[0] == 'rename']
    a, b = m.path(0), m.path(1)
    tmp = 'B:/tmp.SMP'
    check(setup_text == 'REPLACE A-1\nNO TAIL' and m.popup() == 'REPLACED A-1\nORIG ON A-2' and
          texts <= {'REPLACE A-1', 'REPLACED A-1'} and swaps == [('rename', b, tmp), ('rename', a, b), ('rename', tmp, a)]
          and m.file(0)['tag'][0] == 'take' and m.record(1)[3] == orig[3],
          f'REPLACE with every key through the stock dispatcher: the real file swap renames {b} -> tmp, {a} -> {b}, '
          f'tmp -> {a}; the bounce on A-1, the original on A-2 ({m.popup()!r}, {sorted(texts)})')
    note('events through the stock dispatcher')


# ---- the exchange's fence, through SMPL TASK's real queue ----
def fence_checks(img, man):
    """The REPLACE fence lands only after the exchange: the module's posts go through the real post (0x800e25c0)
    and target set (0x800d48e8) into SMPL TASK's one queue, and the task's real loop takes them in order."""
    m = boot(img, man, seed=6)
    pcm = pcm_burst(3000, 6)
    m.load_pad(0, 3000)
    m.voice = Voice(m, 0, pcm, 0, 3000, 0, 1)
    order = []

    def seen(uc, address, size, what):
        if what == 'exchange_done':
            order.append(('exchange returned',))
        elif what == 'store':
            r1, r2 = (uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}')) for k in (1, 2))
            if r1 == 1:
                order.append(('target 1', s32(r2), m.r8(REC_STATE)))
    passes = []

    def loop_entry(uc, address, size, _):
        passes.append(m.pending())
    m.uc.hook_add(UC_HOOK_CODE, seen, 'exchange_done', begin=0x8004F8C8, end=0x8004F8C8)
    m.uc.hook_add(UC_HOOK_CODE, seen, 'store', begin=0x800FB000, end=0x800FB000)
    m.uc.hook_add(UC_HOOK_CODE, loop_entry, None, begin=SMPL_LOOP, end=SMPL_LOOP)
    res = run_bounce(m, 0, 0, target=T_REPLACE)
    fence = [i for i, x in enumerate(order) if x[0] == 'target 1' and x[1] in (14, 15)]
    done = [i for i, x in enumerate(order) if x[0] == 'exchange returned']
    check(res['popup'] == 'REPLACED A-1\nORIG ON A-2' and len(done) == 1 and len(fence) == 1 and done[0] < fence[0],
          f'the fence (target 1 = 15) is stored by the real target store after 0x800a6c30 returned ({order[-6:]})')
    px = [q for q in passes if ('cmd', 0x40D, 0, 1) in q]
    q = px[0] if px else []
    at = q.index(('cmd', 0x40D, 0, 1)) if q else 0
    check(len(px) == 1 and [x for x in q[at + 1:] if x[0] == 'target'][:1] == [('target', 1, 15)],
          f'the exchange and the fence reach SMPL TASK in one pass of its loop, the fence after it ({q})')
    note('the fence through the real queue')


# ---- the image with its global objects built ----
HEAP = 0x32000000
REAL_CODE = ('get', 'set', 'pget', 'pset', 'sysget', 'doom', 'qput', 'other', 0x800E11D0, 0x800D8B90)
KERNEL = {0x310C: 1, 0x22A4: 1, 0x32B8: 0}                 # RTOS object creation in the constructors: an id
SCREEN = (0x8006C088, 0x8006BD48, 0x8015F3A8, 0x800D8020)  # drawing: the display is not built here
UI_TICK, UI_DRAIN, REGISTRY_F, RS_TICK, RS_AFTER = 0x8003C5F0, 0x800BA228, 0x80053CB8, 0x8012DB58, 0x8012CBB0
RS_TICK0, RS_TICK1, RS_STATE = 0x8012CE68, 0x8012D4E8, 0x8012DCB0  # the page vtable's +0xd0, +0xcc; the state handler
PAGE_LAST = 0x1A90                                       # the page object: the recorder state at its last tick
CTORS, NCTORS = 0x8383A30C, 70
SETTINGS, PROJECT, SYSPRM_OBJ = 0x82E01144, 0x82E009D0, 0x82DFEED0
SETTINGS_GET, SETTINGS_SET, PROJECT_GET, PROJECT_SET = 0x800D94D8, 0x800DD0C0, 0x800DDA38, 0x800DED18
SYSTEM_GET, SYSTEM_SET = 0x800DA010, 0x800DE270
WATCHED = {SETTINGS_SET: 'settings', PROJECT_SET: 'project', SYSTEM_SET: 'system', PADSET: 'pad', 0x800E11D0: 'seq',
           0x800DA598: 'page', 0x8001A1C8: 'input volume', 0x800931B8: 'effect'}


class RealMachine(Machine):
    """The image with its global objects built: the boot's 70 static constructors run (the RTOS under them stubbed:
    its pool by a bump allocator, object creation by an id, critical sections by nothing); the settings, project,
    system, sequencer, pad and broadcast code, DOOM OS's page filter and the RESAMPLE page object (made by its
    registry handler, as on page entry) are real; each millisecond the UI task's tick (0x8003c5f0, with the stock
    popup tick behind the module's bridge) runs, its event queue drains through the stock dispatcher, and every
    16 ms the RESAMPLE page's tick runs as its draw calls it. The chip's UARTs (LPUART1-8) are logged byte by
    byte; every settings, project, system, pad and sequencer write, page request and bank or pad change is logged.
    Modelled as in Machine: the recorder commands and finalize, the card, voices, the effects chip's audio."""

    def __init__(self, img, man=None):
        super().__init__(img, man, skip=REAL_CODE)
        uc = self.uc
        for base, size in ((0xE0000000, 0x100000), (0x40000000, 0xE8000), (0x400EA000, 0x316000), (HEAP, 0x1000000)):
            uc.mem_map(base, size, UC_PROT_ALL)
        self.heap = HEAP
        self.mpatched = self.mprofile()
        uc.hook_add(UC_HOOK_CODE, self._malloc, None, begin=0x800E2C68, end=0x800E2C68)
        uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=0x800E2CA8, end=0x800E2CA8)
        for a, v in KERNEL.items():
            uc.hook_add(UC_HOOK_CODE, self._value, v, begin=a, end=a)
        for a in SCREEN:
            uc.hook_add(UC_HOOK_CODE, self._value, 0, begin=a, end=a)
        self.uart, self.calls = [], []
        uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self._uart, None, begin=0x40184000, end=0x401A3FFF)
        for fn in struct.unpack(f'<{NCTORS}I', bytes(uc.mem_read(CTORS, 4 * NCTORS))):
            self.call(fn & ~1 | 1, count=50_000_000)
        self.models()                                    # the modelled side again, over what the constructors set
        self.load_ok = True
        self.fx['L'] = 77
        self.call(SETTINGS_SET | 1, SETTINGS, 0x36, 1, 0)    # RESAMPLE mode, as the page sets it
        uc.mem_write(EVENT2, struct.pack('<6h', 1, 0, 0, 0, 0, 0))
        self.call(REGISTRY_F | 1, EVENT2, count=20_000_000)  # the RESAMPLE page object, as on page entry
        self.page = self.r32(PAGE_PTR)
        self.w32(PREFILTER, 0xFFFFFFFF)
        uc.mem_write(KEY_PAIRS, b'\xff' * 0x80)
        uc.mem_write(PAGE_LIVE, struct.pack('<H', 0x0E))
        for a, n in WATCHED.items():
            uc.hook_add(UC_HOOK_CODE, self._watch, n, begin=a, end=a)
        uc.hook_add(UC_HOOK_MEM_WRITE, self._bank, None, begin=SMPL + 0x14, end=SMPL + 0x1B)

    def mprofile(self):
        """M-profile special registers (the RTOS's critical sections) in this copy of the code: MSR -> nop.w,
        MRS -> mov.w rd, #0 (Unicorn's Thumb is A-profile)."""
        n = 0
        for base, size in ((0x400, 0x1F800), (0x80000000, 0x240000)):
            code = bytearray(self.uc.mem_read(base, size))
            for i in range(0, size - 4, 2):
                h1, h2 = code[i] | code[i + 1] << 8, code[i + 2] | code[i + 3] << 8
                if (h1 & 0xFFF0) == 0xF380 and (h2 & 0xFF00) == 0x8800 and 0x10 <= (h2 & 0xFF) <= 0x14:
                    code[i:i + 4] = bytes.fromhex('aff30080')
                    n += 1
                elif h1 == 0xF3EF and (h2 & 0xF000) == 0x8000 and 0x10 <= (h2 & 0xFF) <= 0x14:
                    code[i:i + 4] = bytes([0x4F, 0xF0, 0x00, (h2 >> 8) & 15])
                    n += 1
            self.uc.mem_write(base, bytes(code))
        return n

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
            self.uart.append((self.ui_ms, (base - 0x40184000) // 0x4000 + 1, value & 0xFF))
        elif off == 0x14:
            uc.mem_write(address, struct.pack('<I', 0x00C00000))    # transmit ready

    def _watch(self, uc, a, size, name):
        r = [s32(uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}'))) for k in range(1, 4)]
        self.calls.append((self.ui_ms, name) + tuple(r))

    def _bank(self, uc, access, address, size, value, _):
        self.calls.append((self.ui_ms, 'current ' + ('bank' if address < SMPL + 0x18 else 'pad'), value))

    def ui(self, ms=1):
        self.ui_ms += ms
        self.call(UI_TICK | 1, ms, count=5_000_000)
        self.call(UI_DRAIN | 1, count=5_000_000)
        if self.ui_ms // 16 != (self.ui_ms - ms) // 16 and self.r16(PAGE_ID) == 0x0E and self.page:
            # every 16 ms (also across a 2 ms step), the page's tick through its vtable entries: +0xd0 (refresh 0),
            # every fourth time +0xcc (refresh 1)
            entry = RS_TICK1 if (self.ui_ms // 16) % 4 == 0 else RS_TICK0
            self.call(entry | 1, self.page, count=20_000_000)
        due = self.final_due
        self.settle()
        if due is not None and self.final_due is None:    # the stock finalize ends with UI events 0xd and 0xc
            self.call(0x800D9ED1, 0xD)
            self.call(0x800D9ED1, 0xC)

    def setting(self, sid, idx=0):
        return s32(self.call(SETTINGS_GET | 1, SETTINGS, sid, idx))

    def system(self, sid, idx=-1):
        return s32(self.call(SYSTEM_GET | 1, SYSPRM_OBJ, sid, idx))

    def bus_fx(self):
        return self.system(0x276, 1), self.system(0x276, 2)

    def chip(self):
        """The UART bytes, grouped into SysEx frames."""
        frames, cur = [], []
        for ms, port, b in self.uart:
            cur.append(b)
            if b == 0xF7:
                frames.append((ms, port, bytes(cur).hex()))
                cur = []
        return frames + ([(None, None, bytes(cur).hex())] if cur else [])

    def params(self):
        """Every settings and system parameter, project parameter (and per pad) and pad parameter, read through
        the stock getters."""
        out = {}
        for sid in range(0xAD):
            out[('settings', sid)] = self.setting(sid)
        for pid in list(range(2, 0x80)) + list(range(0x80, 0x120)):
            out[('project', pid)] = s32(self.call(PROJECT_GET | 1, PROJECT, pid, 0xFFFFFFFF))
        for sid in range(0x2A0):
            out[('system', sid)] = self.system(sid)
        for bus in range(5):
            out[('system', 0x276, bus)] = self.system(0x276, bus)
        out[('bank',)], out[('pad',)] = self.r32(SMPL + 0x14), self.r32(SMPL + 0x18)
        for pad in range(160):
            for pid in range(0x64, 0x80):
                out[('pad', pid, pad)] = self.pad_get(pid, pad)
        return out

    def snapshot(self):
        return {b: bytes(self.uc.mem_read(b, n)) for b, n in AUDIT_REGIONS}


AUDIT_REGIONS = ((0x82DF0000, 0x60000), (0x80590000, 0x10000), (0x80240000, 0x10000), (0x833B8000, 0x1000))


def raw_diff(a, b):
    out = []
    for base in a:
        x, y = a[base], b[base]
        i = 0
        while i < len(x):
            if x[i] != y[i]:
                j = i
                while j < len(x) and x[j] != y[j]:
                    j += 1
                out.append((base + i, j - i))
                i = j
            else:
                i += 1
    return out


def scene(m, src=32, fx=(3, 2)):
    """Bank C current, a one-shot on C-1, BUS 1 and BUS 2 with an effect on, EXT SOURCE off, the UI settled."""
    m.call(SYSTEM_SET | 1, SYSPRM_OBJ, 0x276, fx[0], 1)
    m.call(SYSTEM_SET | 1, SYSPRM_OBJ, 0x276, fx[1], 2)
    m.call(PADSET | 1, SMPL, 0, src // 16, 0)
    pcm = pcm_burst(3000, 9)
    m.load_pad(src, 3000)
    m.voice = Voice(m, src, pcm, 0, 3000, 0, 1)
    for _ in range(32):
        m.ui(1)
    return pcm


def tick_bridge_checks(img, parent, man):
    """The tick bridge, on the real global objects. A take has just ended: the page's last tick saw state 2.
    On the parent, and on the image with no bounce, the page's next tick runs its state handler and its
    after-recording routine (BUS 1/2 effects off, the stock pad handler's destination current, RESAMPLE left).
    While a bounce holds the page (it owns the recorder, or its run is over and the recorder not idle yet) the
    tick finds no change and does none of that; the page is let go on the first tick with the run over and the
    recorder idle, and the tick never sees the run end."""
    res = []
    for image, mm, hold, own, rec in ((parent, None, None, None, 0), (img, man, 0, 0, 0), (img, man, 1, 1, 0),
                                      (img, man, 1, 0, 0), (img, man, 1, 0, 2)):
        m = RealMachine(image, mm)
        m.call(SYSTEM_SET | 1, SYSPRM_OBJ, 0x276, 3, 1)
        m.call(SYSTEM_SET | 1, SYSPRM_OBJ, 0x276, 2, 2)
        m.call(PADSET | 1, SMPL, 0, 2, 0)             # bank C current
        m.call(SETTINGS_SET | 1, SETTINGS, 0x59, 1, 0)  # END Snap on
        m.w32(0x80245A48, 1)                          # the stock pad handler's last destination: B-5
        m.w32(0x80245A44, 4)
        if hold is not None:
            m.w32(m.sym['bnc_page'], hold)
            m.w32(m.sym['bnc_own'], own)
        m.uc.mem_write(REC_STATE, bytes([rec]))
        m.calls, m.uart = [], []
        m.w32(m.page + PAGE_LAST, 2)                  # the page's last tick saw state 2: a take just ended
        held = []
        for i in range(40):                           # its next ticks; SMPL TASK takes the queued writes
            if i == 20:
                m.uc.mem_write(REC_STATE, b'\x00')    # a pending cancel taken: the recorder idle
            m.ui(1)
            held.append(m.r32(m.sym['bnc_page']) if hold is not None else None)
        res.append(dict(fx=m.bus_fx(), bank=m.r32(SMPL + 0x14), pad=m.r32(SMPL + 0x18), resample=m.setting(0x36),
                        snap=m.setting(0x59), last=m.r32(m.page + PAGE_LAST), calls=[c[1:] for c in m.calls],
                        tx=m.chip(), held=held))
    stock, idle, owned, over, pending = res
    check(stock['fx'] == (0, 0) and stock['bank'] == 1 and stock['pad'] == 4 and stock['resample'] == 0,
          f'the stock tick after a take: BUS 1/2 effects off, the stock pad handler\'s destination B-5 current, '
          f'RESAMPLE left ({stock["fx"]}, bank {stock["bank"]}, pad {stock["pad"]}, 0x36 {stock["resample"]})')
    check({k: v for k, v in idle.items() if k != 'held'} == {k: v for k, v in stock.items() if k != 'held'},
          'tick bridge, no bounce: the tick runs exactly as the parent\'s (the same writes, effects, bank, pad, '
          'RESAMPLE mode, END Snap, chip messages)')
    for r, label in ((owned, 'a bounce owning the recorder'), (over, 'the run over, the recorder idle'),
                     (pending, 'the run over, its cancel not yet taken')):
        acts = [c for c in r['calls'] if c[0] in ('page', 'current bank', 'current pad') or c[:2] in (
            ('system', 0x276), ('project', 0), ('project', 1), ('settings', 0x36), ('settings', 0x59),
            ('settings', 0x32), ('pad', 0x6F))]
        check(r['fx'] == (3, 2) and r['bank'] == 2 and r['resample'] == 1 and r['snap'] == 1 and not acts and
              r['tx'] == [] and r['last'] == 0,
              f'tick bridge, {label}: the tick sees no change and does nothing (effects on, bank C, RESAMPLE mode, '
              f'END Snap on, no state handler, no page request, nothing to the chip) ({r["fx"]}, bank {r["bank"]}, '
              f'{acts[:3]})')
    check(owned['held'][-1] == 1 and over['held'][-1] == 0 and pending['held'][19] == 1 and
          pending['held'][-1] == 0,
          f'the page is held while the bounce owns the recorder and let go on the first tick with the run over and '
          f'the recorder idle ({owned["held"][-1]}, {over["held"][-1]}, {pending["held"][19]}, '
          f'{pending["held"][-1]})')
    note('the tick bridge against the parent, on the real global objects')


# What a bounce may change, and why. Parameter keys (see RealMachine.params) and raw address ranges.
AUDIT_PARAMS = {
    ('project', 0xEF): 'the last pad played: the run plays the source through the stock pad note',
    ('project', 0x98): 'derived from the voice slots (0x80017c00 looks for one holding the current pad): the run '
                       'plays the source, which leaves its voice slot pointing at it, as tapping the pad does',
}


CURRENT_PAD_VIEW = ('the current pad\'s parameters as the project getter (0x64..0x7f) and system parameter 0x276 '
                    '(index -1: the effect on the current pad\'s bus) show them: the current pad is the source, '
                    'which REPLACE replaced')


def audit_allowed(addr, pads):
    """Raw bytes a bounce may change, with the reason. pads: the pads the run writes (its destination; with
    REPLACE also the source, which the exchange swaps with it)."""
    for pad in sorted(pads):
        rec = SMPL + 0xD0 + pad * 0xAC
        for lo, hi, why in (
                (rec, rec + 0xAC, "the parameter record of a pad the run writes"),
                (SMPL + 0x6CFC + pad * 24, SMPL + 0x6CFC + pad * 24 + 24, "the name of a pad the run writes"),
                (SMPL + 0xF800 + pad * 0x80, SMPL + 0xF800 + pad * 0x80 + 0x80,
                 "the extended block of a pad the run writes (the stock finalize resets it, the exchange swaps it; "
                 "the modelled finalize does not reset it)"),
                (FILE_INFO + pad * 36, FILE_INFO + pad * 36 + 36, "the file information of a pad the run writes")):
            if lo <= addr < hi:
                return why
    for lo, hi, why in (
            (SMPL + 0x1C, SMPL + 0x1D, 'the pads edited flag (the stock name function sets it)'),
            (0x80592380, 0x80592381, "the stock pad setter's change flag (0x80018600), raised by its writes of the "
                                     "destination pad's START, END and loop point, as the stock finalize raises it"),
            (0x82E00AE0, 0x82E00AE4, 'project 0xef, the last pad played (the run plays the source by the stock '
                                     'pad note)'),
            (0x80246E14, 0x80246E18, "recorder target 0: the destination's bank, as the stock destination pick sets it"),
            (0x805917E0, 0x805917E8, "SMPL TASK's queue: its put and take indices"),
            (0x805919B0, 0x805919B8, 'the UI event queue: its put and take indices'),
            (0x8059179C, 0x805917A0, "the input level meter (the stock feed's peaks, 0x1ca80)"),
            (0x80245884, 0x8024589C, 'the stock key event records (the keys pressed)'),
            (0x8024589C, 0x802458E8, 'the stock popup state'),
            (0x802468D8, 0x80246918, 'the popup text'),
            (0x80592438, 0x8059243C, 'the panel refresh flags (key LEDs)'),
            (0x8059245C, 0x80592460, 'the panel refresh flags'),
    ):
        if lo <= addr < hi:
            return why
    return None


def audit_run(img, man, target=T_PAD, exit_in=None):
    """A bounce of C-1 on the real global objects, every key through the UI task's dispatcher: the gesture, VALUE
    pressed for REPLACE, REC; audio periods until the run is over (EXIT after exit_in = (state, n): n periods in
    that state), then 3 s more of the UI. Before it: bank C, BUS 1 and BUS 2 with an effect on, END Snap on. The RESAMPLE page's
    tick runs every 16 ms through its vtable entries (RealMachine.ui); each entry is logged with the recorder's
    state and the refresh flag."""
    m = RealMachine(img, man)
    m.call(SETTINGS_SET | 1, SETTINGS, 0x59, 1, 0)    # END Snap on: the run pins it off and must restore it
    pcm = scene(m)
    p0, r0 = m.params(), m.snapshot()
    m.calls, m.uart = [], []
    ticks = set()
    m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, size, _: ticks.add((m.r8(REC_STATE), uc.reg_read(ar.UC_ARM_REG_R1))),
                  None, begin=RS_TICK, end=RS_TICK)
    m.dispatch(EV_KEY, KEY_RESAMPLE)
    m.dispatch(EV_PAD, 0, 100)
    m.dispatch(EV_PAD_UP, 0, 0)
    m.dispatch(EV_KEY_UP, KEY_RESAMPLE)
    m.ui(1)
    if target == T_REPLACE:
        m.dispatch(EV_KEY, KEY_VALUE)
        m.dispatch(EV_KEY_UP, KEY_VALUE)
        m.ui(1)
    picked = m.u('target')
    m.dispatch(EV_KEY, KEY_REC)
    m.dispatch(EV_KEY_UP, KEY_REC)
    exited, n = False, 0
    target1 = m.r32(TARGET_VALUES + 4)
    for _ in range(6000):
        m.period()
        st = m.u('state')
        if exit_in is not None and not exited and st == exit_in[0]:
            n += 1
            if n > exit_in[1]:
                m.dispatch(EV_KEY, KEY_EXIT)
                m.dispatch(EV_KEY_UP, KEY_EXIT)
                exited = True
        if st == U_IDLE:
            break
    for _ in range(3000):
        m.ui(1)
    return dict(m=m, pcm=pcm, p0=p0, r0=r0, p1=m.params(), r1=m.snapshot(), picked=picked, ticks=ticks,
                exited=exited, target1=(s32(target1), s32(m.r32(TARGET_VALUES + 4))))


def stock_resample(s, pad):
    """A stock RESAMPLE through the stock page handlers: the empty pad (bank C) as the destination and standby, REC,
    the source C-1, REC, the finalize. Returns the recorder's state after the first REC."""
    s.dispatch(EV_PAD, pad % 16, 100)
    s.dispatch(EV_PAD_UP, pad % 16, 0)
    for _ in range(30):
        s.period()
    s.dispatch(EV_KEY, KEY_REC)                         # REC: the take starts
    s.dispatch(EV_KEY_UP, KEY_REC)
    for _ in range(30):
        s.period()
    started = s.r8(REC_STATE)
    s.dispatch(EV_PAD, 0, 127)                          # the source
    s.dispatch(EV_PAD_UP, 0, 0)
    for _ in range(150):
        s.period()
    s.dispatch(EV_KEY, KEY_REC)                         # REC: the take stops
    s.dispatch(EV_KEY_UP, KEY_REC)
    for _ in range(2000):
        s.period()
    return started


def audit_checks(img, man):
    """Whole bounces on the real global objects, against the state before them and against a stock RESAMPLE.

    Logged: every settings, project, system, pad and sequencer write, every page request, every bank or pad
    change, every byte to the effects chip's UART. Every parameter (settings, project, system, all pads) is read
    through the stock getters before and after, and the global objects are diffed byte for byte. A difference
    passes only if it is on the allowlist above, with its reason. TO PAD, REPLACE, EXIT during the take and EXIT
    in the silence wait; each with the RESAMPLE page's tick running in standby (and while recording)."""
    refresh = set()
    for label, target, exit_in in (('TO PAD', T_PAD, None), ('REPLACE', T_REPLACE, None),
                                   ('EXIT during the take', T_PAD, (U_RUN, 10)),
                                   ('EXIT in the silence wait', T_PAD, (U_SILENCE, 60))):
        r = audit_run(img, man, target, exit_in)
        m, p0, p1 = r['m'], r['p0'], r['p1']
        dst, src = m.u('dst'), 32
        if exit_in is None:
            pads = {dst, src} if target == T_REPLACE else {dst}
            want = 'REPLACED C-1\nORIG ON C-2' if target == T_REPLACE else 'BOUNCED C-1\nON C-2'
            check(r['picked'] == target and m.u('runs') == 1 and m.u('r_exact') == 1 and dst == 33 and
                  m.take[77:77 + 3000] == r['pcm'] and m.popup() == want,
                  f'audit, {label}: the bounce of C-1 ran, frame-exact, on the real objects ({m.popup()!r})')
        else:
            pads = set()
            check(r['exited'] and m.popup() == 'BOUNCE CANCELLED\nNOTHING CHANGED',
                  f'audit, {label}: cancelled ({m.popup()!r})')
        states = {s for s, f in r['ticks']}
        refresh |= {f for s, f in r['ticks']}
        check(1 in states and (exit_in is not None and exit_in[0] == U_SILENCE or 2 in states),
              f'audit, {label}: the RESAMPLE page\'s tick ran during the run (recorder states {sorted(states)})')
        check(m.chip() == [], f'audit, {label}: nothing to the effects chip ({m.chip()[:2]})')
        check(m.bus_fx() == (3, 2), f'audit, {label}: BUS 1 and BUS 2 keep their effects ({m.bus_fx()})')
        check(m.r32(SMPL + 0x14) == 2 and m.setting(0x36) == 1 and m.r16(PAGE_ID) == 0x0E,
              f'audit, {label}: bank C stays current; RESAMPLE mode and page stay')
        check(m.setting(0x59) == 1 and m.setting(0x32) == p0[('settings', 0x32)],
              f'audit, {label}: END Snap back on; the RESAMPLE screen state as before ({m.setting(0x59)}, '
              f'{p0[("settings", 0x32)]} -> {m.setting(0x32)})')
        allowed_calls = {('settings', 0x24), ('settings', 0x59), ('settings', 0x1A), ('settings', 0x32),
                         ('settings', 0x34), ('project', 0xEF)}
        bad = []
        for c in m.calls:
            kind = c[1]
            if kind in ('settings', 'project') and (kind, c[2]) in allowed_calls:
                continue
            if kind == 'pad' and c[4] in pads:
                continue                              # the run's pads: the take's settings, the exchange
            if kind == 'seq' and c[2] in (0x7B, 0x37, 0x46):
                continue                              # the stock pad note and page tick: the tempo recomputed
            if kind == 'system' and c[2] == 0x275 and c[3] == p0[('system', 0x275)]:
                continue                              # the tempo written again with its own value
            bad.append(c)
        check(not bad, f'audit, {label}: every write during the run is on the allowlist ({bad[:4]})')
        changed = {k: (p0[k], p1[k]) for k in p0 if p0[k] != p1[k] and not (k[0] == 'pad' and k[2] in pads)}
        current = p0[('bank',)] * 16 + p0[('pad',)]
        explained = dict(AUDIT_PARAMS)
        if current in pads:                           # REPLACE of the current pad: its views changed with it
            explained.update({k: CURRENT_PAD_VIEW for k in changed if k == ('system', 0x276) or
                              (k[0] == 'project' and 0x64 <= k[1] < 0x80)})
        unexplained = {k: v for k, v in changed.items() if k not in explained}
        check(not unexplained, f'audit, {label}: every settings, project, system and pad parameter but the run\'s '
                               f'pads\' is as before ({list(unexplained.items())[:6]})')
        diffs = raw_diff(r['r0'], r['r1'])
        raw = [(a, n) for a, n in diffs if not audit_allowed(a, pads)]
        used = sorted({audit_allowed(a, pads) for a, n in diffs} - {None})
        print(f'   audit, {label}: changed bytes explained by: ' + '; '.join(used))
        print(f'   audit, {label}: parameters changed besides the run\'s pads: ' +
              ('; '.join(f'{k} {v}' for k, v in changed.items()) or 'none') + f'; recorder target 1 {r["target1"]}')
        check(not raw, f'audit, {label}: every changed byte of the global objects is on the allowlist '
                       f'({[(hex(a), n) for a, n in raw[:8]]})')
        if label == 'TO PAD':                         # the page let go: a stock RESAMPLE next ends as stock
            started = stock_resample(m, 34)
            check(started == 2 and len(m.finalized) == 2 and m.r32(m.sym['bnc_page']) == 0 and
                  m.bus_fx() == (0, 0) and m.setting(0x36) == 0 and m.r32(SMPL + 0x14) == 2 and
                  m.r32(SMPL + 0x18) == 34 % 16,
                  f'audit, a stock RESAMPLE into C-3 after the TO PAD bounce: it ends as stock (BUS 1/2 effects off, '
                  f'the new pad current, RESAMPLE left) ({m.bus_fx()}, 0x36 {m.setting(0x36)}, pad '
                  f'{m.r32(SMPL + 0x18)})')
    check(refresh == {0, 1}, f'audit: the page\'s tick ran through both its entries, refresh 0 and 1 ({refresh})')
    # the stock RESAMPLE of the same pad, through the stock page handlers: it ends with the stock routine
    s = RealMachine(img, man)
    scene(s)
    s.calls = []
    dst = 33
    started = stock_resample(s, dst)
    check(started == 2 and len(s.finalized) == 1 and s.bus_fx() == (0, 0) and s.setting(0x36) == 0 and
          s.r32(SMPL + 0x14) == 2 and s.r32(SMPL + 0x18) == dst % 16,
          f'audit, stock RESAMPLE of the same pad: after the take the stock routine switches BUS 1/2 effects off, '
          f'makes the new pad current and leaves RESAMPLE (effects {s.bus_fx()}, 0x36 {s.setting(0x36)}, '
          f'pad {s.r32(SMPL + 0x18)}); the bounce does none of that')
    note('the whole-state audit against the state before and a stock RESAMPLE')


def main():
    out = Path(sys.argv[1])
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    parent = Path(man['parent_app1']).read_bytes()
    static_checks(out, man, img, parent)
    bridge_checks(img, parent, man)
    tick_bridge_checks(img, parent, man)
    interface_checks(img, man)
    gate_checks(img, man)
    filter_checks(img, man)
    dispatcher_checks(img, man)
    looper_checks(img, man)
    r = runs(img, man)
    settings_checks(img, man)
    replace_checks(img, man)
    fence_checks(img, man)
    audit_checks(img, man)
    leak_checks(img, man)
    failure_checks(img, man)
    cost_checks(img, man)
    print(json.dumps(dict(runs=r, cases=cases[0])))
    print('ALL PASS' if not fails else f'{len(fails)} FAILED')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
