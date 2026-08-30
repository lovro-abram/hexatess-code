"""Hexagonal geometry tests: rings, distances, capacity, pixel mapping."""

import math

import pytest

from hexatess.geometry import (
    DIRS,
    hex_corner,
    hex_distance,
    hex_ring,
    hex_to_pixel,
    ring_capacity,
)


@pytest.mark.parametrize("k", range(0, 12))
def test_ring_size(k):
    expected = 1 if k == 0 else 6 * k
    assert len(hex_ring(k)) == expected


@pytest.mark.parametrize("k", range(0, 12))
def test_ring_all_at_distance_k(k):
    assert all(hex_distance(q, r) == k for q, r in hex_ring(k))


@pytest.mark.parametrize("k", range(1, 12))
def test_ring_cells_unique(k):
    cells = hex_ring(k)
    assert len(set(cells)) == len(cells)


@pytest.mark.parametrize("k", range(1, 12))
def test_ring_starts_at_minus_k_plus_k(k):
    assert hex_ring(k)[0] == (-k, k)


@pytest.mark.parametrize("k", range(1, 10))
def test_ring_is_closed_cycle(k):
    cells = hex_ring(k)
    # consecutive cells must be neighbours
    for (q1, r1), (q2, r2) in zip(cells, cells[1:] + cells[:1]):
        dq, dr = q2 - q1, r2 - r1
        assert (dq, dr) in DIRS


def test_distance_axis_points():
    assert hex_distance(0, 0) == 0
    assert hex_distance(5, 0) == 5
    assert hex_distance(0, 5) == 5
    assert hex_distance(3, 3) == 6
    assert hex_distance(-4, -2) == 6


@pytest.mark.parametrize("n", range(0, 20))
def test_capacity_centered_hex_numbers(n):
    assert 3 * n * (n + 1) + 1 == sum(len(hex_ring(k)) for k in range(n + 1))


def test_ring_capacity_single_ring():
    # NOTE: the helper is defined for r_from >= 1 (payload region usage);
    # ring 0 (the centre cell) is excluded by the radius identity.
    assert ring_capacity(1, 1) == 6
    assert ring_capacity(3, 3) == 18
    assert ring_capacity(6, 6) == 36


def test_ring_capacity_range_identity():
    # capacity over a range equals sum of individual rings
    assert ring_capacity(6, 10) == sum(ring_capacity(k, k)
                                       for k in range(6, 11))


def test_ring_capacity_empty_range():
    assert ring_capacity(8, 3) == 0


def test_hex_to_pixel_origin():
    x, y = hex_to_pixel(0, 0, 10)
    assert x == 0 and y == 0


def test_hex_to_pixel_axes():
    s = 10.0
    x, y = hex_to_pixel(1, 0, s)
    assert abs(x - s * math.sqrt(3)) < 1e-9 and y == 0
    x, y = hex_to_pixel(0, 1, s)
    assert abs(x - s * math.sqrt(3) / 2) < 1e-9
    assert abs(y - 1.5 * s) < 1e-9


def test_hex_corner_count_and_radius():
    pts = [hex_corner(5.0, -3.0, 7.0, i) for i in range(6)]
    for px, py in pts:
        assert abs(math.hypot(px - 5.0, py + 3.0) - 7.0) < 1e-9


def test_hex_corner_pointy_top():
    # corner 0 at angle -30 deg -> above horizontal (pointy top)
    px, py = hex_corner(0.0, 0.0, 1.0, 0)
    assert abs(px - math.cos(math.radians(-30))) < 1e-9
    assert abs(py - math.sin(math.radians(-30))) < 1e-9
