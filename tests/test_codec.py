"""End-to-end codec tests: encode -> damage -> decode."""

import random

import pytest

from hexatess import (
    BULLSEYE_RINGS,
    DATA_RING0,
    KEY_RING,
    MAX_DATA_BYTES,
    add_blob_damage,
    add_random_noise,
    decode,
    encode,
    hex_distance,
    hex_ring,
    ring_capacity,
)

TEXTS = [
    "",
    "A",
    "Hello, Hexatess!",
    "ŠČŽĐ življenje je kodiranje",
    "Emoji ok 🐝🐝",
    "X" * 150,  # fits even at EC90 (3 blocks x 95 B <= 350-byte budget)
    "MaxiCode je dokazal koncept; Hexatess koda pa ga ponasa v 21. stoletju.",
]

EC_LEVELS = list(range(5, 95, 5))


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize("ec", [5, 30, 55, 90])
def test_roundtrip(text, ec):
    grid, params = encode(text, ec_pct=ec)
    out, stats = decode(grid)
    assert out == text
    assert stats["data_len"] == len(text.encode("utf-8"))
    assert stats["ec"] == ec


@pytest.mark.parametrize("ec", EC_LEVELS)
def test_roundtrip_all_ec(ec):
    grid, _ = encode("Sestkotna mreza " * 4, ec_pct=ec)
    out, _ = decode(grid)
    assert out == "Sestkotna mreza " * 4


def test_params_consistency():
    grid, params = encode("ABC", ec_pct=30)
    need = 80 + sum((s + e) for s, e in params["blocks"]) * 8
    assert ring_capacity(DATA_RING0, params["rmax"]) >= need
    assert params["rmax"] >= DATA_RING0 + 1
    assert params["data_len"] == 3


def test_grid_is_hexagon():
    grid, params = encode("hex shape", ec_pct=30)
    assert set(grid.keys()) == {
        c for k in range(params["rmax"] + 1) for c in hex_ring(k)}
    assert max(hex_distance(*c) for c in grid) == params["rmax"]


def test_bullseye_pattern():
    grid, params = encode("bullseye", ec_pct=30)
    for k in range(BULLSEYE_RINGS + 1):
        for c in hex_ring(k):
            assert grid[c] == 1 - (k % 2)   # centre DARK (spec v0.2)
    key = hex_ring(KEY_RING)
    for c in key[2:]:
        assert grid[c] == 0
    assert grid[key[0]] == 1 and grid[key[1]] == 1


def test_encoder_deterministic():
    g1, p1 = encode("determinizem", ec_pct=30)
    g2, p2 = encode("determinizem", ec_pct=30)
    assert g1 == g2 and p1 == p2


def test_min_rings_padding():
    g_small, _ = encode("pad", ec_pct=5)
    g_big, p_big = encode("pad", ec_pct=5, min_rings=12)
    assert p_big["rmax"] == 12
    out, _ = decode(g_big)
    assert out == "pad"
    assert len(g_big) > len(g_small)


def test_forced_mask_roundtrip():
    for m in range(8):
        grid, params = encode("maska %d" % m, ec_pct=30, mask_id=m)
        assert params["mask"] == m
        out, _ = decode(grid)
        assert out == "maska %d" % m


def test_invalid_ec_rejected():
    for ec in (0, 4, 6, 92, 100, -5):
        with pytest.raises(ValueError):
            encode("x", ec_pct=ec)


def test_too_much_data_rejected():
    with pytest.raises(ValueError):
        encode("y" * (MAX_DATA_BYTES + 1))


def test_random_noise_within_tolerance():
    # measured survival (100 trials, seed 42): 68% at 2% noise, EC55
    # -> floor well below measurement to stay robust
    text = "noise tolerance check"
    grid, params = encode(text, ec_pct=55)
    rng = random.Random(7)
    ok = 0
    for _ in range(40):
        g2 = add_random_noise(grid, params, 0.02, rng)
        try:
            t2, _ = decode(g2)
            ok += (t2 == text)
        except (ValueError, UnicodeDecodeError):
            pass
    assert ok >= 20, "survival unexpectedly low: %d/40" % ok


def test_blob_damage_high_survival():
    # measured survival (100 trials, seed 42): 51% at 10% blob, EC90
    text = "blob damage check"
    grid, params = encode(text, ec_pct=90)
    rng = random.Random(11)
    ok = 0
    for _ in range(30):
        g2, _blob = add_blob_damage(grid, params, 0.10, rng)
        try:
            t2, _ = decode(g2)
            ok += (t2 == text)
        except (ValueError, UnicodeDecodeError):
            pass
    assert ok >= 10, "blob survival unexpectedly low: %d/30" % ok


def test_decode_empty_payload():
    grid, _ = encode("", ec_pct=5)
    out, stats = decode(grid)
    assert out == "" and stats["data_len"] == 0
