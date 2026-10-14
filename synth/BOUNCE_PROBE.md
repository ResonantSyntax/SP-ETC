# Bounce probe: measuring the effects-chip round trip (bounce in place, stage 1)

A measurement build, not a feature. It answers the one question the code can't: is the
round trip L through the effects chip (BMC) the same every time? If it is, bounce in place
can cut its takes to the exact frame (NO TAIL and LOOP modes); if it isn't, a bounce has
to line up on the sound's onset instead. Background: the bounce-in-place study,
`analysis/bounce_in_place/REPORT.md` (§3, §7.6, §9 step 1, §10 test T1), outside this
repository.

It is a stage on top of the final v9.46-test2 image (kits plus the RESAMPLE start fix).
Nothing is recorded, changed or saved differently: RESAMPLE works as in v9.46-test2, and
the probe only watches and shows a popup.

## What it measures

The audio task (`0x1cf78`) renders each TX block of 64 frames for the effects chip (mixer
`0x1c2d0`) and hands each received RX block to the recorder (feed `0x1ca80`). The probe
counts both in that same task:

- **TX frame** = 64 × TX blocks rendered since boot + the frame within the block.
- **RX frame** = 64 × RX blocks received since boot + the frame within the block.
- **TX onset**: the first frame in which any of the 14 mixer stems is above 2048
  (about −48 dBFS of their 20 bits), after at least 1024 frames (21 ms) below it.
- **RX onset**: the first frame after the TX onset in which the frames the recorder
  captures (RX words 0/1) are above 128 (about −48 dBFS of 16 bits).
- **L = RX onset − TX onset**, in frames at 48 kHz.

It measures only while the RESAMPLE page's recorder is in standby or recording
(settings param 0x36 = 1, recorder state 1 or 2). Every sound that starts from TX silence
is measured, so one take can hold many runs.

## The popup

After each run, for 3 seconds:

```
L=290 #20 W290
290-290 P33 D0 V0
```

| Field | Meaning |
| --- | --- |
| `L=290` | this run's L, in frames |
| `#20` | runs measured in this take (a new take starts at #1) |
| `W290` | the same onset measured on RX words 2/3; `W--` nothing came back there, `W??` words 2/3 were not silent before it |
| `290-290` | lowest and highest valid L in this take |
| `P33` | eDMA phase: TX line 3 read position minus RX write position, in frames, mod 128 (read when the result is published) |
| `D0` | RX blocks minus TX blocks counted since boot |
| `V0` | frames from the start of the TX block in which a pad voice started to the TX onset; `V-` when no pad voice started for it (a Sound Generator note, say) |

Other results:

- `L=?? #3` / `RX not quiet`: the capture wasn't silent for 256 frames before the
  return. Something else was sounding: an effect tail, the input, the previous hit.
- `L=-- #3` / `no return`: nothing came back within 1 s. Check ROUTING (Mix) and
  the record level.

Numbers are clamped to ±99999, so the text always fits the stock popup buffer.

## Reading the results

- **The same L in every run, after every power cycle and for every routing:** a constant
  can be built in, and every bounce mode is frame-exact.
- **L differs between power cycles:** check whether `L − 64·D + (P mod 64)` stays the
  same. If it does, the chip's delay is constant and only the i.MX's buffer phase moved.
  Stage 2 can then read that phase at run time. (Derivation: with TX and RX DMA
  interrupts at frame phases φtx, φrx and first-counted blocks k0, m0,
  L = Lphys + 128 + (φtx − φrx) + 64·(k0 − m0); D and P give the last two terms.)
- **L varies within one boot:** align bounces on the onset.

## What changes

| Site | Stock code | Now |
| --- | --- | --- |
| `0x0001d090` | audio task, TX: `mov.w r1, #0x1000; mov r0, r5; bl 0x1c2d0` | jump to the tx bridge: the same mixer call, `probe_tx`, back to `0x1d09a` |
| `0x0001d0c2` | audio task, RX: `mov.w r1, #0x800; bl 0x1ca80; b 0x1d05c` | jump to the rx bridge: the same feed call, `probe_rx`, back to the loop head `0x1d05c` |
| `0x8006b950` | popup tick (UI task, every 1 ms), first four instructions | jump to the ui bridge: `probe_ui`, the four instructions, back to `0x8006b95c` |

- The audio bridges use no stack, so the mixer and the feed run at their stock depth.
  `probe_tx` and `probe_rx` run after them.
- **Cost (emulator):** about 4,200 instructions per TX+RX block pair while measuring
  (about 0.5% of a 1.33 ms block at 600 MHz) and about 60 otherwise.
- **The popup** goes through the stock popup function `0x800d3ff0` from the UI task's own
  popup tick, the same context as the stock popups. A popup that closes in that very tick
  would also clear a new one, so the probe waits one tick then.
- **Memory:** the bridges and the module (`bounce_probe.c`, Zig 0.13.0 `-Os`) go in a new
  boot copy row in a 4 KB slot at `0x83FEE000`, just below the start fix's row at
  `0x83FEF000`. The builder checks that no row overlaps the slot and that nothing in the
  input refers to it.
- **Guards:** every patched site is checked against its exact instructions. Twelve stock
  spans the module and bridges rely on are checked byte for byte (SHA-256 in the
  builder): the audio task, the mixer on both sides of the kits' SG call, the recorder
  feed, the renderer's voice test, the voice stub, the popup tick and function,
  REC_START, GetParam and its case for param 0x36, and the RESAMPLE page setting param
  0x36 to 1. GetParam's jump-table entry for 0x36 is checked too.
- **Branch scan:** no direct branch anywhere in the ITCM or SDRAM code lands inside a
  patched span.

## Reproduce

From stock 5.52, after the v9.46-test2 commands in [KITS.md](KITS.md#reproduce):

```sh
python synth/build_start_fix.py out/kits-v946/SP404MKII_APP1.bin out/kits-v946-final
python synth/build_bounce_probe.py out/kits-v946-final/SP404MKII_APP1.bin out/bounce-probe --zig /path/to/zig
python synth/test_bounce_probe.py out/bounce-probe
```

bounce-probe-1 is APP1 `13b2b7fd…fcf5` (3,096,864 bytes), built on v9.46-test2
(`e94b36f8…295b`).

## Checks (emulator)

`test_bounce_probe.py`:

- **Static:** only the header, the three sites and the appended tail differ from the
  parent. The scatter table is the parent's rows (start fix included) plus one.
- **Bridges, in Unicorn, against the parent's own instructions:**
  - TX: the mixer gets the same arguments at the same stack depth.
  - RX: the real stock feed fills the capture buffer and the meter exactly as stock,
    and calls the recorder gate once with the stock arguments.
  - UI: the popup tick continues at `0x8006b95c` with the stock registers and stack
    frame.
  - Registers r4–r11 and sp come back as stock leaves them.
- **Measurement scenarios**, driving both audio bridges block by block with synthetic
  stems and RX data:
  - one click (popup text and 3 s, through the real stock popup function);
  - several runs in one take;
  - words 2/3 silent, with the same latency, and with their own latency;
  - a pad voice starting in, or two blocks before, the onset block;
  - no measurement when the recorder is idle or on the REC sampling page;
  - sounds without 1024 frames of TX silence before them are skipped;
  - "RX not quiet" and "no return";
  - the counter offset (D) and eDMA phase (P);
  - clamped numbers;
  - the popup deferred one tick when the shown popup closes in that tick.

Not checked by the emulator: the real DMA timing, the chip's delay, the popup on the
screen and CPU headroom on the unit. Those are what the hardware test is for.
