"""Mask generation and selection tests."""

import pytest

from hexatess.masks import (
    evaluate_mask,
    mask_bit,
    mask_payload,
    select_mask,
)


def test_mask_bit_deterministic():
    assert mask_bit(0, 0) == mask_bit(0, 0)
    assert mask_bit(123, 5) == mask_bit(123, 5)


def test_mask_bit_in_range():
    for i in range(0, 500):
        for m in range(8):
            assert mask_bit(i, m) in (0, 1)


@pytest.mark.parametrize("m", range(8))
def test_mask_streams_differ(m):
    other = (m + 1) % 8
    stream = [mask_bit(i, m) for i in range(64)]
    stream2 = [mask_bit(i, other) for i in range(64)]
    assert stream != stream2


@pytest.mark.parametrize("m", range(8))
def test_mask_payload_is_involution(m):
    payload = [i % 3 for i in range(100)]
    once = mask_payload(payload, m)
    assert mask_payload(once, m) == payload


def test_evaluate_mask_balance_and_repetition():
    # perfectly alternating bits: zero repetition penalty, balance 0/2
    assert evaluate_mask([0, 1, 0, 1, 0, 1]) == 0
    assert evaluate_mask([0, 1, 0, 1]) == 0
    # all equal: heavy repetition penalty (balance 4 + repetition 3)
    assert evaluate_mask([0, 0, 0, 0]) == 4 + 3


def test_select_mask_returns_lowest_on_tie():
    # empty payload -> all masks tie -> mask 0
    masked, m = select_mask([])
    assert masked == [] and m == 0


def test_select_mask_improves_balance():
    payload = [1] * 200          # badly unbalanced unmasked
    masked, _m = select_mask(payload)
    dark = sum(masked)
    assert abs(2 * dark - len(masked)) < abs(2 * 200 - 200)
