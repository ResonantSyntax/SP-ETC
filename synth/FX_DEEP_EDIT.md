# FX deep edit: a settings page for what the bus effects never get

A hardware test build. Stock 5.52 sends only the six knob parameters (CTRL 1-6) of each effect to
the effects chip (BMC); 142 of the 383 effect parameters are never sent. The FX probe (local branch
`claude/fx-probe`, `synth/FX_PROBE.md` there) showed on the unit that the chip acts on every one it
tried. This page lets you set them.

It is a stage on top of the published Sound Generator + Kits v9.46 (APP1 `7b5fbcb4…684a`). The
firmware's own state is never changed and nothing is saved: values live in RAM, per bus and effect,
until power-off. Outside the page the build behaves as v9.46, except that an edited value goes to
the chip again whenever the firmware selects that effect on that bus.

## Test 8 (fx-deep-edit-test8): the Super Filter's settings are left out

A user's report on v9.48: on the Super Filter's extra screens CTRL 2 spiked the volume (FLT GAIN, 0-12, is
CTRL 2 on the first). The user asked for the Super Filter's hidden settings to go, so all six are on
`EXCLUDED`: the Super Filter has no extra settings, and 135 settings remain. Checked in the emulator.

## Test 7 (fx-deep-edit-test7): no NO EXTRA SETTINGS popup

The user asked for test 4's note to go: an effect without extra settings keeps stock's VALUE, with no popup. The
Compressor's MODE stays left out (test 6). Checked in the emulator: 71 checks pass (Crusher's VALUE as on the
parent, no popup).

## Test 6 (fx-deep-edit-test6): the Compressor's MODE is left out

A user's report on v9.47: the Compressor's extra setting on CTRL 1 (MODE, 0-1) "almost blew my ears off".
Set to 1 it makes the output dangerously loud. The builder now has a list of settings left out on purpose
(`EXCLUDED`), and MODE is on it: the Compressor has no extra settings. 141
settings remain. The patcher page and README tell everyone to turn the volume down before trying the hidden
settings, since others (gains, EQ boosts, feedback, resonance) can also get loud. Checked in the emulator: 71
checks pass (the Compressor offers nothing; every other test 5 check).

## Test 5 (fx-deep-edit-test5): VALUE holds the screen itself

From the user's test of combined-test6: still no extra screens, never the NO EXTRA SETTINGS note, on the main
screen with every FX button, and screen 2 never stayed for more presses: VALUE only peeked at screen 2. The FX
screen is "held" (+0x1b3f) only if REMAIN is down at the moment the show method runs (`0x80146f66`); a screen
that comes up otherwise stays while REMAIN is held but treats VALUE as stock does (the press does nothing, VALUE
held shows screen 2), and the module stepped aside. Now a VALUE press on an FX screen that is not held holds it,
as the show method would have (+0x1b3f and `0x80592320` set), when the effect has screen 2 or extra settings, and
steps on from there: screen 2, the extra screens, screen 1. An effect with neither keeps stock's VALUE. So the
extra screens come however the screen was opened, the FX button alone included; MFX's effect choice before any
VALUE press is stock's.

Checked in the emulator (70 checks pass): FX button alone, then VALUE: held, screen 2, extra screens, no close for
5 s; Crusher opened alone: VALUE stock's, closes after 2 s as on the parent; every test 4 check.

## Test 4 (fx-deep-edit-test4): the input FX too, and a note when there is nothing

From the user's test of combined-test5: on the held FX screen (REMAIN + FX) VALUE only flipped screens 1 and 2,
and the extra screens never came, even after a restart. The extra screens follow the slot the CTRL knobs drive
(settings `0x3a`) and its effect (`0x27c[slot]`), as the FX screen itself does (its update `0x80146598` reads the
same two). Tests 2 and 3 offered them on BUS 1-4 only, so with the knobs on the input FX (slot 0), or on an effect
without extra settings (11 of 48), VALUE quietly did stock's toggle.

- **The input FX** gets its extra screens too. Slot 0 is part of the chip's address map (`03 hi lo aa` with
  hi:lo = (effect − 1) × 5 + slot), and the stock knob path already sends it with slot = `0x3a`. Values are kept per
  slot (`fde_values[5][142]`), and an FxType for slot 0 (`0x7e`) sends the input FX's edited values again, as the
  FxTypes for BUS 1-4 do (`fde_dt1` now passes `0x7e..0x82` to `fde_dt1_fxtype`).
- **An effect without extra settings** says so: the VALUE press that goes back to screen 1 (every press, on an
  effect without screen 2) shows `CHORUS` / `NO EXTRA SETTINGS` for 1.5 s, and stock's toggle runs as before.

Checked in the emulator (68 checks pass): the input FX's extra screen (Reverb's DENSITY on slot 0, `03 .. .. ..`
for slot 0), Crusher's note with stock's flag toggles as on the parent, the input FX's FxType re-sending its edits
(and adding nothing without), the builder's address for all 710 setting/slot pairs, and every test 3 check.

## Test 3 (fx-deep-edit-test3): no FX button hold

From the user's test of combined-test4: "fx screen hold is broken. now on mfx, once pressed cannot get to menu to
change. just get rid of that for now." Test 3 drops test 2's hold (the patch at `0x80146f66`): an FX button alone
is stock again (its screen closes after 2 s, and MFX's effect choice is stock's). The extra screens stay on the
screen REMAIN + FX opens (stock's screen that stays): there VALUE press steps screen 1, screen 2, the extra screens
and screen 1 again, as test 2 did. Three changes in 5.52 space now (the TOP vtable slot, the DT1 builder's entry,
the VALUE toggle).

Checked in the emulator (68 checks pass): only those three sites change inside the parent; an FX button alone opens
the FX screen as on the parent (+0x1b3f clear, VALUE stock's, the close request after 2 s); REMAIN + FX gives the
screen that stays, as on the parent, and the same FX button again does what the parent does (the effect stays on,
the screen stays); every test 2 check of the screens, knobs and re-sending, now with REMAIN + FX.

## Test 2 (fx-deep-edit-test2): on the FX screen

From the user's test of combined-test3: the FX screen should stay up after an FX button, as it does with REMAIN +
FX, and the extra settings should be more screens of the FX screen, reached with VALUE. Test 1's TOP page (EXIT +
VALUE, VALUE turns) is gone; sections below that describe it are test 1's.

### Using it

- **An FX button** opens the FX screen as REMAIN + FX does in stock: it stays until EXIT, REMAIN, or that FX button
  again (the effect goes off). Another FX button shows that one.
- **VALUE press** steps the screens: screen 1 (CTRL 1-3), screen 2 (CTRL 4-6, where the effect has them), then the
  effect's **extra screens**, then screen 1 again. Effects without extra settings keep stock's screens.
- **An extra screen** is a popup with three of the effect's extra settings on CTRL 1-3:

  ```
  TAPE ECHO 3/5
  C1 SYNC 0
  C2 BASS 15
  C3 TREBLE 15
  ```

  Turning CTRL k sets its setting across the firmware's range (knob at 0: the minimum, at the top: the maximum);
  each change is one DT1, as in test 1. A knob without a setting there does nothing.
- On an extra screen, pads play as usual; any button but VALUE and SHIFT leaves it (the popup goes) and does what
  it always does.
- Values are still per bus and effect, in RAM, and sent again after every FxType for that bus.

### How stock's FX screen works (5.52, read in the code and run in Unicorn)

- An FX button (keys 0x2b-0x2f, MFX 0x30) lights its button (system 0x276[bus]) and pushes the FX screen onto TOP's
  view stack (TOP + 0x3dc): constructor `0x80147ba0`, vtable `0x802269c0`, a 2000 ms timer at +0x1b10.
- Its show method (`0x80146e78`) keeps **whether REMAIN (key 0x24) is held** in +0x1b3f (`0x80146f66`), and sets
  `0x80592320` then.
- Its update (`0x80146598`, every 50 ms) counts the timer down and asks to close (`0x800bb180(screen, 1)`) when it
  runs out, unless MFX is held. With +0x1b3f set, the timer is re-armed while the bus has an effect, and screen 2
  shows while +0x1b40 is set and the effect has CTRL 4-6; without it, screen 2 shows while VALUE is held. It asks to
  close when its FX button goes off.
- VALUE pressed: the generic key handler (`0x800cba46`) calls `0x801479a0`, which toggles +0x1b40 when +0x1b3f is
  set. REMAIN pressed closes it (`0x801479b8`); EXIT destroys it.

### Patches

| Site | Stock | Now |
| --- | --- | --- |
| `0x80146f66` | `bl 0x800d9f20` (is REMAIN held?) | `movs r0, #1; nop`: every FX screen is REMAIN's |
| `0x801479a0` | the VALUE toggle's first ten bytes | jump to `fde_value`: screen 1, 2, the extra screens, 1 |
| `0x8022ce64` | TOP vtable +8, DOOM OS's filter | `fde_filter`: CTRL 1-3 on an extra screen, leaving it |
| `0x800d8118` | the DT1 builder's first ten bytes | `fde_dt1`, as test 1 (sending again after an FxType) |

Six more guards (27): the FX screen's constructor, show method, update and VALUE toggle, the generic handler's VALUE
call, TOP's knob handler.

### Checked in the emulator

`test_fx_deep_edit.py` (69 checks) on fx-deep-edit-test2:
- the FX screen: an FX button alone opens it as REMAIN + FX (on v9.46 only with REMAIN held); it stays through 5 s of
  updates where v9.46's asks to close after 2 s; that FX button again, or no effect on the bus, closes it;
- VALUE: Tape Echo goes to screen 2, its three extra screens, then screen 1; Isolator to its one extra screen and
  back; Crusher toggles stock's flag as v9.46 does with REMAIN; nothing sent;
- extra screens: CTRL 1-3 set their settings (one frame a change, none if the value stays), a knob without a setting
  does nothing, pads play, another button leaves, then the knobs are stock's; all 142 settings reach their min and
  max; BUS 2-4; none on the input FX;
- sending again after an FxType, as in test 1; four quick EXITs are STOP; every key alone, the FX buttons included,
  and the other scripts go on as on v9.46.

### Not known

- How the popup looks with four lines on the unit (test 1 showed two).
- EXIT on the FX screen: stock destroys it (the emulator stops there, waiting on another task).

## Using it (test 1)

On the TOP page, **hold EXIT and press VALUE**. The stock popup (`0x800d3ff0`) shows the bus the
CTRL knobs drive, its effect and the first of that effect's extra settings:

```
BUS1 TAPE ECHO          turn VALUE: the next or previous setting
TAPE DIST 4             press VALUE: edit
```

```
BUS1 TAPE ECHO          editing: turn VALUE to change it (each change goes to the chip at once)
TAPE DIST [4]           press VALUE again: stop editing
```

- **EXIT**, or any other button, closes the page and then does what it always does (four quick EXITs
  are still STOP). Pads and knobs work as usual while the page is open, so you can play and listen.
- A setting shows the firmware's default (`0x801abe64`) until you edit it. Numbers are raw: what they
  mean (dB, Hz, cents) is not known.
- Every value stays inside the firmware's own min/max for that parameter (`0x801ad1fc`/`0x801ac830`).
- The popup stays 10 s after the last VALUE action; the page stays open until EXIT or another button
  (turn VALUE to see it again).
- Other popups: `BUS1 / NO EFFECT` (nothing on the bus), `BUS1 CRUSHER / NO EXTRA SETTINGS` (an effect
  whose parameters stock already sends), `INPUT FX / BUS 1-4 ONLY` (the knobs are on the input FX).
- If the bus's effect changes while the page is open, the next VALUE action starts over on the new
  effect's first setting.

## What the page reads and sends

- **Bus:** settings `0x3a` (`0x82e01144`, getter `0x800d94d8`): 0 input FX, 1-4 BUS 1-4. TOP's CTRL
  1-3 path `0x80183c48` → `0x800cc030` picks the slot from it.
- **Effect:** system `0x27c[bus]` (`0x82dfeed0 + 0xc4 + 2 × bus`, getter `0x800da010`), 0 = none; the
  knob path does nothing while it is 0. (`0x276[bus]` is the lit FX button, 1-5 or 6 = MFX; `0x27b` the
  MFX choice; `0x80018bf0` turns those into `0x27c` and calls the effect select.)
- **Settings:** an effect's parameters that are not in its six-ID knob record (`0x802e5b40`) and that
  DM-404's `fxmap.json` gives no boot value; IDs from the firmware's name table (`0x80245ee4`) joined
  with fxmap. The builder insists the firmware's name for every ID is fxmap's name at that address.
  11 effects have none: Crusher, Overdrive, Distortion, Chorus, Downer, Auto Pitch, COMPRESSOR 2, SBF,
  Harmony, Sub Sonic, Cloud Delay.
- **A change** is one DT1 through the stock builder `0x800d8118(0x80592500, parameter ID, bus, value)`,
  the call the bus-effect knobs end in; slot = bus, so `03 hi lo aa` with hi:lo = (effect − 1) × 5 + bus.
  Opening, browsing, entering and leaving edit, a turn past min/max, and closing send nothing.

## Sending again

Stock (re)selects an effect on a slot by sending its FxType (`0x7e` + slot). It never re-sends an
effect's knob parameters on an effect change: the effect select `0x800d0cf0` sends the FxType when it
differs from its cache `0x80246f38`, and the bus switch; the knob stores are per bus and effect and are
sent only by knob moves (`0x80018a98`) and the boot chip reset `0x801803b0`, which first sets every slot
to FxType 0, then sends CTRL 1-3 of every effect on every slot. FxType goes out from the effect select,
the system setter (`0x800de270`, IDs up to `0xa1`), the second setter (`0x8008cabe`), the BUS 1/2 swap
(`0x8001b8e2`, `0x8001b95e`) and the chip reset.

So the hook is on the builder itself: after any FxType for BUS 1-4 (`0x7f..0x82`) with effect *e*, the
bus's edited values for *e* go out, in the page's order, right behind it. That covers an effect
change and coming back, and a project or boot reload that selects the effect again. Nothing else adds
a frame: a knob turn, an FxType for an effect without edits, the input FX's FxType, the chip reset's
FxType 0. Choosing the effect the chip already has sends no FxType (stock's cache), so nothing is
re-sent then either: the chip still has it.

## The patches

1. **TOP's page vtable** `0x8022ce5c`, slot `+0x08` (`0x8022ce64`): DOOM OS ED5E's filter `0x6031c8f9` →
   `fde_filter`, which takes the chord, VALUE while the page is open, and closes the page on any other
   button; every event goes on to DOOM OS's filter as before unless the page took it.
2. **The DT1 builder's first ten bytes** (`0x800d8118`: `push.w {r4-r11, lr}`, `sub sp, #12`,
   `movw sb, #0xe1c8`) → `movw ip / movt ip / bx ip` to `fde_dt1`. Nothing branches into those bytes but
   the entry (the builder checks every BL, B.W and literal). `fde_dt1` is four instructions: anything
   but an FxType for BUS 1-4 branches to `fde_dt1_stock` (the three displaced instructions, then on at
   `0x800d8122`) with the caller's own stack and return address, so the builder runs exactly as stock,
   down to the frames it builds from leftover stack for the `-1` entries of the knob records (the chip
   reset sends 25 of those, with addresses like `d6 00 00 00`); an FxType for BUS 1-4 goes to
   `fde_dt1_fxtype`, which sends it the same way and then the bus's edited values.

The module (Zig 0.13.0, `-Os`, about 5 KB) lives in a new boot copy row in a 16 KB slot at `0x83FE2000`,
below the FX probe's slot `0x83FE6000`, bounce stage 3 `0x83FE8000`, the CPU meter, the bounce probe and
the start fix. 21 SHA-256 guards cover the stock code and tables it calls, reads or relies on.

## The settings

Name, the firmware's min-max, (its default). Effects 23 Gt Amp Sim and 42 Vocoder are not in the BUS
menu; their rows only matter if they ever get onto a bus.

| Effect | Settings |
| --- | --- |
| 1 FILTER+DRIVE | LEVEL 0-255 (255) |
| 2 TIMECTRLDLY | HIGH CUT 0-14 (14), HIGH DAMP 0-81 (81), LOW DAMP 0-81 (81) |
| 3 ISOLATOR | BALANCE 0-255 (255) |
| 5 PHASER | TYPE 0-3 (2) |
| 6 FLANGER | LOW CUT F 0-17 (0), MODE 0-1 (0) |
| 9 TAPE ECHO | SYNC 0-1 (0), BASS 0-30 (15), TREBLE 0-30 (15), PAN S 0-255 (128), PAN M 0-255 (128), PAN L 0-255 (128), TAPE DIST 0-8 (4) |
| 10 REVERB | DENSITY 0-10 (10) |
| 11 WRMSATURATOR | LOW FREQ 0-255 (88), LOW GAIN 0-48 (10), HI SLOPE 0-2 (2), HI FREQ 0-255 (200), PRE1 TYPE 0-4 (0), PRE1 FREQ 0-255 (88), PRE1 GAIN 0-48 (24), PST1 TYPE 0-4 (3), PST1 FREQ 0-255 (88), PST2 TYPE 0-4 (4), PST2 FREQ 0-255 (200), PST3 TYPE 0-4 (4), PST3 FREQ 0-255 (149), PST3 GAIN 0-48 (24), PST3 Q 5-160 (5), SENSE 0-60 (20), POST GAIN 0-60 (57), BALANCE 0-255 (255) |
| 12 RESONATOR | BALANCE 0-255 (255), LOW CUT F 0-17 (0) |
| 13 DJFX LOOPER | LEVEL 0-255 (255) |
| 15 JUNO CHORUS | LEVEL 0-255 (255) |
| 16 TREMOLO/PAN | EQ LOW 0-30 (15), EQ HIGH 0-30 (15), LEVEL 0-255 (255), PHASE 0-180 (90) |
| 17 WAH | BALANCE 0-255 (255), EQ LOW 0-30 (15), EQ HIGH 0-30 (15), LEVEL 0-255 (255) |
| 18 SYNC DELAY | HIGH CUT 0-14 (14), HIGH DAMP 0-81 (81), LOW DAMP 0-81 (81) |
| 19 EQUALIZER | MID Q 0-4 (0), MID2 FREQ 0-16 (7), MID2 GAIN 0-30 (15), MID2 Q 0-4 (0), LEVEL 0-255 (255), BALANCE 0-255 (255) |
| 20 LO-FI | POST FILT 0-2 (1) |
| 21 RING MOD | LEVEL 0-255 (255) |
| 22 CHROMATIC PS | FINE1 0-200 (100), LEVEL1 0-255 (255), FINE2 0-200 (100), LEVEL2 0-255 (255), EQ LOW 0-30 (15), EQ HIGH 0-30 (15), LEVEL 0-255 (255) |
| 23 GT AMP SIM | AMP SW 0-1 (1), AMP TYPE 0-13 (0), MASTER 0-255 (200), GAIN 0-2 (1), PRESENCE 0-255 (0), BRIGHT 0-1 (0), SP SW 0-1 (1), SP TYPE 0-15 (4), MIC SET 0-2 (1), MIC LEVEL 0-255 (255), DIRECT 0-255 (0), PAN 0-255 (128) |
| 24 STOPPER | HOLD 0-1 (1) |
| 26 SLICER | ATTACK 0-255 (100), RESET SW 0-1 (0), RESET THR 0-255 (120), LEVEL 0-255 (255) |
| 28 COMPRESSOR | none since test6 (MODE 0-1 (0) was left out: set to 1 it made the output dangerously loud) |
| 30 SCATTER | BALANCE 0-255 (255) |
| 31 404 VINYLSIM | DIST 0-255 (60), DISC TYPE 0-2 (0), BALANCE 0-255 (255) |
| 32 303 VINYLSIM | BALANCE 0-255 (255) |
| 33 ZAN-ZOU | M D LEVEL 0-255 (0), M D MODE 0-2 (2), M D SYNC 0-1 (0), M D TIME 0-255 (188), M D FBK 0-255 (153), M HF DAMP 0-17 (17), M D PAN1 0-255 (0), M D PAN2 0-255 (255), M D PAN3 0-255 (64), M D PAN4 0-255 (192), S D PAN1 0-255 (0), S D PAN2 0-255 (255), S D PAN3 0-255 (64), S D PAN4 0-255 (192) |
| 34 SUPER FILTER | none since test8 (FLT SLOPE 0-2 (0), FLT GAIN 0-12 (0), MOD SW 0-1 (1), MOD WAVE 0-4 (2), ATTACK 0-255 (100), LEVEL 0-255 (255) were left out: CTRL 2 spiked the volume) |
| 35 HYPER-RESO | BALANCE 0-255 (255), LOW CUT F 0-17 (0) |
| 36 KO-DA-MA | LEVEL 0-255 (255), TAP 0-255 (128), HIGH CUT 0-14 (14), HIGH DAMP 0-81 (81), LOW DAMP 0-81 (81) |
| 37 HA-DOU | DENSITY 0-10 (10) |
| 38 TO-GU-RO | HOLD 0-1 (0) |
| 39 CASSETTE SIM | BALANCE 0-255 (255) |
| 41 SX DELAY | SYNC 0-1 (1), PHASE 0-1 (0), FBK ROUTE 0-1 (0), HF DAMP 0-17 (17), MOD SW 0-1 (0), MOD RATE 0-255 (0), MOD DEPTH 0-255 (0), EQ LOW 0-30 (15), EQ HIGH 0-30 (15), LEVEL 0-255 (255) |
| 42 VOCODER | COLOR 0-255 (0), LEVEL 0-255 (255) |
| 44 SX REVERB | TYPE 0-5 (3), PRE DELAY 0-125 (26), LEVEL 0-255 (255) |
| 46 BACK SPIN | MODE 0-5 (1), FLT MOD 0-255 (0), SYNC 0-1 (1), RESONANCE 0-255 (0), AMP MOD 0-255 (0) |
| 48 DJFX DELAY | HIGH CUT 0-14 (14), HIGH DAMP 0-81 (81), H DAMP F 0-14 (13), LOW DAMP 0-81 (81), L DAMP F 0-11 (8) |

## Checked in the emulator (not on hardware)

`python synth/test_fx_deep_edit.py OUT_DIR` (74 checks), on the image with its static constructors run
and the TOP page made on page entry, every chip byte logged, through the real UI dispatcher, DOOM OS's
filter, TOP's EXIT and knob handlers, the system and settings getters and setters, the effect select,
the chip reset and the DT1 builder:

- static: only the scatter pointer, the TOP vtable word and the builder's first ten bytes change inside
  the parent; one copy row added; the guards hold; nothing reaches into the ten bytes; the compiled
  settings are exactly the 142 the test derives itself from the parent and fxmap; every popup line fits;
- through the jump, every parameter ID on every slot (2,483 that send) and the whole boot chip reset
  (19,560 bytes, its 25 garbage frames included) send the parent's bytes; fxmap's address for all 142
  settings on all 4 buses;
- the page: the chord, browsing, editing (one frame per change, nothing else), every one of the 142
  settings stopping at the firmware's min and max, per-bus and per-effect values, the four other popups,
  the effect changing while open, EXIT;
- sending again, against the parent's own traffic: effect away and back through the stock MFX choice,
  the system setter, an FxType sent straight to the builder as the bus swap does, and system init plus
  the chip reset followed by the effect chosen again: the edited values follow the FxType frame, and
  nothing else differs; a knob turn, another bus, the input FX and FxType 0 add nothing;
- outside the page: every key alone, EXIT and VALUE alone and in pairs, knobs, pads, the encoder, four
  quick EXITs (STOP), a lost VALUE release: as on the parent, with edited values held; while it is open,
  pads and knobs as on the parent, and EXIT or any other button closes it and goes on as on the parent.

The kit suites (test_kits, capture, chord, shortcut, midi, restart, hot resample, test_kit_bounce flow,
13 kits and 4 tweaked) pass on the image. test_start_fix passes on its own release; on this image its
trim and threshold checks pass and its 4 structural checks fail by design (they assert the start fix is
the top stage). Two builds from different build folders are byte-identical.

## Not known (the hardware test, or later)

- What the numbers mean, and whether the chip uses the firmware's ranges.
- Whether the chip's own value for a never-sent parameter at power-on is the firmware's default (the
  page shows the default until edited).
- Whether the chip keeps a never-sent value across an effect change. The page re-sends after every
  FxType, so it should not matter.
- How a project load reaches the chip: stock re-selects effects through the same setters (so FxType goes
  out when the effect differs from the select's cache), but the load path itself was not traced. If a
  project load restarts the unit, the edits are gone like at power-off.
- BUS 3/4: stock's knobs write both slots 3 and 4; the page writes only the bus it shows.

## Build

```sh
python synth/build_fx_deep_edit.py PATH/kits-v9.46-test3/SP404MKII_APP1.bin OUT_DIR \
    --zig PATH/zig.exe --fxmap PATH/dm-404/core/fx/fxmap.json [--build-dir DIR]
python synth/test_fx_deep_edit.py OUT_DIR
```

Stock APP0 must sit beside the input APP1. keystone, unicorn and capstone on PYTHONPATH, Zig 0.13.0.
The manifest lists every setting with its ID, BUS 1 address, range and default, the patches and the
guards.
