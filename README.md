# Tracelistener's SP-404MKII Sound Generator mod

**[Open the patcher](https://tracelistener.github.io/doom-os-etc./)**

The patcher builds **Sound Generator + Kits v9.47** for the SP-404MKII:
Sound Generator **v9.9.3** (four live voices, 17 new waveforms, nine
volume/filter-envelope presets, 34 scale choices and an arpeggiator) plus
thirteen synthesized machine kits. v9.47 also adds bounce in place, pad
envelopes, note repeat, chromatic scales, saved kit edits and Sound Generator
settings, SUB PAD on the Sound Generator, FX deep edit and fast boot. It is built on, and includes, **DOOM OS 0.6.1**
(build ED5E), Klangfeld Labs' pattern sequencer for the SP: hold REMAIN and
press SUB PAD to open it ([DOOM OS quickstart](https://tracelistener.github.io/doom-os-etc./manual/)).
Drop in the stock firmware and press Patch; there is nothing to choose. Firmware
processing happens locally in your browser; nothing is uploaded. [Kit controls,
reproduction and validation](synth/KITS.md).

## New in v9.47

- **Bounce in place:** hold RESAMPLE and tap a pad that holds a sample, then:
  - tap where it goes: the same pad to bounce in place, an empty pad to bounce
    onto it (a pad with a sample says PAD NOT EMPTY). The pad you pick lights
    up;
  - turn VALUE for NO TAIL or TAIL;
  - press RESAMPLE to start. On a pad you bounced in place, VALUE press
    switches to UNDO, which swaps it back.

  The bounce is named after the pad with ` B`. [BOUNCE.md](synth/BOUNCE.md)
- **Pad envelopes:** SHIFT + PITCH/SPEED, then turn VALUE (or tap SHIFT)
  through eight pages:
  - pages 1-4: finer attack, hold and release, with curves, decay and sustain,
    and loop and re-hit modes;
  - pages 5-7: a pitch envelope, a resonant LP/BP/HP filter, and its own cutoff
    envelope;
  - page 8: the envelope curves.

  Per pad, saved with the project; on page 1 VALUE press switches TIME between
  STOCK and FINE; DEL resets a pad's envelopes.
  [PAD_ENV.md](synth/PAD_ENV.md)
- **Note repeat:** hold ROLL and a pad and it repeats at the pad's Roll
  division. Turn VALUE while holding ROLL to change the division; triplets are
  included. Tap ROLL to latch it, and HOLD keeps rolls going. In chromatic mode
  each pad has its own roll division, 1/16 to start. SHIFT + ROLL and DJ mode
  stay stock. [NOTE_REPEAT.md](synth/NOTE_REPEAT.md)
- **Chromatic scales:** in chromatic mode, hold VALUE and turn to choose from
  the Sound Generator's 34 scales (a press steps to the next); hold SHIFT too for
  the key. The pads walk the scale and reach an octave above stock's top (+27).
  [CHROMA.md](synth/CHROMA.md)
- **Saved with the project:** the drum kits, M.CH, the arpeggiator, ENV and
  SCALE, and the Sound Generator's own settings (NOTE, OCT, OFST, TYPE, FREQ,
  LEVEL, Pad Length, DUTY, BALANCE, TUNE), in `SG_KITS.BIN` beside
  `PADCONF.BIN`, about 2 s after the last change, including MIDI CC changes.
  Drum mode and melodic mode each have their own arpeggiator settings.
  [KITS_SAVE.md](synth/KITS_SAVE.md)
- **SUB PAD on the Sound Generator:** plays the last pad again, in melodic and
  drum mode. [SG_SUBPAD.md](synth/SG_SUBPAD.md)
- **FX deep edit:** press an FX button (or REMAIN + FX), then VALUE: the screen
  stays up. Press VALUE to go through its screens and on to extra screens with the
  settings the SP never sends to its effects chip, three at a time on CTRL 1-3
  (Tape Echo's TAPE DIST, Reverb's DENSITY and more), on the bus effects and
  the input FX; an effect without any says NO EXTRA SETTINGS. These live in RAM only,
  the values are raw numbers, and some gains get loud.
  [FX_DEEP_EDIT.md](synth/FX_DEEP_EDIT.md)
- **Fast boot:** once the project has loaded, the SP goes straight to the main
  screen. DOOM OS's boot animation is skipped, which saves about 4 s.
  [BOOT_ANIM.md](synth/BOOT_ANIM.md)
- **RESAMPLE start fix v3:** a resampled take keeps its quiet lead-in, 8 frames
  before its first sound.

How the build is put together, and its test status: [COMBINED.md](synth/COMBINED.md).

## Synthesized kits v9.46

Thirteen kits: TR808, DR110, KPR77, Lel' UDS, FM, TR909, TR606, SDS-V, Mini
Pops 7, CR78, CR8K, TR707 and TR727, every voice fitted to recordings or
plug-in captures. SHIFT+PATTERN EDIT opens Kits; SHIFT+RECORD SETTING opens
melodic mode. Tap SHIFT to toggle the two parameter pages. KIT selects only
machines, never OFF. The modes have separate VALUE menus and share the
arpeggiator. In drum mode REC records the last drums struck together (up to
four within 100 ms), each to its own ring-out. All sounds are synthesized, with
sixteen assignments per kit and same-machine variants marked `+`. These are
independent models, not recovered Roland ACB. APP0 is unchanged. See
[KITS.md](synth/KITS.md).

New in v9.46:

- **MIDI:** sequence the kits and the melodic Sound Generator from a DAW or a
  hardware sequencer. Notes 36–51 play pads 1–16, the M.CH menu item sets the
  channel (default 16), CCs control every kit and synth parameter, and CC
  120/123 stop hung notes. It works while the Sound Generator is open.
  [Note map and CC chart](synth/KITS_MIDI.md).
- **BOUNC:** write the current kit, with every pad's settings, into the sixteen
  pads of a sample bank. A bank that has samples asks once: FILL keeps them and
  fills the empty pads, OVER replaces them all, then SURE? confirms.
- **Drum REC length:** a drum recording runs until its drums have rung out (at
  most 10 s). It no longer takes the melodic Pad Length, which saved only a
  blip when Pad Length was set to waveform cycles.
- **Every recording loads:** the SP leaves a pad empty when its sample is
  shorter than 21 ms. Melodic REC with a Pad Length of a few cycles of a high
  enough note now becomes the fewest whole cycles that reach 21 ms, and drum
  recordings are never shorter.
- **Resample and looper:** SHIFT + PATTERN EDIT opens the kits from the
  RESAMPLE screen while a take is armed, and from the LOOPER screen (MARK with
  MARK Function set to Looper). With the looper on, REC on the Sound Generator
  screen records the loop, in kits as in melodic.
- **RESAMPLE start fix:** a resampled take starts on its first sound instead of
  keeping a few milliseconds of silence from the round trip through the effects.
- **Clean starts:** UDS, MP-7, TR-707 and TR-727 hits start their noise filters
  at rest, so the same pad sounds the same every time.

### Using the kits (v9.46)

| Control | In drum mode |
|---|---|
| SHIFT + PATTERN EDIT | Open the kits with the last kit used |
| SHIFT + RECORD SETTING | Back to the melodic Sound Generator |
| CTRL1 / CTRL2 / CTRL3 | Tune (±12 semitones) / Decay / Tone |
| Tap SHIFT, then CTRL1–3 | Sweep / Noise / Attack; tap SHIFT again to go back |
| Hold a pad, turn VALUE | Step through that machine's sounds |
| VALUE menu | ARP, RATE, HOLD, BPM (a readout), KIT, PAD, SOUND, LEVEL, M.CH, BOUNC |

Tune at 0 and the other knobs at 50 play the machine's own sound. Kit edits
are saved with the project (v9.47).

- **Record a drum:** play, press REC, pick an empty pad (it blinks), press REC
  again. It records the last pad you hit plus up to three others hit within
  100 ms before it, each with its own timing and velocity, until the last one
  has rung out (21 ms to 10 s). You don't need to hold the pads.
- **Bounce a kit into a bank:** turn VALUE to BOUNC, press VALUE, turn to a bank
  (A–J), press VALUE. An empty bank fills at once. A bank with samples asks FILL
  (keep them, fill the empty pads) or OVER (replace them all), then SURE?: NO
  writes nothing, YES starts. The value counts the pads and shows DONE. EXIT
  stops a bounce; the pads already written stay.
- **Resample the kits:** press RESAMPLE, pick an empty pad, then SHIFT + PATTERN
  EDIT. The kits open with the take armed, and the first hit starts it. RESAMPLE
  stops it. SHIFT + RECORD SETTING on the RESAMPLE screen opens the Sound
  Generator as you left it.
- **Loop the kits:** set MARK Function to Looper, press MARK, then SHIFT +
  PATTERN EDIT on the LOOPER screen. REC starts and stops the loop recording,
  and MARK goes back to the LOOPER screen. SHIFT + RECORD SETTING there opens the
  melodic Sound Generator.
- **Sequence over MIDI:** set M.CH in the VALUE menu to a free channel, such as
  11. Notes 36–51 play pads 1–16. Each pad has Tune, Decay and Level CCs (pads
  1–4: 20–31, pads 5–12: 40–63, pads 13–16: 102–113); the last pad heard takes
  Tone 114, Sweep 115, Noise 116 and Attack 117. Melodic mode: TYPE 70, FREQ 71,
  LEVEL 72, DUTY 73, BALANCE 74, ENV 75, TUNE 76. Arp: ARP 33, RATE 34, A.OCT
  35, HOLD 36. CC 123 lets go of MIDI notes and stops the arp; CC 120 also fades
  every voice. [Full note map and CC chart](synth/KITS_MIDI.md).
- **Resampled takes start on time:** in this build a take made on the RESAMPLE
  screen starts on its first sound. Only START moves, so you can pull it back
  in sample edit.

## What this mod adds

- Four live Sound Generator voices with shared controls and held-pad LEDs.
- 17 added waves: FM1:1, FM1:2, FM1:7, CZSaw, CZSqr, CZRes, Sync, Fold,
  Drive, LPSaw, LPSqr, Organ, Vowel, Table, Logic, Metal and Grit.
- Nine timed ENV presets; four also have a resonant low-pass/filter envelope.
- 34 scales (27 added in v9.6): with a SCALE set, the 16 pads play only scale notes, so one
  bank spans two to three octaves.
- An arpeggiator (v9.9.3) in the Sound Generator VALUE menu: six motifs, seven
  rates, octave range and HOLD, following the project or bank tempo.
- MIDI IN on all four voices. When all four are busy, a new note takes one
  after a 2.8 ms fade-out, reducing chord-swap clicks in emulator tests.
- Held-chord REC with fades at the end and when REC starts, voice
  stealing and fixes for release, OCT note-off, FREQ/ENV/START-END, the FREQ
  readout and stale TYPE selection/display.
- Loudness/DC matching and quieter Pulse/Noise, while retaining raw DUTY
  jitter and Sync/CZRes aliasing grit. Stock waves, including Saw2, remain.
- v9.6 fixes out-of-range pad releases after large OCT/ROOT/SCALE changes
  and FREQ bounds for wide MIDI chords. Fitting chords keep their intervals;
  chords wider than 84 semitones stay unchanged when FREQ is adjusted.

This does not turn normal sample pads or patterns into live synth pads.
No ZEN-Core/MC-101 engine is included.

## Sound Generator envelopes (v9.9.3)

In Sound Generator, select **ENV** and choose a preset. Play a new note after
changing ENV: each voice takes its preset when the note starts. These replace
the nine original non-OFF ENV shapes and work with stock and added waveforms,
four-voice playback and held-chord REC.

| ENV | What it does |
|---|---|
| OFF | Stock behavior; no added volume or filter envelope. |
| Pluck | Fast attack, short decay to silence. |
| Perc | Fast attack, longer decay to silence. |
| Keys | Fast attack, decay to a quieter held level, release tail. |
| Pad | Soft attack, full held level, long release. |
| Swell | Slower fade-in and longer release than Pad. |
| Bass | Fast attack with a closing resonant low-pass filter and short release. |
| Acid | Fast attack, stronger resonance/filter drive and very short release. |
| Sweep | Quick volume attack with a slowly opening resonant low-pass filter. |
| FPad | Soft volume attack, slow filter movement and long release. |

Bass, Acid, Sweep and FPad have **both volume and filter envelopes**; the
other five non-OFF presets shape volume only. The filter tracks note pitch.
Release tails continue after note-off, while all-stop still uses the short
stock fade. ENV is a preset selector, not separate ADSR/filter parameter knobs.
REC renders the held chord with its selected envelope, not a live performance.
See [the envelope and previous v9.x notes](synth/V9.md).

## Scale pads (v9.9.3)

Set **SCALE** to anything other than Chrom and the 16 pads play only notes of
that scale, one scale step per pad, from the bottom row (lowest) to the top
row (highest), left to right. Pad 9 plays the first scale note at or above its
usual note. One bank then spans two octaves and a step with a 7-note scale, or
three octaves with a pentatonic one. The pad lights keep their meaning (root,
below and above the root). Chrom, NOTE, OCT and the other screens work as
before. MIDI IN now plays all four voices, and a held MIDI note lights the pad
with the same pitch.

The original scales retain their IDs. New choices include the remaining modes,
blues, bebop, harmonic/melodic minor, whole tone, diminished, several pentatonics
and more. [Full scale list and v9.6 fixes](synth/SCALES.md). Added choices act as
Chrom outside Sound Generator. Extreme OCT settings can put pads outside the
existing playable pitch range; no new save/load persistence has been established.

## Arpeggiator (v9.9.3)

Five items follow TUNE in the Sound Generator **VALUE** menu. Use them like
the others: move to the item, enter edit, turn.

| Item | Values |
|---|---|
| ARP | OFF, UP, DOWN, UP&DN, RAND, ORDER (as pressed), CHORD (all held notes each step) |
| RATE | 1/4, 1/4T, 1/8, 1/8T, 1/16 (default), 1/16T, 1/32 of a beat |
| A.OCT | -3..+3: also play the held notes that many octaves below/above |
| HOLD | OFF, ON: latch; the next key after letting go of everything starts a new chord |
| BPM | Read-only: the tempo the arp plays at |

With ARP on, pads and MIDI IN feed the arp instead of playing directly. Each
step is released half a step later, so the ENV preset shapes every step and
release tails overlap across the four voices. The arp follows the tempo
BPM-synced samples in the current bank follow: the PROJECT BPM, or the bank's
own BPM when the tempo is set to BANK, the MIDI clock when synced, or a
playing pattern's tempo. It runs free from the first key and is not locked to
the pattern's beat grid. Turning ARP on stops notes you were playing directly;
leaving the Sound Generator page stops the arp. Settings are saved with the
project (v9.47); a project without them starts with ARP OFF. [Arpeggiator notes,
build and tests](synth/ARP.md).

## How to install

Use this fork's web patcher, which includes the new synth options:

[Open the patcher](https://tracelistener.github.io/doom-os-etc./)

You can also download this repository as a ZIP file (under the Code button), unzip it and open index.html in your browser. Just follow the instructions on the page.

### Manual installation

1. Download the 5.52 system update from [Roland's support page](https://www.roland.com/global/support/by_product/sp-404mk2/updates_drivers/) and unzip it.
2. Open [our patcher](https://tracelistener.github.io/doom-os-etc./), load the stock `SP404MKII_APP1.bin` and press Patch firmware. It builds Sound Generator + Kits v9.47. The patcher only accepts official 5.52 and checks the result against [the fork's checksums](synth/checksums.txt).
3. Download the patched `SP404MKII_APP1.bin` and use it with the unchanged official 5.52 `SP404MKII_APP0.bin` for your test update. Back up first and keep your known-good update for rollback.
4. Insert the card, hold **SHIFT** while you turn the SP on, and press the **VALUE** knob when the update menu appears.
5. When the update is done, turn the SP off and on again.

To go back to the original firmware, just run the updater with the original Roland firmware.

## Status

**v9.47** (2026-10-22) is combined-test7: every feature's latest test build in
one APP1 (`build_combined.py`), plus fast boot (`build_fast_boot.py`) and no
"SHIFT: PAGE" on the drum kit screen (`build_kit_footer.py`). Its APP1
SHA-256 is `be758f67…34b4`. Each module is byte for byte its own test build's,
and the branch rebuilds the APP1 exactly. In the emulator, every feature suite
passed its behaviour checks on combined-test5 but one by design (in chromatic
mode ROLL + VALUE is the roll speed now, not the key), and the 25 kit suites
passed there. combined-test7 changes only FX deep edit and the kit footer's
text: its FX suite, seven kit suites and the patcher test pass. Bounce in place passed its two checks on the unit as
bounce-3-test6. The other features, and this combined build, have no hardware
report yet. [COMBINED.md](synth/COMBINED.md).

**Kits v9.46** (2026-10-13) is build v9.46-test3 plus the RESAMPLE start fix
(APP1 SHA-256 `7b5fbcb4…684a`). Its test builds were partly played on hardware
(drum REC, BOUNC and the looper), and those reports shaped the release. MIDI,
resampling with the kits and the start fix have no hardware report yet, and the
last changes (the 21 ms minimum, the BOUNC questions, the looper shortcut) are
checked in the emulator only, where every kit suite, the start-fix test and the
patcher test pass. CPU headroom under heavy use is not yet measured on a device.
[Kit test status](synth/KITS.md).

**v9.9.3** (2026-10-07) fixes the reproduced BANK-tempo mismatch: the arp
now uses the active sample bank, matching the normal TEMPO SEL screen. v9.9.2
read an independent pad-selection dialog bank, which could remain at 90 BPM.

All 71 emulator checks pass on the exact build: 21 arpeggiator checks, the
32-check v9.5 suite, 14 voice-fix checks and four new native bank-tempo checks.
The new checks compare the arp with the real TEMPO SEL drawing code across
all 100 active/dialog bank combinations. The build reproduces byte-for-byte;
with ARP OFF it plays bit-identically to v9.6 in the emulator. Earlier builds
had hardware reports confirming menu layout, step timing and PROJECT tempo.
The exact v9.9.3 build is not yet hardware-tested; CPU headroom remains
unmeasured. This remains experimental; four loud voices can clip. The patcher
no longer offers v9.9.3 on its own: it is the Sound Generator inside Kits v9.46.
APP0 stays unchanged stock.

See [the arpeggiator notes](synth/ARP.md), [the v9.6 scale changes](synth/SCALES.md),
[the wave list](synth/WAVES.md) and [integration notes](synth/README.md).
Report synth bugs with the build, waveform, ENV preset, number of held notes
and steps to reproduce. Preserve your backups and known-good firmware pair.

## Disclaimer

Unofficial; not affiliated with Roland or Klangfeld Labs. Firmware modification
is at your own risk. Synth additions are by tracelistener; the underlying
DOOM OS 0.6.1 ED5E base is by Quintus Oostendorp / Klangfeld Labs under the
MIT License ([LICENSE](LICENSE)), retained unchanged. FX deep edit's parameter
table comes from DM-404's `core/fx/fxmap.json` by Nicholas Petty and the dm-404
contributors, under the MIT License ([THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)).
