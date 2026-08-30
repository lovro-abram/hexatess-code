"""Systematic Reed-Solomon codec over GF(256) for Hexatess Code.

Encoder: polynomial long division by the generator polynomial, producing
``nsym`` trailing ECC symbols (systematic code, identical to the scheme
used by QR Code and Aztec Code).

Decoder: syndromes -> Berlekamp-Massey error locator -> Chien search for
error positions -> Forney algorithm for error magnitudes.  The Forney
step internally uses an ascending-order polynomial convention:

    e_i = X_i * Omega(X_i^-1) / Lambda'(X_i^-1)
"""

from __future__ import annotations

from .galois import (
    GF_EXP,
    gf_div,
    gf_inv,
    gf_mul,
    gf_poly_add,
    gf_poly_eval,
    gf_poly_mul,
    gf_poly_scale,
)


def rs_generator_poly(nsym: int):
    """Generator polynomial prod_{i=0..nsym-1} (x - alpha^i)."""
    g = [1]
    for i in range(nsym):
        g = gf_poly_mul(g, [1, GF_EXP[i]])
    return g


def rs_encode_msg(msg_in, nsym: int):
    """Return ``msg_in`` followed by ``nsym`` ECC symbols."""
    if len(msg_in) + nsym > 255:
        raise ValueError(
            "block too long for RS over GF(256): %d + %d > 255"
            % (len(msg_in), nsym))
    gen = rs_generator_poly(nsym)
    msg_out = list(msg_in) + [0] * nsym
    for i in range(len(msg_in)):
        coef = msg_out[i]
        if coef:
            for j in range(1, len(gen)):
                msg_out[i + j] ^= gf_mul(gen[j], coef)
    return list(msg_in) + msg_out[len(msg_in):]


def rs_calc_syndromes(msg, nsym):
    """Evaluate the received word at alpha^0 .. alpha^(nsym-1)."""
    return [gf_poly_eval(msg, GF_EXP[i]) for i in range(nsym)]


def rs_find_error_locator(synd, nsym):
    """Berlekamp-Massey: derive the error locator polynomial L(x)."""
    err_loc = [1]
    old_loc = [1]
    for i in range(nsym):
        delta = synd[i]
        for j in range(1, len(err_loc)):
            delta ^= gf_mul(err_loc[-(j + 1)], synd[i - j])
        old_loc = old_loc + [0]
        if delta != 0:
            if len(old_loc) > len(err_loc):
                new_loc = gf_poly_scale(old_loc, delta)
                old_loc = gf_poly_scale(err_loc, gf_inv(delta))
                err_loc = new_loc
            err_loc = gf_poly_add(err_loc, gf_poly_scale(old_loc, delta))
    while err_loc and err_loc[0] == 0:
        del err_loc[0]
    return err_loc


def rs_find_errors(err_loc_rev, nmess):
    """Chien search: positions of errors, counted from the start."""
    errs = len(err_loc_rev) - 1
    pos = []
    for i in range(nmess):
        if gf_poly_eval(err_loc_rev, GF_EXP[i % 255]) == 0:
            pos.append(nmess - 1 - i)
    if len(pos) != errs:
        raise ValueError(
            "Chien: found %d roots, expected %d" % (len(pos), errs))
    return pos


def rs_find_errata_locator(coef_pos):
    """Errata locator in ascending order: prod (1 + X_i * x)."""
    e_loc = [1]
    for i in coef_pos:
        e_loc = gf_poly_mul(e_loc, gf_poly_add([1], [GF_EXP[i], 0]))
    return e_loc


def rs_find_error_evaluator(synd_rev, err_loc, nsym):
    """Error evaluator polynomial Omega = (S * Lambda) truncated to nsym."""
    prod = gf_poly_mul(synd_rev, err_loc)
    return prod[len(prod) - (nsym + 1):]


def rs_correct_errata(msg_in, synd, err_pos):
    """Forney algorithm (pure ascending convention).

    e_i = X_i * Omega(X_i^-1) / Lambda'(X_i^-1).  All polynomials are
    kept internally in ASCENDING order of degree.
    """
    nmess = len(msg_in)
    coef_pos = [nmess - 1 - p for p in err_pos]
    Xs = [GF_EXP[c % 255] for c in coef_pos]
    nsym = len(synd)

    # Lambda in ascending order: Pi(1 + X_i * x)
    lam = rs_find_errata_locator(coef_pos)[::-1]

    # Omega = (S * Lambda) mod x^nsym   (ascending)
    omega = gf_poly_mul(list(synd), lam)[:nsym]

    # formal derivative of Lambda: odd indices
    lam_d = [0] * max(1, len(lam) - 1)
    for i in range(1, len(lam)):
        if i % 2 == 1:
            lam_d[i - 1] = lam[i]

    E = [0] * nmess
    for i, Xi in enumerate(Xs):
        Xi_inv = gf_inv(Xi)
        num = gf_poly_eval(omega[::-1], Xi_inv)
        den = gf_poly_eval(lam_d[::-1], Xi_inv)
        E[err_pos[i]] = gf_div(gf_mul(Xi, num), den)
    return [m ^ e for m, e in zip(msg_in, E)]


def rs_correct_msg(msg_in, nsym):
    """Correct up to floor(nsym/2) symbol errors in one block.

    Returns the data symbols only.  Raises ValueError when the number of
    errors exceeds the correction capacity (or decoding otherwise fails
    to verify).
    """
    if len(msg_in) > 255:
        raise ValueError("block too long for RS")
    msg = list(msg_in)
    synd = rs_calc_syndromes(msg, nsym)
    if max(synd) == 0:
        return msg[:-nsym]
    err_loc = rs_find_error_locator(synd, nsym)
    errs = len(err_loc) - 1
    if errs == 0:
        raise ValueError("RS: unexpected locator state")
    if 2 * errs > nsym:
        raise ValueError(
            "RS: too many errors (%d errors, capacity %d)"
            % (errs, nsym // 2))
    err_pos = rs_find_errors(err_loc[::-1], len(msg))
    msg = rs_correct_errata(msg, synd, err_pos)
    if max(rs_calc_syndromes(msg, nsym)) != 0:
        raise ValueError("RS: correction failed verification")
    return msg[:-nsym]
