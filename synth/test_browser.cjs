// Test the actual shipped JS applier and page event handlers with a minimal DOM.
// This is not a visual browser test or a device/DOOM OS runtime test.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const root = path.join(__dirname, '..');
const input = process.argv[2];
if (!input) throw new Error('Usage: node synth/test_browser.cjs /path/to/stock/SP404MKII_APP1.bin');
const stock = new Uint8Array(fs.readFileSync(input));
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const KITS_SHA = 'e54935c305cbc16111263dc34614c4a713fba1dda0dff69349cfd5b3fb07d6e6';
const KITS_SIZE = 3152352;

function load(includeKits = true) {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      id, checked: false, hidden: false, disabled: false, value: '', listeners: {},
      classList: { add() {}, remove() {} },
      addEventListener(event, fn) { this.listeners[event] = fn; },
      click() {},
    });
    return elements.get(id);
  };
  let start, blob = null;
  const context = vm.createContext({
    window: { addEventListener() {} },
    document: {
      readyState: 'loading',
      addEventListener(event, fn) { if (event === 'DOMContentLoaded') start = fn; },
      querySelectorAll() { return []; },
      getElementById(id) { return get(id); },
    },
    module: { exports: {} },
    setTimeout(fn) { fn(); },
    Blob,
    URL: { createObjectURL(value) { blob = value; return 'blob:test'; }, revokeObjectURL() { blob = null; } },
  });
  if (includeKits) vm.runInContext(fs.readFileSync(path.join(root, 'kits-data.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(root, 'doomos-patcher.js'), 'utf8'), context);
  start();
  return { context, get, api: context.module.exports, blob: () => blob };
}

async function choose(page, bytes, name = 'SP404MKII_APP1.bin') {
  page.get('file').files = [{ name, size: bytes.length, async arrayBuffer() { return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength); } }];
  await page.get('file').listeners.change();
}

async function download(page) {
  return digest(new Uint8Array(await page.blob().arrayBuffer()));
}

(async () => {
  const page = load();
  const { api } = page;
  for (let len = 0; len < 128; len++) {
    const original = Uint8Array.from({ length: len }, (_, i) => (i * 73 + len) & 255);
    assert.equal(Buffer.from(api.fromBase64(Buffer.from(original).toString('base64'))).toString('hex'), Buffer.from(original).toString('hex'));
  }
  assert.equal(api.hex(api.sha256(stock)), digest(stock), 'browser SHA matches Node');

  // The overlays: DOOM OS base from stock 5.52, then v9.47 (combined-test6: the combined feature build + fast boot + kit footer).
  const kits = page.context.window.DOOMOS_KITS;
  const doom = api.applyPatch(api.fromBase64(page.context.window.DOOMOS_PATCH), stock);
  assert.equal(doom.digest, kits.base_sha256);
  const kitOverlay = api.fromBase64(page.context.window.DOOMOS_KITS_PATCH);
  const kitResult = api.applyPatch(kitOverlay, doom.bytes);
  assert.equal(kitResult.digest, KITS_SHA);
  assert.equal(kitResult.bytes.length, KITS_SIZE);
  assert.equal(kits.sha256, KITS_SHA);
  assert.equal(kits.size, KITS_SIZE);
  assert.equal(kits.release, 'v9.47');
  assert.equal(kits.revision, 'combined-test6');
  assert.equal(kits.start_fix, 'resample-startfix-3');
  assert.equal(kits.combined_sha256, '7fd468087d7b6c4c750256ffebc2cac966cd852086004ee4d33425a6dddebf57');
  assert.equal(kits.kit_stage_sha256, '88384c3c9760559e721c1a14973ef3a2ced6abf016572b0a73c5dfb0cef492ba');
  assert.equal(kits.features.length, 11);
  assert.equal(kits.hardware_verified, false);
  assert.equal(JSON.stringify(kits.kit_selector_range), '[1,13]');
  assert.equal(kits.kits.length, 13);
  assert.equal(kits.synthesis_only, true);
  assert.throws(() => api.applyPatch(kitOverlay, stock), /unsupported firmware/);
  const badKit = kitOverlay.slice(); badKit[badKit.length - 1] ^= 1;
  assert.throws(() => api.applyPatch(badKit, doom.bytes), /came out wrong/);

  // One build, no selector: drop in stock, press Patch, get v9.47.
  const panel = page.get('doomos-patcher').innerHTML;
  assert.equal((panel.match(/type="checkbox"/g) || []).length, 0, 'no build selector');
  assert.match(panel, /Builds Sound Generator \+ Kits v9\.47 on DOOM OS 0\.6\.1 \(ED5E\)/);
  await choose(page, stock);
  assert.equal(page.get('patch').disabled, false);
  await page.get('patch').listeners.click();
  assert.equal(page.get('download').hidden, false);
  assert.equal(await download(page), KITS_SHA);
  assert.match(page.get('status').textContent, /Sound Generator \+ Kits v9\.47 with DOOM OS 0\.6\.1 has been patched into firmware 5\.52\+kits-v9\.47/);

  page.get('reset').listeners.click();
  assert.equal(page.get('download').hidden, true);
  await choose(page, stock);
  await page.get('patch').listeners.click();
  assert.equal(await download(page), KITS_SHA, 'patching again gives the same file');

  page.get('reset').listeners.click();
  await choose(page, kitResult.bytes);
  assert.equal(page.get('patch').disabled, true);
  assert.equal(page.get('download').hidden, true);
  assert.match(page.get('status').textContent, /not a firmware file this patcher knows/);
  await choose(page, new Uint8Array([1, 2, 3]), 'SP404MKII_APP0.bin');
  assert.match(page.get('status').textContent, /This is SP404MKII_APP0.bin/);

  // A failed overlay must never create a downloadable corrupt result.
  const broken = load();
  broken.context.window.DOOMOS_KITS_PATCH = Buffer.from(badKit).toString('base64');
  await choose(broken, stock);
  await broken.get('patch').listeners.click();
  assert.equal(broken.blob(), null);
  assert.equal(broken.get('download').hidden, true);
  assert.match(broken.get('status').textContent, /came out wrong/);

  // Without the kit data the script still makes the DOOM OS base, as upstream does.
  const plain = load(false);
  assert.doesNotMatch(plain.get('doomos-patcher').innerHTML, /Builds Sound Generator/);
  await choose(plain, stock);
  await plain.get('patch').listeners.click();
  assert.equal(await download(plain), doom.digest);
  assert.match(plain.get('status').textContent, /Base build without synth additions/);

  // The page and README.
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8');
  assert.match(html, /kits-data\.js\?v=kits-v9-47-e54935c3/);
  assert.match(html, /doomos-patcher\.js\?v=kits-v9-47-doom-os/);
  assert.doesNotMatch(html, /synth-data\.js|waves-data\.js|kits-midi-data|MIDI test guide|v9\.43|v9\.44/);
  assert.doesNotMatch(html, /[Tt]ick one|unticked|Pick one of/);
  assert.match(html, /What's new in v9\.47/);
  for (const feature of ['Bounce in place', 'Pad envelopes', 'Note repeat', 'Chromatic scales', 'Saved with the project',
                         'SUB PAD on the Sound Generator', 'FX deep edit', 'Fast boot', 'RESAMPLE start fix v3']) {
    assert.ok(html.includes('<strong>' + feature + ':</strong>'), 'page lists ' + feature);
    assert.ok(readme.includes('**' + feature + ':**'), 'README lists ' + feature);
  }
  assert.doesNotMatch(html + readme, /reset at power-on|are not saved|returns to 16 at power-on/);
  assert.match(html + readme, /THIRD-PARTY-NOTICES\.md/);
  assert.ok(fs.existsSync(path.join(root, 'THIRD-PARTY-NOTICES.md')), 'the DM-404 notice is in the repository');
  assert.match(html, /What's new in Kits v9\.46/);
  assert.match(html, /Drum kit guide \(v9\.46\)/);
  assert.match(html, /MIDI guide \(Kits v9\.46\)/);
  assert.match(html, /Envelope preset guide \(ENV\)/);
  assert.match(html, /34 scales and MIDI IN \(v9\.6\)/);
  assert.match(html, /Arpeggiator guide \(v9\.9\.3\)/);
  assert.match(readme, /Sound Generator envelopes \(v9\.9\.3\)/);
  assert.match(readme, /## Scale pads \(v9\.9\.3\)/);
  assert.match(readme, /## Arpeggiator \(v9\.9\.3\)/);
  assert.match(readme, /### Using the kits \(v9\.46\)/);
  assert.doesNotMatch(readme, /Pattern sequencer with a graphical interface|## Main controls|## Upstream plans|## Improvements/);
  assert.doesNotMatch(html, /Base released|data-doomos="version"|data-doomos="build"/);
  // The page says the build includes DOOM OS and links its quickstart.
  assert.match(html, /builds Sound Generator \+ Kits v9\.47 on DOOM OS 0\.6\.1, so your firmware includes DOOM OS/);
  assert.match(html, /<h2>DOOM OS<span class="v">0\.6\.1<\/span><\/h2>/);
  assert.match(html, /<dt>DOOM OS<\/dt><dd>0\.6\.1<\/dd>/);
  assert.match(html, /href="manual\/">DOOM OS quickstart/);
  assert.ok(fs.existsSync(path.join(root, 'manual', 'index.html')), 'DOOM OS quickstart is in the repository');
  assert.match(readme, /built on, and includes, \*\*DOOM OS 0\.6\.1\*\*/);
  for (const name of ['OFF', 'Pluck', 'Perc', 'Keys', 'Pad', 'Swell', 'Bass', 'Acid', 'Sweep', 'FPad']) {
    assert.ok(html.includes(name), 'page documents ENV preset ' + name);
    assert.ok(readme.includes('| ' + name + ' |'), 'README documents ENV preset ' + name);
  }
  assert.doesNotMatch(html, /For V8, start at modest LEVEL|Uncheck Wave Lab|Expected Wave Lab V8 APP1/);
  assert.doesNotMatch(readme, /<img[^>]*doom-os-512/);
  assert.doesNotMatch(html, /<img[^>]*doom-os/);
  console.log('PASS: one build, no selector: stock 5.52 gives exactly Sound Generator + Kits v9.47 (combined-test6), repeatably; overlay metadata, wrong-input and corruption rejection, no corrupt download, DOOM OS base without kit data; page and README text.');
})().catch(error => { console.error(error); process.exitCode = 1; });
