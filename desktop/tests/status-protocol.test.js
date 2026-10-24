'use strict';
// The status page is served over vietdoc-status://app/ (the release build disables file:// privileges).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { STATUS_URL, STATUS_SCHEME_PRIVILEGES, statusFile, statusHandler } = require('../electron/lib/status-protocol');

const ELECTRON_DIR = path.resolve(__dirname, '..', 'electron');

test('only the three status page files are served, for exact URLs', () => {
  assert.equal(STATUS_URL, 'vietdoc-status://app/status.html');
  assert.deepEqual(statusFile(STATUS_URL), { name: 'status.html', type: 'text/html; charset=utf-8' });
  assert.equal(statusFile('vietdoc-status://app/status.css').name, 'status.css');
  assert.equal(statusFile('vietdoc-status://app/status.js').name, 'status.js');
  for (const url of ['vietdoc-status://app/main.js', 'vietdoc-status://app/lib/config.js', 'vietdoc-status://app/../main.js',
    'vietdoc-status://app/%2e%2e/main.js', 'vietdoc-status://app/preload-status.js', 'vietdoc-status://other/status.html',
    'vietdoc-status://app/status.html?x=1', 'vietdoc-status://app/status.html#x', 'vietdoc-status://u:p@app/status.html',
    'vietdoc-status://app/', 'vietdoc-status://app/STATUS.HTML', 'file:///C:/app/electron/status.html',
    'http://127.0.0.1:5000/status.html', 'not a url', '']) {
    assert.equal(statusFile(url), null, url);
  }
});

test('the handler returns the page from the app folder and 404 for anything else', async () => {
  const handle = statusHandler(ELECTRON_DIR);
  const page = handle({ url: STATUS_URL, method: 'GET' });
  assert.equal(page.status, 200);
  assert.equal(page.headers.get('content-type'), 'text/html; charset=utf-8');
  assert.equal(page.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(await page.text(), fs.readFileSync(path.join(ELECTRON_DIR, 'status.html'), 'utf8'));
  assert.equal(handle({ url: 'vietdoc-status://app/main.js', method: 'GET' }).status, 404);
  assert.equal(handle({ url: STATUS_URL, method: 'POST' }).status, 404);
});

test('the page keeps working under its CSP: relative assets resolve to the same served origin', () => {
  assert.deepEqual(STATUS_SCHEME_PRIVILEGES, { scheme: 'vietdoc-status', privileges: { standard: true, secure: true } });
  const html = fs.readFileSync(path.join(ELECTRON_DIR, 'status.html'), 'utf8');
  for (const ref of [...html.matchAll(/(?:href|src)="([^"]+)"/g)].map((m) => m[1])) {
    assert.ok(statusFile(new URL(ref, STATUS_URL).href), `${ref} must be served`);
  }
  assert.match(html, /default-src 'none'; script-src 'self'; style-src 'self'/);
});
