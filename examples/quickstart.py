#!/usr/bin/env python3
"""Quickstart: encode, render and decode a Hexatess Code symbol.

Run:  python examples/quickstart.py
"""

from hexatess import decode, encode, render

text = "Hello, Hexatess! 🐝"

# 1) Encode text (UTF-8) into a hexagonal grid at 30% EC budget
grid, params = encode(text, ec_pct=30)

print("rings:            %d" % params["rmax"])
print("mask:             %d" % params["mask"])
print("EC budget:        %d%%" % params["ec"])
print("blocks (data,ecc): %s" % params["blocks"])
print("payload bytes:    %d" % params["data_len"])

# 2) Render to PNG
render(grid, "quickstart.png")
print("rendered:         quickstart.png")

# 3) Decode back (decoder discovers everything from the header)
text2, stats = decode(grid)
assert text2 == text
print("decoded:          %r" % text2)
print("decoder saw:      rmax=%d mask=%d ec=%d%%"
      % (stats["rmax"], stats["mask"], stats["ec"]))
