# Note repeat: ROLL as an MPC-style note repeat

A study of the stock ROLL and two hardware test builds (`note-repeat-test1`; `note-repeat-test2` adds HOLD
for rolls and triplet divisions, sections 6 and 7) on the published Sound Generator + Kits v9.46 (APP1
`7b5fbcb4…684a`: stock 5.52 + DOOM OS 0.6.1 ED5E + the fork). Addresses are 5.52 runtime addresses. **Verified** means read in the code
(Ghidra decompilation and capstone) or, where marked, run in Unicorn; **inferred** means it follows from the
code but wasn't run; **unknown** needs the unit.

What the build does, in short:

| Gesture | Stock 5.52 | This build |
| --- | --- | --- |
| ROLL + pad | loops the first slice of the pad's sound until ROLL is let go | re-hits the pad at its Roll division until ROLL is let go |
| turn VALUE while rolling | halves or doubles the slice at the end of a pass | steps through the Roll divisions and (test2) six triplets, at once; popup `Roll 1/16T` |
| tap ROLL | rolls the current pad if it is sounding (until the next tap) | latch: held pads repeat, ROLL lit; tap again to unlatch |
| ROLL + VALUE press | VALUE's usual press (no ROLL function) | the current pad follows ROLL or ignores it (saved with the pad) |
| HOLD while rolling (test2) | holds the pads that are down | the rolls go on after you let go; hit the pad again, HOLD again or EXIT + ROLL to stop |
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
- **The renderer** (`0x14b88`, audio task) sees the length, sets the voice's position back (its vtable
  slot 0 with the sample's start: inferred to restart it), records its own output into the ring for that many
  frames (fading the last 64), then plays the ring in a loop (`0x8001c2c8`), with a 64-frame fade in and out
  on every pass. The voice's stream stays where the capture left it; when the roll ends the rest of the
  sample plays from there (inferred).

So **a stock roll is one note-on and a looped slice**: the repeats are replays of the first `length` ms of
the voice (envelope included), not new notes. While the pad's voice rolls, the voice manager ignores a new
hit of that pad (`0x800d63c8`: same pad, `0x800d5d98` rolling, return 0).

### 1.2 Timing (verified; run in Unicorn)

`0x80024450` computes the length in **whole milliseconds**:

```
length_ms = trunc(beats[Roll] x 60000 / (voice +0xc x BPM'))     voice +0xc = 1.0 (Init)
BPM' = voice +0x34 (BPM x 100), doubled until it is >= 50 BPM; the per-voice update sets +0x34 from the
       pad's ORIGINAL BPM (0x6f); that it holds the same at voice start is inferred
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
a long sample plays rolls it until the next tap (the two checks, `0x800d8c08` "a slot plays the pad" and
`0x800cd670` "it rolls", are read from the code; the effect on the unit is inferred). EXIT + ROLL turns every roll off. A GATE pad let go while it
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
| four pads at 1/64: a tick / a repeat | — | about 580 / about 1700 more (two stock pad notes) |

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
- **Recording on the unit.** The stock pattern recorder takes each repeat as a tap (emulator, from the pad
  event on). The pattern REC page itself (page 0x18) was only run idle: it plays a pad through the stock page
  pad handler when the pad is inside its range (`0x80111b38`, project 0x9b), and then a repeat starts as
  anywhere else; in that idle state it played nothing, on the parent too. Whether DOOM OS's own recorder
  takes repeats (they go below DOOM's page code) is not known.
- Pads with Polyphonic bit 5 (ignore a re-hit while sounding) repeat only when the sound has ended.
- Chromatic mode (pads as notes) and the kit pages don't repeat in this build (their pads don't go through
  the stock pad note's page calls).
- The latch light inside DOOM OS's screens, where ROLL blinks for solo.
- Whether the REC page's own ROLL + VALUE (note shift in a scale while recording) is missed: VALUE with ROLL
  held is the module's now.

## 6. Test 2: HOLD keeps rolls going (note-repeat-test2)

The user's ask after test1: keep a pad rolling without holding it, with HOLD, "the same idea as HOLD on gated
pads". Stock's HOLD (verified): the generic key handler's HOLD case marks pads that are down as held (settings
10 per pad: 1 down, 2 held); HOLD with no pad newly held lets every held pad go. In the page pad handler,
without SHIFT, a press first goes through `0x801340c8` (from `0x800c829e`): on a held GATE pad it lets the
pad go (note-off from `0x8013418e`) and takes the press; on any other held pad it clears the hold and the
press plays on. DOOM OS uses SHIFT + HOLD (pattern follow).

### 6.1 What it does

- **HOLD** (no SHIFT) while any roll goes on (ROLL held, latched, or a LOOP pad's stock roll): every roll going
  on becomes a **held roll**, popup `Roll Held`. Stock's HOLD runs as well, as always (it holds the pads that
  are down).
- A held roll **goes on** whatever ROLL does (let go, tapped, unlatched) and whatever other pads do. VALUE with
  ROLL held (or latched) steps its division like any repeating pad's.
- It **stops** when:
  - **its pad is hit again**: a press the page plays (the stock pad note from the page pad handler, or SUB PAD
    on the last pad), or one stock's HOLD takes to let that pad go (a held GATE pad). That press is stock's:
    it plays once (a held GATE pad only ends; a LOOP pad's press stops its loop) and starts no roll, even with
    ROLL latched or held. A press that reaches neither (SHIFT + pad on TOP, which plays nothing) leaves it
    alone, as stock's HOLD leaves its held pads alone then;
  - **HOLD** is pressed with only held rolls going on and no pad down: all stop, popup `Roll Hold Off` (stock
    lets its held pads go at the same press). With a pad down, HOLD is stock's (it holds that pad) and held
    rolls stay;
  - **EXIT + ROLL**, either key first (test1 needed ROLL first: holding EXIT, then ROLL, ran stock's all rolls
    off but left the module's repeats and latch going; fixed);
  - DJ Mixer Mode, or the pad set to ignore ROLL.
- **Lights:** a held roll's pad blinks white (key light page 6, as stock blinks a pad) when its bank is the
  current one and the page isn't DOOM OS's (0x5f; DOOM OS paints the lights there); HOLD is lit (page 0, as
  stock lights it for held pads). Both are written again each tick (the light writer sends only changes).
  When held rolls end the module asks stock to repaint pads and keys (`0x802496f0` |= 2, |= 0x10, the
  request stock's own code sets); DOOM OS's light hook (`0x800d5370`) handles it as it does any other.
- **Stock:** HOLD with nothing rolling, SHIFT + HOLD, HOLD in DJ mode.

### 6.2 Build

No new patch site: HOLD comes in at the UI dispatcher like ROLL and VALUE, and the hit that stops a held roll
at the stock pad note. The module recognises one more caller of the pad note, stock's HOLD let-go
(`0x80134193`; six recognised call sites), and has 42 guards (three new: stock's per-pad HOLD `0x801340c8`,
the UI tick's hand-off of the light requests `0x80182bc8`, the light updater `0x800d5370`). Module 4.6 KB with
the triplets, same slot. Cost (Unicorn, instructions; v9.46 / test2): idle UI tick 41 / 71, a key 1227 / 1313, a pad press
7036 / 7353, HOLD with nothing rolling 4972 / 5160; a tick with a held roll and no repeat due 575.

### 6.3 Checked in the emulator (not on hardware)

`test_note_repeat.py` (section `hold`, and additions elsewhere): latched pad + HOLD (popup, blink and HOLD
light on the chip link, stock's hold state 2), it goes on after the pad, through unlatching and another pad;
hitting the pad again (one stock press, no new roll though latched; the repaint request); a GATE pad (stock's
HOLD lets it go: one note-off, as on the parent); SHIFT + pad leaves it going; SUB PAD stops it; ROLL held +
tap + HOLD + ROLL let go, then HOLD again (`Roll Hold Off`); two pads; EXIT + ROLL both orders; HOLD with a
non-rolling pad down; a LOOP pad's held stock roll (kept unlatched, turned off by the hit); DOOM OS's page (no
blink, HOLD relit) and back; stock's hold states as on the parent; idle asks for no repaint. HOLD added to the
DJ-mode script and to the pass-through scripts (a pad held and let go by HOLD and by its pad, SHIFT + HOLD):
all as on the parent. 89 checks with HOLD (test1's 71 still pass), 97 with the triplets (section 7); the new
EXIT-first check fails on test1, as expected. Six mutants are caught: held rolls not kept, no stop from stock's HOLD let-go, a second note-off on
it, HOLD stopping held rolls with a pad down, blinking on DOOM OS's page, no repaint request.

### 6.4 Not known

- How the blink looks on the unit: stock rewrites a pad's light when it plays or the screen changes, and the
  module writes the blink back at the next tick, so a short flash each repeat is possible. Unicorn checks
  the bytes and the repaint request, not the LEDs or stock's repaint itself.
- Whether DOOM OS shows something on HOLD's light (its pattern follow) that the held-roll light covers.
- Held rolls on pages whose pads don't use the stock pad note (chromatic, kits): they go on there, and their
  pads' presses there don't stop them.

## 7. Test 2: triplet divisions (note-repeat-test2)

The user's second ask: triplets (trap hats use 1/16T and 1/32T). Stock's Roll list (0x7b, 0..10) has none.

### 7.1 What it does

- **VALUE** (ROLL held, or latched with a pad repeating) steps through sixteen divisions, slowest first,
  stopping at the ends: 1/2, 3/8, 1/2T, 1/4, 3/16, 1/4T, 1/8, 3/32, 1/8T, 1/16, 3/64, 1/16T, 1/32, 1/32T,
  1/64, 1/64T (2 beats down to 1/24). Popup `Roll 1/16T`. A triplet is two thirds of its straight division
  (1/16T = 1/6 beat: 83.3 ms at 120 BPM). Everything else (the change at once, the carried remainder, tempo
  changes) is as for stock's ten.
- **1/64T stays:** 8.3 ms at 300 BPM. On the emulator's 1 ms tick every repeat of every division comes within
  a millisecond of its exact time, without drift. On the unit the UI tick's rate is unknown (section 5); a
  slow tick would bunch 1/64T first.
- **SHIFT + ROLL** keeps its stock list and behaviour.

### 7.2 Where the choice is kept

- **Roll (0x7b) always holds a stock value 1..10**, so stock reads it as before (SHIFT + ROLL's popup, a LOOP
  pad's stock roll, patterns). For a triplet it holds the nearest stock division by ratio (`nr_trip_stock`):
  1/2T → 3/8, 1/4T → 3/16, 1/8T → 3/32, 1/16T → 3/64, 1/32T → 1/64, 1/64T → 1/64.
- **The triplet** is in PADCONF reserved byte **0x70, bits 1-3** (1..6 = 1/2T .. 1/64T, 0 none), beside the
  follow flag (bit 0). Bits 4-7 stay free; 0x71-0x7F are not touched (pad envelopes may take them). Stock
  saves, loads, copies, moves and exchanges the byte with the pad and clears it for a new sample.
- **It counts only while Roll holds that triplet's neighbour.** Roll set to anything else drops it: the module
  clears the bits when it next reads the pad (within a tick while the pad rolls). SHIFT + ROLL setting the same
  neighbour while the pad isn't rolling can't be told apart, and keeps it.
- **Saving:** stock's pad setter marks the pads edited when Roll changes and posts no save (run in Unicorn).
  The module marks them itself when only the triplet bits change, and posts the save (0xd) a second after
  the last change, as for the follow flag, **but not while a pad repeats** (a card write in SMPL TASK could
  delay repeats). The follow flag's save waits the same way now. Test1 never saved VALUE's changes itself.
- LOOP pads without GATE keep the stock ring roll at Roll's stock division, so a triplet on one rolls at its
  neighbour.

### 7.3 Checked in the emulator

Section `triplet`, the timing section over all sixteen divisions (16 x 6 tempos x 48 repeats = 4608, the worst
0.98 ms after its exact time), test1's VALUE checks moved to the new list, and the static checks (names, order,
each neighbour the nearest): 97 checks pass on the release; the kit suites as on test1. Mutants caught: the period key without room for the 4 of 1/2T's 4/3, the neighbour
rule, the bits not written, the bits not dropped when Roll changes, the save while a pad repeats.

### 7.4 Not known

- How the fast triplets sound with the unit's real UI tick and SMPL TASK load (1/64T, 1/32T at fast tempos).

## 8. Test 3: chromatic mode (note-repeat-test3)

From the user's test of combined-test3: in chromatic mode the roll ran too fast, and pad 10 never rolled.

### 8.1 Why (run in Unicorn on combined-test3)

A chromatic press reaches the module like any other pad: the chromatic page (0x18) hands it on to the page pad
handler (`0x80111dd2`), which plays it through the stock pad note. So the roll took everything from the pad under
the finger: its Roll, its tempo, LOOP, GATE and the follow flag.
- **Speed:** a pad whose Roll VALUE had set to 1/64 in drum mode rolled 33 times a second.
- **Pad 10:** a pad holding a LOOP sample without GATE asks for the stock ring roll. That waits for the pad to
  sound, but in chromatic mode the voice plays the sample's pad (project 0xC1). So nothing came. A pad set to
  ignore ROLL rolled nothing either.

### 8.2 What it does

- A press the stock pad note plays in chromatic mode (project 0xBF on, not the Sound Generator's page) starts a
  **chromatic roll**: always re-hits, at the tempo the sample's pad follows (`0x80047dd0`, the pad 0xC1 names).
- **One chromatic division** for every chromatic pad: 1/16 from power-on (kept in the module, not saved).
- The pad's Roll, LOOP, GATE and follow flag are not read or written; SHIFT + ROLL's change of a pad's Roll doesn't
  reach chromatic rolls.
- **VALUE** (ROLL held, or latched with pads repeating) steps the chromatic division for all of them at once, and
  with nothing repeating in chromatic mode ROLL + VALUE steps it. Popup `Roll 1/16`.
- **ROLL + VALUE press** in chromatic mode shows the division and toggles no follow flag (the current pad isn't
  the one playing).
- Latched with a chromatic pad repeating, a VALUE turn **with VALUE held** goes on to the page: the chromatic
  page's push-turn (scale, key; chroma-test2). Drum mode keeps test2's ways.

### 8.3 Checked in the emulator

Section `chroma` (5 checks, on the chromatic page, the sample on A-04 at 90 BPM, the other pads at 120): every
pad rolls at 1/16 of 90 BPM, its Roll and byte 0x70 untouched; pad 10 with a LOOP sample without GATE, set to
ignore ROLL, Roll 1/64, rolls the same, no stock roll asked for; VALUE moves two rolling pads to 3/64 at once and
the next roll starts there; ROLL + VALUE press shows it, toggles nothing, saves nothing; latched, VALUE held + turn
is not taken. All 102 checks pass (test2's 97 unchanged). On combined-test3, pad 10's three cases fail as the user
heard (the press plays, no repeats; at 1/64, 33 hits a second).

### 8.4 Not known

- A LOOP sample without GATE as the chromatic sample: re-hits may stop and start it.

## 9. Test 4: a chromatic division per pad (note-repeat-test4)

From the user's test of combined-test4: "last version chromatic roll speed could be changed per pad". Test 3 gave
every chromatic pad one division.

### 9.1 What it does

- Each pad has its own **chromatic division**, kept with the pad in PADCONF reserved byte 0x70, **bits 4-7**: the
  number of steps along VALUE's order from 1/16 (0, the default, is 1/16; 1 is 3/64 ... 6 is 1/64T; 7 wraps round
  to 1/2 ... 15 is 1/8T). It is not Roll, so a drum-mode Roll of 1/64 doesn't make the chromatic pad fast (test 3's
  fix stays), and the pad's Roll, LOOP, GATE and follow flag are still not read or written.
- **VALUE** (ROLL held, or latched with pads repeating) steps each repeating chromatic pad's own division at once;
  with none repeating, ROLL + VALUE steps the last chromatic pad played. Popup `Roll 3/64`. Saved as the follow
  flag is: the pads marked edited, command 0xd a second after the last change once no pad repeats.
- **ROLL + VALUE press** in chromatic mode shows the last chromatic pad's division.
- Stock clears byte 0x70 for a new sample and INIT PARAM clears it (bytes 0x40-0x7F), so those pads start at 1/16
  again; copy, move and exchange carry it with the pad.

### 9.2 The clicks

The user also heard clicks on chromatic rolls. Each repeat stops the note still ringing, as any re-hit does (the
voice manager `0x800d63c8`: chromatic mono stops it for any note, poly for the same note). Run in Unicorn on
combined-test4 with the pad envelope test's re-hit machine: the repeat's note-off (`0x800c0a80`, type 0xC) leaves a
one-shot note alone (the slot must be gated, slot `+0x3c`), and the note-on's stop gives the old voice stock's
1.3 ms declick with RETRIG CUT, or the fade with RETRIG FADE (14 blocks at 19 ms), with or without that note-off,
mono or poly: the same as a tap. So RETRIG on the sample's pad (ENVELOPE page 4, CTRL 2) decides; the module
doesn't change it.

### 9.3 Checked in the emulator

Section `chroma` (7 checks): every pad at 1/16 to begin with, byte 0x70 untouched; pad 10's LOOP, ignore and 1/64
case as in test 3; VALUE while two pads roll moves each to 3/64 at once, kept in bits 4-7 (0x10), the pads marked
edited, the save a second after the rolls end, a third pad still at 1/16, the moved pad at 3/64 next time; VALUE
while one pad rolls moves only that pad; ROLL + VALUE press shows the last pad's division, and with nothing
repeating ROLL + VALUE steps it; latched, a turn with VALUE held is the page's. All 103 checks pass.

## Build

```sh
python synth/build_note_repeat.py PATH/kits-v9.46-test3/SP404MKII_APP1.bin OUT_DIR --zig PATH/zig.exe [--build-dir DIR]
python synth/test_note_repeat.py OUT_DIR [SECTIONS]
```

Stock APP0 must sit beside the input APP1; keystone, unicorn and capstone on PYTHONPATH; Zig 0.13.0.
