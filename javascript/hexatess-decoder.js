/*!
 * Hexatess Code — pure-JavaScript decoder (specification v0.3)
 * ============================================================
 *
 * Zero-dependency, plain JavaScript.  Works in the browser
 * (`<script src="hexatess-decoder.js">` → global `HexatessDecode`,
 * also merged into `Hexatess` when the encoder is loaded first)
 * and in Node.js (`require("./hexatess-decoder.js")`).
 *
 * A 1:1 port of the Python reference decoder:
 *   - spiral deserialization (rings 6..rmax, canonical hex_ring order)
 *   - double-protected 10-byte mode message (RS(5,5), unmasked)
 *   - LCG mask removal
 *   - per-block systematic Reed-Solomon correction over GF(256)
 *     (0x11D): syndromes -> Berlekamp-Massey -> Chien -> Forney
 *   - transparent zlib (RFC 1950) inflation for compressed payloads,
 *     supporting stored, fixed-Huffman and dynamic-Huffman DEFLATE
 *     blocks — so symbols written by Python's zlib (level 9, dynamic
 *     Huffman) decode as well as symbols written by this project's
 *     own fixed-Huffman encoder
 *   - strict UTF-8 validation (overlong forms, surrogates and
 *     out-of-range code points are rejected, matching Python)
 *
 * API:  decode(grid)                -> { text, stats }
 *       decodeHex(gridHex [, rmax]) -> { text, stats }
 *       gridFromHex(gridHex, rmax)  -> Map<"q,r", 0|1>
 *       payloadToText(bytes, compressed) -> string
 *   `grid` accepts a Map (as produced by the encoder) or a plain
 *   object with "q,r" keys.  `stats` mirrors the Python decoder:
 *   { rmax, mask, ec, blocks, dataLen, compressed, repairBits }.
 *
 * Copyright (c) 2026 The Hexatess Code Authors — MIT License.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module !== null && module.exports) {
    module.exports = api;                    // CommonJS / Node.js
  } else {
    root.HexatessDecode = api;               // browser global
    if (root.Hexatess) {                     // merge into the encoder
      root.Hexatess.decode = api.decode;
      root.Hexatess.decodeHex = api.decodeHex;
      root.Hexatess.gridFromHex = api.gridFromHex;
      root.Hexatess.payloadToText = api.payloadToText;
    }
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
  var COMPRESSED_FLAG = 0x40;                    // header byte 4, bit 6

  var VERSION = "0.4.1";
  var SPEC_VERSION = "0.3";

  // ------------------------------------------------------------------
  // GF(256) — primitive polynomial x^8+x^4+x^3+x^2+1 (0x11D), alpha = 2
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

  // Descending-degree coefficient order ([a, b, c] = a*x^2 + b*x + c).

  function gfPolyScale(p, x) {
    var r = new Array(p.length), i;
    for (i = 0; i < p.length; i++) r[i] = gfMul(p[i], x);
    return r;
  }

  function gfPolyAdd(p, q) {
    var r = new Array(Math.max(p.length, q.length)), z;
    for (z = 0; z < r.length; z++) r[z] = 0;
    var i;
    for (i = 0; i < p.length; i++) r[i + r.length - p.length] = p[i];
    for (i = 0; i < q.length; i++) r[i + r.length - q.length] ^= q[i];
    return r;
  }

  function gfPolyMul(p, q) {
    var r = new Array(p.length + q.length - 1), z;
    for (z = 0; z < r.length; z++) r[z] = 0;
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
  // Systematic Reed-Solomon DECODER (syndromes -> BM -> Chien -> Forney)
  // ------------------------------------------------------------------

  function rsCalcSyndromes(msg, nsym) {
    var out = new Array(nsym), i;
    for (i = 0; i < nsym; i++) out[i] = gfPolyEval(msg, GF_EXP[i]);
    return out;
  }

  function rsFindErrorLocator(synd, nsym) {
    var errLoc = [1], oldLoc = [1], i, j;
    for (i = 0; i < nsym; i++) {
      var delta = synd[i];
      for (j = 1; j < errLoc.length; j++)
        delta ^= gfMul(errLoc[errLoc.length - (j + 1)], synd[i - j]);
      oldLoc = oldLoc.concat([0]);
      if (delta !== 0) {
        if (oldLoc.length > errLoc.length) {
          var newLoc = gfPolyScale(oldLoc, delta);
          oldLoc = gfPolyScale(errLoc, gfInv(delta));
          errLoc = newLoc;
        }
        errLoc = gfPolyAdd(errLoc, gfPolyScale(oldLoc, delta));
      }
    }
    while (errLoc.length && errLoc[0] === 0) errLoc.shift();
    return errLoc;
  }

  function rsFindErrors(errLocRev, nmess) {
    // Chien search: positions counted from the start of the message.
    var errs = errLocRev.length - 1, pos = [], i;
    for (i = 0; i < nmess; i++)
      if (gfPolyEval(errLocRev, GF_EXP[i % 255]) === 0)
        pos.push(nmess - 1 - i);
    if (pos.length !== errs)
      throw new Error("Chien: found " + pos.length + " roots, expected " +
                      errs);
    return pos;
  }

  function rsFindErrataLocator(coefPos) {
    // Errata locator, ascending order: prod (1 + X_i * x).
    var eLoc = [1], i;
    for (i = 0; i < coefPos.length; i++)
      eLoc = gfPolyMul(eLoc, gfPolyAdd([1], [GF_EXP[coefPos[i]], 0]));
    return eLoc;
  }

  function rsCorrectErrata(msgIn, synd, errPos) {
    // Forney algorithm, ascending internal convention:
    //   e_i = X_i * Omega(X_i^-1) / Lambda'(X_i^-1)
    var nmess = msgIn.length, i;
    var coefPos = errPos.map(function (p) { return nmess - 1 - p; });
    var Xs = coefPos.map(function (c) { return GF_EXP[c % 255]; });
    var nsym = synd.length;

    var lam = rsFindErrataLocator(coefPos).slice().reverse();
    var omega = gfPolyMul(synd.slice(), lam).slice(0, nsym);

    // Formal derivative of Lambda: odd-index coefficients.
    var lamD = new Array(Math.max(1, lam.length - 1));
    for (i = 0; i < lamD.length; i++) lamD[i] = 0;
    for (i = 1; i < lam.length; i++)
      if (i % 2 === 1) lamD[i - 1] = lam[i];

    var E = new Array(nmess);
    for (i = 0; i < nmess; i++) E[i] = 0;
    for (i = 0; i < Xs.length; i++) {
      var XiInv = gfInv(Xs[i]);
      var num = gfPolyEval(omega.slice().reverse(), XiInv);
      var den = gfPolyEval(lamD.slice().reverse(), XiInv);
      E[errPos[i]] = gfDiv(gfMul(Xs[i], num), den);
    }
    return msgIn.map(function (m, k) { return m ^ E[k]; });
  }

  function rsCorrectMsg(msgIn, nsym) {
    // Correct up to floor(nsym/2) symbol errors; returns data symbols.
    if (msgIn.length > 255) throw new Error("block too long for RS");
    var msg = msgIn.slice(), i;
    var synd = rsCalcSyndromes(msg, nsym);
    var maxS = 0;
    for (i = 0; i < synd.length; i++) if (synd[i] > maxS) maxS = synd[i];
    if (maxS === 0) return msg.slice(0, msg.length - nsym);
    var errLoc = rsFindErrorLocator(synd, nsym);
    if (errLoc.length === 0) throw new Error("RS: unexpected locator state");
    var errs = errLoc.length - 1;
    if (errs === 0) throw new Error("RS: unexpected locator state");
    if (2 * errs > nsym)
      throw new Error("RS: too many errors (" + errs + " errors, capacity " +
                      Math.floor(nsym / 2) + ")");
    var errPos = rsFindErrors(errLoc.slice().reverse(), msg.length);
    msg = rsCorrectErrata(msg, synd, errPos);
    var synd2 = rsCalcSyndromes(msg, nsym);
    for (i = 0; i < synd2.length; i++)
      if (synd2[i] !== 0) throw new Error("RS: correction failed verification");
    return msg.slice(0, msg.length - nsym);
  }

  // ------------------------------------------------------------------
  // Bit / byte helpers (MSB-first bit order everywhere in the symbol)
  // ------------------------------------------------------------------

  function bitsToBytes(bits) {
    var out = [], i, j, v;
    for (i = 0; i + 7 < bits.length; i += 8) {
      v = 0;
      for (j = 0; j < 8; j++) v = (v << 1) | bits[i + j];
      out.push(v);
    }
    return out;
  }

  function popcount8(b) {
    b = b - ((b >> 1) & 0x55);
    b = (b & 0x33) + ((b >> 2) & 0x33);
    return (b + (b >> 4)) & 0x0F;
  }

  // ------------------------------------------------------------------
  // Masking (deterministic pseudo-random stream, LCG + xorshift)
  // ------------------------------------------------------------------

  function maskBit(index, maskId) {
    var x = (index * 1103515245 + 12345 + maskId * 2654435761) & 0x7FFFFFFF;
    x ^= x >> 13;
    return (x >>> 19) & 1;
  }

  // ------------------------------------------------------------------
  // Hexagonal geometry (axial coordinates)
  // ------------------------------------------------------------------

  var DIRS = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];

  function hexRing(k) {
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

  // ------------------------------------------------------------------
  // Block planning (same rule as the encoder)
  // ------------------------------------------------------------------

  function planBlocks(dataLen, ecPct) {
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
  // Mode message (header): RS-correct, then unpack the parameters
  // ------------------------------------------------------------------

  function unpackModeEx(modeBytes) {
    var data = rsCorrectMsg(modeBytes, MODE_ECC);
    var b0 = data[0], b1 = data[1], b2 = data[2], b3 = data[3], b4 = data[4];
    return [
      b0 >> 3,                              // rmax
      b0 & 0x7,                             // mask_id
      (b1 >> 3) * 5,                        // ec_pct
      ((b1 & 0x7) << 5) | (b2 >> 3),        // block_count
      ((b2 & 0x7) << 9) | (b3 << 1) | (b4 >> 7),   // data_len
      !!(b4 & COMPRESSED_FLAG)              // compressed
    ];
  }

  // ------------------------------------------------------------------
  // Strict UTF-8 decoding (mirrors Python's bytes.decode("utf-8"))
  // ------------------------------------------------------------------

  function utf8Decode(bytes) {
    var out = "", i = 0, n = bytes.length;
    while (i < n) {
      var b = bytes[i];
      if (b < 0x80) {
        out += String.fromCharCode(b);
        i += 1;
      } else if ((b & 0xE0) === 0xC0) {
        if (i + 1 >= n || (bytes[i + 1] & 0xC0) !== 0x80)
          throw new Error("invalid UTF-8 byte sequence");
        var cp2 = ((b & 0x1F) << 6) | (bytes[i + 1] & 0x3F);
        if (cp2 < 0x80) throw new Error("overlong UTF-8 encoding");
        out += String.fromCharCode(cp2);
        i += 2;
      } else if ((b & 0xF0) === 0xE0) {
        if (i + 2 >= n || (bytes[i + 1] & 0xC0) !== 0x80 ||
            (bytes[i + 2] & 0xC0) !== 0x80)
          throw new Error("invalid UTF-8 byte sequence");
        var cp3 = ((b & 0x0F) << 12) | ((bytes[i + 1] & 0x3F) << 6) |
                  (bytes[i + 2] & 0x3F);
        if (cp3 < 0x800) throw new Error("overlong UTF-8 encoding");
        if (cp3 >= 0xD800 && cp3 <= 0xDFFF)
          throw new Error("UTF-8 surrogate code point");
        out += String.fromCharCode(cp3);
        i += 3;
      } else if ((b & 0xF8) === 0xF0) {
        if (i + 3 >= n || (bytes[i + 1] & 0xC0) !== 0x80 ||
            (bytes[i + 2] & 0xC0) !== 0x80 || (bytes[i + 3] & 0xC0) !== 0x80)
          throw new Error("invalid UTF-8 byte sequence");
        var cp4 = ((b & 0x07) << 18) | ((bytes[i + 1] & 0x3F) << 12) |
                  ((bytes[i + 2] & 0x3F) << 6) | (bytes[i + 3] & 0x3F);
        if (cp4 < 0x10000 || cp4 > 0x10FFFF)
          throw new Error("invalid UTF-8 code point");
        cp4 -= 0x10000;
        out += String.fromCharCode(0xD800 + (cp4 >> 10),
                                   0xDC00 + (cp4 & 0x3FF));
        i += 4;
      } else {
        throw new Error("invalid UTF-8 byte sequence");
      }
    }
    return out;
  }

  // ------------------------------------------------------------------
  // zlib / DEFLATE inflator (RFC 1950 + 1951)
  //
  // Supports stored, fixed-Huffman and dynamic-Huffman blocks, so any
  // conforming compressor (Python zlib level 9, the project's own JS
  // encoder, ...) can be read back.
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
  var CLEN_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13,
                    2, 14, 1, 15];

  function adler32(bytes) {
    var a = 1, b = 0, i;
    for (i = 0; i < bytes.length; i++) {
      a = (a + bytes[i]) % 65521;
      b = (b + a) % 65521;
    }
    return (b * 65536 + a) >>> 0;
  }

  function BitReader(bytes) {
    this.bytes = bytes;
    this.pos = 0;      // current byte
    this.bit = 0;      // current bit within the byte (LSB first)
  }
  BitReader.prototype.getBit = function () {
    if (this.pos >= this.bytes.length)
      throw new Error("deflate: unexpected end of stream");
    var b = (this.bytes[this.pos] >> this.bit) & 1;
    if (++this.bit === 8) { this.bit = 0; this.pos++; }
    return b;
  };
  BitReader.prototype.getBits = function (n) {
    var v = 0, i;
    for (i = 0; i < n; i++) v |= this.getBit() << i;
    return v;
  };
  BitReader.prototype.align = function () {
    if (this.bit !== 0) { this.bit = 0; this.pos++; }
  };

  // Canonical Huffman decoder in the classic "puff" style: count of
  // codes per length + symbols ordered by (length, symbol value).
  function buildHuffman(lengths) {
    var maxLen = 0, i;
    for (i = 0; i < lengths.length; i++)
      if (lengths[i] > maxLen) maxLen = lengths[i];
    var count = new Array(maxLen + 1);
    for (i = 0; i <= maxLen; i++) count[i] = 0;
    for (i = 0; i < lengths.length; i++)
      if (lengths[i] !== 0) count[lengths[i]]++;

    // Over-subscribed codes are invalid; incomplete codes are allowed
    // here and caught at decode time (zlib does the same for distances).
    var left = 1, len;
    for (len = 1; len <= maxLen; len++) {
      left = (left << 1) - count[len];
      if (left < 0) throw new Error("deflate: over-subscribed Huffman code");
    }

    var offs = new Array(maxLen + 2);
    offs[1] = 0;
    for (i = 1; i <= maxLen; i++) offs[i + 1] = offs[i] + count[i];
    var symbols = new Array(lengths.length), n = 0;
    for (i = 0; i < lengths.length; i++)
      if (lengths[i] !== 0) { symbols[offs[lengths[i]]] = i; offs[lengths[i]]++; n++; }
    symbols.length = n;
    return { count: count, symbols: symbols, maxLen: maxLen };
  }

  function decodeSymbol(br, h) {
    var code = 0, first = 0, index = 0, len;
    for (len = 1; len <= h.maxLen; len++) {
      code |= br.getBit();
      var cnt = h.count[len];
      if (code - first < cnt) return h.symbols[index + (code - first)];
      index += cnt;
      first = (first + cnt) << 1;
      code <<= 1;
    }
    throw new Error("deflate: invalid Huffman code");
  }

  function fixedTables() {
    var lit = new Array(288), dist = new Array(30), i;
    for (i = 0; i < 144; i++) lit[i] = 8;
    for (i = 144; i < 256; i++) lit[i] = 9;
    for (i = 256; i < 280; i++) lit[i] = 7;
    for (i = 280; i < 288; i++) lit[i] = 8;
    for (i = 0; i < 30; i++) dist[i] = 5;
    return [buildHuffman(lit), buildHuffman(dist)];
  }

  function dynamicTables(br) {
    var hlit = br.getBits(5) + 257;
    var hdist = br.getBits(5) + 1;
    var hclen = br.getBits(4) + 4;
    if (hlit > 286 || hdist > 30)
      throw new Error("deflate: too many Huffman codes");
    var clen = new Array(19), i;
    for (i = 0; i < 19; i++) clen[i] = 0;
    for (i = 0; i < hclen; i++) clen[CLEN_ORDER[i]] = br.getBits(3);
    var clH = buildHuffman(clen);

    var total = hlit + hdist;
    var lengths = new Array(total);
    for (i = 0; i < total; i++) lengths[i] = 0;
    var n = 0;
    while (n < total) {
      var sym = decodeSymbol(br, clH);
      if (sym < 16) {
        lengths[n++] = sym;
      } else if (sym === 16) {
        if (n === 0)
          throw new Error("deflate: length repeat with no previous value");
        var prev = lengths[n - 1], rep = 3 + br.getBits(2);
        while (rep-- > 0) {
          if (n >= total) throw new Error("deflate: repeat overflow");
          lengths[n++] = prev;
        }
      } else if (sym === 17) {
        var rep0 = 3 + br.getBits(3);
        while (rep0-- > 0) {
          if (n >= total) throw new Error("deflate: repeat overflow");
          lengths[n++] = 0;
        }
      } else {
        var rep00 = 11 + br.getBits(7);
        while (rep00-- > 0) {
          if (n >= total) throw new Error("deflate: repeat overflow");
          lengths[n++] = 0;
        }
      }
    }
    if (lengths[256] === 0)
      throw new Error("deflate: missing end-of-block code");
    return [buildHuffman(lengths.slice(0, hlit)),
            buildHuffman(lengths.slice(hlit))];
  }

  function inflateReader(br) {
    var out = [], final;
    do {
      final = br.getBit();
      var type = br.getBits(2), i;
      if (type === 0) {
        // Stored block: skip to byte boundary, LEN/NLEN, raw copy.
        br.align();
        if (br.pos + 4 > br.bytes.length)
          throw new Error("deflate: truncated stored block");
        var len = br.bytes[br.pos] | (br.bytes[br.pos + 1] << 8);
        var nlen = br.bytes[br.pos + 2] | (br.bytes[br.pos + 3] << 8);
        if ((len ^ 0xFFFF) !== nlen)
          throw new Error("deflate: stored block length check failed");
        br.pos += 4;
        if (br.pos + len > br.bytes.length)
          throw new Error("deflate: truncated stored data");
        for (i = 0; i < len; i++) out.push(br.bytes[br.pos + i]);
        br.pos += len;
      } else if (type === 1 || type === 2) {
        var tab = (type === 1) ? fixedTables() : dynamicTables(br);
        var litH = tab[0], distH = tab[1];
        for (;;) {
          var sym = decodeSymbol(br, litH);
          if (sym < 256) {
            out.push(sym);
          } else if (sym === 256) {
            break;
          } else {
            var idx = sym - 257;
            if (idx >= LENGTH_BASE.length)
              throw new Error("deflate: invalid length code");
            var length = LENGTH_BASE[idx] + br.getBits(LENGTH_EXTRA[idx]);
            var dsym = decodeSymbol(br, distH);
            if (dsym >= DIST_BASE.length)
              throw new Error("deflate: invalid distance code");
            var dist = DIST_BASE[dsym] + br.getBits(DIST_EXTRA[dsym]);
            if (dist > out.length)
              throw new Error("deflate: distance too far back");
            var from = out.length - dist, j;
            for (j = 0; j < length; j++) out.push(out[from + j]);
          }
        }
      } else {
        throw new Error("deflate: invalid block type");
      }
    } while (!final);
    return out;
  }

  function inflateRaw(bytes) {
    return inflateReader(new BitReader(bytes));
  }

  function zlibInflate(bytes) {
    if (bytes.length < 8) throw new Error("zlib: stream too short");
    var cmf = bytes[0], flg = bytes[1];
    if ((((cmf << 8) | flg) & 0xFFFF) % 31 !== 0)
      throw new Error("zlib: header check failed");
    if ((cmf & 0x0F) !== 8)
      throw new Error("zlib: unsupported compression method");
    if ((flg & 0x20) !== 0)
      throw new Error("zlib: preset dictionary not supported");
    var br = new BitReader(bytes);
    br.pos = 2;
    var out = inflateReader(br);
    br.align();
    if (br.pos + 4 > br.bytes.length)
      throw new Error("zlib: missing adler32 checksum");
    var expect = ((br.bytes[br.pos] << 24) | (br.bytes[br.pos + 1] << 16) |
                  (br.bytes[br.pos + 2] << 8) | br.bytes[br.pos + 3]) >>> 0;
    if (adler32(out) !== expect)
      throw new Error("zlib: adler32 checksum mismatch");
    return out;
  }

  // ------------------------------------------------------------------
  // Payload -> text (mirrors Python payload_to_text)
  // ------------------------------------------------------------------

  function payloadToText(payload, compressed) {
    var bytes = Array.prototype.slice.call(payload);
    if (compressed) bytes = zlibInflate(bytes);
    return utf8Decode(bytes);
  }

  // ------------------------------------------------------------------
  // Canonical serialization helpers (conformance format)
  // ------------------------------------------------------------------

  function gridFromHex(hex, rmax) {
    var bits = [], i;
    hex = String(hex).toLowerCase().replace(/[^0-9a-f]/g, "");
    for (i = 0; i < hex.length; i++) {
      var b = parseInt(hex.charAt(i), 16);
      bits.push((b >> 3) & 1, (b >> 2) & 1, (b >> 1) & 1, b & 1);
    }
    if (rmax === undefined) {
      // Infer the radius from the bit count; the padding never spans
      // the gap between consecutive ring totals (>= 12 cells).
      rmax = 0;
      while (3 * (rmax + 1) * (rmax + 2) + 1 <= bits.length) rmax++;
    }
    var grid = new Map(), idx = 0, k, j;
    for (k = 0; k <= rmax; k++) {
      var ring = hexRing(k);
      for (j = 0; j < ring.length; j++) {
        grid.set(ring[j][0] + "," + ring[j][1],
                 idx < bits.length ? bits[idx] : 0);
        idx++;
      }
    }
    return grid;
  }

  // ------------------------------------------------------------------
  // Per-block RS recovery (port of Python _rs_recover_blocks)
  // ------------------------------------------------------------------

  function rsRecoverBlocks(stream, blocks, dataLen) {
    var out = [], total = 0, posD = 0, posE = 0, i, j;
    for (i = 0; i < blocks.length; i++) {
      var size = blocks[i][0], ecc = blocks[i][1];
      var cw = stream.slice(posD, posD + size)
        .concat(stream.slice(dataLen + posE, dataLen + posE + ecc));
      var fixed = rsCorrectMsg(cw, ecc);
      var full = fixed.concat(cw.slice(size));
      for (j = 0; j < cw.length; j++)
        total += popcount8(cw[j] ^ full[j]);
      out = out.concat(fixed);
      posD += size;
      posE += ecc;
    }
    return { payload: out, repaired: total };
  }

  // ------------------------------------------------------------------
  // Grid input adapters
  // ------------------------------------------------------------------

  function makeGetter(grid) {
    if (grid && typeof grid.get === "function" && typeof grid.set === "function")
      return function (k) { return grid.get(k); };
    if (grid && typeof grid === "object")
      return function (k) { return grid[k]; };
    throw new Error("decode: grid must be a Map or an object with \"q,r\" keys");
  }

  // ------------------------------------------------------------------
  // The decoder
  // ------------------------------------------------------------------

  /**
   * Decode a module grid into text.
   *
   * @param {Map|Object} grid  mapping "q,r" -> 0|1 (all cells of rings
   *                           0..rmax, as produced by the encoder or by
   *                           gridFromHex)
   * @returns {{text: string, stats: object}}
   *   stats: { rmax, mask, ec, blocks, dataLen, compressed, repairBits }
   */
  function decode(grid /*, params (ignored, API symmetry) */) {
    var get = makeGetter(grid);

    // Symbol radius from the grid extent.
    var rmax = 0;
    function visit(v, k) {
      var p = String(k).split(",");
      var d = hexDistance(parseInt(p[0], 10), parseInt(p[1], 10));
      if (d > rmax) rmax = d;
    }
    if (grid && typeof grid.get === "function" &&
        typeof grid.size === "number" && typeof grid.forEach === "function") {
      grid.forEach(function (v, k) { visit(v, k); });
    } else {
      for (var kk in grid)
        if (Object.prototype.hasOwnProperty.call(grid, kk)) visit(grid[kk], kk);
    }
    if (rmax <= DATA_RING0)
      throw new Error("grid too small to contain a symbol");

    // Spiral payload bits (rings DATA_RING0..rmax, canonical order).
    var bits = [], k, i;
    for (k = DATA_RING0; k <= rmax; k++) {
      var ring = hexRing(k);
      for (i = 0; i < ring.length; i++) {
        var c = ring[i], v = get(c[0] + "," + c[1]);
        if (v === undefined || v === null)
          throw new Error("grid is missing cell (" + c[0] + "," + c[1] + ")");
        bits.push(v ? 1 : 0);
      }
    }
    if (bits.length < MODE_BITS)
      throw new Error("grid too small for the mode message");

    // --- protected header (never masked)
    var mode = unpackModeEx(bitsToBytes(bits.slice(0, MODE_BITS)));
    var rmaxM = mode[0], maskId = mode[1], ecPct = mode[2];
    var blockCount = mode[3], dataLen = mode[4], compressed = mode[5];

    // --- masked payload
    var blocks = planBlocks(dataLen, ecPct), eccTotal = 0;
    for (i = 0; i < blocks.length; i++) eccTotal += blocks[i][1];
    var need = (dataLen + eccTotal) * 8;
    if (bits.length < MODE_BITS + need)
      throw new Error("grid truncated: payload incomplete");
    var payloadBits = bits.slice(MODE_BITS, MODE_BITS + need);
    for (i = 0; i < payloadBits.length; i++)
      payloadBits[i] ^= maskBit(i, maskId);
    var stream = bitsToBytes(payloadBits);

    // --- per-block Reed-Solomon correction
    var rec = rsRecoverBlocks(stream, blocks, dataLen);
    var text = payloadToText(rec.payload, compressed);
    return {
      text: text,
      stats: {
        rmax: rmaxM, mask: maskId, ec: ecPct, blocks: blockCount,
        dataLen: dataLen, compressed: compressed, repairBits: rec.repaired
      }
    };
  }

  /**
   * Decode a canonical grid serialization (lowercase hex, ring-major
   * MSB-first bit packing — the test_vectors conformance format).
   */
  function decodeHex(hex, rmax) {
    return decode(gridFromHex(hex, rmax));
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------

  return {
    VERSION: VERSION,
    SPEC_VERSION: SPEC_VERSION,
    decode: decode,
    decodeHex: decodeHex,
    gridFromHex: gridFromHex,
    payloadToText: payloadToText,
    internals: {
      // Exposed for testing and third-party implementations.
      BULLSEYE_RINGS: BULLSEYE_RINGS, KEY_RING: KEY_RING,
      DATA_RING0: DATA_RING0, MAX_RINGS: MAX_RINGS,
      BLOCK_DATA_MAX: BLOCK_DATA_MAX, MODE_BITS: MODE_BITS,
      COMPRESSED_FLAG: COMPRESSED_FLAG,
      GF_EXP: GF_EXP, GF_LOG: GF_LOG,
      gfMul: gfMul, gfDiv: gfDiv, gfInv: gfInv,
      gfPolyAdd: gfPolyAdd, gfPolyMul: gfPolyMul, gfPolyEval: gfPolyEval,
      rsCalcSyndromes: rsCalcSyndromes,
      rsFindErrorLocator: rsFindErrorLocator,
      rsFindErrors: rsFindErrors,
      rsCorrectErrata: rsCorrectErrata,
      rsCorrectMsg: rsCorrectMsg,
      bitsToBytes: bitsToBytes, popcount8: popcount8,
      maskBit: maskBit, hexRing: hexRing, hexDistance: hexDistance,
      planBlocks: planBlocks, unpackModeEx: unpackModeEx,
      utf8Decode: utf8Decode,
      adler32: adler32, inflateRaw: inflateRaw, zlibInflate: zlibInflate,
      buildHuffman: buildHuffman, BitReader: BitReader,
      rsRecoverBlocks: rsRecoverBlocks
    }
  };
});
