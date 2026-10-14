"""Checks for the bounce probe (build_bounce_probe.py).

usage: python synth/test_bounce_probe.py OUT_DIR   (unicorn and keystone on PYTHONPATH)
Reads OUT_DIR/manifest.json for the parent APP1 path. Static image checks, then Unicorn runs:
the three bridges against the parent's own instructions (the real recorder feed and popup
code run; the mixer is a stub that the tests fill), then measurement scenarios that drive the
TX and RX bridges block by block with synthetic stems and RX data.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_HOOK_CODE  # noqa: E402
from unicorn import arm_const as ar  # noqa: E402

FLASH, COPY = 0x60080000, 0x600800E4
TX_SITE, TX_BACK, RX_SITE, LOOP = 0x1D090, 0x1D09A, 0x1D0C2, 0x1D05C
UI_SITE, UI_REST = 0x8006B950, 0x8006B95C
MIXER, FEED, GATE, POPUP = 0x1C2D0, 0x1CA80, 0x1BAA4, 0x800D3FF0
STEMS, CAPTURE, SLOTS = 0x202AD3A0, 0x202AD0A0, 0x202AE1A0
TX3, RX = 0x20006000, 0x20008000
REC, REC_STATE, MODE, P27, FEED_ON = 0x82E0E71C, 0x82E0E755, 0x82E011CC, 0x82E011A8, 0x805917C4
POPUP_STATE, POPUP_TEXT, POPUP_FLAG = 0x8024589C, 0x802468D8, 0x805922AC
TCD3_SADDR, TCD4_DADDR = 0x400E9060, 0x400E9090
VOICES, STREAMS, STACK, RET = 0x30000000, 0x30200000, 0x30F00000, 0x30FF0000
FIELDS = ('tx_blocks rx_blocks phase tx_quiet rx_quiet w_quiet voices voice_block tx_onset lead rx_onset rx_flags '
          'rx_at w_onset w_flags rx_seen runs valid lo hi r_status r_run r_w_flags r_l r_lo r_hi r_w r_lead r_d r_p '
          'seq shown').split()
SAVED = (ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R5, ar.UC_ARM_REG_R6, ar.UC_ARM_REG_R7, ar.UC_ARM_REG_R8,
         ar.UC_ARM_REG_R9, ar.UC_ARM_REG_R10, ar.UC_ARM_REG_R11, ar.UC_ARM_REG_SP)
fails = []


def check(cond, what):
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        fails.append(what)


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


class Machine:
    """An image's copy rows in Unicorn, with the mixer stubbed and the feed's callees stubbed."""

    def __init__(self, img, man=None):
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for base, size in ((0, 0x20000), (0x20000000, 0x10000), (0x20200000, 0x100000), (0x80000000, 0x260000),
                           (0x80590000, 0x10000), (0x82E00000, 0x10000), (0x83F80000, 0x70000),
                           (0x400E8000, 0x2000), (VOICES, 0x400000), (0x30E00000, 0x200000)):
            uc.mem_map(base, size, UC_PROT_ALL)
        for load, dst, n, fn in scatter(img):
            if fn != COPY or not load:
                continue
            for lo, hi in ((0, 0x20000), (0x80000000, 0x80260000), (0x83F80000, 0x83FF0000)):
                if lo <= dst < hi:
                    uc.mem_write(dst, img[load - FLASH:load - FLASH + min(n, hi - dst)])
        stubs = {MIXER: 'movs r0, #1; bx lr', 0x101BA: 'movs r0, #0; bx lr', 0x1BB64: 'movs r0, #0; bx lr',
                 GATE: 'bx lr', 0x10084: 'movs r0, #0; bx lr', 0x1BB6A: 'bx lr', 0x1D634: 'bx lr'}
        from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB, KS_MODE_LITTLE_ENDIAN
        ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB | KS_MODE_LITTLE_ENDIAN)
        for at, src in stubs.items():
            uc.mem_write(at, bytes(ks.asm(src, at)[0]))
        uc.mem_write(RET, b'\x00\xbf')
        self.calls = []
        for at in (MIXER, FEED, GATE, POPUP):
            uc.hook_add(UC_HOOK_CODE, self._record, begin=at, end=at)
        self.sym = man['entries'] if man else {}
        self.write32(FEED_ON, 1)                         # the feed calls the recorder gate
        self.write32(P27, 0)                             # settings 0x27 = 0: the feed takes RX pair 0
        self.uc.mem_write(POPUP_STATE, b'\x01')          # the popup layer is up

    def _record(self, uc, address, size, data):
        regs = [uc.reg_read(r) for r in (ar.UC_ARM_REG_R0, ar.UC_ARM_REG_R1, ar.UC_ARM_REG_R2, ar.UC_ARM_REG_SP)]
        self.calls.append((address, regs))

    def write32(self, at, v):
        self.uc.mem_write(at, struct.pack('<I', v & 0xFFFFFFFF))

    def read32(self, at):
        return struct.unpack('<I', self.uc.mem_read(at, 4))[0]

    def field(self, name):
        v = self.read32(self.sym['probe'] + 4 * FIELDS.index(name))
        return v - (1 << 32) if v & 0x80000000 else v

    def regs(self):
        return [self.uc.reg_read(r) for r in SAVED]

    def setregs(self, values):
        for r, v in zip(SAVED, values):
            self.uc.reg_write(r, v)

    def run(self, start, until, count=400000):
        self.uc.emu_start(start | 1, until, count=count)
        if self.uc.reg_read(ar.UC_ARM_REG_PC) != until:
            raise RuntimeError(f'did not reach {until:#x} from {start:#x}')


AUDIO_REGS = [0x30EF0010, 0x30EF0004, 0x80591D54, 0xFFFFFFFF, 0x20000000, 0x20008000, 0x833B7004, 0x0B0B0B0B,
              0x30EF0000]


def tx_block(m, stems, idx=0):
    """One TX block through the audio task's site: stems = {(frame, slot): value} for the stub mixer."""
    buf = bytearray(64 * 14 * 4)
    for (f, s), v in stems.items():
        struct.pack_into('<i', buf, (f * 14 + s) * 4, v)
    m.uc.mem_write(STEMS, bytes(buf))
    m.setregs(AUDIO_REGS)
    m.uc.reg_write(ar.UC_ARM_REG_R5, 0x30EF0004)
    m.run(TX_SITE, TX_BACK)


def rx_block(m, words, idx=0):
    """One RX block through the audio task's site: words = {(frame, word): value} in the RX DMA half."""
    raw = bytearray(0x800)
    for (f, w), v in words.items():
        struct.pack_into('<h', raw, f * 32 + w * 2, v)
    at = RX + idx * 0x800
    m.uc.mem_write(at, bytes(raw))
    m.setregs(AUDIO_REGS)
    m.uc.reg_write(ar.UC_ARM_REG_R0, at)
    m.run(RX_SITE, LOOP)


def ui_tick(m, elapsed=1):
    sp = STACK - 0x400
    m.setregs([0x44444444, 0x55555555, 0x66666666, 0x77777777, 8, 9, 10, 11, sp])
    m.uc.reg_write(ar.UC_ARM_REG_R0, elapsed)
    m.uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
    m.run(UI_SITE, UI_REST)
    return m


def popup_text(m):
    return bytes(m.uc.mem_read(POPUP_TEXT, 64)).split(b'\0')[0].decode('ascii')


class Scenario:
    """Drive TX then RX block by block. TX frames and RX frames are numbered as the probe numbers
    them (blocks since boot); sounds are placed at absolute frame numbers."""

    def __init__(self, m):
        self.m = m
        self.tx_hits = {}       # TX frame -> (slot, value)
        self.rx_hits = {}       # RX frame -> {word: value}
        self.voice_starts = {}  # TX block -> slot index

    def click(self, tx_frame, slot=0, value=200000, length=40):
        for i in range(length):
            self.tx_hits[tx_frame + i] = (slot, value if i == 0 else value // (2 + i))

    def echo(self, rx_frame, words=(0, 1), value=12000, length=40):
        for i in range(length):
            self.rx_hits.setdefault(rx_frame + i, {}).update({w: value if i == 0 else value // (2 + i) for w in words})

    def noise(self, rx_frame, words=(0, 1), value=300, length=1):
        for i in range(length):
            self.rx_hits.setdefault(rx_frame + i, {}).update({w: value for w in words})

    def period(self, rx_first=False):
        m = self.m
        n, r = m.field('tx_blocks'), m.field('rx_blocks')
        if n in self.voice_starts:
            start_voice(m, self.voice_starts[n])
        stems = {(f, self.tx_hits[64 * n + f][0]): self.tx_hits[64 * n + f][1]
                 for f in range(64) if 64 * n + f in self.tx_hits}
        words = {(f, w): v for f in range(64) for w, v in self.rx_hits.get(64 * r + f, {}).items()}
        if rx_first:
            rx_block(m, words, r & 1)
            tx_block(m, stems, n & 1)
        else:
            tx_block(m, stems, n & 1)
            rx_block(m, words, r & 1)

    def run_to(self, block):
        while self.m.field('tx_blocks') < block:
            self.period()


def start_voice(m, slot):
    voice = VOICES + slot * 0x18000
    stream = STREAMS + slot * 0x100
    m.write32(SLOTS + slot * 0x58, voice)
    m.write32(voice + 0x14268, stream)
    m.uc.mem_write(stream + 1, b'\x00')


def stop_voice(m, slot):
    stream = STREAMS + slot * 0x100
    m.uc.mem_write(stream + 1, b'\xff')


def fresh(img, man, state=1, mode=1, dma=(40 * 64 + 8, 7 * 32)):
    m = Machine(img, man)
    m.uc.mem_write(REC_STATE, bytes([state]))
    m.write32(MODE, mode)
    m.write32(TCD3_SADDR, TX3 + dma[0])
    m.write32(TCD4_DADDR, RX + dma[1])
    for slot in range(32):                    # the stock slots always hold voice objects; all idle
        voice = VOICES + slot * 0x18000
        m.write32(SLOTS + slot * 0x58, voice)
        m.write32(voice + 0x14268, 0)
    return m


def shown(m):
    """Run the UI tick once and return the popup text it raised (None if none)."""
    before = len([c for c in m.calls if c[0] == POPUP])
    ui_tick(m)
    pops = [c for c in m.calls if c[0] == POPUP]
    if len(pops) == before:
        return None
    text_at, ms = pops[-1][1][0], pops[-1][1][1]
    return popup_text(m), ms, text_at


def main():
    out = Path(sys.argv[1])
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    parent = Path(man['parent_app1']).read_bytes()
    check(sha(img) == man['sha256'], 'APP1 matches manifest SHA-256')
    check(sha(parent) == man['parent_sha256'], 'parent APP1 matches manifest')
    check(sha((out / 'SP404MKII_APP0.bin').read_bytes()) == man['app0_sha256'], 'APP0 is stock 5.52')

    # Static: only the header, the three sites and the appended tail differ.
    allowed = set(range(0x80, 0x88))
    for p in man['patches']:
        o = file_offset(parent, p['address'], p['size'])
        allowed |= set(range(o, o + p['size']))
        check(parent[o:o + p['size']].hex() == p['original_hex'] and img[o:o + p['size']].hex() == p['replacement_hex'],
              f"site {p['address']:#x}: parent bytes and replacement as in the manifest")
    diff = [i for i in range(len(parent)) if img[i] != parent[i] and i not in allowed]
    check(not diff, f'no other byte of the parent changed ({len(diff)} found)')
    rows_in, rows_out = scatter(parent), scatter(img)
    check(rows_out[:-1] == rows_in, 'new scatter table = parent rows (start fix included) + one row')
    load, dst, n, fn = rows_out[-1]
    check((dst, n, fn) == (man['blob_base'], man['blob_size'], COPY), 'added row copies the blob to its base')
    check(sha(img[load - FLASH:load - FLASH + n]) == man['blob_sha256'], 'blob bytes match manifest')
    lo_s, hi_s = man['slot']
    check(dst == lo_s and dst + n <= hi_s == 0x83FEF000, 'blob inside its slot, below the start fix row (0x83FEF000)')
    check(all(not (max(d, lo_s) < min(d + k, hi_s)) for _, d, k, _f in rows_in), 'no parent row overlaps the slot')

    sym = man['entries']
    # --- Bridges against the parent's own instructions --------------------------------------
    old, new = fresh(parent, None), fresh(img, man)
    new_regs = []
    for m in (old, new):
        m.calls.clear()
        tx_block(m, {(3, 0): 5000})
        new_regs.append((m.regs(), [c for c in m.calls if c[0] == MIXER]))
    check([c[1][:2] for c in new_regs[0][1]] == [c[1][:2] for c in new_regs[1][1]] == [[0x30EF0004, 0x1000]],
          'TX bridge: the mixer is called once with the same arguments (r5, 0x1000) as stock')
    check(new_regs[0][1][0][1][3] == new_regs[1][1][0][1][3] == AUDIO_REGS[-1],
          'TX bridge: the mixer starts at the stock stack depth (the bridge uses no stack)')
    check(new_regs[0][0] == new_regs[1][0], 'TX bridge: r4-r11 and sp come back as stock leaves them')
    check(new.field('tx_blocks') == 1, 'TX bridge: probe_tx ran once (one TX block counted)')

    rx_cmp = []
    for m in (old, new):
        m.calls.clear()
        m.write32(0x8059179C, 0)
        rx_block(m, {(f, w): (f * 97 + w * 1000) - 3000 for f in range(64) for w in range(16)}, 1)
        rx_cmp.append((m.regs(), bytes(m.uc.mem_read(CAPTURE, 256)), bytes(m.uc.mem_read(0x8059179C, 4)),
                       [(c[0], c[1][:3]) for c in m.calls if c[0] == GATE],
                       [c[1] for c in m.calls if c[0] == FEED]))
    check(rx_cmp[0][1] == rx_cmp[1][1] and rx_cmp[0][2] == rx_cmp[1][2],
          'RX bridge: the stock feed fills the capture buffer and the meter exactly as stock')
    check(rx_cmp[0][3] == rx_cmp[1][3] == [(GATE, [REC, CAPTURE, 64])],
          'RX bridge: the recorder gate is called once, as stock (recorder, capture buffer, 64)')
    check([c[:2] + c[3:] for c in rx_cmp[0][4]] == [c[:2] + c[3:] for c in rx_cmp[1][4]] == [[RX + 0x800, 0x800,
                                                                                              AUDIO_REGS[-1]]],
          'RX bridge: the feed gets the same buffer and size at the stock stack depth (no stack used)')
    check(rx_cmp[0][0] == rx_cmp[1][0], 'RX bridge: r4-r11 and sp come back as stock leaves them at the loop head')
    check(new.field('rx_blocks') == 1, 'RX bridge: probe_rx ran once (one RX block counted)')

    ui_cmp = []
    for m in (old, new):
        m.calls.clear()
        m.write32(POPUP_FLAG + 8, 1234)
        ui_tick(m, 7)
        sp = m.uc.reg_read(ar.UC_ARM_REG_SP)
        ui_cmp.append(([m.uc.reg_read(r) for r in (ar.UC_ARM_REG_R0, ar.UC_ARM_REG_R1, ar.UC_ARM_REG_R4,
                                                  ar.UC_ARM_REG_R5, ar.UC_ARM_REG_R6, ar.UC_ARM_REG_SP)],
                       bytes(m.uc.mem_read(sp, 16)), [c for c in m.calls if c[0] == POPUP]))
    check(ui_cmp[0][:2] == ui_cmp[1][:2], 'UI bridge: r0, r1, r4-r6, sp and the pushed frame at 0x8006b95c as stock')
    check(ui_cmp[1][2] == [], 'UI bridge: no popup while there is no new result')

    # --- Measurement scenarios ------------------------------------------------------------
    m = fresh(img, man)                              # take armed (standby) from block 0
    sc = Scenario(m)
    sc.voice_starts[40] = 5
    sc.click(40 * 64 + 17, slot=2)                   # a BUS 1 stem
    sc.echo(40 * 64 + 17 + 290)
    sc.run_to(125)                                   # the return, then 4800 frames for words 2/3
    r = shown(m)
    check(r is not None and r[0] == 'L=290 #1 W--\n290-290 P33 D0 V17' and r[1] == 3000,
          f'one click: popup "L=290 #1 W--/290-290 P33 D0 V17" for 3 s (got {r and r[:2]})')
    check(r is not None and r[2] == sym['probe_text'] and popup_text(m) == r[0] and m.read32(POPUP_STATE + 4) == 3
          and m.read32(POPUP_STATE + 8) == 3000 and m.uc.mem_read(POPUP_FLAG, 1) == b'\x01',
          'the stock popup function copied the text and armed a type-3 popup of 3000 ms')
    check(shown(m) is None, 'a result is shown once')

    md = fresh(img, man)                             # a popup that closes in this very tick
    scd = Scenario(md)
    scd.click(40 * 64 + 17)
    scd.echo(40 * 64 + 17 + 290)
    scd.run_to(125)
    md.write32(POPUP_FLAG + 8, 1)
    first = shown(md)
    md.write32(POPUP_FLAG + 8, 0xFFFFFFFF)            # closed by that tick
    second = shown(md)
    check(first is None and second is not None and second[0].startswith('L=290 #1 '),
          'a result due while the shown popup closes in the same tick waits one tick (the close clears pending popups)')

    stop_voice(m, 5)
    sc.voice_starts[140] = 6
    sc.click(140 * 64 + 63)                          # last frame of a block
    sc.echo(140 * 64 + 63 + 291, words=(0, 1, 2, 3))
    sc.run_to(150)
    r = shown(m)
    check(r is not None and r[0] == 'L=291 #2 W291\n290-291 P33 D0 V63',
          f'second click in the same take: #2, range 290-291, words 2/3 carry it too (got {r and r[0]})')

    stop_voice(m, 6)
    sc.click(170 * 64)
    sc.echo(170 * 64 + 288)
    sc.echo(170 * 64 + 300, words=(2, 3))
    sc.run_to(180)
    r = shown(m)
    check(r is not None and r[0] == 'L=288 #3 W300\n288-291 P33 D0 V-',
          f'no pad voice started for it (a Sound Generator note): V-; W on its own latency (got {r and r[0]})')

    m.uc.mem_write(REC_STATE, b'\x00')               # the take ends
    sc.run_to(185)
    check(m.field('phase') == 0, 'recorder idle: the probe stops')
    sc.click(200 * 64 + 5)
    sc.echo(200 * 64 + 5 + 290)
    sc.run_to(300)
    check(shown(m) is None, 'no measurement while the recorder is idle')
    m.uc.mem_write(REC_STATE, b'\x02')               # a new take (recording)
    sc.click(330 * 64 + 9)
    sc.echo(330 * 64 + 9 + 300)
    sc.run_to(420)
    r = shown(m)
    check(r is not None and r[0] == 'L=300 #1 W--\n300-300 P33 D0 V-', f'a new take starts at #1 (got {r and r[0]})')

    m2 = fresh(img, man, mode=0)                     # REC sampling page, not RESAMPLE
    sc2 = Scenario(m2)
    sc2.click(40 * 64)
    sc2.echo(40 * 64 + 290)
    sc2.run_to(130)
    check(shown(m2) is None, 'no measurement outside the RESAMPLE page (param 0x36 != 1)')

    m3 = fresh(img, man)                             # sound already playing when the take starts
    sc3 = Scenario(m3)
    for b in range(1, 12):
        sc3.click(b * 64 + 10, value=50000, length=50)
        sc3.echo(b * 64 + 10 + 290, length=50)
    sc3.click(12 * 64 + 50, length=1)                # 975 quiet frames before the next one: too few
    sc3.click(28 * 64 + 2)
    sc3.click(60 * 64 + 2)
    sc3.echo(60 * 64 + 2 + 290)
    sc3.run_to(150)
    r = shown(m3)
    check(r is not None and r[0].startswith('L=290 #1 ') and m3.field('tx_onset') == 60 * 64 + 2,
          f'sounds that do not start from 1024 frames of TX silence are skipped (got {r and r[0]})')

    m4 = fresh(img, man)                             # the return is still sounding at the TX onset
    sc4 = Scenario(m4)
    sc4.click(40 * 64 + 1)
    sc4.noise(40 * 64 + 1 - 50, length=60)
    sc4.echo(40 * 64 + 1 + 290)
    sc4.run_to(130)
    r = shown(m4)
    check(r is not None and r[0] == 'L=?? #1\nRX not quiet', f'RX not quiet first: L=?? (got {r and r[0]})')

    m5 = fresh(img, man)                             # no return at all
    sc5 = Scenario(m5)
    sc5.click(40 * 64 + 1)
    sc5.run_to(40 + 48000 // 64 + 5)
    r = shown(m5)
    check(r is not None and r[0] == 'L=-- #1\nno return', f'no return within 1 s: L=-- (got {r and r[0]})')

    m6 = fresh(img, man, dma=(3 * 64, 70 * 32))      # one RX block counted before the first TX block
    sc6 = Scenario(m6)
    rx_block(m6, {})
    sc6.click(40 * 64 + 4)
    sc6.echo(40 * 64 + 4 + 290 + 64)                 # the same timing, one block later in RX numbering
    sc6.run_to(130)
    r = shown(m6)
    check(r is not None and r[0] == 'L=354 #1 W--\n354-354 P61 D1 V-',
          f'D shows the block offset of the counters and L moves by 64 with it; P from the eDMA positions '
          f'(got {r and r[0]})')

    m7 = fresh(img, man)                             # a voice that starts two blocks before it sounds
    sc7 = Scenario(m7)
    sc7.voice_starts[38] = 9
    sc7.click(40 * 64 + 11)
    sc7.echo(40 * 64 + 11 + 290)
    sc7.run_to(130)
    r = shown(m7)
    check(r is not None and r[0].endswith(' V139'), f'V = frames from the voice start to the onset (got {r and r[0]})')

    m10 = fresh(img, man)                            # counters far apart: numbers clamp, text fits
    m10.write32(sym['probe'] + 4 * FIELDS.index('rx_blocks'), 5000)
    sc10 = Scenario(m10)
    sc10.click(40 * 64 + 4)
    sc10.echo(5000 * 64 + 40 * 64 + 4 + 290, words=(0, 1, 2, 3))
    sc10.run_to(50)
    r = shown(m10)
    check(r is not None and r[0] == 'L=99999 #1 W99999\n99999-99999 P33 D5000 V-' and len(r[0]) < 64,
          f'values beyond 99999 show as 99999 and the text stays inside the 64-byte popup buffer (got {r and r[0]})')

    # Cost in the audio task: instructions in the blob per TX block + RX block.
    lo_c, hi_c = man['blob_base'], man['blob_base'] + man['blob_size']

    def cost(machine, sc_, periods, start):
        sc_.run_to(start)
        n = [0]

        def tick(uc, address, size, data):
            if lo_c <= address < hi_c:
                n[0] += 1
        h = machine.uc.hook_add(UC_HOOK_CODE, tick)
        sc_.run_to(start + periods)
        machine.uc.hook_del(h)
        return n[0] / periods
    m8 = fresh(img, man)
    sc8 = Scenario(m8)
    for b in range(30, 34):
        sc8.click(b * 64 + 1, length=64)
    busy = cost(m8, sc8, 4, 30)
    m9 = fresh(img, man, state=0)
    idle = cost(m9, Scenario(m9), 4, 2)
    print(f'  probe cost: {busy:.0f} instructions per TX+RX block pair while measuring, {idle:.0f} while idle '
          '(a block is 1.33 ms, about 800,000 cycles at 600 MHz)')
    check(busy < 8000, 'measuring costs under 8,000 instructions per block pair (about 1% of a block)')
    check(idle < 100, 'idle costs under 100 instructions per block pair')

    print('ALL PASS' if not fails else f'{len(fails)} FAILED')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
