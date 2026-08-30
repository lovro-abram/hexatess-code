"""Command-line interface for Hexatess Code.

Examples
--------
Encode text to PNG::

    hexatess-code "Hello world" -o koda.png --ec 30

Render a demo symbol and run robustness tests::

    hexatess-code --demo
    hexatess-code --test
"""

from __future__ import annotations

import argparse

from .decoder import decode
from .encoder import encode
from .render import render, sample_grid_from_image


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="hexatess",
        description="Hexatess Code - hexagonal-grid 2D barcode "
                    "(reference implementation, spec v0.2)")
    ap.add_argument("text", nargs="?", help="text to encode (UTF-8)")
    ap.add_argument("-o", "--output", default="hexatess.png",
                    help="output PNG path (default: %(default)s)")
    ap.add_argument("--ec", type=int, default=30,
                    help="error-correction %% (5-90, step 5; default 30)")
    ap.add_argument("--mask", type=int, default=None, metavar="0-7",
                    help="force a mask instead of automatic selection")
    ap.add_argument("--size", type=int, default=18,
                    help="hex radius in pixels (default %(default)s)")
    ap.add_argument("--test", action="store_true",
                    help="run robustness tests")
    ap.add_argument("--demo", action="store_true",
                    help="render a demo symbol and run robustness tests")
    args = ap.parse_args(argv)

    if args.test or args.demo:
        from .resilience import run_tests
        run_tests()

    if args.demo or args.text:
        text = args.text or "Hexatess Code v0.2 - " * 6
        grid, params = encode(text, ec_pct=args.ec, mask_id="auto"
                              if args.mask is None else args.mask)
        render(grid, args.output, size_px=args.size)
        print("\nRendered: %s" % args.output)
        print("  version (rings): %d, EC: %d%%, mask: %d, bytes: %d"
              % (params["rmax"], params["ec"], params["mask"],
                 params["data_len"]))
        grid2 = sample_grid_from_image(args.output, params["rmax"],
                                       size_px=args.size)
        t, _st = decode(grid2)
        print("  self-decode from image: %s"
              % ("OK" if t == text else "FAILED"))


if __name__ == "__main__":
    main()
