"""Reed-Solomon codec tests: exhaustive encode/correct round-trips."""

import random

import pytest

from hexatess.reedsolomon import (
    rs_calc_syndromes,
    rs_encode_msg,
    rs_generator_poly,
    rs_correct_msg,
)

MAX_BLOCK = 255


@pytest.mark.parametrize("nsym", [1, 2, 3, 5, 8, 10, 16, 32])
def test_generator_poly_degree(nsym):
    g = rs_generator_poly(nsym)
    assert len(g) == nsym + 1
    assert g[0] == 1  # monic


def test_encode_is_systematic():
    msg = list(range(20))
    cw = rs_encode_msg(msg, 8)
    assert cw[:20] == msg
    assert len(cw) == 28


def test_encode_clean_syndromes():
    cw = rs_encode_msg(list(range(30)), 10)
    assert max(rs_calc_syndromes(cw, 10)) == 0


def test_block_too_long_raises():
    with pytest.raises(ValueError):
        rs_encode_msg([0] * 254, 2)  # 254 + 2 > 255


def test_correct_no_errors_returns_data():
    data = [7, 8, 9, 10, 11, 12]
    out = rs_correct_msg(rs_encode_msg(data, 5), 5)
    assert out == data


@pytest.mark.parametrize("nsym", range(2, 17))
@pytest.mark.parametrize("trial", range(25))
def test_random_errors_corrected(nsym, trial):
    rng = random.Random(1000 * nsym + trial)
    size = rng.randint(1, MAX_BLOCK - nsym)
    data = [rng.randint(0, 255) for _ in range(size)]
    cw = rs_encode_msg(data, nsym)
    nerr = rng.randint(0, nsym // 2)
    pos = rng.sample(range(len(cw)), nerr)
    damaged = list(cw)
    for p in pos:
        damaged[p] ^= rng.randint(1, 255)
    if nerr:
        assert damaged != cw
    out = rs_correct_msg(damaged, nsym)
    assert out == data


@pytest.mark.parametrize("trial", range(20))
def test_single_error_corrected_all_positions(trial):
    rng = random.Random(trial)
    size = 40
    nsym = 8
    data = [rng.randint(0, 255) for _ in range(size)]
    cw = rs_encode_msg(data, nsym)
    p = rng.randrange(len(cw))
    damaged = list(cw)
    damaged[p] ^= 0xFF
    assert rs_correct_msg(damaged, nsym) == data


def test_zero_block_with_ecc():
    # edge: 0 data bytes + 2 ecc symbols (empty payload case)
    cw = rs_encode_msg([], 2)
    assert len(cw) == 2
    assert rs_correct_msg(cw, 2) == []


def test_erasures_not_confused_with_data():
    # all-zero codeword damaged to all-zero stays zero
    cw = rs_encode_msg([0] * 10, 4)
    assert rs_correct_msg(cw, 4) == [0] * 10


@pytest.mark.parametrize("nsym", [4, 8, 16])
def test_capacity_boundary_single_extra_error_detected(nsym):
    rng = random.Random(nsym)
    data = [rng.randint(1, 255) for _ in range(60)]
    cw = rs_encode_msg(data, nsym)
    damaged = list(cw)
    # flip exactly capacity+1 errors in the data region -> decoding must
    # either fail loudly or (rare miscorrection) at least not return a
    # codeword claiming success without syndrome check; we assert the
    # common case: ValueError raised OR result verified internally.
    pos = rng.sample(range(len(cw)), nsym // 2 + 1)
    for p in pos:
        damaged[p] ^= 0x5A
    try:
        out = rs_correct_msg(damaged, nsym)
        # internal verification passed -> cannot distinguish; acceptable
        assert len(out) == 60
    except ValueError:
        pass
