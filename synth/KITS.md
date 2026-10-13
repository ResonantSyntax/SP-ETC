# Synthesized machine kits v9.45 (test candidate)

This branch carries the v9.45-test1 kit candidate: v9.44-test1 (external MIDI)
plus BOUNC, which writes the current kit's sixteen pads, with their settings,
into the sixteen pads of a sample bank ([Bounce a kit into a
bank](#bounce-a-kit-into-a-bank)). test1 has emulator verification only and is
not in the patcher. The patcher's published option is still v9.43 (build
v9.43-test3, APP1 SHA-256 `f6b83372…a515`); its experimental option is the
v9.44-test1 MIDI build.

v9.44-test1 added external MIDI sequencing, for the kits and the melodic Sound
Generator: a MIDI channel item (M.CH), drum notes 36–51 on pads 1–16 and CCs for
every parameter ([MIDI](#midi)). It too has emulator verification only.

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

Kit VALUE has ARP, RATE, HOLD, BPM, KIT, PAD, SOUND, LEVEL (0–127), M.CH and
BOUNC. The six main-display parameters do not repeat there. A.OCT is a melodic control: it is
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

## Bounce a kit into a bank

BOUNC, the last item of the drum VALUE menu, writes the current kit's sixteen
pads into the sixteen pads of a sample bank. Each pad keeps its own Tune, Decay,
Tone, Sweep, Noise, Attack and Level, so a kit dialled in on the synth becomes a
normal sample kit. BOUNC is not in the melodic menu.

1. Turn VALUE to BOUNC (it shows --) and press VALUE.
2. Turn to a bank, A–J, and press VALUE again.
3. Pads of that bank that are empty are filled. A pad that already holds a
   sample is asked about first, one pad at a time. The item shows the pad (B-3
   is bank B, pad 3) and KEEP. Turn VALUE right for OVER (replace it) or left
   for KEEP, then press VALUE for the next pad. After the last answer the
   bounce starts.
4. The value counts the pads as they are written (3/16) and shows DONE at the
   end. Each pad is written like a REC, so the screen pauses briefly for each
   one.

- EXIT cancels. During the questions nothing has been written. During the
  bounce the pads already written stay and the rest are not written. The value
  shows STOP.
- Outside a bounce EXIT leaves the page as always. To back out after turning to
  a bank, turn back to -- and press VALUE, or press EXIT.
- Each time you press VALUE on BOUNC to edit it, it starts again from --, so a
  bounce always takes a turn to a bank first.
- REC does nothing while BOUNC asks or writes. A bounce does not start while a
  REC imprint is waiting for its second press.
- Leaving the Sound Generator page or switching machines cancels too.
- The pads' settings are taken when you press VALUE on the bank. Changes made
  during the questions or the bounce are not in it.
- Pads whose LEVEL is 0 are left out and not asked about.
- Just before each pad is written the bank is checked again. A pad that got a
  sample in the meantime is replaced only if you chose OVER for it.
- If a file cannot be written (for example, storage full) the value shows ERROR
  and nothing more is written.

Each file is written by the same stock code as a REC imprint, so it has the same
format, the stock imprint name (SG), mono or stereo as BALANCE sets it, and v9's
10 ms fade at the end. What differs from REC:

- Velocity 127 with the pad's LEVEL. REC takes the velocity of the last strike.
- Every pad renders as a first hit on a cleared voice, with the noise seed and
  shared-source timing REC uses for a pad not struck in this kit. The same kit
  always bounces to the same files.
- Length: each sample ends where its drum has fallen 60 dB below its own peak,
  at most 10 s, instead of PAD LENGTH. On the factory TR808 the rim shot comes
  out 22 ms long, the closed hat 0.12 s, the kick 1.0 s and the cymbal 2.1 s; a
  kick with a long decay keeps its whole tail, and reverse playback starts at
  once. Across all factory and tested pads the lengths run from 13 ms to 8.7 s.

The emulator tests model the storage calls; writing to the SP's real storage is
verified only on hardware. Try the first bounce in a scratch project.

How it works:

- BOUNC is VALUE item 22. The stock cursor range becomes 0–22; drum mode shows
  the item and melodic mode skips it.
- The kits' existing page-event hook (0x800a80a8) sees VALUE presses, EXIT and
  REC before the Sound Generator page does.
- The bounce runs one pad per Sound Generator screen update (`arp_poll`, the UI
  task), so the UI task never blocks for the whole batch. Each pad is a
  pre-render on the export voice, which finds its length, and one call of the
  stock exporter (0x801327b8, the v4 export engine) with the destination
  bank × 16 + pad at +0x17c, as REC's second press calls it.
- One new guarded jump in the stock exporter's length code sets the length:

| Site | Stock code | Now |
| --- | --- | --- |
| 0x80132ac8 | `mov r4, r8; cmp.w fp, #1; mov.w r0, #0` after the frame count (fp) and loop limit (`[sp, #4]`) are set from PAD LENGTH | `kit_bounce_length_gate`: while a bounce writes, both become the pad's length; then the same three instructions |

Nine more spans the bounce relies on are checked against their exact v9.6
instructions without being changed: the gate's return, both limit stores, the
loop's limit test, the oscillator call, v9's export-mix entry, the exporter's
jump to the v4 engine, its count test and the stock body's destination test.
They are listed in the manifest as `kit_bounce_guards`. The REC exporter is not
otherwise changed. With no bounce running, the gate runs only the three
displaced instructions.

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
python synth/build_kits.py out/v9.6/SP404MKII_APP1.bin --zig /path/to/zig --out out/kits-v945
```

A clean rebuild from stock 5.52 with these commands reproduces the v9.45-test1
APP1 (`c5e99d93…fde3`, 3,093,024 bytes) and its manifest byte for byte. The
v9.44-test1 APP1 (`d47f46d4…a51d`, 3,088,608 bytes) is rebuilt the same way from
commit `6caf6af`, and the published v9.43 APP1 (`f6b83372…a515`, 3,085,968
bytes) from commit `b1c1b26`. The kit builder requires only the files in this
repository. Patch sites retain exact-byte guards. Zero-filled module sections are
packed into guarded scatter rows and reconstructed to verify the complete runtime
image before writing APP1.
Module: 155,744 bytes at run time (limit 319,488), 121,060 stored.

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

## Checks (v9.45-test1, emulator)

BOUNC (`test_kit_bounce.py`). The built image is booted as for the MIDI checks
below. The stock exporter runs for real: the v4 export engine, Roland's renderer
and file writer, the oscillator gate, the kit engine and v9's export mix. Only
the storage and project calls it makes are modelled: path, open, write, close,
delete, header, stream cache and pad registration. A pad holds a sample exactly
when the model has its file. Keys go through the stock page dispatcher to the
Sound Generator page's own handlers. One screen update is one `arp_poll` call.

- Audio, on every factory pad of all 13 kits (208), and on all 64 pads of TR808,
  FM, SDS-V and TR727 with all six knobs and LEVEL changed across their ranges:
  - bouncing pad p writes one file, to bank × 16 + p. Path, open, header,
    stream cache, size, name (SG), load and save all name that pad, and nothing
    else is touched;
  - the kit engine's output for the bounce is, float for float, that of a drum
    REC of the same pad not struck in this kit at velocity 127 (on a cleared
    export voice);
  - the file's PCM equals that REC's sample for sample, up to v9's 10 ms end
    fade, and the fade frames are exactly v9's fade of the REC's frames;
  - the length is the frame after the last sample at or above −60 dB of the
    pad's own peak (the REC beyond it never rises back above that), and the
    header and the registered size match it.
- The flow:
  - the bank value runs from -- through A–J and stops at both ends; VALUE on --
    only leaves edit mode;
  - an empty bank fills at once;
  - with samples on pads 4, 8 and 13 the questions come in pad order with KEEP
    by default and edit mode kept on. Answering OVER, KEEP, KEEP writes 14
    pads, deletes and replaces pad 4, and never opens pads 8 and 13. The value
    counts 1/14 … 13/14, then DONE;
  - EXIT while asking writes nothing and does not leave the page; EXIT during
    the run keeps the three pads written and writes no more;
  - REC is ignored while asking and while writing; with an imprint armed,
    VALUE does not start a bounce;
  - a pad that gets a sample during the run is left alone, and a knob edit
    made during the run is not in the bounce;
  - leaving the page cancels (STOP when running, -- when asking), and so does
    switching machines;
  - pads with LEVEL 0 or the sound off are not asked about and not written;
  - a file that cannot be created stops the bounce with ERROR and clears REC's
    destination;
  - the melodic menu never reaches BOUNC.
- REC is unchanged. Thirty RECs write byte-identical files, headers and
  registrations on v9.45-test1 and v9.44-test1: 28 drum (factory and tweaked
  pads, PAD LENGTH in seconds and in periods) and 2 melodic (seconds and
  periods).

MIDI (`test_kit_midi.py`, run again on v9.45-test1; the VALUE cursor range is now
0–22). The built image is booted the way its scatter loader
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
- M.CH: name, text, 1–16 bounds, the stock VALUE-cursor range (0–22 with BOUNC),
  and a change stops the voices and clears the arp.
- CCs: 336 drum cases (every pad CC and the four last-pad CCs at 0, 64 and 127,
  on TR808 and TR707) set exactly the knob values at once and select the pad. A
  CC just before a note gives the same audio as the same setting made by hand.
  35 melodic cases wait for the screen update, then match the knobs' scaling
  through the stock setter. 32 arp cases cover both modes, with A.OCT melodic
  only. 1,630 other CCs change nothing: other numbers, the other mode's CCs,
  other channels and other pages. Every CC still reaches the stock CC queue
  byte for byte. CC 123 releases MIDI notes, keeps pad notes and stops the arp
  in both modes. CC 120 fades out every voice.

The kit checks below were run again on v9.45-test1:

- 208 factory pad renders (13 kits × 16) match host/ARM sample for sample for
  3000 samples each, plus 108 control endpoint cases (TUNE, DECAY, TONE, SWEEP,
  NOISE, ATTACK at both ends on nine voices from five engines).
- Machine inventories, held-pad editing, menu ranges (drum mode skips A.OCT,
  the melodic menu ends with M.CH, the drum menu with M.CH and BOUNC), the KIT
  selector ends and seven hat-choke cases pass.
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

Hardware timing, output, CPU headroom and writes to the SP's storage are not yet
verified on a device.

To replay host/ARM audio checks, build the portable engine as a host library:

```sh
zig cc -O2 -ffp-contract=off -fno-fast-math -shared -DKIT_HOST synth/kits/kit_engine.c -o out/kit_engine_host.dll
python synth/test_kits.py out/kits-v945 out/kit_engine_host.dll
python synth/test_kit_capture.py out/kits-v945
python synth/test_kit_chord.py out/kits-v945
python synth/test_kit_shortcut.py out/kits-v945
python synth/test_kit_midi.py out/kits-v945 out/kits-v944
python synth/test_kit_bounce.py out/kits-v945 out/kits-v944
```

The second argument of `test_kit_midi.py` is optional: an earlier kits build to
compare the M.CH 16 note paths against. The second argument of
`test_kit_bounce.py` is optional too: a v9.44 build to compare REC against.
`test_kit_bounce.py` takes about 40 minutes; `--quick` checks three kits and
`--flow` skips the audio part.

Use `.so` for a supported Linux host toolchain; the build was verified on Windows.
