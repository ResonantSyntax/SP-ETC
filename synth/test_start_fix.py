"""Checks for the RESAMPLE start fix (build_start_fix.py).

usage: python -I test_start_fix.py OUT_DIR
Reads OUT_DIR/manifest.json for the parent APP1 path. Static image checks, then
Unicorn runs of both hooks against the parent's stock instructions.
"""
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB, KS_MODE_LITTLE_ENDIAN  # noqa: E402
from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, UC_PROT_ALL  # noqa: E402
from unicorn import arm_const as ar  # noqa: E402

FLASH, COPY = 0x60080000, 0x600800E4
SITE_A, SITE_B, TAIL_A = 0x8017F0AC, 0x800E9EFE, 0x8017F3B8
MODE_TEST, MODE2_PATH = 0x8017EFE4, 0x8017EFEC     # REC_STOP: cmp r7, #2 ... bne SITE_A; mode 2 falls through
MARGIN = 8                                        # frames startfix-3 keeps in front of the first sample above 8
GETPARAM = 0x800D94D8
REC, ENGINE, STACK, RET = 0x30000000, 0x30001000, 0x30108000, 0x30200000
TABLE = (412, 652, 1036, 1462, 2066, 2920, 4124, 5826, 8230, 11626)
KS = Ks(KS_ARCH_ARM, KS_MODE_THUMB | KS_MODE_LITTLE_ENDIAN)
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


def machine(img):
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for b, n in ((0x80000000, 0x250000), (0x83FE0000, 0x10000), (REC, 0x10000), (0x30100000, 0x10000), (RET, 0x1000)):
        uc.mem_map(b, n, UC_PROT_ALL)
    for load, dst, n, fn in scatter(img):
        if fn != COPY or not load:
            continue
        for lo_, hi_ in ((0x80000000, 0x80250000), (0x83FE0000, 0x83FF0000)):
            if lo_ <= dst < hi_:
                uc.mem_write(dst, img[load - FLASH:load - FLASH + min(n, hi_ - dst)])
    uc.mem_write(RET, b'\x00\xbf')
    return uc


def stub_getparam(uc, p36, bpm100, calls):
    src = (f'cmp r1, #0x36\nbne other\nmovw r0, #{p36}\nbx lr\nother:\n'
           f'movw r0, #{bpm100 & 0xFFFF}\nmovt r0, #{bpm100 >> 16}\nbx lr\n')
    uc.mem_write(GETPARAM, bytes(KS.asm(src, GETPARAM)[0]))

    def hook(u, address, size, data):
        calls.append((u.reg_read(ar.UC_ARM_REG_R0), u.reg_read(ar.UC_ARM_REG_R1), u.reg_read(ar.UC_ARM_REG_R2)))
    uc.hook_add(UC_HOOK_CODE, hook, begin=GETPARAM, end=GETPARAM)


def run_trim(img, p36, k, channels, marker, start=0x800, end=0x40000):
    """marker = engine first-sound threshold [+0x1f8] set at standby; p36 = mode at stop time."""
    uc = machine(img)
    calls = []
    stub_getparam(uc, p36, 12000, calls)
    uc.mem_write(REC + 0x254, struct.pack('<I', ENGINE))
    uc.mem_write(ENGINE + 0x208, struct.pack('<q', k))
    uc.mem_write(ENGINE + 0x24, struct.pack('<H', channels))
    uc.mem_write(ENGINE + 0x1F8, struct.pack('<h', marker))
    sp = STACK - 0x100
    uc.mem_write(sp + 8, struct.pack('<I', 0))        # end, high word
    uc.mem_write(sp + 0xC, struct.pack('<I', p36))    # mode, saved by REC_STOP at 0x8017efde
    raw = (k * 4 + 0x200) & ((1 << 64) - 1)           # engine +0x50: 0x200 + 4*k (k = -1 wraps)
    alt_lo, alt_hi = raw & 0xFFFFFFFF, raw >> 32
    gap = (raw - start) & ((1 << 64) - 1)
    for reg, val in ((ar.UC_ARM_REG_R4, REC), (ar.UC_ARM_REG_R10, start), (ar.UC_ARM_REG_R9, 0),
                     (ar.UC_ARM_REG_R6, alt_lo), (ar.UC_ARM_REG_R5, alt_hi),
                     (ar.UC_ARM_REG_R3, gap & 0xFFFFFFFF), (ar.UC_ARM_REG_R2, gap >> 32),
                     (ar.UC_ARM_REG_R7, end), (ar.UC_ARM_REG_R11, 0xFFFF), (ar.UC_ARM_REG_SP, sp)):
        uc.reg_write(reg, val)
    uc.emu_start(SITE_A | 1, TAIL_A, count=200)
    if uc.reg_read(ar.UC_ARM_REG_PC) != TAIL_A:
        raise RuntimeError('trim path did not reach 0x8017f3b8')
    start_out = uc.reg_read(ar.UC_ARM_REG_R10) | (uc.reg_read(ar.UC_ARM_REG_R9) << 32)
    return start_out, calls, uc.reg_read(ar.UC_ARM_REG_R0), uc.reg_read(ar.UC_ARM_REG_R7)


def first_sound(frames, thr):
    """The stock writers' rule (0x1bdcc..0x1c0d6, one per sample format): the engine's frame counter at the first
    frame whose left or right sample is above the threshold in magnitude, else -1 (none)."""
    return next((i for i, (l, r) in enumerate(frames) if abs(l) > thr or abs(r) > thr), -1)


def start_on(img, frames, channels=2, marker=8, p36=1):
    """The START the stop path leaves for a take whose frames from REC_START are `frames`: (frames from REC_START,
    the first-sound frame)."""
    k = first_sound(frames, marker)
    s, *_ = run_trim(img, p36, k, channels, marker)
    return (s - 0x800) // (channels * 2), k


def run_mode(img, mode):
    """REC_STOP from its mode test: the first instruction after the branch, for mode `mode`."""
    uc = machine(img)
    uc.reg_write(ar.UC_ARM_REG_R7, mode)
    uc.reg_write(ar.UC_ARM_REG_SP, STACK - 0x100)
    uc.emu_start(MODE_TEST | 1, 0, count=4)
    return uc.reg_read(ar.UC_ARM_REG_PC)


def run_thr(img, p36, setting):
    uc = machine(img)
    calls = []
    stub_getparam(uc, p36, 12000, calls)
    sp = STACK - 0x200
    saved = [0x11111111, 0x22222222, 0x33333333, 0x44444444, RET | 1]
    uc.mem_write(sp, b'\x00' * 4 + struct.pack('<5I', *saved))
    uc.mem_write(ENGINE + 0x1F8, b'\xAA\xAA')
    for reg, val in ((ar.UC_ARM_REG_R0, setting), (ar.UC_ARM_REG_R4, ENGINE), (ar.UC_ARM_REG_R5, 5),
                     (ar.UC_ARM_REG_R6, 0xFFFFFFFF), (ar.UC_ARM_REG_R7, 0), (ar.UC_ARM_REG_SP, sp)):
        uc.reg_write(reg, val)
    uc.emu_start(SITE_B | 1, RET, count=200)
    if uc.reg_read(ar.UC_ARM_REG_PC) != RET:
        raise RuntimeError('threshold path did not return')
    thr = struct.unpack('<h', uc.mem_read(ENGINE + 0x1F8, 2))[0]
    regs = [uc.reg_read(r) for r in (ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R5, ar.UC_ARM_REG_R6, ar.UC_ARM_REG_R7)]
    return thr, regs, uc.reg_read(ar.UC_ARM_REG_SP) - sp


def main():
    out = Path(sys.argv[1])
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    parent = Path(man['parent_app1']).read_bytes()
    check(sha(img) == man['sha256'], 'APP1 matches manifest SHA-256')
    check(sha(parent) == man['parent_sha256'], 'parent APP1 matches manifest')
    # Static: only the header, the two sites and the appended tail differ.
    site_offs = [file_offset(parent, SITE_A, 12), file_offset(parent, SITE_B, 12)]
    allowed = set(range(0x80, 0x88))
    for o in site_offs:
        allowed |= set(range(o, o + 12))
    diff = [i for i in range(len(parent)) if img[i] != parent[i] and i not in allowed]
    check(not diff, f'no other byte of the parent changed ({len(diff)} found)')
    rows_in, rows_out = scatter(parent), scatter(img)
    check(rows_out[:-1] == rows_in, 'new scatter table = parent rows + one row')
    load, dst, n, fn = rows_out[-1]
    check((dst, n, fn) == (man['blob_base'], man['blob_size'], COPY), 'added row copies the blob to its base')
    check(sha(img[load - FLASH:load - FLASH + n]) == man['blob_sha256'], 'blob bytes match manifest')
    check(all(not (max(d, dst) < min(d + m, dst + n)) for _, d, m, _f in rows_in), 'no parent row overlaps the blob')
    # Trim hook vs the parent's stock instructions. The mark is the engine threshold set at
    # standby: 8 for RESAMPLE takes (hook B), a table value or 0 otherwise. Mode 0x36 at stop
    # time does not matter (the SG page resets it right after posting the stop).
    ok_stock, ok_new = True, True
    for p36 in (0, 1, 3):
        for marker in (0, 412, 1036, 11626, 8):
            for channels in (1, 2):
                for k in (-1, 0, 1, 7, 8, 9, 10, 150, 240, 383, 384, 600, 1133, 1134, 2398, 2399, 2400, 5000):
                    s_new, calls_new, _, end_new = run_trim(img, p36, k, channels, marker)
                    s_old, calls_old, _, end_old = run_trim(parent, p36, k, channels, marker)
                    arg_ok = calls_new == calls_old == [(0x82E01144, 0x1B, 0xFFFFFFFF)]
                    if marker != 8:
                        if (s_new, end_new) != (s_old, end_old) or not arg_ok:
                            ok_stock = False
                            print('  stock mismatch', p36, marker, channels, k, hex(s_new), hex(s_old))
                    else:
                        want = 0x800 + ((k - MARGIN) * channels * 2 if MARGIN < k < 2400 else 0)
                        if s_new != want or not arg_ok or end_new != end_old:
                            ok_new = False
                            print('  resample mismatch', p36, channels, k, hex(s_new), hex(want), calls_new)
    check(ok_stock, 'trim: takes without the resample mark give exactly the stock START, END and REC BPM call')
    check(ok_new, 'trim: marked takes get START = REC_START + first-sound frame - 8 for first sounds 9..2399 frames in, '
                  'else REC_START, mono and stereo, whatever mode 0x36 reads at stop')
    check(run_trim(parent, 1, 600, 2, 412)[0] == 0x200 + 4 * 600,
          'stock reference: first sound 600 frames in -> stock START keeps 384 frames (8 ms) in front')
    s_old_example, *_ = run_trim(parent, 1, 240, 2, 412)
    s_new_example, *_ = run_trim(img, 1, 240, 2, 8)
    print(f'  example, stereo first sound 240 frames in: stock START {s_old_example:#x} (5 ms of silence kept), fixed {s_new_example:#x}')
    # Takes through a return with a quiet lead-in. The unit's effects-chip return reaches the take a few frames before
    # its first sample above 8 (a hi-hat bounced on bounce-3-test3: the first non-zero sample 7 frames before the main
    # delay). START must sit at or before the first non-zero frame, with only exact zeros in front of it.
    def take(lead, pre=300, n=400, first=3000):
        return [(0, 0)] * pre + [(v, v) for v in lead] + [(first, -first)] + [(1000, 1000)] * n
    for label, lead in (('a return whose first sample is 1 LSB and which crosses 8 five frames later', (1, 2, 3, 5, 7)),
                        ('the unit\'s quiet lead-in, 7 frames before the main attack', (1, 1, 2, 2, 3, 4, 6)),
                        ('a sharp attack (no lead-in)', ())):
        frames = take(lead)
        f = next(i for i, fr in enumerate(frames) if fr != (0, 0))
        st, k = start_on(img, frames)
        check(st <= f and all(fr == (0, 0) for fr in frames[st:f]) and f - st <= MARGIN,
              f'{label}: START {st} at or before the first non-zero frame {f}, only zeros between ({f - st}); '
              f'first sample above 8 at {k}')
    # a floor under 8 with no exact zeros (a first-non-zero rule would not trim at all): START still comes to 8
    # frames before the attack, and only floor frames are in front of it
    rnd = random.Random(5)
    floor = [(rnd.choice((-1, 1)) * rnd.randint(1, 7), rnd.choice((-1, 1)) * rnd.randint(1, 7)) for _ in range(600)]
    frames = floor + [(2500, -2500)] + [(900, 900)] * 300
    st, k = start_on(img, frames)
    check(k == 600 and st == 600 - MARGIN and all(max(abs(l), abs(r)) <= 8 for l, r in frames[st:k]),
          f'a noise floor under 8: START {st}, 8 frames of floor before the attack at {k}')
    # the first sound 2400 frames or more in: START stays at REC_START, as stock leaves it
    frames = [(0, 0)] * 2450 + [(1, 1), (3, 3), (5000, 5000)] + [(900, 900)] * 100
    st, k = start_on(img, frames)
    st_stock, k_stock = start_on(parent, frames, marker=412)
    check(k == 2452 and st == 0 and (k_stock, st_stock) == (2452, 0),
          f'a first sound 2452 frames in (over 2399): START stays at REC_START ({st}), as stock leaves it ({st_stock})')
    # mode 2 (the pattern-select resample page) branches to its own stock trim before the hooked site
    check([run_mode(x, m) for x in (img, parent) for m in (0, 1, 2, 3)] == [SITE_A, SITE_A, MODE2_PATH, SITE_A] * 2,
          'mode 2: REC_STOP branches to its own stock trim (0x8017efec) and never reaches the hooked site; '
          'modes 0, 1 and 3 reach it')
    # Threshold hook.
    ok_t = True
    for p36 in (0, 1, 2, 3):
        for setting in range(0, 12):
            t_new, regs_new, sp_delta = run_thr(img, p36, setting)
            t_old, regs_old, _ = run_thr(parent, p36, setting)
            stock_val = TABLE[setting - 1] if 1 <= setting <= 10 else 0
            want = 8 if p36 == 1 else stock_val
            if t_old != stock_val or t_new != want or regs_new != regs_old or sp_delta != 0x18:
                ok_t = False
                print('  threshold mismatch', p36, setting, t_new, t_old, want, regs_new, regs_old, sp_delta)
    check(ok_t, 'threshold: RESAMPLE uses 8 (about -72 dBFS), other modes keep the Auto Trig table; registers and stack restored')
    print('ALL PASS' if not fails else f'{len(fails)} FAILED')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
