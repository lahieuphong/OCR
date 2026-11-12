'use strict';
// The page the main window shows while the local backend starts, so the app opens as ONE window: the
// window appears at once with this page and then loads the real UI from the backend in the same window.
// Static HTML only (no script, no external resource), loaded as a data: URL in the hardened app session.
// Icons are the app's lucide icons as inline SVG (data-lucide names each one; docs/UI_ICONS.md).
// The separate status window is only for startup errors, a backend crash and the status menu.

const SPLASH_HTML = `<!doctype html>
<html lang="vi">
<head>
<meta charset="UTF-8"/>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"/>
<title>VietDoc OCR</title>
<style>
:root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI Variable", "Segoe UI", sans-serif; }
html, body { height: 100%; margin: 0; background: #fff; color: #334155; }
/* On Windows the window has no system title bar (lib/app-window.js): the whole page moves the window. */
body { -webkit-app-region: drag; user-select: none; }
body { display: grid; place-items: center; }
main { display: flex; flex-direction: column; align-items: center; gap: 22px; padding: 24px; text-align: center; }
.brand { display: flex; align-items: center; gap: 12px; text-align: left; }
.mark { display: grid; place-items: center; width: 48px; height: 48px; border-radius: 12px; background: #2563eb; color: #fff; }
h1 { margin: 0; color: #0f172a; font-size: 24px; font-weight: 650; letter-spacing: -.6px; line-height: 1.3; }
.brand p { margin: 3px 0 0; color: #64748b; font-size: 13px; }
.progress { display: flex; align-items: center; gap: 10px; color: #1d4ed8; font-size: 13px; }
/* The app's LoaderCircle, turning as in the app (frontend style.css .spin). */
.spin { flex: none; animation: spin 1.1s linear infinite; }
.note { margin: 0; color: #94a3b8; font-size: 11px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation-duration: 2.5s; } }
</style>
</head>
<body>
<main>
<div class="brand"><span class="mark" aria-hidden="true"><svg class="lucide" data-lucide="scan-text" width="27" height="27" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 8h8"/><path d="M7 12h10"/><path d="M7 16h6"/></svg></span><div><h1>VietDoc OCR</h1><p>Bóc tách văn bản hành chính</p></div></div>
<div class="progress" role="status"><svg class="lucide spin" data-lucide="loader-circle" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>Đang khởi động…</div>
<p class="note">Tài liệu được xử lý trên máy. Ứng dụng không tự tải model.</p>
</main>
</body>
</html>`;

const SPLASH_URL = `data:text/html;charset=utf-8,${encodeURIComponent(SPLASH_HTML)}`;

// The status window stays hidden while the main window shows the app; it only appears for an error.
function statusWindowNeeded(status) {
  return Boolean(status) && status.state === 'error';
}

module.exports = { SPLASH_HTML, SPLASH_URL, statusWindowNeeded };
