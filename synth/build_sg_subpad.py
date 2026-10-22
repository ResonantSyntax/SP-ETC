"""SUB PAD on the Sound Generator page (hardware test build): the last pad played again, on the published v9.46.

A stage on Sound Generator + Kits v9.46 (APP1 7b5fbcb4...684a; SG_SUBPAD.md). In v9.46, SUB PAD on the Sound
Generator page stops the voices or toggles the generator's tone. Here it plays the last pad played on the page,
at SUB PAD's velocity, in melodic and drum mode, and its release lets that pad go.

Two words of the Sound Generator page's vtable (0x802295a8) change; no code does:
- +0xfc  (0x802296a4) the pad press 0x8015bf91 -> sp_press, which calls it;
- +0x100 (0x802296a8) the pad release 0x8015c4b1 -> sp_release, which calls it.
Stock code the module calls or relies on is checked byte for byte (GUARDS). The module (Zig 0.13.0, -Os) goes in
a new boot copy row in a 4 KB slot at 0x83FD4000, below kits save (0x83FD5000), taken from the top of the room
pad FX was given (0x83FC9000-0x83FD4000 stays its own). The builder checks three things: that no row and no other
fork module's slot overlaps the slot, and that nothing in the input refers to it.

usage: python synth/build_sg_subpad.py IN_APP1 OUT_DIR --zig ZIG [--base 0x83FD4000] [--build-dir DIR]
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

from build_arp import file_offset, read_module, scatter
from build_start_fix import refs_into

HERE = Path(__file__).resolve().parent
FLASH, COPY, DECOMPRESS, ZERO = 0x60080000, 0x600800E4, 0x60080088, 0x60080100
APP0_SHA = '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23'
REVISION = 'sg-subpad-test1'
SLOT = 0x1000                       # reserved: [base, base + SLOT)
GAP = (0x83FC9000, 0x83FF0000)      # above the fork's rows (end 0x83FC8450), below the end of cacheable SDRAM
KNOWN_SLOTS = [
    ('pad FX (planned)', 0x83FC9000, 0x83FD4000),
    ('claude/kits-save (kit edits saved with the project)', 0x83FD5000, 0x83FD7000),
    ('claude/chroma-scales (chromatic scales)', 0x83FD7000, 0x83FD9000),
    ('claude/pad-env-pitchfilter (pad envelopes stage 2)', 0x83FD9000, 0x83FDC000),
    ('claude/note-repeat (note repeat)', 0x83FDC000, 0x83FDE000),
    ('claude/pad-env-amp (pad envelopes stage 1)', 0x83FDE000, 0x83FE2000),
    ('claude/fx-deep-edit (FX deep edit)', 0x83FE2000, 0x83FE6000),
    ('claude/fx-probe (FX probe)', 0x83FE6000, 0x83FE8000),
    ('claude/bounce-stage2, claude/bounce-stage3 (bounce)', 0x83FE8000, 0x83FED000),
    ('claude/cpu-meter (CPU meter test)', 0x83FED000, 0x83FEF000),
    ('claude/bounce-probe (bounce probe test)', 0x83FEE000, 0x83FEF000),
    ('main (RESAMPLE start fix)', 0x83FEF000, 0x83FF0000),
]
ENTRIES = ('sp_press', 'sp_release')
EXPORTS = ENTRIES + ('sp_last', 'sp_held', 'sp_plays')
# (address, the word there in the parent, the entry that replaces it, what)
VTABLE = [
    (0x802296A4, 0x8015BF91, 'sp_press', 'SG page vtable 0x802295a8 +0xfc: pad press (page, pad, velocity)'),
    (0x802296A8, 0x8015C4B1, 'sp_release', 'SG page vtable +0x100: pad release (page, pad, velocity)'),
]
# Stock 5.52 code the module calls or relies on, as in v9.46: (start, end, SHA-256, what).
GUARDS = [
    (0x8015BF90, 0x8015C228, '663081d3b4895f336924d620344e4c0859633e8c0b5fd0c039057d218e0d2edf',
     'the SG page\'s pad press (page, pad, velocity): with SHIFT held nothing (pad 1: 0x8015c04c); SUB PAD (0x13) '
     'stops the voices or toggles the tone; a pad 0-15 plays its note (0x83fa1101) through the SG note event '
     '0x1fc01, the pad as its source, after FIXED VELOCITY and the first-hit start'),
    (0x8015C4B0, 0x8015C520, '2942a0816cb7746677751353d7443c4ba18936d6e04a6b9fb0d5d045749a5672',
     'its pad release: SUB PAD nothing; a pad 0-15 its note off through 0x1fc01 (velocity 0), the pad as source'),
    (0x8003B53A, 0x8003B714, '3c7504b76fa8ec6f962a0cf01edde4ce72dfa2cd562889e21023e7fceb0ccb9b',
     'the UI dispatcher after its first ten bytes (note repeat\'s entry): a key press sets its bit in 0x80592448, '
     'a release clears it, before the page gets the event'),
    (0x80065448, 0x800654C0, '667b0f94736e075cb00b7cdad49cf6ec6276d318d0b18427ad7dfa3a9dfdef05',
     'the SG page\'s registry handler: the page object with vptr 0x802295a8'),
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
            out += bytes(count)
    return bytes(out[:size])


class Runtime:
    """Runtime bytes of an APP1 image, as its scatter loader leaves them (copy, decompress and zero rows; a later row
    over an earlier one wins)."""

    def __init__(self, img):
        self.img, self.rows, self.cache = bytes(img), scatter(img), {}

    def row(self, k):
        load, dst, size, fn = self.rows[k]
        if k not in self.cache:
            if fn == COPY:
                self.cache[k] = self.img[load - FLASH:load - FLASH + size]
            elif fn == DECOMPRESS:
                self.cache[k] = decompress(self.img[load - FLASH:], size)
            elif fn == ZERO:
                self.cache[k] = bytes(size)
            else:
                raise ValueError(f'unknown scatter handler {fn:#x}')
        return self.cache[k]

    def read(self, addr, n):
        out, have = bytearray(n), bytearray(n)
        for k in range(len(self.rows) - 1, -1, -1):
            load, dst, size, fn = self.rows[k]
            lo, hi = max(addr, dst), min(addr + n, dst + size)
            if lo >= hi:
                continue
            data = self.row(k)
            for a in range(lo, hi):
                if not have[a - addr]:
                    out[a - addr] = data[a - dst]
                    have[a - addr] = 1
        if not all(have):
            raise ValueError(f'{addr:#x}+{n:#x} is not all set by the scatter rows')
        return bytes(out)


def compile_module(folder: Path, zig: Path, link_base: int, limit: int):
    folder.mkdir(parents=True, exist_ok=True)
    if subprocess.check_output([str(zig), 'version'], text=True).strip() != '0.13.0':
        raise ValueError('needs Zig 0.13.0')
    keep = ' '.join(f'KEEP(*(.text.{n}))' for n in ENTRIES)
    (folder / 'sg_subpad.ld').write_text(f'''ENTRY(sp_press)
SECTIONS {{
 . = {link_base:#x};
 .text : {{ {keep} *(.text*) }}
 .rodata : ALIGN(16) {{ *(.rodata*) }}
 .data : ALIGN(16) {{ *(.data*) }}
 .bss : ALIGN(16) {{ *(.bss*) *(COMMON) }}
 /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.note*) }}
}}
''', encoding='ascii', newline='\n')
    source = folder / 'sg_subpad.c'             # compile LF-normalized source
    source.write_bytes((HERE / 'sg_subpad.c').read_bytes().replace(b'\r\n', b'\n'))
    cache = folder / 'cache'
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache))
    # -g only keeps the symbol table: Zig's -Os (ReleaseSmall) strips it otherwise. Same code. --no-gc-sections
    # keeps every exported variable, also one only the tests read.
    subprocess.run([str(zig), 'cc', '-target', 'thumb-freestanding-eabihf', '-mcpu=cortex_m7+vfp4d16',
                    '-mfloat-abi=hard', '-Os', '-g', '-ffunction-sections', '-fdata-sections', '-nostdlib',
                    '-fno-builtin', '-Wall', '-Werror', '-Wl,--no-undefined', '-Wl,--build-id=none',
                    '-Wl,--no-gc-sections', '-Wl,-e,sp_press', '-Wl,-T,' + str(folder / 'sg_subpad.ld'),
                    str(source), '-o', str(folder / 'sg_subpad.elf')], check=True, env=env)
    code, symbols = read_module((folder / 'sg_subpad.elf').read_bytes(), link_base, limit)
    missing = [n for n in EXPORTS if n not in symbols]
    if missing:
        raise ValueError(f'module exports missing: {missing}')
    for name in ENTRIES:
        if not symbols[name] & 1:
            raise ValueError(f'{name} is not a Thumb function symbol')
    return code, {n: symbols[n] for n in EXPORTS}, sha(source.read_bytes())


def build(inp: Path, out: Path, zig: Path, base: int, build_dir: Path = None):
    img = bytearray(inp.read_bytes())
    app0 = inp.with_name('SP404MKII_APP0.bin')
    if sha(app0.read_bytes()) != APP0_SHA:
        raise ValueError('expected stock APP0 beside the input APP1')
    for name in ('SP404MKII_APP1.bin', 'SP404MKII_APP0.bin', 'manifest.json'):
        if (out / name).exists():
            raise ValueError(f'refusing to overwrite {out / name}')
    if base & 0xFFF or base < GAP[0] or base + SLOT > GAP[1]:
        raise ValueError(f'the slot must be 4 KB aligned inside {GAP[0]:#x}..{GAP[1]:#x}')
    for what, lo, hi in KNOWN_SLOTS:
        if max(lo, base) < min(hi, base + SLOT):
            raise ValueError(f'the slot {base:#x}..{base + SLOT:#x} overlaps {what} ({lo:#x}..{hi:#x})')
    rows = scatter(img)
    rt = Runtime(img)
    for start, end, digest, what in GUARDS:
        if sha(rt.read(start, end - start)) != digest:
            raise ValueError(f'{start:#x}..{end:#x} differs from what the module relies on ({what})')
    for addr, old, entry, what in VTABLE:
        if struct.unpack('<I', rt.read(addr, 4))[0] != old:
            raise ValueError(f'{addr:#x}: expected {old:#x} ({what})')
    for load, dst, n, fn in rows:
        if max(dst, base) < min(dst + n, base + SLOT):
            raise ValueError(f'row {dst:#x}+{n:#x} overlaps the slot {base:#x}..{base + SLOT:#x}')
    hits = refs_into(bytes(img), base, base + SLOT)
    if hits:
        raise ValueError(f'input refers to the slot: {hits[:4]}')

    folder = build_dir or out / 'build'
    module, symbols, source_sha = compile_module(folder, zig, base, base + SLOT)
    if len(module) > SLOT:
        raise ValueError(f'module ({len(module)} bytes) exceeds the slot')

    patches = []
    for addr, old, entry, what in VTABLE:
        off = file_offset(img, addr, 4)
        new = struct.pack('<I', symbols[entry])
        img[off:off + 4] = new
        patches.append(dict(address=addr, size=4, original_hex=struct.pack('<I', old).hex(), replacement_hex=new.hex(),
                            what=what, entry=entry))
    file_at = (len(img) + 15) & ~15
    img += bytes(file_at - len(img)) + module
    table = (len(img) + 15) & ~15
    img += bytes(table - len(img))
    for row in rows + [[FLASH + file_at, base, len(module), COPY]]:
        img += struct.pack('<4I', *row)
    struct.pack_into('<2I', img, 0x80, table - 0x80, len(img) - 0x80)
    after = Runtime(img)
    if after.read(base, len(module)) != module:
        raise ValueError('the new image does not reproduce the module')
    for p in patches:
        if after.read(p['address'], p['size']).hex() != p['replacement_hex']:
            raise ValueError(f'the new image does not hold the patch at {p["address"]:#x}')

    out.mkdir(parents=True, exist_ok=True)
    (out / 'SP404MKII_APP1.bin').write_bytes(img)
    shutil.copy2(app0, out / 'SP404MKII_APP0.bin')
    parent_manifest = inp.with_name('manifest.json')
    manifest = dict(
        revision=REVISION, status='hardware-unverified', published=False,
        description='SUB PAD on the Sound Generator page plays the last pad played there (pads 1-16 without SHIFT), '
                    'at SUB PAD\'s velocity, through the page\'s own pad press, in melodic and drum mode; its release '
                    'lets that pad go. Before any pad it does nothing; v9.46 stopped the voices or toggled the tone',
        parent_app1=str(inp), parent_sha256=sha(inp.read_bytes()),
        parent_revision=json.loads(parent_manifest.read_text(encoding='utf-8')).get('revision')
        if parent_manifest.exists() else None,
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        slot=[base, base + SLOT], known_slots=[dict(what=n, start=lo, end=hi) for n, lo, hi in KNOWN_SLOTS],
        blob_base=base, blob_file_offset=file_at, blob_size=len(module), blob_sha256=sha(module),
        source='synth/sg_subpad.c', source_sha256=source_sha, compiler='zig 0.13.0 cc -Os', entries=symbols,
        patches=patches, guards=[dict(start=s, end=e, sha256=d, establishes=w) for s, e, d, w in GUARDS],
        tool='synth/build_sg_subpad.py')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    sums = ''.join(f'{sha((out / n).read_bytes())}  {n}\n' for n in ('SP404MKII_APP0.bin', 'SP404MKII_APP1.bin',
                                                                       'manifest.json'))
    (out / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8', newline='\n')
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('app1', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--zig', type=Path, required=True)
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0x83FD4000)
    ap.add_argument('--build-dir', type=Path)
    a = ap.parse_args()
    m = build(a.app1.resolve(), a.out.resolve(), a.zig.resolve(), a.base, a.build_dir.resolve() if a.build_dir else None)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size', 'blob_base', 'blob_size')}, indent=1))


if __name__ == '__main__':
    main()
