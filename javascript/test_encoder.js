/*
 * Hexatess Code — JavaScript encoder conformance tests (Node.js).
 *
 * Run:  node javascript/test_encoder.js
 *
 * The strongest check: for every uncompressed vector in
 * test_vectors/vectors_v0.3.json the JS encoder must produce a
 * byte-identical header (mode_hex) and a byte-identical full grid
 * (grid_hex) compared to the Python reference implementation.
 * Compressed vectors use DEFLATE with encoder-specific compression
 * choices, so they are cross-validated by scripts/preveri_js_kodirnik.py
 * (JS output -> Python decoder) instead of byte comparison.
 */
"use strict";

var fs = require("fs");
var path = require("path");
var H = require("./hexatess-encoder.js");

var passed = 0, failed = 0;

function check(name, cond, detail) {
  if (cond) { passed++; }
  else {
    failed++;
    console.error("FAIL: " + name + (detail ? " — " + detail : ""));
  }
}

function hexEqual(a, b) { return a === b; }

// --------------------------------------------------------------------
// 1. Conformance: byte-identical output for uncompressed vectors
// --------------------------------------------------------------------

var vectors = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "test_vectors", "vectors_v0.3.json"), "utf8"));

var uncompressed = 0, compressed = 0;
vectors.encode_vectors.forEach(function (c) {
  if (!c.compressed) {
    uncompressed++;
    var out = H.encode(c.text, { ecPct: c.ec_pct, compress: false });
    var gridHex = H.canonicalHex(out.grid, out.params.rmax);
    check("vector:" + c.name + ":rmax", out.params.rmax === c.rmax,
          "got " + out.params.rmax + ", want " + c.rmax);
    check("vector:" + c.name + ":mask", out.params.mask === c.mask,
          "got " + out.params.mask + ", want " + c.mask);
    check("vector:" + c.name + ":dataLen", out.params.dataLen === c.data_len,
          "got " + out.params.dataLen + ", want " + c.data_len);
    check("vector:" + c.name + ":grid", gridHex === c.grid_hex,
          "grid_hex mismatch (" + gridHex.length + " vs " + c.grid_hex.length + " chars)");
    var modeHex = H.internals.packMode(out.params.rmax, out.params.mask,
                                       c.ec_pct, out.params.blocks.length,
                                       out.params.dataLen, false)
                       .map(function (b) {
                         return (b < 16 ? "0" : "") + b.toString(16);
                       }).join("");
    check("vector:" + c.name + ":mode", modeHex === c.mode_hex,
          "got " + modeHex + ", want " + c.mode_hex);
  } else {
    compressed++;
    // Forced compression must at least mark itself as compressed and
    // store fewer bytes than the raw text in these curated cases.
    var out2 = H.encode(c.text, { ecPct: c.ec_pct, compress: true });
    check("vector:" + c.name + ":compressedFlag", out2.params.compressed === true);
    check("vector:" + c.name + ":shorter",
          out2.params.dataLen < Buffer.byteLength(c.text, "utf8"),
          "stored " + out2.params.dataLen + " vs raw " +
          Buffer.byteLength(c.text, "utf8"));
    // 'auto' must agree on compressing these curated cases.
    var out3 = H.encode(c.text, { ecPct: c.ec_pct });
    check("vector:" + c.name + ":auto", out3.params.compressed === true);
  }
});
check("vectorCount", vectors.encode_vectors.length === 13,
      "expected 13 vectors, found " + vectors.encode_vectors.length);

// --------------------------------------------------------------------
// 2. Internal invariants
// --------------------------------------------------------------------

var sample = "Hexatess conformance sample — čšž ŠČŽ ✓✓✓ 0123456789";
var out = H.encode(sample);
var p = out.params;

check("inv:rmaxRange", p.rmax >= 7 && p.rmax <= 31);
check("inv:maskRange", p.mask >= 0 && p.mask <= 7);
check("inv:ec", p.ec === 30);
check("inv:blocksSum", p.blocks.reduce(function (s, b) { return s + b[0]; }, 0)
      === p.dataLen);
check("inv:capacity",
      H.internals.ringCapacity(6, p.rmax) >=
      H.internals.MODE_BITS + (p.dataLen +
        p.blocks.reduce(function (s, b) { return s + b[1]; }, 0)) * 8);

// grid shape: exactly all cells of rings 0..rmax
var cellCount = 0;
out.grid.forEach(function () { cellCount++; });
check("inv:cellCount", cellCount === 3 * p.rmax * (p.rmax + 1) + 1,
      "got " + cellCount);

// bullseye: centre dark, rings alternate
var I = H.internals;
check("inv:centreDark", out.grid.get("0,0") === 1);
check("inv:ring1Light", I.hexRing(1).every(function (c) {
  return out.grid.get(c[0] + "," + c[1]) === 0; }));
check("inv:ring4Dark", I.hexRing(4).every(function (c) {
  return out.grid.get(c[0] + "," + c[1]) === 1; }));
var kr = I.hexRing(5);
check("inv:keyRing", out.grid.get(kr[0][0] + "," + kr[0][1]) === 1 &&
                      out.grid.get(kr[1][0] + "," + kr[1][1]) === 1 &&
                      kr.slice(2).every(function (c) {
                        return out.grid.get(c[0] + "," + c[1]) === 0; }));

// --------------------------------------------------------------------
// 3. Mask determinism + forced masks
// --------------------------------------------------------------------

var base = H.encode(sample, { compress: false });
for (var m = 0; m < 8; m++) {
  var forced = H.encode(sample, { compress: false, mask: m });
  check("mask" + m, forced.params.mask === m);
}
// auto == forced with the auto-chosen mask
var autoMasked = H.encode(sample, { compress: false,
                                    mask: base.params.mask });
check("maskConsistency",
      H.canonicalHex(autoMasked.grid, autoMasked.params.rmax) ===
      H.canonicalHex(base.grid, base.params.rmax));

// --------------------------------------------------------------------
// 4. Compression behaviour
// --------------------------------------------------------------------

var repetitive = "0123456789".repeat(8);          // 80 digits
var autoRep = H.encode(repetitive);
check("comp:digitsCompressed", autoRep.params.compressed === true,
      "digits should compress");
check("comp:digitsShorter", autoRep.params.dataLen < 80);

var incompressible = "";
(function () {
  // Deterministic pseudo-random text -> deflate cannot shrink it much.
  var x = 12345, chars = "abcdefXYZ0123456789 ,.";
  for (var i = 0; i < 60; i++) {
    x = (x * 1103515245 + 12345) % 2147483648;
    incompressible += chars[x % chars.length];
  }
})();
var autoInc = H.encode(incompressible);
check("comp:incompressibleRaw",
      autoInc.params.compressed === false || autoInc.params.dataLen <= 60,
      "auto may only compress when strictly smaller");
var forced = H.encode(incompressible, { compress: true });
check("comp:forcedCompressed", forced.params.compressed === true);
check("comp:forcedNotSmaller", forced.params.dataLen >= autoInc.params.dataLen,
      "forced compression must never beat auto on stored length");

// --------------------------------------------------------------------
// 5. Error handling
// --------------------------------------------------------------------

function throws(fn) {
  try { fn(); return false; } catch (e) { return true; }
}
check("err:ecBadStep", throws(function () { H.encode("x", { ecPct: 7 }); }));
check("err:ecLow", throws(function () { H.encode("x", { ecPct: 0 }); }));
check("err:ecHigh", throws(function () { H.encode("x", { ecPct: 95 }); }));
check("err:maskRange", throws(function () { H.encode("x", { mask: 9 }); }));
check("err:compressMode", throws(function () {
  H.encode("x", { compress: "yes" }); }));
check("err:tooLong", throws(function () {
  H.encode(new Array(5000).join("a")); }));   // 4999 bytes > 4095

// --------------------------------------------------------------------
// 6. Renderer smoke test
// --------------------------------------------------------------------

var svg = H.renderSVG(out.grid);
check("render:svg", svg.indexOf("<svg") === 0 && svg.indexOf("<path") > 0);
check("render:width", /width="[0-9.]+"/.test(svg));

// --------------------------------------------------------------------
// Summary
// --------------------------------------------------------------------

console.log("Hexatess JS encoder: " + passed + " passed, " + failed +
            " failed" + (failed ? "  ✗" : "  ✓"));
process.exit(failed ? 1 : 0);
