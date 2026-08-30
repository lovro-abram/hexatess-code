# Changelog

All notable changes to Hexatess Code are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/);
versioning follows semver. **Spec** = symbol format version,
**lib** = reference implementation version.

## [0.2.0] — 2026-08-30

### Changed (spec 0.2) — BREAKING
- **Bullseye centre polarity flipped: the centre module is now DARK**
  (`bit = 1 − (k mod 2)` for finder rings 0–4). Rationale: a solid
  high-contrast core markedly improves finder detectability under
  blur and low-resolution imaging, and matches the finder conventions
  of Aztec Code and MaxiCode. Everything else — key ring, header,
  Reed–Solomon, masks, spiral serialization, capacities — is unchanged.
- Conformance vectors regenerated: `test_vectors/vectors_v0.2.json`
  (supersedes `vectors_v0.1.json`). Symbols encoded with v0.1 are not
  compatible with v0.2 decoders and vice versa.

## [0.1.0] — 2026-08-30

### Renamed (pre-release)
- Project renamed **Medena koda / Honeycomb Code → Hexatess Code**
  (Slovenian: *Hexatess Koda*). Package `hexatess`, distribution
  `hexatess-code`, CLI `hexatess`. Symbol format and conformance
  vectors unchanged apart from payload strings used inside test
  vectors (regenerated).

### Added (spec 0.1)
- Initial symbol format: hexagonal lattice (pointy-top, axial
  coordinates), bullseye finder rings 0–4 (bit = ring parity, light
  centre), orientation key ring 5 (two adjacent dark cells at
  canonical positions 0–1), spiral serialization from ring 6.
- Reed-Solomon over GF(256) with primitive polynomial 0x11D:
  systematic encoder, BM/Chien/Forney decoder.
- Continuous error-correction budget 5–90 % (step 5), independent
  blocks ≤ 50 data bytes, balanced block sizes.
- Double-protected 10-byte mode message (RS(5,5), unmasked).
- 8 deterministic LCG masks with balance/repetition auto-selection.
- PNG renderer (pointy-top hexagons, 3× supersampling, quiet zone)
  and ideal grid re-sampler.
- Conformance vectors `test_vectors/vectors_v0.1.json`
  (12 encode vectors, 6 decode vectors incl. damaged and
  expected-failure cases).

### Added (lib 0.1.0)
- Public API: `encode`, `decode`, `render`, `sample_grid_from_image`,
  `run_tests` plus full low-level surface (field, RS, geometry,
  header, masks).
- CLI (`hexatess-code`) with encode, demo and robustness modes.
- Test suite: 2,544 pytest tests (field algebra, RS round-trips,
  geometry identities, header round-trips, mask properties,
  end-to-end codec, conformance vectors, render self-decode,
  robustness statistics).

### Known limitations (candidates for 0.2)
- No camera decoder (ideal upright sampling only).
- Capacity capped at 329 bytes (EC 5) by the 31-ring radius limit.
- Bullseye centre is light (kept for v0.1 conformance; dark centre
  under consideration).
