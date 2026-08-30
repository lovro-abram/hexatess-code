# Contributing to Hexatess Code

Thank you for helping an experimental format grow! 🐝

## Ground rules

1. **The specification is the contract.** Behavioural changes must be
   reflected in `SPECIFICATION.md` in the same pull request. If the
   change is breaking, it targets the next minor/major version and
   must be described in the spec's §11 (design notes / candidates)
   first.
2. **Conformance vectors are sacred.** If your change alters any byte
   of any generated symbol, the vectors in
   `test_vectors/vectors_v0.2.json` must be regenerated
   (`python test_vectors/generate_vectors.py --write`) and the reason
   must be documented. Vectors are only regenerated for new spec
   versions, never silently.
3. **Tests pass, always.** `pytest` must be green; PRs that add
   features without tests will be asked to add them.

## Development setup

```bash
git clone https://github.com/lovro-abram/hexatess-code
cd hexatess-code
pip install -e .[dev]
pytest
```

## Good first issues

These are the highest-value contributions for making the format
adoptable:

* **JavaScript/TypeScript SDK** — port the encoder + renderer to the
  browser; verify against `test_vectors/vectors_v0.2.json`.
* **Camera decoder (Python or JS)** — bullseye detection (concentric
  alternating ring search) + orientation from the ring-5 key pair +
  perspective correction; the spec's §10 describes the reference
  decode procedure.
* **Erasure decoding** — mark blob-occluded modules as erasures and
  double the correction capacity (see spec §11).
* **Documentation & diagrams** — annotate the symbol anatomy, produce
  SVG figures for the spec.

## Project layout

```
src/hexatess/      reference implementation (pure Python + Pillow)
  galois.py           GF(256) field
  reedsolomon.py      RS codec (BM + Chien + Forney)
  geometry.py         hex lattice, rings, spiral helpers
  header.py           mode message, block planning, constants
  masks.py            mask stream + selection
  encoder.py          encode(text) -> grid
  decoder.py          decode(grid) -> text
  render.py           PNG rendering + ideal sampling
  resilience.py       noise/blob robustness harness
tests/                pytest suite (2,500+ tests)
test_vectors/         conformance vectors + generator
SPECIFICATION.md      format specification (the contract)
```

## Versioning

Semver. **Spec version** and **library version** move together but are
tracked separately (`SPEC_VERSION` vs `__version__` in
`src/hexatess/__init__.py`): patch releases may fix the library
without touching the spec; any symbol-format change bumps the spec
minor (additive) or major (breaking).

## License

By contributing you agree your contributions are licensed under MIT
(code) / CC-BY-4.0 (specification and vectors).
