# Chromatic mode: the 34 scales, folded, and a wider range

**Test 2 (chroma-test2)** changes three things; the section "Test 2" below has the details:
- the range is **-12..+27**: stock's bottom, and an octave above stock's top (test 1 went to -36..+18);
- on the chromatic page, **VALUE held and turned** moves the scale, one a turn; with SHIFT held too, the key;
- a VALUE tap steps the next scale **at its release**, and a popup names every scale or key change.

A hardware test build on top of the published Sound Generator + Kits v9.46 (APP1 `7b5fbcb4…684a`). In
chromatic mode:

- **VALUE press** steps through the Sound Generator's 34 scales (stock: Chrom and six), and the screen names
  them (the fork's eight-character labels from `scales.json`).
- **The pads walk the scale**, the way the Sound Generator's pads do (`scales.c`): every pad plays the next
  note of the scale, none is dark or silent. Chrom is stock's chromatic layout.
- **The range is wider**: the pads reach 3 octaves below the sample's pitch (stock 1) and up to +18
  semitones (stock +15). VALUE turns still move the pads a row (4 pads), SHIFT + VALUE one pad; with a scale
  a pad is a scale note.
- Every pad of the range plays, lights and shows its note (stock's chromatic page plays, lights and shows a
  pad only within -12..+12).

With Chrom and a stock shift (-8..4) the pads within -12..+12, MIDI out and recording are stock's, bit for
bit; the pads above +12 (stock's top row at shifts -8..-5), which stock's page leaves dark and silent, play.

## How stock does it (5.52, unchanged in ED5E / v9.46)

- Chromatic mode is project param 0xBF (`[0x805923f8 + 0xc]`); the sample is pad 0xC1's. Pad p plays
  `T[p] - shift` semitones, `T = {4..7, 0..3, -4..-1, -8..-5}` (top row to bottom row), shift = param 0xC0
  (project `+0x2c`, range -8..4). The chromatic page is page 0x18 (key handler `0x801120d8`): a VALUE turn
  moves the shift 4, SHIFT + VALUE 1, ROLL + VALUE moves the root (0xF2, `+0x11c`, 0-11), VALUE press steps
  the scale (0xF1, `+0x118`) through 0-6 (`0x8011247e`; page 0x11 has the same code at `0x80083992`).
- A scale only darkens and silences the pads outside it: `mask[(T[p] + 24 - shift - root) mod 12]` with the
  six stock masks (`0x801ab4bc` for the lights, `0x801ab3b0` for the key handler; C's truncating mod).
- Each user of the note has its own copy of T and subtracts the shift: the voice manager (`0x801aa0a0`, five
  sites), the pad lights (`0x80028f64`), SMPL TASK's pad events and MIDI out (`0x80050ee0`), the last-note
  display (`0x801aa0e0`), the key handler, pattern step entry and roll entry (`0x801aa120`).
- The note becomes the voice's pitch through `0x8001fa20` param 0x73: `2^(n/12)` as a Q14 step, no limit.
- A chromatic note-off finds its voice by the physical pad (slot `+0x48`), not by the note, so the mapping
  can change while a pad is held without leaving a voice on.
- MIDI out (`0x800549e0`) sends note 48 + n on channel 16. SMPL TASK keeps `n + 13` per pad (project
  `+0x664`, a byte) and sends the note-off from it.
- The chromatic page's pad handler (`0x80111b38`) plays a pad only if its note is within param 0x9b's range,
  -12..12 (`0x80111c62`); the pad lights light it only within it (`0x800282f2`, `0x800283fa`) and the note
  display shows "-" outside it (`0x8008d224`). Pattern step entry checks it too (`0x80111c16`, `0x80111cdc`).
- The pattern recorder keeps the note as `n + 13` in 5 bits (-13..+18).

## The design

The module keeps all five copies of T at `T'[p] = note(T[p] - shift) + shift`, so every user reads the
folded note through its own stock code. `note(k)` is the Sound Generator's fold: from the first scale note at
or above the sample's pitch (0), k scale notes up or down; with Chrom it is k, so `T' = T`. The tables are
written again whenever the shift, scale or root changes (the setter's cases); a scale or root change brings a
shift outside the new range back to its nearest end, so the pads always play 16 notes within -36..+18.

| Site | Stock | Now |
|---|---|---|
| `0x800df714`, `0x800dfc00`, `0x800dfc14` | the setter's SHIFT / SCALE / ROOT cases: compare, store | the same, then the tables |
| `0x800d39e4` | SHIFT's range -8..4 | the range that keeps every pad within -36..+18 for the scale and root (Chrom: -11..28) |
| `0x800d38c8` | -12..12 for params 0x73 / 0x9b | -36..+18 for the chromatic page's pad gate, the pad lights and the note display (by return address); -12..12 for every other caller (step entry) |
| `0x800d39fc`, `0x800c5ca4` | the fork's jumps to the scale module's SCALE range and label bridges | in chromatic mode 0-33 and the names; elsewhere on to the scale module |
| `0x8011247e`, `0x80083992` | VALUE press: next scale, 0-6 | 0-33 in chromatic mode, stock's elsewhere |
| `0x80050e78` | MIDI note-off: stored byte - 13 | the byte read signed (notes below -13) |
| `0x800bd644` | the recorder takes the note byte | a chromatic note outside -13..+18 is not recorded |
| `0x801ab4bc`, `0x801ab3b0` (data) | stock's scale masks | the same masks with a period before each (negative indices) |

The module (Zig 0.13.0, -Os, about 1.8 KB) is a new boot copy row in an 8 KB slot at
**`0x83FD7000`-`0x83FD9000`**, from the top of pad FX's planned room. The builder checks the slot against every
row of the input and every fork module's slot (KNOWN_SLOTS), and 28 guards (SHA-256 of every stock span the
module relies on).

Chromatic mode means param 0xBF on and not the Sound Generator page, which keeps the scale module's ways.

## Checked in the emulator (not on hardware)

`python synth/test_chroma.py OUT_DIR`: the parent and the image booted in Unicorn with their static
constructors; the project setter, getter, range method and label formatter, the UI dispatcher with DOOM OS's
page filter and the chromatic page (0x18), the pad handlers and the stock pad note, SMPL TASK's pad events,
MIDI out (logged), the pattern recorder (logged) and the pad lights (logged) run for real; the voices are
logged, not run.

- static: only the sites above change; guards, displaced bytes, mask lists, slot;
- tables: Chrom at every stock shift is stock's T, as on the parent; every scale x five roots x shifts
  across the range (977 settings) after real setter changes matches an independent model of the fold; a
  scale or root change at an extreme shift keeps 16 notes;
- ranges: SHIFT's range for every scale and root keeps every pad within -36..+18 (and one more step would
  leave it); VALUE turns move 4, SHIFT + VALUE 1, from -11 to 28 (stock -8 to 4); SCALE 0-33 in chromatic mode;
- VALUE press: 1 .. 33, 0 in chromatic mode, the pads following; outside it as the parent;
- names: stock's labels for 0-6, the scales' for 7-33 in chromatic mode; the parent's outside it;
- pads: every pad through the chromatic page and SMPL TASK at several scales, roots and shifts (to -36 and
  +18): MIDI out sends the model's note on and off, one voice note-on and note-off each; Chrom at stock shifts
  is the parent's within -12..+12, and the pads above +12 (silent on the parent) play;
- record: Chrom at stock shifts records as the parent; notes outside -13..+18 are not recorded;
- lights: as the parent within -12..+12 with Chrom; with scales every pad lit as the parent lights a scale
  note there.

## Not known (the hardware test, or later)

- How it sounds and plays: the folded layouts, the deep notes, the top notes (+16..+18 is above stock's +15;
  stage 2's study saw the resampler's source run short from about 3x speed).
- The VALUE press handler on page 0x11 (same code as page 0x18's) runs only in a state the emulator didn't set
  up; it gets the same change.
- A project saved with a scale and loaded: the tables follow the setter, which project load is expected to use
  (not traced). Turning VALUE or pressing it sets them in any case.
- Pattern step entry still takes only -12..12 (stock), the realtime recorder -13..+18.
- DOOM OS's own pages (piano roll) with chromatic notes outside stock's range.

## Test 2 (chroma-test2)

From the user's test of combined-test3: go higher, not lower; change scales faster; and a way to change the key,
since note repeat took ROLL + VALUE (stock's key change) for the roll speed.

### Range

- LO..HI is -12..+27. With Chrom, VALUE turns move the shift from 4 (the bottom pad at -12) to -20 (the top pad at
  +27); stock's is -8..4.
- Notes above +18 play, light and show, but patterns don't record them (the pattern keeps a note in 5 bits,
  -13..+18; `chroma_record`, as in test 1).
- With a scale, the shift counts scale notes in the same range. A sparse scale fills it: 16 pentatonic pads
  span about 3.2 octaves, so they cover -12..+27 nearly whole and VALUE turns move them little or not at all.
- No note goes below -13 now, so the signed note-off read (`0x80050e78`) and the masks' extra period change
  nothing; they stay, reading the same.
- `chroma_note_range_case` is C now (`chroma_note_range`: the same callers, LO..HI; the rest stock's -12..12).

### VALUE's push-turn

The chromatic page's vtable (`0x802213f4`, made by `0x80062a10`) takes two more words: key press (+0xd8,
`0x801120d8`) -> `chroma_key`, key release (+0xdc, `0x80111ad0`) -> `chroma_key_up`. A VALUE turn reaches the key
press as key 0x3f or 0x40 (the encoder slot +0xe0, `0x801120b8`, one key per event).

| Gesture (chromatic mode, chromatic page) | Stock / test 1 | Test 2 |
|---|---|---|
| VALUE tap | the next scale at the press | the next scale at the release; popup `Scale Maj` |
| VALUE held + turn | (the press already stepped) | the scale one a turn, round (33 -> 0); nothing at the release |
| SHIFT + VALUE held + turn | (the press already stepped) | the key one a turn, round (B -> C); popup `Key F#` |
| turn, SHIFT + turn | the pads 4, 1 | stock's |
| ROLL + turn | the key (stock); note repeat's roll speed in the combined build | the same |

- VALUE's press waits only when stock's press would step the scale: not while something is over the page
  (`0x800ce420`), nor while the press goes to the base class (`0x800c3f18`). Then it is stock's.
- A change goes through the project setter (the tables follow), asks for the pad lights (`0x802496f0` |= 2) and
  ends the way the key handler does (`0x801125dc`: the page's 16 parts drawn again).
- The popup is `Scale ` or `Key ` and the value's own label (the label formatter `0x800c5168`: stock's names,
  the scales' in chromatic mode).
- Page 0x11's VALUE press (`0x80083992`) still steps at once.
- 12 more guards (40): the key handler's entry, VALUE and turn cases and end, the key release, the encoder slot
  and its vtable word, `0x800ce420`, `0x800c3f18`, the popup, the label formatter's entry.

### Checked in the emulator

`test_chroma.py` on chroma-test2: the sections take the new range, and a new section `push` (6 checks):
- a tap steps at the release;
- held and turned, the scale goes 1, 2, 3, 2, 1, 0, 33, 32 and the release adds nothing;
- with SHIFT, the key goes B, Bb, B, C, C#; VALUE first and SHIFT after works too;
- the popups and the pads follow;
- without VALUE held, Chrom turns are the parent's, and ROLL + turn changes the key with a scale;
- VALUE as the base class's, and outside chromatic mode: as the parent.

All pass.

### Not known

- How +19..+27 sounds: the resampler reads the sample faster than 3x there (stage 2's study saw its source run
  short from about 3x).
- Whether turning VALUE while it is pushed is comfortable on the unit's knob.

## Build

```sh
python synth/build_chroma.py PATH/kits-v9.46-test3/SP404MKII_APP1.bin OUT_DIR --zig PATH/zig.exe [--build-dir DIR]
python synth/test_chroma.py OUT_DIR
```

Stock APP0 must sit beside the input APP1. keystone, unicorn and capstone on PYTHONPATH, Zig 0.13.0.
