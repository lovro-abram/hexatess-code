"""Hexatess Code decoder (ideal-sampling reference).

Accepts a module grid ``{(q, r): 0|1}`` (as produced by the encoder or
sampled from an image) and returns the decoded UTF-8 text together with
the header parameters.  Any symbol error correctable by Reed-Solomon is
absorbed transparently.  Symbols whose payload carries the spec v0.3
zlib-compression flag are inflated automatically.
"""

from __future__ import annotations

import zlib

from .geometry import hex_distance, hex_ring
from .header import (
    DATA_RING0,
    MODE_BITS,
    bits_to_bytes,
    plan_blocks,
    unpack_mode_ex,
)
from .masks import mask_bit
from .reedsolomon import rs_correct_msg


def payload_to_text(payload: bytes, compressed: bool) -> str:
    """Turn the Reed-Solomon-recovered payload bytes into text.

    ``compressed=True`` (spec v0.3 flag) inflates a zlib stream first;
    ``compressed=False`` treats the bytes as raw UTF-8 (spec v0.2).
    Raises :class:`ValueError` on a damaged zlib stream or invalid
    UTF-8.
    """
    if compressed:
        try:
            payload = zlib.decompress(payload)
        except zlib.error as e:
            raise ValueError("payload decompression failed: %s" % e) \
                from None
    return payload.decode("utf-8")


def _rs_recover_blocks(stream, blocks, data_len):
    """Per-block RS recovery; returns ``(payload_bytes, repaired_bits)``.

    ``repaired_bits`` is the total Hamming distance between the
    received codewords and their corrected versions -- a diagnostic
    measure of how damaged the sample was (0 = untouched codewords).
    """
    out = bytearray()
    total = 0
    pos_d = 0
    pos_e = 0
    for size, ecc in blocks:
        cw = list(stream[pos_d:pos_d + size]) + \
             list(stream[data_len + pos_e:data_len + pos_e + ecc])
        fixed = list(rs_correct_msg(cw, ecc))
        full = fixed + cw[size:]
        total += sum(bin(a ^ b).count("1") for a, b in zip(cw, full))
        out += bytes(fixed)
        pos_d += size
        pos_e += ecc
    return bytes(out), total


def decode(grid, params=None):
    """Decode a module grid into text.

    Parameters
    ----------
    grid : dict
        Mapping ``{(q, r): 0|1}``.
    params : dict, optional
        Ignored; kept for API symmetry with the original prototype.

    Returns
    -------
    (text, stats)
        ``text`` is the decoded UTF-8 string; ``stats`` reports the
        parameters read from the header (``rmax``, ``mask``, ``ec``,
        ``blocks``, ``data_len``, ``compressed``) plus ``repair_bits``
        (how many payload bits Reed-Solomon had to correct).
    """
    cells = sorted(grid.keys(), key=lambda c: hex_distance(*c))
    rmax = max(hex_distance(*c) for c in cells)
    data_cells = [c for k in range(DATA_RING0, rmax + 1)
                  for c in hex_ring(k)]
    bits = [grid[c] for c in data_cells]

    # --- protected header
    mode_bits = bits[:MODE_BITS]
    mode = unpack_mode_ex(bits_to_bytes(mode_bits))
    (rmax_m, mask_id, ec_pct, block_count, data_len,
     compressed) = mode

    # --- masked payload
    payload_bits = bits[MODE_BITS:MODE_BITS + (data_len + sum(
        e for _, e in plan_blocks(data_len, ec_pct))) * 8]
    payload_bits = [b ^ mask_bit(i, mask_id)
                    for i, b in enumerate(payload_bits)]
    stream = bits_to_bytes(payload_bits)

    # --- per-block Reed-Solomon correction
    blocks = plan_blocks(data_len, ec_pct)
    out, repaired = _rs_recover_blocks(stream, blocks, data_len)
    text = payload_to_text(out, compressed)
    stats = {"rmax": rmax_m, "mask": mask_id, "ec": ec_pct,
             "blocks": block_count, "data_len": data_len,
             "compressed": compressed, "repair_bits": repaired}
    return text, stats
