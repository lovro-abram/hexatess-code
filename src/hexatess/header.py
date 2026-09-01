"""Symbol constants, header (mode message) handling and block planning."""

from __future__ import annotations

import math

from .reedsolomon import rs_encode_msg, rs_correct_msg

# ----------------------------------------------------------------------
# Symbol constants (fixed in specification v0.2)
# ----------------------------------------------------------------------

BULLSEYE_RINGS = 4     # rings 0..4 form the hexagonal bullseye finder
KEY_RING = 5           # ring 5 is the orientation key
DATA_RING0 = 6         # payload serialization starts at ring 6
MAX_RINGS = 31         # largest permitted symbol radius
BLOCK_DATA_MAX = 50    # max data bytes per independent RS block
MODE_BYTES = 5         # header payload length in bytes
MODE_ECC = 5           # header ECC symbols (corrects up to 2 byte errors)
MODE_BITS = (MODE_BYTES + MODE_ECC) * 8   # 80 bits

MIN_EC_PCT = 5         # minimum error-correction percentage
MAX_EC_PCT = 90        # maximum error-correction percentage
EC_STEP = 5            # EC percentage must be a multiple of 5
MAX_DATA_BYTES = 4095  # 12-bit length field


# ----------------------------------------------------------------------
# Bit/byte helpers
# ----------------------------------------------------------------------

def bytes_to_bits(data) -> list:
    """MSB-first expansion of bytes into a list of 0/1 bits."""
    bits = []
    for b in data:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    return bits


def bits_to_bytes(bits) -> bytes:
    """Pack a list of bits (MSB first) into bytes.

    Trailing bits fewer than 8 are ignored.
    """
    out = bytearray()
    for i in range(0, len(bits) - 7, 8):
        v = 0
        for j in range(8):
            v = (v << 1) | bits[i + j]
        out.append(v)
    return bytes(out)


# ----------------------------------------------------------------------
# Mode message (header): 5 data bytes + 5 ECC bytes, never masked
#
#   byte 0: rmax (5 bits)          | mask_id (3 bits)
#   byte 1: ec_pct/5 (5 bits)      | block_count >> 5 (3 bits)
#   byte 2: block_count & 0x1F (5) | data_len >> 9 (3 bits)
#   byte 3: data_len >> 1 & 0xFF (8 bits)
#   byte 4: data_len & 1 (1 bit)   | compressed (1 bit) | padding (6 bits)
#
# `compressed` (spec v0.3, byte 4 bit 6 = 0x40): 0 = payload is raw
# UTF-8 (spec v0.2 layout), 1 = payload is a zlib stream (RFC 1950)
# of the UTF-8 text.  `data_len` always counts the STORED bytes.
# ----------------------------------------------------------------------

COMPRESSED_FLAG = 0x40   # byte 4, bit 6

def pack_mode(rmax, mask_id, ec_pct, block_count, data_len,
              compressed=False) -> bytes:
    """Encode symbol parameters into a 10-byte protected mode message.

    The returned bytes are the 5 data bytes followed by 5 Reed-Solomon
    ECC bytes.  The mode message is NEVER masked (it contains the mask
    identifier itself -- the same design decision as Aztec Code).
    """
    if rmax > 31 or mask_id > 7 or ec_pct % 5 or ec_pct // 5 > 31 \
            or block_count > 255 or data_len > 4095:
        raise ValueError("parameters out of mode-message range")
    ecq = ec_pct // 5
    b0 = (rmax << 3) | mask_id
    b1 = (ecq << 3) | (block_count >> 5)
    b2 = ((block_count & 0x1F) << 3) | ((data_len >> 9) & 0x7)
    b3 = (data_len >> 1) & 0xFF
    b4 = (data_len & 1) << 7
    if compressed:
        b4 |= COMPRESSED_FLAG
    payload = bytes([b0, b1, b2, b3, b4])
    return rs_encode_msg(list(payload), MODE_ECC)


def unpack_mode(mode_bytes):
    """RS-correct the mode message and decode symbol parameters.

    Returns ``(rmax, mask_id, ec_pct, block_count, data_len)``.
    The compression flag is ignored here (backward-compatible API);
    use :func:`unpack_mode_ex` when it is needed.
    """
    rmax, mask_id, ec_pct, block_count, data_len, _c = unpack_mode_ex(
        mode_bytes)
    return rmax, mask_id, ec_pct, block_count, data_len


def unpack_mode_ex(mode_bytes):
    """Like :func:`unpack_mode` but also returns the payload mode.

    Returns ``(rmax, mask_id, ec_pct, block_count, data_len,
    compressed)`` where ``compressed`` is a bool (spec v0.3 flag;
    always False for spec v0.2 symbols).
    """
    data = rs_correct_msg(list(mode_bytes), MODE_ECC)
    b0, b1, b2, b3, b4 = data
    rmax = b0 >> 3
    mask_id = b0 & 0x7
    ecq = b1 >> 3
    block_count = ((b1 & 0x7) << 5) | (b2 >> 3)
    data_len = ((b2 & 0x7) << 9) | (b3 << 1) | (b4 >> 7)
    compressed = bool(b4 & COMPRESSED_FLAG)
    return rmax, mask_id, ecq * 5, block_count, data_len, compressed


# ----------------------------------------------------------------------
# Block planning
# ----------------------------------------------------------------------

def plan_blocks(data_len: int, ec_pct: int):
    """Split ``data_len`` bytes into independent RS blocks.

    Returns a list of ``(data_bytes, ecc_bytes)`` pairs.  Blocks carry at
    most ``BLOCK_DATA_MAX`` data bytes each.  ECC overhead per block is
    ``ceil(size * ec_pct / 100)``, clamped to a minimum of 2 symbols.
    """
    if data_len == 0:
        return [(0, 2)]
    bc = max(1, math.ceil(data_len / BLOCK_DATA_MAX))
    base, extra = divmod(data_len, bc)
    blocks = []
    for i in range(bc):
        size = base + (1 if i < extra else 0)
        ecc = max(2, math.ceil(size * ec_pct / 100.0))
        blocks.append((size, min(ecc, 255 - size)))
    return blocks
