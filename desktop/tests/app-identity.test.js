'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { appIdentity, configureAppIdentity, portableDataDir } = require('../electron/lib/app-identity');
const original = { name: 'VietDoc OCR', userDataName: null };

test('normal builds retain the existing app and profile identity', () => {
  assert.deepEqual(appIdentity(), original);
  for (const packageJson of [{}, { productName: 'Other' }, null]) {
    assert.deepEqual(appIdentity({ packaged: true, packageJson }), original);
  }
});

test('the packaged test build has a distinct app and user-data identity', () => {
  const identity = appIdentity({ packaged: true, packageJson: { vietdocTestBuild: true } });
  assert.equal(identity.name, 'VietDoc OCR Test');
  assert.equal(identity.userDataName, identity.name);
  assert.notEqual(identity.userDataName, original.name);
  assert.deepEqual(appIdentity({ packaged: false, packageJson: { vietdocTestBuild: true } }), original);
});

test('strings and arbitrary path values cannot select or redirect the test profile', () => {
  for (const value of [false, 'true', 1, '../other-profile', undefined]) {
    assert.deepEqual(appIdentity({ packaged: true, packageJson: { vietdocTestBuild: value } }), original);
  }
});

test('first test launch creates its own profile before Electron accepts it and preserves old data', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-profile-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const originalProfile = path.join(root, 'VietDoc OCR');
  fs.mkdirSync(originalProfile);
  const marker = path.join(originalProfile, 'settings.json');
  fs.writeFileSync(marker, 'existing settings');
  const paths = {};
  const app = {
    isPackaged: true,
    setName(name) { this.name = name; },
    getPath(name) { assert.equal(name, 'appData'); return root; },
    setPath(name, value) { assert.ok(fs.statSync(value).isDirectory()); paths[name] = value; },
  };
  configureAppIdentity(app, { vietdocTestBuild: true });
  assert.equal(app.name, 'VietDoc OCR Test');
  assert.equal(paths.userData, path.join(root, 'VietDoc OCR Test'));
  assert.equal(paths.sessionData, paths.userData);
  assert.equal(fs.readFileSync(marker, 'utf8'), 'existing settings');
});

test('normal builds do not override profiles or session storage', () => {
  const app = {
    isPackaged: true,
    setName(name) { this.name = name; },
    getPath() { assert.fail('normal profile must not be changed'); },
    setPath() { assert.fail('normal profile must not be changed'); },
  };
  configureAppIdentity(app, {});
  assert.equal(app.name, 'VietDoc OCR');
});

function installLayout(t, { dataDir = true, name = 'VietDoc OCR' } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-portable-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const install = path.join(root, 'VietDoc OCR');
  fs.mkdirSync(install);
  const data = path.join(root, `${name} Data`);
  if (dataDir) fs.mkdirSync(data);
  return { root, execPath: path.join(install, 'VietDoc OCR.exe'), data };
}

test('a "<name> Data" folder beside the install folder is used only by packaged apps and only when it exists', (t) => {
  const { execPath, data } = installLayout(t);
  assert.equal(portableDataDir({ packaged: true, name: 'VietDoc OCR', execPath, platform: 'win32' }), data);
  assert.equal(portableDataDir({ packaged: false, name: 'VietDoc OCR', execPath, platform: 'win32' }), null);
  assert.equal(portableDataDir({ packaged: true, name: 'VietDoc OCR Test', execPath, platform: 'win32' }), null);
  assert.equal(portableDataDir({ packaged: true, name: 'VietDoc OCR', execPath: 'relative/VietDoc OCR.exe', platform: 'win32' }), null);
  const missing = installLayout(t, { dataDir: false });
  assert.equal(portableDataDir({ packaged: true, name: 'VietDoc OCR', execPath: missing.execPath, platform: 'win32' }), null);
});

test('a file named like the data folder is not a data folder', (t) => {
  const { execPath, root } = installLayout(t, { dataDir: false });
  fs.writeFileSync(path.join(root, 'VietDoc OCR Data'), 'not a folder');
  assert.equal(portableDataDir({ packaged: true, name: 'VietDoc OCR', execPath, platform: 'win32' }), null);
});

test('on macOS the data folder sits beside the .app bundle', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-portable-mac-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const data = path.join(root, 'VietDoc OCR Data');
  fs.mkdirSync(data);
  const execPath = path.join(root, 'VietDoc OCR.app', 'Contents', 'MacOS', 'VietDoc OCR');
  assert.equal(portableDataDir({ packaged: true, name: 'VietDoc OCR', execPath, platform: 'darwin' }), data);
});

test('an existing data folder holds the profile and session storage instead of AppData', (t) => {
  const { execPath, data } = installLayout(t);
  const paths = {};
  const app = {
    isPackaged: true,
    setName(name) { this.name = name; },
    getPath() { assert.fail('AppData must not be used when the data folder exists'); },
    setPath(name, value) { paths[name] = value; },
  };
  const identity = configureAppIdentity(app, {}, { execPath, platform: 'win32' });
  assert.equal(app.name, 'VietDoc OCR');
  assert.deepEqual(paths, { userData: data, sessionData: data });
  assert.equal(identity.portableDataDir, data);
});

test('the test build looks for its own "VietDoc OCR Test Data" folder and otherwise keeps its AppData profile', (t) => {
  const own = installLayout(t, { name: 'VietDoc OCR Test' });
  const paths = {};
  const app = {
    isPackaged: true,
    setName(name) { this.name = name; },
    getPath() { assert.fail('AppData must not be used when the data folder exists'); },
    setPath(name, value) { paths[name] = value; },
  };
  configureAppIdentity(app, { vietdocTestBuild: true }, { execPath: own.execPath, platform: 'win32' });
  assert.equal(paths.userData, own.data);

  const releaseDataOnly = installLayout(t);
  const appData = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-appdata-'));
  t.after(() => fs.rmSync(appData, { recursive: true, force: true }));
  const testPaths = {};
  configureAppIdentity({
    isPackaged: true,
    setName() {},
    getPath(name) { assert.equal(name, 'appData'); return appData; },
    setPath(name, value) { testPaths[name] = value; },
  }, { vietdocTestBuild: true }, { execPath: releaseDataOnly.execPath, platform: 'win32' });
  assert.equal(testPaths.userData, path.join(appData, 'VietDoc OCR Test'));
});

test('development runs never use a data folder beside the Electron binary', (t) => {
  const { execPath } = installLayout(t);
  const app = {
    isPackaged: false,
    setName(name) { this.name = name; },
    getPath() { assert.fail('development profile must not be changed'); },
    setPath() { assert.fail('development profile must not be changed'); },
  };
  assert.equal(configureAppIdentity(app, {}, { execPath, platform: 'win32' }).portableDataDir, null);
});
