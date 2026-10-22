"""Boot animation: one of DOOM OS's Boot Anim styles shows your own frames.

DOOM OS 0.6.1 ED5E keeps its boot animations in its SPUA block (0x60307a00, in flash, run in place). Its
BOOTANI section holds 61 frames of 128 x 64 at 0x60309770, 1024 bytes each. A table at 0x6033132c gives each
style 15 steps (frame numbers; frame 0 is blank). The boot screen (0x60328b70) draws step
min((t - 80) / 4, 14) of the style with the stock blit 0x800bdc48(context, frame, 0). The blit takes screen
pixel (x, y) from bit 31 - (i & 31) of little-endian word i >> 5, i = 128 * (63 - y) + x: MSB first in
32-bit words, rows bottom-up. The SYSTEM > DOOM OS menu's Boot Anim value picks the style through the bytes at
0x60331324. RANDOM (0) picks one at random, never the last one again (B:/DOOMBOOT.DAT keeps the last).

  value  menu        style row  frames it owns
  1      GRAFFITI    3          37-50
  2      VHS         4          51-60
  3      HELLO       2          24-36
  4      BUBBLE      0          1-12
  5      SKETCH      1          13-23
  6      HYPERSPACE  5          none: drawn by code

A style keeps its menu name and takes up to as many frames as it owns. They replace its frames in order. Its
row plays them, after the blank first step if the style had one, and holds the last until the boot screen
ends. Only those frames and that row change. The guards check DOOM OS 0.6.1 ED5E's bytes and the stock blit
first.

usage: python synth/build_boot_anim.py IN_APP1 OUT_DIR --frames DIR [--style hello] [--revision NAME]
  DIR: 128 x 64 images, played in file-name order; a pixel is lit from 50% grey up
"""
import argparse
import hashlib
import json
import shutil
import struct
from pathlib import Path

from PIL import Image

from build_arp import scatter

FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
APP0_SHA = '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23'
FRAMES, FRAME, COUNT = 0x60309770, 1024, 61
TABLE, STEPS, ROWS = 0x6033132C, 15, 5
STYLES = {'graffiti': (1, 3), 'vhs': (2, 4), 'hello': (3, 2), 'bubble': (4, 0), 'sketch': (5, 1)}
NAMES = ('SP404MKII_APP0.bin', 'SP404MKII_APP1.bin', 'manifest.json')
# (start, end, SHA-256 of the parent's runtime bytes, what it establishes): DOOM OS 0.6.1 ED5E and stock 5.52
GUARDS = [
    (0x60307A00, 0x60307A70, 'c7a24dc9cec868e47126ed5425e550e49f3a4c038fcb7955620deec5d31b7ccc',
     'the SPUA block: SCRTBL SYSTAB SYSSTR CONTBL BOOTANI CODE; BOOTANI at +0x1d70, 0xf400 bytes (61 frames)'),
    (FRAMES, FRAMES + COUNT * FRAME, '9452925e5356c2f8ee36c7076abc9e642cc321dd9f871c3e9c39e416cb3995b4',
     'DOOM OS\'s 61 frames, as published'),
    (TABLE, TABLE + ROWS * STEPS, 'b2ff61d5cbe0c3b87e040cea8c3a909b72c96a5b7f9a8f0ba9f432ef4a552eb2',
     'the five drawn styles\' 15 steps: BUBBLE 0, 1-12; SKETCH 0, 13-23; HELLO 0, 24-36, 34; GRAFFITI 0, 37-50; '
     'VHS 51-60'),
    (0x60331320, 0x6033132B, '14aaab1cd3a276c0bf19e15b0a129f3f1dd5a889368340971c62eba27ae916d6',
     'DOOMBOOT.DAT\'s magic, then menu value 1-6 -> style row 3 4 2 0 1 5'),
    (0x60328B70, 0x60328C34, '0d4e711815efa27fb592d27fa2d548b0ef7fc46d14913d5a131f9a6900cca36e',
     'the boot screen: step min((t - 80) >> 2, 14) of rows 0-4, frame 0x60309770 + 1024 * row[step], the blit '
     'with flag 0; row 5 drawn by code'),
    (0x800BDC48, 0x800BDEC4, 'fed038cd74d40153753023d48fbb55fcef09132b4cd711abf0faebcb9a896965',
     'the stock blit: 128 x 64 to one byte a pixel; pixel (x, y) is bit 31 - (i & 31) of word i >> 5, '
     'i = 128 * (63 - y) + x; flag 0 as is, else inverted'),
]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def decompress(src, size):
    """The scatter loader's decompressing handler (0x60080088)."""
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
            out += bytes(count + 2)
    return bytes(out[:size])


def runtime(img, addr, n):
    """Flash as the file has it (DOOM OS runs in place), SDRAM as the last scatter row over it leaves it."""
    if FLASH <= addr and addr + n <= FLASH + len(img):
        return bytes(img[addr - FLASH:addr - FLASH + n])
    for load, dst, size, fn in reversed(scatter(img)):
        if dst <= addr and addr + n <= dst + size and fn in (COPY, DECOMPRESS):
            data = img[load - FLASH:load - FLASH + size] if fn == COPY else decompress(img[load - FLASH:], size)
            return bytes(data[addr - dst:addr - dst + n])
    raise ValueError(f'{addr:#x}+{n:#x} is not in one copy or decompress row')


def encode(px):
    """128 x 64 lit pixels (rows of bools) -> the blit's 1024 bytes."""
    words = [0] * 256
    for y in range(64):
        for x in range(128):
            if px[y][x]:
                i = 128 * (63 - y) + x
                words[i >> 5] |= 1 << (31 - (i & 31))
    return struct.pack('<256I', *words)


def decode(frame):
    words = struct.unpack('<256I', frame)
    return [[bool(words[(128 * (63 - y) + x) >> 5] >> (31 - ((128 * (63 - y) + x) & 31)) & 1) for x in range(128)]
            for y in range(64)]


def load_frames(folder: Path):
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in ('.png', '.bmp', '.gif', '.jpg', '.jpeg'))
    out = []
    for p in files:
        im = Image.open(p).convert('L')
        if im.size != (128, 64):
            raise ValueError(f'{p.name} is {im.size[0]} x {im.size[1]}, not 128 x 64')
        px = im.load()
        out.append((p, [[px[x, y] >= 128 for x in range(128)] for y in range(64)]))
    if not out:
        raise ValueError(f'no images in {folder}')
    return out


def preview(frames, row, path):
    """The style's 15 steps as the blit draws them, 4x, an animated GIF (250 ms a step)."""
    pics = []
    for f in row:
        im = Image.new('L', (128, 64))
        im.putdata([235 if v else 0 for line in decode(frames[f]) for v in line])
        pics.append(im.resize((512, 256), Image.NEAREST))
    pics[0].save(path, save_all=True, append_images=pics[1:], duration=250, loop=0)


def build(inp: Path, out: Path, folder: Path, style: str, revision: str):
    img = bytearray(inp.read_bytes())
    app0 = inp.with_name('SP404MKII_APP0.bin')
    if sha(app0.read_bytes()) != APP0_SHA:
        raise ValueError('expected stock APP0 beside the input APP1')
    for a, e, d, what in GUARDS:
        if sha(runtime(img, a, e - a)) != d:
            raise ValueError(f'guard {a:#x}..{e:#x} fails: {what}')
    for n in NAMES:
        if (out / n).exists():
            raise ValueError(f'refusing to overwrite {out / n}')
    value, s = STYLES[style]
    table = bytes(img[TABLE - FLASH:TABLE - FLASH + ROWS * STEPS])
    rows = [list(table[STEPS * r:STEPS * (r + 1)]) for r in range(ROWS)]
    own = sorted(set(rows[s]) - {0})
    others = {f for r in range(ROWS) if r != s for f in rows[r]}
    if own != list(range(own[0], own[-1] + 1)) or others & set(own):
        raise ValueError(f'row {s}: its frames {own} are not its own run')
    frames = load_frames(folder)
    if len(frames) > len(own):
        raise ValueError(f'{style.upper()} owns {len(own)} frames; {folder} has {len(frames)}')
    lead = [0] if rows[s][0] == 0 else []
    row = (lead + own[:len(frames)] + [own[len(frames) - 1]] * STEPS)[:STEPS]

    parent_sha = sha(img)
    patches = []
    for (p, px), f in zip(frames, own):
        at = FRAMES + FRAME * f
        new = encode(px)
        old = bytes(img[at - FLASH:at - FLASH + FRAME])
        img[at - FLASH:at - FLASH + FRAME] = new
        patches.append(dict(address=at, size=FRAME, what=f'frame {f}: {p.name}', original_sha256=sha(old),
                            replacement_sha256=sha(new)))
    at = TABLE + STEPS * s
    old = bytes(img[at - FLASH:at - FLASH + STEPS])
    img[at - FLASH:at - FLASH + STEPS] = bytes(row)
    patches.append(dict(address=at, size=STEPS, what=f'{style.upper()}\'s steps (row {s})', original_hex=old.hex(),
                        replacement_hex=bytes(row).hex()))
    all_frames = [bytes(img[FRAMES - FLASH + FRAME * k:FRAMES - FLASH + FRAME * (k + 1)]) for k in range(COUNT)]
    for (p, px), f in zip(frames, own):
        if decode(all_frames[f]) != px:
            raise AssertionError(f'frame {f} does not decode to {p.name}')

    out.mkdir(parents=True, exist_ok=True)
    preview(all_frames, row, out / 'boot-preview.gif')
    (out / 'SP404MKII_APP1.bin').write_bytes(img)
    shutil.copy2(app0, out / 'SP404MKII_APP0.bin')
    parent_manifest = inp.with_name('manifest.json')
    manifest = dict(
        revision=revision, status='hardware-unverified', published=False,
        description=f'DOOM OS\'s Boot Anim style {style.upper()} (menu value {value}) shows {len(frames)} frames of '
                    f'{folder.name}; every other style, and the rest of the parent, as they were',
        parent_app1=str(inp), parent_sha256=parent_sha,
        parent_revision=json.loads(parent_manifest.read_text(encoding='utf-8')).get('revision')
        if parent_manifest.exists() else None,
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        style=dict(name=style.upper(), menu_value=value, row=s, frames_owned=[own[0], own[-1]],
                   steps_before=rows[s], steps_after=row),
        frames=[dict(file=p.name, frame=f, address=FRAMES + FRAME * f) for (p, _), f in zip(frames, own)],
        format='128 x 64, 1024 bytes; screen pixel (x, y) = bit 31 - (i & 31) of little-endian word i >> 5, '
               'i = 128 * (63 - y) + x (the stock blit 0x800bdc48 with flag 0)',
        timing='a step every 4 of the boot screen\'s counts from 80 (0x60328b70); the last step holds',
        patches=patches, guards=[dict(start=a, end=e, sha256=d, establishes=w) for a, e, d, w in GUARDS],
        tool='synth/build_boot_anim.py')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    sums = ''.join(f'{sha((out / n).read_bytes())}  {n}\n' for n in NAMES)
    (out / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8', newline='\n')
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('app1', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--frames', type=Path, required=True)
    ap.add_argument('--style', choices=sorted(STYLES), default='hello')
    ap.add_argument('--revision', default='boot-anim-test1')
    a = ap.parse_args()
    m = build(a.app1.resolve(), a.out.resolve(), a.frames.resolve(), a.style, a.revision)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size')}, indent=1))
    print(json.dumps(m['style']))


if __name__ == '__main__':
    main()
