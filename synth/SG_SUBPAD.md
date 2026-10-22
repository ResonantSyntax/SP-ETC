# SUB PAD on the Sound Generator page: the last pad again

A hardware test build (`sg-subpad-test1`) on the published Sound Generator + Kits v9.46 (APP1 `7b5fbcb4…684a`).
From the user's test of combined-test3: on the Sound Generator page, in melodic and in drum mode, SUB PAD should
play the last pad played, as it does elsewhere on the SP, instead of switching the tone on and off.

## What it does

- **SUB PAD** on the Sound Generator page plays the last of pads 1-16 pressed there (without SHIFT), at SUB PAD's
  velocity; letting go of SUB PAD lets that pad go. It goes through the page's own pad press and release, so the
  note, the scale, FIXED VELOCITY, the arpeggiator, drum mode, REC and the first-hit start work as for that pad.
- Before any pad has been played since power-on, SUB PAD does nothing.
- **Not counted** as the last pad: SHIFT + pad (which plays nothing on the page), MIDI notes, the arpeggiator's
  steps.
- **SHIFT + SUB PAD** stays stock: nothing.
- Everywhere else SUB PAD is stock.

## How stock does it (5.52 and v9.46)

The page's pad press (vtable `0x802295a8` + 0xfc, `0x8015bf90`) sends SUB PAD's event (0x13) to `0x8015bfac`.
There a press stops every voice if one sounds (the fork's poly hook), else it toggles the generator's tone. The
page's pad release (+0x100, `0x8015c4b0`) ignores SUB PAD.

## The build

Two words of the page's vtable change:

| Slot | Stock | Now |
| --- | --- | --- |
| `0x802296a4` (+0xfc, pad press) | `0x8015bf91` | `sp_press`: SUB PAD presses the last pad; pads 1-16 without SHIFT become the last pad; then the stock press |
| `0x802296a8` (+0x100, pad release) | `0x8015c4b1` | `sp_release`: SUB PAD's release lets that pad go; everything else the stock release |

The module (`sg_subpad.c`, Zig 0.13.0 `-Os`) goes in a new boot copy row in a 4 KB slot at `0x83FD4000`, the top of
the room pad FX was given (pad FX keeps `0x83FC9000`-`0x83FD4000`). Four guards: the page's pad press and release,
the UI dispatcher's SUB PAD event, the page's registry handler.

## Checked in the emulator (not on hardware)

`python synth/test_sg_subpad.py OUT_DIR` (25 checks): the image and v9.46 booted with their constructors, the
Sound Generator page opened through its registry handler, the page's pad press and release and the SG's note path
running for real (the notes logged as the SG's note event receives them, the voices not run). In melodic mode and
in drum mode (TR808):
- SUB PAD plays the last pad at SUB PAD's velocity, and its release lets that pad go; v9.46's SUB PAD toggles the
  tone instead;
- before any pad: nothing (v9.46: its voice check and tone toggle);
- SHIFT + pad plays nothing and leaves the last pad; SHIFT + SUB PAD does nothing;
- another pad pressed while SUB PAD is held: SUB PAD's release lets go of the pad it played, and the next SUB PAD
  plays the new last pad;
- every pad's press and release as on v9.46.

Not checked here: the arpeggiator, scales and OCT with SUB PAD (they run inside the page's pad press, which SUB
PAD now calls as a pad does).

## Build

```sh
python synth/build_sg_subpad.py PATH/kits-v9.46-test3/SP404MKII_APP1.bin OUT_DIR --zig PATH/zig.exe
python synth/test_sg_subpad.py OUT_DIR
```

Stock APP0 must sit beside the input APP1; keystone, unicorn and capstone on PYTHONPATH; Zig 0.13.0.
