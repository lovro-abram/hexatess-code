#!/usr/bin/env python3
"""Generate / verify conformance test vectors for Hexatess Code v0.3.

The committed file ``vectors_v0.3.json`` lets independent implementations
(any language) verify conformance to specification v0.3:

* ``encode_vectors`` -- fixed inputs (text, ec_pct) with the expected
  symbol parameters, protected mode message and the full canonical grid
  serialization;
* ``decode_vectors`` -- fixed grids (including deterministically damaged
  ones) with the expected decode result.

Canonical grid serialization
    Bits are taken in symbol order: ring 0 first, then rings 1..rmax;
    within a ring, cells follow ``hex_ring(k)`` canonical order.  Bits
    are packed MSB-first into bytes; the final partial byte is padded
    with zero bits on the right; bytes are written as lowercase hex.

Usage
-----
    python test_vectors/generate_vectors.py --write    # regenerate file
    python test_vectors/generate_vectors.py --verify   # CI self-check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hexatess import (                      # noqa: E402
    SPEC_VERSION,
    __version__,
    decode,
    encode,
    hex_ring,
)

HERE = os.path.dirname(os.path.abspath(__file__))
VECTOR_FILE = os.path.join(HERE, "vectors_v0.3.json")

GENERATED = "2026-09-01"


def _incompressible(n):
    """Deterministic, aperiodic, effectively incompressible ASCII text."""
    return "".join(chr(33 + hashlib.sha256(str(i).encode()).digest()[0] % 94)
                   for i in range(n))


_LOREM = ("Hexatess Code je eksperimentalna dvodimenzionalna koda na "
          "sestkotni mrezi: sestkotni iskalnik, orientacijski obroc, "
          "spiralna serializacija in Reed-Solomon popravki napak. "
          "Ker so moduli sestkotniki, je gostota informacij visja kot "
          "pri kvadratnih mrezah, simbol pa je blizu izotropen. " * 3)

# (name, text, ec_pct, compress) -----------------------------------------
ENCODE_CASES = [
    ("empty", "", 5, "auto"),
    ("one_byte", "A", 5, "auto"),
    ("hello", "Hello, Hexatess!", 30, "auto"),
    ("utf8_slo", "ŠČŽ življenje je kodiranje", 30, "auto"),
    ("utf8_emoji", "bee \U0001F41D hive", 50, "auto"),
    ("mid", "Hexatess Code v0.2 reference vector", 55, "auto"),
    ("digits", "1234567890" * 8, 10, "auto"),
    ("url", "https://example.org/hexatess", 25, "auto"),
    ("min_ec", "compact", 5, "auto"),
    ("max_ec", "resilience", 90, "auto"),
    ("long_multiblock", "X" * 250, 30, "auto"),
    ("max_capacity", _incompressible(329), 5, False),
    ("long_text_zlib", _LOREM, 30, "auto"),
]

# (name, encode-case, [(spiral_index, xor_value), ...]) -------------------
# Spiral indices refer to the data region (ring 6..) of the SOURCE case.
DAMAGE_CASES = [
    # 3 flips on a 17-byte payload with 6 ECC symbols (capacity 3)
    ("damaged_correctable", "hello",
     [(100, 0xFF), (140, 0x5A), (180, 0xA5)]),
    # 6 flips on 35-byte payload with 19 ECC symbols (capacity 9)
    ("damaged_heavy", "mid",
     [(50, 0x01), (80, 0x7F), (110, 0x80), (140, 0xFF),
      (170, 0x33), (200, 0xCC)]),
    # 8 flips on a 1-byte payload with 2 ECC symbols -> decode fails
    ("damaged_uncorrectable", "one_byte",
     [(10, 0xFF), (20, 0x81), (30, 0x42), (40, 0x17),
      (50, 0xC3), (60, 0x66), (70, 0x9D), (80, 0xE0)]),
]


def canonical_bits(grid, rmax):
    bits = []
    for k in range(rmax + 1):
        for (q, r) in hex_ring(k):
            bits.append(grid.get((q, r), 0))
    return bits


def canonical_hex(grid, rmax):
    bits = canonical_bits(grid, rmax)
    out = []
    for i in range(0, len(bits), 8):
        chunk = bits[i:i + 8]
        while len(chunk) < 8:
            chunk.append(0)
        v = 0
        for b in chunk:
            v = (v << 1) | b
        out.append(v)
    return bytes(out).hex()


def grid_from_hex(hexstr, rmax):
    raw = bytes.fromhex(hexstr)
    bits = []
    for byte in raw:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    grid = {}
    idx = 0
    for k in range(rmax + 1):
        for (q, r) in hex_ring(k):
            grid[(q, r)] = bits[idx] if idx < len(bits) else 0
            idx += 1
    return grid


def flip_cells(grid, rmax, flips):
    """Flip grid cells identified by spiral index (data region, ring 6+)."""
    data_cells = [c for k in range(6, rmax + 1) for c in hex_ring(k)]
    g = dict(grid)
    for idx, xor in flips:
        q, r = data_cells[idx]
        g[(q, r)] ^= xor & 1
    return g


def build_vectors():
    encode_vectors = []
    grids = {}
    for name, text, ec, comp in ENCODE_CASES:
        grid, p = encode(text, ec_pct=ec, compress=comp)
        assert decode(grid)[0] == text
        mode_hex = "".join("")  # placeholder, filled below
        from hexatess import pack_mode
        mode_hex = bytes(pack_mode(p["rmax"], p["mask"], p["ec"],
                                   len(p["blocks"]), p["data_len"],
                                   compressed=p["compressed"])).hex()
        gh = canonical_hex(grid, p["rmax"])
        grids[name] = (grid, p)
        encode_vectors.append({
            "name": name,
            "text": text,
            "ec_pct": ec,
            "compress_mode": comp,
            "data_len": p["data_len"],
            "compressed": p["compressed"],
            "rmax": p["rmax"],
            "mask": p["mask"],
            "blocks": [list(b) for b in p["blocks"]],
            "mode_hex": mode_hex,
            "grid_sha256": hashlib.sha256(gh.encode()).hexdigest(),
            "grid_hex": gh,
        })

    decode_vectors = []
    for name, case, flips in DAMAGE_CASES:
        grid, p = grids[case]
        damaged = flip_cells(grid, p["rmax"], flips)
        try:
            text, _ = decode(damaged)
            entry = {"name": name, "source_case": case,
                     "flipped_cells_spiral_index": [f[0] for f in flips],
                     "grid_hex": canonical_hex(damaged, p["rmax"]),
                     "expected_text": text}
        except (ValueError, UnicodeDecodeError):
            entry = {"name": name, "source_case": case,
                     "flipped_cells_spiral_index": [f[0] for f in flips],
                     "grid_hex": canonical_hex(damaged, p["rmax"]),
                     "expected_failure": True}
        decode_vectors.append(entry)
    # undamaged decode references for the three smallest symbols
    for name in ("empty", "one_byte", "hello"):
        grid, p = grids[name]
        decode_vectors.append({
            "name": "plain_" + name,
            "grid_hex": canonical_hex(grid, p["rmax"]),
            "expected_text": ENCODE_CASES[
                [c[0] for c in ENCODE_CASES].index(name)][1],
        })

    return {
        "spec_version": SPEC_VERSION,
        "generator": "hexatess-code %s" % __version__,
        "generated": GENERATED,
        "field": {"primitive_poly": "0x11D", "generator_alpha": 2},
        "canonical_serialization": (
            "bits ordered by ring 0..rmax, cells in hex_ring(k) canonical "
            "order, packed MSB-first, right-padded with zeros to a byte "
            "boundary, lowercase hex"),
        "encode_vectors": encode_vectors,
        "decode_vectors": decode_vectors,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="write vectors_v0.3.json")
    ap.add_argument("--verify", action="store_true",
                    help="verify committed vectors against the library")
    args = ap.parse_args(argv)

    vectors = build_vectors()
    if args.write:
        with open(VECTOR_FILE, "w", encoding="utf-8") as fh:
            json.dump(vectors, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print("wrote %s (%d encode, %d decode vectors)"
              % (VECTOR_FILE, len(vectors["encode_vectors"]),
                 len(vectors["decode_vectors"])))
    if args.verify or not args.write:
        with open(VECTOR_FILE, "r", encoding="utf-8") as fh:
            committed = json.load(fh)
        if committed != vectors:
            print("MISMATCH: committed vectors differ from library output")
            return 1
        print("conformance vectors verified OK (%d encode, %d decode)"
              % (len(vectors["encode_vectors"]),
                 len(vectors["decode_vectors"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
