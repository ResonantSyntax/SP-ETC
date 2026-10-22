"""Fast boot: straight to the main screen once the project has loaded, without the boot animation.

At the end of the project load, the stock boot page's method 0x8013dbe8 does two things. It arms the UI
tick at 50 ms (0x800c7da0(50)). It sets the page's counter [+0x1aa0] to 20 (0x8013dcaa: movs r0, #0x14).
Each tick (0x8013d860) adds 1. The page's draw (0x8013d8b8) ends the boot at 160: it resets the screen
state, sends 01 FF 90 00 to the BMC and asks for page 1, the main screen.

Stock draws the Roland logo stages from 20 to 160, about 7 s. DOOM OS's draw (0x60328b60, vtable slot
0x80224f3c) jumps the counter to 80 and plays its Boot Anim to 160, about 4 s. At 160 or more it goes
straight to the stock draw.

This build changes the 20 to 160, one byte at 0x8013dcab, so the first draw after the load ends the boot.
Everything before the load's end is as it was: a draw during the load still shows the animation's first
step. The Boot Anim setting no longer shows. The guards check the code above byte for byte first.

usage: python synth/build_fast_boot.py IN_APP1 OUT_DIR [--revision NAME]
"""
import argparse
import json
import shutil
import struct
from pathlib import Path

import capstone

from build_arp import file_offset
from build_boot_anim import APP0_SHA, NAMES, runtime, sha

SITE = 0x8013DCAA
BEFORE, AFTER = 'movs r0, #0x14', 'movs r0, #0xa0'
# (start, end, SHA-256 of the parent's runtime bytes, what it establishes): stock 5.52 and DOOM OS 0.6.1 ED5E
GUARDS = [
    (0x8013DBE8, 0x8013DCC0, 'cadcfa1f7e7c850b9c575269d1e392431c4f473d333d97f5e51298b47fd80694',
     'the boot page at the end of the project load: the UI tick at 50 ms (0x800c7da0(50)), the BMC packets, '
     'then counter [+0x1aa0] = 20 (0x8013dcaa) through r8 = page + 0x1a78'),
    (0x8013D860, 0x8013D894, '64371c175bb87e9e1fd4c91777cf018c49a2efbf22a3c523fbec5b85ce1540d2',
     'the boot page\'s tick: counter + 1, the logo stage from 21, 41, 61 and over 80, then a redraw request'),
    (0x8013D8B8, 0x8013D8F8, '35c4d6ef49503969aac5afdba43b0b2cdf37f9ca3ad82a65d60873c2eb4e2e71',
     'the stock draw: from 160 the screen state reset (0x80016880, 0x80016898), 01 FF 90 00 to the BMC and '
     'page 1 (0x800da598); below it the logo'),
    (0x60328B60, 0x60328B7A, 'd42eedb4907e6e8d74e91fff9be62fe04ccca3f511ba7be025b80bdcfd1ea603',
     'DOOM OS\'s draw: from 160 straight to its exit, below 80 the counter to 80'),
    (0x60328C24, 0x60328C34, '53a3bb7ef5cfe547edb8c1e58396a168ab74b0a57a39808cc8471995c55c800a',
     'DOOM OS\'s exit: on to the stock draw 0x8013d8b9 with the page'),
]
TABLE_GUARDS = [(0x80224F3C, 0x60328B61, 'the boot page\'s draw slot: DOOM OS\'s draw'),
                (0x80224F40, 0x8013D861, 'the boot page\'s tick slot: the stock tick')]


def listing(code, at):
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    return [f'{i.mnemonic} {i.op_str}' for i in md.disasm(code, at)]


def build(inp: Path, out: Path, revision: str):
    img = bytearray(inp.read_bytes())
    app0 = inp.with_name('SP404MKII_APP0.bin')
    if sha(app0.read_bytes()) != APP0_SHA:
        raise ValueError('expected stock APP0 beside the input APP1')
    for a, e, d, what in GUARDS:
        if sha(runtime(img, a, e - a)) != d:
            raise ValueError(f'guard {a:#x}..{e:#x} fails: {what}')
    for a, v, what in TABLE_GUARDS:
        if struct.unpack('<I', runtime(img, a, 4))[0] != v:
            raise ValueError(f'{a:#x}: expected {v:#x} ({what})')
    for n in NAMES:
        if (out / n).exists():
            raise ValueError(f'refusing to overwrite {out / n}')
    off = file_offset(img, SITE, 2)
    old = bytes(img[off:off + 2])
    if listing(old, SITE) != [BEFORE]:
        raise ValueError(f'{SITE:#x}: expected {BEFORE}, found {listing(old, SITE)}')
    new = bytes([0xA0, old[1]])
    if listing(new, SITE) != [AFTER]:
        raise ValueError(f'{SITE:#x}: bad encoding {listing(new, SITE)}')
    parent_sha = sha(img)
    img[off:off + 2] = new
    if runtime(img, SITE, 2) != new:
        raise AssertionError('the patch is not what the boot page runs')

    out.mkdir(parents=True, exist_ok=True)
    (out / 'SP404MKII_APP1.bin').write_bytes(img)
    shutil.copy2(app0, out / 'SP404MKII_APP0.bin')
    parent_manifest = inp.with_name('manifest.json')
    manifest = dict(
        revision=revision, status='hardware-unverified', published=False,
        description='fast boot: the main screen right after the project load, without the boot animation (DOOM '
                    'OS\'s Boot Anim, about 4 s); the rest of the parent as it was',
        parent_app1=str(inp), parent_sha256=parent_sha,
        parent_revision=json.loads(parent_manifest.read_text(encoding='utf-8')).get('revision')
        if parent_manifest.exists() else None,
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        patches=[dict(address=SITE, size=2, original_hex=old.hex(), replacement_hex=new.hex(),
                      what=f'the boot page\'s counter at the end of the project load: {BEFORE} -> {AFTER} (20 -> '
                           f'160, the end of the boot screen)')],
        guards=[dict(start=a, end=e, sha256=d, establishes=w) for a, e, d, w in GUARDS],
        table_guards=[dict(address=a, value=v, establishes=w) for a, v, w in TABLE_GUARDS],
        timing='the boot page ticks every 50 ms from the end of the load: stock 140 ticks (20 to 160), DOOM OS 80 '
               '(80 to 160), this build none',
        tool='synth/build_fast_boot.py')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    sums = ''.join(f'{sha((out / n).read_bytes())}  {n}\n' for n in NAMES)
    (out / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8', newline='\n')
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('app1', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--revision', default='fast-boot-test1')
    a = ap.parse_args()
    m = build(a.app1.resolve(), a.out.resolve(), a.revision)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size')}, indent=1))


if __name__ == '__main__':
    main()
