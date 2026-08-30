"""Rendering tests: PNG render + ideal re-sampling round-trips."""

import os

import pytest

from hexatess import decode, encode, render, sample_grid_from_image

HAS_PIL = True
try:
    import PIL  # noqa: F401
except ImportError:
    HAS_PIL = False

pytestmark = pytest.mark.skipif(not HAS_PIL,
                                reason="Pillow not installed")

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "_output")


@pytest.fixture(scope="module")
def out_dir():
    os.makedirs(OUT_DIR, exist_ok=True)
    yield OUT_DIR


@pytest.mark.parametrize("size", [10, 18, 24])
@pytest.mark.parametrize("ec", [5, 30, 90])
def test_render_selfdecode(tmp_path, size, ec):
    text = "Render round-trip %d/%d" % (size, ec)
    grid, params = encode(text, ec_pct=ec)
    path = str(tmp_path / ("k_%d_%d.png" % (size, ec)))
    assert render(grid, path, size_px=size) == path
    assert os.path.exists(path)
    grid2 = sample_grid_from_image(path, params["rmax"], size_px=size)
    out, _ = decode(grid2)
    assert out == text


def test_render_dimensions_grow_with_rings(tmp_path):
    g_small, p_small = encode("tiny", ec_pct=5)
    g_big, _ = encode("tiny", ec_pct=5, min_rings=14)
    p1 = str(tmp_path / "small.png")
    p2 = str(tmp_path / "big.png")
    render(g_small, p1)
    render(g_big, p2)
    from PIL import Image
    s = Image.open(p1).size
    b = Image.open(p2).size
    assert b[0] > s[0] and b[1] > s[1]


def test_render_colors(tmp_path):
    grid, _ = encode("color", ec_pct=30)
    path = str(tmp_path / "color.png")
    render(grid, path, dark=(0, 0, 0), light=(255, 255, 255))
    from PIL import Image
    img = Image.open(path).convert("RGB")
    colors = set(img.getcolors(maxcolors=1 << 24))
    # supersampled edges introduce intermediate colours; but pure black
    # and pure white must both be present
    assert (0, 0, 0) in {c for _, c in colors}
    assert (255, 255, 255) in {c for _, c in colors}


def test_sample_matches_encoder_grid(tmp_path):
    text = "identity"
    grid, params = encode(text, ec_pct=30)
    path = str(tmp_path / "identity.png")
    render(grid, path)
    grid2 = sample_grid_from_image(path, params["rmax"])
    assert grid2 == grid
