"""Kit footer: no "SHIFT: PAGE" at the bottom of the drum kit screen.

The kit stage's footer (kit_ui_footer_draw, kits/kit_ui.inc) takes the Sound Generator page's footer widget
while a kit is on: it clears the footer and draws "SHIFT: PAGE" in it. The user asked for the text to go (the first
draw after entering drum mode also showed it in the big font, as "SHIFT: PA"). The kit stage is baked into every
feature build's parent, so this is a step on top of the finished APP1, as the fast boot is: the string's first
byte becomes 0, so the footer is still cleared and the text function draws nothing.

The guards: the string's 12 bytes at its runtime address, the one literal that refers to it (in the footer's
code) and that nothing else in the image does.

usage: python synth/build_kit_footer.py IN_APP1 OUT_DIR [--revision NAME]
"""
import argparse
import json
import shutil
import struct
from pathlib import Path

from build_arp import file_offset
from build_boot_anim import APP0_SHA, NAMES, runtime, sha

SITE = 0x83FBAF36                   # "SHIFT: PAGE\0" in the kit stage's blob (boot copy row to 0x83fa2000)
TEXT = b'SHIFT: PAGE\0'
LITERAL = 0x83FA7718                # kit_ui_footer_draw's literal pool word for it


def build(inp: Path, out: Path, revision: str):
    img = bytearray(inp.read_bytes())
    app0 = inp.with_name('SP404MKII_APP0.bin')
    if sha(app0.read_bytes()) != APP0_SHA:
        raise ValueError('expected stock APP0 beside the input APP1')
    if runtime(img, SITE, len(TEXT)) != TEXT:
        raise ValueError(f'{SITE:#x}: expected the kit footer\'s {TEXT!r}')
    if struct.unpack('<I', runtime(img, LITERAL, 4))[0] != SITE:
        raise ValueError(f'{LITERAL:#x}: expected the footer\'s literal for {SITE:#x}')
    refs = [i for i in range(0, len(img) - 3) if img[i:i + 4] == struct.pack('<I', SITE)]
    if refs != [file_offset(img, LITERAL, 4)]:
        raise ValueError(f'the string is referred to from elsewhere too: {[hex(r) for r in refs]}')
    for n in NAMES:
        if (out / n).exists():
            raise ValueError(f'refusing to overwrite {out / n}')
    off = file_offset(img, SITE, 1)
    parent_sha = sha(img)
    img[off] = 0
    if runtime(img, SITE, len(TEXT)) != b'\0' + TEXT[1:]:
        raise AssertionError('the patch is not what the footer reads')

    out.mkdir(parents=True, exist_ok=True)
    (out / 'SP404MKII_APP1.bin').write_bytes(img)
    shutil.copy2(app0, out / 'SP404MKII_APP0.bin')
    parent_manifest = inp.with_name('manifest.json')
    manifest = dict(
        revision=revision, status='hardware-unverified', published=False,
        description='no "SHIFT: PAGE" at the bottom of the drum kit screen (the footer is still cleared); the rest '
                    'of the parent as it was',
        parent_app1=str(inp), parent_sha256=parent_sha,
        parent_revision=json.loads(parent_manifest.read_text(encoding='utf-8')).get('revision')
        if parent_manifest.exists() else None,
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        patches=[dict(address=SITE, size=1, original_hex=TEXT[:1].hex(), replacement_hex='00',
                      what='the kit footer\'s "SHIFT: PAGE": its first byte 0, an empty string')],
        guards=[dict(address=SITE, bytes_hex=TEXT.hex(), establishes='the kit footer\'s text'),
                dict(address=LITERAL, value=SITE, establishes='kit_ui_footer_draw\'s literal for it, the only '
                                                                'reference in the image')],
        tool='synth/build_kit_footer.py')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    sums = ''.join(f'{sha((out / n).read_bytes())}  {n}\n' for n in NAMES)
    (out / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8', newline='\n')
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('app1', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--revision', default='kit-footer-test1')
    a = ap.parse_args()
    m = build(a.app1.resolve(), a.out.resolve(), a.revision)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size')}, indent=1))


if __name__ == '__main__':
    main()
