# Tracelistener's SP-404MKII Sound Generator mod

**[Open the patcher](https://tracelistener.github.io/SP-ETC/)**

The patcher builds **Sound Generator + Kits v9.49** for the SP-404MKII:
Sound Generator **v9.9.3** (four live voices, 17 new waveforms, nine
volume/filter-envelope presets, 34 scale choices and an arpeggiator) plus
thirteen synthesized machine kits. It also adds bounce in place, pad
envelopes, note repeat, chromatic scales, settings saved with the project,
SUB PAD on the Sound Generator, hidden effect settings and a faster start-up.
It is built on, and includes, **DOOM OS 0.6.1**
(build ED5E), Klangfeld Labs' pattern sequencer for the SP: hold REMAIN and
press SUB PAD to open it ([DOOM OS quickstart](https://tracelistener.github.io/SP-ETC/manual/)).
Drop in the original, unmodified Roland firmware 5.52 file and press Patch; there is nothing to choose
(an already-patched file or another version is refused). Firmware
processing happens locally in your browser; nothing is uploaded. [Kit controls,
reproduction and validation](synth/KITS.md).

> **Keep your volume low when you try the hidden effect settings.** Some of
> them can make the sound suddenly very loud, loud enough to hurt your ears or
> your speakers. Turn the volume down first, especially on headphones. The
> Compressor and Super Filter settings that did this in v9.47 and v9.48 are
> removed.
> If you installed v9.47 or v9.48, patch again with v9.49.

## New in v9.49

- **Safety fix:** the Super Filter's hidden settings are gone: one of them
  could make the sound suddenly, dangerously loud.
  If you installed v9.47 or v9.48, patch again with v9.49.

## New in v9.48

- **Safety fix:** the Compressor's hidden MODE setting is gone: changing it
  could make the sound suddenly, dangerously loud.
- **No more "NO EXTRA SETTINGS":** on an effect without hidden settings, VALUE
  works as it normally does.

## New in v9.47

- **DOOM OS included:** the firmware this patcher makes already contains DOOM
  OS 0.6.1 (the pattern sequencer). Everything below is added on top of it. You
  don't install DOOM OS separately.
- **Bounce in place:** turn a pad's sound, with its effects, into a new sample.
  1. Hold RESAMPLE and tap the pad.
  2. Tap where the new sample goes: the same pad to replace it (the original
     moves to an empty pad), or an empty pad to put the new sample there. The
     pad you picked lights up. A pad that already has a sample says PAD NOT
     EMPTY.
  3. Turn VALUE to choose NO TAIL (stop when the sound ends) or TAIL (keep the
     echo or reverb until it fades out).
  4. Press RESAMPLE to record.

  To undo a replace: hold RESAMPLE, tap that pad, press VALUE, then press
  RESAMPLE. [BOUNCE.md](synth/BOUNCE.md)
- **Pad envelopes:** shape how each pad's sound starts and fades. Press SHIFT +
  PITCH/SPEED, then turn VALUE to move through eight pages: finer attack, hold
  and release with curves (pages 1-4), a pitch sweep and a filter with its own
  sweep (pages 5-7), and the curve shapes (page 8). On page 1, press VALUE for
  finer timing. Each pad keeps its own settings. To put a pad back to normal,
  press DEL on these pages, then VALUE. [PAD_ENV.md](synth/PAD_ENV.md)
- **Note repeat:** hold ROLL and a pad, and the pad repeats in time with the
  tempo. Turn VALUE while holding ROLL to make the repeats faster or slower
  (triplets included). Tap ROLL to keep repeat switched on. Press HOLD to keep a
  pad repeating after you let go. In chromatic mode each pad remembers its own
  speed. [NOTE_REPEAT.md](synth/NOTE_REPEAT.md)
- **Chromatic scales:** in chromatic mode, hold VALUE and turn it to choose one
  of 34 scales (a quick press steps to the next one). Hold SHIFT as well to
  change the key. The pads now reach an octave higher.
  [CHROMA.md](synth/CHROMA.md)
- **Saved with the project:** the drum kits and their settings, the MIDI
  channel, the arpeggiator, the envelopes, the scale and the Sound Generator's
  sound settings now come back after you restart. Drum mode and melodic mode
  each keep their own arpeggiator settings. [KITS_SAVE.md](synth/KITS_SAVE.md)
- **SUB PAD on the Sound Generator:** plays the last pad again, in melodic and
  drum mode. [SG_SUBPAD.md](synth/SG_SUBPAD.md)
- **Hidden effect settings:** press an FX button, then VALUE. The effect screen
  stays up, and each VALUE press shows the next page, including extra settings
  the SP normally keeps hidden (for example Tape Echo's tape distortion). Turn
  CTRL 1-3 to change them. **Turn your volume down before you try them:** some
  can make the sound suddenly very loud. These settings reset when you turn the
  SP off.
  [FX_DEEP_EDIT.md](synth/FX_DEEP_EDIT.md)
- **Faster start-up:** once the project has loaded, the SP goes straight to the
  main screen and skips DOOM OS's start-up animation (about 4 seconds faster).
  [BOOT_ANIM.md](synth/BOOT_ANIM.md)
- **Cleaner resampling:** a resampled sample now starts just before its first
  sound, so its beginning isn't cut off.


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

[Open the patcher](https://tracelistener.github.io/SP-ETC/)

You can also download this repository as a ZIP file (under the Code button), unzip it and open index.html in your browser. Just follow the instructions on the page.

### Manual installation

1. Download the 5.52 system update from [Roland's support page](https://www.roland.com/global/support/by_product/sp-404mk2/updates_drivers/) and unzip it.
2. Open [our patcher](https://tracelistener.github.io/SP-ETC/), load the stock `SP404MKII_APP1.bin` and press Patch firmware. It builds Sound Generator + Kits v9.49. The patcher only accepts official 5.52 and checks the result against [the fork's checksums](synth/checksums.txt).
3. Download the patched `SP404MKII_APP1.bin` and use it with the unchanged official 5.52 `SP404MKII_APP0.bin` for your test update. Back up first and keep your known-good update for rollback.
4. Insert the card, hold **SHIFT** while you turn the SP on, and press the **VALUE** knob when the update menu appears.
5. When the update is done, turn the SP off and on again.

To go back to the original firmware, just run the updater with the original Roland firmware.

## Questions

**I already have DOOM OS, or an older version of this mod. Can I install this?**
Yes. Patch the file as above, then run the normal update on your SP. Whatever
your SP runs now (the original firmware, DOOM OS or an older version of this
mod), the update replaces it.

**Which file do I need?** Roland's original firmware 5.52 update, on your
computer: `SP404MKII_APP1.bin` and `SP404MKII_APP0.bin`. Load the APP1 file into
the patcher. It won't take a file that is already patched, or another firmware
version. Your SP doesn't need the original firmware installed first.

**Will I lose my work?** No. Updating the firmware doesn't erase your projects
or samples, but back up before any update anyway. Projects you make with this
firmware still open on the original firmware or DOOM OS; the extra settings are
just ignored there. If you have a newer DOOM OS than 0.6.1, this takes you back
to DOOM OS 0.6.1: your projects and samples stay, but settings or patterns from
the newer DOOM OS might not carry over.

## Status

**v9.49** (2026-10-23) is combined-test9: v9.48 with FX deep edit test8. A user
reported that CTRL 2 on the Super Filter's hidden settings spiked the volume,
so all six of its hidden settings are left out. Its APP1 SHA-256 is
`8f285b01…4750`. Only the FX deep edit module differs from v9.48, and the change
was checked in the emulator; every other module is v9.47's byte for byte.
[COMBINED.md](synth/COMBINED.md), [FX_DEEP_EDIT.md](synth/FX_DEEP_EDIT.md).

**v9.48** (2026-10-23) is combined-test8: v9.47 with FX deep edit test7. A user
reported that the Compressor's hidden MODE setting made the sound dangerously
loud, so it is left out of the hidden effect settings; an effect without
hidden settings no longer shows NO EXTRA SETTINGS. Its APP1 SHA-256 is
`fbcff606…e9f0`. Only the FX deep edit module differs from v9.47, and the
change was checked in the emulator; every other module is v9.47's byte for
byte. [COMBINED.md](synth/COMBINED.md), [FX_DEEP_EDIT.md](synth/FX_DEEP_EDIT.md).

**v9.47** (2026-10-22) is combined-test7: every feature's latest test build in
one APP1 (`build_combined.py`), plus fast boot (`build_fast_boot.py`) and no
"SHIFT: PAGE" on the drum kit screen (`build_kit_footer.py`). Its APP1
SHA-256 is `be758f67…34b4`. Each module is byte for byte its own test build's,
and the branch rebuilds the APP1 exactly. It was played on an SP-404MKII as a
whole, with no bugs found, after each feature was tried on the unit in its own
test builds. [COMBINED.md](synth/COMBINED.md).

**Kits v9.46** (2026-10-13) is build v9.46-test3 plus the RESAMPLE start fix
(APP1 SHA-256 `7b5fbcb4…684a`). Its test builds were played on hardware (drum
REC, BOUNC and the looper), and those reports shaped the release. v9.47 carries
it. [Kit test status](synth/KITS.md).

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
is at your own risk. Keep your volume low when you try the hidden effect
settings: some can make the sound suddenly very loud. Synth additions are by tracelistener; the underlying
DOOM OS 0.6.1 ED5E base is by Quintus Oostendorp / Klangfeld Labs under the
MIT License ([LICENSE](LICENSE)), retained unchanged. FX deep edit's parameter
table comes from DM-404's `core/fx/fxmap.json` by Nicholas Petty and the dm-404
contributors, under the MIT License ([THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)).
