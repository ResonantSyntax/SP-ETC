# Changelog

## Synthesized kits v9.43-test4 (test candidate, not yet in the patcher)

Hot resample with the kits (stock: RESAMPLE, pick a pad, SHIFT + RECORD SETTING
opens the Sound Generator, and the first note starts the take):

- On the RESAMPLE screen with the take armed or running, SHIFT + PATTERN EDIT
  opens the Sound Generator in drum mode with the last kit. Before, it did
  nothing there.
- During a hot resample, SHIFT + PATTERN EDIT and SHIFT + RECORD SETTING on the
  Sound Generator page switch machines without starting or stopping the take.
  Before, their press started an armed take before any hit, or stopped a running
  one: the stock page starts and stops a resample on those keys without checking
  SHIFT. Unshifted presses still start and stop it.
- SHIFT + RECORD SETTING from the RESAMPLE screen opens the Sound Generator as
  you left it (kits or melodic) instead of always switching to melodic.
- New synth/test_kit_hot_resample.py drives the real stock key handlers on the
  booted image; with `--baseline` it reproduces the three faults on v9.43.
  Emulator-checked only.

## Synthesized kits v9.43 (2026-10-12)

test3, after the second hardware test:

- The drum VALUE menu no longer shows A.OCT, and drum arps ignore it, so an
  octave set in melodic mode cannot double drum hits.
- BPM is a readout: pressing VALUE on it no longer highlights it as if it could
  be edited (both modes).

test2, after the first hardware test:

- REC records drums struck together: the last struck pad plus up to three
  others struck within 100 ms before it, each at its own offset and velocity.
- The REC destination pad blinks again while it waits for the second REC press,
  in melodic and drum mode. The original polyphony patch had removed the stock
  pad redraw that ends every Sound Generator pad event; it is restored.
- The kit shortcuts do nothing while an imprint is armed (between the two REC
  presses), so they can no longer change state under a pending recording.
- FM kick no longer buzzes: its modulation index was 4–6 times too high. FM
  bells (pads 8 and 15) come down 4.4 dB to the kit's level.
- Kicks are louder: 2–7 dB, up to 3 dB above each kit's median loudness while
  keeping the attack clear of the limiter (808 +1.9 dB, DR-110 and KPR-77
  limited by their peaks).

test1:

- Thirteen kits: Lel' UDS (Soviet drum synthesizer) replaces Digi, Korg Mini
  Pops 7 replaces SY-1, and TR707 and TR727 are new. FM is rebuilt as eight
  DX-style voices with modulator feedback, including a log drum and cowbell.
- Every existing voice re-fitted to recordings, ACB captures and plug-in
  captures: pitch tracks, decays, envelopes and 1/3-octave balance.
- SWEEP 50 no longer adds a pitch blip; 50 is the authentic setting on every
  control. TONE drives the 808 snare's snappy knob. Each hit gets fresh noise.
- Pitch envelopes use time constants (909 kick, SDS-V bends restored); the 909
  snare body falls instead of rising.
- Level trims regenerated for all 143 sounds with the v9.36 policy.
- CPU: median per-voice cost 31k → 19k instructions per block; worst onset block
  215k → 125k. Emulator checks pass; hardware test pending.

## Synthesized kits v9.42 (fork PR)

- Add an opt-in browser patch for eleven synthesized kits with sixteen pads,
  shared arpeggiator and separate melodic/drum entry shortcuts and VALUE menus.
- Tap SHIFT toggles main parameter pages; retain the synth output boost/guard.
- Keep KIT inside machine IDs1–11: OFF can no longer change modes from the menu.
- REC captures the last struck pad after release, preserving controls, velocity,
  onset phase/noise seed and the most recent 808 kick circuit state.
- Include standalone source/build/overlay publication and exact-output tests.
  Exact v9.42 hardware timing remains unverified; APP0 is unchanged.

## 0.6.1-alpha, build ED5E (2026-10-04)

**New**

- **Pattern Follow can be toggled with SHIFT + HOLD**  
  The pattern will stay on the currently selected measure or follow the playback head.
- **Solo is now mapped to SHIFT + ROLL**    
  The **ROLL** button blinks when solo is active.
- **The metronome can be activated with SHIFT + PAD 9**  
  Press once to toggle default metronome behavior (active during playback), press twice to toggle recmode (only active during recording)
- **EXT SOURCE can be toggled with EXT SOURCE** 
- **Time signatures visible in pattern menu**  
  Currently only show the time signature, the ability to change it will be added at a later stage.

**Fixed**
- **Playback of a new pattern with empty tracks is now supported**  
  This allows you to rehearse and record with a running metronome. Previously, an empty pattern was not playable, and adding empty tracks to the pattern would get them removed. This issue made it impossible to record patterns without creating a track with at least one note in it first.
- **REC button flickering fixed**
- **Various smaller bugs involving edge cases**

**Improvements**
- **REC button dimmed when not recording**.  
  The REC button was brighter than on the stock firmware, which could lead users to mistakenly assume REC mode was enabled.

**Miscellaneous**
- **The pattern mode now supports various time signatures internally**  
  For future stock compatibility reasons.

## 0.6-alpha, build 0C34 (2026-09-28)

The first public release, for firmware 5.52.


## 0.6-alpha, build 0C34 (2026-09-28)

The first public release, for firmware 5.52.
