"""GF(256) Galois field arithmetic for Hexatess Code.

The field uses the primitive polynomial x^8 + x^4 + x^3 + x^2 + 1
(0x11D) -- the same choice as QR Code and Aztec Code -- with generator
alpha = 2.  Polynomials are represented as lists of integer coefficients
in descending order of degree (coefficient list ``[a, b, c]`` means
a*x^2 + b*x + c), except inside the Forney algorithm where an ascending
order convention is used explicitly and documented.
"""

from __future__ import annotations

GF_EXP = [0] * 512
GF_LOG = [0] * 256

_x = 1
for _i in range(255):
    GF_EXP[_i] = _x
    GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    GF_EXP[_i] = GF_EXP[_i - 255]

PRIMITIVE_POLY = 0x11D


def gf_mul(x: int, y: int) -> int:
    """Multiply two field elements."""
    if x == 0 or y == 0:
        return 0
    return GF_EXP[GF_LOG[x] + GF_LOG[y]]


def gf_div(x: int, y: int) -> int:
    """Divide two field elements (raises ZeroDivisionError on y == 0)."""
    if y == 0:
        raise ZeroDivisionError("division by zero in GF(256)")
    if x == 0:
        return 0
    return GF_EXP[(GF_LOG[x] + 255 - GF_LOG[y]) % 255]


def gf_inv(x: int) -> int:
    """Multiplicative inverse of a non-zero field element."""
    return GF_EXP[(255 - GF_LOG[x]) % 255]


def gf_poly_scale(p, x):
    """Multiply every coefficient of polynomial ``p`` by ``x``."""
    return [gf_mul(c, x) for c in p]


def gf_poly_add(p, q):
    """Add two polynomials (descending coefficient order)."""
    r = [0] * max(len(p), len(q))
    for i, c in enumerate(p):
        r[i + len(r) - len(p)] = c
    for i, c in enumerate(q):
        r[i + len(r) - len(q)] ^= c
    return r


def gf_poly_mul(p, q):
    """Multiply two polynomials (descending coefficient order)."""
    r = [0] * (len(p) + len(q) - 1)
    for j, qj in enumerate(q):
        for i, pi in enumerate(p):
            r[i + j] ^= gf_mul(pi, qj)
    return r


def gf_poly_eval(p, x):
    """Evaluate polynomial ``p`` at ``x`` using Horner's scheme.

    ``p[0]`` is the highest-degree coefficient.
    """
    y = p[0]
    for c in p[1:]:
        y = gf_mul(y, x) ^ c
    return y
