"""Route the stock MIDI dispatcher through the kit module: M.CH, the drum map and CCs.

Call apply_kit_midi(image, info["arp_symbols"], builder) before sparse packing.
Returns (new_image_bytes, patch_records, guard_records). Both MIDI ports share
the handler table at 0x802091ec (note-off 0x80067020, note-on 0x80066cf8, CC
0x80066130), so the four patched sites cover them. Every patched site, and every
stock instruction a gate relies on or returns into, is checked against its exact
v9.6 instructions first.
"""

# (address, bytes, exact v9.6 instructions, gate). Each becomes a jump to the gate.
SITES = (
    # Channel 16 runs the control functions unless it plays the SG page.
    (0x80066D18, 12, ['cmp r0, #0xf', 'bne #0x80066d50', 'bl #0x800d6380', 'cmp r0, #0x1e',
                      'beq #0x80066d50'], 'kit_midi_control_gate'),
    # Note-on: channel 16 to the stock SG handler 0x8005a680, others to the pad path.
    (0x80066E64, 10, ['cmp r5, #0xf', 'bne #0x80066e78', 'ldrb r0, [r4, #2]', 'movs r2, #0',
                      'ldrb r1, [r4, #3]'], 'kit_midi_on_gate'),
    # Note-off: the same decision.
    (0x800670B8, 10, ['cmp r5, #0xf', 'bne #0x800670cc', 'ldrb r0, [r4, #2]', 'movs r1, #0',
                      'movs r2, #1'], 'kit_midi_off_gate'),
    # CC (0xBn, handler 0x80066130): the SG sees every CC, then the stock queue write runs as before.
    (0x80066174, 10, ['movw r0, #0xd96c', 'ldrh r3, [r4, #2]', 'movt r0, #0x80d3'], 'kit_midi_cc_gate'),
)

# Unpatched stock code the gates depend on: (address, bytes, exact instructions, why).
GUARDS = (
    (0x80066CF8, 4, ['push {r4, r5, r6, r7, lr}', 'sub sp, #4'], 'note-on frame the gates unwind'),
    (0x80066D10, 8, ['mov r4, r0', 'ldrb r0, [r0, #1]', 'and r0, r0, #0xf'],
     'control gate: r0 = channel, r4 = message'),
    (0x80066D24, 6, ['ldrb r1, [r4, #2]', 'sub.w r0, r1, #0x18'], 'control functions entry'),
    (0x80066D50, 8, ['movw r0, #0x370', 'movt r0, #0x82e1'], 'note path entry'),
    (0x80066E5C, 8, ['ldrb r1, [r4, #2]', 'mov r0, r5', 'bl #0x8005ec50'],
     'note-on gate: r0 = pad lookup, r5 = channel'),
    (0x80066E6E, 10, ['add sp, #4', 'pop.w {r4, r5, r6, r7, lr}', 'b.w #0x8005a680'],
     'note-on stock tail to 0x8005a680'),
    (0x80066E78, 2, ['mov r6, r0'], 'note-on pad path'),
    (0x80067020, 4, ['push {r4, r5, r6, r7, lr}', 'sub sp, #4'], 'note-off frame the gates unwind'),
    (0x800670B0, 8, ['ldrb r1, [r4, #2]', 'mov r0, r5', 'bl #0x8005ec50'],
     'note-off gate: r0 = pad lookup, r5 = channel'),
    (0x800670C2, 10, ['add sp, #4', 'pop.w {r4, r5, r6, r7, lr}', 'b.w #0x8005a680'],
     'note-off stock tail to 0x8005a680'),
    (0x800670CC, 2, ['mov r6, r0'], 'note-off pad path'),
    (0x8005A680, 18, ['push {r4, r5, r6, r7, lr}', 'sub sp, #0x14', 'mov r6, r2', 'mov r5, r1',
                      'mov r4, r0', 'bl #0x800d6380', 'cmp r0, #0x1e', 'bne #0x8005a6a6'],
     'stock SG handler frame, rebuilt by the note-off gate'),
    (0x8005A6A4, 10, ['cbz r6, #0x8005a6ae', 'sub.w r0, r4, #0x24', 'cmp r0, #0x18', 'bls #0x8005a6b4'],
     'stock chromatic half after the SG call'),
    (0x8005A6AE, 4, ['add sp, #0x14', 'pop {r4, r5, r6, r7, pc}'], 'stock SG handler epilogue'),
    (0x80066130, 24, ['push {r4, lr}', 'mov r4, r0', 'movw r0, #0x1144', 'movt r0, #0x82e0', 'movs r1, #0x5d',
                      'movs r2, #0', 'bl #0x800d94d8', 'ldrb r1, [r4, #1]', 'cbz r0, #0x80066174'],
     'CC handler: r1 = status, r4 = message; setting 0x5d off reaches the queue write'),
    (0x8006617E, 8, ['ldr r2, [r0, #8]', 'strb r1, [r2], #4', 'movs r1, #2'], 'CC queue write the gate returns to'),
)

EXPORTS = ('kit_midi_control', 'kit_midi_route', 'kit_midi_control_gate', 'kit_midi_on_gate',
           'kit_midi_off_gate', 'kit_midi_cc', 'kit_midi_cc_gate')


def apply_kit_midi(image, symbols, builder):
    original = bytes(image)
    for address, size, expected, why in GUARDS:
        offset = builder.file_offset(original, address, size)
        found = builder.listing(original[offset:offset + size], address)
        if found != expected:
            raise ValueError(f'MIDI guard {address:#x} ({why}): expected {expected}, found {found}')
    result, patches = bytearray(original), []
    for address, size, expected, gate in SITES:
        offset = builder.file_offset(original, address, size)
        found = builder.listing(original[offset:offset + size], address)
        if found != expected:
            raise ValueError(f'MIDI site {address:#x}: expected {expected}, found {found}')
        source = builder.jump(symbols[gate]) + 'nop\n' * ((size - 10) // 2)
        replacement = builder.checked_asm(source, address)
        if len(replacement) != size:
            raise ValueError(f'MIDI site {address:#x}: patch is {len(replacement)} bytes, site {size}')
        result[offset:offset + size] = replacement
        patches.append(dict(address=address, bytes=size, original_hex=original[offset:offset + size].hex(),
                            replacement_hex=replacement.hex(), target_symbol=gate,
                            target=symbols[gate] | 1, original=expected))
    guards = [dict(address=a, bytes=n, instructions=e, why=w) for a, n, e, w in GUARDS]
    return bytes(result), patches, guards
