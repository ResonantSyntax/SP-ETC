"""Bounce in place, stage 2: bounce a sample pad through its effects into an empty pad, frame-exact.

A stage applied to the published Sound Generator + Kits v9.46 image (kits plus the RESAMPLE start
fix). It replaces the bounce probe (build_bounce_probe.py): the same three audio and UI sites, now
bridged to bounce.c, plus page 0xe's event filter. See BOUNCE.md.

Four sites change, each checked against its exact v9.46 contents:
  0x0001d090  audio task, TX block: mov.w r1,#0x1000; mov r0,r5; bl mixer
              -> tx bridge: the same mixer call, then bnc_tx, then back to 0x1d09a
  0x0001d0c2  audio task, RX block: mov.w r1,#0x800; bl feed; b loop
              -> rx bridge: while a bounce owns the recorder the feed enable 0x805917c4 = 0 (the stock
                 gate cannot write the take); the same feed call, then bnc_rx, then the loop head
  0x8006b950  popup tick (UI task, every 1 ms): its first four instructions
              -> ui bridge: bnc_ui, then those four instructions
  0x80223474  RESAMPLE page (0xe) vtable slot +8, the page's event filter: DOOM OS's 0x6031c8f9
              -> bnc_event, which hands every event it does not use to DOOM OS's filter
The two audio bridges use no stack, so the mixer and the feed run at their stock depth. Stock code
and data the module reads, calls or relies on are checked byte for byte (GUARDS, TABLE_GUARDS). The
bridges and the module (Zig 0.13.0, -Os) go in a new boot copy row in a 20 KB slot at 0x83FE8000,
below the CPU meter's test slot (0x83FED000) and the start fix's row (0x83FEF000); the builder
checks that no row overlaps the slot and that nothing in the input refers to it.

usage: python synth/build_bounce.py IN_APP1 OUT_DIR --zig ZIG [--base 0x83FE8000]
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

from build_arp import call, checked_asm, file_offset, jump, listing, load, read_module, scatter
from build_bounce_probe import check_no_branch_into
from build_start_fix import refs_into

HERE = Path(__file__).resolve().parent
FLASH, COPY = 0x60080000, 0x600800E4
APP0_SHA = '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23'
PUBLISHED_V946 = '7b5fbcb4c3ce1e8782fef4b5803be74c7d14eddf25a1b53682abe00c9ed3684a'
REVISION = 'bounce-2-test1'
SLOT = 0x5000                       # reserved: [base, base + SLOT)
SLOT_CEILING = 0x83FED000           # the CPU meter test build's slot, then the start fix at 0x83FEF000
BRIDGES = {'tx': 0x00, 'rx': 0x30, 'ui': 0x80}
CODE_OFFSET = 0x100                 # the C module links after the bridges
PCM_BANK = 0x60376000               # build_arp_kit.py's flash planning boundary for kit PCM
EXPORTS = ('bnc_tx', 'bnc_rx', 'bnc_ui', 'bnc_event', 'bnc_estimate', 'bnc_aud', 'bnc_ui_state', 'bnc_text',
           'bnc_own')
FEED_ON = 0x805917C4                # the recorder feed calls the gate while this word is set
MIXER, FEED, TX_BACK, LOOP, TICK_REST = 0x1C2D0, 0x1CA80, 0x1D09A, 0x1D05C, 0x8006B95C
SITES = {
    'tx': (0x1D090, 10, ['mov.w r1, #0x1000', 'mov r0, r5', 'bl #0x1c2d0']),
    'rx': (0x1D0C2, 10, ['mov.w r1, #0x800', 'bl #0x1ca80', 'b #0x1d05c']),
    'ui': (0x8006B950, 12, ['push {r4, r5, r6, lr}', 'movw r4, #0x22ac', 'movt r4, #0x8059', 'ldr r1, [r4, #8]']),
}
VTABLE_SLOT, DOOM_FILTER = 0x80223474, 0x6031C8F9     # RESAMPLE page vtable 0x8022346c, +8
# Code and data the module and bridges rely on: (start, end, SHA-256 of the v9.46 runtime bytes, what it
# establishes). All are stock 5.52 bytes except the four marked v9.46 (the start fix and DOOM OS's filter).
GUARDS = [
    (0x1CF78, 0x1D0CC, 'f0c95148b5ac8c65cb13170f92197c3cffe4b51fdd832440934444ff10c18e00',
     'audio task: TX line 3 = 0x20006000 (eDMA TCD3 SADDR), RX = 0x20008000 (TCD4 DADDR); TX then RX per wake; '
     'r5 = mixer argument, r0 = RX buffer at the feed call; loop head 0x1d05c; both patch sites'),
    (0x1C2D0, 0x1C766, 'eb32d85ff156e39759b8e74894176ebd7e8c80008a7a79b4abce14960fa28f82',
     'mixer: stems 0x202ad3a0 cleared (64 x 14 int32); 32 voice slots of 0x58 at 0x202ae1a0'),
    (0x1C76A, 0x1CA80, '3954945dc197d01430f655855c12a1c57bbff2e499b8ac9845a67cc4c01354a3',
     'mixer: stems clipped to 20 bits and written back (TX words 0-11, 14-15)'),
    (0x1CA80, 0x1CB84, '40fb002266bf5930ddddbda3b36b26c746acb40a304387c0c5b588d3cb8b1d97',
     'recorder feed: 64 frames of RX pair (param 0x27 / target 7) to 0x202ad0a0; the gate 0x1baa4 is called only '
     'while [0x8059179c+0x28] (0x805917c4) is set; looper test 0x10084(0x82e0b71c)'),
    (0x1BAA4, 0x1BB74, '8dc2d56b776a94e7132510bfb843566de5330e75b89cf6b3513ee61a5741ae03',
     'recorder gate: sub-state 2 writes the block with engine +0x2c (stereo, +0x3b set): (engine, frames, count)'),
    (0x1BD5C, 0x1BE54, '19e84f814674d2afca222bb5a72db95f02172f111e046e0bc67b051f2d31758e',
     'stereo writer: [+0x200] frames written, [+0x208] first frame above [+0x1f8] (-1 = none)'),
    (0x14B88, 0x14BC0, 'cbbd6d0306dbd3c1c5006c6fa9449937940299e005f52f9ce8bfe4a48392300f',
     'renderer: a voice renders when its stream (+0x14268) is set and stream[1] != 0xff; pad index at +0x14274'),
    (0x80005870, 0x8000587C, 'fbc26416b4901ef29527923dc48e3d7926167b2873e14c7d9e7ec00bb5e7e3c5',
     'voice stub: slot word 0 = voice object'),
    (0x8006B950, 0x8006B9E8, 'e4050b0e145b6f8b10f37b0d3b9fc6b35c40c7b82c52bd5ec585eb95408ec833',
     'popup tick: from 0x8006b95c it uses r0 = elapsed, r1 = timer [0x805922b4], r4 = 0x805922ac and its stack '
     'frame; a timer running out closes the popup and clears a pending one'),
    (0x800D3FF0, 0x800D4026, '7399e6400e3ea2ddd99ad6a9f4de1469abffae638c380038c1d7aedbee61886b',
     'popup(text, ms): copies the text and arms the stock type-3 popup'),
    (0x8017F810, 0x8017F8A0, '2e74dee22543eae62b1b431882ebcc5b954d5805a315a8caba5a7826aedd357d',
     'REC_START: state 1/3 -> 2, destination from target params 0/1, engine start, sub-state 2'),
    (0x8017F8A0, 0x8017F970, '5435502d46f2ea259436294b6233586746daae706868d219302d4ba35995503c',
     'cancel (0x1a): close and discard the take, state 0, target param 1 = -1'),
    (0x8017F970, 0x8017FAAA, 'beb69303d61c4c7c1a6fe3790ae8b6f046afe91541a0c51c79172d062d751af0',
     'standby (0x14): .SMP engine for arg 0, stereo from target param 3, temp file, feed enable = 1, state 1'),
    (0x8017ED78, 0x8017F0AC, '2ed808a9aa1a5f1930649d6ca305a15abb6063255501294e9a08f7521c3809cc',
     'REC_STOP: state 1 deletes the temp file; state 2 finalizes into the pad (state 0 before the 500 ms wait); both '
     'end at 0x8017edc4, which sets target param 1 = -1'),
    (0x8017F0B8, 0x8017F810, '4230168430c66b83b320142f7854bc880ceace660bc2037b43b1b3cfc6bec61d',
     'REC_STOP finalize: START/END through 0x800cfa68 (all pad parameters to defaults), name, zero-cross adjust of '
     'START, END Snap (settings 0x59) and REC length (0x24) cut END, 0x59 cleared after the take'),
    (0x8017F0AC, 0x8017F0B8, 'e24fd45663eaa9ec0ae369899848f0ed766da72c358f8f6070d856d3780fb1b2',
     'v9.46: the RESAMPLE start fix jump in REC_STOP'),
    (0x83FEF000, 0x83FEF0B8, '138d719c869ab19345cb66b364f98ba340eab50bae521b99fb0584fc6383b2db',
     'v9.46: the start fix moves START only when [+0x208] is 1..2399 (high word 0)'),
    (0x800E9EFE, 0x800E9F0A, '8e1fdd82606e81bc8de862c617ef85d532f718f5085aad26c7875083a981b5f3',
     'v9.46: the start fix jump in the engine init'),
    (0x800412D0, 0x800412DE, '815da4475a8e6822b2c93be0f01031eff226efb025baaaed7f639ef360db7828',
     'feed enable: 0x805917c4 = 1 (its only writer; called by standby)'),
    (0x8021E020, 0x8021E080, 'ff82d87baae3d7860397029c07ac5caa25aebcaed6efcd7e4ec444db409af6ce',
     '.SMP engine vtable: +0x2c stereo writer 0x1bd5d, +0x14 data start 0x800e9a71'),
    (0x800E9A70, 0x800E9A76, 'c7700f9eab56a5063900b8f2ac0328db79c09ec9db9e14dbef85af43780bd629',
     'engine data start = [+0x1c0]'),
    (0x8004D8B8, 0x8004D8DA, 'e3ebf0eb8af88ced3241a9bf2f7c19205bed5e72612afe1fbfdb2b1f3cea0bbf',
     'SMPL TASK command dispatcher: TBH on the command'),
    (0x8004D8DA, 0x8004E116, '8783619d571a4412cb7c170d8302e3cfb88acd46d742e240289140a6cafed10a',
     'its table: 5 all sound off, 0xd save, 0x14 standby, 0x17 start, 0x18 stop, 0x1a cancel, 0x2a seq sound off'),
    (0x8004E210, 0x8004E220, '34a20182105b1b1f1ebf37a47777baf64120a79c18649a5f2b337d6d15f107cd',
     'command 5: all sample voices off (0x80185a90)'),
    (0x8004E2DA, 0x8004E2F4, '8eb2648246523c32600a4fb97d9f90b1d7f78da08c45e7feb3bbff6ef546bedd',
     'command 0xd: save the pad parameters (0x800cf218)'),
    (0x8004E394, 0x8004E3BE, '4e89d1523b5f8d197578b744fb8c8347c01306155bb5be87be3d20998bc59985',
     'command 0x14: standby (0x8017f970)'),
    (0x8004E14C, 0x8004E15C, '677a3168279b722c0e2b986d35c40c756433903a355a9d45510faf9ebbfeb452',
     'command 0x17: REC_START (0x8017f810)'),
    (0x8004E3E0, 0x8004E410, 'b9b327b9e94fda3749cdc9dc664560a7278db8438210cd6a692030ae636178d6',
     'commands 0x18 / 0x1a: REC_STOP (0x8017ed78), cancel (0x8017f8a0)'),
    (0x8004E7AC, 0x8004E7D6, 'a742ea01121a33f6fef4d2daad1451813a08d8ff933ff39e5715aabc8da4ca5b',
     'command 0x2a: sequencer sound off'),
    (0x800E25C0, 0x800E25E2, '836f8d0f0fc4efdcd3928ea0101b38bcbf75a4fae6e601b3eb25a6a5388c7d13',
     'post(cmd, a1, a2): {0xa4, cmd, a1, a2} to the SMPL TASK command ring'),
    (0x800CDBD0, 0x800CDBE8, '1dd9cf7cefb46ff03c1d98a7b2e34345ce5ee2406b3464c75110c58c64940de0',
     'pad note (global pad, velocity, 1)'),
    (0x800D9F2C, 0x800D9F48, '5e68a59ef7e026fd95f0c640c00ad0953b106bf14ec40f7c56406886326c55ab',
     'key held: bit (key & 7) of [0x80592448 + key / 8] (behind the kits\' gate)'),
    (0x800CE420, 0x800CE430, '61de56adb559b90916caa99dda129a5ef450444ac14cea531459766f97bbd235',
     'page modal state (page)'),
    (0x800D94D8, 0x800D94F2, '3b5fea56fc5c3714d850f372458cf0d1525dd50f3ee639a082ddde2c39df813b',
     'settings get (obj, id, idx): TBH on the id'),
    (0x800DD0C0, 0x800DD0E0, '3e20a3e2a93b9efb07122e0dbe90268461453c13c9310ab2c018777060eef5cc',
     'settings set (obj, id, value, flag)'),
    (0x800DDA38, 0x800DDA58, '33f9ce26b49ab2deaf9bf54ee0bd202afe500a49aedd626959f04bae1dc543be',
     'project get (obj, id, idx)'),
    (0x800DED18, 0x800DED38, '1623cd9b9140d638b3f53745d19c1bc3b26f2d867740bb8c4e501d2b0a9ab18e',
     'project set (obj, id, value, idx)'),
    (0x800DC6B8, 0x800DC6C8, '7e253d5424ce3002d9b93273f10ebe4191e87f03c51d438d4f66d67d553a25a2',
     'pad get (obj, id, pad)'),
    (0x800DC754, 0x800DC774, 'c149afee0c89ca5bbe9976b4f55d2ee626dd86f9c320f21c8865266ae96a5e30',
     'pad get: pads 0..0xa0 of 0xac bytes; empty pads read 0'),
    (0x800DC920, 0x800DC932, '9fedb960cb568f33d4aea115518f1949731891381711f96932000b9599626989',
     'pad get: TBH on id - 2'),
    (0x800DCEA0, 0x800DCED8, 'd3be8b9a7aadecd7a3cc075a2c4b9f12a64df476b1f4d78372802ff78af23f71',
     'pad get START: (+0xd4 - file info +0xc) / file info +8 / 2, frames; file info 0x82e495e4 + pad * 36'),
    (0x800DA720, 0x800DA756, 'd7b96490dc7b123e12112e35b8d11a7f4abfe84ef89560aa17d23bef109c575f',
     'pad set (obj, id, value, pad): the value converted first (frames for START/END)'),
    (0x800DB7C8, 0x800DB7D0, 'c70a6876bc2e467d7ed52ba9b6afcfb6d9ea82ed93eee4a7f1f81d0fb8ac3336',
     'pad set: ids above 0x3f'),
    (0x800DB8C6, 0x800DB8E8, '876e4d7adb48765707345624cd3d5b19c2aedbd8b9f28e93130de6486cd5d09b',
     'pad set: TBH on id - 2'),
    (0x800DBB2C, 0x800DBB98, 'fd9dfdbf4a1a9059510f566d47679111d6ea3cf6fa9e1486a3c37c1088ce5dae',
     'pad set START: snaps to a zero crossing when project param 0xfb is 1'),
    (0x800CFA28, 0x800CFA54, '867ab1a36a683c98c8c170b93661c7a812693525e1118e4206469a3fa3b2efd2',
     'pad name (obj, pad, text): 23 characters'),
    (0x800D48E8, 0x800D48F2, 'e0ac8f6dc1afcc1fec899eab1635d3fbd9a538908815750c800489b506cb460c',
     'recorder target set -> 0x8001f0a8'),
    (0x8001F0A8, 0x8001F0C6, 'f36749e435ee4ad9efbb0f72b5f86c46e0bb90d7068e416ecde8aeab963dd300',
     'recorder target set: a {0xa8} message through the command ring'),
    (0x800D56D8, 0x800D56E6, '79e04aeee32b396a540d08d848f822fae81c86631fbb96df2295073bde004c65',
     'recorder target get: [0x80246e14 + 4 id]'),
    (0x800FB000, 0x800FB090, '92405b314aa064bcae8c819f657a4300c3b38adc208d5d5e60790a27eeb650b1',
     'recorder target store: [0x80246e14 + 4 id] (not while recording)'),
    (0x800DA010, 0x800DA05C, '5b769e5c0bc3f1aacb14c8def404efa6fcd84e7132cb65dc11fb8dc7ef451fac',
     'system parameter get (obj, id, -1)'),
    (0x80108FA8, 0x80108FD4, '1e13fb6648596022c41df34d0f0b8ec960f3b9bd534e18db690e60c01531e598',
     '"Pattern is Running": [0x82e0d660 + 0xa5] or [0x82dffc88 + 0x2c0]'),
    (0x800D5E70, 0x800D5E76, '5c47fe8f5cbd083bae6c2ddba6a98fe9729f7db7b26f324bef6e4f8da57cc508',
     'looper running: [0x82e0b71c + 0x39]'),
    (0x8012CFE8, 0x8012D344, 'e3695b3a54d0b90f92da73e94080df10a565d20183a4f6b06fc9cae4be897a5b',
     'RESAMPLE pad handler: an occupied pad (status 0x64) plays unless project 0xbf/0xdd is 1 or the page is '
     'modal; an empty pad becomes the destination: REC BPM 0x1b from project 0x21 + bank, settings 0x1a, '
     'target 7 = 0, 1 = pad, 0 = bank, standby 0x14(0); Resample_Routing = system param 0x5c'),
    (0x6031C8F8, 0x6031C9A8, 'c3c66d467d9349e7a4cd28da79f776f2aab969f6c04da222f35232ce19e18179',
     'v9.46 (DOOM OS ED5E): the page event filter (page, event); events it does not take go to 0x800a80a9; it '
     'reads the page id at 0x80245880'),
]
# 16-bit jump-table entries: (address, value, what)
TABLE_GUARDS = [
    (0x800D9526, 359, 'settings get 0x1a -> 0x800d97c0'),
    (0x800D9528, 363, 'settings get 0x1b -> 0x800d97c8'),
    (0x800D953A, 399, 'settings get 0x24 -> 0x800d9810'),
    (0x800D955E, 463, 'settings get 0x36 -> 0x800d9890'),
    (0x800D95A4, 551, 'settings get 0x59 -> 0x800d9940'),
    (0x800DC9F6, 299, 'pad get 0x64 (status)'),
    (0x800DC9FC, 695, 'pad get 0x67 (START) -> 0x800dcea0'),
    (0x800DC9FE, 245, 'pad get 0x68 (END)'),
    (0x800DCA04, 235, 'pad get 0x6b (LOOP)'),
    (0x800DCA0A, 187, 'pad get 0x6e (BPM SYNC)'),
    (0x800DCA10, 193, 'pad get 0x71 (loop point)'),
    (0x800DCA14, 643, 'pad get 0x73 (PITCH)'),
    (0x800DCA16, 625, 'pad get 0x74 (FINE)'),
    (0x800DCA18, 683, 'pad get 0x75 (REVERSE)'),
    (0x800DCA1A, 613, 'pad get 0x76 (SPEED)'),
    (0x800DB9B2, 290, 'pad set 0x67 (START) -> 0x800dbb2c'),
    (0x800DB9B4, 344, 'pad set 0x68 (END)'),
    (0x800DB9BA, 468, 'pad set 0x6b (LOOP)'),
    (0x800DB9C6, 634, 'pad set 0x71 (loop point)'),
]
POPUPS = {
    'setup': 'BOUNCE A-1>A-9\\nNO TAIL | TAIL | LOOP | TAIL ONLY',
    'waiting': 'BOUNCE A-1>A-9\\nWAIT SILENCE',
    'running': 'BOUNCE A-1>A-9\\nNO TAIL 37% | LOOP 37% | TAIL 2.4s',
    'done': 'BOUNCED A-1\\nON A-9',
    'cancelled': 'BOUNCE CANCELLED\\nNOTHING CHANGED',
    'refused': ['NO EMPTY PAD', 'STOP PATTERN FIRST', 'STOP LOOPER FIRST', 'FX STILL RINGING', 'BOUNCE FAILED'],
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def runtime(img, address, size):
    """Bytes at a run-time address: a boot copy row, or DOOM OS's code executed in place from flash."""
    if FLASH <= address and address + size <= FLASH + len(img):
        off = address - FLASH
    else:
        off = file_offset(img, address, size)
    return bytes(img[off:off + size])


def compile_module(folder: Path, zig: Path, link_base: int, limit: int):
    folder.mkdir(parents=True, exist_ok=True)
    if subprocess.check_output([str(zig), 'version'], text=True).strip() != '0.13.0':
        raise ValueError('needs Zig 0.13.0')
    keep = ' '.join(f'KEEP(*(.text.{n}))' for n in EXPORTS[:5])
    (folder / 'bounce.ld').write_text(f'''ENTRY(bnc_tx)
SECTIONS {{
 . = {link_base:#x};
 .text : {{ {keep} *(.text*) }}
 .rodata : ALIGN(16) {{ *(.rodata*) }}
 .data : ALIGN(16) {{ *(.data*) }}
 .bss : ALIGN(16) {{ *(.bss*) *(COMMON) }}
 /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.note*) }}
}}
''', encoding='ascii', newline='\n')
    source = folder / 'bounce.c'                     # compile LF-normalized source
    source.write_bytes((HERE / 'bounce.c').read_bytes().replace(b'\r\n', b'\n'))
    cache = folder / 'cache'
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache))
    # -g only keeps the symbol table: Zig's -Os (ReleaseSmall) strips it otherwise. Same code.
    subprocess.run([str(zig), 'cc', '-target', 'thumb-freestanding-eabihf', '-mcpu=cortex_m7+vfp4d16',
                    '-mfloat-abi=hard', '-Os', '-g', '-Wall', '-Wextra', '-Werror', '-ffunction-sections',
                    '-fdata-sections', '-nostdlib', '-Wl,--no-undefined', '-Wl,--build-id=none', '-Wl,-e,bnc_tx',
                    '-Wl,-T,' + str(folder / 'bounce.ld'), str(source), '-o', str(folder / 'bounce.elf')],
                   check=True, env=env)
    code, symbols = read_module((folder / 'bounce.elf').read_bytes(), link_base, limit)
    missing = [n for n in EXPORTS if n not in symbols]
    if missing:
        raise ValueError(f'module exports missing: {missing}')
    return code, {n: symbols[n] for n in EXPORTS}, sha(source.read_bytes())


def bridge_sources(sym):
    """Each bridge re-creates exactly what its site did, plus one call into the module."""
    return {
        # From 0x1d090 (bx): the mixer call with its arguments, bnc_tx, then 0x1d09a.
        'tx': 'mov r0, r5\nmov.w r1, #0x1000\n' + call(MIXER) + call(sym['bnc_tx']) + jump(TX_BACK),
        # From 0x1d0c2 (bx), r0 = RX buffer: while a bounce owns the recorder, clear the feed enable
        # (so the stock gate cannot write the take), the feed call, bnc_rx, the loop's branch.
        'rx': (load('r12', sym['bnc_own']) + 'ldr.w r12, [r12]\ncmp.w r12, #0\nbeq feed\n' +
               load('r12', FEED_ON) + 'movs r1, #0\nstr.w r1, [r12]\nfeed:\nmov.w r1, #0x800\n' + call(FEED) +
               call(sym['bnc_rx']) + jump(LOOP)),
        # From 0x8006b950 (bx), r0 = elapsed ms: the displaced push, bnc_ui(elapsed) with r0 kept, the
        # displaced loads, then the tick at 0x8006b95c.
        'ui': ('push {r4, r5, r6, lr}\npush {r0, r1}\n' + call(sym['bnc_ui']) + 'pop {r0, r1}\n'
               'movw r4, #0x22ac\nmovt r4, #0x8059\nldr r1, [r4, #8]\n' + jump(TICK_REST)),
    }


def check_guards(img):
    for start, end, digest, what in GUARDS:
        if sha(runtime(img, start, end - start)) != digest:
            raise ValueError(f'{start:#x}..{end:#x} differs from v9.46 ({what})')
    for address, value, what in TABLE_GUARDS:
        if struct.unpack('<H', runtime(img, address, 2))[0] != value:
            raise ValueError(f'jump-table entry at {address:#x} differs from stock 5.52 ({what})')


def build(inp: Path, out: Path, zig: Path, base: int):
    img = bytearray(inp.read_bytes())
    app0 = inp.with_name('SP404MKII_APP0.bin')
    if sha(app0.read_bytes()) != APP0_SHA:
        raise ValueError('expected stock APP0 beside the input APP1')
    for name in ('SP404MKII_APP1.bin', 'SP404MKII_APP0.bin', 'manifest.json'):
        if (out / name).exists():
            raise ValueError(f'refusing to overwrite {out / name}')
    if base & 0xFFF or base < 0x83FC9000 or base + SLOT > SLOT_CEILING:
        raise ValueError('the slot must be 4 KB aligned in the free SDRAM gap, below 0x83FED000')
    rows = scatter(img)
    check_guards(img)
    for key, (site, size, expect) in SITES.items():
        found = listing(runtime(img, site, size), site)
        if found != expect:
            raise ValueError(f'{site:#x}: expected {expect}, found {found}')
    if struct.unpack('<I', runtime(img, VTABLE_SLOT, 4))[0] != DOOM_FILTER:
        raise ValueError(f'{VTABLE_SLOT:#x}: expected DOOM OS\'s page filter {DOOM_FILTER:#x}')
    scanned = check_no_branch_into(bytes(img), [(s, n) for s, n, _ in SITES.values()])
    for load_, dst, n, fn in rows:
        if max(dst, base) < min(dst + n, base + SLOT):
            raise ValueError(f'row {dst:#x}+{n:#x} overlaps the slot {base:#x}..{base + SLOT:#x}')
    hits = refs_into(bytes(img), base, base + SLOT)
    if hits:
        raise ValueError(f'input refers to the slot: {hits[:4]}')

    module, symbols, source_sha = compile_module(out / 'build', zig, base + CODE_OFFSET, base + SLOT)
    blob = bytearray(CODE_OFFSET)
    entries = {}
    sources = bridge_sources(symbols)
    for key, offset in BRIDGES.items():
        code = checked_asm(sources[key], base + offset)
        nxt = min([o for o in BRIDGES.values() if o > offset] + [CODE_OFFSET])
        if offset + len(code) > nxt:
            raise ValueError(f'bridge {key} too long ({len(code)} bytes)')
        blob[offset:offset + len(code)] = code
        entries[f'{key}_bridge'] = base + offset
    blob += module
    if len(blob) > SLOT:
        raise ValueError(f'blob ({len(blob)} bytes) exceeds the slot')
    entries.update(symbols)

    patches = []
    for key, (site, size, expect) in SITES.items():
        target = base + BRIDGES[key]
        new = checked_asm(jump(target) + 'nop\n' * ((size - 10) // 2), site)
        want = [f'movw ip, #{(target | 1) & 0xFFFF:#x}', f'movt ip, #{target >> 16:#x}', 'bx ip'] + \
            ['nop'] * ((size - 10) // 2)
        if len(new) != size or listing(new, site) != want:
            raise ValueError(f'{site:#x}: bad replacement {listing(new, site)}')
        off = file_offset(img, site, size)
        patches.append(dict(address=site, size=size, original=expect, original_hex=bytes(img[off:off + size]).hex(),
                            replacement_hex=new.hex(), target=target))
        img[off:off + size] = new
    off = file_offset(img, VTABLE_SLOT, 4)
    new_word = struct.pack('<I', symbols['bnc_event'] | 1)
    data_patches = [dict(address=VTABLE_SLOT, size=4, original_hex=bytes(img[off:off + 4]).hex(),
                         replacement_hex=new_word.hex(), what='RESAMPLE page vtable +8: the event filter')]
    img[off:off + 4] = new_word

    file_at = (len(img) + 15) & ~15
    img += bytes(file_at - len(img)) + blob
    table = (len(img) + 15) & ~15
    img += bytes(table - len(img))
    for row in rows + [[FLASH + file_at, base, len(blob), COPY]]:
        img += struct.pack('<4I', *row)
    struct.pack_into('<2I', img, 0x80, table - 0x80, len(img) - 0x80)
    if FLASH + len(img) > PCM_BANK:
        raise ValueError('APP1 would reach the kit PCM planning boundary')
    if runtime(img, base, len(blob)) != bytes(blob):
        raise ValueError('the new row does not reproduce the blob')

    out.mkdir(parents=True, exist_ok=True)
    (out / 'SP404MKII_APP1.bin').write_bytes(img)
    shutil.copy2(app0, out / 'SP404MKII_APP0.bin')
    parent_manifest = inp.with_name('manifest.json')
    parent_sha = sha(inp.read_bytes())
    manifest = dict(
        revision=REVISION, status='hardware-unverified', published=False,
        description='bounce in place, stage 2: hold RESAMPLE and tap a sample pad; the pad is recorded through '
                    'its effects into the first empty pad, frame-exact, in NO TAIL, TAIL or LOOP mode',
        parent_app1=str(inp), parent_sha256=parent_sha, parent_is_published_v946=parent_sha == PUBLISHED_V946,
        parent_revision=json.loads(parent_manifest.read_text(encoding='utf-8')).get('revision')
        if parent_manifest.exists() else None,
        replaces='bounce-probe-1 (the same three sites)',
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        slot=[base, base + SLOT], blob_base=base, blob_file_offset=file_at, blob_size=len(blob), blob_sha256=sha(blob),
        source='synth/bounce.c', source_sha256=source_sha, compiler='zig 0.13.0 cc -Os',
        entries=entries, patches=patches, data_patches=data_patches,
        branch_scan=dict(bytes=scanned, result='no direct branch into a patched span'),
        guards=[dict(start=s, end=e, sha256=d, establishes=w) for s, e, d, w in GUARDS],
        table_guards=[dict(address=a, value=v, establishes=w) for a, v, w in TABLE_GUARDS],
        latency=dict(k_chip=138, center=75, onset_accept=6, onset_calibrates=3,
                     estimate='K - (P mod 64) + 64 n, the candidate nearest 75; P = eDMA phase as the probe read it',
                     onset='TX stems above 2048 (20-bit) within 100 ms of T0; RX above 128 (16-bit) 8..300 frames later'),
        thresholds=dict(silence='RX |x| <= 8 and TX |x| <= 128 for 9600 frames, at most 10 s',
                        tail='after the voice ends: 12000 frames below RX |x| <= 8; END = last frame above; cap 30 s'),
        popups=POPUPS,
        tool='synth/build_bounce.py')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    sums = ''.join(f'{sha((out / n).read_bytes())}  {n}\n' for n in ('SP404MKII_APP0.bin', 'SP404MKII_APP1.bin',
                                                                       'manifest.json'))
    (out / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8', newline='\n')
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('app1', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--zig', type=Path, required=True)
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0x83FE8000)
    a = ap.parse_args()
    m = build(a.app1.resolve(), a.out.resolve(), a.zig.resolve(), a.base)
    print(json.dumps({k: m[k] for k in ('revision', 'sha256', 'size', 'blob_base', 'blob_size')}, indent=1))


if __name__ == '__main__':
    main()
