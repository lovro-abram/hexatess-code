"""Camera decoder — read Hexatess Code symbols from real photographs.

This module turns a photo of a printed or displayed symbol back into
the encoded text.  It is an *optional* component: the core library
stays Pillow-only, while the camera pipeline needs numpy, OpenCV and
SciPy.  Install them with::

    pip install hexatess-code[camera]

Pipeline overview
-----------------
1.  Grayscale + downscale + illumination-gradient removal (local
    division by a heavily blurred background), Otsu binarization.
2.  Connected components -> bullseye candidates.  Because prints tend
    to merge finder rings into one blob, each blob is tested under
    several cell-count hypotheses (1, 6, ... 48 cells) before the
    radial dark/light profile is scored.
3.  Joint rotation x scale refinement of the finder pose (the finder
    is 60-degree symmetric, so the full circle is swept), followed by
    a Nelder-Mead fit of a full homography on the 91 known finder
    cells (rings 0-5, including the two-cell orientation key).
4.  Model-frame disambiguation: the key arc is only 2 of 91 cells and
    does not reliably pin the canonical frame, so the first 80 data
    cells are sampled under all 6 candidate 60-degree model rotations
    and the RS(5,5)-protected header acts as the judge (a false
    positive is ~1e-12 likely).
5.  Local (adaptive) threshold sampling of the data region, robust to
    illumination gradients, glare and curled prints.
6.  Once the header passes RS, 91 + 80 = 171 cells are *known*; a
    second-order polynomial correction field is fitted to them by
    coordinate descent on a soft margin.  This absorbs the residual
    warp of curled foil that a homography cannot express.
7.  Full grid sample, unmask, RS-decode.  For strong perspective
    (steep camera angles) an annulus-ICP / affine fallback chain is
    used when the fast path fails.

Example
-------
>>> from hexatess.camera import decode_photo      # doctest: +SKIP
>>> text, stats = decode_photo("photo.jpg")       # doctest: +SKIP
>>> text                                          # doctest: +SKIP
'Hello, Hexatess!'
"""

from __future__ import annotations

import math
import os
import time
from itertools import combinations

try:
    import cv2
    import numpy as np
    from scipy.optimize import minimize
    from scipy.spatial import cKDTree
except ImportError as _exc:  # pragma: no cover - depends on env
    raise ImportError(
        "hexatess.camera needs the optional camera dependencies. "
        "Install them with:  pip install hexatess-code[camera] "
        "(numpy, opencv-python, scipy)"
    ) from _exc

from .decoder import decode, payload_to_text
from .geometry import hex_to_pixel, hex_ring, ring_capacity
from .header import DATA_RING0, MAX_RINGS, MODE_BITS, bits_to_bytes, \
    plan_blocks, unpack_mode_ex
from .masks import mask_bit
from .reedsolomon import rs_correct_msg

__all__ = ["decode_image", "decode_photo"]

# Angle of the canonical key cells (-5,+5) and (-4,+5) midpoint, with
# y pointing down as in image coordinates.
_k0 = hex_to_pixel(-5, 5, 1.0)
_k1 = hex_to_pixel(-4, 5, 1.0)
_BETA0 = math.atan2(_k0[1] + _k1[1], _k0[0] + _k1[0])

_FINDER_CELLS = [(q, r) for k in range(5) for (q, r) in hex_ring(k)]
_FINDER_EXP = np.array([1 - (k % 2) for k in range(5)
                        for _ in hex_ring(k)], dtype=int)
_KEY_EXP = np.zeros(30, dtype=int)
_KEY_EXP[0] = 1
_KEY_EXP[1] = 1
_ALL_FINDER = _FINDER_CELLS + list(hex_ring(5))
_ALL_EXP = np.concatenate([_FINDER_EXP, _KEY_EXP])

# plausible cell counts of a dark finder blob (single ring or merged)
_BLOB_HYPOTHESES = (1, 6, 12, 18, 24, 30, 36, 42, 48)


# --------------------------------------------------------------- imaging
def _load_gray(path, max_dim=2400):
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise IOError("cannot read image: %s" % path)
    return img, max_dim


def _prepare(img, max_dim=2400):
    """Normalize illumination; return (blurred, norm8, darkmask).

    The illumination gradient is estimated as a very-low-frequency
    background.  A full-resolution Gaussian with sigma ~= max_dim/8
    needs a ~1800-tap kernel on a 2400 px image and alone costs 20 s
    on a 12 MP photo (85%% of the whole scan in v0.3.0), so the
    background is computed at 1/8 resolution and upsampled -- the
    result differs from the exact blur by at most ~2/255 per pixel,
    which the pose-selection logic tolerates (runner-up poses are
    tried and ranked by correction cost).
    """
    if max(img.shape) > max_dim:
        f = max_dim / max(img.shape)
        img = cv2.resize(img, None, fx=f, fy=f,
                         interpolation=cv2.INTER_AREA)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    h, w = img.shape
    sw, sh = max(1, w // 8), max(1, h // 8)
    small = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), max_dim / 8.0 / 8.0)
    bg = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    norm = img.astype(np.float32) / np.maximum(bg, 1.0)
    n8 = np.clip(norm * 200.0, 0, 255).astype(np.uint8)
    _, dark = cv2.threshold(n8, 0, 255,
                            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return img, n8, dark


def _adaptive_mask(img, module_px):
    """Local mean threshold; INVERTED convention (dark ink = 255)."""
    block = int(round(4.0 * module_px)) | 1
    return cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                 cv2.THRESH_BINARY_INV,
                                 max(7, block), 10)


def _integral(gray):
    return cv2.integral(gray)


def _box_mean(gray, ii, xs, ys, half):
    H, W = gray.shape
    x0 = np.clip(xs - half, 0, W - 1)
    x1 = np.clip(xs + half, 0, W - 1)
    y0 = np.clip(ys - half, 0, H - 1)
    y1 = np.clip(ys + half, 0, H - 1)
    s = ii[y1 + 1, x1 + 1] - ii[y0, x1 + 1] - ii[y1 + 1, x0] + ii[y0, x0]
    area = ((x1 - x0 + 1) * (y1 - y0 + 1)).astype(np.float32)
    return s / area


# --------------------------------------------------------------- finder
def _blob_candidates(dark, min_area=12, max_frac=0.01):
    n, _lab, stats, cent = cv2.connectedComponentsWithStats(dark)
    H, W = dark.shape
    amax = max_frac * H * W
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area or area > amax:
            continue
        if max(w, h) > 2.5 * min(w, h):
            continue
        out.append((cent[i][0], cent[i][1], int(area)))
    return out


def _ring_means(n8, cx, cy, s, n_ang=60):
    th = np.linspace(0, 2 * np.pi, n_ang, endpoint=False)
    H, W = n8.shape
    means = []
    for k in range(6):
        R = 1.5 * k * s
        xs = np.clip((cx + R * np.cos(th)).round().astype(int), 0, W - 1)
        ys = np.clip((cy + R * np.sin(th)).round().astype(int), 0, H - 1)
        means.append(float(n8[ys, xs].mean()))
    return means


def _profile_score(means):
    """Dark rings 0/2/4 vs light rings 1/3 (+ weak 5)."""
    return (means[1] + means[3] + 0.4 * means[5]) \
        - (means[0] + means[2] + means[4])


def _finder_positions(cx, cy, s, phi):
    c, sn = math.cos(phi), math.sin(phi)
    xs, ys = [], []
    for (q, r) in _ALL_FINDER:
        x, y = hex_to_pixel(q, r, s)
        xs.append(cx + x * c - y * sn)
        ys.append(cy + x * sn + y * c)
    return np.column_stack([xs, ys])


def _margin_at(gray, ii, pts, thr, half):
    xs = pts[:, 0].round().astype(int)
    ys = pts[:, 1].round().astype(int)
    H, W = gray.shape
    ok = (xs >= 0) & (xs < W) & (ys >= 0) & (ys < H)
    vals = np.full(len(xs), 255.0, dtype=np.float32)
    if ok.any():
        vals[ok] = _box_mean(gray, ii, xs[ok], ys[ok], half)
    m = np.where(_ALL_EXP == 1, thr - vals, vals - thr)
    return float(m.sum())


def _finder_count(am, ii_am, warp, half):
    """Number of correctly read finder cells (0-91) under a warp."""
    H, W = am.shape
    x, y = warp(_FU, _FV)
    xi = np.rint(x).astype(int)
    yi = np.rint(y).astype(int)
    ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
    vals = np.zeros(len(_FU), dtype=np.float32)
    vals[ok] = _box_mean(am, ii_am, xi[ok], yi[ok], half)
    read = np.where(ok, (vals > 127.5).astype(int), -1)
    return int((read == _ALL_EXP).sum())


def find_bullseye(n8, dark, top=4):
    """Score blobs under several merged-blob size hypotheses.

    Vectorized over all (blob x size-hypothesis x scale-factor x
    offset) configurations; produces the same top list as the
    original per-blob search (verified identical on test photos).
    """
    blobs = _blob_candidates(dark)
    if not blobs:
        return []
    H, W = n8.shape
    th = np.linspace(0, 2 * np.pi, 60, endpoint=False)
    ct, st_ = np.cos(th), np.sin(th)
    Rk = 1.5 * np.arange(6, dtype=np.float64)
    B = len(blobs)
    CX = np.array([b[0] for b in blobs], dtype=np.float64)
    CY = np.array([b[1] for b in blobs], dtype=np.float64)
    AR = np.array([b[2] for b in blobs], dtype=np.float64)
    hyp = np.asarray(_BLOB_HYPOTHESES, dtype=np.float64)
    s0 = np.sqrt(AR[:, None] / (2.598 * hyp[None, :]))
    valid = (s0 >= 1.2) & (s0 <= 80)
    fs = np.linspace(0.85, 1.2, 8)
    offs = np.array([-2., 0., 2.])
    NH = len(_BLOB_HYPOTHESES)
    bi = np.arange(B)[:, None, None, None, None]
    hi = np.arange(NH)[None, :, None, None, None]
    fi = np.arange(8)[None, None, :, None, None]
    xi_ = np.arange(3)[None, None, None, :, None]
    yi_ = np.arange(3)[None, None, None, None, :]
    full = (B, NH, 8, 3, 3)
    sc = np.broadcast_to(s0[bi, hi] * fs[fi], full)
    keep = np.broadcast_to(valid[bi, hi], full)
    fb = np.broadcast_to(bi, full).ravel()[keep.ravel()]
    fsc = sc.ravel()[keep.ravel()]
    fcx = np.broadcast_to(CX[bi] + offs[xi_], full).ravel()[keep.ravel()]
    fcy = np.broadcast_to(CY[bi] + offs[yi_], full).ravel()[keep.ravel()]
    C = len(fb)
    best = np.full(B, -1e18)
    bestk = np.zeros((B, 3))
    CH = max(1, int(2_000_000 // 360))
    for a in range(0, C, CH):
        s_c = fsc[a:a + CH, None, None]
        x = fcx[a:a + CH, None, None] + Rk[None, :, None] * s_c * ct
        y = fcy[a:a + CH, None, None] + Rk[None, :, None] * s_c * st_
        xii = np.clip(np.rint(x).astype(np.int64), 0, W - 1)
        yii = np.clip(np.rint(y).astype(np.int64), 0, H - 1)
        m = n8[yii, xii].mean(-1)
        score = (m[:, 1] + m[:, 3] + 0.4 * m[:, 5]
                 - m[:, 0] - m[:, 2] - m[:, 4])
        bidx = fb[a:a + CH]
        # fancy indexing with duplicates is "last wins": take the
        # per-blob group maximum inside the chunk (lexsort), then
        # merge chunk results into the global best
        o2 = np.lexsort((score, bidx))
        b_s = bidx[o2]
        s_s = score[o2]
        lastm = np.empty(len(b_s), dtype=bool)
        lastm[:-1] = b_s[1:] != b_s[:-1]
        lastm[-1] = True
        bb = b_s[lastm]
        vals = s_s[lastm]
        imp = vals > best[bb]
        if imp.any():
            bbi = bb[imp]
            best[bbi] = vals[imp]
            bestk[bbi, 0] = fcx[a:a + CH][o2][lastm][imp]
            bestk[bbi, 1] = fcy[a:a + CH][o2][lastm][imp]
            bestk[bbi, 2] = fsc[a:a + CH][o2][lastm][imp]
    order = np.argsort(-best)
    kept = []
    for b in order:
        if best[b] <= -1e17:
            break
        cxb, cyb, scb = bestk[b]
        if all(math.hypot(cxb - kx, cyb - ky) > 3 * ks
               for _, kx, ky, ks in kept):
            kept.append((float(best[b]), float(cxb), float(cyb),
                         float(scb)))
        if len(kept) >= top:
            break
    return kept


# model-frame unit-scale coordinates of the 91 finder cells (rings 0-5)
_FINDER_UV = np.array([hex_to_pixel(q, r, 1.0) for (q, r) in _ALL_FINDER])
_FU, _FV = _FINDER_UV[:, 0], _FINDER_UV[:, 1]


def _pose_margins(n8, ii, cxs, cys, ss, phis, thr_m, half):
    """Signed margin sum of every pose against the finder expectation.

    ``cxs/cys/ss/phis`` are equal-length 1-D arrays; returns one margin
    per pose (vectorized equivalent of the original per-config loop).
    """
    c = np.cos(phis)[:, None]
    sn = np.sin(phis)[:, None]
    us = ss[:, None] * _FU[None, :]
    vs = ss[:, None] * _FV[None, :]
    xs = cxs[:, None] + us * c - vs * sn
    ys = cys[:, None] + us * sn + vs * c
    xii = xs.round().astype(int)
    yii = ys.round().astype(int)
    H, W = n8.shape
    ok = (xii >= 0) & (xii < W) & (yii >= 0) & (yii < H)
    vals = np.full(xs.shape, 255.0, dtype=np.float32)
    if ok.any():
        vals[ok] = _box_mean(n8, ii, xii[ok], yii[ok], half)
    m = np.where(_ALL_EXP[None, :] == 1, thr_m - vals, vals - thr_m)
    return m.sum(1)


def _ang_diff(a, b):
    d = abs(a - b) % (2 * math.pi)
    return min(d, 2 * math.pi - d)


def _polish_pose(n8, ii, cx, cy, s, phi, thr_m, half):
    """Local polish sweep around a seed pose (same grid as v0.3.0)."""
    fs2 = np.linspace(0.95, 1.05, 11)
    dfs = np.deg2rad(np.arange(-4, 4.5, 0.5))
    o5 = np.array([-1., -0.5, 0., 0.5, 1.])
    P = np.array(np.meshgrid(fs2, dfs, o5, o5, indexing='ij'))
    P = P.reshape(4, -1).T
    mg = _pose_margins(n8, ii, cx + P[:, 2], cy + P[:, 3],
                       s * P[:, 0], phi + P[:, 1], thr_m, half)
    j = int(np.argmax(mg))
    return (float(mg[j]), float(cx + P[j, 2]), float(cy + P[j, 3]),
            float(s * P[j, 0]), float(phi + P[j, 1]))


def refine_pose(n8, ii, cx0, cy0, s0, half, want=3):
    """Joint rotation x scale sweep + local polish (similarity pose).

    Returns up to ``want`` distinct polished poses as
    ``[(margin, cx, cy, s, phi), ...]`` sorted by descending margin.
    The first entry equals the single-pose result of v0.3.0; the
    runner-ups protect against near-tie flips of the argmax (they are
    resolved downstream by the RS-judged, correction-cost-ranked
    decode).
    """
    thr_m = float(np.median(n8))
    phis = np.radians(np.arange(0, 360, 8, dtype=np.float64))
    fs = np.linspace(0.80, 1.25, 10)
    offs = np.array([-2., 0., 2.])
    P1 = np.array(np.meshgrid(phis, fs, offs, offs, indexing='ij'))
    P1 = P1.reshape(4, -1).T
    mg1 = _pose_margins(n8, ii, cx0 + P1[:, 2], cy0 + P1[:, 3],
                        s0 * P1[:, 1], P1[:, 0], thr_m, half)
    poses = []
    for j in np.argsort(-mg1)[:6]:
        pose = _polish_pose(n8, ii, cx0 + P1[j, 2], cy0 + P1[j, 3],
                            s0 * P1[j, 1], P1[j, 0], thr_m, half)
        # skip seeds whose polish converged to an already-found pose
        dup = False
        for _mgp, cx_p, cy_p, s_p, phi_p in poses:
            if (math.hypot(pose[1] - cx_p, pose[2] - cy_p) < 2.0
                    and abs(pose[3] - s_p) < 0.03 * s0
                    and _ang_diff(pose[4], phi_p) < math.radians(6)):
                dup = True
                break
        if not dup:
            poses.append(pose)
        if len(poses) >= want:
            break
    poses.sort(key=lambda t: -t[0])
    return poses


def homo_finder_fit(n8, ii, cx, cy, s, phi, thr, half):
    """Nelder-Mead fit of a homography on the 91 finder cells."""
    H, W = n8.shape
    p0 = np.array([s * math.cos(phi), -s * math.sin(phi), cx,
                   s * math.sin(phi), s * math.cos(phi), cy, 0.0, 0.0])
    UV = np.array([hex_to_pixel(q, r, 1.0) for (q, r) in _ALL_FINDER])
    uv1 = np.hstack([UV, np.ones((len(UV), 1))])

    def neg(p):
        Hm = np.array([[p[0], p[1], p[2]],
                       [p[3], p[4], p[5]],
                       [p[6], p[7], 1.0]])
        pr = uv1 @ Hm.T
        xs = (pr[:, 0] / pr[:, 2]).round().astype(int)
        ys = (pr[:, 1] / pr[:, 2]).round().astype(int)
        ok = (xs >= 0) & (xs < W) & (ys >= 0) & (ys < H)
        vals = np.full(len(xs), 255.0, dtype=np.float32)
        if ok.any():
            vals[ok] = _box_mean(n8, ii, xs[ok], ys[ok], half)
        m = np.where(_ALL_EXP == 1, thr - vals, vals - thr)
        return -float(np.minimum(m, 300).sum())

    res = minimize(neg, p0, method="Nelder-Mead",
                   options=dict(maxiter=6000, maxfev=8000, xatol=1e-3,
                                fatol=1e-3, adaptive=True))
    Hm = np.array([[res.x[0], res.x[1], res.x[2]],
                   [res.x[3], res.x[4], res.x[5]],
                   [res.x[6], res.x[7], 1.0]])

    def warp(u, v):
        scalar = np.ndim(u) == 0 and np.ndim(v) == 0
        u = np.atleast_1d(np.asarray(u, dtype=np.float64))
        v = np.atleast_1d(np.asarray(v, dtype=np.float64))
        px = Hm[0, 0] * u + Hm[0, 1] * v + Hm[0, 2]
        py = Hm[1, 0] * u + Hm[1, 1] * v + Hm[1, 2]
        pz = Hm[2, 0] * u + Hm[2, 1] * v + Hm[2, 2]
        x, y = px / pz, py / pz
        if scalar:
            return float(x[0]), float(y[0])
        return x, y

    return warp


# ------------------------------------------------------------- header RS
def _unpack_header(bits80, max_flips=2):
    """RS(5,5)-protected header, tolerating up to `max_flips` bit flips.

    Returns (params_or_None, bits_used).  A pass of the double
    protected header is an extremely selective test (~1e-12 false
    positive rate), which makes it safe as a geometry judge.
    """
    try:
        return unpack_mode_ex(bits_to_bytes(bits80)), list(bits80)
    except Exception:
        pass
    for i in range(80):
        b2 = list(bits80)
        b2[i] ^= 1
        try:
            return unpack_mode_ex(bits_to_bytes(b2)), b2
        except Exception:
            continue
    if max_flips >= 2:
        for i, j in combinations(range(80), 2):
            b2 = list(bits80)
            b2[i] ^= 1
            b2[j] ^= 1
            try:
                return unpack_mode_ex(bits_to_bytes(b2)), b2
            except Exception:
                continue
    return None, None


def _header_cells(m):
    """First 80 data cells in the model frame rotated by m sectors.

    A 60-degree model rotation shifts the canonical ring walk by k
    cells on ring k, which a linear bit shift can never express.
    """
    raw = []
    for k in range(DATA_RING0, 9):
        ring = list(hex_ring(k))
        n = len(ring)
        sh = (k * m) % n
        for i in range(n):
            raw.append(ring[(i + sh) % n])
    return raw[:80]


def _remap_grid(grid, m, rmax):
    """Re-index a raw-sampled grid into the m-rotated model frame."""
    out = {}
    for k in range(0, rmax + 1):
        ring = list(hex_ring(k))
        n = len(ring)
        sh = (k * m) % n
        for i, c in enumerate(ring):
            out[c] = grid.get(ring[(i + sh) % n], 0)
    return out


# precomputed per-sector header cells, known-cell sets and their
# model-frame unit-scale coordinates
_SECTOR_CELLS = [_header_cells(m) for m in range(6)]
_SECTOR_UV = [np.array([hex_to_pixel(q, r, 1.0) for (q, r) in hc])
              for hc in _SECTOR_CELLS]
_KNOWN_CELLS = [list(_ALL_FINDER) + hc for hc in _SECTOR_CELLS]
_KNOWN_UV = [np.array([hex_to_pixel(q, r, 1.0) for (q, r) in kc])
             for kc in _KNOWN_CELLS]


def _padding_anchors(rmax_m, ec_pct, data_len, mask_id, m):
    """Free geometric anchors from the tail padding (spec §3).

    Unused tail cells of the data region carry an alternating 0,1,0,1…
    pattern (masked like the rest of the payload), which the header
    (once RS-verified) pins down exactly.  These cells sit at the
    OUTER edge of the symbol -- precisely where the polynomial
    correction field would otherwise be pure extrapolation -- so they
    stabilise the sampling of the largest rings.

    Returns ``(cells, stored_bits)`` in the m-rotated model frame.
    """
    total = (data_len + sum(e for _, e in plan_blocks(data_len,
                                                      ec_pct))) * 8
    cap = ring_capacity(DATA_RING0, rmax_m)
    pad = cap - MODE_BITS - total
    if pad <= 0:
        return [], []
    first = MODE_BITS + total          # spiral index of first pad cell
    cells = []
    bits = []
    idx = 0
    for k in range(DATA_RING0, rmax_m + 1):
        ring = list(hex_ring(k))
        n = len(ring)
        sh = (k * m) % n
        for i in range(n):
            if idx >= first:
                cells.append(ring[(i + sh) % n])
                bit = (idx - first) % 2
                bits.append(bit ^ mask_bit(idx - MODE_BITS, mask_id))
            idx += 1
    return cells, bits


# ------------------------------------------------- correction field (CD)
def _cell_features(cells):
    """[1, u, v, u^2, uv, v^2] features in model units scaled by 1/10."""
    F = []
    for (q, r) in cells:
        u, v = hex_to_pixel(q, r, 1.0)
        F.append([1.0, u / 10.0, v / 10.0, (u / 10.0) ** 2,
                  (u / 10.0) * (v / 10.0), (v / 10.0) ** 2])
    return np.array(F)


def _eval_margin(am, ii_am, W, H, half, base_pts, F, EXP, delta):
    pts = base_pts + F @ delta.reshape(2, 6).T
    xi = pts[:, 0].round().astype(int)
    yi = pts[:, 1].round().astype(int)
    ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
    vals = np.full(len(xi), 255.0, dtype=np.float32)
    vals[ok] = _box_mean(am, ii_am, xi[ok], yi[ok], half)
    m = np.where(EXP == 1, vals - 127.5, 127.5 - vals)
    return float(np.minimum(m, 200).sum())


def _coord_descent(am, ii_am, W, H, half, base_pts, F, EXP, delta0,
                   sweeps=5):
    """Fit a poly-2 correction field on the known cells (soft margin)."""
    delta = delta0.copy()
    best = _eval_margin(am, ii_am, W, H, half, base_pts, F, EXP, delta)
    step_px = half / 0.32
    for st in (0.30 * step_px, 0.15 * step_px, 0.07 * step_px,
               0.03 * step_px):
        for _ in range(2):
            improved = False
            for pi in range(12):
                while True:
                    loc = (best, None)
                    for sgn in (+1, -1):
                        d2 = delta.copy()
                        d2[pi] += sgn * st
                        v = _eval_margin(am, ii_am, W, H, half, base_pts,
                                         F, EXP, d2)
                        if v > loc[0] + 1e-6:
                            loc = (v, d2)
                    if loc[1] is None:
                        break
                    delta, best = loc[1], loc[0]
                    improved = True
            if not improved:
                break
    return delta, best


def _make_warp(warp0, delta):
    def warp(u, v):
        scalar = np.ndim(u) == 0 and np.ndim(v) == 0
        u = np.atleast_1d(np.asarray(u, dtype=np.float64))
        v = np.atleast_1d(np.asarray(v, dtype=np.float64))
        x0, y0 = warp0(u, v)
        a = np.stack([np.ones_like(u), u / 10.0, v / 10.0,
                      (u / 10.0) ** 2, (u / 10.0) * (v / 10.0),
                      (v / 10.0) ** 2])
        x = x0 + a.T @ delta[:6]
        y = y0 + a.T @ delta[6:]
        if scalar:
            return float(x[0]), float(y[0])
        return x, y
    return warp


# -------------------------------------------------------------- sampling
_UV_CACHE = {}


def _model_uv(rmax):
    """Model-frame unit-scale coordinates of all cells r = 0..rmax."""
    uv = _UV_CACHE.get(rmax)
    if uv is None:
        keys = [(q, r) for k in range(rmax + 1)
                for (q, r) in hex_ring(k)]
        uv = (keys, np.array([hex_to_pixel(q, r, 1.0)
                              for (q, r) in keys]))
        _UV_CACHE[rmax] = uv
    return uv


def _sample_grid(warp, rmax, am, ii_am, W, H, half):
    """Sample the grid with the local adaptive threshold (INVERTED mask:
    dark ink = 255, so a bit is 1 when the box mean is above 127.5)."""
    keys, UV = _model_uv(rmax)
    x, y = warp(UV[:, 0], UV[:, 1])
    xi = np.rint(x).astype(int)
    yi = np.rint(y).astype(int)
    ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
    vals = np.zeros(len(keys), dtype=np.float32)
    vals[ok] = _box_mean(am, ii_am, xi[ok], yi[ok], half)
    bits = (vals > 127.5).astype(int)
    bits[~ok] = 0
    return dict(zip(keys, map(int, bits)))


def _sample_grid_gray(warp, rmax, n8, ii, W, H, half, thr):
    keys, UV = _model_uv(rmax)
    x, y = warp(UV[:, 0], UV[:, 1])
    xi = np.rint(x).astype(int)
    yi = np.rint(y).astype(int)
    ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
    vals = np.full(len(keys), 255.0, dtype=np.float32)
    vals[ok] = _box_mean(n8, ii, xi[ok], yi[ok], half)
    bits = (vals < thr).astype(int)
    bits[~ok] = 0
    return dict(zip(keys, map(int, bits)))


def _detect_rmax(vals, rmax_probe, thr):
    """Last ring with content; stop after 3 consecutive empty rings."""
    last, i, empty_run = 0, 0, 0
    for k in range(0, rmax_probe + 1):
        n = 6 * k if k else 1
        seg = vals[i:i + n]
        i += n
        ndark = int((seg < thr).sum())
        need = 1 if k <= 7 else 2
        if ndark >= need:
            last = k
            empty_run = 0
        else:
            empty_run += 1
            if k > 7 and empty_run >= 3:
                break
    return min(max(last, 7), MAX_RINGS)


def _rs_try(data_bytes, ecc):
    try:
        return bytes(rs_correct_msg(list(data_bytes), ecc))
    except Exception:
        return None


def decode_grid_robust(grid):
    """decode() plus a limited bit-flip repair search.

    Returns ``(text, stats, cost)`` where *cost* is the correction
    ledger: the total number of payload bit positions explained as
    errors (RS-corrected bits + applied flips).  Cost 0 means the
    sampled grid is itself a valid codeword, which cannot happen by
    chance (RS code distance 6), so it outranks any repaired result.
    Within the repair radius the codeword is unique, so more than one
    candidate can never exist for a single grid.
    """
    from .geometry import hex_distance
    try:
        text, st = decode(grid)
        return text, st, st.get("repair_bits", 0)
    except Exception:
        pass
    cells = sorted(grid.keys(), key=lambda c: hex_distance(*c))
    rmax_g = max(hex_distance(*c) for c in cells)
    data_cells = [c for k in range(DATA_RING0, rmax_g + 1)
                  for c in hex_ring(k)]
    bits = [grid[c] for c in data_cells]
    if len(bits) < MODE_BITS:
        raise ValueError("not enough bits for the header")
    b80 = list(bits[:MODE_BITS])
    head = None
    try:
        head = unpack_mode_ex(bits_to_bytes(b80))
    except Exception:
        pass
    if head is None:
        for i in range(MODE_BITS):
            b2 = list(b80)
            b2[i] ^= 1
            try:
                head = unpack_mode_ex(bits_to_bytes(b2))
                b80 = b2
                break
            except Exception:
                continue
    if head is None:
        for i, j in combinations(range(MODE_BITS), 2):
            b2 = list(b80)
            b2[i] ^= 1
            b2[j] ^= 1
            try:
                head = unpack_mode_ex(bits_to_bytes(b2))
                b80 = b2
                break
            except Exception:
                continue
    if head is None:
        raise ValueError("header unrecoverable even with bit flips")
    rmax_m, mask_id, ec_pct, bc, data_len, compressed = head
    need = (data_len + sum(e for _, e in plan_blocks(data_len, ec_pct))) * 8
    if len(bits) < MODE_BITS + need:
        raise ValueError("not enough bits for the payload")
    payload = [b ^ mask_bit(i, mask_id)
               for i, b in enumerate(bits[MODE_BITS:MODE_BITS + need])]
    stream = list(bits_to_bytes(payload))
    blocks = plan_blocks(data_len, ec_pct)
    out = bytearray()
    cost = 0
    pos = 0
    for size, ecc in blocks:
        cw = stream[pos:pos + size + ecc]
        pos += size + ecc
        fixed = _rs_try(cw, ecc)
        if fixed is not None:
            full = list(fixed) + cw[len(fixed):]
            cost += sum(bin(a ^ b).count("1")
                        for a, b in zip(cw, full))
        else:
            n = len(cw) * 8
            for i in range(n):
                b2 = list(cw)
                b2[i // 8] ^= (1 << (7 - i % 8))
                fixed = _rs_try(b2, ecc)
                if fixed is not None:
                    cost += 1
                    full = list(fixed) + b2[len(fixed):]
                    cost += sum(bin(a ^ b).count("1")
                                for a, b in zip(b2, full))
                    break
        if fixed is None:
            raise ValueError("block %d+%d unrecoverable" % (size, ecc))
        out += fixed
    text = payload_to_text(bytes(out), compressed)
    stats = {"rmax": rmax_m, "mask": mask_id, "ec": ec_pct,
             "blocks": bc, "data_len": data_len,
             "compressed": compressed, "repair_bits": cost}
    return text, stats, cost


# --------------------------------------------------- perspective fallbacks
def _dlt_h(obs):
    """Homography model(u,v) -> image(x,y), DLT + Hartley normalization."""
    P = np.array([[u, v] for (u, v), _ in obs], dtype=np.float64)
    Q = np.array([[x, y] for _, (x, y) in obs], dtype=np.float64)
    cm, dm = P.mean(0), max(P.std(0).mean(), 1e-9)
    cn, dn = Q.mean(0), max(Q.std(0).mean(), 1e-9)
    Tm = np.array([[1 / dm, 0, -cm[0] / dm],
                   [0, 1 / dm, -cm[1] / dm], [0, 0, 1]])
    Tq = np.array([[1 / dn, 0, -cn[0] / dn],
                   [0, 1 / dn, -cn[1] / dn], [0, 0, 1]])
    A = []
    for (u, v), (x, y) in zip(P, Q):
        un, vn = (u - cm[0]) / dm, (v - cm[1]) / dm
        xn, yn = (x - cn[0]) / dn, (y - cn[1]) / dn
        A.append([-un, -vn, -1, 0, 0, 0, xn * un, xn * vn, xn])
        A.append([0, 0, 0, -un, -vn, -1, yn * un, yn * vn, yn])
    _, _, Vt = np.linalg.svd(np.array(A))
    Hn = Vt[-1].reshape(3, 3)
    H = np.linalg.inv(Tq) @ Hn @ Tm
    return H / (H[2, 2] + 1e-15)


def _warp_from_h(Hm):
    def warp(u, v):
        scalar = np.ndim(u) == 0 and np.ndim(v) == 0
        u = np.atleast_1d(np.asarray(u, dtype=np.float64))
        v = np.atleast_1d(np.asarray(v, dtype=np.float64))
        px = Hm[0, 0] * u + Hm[0, 1] * v + Hm[0, 2]
        py = Hm[1, 0] * u + Hm[1, 1] * v + Hm[1, 2]
        pz = Hm[2, 0] * u + Hm[2, 1] * v + Hm[2, 2]
        x, y = px / pz, py / pz
        if scalar:
            return float(x[0]), float(y[0])
        return x, y
    return warp


def _annulus_icp_rescue(n8, ii, cx, cy, s, phi, thr, half, r_probe,
                        dark_lv=None, light_lv=None, dphi0=0.0, ds0=1.0,
                        iters=8):
    """ICP homography on the ring-2/ring-4 annulus edges (strong
    perspective shots).  Ported from the research prototype."""
    NB = 360
    prof = {}
    for ring in (2, 4):
        rmax_b = np.zeros(NB)
        rmin_b = np.full(NB, 1e9)
        for (q, r) in hex_ring(ring):
            u0, v0 = hex_to_pixel(q, r, 1.0)
            for i in range(6):
                ux, vy = _hex_corner(u0, v0, 1.0, i)
                rr = math.hypot(ux, vy)
                th = math.atan2(vy, ux) % (2 * math.pi)
                b = int(th / (2 * math.pi) * NB) % NB
                if rr > rmax_b[b]:
                    rmax_b[b] = rr
                if rr < rmin_b[b]:
                    rmin_b[b] = rr
        for b in range(NB):
            if rmax_b[b] == 0:
                rmax_b[b] = rmax_b[(b - 1) % NB]
            if rmin_b[b] > 1e8:
                rmin_b[b] = rmin_b[(b - 1) % NB]
        prof[ring] = (rmax_b, rmin_b)

    mid = 0.5 * ((dark_lv if dark_lv is not None else 60)
                 + (light_lv if light_lv is not None else 220))
    H, W = n8.shape

    def model_points(ring, outer):
        rr = prof[ring][0 if outer else 1]
        th = 2 * math.pi * np.arange(NB) / NB
        return np.column_stack([rr * np.cos(th), rr * np.sin(th)])

    sr = s * ds0
    ph = phi + dphi0
    Hmat = np.array([[sr * math.cos(ph), -sr * math.sin(ph), cx],
                     [sr * math.sin(ph), sr * math.cos(ph), cy],
                     [0.0, 0.0, 1.0]])
    warp = _warp_from_h(Hmat)

    NRAY = 96
    ths = np.linspace(0, 2 * math.pi, NRAY, endpoint=False)
    cos_t, sin_t = np.cos(ths), np.sin(ths)
    mp_all = {(ring, o): model_points(ring, o)
              for ring in (2, 4) for o in (True, False)}

    for _ in range(iters):
        mp_model = []
        for ring in (2, 4):
            for o in (True, False):
                mp_model.append(mp_all[(ring, o)][::2])
        mp_model = np.vstack(mp_model)
        wx, wy = warp(mp_model[:, 0], mp_model[:, 1])
        mp_img = np.column_stack([wx, wy])
        tree_w = cKDTree(mp_img)
        obs = []
        for ring in (2, 4):
            for outer in (True, False):
                Rlo = (3.6 if ring == 2 else 7.0) * s if outer \
                    else (2.6 if ring == 2 else 4.6) * s
                Rhi = (5.4 if ring == 2 else 8.6) * s if outer \
                    else (4.4 if ring == 2 else 6.4) * s
                for j in range(NRAY):
                    ts = np.arange(Rlo, Rhi, 1.0)
                    xs = np.clip((cx + ts * cos_t[j]).round().astype(int),
                                 0, W - 1)
                    ys = np.clip((cy + ts * sin_t[j]).round().astype(int),
                                 0, H - 1)
                    pv = n8[ys, xs].astype(np.float32)
                    cross = np.where((pv[:-1] < mid) & (pv[1:] >= mid))[0]
                    if len(cross) == 0:
                        continue
                    i1 = cross[-1]
                    t0, t1 = ts[i1], ts[i1 + 1]
                    v0_, v1_ = pv[i1], pv[i1 + 1]
                    t_star = t1 if v1_ == v0_ else \
                        t0 + (mid - v0_) * (t1 - t0) / (v1_ - v0_)
                    px, py = cx + t_star * cos_t[j], cy + t_star * sin_t[j]
                    dmin, imin = tree_w.query([px, py])
                    if dmin < 0.45 * s:
                        obs.append((tuple(mp_model[imin]), (px, py)))
        if len(obs) < 20:
            break
        try:
            Hmat = _dlt_h(obs)
        except Exception:
            break
        warp = _warp_from_h(Hmat)
        grid = _sample_grid_gray(warp, r_probe, n8, ii, W, H, half, thr)
        try:
            text, st, _cost = decode_grid_robust(grid)
            return text, st, warp
        except Exception:
            continue
    return None


def _affine_rescue(n8, ii, cx, cy, s, phi, thr, half, r_probe,
                   max_combos=1200):
    """Affine (+keystone) search judged by the RS header.

    Combos are ordered by total distortion magnitude, so successful
    rescues cluster at the front; ``max_combos`` bounds the worst case
    (hopeless images) instead of sweeping thousands of hypotheses.
    """
    c0, s0_ = math.cos(phi), math.sin(phi)

    def make_warp(da, db, dc, dd, k=0.0):
        def warp(u, v):
            xs = (1 + da) * u + db * v
            ys = dc * u + (1 + dd) * v
            if k:
                xs = xs * (1.0 + k * v / 12.0)
            x, y = xs * s, ys * s
            return cx + x * c0 - y * s0_, cy + x * s0_ + y * c0
        return warp

    def header_ok(warp):
        g8 = _sample_grid_gray(warp, 8, n8, ii,
                               n8.shape[1], n8.shape[0], half, thr)
        dcells = [c for k in range(DATA_RING0, 9)
                  for c in hex_ring(k)][:80]
        head, _ = _unpack_header([g8[c] for c in dcells], max_flips=1)
        return head is not None

    vals_ad = [round(-0.12 + 0.02 * i, 3) for i in range(13)]
    vals_sh = [round(-0.09 + 0.03 * i, 3) for i in range(7)]
    combos = [(da, db, dc, dd)
              for da in vals_ad for dd in vals_ad
              for db in vals_sh for dc in vals_sh]
    combos.sort(key=lambda t: abs(t[0]) + abs(t[1]) + abs(t[2]) + abs(t[3]))
    for da, db, dc, dd in combos[:max_combos]:
        warp = make_warp(da, db, dc, dd)
        if not header_ok(warp):
            continue
        grid = _sample_grid_gray(warp, r_probe, n8, ii,
                                 n8.shape[1], n8.shape[0], half, thr)
        try:
            text, st, _cost = decode_grid_robust(grid)
            return text, st, warp
        except Exception:
            continue
    return None


def _hex_corner(u0, v0, size, i):
    from .geometry import hex_corner
    return hex_corner(u0, v0, size, i)


# ---------------------------------------------------------------- public
def decode_image(image, max_dim=2400, verbose=False):
    """Decode a Hexatess symbol from a grayscale or BGR image array.

    Returns ``(text, stats)`` where *stats* contains ``rmax``, ``mask``,
    ``ec``, ``blocks``, ``data_len``, ``compressed`` (spec v0.3 payload
    flag), ``sector`` (the model-frame rotation that matched),
    ``finder_hits`` (0-91) and ``repair_bits`` (the correction ledger
    of the winning hypothesis).

    Several finder poses per bullseye candidate are tried and the
    decode with the lowest correction ledger wins; a zero-cost decode
    (sampled grid == valid codeword) returns immediately.  This makes
    the result robust against near-tie flips of the pose argmax.

    Raises :class:`RuntimeError` when no candidate decodes.
    """
    if image.ndim == 3:
        img = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        img = image.copy()
    img, n8, dark = _prepare(img, max_dim)
    ii = _integral(n8)
    found = find_bullseye(n8, dark)
    if verbose:
        print("candidates:", [(round(v, 1), int(x), int(y), round(s, 1))
                              for v, x, y, s in found])
    errors = []
    started = time.perf_counter()

    # A zero-cost decode means the sampled grid IS a codeword -- two
    # codewords are >= 48 bits (RS distance 6) apart, so no other
    # hypothesis can beat an exact match and it returns immediately.
    # Any repaired decode (cost > 0) stays tentative: the runner-up
    # poses are tried as well and the lowest ledger wins.  This is the
    # safeguard against near-tie pose flips producing a plausible but
    # wrong payload.

    for rank, (v0, cx0, cy0, s0) in enumerate(found[:3]):
        half = max(1, int(round(0.32 * s0)))
        poses = refine_pose(n8, ii, cx0, cy0, s0, half)
        W, H = n8.shape[1], n8.shape[0]
        cand_success = False
        cand_best = None                # (cost, -hits, -margin, text, st)
        for pi, (pm, cx, cy, s, phi) in enumerate(poses):
            r_probe = min(MAX_RINGS,
                          int(min(cx, cy, W - cx, H - cy) / (1.5 * s)) - 2)
            am = _adaptive_mask(img, s)
            ii_am = _integral(am)
            warp0 = homo_finder_fit(n8, ii, cx, cy, s, phi,
                                    float(np.median(n8)), half)
            hits = _finder_count(am, ii_am, warp0, half)
            if verbose:
                print("cand %d pose %d: s=%.1f margin=%.0f finder %d/91"
                      % (rank, pi, s, pm, hits))
            if hits < 84:
                errors.append("cand %d pose %d: finder %d/91"
                              % (rank, pi, hits))
                continue
            for m in range(6):
                hx, hy = warp0(_SECTOR_UV[m][:, 0], _SECTOR_UV[m][:, 1])
                xi = hx.round().astype(int)
                yi = hy.round().astype(int)
                ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
                vals = np.full(len(hx), 255.0, dtype=np.float32)
                vals[ok] = _box_mean(am, ii_am, xi[ok], yi[ok], half)
                bits80 = [1 if v > 127.5 else 0 for v in vals]
                head, fixed = _unpack_header(bits80, max_flips=2)
                if head is None:
                    continue
                rmax_m, mask_id_h, _ecp, _bcn, data_len_m, _comp = head
                pad_cells, pad_bits = _padding_anchors(
                    rmax_m, _ecp, data_len_m, mask_id_h, m)
                known = _KNOWN_CELLS[m] + pad_cells
                F = _cell_features(known)
                EXP = np.array(list(_ALL_EXP) + list(fixed) + pad_bits,
                               dtype=int)
                uv_known = np.vstack([
                    _KNOWN_UV[m],
                    np.array([hex_to_pixel(q, r, 1.0)
                              for (q, r) in pad_cells])
                ]) if pad_cells else _KNOWN_UV[m]
                bx, by = warp0(uv_known[:, 0], uv_known[:, 1])
                base = np.column_stack([bx, by])
                delta, _ = _coord_descent(am, ii_am, W, H, half, base,
                                          F, EXP, np.zeros(12))
                warp = _make_warp(warp0, delta)
                grid = _sample_grid(warp, r_probe, am, ii_am, W, H, half)
                try:
                    text, st, cost = decode_grid_robust(
                        _remap_grid(grid, m, r_probe))
                except Exception as e:
                    errors.append("cand %d pose %d sector %d: %s"
                                  % (rank, pi, m, e))
                    continue
                st["sector"] = m
                st["finder_hits"] = hits
                if cost == 0:
                    return text, st     # sampled grid == codeword
                key = (cost, -hits, -pm)
                if cand_best is None or key < cand_best[0]:
                    cand_best = (key, text, st)
                cand_success = True
        if cand_success:
            # this bullseye candidate decoded; its best hypothesis wins
            # (runner-up poses were already tried when the first decode
            # looked suspicious) -- no need for fallbacks or candidates
            return cand_best[1], cand_best[2]
        if rank > 0 and time.perf_counter() - started > 15.0:
            errors.append("cand %d: skipped (timeout)" % rank)
            continue
        # strong-perspective fallbacks (canonical frame, sector 0)
        _pm, cx, cy, s, phi = poses[0]
        r_probe = min(MAX_RINGS,
                      int(min(cx, cy, W - cx, H - cy) / (1.5 * s)) - 2)
        thr_f = _finder_threshold(n8, ii, cx, cy, s, phi, half)
        for (dp, dsc) in [(0.0, 1.0), (3.0, 1.0), (-3.0, 1.0),
                          (0.0, 0.96), (0.0, 1.04)]:
            res = _annulus_icp_rescue(n8, ii, cx, cy, s, phi, thr_f,
                                      half, r_probe,
                                      dphi0=math.radians(dp),
                                      ds0=dsc)
            if res is not None:
                return res[0], dict(res[1], sector=0)
        res = _affine_rescue(n8, ii, cx, cy, s, phi, thr_f, half,
                             r_probe)
        if res is not None:
            return res[0], dict(res[1], sector=0)
        errors.append("cand %d: fallbacks failed" % rank)
    raise RuntimeError("decoding failed: " + "; ".join(errors[:6]))


def _finder_threshold(n8, ii, cx, cy, s, phi, half):
    """Threshold midway between the dark and light finder levels."""
    pts = _finder_positions(cx, cy, s, phi)
    xs = pts[:, 0].round().astype(int)
    ys = pts[:, 1].round().astype(int)
    H, W = n8.shape
    ok = (xs >= 0) & (xs < W) & (ys >= 0) & (ys < H)
    vals = np.full(len(xs), 255.0, dtype=np.float32)
    vals[ok] = _box_mean(n8, ii, xs[ok], ys[ok], half)
    nf = len(_FINDER_CELLS)
    dark_lv = np.median(vals[:nf][_ALL_EXP[:nf] == 1])
    light_lv = np.median(vals[:nf][_ALL_EXP[:nf] == 0])
    return 0.5 * (dark_lv + light_lv)


def decode_photo(path, max_dim=2400, verbose=False):
    """Decode a Hexatess symbol from an image file.

    Returns ``(text, stats)``; see :func:`decode_image`.
    """
    img, max_dim = _load_gray(path, max_dim)
    text, stats = decode_image(img, max_dim=max_dim, verbose=verbose)
    if verbose:
        print("%s: %r" % (os.path.basename(str(path)), text))
    return text, stats
