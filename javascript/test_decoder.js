/*
 * Hexatess Code — JavaScript decoder conformance tests (Node.js).
 *
 * Run:  node javascript/test_decoder.js
 *
 * Checks:
 *   1. all 6 decode vectors from test_vectors/vectors_v0.3.json
 *      (clean + deterministically damaged + expected-failure),
 *   2. encode->decode round-trips (texts x EC x masks x compression),
 *   3. Reed-Solomon error injection with exact repair-bit accounting,
 *   4. the inflator against Node's own zlib (levels 0..9: stored,
 *      fixed and dynamic Huffman blocks) and against full symbols
 *      whose payload was compressed by Node's zlib,
 *   5. strict UTF-8 and API error behaviour.
 */
"use strict";

var fs = require("fs");
var path = require("path");
var zlib = require("zlib");
var H = require("./hexatess-encoder.js");
var D = require("./hexatess-decoder.js");

var passed = 0, failed = 0;

function check(name, cond, detail) {
  if (cond) { passed++; }
  else {
    failed++;
    console.error("FAIL: " + name + (detail ? " — " + detail : ""));
  }
}

function throws(fn) {
  try { fn(); return false; } catch (e) { return true; }
}

function utf8(s) { return Array.from(Buffer.from(s, "utf8")); }

// --------------------------------------------------------------------
// 1. Conformance decode vectors
// --------------------------------------------------------------------

var vectors = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "test_vectors", "vectors_v0.3.json"), "utf8"));

vectors.decode_vectors.forEach(function (c) {
  if (c.expected_failure) {
    check("decode:" + c.name, throws(function () {
      D.decodeHex(c.grid_hex);
    }), "expected a decode failure");
    return;
  }
  var out = D.decodeHex(c.grid_hex);
  check("decode:" + c.name + ":text", out.text === c.expected_text,
        "got " + JSON.stringify(out.text));
  // Spiral indices include the 80 header cells and the flip XOR uses
  // only its lowest bit (mirroring the Python generator), so the exact
  // repair count depends on where the effective flips landed — but a
  // damaged symbol must always show a non-zero ledger.
  if (c.flipped_cells_spiral_index && c.flipped_cells_spiral_index.length)
    check("decode:" + c.name + ":repair", out.stats.repairBits >= 1,
          "repairBits " + out.stats.repairBits);
  else
    check("decode:" + c.name + ":clean", out.stats.repairBits === 0);
});

check("decodeVectorCount", vectors.decode_vectors.length === 6,
      "expected 6 decode vectors, found " + vectors.decode_vectors.length);

// --------------------------------------------------------------------
// 2. Round-trips: encode -> decode
// --------------------------------------------------------------------

var texts = [
  "",
  "A",
  "Hello, Hexatess!",
  "ŠČŽ življenje je kodiranje",
  "bee \u{1F41D} hive \u{1F41D} honey",
  "1234567890".repeat(8),
  "https://example.org/hexatess?query=1&x=%C5%A1",
  "Hexatess Code je eksperimentalna dvodimenzionalna koda na " +
    "sestkotni mrezi. ".repeat(6)
];

texts.forEach(function (t, ti) {
  [["auto", "auto"], [false, "raw"], [true, "forced"]].forEach(function (cm) {
    var enc = H.encode(t, { ecPct: 30, compress: cm[0] });
    var dec = D.decode(enc.grid);
    check("roundtrip[" + ti + "]:" + cm[1] + ":text", dec.text === t,
          "got " + JSON.stringify(dec.text.slice(0, 40)));
    check("roundtrip[" + ti + "]:" + cm[1] + ":stats",
          dec.stats.rmax === enc.params.rmax &&
          dec.stats.mask === enc.params.mask &&
          dec.stats.ec === enc.params.ec &&
          dec.stats.blocks === enc.params.blocks.length &&
          dec.stats.dataLen === enc.params.dataLen &&
          dec.stats.compressed === enc.params.compressed);
    if (cm[0] === "auto" && enc.params.compressed)
      check("roundtrip[" + ti + "]:autoRepair", dec.stats.repairBits === 0);
  });
});

// EC sweep: every supported budget decodes cleanly.
for (var ec = 5; ec <= 90; ec += 5) {
  var e = H.encode("EC sweep ŠČŽ 123", { ecPct: ec, compress: false });
  var d = D.decode(e.grid);
  check("ecSweep:" + ec, d.text === "EC sweep ŠČŽ 123" &&
        d.stats.ec === ec && d.stats.repairBits === 0);
}

// Forced masks 0..7 round-trip.
for (var m = 0; m < 8; m++) {
  var em = H.encode("mask " + m, { mask: m, compress: false });
  var dm = D.decode(em.grid);
  check("maskSweep:" + m, dm.text === "mask " + m && dm.stats.mask === m);
}

// Plain-object grid input is equivalent to the Map input.
var mapGrid = H.encode("object input", { compress: false }).grid;
var objGrid = {};
mapGrid.forEach(function (v, k) { objGrid[k] = v; });
check("plainObjectInput",
      D.decode(objGrid).text === D.decode(mapGrid).text);

// --------------------------------------------------------------------
// 3. Error injection — RS must repair and account every flipped bit
// --------------------------------------------------------------------

function flipSpiralBits(grid, rmax, indices) {
  // Flip payload cells by spiral index (data region, ring 6+).
  var cells = [], k;
  for (k = 6; k <= rmax; k++) cells = cells.concat(H.internals.hexRing(k));
  indices.forEach(function (i) {
    var c = cells[i], key = c[0] + "," + c[1];
    grid.set(key, grid.get(key) ? 0 : 1);
  });
}

function payloadCapacity(params) {
  var ecc = 0, i;
  for (i = 0; i < params.blocks.length; i++) ecc += params.blocks[i][1];
  return (params.dataLen + ecc) * 8;
}

// NOTE on spiral indexing: the first 80 spiral cells carry the mode
// message, then come the data bytes and finally the ECC bytes.  Only
// flips inside the data bytes appear in `repairBits`; header and ECC
// flips are absorbed silently (exactly like the Python decoder).

var msg = "Reed-Solomon is alive and well. ŠČŽ 0123456789.";
var good = H.encode(msg, { ecPct: 45, compress: false });   // 50 B, ecc 23
var dataBits = good.params.dataLen * 8;
var HEADER = 80;

[[3, "light"], [6, "medium"], [9, "heavy"]].forEach(function (fl) {
  var n = fl[0], idx = [], i;
  // Spread the flips deterministically over the DATA bytes only;
  // 9 distinct data symbols stay within the capacity (11) of EC 45.
  var step = Math.floor(dataBits / (n + 1));
  for (i = 1; i <= n; i++) idx.push(HEADER + i * step);
  var g = H.encode(msg, { ecPct: 45, compress: false });
  flipSpiralBits(g.grid, g.params.rmax, idx);
  var dec = D.decode(g.grid);
  check("inject:" + fl[1] + ":text", dec.text === msg,
        "got " + JSON.stringify(dec.text.slice(0, 40)));
  check("inject:" + fl[1] + ":repairBits", dec.stats.repairBits === n,
        "got " + dec.stats.repairBits + ", want " + n);
});

// A header flip is absorbed by the RS-protected mode message and does
// not enter the payload repair ledger.
var gh = H.encode(msg, { ecPct: 45, compress: false });
flipSpiralBits(gh.grid, gh.params.rmax, [10]);
var decH = D.decode(gh.grid);
check("inject:headerFlip", decH.text === msg && decH.stats.repairBits === 0);

// An ECC-region flip is repaired silently as well.
var ge = H.encode(msg, { ecPct: 45, compress: false });
flipSpiralBits(ge.grid, ge.params.rmax, [HEADER + dataBits + 4]);
var decE = D.decode(ge.grid);
check("inject:eccFlip", decE.text === msg && decE.stats.repairBits === 0);

// Beyond capacity the decode must fail (not silently mis-decode):
// "tiny" stores 4 data bytes with 2 ECC symbols -> capacity 1 symbol;
// damaging 4 distinct data symbols must throw.
var bad = H.encode("tiny", { ecPct: 5, compress: false });
flipSpiralBits(bad.grid, bad.params.rmax,
               [80, 88, 96, 104]);
check("inject:beyondCapacity", throws(function () { D.decode(bad.grid); }),
      "expected a decode failure");

// More header damage than RS(5,5) can fix (2 bytes) must also throw.
var badH = H.encode("tiny", { ecPct: 5, compress: false });
flipSpiralBits(badH.grid, badH.params.rmax, [0, 8, 16, 24, 32, 40]);
check("inject:headerOverload", throws(function () { D.decode(badH.grid); }),
      "expected a decode failure");

// --------------------------------------------------------------------
// 4. Inflator vs Node's zlib (stored / fixed / dynamic Huffman)
// --------------------------------------------------------------------

function arr(b) { return Array.prototype.slice.call(b); }

var inflateCases = [
  ["empty", Buffer.alloc(0)],
  ["one", Buffer.from("a", "utf8")],
  ["short", Buffer.from("Hello, Hexatess!", "utf8")],
  ["repetitive", Buffer.from("0123456789".repeat(120), "utf8")],
  ["slovene", Buffer.from(
    "ŠČŽ življenje je kodiranje. ".repeat(40), "utf8")],
  ["randomish", Buffer.from(
    (function () {
      var b = [], x = 987654321;
      for (var i = 0; i < 2000; i++) {
        x = (x * 1103515245 + 12345) % 2147483648;
        b.push(x & 0xFF);
      }
      return b;
    })())]
];

[0, 1, 6, 9].forEach(function (level) {
  inflateCases.forEach(function (c) {
    var packed = zlib.deflateSync(c[1], { level: level });
    var out = D.internals.zlibInflate(arr(packed));
    check("inflate:L" + level + ":" + c[0], JSON.stringify(out) ===
          JSON.stringify(arr(c[1])),
          "lengths " + out.length + " vs " + c[1].length);
  });
});

// Corrupted zlib stream must be rejected (adler32 check).
var corrupted = arr(zlib.deflateSync(Buffer.from("integrity", "utf8"),
                                     { level: 9 }));
corrupted[corrupted.length - 3] ^= 0x55;
check("inflate:adlerGuard",
      throws(function () { D.internals.zlibInflate(corrupted); }));

// A full symbol whose payload was compressed by NODE's zlib (dynamic
// Huffman) decodes end-to-end.
function assembleSymbol(dataBytes, ecPct) {
  var I = H.internals, blocks = I.planBlocks(dataBytes.length, ecPct);
  var eccTotal = 0, i;
  for (i = 0; i < blocks.length; i++) eccTotal += blocks[i][1];
  var needBits = I.MODE_BITS + (dataBytes.length + eccTotal) * 8;
  var rmax = 7;
  while (I.ringCapacity(6, rmax) < needBits) {
    rmax++;
    if (rmax > 31) throw new Error("payload too large");
  }
  var payload = [], pos;
  for (i = 0, pos = 0; i < blocks.length; i++) {
    payload = payload.concat(
      I.bytesToBits(dataBytes.slice(pos, pos + blocks[i][0])));
    pos += blocks[i][0];
  }
  for (i = 0, pos = 0; i < blocks.length; i++) {
    var size = blocks[i][0];
    var cw = I.rsEncodeMsg(dataBytes.slice(pos, pos + size), blocks[i][1]);
    payload = payload.concat(I.bytesToBits(cw.slice(size)));
    pos += size;
  }
  var pad = I.ringCapacity(6, rmax) - I.MODE_BITS - payload.length;
  for (i = 0; i < pad; i++) payload.push(i % 2);
  var sel = I.selectMask(payload);
  var mode = I.packMode(rmax, sel[1], ecPct, blocks.length,
                        dataBytes.length, true);
  var bits = I.bytesToBits(mode).concat(sel[0]);
  var grid = new Map(), k;
  for (k = 0; k <= 4; k++)
    I.hexRing(k).forEach(function (c) {
      grid.set(c[0] + "," + c[1], 1 - (k % 2));
    });
  var kr = I.hexRing(5);
  kr.forEach(function (c) { grid.set(c[0] + "," + c[1], 0); });
  grid.set(kr[0][0] + "," + kr[0][1], 1);
  grid.set(kr[1][0] + "," + kr[1][1], 1);
  var idx = 0;
  for (k = 6; k <= rmax; k++)
    I.hexRing(k).forEach(function (c) {
      grid.set(c[0] + "," + c[1], idx < bits.length ? bits[idx] : 0);
      idx++;
    });
  return grid;
}

var nodeCompressed = Array.from(zlib.deflateSync(
  Buffer.from("Symbols compressed by another encoder must still decode. " +
              "ŠČŽ 🐝 " + "spiral ".repeat(20), "utf8"), { level: 9 }));
var decN = D.decode(assembleSymbol(nodeCompressed, 25));
check("interop:nodeZlibPayload", decN.text.indexOf("Symbols compressed") === 0 &&
      decN.stats.compressed === true && decN.stats.repairBits === 0);

// Stored-block path end-to-end as well (level 0 = stored DEFLATE).
var nodeStored = Array.from(zlib.deflateSync(
  Buffer.from("stored block payload", "utf8"), { level: 0 }));
check("interop:nodeStoredPayload",
      D.decode(assembleSymbol(nodeStored, 15)).text ===
      "stored block payload");

// --------------------------------------------------------------------
// 5. Strict UTF-8 and API errors
// --------------------------------------------------------------------

check("utf8:strictOverlong", throws(function () {
  D.internals.utf8Decode([0xC0, 0x80]); }));
check("utf8:strictSurrogate", throws(function () {
  D.internals.utf8Decode([0xED, 0xA0, 0x80]); }));
check("utf8:strictTruncated", throws(function () {
  D.internals.utf8Decode([0xE2, 0x82]); }));
check("utf8:strictBadContinuation", throws(function () {
  D.internals.utf8Decode([0xC3, 0x28]); }));
check("utf8:emojiOk",
      D.internals.utf8Decode(utf8("bee \u{1F41D}")) === "bee \u{1F41D}");

check("err:tinyGrid", throws(function () {
  D.decode(new Map()); }));
check("err:missingCell", throws(function () {
  var g = H.encode("x", { compress: false }).grid;
  g.delete("0,6");
  D.decode(g);
}));
check("err:notAGrid", throws(function () { D.decode(null); }));
check("err:badHex", throws(function () { D.decodeHex("zz"); }));

// decodeHex infers rmax from the hex length.
var ref = H.encode("hex inference", { compress: false });
var hex = H.canonicalHex(ref.grid, ref.params.rmax);
check("decodeHex:autoRmax",
      D.decodeHex(hex).text === "hex inference");

// --------------------------------------------------------------------
// Summary
// --------------------------------------------------------------------

console.log("Hexatess JS decoder: " + passed + " passed, " + failed +
            " failed" + (failed ? "  ✗" : "  ✓"));
process.exit(failed ? 1 : 0);
