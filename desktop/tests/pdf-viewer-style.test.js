'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { PDF_VIEWER } = require('../electron/lib/security');
const { SCROLLBAR_RULES, stylePdfViewerFrame, viewerScrollbarWidth } = require('../electron/lib/pdf-viewer-style');

const viewer = { url: `${PDF_VIEWER}index.html` };
const frame = (parent, run = async () => {}) => {
  const calls = [];
  return { parent, calls, executeJavaScript: (code) => { calls.push(code); return run(); } };
};

test('only the page inside the PDF viewer is styled', () => {
  const inner = frame(viewer);
  stylePdfViewerFrame(inner);
  assert.equal(inner.calls.length, 1);
  assert.match(inner.calls[0], /-webkit-scrollbar-thumb/);

  for (const other of [frame(null), frame({ url: 'http://127.0.0.1:5000/' }), frame({ url: 'chrome-extension://abcdefghijklmnopabcdefghijklmnop/' })]) {
    stylePdfViewerFrame(other);
    assert.equal(other.calls.length, 0);
  }
  stylePdfViewerFrame(undefined);
});

test('a frame that disappears while the user switches documents is not an error', async () => {
  stylePdfViewerFrame({ get parent() { throw new Error('Render frame was disposed'); } });
  stylePdfViewerFrame(frame(viewer, () => { throw new Error('gone'); }));
  stylePdfViewerFrame(frame(viewer, () => Promise.reject(new Error('gone'))));
  await new Promise(setImmediate);  // an unhandled rejection would fail the test
});

test('the smoke evidence reads the viewer page, and is empty without one', async () => {
  const inner = frame(viewer, async () => 10);
  assert.equal(await viewerScrollbarWidth({ mainFrame: { framesInSubtree: [frame(null), inner] } }), 10);
  assert.equal(await viewerScrollbarWidth({ mainFrame: { framesInSubtree: [frame(null)] } }), null);
});

test('the app, the status window and the PDF preview share one scrollbar', () => {
  const repo = path.join(__dirname, '..', '..');
  for (const file of ['demo/local_pdf_ocr/frontend/src/style.css', 'desktop/electron/status.css']) {
    const css = fs.readFileSync(path.join(repo, file), 'utf8');
    for (const rule of SCROLLBAR_RULES) assert.ok(css.includes(rule), `${file}: ${rule}`);
  }
});
