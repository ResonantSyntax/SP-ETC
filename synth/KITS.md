# Synthesized machine kits v9.43 (test candidate)

This branch carries the v9.43-test1 kit candidate: thirteen kits, every voice
re-measured against references. It has emulator verification only and has not
been played on hardware yet. The published patcher option is still the v9.42
kits until this candidate passes a hardware test and `publish_kits.py` is run.

Select **Sound Generator + Kits** in the patcher. This separate option
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
- KIT stays between TR808 and TR727. Turning beyond either end keeps that kit.
  OFF is an internal melodic state, not a selectable drum-menu choice.

| Main display page | CTRL1 | CTRL2 | CTRL3 |
| --- | --- | --- | --- |
| First | Tune ±12 semitones | Decay 0–100% | Tone 0–100% |
| After tapping SHIFT | Sweep 0–100% | Noise 0–100% | Attack 0–100% |

Kit VALUE has ARP, RATE, A.OCT, HOLD, BPM, KIT, PAD, SOUND and LEVEL (0–127).
The six main-display parameters do not repeat there. Melodic VALUE keeps its
original items and arpeggiator controls, with no drum items. Melodic SHIFT
keeps the existing Pad Length/Balance page. Edits are RAM-only.

**50 is the authentic setting** for Decay, Tone, Sweep, Noise and Attack on
every pad: a pad at 50 plays the modelled machine voice unchanged. TONE is the
808's own knob on its kick (tone), snare (snappy) and cymbal (tone), and a
broadband tilt everywhere else. SWEEP below 50 lowers or removes a voice's own
pitch envelope (or makes the pitch rise into the note); above 50 deepens it.
NOISE above 50 mixes noise into metallic sources; below 50 thins noisy voices.

## Kits

| # | Kit | Voices | Built from |
| --- | --- | --- | --- |
| 1 | TR808 | 16 | circuit models; ACB captures (BD, SD, CY) and the Fischer 808 grid |
| 2 | DR110 | 6 + variants | procedural; 4 recordings per voice |
| 3 | KPR77 | 8 + variants | procedural; 2–4 recordings per voice |
| 4 | UDS | 8 + variants | Lel' UDS (Soviet analog drum synthesizer); 12 recordings |
| 5 | FM | 8 + tuned variants | original DX/TX-style two-operator voices |
| 6 | TR909 | 11 + variants | analog models fitted to ACB captures of every voice; synthetic hat/crash/ride |
| 7 | TR606 | 7 + variants | circuit models; 4–6 recordings per voice |
| 8 | SDS-V | 6 + variants | Simmons SDS-V; 12–20 recordings per voice |
| 9 | MP-7 | 15 + 1 | Korg Mini Pops 7; one recording per voice |
| 10 | CR78 | 14 + 2 | 4–14 recordings per voice, several units |
| 11 | CR8K | 14 + 2 | 3–12 recordings per voice |
| 12 | TR707 | 15 + 1 | synthesized; TR-707 plug-in captures used only as targets |
| 13 | TR727 | 15 + 1 | synthesized; TR-727 plug-in captures used only as targets |

Each kit has sixteen sounding pads. Machine kits restrict SOUND selection to
their own voice inventory. Pads beyond a machine's own voices hold generated
tune/decay/tone/attack variants of those voices. All drums are synthesized on
the SP: no recordings, samples, plugin binaries or recovered Roland ACB code
are used. The 707 and 727 were sample-based machines; their kits are synthesis
(tones, partials, filtered noise and gates) fitted to the captures. These are
machine-inspired models, not claims of exact circuit or ACB fidelity.

## How the voices were fitted

For every voice the comparison covered pitch at 5/20/80 ms, decay to −20 and
−40 dB, a 4 ms envelope and 1/3-octave balance. Tonal drums were fitted by least
squares on the recorded waveform where the recordings agree in phase (606 kick,
CR-8000 kick, snare and congas). Notable corrections in this pass:

- SWEEP 50 no longer adds a pitch blip; cowbells and claves hold steady.
- 909 kick bends 265 Hz to 50 Hz with a 17 ms time constant (ACB 211/118/54 Hz
  at 5/20/80 ms); the 909 snare body falls 232 to 167 Hz.
- 808 toms, congas, rim, clave, clap, maracas, cowbell, hats and cymbal match
  the Fischer grid and ACB decays and spectra.
- 606 kick: a 163 Hz trigger blip over a 56 Hz ring, fitted to the averaged
  recordings; cymbal has its fast 20 dB drop over a long 6–8 kHz tail.
- CR-78: hold-then-release envelopes (hats, snare wires, cowbell, metal beat,
  bongos), 8.4 kHz hat band, 4.7 kHz tambourine with jingle modulation, guiro
  scrapes every 13.3 ms at 5.9 kHz.
- CR-8000: two-mode kick (58.5 and 126 Hz), toms that carry each other's mode,
  congas at 196/304/739 Hz, hats and cymbal flat from 5 to 16 kHz.
- DR-110 kick bends from about 335 Hz in 3 ms; its clap has three bursts 12 ms
  apart before the tail. KPR-77 toms sit at 130 and 199 Hz.
- SDS-V drums bend slowly (pitch time constant 0.2–0.55 s), as the module does.
- Level trims follow the v9.36 policy (attack/body proxy 0.32 at LEVEL 110,
  neutral transient cap 1.6) for all 143 sounds.

## Output and CPU

The synth mix and export retain v9.39's nominal +6.02 dB gain and summed-output
soft knee (starts at 24576, approaches 32000 on the signed 16-bit scale). Existing
live bus audio is preserved. Later effects/mixes can still overload.

ARM instruction counts per voice and 64-frame block (Unicorn, exact module):
median 19k, worst steady 64k (TR-606 cymbal), worst onset block 125k (a TR-606
cymbal whose shared source cache rebuilds). v9.42 measured 31k, 71k and 215k.

## Reproduce

Use Python 3.12, the pinned dependencies and Zig 0.13.0. Supply your own official
5.52 firmware pair. No complete Roland firmware is distributed.

```sh
python -m pip install -r synth/requirements.txt
python synth/build_v9.py /path/to/stock/SP404MKII_APP1.bin --zig /path/to/zig --out out/v9.5-parent
python synth/build_scales.py out/v9.5-parent/SP404MKII_APP1.bin --zig /path/to/zig --out out/v9.6 --fixes
python synth/build_kits.py out/v9.6/SP404MKII_APP1.bin --zig /path/to/zig --out out/kits-v943
```

The kit builder requires only the files in this repository. Patch sites retain
exact-byte guards. Zero-filled module sections are packed into guarded scatter
rows and reconstructed to verify the complete runtime image before writing APP1.
Module: 147,544 bytes at run time (limit 319,488), 113,296 stored.

## Checks (v9.43-test1, emulator)

- 208 factory pad renders (13 kits × 16) match host/ARM sample for sample for
  3000 samples each, plus 108 control endpoint cases (TUNE, DECAY, TONE, SWEEP,
  NOISE, ATTACK at both ends on nine voices from five engines).
- Machine inventories, held-pad editing, menu ranges, the KIT selector ends and
  seven hat-choke cases pass.
- 208 compiled capture cases check released-pad selection and velocity, with
  melodic capture delegated to the original path.
- Every sound renders finite, without DC offset or audible cut-off clicks.

Hardware timing, output and CPU headroom are not yet verified on a device.

To replay host/ARM audio checks, build the portable engine as a host library:

```sh
zig cc -O2 -ffp-contract=off -fno-fast-math -shared -DKIT_HOST synth/kits/kit_engine.c -o out/kit_engine_host.dll
python synth/test_kits.py out/kits-v943 out/kit_engine_host.dll
python synth/test_kit_capture.py out/kits-v943
```

Use `.so` for a supported Linux host toolchain; the build was verified on Windows.
