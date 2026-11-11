'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { windowChrome, nextZoom, shortcutFor, TITLE_BAR_OVERLAY, ZOOM_STEPS } = require('../electron/lib/app-window');

test('app window: only Windows draws its title bar into the page, in the top bar colours', () => {
  assert.deepEqual(windowChrome('win32'), { titleBarStyle: 'hidden', titleBarOverlay: TITLE_BAR_OVERLAY });
  assert.equal(TITLE_BAR_OVERLAY.color, '#ffffff');
  assert.equal(TITLE_BAR_OVERLAY.height, 60);
  assert.deepEqual(windowChrome('darwin'), {});
  assert.deepEqual(windowChrome('linux'), {});
});

test('app window: display sizes step through a fixed list and stop at both ends', () => {
  assert.equal(nextZoom(1, 1), 110);
  assert.equal(nextZoom(1.1, 1), 125);
  assert.equal(nextZoom(1, -1), 90);
  assert.equal(nextZoom(1.25, 0), 100);
  assert.equal(nextZoom(2, 1), 200);
  assert.equal(nextZoom(0.67, -1), 67);
  assert.equal(nextZoom(1.33, 1), 150);     // a size between two steps goes to the next one
  assert.equal(nextZoom(1.33, -1), 125);
  assert.ok(ZOOM_STEPS.includes(100));
});

test('app window: Ctrl (Command on macOS) +/-/0 zoom; the developer tools only in a development run', () => {
  const key = (k, extra = {}) => ({ type: 'keyDown', key: k, code: '', control: false, meta: false, alt: false, shift: false, ...extra });
  const win = { platform: 'win32', dev: false };
  assert.equal(shortcutFor(key('=', { control: true }), win), 'zoom-in');
  assert.equal(shortcutFor(key('+', { control: true, shift: true }), win), 'zoom-in');
  assert.equal(shortcutFor(key('-', { control: true }), win), 'zoom-out');
  assert.equal(shortcutFor(key('0', { control: true }), win), 'zoom-reset');
  assert.equal(shortcutFor(key('', { control: true, code: 'NumpadAdd' }), win), 'zoom-in');
  assert.equal(shortcutFor(key('=', {}), win), null);                       // typing "=" in a field
  assert.equal(shortcutFor(key('0', { control: true, alt: true }), win), null);
  assert.equal(shortcutFor({ ...key('=', { control: true }), type: 'keyUp' }, win), null);
  assert.equal(shortcutFor(key('r', { control: true }), win), null);        // no reload: it would drop the document list
  assert.equal(shortcutFor(key('F12'), win), null);
  assert.equal(shortcutFor(key('F12'), { platform: 'win32', dev: true }), 'devtools');
  assert.equal(shortcutFor(key('I', { control: true, shift: true }), { platform: 'win32', dev: true }), 'devtools');
  assert.equal(shortcutFor(key('=', { meta: true }), { platform: 'darwin', dev: false }), 'zoom-in');
  assert.equal(shortcutFor(key('=', { control: true }), { platform: 'darwin', dev: false }), null);
});
