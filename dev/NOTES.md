# Working notes (ResonantSyntax fork)

My notes for developing new features on this fork. Everything here lives in
`dev/` so the upstream files (tracelistener/SP-ETC) stay untouched and easy to
merge.

## Firmware: never in git

The Roland 5.52 files are copyrighted and this repo is public. `.gitignore`
blocks `*.bin` and `firmware/`. Keep them locally in `firmware/` (ignored), or
upload them into a chat session.

| File | SHA-256 | Size |
|---|---|---|
| stock `SP404MKII_APP1.bin` 5.52 | `4a3d67711e14dcc97d50249a4eee7dd6df0251a2f37757cbbe2556c233730d80` | 2,652,672 |
| stock `SP404MKII_APP0.bin` | `3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23` | 2,359,296 |
| DOOM OS ED5E APP1 | `16c0b62a1a7f385be00d1cf4222180788be1ae29bb2f280a46835a56a055afa7` | 2,830,128 |
| v9.52 APP1 (current release) | `e7b754211f58ed0a46a5dc517ba777118943460998d11479c648726df117be79` | 3,157,104 |

Check a file: `shasum -a 256 FILE` (macOS), `sha256sum FILE` (Linux),
`Get-FileHash FILE` (PowerShell).

## Local setup

Needs Python 3.12+ and Node 18+. Zig 0.13.0 exactly (the builders check the version).

```sh
python3 -m venv .venv
. .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r synth/requirements.txt
pip install ziglang==0.13.0       # Zig 0.13.0 as a Python package; or download it from ziglang.org
python -c "import ziglang, os; print(os.path.join(os.path.dirname(ziglang.__file__), 'zig'))"   # the --zig path
```

Then put the stock firmware in `firmware/` and check that everything works:

```sh
node synth/test_browser.cjs firmware/SP404MKII_APP1.bin          # the web patcher gives exact v9.52
node dev/make_v9_52.cjs firmware/SP404MKII_APP1.bin out/v9.52    # write the v9.52 image (parent for new features)
```

## How a feature is built (short version)

1. Find the stock function/variable addresses (disassembly with capstone).
2. Write the feature in C (`synth/<feature>.c`). It calls stock code by address.
3. A `synth/build_<feature>.py` compiles it with Zig for the SP's Cortex-M7
   (Thumb), adds a boot copy row that loads it into a free RAM slot, and
   rewrites a few hook words/instructions so stock code calls into it.
   Guards check the exact stock bytes first; it refuses anything unexpected.
4. `synth/test_<feature>.py` runs the real firmware code in the Unicorn ARM
   emulator and checks behaviour.
5. A `publish_*.py` makes the browser overlay (`kits-data.js`) for the web patcher.
6. Hardware test on the SP (only I can do this). Keep a stock 5.52 update on hand to roll back.

Free RAM slots used by fork modules are listed in `KNOWN_SLOTS` in
`synth/build_sg_subpad.py`. A new module needs its own slot.

## Log

### 2026-10-27
- Explored the repo: patcher structure, the arp (`synth/arp_v9_9_3.c`, ARP.md) as the reference feature.
- The stock 5.52 APP1/APP0 were uploaded to `main` (commit `4143917`). They match the stock hashes above.
  **Still to do:** remove that commit from `main`. The session's safety settings blocked the force-push;
  needs either a force-push from my machine or permission in the session. Command (run from a clone):
  `git push --force-with-lease=main:4143917b1958673b43aa578bd336e2cf8fe21bb1 origin d8190f5:refs/heads/main`
  (resets `main` to the v9.52 commit, the one before the upload; nothing else is lost).
- Set up the cloud session: Python deps, Zig 0.13.0 (via the `ziglang` PyPI package; ziglang.org is blocked there).
- Verified: `test_browser.cjs` passes; `dev/make_v9_52.cjs` gives the exact v9.52 image; Zig compiles
  `sg_subpad.c` byte-identical to the module inside v9.52, so this toolchain reproduces the author's builds.

## Ideas: chord feature

Existing groundwork: the arp's CHORD mode (all held notes every step), 34 scales
(`synth/scales.c`, `scales.json`), 4 Sound Generator voices (hard limit: chords up to 4 notes).

**Chord pads (first candidate).** On the Sound Generator, each pad plays a
diatonic chord of the current key/scale: pad 1 = I, pad 2 = ii, ... A new
VALUE-menu item picks the type (OFF / triad / 7th / sus2 / sus4, maybe
inversions/voicing). It sits at the same note hook as the arp, so the arp can
arpeggiate the chord. Mostly new C at known hooks: moderate difficulty.

Open questions:
- Pad layout: 7 degrees x 2 octaves + 2 spare pads? Spare pads for "next inversion" / "octave"?
- What happens with Chrom scale (no diatonic chords)? Fixed major/minor per pad?
- MIDI IN: one key = one chord too, or keep notes as they are?
- Save the setting with the project (kits-save mechanism) or not, at first?

**Progressions (later, uncertain).** Recording and playing progressions with
DOOM OS: DOOM OS is a closed binary. First experiment: record chord-pad presses
in a DOOM pattern and check whether playback goes through the same note hook.

## Feasibility (2026-10-27)

Rule of thumb: a feature is cheap where earlier modules already mapped the firmware it touches, and
expensive where nobody has looked yet (new reverse engineering).

### Mapped building blocks

| Block | Where | Gives |
|---|---|---|
| Tempo-synced clock, every 64 frames (~1.3 ms) | arp, note repeat | LFO timing, sequencer steps, swing |
| Reading the tempo (project / bank / MIDI clock) | arp | sync |
| Retriggering sample pads in time | note repeat | sequencing samples |
| Starting Sound Generator notes | arp, scales, MIDI IN | synth parts |
| Catching any key, pad, knob before stock | FX deep edit, note repeat | new gestures, knob takeover |
| Pad LEDs (on/off, colour) | bounce (`F_LED` 0x800D4911) | a 16-step grid on the pads |
| Popups, custom page drawing | most modules, pad envelopes | text, lines, fills on the screen |
| Sending any FX parameter to the effects chip (DT1, within firmware min/max) | FX deep edit | modulating bus/input FX |
| Per-pad pitch and filter | pad envelopes | modulating pad sound |
| Saving with the project | kits save | persistence |

### Assignable LFO
Possible for a curated list of targets, not "any parameter" (each target family needs its own path).
- FX parameters: moderate. Unknown: how fast DT1 can be resent before stepping/zipper. Measure first.
  Safety: clamp ranges; some FX settings were already removed for dangerous loudness.
- Sound Generator pitch/filter/level: moderate (fork's own code).
- Sample pad pitch/filter: moderate (extend pad envelopes).
- Mixer and other stock parameters: unknown, new reverse engineering each.
- UI idea: hold a key + turn the knob to assign (Elektron style); pages for shape/rate/depth/target.

### OP-1 Finger sequencer
Best fit. Note repeat is close to a one-pattern version. Mapping: pads pick patterns; hold to play, HOLD
latches; join/replace/fill as a setting; swing and length as settings; edit mode = 16 pads are 16 steps,
LEDs show the hits. Hard parts: size (like bounce/pad env), gesture choice that doesn't clash with stock or
DOOM OS, storing patterns with the project, behaviour next to DOOM OS patterns (device-only).
Suggested first step: a trial with one pattern and pad-LED editing, to settle the gestures on the device.

### Out of reach
New DSP/effects on the effects chip (separate processor, no code); more than 4 SG voices (CPU headroom
never measured); changing DOOM OS itself (closed binary).

### Suggested order
1. Chord pads (small; exercises the whole build → emulator → device loop).
2. LFO on SG and FX targets (measure DT1 rate first).
3. Finger sequencer.

## UI: what the hardware gives

- Screen: 128 x 64, 1-bit (on/off pixels). Known stock primitives (pad_env.c): text in stock fonts,
  lines, filled rectangles, frame blit (BOOT_ANIM.md), popups. Pad envelopes already draws its own
  8-page screen with these; DOOM OS draws a piano roll, mixer and automation lanes. So: small graphs,
  lanes, grids, a playhead work. No colour, no greyscale, little room for text (about 3-4 rows).
- Inputs: 16 pads (velocity), VALUE encoder (turn + press), CTRL 1-3 knobs, ~20 buttons with
  combinations (SHIFT/HOLD/EXIT/VALUE + X). Taking a button or knob event before stock is solved.
- Lights: pad LEDs with colour, some button LEDs. The pads make a natural 4x4 step/clip grid.
- Constraints: every gesture must avoid stock and DOOM OS gestures; redraws cost CPU on the same
  processor as audio; no touch, no scrolling list widgets beyond what's drawn by hand.

## Why "only" the mapped blocks?

Not a hard limit: the mapped blocks are just what's cheap today. New areas can be reverse engineered
the same way this fork mapped hundreds of addresses (capstone disassembly, Ghidra, running real code in
Unicorn). The cost: slow work, findings that need emulator proof, and behaviour that only the device
shows (timing, CPU, the effects chip). No on-device debugger: each unknown can take several flash-test
rounds. DOOM OS had the same path and the time to walk it.

## Idea: song mode / arranger

Linear tracks of clips, clips placed off-grid, automation spanning clips for transitions.
- Data and timing: fine (the clock is fine-grained enough for off-grid placement).
- Automation: same targets/limits as the LFO (FX via DT1 is the known route).
- Core unknown: starting/stopping patterns from our code at exact times. DOOM OS patterns live in a
  closed binary: arranging them means reverse engineering DOOM OS too, and a DOOM OS update would
  break it. Alternative: our own clip engine driving pads/SG notes directly (bigger, but independent).
- UI is the real bottleneck: a timeline with clips on 128 x 64 and pads is doable but painful to edit.
- Lateral option: arrange in a browser (the patcher already runs there), write a song file to the SD
  card, the SP plays it. Needs the SP's file reading (partly mapped: kits save, bounce write files).
  Splits the big-screen editing from on-device playback (and maybe light on-device edits).
- Size: the largest idea so far. Worth doing only after Finger or a smaller clock-driven feature.
