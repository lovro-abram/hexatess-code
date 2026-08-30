"""Hexagonal grid geometry for Hexatess Code.

The symbol is a hexagonal lattice of "pointy-top" hexagonal modules.
Module positions use integer *axial coordinates* ``(q, r)``.  Rings are
sets of cells at constant hex distance ``k`` from the origin; the cells
within ring ``k`` total ``6k`` for ``k >= 1`` and the region within
radius ``n`` contains ``3n(n+1) + 1`` cells (centered hexagonal numbers).
"""

from __future__ import annotations

import math

# Neighbour directions in axial coordinates, fixed traversal order.
DIRS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


def hex_ring(k: int):
    """All cells at hex distance ``k`` from the origin, in canonical order.

    The ring starts at cell ``(-k, +k)`` and then takes ``k`` steps in
    each direction of ``DIRS`` in order, appending each visited cell.
    """
    if k == 0:
        return [(0, 0)]
    cells = []
    q, r = -k, k          # start: direction 4 * k
    for d in range(6):
        for _ in range(k):
            cells.append((q, r))
            dq, dr = DIRS[d]
            q += dq
            r += dr
    return cells


def hex_distance(q: int, r: int) -> int:
    """Hex distance of ``(q, r)`` from the origin."""
    return max(abs(q), abs(r), abs(q + r))


def hex_to_pixel(q, r, size):
    """Pointy-top conversion: centre of a module in pixel coordinates.

    ``x = size * sqrt(3) * (q + r/2)``, ``y = size * 1.5 * r``.
    """
    x = size * math.sqrt(3.0) * (q + r / 2.0)
    y = size * 1.5 * r
    return x, y


def hex_corner(cx, cy, size, i):
    """The i-th corner (i = 0..5) of the hexagon centred at (cx, cy).

    Corners lie at angles 60*i - 30 degrees (pointy-top orientation).
    """
    ang = math.pi / 180.0 * (60.0 * i - 30.0)
    return (cx + size * math.cos(ang), cy + size * math.sin(ang))


def ring_capacity(r_from: int, r_to: int) -> int:
    """Number of cells in rings ``r_from .. r_to`` inclusive.

    Uses the centered-hexagonal-number identity:
    cells within radius n = 3n(n+1) + 1.
    """
    if r_to < r_from:
        return 0
    return (3 * r_to * (r_to + 1) + 1) - (3 * (r_from - 1) * r_from + 1)
