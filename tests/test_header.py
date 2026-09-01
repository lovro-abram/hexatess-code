"""Header (mode message) and framing tests."""

import pytest

from hexatess.header import (
    COMPRESSED_FLAG,
    MODE_BITS,
    MODE_ECC,
    MODE_BYTES,
    bits_to_bytes,
    bytes_to_bits,
    pack_mode,
    plan_blocks,
    unpack_mode,
    unpack_mode_ex,
)
from hexatess.reedsolomon import rs_calc_syndromes


@pytest.mark.parametrize("data", [b"", b"\x00", b"\xff", b"Hello", bytes(range(256))])
def test_bit_helpers_roundtrip(data):
    assert bits_to_bytes(bytes_to_bits(data)) == data


def test_bits_msb_first():
    assert bytes_to_bits([0b10100000])[:3] == [1, 0, 1]


def test_mode_bits_constant():
    assert MODE_BITS == (MODE_BYTES + MODE_ECC) * 8 == 80


@pytest.mark.parametrize("rmax", [7, 9, 15, 31])
@pytest.mark.parametrize("mask", range(8))
@pytest.mark.parametrize("ec", [5, 30, 55, 90])
@pytest.mark.parametrize("bc", [1, 3, 255])
@pytest.mark.parametrize("dl", [0, 1, 2, 4095])
def test_pack_unpack_roundtrip(rmax, mask, ec, bc, dl):
    mode = pack_mode(rmax, mask, ec, bc, dl)
    assert len(mode) == 10
    assert unpack_mode(mode) == (rmax, mask, ec, bc, dl)
    assert unpack_mode_ex(mode) == (rmax, mask, ec, bc, dl, False)


# ---------------------------------------------------------------- v0.3
# compression flag (byte 4, bit 6)

def test_compressed_flag_roundtrip():
    mode = pack_mode(13, 5, 30, 1, 203, compressed=True)
    assert mode[4] & COMPRESSED_FLAG
    assert unpack_mode_ex(mode) == (13, 5, 30, 1, 203, True)
    # legacy 5-tuple view ignores the flag
    assert unpack_mode(mode) == (13, 5, 30, 1, 203)


def test_uncompressed_padding_zero():
    assert pack_mode(31, 7, 90, 255, 4094)[4] == 0x00
    assert pack_mode(31, 7, 90, 255, 4095)[4] == 0x80


def test_compressed_padding_zero():
    assert pack_mode(10, 0, 5, 1, 0, compressed=True)[4] == COMPRESSED_FLAG
    assert pack_mode(10, 0, 5, 1, 1, compressed=True)[4] \
        == 0x80 | COMPRESSED_FLAG


def test_v02_symbol_is_valid_v03():
    # a v0.2 header (zero padding) must read as uncompressed in v0.3
    for dl in (0, 1, 17, 4095):
        mode = pack_mode(9, 2, 30, 1, dl)
        assert unpack_mode_ex(mode)[5] is False


def test_mode_has_clean_syndromes():
    mode = pack_mode(9, 3, 30, 1, 17)
    assert max(rs_calc_syndromes(list(mode), MODE_ECC)) == 0


def test_pack_out_of_range_raises():
    with pytest.raises(ValueError):
        pack_mode(32, 0, 30, 1, 1)      # rmax too big
    with pytest.raises(ValueError):
        pack_mode(7, 8, 30, 1, 1)       # mask too big
    with pytest.raises(ValueError):
        pack_mode(7, 0, 31, 1, 1)       # ec not multiple of 5
    with pytest.raises(ValueError):
        pack_mode(7, 0, 160, 1, 1)      # ec/5 exceeds 5-bit field (32 > 31)
    with pytest.raises(ValueError):
        pack_mode(7, 0, 30, 256, 1)     # too many blocks
    with pytest.raises(ValueError):
        pack_mode(7, 0, 30, 1, 4096)    # length overflow


@pytest.mark.parametrize("dl,ec", [(0, 30), (1, 5), (49, 90), (50, 30),
                                   (51, 30), (100, 90), (4095, 5)])
def test_plan_blocks_covers_all_bytes(dl, ec):
    blocks = plan_blocks(dl, ec)
    assert sum(s for s, _ in blocks) == dl
    assert all(s <= 50 for s, _ in blocks)
    assert all(e >= 2 for _, e in blocks)
    assert all(s + e <= 255 for s, e in blocks)


def test_plan_blocks_empty():
    assert plan_blocks(0, 30) == [(0, 2)]


def test_plan_blocks_min_ec_monotone():
    # higher EC never yields less ECC for same size
    b30 = plan_blocks(120, 30)
    b90 = plan_blocks(120, 90)
    assert sum(e for _, e in b90) >= sum(e for _, e in b30)


@pytest.mark.parametrize("dl", [30, 60, 61, 100, 123])
def test_plan_blocks_uses_minimum_block_count(dl):
    import math
    expected_bc = max(1, math.ceil(dl / 50))
    assert len(plan_blocks(dl, 30)) == expected_bc
