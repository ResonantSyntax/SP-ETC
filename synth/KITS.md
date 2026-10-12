# Synthesized machine kits v9.42

Select **Sound Generator + Kits v9.42** in the patcher. This separate option
includes the melodic generator and shared arpeggiator. Both browser choices
start unchecked; choosing one deselects the other. Firmware processing stays
local in your browser. The patcher produces APP1 only; APP0 remains stock.

## Open and play

- SHIFT + PATTERN EDIT opens Kits and restores the last selected machine.
- SHIFT + RECORD SETTING opens the melodic Sound Generator.
- Both shortcut release orders work. Tap/release SHIFT to switch parameter
  pages; you can audition pads after releasing it.
- REC uses the last struck pad after release; you do not need to hold it.
  Capture freezes its current controls and velocity, onset phase and noise seed.
  A retriggered 808 kick retains its initial capacitor state when controls match
  that hit; if controls changed afterward, REC renders the current recipe.
- Strike a pad to select it. Hold a pad and turn VALUE outside menu edit mode
  to choose a sound from that machine's inventory.
- KIT stays between TR808 and CR8K. Turning beyond either end keeps that kit.
  OFF is an internal melodic state, not a selectable drum-menu choice.

| Main display page | CTRL1 | CTRL2 | CTRL3 |
| --- | --- | --- | --- |
| First | Tune ±12 semitones | Decay 0–100% | Tone 0–100% |
| After tapping SHIFT | Sweep 0–100% | Noise 0–100% | Attack 0–100% |

Kit VALUE has ARP, RATE, A.OCT, HOLD, BPM, KIT, PAD, SOUND and LEVEL (0–127).
The six main-display parameters do not repeat there. Melodic VALUE keeps its
original items and arpeggiator controls, with no drum items. Melodic SHIFT
keeps the existing Pad Length/Balance page. Edits are RAM-only.

## Sounds and limits

Eleven kits: TR808, DR110, KPR77, Digi, FM, TR909, TR606, SDS-V, SY-1, CR78 and
CR8K. Each has sixteen sounding pads. Machine kits restrict SOUND selection
to their own voice inventory. A `+` beside a pad identifies an alternate
recipe of an existing voice, not an extra authentic machine instrument.
Digi and FM are original electronic kits. All drums are synthesized on the SP;
no recordings, samples, plugin binaries or recovered Roland ACB code are used.
The TR909 metal instruments are synthetic substitutes for sampled originals.
These are machine-inspired models, not claims of exact circuit or ACB fidelity.

The synth mix and export retain v9.39's nominal +6.02 dB gain and summed-output
soft knee (starts at 24576, approaches 32000 on the signed 16-bit scale). Existing
live bus audio is preserved. Later effects/mixes can still overload.

The owner tested preceding builds and supplied listening/UI feedback. This
exact v9.42 candidate has emulator verification; hardware timing, output and
CPU headroom remain unverified. This PR does not flash a device.

## Reproduce

Use Python 3.12, the pinned dependencies and Zig 0.13.0. Supply your own official
5.52 firmware pair. No complete Roland firmware is distributed in this PR.

```sh
python -m pip install -r synth/requirements.txt
python synth/build_v9.py /path/to/stock/SP404MKII_APP1.bin --zig /path/to/zig --out out/v9.5-parent
python synth/build_scales.py out/v9.5-parent/SP404MKII_APP1.bin --zig /path/to/zig --out out/v9.6 --fixes
python synth/build_kits.py out/v9.6/SP404MKII_APP1.bin --zig /path/to/zig --out out/kits-v942
python synth/publish_kits.py /path/to/stock/SP404MKII_APP1.bin --candidate out/kits-v942/SP404MKII_APP1.bin
node synth/test_browser.cjs /path/to/stock/SP404MKII_APP1.bin
```

The publisher accepts only the tested candidate and matching runtime sources.
The kit builder requires only the files in this repository; it has no dependency
on the private research tree. Patch sites retain exact-byte guards. Zero-filled
module sections are packed into guarded scatter rows and reconstructed to
verify the complete runtime image before writing APP1.

APP1: 3073792 bytes.
SHA256: `11e8faa1dc0ef378fbb63af842a8d6991f28608803f120bd3affa98e5f574fa5`.

## Checks

- Standalone source rebuild and browser download match that exact digest.
- 176 factory pad renders match host/ARM for 3000 samples each, plus 84 control
  endpoint cases; machine inventories, held-pad editing, menu ranges and six
  hat-choke cases pass. The checker also tests nine compiled KIT boundary cases.
- Three complete-image physical-panel REC checks on v9.42 pass after releasing
  pad 11. Sixteen prior v9.41 physical-panel emulator checks traverse all
  eleven kits, test both ends and verify returning through the melodic shortcut.
- Prior v9.40 checks cover 44 UI cases, all 176 panel routes, ten lifecycle/ARP
  cases and output-bus regressions. These belong to the preceding candidate.
- All 176 assignments and 176 edited/repeated cases match live/REC source
  bit for bit for 512 frames each. Six native cowbell file-export cases compare
  9600 source frames, with isolated PCM matching in five cases; an overlapping
  kick remains outside the single-pad export.
- 176 compiled capture cases check released-pad selection and velocity, with
  melodic capture delegated to the original path.
- Browser tests cover the new/legacy/base choices, reset, exact downloads,
  unsupported input and corrupt-overlay rejection.

To replay host/ARM audio checks, build the portable engine as a host library:

```sh
zig cc -O2 -ffp-contract=off -fno-fast-math -shared -DKIT_HOST synth/kits/kit_engine.c -o out/kit_engine_host.dll
python synth/test_kits.py out/kits-v942 out/kit_engine_host.dll
python synth/test_kit_capture.py out/kits-v942
```

Use `.so` for a supported Linux host toolchain; the published build was verified
on Windows. [`kits/validation.json`](kits/validation.json) records the validated
candidate and coverage. Real-time and fidelity measurements remain separate.
