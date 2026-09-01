"""Hexatess Code encoder.

Turns UTF-8 text into a hexagonal module grid ``{(q, r): 0|1}``.

Layout summary (specification v0.3):

* rings 0..4 -- hexagonal bullseye finder, ring ``k`` filled with
  ``1 - (k mod 2)`` (bit 1 = dark module; the centre module is DARK
  since spec v0.2);
* ring 5     -- orientation key: all modules light except the first two
  cells of ``hex_ring(5)`` (``(-5, 5)`` and ``(-4, 5)``) which are dark;
* rings 6..rmax -- payload bits in spiral order: header (80 bits,
  unmasked) followed by the masked payload stream; unused tail cells
  are padded with an alternating 0,1,... pattern.

Since spec v0.3 the payload bytes may optionally be zlib-compressed
(header flag bit; ``compress="auto"`` by default, i.e. compressed
whenever that strictly reduces the stored length).
"""

from __future__ import annotations

import zlib

from .geometry import hex_ring, ring_capacity
from .header import (
    BULLSEYE_RINGS,
    DATA_RING0,
    KEY_RING,
    MAX_DATA_BYTES,
    MAX_EC_PCT,
    MAX_RINGS,
    MIN_EC_PCT,
    MODE_BITS,
    bytes_to_bits,
    pack_mode,
    plan_blocks,
)
from .masks import select_mask
from .reedsolomon import rs_encode_msg


def encode(text: str, ec_pct: int = 30, mask_id="auto", min_rings=None,
           compress="auto"):
    """Encode UTF-8 ``text`` into a hexagonal grid.

    Parameters
    ----------
    text : str
        Payload, up to 4095 UTF-8 bytes.
    ec_pct : int
        Error-correction budget as a percentage of data bytes,
        5..90 in steps of 5 (continuous Aztec-style choice).
    mask_id : int | "auto"
        Force a mask (0..7) or let the encoder pick the best.
    min_rings : int | None
        Force a minimum symbol radius (1..31), e.g. for uniform look.
    compress : "auto" | bool
        Payload compression (spec v0.3 header flag).  ``"auto"``
        (default) applies zlib level 9 whenever it strictly reduces
        the stored length; ``True`` forces compression, ``False``
        stores the raw UTF-8 bytes (byte-identical to spec v0.2
        symbols).

    Returns
    -------
    (grid, params)
        ``grid`` maps axial coordinates ``(q, r)`` to 0/1.
        ``params`` is a dict with keys ``rmax``, ``mask``, ``ec``,
        ``blocks`` (list of ``(size, ecc)``), ``data_len`` (stored
        length) and ``compressed``.
    """
    if not MIN_EC_PCT <= ec_pct <= MAX_EC_PCT or ec_pct % 5:
        raise ValueError(
            "ec_pct must be %d..%d in steps of %d"
            % (MIN_EC_PCT, MAX_EC_PCT, 5))
    raw = text.encode("utf-8")
    if len(raw) > MAX_DATA_BYTES:
        raise ValueError(
            "the radius limit supports up to %d bytes of data"
            % MAX_DATA_BYTES)
    compressed = False
    if compress == "auto":
        packed = zlib.compress(raw, 9)
        if len(packed) < len(raw):
            data, compressed = packed, True
        else:
            data = raw
    elif compress is True:
        data, compressed = zlib.compress(raw, 9), True
    elif compress is False:
        data = raw
    else:
        raise ValueError("compress must be 'auto', True or False")
    if len(data) > MAX_DATA_BYTES:
        raise ValueError(
            "the radius limit supports up to %d bytes of data"
            % MAX_DATA_BYTES)
    blocks = plan_blocks(len(data), ec_pct)
    ecc_total = sum(e for _, e in blocks)
    need_bits = MODE_BITS + (len(data) + ecc_total) * 8

    rmax = max(DATA_RING0 + 1, min_rings or 0)
    while ring_capacity(DATA_RING0, rmax) < need_bits:
        rmax += 1
        if rmax > MAX_RINGS:
            raise ValueError("data does not fit (symbol too large)")

    # --- payload (unmasked at this point): data of all blocks in order,
    #     then ECC of all blocks in order.
    payload = []
    pos = 0
    for size, _ in blocks:
        for b in data[pos:pos + size]:
            payload += bytes_to_bits([b])
        pos += size
    pos = 0
    for size, ecc in blocks:
        cw = rs_encode_msg(list(data[pos:pos + size]), ecc)
        payload += bytes_to_bits(cw[size:])
        pos += size
    pad = ring_capacity(DATA_RING0, rmax) - MODE_BITS - len(payload)
    payload += [i % 2 for i in range(pad)]

    # --- mask selection (payload only; the header carries the mask id
    #     and stays unmasked -- same approach as Aztec Code).
    if mask_id == "auto":
        payload, best_mask = select_mask(payload)
    else:
        from .masks import mask_payload
        if not 0 <= mask_id <= 7:
            raise ValueError("mask_id must be 0..7 or 'auto'")
        payload = mask_payload(payload, mask_id)
        best_mask = mask_id

    # --- header with final mask id, then the full bitstream.
    mode = pack_mode(rmax, best_mask, ec_pct, len(blocks), len(data),
                     compressed=compressed)
    bits = bytes_to_bits(mode) + payload

    # --- place modules: bullseye + key + spiral payload.
    data_cells = [c for k in range(DATA_RING0, rmax + 1)
                  for c in hex_ring(k)]
    grid = {}
    for k in range(BULLSEYE_RINGS + 1):
        for c in hex_ring(k):
            grid[c] = 1 - (k % 2)    # centre DARK (v0.2), rings alternate
    for c in hex_ring(KEY_RING):
        grid[c] = 0
    key = hex_ring(KEY_RING)
    grid[key[0]] = 1                 # orientation key cell 1
    grid[key[1]] = 1                 # orientation key cell 2 (adjacent)
    for idx, c in enumerate(data_cells):
        grid[c] = bits[idx] if idx < len(bits) else 0
    return grid, {"rmax": rmax, "mask": best_mask, "ec": ec_pct,
                  "blocks": blocks, "data_len": len(data),
                  "compressed": compressed}
