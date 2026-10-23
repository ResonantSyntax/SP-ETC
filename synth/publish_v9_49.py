"""Generate the guarded browser overlay for Sound Generator + Kits v9.49 (combined-test9).

v9.49 is v9.48 (combined-test8) with FX deep edit test8: the Super Filter's six hidden settings left out (a user
reported CTRL 2 on them spiked the volume), as the Compressor's MODE is since v9.48. Only that module differs
from v9.47, which was played on the unit; hardware_verified stays False until v9.49 itself is.

v9.49 is built in two steps. build_combined.py gives the combined build: every feature branch's module, byte for
byte its own test build's, on bounce-3-test9's parent (resample-startfix-3: the published v9.46's kit stage
plus the RESAMPLE start fix v3). build_fast_boot.py then skips the boot animation, and build_kit_footer.py blanks the drum kit
screen's "SHIFT: PAGE": that is combined-test9. The overlay turns the DOOM OS base into combined-test9. Before writing kits-data.js, this script checks:
- the candidate's hash and its three manifests;
- the chain back to v9.46's kit stage;
- every module's source against this tree.

usage: python synth/publish_v9_49.py /path/to/stock/SP404MKII_APP1.bin \
           --combined dev_combined9/combined-test9-base --candidate release/combined-test9
"""
import argparse
import base64
import json
from pathlib import Path

import build

RELEASE, REVISION, LABEL = 'v9.49', 'combined-test9', '5.52+kits-v9.49'
EXPECTED_SHA, EXPECTED_SIZE = '8f285b018ed7c540fed81f0b39128331edc6039900eed95e1a4ce8e762644750', 3152144
FASTBOOT_SHA = 'c45a4ca97c24a94e3aa387ef3d1d925bb428c3bc37d8b6bc68825324e3652a60'
COMBINED_SHA = '484b4d3a7938e5ed899abd17870af40883167f091cfa9d795142ae910fbd9184'
PARENT_SHA = '7d13c1e26d222cea7cada8b6b8ac986b432bf1b32508b5f39ac9c6c117ea61cc'      # resample-startfix-3
KIT_STAGE_SHA = '88384c3c9760559e721c1a14973ef3a2ced6abf016572b0a73c5dfb0cef492ba'   # v9.46-test3, as in v9.46
STEPS = ['bounce', 'fx-deep-edit', 'pad-env-1', 'pad-env-2', 'kits-save', 'note-repeat', 'chroma', 'sg-subpad']
KITS = ['TR808', 'DR110', 'KPR77', 'UDS', 'FM', 'TR909', 'TR606', 'SDS-V', 'MP-7', 'CR78', 'CR8K', 'TR707', 'TR727']
FEATURES = ['bounce in place', 'pad envelopes', 'note repeat', 'chromatic scales', 'kit edits saved',
            'Sound Generator settings saved', 'an arpeggiator for each mode', 'FX deep edit', 'SUB PAD on the Sound '
            'Generator', 'fast boot', 'RESAMPLE start fix v3']


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('stock', type=Path)
    p.add_argument('--combined', type=Path, required=True, help='the combined build: APP1, manifest.json, steps/')
    p.add_argument('--candidate', type=Path, required=True, help='combined-test9: APP1 and manifest.json')
    a = p.parse_args()
    stock = a.stock.read_bytes()
    build.require_hash(stock, build.v2.STOCK_SHA256, 'stock APP1')
    build.require_hash(a.stock.with_name('SP404MKII_APP0.bin').read_bytes(), build.APP0_SHA, 'stock APP0')

    image = (a.candidate / 'SP404MKII_APP1.bin').read_bytes()
    build.require_hash(image, EXPECTED_SHA, 'v9.49 APP1')
    footer = json.loads((a.candidate / 'manifest.json').read_text(encoding='utf-8'))
    if (len(image) != EXPECTED_SIZE or footer['sha256'] != EXPECTED_SHA or footer['revision'] != REVISION or
            footer['parent_sha256'] != FASTBOOT_SHA or footer['tool'] != 'synth/build_kit_footer.py' or
            [x['address'] for x in footer['patches']] != [0x83FBAF36]):
        raise ValueError('unexpected kit footer stage metadata')
    fast = json.loads(Path(footer['parent_app1']).with_name('manifest.json').read_text(encoding='utf-8'))
    if (fast['sha256'] != FASTBOOT_SHA or fast['parent_sha256'] != COMBINED_SHA or
            fast['tool'] != 'synth/build_fast_boot.py' or [x['address'] for x in fast['patches']] != [0x8013DCAA]):
        raise ValueError('unexpected fast boot stage metadata')
    combined = json.loads((a.combined / 'manifest.json').read_text(encoding='utf-8'))
    build.require_hash((a.combined / 'SP404MKII_APP1.bin').read_bytes(), COMBINED_SHA, 'combined build APP1')
    if (combined['sha256'] != COMBINED_SHA or combined['parent_sha256'] != PARENT_SHA or
            combined['tool'] != 'synth/build_combined.py' or [s['feature'] for s in combined['steps']] != STEPS):
        raise ValueError('unexpected combined stage metadata')
    for i, step in enumerate(combined['steps'], 1):
        m = json.loads((a.combined / step['manifest']).read_text(encoding='utf-8'))
        if m['blob_sha256'] != step['blob_sha256'] or (i == 1 and m['parent_sha256'] != PARENT_SHA):
            raise ValueError(f'step {i} ({step["feature"]}): its manifest is not the combined one\'s')
        build.require_hash((build.REPO / m['source']).read_text(encoding='utf-8').encode(), m['source_sha256'],
                           m['source'])
    start_fix = json.loads((a.combined / 'steps' / '1-bounce.manifest.json').read_text(encoding='utf-8'))
    if start_fix['parent_revision'] != 'resample-startfix-3':
        raise ValueError('bounce is not on resample-startfix-3')
    parent_manifest = Path(combined['parent_app1']).with_name('manifest.json')
    if parent_manifest.exists():
        pm = json.loads(parent_manifest.read_text(encoding='utf-8'))
        if pm['sha256'] != PARENT_SHA or pm['parent_sha256'] != KIT_STAGE_SHA:
            raise ValueError('resample-startfix-3 is not on v9.46\'s kit stage')

    base, _ = build.build(stock)
    overlay = build.make_overlay(base, image, LABEL)
    metadata = dict(release=RELEASE, revision=REVISION, sha256=EXPECTED_SHA, size=EXPECTED_SIZE,
                    base_sha256=build.sha(base), combined_sha256=COMBINED_SHA, start_fix='resample-startfix-3',
                    kit_stage_sha256=KIT_STAGE_SHA, kits=KITS, kit_selector_range=[1, 13], synthesis_only=True,
                    features=FEATURES, hardware_verified=False)
    text = '// Generated by synth/publish_v9_49.py. Guarded overlay; no complete firmware.\n'
    text += 'window.DOOMOS_KITS = ' + json.dumps(metadata, sort_keys=True) + ';\n'
    text += 'window.DOOMOS_KITS_PATCH = ' + json.dumps(base64.b64encode(overlay).decode('ascii')) + ';\n'
    (build.REPO / 'kits-data.js').write_text(text, encoding='ascii', newline='\n')
    print('Verified v9.49 overlay:', build.sha(image), f'({len(overlay)} bytes)')


if __name__ == '__main__':
    main()
