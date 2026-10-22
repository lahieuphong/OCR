'use strict';
// Navigation, request and permission rules for every window. Pure functions are exported for tests.

// The PDF preview (<iframe src="blob:...">) is drawn by Chromium's built-in PDF viewer extension.
const PDF_VIEWER = 'chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/';
// Static scripts and styles the PDF viewer loads from Electron's own resources.pak (no network; web pages
// themselves cannot load chrome:// URLs).
const CHROME_RESOURCES = 'chrome://resources/';
const ALLOWED_PERMISSIONS = new Set(['clipboard-sanitized-write']); // the "copy text" button

function sameOrigin(url, origin) {
  if (!origin) return false;
  try {
    return new URL(url).origin === origin;
  } catch {
    return false;
  }
}

// Top-level navigation: only pages of the local app origin (and the bundled status page).
function isAllowedNavigation(url, origin, statusUrl) {
  return sameOrigin(url, origin) || (Boolean(statusUrl) && url === statusUrl);
}

// Every request the app session may make: its own origin, its own blob/data URLs, the PDF viewer.
function isAllowedRequest(url, origin) {
  if (sameOrigin(url, origin)) return true;
  if (origin && url.startsWith(`blob:${origin}/`)) return true;
  if (url.startsWith('data:')) return true;
  if (url.startsWith(PDF_VIEWER) || url.startsWith(CHROME_RESOURCES)) return true;
  return url.startsWith('devtools://');
}

// Only file downloads the app itself produced (TXT/JSON export: blob URLs of the app origin).
function isAllowedDownload(url, origin) {
  return Boolean(origin) && url.startsWith(`blob:${origin}/`);
}

function hardenContents(contents, getRules) {
  const guard = (event, url) => {
    const { origin, statusUrl } = getRules();
    if (!isAllowedNavigation(url, origin, statusUrl)) event.preventDefault();
  };
  contents.on('will-navigate', guard);
  contents.on('will-redirect', guard);
  contents.on('will-attach-webview', (event) => event.preventDefault());
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
}

function hardenSession(ses, getOrigin, { injectToken, onBlocked } = {}) {
  ses.setPermissionRequestHandler((_wc, permission, callback) => callback(ALLOWED_PERMISSIONS.has(permission)));
  ses.setPermissionCheckHandler((_wc, permission) => ALLOWED_PERMISSIONS.has(permission));
  ses.webRequest.onBeforeRequest({ urls: ['<all_urls>'] }, (details, callback) => {
    const cancel = !isAllowedRequest(details.url, getOrigin());
    if (cancel && onBlocked) onBlocked(details.url);
    callback({ cancel });
  });
  if (injectToken) {
    // All URLs, filtered on the exact origin below (match patterns are vague about ports).
    ses.webRequest.onBeforeSendHeaders({ urls: ['<all_urls>'] }, (details, callback) => {
      const headers = { ...details.requestHeaders };
      if (sameOrigin(details.url, getOrigin())) headers['X-VietDoc-Token'] = injectToken();
      callback({ requestHeaders: headers });
    });
  }
}

module.exports = { isAllowedNavigation, isAllowedRequest, isAllowedDownload, sameOrigin, hardenContents, hardenSession, PDF_VIEWER, CHROME_RESOURCES };
