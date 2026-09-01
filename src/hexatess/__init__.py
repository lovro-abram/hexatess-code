"""Hexatess Code - an experimental 2D barcode on a hexagonal grid.

Reference implementation of specification v0.3.  The symbol is a
hexagonal lattice with a hexagonal bullseye finder, an
orientation key ring, spiral serialization from the centre outwards,
a Reed-Solomon protected header and a continuously selectable
error-correction budget of 5-90 percent (Aztec-style).  Since spec
v0.3 the payload can optionally be zlib-compressed (one header flag
bit; applied automatically whenever it saves space).

Quick start
-----------
>>> from hexatess import encode, decode, render
>>> grid, params = encode("Hello, Hexatess!", ec_pct=30)
>>> params["rmax"], params["mask"], params["data_len"]
(11, 6, 16)
>>> render(grid, "hello.png")
'hello.png'
>>> decode(grid)[0]
'Hello, Hexatess!'

See SPECIFICATION.md in the repository for the full format
specification, and test_vectors/vectors_v0.3.json for conformance
data usable by independent implementations.
"""

from __future__ import annotations

from .decoder import decode, payload_to_text
from .encoder import encode
from .geometry import (
    DIRS,
    hex_corner,
    hex_distance,
    hex_ring,
    hex_to_pixel,
    ring_capacity,
)
from .header import (
    BULLSEYE_RINGS,
    BLOCK_DATA_MAX,
    COMPRESSED_FLAG,
    DATA_RING0,
    KEY_RING,
    MAX_DATA_BYTES,
    MAX_EC_PCT,
    MAX_RINGS,
    MIN_EC_PCT,
    MODE_BITS,
    MODE_BYTES,
    MODE_ECC,
    bits_to_bytes,
    bytes_to_bits,
    pack_mode,
    plan_blocks,
    unpack_mode,
    unpack_mode_ex,
)
from .masks import evaluate_mask, mask_bit, mask_payload, select_mask
from .reedsolomon import rs_correct_msg, rs_encode_msg
from .render import render, sample_grid_from_image
from .resilience import add_blob_damage, add_random_noise, run_tests

__version__ = "0.3.1"
SPEC_VERSION = "0.3"

__all__ = [
    # high-level API
    "encode", "decode", "render", "sample_grid_from_image",
    "run_tests", "add_random_noise", "add_blob_damage",
    # geometry
    "DIRS", "hex_ring", "hex_distance", "hex_to_pixel", "hex_corner",
    "ring_capacity",
    # framing
    "bytes_to_bits", "bits_to_bytes", "pack_mode", "unpack_mode",
    "unpack_mode_ex", "plan_blocks", "payload_to_text",
    # masks
    "mask_bit", "mask_payload", "evaluate_mask", "select_mask",
    # error correction
    "rs_encode_msg", "rs_correct_msg",
    # constants
    "BULLSEYE_RINGS", "KEY_RING", "DATA_RING0", "MAX_RINGS",
    "BLOCK_DATA_MAX", "MODE_BYTES", "MODE_ECC", "MODE_BITS",
    "MIN_EC_PCT", "MAX_EC_PCT", "MAX_DATA_BYTES", "COMPRESSED_FLAG",
    # meta
    "__version__", "SPEC_VERSION",
]
