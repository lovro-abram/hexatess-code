#!/usr/bin/env python3
"""Compare symbol growth and ECC behaviour across EC budgets.

Run:  python examples/custom_ec.py
"""

from hexatess import decode, encode, render

text = "Ordre et progrès — the quick brown fox jumps over the lazy dog."

print("%-6s %-6s %-6s %-8s" % ("EC%", "rings", "mask", "blocks"))
symbols = {}
for ec in (5, 30, 55, 90):
    grid, p = encode(text, ec_pct=ec)
    symbols[ec] = grid
    render(grid, "custom_ec_%02d.png" % ec)
    out, _ = decode(grid)
    assert out == text
    print("%-6d %-6d %-6d %-8s" % (ec, p["rmax"], p["mask"],
                                   "%d x (%d+%d)" % (
                                       len(p["blocks"]),
                                       p["blocks"][0][0],
                                       p["blocks"][0][1])))

print("\nRendered custom_ec_05/30/55/90.png — higher EC costs larger")
print("symbols but tolerates far more damage. Decode is transparent:")
print("the header tells the decoder which budget was used.")
