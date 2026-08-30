"""PNG rendering and ideal re-sampling of Hexatess Code symbols."""

from __future__ import annotations

import math

from .geometry import hex_corner, hex_distance, hex_ring, hex_to_pixel


def render(grid, path, size_px=18, quiet_module=1.5,
           dark=(24, 22, 18), light=(255, 255, 255), ss=3):
    """Render a module grid to a PNG file.

    Parameters
    ----------
    grid : dict
        Mapping ``{(q, r): 0|1}`` (1 = dark module).
    path : str
        Output PNG path.
    size_px : int
        Hexagon radius in pixels.
    quiet_module : float
        Quiet zone width in modules.
    dark, light : tuple
        RGB colours of dark / light modules.
    ss : int
        Supersampling factor for smooth edges.

    Returns
    -------
    str
        The output path.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit("rendering requires Pillow: pip install pillow")
    rmax = max(hex_distance(*c) for c in grid)
    width = int(math.sqrt(3.0) * size_px * (2 * rmax + 1 + 2 * quiet_module))
    height = int(1.5 * size_px * (2 * rmax + 2 * quiet_module + 2))
    img = Image.new("RGB", (width * ss, height * ss), light)
    dr = ImageDraw.Draw(img)
    cx0, cy0 = width * ss / 2.0, height * ss / 2.0
    s = size_px * ss
    for (q, r), val in grid.items():
        if not val:
            continue
        x, y = hex_to_pixel(q, r, s)
        pts = [hex_corner(cx0 + x, cy0 + y, s * 0.995, i) for i in range(6)]
        dr.polygon(pts, fill=dark)
    img = img.resize((width, height), Image.LANCZOS)
    img.save(path)
    return path


def sample_grid_from_image(path, rmax, size_px=18, quiet_module=1.5):
    """Re-sample a rendered image back into a module grid (ideal sampling).

    This is a self-test / conformance helper: it assumes the image was
    produced by :func:`render` with the same geometry parameters and is
    perfectly upright.  Real-world scanning requires finder detection
    and perspective correction (planned for a later release).
    """
    from PIL import Image
    img = Image.open(path).convert("L")
    width, height = img.size
    cx0, cy0 = width / 2.0, height / 2.0
    s = size_px
    grid = {}
    for k in range(rmax + 1):
        for (q, r) in hex_ring(k):
            x, y = hex_to_pixel(q, r, s)
            v = img.getpixel((int(cx0 + x), int(cy0 + y)))
            grid[(q, r)] = 1 if v < 128 else 0
    return grid
