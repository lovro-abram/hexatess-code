"""Camera-decoder tests: synthetic render -> photo pipeline -> decode.

These tests are skipped automatically when the optional camera
dependencies (numpy / opencv / scipy) are not installed.
"""

import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("scipy")

import numpy as np  # noqa: E402

from hexatess.camera import decode_image  # noqa: E402
from hexatess.encoder import encode  # noqa: E402
from hexatess.render import render  # noqa: E402


def _render_bytes(text, ec=30, size_px=24):
    """Render a symbol to a BGR array (as a camera would see it)."""
    import tempfile, os
    grid, params = encode(text, ec_pct=ec)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    render(grid, path, size_px=size_px)
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    os.unlink(path)
    return img, params


def test_straight_photo_roundtrip():
    text = "PHOTO-TEST 42"
    img, _ = _render_bytes(text)
    # pad the symbol into a larger "photo" with background noise level
    canvas = np.full((img.shape[0] + 160, img.shape[1] + 160),
                     235, dtype=np.uint8)
    y0, x0 = 80, 80
    canvas[y0:y0 + img.shape[0], x0:x0 + img.shape[1]] = img
    got, st = decode_image(canvas)
    assert got == text
    assert st["finder_hits"] >= 84


def test_rotated_photo_roundtrip():
    text = "Rotation OK!"
    img, _ = _render_bytes(text)
    canvas = np.full((img.shape[0] + 200, img.shape[1] + 200),
                     235, dtype=np.uint8)
    canvas[100:100 + img.shape[0], 100:100 + img.shape[1]] = img
    h, w = canvas.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), 25.0, 1.0)
    rotated = cv2.warpAffine(canvas, M, (w, h),
                             flags=cv2.INTER_CUBIC,
                             borderValue=228)
    got, st = decode_image(rotated)
    assert got == text


def test_scaled_tilted_photo_roundtrip():
    text = "Hexatess camera v3"
    img, _ = _render_bytes(text)
    canvas = np.full((img.shape[0] + 200, img.shape[1] + 200),
                     240, dtype=np.uint8)
    canvas[100:100 + img.shape[0], 100:100 + img.shape[1]] = img
    h, w = canvas.shape
    # mild perspective (keystone) + slight blur, like a phone snapshot
    src = np.float32([[60, 60], [w - 60, 60], [w - 60, h - 60], [60, h - 60]])
    dst = np.float32([[90, 40], [w - 50, 80], [w - 90, h - 50], [50, h - 90]])
    M = cv2.getPerspectiveTransform(src, dst)
    tilted = cv2.warpPerspective(canvas, M, (w, h),
                                 flags=cv2.INTER_CUBIC,
                                 borderValue=232)
    tilted = cv2.GaussianBlur(tilted, (3, 3), 0)
    got, st = decode_image(tilted)
    assert got == text


def test_compressed_payload_photo_roundtrip():
    text = "Hexatess " * 40          # 320 B -> zlib; exercises the
    img, params = _render_bytes(text)   # inflate path of the camera pipe
    assert params["compressed"] is True
    canvas = np.full((img.shape[0] + 200, img.shape[1] + 200),
                     238, dtype=np.uint8)
    canvas[100:100 + img.shape[0], 100:100 + img.shape[1]] = img
    got, st = decode_image(canvas)
    assert got == text
    assert st["compressed"] is True
