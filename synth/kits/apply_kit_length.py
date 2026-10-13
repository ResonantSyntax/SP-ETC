"""Drum export length: one guarded jump in the stock REC exporter's length code.

Call apply_kit_length(image, info["arp_symbols"], builder) before sparse packing.
Returns (new_image_bytes, patch_record, guard_records). Drum REC and BOUNC end at
each drum's own ring-out instead of the melodic PAD LENGTH: kit_record.inc sets
kit_export_frames for the next export, and the jump lets kit_export_length_gate
replace the exporter's frame count and loop frame limit with it, once. With
kit_export_frames zero (melodic REC) the gate runs the three displaced
instructions and nothing else. The site and every instruction the length relies
on are checked against their exact v9.6 instructions first.
"""

# (address, bytes, exact v9.6 instructions): the exporter's length code, after
# fp (frames) and [sp, #4] (the loop limit) are set from PAD LENGTH.
SITE = (0x80132AC8, 10, ['mov r4, r8', 'cmp.w fp, #1', 'mov.w r0, #0'])

# Unpatched code the length depends on: (address, bytes, exact instructions, why).
GUARDS = (
    (0x80132AD2, 8, ['str r0, [r4, #0x78]!', 'blt.w #0x80132c98'],
     'the gate returns here; the blt reads the flags of the displaced cmp'),
    (0x80132A5E, 2, ['str r0, [sp, #4]'], 'loop limit from PAD LENGTH (seconds), before the site'),
    (0x80132AC4, 4, ['str.w fp, [sp, #4]'], 'loop limit from PAD LENGTH (periods), before the site'),
    (0x80132C6E, 12, ['sub.w r1, sl, #1', 'ldr r2, [sp, #4]', 'cmp r1, r2', 'add r6, r0', 'bge #0x80132c84'],
     'the sample loop ends at the limit in [sp, #4] ...'),
    (0x80132AEC, 6, ['mov r0, r8', 'bl #0x80007700'], '... or at fp; every frame goes through the oscillator gate'),
    (0x8353BA00, 6, ['ldr r2, [sp, #4]', 'mov r0, sl', 'mov r1, fp'],
     'the export mix (end fade) reads the same frame, fp and limit'),
    (0x801327B8, 10, ['movw ip, #0xb781', 'movt ip, #0x8353', 'bx ip'],
     'the exporter entry goes to the v4 export engine'),
    (0x8353B79C, 4, ['ldr r7, [r6]', 'cbnz r7, #0x8353b7c2'],
     'the engine renders the export voices already set (count at 0x8353c700) without a new capture'),
    (0x801327C4, 8, ['mov r8, r0', 'ldr.w r0, [r0, #0x17c]', 'adds r0, #1'],
     'the stock body: destination bank * 16 + pad at +0x17c, -1 = none'),
)

EXPORTS = ('kit_export_length_gate',)
STATE = ('kit_export_frames',)


def apply_kit_length(image, symbols, builder):
    original = bytes(image)
    for address, size, expected, why in GUARDS:
        offset = builder.file_offset(original, address, size)
        found = builder.listing(original[offset:offset + size], address)
        if found != expected:
            raise ValueError(f'length guard {address:#x} ({why}): expected {expected}, found {found}')
    address, size, expected = SITE
    offset = builder.file_offset(original, address, size)
    found = builder.listing(original[offset:offset + size], address)
    if found != expected:
        raise ValueError(f'length site {address:#x}: expected {expected}, found {found}')
    replacement = builder.checked_asm(builder.jump(symbols['kit_export_length_gate']), address)
    if len(replacement) != size:
        raise ValueError(f'length site {address:#x}: patch is {len(replacement)} bytes, site {size}')
    result = bytearray(original)
    result[offset:offset + size] = replacement
    patch = dict(address=address, bytes=size, original_hex=original[offset:offset + size].hex(),
                 replacement_hex=replacement.hex(), target_symbol='kit_export_length_gate',
                 target=symbols['kit_export_length_gate'] | 1, original=expected)
    guards = [dict(address=a, bytes=n, instructions=e, why=w) for a, n, e, w in GUARDS]
    return bytes(result), patch, guards
