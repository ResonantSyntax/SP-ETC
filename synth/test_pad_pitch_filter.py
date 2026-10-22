"""Checks for the pad envelopes, stage 2 (build_pad_pitch_filter.py): the pitch envelope and the filter.

usage: python synth/test_pad_pitch_filter.py OUT_DIR [N]      (unicorn, capstone, numpy on PYTHONPATH; N cases, default 12)

Reads OUT_DIR/manifest.json for the parent APP1 (a stage 1 build). Static checks first: only the header's scatter
pointer, the two resampler veneers, stage 1's env_stages[0] and env_more_pages[0..3] and the appended tail differ from
the parent; the guards hold on the parent; the veneers' only callers are the chunk worker's four BLs; the module's
tails go on to the stock resampler; the slot overlaps no row and no other fork module; the tables are the documented
formulas and stage 1's.

Then the parent and the new image are booted in Unicorn as test_pad_env.py does it. The CPU model is ARM_MAX: the
default ARM model (an ARMv7 Cortex-A) lacks the VSEL / VRINT / VMAXNM / VCVTA the resampler and Init use, and
Unicorn's Cortex-M7 model rejects the kernel's vmov.f64 at 0x12de2 (Codex's finding). A voice's resampler object is
set up with the stock engine init Init uses (0x800259e0, 0x80025858) and filled the way the chunk worker does it
(2048 source frames while the ring holds less than 4096); the real veneers, wrappers and kernel run, chunk after
chunk.

Checks:
- untouched pads (all zero, version 0 with everything set, an unknown version, version 1 with pitch and filter off;
  voices without a pad; objects that are not a voice's): every chunk's frames, the frame counts and the whole
  resampler and engine state are the parent's, in stretch modes 0, 1 and 2, mono and stereo, at several steps
  and speeds;
- pitch: the steps and sub-block lengths the kernel gets are the model's, chunk after chunk; the frames are what
  the parent's kernel gives for that step sequence; the step is put back after each chunk; a step set elsewhere
  between sub-blocks becomes the new base; a short return (the source ran out) stops the chunk;
- filter: every frame is a float32 model's of the TPT state-variable filter on the parent's frames (LP, BP, HP,
  cutoff envelopes up and down, resonance, mono and stereo), with its state carried across chunks;
- both at once; a new start (the recompute from Init, through stage 1's dispatcher) resets the envelopes and the
  filter; other recomputes don't;
- the ENVELOPE pages 5-8 (stage 1's screen harness, boot's surfaces made): the taps and VALUE turns reach them after
  stage 1's four;
  the screen and its static layer are a reference's byte for byte (drawn on the parent with stock's calls from the
  settings: labels, values, the envelope graphs, "A-6 PITCH 5/8"); each turn writes its byte and the layout version;
  every value the knobs reach is shown as the model says; COPY / REMAIN reach the mute group / bank; the save goes
  out 1 s after the last turn and on closing; a pad without a sample gets nothing;
- instruction counts per 2048-frame chunk: stock, pitch, filter, both, mono and stereo, and the module's share.
"""
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

import numpy as np
from unicorn import Uc, UC_HOOK_CODE
from unicorn import arm_const as ar

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_pad_env as T  # noqa: E402
from build_pad_env import Runtime, scatter, branches_into, movw_movt_bx, fine_frames, curve_tables, sha  # noqa: E402
from build_pad_pitch_filter import (GUARDS, VENEERS, CALLERS, KNOWN_SLOTS, SLOT, STAGE1_LINKS, pow2_table,  # noqa
                                    g_table, k_table, k30_table, comp15_table, hz_table, q10_table)
from build_start_fix import refs_into  # noqa: E402


def uc_max(arch, mode):
    u = Uc(arch, mode)
    u.ctl_set_cpu_model(ar.UC_CPU_ARM_MAX)
    return u


T.Uc = uc_max                       # test_pad_env.Machine makes its Uc through this name

FLASH, COPY = 0x60080000, 0x600800E4
VOICES, VOICE_SIZE = 0x805F8834, 0x28820
MONO, STEREO = 0x800D2E38, 0x800D2E2E
KERNEL = 0x12DC0
ENGINE_INIT, WINDOW_INIT = 0x800259E0, 0x80025858
RECOMPUTE, INIT_RET = 0x800A2D98, 0x80023B05
CALLERS_LR = (0x80023B05, 0x8001FF39, 0x80022DAF, 0x80024A8F, 0x8002310F)
CSMPLPRM = 0x82E2CD08
EXT = CSMPLPRM + 0xF800
RING = 0x2800
OUT_L, OUT_R, POSW = 0x30070000, 0x30074000, 0x30078000
STEP_MIN, STEP_MAX = 4096, 34716
ONE, M32 = 32768, 0xFFFFFFFF
FALL = [0, 2, 1, 3]
WINDOWS = {0: 600, 1: 400, 2: 800}
F = np.float32
fails = []
cases = [0]


def check(cond, what):
    cases[0] += 1
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        fails.append(what)
    return cond


def s8(v):
    return v - 256 if v > 127 else v


# ---------------------------------------------------------------- the machine
class Fill:
    """A booted image with voices' resampler objects set up as Init does it, filled as the chunk worker does."""

    def __init__(self, img, symbols=None):
        self.m = T.Machine(img, symbols)
        self.uc = self.m.uc
        self.calls = None
        self.uc.hook_add(UC_HOOK_CODE, self._kernel, None, begin=KERNEL, end=KERNEL)
        self.src = {}

    def _kernel(self, uc, a, s, _):
        if self.calls is not None:
            p = uc.reg_read(ar.UC_ARM_REG_R0)
            n = struct.unpack('<I', bytes(uc.mem_read(uc.reg_read(ar.UC_ARM_REG_SP), 4)))[0]
            self.calls.append((n, self.m.r32(p + 0x20)))

    def setup(self, i, pad, mode=0, step=0x4000, speed=1.0, stereo=False, seed=1):
        """voice i on pad, its resampler object as Init leaves it (engine init, window), empty rings"""
        m, v = self.m, VOICES + i * VOICE_SIZE
        p, e = v + 0x140, v + 0x14328
        m.uc.mem_write(v, bytes(0x200))
        m.uc.mem_write(p + 0x40, bytes(0x60))
        m.uc.mem_write(p + 0xA0A0, bytes(0x60))
        m.uc.mem_write(e, bytes(0x328))
        m.w32(v + 0x14274, pad)
        m.w32(p + 0x14100, e)
        m.uc.mem_write(p + 0x14104, struct.pack('<f', speed))
        m.w32(v + 0x1C, 2 if stereo else 1)
        m.call(ENGINE_INIT | 1, p, e, mode)
        m.call(WINDOW_INIT | 1, p, WINDOWS[mode])
        m.w32(p + 0x20, step)
        m.w32(p + 0x24, step)
        m.recompute(v + 0x60, 0, 400000, 0, 100, 0, 2 if stereo else 1, lr=INIT_RET)   # Init's own recompute call
        self.src[p] = (seed, 0)
        return p

    def source(self, seed, k, ch):
        r = (k * 2654435761 + seed * 40503 + ch * 9973) & M32
        x = int(9000 * np.sin(k * (0.021 + 0.003 * seed) + ch)) + int(5000 * np.sin(k * 0.0047 * (ch + 1))) + \
            (r % 1997) - 998
        return x * 8192

    def fill(self, p, stereo, target=4096, block=2048):
        m = self.m
        seed, pos = self.src[p]
        while True:
            w, r = m.r32(p + 0x54), m.r32(p + 0x78)
            if (w - r) % RING >= target:
                break
            first = min(block, RING - w)
            for ch, data in ((0, p + 0xA0), (1, p + 0xA100)) if stereo else ((0, p + 0xA0),):
                vals = [self.source(seed, pos + k, ch) for k in range(block)]
                m.uc.mem_write(data + 4 * w, struct.pack(f'<{first}i', *vals[:first]))
                if first < block:
                    m.uc.mem_write(data, struct.pack(f'<{block - first}i', *vals[first:]))
            m.w32(p + 0x54, (w + block) % RING)
            if stereo:
                m.w32(p + 0xA0B4, (w + block) % RING)
            pos += block
        self.src[p] = (seed, pos)

    def chunk(self, p, n, stereo, base=None, count=False):
        """one resampler call through the veneer, as the worker makes it (the step set first)"""
        m = self.m
        if base is not None:
            m.w32(p + 0x20, base)
        m.uc.mem_write(OUT_L, bytes(2 * n))
        m.uc.mem_write(OUT_R, bytes(2 * n))
        counter = [0, 0]                                  # all instructions, the module's (0x83f00000 and up)

        def tally(uc, a, s, c):
            c[0] += 1
            if a >= 0x83F00000:
                c[1] += 1
        h = self.uc.hook_add(UC_HOOK_CODE, tally, counter) if count else None
        if stereo:
            got = m.call(STEREO | 1, p, OUT_L, OUT_R, n, stack=(POSW,), count=80_000_000)
        else:
            got = m.call(MONO | 1, p, OUT_L, n, POSW, count=80_000_000)
        if h is not None:
            self.uc.hook_del(h)
        got = struct.unpack('<i', struct.pack('<I', got))[0]
        L = list(struct.unpack(f'<{n}h', bytes(m.uc.mem_read(OUT_L, 2 * n))))
        R = list(struct.unpack(f'<{n}h', bytes(m.uc.mem_read(OUT_R, 2 * n)))) if stereo else []
        return got, L, R, m.r32(POSW), counter

    def driven(self, p, calls, stereo, base):
        """the parent's kernel through its stock veneer, one call per (frames, step), the step put back"""
        L, R, total = [], [], 0
        for n, step in calls:
            got, l, r, pos, _ = self.chunk(p, n, stereo, base=step)
            L += l[:max(got, 0)]
            R += r[:max(got, 0)]
            total += max(got, 0)
            if got != n:
                break
        self.m.w32(p + 0x20, base)
        return total, L, R, self.m.r32(POSW)

    def state(self, p):
        m = self.m
        return (bytes(m.uc.mem_read(p, 0x40)), bytes(m.uc.mem_read(p + 0x40, 0x60)),
                bytes(m.uc.mem_read(p + 0xA0A0, 0x60)), bytes(m.uc.mem_read(p + 0x14100, 8)),
                bytes(m.uc.mem_read(p - 0x140 + 0x14328, 0x328)))

    def set_ext(self, pad, b):
        self.uc.mem_write(EXT + pad * 0x80 + 0x71, bytes(b))


def ext2(depth=0, patk=0, pdec=0, ftype=0, cut=0, res=0, amt=0, fatk=0, fdec=0, pcurve=0, fcurve=0, version=None,
         rest=b'\0\0\0\0'):
    b = bytes([depth & 0xFF, patk, pdec, ftype, cut, res, amt & 0xFF, fatk, fdec, pcurve | fcurve << 2]) + rest
    v = (1 if any(b) else 0) if version is None else version
    return b + bytes([v])


# ---------------------------------------------------------------- the model
class Model:
    def __init__(self):
        self.F = fine_frames()
        self.C = curve_tables()
        self.P = pow2_table()
        self.G = [F(x) for x in g_table()]
        self.K = [F(x) for x in k_table()]
        self.K30 = k30_table()
        self.C15 = comp15_table()

    def settings(self, b):
        if b[14] != 1:
            return None
        s = dict(depth=max(-24, min(24, s8(b[0]))), patk=self.F[b[1] & 127], pdec=self.F[b[2] & 127],
                 type=b[3] & 3, cut=b[4] & 127, res=b[5] & 127, amt=max(-63, min(63, s8(b[6]))),
                 fatk=self.F[b[7] & 127], fdec=self.F[b[8] & 127], pcurve=b[9] & 3, fcurve=b[9] >> 2 & 3)
        return s if s['depth'] or s['type'] else None

    def curve(self, t, ph):
        c = self.C[t]
        i, f = ph >> 24, (ph >> 8) & 0xFFFF
        return c[i] + (((c[i + 1] - c[i]) * f) >> 16)

    @staticmethod
    def phase(t, n):
        return ((t << 24) // n) << 8

    def level(self, t, atk, dec, c):
        if t < atk:
            return self.curve(c, self.phase(t, atk))
        if not dec:
            return ONE
        t -= atk
        if t >= dec:
            return 0
        return ONE - self.curve(FALL[c], self.phase(t, dec))

    def step(self, base, depth, lvl):
        u = (depth * lvl) >> 7
        if not u:
            return base
        octave, rem = divmod(u + 6144, 3072)
        i, f = rem >> 5, rem & 31
        r = self.P[i] + (((self.P[i + 1] - self.P[i]) * f) >> 5)
        p = base * r
        st = ((p << (octave - 2)) >> 16 if octave >= 2 else p >> (16 + 2 - octave)) & M32
        return min(max(st, min(base, STEP_MIN)), max(base, STEP_MAX))

    def calls(self, s, base, mode, t0, n):
        blk = 175 if mode == 2 else 64
        out, done = [], 0
        while done < n:
            left = n - done
            m = min(left, blk)
            st = self.step(base, s['depth'], self.level(t0 + done, s['patk'], s['pdec'], s['pcurve']))
            while m < left:
                m2 = min(blk, left - m)
                if self.step(base, s['depth'], self.level(t0 + done + m, s['patk'], s['pdec'], s['pcurve'])) != st:
                    break
                m += m2
            out.append((m, st))
            done += m
        return out

    # the filter, in the module's fixed point: the signal x 2^9, Q31 coefficients, SMMULR / SMMLAR
    @staticmethod
    def smmulr(a, b):
        return (a * b + 0x80000000) >> 32

    @staticmethod
    def q31(a):
        f = a * F(2147483648.0)
        return 0x7FFFFFFF if f >= F(2147483648.0) else int(f)

    @staticmethod
    def out16(y):
        r = (y + 256) >> 9
        if r > 24576 or r < -24576:
            a = abs(r)
            d = a - 24576
            a = min(32767 if d >= 16384 else 24576 + d - ((d * d) >> 15), 32767)
            r = -a if r < 0 else a
        return r

    def svf(self, st, x, c, kind):
        a1, a2, a3, k, gain = c
        ic1, ic2 = st
        mm = self.smmulr
        out = []
        for v in x:
            xi = (v * gain) >> 6
            v3 = xi - ic2
            hv1 = mm(a1, ic1) + mm(a2, v3)
            hs = mm(a2, ic1) + mm(a3, v3)
            v2 = ic2 + 2 * hs
            ic1 = 4 * hv1 - ic1
            ic2 = ic2 + 4 * hs
            y = v2 if kind == 1 else 8 * mm(k, hv1) if kind == 2 else xi - 8 * mm(k, hv1) - v2
            out.append(self.out16(y))
        bound = 1 << 29
        return out, (max(-bound, min(bound, ic1)), max(-bound, min(bound, ic2)))

    def filter(self, s, st, L, R, t0):
        k = self.K[s['res']]
        k30, gain = self.K30[s['res']], 32768 if s['type'] == 2 else self.C15[s['res']]
        L, R, sl, sr = list(L), list(R), st[0], st[1]
        for j in range(0, len(L), 32):
            c8 = s['cut'] << 8
            if s['amt']:
                c8 += (s['amt'] * self.level(t0 + j, s['fatk'], s['fdec'], s['fcurve'])) >> 6
            c8 = max(0, min(127 << 8, c8))
            m = min(32, len(L) - j)
            if not s['res'] and ((s['type'] == 1 and c8 == 127 << 8) or (s['type'] == 3 and not c8)):
                sl = (0, L[j + m - 1] << 9 if s['type'] == 1 else 0)    # the block passes; the state follows it
                sr = (0, R[j + m - 1] << 9 if s['type'] == 1 and R else 0)
                continue
            ci, cf = c8 >> 8, c8 & 255
            g = self.G[ci] + (self.G[ci + 1] - self.G[ci]) * (F(cf) * F(1 / 256))
            a1 = F(1) / (F(1) + g * (g + k))
            a2 = g * a1
            a3 = g * a2
            c = (self.q31(a1), self.q31(a2), self.q31(a3), k30, gain)
            L[j:j + 32], sl = self.svf(sl, L[j:j + 32], c, s['type'])
            if R:
                R[j:j + 32], sr = self.svf(sr, R[j:j + 32], c, s['type'])
        return L, R, (sl, sr)


ZERO_STATE = ((0, 0), (0, 0))


def voice_state(m, sym, i):
    b = bytes(m.uc.mem_read(sym['pf_voices'] + i * 24, 24))
    gen, clock = struct.unpack_from('<2I', b)
    return gen, clock, struct.unpack_from('<4i', b, 8)


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
    st = man['stage1']['entries']['env_stages']
    mp = man['stage1']['entries']['env_more_pages']
    allowed = set(range(0x80, 0x88)) | set(range(file_off(st), file_off(st) + 4)) | \
        set(range(file_off(mp), file_off(mp) + 16))
    for at, original, _, _, _ in VENEERS:
        allowed |= set(range(file_off(at), file_off(at) + len(original)))
    diff = [i for i in range(len(parent)) if img[i] != parent[i]]
    check(set(diff) <= allowed and img[:len(parent)] != parent,
          f'only the scatter pointer, the two resampler veneers, env_stages[0] and env_more_pages[0..3] change inside '
          f'the parent ({len(diff)} bytes)')
    e = man['entries']
    rt, nrt = Runtime(parent), Runtime(img)
    ok = [rt.read(at, len(orig)) == orig and nrt.read(at, len(orig)) == movw_movt_bx(12, e[entry])
          for at, orig, _, _, entry in VENEERS]
    ok.append(rt.read(st, 16) == bytes(16) and nrt.word(st) == e['pf_stage'] and nrt.read(st + 4, 12) == bytes(12))
    ok.append(rt.read(mp, 16) == bytes(16) and
              [nrt.word(mp + 4 * k) for k in range(4)] == [e['pf_pages'] + 28 * k for k in range(4)])
    check(all(ok), f'each veneer: the stock movw/movt/bx to the resampler on the parent, the module\'s entry here; '
                   f'env_stages[0] = pf_stage, the other three empty; env_more_pages[0..3] = the four pages ({ok})')
    check(all(sha(rt.read(s, en - s)) == d for s, en, d, w in GUARDS), f'{len(GUARDS)} guards hold on the parent')
    inside, callers = [], []
    for at, original, _, _, _ in VENEERS:
        inside += branches_into(rt, at + 1, at + len(original))
        inside += [h for h in refs_into(parent, at + 1, at + len(original)) if h[2] & ~1 != at]
        callers.append(sorted(a for k, a in branches_into(rt, at, at + 1) if k == 'branch') == sorted(CALLERS[at]) and
                       not [a for k, a in branches_into(rt, at, at + 1) if k == 'word'])
    check(not inside and all(callers), f'nothing branches or points into the veneers; their only callers are the '
                                       f'chunk worker\'s four BLs ({inside[:4]}, {callers})')
    tails = []
    for name, target in (('pf_mono_entry', 0x1409B), ('pf_stereo_entry', 0x140C5)):
        code = nrt.read(e[name] & ~1, 28)
        tails.append(code[18:28] == movw_movt_bx(12, target))
    check(all(tails), 'the entries go on to the stock resampler (0x1409b mono, 0x140c5 stereo) for other voices')
    check(nrt.read(base, size) == img[man['blob_file_offset']:man['blob_file_offset'] + size] and
          base + size <= man['slot'][1] and man['slot'] == [base, base + SLOT] and
          not any(max(lo, base) < min(hi, base + SLOT) for _, lo, hi in KNOWN_SLOTS) and
          not any(max(dst, base) < min(dst + n, base + SLOT) for load, dst, n, fn in prow),
          f'the module ({size} bytes) fits its slot {base:#x}..{base + SLOT:#x}, which overlaps no row of the parent '
          f'and no other fork module\'s slot ({len(KNOWN_SLOTS)} listed, note repeat and stage 1 among them)')
    check(not refs_into(parent, base, base + SLOT), 'nothing in the parent refers to the slot')
    pow2 = list(struct.unpack('<97I', nrt.read(e['pf_pow2'], 388)))
    g = list(struct.unpack('<129f', nrt.read(e['pf_g'], 516)))
    k = list(struct.unpack('<128f', nrt.read(e['pf_k'], 512)))
    k30 = list(struct.unpack('<128i', nrt.read(e['pf_k30'], 512)))
    comp = list(struct.unpack('<128H', nrt.read(e['pf_comp15'], 256)))
    import math
    check(pow2 == [round(2 ** (i / 96) * 65536) for i in range(97)] and pow2[0] == 65536 and pow2[96] == 131072,
          'pf_pow2: 2^(i / 96) in Q16, 65536 .. 131072')
    fc = [20 * 1000 ** (i / 127) for i in range(128)]
    check(all(abs(g[i] - math.tan(math.pi * fc[i] / 48000)) <= 1e-6 * max(1, g[i]) for i in range(128)) and
          g[128] == g[127] and all(g[i] < g[i + 1] for i in range(127)),
          f'pf_g: tan(pi fc / 48000), fc 20 Hz .. 20 kHz in 128 log steps ({g[0]:.6f} .. {g[127]:.4f})')
    q = [0.7071067811865476 * 2 ** (r * 4.5 / 127) for r in range(128)]
    check(all(abs(k[r] - 1 / q[r]) <= 1e-6 for r in range(128)) and
          k30 == [round(2 ** 30 / q[r]) for r in range(128)] and
          comp == [round((q[r] / 0.7071067811865476) ** -0.5 * 32768) for r in range(128)] and comp[0] == 32768 and
          abs(1 / k[127] - 16) < 1e-3,
          f'pf_k = 1 / Q (float and Q30), Q 0.707 .. {1 / k[127]:.2f}; pf_comp15 = 1 / sqrt(Q / 0.707) in Q15 '
          f'(32768 at RESO 0)')
    hz = list(struct.unpack('<128H', nrt.read(e['pf_hz'], 256)))
    q10 = list(nrt.read(e['pf_q10'], 128))
    check(hz == [round(f) for f in fc] and hz[0] == 20 and hz[127] == 20000 and q10 == [round(x * 10) for x in q] and
          q10[0] == 7 and q10[127] == 160, f'the screen\'s tables: cutoffs in Hz (20 .. 20000), Q x 10 (7 .. 160)')
    links = man['stage1_links']
    ok = links == {n: man['stage1']['entries'][n] for n in STAGE1_LINKS} and \
        list(struct.unpack('<128I', nrt.read(links['env_fine_frames'], 512))) == fine_frames() and \
        [list(struct.unpack('<258H', nrt.read(links['env_curve'] + 516 * c, 516))) for c in range(4)] == curve_tables()
    check(ok, 'the module links stage 1\'s env_fine_frames and env_curve (stage 1\'s tables) and its env_targets and '
              'env_touched at their addresses')


# ---------------------------------------------------------------- untouched pads
NEUTRAL = [('all zero', ext2()),
           ('version 0, everything else set', ext2(12, 30, 40, 1, 60, 70, 20, 10, 50, 1, 2, version=0)),
           ('an unknown version, everything set', ext2(12, 30, 40, 1, 60, 70, 20, 10, 50, 1, 2, version=2)),
           ('version 1, depth 0 and filter off, the rest set', ext2(0, 30, 40, 0, 60, 70, 20, 10, 50, 1, 2)),
           ('version 1, reserved bytes only', ext2(rest=b'\x05\x06\x07\x08'))]
ACTIVE = ext2(12, 0, 60, 1, 40, 60, 30, 0, 70, 1, 1)


def neutral_checks(img, parent, man, n):
    rnd = random.Random(5)
    p, m = Fill(parent), Fill(img, man['entries'])
    bad, total, kinds = [], 0, set()
    for k in range(n * 3):
        label, b = NEUTRAL[k % len(NEUTRAL)]
        i = rnd.randrange(32)
        pad = rnd.randrange(160)
        mode, stereo = k % 3, k // 3 % 2 == 1
        step = rnd.choice((0x4000, 7732, 34716, 20000, 12000, 0x4000 + rnd.randrange(-4000, 9000)))
        speed = rnd.choice((1.0, 1.0, 0.5, 1.5, 0.8))
        if k % 7 == 6:                                  # a voice without a pad, the pad bytes shaped
            label, b, vpad = 'a voice whose pad index is not a pad', ACTIVE, rnd.choice((160, 1000, -1))
            for f in (p, m):
                f.set_ext(0, b)
        else:
            vpad = pad
        for f in (p, m):
            f.set_ext(max(vpad, 0) % 160, b)
        objs = [f.setup(i, vpad & M32, mode, step, speed, stereo, seed=k) for f in (p, m)]
        res = [[], []]
        for c in range(4):
            for j, f in enumerate((p, m)):
                f.fill(objs[j], stereo)
                got, L, R, pos, _ = f.chunk(objs[j], 2048, stereo, base=step)
                res[j].append((got, L, R, pos, f.state(objs[j])))
        total += 4
        kinds.add((mode, stereo))
        if res[0] != res[1]:
            bad.append((label, i, vpad, mode, stereo, step, speed))
    check(not bad and len(kinds) == 6,
          f'untouched pads: every chunk\'s frames, frame count, position tag and the whole resampler and engine state '
          f'are the parent\'s ({total} chunks; {len(NEUTRAL)} kinds of neutral bytes and voices without a pad; '
          f'stretch modes 0-2, mono and stereo, steps 7732-34716, speeds 0.5-1.5; {bad[:2]})')
    # an object that is not one of the voices' is stock, whatever the pad bytes say
    m.set_ext(9, ACTIVE)
    m.setup(4, 9)
    active = m.m.call(man['entries']['pf_active'], VOICES + 4 * VOICE_SIZE + 0x140)
    bad = [m.m.call(man['entries']['pf_active'], a) for a in (VOICES + 4 * VOICE_SIZE + 0x144, VOICES + 0x140 - VOICE_SIZE,
                                                               VOICES + 0x140 + 32 * VOICE_SIZE, 0x30000000)]
    check(not any(bad) and active == 1,
          f'pf_active: an object that is not one of the 32 voices\' (off by a word, past the last, elsewhere) is '
          f'stock even when pad bytes are set; voice 4 on a shaped pad is not ({bad})')


# ---------------------------------------------------------------- pitch
def random_pitch(rnd, model):
    b = ext2(rnd.choice((12, -12, 24, -24, 7, -5, 1, rnd.randrange(-30, 31) or 3)),
             rnd.choice((0, 0, 1, 20, 40, 64, 80, rnd.randrange(128))),
             rnd.choice((0, 30, 50, 64, 72, 80, 96, rnd.randrange(128))),
             pcurve=rnd.randrange(4))
    return b


def pitch_checks(img, parent, man, model, n):
    rnd = random.Random(9)
    p, m = Fill(parent), Fill(img, man['entries'])
    bad_calls, bad_frames, bad_state, total, seen = [], [], [], 0, set()
    for k in range(n * 2):
        i, pad = rnd.randrange(32), rnd.randrange(160)
        b = random_pitch(rnd, model)
        s = model.settings(b)
        mode, stereo = k % 3, k // 3 % 2 == 1
        base = rnd.choice((0x4000, 0x4000, 9000, 25000, 34716, 7732, 3000, 40000))
        speed = rnd.choice((1.0, 1.0, 0.75, 1.25))
        for f in (p, m):
            f.set_ext(pad, b)
        objs = [f.setup(i, pad, mode, base, speed, stereo, seed=k + 100) for f in (p, m)]
        gen0, t = voice_state(m.m, man['entries'], i)[0], 0
        for c in range(rnd.choice((3, 5, 8))):
            for f, o in zip((p, m), objs):
                f.fill(o, stereo)
            want = model.calls(s, base, mode, t, 2048)
            m.calls = []
            got, L, R, pos, _ = m.chunk(objs[1], 2048, stereo, base=base)
            calls, m.calls = m.calls, None
            total += 1
            seen.add((mode, len(want) > 1, any(st == base for _, st in want), any(st != base for _, st in want)))
            if calls != want:
                bad_calls.append((b.hex(), mode, stereo, base, c, calls[:4], want[:4]))
                break
            pgot, pL, pR, ppos = p.driven(objs[0], want, stereo, base)
            if (got, L[:got], R[:got], pos) != (pgot, pL, pR, ppos):
                bad_frames.append((b.hex(), mode, stereo, base, c, got, pgot))
                break
            if p.state(objs[0]) != m.state(objs[1]) or m.m.r32(objs[1] + 0x20) != base:
                bad_state.append((b.hex(), mode, stereo, base, c))
                break
            t += got
            if voice_state(m.m, man['entries'], i)[1] != t:
                bad_state.append(('clock', b.hex(), c, voice_state(m.m, man['entries'], i)[1], t))
                break
    check(not bad_calls, f'pitch: the kernel gets the model\'s steps and sub-block lengths (64 frames, 175 in stretch mode '
                         f'2; equal steps in one call), chunk after chunk ({total} chunks; depths -30..30, attack, decay '
                         f'and hold, four curves, bases 3000-40000; {bad_calls[:1]})')
    check(not bad_frames, f'pitch: every frame, the frame count and the position tag are the parent kernel\'s for that '
                          f'step sequence ({bad_frames[:2]})')
    check(not bad_state and len({x[0] for x in seen}) == 3,
          f'pitch: the resampler and engine state after each chunk are the parent\'s, the step is put back to the base, '
          f'and the clock counts the frames produced ({bad_state[:2]}; {sorted(seen)})')
    # the clamp: within -24..+13 semitones of unity, a base outside is not pushed further out
    edge = []
    for base, depth, want_lo, want_hi in ((0x4000, 24, None, 34716), (0x4000, -24, 4096, None), (40000, 12, None, 40000),
                                          (3000, -12, 3000, None), (30000, 5, None, 34716)):
        st = model.step(base, depth, ONE)
        edge.append((want_hi is None or st == want_hi) and (want_lo is None or st == want_lo))
    check(all(edge) and model.step(0x4000, 12, ONE) == 32768 and model.step(0x4000, -12, ONE) == 8192 and
          model.step(0x4000, 7, ONE) == 24548 and model.step(12345, 3, 0) == 12345,
          f'the step: +12 = 32768, -12 = 8192, +7 = 24548 (2^(7/12) x 16384 = 24548.4) from unity; level 0 leaves the '
          f'base; clamped to 4096..34716 unless the base is outside ({edge})')
    # a step set elsewhere between sub-blocks becomes the new base; a short return stops the chunk
    b = ext2(12, 0, 64)
    for f in (p, m):
        f.set_ext(3, b)
    s = model.settings(b)
    obj = m.setup(5, 3, 0, 0x4000, 1.0, False, seed=77)
    m.fill(obj, False)
    m.calls = []
    hits = []

    def poke(uc, a, sz, _):
        if len(m.calls) == 3 and not hits:      # the kernel's third call: a pitch edit lands meanwhile
            hits.append(1)
            m.m.w32(obj + 0x20, 20000)
    h = m.uc.hook_add(UC_HOOK_CODE, poke, None, begin=0x140BE, end=0x140BE)   # the mono wrapper after the kernel
    m.chunk(obj, 2048, False, base=0x4000)
    m.uc.hook_del(h)
    calls, m.calls = m.calls, None
    t = 64 * 3
    want = model.calls(s, 0x4000, 0, 0, 2048)[:3] + [(mm, st) for mm, st in model.calls(s, 20000, 0, t, 2048 - t)]
    check(calls == want and m.m.r32(obj + 0x20) == 20000,
          f'a step set elsewhere during a chunk (after the third sub-block) is the base from then on, and it is left '
          f'in place at the end ({calls[:5]} / {want[:5]})')
    obj = m.setup(6, 3, 0, 0x4000, 1.0, False, seed=78)
    m.fill(obj, False, target=600, block=600)     # 600 frames of source, then nothing: the voice's last chunk
    m.calls = []
    got = m.chunk(obj, 2048, False, base=0x4000)
    calls, m.calls = m.calls, None
    check(0 < got[0] < 600 and len(calls) < 32 and got[3] == M32 and sum(c[0] for c in calls[:-1]) < got[0] and
          m.m.r32(obj + 0x20) == 0x4000,
          f'a source that runs out: the sub-block that comes back short ends the chunk; the frames so far, tag -1, the '
          f'base step back ({got[0]} frames, {len(calls)} calls)')


# ---------------------------------------------------------------- filter
def random_filter(rnd):
    return ext2(0, 0, 0, rnd.choice((1, 1, 2, 3)), rnd.choice((0, 20, 40, 64, 90, 127, rnd.randrange(128))),
                rnd.choice((0, 40, 80, 127, rnd.randrange(128))), rnd.choice((0, 40, -40, 63, -63, 20)),
                rnd.choice((0, 0, 30, 60)), rnd.choice((0, 50, 70, 90)), fcurve=rnd.randrange(4))


def filter_checks(img, parent, man, model, n, both=False):
    rnd = random.Random(13 if not both else 17)
    p, m = Fill(parent), Fill(img, man['entries'])
    bad, total, kinds = [], 0, set()
    for k in range(n * 2):
        i, pad = rnd.randrange(32), rnd.randrange(160)
        b = random_filter(rnd)
        if both:
            pb = random_pitch(rnd, model)
            b = pb[:3] + b[3:9] + bytes([pb[9] & 3 | b[9] & 12]) + b[10:]
        s = model.settings(b)
        mode, stereo = k % 3, k // 3 % 2 == 1
        if not both:
            b = b[:3] + bytes([k % 3 + 1]) + b[4:]         # LP, BP, HP in turn
            s = model.settings(b)
        base = rnd.choice((0x4000, 12000, 25000))
        for f in (p, m):
            f.set_ext(pad, b)
        objs = [f.setup(i, pad, mode, base, 1.0, stereo, seed=k + 300) for f in (p, m)]
        st, t = ZERO_STATE, 0
        for c in range(rnd.choice((2, 4, 6))):
            for f, o in zip((p, m), objs):
                f.fill(o, stereo)
            got, L, R, pos, _ = m.chunk(objs[1], 2048, stereo, base=base)
            calls = model.calls(s, base, mode, t, 2048) if s['depth'] else [(2048, base)]
            pgot, pL, pR, ppos = p.driven(objs[0], calls, stereo, base)
            wL, wR, st = model.filter(s, st, pL, pR, t)
            total += 1
            kinds.add(('LP', 'BP', 'HP')[s['type'] - 1] + ('+env' if s['amt'] else '') + ('+pitch' if s['depth'] else ''))
            vs = voice_state(m.m, man['entries'], i)
            if (got, L, R, pos) != (pgot, wL, wR, ppos) or vs[2] != (st[0][0], st[0][1], st[1][0], st[1][1]) or \
                    vs[1] != t + got:
                diff = [j for j in range(len(L)) if L[j] != wL[j]]
                bad.append((b.hex(), mode, stereo, c, got, pgot, len(diff), diff[:3]))
                break
            t += got
    label = 'pitch and filter together' if both else 'filter'
    covered = {x.split('+')[0] for x in kinds} == {'LP', 'BP', 'HP'} and any('+env' in x for x in kinds) if not both \
        else all('+pitch' in x for x in kinds)
    check(not bad and covered,
          f'{label}: every frame is the float32 model\'s TPT state-variable filter on the parent\'s frames, and the '
          f'filter state and clock carry over from chunk to chunk ({total} chunks; {sorted(kinds)}; {bad[:2]})')


# ---------------------------------------------------------------- new starts
def restart_checks(img, man, model):
    m = Fill(img, man['entries'])
    e = man['entries']
    b = ext2(12, 0, 64, 1, 50, 90, 40, 0, 72, 1, 1)
    s = model.settings(b)
    m.set_ext(11, b)
    gens, clocks = [], []
    obj = m.setup(7, 11, 0, 0x4000, 1.0, True, seed=5)
    for c in range(3):
        m.fill(obj, True)
        m.chunk(obj, 2048, True, base=0x4000)
    clocks.append(voice_state(m.m, e, 7)[1])
    env = VOICES + 7 * VOICE_SIZE + 0x60
    for lr in CALLERS_LR[1:] + (0x30001F00,):            # edits and a non-Init caller: no new start
        m.m.recompute(env, 0, 400000, 0, 100, 0, 2, lr=lr)
    gens.append(m.m.r32(e['pf_gen'] + 7 * 4))
    m.m.recompute(env, 0, 400000, 0, 100, 0, 2, lr=INIT_RET)
    gens.append(m.m.r32(e['pf_gen'] + 7 * 4))
    m.m.recompute(T.SCRATCH + 0x800, 0, 1000, 0, 100, 0, 2, lr=INIT_RET)                 # not a voice's block
    gens.append(sum(m.m.r32(e['pf_gen'] + 4 * j) for j in range(32)))
    # the voice is reused: Init sets its resampler up again, the next chunk starts from zero
    obj = m.setup(7, 11, 0, 0x4000, 1.0, True, seed=6)
    ref = Fill(img, man['entries'])
    ref.set_ext(11, b)
    robj = ref.setup(7, 11, 0, 0x4000, 1.0, True, seed=6)
    same = []
    for c in range(3):
        m.fill(obj, True)
        ref.fill(robj, True)
        a, bb = m.chunk(obj, 2048, True, base=0x4000), ref.chunk(robj, 2048, True, base=0x4000)
        same.append(a[:4] == bb[:4])
    clocks.append(voice_state(m.m, e, 7)[1])
    check(clocks == [6144, 6144] and gens == [1, 2, 2] and all(same),
          f'a new start: only the recompute from Init (return address 0x80023b05) bumps the voice\'s generation (A/H/R, '
          f'START, END, loop-point edits and other callers don\'t; a block that is not a voice\'s neither); the next '
          f'chunks are a fresh voice\'s: envelopes and filter from zero ({gens}, {clocks}, {same})')
    # stage 1's dispatcher calls the stage: env_stages[0]
    check(m.m.r32(man['stage1']['entries']['env_stages']) == e['pf_stage'],
          'stage 1\'s env_stages[0] is pf_stage in the running image')


# ---------------------------------------------------------------- test 5: the bypass, the race
def robust_checks(img, parent, man, model):
    e = man['entries']
    # an LP fully open (or an HP fully down) without resonance passes the frames as they are
    p, m = Fill(parent), Fill(img, e)
    ok = []
    for b, follows, bypass in ((ext2(0, 0, 0, 1, 127, 0), True, True), (ext2(0, 0, 0, 3, 0, 0), False, True),
                               (ext2(0, 0, 0, 1, 127, 0, -40, 0, 40), True, None),
                               (ext2(0, 0, 0, 1, 126, 0), None, False), (ext2(0, 0, 0, 3, 1, 0), None, False),
                               (ext2(0, 0, 0, 1, 127, 1), None, False)):
        for stereo in (False, True):
            for f in (p, m):
                f.set_ext(4, b)
            objs = [f.setup(6, 4, 0, 0x4000, 1.0, stereo, seed=21) for f in (p, m)]
            s = model.settings(b)
            st, t, same = ZERO_STATE, 0, True
            for c in range(3):
                outs = []
                for f, o in zip((p, m), objs):
                    f.fill(o, stereo)
                    outs.append(f.chunk(o, 2048, stereo, base=0x4000))
                wL, wR, st = model.filter(s, st, outs[0][1], outs[0][2], t)
                vs = voice_state(m.m, e, 6)
                same = same and outs[1][1:3] == (wL, wR) and vs[2] == (st[0][0], st[0][1], st[1][0], st[1][1])
                t += 2048
            passes = outs[1][1:3] == outs[0][1:3]
            ok.append((same, bypass is None or passes == bypass,
                       follows is None or (vs[2][0] == 0 and (vs[2][1] != 0) == follows)))
    check(all(all(x) for x in ok),
          f'the bypass: an LP at 127 or an HP at 0 without resonance passes the frames as they are (the parent\'s), its '
          f'state following the input (LP: the low state on the last sample, HP: zero); an LP opening back up after a '
          f'falling envelope matches the model through the switch; an LP at 126, an HP at 1 and an LP at 127 with '
          f'RESO 1 filter ({ok})')
    # a new start (another task's Init) while a fill is running: that fill's state isn't written back
    m = Fill(img, e)
    b = ext2(12, 0, 64, 1, 50, 90, 40, 0, 72, 1, 1)
    m.set_ext(9, b)
    obj = m.setup(8, 9, 0, 0x4000, 1.0, False, seed=8)
    for c in range(2):
        m.fill(obj, False)
        m.chunk(obj, 2048, False, base=0x4000)
    before = bytes(m.uc.mem_read(e['pf_voices'] + 8 * 24, 24))
    fired = []

    def init_now(uc, a, sz, _):
        if not fired:
            fired.append(1)
            m.m.w32(e['pf_gen'] + 8 * 4, m.m.r32(e['pf_gen'] + 8 * 4) + 1)
    h = m.uc.hook_add(UC_HOOK_CODE, init_now, None, begin=KERNEL, end=KERNEL)
    m.fill(obj, False)
    m.chunk(obj, 2048, False, base=0x4000)
    m.uc.hook_del(h)
    after = bytes(m.uc.mem_read(e['pf_voices'] + 8 * 24, 24))
    m.fill(obj, False)
    m.calls = []
    m.chunk(obj, 2048, False, base=0x4000)
    calls, m.calls = m.calls, None
    fresh = voice_state(m.m, e, 8)
    want = model.calls(model.settings(b), 0x4000, 0, 0, 2048)
    check(fired and after == before and calls == want and fresh[1] == 2048,
          f'a new start while a fill runs (pf_gen bumped during the chunk, as another task\'s Init on a reused voice '
          f'would): the fill\'s clock and filter state are not written back, and the next chunk starts the envelopes '
          f'from zero ({after == before}, {calls[:2]}, clock {fresh[1]})')


# ---------------------------------------------------------------- CPU
def cpu_checks(img, parent, man):
    p, m = Fill(parent), Fill(img, man['entries'])
    rows = {}
    settings = (('stock (untouched pad)', ext2()), ('pitch: depth 12, decay 739 ms (moving all chunk)', ext2(12, 0, 96)),
                ('pitch: after its decay (one call)', ext2(12, 0, 8)),
                ('filter: LP, resonance 80, cutoff envelope', ext2(0, 0, 0, 1, 40, 80, 40, 0, 90)),
                ('pitch + filter', ext2(12, 0, 96, 1, 40, 80, 40, 0, 90)))
    for stereo in (False, True):
        for mode in (0, 2):
            for label, b in settings:
                counts = []
                for which, f in (('parent', p), ('image', m)):
                    f.set_ext(2, b)
                    obj = f.setup(1, 2, mode, 0x4000, 1.0, stereo, seed=3)
                    f.fill(obj, stereo)
                    f.chunk(obj, 2048, stereo, base=0x4000)
                    f.fill(obj, stereo)
                    counts.append(f.chunk(obj, 2048, stereo, base=0x4000, count=True)[4])
                rows[(stereo, mode, label)] = counts
    lines = ['  instructions per 2048-frame chunk (the second chunk of a voice):']
    for (stereo, mode, label), (pc, mc) in rows.items():
        lines.append(f'  {"stereo" if stereo else "mono  "} mode {mode} {label:50s} parent {pc[0]:8d}  image {mc[0]:8d} '
                     f'(x{mc[0] / pc[0]:.2f}), in the module {mc[1]:6d}')
    print('\n'.join(lines))
    stock_extra = max(rows[(st, md, 'stock (untouched pad)')][1][0] - rows[(st, md, 'stock (untouched pad)')][0][0]
                      for st in (False, True) for md in (0, 2))
    check(stock_extra <= 200, f'an untouched pad costs the image {stock_extra} instructions more per 2048-frame chunk '
                              f'(the settings check)')
    return rows


# ---------------------------------------------------------------- the ENVELOPE pages
PF_LABELS = [['C1:DEPTH', 'C2:ATTACK', 'C3:DECAY'], ['C1:TYPE', 'C2:CUTOFF', 'C3:RESO'],
             ['C1:AMOUNT', 'C2:ATTACK', 'C3:DECAY'], ['C1:PITCH', '', 'C3:FILTER']]
PF_NAMES = ['PITCH', 'FILTER', 'F-ENV', 'CURVES']
FILTER_NAMES = ['OFF', 'LPF', 'BPF', 'HPF']
CURVE_NAMES = ['LIN', 'EXP', 'LOG', 'S']
PAGES = 8                                                # stage 1's four, then these four


def ext2_of(m, pad):
    return bytes(m.uc.mem_read(EXT + pad * 0x80 + 0x71, 15))


def set_ext2(m, pad, b):
    m.uc.mem_write(EXT + pad * 0x80 + 0x71, bytes(b))


def zone(raw, n):
    return max(0, min(127, raw)) * n >> 7


def pf_values(model, k, b):
    """the three values page 5 + k shows for bytes 0x71-0x7f"""
    e = b if b[14] == 1 else bytes(15)
    F = model.F

    def times(ai, di):
        return [T.time_text(F[e[ai] & 127]), T.time_text(F[e[di] & 127]) if e[di] & 127 else 'HOLD']
    if k == 0:
        d = max(-24, min(24, s8(e[0])))
        return ['OFF' if not d else f'{d:+d}st'] + times(1, 2)
    if k == 1:
        hz, q = hz_table()[e[4] & 127], q10_table()[e[5] & 127]
        t = (hz + 50) // 100
        return [FILTER_NAMES[e[3] & 3], f'{hz}Hz' if hz < 1000 else f'{t // 10}.{t % 10}k', f'{q // 10}.{q % 10}']
    if k == 2:
        a = max(-63, min(63, s8(e[6])))
        t = (abs(a) * 156942 + 50000) // 100000
        return ['0' if not a else f'{"-" if a < 0 else "+"}{t // 10}.{t % 10}oct'] + times(7, 8)
    return [CURVE_NAMES[e[9] & 3], '', CURVE_NAMES[e[9] >> 2 & 3]]


def pf_graph(model, k, b):
    """the points page 5 + k draws (PITCH, F-ENV: the envelope, up for +, down for -), or None: stage 1's graph"""
    e = b if b[14] == 1 else bytes(15)
    F = model.F
    if k == 0:
        sign, atk, dec, c = max(-24, min(24, s8(e[0]))), F[e[1] & 127], F[e[2] & 127], e[9] & 3
    elif k == 2:
        sign = max(-63, min(63, s8(e[6]))) if e[3] & 3 else 0
        atk, dec, c = F[e[7] & 127], F[e[8] & 127], e[9] >> 2 & 3
    else:
        return None
    if not sign:
        return []
    span = atk + (dec if dec else atk // 4 + 1)
    pts = []
    for x in range(128):
        t = x * (span // 127) + x * (span % 127) // 127
        y = (model.level(t, atk, dec, c) * 15 + 16384) >> 15
        pts.append((x, 17 + y if sign < 0 else 32 - y))
    return pts


def pf_matches(m, screens, model, pad, k):
    """the image's screen and static layer are the reference's for page 5 + k of pad"""
    st = T.pad_state(m, pad)
    b2 = ext2_of(m, pad)
    v = dict(labels=PF_LABELS[k], values=pf_values(model, k, b2),
             bottom=f'{T.pad_label(pad)} {PF_NAMES[k]} {5 + k}/{PAGES}')
    g = pf_graph(model, k, b2)
    if g is None:
        sh = screens.shape(st['b'], pad, st['a'], st['h'], st['r'])
        v['graph'] = screens.points(sh, st['loop'], st['play']) if sh else None
    else:
        v['graph'] = g
    return m.screen() == screens.draw(v, pad, st['a'], st['h'], st['r'], st['loop'], st['play'])


PF_CONFIGS = [  # (what, bytes 0x71-0x7f, stage 1 bytes)
    ('all off', ext2(), T.ext_bytes()),
    ('pitch +12, decay 216 ms, EXP; LP 40 / reso 80, amount +40, attack 5.4 ms, decay 739 ms, LOG',
     ext2(12, 0, 80, 1, 40, 80, 40, 32, 96, 1, 2), T.ext_bytes()),
    ('pitch -24, attack 63 ms, HOLD, S; HP 100, amount -63, HOLD; stage 1 FINE + decay',
     ext2(-24, 64, 0, 3, 100, 127, -63, 0, 0, 3, 3), T.ext_bytes(3, 32, 90, 0x19, 70, 40)),
    ('BP at 20 Hz with no envelope; pitch +1 with no times', ext2(1, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0), T.ext_bytes()),
    ('an unknown layout version, everything set', ext2(12, 30, 40, 1, 60, 70, 20, 10, 50, 1, 2, version=2),
     T.ext_bytes()),
]


def ui_checks(img, parent, man, model):
    sym = dict(man['stage1']['entries'], **man['entries'])
    screens = T.Screens(T.Model(curve_tables(), fine_frames()), fine_frames(), parent)
    m = T.Machine(img, sym, screen=True)
    for pad in range(32):
        m.load_pad(pad)
        m.samples[pad] = T.SPAN
    T.setup(m, 5, T.ext_bytes(), 20, 80, 40, 0, 0)
    m.current_pad(5)
    m.dispatch(T.EV_KEY, T.KEY_SHIFT)
    m.open_page()
    m.tick(2)
    m.dispatch(T.EV_KEY_UP, T.KEY_SHIFT)
    m.tick()
    # the pages come after stage 1's four, each on the screen
    seq = []
    for k in range(PAGES):
        m.tap()
        n = m.ui()['page']
        seq.append((n, pf_matches(m, screens, model, 5, n - 4) if 4 <= n < 8 else
                    T.matches(m, screens, n, 5, count=PAGES)))
    check(seq == [(1, True), (2, True), (3, True), (4, True), (5, True), (6, True), (7, True), (0, True)],
          f'tapping SHIFT: stage 1\'s pages ("A-6 SHAPE 2/8" ...), then PITCH 5/8, FILTER 6/8, F-ENV 7/8, CURVES 8/8 on '
          f'the screen (labels, values, graph, bottom line, byte for byte with the reference), then page 1 '
          f'("A-6 AMP 1/8") ({seq})')
    turned = []
    for delta in (-1, -1, 1, 1):
        m.dispatch(T.EV_ENCODER, 0, delta)
        n = m.ui()['page']
        turned.append((n, pf_matches(m, screens, model, 5, n - 4) if 4 <= n < 8 else
                       T.matches(m, screens, n, 5, count=PAGES)))
    check(turned == [(7, True), (6, True), (7, True), (0, True)],
          f'VALUE turned: left from page 1 to CURVES 8/8 (round), F-ENV 7/8, right back to 8/8 and round to 1/8, each '
          f'on the screen; CURVES shows nothing for CTRL 2 ({turned})')
    # every page for several kinds of settings
    bad = []
    for what, b2, b1 in PF_CONFIGS:
        m.set_ext(5, b1)
        set_ext2(m, 5, b2)
        for k in range(4):
            T.go_to(m, 4 + k)
            m.draw()
            if not pf_matches(m, screens, model, 5, k):
                bad.append((what, PF_NAMES[k]))
    check(not bad, f'pages 5-8 for {len(PF_CONFIGS)} kinds of settings (off; both envelopes and LP; -24 st with HOLD, '
                   f'HP, a falling cutoff, stage 1 shaping too; BP without envelopes; an unknown layout): the screen and '
                   f'static layer are the reference\'s byte for byte, the PITCH and F-ENV graphs the envelopes ({bad})')
    # the knobs: bytes, the layout version, the screen after each turn
    m.set_ext(5, T.ext_bytes())
    set_ext2(m, 5, ext2())
    turns = [(0, 1, 100), (0, 1, 0), (0, 1, 64), (0, 2, 40), (0, 3, 0), (0, 3, 90), (0, 1, 127),
             (1, 1, 40), (1, 2, 30), (1, 3, 127), (1, 1, 100), (1, 1, 0), (1, 2, 0), (1, 1, 64),
             (2, 1, 0), (2, 1, 127), (2, 1, 64), (2, 1, 90), (2, 2, 20), (2, 3, 0), (2, 3, 100),
             (3, 1, 40), (3, 3, 127), (3, 2, 77), (3, 1, 0)]
    want = bytearray(15)
    seq = []
    for k, ctrl, raw in turns:
        T.go_to(m, 4 + k)
        before = bytes(want)
        m.knob(ctrl, raw)
        byte = {(0, 1): 0, (0, 2): 1, (0, 3): 2, (1, 1): 3, (1, 2): 4, (1, 3): 5, (2, 1): 6, (2, 2): 7, (2, 3): 8}
        if (k, ctrl) in byte:
            i = byte[(k, ctrl)]
            v = {(0, 1): (zone(raw, 49) - 24) & 0xFF, (2, 1): (zone(raw, 127) - 63) & 0xFF}.get((k, ctrl),
                                                                                                zone(raw, 4 if (k, ctrl) == (1, 1) else 128))
            if (k, ctrl) == (1, 1) and not want[3] and v in (1, 2) and not want[4]:
                want[4] = 127                                # the filter turned on: the cutoff opens
            want[i] = v
        elif k == 3 and ctrl != 2:
            sh = 0 if ctrl == 1 else 2
            want[9] = want[9] & ~(3 << sh) | zone(raw, 4) << sh
        want[14] = 1 if any(want[:14]) else 0
        got = ext2_of(m, 5)
        seq.append(got == bytes(want) and pf_matches(m, screens, model, 5, k))
        if got != bytes(want):
            seq.append(('bytes', k, ctrl, raw, got.hex(), bytes(want).hex(), before.hex()))
    check(all(x is True for x in seq),
          f'each turn on pages 5-8 writes its byte (DEPTH -24..+24 in 49 zones, times as the fine index, TYPE in 4 '
          f'zones, AMOUNT -63..+63), sets the layout version (back to 0 when all are 0), opens the cutoff when the '
          f'filter goes on at 0, and the screen follows ({len(turns)} turns; {[x for x in seq if x is not True][:2]})')
    # every value the knobs reach, as the screen writes it
    texts = []
    for k, ctrl, values in ((0, 1, range(128)), (0, 2, range(128)), (0, 3, range(128)), (1, 2, range(128)),
                            (1, 3, range(128)), (2, 1, range(128))):
        T.go_to(m, 4 + k)
        for raw in values:
            m.texts.clear()
            m.knob(ctrl, raw)
            shown = [s for x, y, s in m.texts if y == T.VALUE_Y and x == T.COLUMNS[ctrl - 1]]
            texts.append((shown[-1:] == [pf_values(model, k, ext2_of(m, 5))[ctrl - 1]], shown[-1:]))
    sample = [t[1] for t in texts[0::37]]
    check(all(t[0] for t in texts), f'every value the knobs reach is shown as the model says: depths, attack and decay '
                                    f'times (and HOLD), cutoffs in Hz and k, Q, amounts in octaves ({len(texts)} turns; '
                                    f'e.g. {sample})')
    # an unknown layout version: the old bytes didn't count, so they start from zero
    set_ext2(m, 5, ext2(12, 30, 40, 1, 60, 70, 20, 10, 50, 1, 2, version=2))
    T.go_to(m, 4)
    m.knob(1, 100)
    check(ext2_of(m, 5) == ext2((zone(100, 49) - 24), 0, 0), f'a turn on a pad with an unknown layout version: the '
                                                              f'other bytes are cleared first ({ext2_of(m, 5).hex()})')
    # COPY / REMAIN: the mute group and the bank, as stage 1's pages
    for pad in range(32):
        set_ext2(m, pad, ext2())
    for pad, group in ((5, 2), (7, 2), (12, 2), (18, 2), (3, 1), (21, 0)):
        m.set(0x6D, group, pad)
    m.protected = {1}
    T.go_to(m, 5)
    m.uc.mem_write(T.APPLY_MODE, struct.pack('<i', 1))
    m.knob(3, 90)                                         # RESO to the mute group
    group = [pad for pad in range(32) if ext2_of(m, pad)[5] == 90]
    m.uc.mem_write(T.APPLY_MODE, struct.pack('<i', 2))
    m.unload_pad(9)
    m.knob(2, 70)                                         # CUTOFF to the bank (pad 9 holds no sample)
    m.load_pad(9)
    bank = [pad for pad in range(32) if ext2_of(m, pad)[4] == 70]
    m.uc.mem_write(T.APPLY_MODE, struct.pack('<i', 0))
    check(group == [5, 7, 12] and bank == [pad for pad in range(16) if pad != 9] and
          all(ext2_of(m, pad)[14] == 1 for pad in bank),
          f'COPY held: the mute group (pads 5, 7, 12; pad 18 is in protected bank B); REMAIN held: the bank but pad 9, '
          f'which holds no sample; each with its layout version ({group}, {bank})')
    # the save: Edited, then command 0xD once, 1 s after the last turn; and on leaving
    m.clear()
    m.w32(CSMPLPRM + 0x1C, 0)
    m.knob(2, 33)
    edited = m.r32(CSMPLPRM + 0x1C) & 0xFF
    m.tick(19)
    early = list(m.posts)
    m.tick(1)
    once = [x[:3] for x in m.posts]
    m.tick(30)
    m.clear()
    m.knob(2, 34)
    m.leave()
    check(edited == 1 and not early and once == [(0xD, 1, 0)] and [x[:3] for x in m.posts][:1] == [(0xD, 1, 0)],
          f'a turn sets stock\'s Edited flag; command 0xD (1, 0) goes out once 1 s after the last turn, and when the '
          f'page closes with a change not yet saved ({early}, {once}, {m.posts[:2]})')
    # a pad without a sample: nothing written
    m.current_pad(5)
    m.open_page()
    m.unload_pad(5)
    before = ext2_of(m, 5)
    for k in range(4):
        T.go_to(m, 4 + k)
        for ctrl in (1, 2, 3):
            m.knob(ctrl, 99)
    check(ext2_of(m, 5) == before, 'a pad holding no sample: pages 5-8 write nothing (stage 1 calls no turn)')
    m.load_pad(5)
    lines = [s for _, _, s in m.texts] + [x for k in range(4) for x in PF_LABELS[k] + PF_NAMES[k:k + 1]]
    T.go_to(m, 7)
    m.draw()
    first = pf_matches(m, screens, model, 5, 3)          # the reference's label and value for CTRL 2 are empty
    b = ext2_of(m, 5)
    m.knob(2, 77)
    check(first and pf_matches(m, screens, model, 5, 3) and ext2_of(m, 5) == b and PF_LABELS[3][1] == '',
          'page 8 (CURVES) has nothing in CTRL 2\'s place, no label and no value (the screen is the reference\'s, '
          'byte for byte); turning CTRL 2 writes nothing and shows nothing')
    check(all(len(s) <= 16 and s.isascii() for s in lines) and all(len(x) <= 10 for k in range(4) for x in PF_LABELS[k]),
          f'labels at most 10 characters, values and names at most 16 ({max(lines, key=len)!r})')
    # DEL, then VALUE, on one of these pages: stage 1's reset clears this stage's bytes too, 0x70 stays
    T.go_to(m, 4)
    m.uc.mem_write(EXT + 5 * 0x80 + 0x64, T.full_settings(5)[:13] + ext2(12, 30, 80, 1, 50, 90, 40, 0, 72, 1, 1))
    before = T.all_bytes(m, 5)
    m.w32(VOICES + 2 * VOICE_SIZE + 0x14274, 5)
    on_before = m.call(man['entries']['pf_active'] | 1, VOICES + 2 * VOICE_SIZE + 0x140)
    m.draw()
    m.clear()
    T.press(m, T.KEY_DEL)
    asked = m.ui()['asking'] == 1 and (64, T.NAME_Y, 'RESET A-6? press VALUE') in m.texts
    T.press(m, T.KEY_VALUE)
    after = T.all_bytes(m, 5)
    on_after = m.call(man['entries']['pf_active'] | 1, VOICES + 2 * VOICE_SIZE + 0x140)
    check(asked and after[:12] == bytes(12) and after[12] == before[12] and after[13:] == bytes(15) and
          pf_matches(m, screens, model, 5, 0) and on_before and not on_after and {x[1] for x in m.fanouts} == {5},
          f'DEL on page 5 asks "RESET A-6? press VALUE"; VALUE clears stage 1\'s bytes and these (0x71-0x7F: pitch and '
          f'filter off, PITCH 5/8 shows it), note repeat\'s 0x70 stays, the pad\'s voices recompute ({after.hex()})')


def main():
    out = Path(sys.argv[1]).resolve()
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    parent = Path(man['parent_app1']).read_bytes()
    check(sha(parent) == man['parent_sha256'], 'the parent APP1 is the manifest\'s')
    model = Model()
    static_checks(out, man, img, parent)
    neutral_checks(img, parent, man, n)
    pitch_checks(img, parent, man, model, n)
    filter_checks(img, parent, man, model, n)
    filter_checks(img, parent, man, model, max(2, n // 2), both=True)
    restart_checks(img, man, model)
    robust_checks(img, parent, man, model)
    ui_checks(img, parent, man, model)
    cpu_checks(img, parent, man)
    print(f'\n{cases[0] - len(fails)}/{cases[0]} checks pass')
    if fails:
        print('FAILED:')
        for f in fails:
            print('  ' + f[:300])
        sys.exit(1)


if __name__ == '__main__':
    main()
