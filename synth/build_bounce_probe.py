"""Bounce in place, stage 1: a measurement build that shows the effects-chip round trip L.

A stage after the RESAMPLE start fix (build_start_fix.py), applied the same way to the
final v9.46-test2 image. bounce_probe.c counts TX frames after the mixer renders each
block and RX frames after the recorder feed takes each block, both in the audio task, and
shows L = RX onset - TX onset in a popup for every sound that starts from silence while
the RESAMPLE page's recorder is in standby or recording. See BOUNCE_PROBE.md.

Three sites change, each checked against its exact instructions:
  0x0001d090  audio task, TX block: mov.w r1,#0x1000; mov r0,r5; bl mixer
              -> tx bridge: the same mixer call, then probe_tx, then back to 0x1d09a
  0x0001d0c2  audio task, RX block: mov.w r1,#0x800; bl feed; b loop
              -> rx bridge: the same feed call, then probe_rx, then the loop head
  0x8006b950  popup tick (UI task, every 1 ms): its first four instructions
              -> ui bridge: probe_ui, then those four instructions
The two audio bridges use no stack, so the mixer and the feed run at their stock depth.
Stock code the module reads or calls is checked byte for byte (GUARDS). The bridges and
the module (Zig 0.13.0, -Os) go in a new boot copy row in a 4 KB slot at 0x83FEE000, just
below the start fix's row at 0x83FEF000; the builder checks that no row overlaps the slot
and that nothing in the input refers to it.

usage: python synth/build_bounce_probe.py IN_APP1 OUT_DIR --zig ZIG [--base 0x83FEE000]
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

from build_arp import call, checked_asm, file_offset, jump, listing, load, read_module, scatter
from build_start_fix import refs_into

HERE = Path(__file__).resolve().parent
FLASH, COPY = 0x60080000, 0x600800E4
APP0_SHA = '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23'
REVISION = 'bounce-probe-1'
SLOT = 0x1000                       # reserved: [base, base + SLOT)
BRIDGES = {'tx': 0x00, 'rx': 0x40, 'ui': 0x80}
CODE_OFFSET = 0x100                 # the C module links after the bridges
PCM_BANK = 0x60376000               # build_arp_kit.py's flash planning boundary for kit PCM
EXPORTS = ('probe_tx', 'probe_rx', 'probe_ui', 'probe', 'probe_text', 'probe_rx_buffer')
MIXER, FEED, TX_BACK, LOOP, TICK_REST = 0x1C2D0, 0x1CA80, 0x1D09A, 0x1D05C, 0x8006B95C
SITES = {
    'tx': (0x1D090, 10, ['mov.w r1, #0x1000', 'mov r0, r5', 'bl #0x1c2d0'], 'jump'),
    'rx': (0x1D0C2, 10, ['mov.w r1, #0x800', 'bl #0x1ca80', 'b #0x1d05c'], 'jump'),
    'ui': (0x8006B950, 12, ['push {r4, r5, r6, lr}', 'movw r4, #0x22ac', 'movt r4, #0x8059', 'ldr r1, [r4, #8]'],
           'jump'),
}
# Stock 5.52 code the module and bridges rely on, unchanged in DOOM OS ED5E and the fork
# up to v9.46-test2: (start, end, SHA-256 of the runtime bytes, what it establishes).
GUARDS = [
    (0x1CF78, 0x1D0CC, 'f0c95148b5ac8c65cb13170f92197c3cffe4b51fdd832440934444ff10c18e00',
     'audio task: TX line 3 = 0x20006000 (eDMA TCD3 SADDR), RX = 0x20008000 (TCD4 DADDR); TX then RX per wake; '
     'r5 = mixer argument; loop head 0x1d05c; both patch sites'),
    (0x1C2D0, 0x1C766, 'eb32d85ff156e39759b8e74894176ebd7e8c80008a7a79b4abce14960fa28f82',
     'mixer: stem buffer 0x202ad3a0 cleared (0xe00 bytes); 32 voice slots of 0x58 at 0x202ae1a0'),
    (0x1C76A, 0x1CA80, '3954945dc197d01430f655855c12a1c57bbff2e499b8ac9845a67cc4c01354a3',
     'mixer: 64 frames x 14 stems clipped to 20 bits and written back; TX words 0-11 and 14-15'),
    (0x1CA80, 0x1CB84, '40fb002266bf5930ddddbda3b36b26c746acb40a304387c0c5b588d3cb8b1d97',
     'recorder feed: 64 frames of 32 bytes; the selected pair (words 1/0) copied to 0x202ad0a0'),
    (0x14B88, 0x14BAC, 'f1b47541558c7a5c0065167689b748f87ef717dfe9defa23ebd48ae25723929c',
     'renderer: a voice renders when its stream (+0x14268) is set and stream[1] != 0xff'),
    (0x80005870, 0x8000587C, 'fbc26416b4901ef29527923dc48e3d7926167b2873e14c7d9e7ec00bb5e7e3c5',
     'voice stub: slot word 0 = voice object, 0 = empty'),
    (0x8006B950, 0x8006B9E8, 'e4050b0e145b6f8b10f37b0d3b9fc6b35c40c7b82c52bd5ec585eb95408ec833',
     'popup tick: from 0x8006b95c it uses r0 = elapsed, r1 = timer [0x805922b4], r4 = 0x805922ac and its '
     'stack frame, nothing else of the caller; a timer running out closes the popup and clears a pending one'),
    (0x800D3FF0, 0x800D4026, '7399e6400e3ea2ddd99ad6a9f4de1469abffae638c380038c1d7aedbee61886b',
     'popup(text, ms): copies the text and arms the stock type-3 popup'),
    (0x8017F810, 0x8017F866, '351eafb4b12e9bc5a923e66354c9d1d779317a3afec2eab43a94d4fb1a097f7d',
     'REC_START: recorder 0x82e0e71c state byte +0x39 (1 standby -> 2 recording)'),
    (0x800D94D8, 0x800D94F2, '3b5fea56fc5c3714d850f372458cf0d1525dd50f3ee639a082ddde2c39df813b',
     'settings GetParam: ip = object, TBH on the id'),
    (0x800D9890, 0x800D9896, '829ef2a46807ace75d9747d1aa263221f8f089fbd8e28f9cab14f103280a2886',
     'settings param 0x36 = word +0x88 (0x82e011cc)'),
    (0x8012CEE2, 0x8012CEEE, '0d49d1e48cd07ba6565dd1cd557b19e9a67bb055020c1a354d296e8c82be930e',
     'RESAMPLE page enter sets param 0x36 = 1'),
]
TABLE_GUARDS = [(0x800D94F2 + 0x36 * 2, 463)]    # GetParam's TBH entry for 0x36 -> 0x800d9890


def sha(b):
    return hashlib.sha256(b).hexdigest()


def runtime(img, address, size):
    off = file_offset(img, address, size)
    return bytes(img[off:off + size])


def compile_module(folder: Path, zig: Path, link_base: int, limit: int):
    folder.mkdir(parents=True, exist_ok=True)
    if subprocess.check_output([str(zig), 'version'], text=True).strip() != '0.13.0':
        raise ValueError('needs Zig 0.13.0')
    keep = ' '.join(f'KEEP(*(.text.{n}))' for n in EXPORTS[:3])
    (folder / 'probe.ld').write_text(f'''ENTRY(probe_tx)
SECTIONS {{
 . = {link_base:#x};
 .text : {{ {keep} *(.text*) }}
 .rodata : ALIGN(16) {{ *(.rodata*) }}
 .data : ALIGN(16) {{ *(.data*) }}
 .bss : ALIGN(16) {{ *(.bss*) *(COMMON) }}
 /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.note*) }}
}}
''', encoding='ascii', newline='\n')
    source = folder / 'bounce_probe.c'               # compile LF-normalized source
    source.write_bytes((HERE / 'bounce_probe.c').read_bytes().replace(b'\r\n', b'\n'))
    cache = folder / 'cache'
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache))
    # -g only keeps the symbol table: Zig's -Os (ReleaseSmall) strips it otherwise. Same code.
    subprocess.run([str(zig), 'cc', '-target', 'thumb-freestanding-eabihf', '-mcpu=cortex_m7+vfp4d16',
                    '-mfloat-abi=hard', '-Os', '-g', '-ffunction-sections', '-fdata-sections', '-nostdlib',
                    '-Wl,--no-undefined', '-Wl,--build-id=none', '-Wl,-e,probe_tx',
                    '-Wl,-T,' + str(folder / 'probe.ld'), str(source), '-o', str(folder / 'probe.elf')],
                   check=True, env=env)
    code, symbols = read_module((folder / 'probe.elf').read_bytes(), link_base, limit)
    missing = [n for n in EXPORTS if n not in symbols]
    if missing:
        raise ValueError(f'module exports missing: {missing}')
    return code, {n: symbols[n] for n in EXPORTS}, sha(source.read_bytes())


def bridge_sources(sym):
    """Each bridge re-creates exactly what its site did, plus one call into the module."""
    keep = load('r12', sym['probe_rx_buffer'])
    return {
        # From 0x1d090 (bx): the mixer call with its arguments, probe_tx, then 0x1d09a.
        'tx': 'mov r0, r5\nmov.w r1, #0x1000\n' + call(MIXER) + call(sym['probe_tx']) + jump(TX_BACK),
        # From 0x1d0c2 (bx), r0 = RX buffer: keep it for probe_rx, the feed call, probe_rx, the
        # loop's branch.
        'rx': keep + 'str r0, [r12]\nmov.w r1, #0x800\n' + call(FEED) + call(sym['probe_rx']) + jump(LOOP),
        # From 0x8006b950 (bx), r0 = elapsed ms: the displaced push, probe_ui(elapsed) with r0
        # kept, the displaced loads, then the tick at 0x8006b95c.
        'ui': ('push {r4, r5, r6, lr}\npush {r0, r1}\n' + call(sym['probe_ui']) + 'pop {r0, r1}\n'
               'movw r4, #0x22ac\nmovt r4, #0x8059\nldr r1, [r4, #8]\n' + jump(TICK_REST)),
    }


def thumb_branch_targets(code, at):
    """Every direct branch target decodable at any halfword (a superset of the real ones)."""
    out = []
    n = len(code) - 1
    for i in range(0, n, 2):
        h1 = code[i] | code[i + 1] << 8
        pc = at + i + 4
        if (h1 & 0xF000) == 0xD000 and (h1 & 0x0F00) < 0x0E00:          # B<c> T1
            out.append((at + i, pc + ((h1 & 0xFF) ^ 0x80) * 2 - 0x100))
        elif (h1 & 0xF800) == 0xE000:                                     # B T2
            out.append((at + i, pc + ((h1 & 0x7FF) ^ 0x400) * 2 - 0x800))
        elif (h1 & 0xF500) == 0xB100:                                     # CBZ/CBNZ
            out.append((at + i, pc + (((h1 >> 9) & 1) << 6 | ((h1 >> 3) & 0x1F) << 1)))
        elif (h1 & 0xF800) == 0xF000 and i + 3 < len(code):
            h2 = code[i + 2] | code[i + 3] << 8
            s = (h1 >> 10) & 1
            j1, j2 = (h2 >> 13) & 1, (h2 >> 11) & 1
            if (h2 & 0xD000) in (0x9000, 0xD000):                         # B.W T4 / BL
                i1, i2 = 1 - (j1 ^ s), 1 - (j2 ^ s)
                off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
                out.append((at + i, pc + off - (s << 25)))
            elif (h2 & 0xD000) == 0x8000 and ((h1 >> 6) & 0xF) < 0xE:     # B<c>.W T3
                off = (s << 20) | (j2 << 19) | (j1 << 18) | ((h1 & 0x3F) << 12) | ((h2 & 0x7FF) << 1)
                out.append((at + i, pc + off - (s << 21)))
    return out


def check_no_branch_into(img, spans):
    """No direct branch in any ITCM or SDRAM copy row lands inside a patched span (its first
    byte excepted). DOOM's XIP flash code is out of branch range of every span."""
    hits, scanned = [], 0
    for load, dst, n, fn in scatter(img):
        if fn != COPY or not load or 0x20000 <= dst < 0x80000000:
            continue
        code = img[load - FLASH:load - FLASH + n]
        scanned += n
        for site, target in thumb_branch_targets(code, dst):
            for start, size in spans:
                if start < target < start + size and not start <= site < start + size:
                    hits.append((site, target))
    if hits:
        raise ValueError('branches into a patched span: ' + ', '.join(f'{a:#x}->{t:#x}' for a, t in hits[:8]))
    return scanned


def build(inp: Path, out: Path, zig: Path, base: int):
    img = bytearray(inp.read_bytes())
    app0 = inp.with_name('SP404MKII_APP0.bin')
    if sha(app0.read_bytes()) != APP0_SHA:
        raise ValueError('expected stock APP0 beside the input APP1')
    for name in ('SP404MKII_APP1.bin', 'SP404MKII_APP0.bin', 'manifest.json'):
        if (out / name).exists():
            raise ValueError(f'refusing to overwrite {out / name}')
    if base & 0xFFF or base < 0x83F7A424 or base + SLOT > 0x83FF0000:
        raise ValueError('the slot must be a 4 KB page in the unused SDRAM gap below 0x83FF0000')
    rows = scatter(img)
    for start, end, digest, what in GUARDS:
        if sha(runtime(img, start, end - start)) != digest:
            raise ValueError(f'{start:#x}..{end:#x} differs from stock 5.52 ({what})')
    for address, value in TABLE_GUARDS:
        if struct.unpack('<H', runtime(img, address, 2))[0] != value:
            raise ValueError(f'jump-table entry at {address:#x} differs from stock 5.52')
    for key, (site, size, expect, _) in SITES.items():
        found = listing(runtime(img, site, size), site)
        if found != expect:
            raise ValueError(f'{site:#x}: expected {expect}, found {found}')
    scanned = check_no_branch_into(bytes(img), [(s, n) for s, n, _, _ in SITES.values()])
    for load, dst, n, fn in rows:
        if max(dst, base) < min(dst + n, base + SLOT):
            raise ValueError(f'row {dst:#x}+{n:#x} overlaps the slot {base:#x}..{base + SLOT:#x}')
    hits = refs_into(bytes(img), base, base + SLOT)
    if hits:
        raise ValueError(f'input refers to the slot: {hits[:4]}')

    module, symbols, source_sha = compile_module(out / 'build', zig, base + CODE_OFFSET, base + SLOT)
    blob = bytearray(CODE_OFFSET)
    entries = {}
    sources = bridge_sources(symbols)
    for key, offset in BRIDGES.items():
        code = checked_asm(sources[key], base + offset)
        nxt = min([o for o in BRIDGES.values() if o > offset] + [CODE_OFFSET])
        if offset + len(code) > nxt:
            raise ValueError(f'bridge {key} too long ({len(code)} bytes)')
        blob[offset:offset + len(code)] = code
        entries[f'{key}_bridge'] = base + offset
    blob += module
    if len(blob) > SLOT:
        raise ValueError(f'blob ({len(blob)} bytes) exceeds the slot')
    entries.update(symbols)

    patches = []
    for key, (site, size, expect, kind) in SITES.items():
        target = base + BRIDGES[key]
        text = (call if kind == 'call' else jump)(target)
        new = checked_asm(text + 'nop\n' * ((size - 10) // 2), site)
        want = [f'movw ip, #{(target | 1) & 0xFFFF:#x}', f'movt ip, #{target >> 16:#x}',
                'blx ip' if kind == 'call' else 'bx ip'] + ['nop'] * ((size - 10) // 2)
        if len(new) != size or listing(new, site) != want:
            raise ValueError(f'{site:#x}: bad replacement {listing(new, site)}')
        off = file_offset(img, site, size)
        patches.append(dict(address=site, size=size, original=expect, original_hex=bytes(img[off:off + size]).hex(),
                            replacement_hex=new.hex(), target=target))
        img[off:off + size] = new

    file_at = (len(img) + 15) & ~15
    img += bytes(file_at - len(img)) + blob
    table = (len(img) + 15) & ~15
    img += bytes(table - len(img))
    for row in rows + [[FLASH + file_at, base, len(blob), COPY]]:
        img += struct.pack('<4I', *row)
    struct.pack_into('<2I', img, 0x80, table - 0x80, len(img) - 0x80)
    if FLASH + len(img) > PCM_BANK:
        raise ValueError('APP1 would reach the kit PCM planning boundary')
    if runtime(img, base, len(blob)) != bytes(blob):
        raise ValueError('the new row does not reproduce the blob')

    out.mkdir(parents=True, exist_ok=True)
    (out / 'SP404MKII_APP1.bin').write_bytes(img)
    shutil.copy2(app0, out / 'SP404MKII_APP0.bin')
    parent_manifest = inp.with_name('manifest.json')
    manifest = dict(
        revision=REVISION, status='hardware-unverified', published=False,
        description='measurement build: shows the effects-chip round trip L of every sound that starts from silence '
                    'while the RESAMPLE recorder is in standby or recording',
        parent_app1=str(inp), parent_sha256=sha(inp.read_bytes()),
        parent_revision=json.loads(parent_manifest.read_text(encoding='utf-8')).get('revision')
        if parent_manifest.exists() else None,
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        slot=[base, base + SLOT], blob_base=base, blob_file_offset=file_at, blob_size=len(blob), blob_sha256=sha(blob),
        source='synth/bounce_probe.c', source_sha256=source_sha, compiler='zig 0.13.0 cc -Os',
        entries=entries, patches=patches,
        branch_scan=dict(bytes=scanned, result='no direct branch into a patched span'),
        guards=[dict(start=s, end=e, sha256=d, establishes=w) for s, e, d, w in GUARDS],
        table_guards=[dict(address=a, value=v) for a, v in TABLE_GUARDS],
        thresholds=dict(tx='|stem| > 2048 (20-bit, about -48 dBFS)', rx='|sample| > 128 (16-bit, about -48 dBFS)',
                        tx_quiet_frames=1024, rx_quiet_frames=256, words23_wait_frames=4800, timeout_frames=48000),
        popup='L=<L> #<run> W<words 2/3 L>\\n<lo>-<hi> P<eDMA phase> D<RX-TX blocks> V<voice lead>; '
              'L=?? #<run>\\nRX not quiet; L=-- #<run>\\nno return',
        scope='measures only while settings param 0x36 == 1 (RESAMPLE page) and the recorder is in standby or '
              'recording; changes no audio, take, setting or file',
        tool='synth/build_bounce_probe.py')
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
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0x83FEE000)
    a = ap.parse_args()
    m = build(a.app1.resolve(), a.out.resolve(), a.zig.resolve(), a.base)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size', 'blob_base', 'blob_size')}, indent=1))


if __name__ == '__main__':
    main()
