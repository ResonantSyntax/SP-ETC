# Pad envelopes, stage 1: a better amplitude envelope per pad

A hardware test build on top of the published Sound Generator + Kits v9.46 (APP1 `7b5fbcb4…684a`). It is
stages E1 and E2 of the pad envelope study (`analysis/pad_envelope/REPORT.md`): finer attack and release
times, curves, decay and sustain, and two options for loops and reverse; and from E3a, a fade instead of
the cut when a new hit stops a pad's sounding voice. Everything is opt-in per pad.
**A pad you don't touch plays exactly as on v9.46**: it runs the stock code, and the emulator checks
compare it bit for bit with the parent.

## What it adds

| Setting | Values | Stock |
|---|---|---|
| TIME | STOCK (23.6 ms steps, 0-3 s) or FINE: 0, then 0.5 ms - 8 s in 127 steps of about 8 % | STOCK |
| Curves | LIN, EXP, LOG or S, separately for attack, decay and release | LIN |
| Decay | OFF, or 0.5 ms - 8 s (the FINE map) | OFF |
| Sustain | 0-100 %, the level the decay falls to | - |
| LOOP | EVERY PASS (stock) or FIRST PASS: a looping pad shapes only its first pass, then holds the sustain level and fades only at key-up or stop | EVERY PASS |
| REVERSE | MIRROR (stock: in reverse the release is heard first) or TIME: the attack is heard first | MIRROR |
| RETRIG | CUT (stock: a new hit stops the sounding voice with the 1.3 ms declick, which clicks on a loud note) or a fade, 0.5 ms - 8 s (the FINE map): the old voice fades out over it while the new one starts | CUT |

RETRIG covers every hit that stops the pad's own sounding voice: the pad hit again, and in chromatic mode a
new note when chromatic is mono (it stops the ringing note whatever the note; the hardware report: "only when
ringing") or the same note again when poly. The fade is stock's key-up release (linear, in output time; it
ends at END if that comes first), started in place of the declick, so the old voice keeps its slot until the
fade ends and the new voice takes a free one. When the new voice needs that slot (every slot busy), when the
fade is under 64 frames (1.3 ms) or nothing is left to play, it is stock's cut. A voice already releasing goes
on (stock does that only for panel pads). Steals, the stop-all while recording and mute-group chokes stay stock.

The envelope stays positional, as stock's is: it is applied to the sample data by source position while each
voice's stream is filled (`0x16f50` forward, `0x17196` reverse), before PITCH/SPEED/stretch, so it scales with
pitch, and the release still ends at the HOLD point (HOLD stays stock: a % of START-END). The order is attack,
decay, sustain, release; when attack, decay and release don't fit the HOLD span, the release cuts the decay,
and when attack and release alone don't fit, they cross where stock's lines do and the release falls from
the level reached there. GATE key-up keeps stock's linear release in output time, sized from the FINE release
when FINE is on (under 64 frames: stock's 1.3 ms declick).

Curves: EXP is (2^(6x) - 1) / 63 (about 36 dB of travel), LOG is 1 - EXP(1 - x), S is 3x^2 - 2x^3. A rising
segment (attack) is level = curve(x); a falling one (decay, release) is level = low + (high - low) x curve(1 - x),
so EXP is the natural fast-then-slow fade and LOG a fast attack. Levels are Q15, the per-frame phase is exact
(no drift across chunks), and the curve is a 257-entry table with linear interpolation.

FINE map: index 0 = 0; 1-127 = 0.5 ms x 16000^((i - 1) / 126) at 48 kHz, rounded (24 frames to 8 s = 384,000
frames). Anchors, as the screen shows them: 8 = 0.9 ms, 16 = 1.6 ms, 24 = 2.9 ms, 32 = 5.4 ms, 40 = 10 ms,
48 = 19 ms, 64 = 63 ms, 80 = 216 ms, 96 = 739 ms, 112 = 2.53 s, 127 = 8.00 s.

## Using it (the ENVELOPE page, SHIFT + PITCH/SPEED)

Tap SHIFT (press and let go within a second, touching nothing else) for the next page. The screen shows the
page, no popups (test 1 used popups; test 2 draws on the page itself):

| Page | CTRL 1 | CTRL 2 | CTRL 3 | Bottom line |
|---|---|---|---|---|
| 1 A-H-R (stock) | `C1:ATTACK` | `C2:HOLD` | `C3:RELEASE` | `A-1` (stock's) |
| 2 SHAPE | `C1:ATTACK` LIN/EXP/LOG/S | `C2:TIME` STOCK / FINE | `C3:RELEASE` curve | `A-1 SHAPE 2/4` |
| 3 DECAY | `C1:DECAY` OFF or the time | `C2:SUSTAIN` 0-100% | `C3:CURVE` the decay's | `A-1 DECAY 3/4` |
| 4 MODE | `C1:LOOP` EVERY / FIRST | `C2:RETRIG` CUT or the fade | `C3:REVERSE` MIRROR / TIME | `A-1 MODE 4/4` |

- The screen keeps stock's layout (rows 0-7 the CTRL labels, 8-16 their values under them, 17-32 the graph, the
  S and E marks at the bottom) and is drawn with stock's own calls on the page's context; the labels go into the
  page's static layer too, which stock copies back over the screen on a refresh.
- The graph shows the pad's real envelope, as the voices will play it: x = START..END, y = level; FINE times,
  curves, decay and sustain, the release ending at the HOLD point; a looping pad on FIRST PASS holds its
  sustain level to the end; a reverse pad on REV-TIME is drawn mirrored (the attack at the END side, as heard
  first). A pad with stock settings keeps stock's graph, and on page 1 stock's whole screen.
- Page 1 is stock's own page. With FINE on, ATTACK and RELEASE choose the fine index (knob = index), the values
  show the times (`5.4ms`, `216ms`, `2.53s`), and the stock fields get the nearest stock value (216 ms -> 9), so
  stock firmware plays the closest stock time.
- Turning TIME to FINE keeps the pad's fine times when its stock values still match them, else starts from the
  fine times nearest its stock ones.
- Holding COPY or REMAIN applies a turn to the pad's mute group or bank, as stock's apply `0x800f5df0` does
  (protected banks skipped). On page 1 with FINE, the group's FINE pads take the fine index; every pad takes the
  nearest stock value through stock's apply.
- While the CTRL knobs drive the effect (`0x800ce420`), every page leaves them to stock. A pad without a sample
  the setter edits (`0x800d9e30`) gets nothing, as stock's setter.
- Re-opening the page starts on page 1. A SHIFT held since the opening chord, held over a second, or with another
  key pressed or let go, a knob turned or the pad changed in between, is no tap. A key held from before SHIFT
  until after it, or a key bit that never changes, doesn't stop a tap.

## Storage and saving

Per pad, in the PADCONF extended block's reserved bytes (pad FX uses 0x54-0x63):
`CSmplPrm 0x82e2cd08 + 0xF800 + pad x 0x80`:

| Byte | Field |
|---|---|
| 0x64 | flags: b0 FINE, b1 ADSR, b2 LOOP-ONCE, b3 REV-TIME |
| 0x65 / 0x66 | attack / release, fine index |
| 0x67 | curves: b0-1 attack, b2-3 decay, b4-5 release (LIN, EXP, LOG, S) |
| 0x68 / 0x69 | decay, fine index (0 off) / sustain 0-100 % |
| 0x6a | retrigger: 0 CUT (stock), 1 FADE |
| 0x6b | the re-hit fade, fine index |
| 0x6c | reserved for E3a's choke |
| 0x6d | layout version: 1 whenever any of 0x64-0x6c is not 0; anything else = stock |
| 0x6e-0x6f | reserved |

Stock saves, loads, copies, moves and exchanges these bytes and resets them for a new sample (pad FX study
§5.2). A change sets stock's Edited flag; command 0xD (`0x800e25c0(0xd, 1, 0)`, what stock's setter posts)
goes out once, 1 s after the last change, or when the page closes.

## The patches

All on code DOOM OS ED5E and the fork leave stock (39 guards, SHA-256 of every span the module calls, reads or
relies on). Nothing branches into the displaced bytes but their entries (every BL, B, B<cond>, CB(N)Z, B.W,
literal and MOVW/MOVT pair in the image is checked).

1. **Recompute entry** `0x800a2d98` (12 bytes: `push.w`, `sub sp`, `mov r4, r0`, `movw sb`) -> `env_recompute`,
   **the shared dispatcher**: it runs the stock body first (`env_recompute_stock`: the four instructions, then on
   at `0x800a2da4`) so the stock block and r0 are always stock's, then this stage, then every non-zero
   `env_stages[]` entry.
2. **Note-off** `0x8002315a` (16 bytes: `ldr r1, [r4, #0x100]`, `movw/movt r2, #144000`, `mul r6`) ->
   `env_release`: r6 = FINE release x 127 for a FINE voice, else R x 144000; on at `0x8002316a`.
3. **Applicators** `0x16f50` and `0x17196` (ITCM, 10 bytes each) -> `env_fwd` / `env_rev`: a voice whose envelope
   is the module's gets `env_fwd_apply` / `env_rev_apply`; anything else (stock pads, blocks that aren't a voice's)
   runs the displaced instructions and goes on in ITCM.
4. **ENVELOPE page vtable** `0x8021ec14`: +0x04 (deleting destructor) -> `env_ui_leave`, +0xC8 (pad change:
   START/END again, then `0x800f5f00`) -> `env_ui_pad`, +0xCC (redraw, `b.w 0x800f5f00`) -> `env_ui_draw`, +0xD0
   (tick, stock `bx lr`, called every 50 ms with 50) -> `env_ui_poll`, +0xE4 (knob) -> `env_ui_knob`. DOOM OS's
   +0x08 is untouched. The REPORT named +0xD0 and +0xE4; +0x04 makes the save go out when the page closes, and
   +0xC8/+0xCC draw the pages: those two are the only callers of stock's redraw `0x800f5f00`, and stock's
   refresh (event 4: the static layer copied over the screen, then +0xCC) goes through them too.
5. **The re-hit**: in the stop `0x80094168`, its call of the re-hit / steal stop `0x80024580` (10 bytes at
   `0x8009424e`: `movs r1, #0`, `bl 0x80024580`, `eor r7, r0, #1`) -> `movw ip / movt ip / blx ip` to
   `env_retrig`, which reads the stop's wait flag (r5) and its caller's return address (sp + 0x24). For the
   voice manager's re-hits (`0x800d63c8`: the call at `0x800d6c08`, and `0x800d6954` for a looping chromatic
   note hit again with HOLD down) of a FADE pad, with wait 0, a sounding voice gets stock's note-off
   `0x80023118` instead, its release sized from the fade (`env_release` takes it from `env_fade_frames` for that
   voice). Otherwise it calls `0x80024580` as stock did, and sets r7 as the `eor` did. The stop's own
   bookkeeping (lock, wait, slot flags, time) stays stock's. The study's plan patched the stop's entry; the
   call site keeps all of that and needs no displaced code in the module.
   Stock decides where the new voice goes: free slots first, a steal only when there are too few, and then
   the re-hit stop has wait 1 (it waits for the declick to free the slot), which this leaves stock.

The module (Zig 0.13.0, -Os; about 7.6 KB code, 3.1 KB tables, 3.7 KB state; 2.0 KB of the slot free) is a new
boot copy row in a 16 KB slot at
**`0x83FDE000`-`0x83FE2000`**. The REPORT's slot `0x83FE4000`-`0x83FE8000` is taken since: FX deep edit uses
`0x83FE2000`-`0x83FE6000` and the FX probe `0x83FE6000`-`0x83FE8000`. The builder checks the slot against every
row of the input, against every fork module's slot (a chromatic-mode module `0x83FD7000` (planned), stage 2
`0x83FD9000`, note repeat `0x83FDC000`, FX deep edit, FX probe, bounce stage 2/3 `0x83FE8000`, CPU meter
`0x83FED000`, bounce probe `0x83FEE000`, start fix `0x83FEF000`) and that nothing refers to it. Pad FX keeps
`0x83FC9000`-`0x83FD7000` (56 KB).

## Stage 2 and later: `env_stages`

Every recompute (voice start, A/H/R, START, END and loop-point edits) calls each non-zero entry of
`env_stages[4]` (exported; in the module's copy row, zero at boot) with a pointer to:

```c
struct env_call {
    u8 *env;            /* the block the stock body just wrote (voice + 0x60) */
    u32 start, length;  /* the recompute's arguments, as passed */
    s32 a, h, r, ch;
    u32 lr;             /* return address: 0x80023b05 Init, 0x8001ff39 A/H/R, 0x80022daf START,
                           0x80024a8f END, 0x8002310f loop point */
    s32 voice;          /* 0-31, or -1 when env is not a voice's block */
    s32 pad;            /* voice + 0x14274, or -1 */
};
```

A pitch envelope (Codex's design: the voice's Q14 step inside the 2048-frame fill `0x800e48ac` -> `0x800d2e38`
-> `0x1409a`) registers its entry there (a 4-byte data patch in this module's copy row) and acts on the four
start/position return addresses it needs, leaving the A/H/R edit alone. Its fill-path hook is a different site.

Its pages go in `env_more_pages[4]` (exported, zero at boot): pointers to

```c
struct env_page {
    const char *name;                                    /* bottom line: "A-1 PITCH 5/5" */
    const char *label[3];                                /* top line, CTRL 1-3 ("" none; 10 characters) */
    void (*value)(u32 pad, u32 ctrl, char *out);         /* CTRL ctrl's value as text, out[16] */
    void (*turn)(u32 pad, u32 ctrl, s32 raw);            /* CTRL ctrl turned to raw (0-127) */
    void (*graph)(u32 ctx, u32 pad, s32 start, s32 end); /* its own graph in rows 17-32 (cleared), or 0 */
};
```

They come after MODE in order, the taps reach them, the bottom lines count them ("n/5"), and the module
redraws after each turn. A graph draws with stock's calls on `ctx` (line `0x800c0660`, text `0x800d4fa0`, ...).

## Checked in the emulator (not on hardware)

`python synth/test_pad_env.py OUT_DIR [N]`: the parent and the image booted in Unicorn with their scatter
loaders and static constructors, real stock code throughout (recompute, applicators, note-off, getter,
setter, fan-out, UI dispatcher, the page's registry handler, DOOM OS's filter, the page's methods) and, for the
page, boot's three 128 x 64 surfaces made (`0x8006fcb8`) so every drawing call runs down to the pixels.

- static: only the scatter pointer, the five code sites and the five vtable words change inside the parent;
  the guards and displaced bytes hold; nothing reaches into them; the module's copies are exact; the slot
  is free; the FINE map and curves are the formulas above;
- neutral pads (all zero, version 0 with anything else, version 1 at stock settings, an unknown version, voices
  without a pad, blocks that aren't a voice's): recompute (block and r0, from every caller), note-off (result,
  release counters) and both applicators and their wrappers (every frame, mono, stereo, slot state 7, before
  START) are bit-identical to the parent;
- shaped pads: the published shape and every frame of both applicators match a Python model (FINE and stock
  times, curves, ADSR, overlap, decay cut by the release, REV-TIME, LOOP-ONCE with wraps, turns and an Init
  reset, mono/stereo, state 7, before START, past HOLD);
- note-off: every fine index, short and long releases; curves-only pads keep stock's release;
- the re-hit: the stop `0x80094168` called as each of its five callers calls it, wait 0 and 1, on 8 kinds of
  pad and 6 kinds of voice (480 cases): a FADE pad's sounding voice, stopped for a new hit, gets the release over
  the fade (ceil(min(fade, frames left) / 64) blocks) and no declick, a releasing one goes on; everything else
  (CUT, other layouts or retrigger values, a fade under 64 frames, nothing left to play, wait 1, the steal, the
  stop-all, the MIDI chromatic loop) is the parent's byte for byte. Then the voice manager `0x800d63c8` itself
  (Unicorn's ARM_MAX CPU; the voice start only noted): chromatic mono with another note, poly with the same note
  and with another (no stop), a panel pad hit again, every slot busy: the old voice keeps its slot while the new
  one starts in a free slot, and CUT pads and the busy case are the parent's;
- dispatcher: stock block first, then `env_stages` gets the call once from all five callers;
- the page: SHIFT taps (and what isn't one), page 1 stock until FINE, FINE writes, pages 2-4, COPY / REMAIN
  (mute group, bank, protected bank, empty pad), effect knobs, the save timer and the save on close, a later
  stage's page through `env_more_pages`;
- the screen and its static layer, byte for byte: page 1 with stock settings is the parent's (after opening,
  every knob turn and a return from the other pages); every page for 9 kinds of settings, after every turn, a
  refresh and a pad change, is a reference drawn on the parent with stock's own calls from the settings alone
  (labels, values, every fine time, the graph from a Python model of the envelope, the bottom line); the module
  shows no popups. Two broken builds (labels not in the static layer, the graph a row off) fail it.

Cost (Unicorn instructions, stereo): stock pads unchanged (unity 41, attack ramp 119, release 54 per frame; the
hook adds about 25 per 2048-frame call). Shaped pads: ramps 41 per frame with any curve, sustain 20, unity 0.
A knob turn's redraw on the page: about 125-140k instructions (stock's 27k).
Stack: the shaped applicator path uses about 100 bytes more than stock's (172-212 bytes), the recompute about
160 more (240); the charge task has a 16 KB stack.

The kit suites (test_kits, capture, chord, shortcut, midi, restart, hot resample, test_kit_bounce flow, 13 kits
and 4 tweaked) pass on the image; test_start_fix passes on its own release, and on this image its trim and
threshold checks pass while its structural checks expect the start fix to be the top stage.

## Not known (the hardware test, or later)

- How it sounds: the curves, the FINE times near the click threshold, the pluck (test 1: "sound fine").
- The screen on the unit: the emulator draws into the screen surface and stops there (the display transfer
  isn't run); which events refresh the page on the unit (event 4 and the pad change go through the module).
- Stock behaviour the design leans on but the unit hasn't confirmed (REPORT E0): every LOOP pass faded, the
  reverse swap, the silent run-on after HOLD. LOOP-ONCE takes a read that jumps back against its direction, or a
  turn, as the end of the first pass; loop crossfade reads might end it a little early.
- The tick's real period: the page arms stock's 50-tick page timer on entry (vtable +0x10 -> `0x800738a8`), and
  50 ms assumes the UI loop's 1 ms tick (the save delay and the 1 s tap limit count it).
- Whether stock firmware keeps the bytes through a load and save (pad FX study, test S2), and whether Roland's
  app touches them.
- CPU with many shaped voices next to the kits (cheaper than stock per frame in the emulator).
- The re-hit fade on the unit: the voice start (Init), the audio task's release and the slot freed at its end
  weren't run (the release is stock's key-up one, which the unit plays for GATE pads). A fading voice holds its
  slot for the fade, so fast rolls with long fades steal earlier. Chromatic mono sends its message for the old
  note (`0x800bd5a0`) again if a new note comes while one fades. Which UI setting project param 0xf3 (chromatic
  mono when not 2) is wasn't looked up.

## Build

```sh
python synth/build_pad_env.py PATH/kits-v9.46-test3/SP404MKII_APP1.bin OUT_DIR --zig PATH/zig.exe [--build-dir DIR]
python synth/test_pad_env.py OUT_DIR
```

Stock APP0 must sit beside the input APP1. keystone, unicorn and capstone on PYTHONPATH, Zig 0.13.0.
