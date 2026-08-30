"""Unit tests for GF(256) arithmetic."""

import pytest

from hexatess.galois import (
    GF_EXP,
    GF_LOG,
    PRIMITIVE_POLY,
    gf_div,
    gf_inv,
    gf_mul,
    gf_poly_add,
    gf_poly_eval,
    gf_poly_mul,
    gf_poly_scale,
)

SOME_VALUES = [0, 1, 2, 3, 5, 17, 64, 127, 128, 199, 254, 255]


def test_primitive_polynomial_constant():
    assert PRIMITIVE_POLY == 0x11D


def test_tables_sizes():
    assert len(GF_LOG) == 256
    assert len(GF_EXP) == 512


def test_exp_log_roundtrip():
    for x in range(1, 256):
        assert GF_EXP[GF_LOG[x]] == x


def test_generator_is_two():
    assert GF_EXP[0] == 1
    assert GF_EXP[1] == 2
    assert GF_EXP[8] == 0x11D ^ 0x100  # reduction of x^8


@pytest.mark.parametrize("x", SOME_VALUES)
@pytest.mark.parametrize("y", SOME_VALUES)
def test_mul_commutative(x, y):
    assert gf_mul(x, y) == gf_mul(y, x)


@pytest.mark.parametrize("x", [1, 2, 3, 7, 17, 128, 255])
def test_mul_identity(x):
    assert gf_mul(x, 1) == x


@pytest.mark.parametrize("x", SOME_VALUES)
@pytest.mark.parametrize("y", SOME_VALUES)
def test_div_mul_roundtrip(x, y):
    if y == 0:
        return
    if x == 0:
        assert gf_div(x, y) == 0
        return
    q = gf_div(x, y)
    assert gf_mul(q, y) == x


@pytest.mark.parametrize("x", [1, 2, 3, 7, 17, 128, 255])
def test_inv_roundtrip(x):
    assert gf_mul(x, gf_inv(x)) == 1


def test_div_by_zero_raises():
    with pytest.raises(ZeroDivisionError):
        gf_div(1, 0)


def test_mul_by_zero():
    assert gf_mul(0, 123) == 0
    assert gf_mul(123, 0) == 0


@pytest.mark.parametrize("p", [[], [1], [1, 2, 3], [7, 0, 5, 200]])
@pytest.mark.parametrize("x", SOME_VALUES)
def test_poly_eval_scale_zero(p, x):
    # p(x) - x*p(x) evaluated via add/scale consistency at x=0 coefficient
    scaled = gf_poly_scale(p, x)
    assert len(scaled) == len(p)


def test_poly_add_alignment():
    # (x^2 + 1) + (x) = x^2 + x + 1  ([1, 0] is x in descending order)
    assert gf_poly_add([1, 0, 1], [1, 0]) == [1, 1, 1]


def test_poly_add_cancels():
    assert all(c == 0 for c in gf_poly_add([1, 2, 3], [1, 2, 3]))


def test_poly_mul_by_one():
    assert gf_poly_mul([1, 2, 3], [1]) == [1, 2, 3]


def test_poly_mul_distribution():
    # (x + 1)(x + alpha) with alpha = 2: x^2 + 3x + 2
    assert gf_poly_mul([1, 1], [1, 2]) == [1, 3, 2]


@pytest.mark.parametrize("p", [[1], [1, 1], [1, 2, 3, 4], [5, 0, 9]])
def test_eval_homogeneous(p):
    # p(a) * b == (b*p)(a)
    a, b = 37, 91
    lhs = gf_mul(gf_poly_eval(p, a), b)
    rhs = gf_poly_eval(gf_poly_scale(p, b), a)
    assert lhs == rhs
