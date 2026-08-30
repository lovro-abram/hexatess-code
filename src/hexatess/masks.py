"""Mask bit generation and automatic mask selection."""

from __future__ import annotations


def mask_bit(index: int, mask_id: int) -> int:
    """Deterministic pseudo-random mask bit (32-bit LCG + xorshift).

    The mask stream is a function of the payload bit position and the
    mask identifier (0..7).  Masking applies to the payload ONLY; the
    mode message is never masked (it carries the mask id itself).
    """
    x = (index * 1103515245 + 12345 + mask_id * 2654435761) & 0x7FFFFFFF
    x ^= x >> 13
    return (x >> 19) & 1


def mask_payload(payload, mask_id: int):
    """XOR ``payload`` bit-by-bit with mask stream ``mask_id``."""
    return [b ^ mask_bit(i, mask_id) for i, b in enumerate(payload)]


def evaluate_mask(masked) -> int:
    """Penalty score of an already-masked bit list (lower is better).

    Score = |2 * dark - total|  (balance penalty)
          + count of adjacent equal-bit pairs  (repetition penalty).
    """
    score = abs(2 * sum(masked) - len(masked))
    for i in range(1, len(masked)):
        if masked[i] == masked[i - 1]:
            score += 1
    return score


def select_mask(payload):
    """Evaluate all 8 masks and return ``(masked_payload, mask_id)``.

    Ties resolve to the lowest mask id, mirroring the reference
    implementation.
    """
    best, best_id, best_score = None, 0, None
    for m in range(8):
        masked = mask_payload(payload, m)
        score = evaluate_mask(masked)
        if best_score is None or score < best_score:
            best, best_id, best_score = masked, m, score
    return best, best_id
