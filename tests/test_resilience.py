"""Robustness smoke tests (fast subset of the full resilience suite)."""

import random

import pytest

from hexatess import (
    add_blob_damage,
    add_random_noise,
    decode,
    encode,
)

TEXT = "Hexatess Code - hexagonal 2D code with EC. "


@pytest.mark.parametrize("ec", [30, 50, 90])
def test_clean_roundtrip(ec):
    grid, _ = encode(TEXT, ec_pct=ec)
    out, _ = decode(grid)
    assert out == TEXT


def test_noise_survival_matches_reference_stats():
    """Seed-42 statistics must stay close to the published reference
    numbers: EC30 @1% noise -> ~85%, EC30 @2% -> ~23% (100 trials).
    Floors sit well below measurement for robustness.
    """
    grid, params = encode(TEXT, ec_pct=30)
    rng = random.Random(42)
    for p, floor in ((0.01, 0.75), (0.02, 0.10)):
        ok = 0
        trials = 30
        for _ in range(trials):
            g2 = add_random_noise(grid, params, p, rng)
            try:
                t2, _ = decode(g2)
                ok += (t2 == TEXT)
            except (ValueError, UnicodeDecodeError):
                pass
        assert ok / trials >= floor, "noise %.0f%%: %d/%d < %.0f%%" % (
            p * 100, ok, trials, floor * 100)


def test_blob_damage_beats_noise():
    """Blob (smudge) damage must survive far higher area fractions than
    uniform noise at the same EC, because damage clusters inside whole
    RS symbols.  Measured (seed 42, 100 trials): blob 10% @ EC90 -> 56%,
    while uniform noise at 10% is far beyond the ~EC/16% tolerance and
    essentially never decodes."""
    grid, params = encode(TEXT, ec_pct=90)
    rng = random.Random(42)
    ok = 0
    trials = 20
    for _ in range(trials):
        g2, _blob = add_blob_damage(grid, params, 0.10, rng)
        try:
            t2, _ = decode(g2)
            ok += (t2 == TEXT)
        except (ValueError, UnicodeDecodeError):
            pass
    assert ok / trials >= 0.35

    ok_noise = 0
    for _ in range(trials):
        g2 = add_random_noise(grid, params, 0.10, rng)
        try:
            t2, _ = decode(g2)
            ok_noise += (t2 == TEXT)
        except (ValueError, UnicodeDecodeError):
            pass
    assert ok_noise == 0
