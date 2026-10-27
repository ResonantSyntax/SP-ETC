// Write the DOOM OS base and the v9.52 APP1 from a stock 5.52 APP1, using the
// shipped browser patcher (the same code path as index.html), to a folder.
// The v9.52 image is the parent a new feature module is built on.
//
// usage: node dev/make_v9_52.cjs /path/to/stock/SP404MKII_APP1.bin out/v9.52
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');

const root = path.resolve(__dirname, '..');
const [stockPath, outDir] = process.argv.slice(2);
if (!stockPath || !outDir) {
  console.error('usage: node dev/make_v9_52.cjs STOCK_APP1.bin OUT_DIR');
  process.exit(2);
}
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

const context = vm.createContext({
  window: { addEventListener() {} },
  document: { readyState: 'loading', addEventListener() {}, querySelectorAll: () => [], getElementById: () => null },
  module: { exports: {} },
  setTimeout() {},
  Blob,
  URL: {},
});
vm.runInContext(fs.readFileSync(path.join(root, 'kits-data.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.join(root, 'doomos-patcher.js'), 'utf8'), context);
const api = context.module.exports;
const kits = context.window.DOOMOS_KITS;

const stock = new Uint8Array(fs.readFileSync(stockPath));
const doom = api.applyPatch(api.fromBase64(context.window.DOOMOS_PATCH), stock);
const full = api.applyPatch(api.fromBase64(context.window.DOOMOS_KITS_PATCH), doom.bytes);
if (doom.digest !== kits.base_sha256 || full.digest !== kits.sha256) throw new Error('unexpected output hash');

fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(path.join(outDir, 'DOOM-ED5E_APP1.bin'), doom.bytes);
fs.writeFileSync(path.join(outDir, 'SP404MKII_APP1.bin'), full.bytes);
const app0 = path.join(path.dirname(stockPath), 'SP404MKII_APP0.bin');
if (fs.existsSync(app0)) fs.copyFileSync(app0, path.join(outDir, 'SP404MKII_APP0.bin'));
console.log(`DOOM OS ED5E  ${doom.digest}`);
console.log(`${kits.release} (${kits.revision})  ${digest(full.bytes)}  ${full.bytes.length} bytes`);
