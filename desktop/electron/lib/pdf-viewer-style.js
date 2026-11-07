'use strict';
// The PDF preview's scrollbar belongs to a page inside Chromium's PDF viewer, out of reach of the app's stylesheet,
// so the app's scrollbar rules are added to that page as it loads. If a future Electron moves that page, the preview
// only falls back to Chromium's default scrollbar, and the smoke report warns about it.
const { PDF_VIEWER } = require('./security');

// The same text is in the frontend's style.css and in status.css (tests/pdf-viewer-style.test.js compares them).
const SCROLLBAR_RULES = [
  '::-webkit-scrollbar { width: 10px; height: 10px; }',
  '::-webkit-scrollbar-thumb { min-width: 32px; min-height: 32px; background: #cbd5e1 content-box; border: 3px solid transparent; border-radius: 999px; }',
  '::-webkit-scrollbar-thumb:hover { background-color: #94a3b8; border-width: 2px; }',
  '::-webkit-scrollbar-thumb:active { background-color: #2563eb; border-width: 2px; }',
];
const STYLE_ID = 'vietdoc-scrollbar';
// Elsewhere the track is transparent over a white panel; here that would show the viewer's dark background.
const VIEWER_CSS = [...SCROLLBAR_RULES, '::-webkit-scrollbar-track, ::-webkit-scrollbar-corner { background: #f8fafc; }'].join('\n');
const ADD_STYLE = `(() => {
  if (document.getElementById(${JSON.stringify(STYLE_ID)})) return;
  const style = document.createElement('style');
  style.id = ${JSON.stringify(STYLE_ID)};
  style.textContent = ${JSON.stringify(VIEWER_CSS)};
  (document.head || document.documentElement).append(style);
})()`;

// Whether this is the viewer's inner page, the one holding the scrollbar. Reading a frame that is gone throws.
function isViewerPage(frame) {
  try {
    return Boolean(frame && frame.parent && frame.parent.url.startsWith(PDF_VIEWER));
  } catch {
    return false;
  }
}

// Switching documents quickly removes frames at any moment: a lost frame needs nothing more.
function stylePdfViewerFrame(frame) {
  if (!isViewerPage(frame)) return;
  try {
    Promise.resolve(frame.executeJavaScript(ADD_STYLE)).catch(() => {});
  } catch {
    // Same: the frame went away.
  }
}

// Evidence for the smoke report: the scrollbar's width in the viewer's page, or null if the style is not there.
async function viewerScrollbarWidth(contents) {
  const frame = contents.mainFrame.framesInSubtree.find(isViewerPage);
  if (!frame) return null;
  return frame.executeJavaScript(`document.getElementById(${JSON.stringify(STYLE_ID)}) ? innerWidth - document.documentElement.clientWidth : null`);
}

module.exports = { SCROLLBAR_RULES, stylePdfViewerFrame, viewerScrollbarWidth };
