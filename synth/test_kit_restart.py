"""A live hit does not depend on what its voice played before (kits v9.45).

The table voices (UDS, MP-7, TR-707, TR-727) used to start their noise filters
from the filter memory of the voice's previous sound; v9.45 clears it at every
hit, as the other engines do. On the built ARM module (kit_output on fake stock
voice states, the live render path, as test_kit_chord.py does it), every pad of
those four kits is struck twice at the same live clock frame, so its noise seed
is the same: once on a fresh voice, once on a voice that has been playing a
ringing open hat, cymbal or cabasa for 43 ms. The two hits must match sample for
sample. With an older build as the second argument, the same cases are run on it
and the pads that differed there are reported, with how large the
difference was against each hit's own peak.
Usage: python synth/test_kit_restart.py out/kits-v945 [out/kits-v944]
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL
from unicorn import arm_const as ar

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from kits.sparse_module import reconstruct_module  # noqa: E402

V0, RET, STACK, VOICE = 0x80249800, 0x1000, 0x20200000, 0x1B0
# (kit, the ringing pad played first): UDS open hat, MP-7 cymbal 2, TR-707 open hat, TR-727 cabasa.
CASES = ((4, 3), (9, 3), (12, 3), (13, 9))
BEFORE_BLOCKS, HIT_BLOCKS = 32, 16                 # 43 ms of the other pad, then 21 ms of the hit


class Module:
    def __init__(self, folder: Path):
        self.man = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        img = (folder / 'SP404MKII_APP1.bin').read_bytes()
        if hashlib.sha256(img).hexdigest() != self.man['sha256']:
            raise ValueError('APP1/manifest hash mismatch')
        self.base, self.module, self.S = self.man['arp_code_base'], reconstruct_module(img, self.man), self.man['arp_symbols']
        uc = self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for b, n in ((0, 0x2000), (0x80249000, 0x1000), (0x8353A000, 0x3000), (0x83F80000, 0x70000),
                     (STACK - 0x4000, 0x4000), (0x800DE000, 0x1000)):
            uc.mem_map(b, n, UC_PROT_ALL)
        uc.mem_write(RET, b'\x00\xbf')
        for address in (0x800DED08, 0x800DECF8):          # DISPATCH_OFF / DISPATCH_ON stubs
            uc.mem_write(address, b'\x70\x47')
        uc.reg_write(ar.UC_ARM_REG_C1_C0_2, uc.reg_read(ar.UC_ARM_REG_C1_C0_2) | (0xf << 20))
        uc.reg_write(ar.UC_ARM_REG_FPEXC, 0x40000000)

    def call(self, fn, *args):
        uc = self.uc
        uc.reg_write(ar.UC_ARM_REG_SP, STACK - 0x100)
        uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        for k, a in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), a & 0xFFFFFFFF)
        uc.emu_start(self.S[fn] | 1, RET, count=50_000_000)
        if uc.reg_read(ar.UC_ARM_REG_PC) != RET:
            raise RuntimeError(('instruction limit or early exit', fn))
        return uc.reg_read(ar.UC_ARM_REG_S0)

    def strike(self, pad):
        st = bytearray(VOICE)
        st[0] = 1
        struct.pack_into('<I', st, 0x1AC, pad)
        struct.pack_into('<i', st, 0x19C, 8 + pad)
        self.uc.mem_write(V0, bytes(st))

    def block(self, sounding):
        self.call('kit_begin_block', 64)
        self.call('kit_finish_begin_block', 64)
        out = []
        if sounding:
            for _ in range(64):
                out.append(self.call('kit_output', V0))
                self.uc.mem_write(V0 + 0x18C, struct.pack('<f', 1.0))   # the parent's ENV marks the start
        return out

    def hit(self, kit, pad, before):
        """pad struck at block BEFORE_BLOCKS on voice 0; `before` rings there first (or nothing)."""
        self.uc.mem_write(self.base, self.module)
        self.uc.mem_write(self.S['kit_mode'], bytes([kit]))
        if before is not None:
            self.strike(before)
        for _ in range(BEFORE_BLOCKS):
            self.block(before is not None)
        self.strike(pad)
        out = []
        for _ in range(HIT_BLOCKS):
            out += self.block(True)
        return b''.join(struct.pack('<I', v) for v in out)


def run(module):
    """Pads (1..16) whose hit differed, per kit, and each difference's peak relative to the hit's peak (dB)."""
    differ, levels = {}, []
    for kit, other in CASES:
        differ[kit] = []
        for pad in range(16):
            fresh, after = module.hit(kit, pad, None), module.hit(kit, pad, other)
            if fresh != after:
                differ[kit].append(pad + 1)
                a = struct.unpack(f'<{len(fresh) // 4}f', fresh)
                b = struct.unpack(f'<{len(after) // 4}f', after)
                peak, diff = max(map(abs, a)), max(abs(x - y) for x, y in zip(a, b))
                levels.append(20 * math.log10(diff / peak) if peak > 0 and diff > 0 else -200.0)
    return differ, levels


def main():
    new = Module(Path(sys.argv[1]).resolve())
    differ, _ = run(new)
    if any(differ.values()):
        raise AssertionError(('a live hit depends on what its voice played before', differ))
    report = dict(passed=True, kits=[k for k, _ in CASES], pads=16 * len(CASES), frames=64 * HIT_BLOCKS,
                  history_ms=round(64 * BEFORE_BLOCKS / 48), app1_sha256=new.man['sha256'])
    if len(sys.argv) > 2:
        old = Module(Path(sys.argv[2]).resolve())
        before, levels = run(old)
        levels.sort()
        report['baseline'] = dict(build=old.man['revision'], pads_that_differed={str(k): v for k, v in before.items()},
                                  count=sum(len(v) for v in before.values()),
                                  difference_db_re_peak=dict(largest=round(levels[-1], 1), median=round(levels[len(levels) // 2], 1)) if levels else None)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
