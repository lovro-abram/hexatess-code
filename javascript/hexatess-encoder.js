/*!
 * Hexatess Code — pure-JavaScript encoder (specification v0.3)
 * ============================================================
 *
 * Zero-dependency, plain JavaScript.  Works in the browser
 * (`<script src="hexatess-encoder.js">` → global `Hexatess`)
 * and in Node.js (`require("./hexatess-encoder.js")`).
 *
 * The encoder is a 1:1 port of the reference Python implementation
 * and produces byte-identical symbols for uncompressed payloads
 * (verified against test_vectors/vectors_v0.3.json).  Payload
 * compression uses a self-contained fixed-Huffman DEFLATE compressor
 * (RFC 1950/1951); any spec-conforming inflator — including Python's
 * zlib — decodes the result.
 *
 * Layout summary (spec v0.3):
 *   rings 0..4  hexagonal bullseye finder, ring k filled with 1-(k%2)
 *               (bit 1 = dark module; the centre module is DARK)
 *   ring 5      orientation key: all light except the first two cells
 *               of hex_ring(5) — (-5,5) and (-4,5) — which are dark
 *   rings 6..n  payload bits in spiral order: 80-bit header (unmasked)
 *               followed by the masked payload stream; the unused tail
 *               is padded with an alternating 0,1,... pattern
 *
 * Header (10 bytes = 5 data + 5 Reed-Solomon ECC, never masked):
 *   byte 0: rmax (5 bits)          | mask_id (3 bits)
 *   byte 1: ec_pct/5 (5 bits)      | block_count >> 5 (3 bits)
 *   byte 2: block_count & 0x1F (5) | data_len >> 9 (3 bits)
 *   byte 3: data_len >> 1 & 0xFF (8 bits)
 *   byte 4: data_len & 1 (1 bit)   | compressed (1 bit) | padding (6 bits)
 *
 * Copyright (c) 2026 The Hexatess Code Authors — MIT License.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module !== null && module.exports) {
    module.exports = api;              // CommonJS / Node.js
  } else {
    root.Hexatess = api;               // browser global
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ------------------------------------------------------------------
  // Symbol constants (fixed by the specification)
  // ------------------------------------------------------------------

  var BULLSEYE_RINGS = 4;   // rings 0..4 form the hexagonal bullseye
  var KEY_RING = 5;         // ring 5 is the orientation key
  var DATA_RING0 = 6;       // payload serialization starts at ring 6
  var MAX_RINGS = 31;       // largest permitted symbol radius
  var BLOCK_DATA_MAX = 50;  // max data bytes per independent RS block
  var MODE_BYTES = 5;       // header payload length in bytes
  var MODE_ECC = 5;         // header ECC symbols (fixes up to 2 bytes)
  var MODE_BITS = (MODE_BYTES + MODE_ECC) * 8;   // 80 bits
  var MIN_EC_PCT = 5, MAX_EC_PCT = 90, EC_STEP = 5;
  var MAX_DATA_BYTES = 4095;                     // 12-bit length field
  var COMPRESSED_FLAG = 0x40;                    // header byte 4, bit 6

  var VERSION = "0.4.0";
  var SPEC_VERSION = "0.3";

  // ------------------------------------------------------------------
  // GF(256) — primitive polynomial x^8+x^4+x^3+x^2+1 (0x11D), alpha = 2
  // Same choice as QR Code and Aztec Code.
  // ------------------------------------------------------------------

  var GF_EXP = new Uint8Array(512);
  var GF_LOG = new Uint8Array(256);
  (function buildTables() {
    var x = 1, i;
    for (i = 0; i < 255; i++) {
      GF_EXP[i] = x;
      GF_LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11D;
    }
    for (i = 255; i < 512; i++) GF_EXP[i] = GF_EXP[i - 255];
  })();

  function gfMul(x, y) {
    if (x === 0 || y === 0) return 0;
    return GF_EXP[GF_LOG[x] + GF_LOG[y]];
  }

  function gfDiv(x, y) {
    if (y === 0) throw new Error("division by zero in GF(256)");
    if (x === 0) return 0;
    return GF_EXP[(GF_LOG[x] + 255 - GF_LOG[y]) % 255];
  }

  function gfInv(x) {
    return GF_EXP[(255 - GF_LOG[x]) % 255];
  }

  // Polynomials are arrays of coefficients in DESCENDING degree order
  // ([a, b, c] means a*x^2 + b*x + c).

  function gfPolyScale(p, x) {
    var r = new Array(p.length), i;
    for (i = 0; i < p.length; i++) r[i] = gfMul(p[i], x);
    return r;
  }

  function gfPolyAdd(p, q) {
    var r = new Array(Math.max(p.length, q.length));
    for (var z = 0; z < r.length; z++) r[z] = 0;
    var i;
    for (i = 0; i < p.length; i++) r[i + r.length - p.length] = p[i];
    for (i = 0; i < q.length; i++) r[i + r.length - q.length] ^= q[i];
    return r;
  }

  function gfPolyMul(p, q) {
    var r = new Array(p.length + q.length - 1);
    for (var z = 0; z < r.length; z++) r[z] = 0;
    var i, j;
    for (j = 0; j < q.length; j++)
      for (i = 0; i < p.length; i++)
        r[i + j] ^= gfMul(p[i], q[j]);
    return r;
  }

  function gfPolyEval(p, x) {
    var y = p[0], i;
    for (i = 1; i < p.length; i++) y = gfMul(y, x) ^ p[i];
    return y;
  }

  // ------------------------------------------------------------------
  // Systematic Reed-Solomon encoder (QR/Aztec-style)
  // ------------------------------------------------------------------

  function rsGeneratorPoly(nsym) {
    var g = [1], i;
    for (i = 0; i < nsym; i++) g = gfPolyMul(g, [1, GF_EXP[i]]);
    return g;
  }

  function rsEncodeMsg(msgIn, nsym) {
    if (msgIn.length + nsym > 255)
      throw new Error("block too long for RS over GF(256): " +
                      msgIn.length + " + " + nsym + " > 255");
    var gen = rsGeneratorPoly(nsym);
    var msgOut = [], i, j;
    for (i = 0; i < msgIn.length; i++) msgOut.push(msgIn[i]);
    for (i = 0; i < nsym; i++) msgOut.push(0);
    for (i = 0; i < msgIn.length; i++) {
      var coef = msgOut[i];
      if (coef !== 0)
        for (j = 1; j < gen.length; j++)
          msgOut[i + j] ^= gfMul(gen[j], coef);
    }
    var out = [];
    for (i = 0; i < msgIn.length; i++) out.push(msgIn[i]);
    for (i = msgIn.length; i < msgOut.length; i++) out.push(msgOut[i]);
    return out;
  }

  // ------------------------------------------------------------------
  // Bit / byte helpers (MSB-first bit order everywhere in the symbol)
  // ------------------------------------------------------------------

  function bytesToBits(data) {
    var bits = new Array(data.length * 8), i, j;
    for (i = 0; i < data.length; i++)
      for (j = 0; j < 8; j++)
        bits[i * 8 + j] = (data[i] >> (7 - j)) & 1;
    return bits;
  }

  function bitsToBytes(bits) {
    var out = [], i, j, v;
    for (i = 0; i + 7 < bits.length; i += 8) {
      v = 0;
      for (j = 0; j < 8; j++) v = (v << 1) | bits[i + j];
      out.push(v);
    }
    return out;
  }

  // ------------------------------------------------------------------
  // Mode message (header) and block planning
  // ------------------------------------------------------------------

  function packMode(rmax, maskId, ecPct, blockCount, dataLen, compressed) {
    if (rmax > 31 || maskId > 7 || ecPct % 5 !== 0 || ecPct / 5 > 31 ||
        blockCount > 255 || dataLen > 4095)
      throw new Error("parameters out of mode-message range");
    var ecq = ecPct / 5;
    var b0 = (rmax << 3) | maskId;
    var b1 = (ecq << 3) | (blockCount >> 5);
    var b2 = ((blockCount & 0x1F) << 3) | ((dataLen >> 9) & 0x7);
    var b3 = (dataLen >> 1) & 0xFF;
    var b4 = (dataLen & 1) << 7;
    if (compressed) b4 |= COMPRESSED_FLAG;
    return rsEncodeMsg([b0, b1, b2, b3, b4], MODE_ECC);   // 10 bytes
  }

  function planBlocks(dataLen, ecPct) {
    // Returns an array of [dataBytes, eccBytes] pairs.
    if (dataLen === 0) return [[0, 2]];
    var bc = Math.max(1, Math.ceil(dataLen / BLOCK_DATA_MAX));
    var base = Math.floor(dataLen / bc), extra = dataLen % bc;
    var blocks = [], i;
    for (i = 0; i < bc; i++) {
      var size = base + (i < extra ? 1 : 0);
      var ecc = Math.max(2, Math.ceil((size * ecPct) / 100));
      blocks.push([size, Math.min(ecc, 255 - size)]);
    }
    return blocks;
  }

  // ------------------------------------------------------------------
  // Masking: deterministic pseudo-random stream (32-bit LCG + xorshift)
  // ------------------------------------------------------------------

  function maskBit(index, maskId) {
    var x = (index * 1103515245 + 12345 + maskId * 2654435761) & 0x7FFFFFFF;
    x ^= x >> 13;
    return (x >>> 19) & 1;
  }

  function maskPayload(payload, maskId) {
    var out = new Array(payload.length), i;
    for (i = 0; i < payload.length; i++) out[i] = payload[i] ^ maskBit(i, maskId);
    return out;
  }

  function evaluateMask(masked) {
    // Score = |2*dark - total| (balance) + adjacent equal pairs (runs).
    var sum = 0, i, runs = 0;
    for (i = 0; i < masked.length; i++) sum += masked[i];
    var score = Math.abs(2 * sum - masked.length);
    for (i = 1; i < masked.length; i++)
      if (masked[i] === masked[i - 1]) runs++;
    return score + runs;
  }

  function selectMask(payload) {
    // Evaluates all 8 masks; ties resolve to the lowest mask id.
    var best = null, bestId = 0, bestScore = null, m;
    for (m = 0; m < 8; m++) {
      var masked = maskPayload(payload, m);
      var score = evaluateMask(masked);
      if (bestScore === null || score < bestScore) {
        best = masked; bestId = m; bestScore = score;
      }
    }
    return [best, bestId];
  }

  // ------------------------------------------------------------------
  // Hexagonal geometry (axial coordinates, pointy-top)
  // ------------------------------------------------------------------

  var DIRS = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];

  function hexRing(k) {
    // Cells at hex distance k, canonical order: start at (-k, +k),
    // then k steps in each direction of DIRS.
    if (k === 0) return [[0, 0]];
    var cells = [], q = -k, r = k, d, i;
    for (d = 0; d < 6; d++)
      for (i = 0; i < k; i++) {
        cells.push([q, r]);
        q += DIRS[d][0];
        r += DIRS[d][1];
      }
    return cells;
  }

  function hexDistance(q, r) {
    return Math.max(Math.abs(q), Math.abs(r), Math.abs(q + r));
  }

  function ringCapacity(rFrom, rTo) {
    if (rTo < rFrom) return 0;
    return (3 * rTo * (rTo + 1) + 1) - (3 * (rFrom - 1) * rFrom + 1);
  }

  function hexToPixel(q, r, size) {
    return [size * Math.sqrt(3.0) * (q + r / 2.0), size * 1.5 * r];
  }

  function hexCorner(cx, cy, size, i) {
    var ang = Math.PI / 180.0 * (60.0 * i - 30.0);
    return [cx + size * Math.cos(ang), cy + size * Math.sin(ang)];
  }

  // ------------------------------------------------------------------
  // Payload compression: minimal DEFLATE (fixed Huffman) + zlib wrapper
  //
  // The spec only requires the payload to be a valid zlib (RFC 1950)
  // stream, so any conforming compressor is allowed.  This compact
  // fixed-Huffman implementation with hash-chain LZ77 keeps the
  // library dependency-free; it is validated against Python's zlib.
  // ------------------------------------------------------------------

  var LENGTH_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27,
                     31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195,
                     227, 258];
  var LENGTH_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3,
                      3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
  var DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129,
                   193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097,
                   6145, 8193, 12289, 16385, 24577];
  var DIST_EXTRA = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7,
                    8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];

  function adler32(bytes) {
    var a = 1, b = 0, i;
    for (i = 0; i < bytes.length; i++) {
      a = (a + bytes[i]) % 65521;
      b = (b + a) % 65521;
    }
    return b * 65536 + a;   // (b << 16) | a  — fits in 32 bits
  }

  function BitWriter() {
    this.bytes = [];
    this.acc = 0;
    this.n = 0;
  }
  BitWriter.prototype.putBit = function (b) {           // LSB-first stream
    this.acc |= (b & 1) << this.n;
    if (++this.n === 8) { this.bytes.push(this.acc); this.acc = 0; this.n = 0; }
  };
  BitWriter.prototype.putBits = function (v, count) {   // value, LSB first
    for (var i = 0; i < count; i++) this.putBit((v >>> i) & 1);
  };
  BitWriter.prototype.putCode = function (code, len) {  // Huffman: MSB first
    for (var i = len - 1; i >= 0; i--) this.putBit((code >>> i) & 1);
  };
  BitWriter.prototype.flush = function () {
    if (this.n > 0) { this.bytes.push(this.acc); this.acc = 0; this.n = 0; }
  };

  function lz77Tokens(bytes) {
    // Greedy LZ77 with hash chains (3-byte hash).  Payloads in Hexatess
    // are at most a few KB, so modest chain limits keep this fast.
    var tokens = [];
    var n = bytes.length;
    var HBITS = 16, HSIZE = 1 << HBITS, HMASK = HSIZE - 1;
    var head = new Int32Array(HSIZE);
    var prev = new Int32Array(Math.max(n, 1));
    var i;
    for (i = 0; i < HSIZE; i++) head[i] = -1;
    for (i = 0; i < n; i++) prev[i] = -1;
    var hash = function (p) {
      return ((bytes[p] << 10) ^ (bytes[p + 1] << 5) ^ bytes[p + 2]) & HMASK;
    };
    var pos = 0;
    while (pos < n) {
      var bestLen = 0, bestDist = 0;
      if (pos + 2 < n) {
        var maxLen = Math.min(258, n - pos);
        var cand = head[hash(pos)];
        var chain = 0;
        while (cand >= 0 && chain++ < 64 && pos - cand <= 32768) {
          var len = 0;
          while (len < maxLen && bytes[cand + len] === bytes[pos + len]) len++;
          if (len > bestLen) {
            bestLen = len; bestDist = pos - cand;
            if (len >= maxLen) break;
          }
          cand = prev[cand];
        }
      }
      if (bestLen >= 3) {
        tokens.push([bestLen, bestDist]);
        var end = pos + bestLen;
        while (pos < end) {
          if (pos + 2 < n) { var h = hash(pos); prev[pos] = head[h]; head[h] = pos; }
          pos++;
        }
      } else {
        tokens.push([bytes[pos]]);
        if (pos + 2 < n) { var h2 = hash(pos); prev[pos] = head[h2]; head[h2] = pos; }
        pos++;
      }
    }
    return tokens;
  }

  function lengthCode(len) {
    var i = LENGTH_BASE.length - 1;
    while (LENGTH_BASE[i] > len) i--;
    return i;                       // 0..28 -> code 257+i
  }

  function distCode(dist) {
    var i = DIST_BASE.length - 1;
    while (DIST_BASE[i] > dist) i--;
    return i;                       // 0..29
  }

  function deflateFixed(bytes) {
    var bw = new BitWriter();
    bw.putBit(1);                   // BFINAL = 1
    bw.putBit(1); bw.putBit(0);     // BTYPE = 01 (fixed Huffman)
    var tokens = lz77Tokens(bytes), i;
    for (i = 0; i < tokens.length; i++) {
      var t = tokens[i];
      if (t.length === 1) {                              // literal
        var lit = t[0];
        if (lit < 144) bw.putCode(0x30 + lit, 8);
        else bw.putCode(0x190 + lit - 144, 9);
      } else {                                           // <length, dist>
        var lIdx = lengthCode(t[0]);
        var lc = 257 + lIdx;
        if (lc <= 279) bw.putCode(lc - 256, 7);
        else bw.putCode(0xC0 + lc - 280, 8);
        if (LENGTH_EXTRA[lIdx]) bw.putBits(t[0] - LENGTH_BASE[lIdx], LENGTH_EXTRA[lIdx]);
        var dIdx = distCode(t[1]);
        bw.putCode(dIdx, 5);
        if (DIST_EXTRA[dIdx]) bw.putBits(t[1] - DIST_BASE[dIdx], DIST_EXTRA[dIdx]);
      }
    }
    bw.putCode(0, 7);               // end-of-block (code 256)
    bw.flush();
    return bw.bytes;
  }

  function zlibCompress(bytes) {
    var out = [0x78, 0x01];         // CM=8, CINFO=7, FCHECK valid
    var defl = deflateFixed(bytes), i;
    for (i = 0; i < defl.length; i++) out.push(defl[i]);
    var ad = adler32(bytes);
    out.push((ad >>> 24) & 0xFF, (ad >>> 16) & 0xFF, (ad >>> 8) & 0xFF, ad & 0xFF);
    return out;
  }

  // ------------------------------------------------------------------
  // UTF-8 helpers
  // ------------------------------------------------------------------

  function utf8Bytes(input) {
    if (typeof input === "string") return new TextEncoder().encode(input);
    if (typeof Uint8Array !== "undefined" && input instanceof Uint8Array)
      return input;
    if (Array.isArray(input)) return Uint8Array.from(input);
    throw new Error("encode() expects a string or a byte array");
  }

  // ------------------------------------------------------------------
  // Canonical serialization (matches test_vectors conformance format)
  // ------------------------------------------------------------------

  function key(q, r) { return q + "," + r; }

  function canonicalBits(grid, rmax) {
    var bits = [], k, i, cells, c;
    for (k = 0; k <= rmax; k++) {
      cells = hexRing(k);
      for (i = 0; i < cells.length; i++) {
        c = cells[i];
        bits.push(grid.get(key(c[0], c[1])) || 0);
      }
    }
    return bits;
  }

  function canonicalHex(grid, rmax) {
    var bits = canonicalBits(grid, rmax), out = [], i;
    for (i = 0; i < bits.length; i += 8) {
      var chunk = (i + 8 > bits.length) ? bits.length - i : 8;
      var v = 0, j;
      for (j = 0; j < chunk; j++) v = (v << 1) | bits[i + j];
      v <<= (8 - chunk);
      out.push(v);
    }
    var hex = "";
    for (i = 0; i < out.length; i++) {
      var b = out[i];
      hex += (b < 16 ? "0" : "") + b.toString(16);
    }
    return hex;
  }

  function gridToJSON(grid) {
    var o = {};
    grid.forEach(function (val, k) { o[k] = val; });
    return o;
  }

  // ------------------------------------------------------------------
  // The encoder
  // ------------------------------------------------------------------

  /**
   * Encode text (or raw bytes) into a hexagonal module grid.
   *
   * options:
   *   ecPct    error-correction budget, 5..90 in steps of 5 (default 30)
   *   mask     force a mask 0..7, or "auto" (default "auto")
   *   minRings force a minimum symbol radius 1..31 (default: none)
   *   compress "auto" (default) compresses with deflate whenever that
   *            strictly reduces the stored length; true forces; false
   *            stores raw UTF-8 (byte-identical to spec v0.2 symbols)
   *
   * returns { grid: Map<"q,r", 0|1>,
   *           params: {rmax, mask, ec, blocks, dataLen, compressed} }
   */
  function encode(input, options) {
    var opts = options || {};
    var ecPct = opts.ecPct === undefined ? 30 : opts.ecPct;
    var maskOpt = opts.mask === undefined ? "auto" : opts.mask;
    var minRings = opts.minRings || 0;
    var compress = opts.compress === undefined ? "auto" : opts.compress;

    if (ecPct < MIN_EC_PCT || ecPct > MAX_EC_PCT || ecPct % 5 !== 0)
      throw new Error("ec_pct must be " + MIN_EC_PCT + ".." + MAX_EC_PCT +
                      " in steps of " + EC_STEP);

    var raw = utf8Bytes(input);
    if (raw.length > MAX_DATA_BYTES)
      throw new Error("the radius limit supports up to " + MAX_DATA_BYTES +
                      " bytes of data");

    var data, compressed = false, packed;
    if (compress === "auto") {
      packed = zlibCompress(raw);
      if (packed.length < raw.length) { data = packed.slice(); compressed = true; }
      else data = Array.prototype.slice.call(raw);
    } else if (compress === true) {
      data = zlibCompress(raw);
      compressed = true;
    } else if (compress === false) {
      data = Array.prototype.slice.call(raw);
    } else {
      throw new Error("compress must be 'auto', true or false");
    }
    if (data.length > MAX_DATA_BYTES)
      throw new Error("the radius limit supports up to " + MAX_DATA_BYTES +
                      " bytes of data");

    var blocks = planBlocks(data.length, ecPct);
    var eccTotal = 0, i, j;
    for (i = 0; i < blocks.length; i++) eccTotal += blocks[i][1];
    var needBits = MODE_BITS + (data.length + eccTotal) * 8;

    var rmax = Math.max(DATA_RING0 + 1, minRings);
    while (ringCapacity(DATA_RING0, rmax) < needBits) {
      rmax += 1;
      if (rmax > MAX_RINGS)
        throw new Error("data does not fit (symbol too large)");
    }

    // --- payload (unmasked at this point): data of all blocks in order,
    //     then ECC of all blocks in order.
    var payload = [], pos = 0;
    for (i = 0; i < blocks.length; i++) {
      var size = blocks[i][0];
      payload = payload.concat(bytesToBits(data.slice(pos, pos + size)));
      pos += size;
    }
    pos = 0;
    for (i = 0; i < blocks.length; i++) {
      size = blocks[i][0];
      var ecc = blocks[i][1];
      var cw = rsEncodeMsg(data.slice(pos, pos + size), ecc);
      payload = payload.concat(bytesToBits(cw.slice(size)));
      pos += size;
    }
    var pad = ringCapacity(DATA_RING0, rmax) - MODE_BITS - payload.length;
    for (i = 0; i < pad; i++) payload.push(i % 2);

    // --- mask selection (payload only; the header carries the mask id
    //     and stays unmasked).
    var bestMask;
    if (maskOpt === "auto") {
      var sel = selectMask(payload);
      payload = sel[0];
      bestMask = sel[1];
    } else {
      if (!(maskOpt >= 0 && maskOpt <= 7 && maskOpt % 1 === 0))
        throw new Error("mask_id must be 0..7 or 'auto'");
      payload = maskPayload(payload, maskOpt);
      bestMask = maskOpt;
    }

    // --- header with the final mask id, then the full bitstream.
    var mode = packMode(rmax, bestMask, ecPct, blocks.length, data.length,
                        compressed);
    var bits = bytesToBits(mode).concat(payload);

    // --- place modules: bullseye + key + spiral payload.
    var dataCells = [], k;
    for (k = DATA_RING0; k <= rmax; k++)
      dataCells = dataCells.concat(hexRing(k));

    var grid = new Map();
    for (k = 0; k <= BULLSEYE_RINGS; k++) {
      var ringCells = hexRing(k), c;
      for (i = 0; i < ringCells.length; i++) {
        c = ringCells[i];
        grid.set(key(c[0], c[1]), 1 - (k % 2));   // centre DARK
      }
    }
    var keyRing = hexRing(KEY_RING);
    for (i = 0; i < keyRing.length; i++)
      grid.set(key(keyRing[i][0], keyRing[i][1]), 0);
    grid.set(key(keyRing[0][0], keyRing[0][1]), 1);   // orientation key
    grid.set(key(keyRing[1][0], keyRing[1][1]), 1);   // two adjacent cells

    for (i = 0; i < dataCells.length; i++) {
      var cell = dataCells[i];
      grid.set(key(cell[0], cell[1]), i < bits.length ? bits[i] : 0);
    }

    return {
      grid: grid,
      params: {
        rmax: rmax, mask: bestMask, ec: ecPct,
        blocks: blocks, dataLen: data.length, compressed: compressed
      }
    };
  }

  // ------------------------------------------------------------------
  // SVG renderer
  // ------------------------------------------------------------------

  /**
   * Render a grid to an SVG string.
   *
   * options: size (module radius px, default 18), quiet (quiet zone in
   * modules, default 1.5), dark, light (CSS colors), background (false
   * disables the light rectangle).
   */
  function renderSVG(grid, options) {
    var opts = options || {};
    var size = opts.size === undefined ? 18 : opts.size;
    var quiet = opts.quiet === undefined ? 1.5 : opts.quiet;
    var dark = opts.dark || "#181612";       // matches Python (24, 22, 18)
    var light = opts.light || "#ffffff";
    var withBg = opts.background === undefined ? true : !!opts.background;

    var rmax = 0;
    grid.forEach(function (_val, k) {
      var p = k.split(",");
      var d = hexDistance(parseInt(p[0], 10), parseInt(p[1], 10));
      if (d > rmax) rmax = d;
    });
    if (rmax === 0) throw new Error("renderSVG: empty grid");

    var width = Math.sqrt(3.0) * size * (2 * rmax + 1 + 2 * quiet);
    var height = 1.5 * size * (2 * rmax + 2 * quiet + 2);
    var cx0 = width / 2.0, cy0 = height / 2.0;
    var r = size * 0.995;

    function f(v) { return Math.round(v * 100) / 100; }

    var path = "";
    grid.forEach(function (val, k) {
      if (!val) return;
      var p = k.split(",");
      var xy = hexToPixel(parseInt(p[0], 10), parseInt(p[1], 10), size);
      var d = "";
      for (var i = 0; i < 6; i++) {
        var c = hexCorner(cx0 + xy[0], cy0 + xy[1], r, i);
        d += (i === 0 ? "M" : "L") + f(c[0]) + " " + f(c[1]);
      }
      path += d + "Z";
    });

    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + f(width) +
              '" height="' + f(height) + '" viewBox="0 0 ' + f(width) + ' ' +
              f(height) + '">';
    if (withBg)
      svg += '<rect width="100%" height="100%" fill="' + light + '"/>';
    svg += '<path d="' + path + '" fill="' + dark + '"/></svg>';
    return svg;
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------

  return {
    VERSION: VERSION,
    SPEC_VERSION: SPEC_VERSION,
    encode: encode,
    renderSVG: renderSVG,
    canonicalHex: canonicalHex,
    canonicalBits: canonicalBits,
    gridToJSON: gridToJSON,
    internals: {
      // Exposed for testing and third-party implementations.
      BULLSEYE_RINGS: BULLSEYE_RINGS, KEY_RING: KEY_RING,
      DATA_RING0: DATA_RING0, MAX_RINGS: MAX_RINGS,
      BLOCK_DATA_MAX: BLOCK_DATA_MAX, MODE_BITS: MODE_BITS,
      MIN_EC_PCT: MIN_EC_PCT, MAX_EC_PCT: MAX_EC_PCT,
      MAX_DATA_BYTES: MAX_DATA_BYTES, COMPRESSED_FLAG: COMPRESSED_FLAG,
      GF_EXP: GF_EXP, GF_LOG: GF_LOG,
      gfMul: gfMul, gfDiv: gfDiv, gfInv: gfInv,
      gfPolyAdd: gfPolyAdd, gfPolyMul: gfPolyMul, gfPolyEval: gfPolyEval,
      rsGeneratorPoly: rsGeneratorPoly, rsEncodeMsg: rsEncodeMsg,
      bytesToBits: bytesToBits, bitsToBytes: bitsToBytes,
      packMode: packMode, planBlocks: planBlocks,
      maskBit: maskBit, maskPayload: maskPayload,
      evaluateMask: evaluateMask, selectMask: selectMask,
      DIRS: DIRS, hexRing: hexRing, hexDistance: hexDistance,
      ringCapacity: ringCapacity, hexToPixel: hexToPixel,
      hexCorner: hexCorner,
      adler32: adler32, deflateFixed: deflateFixed, zlibCompress: zlibCompress,
      lz77Tokens: lz77Tokens, BitWriter: BitWriter,
      utf8Bytes: utf8Bytes
    }
  };
});
