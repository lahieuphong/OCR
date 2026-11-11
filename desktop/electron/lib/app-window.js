'use strict';
// The app window's frame, zoom and keyboard shortcuts. Pure functions, exported for tests.
//
// The native menu bar is not themeable (on Windows it follows the system's dark mode), so Windows and Linux
// have none: the page's own top bar carries the app menu (preload-app.js). On Windows the top bar is also
// the title bar: the system draws only the minimise/maximise/close buttons over it, in the page's colours.
// macOS keeps its system menu bar (the Edit menu gives the standard Command shortcuts) and its own frame.

// Same height and colours as the page's top bar (.topbar in the frontend's style.css).
const TITLE_BAR_HEIGHT = 60;
const TITLE_BAR_OVERLAY = { color: '#ffffff', symbolColor: '#475569', height: TITLE_BAR_HEIGHT };

function windowChrome(platform) {
  return platform === 'win32' ? { titleBarStyle: 'hidden', titleBarOverlay: TITLE_BAR_OVERLAY } : {};
}

// Display sizes offered by the menu and Ctrl +/-/0 (percent of the normal size).
const ZOOM_STEPS = [67, 75, 80, 90, 100, 110, 125, 150, 175, 200];

function nextZoom(currentFactor, step) {
  if (step === 0) return 100;
  const current = Math.round(currentFactor * 100);
  if (step > 0) return ZOOM_STEPS.find((value) => value > current) ?? ZOOM_STEPS.at(-1);
  return [...ZOOM_STEPS].reverse().find((value) => value < current) ?? ZOOM_STEPS[0];
}

// Keyboard shortcuts the native menu used to provide: zoom, and the developer tools in a development run.
// Returns 'zoom-in' | 'zoom-out' | 'zoom-reset' | 'devtools' | null for a before-input-event input.
function shortcutFor(input, { platform, dev }) {
  if (input.type !== 'keyDown') return null;
  const command = platform === 'darwin' ? input.meta : input.control;
  if (command && !input.alt) {
    if (['=', '+', 'Add'].includes(input.key) || input.code === 'NumpadAdd') return 'zoom-in';
    if (['-', '_', 'Subtract'].includes(input.key) || input.code === 'NumpadSubtract') return 'zoom-out';
    if (input.key === '0' || input.code === 'Numpad0') return 'zoom-reset';
  }
  if (dev && (input.key === 'F12' || (command && input.shift && input.key.toLowerCase() === 'i'))) return 'devtools';
  return null;
}

module.exports = { TITLE_BAR_HEIGHT, TITLE_BAR_OVERLAY, ZOOM_STEPS, windowChrome, nextZoom, shortcutFor };
