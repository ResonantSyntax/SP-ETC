"""BOUNC (kits v9.45): the kit into a sample bank, through the real stock REC exporter.

The built APP1 is booted as test_kit_midi.py does it (its Machine). The stock
exporter runs for real: 0x801327b8, the v4 export engine, Roland's renderer and
file writer, the oscillator gate, the kit engine and v9's export mix. Only the
file and project calls the exporter makes are modelled: path, open, write,
close, delete, the header, the stream cache and the pad registration (size,
name, load, save). A pad holds a sample exactly when the model holds its file,
which is also what 0x800d8b00 answers. Keys reach the SG page through the stock
page dispatcher 0x800a80a8 (the kits' event hook included) and the SG page's own
handlers (vtable 0x80229668). One SG screen update is one call of arp_poll. No
screen, SD card, eMMC or RTOS: writes to a real card are not covered.

1. Audio. All 13 kits x 16 factory pads, then four kits (TR808, FM, SDS-V,
   TR727) with every pad's six knobs and LEVEL changed. Bouncing pad p writes
   one file, to bank * 16 + p: path, open, header, stream cache, size, name SG,
   load and save all name that pad, and nothing else is touched. Its audio is a
   drum REC of pad p as REC takes a pad not struck in this kit, at velocity
   127, on a cleared export voice (BOUNC clears it; REC keeps whatever filter
   state the table voices' previous export left): the kit engine's output is
   the same float for float, the PCM the same sample for sample up to v9's
   10 ms end fade, and the fade frames are exactly v9's fade of the REC frames.
   The length is the ring-out: the frame after the last sample at or above
   -60 dB of the pad's own peak, at most 10 s. The header and the size match
   that length.
2. The flow. An empty bank fills at once. A bank with samples asks about each
   used pad (KEEP/OVER, KEEP by default), keeps edit mode on while asking,
   replaces only OVER pads (old file deleted first) and never touches a KEEP
   pad. EXIT during the questions writes nothing and stays on the page; EXIT
   during the run keeps what was written and writes nothing more. REC is
   ignored while a bounce is open, and a bounce does not start while an imprint
   is armed. A pad that gets a sample during the run is left alone. Knob edits
   during the run do not reach it. Leaving the page or switching the machine
   cancels. Pads with LEVEL 0 or the sound off are left out and never asked
   about. A file that cannot be created stops the bounce with ERROR. The bank
   value stops at -- and J.
3. With a v9.44 build as the second argument: drum REC (factory and tweaked
   pads, seconds and periods PAD LENGTH) and melodic REC write byte-identical
   files with identical headers and registrations on both builds, so the length
   hook does nothing outside BOUNC.

Usage: python synth/test_kit_bounce.py out/kits-v945 [out/kits-v944] [--quick | --flow]
(--quick: three kits for part 1; --flow: no part 1. The full run takes about 40 minutes.)
"""
from __future__ import annotations

import json
import math
import struct
import sys
import time
from pathlib import Path

import numpy as np
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as ar

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_kit_midi import Machine, RET, STACK, BUF, KB, PAGE, SG  # noqa: E402

V0, EXPORT_BASE, COUNT = 0x80249800, 0x8353C000, 0x8353C700
EXPORTER, PCM_BUF, HEADER_BUF = 0x801327B8, 0x80BCD208, 0x30018000
DISPATCHER, SG_VTABLE, FAKE_PAGE, EVENT = 0x800A80A8, 0x80229668, 0x83D00000, 0x30017000
PAGE_REQUEST = 0x8024587C                 # 0x800da598(n) stores the page it requests here
EDIT = KB + 0x14
CAP, FLOOR, FADE = 480000, np.float32(1e-3), 480
VALUE, EXIT, REC_KEY = 0x31, 0x22, 0x1B
IDLE, ASK, RUN, DONE, STOP, FAIL = range(6)
SCRATCH_BANK = 9                          # references are recorded into bank J
# Stock file and project calls the exporter makes (all modelled, see Bouncer._fs).
FS = dict(project=0x800E1190, path=0x800D60C8, open=0x800DEC60, write=0x800DD9B8, close=0x800DEBD8,
          delete=0x800DECD8, alloc=0x800E1176, free=0x800E25B8, header=0x800C6B88, cache_close=0x800D0030,
          cache_pad=0x800D08E0, cache_a=0x800CF878, cache_b=0x800C0DB8, pad_info=0x800D9440,
          registered=0x800CFB20, size=0x800CFA68, name=0x800CFA28, load=0x800CFCA8, save=0x800CF218,
          used=0x800D8B00)


def f32(bits):
    return struct.unpack('<f', struct.pack('<I', bits))[0]


class Bouncer(Machine):
    """test_kit_midi's machine plus the exporter's file system and the SG page."""

    def __init__(self, folder, parent_symbols):
        self.files, self.log, self.fds, self.next_fd = {}, [], {}, 3
        self.fail_create = set()                                  # pads whose file cannot be created
        self.capture_y, self.y = False, []
        super().__init__(folder, parent_symbols)
        self._fpv5()
        self._fs()
        self._osc_hook()
        self.put(FAKE_PAGE, SG_VTABLE, '<I')                      # the SG page object: its vtable ...
        for k in range(3):                                        # ... and three child widgets
            self.put(FAKE_PAGE + 0x1A6C + 4 * k, FAKE_PAGE + 0x2000 + 0x100 * k, '<I')
        self.stub(0x800D0018)                                     # widget redraw request
        self.put(V0 + 0x5C, 33)                                   # note A4 and TUNE 440.0 Hz, as the SP
        self.put(V0 + 0x60, 4400)                                 # starts (PAD LENGTH in periods uses them)

    # -- emulator plumbing --
    def call(self, fn, *args, stack0=0, count=4_000_000_000):
        uc = self.uc
        uc.reg_write(ar.UC_ARM_REG_SP, STACK)
        uc.mem_write(STACK, struct.pack('<I', stack0 & 0xFFFFFFFF))
        for k, value in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), value & 0xFFFFFFFF)
        uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        uc.emu_start(fn | 1, RET, count=count)
        if uc.reg_read(ar.UC_ARM_REG_PC) != RET or uc.reg_read(ar.UC_ARM_REG_SP) != STACK:
            raise RuntimeError(('did not return cleanly', hex(fn), hex(uc.reg_read(ar.UC_ARM_REG_PC))))
        return uc.reg_read(ar.UC_ARM_REG_R0)

    def _fpv5(self):
        """Unicorn 2.1.4 lacks FPv5 VSEL and VRINTZ, which stock oscillator and exporter code use."""
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        regions = ((0x80007700, 0x840), (0x0001CB84, 0x180), (0x80132340, 0x320), (0x800D0668, 0x180),
                   (0x80019E30, 0x1F0), (0x80131C48, 0x2C0), (0x801327B8, 0x5A8))
        for start, size in regions:
            for ins in md.disasm(bytes(self.uc.mem_read(start, size)), start):
                if ins.mnemonic.startswith('vsel'):
                    self.uc.hook_add(UC_HOOK_CODE, self._vsel, (ins.mnemonic, ins.op_str),
                                     begin=ins.address, end=ins.address)
                elif ins.mnemonic == 'vrintz.f64':
                    regs = tuple(int(r.strip()[1:]) for r in ins.op_str.split(','))
                    self.uc.hook_add(UC_HOOK_CODE, self._vrintz, regs, begin=ins.address, end=ins.address)
                elif ins.mnemonic.startswith('vrint'):
                    raise ValueError(('unemulated FPv5 instruction', hex(ins.address), ins.mnemonic))

    @staticmethod
    def _vrintz(uc, address, size, regs):
        value = struct.unpack('<d', struct.pack('<Q', uc.reg_read(ar.UC_ARM_REG_D0 + regs[1])))[0]
        uc.reg_write(ar.UC_ARM_REG_D0 + regs[0], struct.unpack('<Q', struct.pack('<d', math.trunc(value)))[0])
        uc.reg_write(ar.UC_ARM_REG_PC, (address + size) | 1)

    @staticmethod
    def _vsel(uc, address, size, insn):
        mn, op = insn
        regs = [r.strip() for r in op.split(',')]
        nzcv = uc.reg_read(ar.UC_ARM_REG_APSR) >> 28
        n_, z, v = (nzcv >> 3) & 1, (nzcv >> 2) & 1, nzcv & 1
        take = {'gt': z == 0 and n_ == v, 'ge': n_ == v, 'eq': z == 1, 'vs': v == 1}[mn[4:6]]
        src = regs[1] if take else regs[2]
        uc.reg_write(ar.UC_ARM_REG_S0 + int(regs[0][1:]), uc.reg_read(ar.UC_ARM_REG_S0 + int(src[1:])))
        uc.reg_write(ar.UC_ARM_REG_PC, (address + size) | 1)

    def _ret(self, value=0):
        self.uc.reg_write(ar.UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.uc.reg_write(ar.UC_ARM_REG_PC, self.uc.reg_read(ar.UC_ARM_REG_LR))

    def _reg(self, n):
        return self.uc.reg_read(getattr(ar, f'UC_ARM_REG_R{n}'))

    def _cstr(self, address, limit=64):
        return bytes(self.uc.mem_read(address, limit)).split(b'\0')[0].decode('latin-1')

    def _pad_of_path(self, address):
        text = self._cstr(address)
        if not text.startswith('PAD'):
            raise AssertionError(('unexpected path', text))
        return int(text[3:])

    def _fs(self):
        def handler(name):
            def hook(uc, address, size, _):
                r0, r1, r2, r3 = (self._reg(k) for k in range(4))
                value = 0
                if name == 'path':                                # (buffer, pad, 0, project)
                    uc.mem_write(r0, b'PAD%03d\0' % r1)
                    self.log.append(('path', r1))
                elif name == 'open':
                    pad = self._pad_of_path(r0)
                    if r1 == 0:                                   # an existing file
                        value = 0xFFFFFFFF
                        if pad in self.files:
                            value = self.next_fd; self.next_fd += 1
                            self.fds[value] = dict(pad=pad, mode='read')
                        self.log.append(('open', pad, value != 0xFFFFFFFF))
                    elif r1 == 0x602 and pad in self.fail_create:  # e.g. storage full
                        value = 0xFFFFFFFF
                        self.log.append(('create_failed', pad))
                    elif r1 == 0x602:                             # create / truncate
                        value = self.next_fd; self.next_fd += 1
                        self.fds[value] = dict(pad=pad, mode='write', writes=[], header=None)
                        self.log.append(('create', pad))
                    else:
                        raise AssertionError(('open mode', hex(r1)))
                elif name == 'write':
                    fd = self.fds[r0]
                    if fd['mode'] != 'write':
                        raise AssertionError('write to a read handle')
                    fd['writes'].append((r1, bytes(uc.mem_read(r1, r2))))
                    value = r2
                elif name == 'close':
                    fd = self.fds.pop(r0)
                    if fd['mode'] == 'write':
                        self.files[fd['pad']] = fd
                    self.log.append(('close', fd['pad']))
                elif name == 'delete':
                    pad = self._pad_of_path(r0)
                    self.files.pop(pad, None)
                    self.log.append(('delete', pad))
                elif name == 'alloc':
                    uc.mem_write(HEADER_BUF, bytes(r0))
                    value = HEADER_BUF
                elif name == 'header':                            # (voice, fd, channels, data bytes)
                    self.fds[r1]['header'] = (r2, r3)
                elif name == 'cache_close':
                    self.log.append(('cache_close', r2))
                elif name == 'cache_pad':
                    self.log.append(('cache_pad', r1))
                elif name == 'pad_info':
                    self.log.append(('pad_info', r0))
                elif name == 'registered':
                    value = 1
                elif name == 'size':
                    self.log.append(('size', r1, r3))
                elif name == 'name':
                    self.log.append(('name', r1, self._cstr(r2)))
                elif name == 'load':
                    self.log.append(('load', r1))
                elif name == 'save':
                    self.log.append(('save', r1 - (1 << 32) if r1 >> 31 else r1))
                elif name == 'used':
                    value = int(r0 in self.files)
                elif name in ('cache_a', 'cache_b'):
                    self.log.append((name,))
                self._ret(value)
            return hook
        for name, address in FS.items():
            if name != 'project':
                self.uc.hook_add(UC_HOOK_CODE, handler(name), begin=address, end=address)
        self.stub(FS['project'])

    def _osc_hook(self):
        """Every kit_output return for export voice 0 (s0, right after the call in kit_gate)."""
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        gate, target = self.S['kit_gate'] & ~1, self.S['kit_output'] & ~1
        after = None
        for ins in md.disasm(bytes(self.uc.mem_read(gate, 0x40)), gate):
            if ins.mnemonic == 'bl' and int(ins.op_str.lstrip('#'), 16) == target:
                after = ins.address + ins.size
                break
        if after is None:
            raise AssertionError('kit_gate: no call to kit_output')

        def hook(uc, address, size, _):
            if self.capture_y and uc.reg_read(ar.UC_ARM_REG_R4) == EXPORT_BASE:
                self.y.append(uc.reg_read(ar.UC_ARM_REG_S0))
        self.uc.hook_add(UC_HOOK_CODE, hook, begin=after, end=after)

    # -- the SG page --
    def event(self, kind, a=0, b=0):
        self.uc.mem_write(EVENT, struct.pack('<3h', kind, a, b))
        return self.call(DISPATCHER, FAKE_PAGE, EVENT, count=50_000_000)

    def press(self, key):
        handled = self.event(5, key)
        self.event(6, key)
        return handled

    def turn(self, delta):
        self.event(7, 0, delta)

    def cursor(self):
        return self.setting(0x83)

    def to_bounce(self):
        if self.get(EDIT):
            raise AssertionError('edit mode on before moving the cursor')
        for _ in range(30):
            if self.cursor() == 22:
                return
            self.turn(1)
        raise AssertionError(('cursor never reached BOUNC', self.cursor()))

    def item(self):
        return self.text('arp_item_name', 22), self.text('arp_item_text', 22)

    def bstate(self):
        return self.sym('kit_bounce_state')

    def choose(self, bank):
        """Cursor on BOUNC, VALUE into edit mode, turn to `bank` (from --)."""
        self.to_bounce()
        self.press(VALUE)
        if self.get(EDIT) != 1 or self.item() != ('BOUNC', '--'):
            raise AssertionError(('BOUNC edit mode', self.get(EDIT), self.item()))
        for _ in range(bank + 1):
            self.turn(1)
        if self.item()[1] != 'ABCDEFGHIJ'[bank]:
            raise AssertionError(('bank value', self.item()))

    def run(self, limit=40):
        """SG screen updates until the bounce is no longer running; the log of each update.
        self.progress holds the BOUNC value after each update."""
        steps, self.progress = [], []
        for _ in range(limit):
            if self.bstate() != RUN:
                return steps
            mark = len(self.log)
            self.capture_y, self.y = True, []
            self.poll()
            self.capture_y = False
            steps.append((self.log[mark:], list(self.y)))
            self.progress.append(self.item()[1])
        raise AssertionError('bounce did not finish')

    # -- REC (the reference) --
    def clear_export_voice(self):
        stride = self.get(self.S['kit_voice_stride'], '<I')
        self.uc.mem_write(self.S['kit_slot'] + 4 * stride, bytes(stride))

    def rec(self, pad, abs_pad, units, velocity=127, clear=False):
        """A drum REC of `pad` through the stock exporter (count 0: the kit capture runs).
        clear: start from a cleared export voice, as BOUNC does (REC itself keeps whatever
        filter state the voice's previous export left in the table voices)."""
        if clear:
            self.clear_export_voice()
        self.setsym('kit_record_pad', pad)
        self.setsym('kit_record_velocity', velocity)
        self.put(COUNT, 0, '<I')
        self.put(V0 + 0x17C, abs_pad)
        self.put(V0 + 0x180, units)
        mark = len(self.log)
        self.capture_y, self.y = True, []
        self.call(EXPORTER, V0)
        self.capture_y = False
        if self.get(V0 + 0x17C) != -1:
            raise AssertionError(('REC did not finish', abs_pad))
        return self.files[abs_pad], self.log[mark:], list(self.y)

    def pad_bytes(self, kit, pad):
        return bytes(self.uc.mem_read(self.S['kit_pads'] + ((kit - 1) * 16 + pad) * 8, 8))

    def set_pad(self, kit, pad, raw):
        self.uc.mem_write(self.S['kit_pads'] + ((kit - 1) * 16 + pad) * 8, bytes(raw))


def pcm(file):
    """The file's PCM (big-endian, as the stock writer stores it) as frames x channels."""
    channels, size = file['header']
    head = [d for a, d in file['writes'] if a == HEADER_BUF]
    data = b''.join(d for a, d in file['writes'] if a == PCM_BUF)
    if len(head) != 1 or len(head[0]) != 0x200 or file['writes'][0][0] != HEADER_BUF:
        raise AssertionError('expected one 512-byte header block first')
    if len(data) != size or size % (2 * channels):
        raise AssertionError(('PCM size', len(data), size, channels))
    return np.frombuffer(data, dtype='>i2').astype(np.int64).reshape(-1, channels)


def ring_out(y_bits):
    """The kit_bounce_measure rule on float32 kit_output values."""
    peak, end = np.float32(0), 0
    for n, bits in enumerate(y_bits):
        y = np.float32(abs(f32(bits)))
        if y > peak:
            peak = y
        if y > 0 and y >= np.float32(peak * FLOOR):
            end = n + 1
    return end


def fade_model(rec_frames, length):
    """v9 export_mix's end fade, applied to REC frames that the master stage passed linearly."""
    fade = max(min(length // 4, FADE), 1)
    out = rec_frames[length - fade:length].copy()
    for k in range(fade):
        i = length - fade + k
        left = length - (i + 1)
        for c in range(out.shape[1]):
            x = int(out[k, c])
            if x % 2 or abs(x) > 24576:
                raise AssertionError(('fade frame outside the linear master range', i, x))
            s = x // 2
            faded = int(np.float32(s) * np.float32(left + 1) / np.float32(fade))
            out[k, c] = 2 * faded
    return out, fade


def check_pad(m, kit, pad, bank, steps_entry, label):
    """One bounced pad against an unstruck velocity-127 REC of it."""
    log, y_bounce = steps_entry
    target = bank * 16 + pad
    file = m.files[target]
    frames = pcm(file)
    length, channels = len(frames), frames.shape[1]
    if not 0 < length <= CAP or m.get(m.S['kit_bounce_length'] + 4 * pad, '<I') != length:
        raise AssertionError((label, 'length', length))
    touched = {e[1] for e in log if len(e) > 1 and e[0] != 'save'}
    want_log = [('path', target), ('open', target, False), ('cache_close', target), ('cache_pad', target),
                ('create', target), ('cache_pad', target), ('pad_info', target), ('close', target),
                ('size', target, 0x200 + length * channels * 2), ('name', target, 'SG'), ('load', target),
                ('save', -1)]
    if touched != {target} or log != want_log:
        raise AssertionError((label, 'file calls', log))
    if file['header'] != (channels, length * channels * 2):
        raise AssertionError((label, 'header', file['header']))
    # The reference: REC of the same pad into bank J, longer than the bounce.
    units = (length + 2 * FADE + 23999) // 24000
    ref, _, y_rec = m.rec(pad, SCRATCH_BANK * 16 + pad, units, clear=True)
    rec_frames = pcm(ref)
    if len(y_bounce) != length or len(y_rec) != units * 24000:
        raise AssertionError((label, 'oscillator calls', len(y_bounce), len(y_rec)))
    if y_bounce != y_rec[:length]:
        bad = next(i for i in range(length) if y_bounce[i] != y_rec[i])
        raise AssertionError((label, 'kit engine output differs', bad, f32(y_bounce[bad]), f32(y_rec[bad])))
    if ring_out(y_rec) != length and length != CAP:
        raise AssertionError((label, 'not the ring-out', length, ring_out(y_rec)))
    tail, fade = fade_model(rec_frames, length)
    if not np.array_equal(frames[:length - fade], rec_frames[:length - fade]):
        bad = int(np.argmax(np.any(frames[:length - fade] != rec_frames[:length - fade], axis=1)))
        raise AssertionError((label, 'PCM differs', bad, frames[bad], rec_frames[bad]))
    if not np.array_equal(frames[length - fade:], tail):
        raise AssertionError((label, 'end fade differs'))
    del m.files[SCRATCH_BANK * 16 + pad]
    return dict(frames=length, peak=int(np.abs(rec_frames).max()))


def bounce_all(m, kit, bank, label):
    m.files.clear()
    m.setsym('kit_mode', kit)
    m.choose(bank)
    if m.press(VALUE) != 1 or m.bstate() != RUN or m.get(EDIT) != 0 or m.item() != ('BOUNC', '0/16'):
        raise AssertionError((label, 'empty bank did not start', m.bstate(), m.get(EDIT), m.item()))
    steps = m.run()
    if len(steps) != 16 or m.bstate() != DONE or m.item() != ('BOUNC', 'DONE'):
        raise AssertionError((label, 'run', len(steps), m.bstate(), m.item()))
    if sorted(m.files) != [bank * 16 + p for p in range(16)]:
        raise AssertionError((label, 'files', sorted(m.files)))
    out = {}
    for pad in range(16):
        out[pad] = check_pad(m, kit, pad, bank, steps[pad], f'{label} pad {pad + 1}')
    return out


def tweak(seed, pad, raw):
    """Deterministic knob and LEVEL settings across the whole range (8-byte kit_pad)."""
    x = (seed * 1103515245 + pad * 2654435761 + 12345) & 0xFFFFFFFF
    r = lambda k, n: (x >> k) % n
    sound = raw[0]
    tune = r(0, 25) - 12
    decay = [0, 15, 35, 50, 65, 80][r(5, 6)]
    tone, sweep, noise, attack = r(8, 101), [0, 25, 50, 75, 100][r(12, 5)], r(15, 101), [0, 50, 100][r(19, 3)]
    level = 1 + r(21, 127)
    return bytes([sound, tune & 0xFF, decay, tone, level, sweep, noise, attack])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    quick = '--quick' in sys.argv
    out = Path(args[0]).resolve()
    baseline = Path(args[1]).resolve() if len(args) > 1 else None
    parent = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))['symbols']
    report, t0 = {}, time.time()

    # 1. Audio ---------------------------------------------------------------------------------------
    m = Bouncer(out, parent)
    kits = [] if '--flow' in sys.argv else [1, 6, 12] if quick else list(range(1, 14))
    factory, lengths, tweaked = {}, [], {}
    for kit in kits:
        res = bounce_all(m, kit, 1, f'kit {kit}')
        factory[kit] = [r['frames'] for r in res.values()]
        lengths += factory[kit]
        print(f'kit {kit}: 16 pads exact ({time.time() - t0:.0f} s)', flush=True)
    for kit in ([] if not kits else [12] if quick else [1, 5, 8, 13]):
        for pad in range(16):
            m.set_pad(kit, pad, tweak(kit, pad, m.pad_bytes(kit, pad)))
        res = bounce_all(m, kit, 2, f'kit {kit} tweaked')
        tweaked[kit] = [r['frames'] for r in res.values()]
        lengths += tweaked[kit]
        print(f'kit {kit} tweaked: 16 pads exact ({time.time() - t0:.0f} s)', flush=True)
    report['audio'] = dict(factory_pads=16 * len(factory), tweaked_pads=16 * len(tweaked),
                           frames_min=min(lengths, default=0), frames_max=max(lengths, default=0),
                           cap_reached=CAP in lengths,
                           factory_frames=factory, tweaked_frames=tweaked,
                           matches='kit engine float-exact and PCM sample-exact to an unstruck velocity-127 REC, '
                                   'end fade as v9 export_mix, length = ring-out (-60 dB of the pad peak)')

    # 2. The flow ------------------------------------------------------------------------------------
    m = Bouncer(out, parent)
    kit = 12
    m.setsym('kit_mode', kit)
    m.to_bounce()
    if m.item() != ('BOUNC', '--'):
        raise AssertionError(('BOUNC at rest', m.item()))
    # Bank value: -- .. J, clamped at both ends; turning in edit mode never moves the cursor.
    m.press(VALUE)
    seen = []
    for d in [-1, -1] + [1] * 12 + [-1] * 3:
        m.turn(d)
        seen.append(m.item()[1])
    if seen != ['--', '--', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'J', 'J', 'I', 'H', 'G'] or m.cursor() != 22:
        raise AssertionError(('bank values', seen))
    for _ in range(10):
        m.turn(-1)
    if m.press(VALUE) != 1 or m.bstate() != IDLE or m.get(EDIT) != 0 or m.files:
        raise AssertionError('VALUE on -- must just leave edit mode')
    report['bank_value'] = dict(values=['--'] + list('ABCDEFGHIJ'), clamped=True)

    # A bank with samples on pads 4, 8 and 13: KEEP/OVER for each, KEEP by default.
    bank = 2
    old = {p: dict(pad=bank * 16 + p, mode='write', writes=[(HEADER_BUF, b'old')], header=(2, 0)) for p in (3, 7, 12)}
    m.files.update({bank * 16 + p: f for p, f in old.items()})
    m.choose(bank)
    m.log.clear()
    if m.press(VALUE) != 1 or m.bstate() != ASK or m.get(EDIT) != 1 or m.item() != ('C-4', 'KEEP'):
        raise AssertionError(('first question', m.bstate(), m.get(EDIT), m.item()))
    if m.press(REC_KEY) != 1 or m.get(KB, '<B') != 1:
        raise AssertionError('REC during the questions must do nothing')
    m.turn(1)
    if m.item() != ('C-4', 'OVER'):
        raise AssertionError(('OVER', m.item()))
    m.press(VALUE)
    if m.item() != ('C-8', 'KEEP') or m.get(EDIT) != 1:
        raise AssertionError(('second question', m.item()))
    m.press(VALUE)
    m.turn(1)
    m.turn(-1)
    if m.item() != ('C-13', 'KEEP'):
        raise AssertionError(('third question', m.item()))
    m.poll()                                                      # a screen update while asking: nothing
    if m.log or m.bstate() != ASK:
        raise AssertionError(('wrote while asking', m.log))
    m.press(VALUE)
    if m.bstate() != RUN or m.get(EDIT) != 0 or m.item() != ('BOUNC', '0/14'):
        raise AssertionError(('run after the questions', m.bstate(), m.get(EDIT), m.item()))
    if m.press(REC_KEY) != 1 or m.get(KB, '<B') != 1:
        raise AssertionError('REC during the run must do nothing')
    m.run()
    progress = m.progress
    written = sorted(e[1] - bank * 16 for e in m.log if e[0] == 'create')
    deleted = sorted(e[1] - bank * 16 for e in m.log if e[0] == 'delete')
    touched = {e[1] - bank * 16 for e in m.log if len(e) > 1 and e[0] not in ('save',)}
    if written != [p for p in range(16) if p not in (7, 12)] or deleted != [3] or touched & {7, 12}:
        raise AssertionError(('KEEP/OVER result', written, deleted, touched))
    if m.files[bank * 16 + 7] is not old[7] or m.files[bank * 16 + 12] is not old[12] or m.files[bank * 16 + 3] is old[3]:
        raise AssertionError('kept files must stay untouched, the OVER pad replaced')
    if progress[-1] != 'DONE' or progress[:3] != ['1/14', '2/14', '3/14']:
        raise AssertionError(('progress', progress))
    m.press(VALUE)                                                # edit mode again: back to --
    if m.item() != ('BOUNC', '--') or m.bstate() != IDLE:
        raise AssertionError(('after DONE', m.item()))
    m.turn(-1)
    m.press(VALUE)
    report['questions'] = dict(used_pads=[4, 8, 13], answers=['OVER', 'KEEP', 'KEEP'], written=14,
                               replaced=[4], kept_untouched=[8, 13], old_file_deleted_first=True,
                               edit_mode_kept_while_asking=True, rec_ignored=True, progress=progress)

    # EXIT during the questions: nothing written, no page change, edit mode off.
    bank = 3
    m.files[bank * 16] = dict(pad=bank * 16, mode='write', writes=[], header=(2, 0))
    m.choose(bank)
    m.log.clear()
    before = m.get(PAGE_REQUEST, '<H')
    m.press(VALUE)
    if m.bstate() != ASK or m.press(EXIT) != 1:
        raise AssertionError('EXIT while asking')
    for _ in range(3):
        m.poll()
    if m.bstate() != IDLE or m.get(EDIT) != 0 or m.log or m.get(PAGE_REQUEST, '<H') != before or m.item() != ('BOUNC', '--'):
        raise AssertionError(('EXIT while asking', m.bstate(), m.get(EDIT), m.log, m.item()))
    # EXIT during the run: the pads written so far stay, nothing more is written.
    bank = 4
    m.choose(bank)
    m.press(VALUE)
    for _ in range(3):
        m.poll()
    if m.press(EXIT) != 1 or m.bstate() != STOP or m.item() != ('BOUNC', 'STOP'):
        raise AssertionError(('EXIT during the run', m.bstate(), m.item()))
    count = len(m.files)
    for _ in range(5):
        m.poll()
    if sorted(p for p in m.files if bank * 16 <= p < bank * 16 + 16) != [bank * 16 + p for p in range(3)] or len(m.files) != count:
        raise AssertionError(('EXIT during the run wrote more', sorted(m.files)))
    if m.get(PAGE_REQUEST, '<H') != before:
        raise AssertionError('EXIT during the run left the page')
    report['exit'] = dict(while_asking='nothing written, stays on the page', during_run='3 pads written stay, no more')

    # An imprint armed: VALUE does not start a bounce.
    m.press(VALUE)                                                # edit mode on (from STOP: back to --)
    for _ in range(6):
        m.turn(1)                                                 # bank F
    m.press(REC_KEY)                                              # stock REC: the imprint is armed
    if m.get(KB, '<B') != 0:
        raise AssertionError('stock REC should arm an imprint outside a bounce')
    m.press(VALUE)
    if m.bstate() != IDLE or m.get(EDIT) != 0:
        raise AssertionError('a bounce started with an imprint armed')
    m.put(KB, 1, '<B')                                            # the imprint cancelled
    report['imprint_armed'] = 'no start'

    # A pad that gets a sample during the run is left alone; knob edits during the run do not reach it.
    bank = 5
    ref_pad = 8
    m.files.clear()
    original = m.pad_bytes(kit, ref_pad)
    ref, _, _ = m.rec(ref_pad, SCRATCH_BANK * 16 + ref_pad, 2, clear=True)
    m.choose(bank)
    m.press(VALUE)
    m.poll()
    m.poll()
    late = dict(pad=bank * 16 + 5, mode='write', writes=[], header=(2, 0))
    m.files[bank * 16 + 5] = late                                  # someone recorded into pad 6
    edited = bytearray(original); edited[1] = 5; edited[2] = 90; edited[4] = 40
    m.set_pad(kit, ref_pad, edited)                                 # pad 9 changed after the bank was chosen
    m.run()
    if m.files[bank * 16 + 5] is not late or m.sym('kit_bounce_wrote', '<H') != 0xFFFF & ~(1 << 5):
        raise AssertionError(('late sample replaced', hex(m.sym('kit_bounce_wrote', '<H'))))
    got = pcm(m.files[bank * 16 + ref_pad])
    want = pcm(ref)
    n = len(got) - FADE
    if not np.array_equal(got[:n], want[:n]):
        raise AssertionError('an edit during the run reached the bounce')
    m.set_pad(kit, ref_pad, original)
    m.press(VALUE)
    m.turn(-1)
    m.press(VALUE)
    report['during_run'] = dict(new_sample_kept=True, edits_not_applied=True)

    # Leaving the page, or switching the machine, cancels.
    bank = 6
    m.choose(bank)
    m.press(VALUE)
    m.poll()
    m.page(0x01)
    m.event(0)                                                    # any event on another page
    m.page(SG)
    for _ in range(3):
        m.poll()
    if m.bstate() != STOP or len([p for p in m.files if bank * 16 <= p < bank * 16 + 16]) != 1:
        raise AssertionError(('page change', m.bstate()))
    m.press(VALUE)
    m.turn(-1)
    m.press(VALUE)
    m.files[7 * 16] = dict(pad=7 * 16, mode='write', writes=[], header=(2, 0))
    m.choose(7)
    m.press(VALUE)
    if m.bstate() != ASK:
        raise AssertionError('bank H should ask')
    m.page(0x01)
    m.event(0)
    m.page(SG)
    if m.bstate() != IDLE or m.get(EDIT) != 0:
        raise AssertionError('page change while asking')
    bank = 8
    m.choose(bank)
    m.press(VALUE)
    m.poll()
    m.uc.mem_write(0x80592448, bytes(16))
    keys = bytearray(16); keys[42 >> 3] |= 1 << (42 & 7); keys[21 >> 3] |= 1 << (21 & 7)
    m.uc.mem_write(0x80592448, bytes(keys))                         # SHIFT + PATTERN EDIT held
    m.call(m.S['kit_ui_key_query'], 42, 0)
    m.uc.mem_write(EVENT, struct.pack('<3h', 6, 21, 0))
    m.call(m.S['kit_shortcut_event'], FAKE_PAGE, EVENT, count=50_000_000)
    m.uc.mem_write(0x80592448, bytes(16))
    m.call(m.S['kit_ui_key_query'], 42, 0)
    if m.bstate() != STOP:
        raise AssertionError(('machine switch', m.bstate()))
    m.setsym('kit_mode', kit)
    report['cancel'] = dict(page_change='STOP (running) / -- (asking)', machine_switch='STOP')

    # Pads with LEVEL 0 or the sound off: left out, never asked about.
    m.files.clear()
    bank = 0
    m.files[2] = dict(pad=2, mode='write', writes=[], header=(2, 0))   # pad 3 used, but its LEVEL is 0
    saved = [m.pad_bytes(kit, p) for p in (2, 3)]
    silent = bytearray(saved[0]); silent[4] = 0
    off = bytearray(saved[1]); off[0] = 255
    m.set_pad(kit, 2, silent)
    m.set_pad(kit, 3, off)
    m.to_bounce()
    m.press(VALUE)
    m.turn(1)
    m.press(VALUE)
    if m.bstate() != RUN or m.item()[1] != '0/14':
        raise AssertionError(('silent pads', m.bstate(), m.item()))
    m.run()
    if sorted(m.files) != [p for p in range(16) if p != 3]:
        raise AssertionError(('silent pads written', sorted(m.files)))
    if m.files[2]['writes']:
        raise AssertionError('a LEVEL-0 pad replaced a sample')
    for p, raw in zip((2, 3), saved):
        m.set_pad(kit, p, raw)
    report['left_out'] = dict(level_0='not asked, not written', sound_off='not written')

    # A file that cannot be created: ERROR, nothing more is written, REC's destination is clear again.
    m.files.clear()
    bank = 9
    m.fail_create = {bank * 16 + 2}
    m.choose(bank)
    m.press(VALUE)
    m.run()
    if m.bstate() != FAIL or m.item() != ('BOUNC', 'ERROR') or sorted(m.files) != [bank * 16, bank * 16 + 1]:
        raise AssertionError(('failed write', m.bstate(), m.item(), sorted(m.files)))
    if m.get(V0 + 0x17C) != -1 or m.get(COUNT, '<I') != 0:
        raise AssertionError(('REC destination after a failed write', m.get(V0 + 0x17C), m.get(COUNT, '<I')))
    for _ in range(3):
        m.poll()
    if sorted(m.files) != [bank * 16, bank * 16 + 1]:
        raise AssertionError('wrote after ERROR')
    m.fail_create = set()
    m.press(VALUE)
    if m.item() != ('BOUNC', '--'):
        raise AssertionError(('after ERROR', m.item()))
    m.turn(-1)
    m.press(VALUE)
    report['write_error'] = dict(shown='ERROR', written_before=2, stops=True, rec_destination_cleared=True)

    # Melodic mode: BOUNC is not in the menu and its keys do nothing.
    m.setsym('kit_mode', 0)
    for _ in range(25):
        m.turn(1)
    if m.cursor() == 22:
        raise AssertionError('melodic menu reaches BOUNC')
    report['melodic'] = 'BOUNC not in the menu'

    # 3. The hook is inert outside BOUNC -------------------------------------------------------------
    if baseline:
        base_parent = json.loads((baseline / 'manifest.json').read_text(encoding='utf-8'))['symbols']
        builds = [Bouncer(out, parent), Bouncer(baseline, base_parent)]
        cases = []
        for kit in (1, 6, 10, 12):
            for pad in range(0, 16, 3):
                cases.append((kit, pad, 1, None))
        cases += [(5, 4, 2, 'tweak'), (13, 9, 1, 'tweak'), (1, 7, -1, None), (12, 0, -2, None)]
        results = []
        for build in builds:
            res = []
            for kit, pad, units, mod in cases:
                build.setsym('kit_mode', kit)
                if mod:
                    build.set_pad(kit, pad, tweak(kit, pad, build.pad_bytes(kit, pad)))
                file, log, _ = build.rec(pad, 3 * 16 + pad, units)
                res.append((file['header'], file['writes'], log))
                del build.files[3 * 16 + pad]
            build.setsym('kit_mode', 0)                           # melodic REC: Saw, A4
            build.uc.mem_write(V0 + 0x70, bytes([6, 6]))
            build.put(V0 + 0x5C, 33)
            build.put(V0 + 0x74, 10000)
            build.put(V0 + 0x198, 10000)
            for units in (1, -1):
                file, log, _ = build.rec(0, 3 * 16, units)
                res.append((file['header'], file['writes'], log))
                del build.files[3 * 16]
            results.append(res)
        if results[0] != results[1]:
            bad = next(i for i in range(len(results[0])) if results[0][i] != results[1][i])
            raise AssertionError(('REC differs from the baseline build', bad))
        frames = [r[0][1] // (2 * r[0][0]) for r in results[0]]
        report['baseline'] = dict(build=json.loads((baseline / 'manifest.json').read_text())['revision'],
                                  identical_recs=len(results[0]), drum=len(cases), melodic=2,
                                  pad_length_seconds_and_periods=True, frames=frames)

    report.update(passed=True, app1_sha256=m.man['sha256'], revision=m.man['revision'],
                  seconds=round(time.time() - t0))
    (out / 'bounce_check.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
