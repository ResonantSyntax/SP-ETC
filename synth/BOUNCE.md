# Bounce in place, stage 3: a pad through its effects, to a new pad or in its place

Hold RESAMPLE and tap a pad that holds a sample. The SP plays that pad once (or twice for
LOOP), records it through its effects exactly as you hear it, and cuts the take to the exact
frame. **TO PAD** puts the result on the first empty pad and leaves the original alone.
**REPLACE** puts it on the pad itself and keeps the original on the first empty pad; **UNDO**
swaps them back.

This is a test build on the published Sound Generator + Kits v9.46 (kits plus the RESAMPLE start
fix). It supersedes stage 2 (bounce-2-test1, which never ran on the unit) on the same sites, plus
one more. Emulator-checked only; the next hardware round covers stage 2 and stage 3 together.
Stage 1 is the bounce probe ([BOUNCE_PROBE.md](BOUNCE_PROBE.md)).

Background: the bounce-in-place study, `analysis/bounce_in_place/REPORT.md` (§2–§4, §7, §9),
outside this repository.

## Using it

1. Hold **RESAMPLE** and tap a pad that holds a sample. This works from any screen: pressing
   RESAMPLE opens the RESAMPLE screen, and it works on that screen too.
   - Without RESAMPLE held, a sample pad on the RESAMPLE screen still just plays, as stock.
   - Tapping an empty pad while holding RESAMPLE still picks a normal resample destination.
2. A popup shows the target and the mode:

   ```
   BOUNCE A-1>A-9          REPLACE A-1
   NO TAIL                 NO TAIL
   ```

   - Turn **VALUE** for the mode: NO TAIL, TAIL or LOOP. Turning past either end stays on that
     end.
   - Press **VALUE**, or turn VALUE with **SHIFT** held, for the target: TO PAD (`BOUNCE A-1>A-9`)
     or REPLACE (`REPLACE A-1`).
3. Press **REC** to start, or **EXIT** to back out (`BOUNCE CANCELLED` / `NOTHING CHANGED`).
4. The SP stops every sound, waits for silence (`WAIT SILENCE`, at most 10 s), then plays the
   pad and records. The popup counts (`NO TAIL 37%`, `LOOP 37%`, `TAIL 2.4s`).
5. At the end:
   - TO PAD: `BOUNCED A-1` / `ON A-9`.
   - REPLACE: `SWAPPING`, then `REPLACED A-1` / `ORIG ON A-9`.

**EXIT** cancels at any point until the take is being saved. Nothing is written, and every
setting the run changed comes back. While a bounce is set up or running, every other key, knob
and pad is ignored, so nothing else can sound in the take.

The first bounce after power-on starts on TO PAD and NO TAIL. After that the setup popup starts
on the target and mode you used last; this is kept in RAM only.

### UNDO

On a pad you replaced since power-on, the same gesture offers the undo first:

```
UNDO BOUNCE?
ORIG ON A-9
```

- **REC** swaps the two pads back: `UNDONE A-1` / `BOUNCE ON A-9`. The original is back on its
  pad, bit for bit, with every setting it had. The bounce stays on A-9, as after TO PAD.
- **EXIT** leaves both pads as they are.
- Press **VALUE** (or SHIFT + VALUE) to bounce the pad again instead (TO PAD or REPLACE).

UNDO goes back one REPLACE per pad. It is kept for the last eight REPLACEs, in RAM. It is offered
only while both pads still hold the same samples: if either was deleted, replaced or recorded
over, the gesture shows the normal setup.

**After power-off** there is no UNDO. The original is still on the pad the done popup named
(`ORIG ON A-9`), with its own settings except PAD LINK (off; see below). To put it back by hand:

- copy that pad back onto the replaced one with the SP's pad COPY (this overwrites the bounce),
  or
- move it there with the SP's pad MOVE: moving a pad onto a pad that holds a sample exchanges
  the two, which keeps the bounce (stock `0x800691a0` calls the same exchange, mode 0).

Then set PAD LINK on the original again if it had one.

### The destination

The scratch pad (TO PAD's destination, REPLACE's home for the original) is the first empty pad
after the source in its bank, wrapping around inside the bank. If the bank is full, it is the
first empty pad of banks A to J. Protected banks are skipped. With no empty pad anywhere, the popup
says `NO EMPTY PAD` (unless the pad offers UNDO).

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
- Exact lengths for BPM SYNC loops (study §7.5) are not in this build. Such a loop is stretched
  to the bank tempo inside SMPL CHARGE TASK, out of the module's sight; a stretched pass need not
  be a whole number of frames, and whether the stretcher repeats exactly is unknown. They stay
  TAIL ONLY until the unit shows how they behave.

### What ends up in the take

The bounce records what RESAMPLE records: the main mix after the bus effects and the master
effects (BUS 3/4), before the output volume. Only the pad itself sounds:

- **Other sounds:** the run posts ALL SOUND OFF and the sequencer's sound off, and waits for
  silence. A pattern or the looper must be stopped first (`STOP PATTERN FIRST`,
  `STOP LOOPER FIRST`); one that starts during the run ends it with the same popup, and the take
  is discarded.
- **Notes:** while a bounce owns the recorder, every pad note-on but the run's own trigger is
  dropped where all of them meet, at the stock pad-event dispatcher (`0x800bef10`): MIDI notes
  (the stock MIDI note-on posts them there), rolls, the sequencer. Note-offs pass.
- **The input:** EXT SOURCE is switched off from REC until the end, through the stock setter
  (settings 0x25), which sends input volume 0 to the effects chip; it is switched on again at the
  end. If something switches it on during the take (the MIDI EXT SOURCE note runs in the MIDI
  task, not through the page), the run switches it off again and discards the take:
  `INPUT TURNED ON` / `NOTHING CHANGED`. During the silence wait it is just switched off again.
- **PAD LINK:** the source leaves its PAD LINK group for the run, so linked pads do not play
  along. (Stage 2 recorded them; with REPLACE they would sound twice afterwards.) The group comes
  back, and is saved, before the take is.
- **ROUTING** (INPUT SETTING) must be Mix; otherwise `BOUNCE FAILED`.
- **Level and quality:** the take is recorded at the RESAMPLE screen's record level (CTRL 3)
  and the REC SETTING resolution, as any resample. This build does not set them. The hardware
  test includes a level check.

### The bounced pad's settings

The stock finalize gives the new pad the same settings as any new resample (`0x800cfa68`), and
ORIGINAL BPM as any resample sets it (REC BPM, which the run sets to the source bank's tempo).
Then the run sets the exact window and the settings below, through the stock pad setter, and
saves. Each parameter's meaning was read in the stock code first: the setter's conversion
(`0x8001a570`) for ranges and units, the per-voice update (`0x800a2c98`) and the renderer for what
playback does with it, the firmware's own label table (`0x800c30d8`) for names, Roland's
reference manual for VINYL MODE.

| Group | Parameter (id) | The bounce gets | Why |
| --- | --- | --- | --- |
| performance | GATE (0x6a), MUTE GROUP (0x6d, 0..10), Roll (0x7b, 0..10), Polyphonic (0x70) | the source's | how the pad is played, not what it sounds like. Polyphonic is a bit field: bit 5 is the poly one-shot (the setter clears it when GATE or LOOP goes on), bits 1–2 the stretch (VARI) mode, unused at the bounce's own rate. It is copied first, so the stock rule applies as for the source |
| performance | TEMPO SYNC (0x6e) | the source's | with ORIGINAL BPM = the render tempo, the bounce plays unstretched at that tempo and follows a tempo change as the source does |
| performance | VINYL MODE (0x77) | the source's with TEMPO SYNC on, else 1 (the stock default) | sync needs VINYL MODE off (the BPM SYNC light is forced off while it is on); with it on, pitch and speed stay tied and VARI processing is never used, so the bounce plays its file untouched |
| performance | LOOP (0x6b) | NO TAIL: the source's; LOOP: on; TAIL: off | the take is a loop in LOOP mode and one pass plus a tail in TAIL mode |
| performance | loop point (0x71), loop flag 0x72 ("TOP") | NO TAIL of a loop: the source's offset from START and its flag; else START, off | the bounce repeats from the same place as the source |
| performance | PAD LINK (0x79, 0..10) | TO PAD: off. REPLACE: the source's | TO PAD in the source's group would trigger the source with it. After REPLACE the bounce takes the source's place and the parked original leaves the group (UNDO puts it back) |
| printed | VOLUME (0x69, 0..127) | 127 | the stock default; the source's level is in the take |
| printed | PAN (0x78, 13..115) | 64 | centre: both channel gains at unity in the per-voice update |
| printed | PITCH (0x73, semitones), FINE (0x74, 1/100 semitone) | 0, 0 | the pitch ratio 2^((PITCH + FINE/100)/12) = 1 |
| printed | SPEED (0x76, 1/100 %) | 10000 | 100 % |
| printed | PLAY (0x75) | 0 | forward; bit 0 is reverse |
| printed | BUS FX Assign (0x7a) | 0, DRY | the renderer routes 0 through DRY Routing. 1 (BUS 1) is the stock default for every new pad, so a stage 2 bounce would have played through the bus effect a second time |
| printed | Attack (0x7d), Hold (0x7e, 1..100 %), Release (0x7f) | 0, 100, 0 | the stock envelope page sets these three from CTRL 1–3 (`0x800f5d10`): Hold is the envelope's hold, so it is printed, not a performance setting (the study listed it under performance) |
| other | everything else (BUS Effect Asgn 0x6c, 0x7c, the DJ and extended blocks) | as any new resample | 0x6c's role is not identified; the finalize resets the extended block (0x8e–0x9d) and the tempo-synced modulation (0x8a–0x8c, off) |

The source's own settings are not changed, apart from LOOP and PAD LINK during the run, which come
back.

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

These stay in bounce-3-test1: this round is the first time the timing runs on the unit, and T3
reads L and M from every bounce. A REPLACE shows them on the replaced pad; the parked original
keeps its own name. The release names the pads instead (for example the source's name plus
` BNC`), once the numbers have done their job.

### When it fails

| What happens | The run | The popup |
| --- | --- | --- |
| EXIT in the setup, the standby, the silence wait or the take | discards the take (cancel 0x1a, or 0x18 in standby), restores everything | `BOUNCE CANCELLED` / `NOTHING CHANGED` |
| EXIT while the take is saved or the pads are swapped | ignored: these steps run to the end | |
| the input never quiet for 200 ms in 10 s | discards | `FX STILL RINGING` |
| a pattern or the looper running, or starting | refuses, or discards | `STOP PATTERN FIRST`, `STOP LOOPER FIRST` |
| EXT SOURCE switched on during the take | discards | `INPUT TURNED ON` / `NOTHING CHANGED` |
| a protected bank (REPLACE from it, or a source the run would have to change) | refuses before anything is set | `BANK PROTECTED` / `NOTHING CHANGED` |
| the standby, the take start or the voice not coming (1–3 s), ROUTING not Mix, a mono recorder | discards | `BOUNCE FAILED` |
| the stock recorder ends the take itself: the card full or the 16-minute budget spent (error −0x3e, −0x78, −0x80), its write ring overrun (−0x79) | stops writing at once (it writes only while the stock gate would), posts nothing, waits for the stock finalize, which keeps what it had on the scratch pad; no exchange | `STORAGE FULL` or `BOUNCE FAILED`, with `PART ON A-9` or `NOTHING CHANGED` |
| the finalize leaves the pad empty, or START/END do not take | no exchange | `BOUNCE FAILED` |
| the exchange does not show both pads with their samples swapped, or does not finish within 10 s | no UNDO record | `SWAP FAILED` / `CHECK A-1 A-9` |
| an UNDO whose pads changed before REC | nothing posted | `CANNOT UNDO` / `PADS CHANGED` |

**What REPLACE guarantees, and what it does not.** REPLACE is the stock exchange, command 0x40d,
which SMPL TASK runs as `0x800a6c30(gSmplMgr, source, scratch, 2)`. It closes the sample manager's
preview files, stops both pads' voices and unloads them, renames the files through `B:/tmp.SMP`
(scratch → tmp, source → scratch, tmp → source; the results are not checked, and if the source's
file cannot be opened the last two renames are skipped and the scratch file stays parked as
`B:/tmp.SMP`), swaps the two pads' parameter records, names and extended blocks in RAM, reloads
both pads (one whose file does not load is cleared), and saves the pad parameters. It always
reports success. The run therefore checks the result itself: a recorder target write posted
behind the exchange in the same FIFO command ring marks its end, and then both pads must hold
samples with each other's former size and channels. That catches a swap that did not happen; it
cannot tell two files of the same size apart.

It is **not atomic**. The pad parameters are saved only after the renames and reloads, so a power
loss during the exchange can leave the files and the parameters out of step, or a file parked as
`B:/tmp.SMP` (which the next exchange deletes). The source's file is renamed second: until then
the original is untouched in place. The stock pad exchange has the same risk. Outside the
exchange the run saves after each step (the bounce's settings before the exchange, PAD LINK after
it), so a power loss there leaves pads that match their files; at worst the bounce still has the
stock new-sample settings, or the moved PAD LINK is lost. A power loss during a take can leave the
source's LOOP or PAD LINK as the run set them.

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
  to 1, and the run sets it back to 1 when it ends. The module writes only while the stock gate
  itself would (sub-state `+0x24e` = 2, error word `+0x250` = 0), so it never races a stock
  finalize.
- **The stock finalize:** at REC_STOP the engine's first-sound position is "none" (−1), so
  neither the stock trim nor the start fix moves START. The finalize still snaps START to a zero
  crossing and resets every pad parameter. After it, the run sets START, END and the loop point
  through the stock pad setter (`0x800da720`, in frames). Project parameter 0xfb (the setter's
  zero-cross snap) is off for those three calls.

The file holds L frames of silence before START (plus the stock 384-frame pre-roll before that)
and up to 32 frames after END; a take is never shorter than 1,000 frames (the stock pad loader's
minimum). Only the window plays.

## What changes

| Site | v9.46 | Now |
| --- | --- | --- |
| `0x0001d090` | audio task, TX: `mov.w r1, #0x1000; mov r0, r5; bl 0x1c2d0` | jump to the tx bridge: the same mixer call, `bnc_tx`, back to `0x1d09a` |
| `0x0001d0c2` | audio task, RX: `mov.w r1, #0x800; bl 0x1ca80; b 0x1d05c` | jump to the rx bridge: while a bounce owns the recorder, feed enable `0x805917c4` = 0; the same feed call, `bnc_rx`, the loop head `0x1d05c` |
| `0x8006b950` | popup tick (UI task, every 1 ms), first four instructions | jump to the ui bridge: `bnc_ui`, the four instructions, back to `0x8006b95c` |
| `0x800bef10` | pad-event dispatcher: `ldrb r1, [r0]; cmp r1, #0xa0; bhi 0x800bef1c; b.w 0x80018590` | jump to the gate bridge: `bnc_gate(event)`; 0 returns to the caller (the event is dropped), else the four instructions |
| `0x80223474` | RESAMPLE page vtable +8 (the page's event filter) = DOOM OS's `0x6031c8f9` | `bnc_event`, which hands every event it does not take to DOOM OS's filter |

- The audio bridges use no stack, so the mixer and the feed run at their stock depth. The gate
  bridge pushes two words around one call; idle, it adds 20 instructions to a pad event.
- The run itself goes in the popup tick, from the UI task, the same context as the stock
  RESAMPLE page's handlers. It posts the stock recorder commands (`0x800e25c0`: 0x14 standby,
  0x17 start, 0x18 stop, 0x1a cancel, 5 and 0x2a sound off, 0xd save) and the exchange (0x40d),
  and writes the recorder target (`0x800d48e8`) for the destination and the exchange's fence.
- It sets the destination as the stock pad handler does: settings 0x1a, recorder target 0/1/7.
- It pins and restores on every path: REC length (settings 0x24, to FREE), END Snap (0x59, off),
  REC BPM (0x1b, the source bank's tempo), EXT SOURCE (0x25, off), and on the source LOOP and
  PAD LINK.
- It triggers the source through the stock pad note (`0x800cdbd0`, velocity 127, mode 1); the gate
  lets that one note through by its pad, whatever velocity FIXED VELOCITY gives it.
- **Memory:** the bridges and the module (`bounce.c`, Zig 0.13.0 `-Os`) go in a 20 KB slot at
  `0x83FE8000`, below the CPU meter's test slot (`0x83FED000`) and the start fix's row
  (`0x83FEF000`): a boot copy row for the bridges, code and constants, and a zero-fill row for the
  module's state, so its zeros take no flash. APP1 stays below the kit PCM planning boundary
  (`0x60376000`). The builder checks that no row overlaps the slot and that nothing in the input
  refers to it.
- **Guards:** every patched site is checked against its exact v9.46 contents. 79 spans the module
  calls or relies on are checked byte for byte (SHA-256 in the builder), plus 21 jump-table
  entries. Stage 3 adds the pad-event dispatcher and its ring, the pad note and the note-on's PAD
  LINK loop, command 0x40d and the exchange with its file and parameter swaps, the whole pad getter
  and setter with its conversions and protect test, the new-sample defaults, the envelope page, the
  renderer's routing and the per-voice update, the recorder's overrun, error word and drain, and
  the EXT SOURCE setter case with the input volume. All are stock 5.52 bytes in v9.46 except the
  four marked v9.46 (the start fix and DOOM OS's filter).
- **Branch scan:** no direct branch anywhere in the ITCM or SDRAM code lands inside a patched
  span.
- **Cost (emulator):** about 50 instructions per TX+RX block pair when idle; up to about 2,600
  while bouncing, plus the stock engine writer that the stock gate would call anyway; up to about
  8,000 while a source with no onset is still being searched (its first 100 ms): about 1% of a
  block.

## Reproduce

From stock 5.52, after the v9.46 commands in [KITS.md](KITS.md#reproduce) (the start fix stage
included):

```sh
python synth/build_bounce.py out/kits-v946-final/SP404MKII_APP1.bin out/bounce --zig /path/to/zig
python synth/test_bounce.py out/bounce
```

bounce-3-test1 is APP1 `59e061cf…221d` (3,103,744 bytes). It comes out the same on the published
v9.46 (`7b5fbcb4…684a`) and on a clean rebuild of every stage from stock 5.52 (v9.5 `d0919e40…`,
v9.6 `1b2d50e0…`, kits `88384c3c…`, start fix `7b5fbcb4…684a`), and two builds are byte-identical.

## Checks (emulator)

`test_bounce.py` boots the built image in Unicorn the way its scatter loader does. Stock code runs
for real: the recorder feed behind the RX bridge, the pad note and the pad-event dispatcher behind
the gate bridge, the pad parameter getter and setter (with their conversions, protect test and
side effects), the pad name, SMPL TASK's command dispatcher for 0x40d with the exchange and its
parameter swap, the settings setter for EXT SOURCE, the stock MIDI dispatcher, the popup function
and the page's vtable.

Modelled:

- SMPL TASK: standby, REC_START, the finalize (with a stock-like snap of START), cancel, sound
  off, the command ring's order, a busy task;
- the pad-event ring (a note-on there starts the source's voice), the files on the card (renames,
  loads, a failed rename);
- the source pad's voice, which renders the pad's frames into the DRY stems from the first block
  after its trigger;
- the effects chip: RX = the record mix L frames later, optionally with gain, an echo, noise, or
  music on the input while EXT SOURCE is on;
- the eDMA positions (reads jitter by one frame), the recorder engine's writer (it keeps the
  take, and can fill its ring), and the settings, project and system parameter stores.

The checks (373 cases):

- **Static:** only the header, the five sites and the appended tail differ from v9.46. The
  scatter table is v9.46's rows plus a copy row and a zero-fill row; APP1 ends below the PCM
  planning boundary; every guard holds.
- **Bridges, against the parent's own instructions:** the mixer's arguments and stack depth; the
  stock feed's capture, meter and gate call (none while a bounce owns the recorder); the popup
  tick's registers and frame; the pad-event dispatcher's paths for pads, 0xa1, commands and other
  events.
- **Interfaces:** the stock settings setter for EXT SOURCE sends input volume 0 when switched off,
  the input level when on, nothing when unchanged.
- **The gate:** while a bounce owns the recorder, every note-on is dropped and note-offs pass; the
  run's own trigger passes once, by its pad, at any velocity; idle, everything passes.
- **Page filter:** every event type goes to DOOM OS's filter when idle; no gesture without
  RESAMPLE held, with SHIFT, with the recorder busy, outside the RESAMPLE mode, on a modal page,
  with project 0xbf/0xdd set, on an empty pad, or on pad 17+; in setup, keys, knobs and pads are
  swallowed; VALUE clamps; VALUE pressed and SHIFT + VALUE pick the target; EXIT changes nothing;
  the modes each kind of pad offers; the destination search, protected banks skipped; the
  refusals.
- **Whole runs through the bridges:** the take is the RX stream from F0 frame for frame,
  START/END and the loop point land on the window, a dry take is the source's own frames: NO TAIL
  (sharp attack, echo, 125 ms soft start, START/END inside the file, a looped pad, a pitched
  one-shot), TAIL (an echo, a looped pad, never quiet), LOOP (a loop point, a one-shot), L ±, D −1
  / 0 / +1, the boot's calibration, bank B, the popups, a tail still ringing at REC, END Snap; the
  commands posted, the settings pinned and restored, the stock gate never running, the name and
  the save.
- **The bounced pad's settings,** read back through the stock getter: performance settings
  copied, printed ones neutral, VINYL MODE with and without TEMPO SYNC, the poly bit under GATE,
  LOOP, loop point and the 0x72 flag per mode, PAD LINK; the source untouched.
- **REPLACE and UNDO** through the real exchange: the commands in order; the source out of its
  link group while triggered; the original's file, record, name and block on the scratch pad; PAD
  LINK moved; the UNDO record; UNDO offered first, VALUE alone ignored there, VALUE pressed for a
  new bounce; UNDO bit-exact (file, record, name, block); no second UNDO; a changed pad (before
  the gesture, and between gesture and REC); a stale recorder target value; protected banks; a
  rename that fails; a stalled command ring; EXIT while swapping; eight records at most.
- **Leaks:** EXT SOURCE on with music on the input (muted, a clean take, on again), switched on
  during the take (discarded) and during the silence wait (muted again); a MIDI note on channel 1
  through the stock MIDI dispatcher during the take (dropped at the gate, the take clean) and when
  idle (passes); FIXED VELOCITY; a pattern or the looper starting; PAD LINK.
- **Refusals, EXIT and failures:** EXIT during standby, the silence wait, the recording (TO PAD
  and REPLACE), while saving, while swapping; `FX STILL RINGING`; ROUTING not Mix; a mono
  recorder; a pattern started during setup; a source that never sounds; a finalize that leaves
  the pad empty (also with REPLACE); zero-cross snapping on; a standby that never starts; the
  stock recorder ending the take itself (the card full, a full ring, no space; TO PAD and
  REPLACE; with and without a partial take), including a ring that fills on the take's last
  frames.
- **Cost:** instructions in the module per block pair, idle and bouncing, and per pad event.

On the final image every kit suite passes (the kits manifest pointed at this APP1), and the start
fix and bounce probe suites pass on their own builds.

Not checked by the emulator, which is what the hardware test is for:

- the real voice start and stream timing, and the effects chip's delay;
- the SD card: the take's writes, the renames, a full card, a slow card, a power loss;
- that input volume 0 silences every input path the effects chip mixes;
- the stock finalize and exchange themselves on the card, the project reload;
- MIDI from a real port, the screen, popups' lengths and LEDs;
- CPU headroom on the unit.
