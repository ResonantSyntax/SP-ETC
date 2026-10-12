"""Strict host-side reconstruction for sparse APP1 module COPY/ZERO rows."""
from __future__ import annotations

import hashlib
import struct

FLASH_BASE = 0x60080000
COPY_HANDLER = 0x600800E4
ZERO_HANDLER = 0x60080100


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scatter_rows(image: bytes) -> list[list[int]]:
    """Read the header-bounded scatter table, rejecting malformed bounds."""
    if len(image) < 0x88:
        raise ValueError("APP1 is too short for scatter header")
    start_field, end_field = struct.unpack_from("<2I", image, 0x80)
    start, end = start_field + 0x80, end_field + 0x80
    if not (0x88 <= start <= end <= len(image)) or (end - start) % 16:
        raise ValueError("invalid header-bounded scatter table")
    return [list(struct.unpack_from("<4I", image, at))
            for at in range(start, end, 16)]


def reconstruct_module(image: bytes, manifest: dict) -> bytes:
    """Reconstruct and hash-check the dense module from APP1 COPY/ZERO rows.

    Older dense APP1 manifests are supported when the sparse metadata is absent.
    Sparse manifests use `arp_code_size` for the runtime VMA extent and
    `arp_code_stored_bytes` for the compact COPY payload length.
    """
    if len(image) < 0x88:
        raise ValueError("APP1 is too short for scatter header")
    try:
        base = int(manifest["arp_code_base"])
        dense_size = int(manifest["arp_code_size"])
        payload_file = int(manifest["arp_code_file"])
        expected_hash = manifest["arp_module_sha256"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("manifest lacks valid dense module identity") from exc
    if dense_size <= 0 or base < 0 or base + dense_size > 0x100000000 or payload_file < 0:
        raise ValueError("invalid module address, size, or payload offset")

    sparse_fields = ("arp_code_stored_bytes", "arp_code_stored_sha256")
    if not any(name in manifest for name in sparse_fields):
        end = payload_file + dense_size
        if end > len(image):
            raise ValueError("dense module payload exceeds APP1")
        dense = image[payload_file:end]
        if _sha(dense) != expected_hash:
            raise ValueError("dense module hash does not match manifest")
        return dense
    if not all(name in manifest for name in sparse_fields):
        raise ValueError("incomplete sparse module metadata")

    stored_size = int(manifest["arp_code_stored_bytes"])
    stored_hash = manifest["arp_code_stored_sha256"]
    if stored_size <= 0 or payload_file + stored_size > len(image):
        raise ValueError("sparse module payload bounds are invalid")
    # Scatter offsets are relative to the fixed 0x80-byte APP1 header.
    table_start, table_end = struct.unpack_from("<2I", image, 0x80)
    table_start += 0x80
    table_end += 0x80
    if payload_file + stored_size > table_start:
        raise ValueError("compact module payload overlaps the scatter table")
    payload = image[payload_file:payload_file + stored_size]
    if _sha(payload) != stored_hash:
        raise ValueError("sparse module payload hash does not match manifest")

    dense = bytearray(dense_size)
    target_end = base + dense_size
    module_rows = []
    for src, dst, size, handler in scatter_rows(image):
        # Reject rows that partially cross module bounds as well as exact hits.
        if dst < target_end and dst + size > base:
            if not (base <= dst < target_end and size > 0 and dst + size <= target_end):
                raise ValueError("scatter row partially overlaps module bounds")
            if handler not in (COPY_HANDLER, ZERO_HANDLER):
                raise ValueError("module row uses an unsupported loader handler")
            module_rows.append((src, dst, size, handler))

    module_rows.sort(key=lambda row: row[1])
    expected_dst = base
    expected_payload_offset = 0
    for src, dst, size, handler in module_rows:
        if dst != expected_dst:
            raise ValueError("module scatter rows contain a gap or overlap")
        offset = dst - base
        if handler == ZERO_HANDLER:
            if src != 0:
                raise ValueError("ZERO module row must have a zero source address")
            # New bytearray storage is already zero; preserve explicit assignment
            # to make coverage semantics clear.
            dense[offset:offset + size] = bytes(size)
        else:
            if src < FLASH_BASE:
                raise ValueError("COPY module source is below APP1 flash base")
            source_file = src - FLASH_BASE
            if source_file != payload_file + expected_payload_offset:
                raise ValueError("COPY rows do not consume compact payload contiguously")
            source_end = source_file + size
            if source_end > payload_file + stored_size or source_end > len(image):
                raise ValueError("COPY module source exceeds declared payload bounds")
            dense[offset:offset + size] = image[source_file:source_end]
            expected_payload_offset += size
        expected_dst += size
    if expected_dst != target_end:
        raise ValueError("module scatter rows do not cover the dense module extent")
    if expected_payload_offset != stored_size:
        raise ValueError("module COPY rows do not cover the complete stored payload")
    result = bytes(dense)
    if _sha(result) != expected_hash:
        raise ValueError("reconstructed dense module hash does not match manifest")
    return result
