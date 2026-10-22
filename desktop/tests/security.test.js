'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const security = require('../electron/lib/security');

const ORIGIN = 'http://127.0.0.1:51234';
const STATUS = 'file:///E:/app/desktop/electron/status.html';

test('navigation stays on the app origin or the status page', () => {
  assert.ok(security.isAllowedNavigation(`${ORIGIN}/`, ORIGIN, STATUS));
  assert.ok(security.isAllowedNavigation(`${ORIGIN}/index.html?x=1#a`, ORIGIN, STATUS));
  assert.ok(security.isAllowedNavigation(STATUS, ORIGIN, STATUS));
  for (const url of ['https://example.com/', 'http://127.0.0.1:51235/', 'http://localhost:51234/', 'http://127.0.0.1.nip.io:51234/',
    'file:///C:/Windows/win.ini', 'javascript:alert(1)', `${STATUS}?x`, 'not a url']) {
    assert.equal(security.isAllowedNavigation(url, ORIGIN, STATUS), false, url);
  }
  assert.equal(security.isAllowedNavigation(`${ORIGIN}/`, null, STATUS), false, 'no backend yet');
});

test('requests: app origin, its own blob/data URLs and the PDF viewer only', () => {
  for (const url of [`${ORIGIN}/api/health`, `${ORIGIN}/assets/index.js`, `blob:${ORIGIN}/0b6c1d5e`, 'data:image/png;base64,AA==',
    `${security.PDF_VIEWER}index.html`, 'chrome://resources/js/assert.js']) {
    assert.ok(security.isAllowedRequest(url, ORIGIN), url);
  }
  for (const url of ['https://fonts.googleapis.com/css', 'http://127.0.0.1:8765/api/ocr', 'blob:http://127.0.0.1:9/x',
    'chrome-extension://abcdefghijklmnopabcdefghijklmnop/', 'file:///C:/secret.txt', 'ws://127.0.0.1:51234/',
    'chrome://settings/', 'chrome://gpu/', 'chrome://resourcesx/']) {
    assert.equal(security.isAllowedRequest(url, ORIGIN), false, url);
  }
});

test('downloads: only blob URLs created by the app origin (TXT/JSON export)', () => {
  assert.ok(security.isAllowedDownload(`blob:${ORIGIN}/7f1e`, ORIGIN));
  assert.equal(security.isAllowedDownload(`${ORIGIN}/api/ocr`, ORIGIN), false);
  assert.equal(security.isAllowedDownload('https://example.com/a.exe', ORIGIN), false);
  assert.equal(security.isAllowedDownload('blob:http://127.0.0.1:1/x', ORIGIN), false);
  assert.equal(security.isAllowedDownload(`blob:${ORIGIN}/x`, null), false);
});

test('hardenContents blocks foreign navigation, webviews and new windows', () => {
  const contents = new EventEmitter();
  let openHandler;
  contents.setWindowOpenHandler = (fn) => { openHandler = fn; };
  security.hardenContents(contents, () => ({ origin: ORIGIN, statusUrl: STATUS }));
  const fire = (name, url) => {
    let prevented = false;
    contents.emit(name, { preventDefault: () => { prevented = true; } }, url);
    return prevented;
  };
  assert.equal(fire('will-navigate', `${ORIGIN}/`), false);
  assert.equal(fire('will-navigate', 'https://example.com/'), true);
  assert.equal(fire('will-redirect', 'https://example.com/'), true);
  assert.equal(fire('will-attach-webview', `${ORIGIN}/`), true);
  assert.deepEqual(openHandler({ url: `${ORIGIN}/` }), { action: 'deny' });
});

function fakeSession() {
  const handlers = {};
  return {
    handlers,
    setPermissionRequestHandler: (fn) => { handlers.permissionRequest = fn; },
    setPermissionCheckHandler: (fn) => { handlers.permissionCheck = fn; },
    webRequest: {
      onBeforeRequest: (filter, fn) => { handlers.beforeRequest = { filter, fn }; },
      onBeforeSendHeaders: (filter, fn) => { handlers.beforeSendHeaders = { filter, fn }; },
    },
  };
}

test('hardenSession: permissions, request filter and token only for the app origin', () => {
  const ses = fakeSession();
  security.hardenSession(ses, () => ORIGIN, { injectToken: () => 'a'.repeat(64) });
  const h = ses.handlers;
  const ask = (permission) => new Promise((resolve) => h.permissionRequest(null, permission, resolve));
  return Promise.all([ask('clipboard-sanitized-write'), ask('media'), ask('geolocation'), ask('notifications'), ask('openExternal')])
    .then(([clip, ...rest]) => {
      assert.equal(clip, true);
      assert.deepEqual(rest, [false, false, false, false]);
      assert.equal(h.permissionCheck(null, 'clipboard-read'), false);
      const verdict = (url) => new Promise((resolve) => h.beforeRequest.fn({ url }, resolve));
      return Promise.all([verdict(`${ORIGIN}/api/ocr`), verdict('https://example.com/')]);
    })
    .then(([own, foreign]) => {
      assert.deepEqual(own, { cancel: false });
      assert.deepEqual(foreign, { cancel: true });
      const send = (url) => new Promise((resolve) => h.beforeSendHeaders.fn({ url, requestHeaders: { Accept: '*/*' } }, resolve));
      return Promise.all([send(`${ORIGIN}/api/health`), send('http://127.0.0.1:51235/api/health'), send(`${security.PDF_VIEWER}x`)]);
    })
    .then(([own, otherPort, viewer]) => {
      assert.equal(own.requestHeaders['X-VietDoc-Token'], 'a'.repeat(64));
      assert.equal(otherPort.requestHeaders['X-VietDoc-Token'], undefined);
      assert.equal(viewer.requestHeaders['X-VietDoc-Token'], undefined);
      assert.equal(own.requestHeaders.Accept, '*/*');
    });
});
