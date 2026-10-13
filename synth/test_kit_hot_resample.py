"""Hot resample with the kits: the SHIFT shortcuts on the RESAMPLE and SG pages.

Stock 5.52 hot resample: RESAMPLE, pick a pad (armed: "press pad to start"),
then SHIFT + RECORD SETTING opens the Sound Generator page; the first SG note
starts the take. The built APP1 is booted the way its scatter loader does it
(copy, decompress and zero rows). Key events go through the stock page-event
dispatcher entry 0x800a80a8, where the kit shortcut gate is installed, into
the real stock RESAMPLE (0x8012d5f0) and Sound Generator (0x8015c550) key and
release handlers. The SG screen poll is modelled by the stock key getter
0x800d9f20 (routed to kit_ui_key_query, which runs the kit chord observer).
The first kit hit goes through the real SG pad handler 0x8015bf90.

Stubbed and logged: the recorder command post 0x800e25c0 (a model of the
recorder state machine applies queued commands when settle() is called, as
SMPL TASK would later), both page requests (stock 0x800da598, DOOM
0x6031c9a8; settle() switches the page), the generic key handler, the settings
getter/setter/stepper (a dictionary), the all-stop, the dispatch locks, the SG
note engine bridge and the stock calls on the stop and LED paths. DOOM's
page-event filter in front of 0x800a80a8 is not run: it passes these keys on
unless the user binds them as DOOM shortcuts. No audio, timing or screen. This
is not a hardware test.

Checks:
1. RESAMPLE page: SHIFT + PATTERN EDIT opens the SG page in kit mode (the
   last kit) exactly when stock SHIFT + RECORD SETTING opens it (recorder
   state 0-3, destination chosen or not), posts no recorder command and keeps
   the take armed; its release does not select again.
2. SG page, settings 0x36 = 1, recorder state 1 or 2: SHIFT + PATTERN EDIT and
   SHIFT + RECORD SETTING switch machines without posting a recorder command
   (stock would start the take in state 1, stop it in state 2). Unshifted
   presses keep the stock start/stop; PATTERN SELECT and PITCH/SPEED are
   untouched; states 0 and 3 and ordinary SG use (0x36 != 1) are unchanged.
3. The stock chord SHIFT + RECORD SETTING from RESAMPLE opens the SG page
   with the current machine (kit or melodic) in every release order.
4. A whole session: RESAMPLE, pick a pad, SHIFT + PATTERN EDIT, switch
   machines, the first kit hit posts the start, switch machines while
   recording, RESAMPLE stops.

With --baseline the same scenarios run on v9.43 and must show its faults:
SHIFT + PATTERN EDIT does nothing on RESAMPLE, the SG chords start or stop
the take at the press, and the stock chord forces melodic.

Usage: python synth/test_kit_hot_resample.py out/kits-v943-test4
       python synth/test_kit_hot_resample.py out/kits-v943 --baseline
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_HOOK_CODE
from unicorn import arm_const as ar

FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
RET, STACK, OBJ, VTABLE, EVENT = 0x3001F000, 0x30010000, 0x30004000, 0x30008000, 0x30009000
PAGE, KEYS, KB, REC_STATE = 0x80245880, 0x80592448, 0x80591C48, 0x82E0E755
TOP, RESAMPLE, SG = 0x01, 0x0E, 0x1E
SHIFT, PATTERN_SELECT, PATTERN_EDIT, RECORD_SETTING, PITCH_SPEED, RESAMPLE_KEY = 42, 20, 21, 22, 24, 28
PRESS, RELEASE = 5, 6
P_DEST, P_MODE, P_CURSOR = 0x1A, 0x36, 0x83
DISPATCHER = 0x800A80A8                   # first 12 bytes jump to kit_shortcut_gate
KEY_GETTER = 0x800D9F20                   # jumps to kit_ui_key_gate
SG_PAD = 0x8015BF90
HANDLERS = {RESAMPLE: (0x8012D5F0, 0x8012CF60), SG: (0x8015C550, 0x8015BF78)}   # key press, release
# address: (name, value returned in r0)
STUBS = {
    0x800E25C0: ('post', 0), 0x800DA598: ('page_request', 0), 0x6031C9A8: ('doom_page_request', 0),
    0x800C9788: ('generic', 1), 0x800D94D8: ('setting_get', None), 0x800DD0C0: ('setting_set', 0),
    0x800BF8C8: ('setting_step', 0), 0x0001FE00: ('release_all', 0), 0x800DED08: ('dispatch_off', 0),
    0x800DECF8: ('dispatch_on', 0), 0x0001FC00: ('note', 0), 0x800CEDC0: ('led', 0),
    0x800CE420: ('modal', 0), 0x800C3E68: ('pad_mode', 0), 0x800BD8D0: ('stock', 0), 0x800E11D0: ('stock', 0),
    0x800DD030: ('stock', 0), 0x800BB128: ('stock', -1), 0x800BB110: ('stock', -1), 0x800DED18: ('stock', 0),
    0x800DDA38: ('stock', 0), 0x800E1180: ('stock', 0), 0x800D8C88: ('stock', 0), 0x800D31EE: ('stock', 0),
}
LAST_KIT = 6                              # TR909, chosen before each scenario


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
    """The built image after its boot copy, with a page object for one page's handlers."""

    def __init__(self, image, man):
        self.S = man['arp_symbols']
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
            elif handler != ZERO:                   # fresh mappings are already zero
                raise ValueError(f'unknown scatter handler {handler:#x}')
        uc.reg_write(ar.UC_ARM_REG_C1_C0_2, uc.reg_read(ar.UC_ARM_REG_C1_C0_2) | (0xF << 20))
        uc.reg_write(ar.UC_ARM_REG_FPEXC, 0x40000000)
        uc.mem_write(RET, b'\x00\xbf\x00\xbf')
        self.log, self.queue, self.requested = [], [], None
        self.settings = {P_DEST: -1, P_MODE: 0, P_CURSOR: 0}
        for address, (name, value) in STUBS.items():
            uc.hook_add(UC_HOOK_CODE, self._stub, (name, value), begin=address, end=address)
        self.put(KB, 1, '<B')                      # SG keyboard on (no imprint armed)
        self.keys = set()

    # -- emulator plumbing --
    def _stub(self, uc, address, size, data):
        name, value = data
        r = [uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}')) for k in range(4)]
        signed = [struct.unpack('<i', struct.pack('<I', x))[0] for x in r]
        if name == 'post':
            self.queue.append(r[0])
            self.log.append(('post', r[0]))
        elif name in ('page_request', 'doom_page_request'):
            self.requested = signed[0]
            self.log.append((name, signed[0]))
        elif name == 'generic':
            self.log.append(('generic', signed[2]))
        elif name == 'setting_get':
            value = self.settings.get(r[1], 0)
        elif name == 'setting_set':
            self.settings[r[1]] = signed[2]
            self.log.append(('set', r[1], signed[2]))
        elif name == 'setting_step':
            self.settings[r[1]] = self.settings.get(r[1], 0) + signed[2]
        elif name in ('release_all', 'note'):
            self.log.append((name,))
        uc.reg_write(ar.UC_ARM_REG_R0, value & 0xFFFFFFFF)
        uc.reg_write(ar.UC_ARM_REG_PC, uc.reg_read(ar.UC_ARM_REG_LR))

    def call(self, fn, *args):
        uc = self.uc
        uc.reg_write(ar.UC_ARM_REG_SP, STACK)
        for k, value in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), value & 0xFFFFFFFF)
        uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        uc.emu_start(fn | 1, RET, count=2_000_000)
        if uc.reg_read(ar.UC_ARM_REG_PC) != RET or uc.reg_read(ar.UC_ARM_REG_SP) != STACK:
            raise RuntimeError(('did not return cleanly', hex(fn), hex(uc.reg_read(ar.UC_ARM_REG_PC))))
        return uc.reg_read(ar.UC_ARM_REG_R0)

    def put(self, address, value, fmt='<i'):
        self.uc.mem_write(address, struct.pack(fmt, value))

    def get(self, address, fmt='<i'):
        return struct.unpack(fmt, bytes(self.uc.mem_read(address, struct.calcsize(fmt))))[0]

    # -- the SP --
    @property
    def mode(self):
        return self.get(self.S['kit_mode'], '<B')

    @mode.setter
    def mode(self, value):
        self.put(self.S['kit_mode'], value, '<B')

    @property
    def state(self):
        return self.get(REC_STATE, '<B')

    def page(self, value):
        """Show a page: the page object's vtable holds that page's stock key handlers."""
        self.put(PAGE, value, '<h')
        press, release = HANDLERS.get(value, HANDLERS[SG])
        self.put(OBJ, VTABLE, '<I')
        self.put(VTABLE + 0x18, press | 1, '<I')
        self.put(VTABLE + 0x1C, release | 1, '<I')

    @property
    def current(self):
        return self.get(PAGE, '<h')

    def recorder(self, state, dest=None, mode=None):
        self.put(REC_STATE, state, '<B')
        if dest is not None:
            self.settings[P_DEST] = dest
        if mode is not None:
            self.settings[P_MODE] = mode

    def _bitmap(self):
        bits = bytearray(16)
        for k in self.keys:
            bits[k >> 3] |= 1 << (k & 7)
        self.uc.mem_write(KEYS, bytes(bits))

    def event(self, kind, key):
        """The key bitmap changes first, then the event is dispatched (as the key task does)."""
        (self.keys.add if kind == PRESS else self.keys.discard)(key)
        self._bitmap()
        self.uc.mem_write(EVENT, struct.pack('<4h', kind, key, 0, 0))
        return self.call(DISPATCHER, OBJ, EVENT)

    def press(self, key):
        return self.event(PRESS, key)

    def release(self, key):
        return self.event(RELEASE, key)

    def poll(self):
        """The SG screen poll reads SHIFT through the stock key getter (runs the kit observer)."""
        return self.call(KEY_GETTER, SHIFT)

    def hit(self, pad, vel=100):
        """A pad strike on the SG page, through the stock pad handler."""
        return self.call(SG_PAD, OBJ, pad, vel)

    def settle(self):
        """SMPL TASK applies posted recorder commands; the UI task switches to a requested page."""
        for cmd in self.queue:
            s = self.state
            if cmd == 0x14 and s == 0:
                s = 1
            elif cmd == 0x17 and s in (1, 3):
                s = 2
            elif cmd in (0x18, 0x1A):
                s = 0
            elif cmd == 0x41D and s == 1:
                s = 3
            self.put(REC_STATE, s, '<B')
        self.queue = []
        if self.requested is not None:
            self.page(self.requested)
            self.requested = None

    def mark(self):
        self.log = []

    def posts(self):
        return [x[1] for x in self.log if x[0] == 'post']

    def requests(self):
        return [x[1] for x in self.log if x[0] in ('page_request', 'doom_page_request')]

    def count(self, name):
        return sum(1 for x in self.log if x[0] == name)


def check(ok, what):
    if not ok:
        raise AssertionError(what)


class Suite:
    def __init__(self, folder, baseline):
        self.man = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        self.image = (folder / 'SP404MKII_APP1.bin').read_bytes()
        if hashlib.sha256(self.image).hexdigest() != self.man['sha256']:
            raise ValueError('APP1/manifest hash mismatch')
        self.baseline = baseline
        self.cases = 0

    def machine(self, page, start_mode=LAST_KIT):
        """A fresh boot whose last kit is LAST_KIT, showing page with the SG in start_mode."""
        m = Machine(self.image, self.man)
        m.mode = LAST_KIT
        if start_mode == 0:                         # melodic now, LAST_KIT remembered
            m.page(SG)
            m.press(SHIFT); m.press(RECORD_SETTING); m.release(RECORD_SETTING); m.release(SHIFT); m.poll()
            check(m.mode == 0, ('setup: melodic shortcut', m.mode))
        else:
            m.mode = start_mode
        m.page(page)
        m.recorder(0, dest=-1, mode=0)
        m.queue, m.requested = [], None
        m.mark()
        return m

    # 1. SHIFT + PATTERN EDIT on the RESAMPLE page
    def resample_twin(self):
        out = []
        for state, dest in ((0, -1), (0, 5), (1, 5), (2, 5), (3, 5)):
            for start in (0, 3, LAST_KIT):
                stock = self.machine(RESAMPLE, start)
                stock.recorder(state, dest, 1)
                stock.press(SHIFT); stock.press(RECORD_SETTING)
                stock_jump = stock.requests() == [SG]
                check(stock.requests() in ([], [SG]) and not stock.posts(), ('stock RECORD SETTING', state, dest))
                for order in ('key_first', 'shift_first', 'release_after_switch'):
                    m = self.machine(RESAMPLE, start)
                    m.recorder(state, dest, 1)
                    m.press(SHIFT)
                    m.press(PATTERN_EDIT)
                    pressed = dict(requests=m.requests(), mode=m.mode, posts=m.posts(), generic=m.count('generic'))
                    if order == 'release_after_switch':
                        m.settle()
                        m.poll()
                    if order == 'shift_first':
                        m.release(SHIFT); m.release(PATTERN_EDIT)
                    else:
                        m.release(PATTERN_EDIT); m.release(SHIFT)
                    m.settle()
                    m.poll()
                    expected_mode = start if start else LAST_KIT
                    if self.baseline:
                        check(pressed['requests'] == [] and m.requests() == [] and m.mode == start and
                              m.current == RESAMPLE and pressed['generic'] == 1 and not m.posts(),
                              ('v9.43 RESAMPLE: SHIFT+PATTERN EDIT should do nothing', state, dest, start, order,
                               pressed, m.log))
                    elif stock_jump:
                        check(pressed['requests'] == [SG] and pressed['mode'] == expected_mode and
                              pressed['generic'] == 0 and m.requests() == [SG] and m.current == SG and
                              m.mode == expected_mode and not m.posts() and m.state == state and
                              m.count('release_all') == 1 and m.settings[P_MODE] == 1,
                              ('RESAMPLE twin should open kits', state, dest, start, order, pressed, m.mode, m.log))
                    else:
                        check(m.requests() == [] and m.mode == start and m.current == RESAMPLE and
                              not m.posts() and m.count('release_all') == 0,
                              ('RESAMPLE twin should do nothing with no pad armed', state, dest, start, order, m.log))
                    self.cases += 1
                out.append(dict(state=state, dest=dest, start_mode=start, stock_record_setting_opens_sg=stock_jump,
                                pattern_edit=('nothing' if self.baseline or not stock_jump else 'SG in kits')))
        return out

    # 2. SHIFT chords on the SG page during a hot resample
    def sg_chords(self):
        out = []
        for p36 in (1, 0):
            for state in (0, 1, 2, 3):
                for start in (0, LAST_KIT):
                    for key in (PATTERN_EDIT, RECORD_SETTING):
                        for order in ('key_first', 'shift_first'):
                            m = self.machine(SG, start)
                            m.recorder(state, 5, p36)
                            m.press(SHIFT); m.poll()
                            m.press(key)
                            at_press = m.posts()
                            m.poll()
                            if order == 'key_first':
                                m.release(key); m.release(SHIFT)
                            else:
                                m.release(SHIFT); m.release(key)
                            m.poll()
                            target = LAST_KIT if key == PATTERN_EDIT else 0
                            live = p36 == 1 and state in (1, 2)
                            stock = [0x17] if state == 1 else [0x18] if state == 2 else []
                            if self.baseline and live:
                                check(at_press == stock and (state != 2 or TOP in m.requests()),
                                      ('v9.43 SG chord should start/stop the take', p36, state, start, key, order, m.log))
                            else:
                                check(not m.posts() and TOP not in m.requests() and m.mode == target and
                                      m.current == SG,
                                      ('SG chord must not touch the recorder', p36, state, start, key, order, m.log, m.mode))
                            self.cases += 1
                        out.append(dict(p36=p36, state=state, start_mode=start, key=key,      # the shift_first run
                                        posts_at_press=[hex(x) for x in at_press], mode_after=m.mode))
        return out

    def sg_stock_keys(self):
        """Unshifted start/stop and the other stock start/stop keys are unchanged."""
        out = []
        for key in (PATTERN_SELECT, PATTERN_EDIT, RECORD_SETTING, PITCH_SPEED, RESAMPLE_KEY):
            for shifted in (False, True):
                if shifted and key in (PATTERN_EDIT, RECORD_SETTING):
                    continue
                for state in (1, 2):
                    m = self.machine(SG, LAST_KIT)
                    m.recorder(state, 5, 1)
                    if shifted:
                        m.press(SHIFT)
                    m.press(key)
                    posts = m.posts()
                    m.release(key)
                    if shifted:
                        m.release(SHIFT)
                    expected = [0x17] if state == 1 else [0x18]
                    check(posts == expected and m.mode == LAST_KIT,
                          ('stock start/stop key changed', key, shifted, state, m.log))
                    if state == 2:
                        check(TOP in m.requests() and m.settings[P_MODE] == 0, ('stock stop path', key, m.log))
                    out.append(dict(key=key, shifted=shifted, state=state, posts=[hex(x) for x in posts]))
                    self.cases += 1
        return out

    # 3. The stock chord from the RESAMPLE page
    def stock_entry(self):
        out = []
        for start in (0, 3, LAST_KIT):
            for order in ('key_first', 'shift_first', 'release_before_switch', 'shift_released_before_switch'):
                m = self.machine(RESAMPLE, start)
                m.recorder(1, 5, 1)
                m.press(SHIFT)
                m.press(RECORD_SETTING)
                check(m.requests() == [SG] and not m.posts(), ('stock jump', start, order, m.log))
                if order == 'release_before_switch':
                    m.release(RECORD_SETTING); m.release(SHIFT)
                    m.settle(); m.poll()
                elif order == 'shift_released_before_switch':
                    m.release(SHIFT)
                    m.settle(); m.poll()
                    m.release(RECORD_SETTING); m.poll()
                else:
                    m.settle()
                    arrival = m.poll()
                    arrived_mode = m.mode
                    m.poll()
                    if order == 'key_first':
                        m.release(RECORD_SETTING); m.poll(); m.release(SHIFT)
                    else:
                        m.release(SHIFT); m.poll(); m.release(RECORD_SETTING)
                    m.poll()
                check(m.current == SG and m.state == 1 and not m.posts(), ('stock entry recorder', start, order, m.log))
                if self.baseline and order in ('key_first', 'shift_first'):
                    check(arrived_mode == 0 and m.mode == 0, ('v9.43 stock chord should force melodic', start, order))
                else:
                    check(m.mode == start and m.count('release_all') == 0,
                          ('stock chord must keep the machine', start, order, m.mode, m.log))
                out.append(dict(start_mode=start, order=order, mode_after=m.mode))
                self.cases += 1
        return out

    # 4. A whole hot resample in kit mode
    def session(self):
        m = self.machine(RESAMPLE, 0)            # melodic last used; LAST_KIT remembered
        steps = []
        m.recorder(1, 5, 1)                      # pad 6 picked: armed, "press pad to start"
        m.press(SHIFT); m.press(PATTERN_EDIT); m.release(PATTERN_EDIT); m.release(SHIFT)
        m.settle(); m.poll()
        check(m.current == SG and m.mode == LAST_KIT and m.state == 1 and not m.posts(), ('enter kits', m.log))
        steps.append('RESAMPLE armed; SHIFT+PATTERN EDIT: SG page, kit %d, take armed' % m.mode)
        m.press(SHIFT); m.press(RECORD_SETTING); m.poll(); m.release(RECORD_SETTING); m.release(SHIFT); m.poll()
        check(m.mode == 0 and m.state == 1 and not m.posts(), ('to melodic while armed', m.log))
        m.press(SHIFT); m.press(PATTERN_EDIT); m.poll(); m.release(PATTERN_EDIT); m.release(SHIFT); m.poll()
        check(m.mode == LAST_KIT and m.state == 1 and not m.posts(), ('back to kits while armed', m.log))
        steps.append('SHIFT+RECORD SETTING / SHIFT+PATTERN EDIT while armed: melodic, kits, nothing posted')
        m.hit(0)
        check(m.posts() == [0x17] and m.count('note') == 1, ('first kit hit starts the take', m.log))
        m.settle()
        check(m.state == 2, 'recording after the first hit')
        steps.append('first kit hit: stock pad handler posts 0x17 (start) and plays the note')
        m.mark()
        m.hit(1)
        check(not m.posts() and m.count('note') == 1, ('later hits only play', m.log))
        m.press(SHIFT); m.press(RECORD_SETTING); m.poll(); m.release(RECORD_SETTING); m.release(SHIFT); m.poll()
        m.press(SHIFT); m.press(PATTERN_EDIT); m.poll(); m.release(SHIFT); m.release(PATTERN_EDIT); m.poll()
        check(m.mode == LAST_KIT and m.state == 2 and not m.posts() and TOP not in m.requests(),
              ('switching while recording', m.log))
        steps.append('while recording: melodic and back to kits, nothing posted, still recording')
        m.press(RESAMPLE_KEY)
        check(m.posts() == [0x18] and TOP in m.requests(), ('RESAMPLE stops', m.log))
        m.release(RESAMPLE_KEY)
        m.settle()
        check(m.state == 0 and m.current == TOP, 'stopped, back to TOP')
        steps.append('RESAMPLE: stock stop (0x18), TOP page')
        self.cases += 1
        return steps


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('build', type=Path)
    parser.add_argument('--baseline', action='store_true', help='expect the v9.43 faults instead of the fix')
    args = parser.parse_args()
    suite = Suite(args.build.resolve(), args.baseline)
    report = dict(resample_page=suite.resample_twin(), sg_page_chords=suite.sg_chords(),
                  stock_entry_chord=suite.stock_entry())
    if not args.baseline:
        report.update(sg_stock_keys=suite.sg_stock_keys(), session=suite.session())
    report.update(cases=suite.cases, passed=True, baseline=args.baseline, app1_sha256=suite.man['sha256'],
                  revision=suite.man.get('revision'))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
