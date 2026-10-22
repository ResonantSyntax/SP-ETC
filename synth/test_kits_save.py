"""Checks for kits save (build_kits_save.py): the kit edits saved with the project in SG_KITS.BIN.

usage: python synth/test_kits_save.py OUT_DIR [--quick]      (unicorn, keystone and capstone on PYTHONPATH)

Reads OUT_DIR/manifest.json for the parent APP1 (v9.46). Static image checks first. Then the built image (and the
parent, for the comparisons) is booted in Unicorn the way its scatter loader does it, with its 70 static
constructors run (the RTOS under them stubbed: object creation by an id, the pool by a bump allocator). Real code:
the stock PADCONF save (0x800cf218) and load (0x8018ae68) with everything under them but the file calls, the stock
path builder, the post (0x800e25c0) and SMPL TASK's command dispatcher (0x8004d8b8) for the commands the post
queues, the settings setter (ENV), the kits module's knob, VALUE-menu and arp code, the module. Modelled: the card
under the stock file calls (open, read, write, close, fstat, opendir; by path, with failures on demand), the queue
put (0x800da528: the command is kept and run through the dispatcher when the test lets SMPL TASK run), the kits'
screen update kit_ui_poll and the SG page's stock deleting destructor (both only logged: the module's wrappers must
call them as they were called), dispatch off/on and the task delay (logged), the tempo calls. A screen update is one
call of the SG vtable's +0xd0 entry, a page close one call of its +0x04 entry. No screen, no SD card, no real tasks
or timing: those need the unit.

Checks:
- static: only the header, the two entries, the two vtable words and the appended tail differ from the parent;
  the rows (one copy row added); the guards hold on the parent; the slot is free; the trampolines;
- boot: without a file the power-on defaults (the factory pads as the parent's kit_init_pads makes them, TR808,
  M.CH 16, ARP OFF, 1/16, A.OCT 0, HOLD OFF, ENV 4, SCALE 0) and nothing written; the boot's PADCONF load leaves
  CSmplPrm exactly as on the parent;
- round trip: edits through the kits' knob, VALUE-menu and arp code, the settings setter and the keyboard state,
  saved by the module's own command 0xd through the real post and dispatcher: the file is exactly the expected
  bytes (header, CRC-32, payload); a fresh boot with that card restores every value; kit mode stays melodic at boot
  as in v9.46; leaving the page saves at once; PADCONF.BIN is never opened by the module's own saves while
  CSmplPrm is not edited, and is written exactly as on the parent when it is;
- bad files: missing, empty, short, long, other magic, version, header or payload size, CRC, each field out of
  range (with a good CRC): the power-on defaults, and the bad file is left alone until the kits change;
- projects: each project its own file; switching flushes unsaved edits to the project they belong to; a project
  without a file starts from the defaults; a reload of the same project keeps RAM and writes nothing unless the
  card changed (file deleted or replaced: RAM follows it); SD-card projects (settings 0x84) use their own folder;
- moments: no post while the kits keep changing (debounce of 40 screen updates, one write per burst); none while
  the recorder is armed or recording (states 1, 2, 3) or a BOUNC runs, neither from the screen updates, the page
  close, nor the stock PADCONF save; the stock save of another project never writes our file; a failed open or a
  short write keeps the edits for the next save; a held lock skips a save and makes a load wait;
- the stock paths: a stock command 0xd, the stock save and load, the page close and the screen update behave as
  on the parent (the same files, CSmplPrm and calls).
"""
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_HOOK_CODE, UcError
from unicorn import arm_const as ar

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_kits_save import GUARDS, Runtime, SITES, VTABLE, KNOWN_SLOTS, listing, sha  # noqa: E402

FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
RET, STACK, HEAP = 0x3001F000, 0x30010000, 0x32000000
MSG, PAGE_OBJ, BUF = 0x30014000, 0x30090000, 0x30016000
CTORS, NCTORS = 0x8383A30C, 70
KERNEL = {0x310C: 1, 0x22A4: 1, 0x32B8: 0}                 # RTOS object creation in the constructors: an id
SCREEN = (0x8006C088, 0x8006BD48, 0x8015F3A8, 0x800D8020)  # drawing: the display is not built here
SMPL, CUR, REC_STATE, SETTINGS, KB = 0x82E2CD08, 0x805923FC, 0x82E0E755, 0x82E01144, 0x80591C48
SAVE, LOAD, DISPATCHER, POST, QPUT = 0x800CF218, 0x8018AE68, 0x8004D8B8, 0x800E25C0, 0x800DA528
SG_VT, SG_DELETE, SETTINGS_SET, SETTINGS_GET = 0x802295A8, 0x8015CEF8, 0x800DD0C0, 0x800D94D8
FILE = dict(open=0x800DEC60, read=0x800DEC48, write=0x800DD9B8, close=0x800DEBD8, fstat=0x800D1130, opendir=0x800D4D8C)
# the kits module of v9.46 (guarded by the builder)
KIT = dict(kit_pads=0x83FBFCC0, kit_pads_ready=0x83FC0340, kit_mode=0x83FC58E0, kit_last_mode=0x83FC58D1,
           kit_midi_channel=0x83FBFCBC, kit_edit_pad=0x83FC59A1, kit_ui_shift=0x83FC59A6, kit_bounce_state=0x83FC7E3A,
           arp_mode=0x83FC7B70, arp_rate=0x83FBFCB0, arp_oct=0x83FC7B74, arp_hold=0x83FC7B78,
           held_count=0x83FC7B84, down_count=0x83FC7B88)
KIT_INIT_PADS, KIT_UI_POLL, KIT_UI_KNOB, KIT_ITEM_STEP, ARP_ITEM_STEP = (0x83FA7F85, 0x83FA7484, 0x83FA73DD,
                                                                         0x83FA6F55, 0x83FA3E79)
ENV, SCALE = 0x80249810, KB + 0xC
MAGIC, PAYLOAD, FILE_SIZE, PADS = 0x544B4753, 1672, 1688, 13 * 16 * 8    # the file starts "SGKT"
QUIET = 40
DEFAULT_TAIL = bytes([1, 15, 0, 4, 0, 0, 4, 0])
P = lambda n: f'B:/ROLAND/SP-404MKII/PROJECT_{n + 1:02d}/SG_KITS.BIN'          # noqa: E731
PADCONF = lambda n: f'B:/ROLAND/SP-404MKII/PROJECT_{n + 1:02d}/PADCONF.BIN'    # noqa: E731
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


def s32(v):
    return struct.unpack('<i', struct.pack('<I', v & 0xFFFFFFFF))[0]


class Machine:
    """The image after its boot copy and static constructors, with the card and SMPL TASK's queue modelled."""

    def __init__(self, img, man=None, files=None, project=0):
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for base, size in ((0x0, 0x20000), (0x20000000, 0x80000), (0x20200000, 0x100000), (0x80000000, 0x4000000),
                           (0x30000000, 0x100000), (0x60000000, 0x400000), (0xE0000000, 0x100000),
                           (0x40000000, 0xE8000), (0x400E8000, 0x2000), (0x400EA000, 0x316000), (HEAP, 0x1000000)):
            uc.mem_map(base, size, UC_PROT_ALL)
        uc.mem_write(FLASH, img)
        a, b = struct.unpack_from('<2I', img, 0x80)
        for load, dst, size, fn in (struct.unpack_from('<4I', img, i) for i in range(a + 0x80, b + 0x80, 16)):
            if fn == COPY:
                uc.mem_write(dst, img[load - FLASH:load - FLASH + size])
            elif fn == DECOMPRESS:
                uc.mem_write(dst, decompress(img[load - FLASH:], size))
            elif fn == ZERO:
                uc.mem_write(dst, bytes(size))
            else:
                raise ValueError(f'unknown scatter handler {fn:#x}')
        uc.reg_write(ar.UC_ARM_REG_C1_C0_2, uc.reg_read(ar.UC_ARM_REG_C1_C0_2) | (0xF << 20))
        uc.reg_write(ar.UC_ARM_REG_FPEXC, 0x40000000)
        uc.mem_write(RET, b'\x00\xbf\x00\xbf')
        self.mprofile()
        self.sym = man['entries'] if man else {}
        self.heap = HEAP
        self.files = {k: bytearray(v) for k, v in (files or {}).items()}
        self.fds, self.fs, self.queue, self.calls = {}, [], [], []
        self.fail_open, self.short_write = set(), set()
        self.hook(0x800E2C68, self._malloc)
        for addr, v in {**KERNEL, 0x800E2CA8: 0}.items():
            self.value(addr, v)
        for addr in SCREEN:
            self.value(addr, 0)
        for fn in struct.unpack(f'<{NCTORS}I', bytes(uc.mem_read(CTORS, 4 * NCTORS))):
            self.call(fn & ~1 | 1, count=50_000_000)
        self.card()
        self.hook(QPUT, self._qput)
        self.hook(KIT_UI_POLL, lambda: self._log('kit_ui_poll', 2))
        self.hook(SG_DELETE, lambda: self._log('sg_delete', 1, ret=self.regs(1)[0]))
        for addr, name in ((0x800DED08, 'dispatch_off'), (0x800DECF8, 'dispatch_on'), (0x800D31EE, 'delay')):
            self.hook(addr, lambda name=name: self._log(name, 1))
        for addr in (0x800D31C6, 0x0000E668):             # debug prints
            self.value(addr, 0)
        self.value(0x800CE420, 0)                         # the page modal test: none
        self.value(0x800D314E, 0x1234567)                 # random()
        self.value(0x80047DD0, 12000)                     # pad tempo: 120 BPM (the arp's refresh)
        self.value(0x800D5640, 12000)                     # current tempo
        self.w32(CUR, project)

    # ---- plumbing ----
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

    def hook(self, addr, fn):
        self.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, _: fn(), begin=addr, end=addr)

    def value(self, addr, v):
        self.hook(addr, lambda: self.ret(v))

    def regs(self, n=4):
        return [self.uc.reg_read(getattr(ar, f'UC_ARM_REG_R{k}')) for k in range(n)]

    def ret(self, v=0):
        self.uc.reg_write(ar.UC_ARM_REG_R0, v & 0xFFFFFFFF)
        self.uc.reg_write(ar.UC_ARM_REG_PC, self.uc.reg_read(ar.UC_ARM_REG_LR))

    def _log(self, name, n, ret=0):
        self.calls.append((name,) + tuple(self.regs(n)))
        self.ret(ret)

    def _malloc(self):
        n = (self.regs(1)[0] + 15) & ~7
        at = self.heap
        self.heap += n + 8
        self.uc.mem_write(at, bytes(n + 8))
        self.ret(at + 8)

    def call(self, fn, *args, count=30_000_000):
        uc = self.uc
        for k, v in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), v & 0xFFFFFFFF)
        uc.reg_write(ar.UC_ARM_REG_SP, STACK)
        uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        try:
            uc.emu_start(fn | 1, RET, count=count)
        except UcError as e:
            raise RuntimeError(f'{e} at pc {uc.reg_read(ar.UC_ARM_REG_PC):#x} from {fn:#x}')
        if uc.reg_read(ar.UC_ARM_REG_PC) != RET or uc.reg_read(ar.UC_ARM_REG_SP) != STACK:
            raise RuntimeError(f'{fn:#x} did not return cleanly (pc {uc.reg_read(ar.UC_ARM_REG_PC):#x})')
        return uc.reg_read(ar.UC_ARM_REG_R0)

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))

    def r32(self, a):
        return struct.unpack('<I', self.uc.mem_read(a, 4))[0]

    def r8(self, a):
        return self.uc.mem_read(a, 1)[0]

    def w8(self, a, v):
        self.uc.mem_write(a, bytes([v & 0xFF]))

    def mem(self, a, n):
        return bytes(self.uc.mem_read(a, n))

    def cstr(self, a):
        return self.mem(a, 256).split(b'\0')[0].decode('latin-1')

    def s(self, name):
        """A function's code address."""
        return self.sym[name] & ~1

    def d(self, name):
        """A variable's address (a char array may sit at an odd one)."""
        return self.sym[name]

    def ks(self, name, size=4):
        v = self.mem(self.d(name), size)
        return int.from_bytes(v, 'little')

    # ---- the card ----
    def card(self):
        def op():
            path, flags = self.cstr(self.regs(2)[0]), self.regs(2)[1]
            self.fs.append(('open', path, flags))
            if flags == 0:
                if path not in self.files:
                    return self.ret(-1)
            elif flags == 0x601:
                if path in self.fail_open:
                    return self.ret(-1)
                self.files[path] = bytearray()
            else:
                raise RuntimeError(f'open {path} with flags {flags:#x}')
            fd = 3
            while fd in self.fds:
                fd += 1
            self.fds[fd] = [path, 0]
            self.ret(fd)

        def rd():
            fd, buf, n = self.regs(3)
            path, pos = self.fds[fd]
            data = bytes(self.files[path][pos:pos + n])
            self.uc.mem_write(buf, data)
            self.fds[fd][1] += len(data)
            self.ret(len(data))

        def wr():
            fd, buf, n = self.regs(3)
            path, pos = self.fds[fd]
            if path in self.short_write:
                n -= 1
            self.files[path][pos:pos + n] = self.mem(buf, n)
            self.fds[fd][1] += n
            self.fs.append(('write', path, n))
            self.ret(n)

        def cl():
            fd = self.regs(1)[0]
            self.fs.append(('close', self.fds.pop(fd)[0]))
            self.ret(0)

        def st():
            fd, buf = self.regs(2)
            self.uc.mem_write(buf, bytes(0x20))
            self.uc.mem_write(buf + 8, struct.pack('<Q', len(self.files[self.fds[fd][0]])))
            self.ret(0)
        for name, fn in (('open', op), ('read', rd), ('write', wr), ('close', cl), ('fstat', st)):
            self.hook(FILE[name], fn)
        self.value(FILE['opendir'], 0)          # no folder listing (the save's content check)

    def writes(self, path=None):
        return [x for x in self.fs if x[0] == 'open' and x[2] == 0x601 and (path is None or x[1] == path)]

    # ---- SMPL TASK ----
    def _qput(self):
        self.queue.append(self.mem(self.regs(1)[0], 12))
        self.ret(0)

    def smpl(self):
        """SMPL TASK takes what was queued, in order, through the real dispatcher."""
        done = []
        while self.queue:
            m = self.queue.pop(0)
            self.uc.mem_write(MSG, m + bytes(4))
            self.call(DISPATCHER, MSG)
            done.append(struct.unpack('<BBHii', m))
        return done

    def post(self, cmd, a1, a2=0):
        self.call(POST, cmd, a1, a2)

    # ---- the SP ----
    def load(self, project=None):
        """The stock PADCONF load of the current project (as a project load, the boot's included, calls it)."""
        if project is not None:
            self.w32(CUR, project)
        return self.call(LOAD, SMPL, 0)

    def save(self, project=-1, edited=None):
        if edited is not None:
            self.w8(SMPL + 0x1C, edited)
        return self.call(SAVE, SMPL, project)

    def poll(self, n=1):
        entry = self.r32(SG_VT + 0xD0)
        for _ in range(n):
            self.call(entry, PAGE_OBJ, 50)

    def leave(self):
        return self.call(self.r32(SG_VT + 4), PAGE_OBJ)

    def kits(self):
        """Everything the file holds, as the kits module and the stock hold it."""
        r = self.r8
        return (self.mem(KIT['kit_pads'], PADS), r(KIT['kit_mode']), r(KIT['kit_last_mode']), r(KIT['kit_midi_channel']),
                s32(self.r32(KIT['arp_mode'])), s32(self.r32(KIT['arp_rate'])), s32(self.r32(KIT['arp_oct'])),
                s32(self.r32(KIT['arp_hold'])), s32(self.r32(ENV)), s32(self.r32(SCALE)))

    def payload(self):
        k = self.kits()
        kit = k[1] or k[2]
        return k[0] + bytes([kit, k[3], k[4] & 0xFF, k[5] & 0xFF, k[6] & 0xFF, k[7] & 0xFF, k[8] & 0xFF, k[9] & 0xFF])

    # edits, through the kits' own code
    def kit_on(self, kit):
        """Drum mode with that kit, as SHIFT + PATTERN EDIT leaves it."""
        self.w8(KIT['kit_mode'], kit)
        self.w8(KIT['kit_last_mode'], kit)

    def knob(self, k, raw, shift=0):
        self.w8(KIT['kit_ui_shift'], shift)
        return self.call(KIT_UI_KNOB, PAGE_OBJ, k, raw)

    def step(self, item, d):
        self.call(ARP_ITEM_STEP, item, d & 0xFFFFFFFF)

    def pad(self, p):
        self.w8(KIT['kit_edit_pad'], p)

    def env(self, v):
        self.call(SETTINGS_SET, SETTINGS, 0x82, v, 0)


def file_bytes(payload, version=1, magic=MAGIC, header=16, size=PAYLOAD, crc=None):
    crc = zlib.crc32(payload) if crc is None else crc
    return struct.pack('<IBBBBII', magic, version & 0xFF, version >> 8, header & 0xFF, header >> 8, size, crc) + payload


def edit_a(m):
    """A spread of edits: KPR77, pads with every control moved, sounds stepped, two kits, M.CH, the arp, ENV, SCALE."""
    m.kit_on(3)
    for p, (t, d, o) in enumerate([(0, 127, 3), (127, 0, 90), (64, 64, 64), (10, 99, 120)]):
        m.pad(p)
        m.knob(1, t); m.knob(2, d); m.knob(3, o)
        m.knob(1, 120 - t, shift=1); m.knob(2, d // 2, shift=1); m.knob(3, 127 - o, shift=1)
    m.pad(5)
    m.step(13, 1); m.step(13, 1); m.step(17, -30)
    m.step(11, 2)                                   # KIT: KPR77 -> FM
    m.pad(9)
    m.knob(1, 3); m.step(13, -1); m.step(17, 17)
    m.step(21, -6)                                  # M.CH 16 -> 10
    m.step(6, 2); m.step(7, -3); m.step(8, -2); m.step(9, 1)   # ARP DOWN, RATE 1/4T, A.OCT -2, HOLD ON
    m.env(7)
    m.uc.mem_write(SCALE, struct.pack('<i', 21))


def edit_b(m):
    m.kit_on(12)
    m.pad(0)
    m.knob(2, 5); m.step(17, 9)
    m.step(21, -1)
    m.env(1)


def boot(img, man, files=None, project=0):
    """Power on: the constructors, then the boot's PADCONF load of the current project."""
    m = Machine(img, man, files, project)
    m.load()
    return m


def factory(parent):
    """The factory pads, as the parent's own kit_init_pads makes them."""
    m = Machine(parent)
    m.w8(KIT['kit_pads_ready'], 0)
    m.call(KIT_INIT_PADS)
    return m.mem(KIT['kit_pads'], PADS)


# ---------------------------------------------------------------- checks
def static_checks(img, parent, man):
    rt, prt = Runtime(img), Runtime(parent)
    a, b = struct.unpack_from('<2I', parent, 0x80)
    table_end = b + 0x80
    diff = [i for i in range(min(len(parent), table_end)) if img[i] != parent[i]]
    sites = set()
    for p in man['patches']:
        sites.update(range(p['address'], p['address'] + p['size']))
    from build_arp import file_offset
    allowed = {0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87}
    for p in man['patches']:
        off = file_offset(parent, p['address'], p['size'])
        allowed.update(range(off, off + p['size']))
    check(set(diff) <= allowed and len(img) > len(parent),
          f'only the header, the sites and the appended tail differ from the parent ({len(diff)} bytes)')
    rows, prows = rt.rows, prt.rows
    check(rows[:-1] == prows and list(rows[-1][1:]) == [man['blob_base'], man['blob_size'], COPY],
          'the rows are the parent\'s plus one copy row for the module')
    check(rt.read(man['blob_base'], man['blob_size']) == img[man['blob_file_offset']:man['blob_file_offset'] +
                                                             man['blob_size']], 'the copy row holds the module')
    for s, e, d, w in GUARDS:
        new, old = rt.read(s, e - s), prt.read(s, e - s)
        changed = [s + i for i in range(e - s) if new[i] != old[i]]
        check(sha(old) == d and set(changed) <= sites,
              f'guard {s:#x}..{e:#x} holds on the parent; the image differs there only at the sites ({w[:40]})')
    for addr, orig, what, entry, back in SITES:
        got = listing(rt.read(addr, len(orig)), addr)
        want = [f'movw ip, #{man["entries"][entry] & 0xFFFF:#x}', f'movt ip, #{man["entries"][entry] >> 16:#x}',
                'bx ip'] + ['nop'] * ((len(orig) - 10) // 2)
        check(got == want and prt.read(addr, len(orig)) == orig, f'{addr:#x}: jump to {entry} ({got})')
    for addr, old, entry, what in VTABLE:
        check(struct.unpack('<I', rt.read(addr, 4))[0] == man['entries'][entry] and
              struct.unpack('<I', prt.read(addr, 4))[0] == old, f'{addr:#x}: {entry} in the SG vtable')
    base, end = man['slot']
    check(all(not max(lo, base) < min(hi, end) for _, lo, hi in KNOWN_SLOTS) and man['blob_size'] <= end - base,
          f'the module ({man["blob_size"]} bytes) fits its slot, which no other fork module has')
    note('static image')


def boot_checks(img, parent, man, fac):
    m = boot(img, man)
    p = Machine(parent)
    p.load()
    check(m.kits()[0] == fac, 'boot without a file: the factory pads (the parent\'s kit_init_pads)')
    check(m.payload()[PADS:] == DEFAULT_TAIL and m.r8(KIT['kit_mode']) == 0,
          f'boot without a file: TR808, M.CH 16, ARP OFF, 1/16, A.OCT 0, HOLD OFF, ENV 4, SCALE 0, melodic '
          f'({m.payload()[PADS:].hex()})')
    pk = p.kits()
    check(pk[1:] == (0, 1, 15, 0, 4, 0, 0, 4, 0), f'the parent powers on with the same values ({pk[1:]})')
    check(not m.writes() and [x[1] for x in m.fs if x[0] == 'open'] == [P(0), PADCONF(0)],
          f'boot: our file is looked for, then PADCONF.BIN; nothing written ({m.fs})')
    check(m.mem(SMPL, 0x19904) == p.mem(SMPL, 0x19904), 'boot: CSmplPrm as on the parent after the PADCONF load')
    check(m.ks('ks_defaults') == 1 and m.ks('ks_loads') == 0 and m.cstr(m.d('ks_path')) == P(0),
          'boot: defaults counted, the project\'s path kept')
    m.poll(3 * QUIET)
    check(not m.queue and not m.writes(), 'nothing changed: no post, no write, however long the page stays open')
    m.leave()
    check(not m.queue and not m.writes(), 'nothing changed: closing the page posts nothing')
    note('boot')


def roundtrip_checks(img, parent, man):
    m = boot(img, man)
    edit_a(m)
    want = m.payload()
    check(want != boot(img, man).payload(), 'the edits change the kits')
    m.poll(1)
    m.poll(QUIET - 1)
    check(not m.queue, 'no post before 40 quiet screen updates')
    m.poll(1)
    q = [struct.unpack('<BBHii', x) for x in m.queue]
    check(q == [(0xA4, q[0][1] if q else 0, 0xD, MAGIC, 0)] if q else False,
          f'after 40 quiet updates one command 0xd, a1 = the module\'s, a2 = the current project ({q})')
    m.fs.clear()
    m.smpl()
    f = m.files.get(P(0))
    check(f is not None and bytes(f) == file_bytes(want) and bytes(f[:4]) == b'SGKT' and len(f) == FILE_SIZE,
          'SMPL TASK writes SG_KITS.BIN: "SGKT", version, sizes, CRC-32, then exactly the kits (1688 bytes)')
    check([x for x in m.fs if x[0] == 'open'] == [('open', P(0), 0x601)] and PADCONF(0) not in m.files,
          f'the module\'s own command 0xd leaves PADCONF.BIN alone while CSmplPrm is not edited ({m.fs})')
    check(m.ks('ks_writes') == 1 and m.ks('ks_skips') == 1 and m.ks('ks_pending', 1) == 0, 'counted; nothing pending')
    m.poll(3 * QUIET)
    m.leave()
    m.smpl()
    check(len(m.writes(P(0))) == 1, 'saved kits: no more posts or writes')
    # power off, on
    n = boot(img, man, m.files)
    k = n.kits()
    check(n.payload() == want and k[1] == 0 and k[2] == want[PADS],
          f'power on: every value back, kit mode melodic at boot as in v9.46, SHIFT + PATTERN EDIT\'s kit restored')
    check(not n.writes() and n.ks('ks_loads') == 1, 'power on: read once, nothing written')
    # leaving the page saves at once
    n.kit_on(n.r8(KIT['kit_last_mode']))
    n.pad(2)
    n.knob(3, 1)
    n.poll(2)
    n.leave()
    check(len(n.queue) == 1, 'an edit, then the page closes before 40 updates: one post at once')
    n.smpl()
    check(bytes(n.files[P(0)]) == file_bytes(n.payload()) and len(n.writes(P(0))) == 1, 'and the file has the edit')
    check([c for c in n.calls if c[0] == 'sg_delete'] == [('sg_delete', PAGE_OBJ)],
          'the page close goes on to the stock deleting destructor with the page')
    # with CSmplPrm edited the stock body runs as on the parent
    n.knob(3, 77)
    n.w8(SMPL + 0x1C, 1)
    p = boot(parent, None, m.files)
    p.w8(SMPL + 0x1C, 1)
    n.leave()
    n.smpl()
    p.post(0xD, MAGIC)
    p.smpl()
    check(PADCONF(0) in n.files and n.files.get(PADCONF(0)) == p.files.get(PADCONF(0)) and
          n.mem(SMPL, 0x19904) == p.mem(SMPL, 0x19904),
          'the module\'s command 0xd with CSmplPrm edited: the stock save runs, PADCONF.BIN as the parent writes it')
    check(bytes(n.files[P(0)]) == file_bytes(n.payload()), 'and our file too')
    note('round trip')


def bad_file_checks(img, man, fac):
    good = boot(img, man)
    edit_a(good)
    pay = good.payload()
    cases_ = {'missing': None, 'empty': b'', 'short': file_bytes(pay)[:-1], 'long': file_bytes(pay) + b'\0',
              'magic': file_bytes(pay, magic=MAGIC ^ 1), 'version 2': file_bytes(pay, version=2),
              'version 0x101': file_bytes(pay, version=0x101), 'header size': file_bytes(pay, header=20),
              'payload size': file_bytes(pay, size=PAYLOAD - 1), 'CRC': file_bytes(pay, crc=zlib.crc32(pay) ^ 0x80),
              'one payload bit': file_bytes(pay[:100] + bytes([pay[100] ^ 4]) + pay[101:], crc=zlib.crc32(pay))}
    # every field out of range, each with a CRC that matches
    fields = [(1, 13, 'tune 13'), (1, 0xF3, 'tune -13'), (2, 101, 'decay 101'), (3, 101, 'tone 101'),
              (3, 0xFF, 'tone -1'), (4, 128, 'level 128'), (5, 101, 'sweep 101'), (6, 101, 'noise 101'),
              (7, 101, 'attack 101'), (0, 143, 'sound 143'), (0, 254, 'sound 254')]
    for off, v, what in fields:
        b_ = bytearray(pay)
        b_[8 * 37 + off] = v
        cases_[what] = file_bytes(bytes(b_))
    for off, v, what in [(0, 0, 'kit 0'), (0, 14, 'kit 14'), (1, 16, 'M.CH 17'), (2, 7, 'ARP 7'), (3, 7, 'RATE 7'),
                         (4, 4, 'A.OCT 4'), (4, 0xFC, 'A.OCT -4'), (5, 2, 'HOLD 2'), (6, 10, 'ENV 10'),
                         (7, 34, 'SCALE 34')]:
        b_ = bytearray(pay)
        b_[PADS + off] = v
        cases_[what] = file_bytes(bytes(b_))
    defaults = boot(img, man).payload()
    for what, data in cases_.items():
        files = {} if data is None else {P(0): data}
        m = boot(img, man, files)
        ok = m.payload() == defaults and m.kits()[0] == fac and not m.writes() and \
            (data is None or bytes(m.files[P(0)]) == data)
        m.poll(2 * QUIET)
        m.leave()
        m.smpl()
        ok = ok and not m.writes()
        check(ok, f'file {what}: the power-on defaults; the file left alone, nothing written')
    # a good file with OFF sounds and every extreme loads
    b_ = bytearray(pay)
    for i, row in enumerate([(255, 12, 100, 100, 127, 100, 100, 100), (0, 0xF4, 0, 0, 0, 0, 0, 0)]):
        b_[8 * i:8 * i + 8] = bytes(row)
    b_[PADS:] = bytes([13, 15, 6, 6, 0xFD, 1, 9, 33])
    m = boot(img, man, {P(0): file_bytes(bytes(b_))})
    check(m.payload() == bytes(b_), 'a file at every extreme (OFF sound, TR727, M.CH 16, CHORD, 1/32, A.OCT -3, ENV 9, '
                                    'SCALE 33) loads as it is')
    b_[PADS:] = bytes([1, 0, 0, 0, 3, 0, 0, 0])
    m = boot(img, man, {P(0): file_bytes(bytes(b_))})
    check(m.payload() == bytes(b_), 'and at the other ends (TR808, M.CH 1, OFF, 1/4, A.OCT +3, ENV OFF, Chrom)')
    # the bad file goes once the kits change
    m = boot(img, man, {P(0): cases_['CRC']})
    m.kit_on(1)
    m.knob(2, 9)
    m.poll(QUIET + 1)
    m.smpl()
    check(bytes(m.files[P(0)]) == file_bytes(m.payload()), 'after an edit the bad file is replaced by a good one')
    note('bad files')


def project_checks(img, man):
    m = boot(img, man)
    a_ = edit_a(m) or m.payload()
    m.poll(QUIET + 1)
    m.smpl()
    defaults = boot(img, man).payload()
    m.fs.clear()
    m.load(1)
    check(m.payload() == defaults and not m.writes() and bytes(m.files[P(0)]) == file_bytes(a_),
          'project 2 without a file: the defaults; project 1\'s file untouched')
    edit_b(m)
    b_ = m.payload()
    m.poll(QUIET + 1)
    m.smpl()
    check(bytes(m.files[P(1)]) == file_bytes(b_), 'project 2 saves to its own file')
    m.load(0)
    check(m.payload() == a_, 'back to project 1: its kits')
    m.kit_on(3)
    m.knob(1, 99)
    c_ = m.payload()
    m.fs.clear()
    m.load(1)
    check(bytes(m.files[P(0)]) == file_bytes(c_) and m.payload() == b_ and
          [x[1] for x in m.writes()] == [P(0)],
          'switching with unsaved edits: they go to project 1\'s file first, then project 2 loads')
    m.load(2)
    check(m.payload() == defaults, 'project 3: the defaults')
    m.load(1)
    check(m.payload() == b_, 'project 2 again')
    # the same project again (a pad reload, or loading the project again): RAM stays, nothing written
    m.kit_on(12)
    m.knob(2, 1)
    d_ = m.payload()
    m.fs.clear()
    m.load(1)
    check(m.payload() == d_ and not m.writes() and [x for x in m.fs if x[0] == 'open'] == [('open', P(1), 0)] +
          [('open', PADCONF(1), 0)], 'a reload of the same project keeps the unsaved edits and writes nothing')
    m.poll(QUIET + 1)
    m.smpl()
    check(bytes(m.files[P(1)]) == file_bytes(d_), 'and saves them later')
    # the card changed under the same project: RAM follows it
    del m.files[P(1)]
    m.load(1)
    check(m.payload() == defaults, 'its file deleted (a project import or delete), then reloaded: the defaults')
    m.files[P(1)] = bytearray(file_bytes(a_))
    m.load(1)
    check(m.payload() == a_, 'a file put there, then reloaded: that file\'s kits')
    m.files[P(1)] = bytearray(file_bytes(a_)[:-3])
    m.load(1)
    check(m.payload() == defaults, 'the file made bad, then reloaded: the defaults')
    m.fs.clear()
    m.load(1)
    check(m.payload() == defaults and not m.writes(), 'a bad file and no edit: reloads change nothing')
    # SD-card projects: settings 0x84 = 1
    m.call(SETTINGS_SET, SETTINGS, 0x84, 1, 0)
    m.load(4)
    sd = 'A:/EXPORT/PROJECT/PROJECT_05/SG_KITS.BIN'
    m.kit_on(2)
    m.knob(1, 5)
    e_ = m.payload()
    m.poll(QUIET + 1)
    m.smpl()
    check(bytes(m.files.get(sd, b'')) == file_bytes(e_) and m.cstr(m.d('ks_path')) == sd,
          'an SD-card project (settings 0x84) keeps its file in A:/EXPORT/PROJECT/PROJECT_05')
    m.call(SETTINGS_SET, SETTINGS, 0x84, 0, 0)
    m.load(4)
    check(m.payload() == defaults and m.cstr(m.d('ks_path')) == P(4), 'internal PROJECT_05 is another project')
    note('projects')


def moment_checks(img, man):
    # debounce: a burst of knob steps
    m = boot(img, man)
    m.kit_on(1)
    m.pad(0)
    posts = []
    for i in range(30):
        m.knob(2, i * 4)
        m.poll(QUIET // 2)
        posts.append(len(m.queue))
    check(not any(posts) and not m.writes(), 'knob steps every 20 screen updates for 600: no post, no write')
    m.poll(QUIET)
    m.smpl()
    check(len(m.writes(P(0))) == 1 and bytes(m.files[P(0)]) == file_bytes(m.payload()),
          'then 40 quiet updates: one post, one write, the last value')
    # the recorder: armed, recording, armed for START
    for state in (1, 2, 3):
        m.knob(1, 20 * state)
        m.w8(REC_STATE, state)
        m.poll(3 * QUIET)
        m.leave()
        m.fs.clear()
        m.save(edited=1)
        m.post(0xD, MAGIC)
        m.smpl()
        ok = not [x for x in m.queue] and not m.writes(P(0)) and m.writes(PADCONF(0))
        m.w8(REC_STATE, 0)
        check(ok, f'recorder state {state}: no post from the screen updates or the page close, no write from the '
                  f'stock PADCONF save (which writes PADCONF.BIN) or a command 0xd')
        m.fs.clear()
        m.save(edited=1)
        check(bytes(m.files[P(0)]) == file_bytes(m.payload()) and len(m.writes(P(0))) == 1,
              f'state {state} back to idle: the next stock save writes the kits')
    # BOUNC running
    m.knob(3, 33)
    m.w8(KIT['kit_bounce_state'], 2)
    m.poll(3 * QUIET)
    m.leave()
    m.fs.clear()
    m.save(edited=1)
    check(not m.queue and not m.writes(P(0)), 'a BOUNC running: no post, no write')
    m.w8(KIT['kit_bounce_state'], 3)
    m.poll(QUIET + 1)
    m.smpl()
    check(bytes(m.files[P(0)]) == file_bytes(m.payload()), 'BOUNC done (DONE shown): the kits are saved')
    # another project's stock save
    m.knob(3, 44)
    m.fs.clear()
    m.save(project=5, edited=1)
    check(not m.writes(P(0)) and not m.writes(P(5)) and m.writes(PADCONF(5)),
          'the stock save of another project (PADCONF.BIN of PROJECT_06) never writes a kits file')
    m.save(project=0, edited=1)
    check(bytes(m.files[P(0)]) == file_bytes(m.payload()), 'its own project number: written')
    # clean: stock saves write PADCONF only
    m.fs.clear()
    m.save(edited=1)
    m.post(0xD, 1)
    m.smpl()
    check(not m.writes(P(0)), 'nothing changed: stock saves never write the kits file')
    # failures: open refused, short write
    for kind in ('open', 'short'):
        m.knob(1, 50 + len(kind))
        (m.fail_open if kind == 'open' else m.short_write).add(P(0))
        m.poll(QUIET + 1)
        m.smpl()
        errs = m.ks('ks_errors')
        m.fail_open.clear()
        m.short_write.clear()
        m.poll(QUIET + 1)
        m.smpl()
        check(errs >= 1 and bytes(m.files[P(0)]) == file_bytes(m.payload()),
              f'a failed write ({kind}) is counted and the edits are saved by the next try')
    # a held lock: a save skips, a load waits, then goes on
    m.knob(1, 70)
    m.w8(m.d('ks_busy'), 1)
    m.fs.clear()
    m.save(edited=1)
    check(not m.writes(P(0)), 'the lock held: the stock save goes on without our write')
    m.calls.clear()
    m.load(3)
    delays = [c for c in m.calls if c[0] == 'delay']
    check(len(delays) == 1000 and m.cstr(m.d('ks_path')) == P(3) and m.ks('ks_busy', 1) == 0,
          f'the lock held: a load waits 1000 x 1 ms, then goes on ({len(delays)})')
    note('moments')


def parent_checks(img, parent, man):
    """The stock paths, with the module present, against the parent."""
    def scenario(image, man_):
        m = boot(image, man_)
        m.w8(SMPL + 0x1C, 1)
        m.post(0xD, 1)
        m.smpl()
        a = (bytes(m.files[PADCONF(0)]), m.mem(SMPL, 0x19904))
        m.load()
        b = m.mem(SMPL, 0x19904)
        m.calls.clear()
        m.poll(5)
        polls = [c for c in m.calls if c[0] == 'kit_ui_poll']
        r = m.leave()
        return a, b, polls, [c for c in m.calls if c[0] == 'sg_delete'], r, \
            [x for x in m.fs if 'SG_KITS' not in x[1]]
    n, p = scenario(img, man), scenario(parent, None)
    check(n[0] == p[0], 'a stock command 0xd: PADCONF.BIN and CSmplPrm as on the parent')
    check(n[1] == p[1], 'the stock load: CSmplPrm as on the parent')
    check(n[2] == p[2] == [('kit_ui_poll', PAGE_OBJ, 50)] * 5, 'each screen update calls the kits\' update once, '
                                                               'with the page and 50')
    check(n[3] == p[3] == [('sg_delete', PAGE_OBJ)] and n[4] == p[4] == PAGE_OBJ,
          'the page close: the stock deleting destructor once, with the page, its result returned')
    check(n[5] == p[5], f'the stock file calls are the parent\'s ({len(n[5])} calls)')
    note('stock paths as on the parent')


def main():
    out = Path(sys.argv[1])
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    if hashlib.sha256(img).hexdigest() != man['sha256']:
        raise SystemExit('APP1 does not match the manifest')
    parent = Path(man['parent_app1']).read_bytes()
    if hashlib.sha256(parent).hexdigest() != man['parent_sha256']:
        raise SystemExit('the parent APP1 does not match the manifest')
    static_checks(img, parent, man)
    fac = factory(parent)
    boot_checks(img, parent, man, fac)
    roundtrip_checks(img, parent, man)
    bad_file_checks(img, man, fac)
    project_checks(img, man)
    moment_checks(img, man)
    parent_checks(img, parent, man)
    print(f'{cases[0] - len(fails)}/{cases[0]} checks pass' + (f'; FAILED: {len(fails)}' if fails else ''))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
