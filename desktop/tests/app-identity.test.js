'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { appIdentity, configureAppIdentity } = require('../electron/lib/app-identity');
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
