# Synthesized machine kits v9.44 (test candidate)

This branch carries the v9.44-test1 kit candidate: v9.43 plus external MIDI
sequencing, for the kits and the melodic Sound Generator. It adds a MIDI channel
item (M.CH), drum notes 36–51 on pads 1–16 and CCs for every parameter
([MIDI](#midi)). test1 has emulator verification only. The published patcher
option is still v9.43 (build v9.43-test3, APP1 SHA-256 `f6b83372…a515`) until
this candidate passes a hardware test and `publish_kits.py` is run.

v9.43 has thirteen kits, every voice re-measured against references. Its test1
and test2 were played on hardware. test2 answered the first report (kick level,
FM kick and bells, recording struck drums together, the REC destination pad
blink). test3 trims the drum VALUE menu after the second report and has emulator
verification only.

Select **Sound Generator + Kits** in the patcher. This separate option
includes the melodic generator and shared arpeggiator. Both browser choices
start unchecked; choosing one deselects the other. Firmware processing stays
local in your browser. The patcher produces APP1 only; APP0 remains stock.

## Open and play

- SHIFT + PATTERN EDIT opens Kits and restores the last selected machine.
- SHIFT + RECORD SETTING opens the melodic Sound Generator.
- Both shortcut release orders work. Tap/release SHIFT to switch parameter
  pages; you can audition pads after releasing it.
- In drum mode, REC uses the last struck pad after release; you do not need to
  hold it. (The melodic Sound Generator still records the notes held while REC
  is pressed.)
  Drums struck together record together: REC also takes up to three other pads
  struck within 100 ms before the last one, each at its own offset and velocity.
  Capture freezes each pad's controls, velocity, onset phase and noise seed.
  A retriggered 808 kick retains its initial capacitor state when controls match
  that hit; if controls changed afterward, REC renders the current recipe.
- After the first REC press, the destination pad you choose blinks until the
  second REC press imprints it, as in the stock firmware (melodic and drum mode).
  The two kit shortcuts do nothing between those presses.
- Strike a pad to select it. Hold a pad and turn VALUE outside menu edit mode
  to choose a sound from that machine's inventory.
- KIT stays between TR808 and TR727. Turning beyond either end keeps that kit.
  OFF is an internal melodic state, not a selectable drum-menu choice.

| Main display page | CTRL1 | CTRL2 | CTRL3 |
| --- | --- | --- | --- |
| First | Tune ±12 semitones | Decay 0–100% | Tone 0–100% |
| After tapping SHIFT | Sweep 0–100% | Noise 0–100% | Attack 0–100% |

Kit VALUE has ARP, RATE, HOLD, BPM, KIT, PAD, SOUND, LEVEL (0–127) and M.CH. The
six main-display parameters do not repeat there. A.OCT is a melodic control: it is
not in the drum menu, and drum arps ignore it. BPM is a readout in both modes;
pressing VALUE on it does nothing. Melodic VALUE keeps its original items and
arpeggiator controls, with no drum items, and ends with M.CH. Melodic SHIFT keeps
the existing Pad Length/Balance page. Edits are RAM-only.

**50 is the authentic setting** for Decay, Tone, Sweep, Noise and Attack on
every pad: a pad at 50 plays the modelled machine voice unchanged. TONE is the
808's own knob on its kick (tone), snare (snappy) and cymbal (tone), and a
broadband tilt everywhere else. SWEEP below 50 lowers or removes a voice's own
pitch envelope (or makes the pitch rise into the note); above 50 deepens it.
NOISE above 50 mixes noise into metallic sources; below 50 thins noisy voices.

## MIDI

The kits and the melodic Sound Generator can be sequenced from a DAW or a
hardware sequencer. Everything below acts only while the Sound Generator page
is open, as stock MIDI to the Sound Generator always has.

### Channel: M.CH

M.CH is the last VALUE item in both modes: 1–16, default 16. It is RAM-only and
returns to 16 at power-on. Changing it stops the sounding notes and clears the
arp's held notes, so a note held on the old channel cannot hang.

- M.CH 16 is the stock routing. Channel 16 plays the Sound Generator on its page
  and is the SP's control channel on every other page.
- With another channel, that channel plays the Sound Generator on its page and
  keeps its usual sample-pad routing elsewhere. Channel 16 is then the control
  channel on every page: notes 12–19 and 24–31 run the SP's functions on the
  Sound Generator page too. Its other notes never play the Sound Generator; on
  other pages they behave as stock.

### Notes

Drum mode: notes 36–51 play pads 1–16 in pad order (36 = pad 1, 37 = pad 2 …
51 = pad 16), so the GM kick lands on pad 1, the kick in every kit but TR727.
A MIDI hit is a pad strike: the same sound, velocity and pad light. It selects
the pad (PAD), REC captures it as the last struck pad, and with ARP on it joins
the arp like a held pad. Other notes are ignored. Drums ring out either way;
the note-off matters only for ARP and HOLD.

If OCT, carried over from melodic mode, is +4 or −3, some pads' own notes fall
outside the playable range and those pads are silent when struck by hand (a
known issue, also in v9.43; set OCT back toward 0 in melodic mode). MIDI notes
still play them.

Melodic mode plays MIDI notes as before.

### CCs

CCs on M.CH change parameters while the page is open, and every CC still goes on
to the SP's own CC handling unchanged. Stock 5.52 uses CCs only on channels 1–5:
7, 8 and 85–91 on channel 1, 7 on channels 2–3, and the effect controls 16–19
and 80–83 on channels 1–5. The chart avoids all of them, and the CCs that DAWs
and GM files send by themselves (0, 1, 6, 7, 10, 11, 32, 38, 64–69, 91, 93,
96–101, 120–127 apart from 120 and 123 below).

Drum mode, three CCs per pad:

| Pad | Tune | Decay | Level |
| --- | --- | --- | --- |
| 1 | 20 | 21 | 22 |
| 2 | 23 | 24 | 25 |
| 3 | 26 | 27 | 28 |
| 4 | 29 | 30 | 31 |
| 5 | 40 | 41 | 42 |
| 6 | 43 | 44 | 45 |
| 7 | 46 | 47 | 48 |
| 8 | 49 | 50 | 51 |
| 9 | 52 | 53 | 54 |
| 10 | 55 | 56 | 57 |
| 11 | 58 | 59 | 60 |
| 12 | 61 | 62 | 63 |
| 13 | 102 | 103 | 104 |
| 14 | 105 | 106 | 107 |
| 15 | 108 | 109 | 110 |
| 16 | 111 | 112 | 113 |

The last pad heard (struck, played by MIDI or stepped by the arp): Tone 114,
Sweep 115, Noise 116, Attack 117.

The scaling is the knobs': Tune −12 to +12 semitones (CC 64 = 0); Decay, Tone,
Sweep, Noise and Attack 0–100% (CC 64 = 50%, the authentic setting); Level 0–127
equals the CC value. Drum CCs act on the current kit at once, so a CC sent just
before a note shapes that hit. A drum CC selects the pad it changed, as a strike
does, so the main display shows that pad. The knob page (tap SHIFT) and the
VALUE cursor stay where you left them.

Melodic mode: TYPE 70, FREQ 71, LEVEL 72, DUTY 73, BALANCE 74, ENV 75, TUNE 76.
CC 0–127 covers each parameter's full range exactly as its knob does (TUNE:
CC 64 = 440.0 Hz). DUTY does nothing on types without it, as the knob.

Many keyboards send CC 71–74 from their knobs by default (resonance, release,
attack and cutoff in the MIDI standard). On M.CH those knobs move FREQ, LEVEL,
DUTY and BALANCE. If that is not wanted, put the keyboard on another channel or
remap its knobs.

Arpeggiator, both modes: ARP 33 (OFF, UP, DOWN, UP&DN, RAND, ORDER and CHORD
in seven equal zones), RATE 34 (seven zones), A.OCT 35 (−3 to +3, melodic only),
HOLD 36 (0–63 OFF, 64–127 ON). Switching ARP on by CC stops notes played
directly, as the menu does.

Melodic and arp CCs take effect at the next Sound Generator screen update (one
UI refresh) through the knobs' and the VALUE menu's own code, and the screen
shows them.

CC 123 (All Notes Off) lets go of every note MIDI holds and stops the arp,
whatever it holds. With ARP off, notes held on the pads keep sounding. CC 120
(All Sound Off) does the same, then fades every Sound Generator voice out at once
(the all-stop). CC changes are RAM-only, like knob edits.

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
- FM: modulation indexes are counted in cycles (0.16 cycle is about 1 radian).
  test1 set the kick's index 4–6 times too high, which buzzed; the kick is now a
  short sine thump with a light modulator click, and the bells ring cleaner.
- Level trims follow the v9.36 policy (attack/body proxy 0.32 at LEVEL 110,
  neutral transient cap 1.6) for all 143 sounds. Kicks are then raised to 3 dB
  above their kit's median momentary loudness (BS.1770, 400 ms, measured after
  the output stage) unless the raw peak would pass 1.3, where the per-voice knee
  would flatten the attack. DR-110 and KPR-77 kicks stop at that cap, 1–4 dB
  under. FM bells sit 1 dB above the median instead of 7–8 dB.

## Output and CPU

The synth mix and export retain v9.39's nominal +6.02 dB gain and summed-output
soft knee (starts at 24576, approaches 32000 on the signed 16-bit scale). Existing
live bus audio is preserved. Later effects/mixes can still overload.

ARM instruction counts per voice and 64-frame block (Unicorn, exact module):
median 19.6k, worst steady 65k (TR-606 cymbal), worst onset block 125k (a TR-606
cymbal whose shared source cache rebuilds). v9.43 measured 19.4k, 65k and 125k,
and v9.42 31k, 71k and 215k. MIDI handling runs in the MIDI task, not in the
render loop.

## Reproduce

Use Python 3.12, the pinned dependencies and Zig 0.13.0. Supply your own official
5.52 firmware pair. No complete Roland firmware is distributed.

```sh
python -m pip install -r synth/requirements.txt
python synth/build_v9.py /path/to/stock/SP404MKII_APP1.bin --zig /path/to/zig --out out/v9.5-parent
python synth/build_scales.py out/v9.5-parent/SP404MKII_APP1.bin --zig /path/to/zig --out out/v9.6 --fixes
python synth/build_kits.py out/v9.6/SP404MKII_APP1.bin --zig /path/to/zig --out out/kits-v944
```

A clean rebuild from stock 5.52 with these commands reproduces the v9.44-test1
APP1 (`d47f46d4…a51d`, 3,088,608 bytes). The published v9.43 APP1
(`f6b83372…a515`, 3,085,968 bytes) is rebuilt the same way from commit
`b1c1b26`. The kit builder requires only the files in this repository. Patch
sites retain exact-byte guards. Zero-filled module sections are packed into
guarded scatter rows and reconstructed to verify the complete runtime image
before writing APP1.
Module: 151,108 bytes at run time (limit 319,488), 116,644 stored.

MIDI reaches the module through four guarded jumps in the stock MIDI handlers,
which both MIDI ports share through the table at 0x802091ec:

| Site | Stock code | Now |
| --- | --- | --- |
| 0x80066d18 | note-on: channel 16 runs control functions unless the SG page is open | the same unless M.CH is another channel; then channel 16 runs them on every page |
| 0x80066e64 | note-on: channel 16 goes to the SG handler 0x8005a680 | M.CH decides (`kit_midi_route`) |
| 0x800670b8 | note-off: the same | the same |
| 0x80066174 | CC: the stock CC queue write | `kit_midi_cc` first, then the stock queue write unchanged |

Sixteen more spans the gates rely on or return into are checked against their
exact v9.6 instructions without being changed (listed in the manifest as
`kit_midi_guards`).

The kit builder also restores one stock instruction block outside the module.
Every Sound Generator pad event ends in a shared UI redraw request at
0x8015c01c. The original polyphony patch moved that request into its
all-notes-off wrapper and left NOPs in its place, so choosing an imprint
destination stopped redrawing the pads. The 14 stock bytes are written back
behind an exact-byte guard.

## Checks (v9.44-test1, emulator)

MIDI (`test_kit_midi.py`). The built image is booted the way its scatter loader
does it, and MIDI messages go through the stock dispatcher with the Sound
Generator code running for real:

- Drum map: every note 0–127. Notes 36–51 start a voice exactly as a strike of
  pads 1–16 does (source, pad note, velocity, PAD, REC pad, no pad held down).
  Through the real render loop, each sounds sample for sample like striking its
  pad. The other 112 notes do nothing. With ARP on, a note enters the held list
  as its pad. OCT +4 falls back to the MIDI pitch and still sounds. Melodic MIDI
  is unchanged.
- Routing: 2,736 messages over every channel, M.CH 16, 10 and 1, and three
  pages match a model of the stock dispatcher plus the M.CH rules, including the
  control functions' codes. With M.CH 16, all 8,192 note messages (16 channels,
  note-on and note-off, notes 0–127, the SG page and another page) take the same
  path as in v9.43-test3.
- M.CH: name, text, 1–16 bounds, the stock VALUE-cursor range 0–21, and a change
  stops the voices and clears the arp.
- CCs: 336 drum cases (every pad CC and the four last-pad CCs at 0, 64 and 127,
  on TR808 and TR707) set exactly the knob values at once and select the pad. A
  CC just before a note gives the same audio as the same setting made by hand.
  35 melodic cases wait for the screen update, then match the knobs' scaling
  through the stock setter. 32 arp cases cover both modes, with A.OCT melodic
  only. 1,630 other CCs change nothing: other numbers, the other mode's CCs,
  other channels and other pages. Every CC still reaches the stock CC queue
  byte for byte. CC 123 releases MIDI notes, keeps pad notes and stops the arp
  in both modes. CC 120 fades out every voice.

The kit checks below were run again on v9.44-test1:

- 208 factory pad renders (13 kits × 16) match host/ARM sample for sample for
  3000 samples each, plus 108 control endpoint cases (TUNE, DECAY, TONE, SWEEP,
  NOISE, ATTACK at both ends on nine voices from five engines).
- Machine inventories, held-pad editing, menu ranges (drum mode skips A.OCT,
  both menus end with M.CH), the KIT selector ends and seven hat-choke cases pass.
- VALUE pressed on BPM leaves the stock edit flag off; on every other item it
  sets it. The gate returns through the stock handler's own epilogue.
- 208 compiled capture cases check released-pad selection and velocity, with
  melodic capture delegated to the original path.
- Chord capture (TR707, TR808, CR78): two pads struck 64 frames apart export
  as two voices, anchor first, each with its own velocity. The export renders
  match the live voices sample for sample, the later hit after 64 silent frames.
  A strike 107 ms earlier is left out.
- Kit shortcuts switch machines with the keyboard flag on. With an imprint
  armed they change nothing: no machine switch, all-stop or cursor step.
- Every sound renders finite, without DC offset or audible cut-off clicks.

Hardware timing, output and CPU headroom are not yet verified on a device.

To replay host/ARM audio checks, build the portable engine as a host library:

```sh
zig cc -O2 -ffp-contract=off -fno-fast-math -shared -DKIT_HOST synth/kits/kit_engine.c -o out/kit_engine_host.dll
python synth/test_kits.py out/kits-v944 out/kit_engine_host.dll
python synth/test_kit_capture.py out/kits-v944
python synth/test_kit_chord.py out/kits-v944
python synth/test_kit_shortcut.py out/kits-v944
python synth/test_kit_midi.py out/kits-v944 out/kits-v943
```

The second argument of `test_kit_midi.py` is optional: a v9.43 build to compare
the M.CH 16 note paths against.

Use `.so` for a supported Linux host toolchain; the build was verified on Windows.
