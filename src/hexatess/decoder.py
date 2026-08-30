"""Hexatess Code decoder (ideal-sampling reference).

Accepts a module grid ``{(q, r): 0|1}`` (as produced by the encoder or
sampled from an image) and returns the decoded UTF-8 text together with
the header parameters.  Any symbol error correctable by Reed-Solomon is
absorbed transparently.
"""

from __future__ import annotations

from .geometry import hex_distance, hex_ring
from .header import (
    DATA_RING0,
    MODE_BITS,
    bits_to_bytes,
    plan_blocks,
    unpack_mode,
)
from .masks import mask_bit
from .reedsolomon import rs_correct_msg


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
        ``blocks``, ``data_len``).
    """
    cells = sorted(grid.keys(), key=lambda c: hex_distance(*c))
    rmax = max(hex_distance(*c) for c in cells)
    data_cells = [c for k in range(DATA_RING0, rmax + 1)
                  for c in hex_ring(k)]
    bits = [grid[c] for c in data_cells]

    # --- protected header
    mode_bits = bits[:MODE_BITS]
    mode = unpack_mode(bits_to_bytes(mode_bits))
    rmax_m, mask_id, ec_pct, block_count, data_len = mode

    # --- masked payload
    payload_bits = bits[MODE_BITS:MODE_BITS + (data_len + sum(
        e for _, e in plan_blocks(data_len, ec_pct))) * 8]
    payload_bits = [b ^ mask_bit(i, mask_id)
                    for i, b in enumerate(payload_bits)]
    stream = bits_to_bytes(payload_bits)

    # --- per-block Reed-Solomon correction
    blocks = plan_blocks(data_len, ec_pct)
    out = bytearray()
    pos_d = 0
    pos_e = 0
    ecc_total = sum(e for _, e in blocks)
    data_bytes = stream[:data_len]
    ecc_bytes = stream[data_len:data_len + ecc_total]
    for size, ecc in blocks:
        cw = list(data_bytes[pos_d:pos_d + size]) + \
             list(ecc_bytes[pos_e:pos_e + ecc])
        out += bytes(rs_correct_msg(cw, ecc))
        pos_d += size
        pos_e += ecc
    text = bytes(out).decode("utf-8")
    stats = {"rmax": rmax_m, "mask": mask_id, "ec": ec_pct,
             "blocks": block_count, "data_len": data_len}
    return text, stats
