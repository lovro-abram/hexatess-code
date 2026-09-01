# Hexatess Code Specification — Version 0.3

**Status:** Stable draft (reference implementation available)
**Date:** 2026-09-01
**License:** CC-BY-4.0 (this document); reference code under MIT

Hexatess Code is an experimental two-dimensional
barcode built on a **hexagonal module grid** with a hexagonal bullseye
finder pattern, spiral serialization from the centre outwards, a
Reed-Solomon protected header and a **continuously selectable
error-correction budget of 5–90 %** (Aztec-style).

This document contains everything needed to implement an independent
encoder or decoder in any language. The key words MUST, MUST NOT,
SHOULD and MAY are to be interpreted as described in RFC 2119.

> **What changed in v0.3.** One formerly reserved header bit is now
> the **payload compression flag** (§4.3): when set, the payload is a
> zlib stream (RFC 1950) of the UTF-8 text. Symbols produced under
> the v0.2 rules remain valid v0.3 symbols (flag = 0), so the change
> is strictly additive.

> **Design heritage.** The architecture deliberately follows proven
> ideas: the bullseye + spiral layout follows Aztec Code (ISO/IEC
> 24778), independent RS blocks with ≤ 50 data bytes follow Data
> Matrix / Aztec practice, and the GF(256) field with primitive
> polynomial 0x11D follows QR Code and Aztec. The hexagonal grid
> follows MaxiCode (ISO/IEC 16023) — extended, unlike MaxiCode, to
> variable-size, high-capacity symbols.

---

## 1. Conventions and terminology

* **Module** — one hexagonal cell of the grid; its value is a **bit**:
  `1` = dark (printed), `0` = light (background).
* **Axial coordinates** `(q, r)` — integer coordinates of a module.
  The six neighbour directions in fixed traversal order are:

  ```
  DIRS = [(+1, 0), (+1, -1), (0, -1), (-1, 0), (-1, +1), (0, +1)]
  ```

* **Ring `k`** — the set of modules at *hex distance* `k` from the
  origin, where hex distance is `max(|q|, |r|, |q + r|)`.
  Ring 0 is the single origin module `(0, 0)`.
* **Canonical ring order** — ring `k ≥ 1` starts at module `(-k, +k)`
  and then takes `k` steps in each direction of `DIRS` in order,
  appending every visited module. Ring `k` therefore contains `6k`
  modules. Pseudocode:

  ```
  function hex_ring(k):
      if k = 0: return [(0, 0)]
      cells ← []
      (q, r) ← (-k, +k)
      for d in 0 .. 5:
          repeat k times:
              append (q, r) to cells
              (q, r) ← (q, r) + DIRS[d]
      return cells
  ```

* **Radius of a symbol** — the largest ring index present, `rmax`.
* The number of modules within radius `n` is the centered hexagonal
  number `3n(n+1) + 1`.

## 2. Symbol structure

A Hexatess Code symbol consists of:

| Region        | Rings        | Content                                        |
|---------------|--------------|------------------------------------------------|
| Bullseye      | 0 … 4        | finder pattern, `bit = 1 − (k mod 2)`          |
| Key ring      | 5            | orientation key (see §2.2)                     |
| Data region   | 6 … rmax     | header + masked payload, spiral order (§3, §4) |

`rmax` MUST be between 7 and 31. The data region of radius `rmax`
contains `3·rmax·(rmax+1) + 1 − 91` modules.

### 2.1 Bullseye finder

For every module of ring `k`, `0 ≤ k ≤ 4`, set `bit = 1 − (k mod 2)`.
Consequence (v0.2): the **centre module is DARK** (ring 0 → 1),
ring 1 is light, ring 2 dark, ring 3 light, ring 4 dark.
*Note:* v0.1 used the opposite polarity (light centre, `bit = k mod 2`).
The dark centre improves finder detectability — it gives the bullseye
a solid high-contrast core that survives blur and low-resolution
imaging, matching the finder conventions of Aztec Code and MaxiCode.
The change is format-breaking; conformance vectors for v0.1 are
superseded.

### 2.2 Orientation key (ring 5)

All 30 modules of ring 5 are LIGHT (`0`), **except** the first two
modules in canonical ring order — `(−5, +5)` and `(−4, +5)` — which
are DARK (`1`). The pair breaks the 60-fold rotational symmetry of the
hexagonal lattice and defines the spiral start direction for camera
decoders: the vector from the symbol centre to the key pair points
"backwards along the spiral start".

## 3. Data region and spiral serialization

Payload bits are placed in **spiral order**: all modules of ring 6 in
canonical order, then ring 7, and so on up to ring `rmax`. The data
region therefore contains, in order:

```
data_cells = concat(hex_ring(k) for k = 6 .. rmax)
```

Bit `i` of the full bitstream (§4) is written to `data_cells[i]`. If
the bitstream is shorter than the data region, the remaining modules
MUST be set to the alternating padding pattern `0, 1, 0, 1, …`
(indexed from 0 at the first empty module).

## 4. Bitstream structure

```
+--------------------+-----------------------------------+
| mode message       | payload                           |
| 80 bits (10 bytes) | (data + ECC + padding)            |
| never masked       | masked (§6)                       |
+--------------------+-----------------------------------+
```

### 4.1 Mode message (header)

5 data bytes, each protected by a separate Reed-Solomon code (§5),
giving 10 bytes = 80 bits. Bit layout, MSB first:

| Byte | Bits   | Field                          | Range     |
|------|--------|--------------------------------|-----------|
| 0    | 5      | `rmax` (symbol radius)         | 7 … 31    |
| 0    | 3      | `mask_id`                      | 0 … 7     |
| 1    | 5      | `ec_pct / 5`                   | 1 … 18    |
| 1    | 3      | `block_count >> 5` (high)      | 0 … 7     |
| 2    | 5      | `block_count & 0x1F` (low)     | —         |
| 2    | 3      | `data_len >> 9` (high)         | 0 … 7     |
| 3    | 8      | `data_len >> 1` (middle)       | —         |
| 4    | 1      | `data_len & 1` (low, leftmost) | —         |
| 4    | 1      | `compressed` (v0.3, §4.3)      | 0 … 1     |
| 4    | 6      | padding (zero)                 | 0         |

* `ec_pct` MUST be a multiple of 5 between 5 and 90 (only `ec_pct/5`
  is stored).
* `data_len` is the stored payload byte length (§4.3), up to 4095.
* The mode message is **never masked** — it contains the mask id.
* In v0.2 bit 6 of byte 4 was padding (zero); v0.3 defines it as the
  compression flag. Decoders SHOULD treat unknown flag values as a
  corrupt symbol.

Pseudocode (packing):

```
b0 = (rmax << 3) | mask_id
b1 = (ecq << 3) | (block_count >> 5)          # ecq = ec_pct / 5
b2 = ((block_count & 0x1F) << 3) | (data_len >> 9)
b3 = (data_len >> 1) & 0xFF
b4 = ((data_len & 1) << 7) | (compressed << 6)
mode_data = [b0, b1, b2, b3, b4]
mode = RS_encode(mode_data, ecc=5)            # 10 bytes total
```

### 4.2 Payload layering

Let `data` be the UTF-8 payload (`data_len` bytes) and `blocks` the
block plan (§5.2). The unmasked payload bitstream is:

1. **Data part:** the bytes of all blocks in block order
   (block 0 data, block 1 data, …),
2. **ECC part:** the Reed-Solomon ECC symbols of all blocks in block
   order (block 0 ECC, block 1 ECC, …),
3. **Padding:** alternating `0, 1, 0, 1, …` until the data region is
   exactly filled.

Note the interleaving level: *all data of all blocks first, then all
ECC of all blocks* — each group internally in block order.

### 4.3 Payload compression (v0.3)

Bit 6 of header byte 4 selects the payload byte stream:

* `compressed = 0` — the payload bytes are the raw UTF-8 text
  (the v0.2 layout). `data_len` is the text length in bytes.
* `compressed = 1` — the payload bytes are a **zlib stream
  (RFC 1950, DEFLATE)** of the UTF-8 text. `data_len` is the length
  of the *stored* stream; the encoder SHOULD use the highest
  practical compression level (the reference uses zlib level 9).
  After Reed-Solomon recovery the decoder MUST inflate the stream
  and then interpret the result as UTF-8.

Encoders SHOULD set the flag only when it strictly reduces the stored
length (short payloads grow from the stream overhead); the reference
`compress="auto"` rule is *compress iff `len(zlib(text)) <
len(text)`*. Decoders MUST support both modes. A zlib stream that
fails to inflate MUST be rejected as a corrupt symbol.

## 5. Error correction

### 5.1 Reed-Solomon over GF(256)

* Field: GF(2^8) with primitive polynomial
  **x^8 + x^4 + x^3 + x^2 + 1 = 0x11D**, generator α = 2
  (identical to QR Code and Aztec Code).
* Code: **systematic** RS, generator polynomial
  `g(x) = ∏_{i=0}^{nsym−1} (x − α^i)`.
* Encoding: polynomial long division of `(m(x) · x^nsym)` by `g(x)`;
  the codeword is `data || remainder` (nsym trailing ECC symbols).
* Decoding: syndromes → Berlekamp–Massey locator → Chien search →
  Forney magnitudes. A block MUST be rejected if the number of found
  errors exceeds `⌊nsym/2⌋` or if the corrected word fails syndrome
  verification.

### 5.2 Block plan

The payload is split into independent RS blocks, each carrying at most
**50 data bytes**:

```
function plan_blocks(data_len, ec_pct):
    if data_len = 0: return [(0, 2)]
    bc ← ceil(data_len / 50)
    (base, extra) ← divmod(data_len, bc)      # balanced block sizes
    blocks ← []
    for i in 0 .. bc-1:
        size ← base + (1 if i < extra else 0)
        ecc  ← max(2, ceil(size · ec_pct / 100))
        ecc  ← min(ecc, 255 − size)           # hard RS limit
        append (size, ecc) to blocks
    return blocks
```

`block_count` (the number of blocks) MUST be ≤ 255; combined with the
12-bit `data_len` field and the 31-ring radius limit this yields the
practical capacity of §8.

The mode message itself is a single RS block with 5 data bytes and
5 ECC symbols (corrects up to 2 byte errors).

## 6. Masking

The payload bitstream (§4.2, data + ECC + padding, *before* header
placement) is XORed bit-by-bit with a deterministic pseudo-random
stream selected from 8 candidates:

```
function mask_bit(index, mask_id):            # index = position in payload
    x = (index · 1103515245 + 12345 + mask_id · 2654435761) & 0x7FFFFFFF
    x = x XOR (x >> 13)
    return (x >> 19) & 1
```

Mask selection SHOULD evaluate all 8 masks and minimise the penalty

```
score(mask) = |2·dark − total|               # balance term
            + count(adjacent equal pairs)    # repetition term
```

with ties resolving to the **lowest** mask id. Encoders MAY force a
specific mask; decoders MUST honour the mask id in the header.

## 7. Encoding procedure

1. Validate `ec_pct` (multiple of 5, 5…90); encode the text to UTF-8.
2. Optionally compress (§4.3): when compression is enabled and
   strictly reduces the length, replace the byte string with its
   zlib stream and set `compressed = 1`; in both cases
   `data_len ≤ 4095` counts the stored bytes.
3. Compute `blocks = plan_blocks(data_len, ec_pct)`.
4. Compute the required bit count
   `need = 80 + 8 · (data_len + Σ ecc)` and the smallest
   `rmax ∈ 7…31` with `modules(6..rmax) ≥ need` (or honour a caller
   minimum radius).
5. Build the unmasked payload stream (§4.2).
6. Select and apply a mask (§6).
7. Build and place the mode message with the final mask id.
8. Place header + masked payload in spiral order (§3); pad the tail.
9. Stamp bullseye (§2.1) and key ring (§2.2).

## 8. Capacity

Data-region modules and maximum payload byte counts (rounded down by
the exact block rule of §5.2):

| rings (rmax) | modules | EC 5 | EC 30 | EC 55 | EC 90 |
|---|---|---|---|---|---|
| 8   | 126  | 3   | 3   | 3   | 2   |
| 10  | 240  | 18  | 15  | 12  | 10  |
| 12  | 378  | 35  | 28  | 23  | 19  |
| 14  | 540  | 53  | 43  | 36  | 30  |
| 17  | 828  | 87  | 71  | 59  | 48  |
| 20  | 1170 | 127 | 103 | 87  | 71  |
| 24  | 1710 | 191 | 155 | 130 | 106 |
| 28  | 2346 | 265 | 216 | 181 | 148 |
| 31  | 2886 | 329 | 266 | 225 | 183 |

The 12-bit length field allows up to 4095 bytes, but the radius
limit (31 rings) caps capacity at **329 bytes (EC 5)**. Larger radii
are a candidate extension.

With the v0.3 compression flag the *effective text* capacity is
considerably higher for compressible content: e.g. an 849-byte
Slovene paragraph stores in 203 bytes and fits at rmax 28 (raw it
exceeds the radius limit), and a 250-byte repetitive payload stores
in 12 bytes. Incompressible data (random bytes, already-compressed
text) is unaffected.

## 9. Rendering recommendations

* Modules are **pointy-top** hexagons. With module radius `s`, the
  centre of module `(q, r)` maps to
  `x = s·√3·(q + r/2)`, `y = s·1.5·r`.
* Corners of a module lie at angles `60°·i − 30°`, `i = 0…5`.
* Hexagons SHOULD be drawn at ≥ 99 % of nominal size to avoid hairline
  gaps between adjacent dark modules; the reference draws at 99.5 %
  with 3× supersampling.
* Quiet zone MUST be ≥ 1 module on all sides; the reference default is
  1.5 modules.
* Dark/light contrast SHOULD be ≥ 40 % (the reference uses near-black
  `rgb(24, 22, 18)` on white).

## 10. Decoding procedure (reference)

1. Detect the hexagonal bullseye (concentric alternating rings) and
   the key pair on ring 5; establish centre, scale and rotation.
2. Sample every data-region module; build the bitstream in spiral
   order (§3).
3. Read the 80-bit mode message; RS-correct it (capacity: 2 byte
   errors); unpack parameters (§4.1). Reject the symbol if
   correction fails.
4. Unmask the payload with `mask_id` (§6).
5. Rebuild the block plan (§5.2) from `data_len` and `ec_pct`;
   RS-correct each block independently; reject on failure.
6. If the compression flag (§4.3) is 1, inflate the payload with
   zlib (RFC 1950); reject the symbol if inflation fails.
7. Decode the payload bytes as UTF-8.

## 11. Design notes and future candidates

* **Centre polarity (resolved in v0.2).** The bullseye centre is DARK
  (`bit = 1 − (k mod 2)`), chosen for stronger detectability; the
  opposite light-centre polarity of v0.1 is deprecated.
* **Erasure decoding.** Modules occluded by a detected blob can be
  declared erasures, doubling correctable symbol counts (RS corrects
  `nsym` erasures vs `nsym/2` errors). Not part of v0.3.
* **Camera decoding (shipped in lib v0.3.0).** The symbol format is
  unchanged; the reference repository now ships an optional photo
  decoder (`hexatess.camera`, the `[camera]` extra).  It locates the
  bullseye under merged-blob and illumination hazards, fits a
  homography on the 91 known finder cells, disambiguates the
  canonical frame with the RS-protected header across all six
  60-degree model rotations, refits a polynomial correction field on
  the 171 known cells (finder + verified header), and samples with a
  local adaptive threshold.  Note for implementers: the two-cell key
  alone is too weak to pin the canonical frame — a conformant *photo*
  decoder should validate the frame via the header, exactly like the
  reference does.  Ideal-grid decoding (§8) is unaffected.
* **Larger radii.** Extending `rmax` beyond 31 requires only widening
  the header's radius field (a breaking change).
* **Other compressors.** zlib (RFC 1950) was chosen for v0.3 because
  every ecosystem has a mature inflate implementation; the flag field
  leaves room for future mode bits (e.g. bzip or a text model) but
  modes MUST be introduced one bit at a time so old decoders fail
  cleanly instead of mis-decoding.
* **Mask quality.** The LCG mask is fast and deterministic but not
  optimized against any adversarial pattern class; penalty terms may
  be extended in a future minor revision *without* breaking decoders
  (selection is an encoder-side choice).

## 12. Conformance

An implementation is conformant with this specification if, for every
vector in `test_vectors/vectors_v0.3.json`:

1. its encoder produces the recorded symbol parameters, mode message
   bytes and canonical grid serialization for the given input; and
2. its decoder returns the recorded text for the recorded grids,
   including the deterministically damaged ones (ECC correction) and
   the recorded decode failure.

**Canonical grid serialization:** bits ordered by ring 0…rmax, within
each ring in canonical order (§1); packed MSB-first into bytes,
right-padded with zero bits to a byte boundary; written as lowercase
hexadecimal.

## Appendix A — Constants

| Constant        | Value | Meaning                                |
|-----------------|-------|----------------------------------------|
| `GF_PRIM_POLY`  | 0x11D | GF(256) primitive polynomial           |
| `BULLSEYE_RINGS`| 4     | finder rings (0…4)                     |
| `KEY_RING`      | 5     | orientation key ring                   |
| `DATA_RING0`    | 6     | first payload ring                     |
| `MAX_RINGS`     | 31    | radius limit (v0.2)                    |
| `BLOCK_DATA_MAX`| 50    | data bytes per RS block                |
| `MODE_BYTES`    | 5     | header data bytes                      |
| `MODE_ECC`      | 5     | header ECC symbols                     |
| `MODE_BITS`     | 80    | header bit length                      |
| `MIN/MAX_EC_PCT`| 5 / 90| EC budget bounds (step 5)              |
| `MAX_DATA_BYTES`| 4095  | length-field limit                     |
| masks           | 8     | mask ids 0…7                           |
