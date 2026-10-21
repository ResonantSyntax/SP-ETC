# Bounce in place, stage 3: a pad through its effects, to a new pad or in its place

Hold RESAMPLE and tap a pad that holds a sample. The SP plays that pad once (or twice for
LOOP), records it through its effects exactly as you hear it, and cuts the take to the exact
frame. **TO PAD** puts the result on the first empty pad and leaves the original alone.
**REPLACE** puts it on the pad itself and keeps the original on the first empty pad; **UNDO**
swaps them back.

This is a test build on Sound Generator + Kits v9.46: the kit stage of the published v9.46 plus the
RESAMPLE start fix v3 (the published v9.46 carries v2; see
[KITS.md](KITS.md#start-fix-v3-test-builds-only)). It supersedes stage 2 (bounce-2-test1, which never
ran on the unit) on the same four sites, plus the pad-event dispatcher and, since bounce-3-test2, the
RESAMPLE page's tick. Stage 1 is the bounce probe ([BOUNCE_PROBE.md](BOUNCE_PROBE.md)).

**bounce-3-test5** changes only the image under the bounce. The user found a normal RESAMPLE's
START a few samples after the start of its wave. The cause is the RESAMPLE start fix (v2): it puts
START on the take's first sample above −72 dBFS. The effects chip's return reaches the take with a
quiet lead-in a few frames before that, and the stock finalize then moves START to the nearest zero
crossing (`0x80017200`, called at `0x8017f626`). In an oscillating lead-in that crossing lies inside
it.

- **Start fix v3** puts START 8 frames before the first sample above −72 dBFS (never before the
  take's start): in the silence in front of a lead-in of up to 7 frames, where the zero-cross snap
  leaves it. The engine keeps only the first-sound frame (its writers compare each sample with the
  threshold as they stage it for the card), so the margin is fixed. The code stays 184 bytes with
  the same two entry points, so both jumps keep v2's bytes; 11 bytes of the image change.
- **The bounce module, bridges and sites are test4's, byte for byte.** A bounce never goes through
  the start fix: its take ends with the engine's first-sound frame set to none, and the run sets
  START after the finalize. The builder's guard on the start fix's code now holds v3's bytes.
- **Evidence, dm-404 (real firmware):** A-1's samples are written into its charge, the copy the
  voice plays: 400 zero frames, then `1 −1 2 −2 3 −4`, then a cosine at 3000. The first sample above
  8 comes 6 frames after the first non-zero one. In both builds a bounce of A-1 keeps the run's own
  START after it settles and 5 s later: test4 START 450 = r_start, END 13578 = r_end; test5 458 =
  r_start, 6674 = r_end. The engine's first-sound frame reads −1, and the take holds only zeros
  between START and the lead-in. A normal RESAMPLE of A-1 (first sound k = 151, REC_START 384):
  - test4 START 535 = 384 + 151, on the 3000 sample, with the lead-in cut;
  - test5 START 527 = 384 + 151 − 8, followed by `0 0 1 −1 2 −2 3 −4 3000`.
- **Evidence, Unicorn** (`test_start_fix.py`, 17 checks): a lead-in from 1 LSB crossing 8 five frames
  later, the unit's 7-frame lead-in, a sharp attack, a floor under 8, a first sound after 2399
  frames and mode 2. v2 fails 4 of them; v3 passes all.

**bounce-3-test4** follows the hardware run of bounce-3-test3 (2026-10-19). A LOOP bounce still
clicked at its end with LOOP off, and every bounce's START sat a few frames after the waveform's
first non-zero sample.

- **The return departs from silence before its main delay.** A closed hi-hat bounced NO TAIL read
  `L73 M73 P65.1`: the phase estimate and the matched −48 dB onset agree on the main delay, 73.
  Yet START sat at 457 (384 + 73) and the waveform's first non-zero sample at 450. A pure delay
  cannot put sound before its delay. The effects chip's return pre-rings each attack: about 7
  frames of low-level sound before the main delay. test3 cut the take at the main delay, so the
  start of the attack was lost. A LOOP take, one pass long, then ended inside the next pass's
  pre-ring, which is the click with LOOP off.
- **test4 starts the take where the return departs from silence.** That is the first RX frame
  that is not 0 in the 16 frames before L, counted from the sound's first TX frame that is not 0,
  after 8 silent frames. If no departure is found (a noisy floor, or frames no longer kept), the
  take starts at L. The window stays one pass, so a LOOP take now ends just before the next
  pass's pre-ring. The pad's name shows the departure: `A1 L73-7 M73 P65.1 D-1`. The stock name
  keeps 23 characters, so when the name would be longer (a source on pads 10–16 after a take that
  calibrated the boot) P's tenth is left out and D stays.
- **The trade-off:** layered with its source, the bounce's main attack sits up to the pre-ring
  later, about 7 frames (0.15 ms), which puts the first comb notch near 3.4 kHz. Played alone, or
  in its source's place, nothing changes.
- **The calibration now follows P.** In the same session the LOOP bounce read P62.0, against the
  others' P65.1, and used the boot's stored L73, although its own phase and its onset (M76) both
  said 76. P and D can move within a boot, and T1's relation held through the move: L − 64 D +
  (P mod 64) was 138 for both takes. test4 keeps the boot's calibration as an offset on that
  relation, in 1/16 frames, and applies it to each take's own P and D.
- A recalibration of T1's constant by −7 was ruled out: it contradicts T1's own click readings
  (L77 at P61 D0) and test2's `L72 M72` at P66, since test2's thresholds could only make M early.
- **Evidence:**
  - Unicorn models a return with a low symmetric ring around 73 that departs at 66. test3 starts
    on 73, and its LOOP take's last 7 frames hold the next pass. test4 starts on 66, and its LOOP
    take holds nothing of the next pass.
  - A pure 66-frame return under an estimate of 73: test4 starts on 66 too.
  - P moving from 65.5 to 62.5 within one boot: test3 uses 73, test4 76.
  - dm-404's return is a plain delay of about 65 where the unit's relation gives 74. test4 finds
    the emulator's own start there (`L74-8 M66`); the bounce lines up with its source within a
    frame, sounds for END − START and loops at END − the loop point. Its boots that read
    `L10 M8 P1.0 D-2` (in test2's and test3's runs too) are below the search and start at L, as in
    test3.

**bounce-3-test3** followed the hardware run of bounce-3-test2 (2026-10-19), which found two
faults in a LOOP bounce. Played with LOOP off it clicked at its end, because the end held a little
of the loop's beginning. Layered with its source (PAD LINK) it phased: a constant offset of a few
frames, steady over 30 s, with no effect on.

- **The bounce played on past its END.** Playback does not read START and END directly. It reads
  the pad's charge: SMPL CHARGE's cache entry, charged by `0x800d84f0` from the pad's range at
  that moment. The entry holds up to 80 KB from START, the rest of END − START to stream, and
  END − the loop point as the loop's length. The stock setters only store a new range and mark
  it (`0x800d8b40`); `0x800d7508` charges marked pads again. The stock finalize ends that way:
  the take's range, the mark, the charge. test2 then set START, END and the loop point and
  charged nothing. The bounce kept the take's charge and played the take's length from its new
  START, which ends L + 32 frames past END. In LOOP mode those frames are the next pass's first
  frames: a click with LOOP off, and with LOOP on every loop L + 32 frames too long, drifting
  against the source. test3 marks the pad and charges it again (`0x800d6390`, `0x800d7508`)
  after the window and the settings, as the finalize does.
- **Evidence,** in the full-firmware emulator (dm-404), which runs the real voice, charge and
  recorder code:
  - A stock-recorded noise sample on A-1 sounds for END − START frames and loops at exactly
    END − the loop point (correlation 1.0).
  - Its LOOP bounce on test2, with L 8, sounds for END − START + 39 frames and loops 40 frames
    too long (L + 32). Its range is marked and never charged (file information +0x14 = 1).
    With L 74 the overrun was 106.
  - On test3 the bounce sounds for END − START and loops at exactly END − the loop point, and the
    mark is cleared.
  - The Unicorn checks now record the pad's charge where the stock code makes it, and every
    whole run checks that the bounce's last charge is its final window. On test2 all 14 fail.
  - REPLACE and UNDO were not affected: the stock exchange reloads both pads, which charges them
    afresh. A REPLACE in LOOP mode on test2 sounds for END − START and loops at END − the loop
    point in dm-404.
- **The window started a few frames early.** The user's two bounces at the same P66 read
  `L72 M72` (an earlier bounce, used as the source) and `L69 M69` (the LOOP bounce). T1's
  relation, L − 64 D + (P mod 64) = 138 or 139, puts L at 72 or 73 there. The LOOP bounce
  measured its onset 3 frames early and used it. Two things let that through:
  - **The onset thresholds did not match.** The TX threshold, 2048, assumed stems at full
    20-bit scale. The stems carry 16-bit samples at the capture's scale: in dm-404 a pad of
    full-scale noise peaks at about 8,900 in its stem, and the capture reads the same level. So
    TX's −48 dBFS was really −24 dB, and any attack that is not instant crossed it later than
    RX crossed its own −48 dB. That made M too small by the attack's rise from −48 to −24 dB.
    T1 used clicks, whose attack is instant, so it never showed.
  - **The rule trusted the onset within 6 frames of the estimate, modulo 64.** A 3-frame error
    passed. So could an onset 69 frames off, which looks like another 64-frame block.
  - test3 matches the thresholds (TX 128 and quiet 8, as RX). The estimate is primary:
    138.5 − (P mod 64) + 64 D, T1's relation with D, or this boot's calibration. An onset is
    used only within 1 frame of it, and calibrates the boot only within 1 frame of the phase.
  - In Unicorn, with true L 77: a 32-frame attack, 20 ms attacks with RX +6 and −6 dB, a 10 ms
    attack through an echo with +3.5 dB, and a LOOP pass with a soft start. The test2 rule took
    L 71, 8, 8, 77 and 73. test3 gives 77, and 76 for the level step, which the rule cannot tell
    from T1's one-frame spread. One frame is 21 µs, so its first comb notch is at 24 kHz.
  - dm-404's effects stand-in has its own round trip (65 at P65, where the unit's relation gives
    73), so there test3 aligns to the unit's estimate, about 9 frames off the emulator's.

**bounce-3-test2** followed the first hardware run of bounce-3-test1 (2026-10-19), which found three
bugs:

- **After a TO PAD bounce the effects stopped and the SP jumped to bank A.** The RESAMPLE page's
  tick (`0x8012db58`, run by the page on every screen refresh) compares the recorder's state with
  the state it saw last time (page `+0x1a90`). When it changes, the tick runs the page's state
  handler (`0x8012dcb0`) and then its after-recording routine (`0x8012cbb0`). When the recorder
  goes idle after a take, the routine finishes a stock RESAMPLE. It switches the BUS 1 and BUS 2
  effects off (`0x800bb140`, system parameter 0x276) so the new pad does not play through them a
  second time, and makes the stock pad handler's destination current. Then it waits 300 ms and
  leaves RESAMPLE for the main screen (`0x8012d438`). A bounce records with the stock recorder on
  the RESAMPLE page, so the routine ran after every bounce. A bounce never goes through the stock
  pad handler, so that destination was stale. It is −1 until a stock RESAMPLE picks a pad, and
  the RESAMPLE exit's restore (`0x80134990`) turns −1 into bank A. The state handler did more for a
  bounce: after a standby that ended without a take (EXIT in the silence wait) it switched END Snap
  off, and after any take or standby it stopped every sound and the looper (`0x800dd030`: ALL
  SOUND OFF and LOOPER TASK command 9, the looper's stop `0x8001f820`) and changed the RESAMPLE
  screen's state (settings 0x32).

  test2 adds a sixth site at the start of the tick. From REC until the first tick after the run
  with the recorder idle, the tick bridge gives the page the recorder's current state as the state
  it saw last time. The tick then sees no change from a bounce's standby, take or cancel, and runs
  neither the handler nor the routine for it. A stock RESAMPLE still ends as stock. A first fix
  only skipped the routine while the bounce owned the recorder. That was not enough. On EXIT during
  a take the module lets go of the recorder within a millisecond, and the next tick, up to 16 ms
  later, still saw the take end. In the emulator, with the image's own global objects built and the
  page tick running every 16 ms, test1 ends a bounce of C-1 in bank C with BUS 1/2 off, RESAMPLE left
  and bank A current, as on the unit. The first fix still did that on EXIT during the take, and
  turned END Snap off on EXIT in the silence wait. test2 changes none of them on any path checked.
  (The checks of test1 missed it: until test2 they did not run the page tick during a take.)
- **REC BPM is no longer touched.** test1 set REC BPM (settings 0x1b) to the bank's stored tempo
  for the run and set it back afterwards. REC BPM is the SP's tempo: the stock tempo setter
  (`0x80019820`) writes it, and its own setter retunes the sequencer and the effects chip (system
  parameter 0x275). When the stored tempo differed from the playing tempo, the take ran at the
  stored one, and a tempo message went to the chip each way. Either way the run left two stock
  flags set: `0x80592360`, which the stock RESAMPLE pad handler checks before it takes REC BPM from
  the bank for a bar-length take, and `0x833b80f8`. A stock RESAMPLE with REC length FREE does not
  set REC BPM. test2 leaves it alone, so the bounce renders at the tempo you hear, and ORIGINAL BPM
  is still that tempo.
- **MARK Function = LOOPER refused every bounce** (`STOP LOOPER FIRST` with the looper stopped).
  The module read `0x82e0b71c + 0x39`, which is the looper's *enable* flag: the MARK Function
  setter (system parameter 0x141 = 2) sets it through `0x8001c1a8` whether anything plays or not.
  test2 reads the looper's phase (`+0x101`) instead and refuses only while it plays, records,
  overdubs or waits for a level ([what ends up in the take](#what-ends-up-in-the-take)).
- **A REPLACE ended on `BOUNCED …`:** the run had TO PAD selected when REC was pressed. Only the
  gesture and VALUE (or SHIFT + VALUE) in the setup popup write the target. The emulator now runs
  the gesture, VALUE pressed and REC through the UI task's own dispatcher (`0x8003b530`): VALUE
  arrives as key 0x31, as on the stock SG page, and selects REPLACE, which then runs to
  `REPLACED`. One way to reach REC on TO PAD was that the choice was kept only once a run started,
  so after EXIT or a refusal the next gesture came back on TO PAD. In test2 the target and the
  mode are kept as soon as they are picked. Check the popup's first line before pressing REC.
- The timing matched: L = M on every take, P 65 on that boot.
- The pad name's edited flag is left to the stock name function, which sets the byte at
  `SMPL + 0x1c` itself. test1 also wrote it as a 32-bit word, over the three bytes after it.

test2 also runs a whole-state audit in the emulator ([Checks](#checks-emulator)). A bounce runs
on the image's own global objects. Every write, every page request, every bank or pad change and
every byte to the effects chip is logged. Every parameter is read before and after, and the
objects are diffed byte for byte. Each difference has to be on an allowlist with a reason, and a
stock RESAMPLE of the same pad runs alongside for comparison. Emulator-checked only otherwise; the
hardware test is `analysis/kit_pr1_audit/release/bounce-3-test2/HARDWARE_TEST.md`.

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
on the target and mode you picked last, as soon as you picked them (EXIT does not lose them); this
is kept in RAM only.

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
  silence. A pattern must be stopped first (`STOP PATTERN FIRST`); one that starts during the run
  ends it with the same popup, and the take is discarded.
- **The looper:** MARK Function = LOOPER is fine while the looper is empty or stopped. It is
  refused (`STOP LOOPER FIRST`), and a run it starts during is discarded, while the looper plays,
  records its first pass, overdubs, or is armed to start on a level (its own trigger would fire
  on the bounce). The module reads the looper's phase, `0x82e0b71c + 0x101`, which the LOOPER
  TASK's commands (`0x80070280`) and the looper's audio input (`0x1d634`) set:

  | Phase | The looper | Bounce |
  | --- | --- | --- |
  | 0 | empty (MARK Function = LOOPER enables it here, `0x8001c1a8`) | allowed |
  | 1, 7 | armed: waits for the input level to start the first take, or an overdub | refused |
  | 2, 3 | records the first pass | refused |
  | 4 | the loop buffer full: the task starts playing or overdubbing | refused |
  | 5, 10 | plays (10: an overdub queued for the loop's start) | refused |
  | 6 | stopped (with `+0x102` set: an overdub starts on the next audio block, refused) | allowed |
  | 8, 9 | overdubs (9: to the end of the loop) | refused |

  The mixer (`0x1e248`) plays phases 5, 8, 9 and 10 whether the looper is enabled or not; the
  feed records into it only while it is enabled (`+0x39`, `0x1cb44`). With MARK Function set to
  something else, the stock disable has stopped it (`0x8001f820`: 5, 8, 9, 10 → 6), and only
  those playing phases refuse.
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
ORIGINAL BPM as any resample sets it: REC BPM, which is the SP's tempo during the run (the run
leaves it alone).
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
A1 L73-7 M73 P65.1 D-1
```

| Field | Meaning |
| --- | --- |
| `A1` | the source pad |
| `L73` | the L used: the return's main delay |
| `-7` | the window starts this many frames before L, where the return departs from silence; left out when it starts at L |
| `C` | after L and the departure (`L73C`, `L73-7C`): the estimate included this boot's calibration |
| `M73` | the onset-measured L; `M--` = no onset within 100 ms |
| `P65.1` | the mean eDMA phase over the silence wait |
| `D-1` | RX blocks minus TX blocks counted since boot |

The stock name keeps 23 characters. A longer name loses P's tenth instead of D's end, for example
`A12 L73-7C M73 P65 D-1`.

These stay in the bounce-3 test builds: the timing is being checked on the unit, and T3 reads L
and M from every bounce. A REPLACE shows them on the replaced pad; the parked original
keeps its own name. The release names the pads instead (for example the source's name plus
` BNC`), once the numbers have done their job.

### When it fails

| What happens | The run | The popup |
| --- | --- | --- |
| EXIT in the setup, the standby, the silence wait or the take | discards the take (cancel 0x1a, or 0x18 in standby), restores everything | `BOUNCE CANCELLED` / `NOTHING CHANGED` |
| EXIT while the take is saved or the pads are swapped | ignored: these steps run to the end | |
| the input never quiet for 200 ms in 10 s | discards | `FX STILL RINGING` |
| a pattern running, or starting | refuses, or discards | `STOP PATTERN FIRST` |
| the looper playing, recording, overdubbing or armed, or starting (MARK Function = LOOPER alone is fine) | refuses, or discards | `STOP LOOPER FIRST` |
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
behind the exchange marks its end, and then both pads must hold samples with each other's former
size and channels. The fence holds because SMPL TASK has one queue: the post (`0x800e25c0`, type
0xa4) and the target set (`0x800d48e8`, type 0xa8) both go through `0x800da528`, and the task's
loop (`0x801947c0`) takes messages oldest first, runs 0xa4 commands in the dispatcher
`0x8004d8b8` (the exchange runs to its end inside it), and only then stores the 0xa8 write
(`0x800fb000`). That catches a swap that did not happen; it
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
- **L:** the return's main delay through the effects chip, in these frame counts. START = F0 +
  the window's delay in the file, END = START + the window.
  - **Estimate:** 138.5 − (P mod 64) + 64 D for this take's P and D, plus this boot's
    calibration, rounded. If that is outside 8..300, the candidate 138.5 − (P mod 64) + 64 n
    nearest 75. P is the eDMA phase (TX line 3 read position minus RX write position, in frames)
    averaged over this take's silence wait; D is the RX blocks minus the TX blocks counted since
    boot. P and D can move between takes in one boot.
  - **Onset:** L = the first RX frame above −48 dBFS minus the first TX frame above −48 dBFS
    (both 128: the stems carry 16-bit samples, at the capture's scale), searched within 100 ms
    of T0. It is used only within 1 frame of the estimate. Within 1 frame of the phase alone it
    also calibrates the boot: the onset minus T1's relation, kept in 1/16 frames. A threshold
    crossing moves with the attack's shape and with any level step between the stems and the
    return, so it only settles T1's one-frame spread.
  - **The window's delay:** where the return departs from silence. That is the first RX frame not
    0 in the 16 frames before L, from the sound's first TX frame not 0, after 8 silent RX frames;
    otherwise L. The unit's return pre-rings each attack about 7 frames before L. The search runs
    only when L is above 24, so its frames come after the sound's first TX frame. The unit's L has
    been 69–77; dm-404's boots that read `L10 M8 P1.0 D-2` start at L.
  - **Basis:** T1 read L − 64 D + (P mod 64) as 138 and 139 on two boots, with L 77 and 73. The
    unit has kept to it since: `L72 M72` at P66 with D −1 is 138.
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
minimum). Only the window plays: after setting it the run charges the pad from it, as the
finalize does. test2 did not, and its bounce played into those frames.

## What changes

| Site | v9.46 | Now |
| --- | --- | --- |
| `0x0001d090` | audio task, TX: `mov.w r1, #0x1000; mov r0, r5; bl 0x1c2d0` | jump to the tx bridge: the same mixer call, `bnc_tx`, back to `0x1d09a` |
| `0x0001d0c2` | audio task, RX: `mov.w r1, #0x800; bl 0x1ca80; b 0x1d05c` | jump to the rx bridge: while a bounce owns the recorder, feed enable `0x805917c4` = 0; the same feed call, `bnc_rx`, the loop head `0x1d05c` |
| `0x8006b950` | popup tick (UI task, every 1 ms), first four instructions | jump to the ui bridge: `bnc_ui`, the four instructions, back to `0x8006b95c` |
| `0x800bef10` | pad-event dispatcher: `ldrb r1, [r0]; cmp r1, #0xa0; bhi 0x800bef1c; b.w 0x80018590` | jump to the gate bridge: `bnc_gate(event)`; 0 returns to the caller (the event is dropped), else the four instructions |
| `0x80223474` | RESAMPLE page vtable +8 (the page's event filter) = DOOM OS's `0x6031c8f9` | `bnc_event`, which hands every event it does not take to DOOM OS's filter |
| `0x8012db58` | the RESAMPLE page's tick (vtable +0xcc and +0xd0): `push {r4-r7, lr}; sub sp, #4; mov r6, r1; mov r5, r0; bl 0x800ce420` | jump to the tick bridge: the push and frame, `bnc_tick(page)`, the moves and the modal test, on to `0x8012db64` (new in test2) |

- The audio bridges use no stack, so the mixer and the feed run at their stock depth. The gate
  bridge pushes two words around one call; idle, it adds 20 instructions to a pad event. The tick
  bridge keeps the tick's stack frame and pushes two words around one call; it adds about 20
  instructions to each page tick (once per screen refresh).
- The run itself goes in the popup tick, from the UI task, the same context as the stock
  RESAMPLE page's handlers. It posts the stock recorder commands (`0x800e25c0`: 0x14 standby,
  0x17 start, 0x18 stop, 0x1a cancel, 5 and 0x2a sound off, 0xd save) and the exchange (0x40d),
  and writes the recorder target (`0x800d48e8`) for the destination and the exchange's fence.
- It sets the destination as the stock pad handler does: settings 0x1a, recorder target 0/1/7.
- After the stock finalize it sets the window and the settings through the stock pad setter, then
  marks the pad and charges it again (`0x800d6390`, `0x800d7508`), as the finalize itself ends.
- It pins and restores on every path: REC length (settings 0x24, to FREE), END Snap (0x59, off),
  EXT SOURCE (0x25, off), and on the source LOOP and PAD LINK. REC BPM (0x1b) is not touched (see
  above).
- From REC until the first page tick after the run with the recorder idle, `bnc_tick` writes the
  recorder's state into the RESAMPLE page's last-seen state (`+0x1a90`) before the tick reads it. The
  tick's state handler and after-recording routine therefore never run for a bounce, and the end of
  a bounce's take or cancel leaves the bus effects, the current bank and pad, the RESAMPLE mode and
  screen, END Snap and the page as they were. At any other time the tick runs exactly as in v9.46.
- It triggers the source through the stock pad note (`0x800cdbd0`, velocity 127, mode 1); the gate
  lets that one note through by its pad, whatever velocity FIXED VELOCITY gives it.
- **Memory:** the bridges and the module (`bounce.c`, Zig 0.13.0 `-Os`) go in a 20 KB slot at
  `0x83FE8000`, below the CPU meter's test slot (`0x83FED000`) and the start fix's row
  (`0x83FEF000`): a boot copy row for the bridges, code and constants, and a zero-fill row for the
  module's state, so its zeros take no flash. APP1 stays below the kit PCM planning boundary
  (`0x60376000`). The builder checks that no row overlaps the slot and that nothing in the input
  refers to it.
- **Guards:** every patched site is checked against its exact v9.46 contents. 109 spans the module
  calls or relies on are checked byte for byte (SHA-256 in the builder), plus 21 jump-table
  entries. Stage 3 adds the pad-event dispatcher and its ring, the pad note and the note-on's PAD
  LINK loop, command 0x40d and the exchange with its file and parameter swaps, the whole pad getter
  and setter with its conversions and protect test, the new-sample defaults, the envelope page, the
  renderer's routing and the per-voice update, the recorder's overrun, error word and drain, and
  the EXT SOURCE setter case with the input volume. bounce-3-test2 adds the looper: the MARK
  Function setter case and its jump-table entry, enable, disable and the disable's stop, the LOOPER
  TASK's commands, the looper's audio input and output. It also adds SMPL TASK's queue put, pop and
  loop, behind the REPLACE fence, and behind the tick bridge the RESAMPLE page's tick, its two
  vtable entries (the tick's only callers), its state handler and after-recording routine, the bus
  effect off, the RESAMPLE exit and its restore. bounce-3-test3 adds the pad's charge: the
  finalize's end, the range setter, the mark and its clearing, `0x800d7508` and the charge entry
  functions under it. The jump-table entry
  for settings get 0x1b (REC BPM) is gone with the module's REC BPM read. All are stock 5.52 bytes
  except DOOM OS's filter (v9.46) and the start fix's three spans (startfix-3: its two jumps are
  v9.46's bytes, its code is v3's).
- **Branch scan:** no direct branch anywhere in the ITCM or SDRAM code lands inside a patched
  span.
- **Cost (emulator):** about 50 instructions per TX+RX block pair when idle; up to about 2,600
  while bouncing, plus the stock engine writer that the stock gate would call anyway; up to about
  8,000 while a source with no onset is still being searched (its first 100 ms): about 1% of a
  block.

## Reproduce

From stock 5.52, after the v9.46 commands in [KITS.md](KITS.md#reproduce) up to the kit stage,
with this branch's start fix (v3):

```sh
python synth/build_start_fix.py out/kits-v946/SP404MKII_APP1.bin out/kits-v946-sf3
python synth/test_start_fix.py out/kits-v946-sf3
python synth/build_bounce.py out/kits-v946-sf3/SP404MKII_APP1.bin out/bounce --zig /path/to/zig
python synth/test_bounce.py out/bounce
```

bounce-3-test5 is APP1 `51583df0…1c35` (3,104,320 bytes) on start fix v3 `7d13c1e2…61cc`
(3,094,624 bytes). Both come out the same on the kit stage the published v9.46 was built from
(`88384c3c…92ba`) and on a clean rebuild of every stage from stock 5.52 (v9.5 `d0919e40…`, v9.6
`1b2d50e0…`, kits `88384c3c…`), and two builds are byte-identical.
(bounce-3-test4 was `d6c86579…4da2`, 3,104,320 bytes, on the published v9.46 `7b5fbcb4…684a`;
bounce-3-test3 `b9b11fb0…3c52b`, 3,103,872 bytes; bounce-3-test2 `26f594db…11bf`, 3,103,856
bytes; bounce-3-test1 `59e061cf…221d`, 3,103,744 bytes. These builds were never handed over:
`36d697c0…c2d7`, test4 before its name kept D; `97ff1a5f…fc97` and `e77aa89b…4369`, fixes (b) and
(a) as prepared for the decision; `8995fd25…8927`, an earlier test3 with the charge fix alone;
`571589da…20aa`, a test2 from before the third bug was known; and `9e438a84…0373`, the first test2
fix, which skipped only the after-recording routine.)

## Checks (emulator)

`test_bounce.py` boots the built image in Unicorn the way its scatter loader does. Stock code runs
for real:

- the recorder feed behind the RX bridge, the pad note and the pad-event dispatcher behind the
  gate bridge;
- the pad parameter getter and setter (with their conversions, protect test and side effects),
  and the pad name;
- SMPL TASK's command queue end to end: the module's posts and target sets (`0x800e25c0`,
  `0x800d48e8`), the queue put and pop, the task's loop, the target store (`0x800fb000`), and the
  command dispatcher for 0x40d with the exchange, its file swap (`0x80051040`) and path builder,
  and its parameter swap;
- the settings setter for EXT SOURCE, and the stock MIDI dispatcher;
- the UI task's event dispatcher (`0x8003b530`) with page 0xe's registry handler, in the checks
  that drive keys, the encoder and pads through it;
- the looper: the MARK Function setter, the looper's boot init, the LOOPER TASK's commands, its
  level-trigger option and its audio input;
- the popup function and the page's vtable;
- in the tick bridge checks and the whole-state audit, the image's own global objects: the boot's
  70 static constructors run (the RTOS pool under them as a bump allocator, object creation as an
  id, critical sections as nothing); the settings, project, system, sequencer and pad setters and
  getters; DOOM OS's page filter; the RESAMPLE page object, made by its registry handler as on page
  entry; the UI task's 1 ms tick (`0x8003c5f0`, with the stock popup tick behind the module's
  bridge) and its event queue, drained through the stock dispatcher; the RESAMPLE page's tick every
  16 ms through its two vtable entries, with its state handler, its after-recording routine, the
  bus effect off, the RESAMPLE exit and the restore; SMPL TASK's queue loop. The effects chip's
  UARTs (LPUART1–8) are logged byte by byte.

Modelled:

- SMPL TASK's recorder commands, at the dispatcher's entry: standby, REC_START, the finalize
  (with a stock-like snap of START, ending with the take charged with its range), cancel, sound
  off; a busy task (the queue's pop holds the exchange);
- the pad's charge, recorded where the stock code makes it: in the finalize, and where
  `0x800d7508` clears a pad's mark (the real `0x800d7508`, range setter and mark run; the cache
  entry and its card reads do not);
- the pad-event ring (a note-on there starts the source's voice); the card under the file swap,
  at its file calls (unlink, rename (FatFs: not onto an existing name), open), keyed by path; the
  pad loader and the parameter save; a failed rename;
- the RTOS under the looper and the queue (locks, waits, task creation, event flags), and the
  dispatcher's run-time state on the RESAMPLE page (no mode holding the keys, no key pairs, the
  page object live);
- the source pad's voice, which renders the pad's frames into the DRY stems (16-bit samples in
  the 20-bit slots, at the capture's scale, as dm-404 reads them) from the first block
  after its trigger;
- the effects chip: RX = the record mix L frames later, optionally with gain, an echo, noise, or
  music on the input while EXT SOURCE is on;
- the eDMA positions (reads jitter by one frame), the recorder engine's writer (it keeps the
  take, and can fill its ring), and, outside the real-object checks, the settings, project and
  system parameter stores;
- the screen: drawing returns at once.

The checks (511 cases):

- **Static:** only the header, the six sites and the appended tail differ from the parent. The
  scatter table is the parent's rows plus a copy row and a zero-fill row; APP1 ends below the PCM
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
  the target and mode kept once picked (after EXIT the gesture offers them again); the modes each
  kind of pad offers; the destination search, protected banks skipped; the refusals.
- **Through the UI task's own dispatcher** (`0x8003b530`, page 0xe's registry handler
  `0x80053cb8`): the gesture (RESAMPLE's held bit set by the dispatcher itself), VALUE pressed
  (key 0x31) to REPLACE and back, SHIFT + VALUE, VALUE turned, EXIT; and a whole REPLACE with
  every key sent that way. That REPLACE checks the real file swap's renames, by the path builder's
  own paths, and ends on `REPLACED`.
- **The looper, through its stock code:** after the boot init, disabled and empty; MARK Function =
  LOOPER through the stock setter: enabled, empty, a bounce set up; then each phase through the
  LOOPER TASK's commands and the audio input. The phases are armed (level trigger on, the boot
  default), recording, playing, stopped, overdub queued, overdubbing, ending an overdub, stopped,
  erased, and armed again. Each is refused or set up as it should be. MARK Function changed back
  while armed and while playing (the stock disable stops it): set up. The looper started between
  the gesture and REC: refused at REC, nothing posted. A whole bounce with the loop stopped: done,
  the looper left as it was. On bounce-3-test1 these checks fail as the unit did.
- **The fence through the real queue:** the exchange and the fence reach SMPL TASK in one pass of
  its loop, the fence after it, and the real target store writes 15 only after `0x800a6c30` has
  returned.
- **Whole runs through the bridges:** the take is the RX stream from F0 frame for frame,
  START/END and the loop point land on the window, a dry take is the source's own frames: NO TAIL
  (sharp attack, echo, 125 ms soft start, START/END inside the file, a looped pad, a pitched
  one-shot), TAIL (an echo, a looped pad, never quiet), LOOP (a loop point, a one-shot), L ±, D −1
  / 0 / +1, the boot's calibration, bank B, the popups, a tail still ringing at REC, END Snap; the
  commands posted, the settings pinned and restored, the stock gate never running, the name and
  the save; the bounce's last charge is its final START, END and loop point (on test2 each of these
  fails: the last charge was the take's).
- **A return that departs before its main delay:** a low symmetric ring around 73 that departs at
  66. NO TAIL starts on 66, and a LOOP take's last 7 frames hold nothing of the next pass. A pure
  66-frame return under an estimate of 73 also starts on 66. From A-12 after a take that calibrated
  the boot, the name (24 characters in full) loses P's tenth, not D.
- **P moving within a boot:** calibrated at P65.5 D −1 with L 73, then P 62.5 D 0 with L 76. The
  next take uses 76.
- **Onsets a threshold crossing gets wrong,** with true L 77: a 32-frame attack, 20 ms attacks
  with RX +6 and −6 dB, a 10 ms attack through an echo with +3.5 dB, and a LOOP pass with a soft
  start. L stays 77, and is within a frame with the level step. An onset 5 frames or 20 frames
  from the estimate is not used.
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
  idle (passes); FIXED VELOCITY; a pattern starting, or the looper (enabled, stopped) told to
  play by the LOOPER TASK, during the take: discarded; PAD LINK.
- **Refusals, EXIT and failures:** EXIT during standby, the silence wait, the recording (TO PAD
  and REPLACE), while saving, while swapping; `FX STILL RINGING`; ROUTING not Mix; a mono
  recorder; a pattern started during setup; a source that never sounds; a finalize that leaves
  the pad empty (also with REPLACE); zero-cross snapping on; a standby that never starts; the
  stock recorder ending the take itself (the card full, a full ring, no space; TO PAD and
  REPLACE; with and without a partial take), including a ring that fills on the take's last
  frames.
- **The tick bridge, on the real global objects, against the parent:** a take has just ended (the
  page's last tick saw state 2, the recorder idle). On the parent, and with no bounce, the page's
  next tick runs the stock routine: BUS 1/2 off, the stock pad handler's destination current,
  RESAMPLE left, with the same writes on both. With a bounce holding the page, the tick does
  nothing: effects on, bank C, RESAMPLE mode, END Snap on, no state handler, no page request,
  nothing to the chip. That holds while the bounce owns the recorder, once its run is over with the
  recorder idle, and once its run is over with its cancel not yet taken. The page is let go on the
  first tick with the run over and the recorder idle.
- **The whole-state audit, on the real global objects:** TO PAD, REPLACE, EXIT during the take and
  EXIT in the silence wait, every key through the UI task's dispatcher. Each starts in bank C with
  BUS 1 and BUS 2 effects on and END Snap on. The page's tick runs every 16 ms through both its
  vtable entries, and is seen to run in standby and while recording. Logged: every settings,
  project, system, pad and sequencer write, every page request, every bank or pad change and every
  byte to the effects chip's UARTs. Every settings, project and system parameter and every pad
  parameter is read through the stock getters before and after. The global objects
  (`0x82df0000`–`0x82e50000`, `0x80590000`–`0x805a0000`, `0x80240000`–`0x80250000`,
  `0x833b8000`–`0x833b9000`) are diffed byte for byte. Nothing goes to the effects chip. BUS 1/2
  keep their effects, and bank C, the RESAMPLE mode and page, END Snap and the screen state stay.
  Every write and every changed parameter or byte must be on an allowlist with its reason:
  - the run's pads: the destination; with REPLACE also the source, and the current pad's views of
    it, since the source is the current pad;
  - the edited and change flags that the stock name function and pad setter raise;
  - project 0xef and 0x98 (the source played through the stock pad note);
  - recorder target 0, the queues' indices, the input meter, the key records, the popup and the
    panel refresh flags.

  A stock RESAMPLE of the same pad, through the stock page handlers, ends with BUS 1/2 off, the
  new pad current and RESAMPLE left, on a fresh boot and right after the TO PAD bounce. The audit fails on bounce-3-test1 as the unit did: BUS 1/2
  off, bank A, RESAMPLE left, REC BPM written and two flags left set. It also fails on the first
  fix, which skipped only the routine: EXIT during the take ends the same way, and EXIT in the
  silence wait turns END Snap off.
- **Cost:** instructions in the module per block pair, idle and bouncing, and per pad event.

On the final image every kit suite passes (the kits manifest pointed at this APP1), and the start
fix and bounce probe suites pass on their own builds.

Not checked by the emulator, which is what the hardware test is for:

- the real voice start and stream timing, and the effects chip's delay;
- the SD card: the take's writes, the renames themselves (the emulator runs the file swap down to
  its file calls), the pad loader and save, a full card, a slow card, a power loss;
- the looper's real timing and its level trigger on the unit's input;
- that input volume 0 silences every input path the effects chip mixes;
- the stock finalize and exchange themselves on the card, the project reload;
- the charge's card reads and the voice reading the charge (dm-404 runs them: there test3's LOOP
  bounce sounds for END − START and loops at END − the loop point, test2's for L + 32 more);
- MIDI from a real port, the screen, popups' lengths and LEDs;
- which of the page tick's two vtable entries the page's draw calls, and how often (the emulator
  runs the tick every 16 ms through both);
- the stock finalize's own writes (ORIGINAL BPM = REC BPM is read in its code; the emulator models
  the finalize);
- CPU headroom on the unit.
