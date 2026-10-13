"""Chord REC on the built ARM module: drums struck together are captured together.

Two pads are struck 64 frames apart on live voices 0 and 1 (kit_output on fake
stock voice states, as test_kits.py does). kit_capture_selected must return 2,
fill both export voices (anchor = the last struck pad first) with their pads and
velocities, and the export render must reproduce each live voice sample for
sample, the earlier hit at offset 0 and the later one after 64 silent frames.
Also checks that a strike outside the 100 ms window is not captured.
Usage: python synth/test_kit_chord.py out/kits-v943
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL
from unicorn import arm_const as ar

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from kits.sparse_module import reconstruct_module  # noqa: E402

V0, CLONE, EXPORT, COUNT = 0x80249800, 0x8353A310, 0x8353C000, 0x8353C700
RET, STACK = 0x1000, 0x20200000
VOICE = 0x1B0


def main():
    out = Path(sys.argv[1]).resolve()
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    if hashlib.sha256(img).hexdigest() != man['sha256']:
        raise ValueError('APP1/manifest hash mismatch')
    base = man['arp_code_base']
    module = reconstruct_module(img, man)
    S = man['arp_symbols']
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for b, n in ((0, 0x2000), (0x80249000, 0x1000), (0x8353A000, 0x3000), (0x83F80000, 0x70000),
                 (STACK - 0x4000, 0x4000), (0x800DE000, 0x1000)):
        uc.mem_map(b, n, UC_PROT_ALL)
    uc.mem_write(base, module)
    uc.mem_write(RET, b'\x00\xbf')
    for address in (0x800DED08, 0x800DECF8):          # DISPATCH_OFF / DISPATCH_ON stubs
        uc.mem_write(address, b'\x70\x47')
    uc.reg_write(ar.UC_ARM_REG_C1_C0_2, uc.reg_read(ar.UC_ARM_REG_C1_C0_2) | (0xf << 20))
    uc.reg_write(ar.UC_ARM_REG_FPEXC, 0x40000000)

    def call(fn, *args):
        uc.reg_write(ar.UC_ARM_REG_SP, STACK - 0x100)
        uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        for k, a in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), a & 0xFFFFFFFF)
        uc.emu_start(S[fn] | 1, RET, count=2000000000)   # a drum capture pre-renders its ring-out
        if uc.reg_read(ar.UC_ARM_REG_PC) != RET:
            raise RuntimeError(('instruction limit or early exit', fn))
        return uc.reg_read(ar.UC_ARM_REG_R0), struct.unpack('<f', struct.pack('<I', uc.reg_read(ar.UC_ARM_REG_S0)))[0]

    def voice(addr, pad):
        st = bytearray(VOICE)
        st[0] = 1
        struct.pack_into('<I', st, 0x1AC, pad)
        struct.pack_into('<i', st, 0x19C, 8 + pad)
        uc.mem_write(addr, bytes(st))

    def sample(addr):
        _, y = call('kit_output', addr)
        uc.mem_write(addr + 0x18C, struct.pack('<f', 1.0))   # the parent's ENV marks the start
        return y

    def block(frames=64):
        call('kit_begin_block', frames)
        call('kit_finish_begin_block', frames)

    results = {}
    for kit, first, second in ((12, 0, 2), (1, 2, 9), (10, 4, 6)):
        uc.mem_write(base, module)
        uc.mem_write(S['kit_mode'], bytes([kit]))
        N = 1024
        live_a, live_b = [], []
        # Block 0: pad `first` starts on voice 0; block 1: pad `second` on voice 1.
        block()
        call('kit_note_seen', first, 100)
        voice(V0, first)
        live_a += [sample(V0) for _ in range(64)]
        block()
        call('kit_note_seen', second, 90)
        voice(CLONE, second)
        for _ in range(64):
            live_a.append(sample(V0))
            live_b.append(sample(CLONE))
        while len(live_a) < N:
            block()
            for _ in range(64):
                live_a.append(sample(V0))
                live_b.append(sample(CLONE))
        call('kit_note_seen', first, 0)
        call('kit_note_seen', second, 0)
        uc.mem_write(V0, bytes(VOICE))
        n, _ = call('kit_capture_selected')
        if n != 2:
            raise AssertionError(('chord count', kit, n))
        count = struct.unpack('<I', uc.mem_read(COUNT, 4))[0]
        pads = [struct.unpack('<I', uc.mem_read(EXPORT + j * VOICE + 0x1AC, 4))[0] for j in range(2)]
        vels = [struct.unpack('<I', uc.mem_read(EXPORT + j * VOICE + 0x198, 4))[0] for j in range(2)]
        if count != 2 or pads != [second, first] or vels != [9000, 10000]:
            raise AssertionError(('export voices', kit, count, pads, vels))
        # The parent's export start marks each export voice fresh and active.
        for j in range(2):
            uc.mem_write(EXPORT + j * VOICE, b'\x01')
            uc.mem_write(EXPORT + j * VOICE + 0x18C, bytes(4))
        exp_b = [sample(EXPORT) for _ in range(N)]
        exp_a = [sample(EXPORT + VOICE) for _ in range(N)]
        want_b = [0.0] * 64 + live_b[:N - 64]
        pack = lambda xs: struct.pack(f'<{len(xs)}f', *xs)
        if pack(exp_a) != pack(live_a[:N]):
            bad = next(i for i in range(N) if pack([exp_a[i]]) != pack([live_a[i]]))
            raise AssertionError(('first hit differs', kit, bad, exp_a[bad], live_a[bad]))
        if pack(exp_b) != pack(want_b):
            bad = next(i for i in range(N) if pack([exp_b[i]]) != pack([want_b[i]]))
            raise AssertionError(('second hit differs', kit, bad, exp_b[bad], want_b[bad]))
        results[kit] = dict(pads=pads, frames=N, peak_a=max(map(abs, exp_a)), peak_b=max(map(abs, exp_b)))
    # A strike more than 100 ms before the last one is not part of the chord.
    uc.mem_write(base, module)
    uc.mem_write(S['kit_mode'], bytes([12]))
    block()
    call('kit_note_seen', 0, 100)
    voice(V0, 0)
    for _ in range(64):
        sample(V0)
    for _ in range(80):          # 80 blocks = 106.7 ms
        block()
    call('kit_note_seen', 2, 90)
    voice(CLONE, 2)
    for _ in range(64):
        sample(CLONE)
    n, _ = call('kit_capture_selected')
    if n != 1:
        raise AssertionError(('window', n))
    report = dict(passed=True, chord_cases=results, outside_window_single=True, app1_sha256=man['sha256'])
    print(json.dumps(report))


if __name__ == '__main__':
    main()
