# Hexatess Code — JavaScript encoder & decoder

Pure-JavaScript, **zero-dependency** encoder **and decoder** for
Hexatess Code (specification v0.3).  Both are 1:1 ports of the reference
Python implementation: the encoder produces **byte-identical symbols**
for uncompressed payloads (compressed payloads use a self-contained
fixed-Huffman DEFLATE compressor that any spec-conforming inflator,
including Python's `zlib`, decodes), and the decoder reads back any
conforming symbol — including those written by Python's `zlib -9`
(dynamic-Huffman DEFLATE).

The browser playground **`demo.html` lives at the repository root**
(one level up) — double-click it, no server needed: live encoding with
SVG/PNG export, instant decode round trip, and decoding of uploaded
clean, upright symbol images.

## Files

| File | Purpose |
|------|---------|
| `hexatess-encoder.js` | Encoder library (UMD: browser global `Hexatess` + Node `require`) |
| `hexatess-decoder.js` | Decoder library (browser global `HexatessDecode`, merged into `Hexatess`; Node `require`) |
| `../demo.html` | Playground — encode + decode, at the repository root |
| `test_encoder.js` | Encoder conformance tests (`node test_encoder.js`) |
| `test_decoder.js` | Decoder conformance tests (`node test_decoder.js`) |
| `package.json` | Metadata for a future npm release |

## Usage — browser

```html
<script src="javascript/hexatess-encoder.js"></script>
<script src="javascript/hexatess-decoder.js"></script>
<script>
  var out = Hexatess.encode("Hello, Hexatess!", { ecPct: 30 });
  document.body.innerHTML = Hexatess.renderSVG(out.grid);

  var dec = Hexatess.decode(out.grid);          // merged from HexatessDecode
  console.log(dec.text);                        // "Hello, Hexatess!"
  console.log(dec.stats);                       // { rmax, mask, ec, blocks,
                                                //  dataLen, compressed, repairBits }
</script>
```

## Usage — Node.js

```js
const Hexatess = require("./hexatess-encoder.js");
const HexatessDecode = require("./hexatess-decoder.js");

const { grid, params } = Hexatess.encode("Zdravo 🐝", { ecPct: 25 });
const { text, stats } = HexatessDecode.decode(grid);
console.log(text === "Zdravo 🐝", stats.repairBits);   // true 0
```

## Encoder API

### `encode(input, options?) → { grid, params }`

| Option | Default | Meaning |
|--------|---------|---------|
| `input` | — | `string` (UTF-8 encoded) or `Uint8Array` of bytes |
| `options.ecPct` | `30` | Error-correction budget, 5–90 in steps of 5 |
| `options.mask` | `"auto"` | Force mask 0–7, or let the encoder pick |
| `options.minRings` | — | Force a minimum symbol radius (1–31) |
| `options.compress` | `"auto"` | `"auto"` = deflate when strictly smaller; `true` = force; `false` = raw UTF-8 (byte-identical to spec v0.2 symbols) |

`grid` is a `Map` keyed by axial coordinates `"q,r"` with values `0|1`
(1 = dark module).  `params` reports `rmax`, `mask`, `ec`, `blocks`
(`[dataBytes, eccBytes]` pairs), `dataLen` (stored bytes) and
`compressed`.

### `renderSVG(grid, options?) → string`

Options: `size` (module radius px, default 18), `quiet` (quiet zone in
modules, default 1.5), `dark`, `light` (CSS colors), `background`
(`false` disables the light rectangle).

### Helpers

`canonicalHex(grid, rmax)` — canonical bitstream hex (the conformance
format used by `test_vectors/vectors_v0.3.json`).
`gridToJSON(grid)` — plain object `{"q,r": bit}`.
`Hexatess.internals` — GF(256), Reed-Solomon, header packing, masks,
geometry and the DEFLATE compressor, exposed for testing and for
third-party implementations.

## Decoder API

### `decode(grid) → { text, stats }`

`grid` is the encoder's `Map` or a plain object with `"q,r"` keys.
Throws on uncorrectable damage, damaged zlib streams or invalid UTF-8.
`stats` mirrors the Python decoder: `rmax`, `mask`, `ec`, `blocks`,
`dataLen`, `compressed` and `repairBits` (total Hamming distance the
Reed–Solomon layer had to correct inside the data bytes; header and
ECC repairs are absorbed silently).

### `decodeHex(hex, rmax?)`, `gridFromHex(hex, rmax?)`, `payloadToText(bytes, compressed)`

`gridFromHex` parses the canonical conformance hex (`rmax` inferred
from the length when omitted); `decodeHex` = `decode(gridFromHex(...))`.
`payloadToText` inflates (when `compressed`) and strictly validates
UTF-8.  `HexatessDecode.internals` exposes the RS decoder (syndromes →
Berlekamp–Massey → Chien → Forney), the full zlib/DEFLATE inflator and
the strict UTF-8 decoder.

## Conformance status

- **Encoder: 10/10 uncompressed vectors byte-identical** (grid + header
  + mask + data length) with `test_vectors/vectors_v0.3.json` — run
  `node test_encoder.js` (92 checks).
- **Decoder: all 6 decode vectors pass** — clean symbols, two
  deterministically damaged symbols (with exact repair accounting) and
  the expected-failure case — plus round-trips across texts × EC 5–90 ×
  masks 0–7 × compression modes, error injection within and beyond RS
  capacity, the inflator verified against Node's own zlib (levels
  0/1/6/9: stored, fixed and dynamic Huffman) and two-way JS↔Python
  cross-validation.  Run `node test_decoder.js` (136 checks).
- Compressed payload sizes are encoder-specific (the spec accepts any
  valid RFC 1950 stream); the compact fixed-Huffman compressor may
  store slightly more bytes than Python's `zlib -9` on natural text,
  and occasionally fewer (e.g. 80 digits: 20 B vs 21 B).

## Rendering notes

The SVG renderer draws the same pointy-top hexagonal lattice as the
Python renderer (`x = s·√3·(q + r/2)`, `y = s·1.5·r`), with the same
default colors (`dark #181612` = RGB 24,22,18) and a 1.5-module quiet
zone.  `demo.html` additionally exports PNG via canvas with 3×
supersampling, mirroring the Python PNG pipeline, and its Decode panel
scans clean upright symbol images (Otsu thresholding, bullseye-centre
refinement, run-length cell sizing, lattice sampling).
