# Changelog

All notable changes to Hexatess Code are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/);
versioning follows semver. **Spec** = symbol format version,
**lib** = reference implementation version.

## [0.4.1] — 2026-09-05

### Added — pure-JavaScript decoder + playground upgrade
- **`javascript/hexatess-decoder.js`**: the complete decoder in
  zero-dependency plain JavaScript — spiral deserialization, RS-protected
  mode message, mask removal, per-block Reed-Solomon correction
  (syndromes → Berlekamp–Massey → Chien → Forney over GF(256), 0x11D),
  transparent zlib inflation and strict UTF-8 validation.  The inflator
  supports stored, fixed-Huffman **and dynamic-Huffman** DEFLATE blocks,
  so symbols written by Python's `zlib -9` decode as well as those
  written by the project's own fixed-Huffman encoder.
  API: `decode(grid)` → `{text, stats}` (stats mirror the Python
  decoder, including the `repairBits` ledger), plus `decodeHex`,
  `gridFromHex` and `payloadToText`; UMD (browser global
  `HexatessDecode`, merged into `Hexatess` when the encoder is loaded,
  or Node `require`).
- **Conformance**: all 6 decode vectors pass, including the
  deterministically damaged symbols (exact `repairBits` accounting,
  header/ECC flips absorbed silently exactly like Python) and the
  expected-failure case.  Round-trips over texts × EC 5–90 × masks 0–7
  × compression modes; error injection within and beyond RS capacity;
  the inflator verified against Node's own zlib (levels 0/1/6/9 =
  stored, fixed and dynamic Huffman) and against Python-encoded
  compressed symbols; two-way JS↔Python cross-validation.
  `node javascript/test_decoder.js`: 136 checks.
- **`demo.html` moved to the repository root** and upgraded into the
  full playground: the encoder panel is unchanged, and a new **Decode**
  panel can (a) decode the live symbol as an instant round trip and
  (b) decode an uploaded PNG/JPEG/WebP/SVG of a clean, upright symbol —
  a self-contained scanner (Otsu thresholding, bullseye-centre
  refinement, run-length cell-size estimation, hex-lattice sampling
  with size-correction retries) locates and samples the symbol, then
  hands the grid to the JS decoder.  Photographic/tilted capture
  remains the domain of the Python camera pipeline.
- `javascript/test_encoder.js` (92 checks) still green; CI gained a
  JavaScript job running both suites on Node 18.

### Changed
- Version metadata only: Python package 0.4.1, spec stays **v0.3**;
  conformance vectors regenerated (provenance fields only, vector data
  byte-identical).

## [0.4.0] — 2026-09-02

### Added — pure-JavaScript encoder (experimental)
- **`javascript/`**: a zero-dependency encoder for spec v0.3 in plain
  JavaScript (UMD — browser global `Hexatess` and Node `require`),
  a 1:1 port of the Python reference.
  `hexatess-encoder.js` (encode, SVG render, canonical serialization),
  `demo.html` (self-contained browser playground: live preview, EC
  slider, compression and mask controls, SVG/PNG download — works from
  `file://`), `test_encoder.js`, `package.json` (npm release later).
- Conformance: **10/10 uncompressed vectors byte-identical**
  (`grid_hex`, `mode_hex`, mask, data length) against
  `test_vectors/vectors_v0.3.json` (92 JS checks); cross-validated
  with the Python decoder on 23 additional cases including
  deflate-compressed payloads, emoji, binary-ish and empty inputs.
- Self-contained **fixed-Huffman DEFLATE** compressor (RFC 1950/1951)
  with hash-chain LZ77; streams verified with Python's `zlib`.
  Compressed sizes are encoder-specific per the spec — the JS
  compressor stores slightly more than `zlib -9` on natural text and
  occasionally less (80 digits: 20 B vs 21 B).
- API mirrors the Python encoder: `encode(input, {ecPct, mask,
  minRings, compress})` → `{grid, params}`; `renderSVG`,
  `canonicalHex`, `gridToJSON`, plus `internals` (GF(256), RS, header,
  masks, geometry, DEFLATE) for third-party implementations.

## [0.3.1] — 2026-09-01

### Added (spec 0.3) — payload compression
- **zlib payload compression** via a new header flag (byte 4, bit 6;
  the former padding).  Encoders compress automatically whenever that
  strictly reduces the stored length (`compress="auto"` default;
  `compress=False` reproduces byte-identical v0.2 symbols, CLI
  opt-out `--no-compress`).  Decoders inflate transparently.
- Effective text capacity rises accordingly: an 849-byte Slovene
  paragraph stores in 203 bytes and fits at rmax 28 (uncompressed it
  exceeds the radius limit), `"X" × 250` stores in 12 bytes, 80
  digits in 21.  Incompressible payloads are unaffected; the maximum
  *stored* capacity stays 329 bytes (EC 5).
- `unpack_mode_ex` / `payload_to_text` API additions; `encode`
  params and `decode` stats gained `compressed`, and the RS repair
  ledger `repair_bits` is now reported.
- Conformance vectors regenerated for spec 0.3:
  `test_vectors/vectors_v0.3.json` (new cases `max_capacity`
  incompressible raw and `long_text_zlib` natural text).

### Changed — camera decoder speed (~10x)
- The illumination background is now computed at 1/8 resolution
  instead of a full-resolution Gaussian with a ~1800-tap kernel,
  which alone consumed ~85 % of a v0.3.0 scan.  Finder search and
  pose refinement are vectorized (NumPy) and grid sampling is
  batched.  Measured on 12 MP photos: **6-8 s → ≈1 s per scan**
  (0.5-2.5 s on the reference machine, depending on warp; the curled
  transparency dropped to ~0.5 s).  Failed scans are bounded too
  (affine fallback capped, later candidates time-boxed), so an
  unreadable image no longer sweeps thousands of hypotheses for a
  minute.

### Fixed — camera decoder robustness
- **Outer-ring sampling stabilized by padding anchors.**  The tail
  padding of the data region is an alternating 0,1,0,1… pattern known
  as soon as the header passes RS, so those outer-edge cells are used
  as extra anchors for the polynomial correction field.  This removes
  the pure-extrapolation regime on rings beyond the header that could
  produce ~18 scattered sampling errors on slightly warped shots.
- **Mis-decode-proof pose selection.**  The decoder tries the top-3
  finder poses per bullseye candidate and ranks successful decodes by
  their correction ledger (`repair_bits`); only a zero-cost decode
  (sample == valid codeword, unambiguous by the RS distance of 6)
  returns immediately.  This removes a rare but real mis-decode where
  a near-tie pose flip produced scattered bit errors that the limited
  flip search resolved to a *plausible but wrong* payload
  (`'Ba\`Fam)lnnro'` instead of `'@abram.lovro'`).

## [0.3.0] — 2026-08-31

### Added
- **Camera decoder** (`hexatess.camera`, optional extra `[camera]`):
  decode symbols from real photographs — printed labels, foil
  transparencies, screens.  Pipeline: illumination normalization,
  blob-hypothesis finder detection, joint rotation x scale pose
  search, homography fit on the 91 finder cells, local (adaptive)
  threshold sampling, RS-header-judged model-frame disambiguation
  across all six 60° rotations, a polynomial correction field fitted
  on the 171 known cells (finder + RS-verified header), and an
  annulus-ICP / affine fallback chain for strong perspective.
  Dependencies (numpy, opencv-python, scipy) are optional:
  `pip install hexatess-code[camera]`.
- CLI subcommand `hexatess decode-photo IMAGE [IMAGE ...]`.
- New tests: synthetic render → photo-pipeline round-trips (straight,
  rotated 25°, mild perspective + blur).  Skipped automatically when
  the camera extra is not installed.
- Validated on real 12 MP photographs: upright, tilted, rotated and
  combined variants, plus a printed transparency with curl and glare.

### Fixed
- `.github/workflows/ci.yml` trigger branch list corruption
  (`branches: ain]` → `branches: [main]`).

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
