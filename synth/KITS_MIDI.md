# Kits MIDI (Sound Generator + Kits v9.46)

External MIDI is part of **Sound Generator + Kits v9.46** in the patcher, so the
kits and the melodic Sound Generator can be sequenced from a DAW or a hardware
sequencer instead of being resampled. It first appeared as the experimental
v9.44-test1 build (APP1 `d47f46d4…a51d`), which v9.46 replaces; the patcher no
longer offers that test build.

**Status:** emulator-checked as described below; not yet confirmed on hardware.
Back up first and keep your known-good update for rollback. Source, build and
the other v9.46 features: [KITS.md](KITS.md).

Everything below works while the Sound Generator is open, in drum (kits) or
melodic mode; the kits run on the Sound Generator screen. Leaving that screen,
for example with EXIT, stops it, as with stock MIDI to the Sound Generator. Drums and melodic mode still share the
same four voices, so only one of them plays at a time.

## Channel: M.CH

M.CH is in the VALUE menu of both modes (the last item in melodic mode, just
before BOUNC in drum mode): 1–16, default 16. It is RAM-only and
returns to 16 at power-on. Changing it stops the sounding notes and clears the
arp's held notes, so a note held on the old channel cannot hang.

- M.CH 16 is the stock routing. Channel 16 plays the Sound Generator on its page
  and is the SP's control channel on every other page.
- With another channel, that channel plays the Sound Generator on its page and
  keeps its usual sample-pad routing elsewhere. Channel 16 is then the control
  channel on every page. For sequencing, a channel your sample banks don't use
  (11–15 with the default bank channels) avoids triggering SP functions when you
  leave the Sound Generator.

## Notes

Drum mode: notes 36–51 play pads 1–16 in pad order (36 = pad 1, 37 = pad 2 …
51 = pad 16), so the GM kick lands on pad 1, the kick in every kit but TR727.
A MIDI hit is a pad strike: the same sound, velocity and pad light. It selects
the pad (PAD), REC captures it as the last struck pad, and with ARP on it joins
the arp like a held pad. Other notes are ignored. Drums ring out either way;
the note-off matters only for ARP and HOLD.

Melodic mode plays MIDI notes as before.

## CCs

CCs on M.CH change parameters while the Sound Generator is open, and every CC still goes on
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
(the all-stop), including notes held on the pads. CC changes are RAM-only, like
knob edits.

## Emulator checks

`synth/test_kit_midi.py` boots the built image the way its
scatter loader does and feeds MIDI through the stock dispatcher with the Sound
Generator code running:

- Every note 0–127 in drum mode: notes 36–51 start a voice exactly as striking
  pads 1–16 does and sound sample for sample like the pad; the other 112 notes
  do nothing. Melodic MIDI is unchanged.
- 2,736 routing messages over every channel, M.CH 16, 10 and 1 and three pages
  match a model of the stock dispatcher plus the M.CH rules. With M.CH 16, all
  8,192 note messages take the same path as in v9.43.
- 336 drum, 35 melodic and 32 arp CC cases set exactly the knob values; 1,630
  other CCs change nothing; every CC still reaches the stock CC queue byte for
  byte; CC 123 and CC 120 behave as described above.
- The kit, capture, chord, shortcut and menu checks pass on v9.46, and the
  patcher test applies its overlay to an exact APP1.

## Known stock quirk

Stock 5.52 reads past its control-note table for channel-16 notes 32–35
wherever channel 16 acts as the control channel: with M.CH 16 whenever the
Sound Generator page is closed, and with another M.CH on every page. The test
build leaves that stock code as it is; another reason to sequence on a channel
other than 16.
