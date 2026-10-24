'use strict';
// The status window's page, served from the app (app.asar) over a private scheme instead of file://.
//
// The release build disables the GrantFileProtocolExtraPrivileges fuse, and with it a file:// page in the
// status window's own session does not load (ERR_FILE_NOT_FOUND: the window stayed blank, so a start-up
// error was never shown). Electron's recommended replacement is a custom protocol: only the three files of
// the status page are served, read from this folder, for GET requests of exactly vietdoc-status://app/<file>.
const fs = require('node:fs');
const path = require('node:path');

const STATUS_SCHEME = 'vietdoc-status';
const STATUS_ORIGIN = `${STATUS_SCHEME}://app`;
const STATUS_URL = `${STATUS_ORIGIN}/status.html`;
const STATUS_FILES = new Map([
  ['/status.html', 'text/html; charset=utf-8'],
  ['/status.css', 'text/css; charset=utf-8'],
  ['/status.js', 'text/javascript; charset=utf-8'],
]);

// { name, type } for an allowed URL, otherwise null (other host, path, query, credentials or scheme).
function statusFile(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== `${STATUS_SCHEME}:` || parsed.host !== 'app' || parsed.search || parsed.hash
    || parsed.username || parsed.password || !STATUS_FILES.has(parsed.pathname)) return null;
  return { name: parsed.pathname.slice(1), type: STATUS_FILES.get(parsed.pathname) };
}

// The protocol handler for session.protocol.handle(STATUS_SCHEME, ...): dir is the folder of status.html.
function statusHandler(dir) {
  return (request) => {
    const file = statusFile(request.url);
    if (!file || request.method !== 'GET') return new Response('Not found', { status: 404 });
    return new Response(fs.readFileSync(path.join(dir, file.name)), {
      headers: { 'content-type': file.type, 'x-content-type-options': 'nosniff', 'cache-control': 'no-store' },
    });
  };
}

// Before the app is ready: a standard, secure scheme so relative links and the page's CSP 'self' work.
const STATUS_SCHEME_PRIVILEGES = { scheme: STATUS_SCHEME, privileges: { standard: true, secure: true } };

module.exports = { STATUS_SCHEME, STATUS_ORIGIN, STATUS_URL, STATUS_SCHEME_PRIVILEGES, statusFile, statusHandler };
