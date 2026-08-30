"""Conformance tests against the committed JSON vectors.

These vectors are the contract for independent implementations: any
encoder/decoder that matches them behaves identically to the reference
on the covered parameter space.
"""

import hashlib
import json
import os

import pytest

from hexatess import SPEC_VERSION, decode, encode, pack_mode
from test_vectors.generate_vectors import grid_from_hex

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VECTOR_FILE = os.path.join(ROOT, "test_vectors", "vectors_v0.2.json")

with open(VECTOR_FILE, "r", encoding="utf-8") as fh:
    VECTORS = json.load(fh)


def test_spec_version():
    assert VECTORS["spec_version"] == SPEC_VERSION


@pytest.mark.parametrize("case", VECTORS["encode_vectors"],
                         ids=lambda c: c["name"])
def test_encode_vector(case):
    grid, p = encode(case["text"], ec_pct=case["ec_pct"])
    assert p["rmax"] == case["rmax"]
    assert p["mask"] == case["mask"]
    assert p["data_len"] == case["data_len"]
    assert [list(b) for b in p["blocks"]] == case["blocks"]
    mode_hex = bytes(pack_mode(p["rmax"], p["mask"], p["ec"],
                               len(p["blocks"]), p["data_len"])).hex()
    assert mode_hex == case["mode_hex"]
    from test_vectors.generate_vectors import canonical_hex
    gh = canonical_hex(grid, p["rmax"])
    assert hashlib.sha256(gh.encode()).hexdigest() == case["grid_sha256"]
    assert gh == case["grid_hex"]


@pytest.mark.parametrize("case", VECTORS["encode_vectors"],
                         ids=lambda c: c["name"])
def test_decode_reference_grid(case):
    rmax = case["rmax"]
    grid = grid_from_hex(case["grid_hex"], rmax)
    text, _stats = decode(grid)
    assert text == case["text"]


@pytest.mark.parametrize("case", VECTORS["decode_vectors"],
                         ids=lambda c: c["name"])
def test_decode_vector(case):
    # infer rmax from the bit count recorded implicitly: decode derives
    # it from grid extent, so rebuild with the matching encode case rmax
    rmax = None
    if "source_case" in case:
        match = [c for c in VECTORS["encode_vectors"]
                 if c["name"] == case["source_case"]]
        rmax = match[0]["rmax"]
    else:
        match = [c for c in VECTORS["encode_vectors"]
                 if c["text"] == case["expected_text"]]
        rmax = match[0]["rmax"] if match else None
    if rmax is None:
        pytest.skip("cannot infer rmax")
    grid = grid_from_hex(case["grid_hex"], rmax)
    if case.get("expected_failure"):
        with pytest.raises((ValueError, UnicodeDecodeError)):
            decode(grid)
    else:
        text, _ = decode(grid)
        assert text == case["expected_text"]
