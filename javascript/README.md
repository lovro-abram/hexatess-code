# Hexatess Code — JavaScript encoder

A pure-JavaScript, **zero-dependency** encoder for Hexatess Code
(specification v0.3).  It is a 1:1 port of the reference Python
implementation and produces **byte-identical symbols** for uncompressed
payloads; compressed payloads use a self-contained fixed-Huffman DEFLATE
compressor that any spec-conforming inflator (including Python's `zlib`)
decodes.

## Files

| File | Purpose |
|------|---------|
| `hexatess-encoder.js` | The library (UMD: browser global `Hexatess` + Node `require`) |
| `demo.html` | Self-contained encoder playground — open directly in a browser |
| `test_encoder.js` | Conformance tests against `test_vectors/vectors_v0.3.json` |
| `package.json` | Metadata for a future npm release |

## Usage — browser

```html
<script src="hexatess-encoder.js"></script>
<script>
  var out = Hexatess.encode("Hello, Hexatess!", { ecPct: 30 });
  document.body.innerHTML = Hexatess.renderSVG(out.grid);
  // out.params = { rmax, mask, ec, blocks, dataLen, compressed }
</script>
```

`demo.html` does all of this already — double-click it (no server needed).

## Usage — Node.js

```js
const Hexatess = require("./hexatess-encoder.js");

const { grid, params } = Hexatess.encode("Zdravo 🐝", { ecPct: 25 });
console.log(params);            // { rmax: 8, mask: 4, ec: 25, ... }
console.log(Hexatess.renderSVG(grid));   // SVG string
```

## API

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

## Conformance status

- **10/10 uncompressed vectors byte-identical** (grid + header + mask +
  data length) with `test_vectors/vectors_v0.3.json` — run
  `node test_encoder.js` (92 checks).
- **Cross-validated against the Python decoder**: every JS-encoded
  symbol — including deflate-compressed payloads, emoji, binary-ish and
  empty inputs — decodes to the original text; JS DEFLATE streams
  inflate with Python's `zlib`; forced-mask (0–7) and EC-sweep
  (5–90) encodes are byte-identical to the Python encoder
  (`scripts/preveri_js_kodirnik.py` in the development workspace).
- Compressed payload sizes are encoder-specific (the spec accepts any
  valid RFC 1950 stream); the compact fixed-Huffman compressor may
  store slightly more bytes than Python's `zlib -9` on natural text,
  and occasionally fewer (e.g. 80 digits: 20 B vs 21 B).
- A JavaScript **decoder** is planned as the next step, together with
  the hosted web playground.

## Rendering notes

The SVG renderer draws the same pointy-top hexagonal lattice as the
Python renderer (`x = s·√3·(q + r/2)`, `y = s·1.5·r`), with the same
default colors (`dark #181612` = RGB 24,22,18) and a 1.5-module quiet
zone.  `demo.html` additionally exports PNG via canvas with 3×
supersampling, mirroring the Python PNG pipeline.
