"""Bounce in place, stage 3: a sample pad through its effects, frame-exact, to an empty pad or in its
place (REPLACE through the stock pad exchange, with UNDO).

A stage applied to Sound Generator + Kits v9.46: the kit stage of the published v9.46 plus the
RESAMPLE start fix v3 (resample-startfix-3, build_start_fix.py; the published v9.46 carries v2). It
supersedes stage 2 (bounce-2-test1): the same four sites, bridged to the stage 3 bounce.c, plus the
pad-event dispatcher. See BOUNCE.md.

Six sites change, each checked against its exact v9.46 contents:
  0x0001d090  audio task, TX block: mov.w r1,#0x1000; mov r0,r5; bl mixer
              -> tx bridge: the same mixer call, then bnc_tx, then back to 0x1d09a
  0x0001d0c2  audio task, RX block: mov.w r1,#0x800; bl feed; b loop
              -> rx bridge: while a bounce owns the recorder the feed enable 0x805917c4 = 0 (the stock
                 gate cannot write the take); the same feed call, then bnc_rx, then the loop head
  0x8006b950  popup tick (UI task, every 1 ms): its first four instructions
              -> ui bridge: bnc_ui, then those four instructions
  0x800bef10  pad-event dispatcher, every pad note from every task: ldrb; cmp #0xa0; bhi; b.w ring
              -> gate bridge: bnc_gate(event); 0 drops the event (a note-on while a bounce owns the
                 recorder), 1 runs the four displaced instructions
  0x80223474  RESAMPLE page (0xe) vtable slot +8, the page's event filter: DOOM OS's 0x6031c8f9
              -> bnc_event, which hands every event it does not use to DOOM OS's filter
  0x8012db58  the RESAMPLE page's tick (from the page, every screen refresh): push; sub sp; mov; mov;
              bl modal
              -> tick bridge: the push and frame, bnc_tick(page), then the moves and the modal test and
                 on to 0x8012db64. While a bounce holds the page (from REC to the first tick after it with
                 the recorder idle), bnc_tick gives the page the recorder's state as the one its tick last
                 saw, so the tick's state handler (0x8012dcb0) and after-recording routine (0x8012cbb0:
                 BUS 1/2 effects off, the stock pad handler's destination current, the main screen) do not
                 run for a bounce's standby, take or cancel. A stock RESAMPLE ends as stock.
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
FLASH, COPY, ZERO = 0x60080000, 0x600800E4, 0x60080100   # scatter rows: copy, zero fill
APP0_SHA = '3e35ff30137f741a715566e205384f9b434ca7ac3847e247bad3f0c9c8a2bd23'
PUBLISHED_V946 = '7b5fbcb4c3ce1e8782fef4b5803be74c7d14eddf25a1b53682abe00c9ed3684a'
REVISION = 'bounce-3-test8'
SLOT = 0x5000                       # reserved: [base, base + SLOT)
SLOT_CEILING = 0x83FED000           # the CPU meter test build's slot, then the start fix at 0x83FEF000
BRIDGES = {'tx': 0x00, 'rx': 0x30, 'ui': 0x80, 'gate': 0xC0, 'tick': 0x100}
CODE_OFFSET = 0x140                 # the C module links after the bridges
PCM_BANK = 0x60376000               # build_arp_kit.py's flash planning boundary for kit PCM
FUNCTIONS = ('bnc_tx', 'bnc_rx', 'bnc_ui', 'bnc_event', 'bnc_estimate', 'bnc_gate', 'bnc_tick')
EXPORTS = FUNCTIONS + ('bnc_aud', 'bnc_ui_state', 'bnc_text', 'bnc_own', 'bnc_expect', 'bnc_page')
FEED_ON = 0x805917C4                # the recorder feed calls the gate while this word is set
MIXER, FEED, TX_BACK, LOOP, TICK_REST = 0x1C2D0, 0x1CA80, 0x1D09A, 0x1D05C, 0x8006B95C
RING, DISPATCH_HIGH = 0x80018590, 0x800BEF1C   # the pad-event ring put; the dispatcher's path for 0xa1+
MODAL, PAGE_TICK_REST = 0x800CE420, 0x8012DB64   # the page modal test; the RESAMPLE page's tick after it
SITES = {
    'tx': (0x1D090, 10, ['mov.w r1, #0x1000', 'mov r0, r5', 'bl #0x1c2d0']),
    'rx': (0x1D0C2, 10, ['mov.w r1, #0x800', 'bl #0x1ca80', 'b #0x1d05c']),
    'ui': (0x8006B950, 12, ['push {r4, r5, r6, lr}', 'movw r4, #0x22ac', 'movt r4, #0x8059', 'ldr r1, [r4, #8]']),
    'gate': (0x800BEF10, 10, ['ldrb r1, [r0]', 'cmp r1, #0xa0', 'bhi #0x800bef1c', 'b.w #0x80018590']),
    'tick': (0x8012DB58, 12, ['push {r4, r5, r6, r7, lr}', 'sub sp, #4', 'mov r6, r1', 'mov r5, r0',
                              'bl #0x800ce420']),
}
VTABLE_SLOT, DOOM_FILTER = 0x80223474, 0x6031C8F9     # RESAMPLE page vtable 0x8022346c, +8
# Code and data the module and bridges rely on: (start, end, SHA-256 of the parent's runtime bytes, what it
# establishes). All are stock 5.52 bytes except DOOM OS's filter (marked v9.46) and the three start fix spans
# (marked startfix-3: its two jumps are v9.46's bytes, its code is v3's).
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
     'startfix-3: the RESAMPLE start fix jump in REC_STOP'),
    (0x83FEF000, 0x83FEF0B8, 'adb5394e72895911f7617dfbee500af9333a9503dd4cb8c29bef84be3ca2df61',
     'startfix-3: the start fix moves START only when [+0x208] is 9..2399 (high word 0), to 8 frames before it; '
     'a first sound of none (-1) leaves it'),
    (0x800E9EFE, 0x800E9F0A, '8e1fdd82606e81bc8de862c617ef85d532f718f5085aad26c7875083a981b5f3',
     'startfix-3: the start fix jump in the engine init'),
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
     'looper enabled: [0x82e0b71c + 0x39] (the feed records into the looper while it is set)'),
    (0x8012CFE8, 0x8012D344, 'e3695b3a54d0b90f92da73e94080df10a565d20183a4f6b06fc9cae4be897a5b',
     'RESAMPLE pad handler: an occupied pad (status 0x64) plays unless project 0xbf/0xdd is 1 or the page is '
     'modal; an empty pad becomes the destination: REC BPM 0x1b from project 0x21 + bank (only with a bar '
     'REC length and [0x80592360] clear), settings 0x1a, '
     'target 7 = 0, 1 = pad, 0 = bank, standby 0x14(0); Resample_Routing = system param 0x5c'),
    (0x6031C8F8, 0x6031C9A8, 'c3c66d467d9349e7a4cd28da79f776f2aab969f6c04da222f35232ce19e18179',
     'v9.46 (DOOM OS ED5E): the page event filter (page, event); events it does not take go to 0x800a80a9; it '
     'reads the page id at 0x80245880'),
    # stage 3
    (0x800BEF10, 0x800BEF4A, 'deaea7d78c2fba4baa97bd35b05354f3795aa79ee12b35963e4c02adf429fb89',
     'pad-event dispatcher (event): byte 0 <= 0xa0 -> the ring put 0x80018590, 0xa1 too; the site'),
    (0x80018590, 0x800185FA, 'ef7f3106abb62df882ad3923ec1b9afc434170ff4caf07aba9129dcf3109bd8b',
     'pad-event ring put: SMPL TASK starts the voice from it (byte 3 velocity, 0x80+ = off)'),
    (0x800CDBD0, 0x800CDE80, 'e54db5be9985d3a1a74b5a7499e219207f8faf3f4be9bb35fe099cb4aa8efc9d',
     'pad note: event {pad, 4, -, velocity or 0xff, 0xff or 0x40, 0} through 0x800bef10; FIXED VELOCITY '
     '(project 0xf5) replaces the velocity with project 0xdc'),
    (0x800AEC48, 0x800AF0CE, '6844ac43adc6e43642f416c0b6d93e19a79215b644ac70757643961b1fc99177',
     'note-on: every other pad with the same nonzero PAD LINK (0x79) starts directly, not through the ring'),
    (0x8004F88C, 0x8004F91C, '1e10109b4687cb94f4f379b29c119383c1a25a339837a2f243b50a97d6597f4b',
     'command 0x40d: close the sample manager\'s preview files, 0x800a6c30(gSmplMgr, [msg+4], [msg+8], 2)'),
    (0x8004FAE8, 0x8004FB14, 'd09aec034373cadb12deaf759da0dc6413a2ab63fbd127c493205652f5e82595',
     'command 0x40d, its only exit for 0x800a6c30\'s result 0: remote notice, UI refresh'),
    (0x800A6C30, 0x800A6D80, '2db31f7921c4570befc87b1901974504fc86f0fe20b9837c9ac88789285ac736',
     'exchange (mode 2): stop both pads\' voices, unload, swap files, swap parameters, reload both, save the '
     'pads; always returns 0'),
    (0x80051040, 0x800510CE, 'b04a9a29a04085625e2d2ecd634b91f3b9a6635f642e2f71ee9baeedc7fc6601',
     'file swap: delete B:/tmp.SMP, rename B -> tmp, A -> B, tmp -> A (.SMP paths), results unchecked'),
    (0x8018C2D8, 0x8018C3BC, '12df8970c14d03d51758be3e9bf77a696f783894372c758f7bee73844b3405ef',
     'parameter swap: the 0xac-byte record, the 24-byte name and the 0x80-byte block of both pads'),
    (0x800DA720, 0x800DC6B2, '967531f2cdcdb042fac6065253e54bb04ac5fa038269cb6cc8e4db5f6526026c',
     'pad set, whole: protect test, conversion, a store per id; GATE/LOOP on clear Polyphonic bit 5; '
     'GATE/LOOP/0x72/PLAY post a save'),
    (0x800DC6B8, 0x800DCF08, '76d59a974bf02d89a2b46f14293ee991a737fc3f66453f2c7c952414e5cd4fc7',
     'pad get, whole: LENGTH and channels from the file info; 0x69..0x7f from the pad record'),
    (0x8001A570, 0x8001AA78, '755e7c5ef0a9001df5858fd2857cad3c307d4c76f841897e4208f04ed11c956d',
     'pad set conversion: VOLUME 0..127, PITCH -12..12, FINE -100..100, SPEED 500..15000, PAN 13..115, BUS 0..6, '
     'Hold 1..100, Attack/Release 0..127'),
    (0x8001AA78, 0x8001AB80, 'c9e9ba56aa278c29362633315c6b761f97aa2a565977d772cffa3738a7731ef0',
     'protect test (obj, id, pad): SMPL+0x19900 and the bank\'s Protect (pad get 0x17 + bank)'),
    (0x800CFA68, 0x800CFB1C, '5076537fa1fe4b05572f552f9deb65f65449cd8e0612cfbab02eeb147ecc0aed',
     'a new sample\'s defaults: VOLUME 127, PAN 64, PITCH/FINE 0, SPEED 10000, PLAY 0, VINYL 1, BUS FX 1, '
     'Attack 0, Hold 100, Release 0'),
    (0x800F5D10, 0x800F5DEC, 'deec1a510192f8edc85ba6341dd3a98c7d8442672ce69a1dd7671f4001e98226',
     'envelope page: CTRL1 Attack (0x7d), CTRL2 Hold (0x7e, x100/127), CTRL3 Release (0x7f)'),
    (0x00014B88, 0x00014D90, 'f77ecc56d616e6b5f40b56b3373bb290e2e8e0684df59d9de46c34104c20ec51',
     'renderer: the voice\'s bus is its BUS FX Assign; 0 (DRY) is the one value sent through DRY Routing'),
    (0x800A2C98, 0x800A2D98, 'a9218e7997eb2fb293fe96cc2c645194f7e7bc4703d3577b5a92e4bae13ee405',
     'per-voice parameter update: PITCH/FINE ratio, PAN gains (64 = unity), BUS, envelope'),
    (0x8017E5B0, 0x8017E5D0, '578aa0664efb99b60a39a5d1912e25f23025469e1bc4d2426bb377abfda0e34a',
     'stereo writer, ring full: error word -0x79, REC TASK stop (flag 0x20), 100 ms delay'),
    (0x8017EA10, 0x8017EA16, '00488a29c8a023bfe68da1993f62328446bd6d4816032b28805e74aa68e4bbd9',
     'the error word store, CSampleRec + 0x250'),
    (0x800EA308, 0x800EA3D4, '766012228ecb48eb25b61b72012d2e37985a2df485e26636926079c7d95d8fc8',
     'REC TASK drain: a failed write or the spent budget -> error word -0x3e, then the stock finalize'),
    (0x800DD46C, 0x800DD494, '34fc5f0db81d56f76bb2f3eca39f45ebd4ac333bd4ece2ac05a840a99622b117',
     'settings set 0x25 (EXT SOURCE): with the input forced off (project 0xf8) input volume 0'),
    (0x800DD97C, 0x800DD9B4, '0a343872dd225f95b7ea0cca36148486878ab44c242dfc159a0ca5ac48333d34',
     'settings set 0x25: on a change, 0 -> input volume 0, 1 -> system parameter 0x22'),
    (0x8001A1C8, 0x8001A1F2, '5bbdd2c7802f21b59c6f3433e7237c912daf9f2b804a9f0ec82382f8c6d5016d',
     'input volume (0x80591aac, level): the effects chip\'s parameter 0x22'),
    (0x800D9818, 0x800D981E, '027168e16d284f28241b05568b507a1d17524c770be025e9a9485316d18d0875',
     'settings get 0x25: the value the setter stores ([obj + 0x5c])'),
    # bounce-3-test2: the looper's phase, and the command queue behind the exchange's fence
    (0x8001921C, 0x80019242, '58c56d7e67c9ffdcba345cddc05e94e459e63ec3c62d4602073b14fd6e37a2e5',
     'MARK Function (param 0x141) set: 2 enables the looper (0x8001c1a8), 0..1 disables it (0x8001c2b0)'),
    (0x800195EC, 0x800195F6, 'ef2b617ba6d09188b26a1a6db2ae1e34a1f29ac7d622e8cd50cc85044a99f758',
     'MARK Function set to 2: the enable, a tail call'),
    (0x8001C1A8, 0x8001C2AC, '9c5b42cdb7cf4f4491c81b2debc4b5d46149a1b842ab93259fd534ecf5ebfc5a',
     'looper enable: +0x39 = 1, the loop buffers cleared, phase +0x101 = 0 (empty)'),
    (0x8001C2B0, 0x8001C2C0, '5ac3c7b29ce98507714034a750ef06c39376c6e457560d8eaeda6e2019099c28',
     'looper disable: 0x8001f820, then +0x39 = 0'),
    (0x8001F820, 0x8001F934, '06b3f0532cde142dd7860fc68a2c7a6caa37e277830cbc3c7762364274ddf020',
     'looper stop on disable: phases 5, 8, 9 and 10 -> 6 (stopped)'),
    (0x80070280, 0x80070A80, '76144f6bc55718389d920608f3be059b76b8b23b114c48e4643e92151b01fb45',
     'looper task commands: 0 record / close the loop / play / stop, 1 overdub, 4 erase; the phases +0x101'),
    (0x0001D634, 0x0001E248, 'f56dd99c8e64fe54d794780653525279c183b40e1d17cd2ec8ac6634f61193dc',
     'looper input (audio task): phase 1 waits for the level, 2-3 record the first pass, 6 + [+0x102] starts '
     'an overdub, 7 waits for the level, 8-9 overdub'),
    (0x0001E248, 0x0001E622, 'ba99b137dbb938e62a8da01c555a31e88ea496f73ade99cd50d91c4f7bde6555',
     'looper output (mixer): plays in phases 5, 8, 9 and 10 only, enabled or not'),
    (0x800DA528, 0x800DA592, 'd2b82ce8b93f0a905b84ff8c84c1bf4cc43e3767edd15df4c08a56191dfd0f2c',
     'SMPL TASK queue put (0x800e25c0 type 0xa4 commands and 0x800d48e8 type 0xa8 target sets): one FIFO'),
    (0x8004C230, 0x8004C27A, '5012df16e16e7fef1be360f81faac55d352c05fd3e3c477ded5640937705dac0',
     'SMPL TASK queue pop: oldest first'),
    (0x801947C0, 0x80194890, 'a2139db2a6c6eb3e9b77df005d5b1e424b36ca27babcb5d687e0f196c5ecc5a2',
     'SMPL TASK queue loop: pops in order; 0xa4 -> the command dispatcher 0x8004d8b8 (the exchange runs inside '
     'it), 0xa8 -> the target store 0x800fb000'),
    # bounce-3-test2: the RESAMPLE page's tick, which the tick bridge keeps from seeing a bounce, and what it
    # would have run
    (0x8012DB58, 0x8012DCA4, '8a8a5fb0bfa74d8e2310f130373336f730b540b6df47e65311222f854390a3c8',
     'RESAMPLE page tick (page, refresh): returns while the page is modal; then reads the recorder state '
     '0x82e0e755 and +0x1a90 = the state at its last tick; on a change (or refresh != 0) the state handler '
     '0x8012dcb0, then the after-recording routine 0x8012cbb0; +0x1a90 = the state; settings 0x34 = idle; '
     'the tick site'),
    (0x8012DCB0, 0x8012DE22, '94638b4abdfd4c59d0c321bdcedd646fc04fd7ff9ff3d0b56e300d69a8ed2770',
     'RESAMPLE state handler (page, state): 2 -> settings 0x34 = 0, REC_STOP when no recording time is left; '
     '1 -> settings 0x34 = 0; 0 -> after state 2 ORIGINAL BPM (pad 0x6f) of settings 0x1a\'s pad = REC BPM, '
     'settings 0x34 = 1, after a take or standby every sound and the looper stopped (0x800dd030: ALL SOUND OFF, '
     'LOOPER TASK command 9 = 0x8001f820), after a standby END Snap (0x59) off; the '
     'screen state (settings 0x32) from the state and settings 0x1a'),
    (0x8012CE68, 0x8012CE6E, 'cf37588d6543c6f4994c1305e2fe36ea05a9ecd51aa8637ee24b881eb28dd83e',
     'RESAMPLE page vtable +0xd0: tick(page, 0)'),
    (0x8012D4E8, 0x8012D4EE, '9c5e90818f3f2660232e5e7863bbe7680cb1377aab2becffbc576740799aa7c8',
     'RESAMPLE page vtable +0xcc: tick(page, 1)'),
    (0x80223538, 0x80223540, '167ae5e09de5a73e3df3c6d1e1408691c36ef7b2ad8f820aa7810bb880929c04',
     'RESAMPLE page vtable +0xcc, +0xd0 = 0x8012d4e9, 0x8012ce69: the tick\'s only callers'),
    # bounce-3-test3: the pad's charge, which playback reads, made again from the window as the finalize ends
    (0x8017F4C0, 0x8017F51A, '364d13603e31ace4bf1c59261ee340d8a3a06ea8c6ed9067f1b18e5a472d8d87',
     'the finalize\'s end: new-sample defaults (0x800cfa68), name, 0x800d8b40(pad, START, END, START), '
     '0x800d6390(pad), 0x800d7508(gSmplMgr): the take is charged with its own range'),
    (0x800D8B40, 0x800D8B90, '6a19622302007bfd61a6ccf78912c48c3c155bf255b5121af6b2422ef62c79ae',
     'the range setter (pad, start, end, loop point): file information +0x18/+0x1c/+0x20, the marked byte +0x14 '
     "when one changes (the pad setter's START, END, loop point and PLAY cases, the finalize, the zero-cross "
     'adjust 0x80017200 and SMPL TASK call it); it charges nothing'),
    (0x800D6390, 0x800D63A6, '8620bbd299ece9fc618c5bff32a6c8d82dec76e2a329b42c015b48d3a3b737a2',
     'mark a pad\'s range for a new charge: file information +0x14 = 1'),
    (0x800D7508, 0x800D7562, '51de26ad13216de84918ef89d2bf8fbecb43012bae1c75907399906f21b49e21',
     'charge every marked pad again: for each marked pad with a charge entry (0x800d8998), the entry freed '
     '(0x800d8a70), a new one (0x800d8628) charged (0x800d84f0(entry, 1)); then the mark cleared (0x800d88c8)'),
    (0x800D88B0, 0x800D88C4, '0a2ad26112b20015199847784a791c676afc923ea81f026442584494977f97e8',
     'the mark: file information +0x14'),
    (0x800D88C8, 0x800D88DE, 'bc286ed37811f5dddc5a156cbf4ced706437047243fbe5a5c02ac753e0d30bbf',
     'the mark cleared'),
    (0x800D8998, 0x800D8A6E, '9f93d86df0b0f3e56f11f6f2153a1445ca416215255b44c65dc9a6124c10055e',
     'the pad\'s charge entry (161 of 0x68 bytes at 0x80b08cb8), if any'),
    (0x800D8A70, 0x800D8A7C, '781d4929f92b424a51985f40c162e0947014411b3ad6c5c5ff77663a78641bff',
     'a charge entry freed'),
    (0x800D8628, 0x800D88AC, '508cb41b4de538055a8b5d441739f59708ac318833988f1924f503f145700cd6',
     'the pad\'s charge entry, or a free one with its 80 KB buffers'),
    (0x800D84F0, 0x800D8628, 'ae1cc6f81ab9b9f7c17629d6e204642627bef76b03ad1a429504e27bd224385c',
     'charge an entry not yet charged from the pad\'s range: up to 80 KB from START, the rest of END - START to '
     'stream, the loop point and END - loop point; an entry already charged is left as it is'),
    (0x8012CBB0, 0x8012CCBA, '80436add6ca79917021f3d14659c5d782cdc8cd26b77404f7fe0720b01b07ce1',
     'after-recording routine: the recorder idle (0x82e0e755 = 0) after a tick that saw state 2, +0x1aa0 clear -> '
     'BUS 1/2 effects off (0x800bb140), [0x805925b4] = the stock pad handler\'s destination bank [0x80245a48] '
     '(-1 until a stock RESAMPLE picks a pad: the restore then selects bank A) and its pad current, 300 ms wait, '
     'RESAMPLE left (0x8012d438), page 1'),
    (0x800BB140, 0x800BB17A, '370ac705d9fdd9a4d31363fe8d475e7e619285b61af48d4c858732a3af3abe28',
     'bus effect off: system parameter 0x276 [bus] = 0 (0 = no effect, 1..5 the FX buttons, 6 custom)'),
    (0x8012D438, 0x8012D4D8, '199cacdfbd64cbae6295c2b6c57264bc18dc6d1ce343078f4f67fbf426215005',
     'RESAMPLE exit: settings 0x36 = 0, STOP, REC_STOP (0x18), settings 0x1a = -1, project 0xdd/0xbf = 0, bank and '
     'pad restored (0x80134990)'),
    (0x80134990, 0x801349C2, 'be51cc3d91015b9b4ed0ebd8a0aabfbc9f3930a878054e3fc3c5187d2614be9a',
     'the restore: project 1 (pad) = [0x805925b0], project 0 (bank) = [0x805925b4]'),
    # leaving RESAMPLE after a finished bounce (bounce.c leave_resample): what the stock exit does, less its REC_STOP,
    # ALL SOUND OFF and bank and pad restore, then the page request the after-recording routine ends with
    (0x800DA598, 0x800DA618, '83dd79362ff54dd4922cda7b443dbf31e5002d4fc57a5fd9239271856ed07a5c',
     'page request (page): 1 = TOP, refused while [0x80bcc418] is set; [0x8024587c] = page, [0x8059245c] |= 0x8000 '
     'for the UI task\'s page switch (0x800d0040)'),
    (0x800D61F0, 0x800D63C8, '3c4e5f164be752fbdfeb74f6716cc000e75a117ab4a700d3cc31cebba14ec6a5',
     'the value the RESAMPLE page\'s entry (obj 0x80591adc, 9, 0) and its exit (9, 1) give sequencer 0x46'),
    (0x800E11D0, 0x800E11EE, 'c0b74cceabd0eb0e6a05e947dcabfb33d041b311358f73dfdd124a70f73680e3',
     'sequencer parameter set (obj, id, value, idx): TBH on the id'),
    (0x800E1330, 0x800E136E, '79fe9ebfa959800ce86480a7bcdfaf95b7d1fb4c9030182d239f4b6e6eabe554',
     'sequencer parameter set, id 0x46: the value range-checked through the object, then stored (0x80016228)'),
    (0x8012CE20, 0x8012CE70, 'cf4f00cc08b9f67c5626e3b41bd7ca230b859723c37a1c108db64e5bc9a826d0',
     'the RESAMPLE page\'s leave (vtable +0x11c): the current bank and pad kept while project 100 [bank * 16 + pad] '
     '(the pad holds a sample) is set, else restored as the exit restores them (0x80134990)'),
    (0x801348F0, 0x80134918, '41deecdd7e3c3bc2bbac0b3d286468acafb66a34794104f235cc6c746096a224',
     'the RESAMPLE page\'s leave event (vtable +0x14): its +0x11c, then the base page\'s'),
    (0x80223480, 0x80223484, 'b202e477e04e2278af881afe8fd8b68e08ab940f5c3ad3fdc567bed411de07a1',
     'RESAMPLE page vtable +0x14 = 0x801348f1'),
    (0x80223588, 0x8022358C, 'eb85cd1c803a2aec47e120f541e71334c33e1d765205b7643ae5dd8a21834587',
     'RESAMPLE page vtable +0x11c = 0x8012ce21'),
    (0x801F9054, 0x801F9058, 'f6057c13c9a5310f306fbfaa4a7be311d732e1b9c2ad293c5971255d4b7ac219',
     'page registry 0x801f8f74, page 0xe: its handler slot 0x8023b5fc'),
    (0x8023B5FC, 0x8023B600, '83b18a8e24ec776b6e70c918ea60ee726c60b978f834839ccf40525ec13320e6',
     'page 0xe\'s handler slot: 0x80053cb9'),
    (0x80053CB8, 0x80053CCE, '1abdc2a2d370e2988593766bbb8141cb6a7c691a90b9e3fae1314223830e6e9a',
     'page 0xe\'s handler: event 0x13, 2 (leave) and 1 (enter)'),
    (0x80053D7C, 0x80053DA8, '98481fc8b91f20813735f95125b64e37946e0901d6566783de8e82aa6b6193d7',
     'page 0xe\'s handler, leave: the page object\'s event (+8) with the event, then its destructor (+4)'),
    (0x801F8F84, 0x801F8F88, '26f07975d0102f4cf9cce345728b2e7c470e1eecad90cddbd51f7e02f4a63cab',
     'page registry, page 1 (TOP, the main screen): its handler slot 0x8023b64c'),
]
# 16-bit jump-table entries: (address, value, what)
TABLE_GUARDS = [
    (0x800D9526, 359, 'settings get 0x1a -> 0x800d97c0'),
    (0x800D953A, 399, 'settings get 0x24 -> 0x800d9810'),
    (0x800D955E, 463, 'settings get 0x36 -> 0x800d9890'),
    (0x800E127A, 161, 'sequencer set 0x46 -> 0x800e1330'),
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
    (0x800D953C, 403, 'settings get 0x25 (EXT SOURCE) -> 0x800d9818'),
    (0x800DD148, 439, 'settings set 0x25 (EXT SOURCE) -> 0x800dd46c'),
    (0x80018FBE, 621, 'system parameter set 0x141 (MARK Function) -> 0x8001921c'),
]
POPUPS = {
    'setup': 'BOUNCE A-1>A-9 | REPLACE A-1\\nNO TAIL | TAIL | TAIL ONLY',
    'undo': 'UNDO BOUNCE?\\nORIG ON A-9',
    'waiting': 'BOUNCE A-1>A-9 | REPLACE A-1\\nWAIT SILENCE',
    'running': 'BOUNCE A-1>A-9 | REPLACE A-1\\nNO TAIL 37% | TAIL 2.4s',
    'swapping': 'REPLACE A-1\\nSWAPPING | UNDO A-1\\nSWAPPING',
    'done': ['BOUNCED A-1\\nON A-9', 'REPLACED A-1\\nORIG ON A-9', 'UNDONE A-1\\nBOUNCE ON A-9'],
    'cancelled': 'BOUNCE CANCELLED\\nNOTHING CHANGED',
    'refused': ['NO EMPTY PAD', 'STOP PATTERN FIRST', 'STOP LOOPER FIRST', 'FX STILL RINGING', 'BOUNCE FAILED',
                'BANK PROTECTED\\nNOTHING CHANGED', 'INPUT TURNED ON\\nNOTHING CHANGED', 'CANNOT UNDO\\nPADS CHANGED'],
    'failed': ['STORAGE FULL\\nPART ON A-9 | NOTHING CHANGED', 'BOUNCE FAILED\\nPART ON A-9 | NOTHING CHANGED',
               'SWAP FAILED\\nCHECK A-1 A-9'],
}
PAD_SETTINGS = dict(
    copied=['GATE 0x6a', 'MUTE GROUP 0x6d', 'TEMPO SYNC 0x6e', 'Polyphonic 0x70 (its stretch bits too)', 'Roll 0x7b'],
    copied_when='VINYL MODE 0x77 with TEMPO SYNC on (sync needs it off), else the default 1; the loop flag 0x72 when '
                'NO TAIL keeps a loop',
    neutral={'VOLUME 0x69': 127, 'PAN 0x78': 64, 'PITCH 0x73': 0, 'FINE 0x74': 0, 'SPEED 0x76': 10000,
             'PLAY 0x75': 0, 'BUS FX Assign 0x7a': '0 (DRY)', 'Attack 0x7d': 0, 'Hold 0x7e': 100},
    release='Release 0x7f: 1 (23.6 ms, the shortest stock step) for a NO TAIL one-shot, whose effect is cut at END: '
            'with Hold 100 the positional envelope fades its last 23.6 ms, and a GATE key-up fades over min(23.6 ms, '
            'what is left). 0 for a NO TAIL of a loop (the fade would dip every pass) and for TAIL (it ends below '
            '-72 dBFS)',
    by_mode='LOOP 0x6b: NO TAIL keeps the source\'s, TAIL off; loop point: NO TAIL of a loop at the source\'s own '
            'offset, else START',
    name='the source\'s name, then " B", in the stock 23 characters: the source\'s cut to make room, its trailing spaces '
         'dropped; a source with no name gives its pad (A1 B). The run\'s numbers stay in RAM (bnc_ui_state r_*)',
    pad_link='TO PAD: 0. REPLACE: the bounce takes the source\'s group and the parked original leaves it (0); UNDO '
             'puts it back. During the run the source is out of its group, so only the pad itself is recorded',
    stock_defaults='everything else as the stock finalize leaves any new sample (0x800cfa68), ORIGINAL BPM = REC BPM '
                   '(the SP\'s tempo: the stock tempo setter 0x80019820 writes it; the run leaves it alone)')


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
    keep = ' '.join(f'KEEP(*(.text.{n}))' for n in FUNCTIONS)
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
    elf = (folder / 'bounce.elf').read_bytes()
    code, symbols = read_module(elf, link_base, limit)
    missing = [n for n in EXPORTS if n not in symbols]
    if missing:
        raise ValueError(f'module exports missing: {missing}')
    bss = bss_range(elf)
    if bss[0] < link_base or bss[0] + bss[1] != link_base + len(code) or any(code[bss[0] - link_base:]):
        raise ValueError('the module must end with its zero-initialised .bss')
    return code, {n: symbols[n] for n in EXPORTS}, sha(source.read_bytes()), bss


def bss_range(elf):
    """(address, size) of the ELF's .bss: it becomes a zero-fill boot row instead of stored zeros."""
    shoff = struct.unpack_from('<I', elf, 32)[0]
    shsize, count, names = struct.unpack_from('<3H', elf, 46)
    sections = [struct.unpack_from('<10I', elf, shoff + i * shsize) for i in range(count)]
    strings = sections[names]
    for s in sections:
        if elf[strings[4] + s[0]:].split(b'\0')[0] == b'.bss':
            return s[3], s[5]
    raise ValueError('the module has no .bss')


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
        # From 0x800bef10 (bx), r0 = the event, lr = the caller: bnc_gate(event); 0 returns to the caller
        # (the event is dropped), else the four displaced instructions with the event in r0.
        'gate': ('push {r0, lr}\n' + call(sym['bnc_gate']) + 'mov r12, r0\npop.w {r0, lr}\ncmp.w r12, #0\n'
                 'bne pass\nbx lr\npass:\nldrb r1, [r0]\ncmp r1, #0xa0\nbhi high\n' + jump(RING) + 'high:\n' +
                 jump(DISPATCH_HIGH)),
        # From 0x8012db58 (bx), r0 = the RESAMPLE page, r1 = its refresh flag, lr = the caller: the displaced push
        # and frame, bnc_tick(page) with r0 and r1 kept, the displaced moves and modal test (r0 = the page), then
        # the tick at 0x8012db64 with the test's result in r0.
        'tick': ('push {r4, r5, r6, r7, lr}\nsub sp, #4\npush {r0, r1}\n' + call(sym['bnc_tick']) +
                 'pop {r0, r1}\nmov r6, r1\nmov r5, r0\n' + call(MODAL) + jump(PAGE_TICK_REST)),
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

    module, symbols, source_sha, (bss_at, bss_size) = compile_module(out / 'build', zig, base + CODE_OFFSET,
                                                                     base + SLOT)
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
    blob += module[:bss_at - (base + CODE_OFFSET)]      # stored: bridges, code, constants; .bss is a zero row
    if bss_at + bss_size > base + SLOT:
        raise ValueError(f'the module ({bss_at + bss_size - base} bytes) exceeds the slot')
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
    new_rows = [[FLASH + file_at, base, len(blob), COPY], [0, bss_at, bss_size, ZERO]]
    for row in rows + new_rows:
        img += struct.pack('<4I', *row)
    struct.pack_into('<2I', img, 0x80, table - 0x80, len(img) - 0x80)
    if FLASH + len(img) > PCM_BANK:
        raise ValueError(f'APP1 would reach the kit PCM planning boundary ({FLASH + len(img) - PCM_BANK} bytes over)')
    if runtime(img, base, len(blob)) != bytes(blob) or scatter(img)[-2:] != new_rows:
        raise ValueError('the new rows do not reproduce the module')

    out.mkdir(parents=True, exist_ok=True)
    (out / 'SP404MKII_APP1.bin').write_bytes(img)
    shutil.copy2(app0, out / 'SP404MKII_APP0.bin')
    parent_manifest = inp.with_name('manifest.json')
    parent_sha = sha(inp.read_bytes())
    manifest = dict(
        revision=REVISION, status='hardware-unverified', published=False,
        description='bounce in place, stage 3: hold RESAMPLE and tap a sample pad; the pad is recorded through '
                    'its effects, frame-exact, in NO TAIL or TAIL mode, onto the first empty pad (TO PAD) or in its '
                    'place (REPLACE: the stock pad exchange, the original kept on that pad), with UNDO; named after '
                    'the source with " B"; a finished bounce returns to the main screen. test8: a pad tapped in the '
                    'setup picks the target (the source itself REPLACE, an empty pad TO PAD onto it, a pad with a '
                    'sample PAD NOT EMPTY), RESAMPLE (or REC) starts',
        parent_app1=str(inp), parent_sha256=parent_sha, parent_is_published_v946=parent_sha == PUBLISHED_V946,
        parent_revision=json.loads(parent_manifest.read_text(encoding='utf-8')).get('revision')
        if parent_manifest.exists() else None,
        replaces='bounce-3-test7 (the same six sites, the same parent)',
        changes=["a pad tapped in the setup picks the target (the user's ask after combined-test3): the source itself "
                 "is REPLACE (the original parked on the home pad, the first empty one), an empty pad TO PAD onto that "
                 "pad, a pad with a sample is refused with PAD NOT EMPTY and its name for a second (a protected bank: "
                 "BANK PROTECTED); in the UNDO popup a tap leaves UNDO for that bounce. VALUE press no longer picks the "
                 "target (VALUE turned still picks NO TAIL / TAIL)",
                 "RESAMPLE pressed starts the bounce (or the UNDO), as REC does"],
        changes_test7=["no LOOP mode: the setup offers NO TAIL and TAIL (TAIL only for a loop not at its own rate). On the "
                 "unit a LOOP take of a pad through a reverb started inside the previous pass's tail, so played once "
                 "it clicked at its start; the user bounces one-shots. NO TAIL of a loop keeps one pass from T0 with "
                 "LOOP and the loop point copied, as before. The pass comparison and its RAM are gone",
                 "a NO TAIL one-shot gets Release 1 (23.6 ms, the shortest stock step) with Hold 100: the positional "
                 "envelope fades its last 23.6 ms, so an effect cut at END fades instead of clicking; the length stays "
                 "the source's. Not for a NO TAIL of a loop (the fade would dip every pass) nor TAIL (it ends quiet)",
                 "the bounced pad is named after the source with \" B\", in the stock 23 characters (the source's name "
                 "cut to make room); the test numbers stay in RAM (bnc_ui_state r_*)",
                 "a finished bounce (BOUNCED, REPLACED, UNDONE) leaves RESAMPLE for the main screen: RESAMPLE mode off "
                 "(settings 0x36), sequencer 0x46 back as the stock exit sets it, every LED redrawn, then the page "
                 "request for page 1 (0x800da598), as the after-recording routine ends. Not its BUS 1/2 effects off, "
                 "not the exit's REC_STOP, ALL SOUND OFF and bank and pad restore: the effects, bank, pad and END "
                 "Snap stay as they were. EXIT or a refusal stays on RESAMPLE"],
        changes_test6=["the take's start is found in the return alone: the first non-zero RX frame after 8 silent ones, at "
                 "most 24 frames before the return's onset (the RX onset; when none was measured, the TX onset's frame "
                 "plus L), not before T0; else L. test4 and test5 placed the search from the sound's first non-zero "
                 "TX frame, which says nothing of where the return begins (bounce-3-test5 on the unit: D1 L72-3 M69 "
                 "P66.1 D-1, START 453, the take's first non-zero sample at 450; D1 the original hi-hat, whose quiet "
                 "start can round to 0 in the stems at a pad VOLUME below 127). Never later than L, so a source that "
                 "begins with silence keeps it",
                 "LOOP takes a pass of the loop's steady state: each pass's return is summed per bin (|L| + |R|, a block "
                 "a bin, at most 256) and compared with the first pass of the current run of agreeing passes (every bin "
                 "within about 0.5 dB, or both near silence); the take is the pass after a run of 3 s, or at 30 s the "
                 "next pass with the popup LOOP NOT SETTLED. test5 took the second pass, which an echo longer than a "
                 "pass had not reached (the user: a delayed hi-hat as LOOP missed the delayed hit). The popup counts "
                 "the passes (LOOP x12); the name ends with the pass taken (x80). put and put_uint out of line: APP1 "
                 "stays below the kit PCM planning boundary"],
        changes_test5=["the parent is the published v9.46's kit stage plus the RESAMPLE start fix v3 (resample-startfix-3) "
                 "instead of the published v9.46 (v2): a normal RESAMPLE's START keeps the return's quiet lead-in, "
                 "8 frames before the first sample above -72 dBFS, where v2 put it on that sample. The bounce module, "
                 "bridges and sites are test4's, byte for byte; a bounce never goes through the start fix (its take "
                 "ends with the engine's first-sound frame set to none, and the run sets START after the finalize). "
                 "The guard on the start fix's code holds v3's bytes"],
        changes_test4=["the take starts where the return departs from silence: the first non-zero RX frame in the 16 "
                 "frames before L, after 8 silent ones, else L. The unit's return pre-rings each attack about 7 "
                 "frames before its main delay (a closed hi-hat on test3: L73 M73, START 457, first non-zero 450), so "
                 "test3 cut the attack's start and a LOOP take ended in the next pass's pre-ring (the end click). The "
                 "window stays one pass; layered with its source, the bounce's main attack sits up to the pre-ring "
                 "(about 7 frames, 0.15 ms) late",
                 "the boot's calibration is an offset on T1's relation (1/16 frames), applied to each take's own P "
                 "and D: test3 kept an L, which a P move within the boot made wrong (P65.1 then P62.0: the LOOP "
                 "take used L73 where its phase and its onset M76 said 76)",
                 "the pad's name shows the departure (A1 L73-7 M73 P65.1 D-1); a name longer than the stock 23 "
                 "characters leaves out P's tenth, so D is never cut (A12 L73-7C M73 P65 D-1)"],
        changes_test3=["the bounced pad is charged again from its window after its settings, as the stock finalize ends "
                 "(0x800d6390, 0x800d7508): bounce-3-test2 kept the take's charge, so it played the take's length from "
                 "its new START, L + 32 frames past END (in LOOP mode the next pass's beginning, a click with LOOP off, "
                 "each loop L + 32 frames long)",
                 "L is the phase estimate, 138.5 - (P mod 64) + 64 D: an onset is used only within 1 frame of it "
                 "(test2: within 6, modulo 64, so a soft attack's onset 3 frames early was used, L69 M69 against "
                 "L72 M72 at the same P66, and a far one could pass as another 64-frame block)",
                 "the TX onset and quiet thresholds are the RX ones (128, 8): the stems carry 16-bit samples, at the "
                 "capture's scale (test2 put TX 24 dB higher, so a soft attack crossed it late)"],
        changes_test2=['the looper refuses or ends a bounce only while it plays, records, overdubs or waits for a '
                 'level (phase +0x101), no longer whenever MARK Function = LOOPER (+0x39 = enabled)',
                 "the RESAMPLE page's tick (0x8012db58) no longer sees a bounce's standby, take or cancel: after a "
                 "take its after-recording routine (0x8012cbb0) switched the BUS 1/2 effects off, made the stock "
                 "pad handler's last destination current (bank A after a reboot) and left RESAMPLE, and its state "
                 'handler (0x8012dcb0) switched END Snap off after a cancelled standby',
                 'REC BPM (settings 0x1b) is no longer set and restored: it retuned the sequencer and the '
                 'effects chip (system parameter 0x275) and left the stock REC BPM flags set',
                 'TO PAD / REPLACE and the mode are kept as soon as they are picked',
                 "the pad name's edited flag is left to the stock name function (no 32-bit write)"],
        pad_settings=PAD_SETTINGS,
        replace=dict(command='0x40d -> 0x800a6c30(gSmplMgr 0x80591800, source, scratch, 2), then a recorder target '
                             'write (param 1 = 15) as the fence; checked: both pads hold samples, sizes swapped',
                     guarantees='files renamed through B:/tmp.SMP and parameters swapped in RAM, then both pads '
                                'reloaded and the pad parameters saved; not atomic: a power loss between the '
                                'renames and the save leaves files and parameters out of step',
                     undo='RAM only, up to 8 pairs; the same exchange again, then the original\'s PAD LINK back'),
        leaks=dict(input='EXT SOURCE (settings 0x25) off from REC to the end, then back; switched on during a take '
                         '-> INPUT TURNED ON, the take discarded',
                   notes='0x800bef10 drops every pad note-on but the run\'s own trigger while a bounce owns the '
                         'recorder (MIDI, rolls, the sequencer); a pattern or the looper starting -> discarded',
                   pad_link='the source out of its PAD LINK group for the run',
                   looper='refused, or the take discarded, while the looper phase (0x82e0b71c + 0x101) is '
                          'not 0 (empty) or 6 (stopped), or is 6 with an overdub queued (+0x102); when '
                          'the looper is disabled, only its playing phases 5, 8, 9, 10'),
        recorder_failures='the RX side writes only while the stock gate would (sub-state 2, error word 0); when the '
                          'stock recorder ends a take itself the run waits for its finalize and reports STORAGE FULL '
                          '(-0x3e, -0x78, -0x80) or BOUNCE FAILED, with PART ON <scratch> when it left a take there',
        sha256=sha(img), size=len(img), app0_sha256=APP0_SHA,
        slot=[base, base + SLOT], blob_base=base, blob_file_offset=file_at, blob_size=len(blob), blob_sha256=sha(blob),
        bss=[bss_at, bss_size], rows_added='a copy row for the blob, a zero-fill row for the module\'s .bss',
        source='synth/bounce.c', source_sha256=source_sha, compiler='zig 0.13.0 cc -Os',
        entries=entries, patches=patches, data_patches=data_patches,
        branch_scan=dict(bytes=scanned, result='no direct branch into a patched span'),
        guards=[dict(start=s, end=e, sha256=d, establishes=w) for s, e, d, w in GUARDS],
        table_guards=[dict(address=a, value=v, establishes=w) for a, v, w in TABLE_GUARDS],
        latency=dict(k_chip=138.5, center=75, onset_accept=1, onset_calibrates=1, depart_span=24, depart_quiet=8,
                     estimate='138.5 - (P mod 64) + 64 D (T1: L - 64 D + (P mod 64) = 138 or 139) for this take\'s P '
                              'and D, plus this boot\'s calibration (an offset in 1/16 frames); outside 8..300 the '
                              'candidate nearest 75. P = eDMA phase as the probe read it, D = RX blocks - TX blocks',
                     window='START = F0 + where the return departs from silence, found in the return: the first RX '
                            'frame not 0 after 8 silent ones, at most 24 frames before the RX onset (else the TX '
                            'onset\'s frame plus L), not before T0; else F0 + L',
                     onset='TX stems above 128 within 100 ms of T0; RX above 128 8..300 frames later (the stems carry '
                           '16-bit samples, at the capture\'s scale); used only within 1 frame of the estimate, and '
                           'calibrates the boot only within 1 frame of the phase'),
        thresholds=dict(silence='RX |x| <= 8 and TX |x| <= 8 for 9600 frames, at most 10 s',
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
