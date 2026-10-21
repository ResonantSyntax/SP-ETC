# Note repeat: ROLL as an MPC-style note repeat

A study of the stock ROLL and a hardware test build (`note-repeat-test1`) on the published Sound Generator +
Kits v9.46 (APP1 `7b5fbcb4…684a`: stock 5.52 + DOOM OS 0.6.1 ED5E + the fork). Addresses are 5.52 runtime
addresses. **Verified** means read in the code (Ghidra decompilation and capstone) or, where marked, run in
Unicorn; **inferred** means it follows from the code but wasn't run; **unknown** needs the unit.

What the build does, in short:

| Gesture | Stock 5.52 | This build |
| --- | --- | --- |
| ROLL + pad | loops the first slice of the pad's sound until ROLL is let go | re-hits the pad at its Roll division until ROLL is let go |
| turn VALUE while rolling | halves or doubles the slice at the end of a pass | steps through the Roll divisions, at once; popup `Roll 1/16` |
| tap ROLL | rolls the current pad if it is sounding (until the next tap) | latch: held pads repeat, ROLL lit; tap again to unlatch |
| ROLL + VALUE press | VALUE's usual press (no ROLL function) | the current pad follows ROLL or ignores it (saved with the pad) |
| SHIFT + ROLL, EXIT + ROLL | the Roll popup / all rolls off | unchanged |

## 1. How stock ROLL works (5.52; all of it unchanged in v9.46)

### 1.1 Starting a roll (verified)

- **ROLL + pad.** A panel pad is a type-4 pad event. When SMPL TASK plays it (note-on `0x800aec48`) and the
  key-held query says ROLL is down (`0x800d9f20(0x21)` at `0x800aee1e`), it sets the pad's Roll to 2 (1/4) if
  it is 0 (Off), puts the pad in a four-entry roll list (`gSmplMgr + 4..+0x10`) and calls the roll engine
  `0x8001a378(gSmplMgr, pad, 0x7f, 0, 0)`. PAD LINK pads do the same (`0x800aef92`, `0x800af06a`).
- **The engine** takes one of four roll slots (`0x802e5ffc..0x802e6008`; with all four in use it says so
  through settings 0xec) and finds the first voice slot playing the pad (`0x8008d9a0`), then
  `0x80024450(voice, on, change, slot, value)`:
  - it records the roll for a recording pattern (`0x800257b0`, "RecordRollPending", §1.6);
  - it sets the ring (`voice + 0x287f4` = `0x8300d760 + slot × 960000`, 5 s of 16-bit stereo) and the
    roll length in ms (`voice + 0x143a4`).
- **The renderer** (`0x14b88`, audio task) sees the length, restarts the voice, records its own output into
  the ring for that many frames (fading the last 64), then plays the ring in a loop (`0x8001c2c8`), with a
  64-frame fade in and out on every pass. The voice's stream stays where the capture left it; when the roll
  ends the rest of the sample plays from there.

So **a stock roll is one note-on and a looped slice**: the repeats are replays of the first `length` ms of
the voice (envelope included), not new notes. While the pad's voice rolls, the voice manager ignores a new
hit of that pad (`0x800d63c8`: same pad, `0x800d5d98` rolling, return 0).

### 1.2 Timing (verified; run in Unicorn)

`0x80024450` computes the length in **whole milliseconds**:

```
length_ms = trunc(beats[Roll] x 60000 / (voice +0xc x BPM'))     voice +0xc = 1.0 (Init)
BPM' = voice +0x34 (BPM x 100, from the pad's ORIGINAL BPM 0x6f), doubled until it is >= 50 BPM
beats[1..10] (0x801a9f18) = 2, 1, 1/2, 1/4, 1/8, 1/16, 3/2, 3/4, 3/8, 3/16
```

The renderer turns it into frames (`ms × 48`, at most 240,000). Unicorn runs of `0x80024450` match this for
every division at 24, 40, 60, 90, 120, 140, 174 and 200 BPM (80 cases). Consequences:

- the roll follows the **sample's** ORIGINAL BPM, not the project tempo (the same thing for samples recorded
  in the project; not for imported ones with another BPM);
- the truncation to whole ms makes fast rolls run fast: 1/32 at 120 BPM loops every 62 ms (not 62.5), 1/64
  at 200 BPM every 18 ms (not 18.75, **4% fast**);
- below 50 BPM the divisions double (1/4 at 40 BPM lasts as 1/8).

### 1.3 VALUE while ROLL is held (verified)

The generic key handler (`0x800c9788`) gets the turn as key 0x3f (left) or 0x40 (right). With ROLL held and
at least one roll running it sets settings 0x91 = 3 (`ROLL <<`) or 2 (`ROLL >>`), which marks every roll:
at the **end of the current pass** the reader halves the loop (only if it is longer than 2000 frames) or
doubles it (at most to the captured length). So VALUE can only go faster by halves from the start division,
and back; it cannot go slower than the slice it captured, and it waits for the pass to end.

### 1.4 SHIFT + ROLL, the divisions (verified; the names run in Unicorn)

Roll is a pad parameter (0x7b, 0..10, pad record +0x54, copied to voice +0xf4). SHIFT + ROLL shows
`Roll 1/16`; pressed again while the popup shows, it steps the current pad's Roll 1 → 10 → 1. The firmware's
names (`0x800bf788`): 0 Off, 1 1/2, 2 1/4, 3 1/8, 4 1/16, 5 1/32, 6 1/64, 7 3/8, 8 3/16, 9 3/32, 10 3/64 (the
last four are the dotted 1/4 … 1/32). SHIFT + ROLL writes through the queued setter, so a running roll keeps
its length.

### 1.5 Letting go (verified)

ROLL let go (no SHIFT, no EXIT) → `0x80135d40`: every pad in the roll list that still rolls gets roll-off
(settings 0x91 = 0 for it: the ring stops at the end of the pass). Before that, if the **current pad** sounds
and is not rolling, it **starts** a roll on it (0x91 = 1, and settings 0x7c = 1) — so in stock a ROLL tap while
a long sample plays rolls it until the next tap. EXIT + ROLL turns every roll off. A GATE pad let go while it
rolls is let go at roll-off (`0x8001e2d0` marks the slot, `0x800202b8` sends the note-off).

### 1.6 Recording (verified code; DOOM OS's recorder not traced)

- **Stock patterns:** every roll on/off and halve/double goes to the pattern recorder as a roll event
  (`0x800257b0` → `0x80030760` → `0x80030700`, status 0x8d, value = division, 0 off, 7/8 double/halve), and
  playback rebuilds the roll with the same ring (`0x800e3d40`). A recorded stock roll is a roll event, not
  notes.
- **A pad note** (what the stock pad note `0x800cdbd0` posts) is recorded by the pad-event consumer
  (`0x80050be0` → `0x800bd5a0` → `0x80030700`) while the sequencer records (`0x80591f20` = 1) — note-on and
  note-off, as for a tap.
- **DOOM OS 0.6.1** never refers to the stock pad note, the pad-event ring or the stock recorder (a scan of
  its code for literals and movw/movt pairs finds none); the only pad entry it refers to is the stock page
  pad handler `0x800c7db8` (two thunks, `0x6031c8d0`/`0x6031c8e4`). How its own recorder captures pads was
  not traced.

### 1.7 Cost of the stock roll (inferred)

One voice per rolling pad (the ring replaces its stream), at most four rolls; the capture clears up to
480,000 bytes of ring in the renderer when a roll starts.

## 2. Decision: re-hit the pad (MPC style)

| | Extend the stock roll | Re-hit through the stock pad note |
| --- | --- | --- |
| live division change | only shorter than the captured slice; longer means silence or a new capture (the sample restarts) | any division, at once |
| what a repeat plays | the first slice of the first hit, faded in and out | the whole sample, a new note each time |
| timing | whole ms, ORIGINAL BPM, doubled below 50 BPM | exact, the tempo BPM-synced samples follow |
| recording | roll events; a division change has no event (off + on would restart the capture) | notes, through the stock recorder, like taps |
| per-pad follow, latch | new code in SMPL TASK's note-on | in the module, UI task |
| LOOP pads without GATE | work | a second hit stops them: keep the stock roll for them |
| voices | 1 per pad | 1-2 per pad (the old one declicks or releases) |
| CPU | ring copy in the audio task | a pad note per repeat in the UI and SMPL tasks |

**Re-hit**, as the brief suggested: it is the only way to get any division live and repeats that record as
notes, and it is what an MPC does. LOOP pads without GATE keep the stock ring roll.

## 3. The build (note-repeat-test1)

### 3.1 Controls

- **ROLL + pad:** the pad repeats at its Roll division until ROLL is let go; letting go of the pad first
  doesn't stop it (as stock). Pads already held when ROLL goes down start at once.
- **Tap ROLL** (press and let go with nothing else touched: no pad, key, VALUE or knob) latches; ROLL is lit
  (key light 0x21, page 0, 0xff; written again at the next tick if something else writes it). Latched, a pad
  repeats **while it is held**. Another tap unlatches (`Roll Latch Off`, the light back to stock's dim).
  Holding ROLL while latched works as ROLL + pad; letting go after using it keeps the latch.
- **VALUE** while ROLL is held, or while latched with a pad repeating: every repeating pad's division moves
  along `1/2 3/8 1/4 3/16 1/8 3/32 1/16 3/64 1/32 1/64` (right = faster), stopping at the ends; the next repeat
  comes one new division after the last one (at once if that is already past). The division is the pad's
  own Roll setting (written with the stock pad setter), so SHIFT + ROLL shows it and the next roll starts
  there. With nothing repeating, VALUE + ROLL steps the current pad's Roll. Popup: `Roll 3/32`.
- **ROLL + VALUE press:** the current pad follows ROLL or ignores it. Popup `A-04 IGNORES ROLL` /
  `A-04 FOLLOWS ROLL`. An ignoring pad plays once, as without ROLL.
- **Unchanged:** SHIFT + ROLL (and a change it makes while a pad repeats is taken at the next tick), EXIT +
  ROLL (all rolls off, and unlatched), patterns' recorded rolls, everything in DJ Mixer Mode (project
  0xc2).

### 3.2 How

- **A repeat** is a note-off then a note-on of the pad at the press's velocity, through the stock pad note's
  own body (mode 1: FIXED VELOCITY, PAD LINK, mute groups, the recorder all as for a tap). The note-off gives
  a GATE pad its release and every recorded note a length.
- **Timing:** each repeat is due at the last one + `beats × 288000000 / (BPM × 100)` frames, the remainder
  carried (no drift), on the **audio clock**: `0x8059226c` (+32 every 64-frame block, from the DMA interrupt)
  interpolated with the cycle counter as the stock MIDI clock does (`0x80009de0`). It is sent at the first UI
  tick (`0x8003c5f0`, the UI task's periodic call) at or after that time, from the UI task, like a pad press.
  A late or bunched UI task delays a repeat but never moves the next one; after a stall longer than a
  division it sends one repeat and starts the grid again from there. A new division or tempo applies at once.
- **Tempo:** `0x80047dd0(pad)`, the tempo BPM-synced samples on the pad follow (project or bank BPM, MIDI
  clock, a playing pattern), read every tick; 120 BPM if it isn't 20..300.
- **LOOP pads without GATE** (a second hit stops them): the module asks for the stock roll once the pad sounds
  (`0x800163a8(pad, 0x7f, 0, 0)`, what settings 0x91 does) and turns it off (`0x800163a8(pad, 0, 0, 0)`) when
  the repeat would stop. VALUE doesn't change them while they roll.
- **Off pads:** Roll 0 becomes 1/4 when the pad first rolls, as stock.
- **The follow flag:** PADCONF reserved byte **0x70**, bit 0 (runtime `0x82e3c578 + pad × 0x80`); zero, the
  default, follows. Stock saves, loads, copies, moves and exchanges the reserved bytes with the pad (the pad
  FX and envelope studies); the module sets CSmplPrm's Edited flag and posts command 0xd a second after the
  last change.
- **The stock roll from pad hits** is off while the module runs: the key-held query answers "ROLL not held"
  to the note-on's three roll starts (and only those); ROLL's stock release handling (`0x80135d40`) doesn't
  run (the module does ROLL's release). Both are stock again in DJ mode.
- **Held pads** come from the pad events at the UI dispatcher (pads 1-16 and SUB PAD, whatever the page); the
  pad a press plays comes from the stock pad note's two page calls (`0x800c904a` a pad, `0x800c8d3c` SUB PAD).
  A press whose page doesn't play the pad (a mode, a menu) starts nothing.

### 3.3 Patches

| Site | v9.46 | Now |
| --- | --- | --- |
| `0x8003b530` | UI dispatcher: `ldrsh.w r1, [r0]; subs r1, #5; cmp r1, #0x20; bhi` | jump to `nr_event`: pads, ROLL, VALUE; then the four instructions, on at the `tbb` `0x8003b53a` |
| `0x800cdbd0` | stock pad note: `push.w; sub sp, #0x18; mov r4, r1; mov r5, r0` | jump to `nr_pad` (which pad a page plays), then the four, on at `0x800cdbda`; the module's repeats enter after the observer |
| `0x8003c5f0` | UI tick: `push; sub sp, #4; mov r4, r0; movw r0, #0xeebc` | jump to `nr_tick`, then the four, on at `0x8003c5fa` |
| `0x80135d40` | ROLL let go: `push; movw r4; mov r5, r0; movt r4` (12 bytes) | jump (+ nop) to `nr_release`: stock only in DJ mode |
| `0x800d9f20` | the kits' jump to their key-query gate `0x83fa5ae5` | jump to `nr_key_gate`, which answers 0 for ROLL from `0x800aee23`, `0x800aef97`, `0x800af06f` while the module runs and goes on to the kits' gate otherwise |

The module (`note_repeat.c`, Zig 0.13.0 `-Os`, 3.7 KB with its state) goes in a new boot copy row in an 8 KB
slot at **`0x83FDC000`-`0x83FDE000`**, the top of the room pad FX was given (pad FX keeps
`0x83FC9000`-`0x83FDC000`, 76 KB for its planned ~15 KB). 39 SHA-256 guards cover the stock code it calls or
relies on; the builder also checks every patched site and recognised call site byte for byte, that nothing
branches into the displaced bytes, that no row or other fork module overlaps the slot and nothing refers to
it.

### 3.4 Cost (measured in Unicorn, instructions)

| | v9.46 | here |
| --- | --- | --- |
| UI tick, nothing rolling | 41 | 67 |
| a key event / a pad press | 1227 / 7036 | 1311 / 7235 |
| key-held query (other keys) | 55 | 60 |
| four pads at 1/64: a tick / a repeat | — | about 560 / about 1700 more (two stock pad notes) |

In the UI task that is well under 1% of the CPU. Not measured: SMPL TASK's work per repeat (voice start and
first charge), the same as tapping the pad that fast. Voices: a repeat cuts the pad's last voice with the
stock 64-frame declick, or, for a GATE pad with a Release, lets it ring out while the new one starts.

## 4. Checked in the emulator (not on hardware)

`python synth/test_note_repeat.py OUT_DIR` (71 checks; the parent and the image booted with their static
constructors, the TOP page made on page entry; the UI dispatcher, DOOM OS's filter, TOP's key and pad
handlers, the generic key handler, the page pad handler, the stock pad note, the UI tick, the pad and project
getters and setters, the popup, the key light and its bytes on the chip link, the key query through the
kits' gate, and the pattern recorder's pad-note path run for real):

- timing: every division at 60, 87.5, 120, 140, 174, 300 BPM (2880 repeats) each at the first tick at or
  after its exact time; 2000 repeats at 1/64, 133.37 BPM without drift; UI ticks late and bunched (1-9 ms
  gaps) and a 300 ms stall; a tempo change while rolling;
- VALUE steps (both directions, several detents, the ends, two pads), SHIFT + ROLL's change taken;
- ROLL + pad with the pad let go first (and a GATE pad's note-off at the end), pads held when ROLL goes down,
  latch on/off and its light, taps that aren't (a pad, a key, VALUE, a knob), EXIT + ROLL, SUB PAD;
- the follow flag (byte, Edited, the save a second later, ignoring pads play once);
- LOOP pads without GATE get the stock roll (asked for once, also when tapped again), with GATE they re-hit;
- the note-on's roll starts hear "not held" only from their three sites and only while the module runs;
  stock's release handling runs on the parent and in DJ mode only; DJ mode exactly as the parent;
- the pattern recorder gets each repeat as the note-off and note-on of a tap;
- every other path as on the parent: pads, SUB PAD, VALUE turns and presses, SHIFT + ROLL, EXIT + ROLL,
  SHIFT/EXIT + VALUE, HOLD + pads, knobs, the first hit of ROLL + pad, each key alone, with SHIFT, with EXIT
  and with ROLL held: the same pad events, popups, chip bytes, DOOM OS calls, held keys and page.

Three mutants (no remainder carry, a gate that never fires, the tap rule) are caught. The kit suites pass on
the image; test_start_fix passes on its own release and, as on every stage image, fails only its four
"the start fix is the top stage" checks here. Two builds from different build folders are byte-identical.

## 5. Not known (the hardware test, or later)

- **The UI tick's real rate.** The firmware calls it with 1 every time; if the UI task is busy the repeats
  come late (never drifting). How even they sound is the main thing to hear.
- SMPL TASK's latency and CPU per repeat at fast divisions with several pads, and voice stealing then.
- **DOOM OS's recorder:** whether recording in DOOM OS's screens takes the repeats (they go below DOOM's
  page code). The stock pattern REC takes them (emulator).
- Pads with Polyphonic bit 5 (ignore a re-hit while sounding) repeat only when the sound has ended.
- Chromatic mode (pads as notes) and the kit pages don't repeat in this build (their pads don't go through
  the stock pad note's page calls).
- The latch light inside DOOM OS's screens, where ROLL blinks for solo.
- Whether the REC page's own ROLL + VALUE (note shift in a scale while recording) is missed: VALUE with ROLL
  held is the module's now.

## Build

```sh
python synth/build_note_repeat.py PATH/kits-v9.46-test3/SP404MKII_APP1.bin OUT_DIR --zig PATH/zig.exe [--build-dir DIR]
python synth/test_note_repeat.py OUT_DIR [SECTIONS]
```

Stock APP0 must sit beside the input APP1; keystone, unicorn and capstone on PYTHONPATH; Zig 0.13.0.
