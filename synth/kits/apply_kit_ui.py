"""Three SG UI callback pointer patches; no code-entry or audio setter hooks.

Call apply_kit_ui(image, info["arp_symbols"], builder) before sparse packing.
Returns (new_image_bytes, patch_records). Verifies every site before mutation.
"""
import struct

EXPORTS = ("kit_ui_knob", "kit_ui_poll", "kit_ui_draw", "kit_ui_footer_draw")
SITES = (
    (0x802256FC, 0x80140069, "kit_ui_footer_draw"),
    (0x8022968C, 0x8015CE09, "kit_ui_knob"),
    (0x80229678, 0x8015BF19, "kit_ui_poll"),
    (0x8022BBD4, 0x801707C1, "kit_ui_draw"),
)


def apply_kit_ui(image, symbols, builder):
    original = bytes(image)
    patches = []
    for address, old_target, symbol in SITES:
        offset = builder.file_offset(original, address, 4)
        expected = struct.pack("<I", old_target)
        actual = original[offset:offset + 4]
        if actual != expected:
            raise ValueError(f"kit UI callback {address:#x}: expected {expected.hex()}, found {actual.hex()}")
        target = symbols[symbol] | 1
        patches.append(dict(address=address, offset=offset, bytes=4,
                            original_hex=expected.hex(), target_symbol=symbol,
                            target=target, replacement_hex=struct.pack("<I", target).hex()))
    result = bytearray(original)
    for patch in patches:
        at = patch["offset"]
        result[at:at + 4] = bytes.fromhex(patch["replacement_hex"])
    return bytes(result), patches
