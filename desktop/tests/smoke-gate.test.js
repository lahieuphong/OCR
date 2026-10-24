'use strict';
// The smoke test is a development/CI tool: a release build refuses it, only the internal test build allows it.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { smokeArgs, smokeAllowed } = require('../electron/lib/smoke-gate');
const afterPack = require('../scripts/after-pack');

const DESKTOP = path.resolve(__dirname, '..');

test('smoke options are parsed from argv; other options are ignored', () => {
  assert.deepEqual(smokeArgs(['electron.exe', '.', '--smoke-test=C:\\out=1', '--smoke-pdf=a.pdf', '--lang=vi']),
    { 'smoke-test': 'C:\\out=1', 'smoke-pdf': 'a.pdf' });
  assert.deepEqual(smokeArgs(['VietDoc OCR.exe']), {});
});

test('development allows the smoke test; a packaged build only with vietdocSmokeTest: true', () => {
  assert.equal(smokeAllowed({ packaged: false, packageJson: {} }), true);
  assert.equal(smokeAllowed({ packaged: true, packageJson: {} }), false);
  assert.equal(smokeAllowed({ packaged: true, packageJson: { vietdocSmokeTest: false } }), false);
  assert.equal(smokeAllowed({ packaged: true, packageJson: { vietdocSmokeTest: 'true' } }), false);
  assert.equal(smokeAllowed({ packaged: true, packageJson: null }), false);
  assert.equal(smokeAllowed({ packaged: true, packageJson: { vietdocSmokeTest: true } }), true);
});

// A Windows checkout (core.autocrlf=true, the default of actions/checkout on windows-latest) has CRLF line
// endings: compare the YAML text with LF endings so the same strict patterns apply on every OS.
function checkSmokeConfigs(releaseText, smokeText) {
  const release = releaseText.replace(/\r\n/g, '\n');
  const smoke = smokeText.replace(/\r\n/g, '\n');
  assert.match(release, /^extraMetadata:\n {2}vietdocSmokeTest: false$/m);
  assert.doesNotMatch(release, /vietdocSmokeTest: true/);
  assert.match(smoke, /^extends: electron-builder\.yml$/m);
  assert.match(smoke, /^ {2}vietdocSmokeTest: true$/m);
}

test('release config refuses the smoke test; only the test config enables it; the checkout sets neither', () => {
  checkSmokeConfigs(fs.readFileSync(path.join(DESKTOP, 'electron-builder.yml'), 'utf8'),
    fs.readFileSync(path.join(DESKTOP, 'electron-builder.smoke.yml'), 'utf8'));
  const pkg = JSON.parse(fs.readFileSync(path.join(DESKTOP, 'package.json'), 'utf8'));
  assert.equal('vietdocSmokeTest' in pkg, false);
});

test('the config check gives the same verdict for LF and CRLF files and still rejects a smoke-enabled release', () => {
  const lf = (text) => text.replace(/\r\n/g, '\n');
  const crlf = (text) => lf(text).replace(/\n/g, '\r\n');
  const release = fs.readFileSync(path.join(DESKTOP, 'electron-builder.yml'), 'utf8');
  const smoke = fs.readFileSync(path.join(DESKTOP, 'electron-builder.smoke.yml'), 'utf8');
  for (const eol of [lf, crlf]) {
    checkSmokeConfigs(eol(release), eol(smoke));
    const enabled = lf(release).replace('  vietdocSmokeTest: false', '  vietdocSmokeTest: true');
    assert.throws(() => checkSmokeConfigs(eol(enabled), eol(smoke)), assert.AssertionError);
    const unindented = lf(release).replace('  vietdocSmokeTest: false', 'vietdocSmokeTest: false');
    assert.throws(() => checkSmokeConfigs(eol(unindented), eol(smoke)), assert.AssertionError);
    assert.throws(() => checkSmokeConfigs(eol(release), eol(lf(smoke).replace('extends:', '# extends:'))), assert.AssertionError);
  }
});

test('afterPack removes only default_app.asar', async (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-afterpack-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const res = path.join(root, 'resources');
  fs.mkdirSync(res);
  fs.writeFileSync(path.join(res, 'default_app.asar'), 'x');
  fs.writeFileSync(path.join(res, 'app.asar'), 'y');
  await afterPack({ appOutDir: root });
  assert.deepEqual(fs.readdirSync(res), ['app.asar']);
  await afterPack({ appOutDir: root });  // already gone: no error
});
