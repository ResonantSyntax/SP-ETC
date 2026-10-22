# Boot animation: your own frames in a DOOM OS Boot Anim style

`build_boot_anim.py` puts your own frames in one of DOOM OS's boot animations. The style keeps its name in the
Boot Anim menu (SHIFT + pad 13 › SYSTEM › DOOM OS). Every other style and the rest of the APP1 stay as they
were. The frames are 128 x 64 images that you supply; none are in this repository.

```
python synth/build_boot_anim.py IN_APP1 OUT_DIR --frames DIR [--style hello] [--revision NAME]
```

`OUT_DIR` gets the APP1, stock APP0, `manifest.json`, `SHA256SUMS.txt` and `boot-preview.gif` (the style's 15
steps, decoded from the output as the blit reads them).

## How DOOM OS 0.6.1 ED5E does it

Verified by reading the code (capstone) and by decoding all 61 frames:
- **Storage:** the animations are in DOOM OS's `SPUA` block at `0x60307a00`, in flash, run in place. Its
  `BOOTANI` section holds 61 frames at `0x60309770`, 1024 bytes each. Frame 0 is blank.
- **Steps:** a table at `0x6033132c` gives each drawn style 15 steps (frame numbers). The boot screen
  (`0x60328b70`) draws step `min((t - 80) >> 2, 14)`, so the last step holds until the boot screen ends.
- **Pixel format:** frames go through the stock blit `0x800bdc48(context, frame, 0)`, which writes one byte a
  pixel. Screen pixel (x, y) is bit `31 - (i & 31)` of little-endian word `i >> 5`, where
  `i = 128 * (63 - y) + x`. So it's MSB first in 32-bit words, rows bottom-up. Flag 1 would invert.
- **Menu:** the Boot Anim value picks the style through the bytes at `0x60331324`. RANDOM (0) picks one at
  random but never the last one again; `B:/DOOMBOOT.DAT` keeps the last pick and the random state.

| Value | Menu | Style row | Frames it owns |
| --- | --- | --- | --- |
| 1 | GRAFFITI | 3 | 37-50 (14) |
| 2 | VHS | 4 | 51-60 (10) |
| 3 | HELLO | 2 | 24-36 (13) |
| 4 | BUBBLE | 0 | 1-12 (12) |
| 5 | SKETCH | 1 | 13-23 (11) |
| 6 | HYPERSPACE | 5 | none: drawn by code |

## What the builder changes

- **Frames:** your frames replace the style's own frames, in file-name order. There can't be more than the
  style owns.
- **Steps:** its row plays your frames, after the blank first step if the style had one, then repeats the
  last to fill 15 steps.
- **Pixels:** a pixel is lit from 50% grey up. Each frame is checked to decode back to its image.
- **Guards:** before anything changes, the builder checks the bytes it relies on by SHA-256: the `SPUA`
  block's section table, the 61 published frames, the step table, the menu table, the boot screen's draw code
  and the stock blit. They are the same in v9.46 and combined-test1.

## combined-test2 (2026-10-22)

combined-test1 with HELLO as the Homer car: 13 frames from a 1.7 s clip, played in reverse so the turn ends on
the car's front. The conversion was done by hand, outside this repository:
- **Crop:** the car's extent over the clip, 2:1.
- **Pixels:** its yellow and green lit, cut to its hull. The cartoon's black outlines were thickened before the
  3.3x shrink so they survive.

Only HELLO's frames and step row changed: 8,846 bytes. `build_combined.check_combined` still passes on the
image. Not run on the unit. The frames are from a TV clip, so the build is for the owner's unit only.
