# Bounce in place, stage 2: a pad through its effects into an empty pad

Hold RESAMPLE and tap a pad that holds a sample. The SP plays that pad once (or twice for
LOOP), records it through its effects exactly as you hear it, and puts the result on the first
empty pad, cut to the exact frame. The original pad is not touched.

This is a test build on the published Sound Generator + Kits v9.46 (kits plus the RESAMPLE start
fix). It replaces the bounce probe (stage 1, [BOUNCE_PROBE.md](BOUNCE_PROBE.md)): the probe's
measurement code is gone, and the same three hook sites carry the bounce. Emulator-checked only.
REPLACE with undo (swap the bounce onto the source pad through the stock pad exchange) is stage 3.

Background: the bounce-in-place study, `analysis/bounce_in_place/REPORT.md` (§2, §3, §4, §7, §9
step 2), outside this repository.

## Using it

1. Hold **RESAMPLE** and tap a pad that holds a sample. This works from any screen: pressing
   RESAMPLE opens the RESAMPLE screen, and it works on that screen too.
   - Without RESAMPLE held, a sample pad on the RESAMPLE screen still just plays, as stock.
   - Tapping an empty pad while holding RESAMPLE still picks a normal resample destination.
2. A popup shows the source, the destination and the mode:

   ```
   BOUNCE A-1>A-9
   NO TAIL
   ```

   Turn **VALUE** to choose NO TAIL, TAIL or LOOP. Turning past either end stays on that end.
3. Press **REC** to start, or **EXIT** to back out (`BOUNCE CANCELLED` / `NOTHING CHANGED`).
4. The SP stops every sound, waits for silence (`WAIT SILENCE`, at most 10 s), then plays the
   pad and records. The popup counts (`NO TAIL 37%`, `LOOP 37%`, `TAIL 2.4s`).
5. At the end: `BOUNCED A-1` / `ON A-9`.

**EXIT** cancels at any point until the take is being saved. Nothing is written, and every
setting the run changed comes back. While a bounce is set up or running, every other key, knob
and pad is ignored, so nothing else can sound in the take.

The first bounce after power-on starts on NO TAIL. After that the setup popup starts on the mode
you used last; this is kept in RAM only.

### The destination

The destination is the first empty pad after the source in its bank, wrapping around inside the
bank. If the bank is full, it is the first empty pad of banks A to J. With no empty pad anywhere,
the popup says `NO EMPTY PAD` and nothing happens.

### The modes

| Mode | What is recorded | Use |
| --- | --- | --- |
| NO TAIL | exactly one pass of the pad: from its first frame for as long as it plays | loops that must keep their length; one-shots with the effect cut at the end |
| TAIL | one pass and the effects ringing out, to the last frame above about −72 dBFS once 250 ms are quiet (at most 30 s) | one-shots through delay or reverb |
| LOOP | the second pass of the pad: the pad loops, and the take is the pass that already carries the first pass's delay and reverb tails | seamless loops through time effects |

Whether NO TAIL and LOOP can be exact depends on the pad. "At its own rate" means PITCH 0, FINE
0, SPEED 100%, no BPM SYNC and no REVERSE.

| Pad | Modes offered |
| --- | --- |
| at its own rate, one-shot or loop | NO TAIL, TAIL, LOOP |
| one-shot, not at its own rate | NO TAIL (the voice's own length, to its last non-silent frame), TAIL |
| loop, not at its own rate | TAIL only (the popup says `TAIL ONLY`) |

- A one-shot in LOOP mode loops for the run: its LOOP is switched on before the pad is played
  and switched back off before the take is saved.
- A loop in TAIL mode plays once: its LOOP is switched off for the run.
- A pad with a loop point plays START to END first, then loops from the loop point. LOOP mode
  records one loop-point-to-END pass.

### What ends up in the take

The bounce records what RESAMPLE records: the main mix after the bus effects and the master
effects (BUS 3/4), before the output volume. So:

- **Other sounds:** the run posts ALL SOUND OFF and the sequencer's sound off, and waits for
  silence. A pattern or the looper must be stopped first (`STOP PATTERN FIRST`,
  `STOP LOOPER FIRST`). MIDI notes sent to the SP during a bounce would be recorded.
- **The input:** with EXT SOURCE on, whatever is on the input is recorded too. If the input
  never falls below about −72 dBFS, the silence wait ends with `FX STILL RINGING`.
- **ROUTING** (INPUT SETTING) must be Mix; otherwise `BOUNCE FAILED`.
- **Level and quality:** the take is recorded at the RESAMPLE screen's record level (CTRL 3)
  and the REC SETTING resolution, as any resample. This build does not set them. The hardware
  test includes a level check.
- **PAD LINK:** a linked pad plays along and is recorded, as when you hit the pad.

### The new pad

The stock finalize gives the new pad the same settings as any new resample: default VOLUME,
PAN and so on, and ORIGINAL BPM = the source bank's tempo. Then the run:

- sets START, END and the loop point to the exact window;
- switches LOOP on after LOOP mode and after NO TAIL of a looped pad;
- names the pad with the run's numbers for the hardware test (below);
- saves.

Copying the source's other performance settings (GATE, MUTE GROUP and so on) is stage 3.

## Frame-exact: how

The audio task renders each TX block of 64 frames for the effects chip (mixer `0x1c2d0`) and hands
each received RX block to the recorder feed (`0x1ca80`). The two audio bridges (as in the probe)
count both and call `bnc_tx` after the mixer and `bnc_rx` after the feed.

- **T0:** a voice renders whole 64-frame blocks. T0 is the TX frame that starts the block in
  which the source pad's new voice first renders. The renderer's own test is used: the stream is
  set, its chunk index isn't 0xff, and the voice's pad index is the source.
- **F0:** the take starts at RX frame F0 = T0 (one pass later in LOOP mode). From there the RX
  frames go straight to the recorder engine's stereo writer. The last four RX blocks are kept,
  so F0 may lie behind the block being processed. File frame *k* of the take is RX frame
  F0 + *k*.
- **L:** the round trip through the effects chip, in these frame counts. START = F0 + L in the
  file, END = START + the window.
  - **Onset:** measured as in the probe. L = the first RX frame above −48 dBFS (128) minus the
    first TX frame above −48 dBFS (2048), searched within 100 ms of T0. It is used when it lies
    within 6 frames of the estimate, modulo 64.
  - **Estimate:** this boot's last onset L that agreed with the estimate within 3. Otherwise
    138.5 − (P mod 64), taking the candidate nearest 75 and rounding. P is the eDMA phase (TX
    line 3 read position minus RX write position, in frames) averaged over the silence wait.
  - **Basis:** T1 read L − 64 D + (P mod 64) as 138 and 139 on two boots, with L 77 and 73.
- **The stock recorder never writes:** before every feed call the RX bridge clears the feed's
  gate enable (`0x805917c4`) while a bounce owns the recorder. Every stock standby sets it back
  to 1, and the run sets it back to 1 when it ends.
- **The stock finalize:** at REC_STOP the engine's first-sound position is "none" (−1), so
  neither the stock trim nor the start fix moves START. The finalize still snaps START to a zero
  crossing and resets every pad parameter. After it, the run sets START, END and the loop point
  through the stock pad setter (`0x800da720`, in frames). Project parameter 0xfb (the setter's
  zero-cross snap) is off for those three calls.

The file holds L frames of silence before START (plus the stock 384-frame pre-roll before that)
and up to 32 frames after END; a take is never shorter than 1,000 frames (the stock pad loader's
minimum). Only the window plays.

### The pad's name (test build)

The bounced pad is named with the run's numbers, so a hardware test can read them on the SP:

```
A1 L77 M77 P61.5 D0
```

| Field | Meaning |
| --- | --- |
| `A1` | the source pad |
| `L77` | the L used; `L73C` = this boot's calibrated L was the estimate |
| `M77` | the onset-measured L; `M--` = no onset within 100 ms |
| `P61.5` | the mean eDMA phase over the silence wait |
| `D0` | RX blocks minus TX blocks counted since boot |

## What changes

| Site | v9.46 | Now |
| --- | --- | --- |
| `0x0001d090` | audio task, TX: `mov.w r1, #0x1000; mov r0, r5; bl 0x1c2d0` | jump to the tx bridge: the same mixer call, `bnc_tx`, back to `0x1d09a` |
| `0x0001d0c2` | audio task, RX: `mov.w r1, #0x800; bl 0x1ca80; b 0x1d05c` | jump to the rx bridge: while a bounce owns the recorder, feed enable `0x805917c4` = 0; the same feed call, `bnc_rx`, the loop head `0x1d05c` |
| `0x8006b950` | popup tick (UI task, every 1 ms), first four instructions | jump to the ui bridge: `bnc_ui`, the four instructions, back to `0x8006b95c` |
| `0x80223474` | RESAMPLE page vtable +8 (the page's event filter) = DOOM OS's `0x6031c8f9` | `bnc_event`, which hands every event it does not take to DOOM OS's filter |

- The audio bridges use no stack, so the mixer and the feed run at their stock depth.
- The run itself goes in the popup tick, from the UI task, the same context as the stock
  RESAMPLE page's handlers. It posts the stock recorder commands (`0x800e25c0`: 0x14 standby,
  0x17 start, 0x18 stop, 0x1a cancel, 5 and 0x2a sound off, 0xd save).
- It sets the destination as the stock pad handler does: settings 0x1a, recorder target 0/1/7.
- It pins two settings and restores them on every path: REC length (settings 0x24, to FREE) and
  END Snap (0x59, off). It also sets REC BPM (0x1b, the source bank's tempo) and puts it back.
- It triggers the source through the stock pad note (`0x800cdbd0`, velocity 127, mode 1).
- **Memory:** the bridges and the module (`bounce.c`, Zig 0.13.0 `-Os`) go in a new boot copy row
  in a 20 KB slot at `0x83FE8000`, below the CPU meter's test slot (`0x83FED000`) and the start
  fix's row (`0x83FEF000`). The builder checks that no row overlaps the slot and that nothing in
  the input refers to it.
- **Guards:** every patched site is checked against its exact v9.46 contents. 55 more spans the
  module calls or relies on are checked byte for byte (SHA-256 in the builder), plus 19
  jump-table entries. The spans cover:
  - the audio task, mixer, recorder feed, gate and stereo writer;
  - standby, REC_START, REC_STOP, cancel, and the start fix's three spans;
  - the command dispatcher and its cases, the popup tick and popup;
  - the settings, project, pad and recorder-target getters and setters;
  - the pattern and looper flags, the RESAMPLE pad handler, and DOOM OS's filter.
- **Branch scan:** no direct branch anywhere in the ITCM or SDRAM code lands inside a patched
  span.
- **Cost (emulator):**
  - About 50 instructions per TX+RX block pair when idle.
  - While bouncing, up to about 2,600, plus the stock engine writer that the stock gate would
    call anyway.
  - Up to about 8,000 while a source with no onset is still being searched (its first 100 ms):
    about 1% of a block.

## Reproduce

From stock 5.52, after the v9.46 commands in [KITS.md](KITS.md#reproduce) (the start fix stage
included):

```sh
python synth/build_bounce.py out/kits-v946-final/SP404MKII_APP1.bin out/bounce --zig /path/to/zig
python synth/test_bounce.py out/bounce
```

bounce-2-test1 is APP1 `7480797c…9f24` (3,103,248 bytes). The stage gives it both on the published
v9.46 (`7b5fbcb4…684a`) and on a clean rebuild of v9.46 from stock 5.52 (the same `7b5fbcb4…684a`),
and two builds are byte-identical.

## Checks (emulator)

`test_bounce.py` boots the built image in Unicorn the way its scatter loader does. Stock code runs
for real: the recorder feed behind the RX bridge, the pad parameter getter and setter, the pad
name, the popup function and the page's vtable.

Modelled:

- SMPL TASK: standby, REC_START, the finalize (with a stock-like snap of START), cancel, sound off;
- the source pad's voice, which renders the pad's frames into the DRY stems from the first block
  after its trigger;
- the effects chip: RX = the record mix L frames later, optionally with gain, an echo or noise;
- the eDMA positions (reads jitter by one frame), the recorder engine's writer (it keeps the
  take), and the settings, project and system parameter stores.

The checks:

- **Static:** only the header, the four sites and the appended tail differ from v9.46. The
  scatter table is v9.46's rows plus one, and every guard holds.
- **Bridges, against the parent's own instructions:**
  - the mixer gets the same arguments at the same stack depth;
  - the stock feed fills the capture buffer and the meter as stock, and calls the gate as stock
    when no bounce owns the recorder, and not at all when one does;
  - the popup tick continues with the stock registers and frame.
- **Page filter:**
  - idle, every event type goes to DOOM OS's filter and its result comes back;
  - no gesture without RESAMPLE held, with SHIFT, with the recorder busy, outside the RESAMPLE
    mode, on a modal page, with project 0xbf/0xdd set, on an empty pad, or on pad 17+;
  - in setup, keys, knobs and pads are swallowed, and other events still reach DOOM OS;
  - VALUE clamps at both ends;
  - EXIT in setup changes nothing;
  - each kind of pad offers its modes, and the mode used last comes back;
  - the destination search follows the order above;
  - the refusals.
- **Whole runs through the bridges.** Each run checks that the take is the RX stream from F0
  frame for frame, that START/END and the loop point land on the window, and that a dry take is
  the source's own frames:
  - NO TAIL: one-shot (sharp attack, echo, 125 ms soft start), START/END inside the file, a
    looped pad, a pitched one-shot (its own length);
  - TAIL with an echo, and of a looped pad;
  - LOOP: a looped pad with a loop point, and a one-shot;
  - L one frame above the estimate, 5 below, and 20 off (not used);
  - D −1 (T1's second boot), D 0, and D +1 (the kept blocks);
  - the boot's calibration used for a later soft start;
  - a source in bank B;
  - the popups in order;
  - a tail still ringing at REC (REC_START comes 200 ms after it dies away);
  - END Snap armed before (off at REC_STOP, restored);
  - TAIL that never falls quiet (stops at 30 s).

  Every run also checks what the SP is left with:

  - the commands posted, in order;
  - the settings pinned and restored;
  - the stock gate never running;
  - the pad's name and the save.
- **Refusals, EXIT and failures:**
  - EXIT during standby, the silence wait and the recording: the take is discarded, never
    finalized;
  - EXIT while the take is being saved is ignored;
  - the source's temporary LOOP comes back;
  - `FX STILL RINGING`;
  - ROUTING not Mix; a mono recorder; a pattern started during setup;
  - a source that never sounds;
  - a finalize that leaves the pad empty;
  - zero-cross snapping on.
- **Cost:** instructions in the module per block pair, idle and bouncing.

Not checked by the emulator, which is what the hardware test is for:

- the real voice start and stream timing;
- the effects chip's delay;
- the SD card writes and the stock finalize itself;
- the screen and LEDs;
- CPU headroom on the unit.
