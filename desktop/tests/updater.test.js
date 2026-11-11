'use strict';
// Only the installed release updates itself; the Portable copy, development runs, smoke and test builds never do.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { updatesAllowed, startUpdates, checkNow } = require('../electron/lib/updater');

function installed({ uninstaller = true, feed = true } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-updater-'));
  const resources = path.join(dir, 'resources');
  fs.mkdirSync(resources);
  fs.writeFileSync(path.join(dir, 'VietDoc OCR.exe'), '');
  if (uninstaller) fs.writeFileSync(path.join(dir, 'Uninstall VietDoc OCR.exe'), '');
  if (feed) fs.writeFileSync(path.join(resources, 'app-update.yml'), 'provider: github\n');
  return { packaged: true, smoke: false, packageJson: { vietdocUpdates: true }, execPath: path.join(dir, 'VietDoc OCR.exe'),
    resourcesPath: resources, productName: 'VietDoc OCR', portableDataDir: null };
}

test('updater: the installed release with an update feed updates itself', () => {
  assert.deepEqual(updatesAllowed(installed()), { allowed: true, reason: 'installed release' });
});

test('updater: never in development, smoke, Portable, test builds or builds without the switch', () => {
  const base = installed();
  const cases = {
    'development run': { packaged: false },
    'smoke test': { smoke: true },
    'portable copy': { portableDataDir: 'D:\\VietDoc OCR Data' },
    'build without updates': { packageJson: {} },
    'test build': { packageJson: { vietdocUpdates: true, vietdocTestBuild: true } },
  };
  for (const [reason, change] of Object.entries(cases)) {
    assert.deepEqual(updatesAllowed({ ...base, ...change }), { allowed: false, reason }, reason);
  }
  assert.equal(updatesAllowed({ ...base, packageJson: { vietdocUpdates: true, vietdocSmokeTest: true } }).reason, 'test build');
});

test('updater: a copy without an uninstaller (Portable ZIP, unpacked folder) or without a feed does not update', () => {
  assert.equal(updatesAllowed(installed({ uninstaller: false })).reason, 'not an installed copy');
  assert.equal(updatesAllowed(installed({ feed: false })).reason, 'no update feed');
});

test('updater: checks once after start-up, downloads in the background, installs on quit, logs every event', async () => {
  const updater = new EventEmitter();
  let checks = 0;
  updater.checkForUpdatesAndNotify = async () => { checks += 1; };
  const lines = [];
  let scheduled;
  startUpdates({ updater, log: (kind, message) => lines.push(`${kind} ${message}`), schedule: (fn, ms) => { scheduled = ms; fn(); } });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(checks, 1);
  assert.equal(scheduled, 10_000);
  assert.equal(updater.autoDownload, true);
  assert.equal(updater.autoInstallOnAppQuit, true);
  updater.emit('update-available', { version: '0.1.1' });
  updater.emit('error', new Error('offline'));
  assert.deepEqual(lines, ['update update-available version 0.1.1', 'update error offline']);
});

test('updater: a failing check is logged, never thrown', async () => {
  const updater = new EventEmitter();
  updater.checkForUpdatesAndNotify = async () => { throw new Error('no network'); };
  const lines = [];
  startUpdates({ updater, log: (kind, message) => lines.push(`${kind} ${message}`), schedule: (fn) => fn() });
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.match(lines.join('\n'), /update error Error: no network/);
});

test('updater: the menu answer says whether a newer version is downloading', async () => {
  const newer = { checkForUpdates: async () => ({ isUpdateAvailable: true, updateInfo: { version: '0.1.1' } }) };
  const same = { checkForUpdates: async () => ({ isUpdateAvailable: false, updateInfo: { version: '0.1.0' } }) };
  const offline = { checkForUpdates: async () => { throw new Error('net::ERR_INTERNET_DISCONNECTED'); } };
  assert.match((await checkNow({ updater: newer, currentVersion: '0.1.0' })).message, /Đang tải VietDoc OCR 0\.1\.1/);
  assert.match((await checkNow({ updater: same, currentVersion: '0.1.0' })).message, /bản mới nhất \(0\.1\.0\)/);
  const answer = await checkNow({ updater: offline, currentVersion: '0.1.0' });
  assert.equal(answer.type, 'warning');
  assert.match(answer.detail, /ERR_INTERNET_DISCONNECTED/);
});
