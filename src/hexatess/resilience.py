"""Robustness self-tests: random noise and blob (smudge) damage."""

from __future__ import annotations

import random

from .decoder import decode
from .encoder import encode
from .geometry import hex_distance, hex_ring


def data_cell_list(rmax):
    """All payload cells from ring DATA_RING0 to ``rmax`` in spiral order."""
    from .header import DATA_RING0
    return [c for k in range(DATA_RING0, rmax + 1) for c in hex_ring(k)]


def add_random_noise(grid, params, p, rng):
    """Flip each payload cell independently with probability ``p``."""
    rmax = params["rmax"]
    g = dict(grid)
    for c in data_cell_list(rmax):
        if rng.random() < p:
            g[c] ^= 1
    return g


def add_blob_damage(grid, params, target_frac, rng):
    """Smudge damage: set all cells within radius ``d`` of a random
    payload cell to 0, growing ``d`` until ~``target_frac`` of payload
    cells are covered.  Returns ``(grid, blob_size)``."""
    rmax = params["rmax"]
    data_cells = data_cell_list(rmax)
    total = len(data_cells)
    d = 1
    while True:
        seed = rng.choice(data_cells)
        blob = [c for c in data_cells
                if hex_distance(c[0] - seed[0], c[1] - seed[1]) <= d]
        if len(blob) >= total * target_frac or d > rmax:
            break
        d += 1
    g = dict(grid)
    for c in blob:
        g[c] = 0
    return g, len(blob)


def run_tests(text="Hexatess Code - hexagonal 2D code with EC. ",
              trials=30, seed=42, verbose=True):
    """Round-trip plus random-noise and blob-damage survival statistics.

    Physical note: one flipped module is one RS *symbol* error, so the
    theoretical tolerance to uniformly random noise is roughly
    ``ec_pct / 16`` percent of modules; blob damage survives much higher
    area fractions because flips cluster inside whole bytes.
    """
    rng = random.Random(seed)
    results = []
    for ec in (30, 50, 90):
        grid, params = encode(text, ec_pct=ec, mask_id="auto")
        t, _ = decode(grid)
        assert t == text, "round-trip failed at EC=%d" % ec
        for p in (0.01, 0.02, 0.03, 0.05):
            ok = 0
            for _ in range(trials):
                g2 = add_random_noise(grid, params, p, rng)
                try:
                    t2, _ = decode(g2)
                    ok += (t2 == text)
                except (ValueError, UnicodeDecodeError):
                    pass
            results.append(("noise %.0f%%" % (p * 100), ec, ok, trials))
        for frac in (0.05, 0.10, 0.15, 0.20):
            ok = 0
            for _ in range(trials):
                g2, _blob = add_blob_damage(grid, params, frac, rng)
                try:
                    t2, _ = decode(g2)
                    ok += (t2 == text)
                except (ValueError, UnicodeDecodeError):
                    pass
            results.append(("blob %.0f%%" % (frac * 100), ec, ok, trials))
    if verbose:
        print("=" * 56)
        print("ROBUSTNESS TESTS (%d trials per setting, seed=%d)"
              % (trials, seed))
        print("payload: %d bytes; random-noise tolerance ~ EC/16%%"
              % len(text.encode("utf-8")))
        print("=" * 56)
        print("%-14s %-6s %s" % ("damage", "EC%", "survival"))
        for name, ec, ok, n in results:
            print("%-14s %-6d %s  (%d/%d)"
                  % (name, ec, "%.0f%%" % (100.0 * ok / n), ok, n))
    return results
