"""RESAMPLE start fix: put a resampled take's START just before its first sound.

Stock 5.52 (REPORT.md §2.8 step 9) trims a take's lead-in only when the
first sound arrives 8-23.6 ms after recording started, and even then keeps
8 ms in front. A pad-triggered resample hears its sound sooner (the effects
chip's round trip), so stock leaves that silence in. This patch:

  B  0x800e9efe  recorder engine init (at standby): for RESAMPLE takes
     (settings param 0x36 == 1) use a fixed first-sound threshold of LOW
     (|sample| > LOW) instead of the Auto Trig Level table, so soft attacks
     aren't cut. Other modes keep the table. LOW never comes from the table,
     so it also marks the take as a resample for hook A.
  A  0x8017f0ac  REC_STOP, mode != 2 branch: for takes carrying that mark,
     set START = REC_START point + first-sound frame - MARGIN, when that
     frame is MARGIN+1..WINDOW-1; otherwise START stays at the REC_START
     point. Everything else runs the stock instructions.

The margin keeps the quiet lead-in of the effects chip's return: it reaches
the take a few frames before its first sample above LOW (a hi-hat bounced on
the unit: the first non-zero sample 7 frames before the main delay).
resample-startfix-2 put START on the first sample above LOW and cut that
lead-in. The engine keeps only the first-sound frame (its writers compare each
sample with the threshold as they stage it for the card), so the margin is
fixed rather than measured back from the samples.

The code goes in a new boot copy row at BASE (top of the free SDRAM gap).
The audio data is untouched; only the pad's START moves. Mode 2 (the
pattern-select resample page) and REC sampling keep stock behaviour.

usage: python synth/build_start_fix.py IN_APP1 OUT_DIR [--base 0x83FEF000]
"""
import argparse
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

import capstone  # noqa: E402
from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB, KS_MODE_LITTLE_ENDIAN  # noqa: E402

FLASH, COPY = 0x60080000, 0x600800E4
APP0_SHA = '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23'
WINDOW = 2400          # frames (50 ms): first sound later than this keeps its lead-in
LOW = 8                # |sample| > 8 (about -72 dBFS)
MARGIN = 8             # frames kept in front of the first sample above LOW
GETPARAM = 0x800D94D8  # GetParam(settings 0x82e01144, id, idx)
SITE_A, SITE_B = 0x8017F0AC, 0x800E9EFE
EXPECT_A = ['subs.w r0, sl, r6', 'movw r1, #0xbb8', 'sbcs.w r0, sb, r5']
EXPECT_B = ['subs r0, #1', 'cmp r0, #9', 'bhi #0x800e9f0a', 'adr r1, #0xc', 'ldrh.w r7, [r1, r0, lsl #1]']
TAIL_A = 0x8017F3B8    # where the stock branch continues after reading REC BPM
TABLE_B = 0x800E9F14   # stock Auto Trig Level threshold table (left in place)
REVISION = 'resample-startfix-3'

MD = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)
KS = Ks(KS_ARCH_ARM, KS_MODE_THUMB | KS_MODE_LITTLE_ENDIAN)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def asm(src, at):
    return bytes(KS.asm(src, at)[0])


def listing(code, at):
    return [f'{i.mnemonic} {i.op_str}'.strip() for i in MD.disasm(code, at)]


def scatter(img):
    a, b = struct.unpack_from('<2I', img, 0x80)
    return [list(struct.unpack_from('<4I', img, i)) for i in range(a + 0x80, b + 0x80, 16)]


def file_offset(img, addr, size):
    for load, dst, n, fn in scatter(img):
        if fn == COPY and load and dst <= addr and addr + size <= dst + n:
            return load - FLASH + addr - dst
    raise ValueError(f'{addr:#x} not in a copy row')


def lo(v):
    return v & 0xFFFF


def hi(v):
    return v >> 16


def blob_source(base):
    """Two entry points; every external target is reached through r12."""
    t = TAIL_A | 1
    g = GETPARAM | 1
    # The trim keys on the engine threshold, not on mode 0x36 at stop time: hook B gives
    # RESAMPLE takes the value LOW when they are armed, which the stock table never yields,
    # and the SG page's stop path resets 0x36 right after posting the stop.
    return f"""
trim:
    ldr.w   r12, [r4, #0x254]
    ldrsh.w r0, [r12, #0x1f8]
    cmp     r0, #{LOW}
    bne     stock
    ldrd    r0, r1, [r12, #0x208]
    cmp     r1, #0
    bne     bpm
    movw    r1, #{WINDOW}
    cmp     r0, r1
    bhs     bpm
    subs    r0, #{MARGIN}
    ble     bpm
    ldrh.w  r1, [r12, #0x24]
    muls    r0, r1, r0
    lsls    r0, r0, #1
    adds.w  sl, sl, r0
    adc     sb, sb, #0
    b       bpm
stock:
    subs.w  r0, sl, r6
    movw    r1, #0xbb8
    sbcs.w  r0, sb, r5
    mov.w   r0, #0
    it      lo
    movlo   r0, #1
    subs    r1, r3, r1
    mov.w   r1, #0
    sbcs    r2, r2, #0
    it      lo
    movlo   r1, #1
    ands    r0, r1
    itt     ne
    movne   sb, r5
    movne   sl, r6
bpm:
    sxth.w  r2, fp
    movw    r0, #0x1144
    movt    r0, #0x82e0
    mov.w   r1, #0x1b
    movw    r12, #{lo(g)}
    movt    r12, #{hi(g)}
    blx     r12
    movw    r12, #{lo(t)}
    movt    r12, #{hi(t)}
    bx      r12
    nop
thr:
    subs    r0, #1
    cmp     r0, #9
    bhi     thr_mode
    movw    r1, #{lo(TABLE_B)}
    movt    r1, #{hi(TABLE_B)}
    ldrh.w  r7, [r1, r0, lsl #1]
thr_mode:
    movw    r0, #0x1144
    movt    r0, #0x82e0
    movs    r1, #0x36
    movs    r2, #0
    movw    r12, #{lo(g)}
    movt    r12, #{hi(g)}
    blx     r12
    cmp     r0, #1
    bne     thr_store
    movs    r7, #{LOW}
thr_store:
    strh.w  r7, [r4, #0x1f8]
    add     sp, #4
    pop     {{r4, r5, r6, r7, pc}}
"""


def labels(src):
    out, pc_names = {}, []
    for line in src.splitlines():
        line = line.strip()
        if line.endswith(':'):
            pc_names.append(line[:-1])
    return pc_names


def assemble_blob(base):
    src = blob_source(base)
    code = asm(src, base)
    # Entry offsets: assemble the prefix up to each label.
    entries = {}
    lines = src.splitlines()
    for name in ('trim', 'thr'):
        idx = next(i for i, l in enumerate(lines) if l.strip() == name + ':')
        prefix = '\n'.join(lines[:idx]) + '\n'
        entries[name] = base + len(asm(prefix, base)) if prefix.strip() else base
    # Every direct branch must stay inside the blob (keystone has mis-encoded wide branches before).
    for ins in MD.disasm(code, base):
        if ins.mnemonic.startswith(('b', 'cb')) and ins.mnemonic not in ('bx', 'blx') and '#' in ins.op_str:
            target = int(ins.op_str.split('#')[-1], 16)
            if not base <= target < base + len(code):
                raise ValueError(f'blob branch at {ins.address:#x} leaves the blob: {target:#x}')
    text = listing(code, base)
    for must in ('mov.w r0, #0', 'mov.w r1, #0', 'sbcs.w r0, sb, r5', 'subs.w r0, sl, r6'):
        if must not in text:
            raise ValueError(f'assembled stock replica lacks {must!r}')
    return code, entries


def jump(target):
    return f'movw r12, #{lo(target | 1)}\nmovt r12, #{hi(target | 1)}\nbx r12\nnop\n'


def loaded_literal(img, off):
    """True if some Thumb PC-relative LDR/LDR.W/LDRD/VLDR within 4 KB before `off` reads it.
    PC-relative loads use file offsets equivalently here: rows map file and runtime linearly."""
    for a in range(max(off - 4096, 0) & ~1, off, 2):
        h1 = struct.unpack_from('<H', img, a)[0]
        pc = (a + 4) & ~3
        if (h1 & 0xF800) == 0x4800 and pc + (h1 & 0xFF) * 4 == off:
            return True
        if a + 4 > len(img):
            continue
        h2 = struct.unpack_from('<H', img, a + 2)[0]
        if (h1 & 0xFF7F) == 0xF85F and (pc + (h2 & 0xFFF) if h1 & 0x80 else pc - (h2 & 0xFFF)) == off:
            return True
        if (h1 & 0xFE7F) in (0xE85F, 0xE95F) and (pc + (h2 & 0xFF) * 4 if h1 & 0x80 else pc - (h2 & 0xFF) * 4) == off:
            return True
    return False


def refs_into(img, lo_a, hi_a):
    """32-bit literals actually loaded by PC-relative instructions, or MOVW/MOVT pairs, in the whole
    file, pointing into [lo_a, hi_a). (Instruction bytes that merely look like an address don't count.)"""
    hits = []
    for off in range(0, len(img) - 3, 4):
        v = struct.unpack_from('<I', img, off)[0]
        if lo_a <= v < hi_a and loaded_literal(img, off):
            hits.append(('literal', off, v))
    regs = {}
    for off in range(0, len(img) - 3, 2):
        h1, h2 = struct.unpack_from('<HH', img, off)
        if (h1 & 0xFBF0) in (0xF240, 0xF2C0) and not h2 & 0x8000:
            imm = ((h1 & 0xF) << 12) | (((h1 >> 10) & 1) << 11) | (((h2 >> 12) & 7) << 8) | (h2 & 0xFF)
            rd = (h2 >> 8) & 0xF
            if (h1 & 0xFBF0) == 0xF240:
                regs[rd] = (off, imm)
            elif rd in regs and off - regs[rd][0] <= 64:
                v = (imm << 16) | regs[rd][1]
                if lo_a <= v < hi_a:
                    hits.append(('movw/movt', off, v))
    return hits


def build(inp: Path, out: Path, base: int):
    img = bytearray(inp.read_bytes())
    app0 = inp.with_name('SP404MKII_APP0.bin')
    if sha(app0.read_bytes()) != APP0_SHA:
        raise ValueError('expected stock APP0 beside the input APP1')
    rows = scatter(img)
    code, entries = assemble_blob(base)
    end = base + len(code)
    if end > 0x83FF0000:
        raise ValueError('blob crosses the non-cacheable region')
    for load, dst, n, fn in rows:
        if max(dst, base) < min(dst + n, end):
            raise ValueError(f'row {dst:#x}+{n:#x} overlaps the blob area')
    hits = refs_into(bytes(img), base & ~0xFFF, (end + 0xFFF) & ~0xFFF)
    if hits:
        raise ValueError(f'input refers to the blob area: {hits[:4]}')
    patches = []
    for site, expect, target in ((SITE_A, EXPECT_A, entries['trim']), (SITE_B, EXPECT_B, entries['thr'])):
        off = file_offset(img, site, 12)
        found = listing(bytes(img[off:off + 12]), site)
        if found != expect:
            raise ValueError(f'{site:#x}: expected {expect}, found {found}')
        new = asm(jump(target), site)
        if len(new) != 12 or listing(new, site)[:3] != [f'movw ip, #{lo(target | 1):#x}', f'movt ip, #{hi(target | 1):#x}', 'bx ip']:
            raise ValueError(f'{site:#x}: bad jump encoding {listing(new, site)}')
        patches.append(dict(address=site, size=12, original_hex=bytes(img[off:off + 12]).hex(),
                            replacement_hex=new.hex(), target=target))
        img[off:off + 12] = new
    file_at = (len(img) + 15) & ~15
    img += bytes(file_at - len(img)) + code
    table = (len(img) + 15) & ~15
    img += bytes(table - len(img))
    for row in rows + [[FLASH + file_at, base, len(code), COPY]]:
        img += struct.pack('<4I', *row)
    struct.pack_into('<2I', img, 0x80, table - 0x80, len(img) - 0x80)
    out.mkdir(parents=True, exist_ok=True)
    for name in ('SP404MKII_APP1.bin', 'SP404MKII_APP0.bin', 'manifest.json'):
        if (out / name).exists():
            raise ValueError(f'refusing to overwrite {out / name}')
    (out / 'SP404MKII_APP1.bin').write_bytes(img)
    shutil.copy2(app0, out / 'SP404MKII_APP0.bin')
    parent_manifest = inp.with_name('manifest.json')
    manifest = dict(
        revision=REVISION, status='hardware-unverified', published=False,
        description='RESAMPLE takes start just before their first sound, with its quiet lead-in (stock leaves the '
                    'effects-chip delay as silence)',
        replaces='resample-startfix-2 (START on the first sample above the threshold, which cut the return\'s '
                 'quiet lead-in)',
        parent_app1=str(inp), parent_sha256=sha(inp.read_bytes()),
        parent_revision=json.loads(parent_manifest.read_text()).get('revision') if parent_manifest.exists() else None,
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        blob_base=base, blob_file_offset=file_at, blob_size=len(code), blob_sha256=sha(code),
        entries=entries, patches=patches, window_frames=WINDOW, threshold=LOW, margin_frames=MARGIN,
        scope='takes armed with settings param 0x36 == 1 (RESAMPLE page, incl. hot resample into the SG); REC sampling, the pattern-select resample page and pattern export are stock',
        tool='synth/build_start_fix.py')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    sums = ''.join(f'{sha((out / n).read_bytes())}  {n}\n' for n in ('SP404MKII_APP0.bin', 'SP404MKII_APP1.bin', 'manifest.json'))
    (out / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8', newline='\n')
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('app1', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0x83FEF000)
    a = ap.parse_args()
    m = build(a.app1, a.out, a.base)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size', 'blob_base', 'blob_size', 'entries')}, indent=1))


if __name__ == '__main__':
    main()
