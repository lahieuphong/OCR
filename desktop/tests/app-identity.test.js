'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { appIdentity } = require('../electron/lib/app-identity');
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
