'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { SPLASH_HTML, SPLASH_URL, statusWindowNeeded } = require('../electron/lib/splash');
const { isAllowedRequest } = require('../electron/lib/security');

test('the startup page is static: no script, no external resource, a strict CSP', () => {
  assert.doesNotMatch(SPLASH_HTML, /<script|<link|<img|<iframe|https?:|src=|href=/i);
  assert.match(SPLASH_HTML, /Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"/);
  assert.match(SPLASH_HTML, /Đang khởi động…/);
});

test('the startup page loads in the hardened app session before the backend has an origin', () => {
  assert.ok(SPLASH_URL.startsWith('data:text/html;charset=utf-8,'));
  assert.equal(decodeURIComponent(SPLASH_URL.slice(SPLASH_URL.indexOf(',') + 1)), SPLASH_HTML);
  assert.equal(isAllowedRequest(SPLASH_URL, null), true);
});

test('the status window is only needed for an error, not for missing models', () => {
  assert.equal(statusWindowNeeded({ state: 'starting' }), false);
  assert.equal(statusWindowNeeded({ state: 'ready', desktop: { ocr_allowed: true } }), false);
  assert.equal(statusWindowNeeded({ state: 'limited', desktop: { ocr_allowed: false } }), false);
  assert.equal(statusWindowNeeded({ state: 'error' }), true);
  assert.equal(statusWindowNeeded(null), false);
});
