"""Kit shortcuts on the built ARM module, including the armed-imprint guard.

On the SG page with the stock keyboard flag on, SHIFT + RECORD SETTING leaves
the kits and SHIFT + PATTERN EDIT returns to the last kit. Between the two REC
presses (keyboard flag off: an imprint destination is being chosen) both
chords must change nothing: no machine switch, no all-stop, no cursor step.
Stock helpers are stubs; calls into them are counted.
Usage: python synth/test_kit_shortcut.py out/kits-v943
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_ALL, UC_HOOK_CODE
from unicorn import arm_const as ar

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from kits.sparse_module import reconstruct_module  # noqa: E402

PAGE, KB, KEYS = 0x80245880, 0x80591C48, 0x80592448
SG_PAGE, SHIFT, PATTERN, RECORD = 0x1E, 42, 21, 22
RET, STACK, EVENT = 0x1000, 0x20200000, 0x20100000
STUBS = {'release_all': 0x0001FE00, 'setting_get': 0x800D94D8, 'setting_step': 0x800BF8C8,
         'page_switch': 0x6031C9A8, 'stock_start': 0x800D0668,
         'dispatch_off': 0x800DED08, 'dispatch_on': 0x800DECF8}


def main():
    out = Path(sys.argv[1]).resolve()
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    img = (out / 'SP404MKII_APP1.bin').read_bytes()
    if hashlib.sha256(img).hexdigest() != man['sha256']:
        raise ValueError('APP1/manifest hash mismatch')
    base = man['arp_code_base']
    S = man['arp_symbols']
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for b, n in ((0, 0x20000), (0x80245000, 0x1000), (0x80249000, 0x1000), (0x80591000, 0x2000),
                 (0x800BF000, 0x1000), (0x800D0000, 0x1000), (0x800D9000, 0x1000), (0x800DE000, 0x1000),
                 (0x6031C000, 0x1000), (0x8353A000, 0x3000), (0x83F80000, 0x70000),
                 (EVENT, 0x1000), (STACK - 0x4000, 0x4000)):
        uc.mem_map(b, n, UC_PROT_ALL)
    uc.mem_write(base, reconstruct_module(img, man))
    uc.mem_write(RET, b'\x00\xbf')
    bx_lr, ret0 = b'\x70\x47', b'\x00\x20\x70\x47'
    for name, address in STUBS.items():
        uc.mem_write(address, ret0 if name == 'setting_get' else bx_lr)
    # The image routes the stock key getter to kit_ui_key_gate; do the same.
    uc.mem_write(0x800D9F20, bytes.fromhex(_jump_hex(S['kit_ui_key_gate'] | 1)))
    uc.reg_write(ar.UC_ARM_REG_C1_C0_2, uc.reg_read(ar.UC_ARM_REG_C1_C0_2) | (0xf << 20))
    uc.reg_write(ar.UC_ARM_REG_FPEXC, 0x40000000)
    calls = {name: 0 for name in STUBS}

    def counter(name):
        def hook(_uc, _address, _size, _data):
            calls[name] += 1
        return hook
    for name, address in STUBS.items():
        uc.hook_add(UC_HOOK_CODE, counter(name), begin=address, end=address)

    def call(fn, *args):
        uc.reg_write(ar.UC_ARM_REG_SP, STACK - 0x100)
        uc.reg_write(ar.UC_ARM_REG_LR, RET | 1)
        for k, a in enumerate(args):
            uc.reg_write(getattr(ar, f'UC_ARM_REG_R{k}'), a & 0xFFFFFFFF)
        uc.emu_start(S[fn] | 1, RET, count=2000000)
        if uc.reg_read(ar.UC_ARM_REG_PC) != RET:
            raise RuntimeError(('instruction limit or early exit', fn))
        return uc.reg_read(ar.UC_ARM_REG_R0)

    def keys(*down):
        bits = bytearray(16)
        for k in down:
            bits[k >> 3] |= 1 << (k & 7)
        uc.mem_write(KEYS, bytes(bits))

    def press_release(key):
        """Hold SHIFT + key (the press-side observer runs), then the key's release event."""
        keys(SHIFT, key)
        call('kit_ui_key_query', SHIFT, 0)
        uc.mem_write(EVENT, struct.pack('<2H', 6, key))
        handled = call('kit_shortcut_event', 0, EVENT)
        keys()
        call('kit_ui_key_query', SHIFT, 0)
        return handled

    def mode():
        return uc.mem_read(S['kit_mode'], 1)[0]

    uc.mem_write(PAGE, struct.pack('<h', SG_PAGE))
    uc.mem_write(KB, b'\x01')
    uc.mem_write(S['kit_mode'], bytes([5]))
    keys()
    call('kit_ui_key_query', SHIFT, 0)
    report = {}
    # Keyboard on: the shortcuts switch as documented.
    handled = press_release(RECORD)
    if handled != 1 or mode() != 0 or calls['release_all'] == 0:
        raise AssertionError(('SHIFT+RECORD SETTING should leave the kits', handled, mode(), calls))
    handled = press_release(PATTERN)
    if handled != 1 or mode() != 5:
        raise AssertionError(('SHIFT+PATTERN EDIT should restore kit 5', handled, mode()))
    report['keyboard_on'] = dict(record_setting_to=0, pattern_edit_to=5)
    # Imprint armed (first REC pressed): nothing may change.
    uc.mem_write(KB, b'\x00')
    before = dict(calls)
    for key, start in ((RECORD, 5), (PATTERN, 5)):
        handled = press_release(key)
        if handled != 1 or mode() != start or calls != before:
            raise AssertionError(('armed imprint changed state', key, handled, mode(), calls, before))
    uc.mem_write(S['kit_mode'], bytes([0]))
    handled = press_release(PATTERN)
    if handled != 1 or mode() != 0 or calls != before:
        raise AssertionError(('armed imprint entered kits', handled, mode(), calls, before))
    report['imprint_armed'] = dict(record_setting='ignored', pattern_edit='ignored', stock_calls_unchanged=True)
    # Imprint done (keyboard back on): the shortcut works again.
    uc.mem_write(KB, b'\x01')
    handled = press_release(PATTERN)
    if handled != 1 or mode() != 5:
        raise AssertionError(('shortcut after imprint', handled, mode()))
    report['after_imprint'] = dict(pattern_edit_to=5)
    report.update(passed=True, app1_sha256=man['sha256'])
    print(json.dumps(report))


def _jump_hex(target):
    from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB, KS_MODE_LITTLE_ENDIAN
    text = f'movw r12, #{target & 0xFFFF}\nmovt r12, #{target >> 16}\nbx r12\n'
    return bytes(Ks(KS_ARCH_ARM, KS_MODE_THUMB | KS_MODE_LITTLE_ENDIAN).asm(text, 0x800D9F20)[0]).hex()


if __name__ == '__main__':
    main()
