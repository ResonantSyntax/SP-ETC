# Kits save: the kit edits saved with the project

A hardware test build (`kits-save-test1`) on the published Sound Generator + Kits v9.46 (APP1 `7b5fbcb4…684a`:
stock 5.52 + DOOM OS 0.6.1 ED5E + the fork). In v9.46 every drum-mode edit lives in RAM and resets at power-on
(README: "Kit edits reset at power-on"); a user lost a customised kit that way. This build saves the edits per
project in a small file beside the project's `PADCONF.BIN`, so each project keeps its own kits.

Addresses are 5.52 runtime addresses. **Verified** means read in the code (Ghidra decompilation and capstone)
and, where marked, run in Unicorn; **inferred** means it follows from the code but wasn't run; **unknown**
needs the unit.

## 1. What is saved

| Saved in the project's file | Not saved (as in v9.46) |
| --- | --- |
| every pad of all 13 kits: SOUND, Tune, Decay, Tone, LEVEL, Sweep, Noise, Attack | the selected pad (PAD), the knob page (SHIFT), the VALUE cursor |
| the current kit (the one SHIFT + PATTERN EDIT opens) | drum or melodic mode: the Sound Generator still starts melodic at power-on |
| M.CH | NOTE (root), OCT, OFST, TUNE |
| ARP, RATE, A.OCT, HOLD (both modes share them) | the melodic knobs (TYPE, FREQ, LEVEL, DUTY, BALANCE) and Pad Length |
| ENV, SCALE | BOUNC's state, held notes, sounding voices |

ENV, SCALE, the arpeggiator and M.CH were asked for; they cost 8 bytes. The other melodic settings stay as
v9.46 has them (RAM, power-on values). A project without the file gets the power-on values of everything in
the left column: factory kits, TR808, M.CH 16, ARP OFF, RATE 1/16, A.OCT 0, HOLD OFF, ENV 4, SCALE Chrom (the
builder reads these from v9.46's boot image; Unicorn shows the same after the boot's constructors).

## 2. The file: `SG_KITS.BIN`

`B:/ROLAND/SP-404MKII/PROJECT_nn/SG_KITS.BIN` (internal projects), or
`A:/EXPORT/PROJECT/PROJECT_nn/SG_KITS.BIN` for a project on the SD card (settings 0x84 = 1). The module builds
the path with the stock PADCONF path builder `0x800cf018` and swaps the file name, so it is always beside the
project's `PADCONF.BIN`, wherever the stock keeps that.

Why this name: 8.3 (no long-name support needed), upper case like the stock's `PADCONF.BIN`; `SG` because it
belongs to the Sound Generator (it also holds the melodic ENV, SCALE, arp and M.CH, so not just "kits"); and it
is unlike every name the stock uses (`PADCONF.BIN`, `PAD_INFO.BIN`, `STPINFO.BIN`, `QSPI.bin`, `BKUP%02d.bin`),
so neither firmware can take it for one of its own. It sits in the project folder, not in `SMPL/` or `PTN/`,
which the stock scans (the project-content test `0x80188d08` looks only there).

Layout (1688 bytes, little-endian):

| Offset | Size | Contents |
| --- | --- | --- |
| 0x00 | 4 | magic `SGKT` |
| 0x04 | 2 | version 1 |
| 0x06 | 2 | header size 16 |
| 0x08 | 4 | payload size 1672 |
| 0x0c | 4 | CRC-32 (IEEE, as zlib's) of the payload |
| 0x10 | 1664 | `kit_pads[13][16]`: sound, tune, decay, tone, level, sweep, noise, attack per pad |
| 0x690 | 8 | kit 1..13, M.CH 0..15 (= 1..16), ARP 0..6, RATE 0..6, A.OCT −3..3, HOLD 0..1, ENV 0..9, SCALE 0..33 |

A file that is missing, shorter or longer than 1688 bytes, has another magic, version, header or payload size,
a CRC mismatch, or any value outside what the knobs and menus can set (sound 0..142 or 255 = off, Tune −12..12,
Decay/Tone/Sweep/Noise/Attack 0..100, LEVEL 0..127, the ranges above) gives the power-on values, as if there
were no file. The bad file stays as it is until the kits change; then a good one replaces it.

**Stock firmware** opens files by name and never asks for this one, so it ignores it (verified: the name is
not in the stock image; the content test looks only in `SMPL/` and `PTN/`). A project used on stock and back keeps
its file. The stock project import and copy (command 0x65, `0x8008a188`) delete the destination folder
(`0x8005cc98`, recursive) and copy `SMPL/` and `PADCONF.BIN` only: a copied or imported project starts with
the power-on kits, and an old file in the destination does not survive (verified in the code, not run). Project
delete and export were not traced.

## 3. When it is read

The stock PADCONF load `0x8018ae68` (its entry patched) loads the current project's pad parameters. Every
load (verified in Unicorn), before the stock body:

- If its project (its file's path) is not the one whose kits are in RAM: unsaved edits of that project are
  written to its own file first (§4), then the new project's file is read: its kits, or the power-on values.
- If it is the same project (a single pad reload after an import, or loading the project again): RAM stays,
  edits not yet saved included, unless the card changed under it (the file deleted, replaced or made bad by a
  project import or delete); then RAM follows the card.

The boot loads the current project through the same function (inferred: a storage event handler,
`0x80078550`, posts command 3, which reaches `0x800554d0` → `0x800a1958` → `0x80184fd0` → `0x8018ae68`; read
in the code, not run; in Unicorn the load is called directly). A project change (commands 1, 4, 0x65, 0x66, 0x405 →
`0x800a1958`) goes the same way. Kit mode stays melodic at power-on, as in v9.46; SHIFT + PATTERN EDIT opens
the saved kit. A project load with kits mode on (the page closed) switches it to the new project's kit.

## 4. When it is written

Only when the kits in RAM differ from what the card holds for that project, never from the audio task, and
never while the recorder is armed or recording (sampling, RESAMPLE, a hot resample: recorder state
`0x82e0e755` 1, 2 or 3) or a BOUNC runs (`kit_bounce_state` = 2). Writes always go to the project the kits
belong to.

1. **About 2 s after the last change on the Sound Generator page.** Each screen update (SG vtable +0xd0, the
   UI task; the page asks for one every 50 ms with `0x800c7da0(0x32)`, the tick not measured on the unit)
   hashes the kits; after 40 updates without a change, if they differ from the card, the module posts command
   0xd (`0x800e25c0(0xd, 'SGKT', 0)`, as the stock pad setter posts its saves). Knob turns, VALUE steps and
   MIDI CCs only restart the count: one write per burst, never per step.
2. **When the page closes** (SG vtable +0x04, its deleting destructor; the UI task): the same post at once.
3. **With the stock PADCONF save** `0x800cf218` (its entry patched), for that project, in the stock's own
   task: after a pad edit, a REC or RESAMPLE take (the finalize clears the recorder state before its saves), a
   BOUNC pad, an import.

SMPL TASK runs the posted command 0xd: the real dispatcher calls the PADCONF save, the module writes
`SG_KITS.BIN` there, and for its own post (the call from `0x8004e2e4` with a1 = `'SGKT'`) it leaves the stock
body out unless CSmplPrm is edited: the module's saves never rewrite `PADCONF.BIN` (52 KB) on their own
(verified in Unicorn: no open of `PADCONF.BIN`; with CSmplPrm edited, `PADCONF.BIN` comes out as the parent
writes it). A stock command 0xd (a1 = 0 or 1) runs as before.

The write is `open(path, 0x601)` (create, truncate), one write of 1688 bytes, close, as the stock writes
`PADCONF.BIN`. A failed open or a short write is counted and the edits stay pending for the next moment. A
lock (`ks_busy`, ldrexb/strexb) keeps a save in one task from meeting a save or load in another; a save that
finds it held goes on without writing, a load waits up to 1 s.

What is lost if the power goes: edits made less than about 2 s before power-off while the page is open. If
the power goes during the write itself (a few ms), the file is short or bad and the project starts with the
power-on kits; the stock's `PADCONF.BIN` has the same window.

## 5. How

Two 5.52 entries jump to the module (`movw ip` / `movt ip` / `bx ip`, a `nop` after it where the displaced
instructions take 12 bytes); the module runs the displaced instructions and goes on:

| Site | Stock code | Now |
| --- | --- | --- |
| `0x800cf218` | PADCONF save (CSmplPrm, project or −1): `push.w {r4-r11, lr}; sub sp, #0x19c; mov r4, r1; mov sb, r0` | `ks_save_entry`: `ks_save_c(CSmplPrm, project, lr, r4)`, then the four instructions and on at `0x800cf222`, or `return 0` for the module's own post with CSmplPrm not edited |
| `0x8018ae68` | PADCONF load (CSmplPrm, flag): `push.w {r4-r11, lr}; sub sp, #0x154; str r1, [sp, #0x24]; movw r2, #0xc431` | `ks_load_entry`: `ks_load_c`, then the four instructions and on at `0x8018ae74` |
| `0x802295ac` | SG page vtable +0x04: `0x8015cef9` (deleting destructor) | `ks_sg_leave`, which goes on to it |
| `0x80229678` | SG page vtable +0xd0: `0x83fa7485` (the kits' `kit_ui_poll`) | `ks_sg_poll`: `kit_ui_poll(page, ms)`, then the module's update |

Nothing branches into the displaced instructions (checked by the builder over the whole image). The module
(Zig 0.13.0, `-Os`, 5,996 bytes with its buffers) goes in a new boot copy row in an 8 KB slot at
**`0x83FD5000`-`0x83FD7000`**, below the planned chromatic-mode module (`0x83FD7000`-`0x83FD9000`) and pad
envelopes stage 2 (`0x83FD9000`-`0x83FDC000`), taken from the top of the room pad FX was given: pad FX now has
`0x83FC9000`-`0x83FD5000` (48 KB; its study estimates 15 KB). The builder's `KNOWN_SLOTS` lists every fork
module's slot and refuses an overlap.

The kits module's variables (`kit_pads`, `kit_mode`, `kit_midi_channel`, the arp's settings and held list,
`kit_bounce_state`, …) are exported in v9.46's kits manifest; `kit_last_mode` (`0x83fc58d1`) and
`kit_init_pads` (`0x83fa7f84`) are static and found in the code (`kit_shortcut_select`'s
`if (kit_mode) kit_last_mode = kit_mode`; `kit_edit`'s first call). The builder checks the whole kits module
(`0x83fa2000`-`0x83fc8450` as booted) against v9.46 and those instructions by listing, so every address is
v9.46's. ENV is the SG singleton's +0x10 (`0x80249810`, settings 0x82's store `0x80019e30`, range 0..9 at
`0x80132658`), SCALE the stock keyboard state's +0xc (`0x80591c54`, stepped by the SG key handler within
project parameter 0xf1's range, 0..33 on the SG page with v9.6's scales).

Loading the factory kits is the kits module's own `kit_init_pads` (with `kit_pads_ready` cleared); a file's
pads are copied over them. An ARP or HOLD change clears the arp's held list with dispatch off, as the VALUE
menu does it; the Sound Generator page is not open while a project loads.

Every stock span the module calls, reads or relies on is checked byte for byte (`GUARDS` in the builder: the
path builder, the PADCONF save, the load's entry, the current project, the file calls, the post, SMPL TASK's
dispatcher and its command 0xd, the task delay, dispatch off/on, the SG deleting destructor, the ENV store and
range, the SCALE steps, the scales module, the kits module), and so is the caller whose return address the
module recognises (`0x8004e2e4`, command 0xd, `r4` = the command). The guards that other fork branches share
(the post, the dispatcher, command 0xd) have the same ranges and hashes as theirs.

## 6. Checks (emulator)

`synth/test_kits_save.py OUT_DIR` (122 checks, about 20 s): the built image and the parent are booted in
Unicorn as their scatter loaders do it, with the 70 static constructors run. Real: the stock PADCONF save and
load with everything under them but the file calls, the path builder, the post and SMPL TASK's dispatcher for
what the post queues, the settings setter, the kits' knob, VALUE-menu and arp code, the module. Modelled: the
card under the stock file calls (by path; failures on demand), the queue put, the kits' `kit_ui_poll` and the
stock deleting destructor (logged), dispatch off/on and the task delay (logged), the tempo calls.

- static: only the header, the two entries, the two vtable words and the appended tail differ from v9.46; one
  copy row added; the guards; the trampolines;
- boot without a file: the factory pads exactly as v9.46's `kit_init_pads` makes them and the other power-on
  values, nothing written, CSmplPrm as on v9.46 after the load; nothing posted however long the page stays open;
- round trip: edits through the kits' own code (KPR77 pads with all six knobs, SOUND, LEVEL, KIT to FM, M.CH 10,
  ARP DOWN, RATE 1/4T, A.OCT −2, HOLD ON, ENV 7, SCALE 21), saved by the module's own command 0xd through the
  real post and dispatcher: the file is exactly the expected bytes; a fresh boot with that card restores every
  value (melodic mode, the saved kit for SHIFT + PATTERN EDIT); closing the page saves at once; `PADCONF.BIN`
  untouched while CSmplPrm is not edited, as the parent writes it when it is;
- bad files (32 kinds: missing, empty, short, long, magic, two versions, header and payload size, CRC, a
  flipped payload bit, and 21 fields out of range with a good CRC): the power-on values, the file left alone
  until an edit replaces it; files at every extreme load as they are;
- projects: own files; unsaved edits flushed to their own project on a switch; a project without a file gets
  the defaults; the same project reloaded keeps RAM and writes nothing, follows the card when it changed;
  SD-card projects (settings 0x84) use `A:/EXPORT/PROJECT/PROJECT_nn`;
- moments: knob steps every 20 updates for 600 updates post nothing, then one write; recorder states 1, 2 and 3
  and a running BOUNC: no post from updates or the page close, no write from the stock save or a command 0xd,
  and the next save after them writes; another project's stock save never writes; a failed open or short
  write retries; a held lock skips a save and makes a load wait 1000 × 1 ms;
- the stock paths with the module present, against v9.46: a stock command 0xd, the PADCONF load, the screen
  update and the page close give the same files, CSmplPrm and calls.

Six mutants (no debounce, no recorder/BOUNC test, the stock body never skipped, no CRC check, no flush on a
project switch, no range check) each fail the suite. The kit suites run on the image as on the other stages
(v9.46's kits manifest re-pointed at it): test_kits, capture, chord, shortcut, midi, restart, hot resample,
bounce flow, the 13 kits and 4 tweaked kits all pass. test_start_fix passes on v9.46; on this image its
trim and threshold checks pass and its 4 structural checks fail by design (they assert the start fix is the
last stage), as on every stage image.

**Not tested** (needs the unit): writes and reads on the real card and FAT, their timing and the screen
updates' real period, the boot actually reaching the load with the card mounted, power loss during a write,
the SG page's destructor and update being called as read in the code, project copy / import / delete / export
with the file present, an SD-card project, USB storage mode, and how the file behaves with Roland's app or
librarian.

## 7. Test 2 (kits-save-test2): the Sound Generator, and an arp for each mode

From the user's test of combined-test3: turning the arp on in drum mode turned it on in melodic mode too (one arp
serves both in v9.46), and the Sound Generator's settings reset at power-on.

### 7.1 Each mode its own arp

ARP, RATE, A.OCT and HOLD are the kits module's variables, one set. The module keeps the set of the mode not on
now (`ks_arp_other`; `ks_arp_drum` says which mode the arp's own variables hold). At each screen update, before
the kits' own, a kit mode change puts the arp's settings away for the mode left and brings back the other mode's.
An ARP or HOLD change on the way lets go of the arp's held notes with dispatch off, as the VALUE menu does it. The
update comes every 50 ms while the page is open; the arp only plays there.

### 7.2 The Sound Generator's settings

| Saved | Where it lives | Range |
| --- | --- | --- |
| NOTE | keyboard state `0x80591c48` + 0x10 | 0..11 (project parameter 0xf2) |
| OCT | + 0x4 | -3..4 |
| OFST | + 0x8 | -4..11 |
| TYPE, FREQ, LEVEL (CTRL 1-3) | settings 0x7b, 0x7c, 0x7d | 0..31, -36..48, 0..127 |
| Pad Length, DUTY, BALANCE (SHIFT + CTRL 1-3) | settings 0x7e, 0x7f, 0x80 | -8..20, 0..100 (0..0 on TYPEs 0-9), -51..51 |
| TUNE | settings 0x81 | 4160..4640 (416.0..464.0 Hz) |

The settings go back through the stock setter (`0x800dd0c0`), TYPE first: it clamps to the range (DUTY's follows
TYPE) and gives the four voices the value too, as a knob does. NOTE, OCT and OFST are stored as the VALUE menu
stores them. A project without a file gets the power-on values, which the boot's load keeps before anything is
applied (`ks_power_on`): NOTE C, OCT 0, OFST 0, TYPE 0, FREQ 0, LEVEL 127, Pad Length 4, DUTY 0, BALANCE 0,
TUNE 440.0.

### 7.3 The file, version 2

1712 bytes: the header as before with version 2 and payload size 1696; the pads; then a 32-byte tail:

| Offset in the tail | Contents |
| --- | --- |
| 0..7 | as version 1: kit, M.CH, melodic mode's ARP, RATE, A.OCT, HOLD, ENV, SCALE |
| 8..11 | drum mode's ARP, RATE, A.OCT, HOLD |
| 12..15 | NOTE, OCT, OFST, 0 |
| 16..29 | settings 0x7b..0x81, signed 16 bits each, little-endian |
| 30..31 | 0 |

A version 1 file (1688 bytes, from kits-save-test1 or the combined builds) still loads: its arp for both modes,
the Sound Generator's power-on settings. It stays until something changes; then version 2 replaces it. Any field
out of its range, a non-zero reserved byte, or a version and size that don't go together is a bad file, as
before.

### 7.4 Checked in the emulator

`test_kits_save.py` (169 checks) passes on kits-save-test2: the sections above with the new layout, plus:
- each mode's arp: melodic ARP UP, 1/8T, HOLD ON, then drum mode brings its own (OFF, 1/16) with the held
  notes let go; drum ARP DOWN; back to melodic, its own again; both saved and restored at power-on; on v9.46 one
  arp serves both (the user's report);
- the Sound Generator: every setting saved, and restored at power-on with the SG singleton and its voices exactly
  as the knobs and the menu leave them on v9.46; a project without a file gets the power-on values; every field at
  both ends loads, one past each end is a bad file; a version 1 file loads as above, writes nothing, and becomes
  version 2 after a change.

## 8. Reproduce

```sh
python synth/build_kits_save.py out/kits-v946-final/SP404MKII_APP1.bin out/kits-save --zig /path/to/zig
python synth/test_kits_save.py out/kits-save
```

The input is v9.46's final APP1 (KITS.md, Reproduce) with the stock APP0 beside it. Two builds from different
build folders are byte-identical.
