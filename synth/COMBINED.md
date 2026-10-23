# Combined: every feature test build in one APP1

**combined-test5** (section 6) follows the user's test of combined-test4: bounce, FX deep edit and note repeat
at their new revisions, the rest as in combined-test4 (section 5), then the fast boot. Sections 1-4 describe
combined-test1.

A hardware test build (`combined-test1`) with the latest test build of each feature in one APP1, so they can
be tried together. Branch `claude/combined`: the six feature branches merged on `main` (v9.46), plus
`build_combined.py`, which runs each feature's own builder in turn. Nothing in a feature changes: each module
is byte for byte the one in its own test build.

| Step | Feature | Branch | Builder | Slot | Module as in |
| --- | --- | --- | --- | --- | --- |
| 1 | bounce in place, stage 3 | `claude/bounce-stage3` | `build_bounce.py` | `0x83FE8000` 20 KB | `bounce-3-test7` |
| 2 | FX deep edit | `claude/fx-deep-edit` | `build_fx_deep_edit.py` | `0x83FE2000` 16 KB | `fx-deep-edit-test1` |
| 3 | pad envelopes, stage 1 | `claude/pad-env-pitchfilter` | `build_pad_env.py` | `0x83FDE000` 16 KB | `pad-env-test5` (stage 1) |
| 4 | pad envelopes, stage 2 | `claude/pad-env-pitchfilter` | `build_pad_pitch_filter.py` | `0x83FD9000` 12 KB | `pad-env-test5` |
| 5 | kit edits saved | `claude/kits-save` | `build_kits_save.py` | `0x83FD5000` 8 KB | `kits-save-test1` |
| 6 | note repeat | `claude/note-repeat` | `build_note_repeat.py` | `0x83FDC000` 8 KB | `note-repeat-test2` |
| 7 | chromatic scales | `claude/chroma-scales` | `build_chroma.py` | `0x83FD7000` 8 KB | `chroma-test1` |

Left out: the FX probe (`fx-probe-test1`). FX deep edit uses its TOP EXIT + VALUE chord and the same TOP
vtable slot (`0x8022ce64`), and the unit has answered the probe's questions.

## 1. Build

```
python synth/build_combined.py PARENT_DIR OUT_DIR --zig ZIG --fxmap dm-404/core/fx/fxmap.json --refs RELEASE_DIR
```

`PARENT_DIR` holds bounce-3-test7's parent, `resample-startfix-3` (`7d13c1e2…61cc`: the published v9.46's kit
stage plus the RESAMPLE start fix v3), with stock APP0 and its manifest. `RELEASE_DIR` holds the seven test
builds the modules are compared with. Each step writes `OUT_DIR-steps/<n>-<feature>/`; `OUT_DIR` gets the
final APP1, stock APP0, `manifest.json`, `SHA256SUMS.txt` and `steps/` (each step's own manifest).

The builder stops unless:
- each module's bytes are its test build's (blob SHA-256), and step 1's APP1 is bounce-3-test7's;
- on the final image, every step's patches are in place, its guards and table guards hold, its module is at
  its slot as built (with stage 2's links into stage 1), and no two slots overlap;
- APP1 ends below the 4 MB flash's end (`0x60400000`).

## 2. Order and guards

Every builder checks the code it relies on byte for byte (its guards) before it patches. So a builder runs
before the ones that patch inside its guards: FX deep edit and pad envelopes guard the UI dispatcher
`0x8003b530`, which note repeat bridges; note repeat guards the pad-event consumer (`0x80050be0..0x80050f20`)
and the pattern recorder (`0x800bd5a0..0x800bd7a0`), where chroma patches `0x80050e78` and `0x800bd644`.

One pair guards each other's site: note repeat guards the pad-event dispatcher `0x800bef10` that bounce
bridges, and bounce guards the pad note `0x800cdbd0` that note repeat bridges. Bounce goes first: its
builder refuses an APP1 past the kit PCM planning boundary, which the later modules cross. So note repeat's
builder checks an input with bounce's ten bytes at `0x800bef10` put back to stock, and its output gets them
again (`FOREIGN`). The step's manifest records it.

On the final image, 7 guards span another feature's hook. Each one holds with that hook's bytes put back to
stock, and `SHARED` says why its reason still holds:

| Guard (whose) | Hook inside it (whose) | Why it still holds |
| --- | --- | --- |
| pad note `0x800cdbd0` (bounce, 2 spans) | `0x800cdbd0` (note repeat) | note repeat's pad note acts only for the stock pad handler's press and HOLD let-go callers. Bounce triggers its source from its own code (`F_TRIGGER`), which goes straight on to the stock body |
| UI dispatcher `0x8003b530` (FX deep edit) | `0x8003b530` (note repeat) | the entry takes VALUE (press and release) only while ROLL is held, and VALUE turns only while ROLL is held or latched with a pad repeating. EXIT + VALUE on TOP reaches `fde_filter` |
| UI dispatcher `0x8003b530` (pad envelopes) | `0x8003b530` (note repeat) | the same: the ENVELOPE page's SHIFT and DEL are never taken |
| pad-event dispatcher `0x800bef10` (note repeat) | `0x800bef10` (bounce) | bounce's gate passes every event to the ring as stock unless a bounce owns the recorder. Then it drops note-ons except its own trigger, so repeats during a take are dropped like any other pad |
| pad-event consumer (note repeat) | `0x80050e78` (chroma) | chroma's note-off reads the stored note signed. The consumer still gives a type-4 note to the recorder, then plays it or lets it go |
| pattern recorder (note repeat) | `0x800bd644` (chroma) | `chroma_record` records a pad note with its note byte and goes on with the recorder, so a repeat is recorded as a tap, with chroma's note |

Nothing else is shared:
- **PADCONF reserved bytes:** pad envelopes stage 1 uses `0x64-0x6F`, note repeat `0x70`, stage 2 `0x71-0x7F`.
- **Files:** kits save writes its own `SG_KITS.BIN`.
- **RAM:** each module's state is in its own slot.

## 3. Size

APP1 is 3,148,576 bytes. That is 43,808 bytes past the kit PCM planning boundary (`0x60376000`, where
`kits/build_arp_kit.py` plans a PCM bank that holds nothing yet), as pad-env-test5 already was. It is
521,440 bytes below the end of the 4 MB flash (`0x60400000`).

## 4. Checked

**combined-test1:** APP1 `10616541…eb84`. The build passed every check in section 1. Unicorn, 2026-10-21, with
`analysis/kit_pr1_audit/dev_combined/run_suites.py`:
- Each feature suite ran on the final APP1, with that step's manifest re-pointed at it (`make_views.py`).
- The kit and start-fix suites ran on it through the v9.46 kits manifest and the start fix v3 manifest.

| Suite | Result | What fails |
| --- | --- | --- |
| `test_bounce.py` | 528 of 535 cases | 7 layout checks: the parent's bytes, the last two rows, the PCM boundary |
| `test_fx_deep_edit.py` | every behaviour check | 2 layout checks; against a parent without note repeat, also ROLL (key 0x21): it latches note repeat now |
| the same, parent: this chain without FX deep edit (`variant.py`) | every behaviour check, ROLL included | 2 layout checks; its UI dispatcher guard (note repeat's hook, `SHARED`) |
| `test_pad_env.py` (stage 1) | the audio and envelope sections (31) | 2 layout checks. The UI section stops at page 5, which stage 2 adds: the test knows 4 pages |
| the same, on step 3's output (stage 1, before stage 2) | 62 of 62 | |
| `test_pad_pitch_filter.py` (stage 2, all 8 pages) | 42 of 44 | 2 layout checks |
| `test_kits_save.py` | 120 of 122 | 2 layout checks |
| `test_note_repeat.py` | every behaviour check (97 cases) | the parent is not v9.46, 2 layout checks, its guard on bounce's gate (`SHARED`) |
| `test_chroma.py` | all | |
| `test_start_fix.py` (v3) | every behaviour check | 4 layout checks (the last row) |
| kit suites: kits, capture, chord, shortcut, midi, restart, hot resample, bounce (13 kits, 4 tweaked, flow) | 25 of 25 | |

The final scatter table is the parent's 25 rows plus the 8 rows the steps added, in order: bounce's
copy and zero-fill rows, and one copy row for each of the six other modules.

**One interaction found:** on the chromatic page, stock's ROLL + VALUE moves the root. Note repeat takes
VALUE turns while ROLL is held, so there it steps the roll division instead. That is
note-repeat-test2's behaviour on its own as well (NOTE_REPEAT.md section 5). The combination doesn't
change it.

**Not run:** dm-404 (not built on this machine: no `build/`, no MSYS2), and the unit.

## 5. combined-test4

From the user's test of combined-test3, every change in one build. Branch `claude/combined` merges the feature
branches at these revisions and `claude/boot-anim` (the fast boot); `build_combined.py` runs eight steps, then
`build_fast_boot.py` on its result, as for combined-test3.

| Step | Feature | Module as in | What changed since combined-test3 |
| --- | --- | --- | --- |
| 1 | bounce in place | `bounce-3-test8` | a pad tap picks the target (the source REPLACE, an empty pad TO PAD, a used pad PAD NOT EMPTY); RESAMPLE starts |
| 2 | FX deep edit | `fx-deep-edit-test2` | an FX button's screen stays (as REMAIN + FX); VALUE steps its screens, then the extra screens on CTRL 1-3 |
| 3, 4 | pad envelopes | `pad-env-test6` | page 1 named on its bottom line, TIME on VALUE press, VALUE turns the pages, no DROPS |
| 5 | kits save | `kits-save-test2` | an arp for each mode; the Sound Generator's settings saved per project (SG_KITS.BIN version 2) |
| 6 | note repeat | `note-repeat-test3` | chromatic rolls: 1/16 from power-on, nothing taken from the pad under the finger (pad 10) |
| 7 | chromatic scales | `chroma-test2` | -12..+27; VALUE held and turned: the scale; with SHIFT: the key |
| 8 | SUB PAD on the SG page | `sg-subpad-test1` | new: SUB PAD plays the last pad again, in melodic and drum mode |

- **Build:** every module byte for byte its own test build's; every patch in place and every guard holding on the
  final image, with the same 7 reviewed overlaps (`SHARED`) as combined-test1; no new one. `--refs` takes a folder
  of the seven test builds' manifests (`analysis/kit_pr1_audit/dev_combined4/refs`); the builds themselves are in
  the dev folders.
- **APP1** (after the fast boot): `adcb6f70…157f`, 3,151,616 bytes, in `analysis/kit_pr1_audit/release/combined-test4`.
- **SUB PAD's slot** `0x83FD4000`-`0x83FD5000` comes from the top of pad FX's planned room, below kits save.

**Checked** (Unicorn, 2026-10-22, `analysis/kit_pr1_audit/dev_combined4/run_suites.py`): every suite on the
flashable APP1 (fast boot included), each feature suite with its step's manifest re-pointed at it.

| Suite | Result | What fails |
| --- | --- | --- |
| `test_bounce.py` | 15 of 22 sections | 7 layout checks (the parent's bytes, the last rows, the PCM boundary, now 46,848 bytes over) |
| `test_fx_deep_edit.py` | 66 of 69 | 2 layout checks; against its parent (bounce only), ROLL (key 0x21): it latches note repeat now |
| `test_pad_env.py` (stage 1) | 29 | 2 layout checks; the UI section stops at page 5, which stage 2 adds (the test knows 4 pages) |
| the same, on step 3's output (stage 1, before stage 2) | 64 of 64 | |
| `test_pad_pitch_filter.py` | 42 of 44 | 2 layout checks |
| `test_kits_save.py` | 167 of 169 | 2 layout checks |
| `test_note_repeat.py` | 98 of 102 | the parent is not v9.46, 2 layout checks, its guard on bounce's gate (`SHARED`) |
| `test_chroma.py` | 35 of 38 | 2 layout checks; ROLL + VALUE turned no longer moves the key: note repeat takes it for the roll speed, as chosen (the key is SHIFT + VALUE held and turned) |
| `test_sg_subpad.py` | 24 of 25 | 1 layout check |
| `test_start_fix.py` (v3) | every behaviour check | 4 layout checks (the last row) |
| kit suites: kits, capture, chord, shortcut, midi, restart, hot resample, bounce (13 kits, 4 tweaked, flow) | 25 of 25 | |

The patcher test (`node synth/test_browser.cjs`, branch `claude/publish-v9.47`) passes with v9.47 = combined-test4.
**Not run:** dm-404, and the unit.

## 6. combined-test5

From the user's test of combined-test4, in one build. Branch `claude/combined` merges the three feature branches
at their new revisions; the other five steps are combined-test4's. `build_combined.py`, then `build_fast_boot.py`.

| Step | Feature | Module as in | What changed since combined-test4 |
| --- | --- | --- | --- |
| 1 | bounce in place | `bounce-3-test9` | a replaced pad sets up as a bounce (VALUE press for UNDO and back); the target pad lit steady white |
| 2 | FX deep edit | `fx-deep-edit-test3` | no FX button hold (it kept MFX's effect choice away); the extra screens on REMAIN + FX's screen |
| 6 | note repeat | `note-repeat-test4` | chromatic rolls: each pad its own division (byte 0x70 bits 4-7), 1/16 to start |

- **Build:** every module byte for byte its own test build's (`--refs analysis/kit_pr1_audit/dev_combined5/refs`);
  every patch in place and every guard holding on the final image, with the same 7 reviewed overlaps (`SHARED`).
  Bounce's new guard (the key light `0x800d4910`) covers code nothing patches.
- **APP1** (after the fast boot): `634f7af1…0bef`, 3,151,952 bytes, in `analysis/kit_pr1_audit/release/combined-test5`
  (the combined build before it: `292462e7…9a0a`).
- **The clicks** the user heard on chromatic rolls are RETRIG CUT on the sample's pad (NOTE_REPEAT.md 9.2): each
  repeat stops the ringing note as a re-hit does; RETRIG set to a fade fades it instead.

**Checked** (Unicorn, 2026-10-22, `analysis/kit_pr1_audit/dev_combined5/run_suites.py`): every suite on the
flashable APP1 (fast boot included), each feature suite with its step's manifest re-pointed at it. The same
results as combined-test4's, with the new checks passing.

| Suite | Result | What fails |
| --- | --- | --- |
| `test_bounce.py` | 543 cases, 15 of 22 sections | 7 layout checks (the parent's bytes, the last rows, the PCM boundary, now 47,184 bytes over) |
| `test_fx_deep_edit.py` | 65 of 68 | 2 layout checks; against its parent (bounce only), ROLL (key 0x21): it latches note repeat now |
| `test_pad_env.py` (stage 1) | 29 | 2 layout checks; the UI section stops at page 5, which stage 2 adds (the test knows 4 pages) |
| the same, on step 3's output (stage 1, before stage 2) | 64 of 64 | |
| `test_pad_pitch_filter.py` | 42 of 44 | 2 layout checks |
| `test_kits_save.py` | 167 of 169 | 2 layout checks |
| `test_note_repeat.py` | 99 of 103 | the parent is not v9.46, 2 layout checks, its guard on bounce's gate (`SHARED`); every chromatic check passes |
| `test_chroma.py` | 35 of 38 | 2 layout checks; ROLL + VALUE turned is the roll speed, as chosen |
| `test_sg_subpad.py` | 24 of 25 | 1 layout check |
| `test_start_fix.py` (v3) | every behaviour check | 4 layout checks (the last row) |
| kit suites: kits, capture, chord, shortcut, midi, restart, hot resample, bounce (13 kits, 4 tweaked, flow) | 25 of 25 | |

The patcher test (`node synth/test_browser.cjs`, branch `claude/publish-v9.47`) passes with v9.47 = combined-test5.
**Not run:** dm-404, and the unit.

## 7. combined-test6

From the user's test of combined-test5: the FX deep edit's extra screens never came (VALUE only flipped screens
1 and 2), and the drum kit screen's "SHIFT: PAGE" should go. `build_combined.py` with FX deep edit at
`fx-deep-edit-test4` (the input FX gets the extra screens too; an effect without any says NO EXTRA SETTINGS), the
other seven steps as in combined-test5; then `build_fast_boot.py`; then the new `build_kit_footer.py`.

- **Kit footer:** the kit stage's `kit_ui_footer_draw` (`kits/kit_ui.inc`) clears the Sound Generator page's footer
  while a kit is on and draws "SHIFT: PAGE" there (the first draw after entering drum mode showed it in the big
  font, cut to "SHIFT: PA"). The kit stage is baked into every feature build's parent, so the text goes in a step on
  top, as the fast boot does: the string's first byte at `0x83fbaf36` (the kit blob's boot copy row to
  `0x83fa2000`) becomes 0, so the footer is cleared and nothing is drawn. Guards: the 12 bytes, the footer's one
  literal for them (`0x83fa7718`) and that nothing else in the image refers to them.
- **APP1:** `e54935c3…d6e6`, 3,152,352 bytes, in `analysis/kit_pr1_audit/release/combined-test6` (the combined build
  `7fd46808…bf57`, after the fast boot `52d91be4…23e9`). Every module byte for byte its own test build's; the same
  7 reviewed overlaps.

**Checked** (Unicorn, `analysis/kit_pr1_audit/dev_combined6/run_suites.py`, which takes a list of suites now): on
the final APP1, `test_fx_deep_edit.py` 65 of 68 (the same 2 layout checks and ROLL's key as on combined-test5)
and the kit suites kits, capture, chord, shortcut, midi, restart and hot resample pass. The kit suites check the
kit module's two hashes first; the runner re-points them at the module with the footer's one byte, and says so
in the view's manifest. Not rerun: the other feature suites and the 18 kit bounce runs, whose modules and code
are combined-test5's byte for byte. The patcher test passes with v9.47 = combined-test6.

## 8. combined-test7

From the user's test of combined-test6: the FX deep edit's extra screens still never came, on the main screen with
every FX button, and never the NO EXTRA SETTINGS note; screen 2 never stayed for more VALUE presses. So the FX
screen was not "held" when VALUE came (held is decided once, by REMAIN being down when the screen shows), and the
module stepped aside. FX deep edit at `fx-deep-edit-test5`: a VALUE press holds the screen itself when the effect
has screen 2 or extra settings, then steps on. The rest as in combined-test6, then the fast boot and the kit footer.

- **APP1:** `be758f67…34b4`, 3,152,432 bytes, in `analysis/kit_pr1_audit/release/combined-test7` (the combined build
  `94d2786c…8ea7`, after the fast boot `407d4a99…2b70`). Every module byte for byte its own test build's; the same 7
  reviewed overlaps.

**Checked** (Unicorn, `analysis/kit_pr1_audit/dev_combined7/run_suites.py`): on the final APP1,
`test_fx_deep_edit.py` 67 of 70 (the same 2 layout checks and ROLL's key) and the kit suites kits, capture, chord,
shortcut, midi, restart and hot resample pass (the kit module's hashes re-pointed for the footer byte). Not rerun:
the other feature suites and the 18 kit bounce runs (their modules are combined-test5's byte for byte). The patcher
test passes with v9.47 = combined-test7.

## 9. combined-test8

A user reported that the Compressor's hidden MODE setting on v9.47 (combined-test7) made the output dangerously
loud, and the user asked for the NO EXTRA SETTINGS note to go. FX deep edit at `fx-deep-edit-test7`: the
builder leaves the Compressor's MODE out of its table (`EXCLUDED`), and an effect without extra settings keeps
stock's VALUE with no popup. The rest as in combined-test7, then the fast boot and the kit footer.

- **APP1:** `fbcff606…e9f0`, 3,152,272 bytes, in `analysis/kit_pr1_audit/release/combined-test8` (the combined build
  `7e294a75…a4d6`, after the fast boot `7fb4371c…2c96`). Every module byte for byte its own test build's; the same 7
  reviewed overlaps. Only the FX deep edit module differs from combined-test7.

**Checked** (Unicorn, `analysis/kit_pr1_audit/dev_combined8/run_suites.py`): on the final APP1,
`test_fx_deep_edit.py` 68 of 71 (the same 2 layout checks and ROLL's key; the Compressor has no extra settings,
Crusher's VALUE shows no popup) and the kit suites kits, capture, chord, shortcut, midi, restart and hot resample
pass (the kit module's hashes re-pointed for the footer byte). Not rerun: the other feature suites and the 18 kit
bounce runs (their modules are combined-test7's byte for byte). The patcher test passes with v9.48 = combined-test8.

## 10. combined-test9

A user's report on v9.48 (combined-test8): on the Super Filter's extra screens CTRL 2 spiked the volume (FLT
GAIN, 0-12, is CTRL 2 on the first). The user asked for the Super Filter's hidden settings to go. FX deep edit at
`fx-deep-edit-test8`: all six are on the builder's `EXCLUDED` (135 settings remain). The rest as in combined-test8,
then the fast boot and the kit footer.

- **APP1:** `8f285b01…4750`, 3,152,144 bytes, in `analysis/kit_pr1_audit/release/combined-test9` (the combined build
  `484b4d3a…9184`, after the fast boot `c45a4ca9…2a60`). Every module byte for byte its own test build's; the same 7
  reviewed overlaps. Only the FX deep edit module differs from combined-test8.

**Checked** (Unicorn, `analysis/kit_pr1_audit/dev_combined9/run_suites.py`): on the final APP1,
`test_fx_deep_edit.py` 69 of 72 (the same 2 layout checks and ROLL's key; the Super Filter and the Compressor have
no extra settings) and the kit suites kits, capture, chord, shortcut, midi, restart and hot resample pass. Not
rerun: the other feature suites and the 18 kit bounce runs (their modules are combined-test7's byte for byte). The
patcher test passes with v9.49 = combined-test9.
