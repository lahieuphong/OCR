'use strict';
// VietDoc OCR desktop shell (development MVP). Starts the local OCR server, shows its state, loads the
// existing React UI from it and stops it on exit. Recognition, limits and models are the backend's own.
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const { app, BrowserWindow, Menu, clipboard, ipcMain, protocol, session, shell } = require('electron');
const { resolveConfig } = require('./lib/config');
const { BackendProcess, describeExit } = require('./lib/backend');
const security = require('./lib/security');
const { smokeArgs, smokeAllowed } = require('./lib/smoke-gate');
const { configureAppIdentity } = require('./lib/app-identity');
const { matchesTextView } = require('./lib/smoke-text');
const { STATUS_SCHEME, STATUS_ORIGIN, STATUS_URL, STATUS_SCHEME_PRIVILEGES, statusHandler } = require('./lib/status-protocol');
const { SPLASH_URL, statusWindowNeeded } = require('./lib/splash');

// The status page is served over vietdoc-status://app/ (see lib/status-protocol.js), not file://.
const STATIC_PREFIX = `${STATUS_ORIGIN}/`;
protocol.registerSchemesAsPrivileged([STATUS_SCHEME_PRIVILEGES]);
const DEV = !app.isPackaged;
const ARGS = smokeArgs(process.argv);
// A release build refuses the smoke options (see lib/smoke-gate.js): it starts nothing and exits with code 2.
const SMOKE_REFUSED = Object.keys(ARGS).length > 0
  && !smokeAllowed({ packaged: app.isPackaged, packageJson: require('../package.json') });
const SMOKE_DIR = SMOKE_REFUSED ? null : ARGS['smoke-test'] || null;

let backend = null;
let statusWindow = null;
let mainWindow = null;
let appSession = null;
let quitting = false;
let lastStatus = { state: 'starting', message: 'Đang khởi động…' };
const smoke = { started_at: new Date().toISOString(), checks: {}, console: [] };

configureAppIdentity(app, require('../package.json'));
if (SMOKE_DIR) app.setPath('userData', path.join(SMOKE_DIR, 'userData'));
app.setAppLogsPath(path.join(app.getPath('userData'), 'logs'));

// Main-process errors go to a log file instead of a modal dialog or a silent hang.
function logMainError(kind, error) {
  const line = `${new Date().toISOString()} ${kind}: ${(error && error.stack) || error}\n`;
  try {
    fs.mkdirSync(app.getPath('logs'), { recursive: true });
    fs.appendFileSync(path.join(app.getPath('logs'), 'main.log'), line, 'utf8');
  } catch { /* nothing else to do */ }
  if (SMOKE_DIR) (smoke.main_errors ||= []).push(line.trim());
}
process.on('uncaughtException', (error) => logMainError('uncaughtException', error));
process.on('unhandledRejection', (error) => logMainError('unhandledRejection', error));
if (SMOKE_DIR) {
  // A smoke run must never hang: stop the backend, write what we have, exit non-zero.
  // --smoke-timeout=<seconds> (default 300) leaves room for real OCR of a multi-page DEV PDF.
  const limitSeconds = Math.max(60, Number(ARGS['smoke-timeout']) || 300);
  setTimeout(() => {
    smoke.error = `watchdog: smoke test did not finish in ${limitSeconds} s (last step: ${smoke.step})`;
    Promise.resolve(backend && backend.stop()).finally(() => { writeSmokeReport(); app.exit(3); });
  }, limitSeconds * 1000).unref();
}

function logDir() {
  return app.getPath('logs');
}

function sendStatus(update) {
  lastStatus = { ...lastStatus, ...update, at: new Date().toISOString() };
  if (statusWindow && !statusWindow.isDestroyed()) statusWindow.webContents.send('vietdoc:status', lastStatus);
}

function fromStatusPage(event) {
  return Boolean(event.senderFrame) && event.senderFrame.url === STATUS_URL;
}

app.on('web-contents-created', (_event, contents) => {
  security.hardenContents(contents, () => ({ origin: backend && backend.origin, statusUrl: STATUS_URL }));
});

// The status window is created on demand only (startup error, backend crash, status menu, smoke checks):
// the app itself opens as one window (createMainWindow). Resolves when its page has loaded.
function createStatusWindow({ show = true } = {}) {
  const statusSession = session.fromPartition('vietdoc-status');
  statusSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  statusSession.setPermissionCheckHandler(() => false);
  statusSession.webRequest.onBeforeRequest({ urls: ['<all_urls>'] }, (details, callback) => {
    callback({ cancel: !(details.url.startsWith(STATIC_PREFIX) || details.url.startsWith('devtools://')) });
  });
  if (!statusSession.protocol.isProtocolHandled(STATUS_SCHEME)) statusSession.protocol.handle(STATUS_SCHEME, statusHandler(__dirname));
  statusWindow = new BrowserWindow({
    width: 680, height: 680, minHeight: 420, show: false, title: 'VietDoc OCR · Trạng thái', autoHideMenuBar: true, backgroundColor: '#ffffff',
    webPreferences: {
      contextIsolation: true, nodeIntegration: false, sandbox: true, session: statusSession, spellcheck: false,
      preload: path.join(__dirname, 'preload-status.js'), devTools: DEV,
    },
  });
  statusWindow.on('close', (event) => {
    if (!quitting && mainWindow && mainWindow.isVisible()) {  // kept for the menu while the app runs
      event.preventDefault();
      statusWindow.hide();
    }
  });
  statusWindow.on('closed', () => {
    statusWindow = null;
    // After a startup error the main window is hidden: closing the status window ends the app.
    if (!quitting && !(mainWindow && mainWindow.isVisible())) app.quit();
  });
  if (show) statusWindow.once('ready-to-show', () => { if (statusWindow) statusWindow.show(); });
  statusWindow.webContents.on('console-message', (event) => {
    if (SMOKE_DIR) smoke.console.push({ level: event.level, message: event.message, source: event.sourceId, phase: smoke.step, window: 'status' });
  });
  const loaded = new Promise((r) => statusWindow.webContents.once('did-finish-load', r));
  statusWindow.loadURL(STATUS_URL);
  return loaded;
}

function showStatusWindow() {
  if (!statusWindow) return createStatusWindow({ show: true });
  statusWindow.show();
  statusWindow.focus();
  return Promise.resolve();
}

// The one window of the app: it appears at once with the startup page (lib/splash.js) while the backend
// starts, then loadApp() replaces that page with the real UI in the same window.
function createMainWindow() {
  if (!appSession) {
    appSession = session.fromPartition('vietdoc-app');  // in memory only: no cache or storage on disk
    security.hardenSession(appSession, () => backend && backend.origin, {
      injectToken: () => backend && backend.token,
      onBlocked: SMOKE_DIR ? (url) => { (smoke.blocked_requests ||= []).push(url.slice(0, 200)); } : undefined,
    });
    appSession.on('will-download', (_event, item) => {
      if (!security.isAllowedDownload(item.getURL(), backend && backend.origin)) {
        item.cancel();
        return;
      }
      if (SMOKE_DIR) {
        item.setSavePath(path.join(SMOKE_DIR, 'downloads', item.getFilename()));
      } else {
        item.setSaveDialogOptions({ title: 'Lưu kết quả', defaultPath: path.join(app.getPath('documents'), item.getFilename()) });
      }
    });
  }
  if (!mainWindow) {
    mainWindow = new BrowserWindow({
      width: 1360, height: 900, show: false, title: 'VietDoc OCR', backgroundColor: '#ffffff',
      // plugins: Chromium's built-in PDF viewer (PDFium) for the existing PDF preview; it is the only plugin left.
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, session: appSession, spellcheck: false, devTools: DEV, plugins: true },
    });
    // First paint is the startup page; a startup error may hide the window before that.
    mainWindow.once('ready-to-show', () => { if (mainWindow && !statusWindowNeeded(lastStatus)) mainWindow.show(); });
    mainWindow.webContents.on('console-message', (event) => {
      if (SMOKE_DIR) smoke.console.push({ level: event.level, message: event.message, source: event.sourceId, phase: smoke.step });
    });
    mainWindow.on('closed', () => {
      mainWindow = null;
      if (!quitting) app.quit();  // the hidden status window must not keep the app (and backend) alive
    });
    // ERR_ABORTED only means the real UI replaced the startup page before it finished loading.
    mainWindow.loadURL(SPLASH_URL).catch((error) => { if (error.code !== 'ERR_ABORTED') logMainError('startup page', error); });
  }
  return mainWindow;
}

// Loads the real UI from the backend into the main window (after startup or a successful retry).
async function loadApp() {
  createMainWindow();
  await mainWindow.loadURL(`${backend.origin}/`);
  if (!mainWindow.isVisible()) mainWindow.show();
}

async function startBackend() {
  sendStatus({ state: 'starting', step: 'config', message: 'Đang kiểm tra cấu hình…', error: null, desktop: null, log: null });
  let config;
  try {
    config = resolveConfig({ packaged: app.isPackaged, resourcesPath: process.resourcesPath, userConfigDir: app.getPath('userData') });
  } catch (error) {
    sendStatus({ state: 'error', step: 'config', message: error.message });
    return false;
  }
  backend = new BackendProcess(config, { logDir: logDir() });
  backend.on('status', (s) => sendStatus({ state: 'starting', ...s }));
  backend.on('exit', onBackendExit);
  try {
    await backend.start();
    const health = await backend.request('/api/health', { timeoutMs: 10_000 });
    const desktop = await backend.request('/__desktop__/status', { timeoutMs: 10_000 });
    const ocr = desktop.data.ocr_allowed;
    sendStatus({
      state: ocr ? 'ready' : 'limited', step: 'ready', health: health.data, desktop: desktop.data, log: backend.logFile,
      message: ocr ? 'Sẵn sàng bóc tách văn bản từ PDF và ảnh.'
        : 'OCR chưa sẵn sàng. Bạn vẫn có thể trích xuất văn bản có sẵn trong PDF.',
    });
    return true;
  } catch (error) {
    sendStatus({ state: 'error', step: 'backend', message: `Không khởi động được backend: ${error.message}`, log: backend.logFile });
    await backend.stop();
    return false;
  }
}

function onBackendExit(info) {
  if (quitting || info.expected) return;
  sendStatus({ state: 'error', step: 'crashed', desktop: null,
    message: `Máy chủ xử lý đã dừng (${describeExit(info.code)}). Bấm "Thử lại" hoặc mở log để kiểm tra.` });
  showStatusWindow();
}

async function restart() {
  if (backend) await backend.stop();
  const afterStartupError = !(mainWindow && mainWindow.isVisible());
  if (await startBackend()) {
    await loadApp();
    // Retried from a startup error: the app window takes over, as after a normal start.
    if (afterStartupError && statusWindow) statusWindow.hide();
    return true;
  }
  return false;
}

function buildMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: 'VietDoc', submenu: [
      { label: 'Trạng thái backend và model', click: showStatusWindow },
      { label: 'Mở thư mục log', click: () => shell.openPath(logDir()) },
      { type: 'separator' },
      { label: 'Thoát', role: 'quit' },
    ] },
    // Native Edit roles register the standard Command shortcuts on macOS.
    ...(process.platform === 'darwin' ? [{ id: 'vietdoc-edit', role: 'editMenu' }] : []),
    { label: 'Xem', submenu: [
      { label: 'Tải lại', role: 'reload' }, { label: 'Phóng to', role: 'zoomIn' }, { label: 'Thu nhỏ', role: 'zoomOut' },
      { label: 'Cỡ mặc định', role: 'resetZoom' }, ...(DEV ? [{ type: 'separator' }, { role: 'toggleDevTools' }] : []),
    ] },
  ]));
}

ipcMain.handle('vietdoc:get-status', (event) => (fromStatusPage(event) ? lastStatus : null));
ipcMain.on('vietdoc:retry', (event) => { if (fromStatusPage(event)) restart(); });
ipcMain.on('vietdoc:open-logs', (event) => { if (fromStatusPage(event)) shell.openPath(logDir()); });
ipcMain.on('vietdoc:quit', (event) => { if (fromStatusPage(event)) app.quit(); });

app.on('before-quit', (event) => {
  if (quitting) return;
  quitting = true;
  if (backend && backend.running) {
    event.preventDefault();
    const { port, serverPid } = backend;
    const pid = backend.child.pid;
    backend.stop().then(async (result) => {
      await sleep(300);
      smoke.checks.shutdown = { ...result, launcher_pid: pid, launcher_alive_after: isAlive(pid), server_pid: serverPid,
        server_alive_after: serverPid ? isAlive(serverPid) : null, port_closed_after: await portClosed(port) };
      writeSmokeReport();
      app.quit();
    });
  } else {
    writeSmokeReport();
  }
});
app.on('window-all-closed', () => app.quit());

function isAlive(pid) {
  try {
    process.kill(pid, 0);  // signal 0: existence probe only
    return true;
  } catch {
    return false;
  }
}

function portClosed(port) {
  if (!port) return Promise.resolve(true);
  return new Promise((resolve) => {
    const socket = net.connect({ host: '127.0.0.1', port }, () => { socket.destroy(); resolve(false); });
    socket.on('error', () => resolve(true));
  });
}

// --------------------------------------------------------------- smoke test (development only)
// `electron . --smoke-test=<dir> [--smoke-pdf=<dev pdf>]` drives the real UI, writes smoke_report.json,
// screenshots and the exported files into <dir>, then quits. Never point it at blind documents.

function writeSmokeReport() {
  if (!SMOKE_DIR) return;
  smoke.finished_at = new Date().toISOString();
  smoke.final_status = lastStatus;
  fs.mkdirSync(SMOKE_DIR, { recursive: true });
  fs.writeFileSync(path.join(SMOKE_DIR, 'smoke_report.json'), JSON.stringify(smoke, null, 1), 'utf8');
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const value = await fn().catch(() => null);
    if (value) return value;
    await sleep(250);
  }
  return null;
}

// Screenshots are evidence only: a capture failure (e.g. Chromium's UnknownVizError right after the
// window reloads behind the status window, or a window that is hidden or gone) is retried, then recorded
// in capture_errors (a warning for check-smoke-report.js) instead of failing the run. Only the capture
// itself is caught here: every check of the backend, OCR, security, export and shutdown stays strict.
// capturePage() never resolves for a hidden window, so the window is shown without focus first.
async function screenshot(name, win = mainWindow) {
  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      if (!win || win.isDestroyed()) {
        lastError = 'window not available';
        break;
      }
      if (!win.isVisible()) win.showInactive();
      const image = await Promise.race([win.capturePage(), sleep(5000).then(() => null)]);
      if (image && !image.isEmpty()) {
        fs.writeFileSync(path.join(SMOKE_DIR, name), image.toPNG());
        return true;
      }
      lastError = 'empty or timed out';
    } catch (error) {
      lastError = String((error && error.message) || error);
    }
    await sleep(1000);
  }
  (smoke.capture_errors ||= []).push({ name, error: lastError });
  return false;
}

async function setInputFile(wc, file, selector = 'input[type=file]') {
  wc.debugger.attach('1.3');
  try {
    const { root } = await wc.debugger.sendCommand('DOM.getDocument', { depth: 1 });
    const { nodeId } = await wc.debugger.sendCommand('DOM.querySelector', { nodeId: root.nodeId, selector });
    await wc.debugger.sendCommand('DOM.setFileInputFiles', { nodeId, files: Array.isArray(file) ? file : [file] });
  } finally {
    wc.debugger.detach();
  }
}

function sha256(file) {
  return require('node:crypto').createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

async function uiState(js) {
  return js(`(() => { const pill = document.querySelector('.server-pill');
    return pill && !pill.className.includes('checking') && document.querySelector('#root').children.length > 0
      ? { title: document.title, pill: pill.textContent.trim(), pill_class: pill.className, url: location.href } : null; })()`);
}

async function runSmoke() {
  const assert = require('node:assert/strict');
  const wc = mainWindow.webContents;
  const js = (code) => wc.executeJavaScript(code, true);
  const c = smoke.checks;
  if (process.platform === 'darwin') {
    const edit = Menu.getApplicationMenu().getMenuItemById('vietdoc-edit');
    const roles = (edit && edit.submenu ? edit.submenu.items : []).map(item => String(item.role).toLowerCase());
    c.macos_edit_menu = roles;
    for (const role of ['undo', 'redo', 'cut', 'copy', 'paste', 'selectall']) {
      assert.ok(roles.includes(role), `macOS native Edit menu is missing ${role}`);
    }
  }
  async function clickResultTab(label) {
    const point = await js(`(() => { const tab = Array.from(document.querySelectorAll('[role=tab]')).find(t => t.textContent === ${JSON.stringify(label)});
      if (!tab) return null; tab.scrollIntoView({block: 'nearest'}); const r = tab.getBoundingClientRect(); return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)}; })()`);
    assert.ok(point, 'missing result tab: ' + label);
    // Radix tabs select on pointer-down/keyboard, so drive a real mouse gesture.
    wc.sendInputEvent({ type: 'mouseDown', ...point, button: 'left', clickCount: 1 });
    wc.sendInputEvent({ type: 'mouseUp', ...point, button: 'left', clickCount: 1 });
    assert.ok(await waitFor(() => js(`document.querySelector('[role=tab][data-state=active]')?.textContent === ${JSON.stringify(label)}`), 5000));
  }
  const downloads = path.join(SMOKE_DIR, 'downloads');
  fs.mkdirSync(downloads, { recursive: true });

  c.ui = await waitFor(() => uiState(js), 20_000);
  smoke.step = 'ui-review';
  await screenshot('01_ui_start.png');
  // UI acceptance checks supplement the existing OCR/security smoke; no original assertion is removed.
  const layout = () => js(`(() => {
    const left = document.querySelector('.left-pane').getBoundingClientRect();
    const right = document.querySelector('.right-pane').getBoundingClientRect();
    const run = document.querySelector('.run-button').getBoundingClientRect();
    return { width: innerWidth, height: innerHeight, scroll_width: document.documentElement.scrollWidth,
      left_width: left.width, right_width: right.width, stacked: right.top >= left.bottom,
      run_bottom: run.bottom, background: getComputedStyle(document.querySelector('.right-pane')).backgroundColor,
      font: getComputedStyle(document.body).fontFamily };
  })()`);
  c.ui_layout = { default: await layout() };
  assert.equal(c.ui_layout.default.background, 'rgb(255, 255, 255)', 'result card must be white');
  assert.ok(c.ui_layout.default.scroll_width <= c.ui_layout.default.width, 'default layout overflows horizontally');
  assert.ok(c.ui_layout.default.run_bottom <= c.ui_layout.default.height, 'run button must be visible at the default size');
  assert.ok(c.ui_layout.default.left_width / c.ui_layout.default.right_width > 0.78
    && c.ui_layout.default.left_width / c.ui_layout.default.right_width < 0.86, 'workspace must be about 45/55');
  assert.equal(await js(`document.querySelector('.run-button').disabled`), true, 'no file must disable processing');
  const originalBounds = mainWindow.getBounds();
  for (const [name, width, height] of [['compact', 960, 720], ['narrow', 760, 860]]) {
    mainWindow.setSize(width, height);
    await sleep(350);
    c.ui_layout[name] = await layout();
    assert.ok(c.ui_layout[name].scroll_width <= c.ui_layout[name].width, name + ' layout overflows horizontally');
    assert.ok(c.ui_layout[name].run_bottom <= c.ui_layout[name].height, name + ' run button must stay visible');
    if (name === 'narrow') assert.equal(c.ui_layout[name].stacked, true, 'narrow workspace must stack');
    await screenshot('01_ui_' + name + '.png');
  }
  mainWindow.setBounds(originalBounds);
  await sleep(350);
  c.renderer_has_node = await js(`typeof require !== 'undefined' || typeof process !== 'undefined'`);
  smoke.step = 'security-probes';
  c.external_fetch_blocked = await js(`fetch('https://example.com/').then(() => false, () => true)`);
  const before = wc.getURL();
  await js(`window.open('https://example.com/'); location.href = 'https://example.com/'; true`).catch(() => true);
  await sleep(1500);
  c.external_navigation_blocked = wc.getURL() === before && BrowserWindow.getAllWindows().length <= 2;
  c.request_without_token_status = await fetch(`${backend.origin}/api/health`).then((r) => r.status);
  c.request_localhost_host_status = await fetch(`http://localhost:${backend.port}/api/health`,
    { headers: { 'X-VietDoc-Token': backend.token } }).then((r) => r.status, (e) => `error: ${e.cause?.code || e.message}`);

  const pdf = ARGS['smoke-pdf'];
  smoke.step = 'document-flow';
  if (pdf) {
    // Real UI path: choose the file, run "Text có sẵn trong PDF", export TXT and JSON with the UI buttons.
    await setInputFile(wc, pdf);
    c.ui_file_selected = await waitFor(() => js(`document.querySelector('.selected-file strong')?.textContent || null`), 10_000);
    assert.equal(await js(`document.querySelector('input[name=mode]:checked').value`), 'native_text', 'PDF must visibly default to native_text');
    c.ui_hybrid_choice = await js(`(() => { const h = document.querySelector('input[name=mode][value=hybrid_h1]');
      return { present: Boolean(h), selected: Boolean(h?.checked) }; })()`);
    assert.deepEqual(c.ui_hybrid_choice, { present: true, selected: false }, 'experimental H1 must be available for PDF and off by default');
    await js(`document.querySelector('input[name=mode][value=hybrid_h1]').closest('label').scrollIntoView({block: 'center'}); true`);
    await screenshot('02a_ui_hybrid_option.png');
    await js(`document.querySelector('input[name=mode][value=native_text]').click(); true`);
    await sleep(1000);
    // PDF preview: scroll the iframe into view and measure how much of it is light (a rendered page) versus
    // the dark empty frame. Chromium's PDF viewer is out of reach of executeJavaScript, so pixels decide.
    const rect = await js(`(() => { const f = document.querySelector('iframe.pdf-view'); if (!f) return null; f.scrollIntoView({block: 'center'});
      const r = f.getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height), scheme: f.src.split(':')[0] }; })()`);
    c.ui_preview = { iframe: rect && rect.scheme };
    if (rect) {
      const preview = await waitFor(async () => {
        const image = await mainWindow.capturePage({ x: rect.x, y: rect.y, width: rect.width, height: rect.height });
        const { width, height } = image.getSize();
        const bitmap = image.toBitmap();
        let light = 0;
        for (let i = 0; i < bitmap.length; i += 4) if (bitmap[i] > 200 && bitmap[i + 1] > 200 && bitmap[i + 2] > 200) light += 1;
        const share = light / (width * height);
        return share > 0.2 ? { light_pixel_share: Number(share.toFixed(3)), size: [width, height] } : null;
      }, 15_000);
      c.ui_preview.rendered = Boolean(preview);
      Object.assign(c.ui_preview, preview || {});
    }
    await screenshot('02_ui_pdf_preview.png');
    await js(`window.scrollTo(0, 0); true`);
    const t0 = Date.now();
    // Pause the real request briefly to inspect the busy state without fabricating progress or OCR output.
    wc.debugger.attach('1.3');
    try {
      await wc.debugger.sendCommand('Fetch.enable', { patterns: [{ urlPattern: '*/api/ocr', requestStage: 'Request' }] });
      const paused = new Promise((resolve) => {
        const onMessage = (_event, method, params) => {
          if (method === 'Fetch.requestPaused') { wc.debugger.off('message', onMessage); resolve(params); }
        };
        wc.debugger.on('message', onMessage);
      });
      await js(`document.querySelector('.run-button').click(); true`);
      const request = await Promise.race([paused, sleep(5000).then(() => null)]);
      assert.ok(request, 'processing request was not sent');
      c.ui_working = await js(`({ run_disabled: document.querySelector('.run-button').disabled,
        file_disabled: document.querySelector('input[type=file]').disabled,
        modes_disabled: document.querySelector('.ocr-mode-selector').disabled,
        busy: document.querySelector('.right-pane').getAttribute('aria-busy'),
        indeterminate: document.querySelector('[role=progressbar]')?.getAttribute('data-state'),
        progress_value: document.querySelector('[role=progressbar]')?.getAttribute('aria-valuenow') })`);
      assert.deepEqual(c.ui_working, { run_disabled: true, file_disabled: true, modes_disabled: true,
        busy: 'true', indeterminate: 'indeterminate', progress_value: null });
      await screenshot('02b_ui_processing.png');
      await wc.debugger.sendCommand('Fetch.continueRequest', { requestId: request.requestId });
    } finally {
      wc.debugger.detach();
    }
    c.ui_native_text = await waitFor(() => js(`(() => { const s = document.querySelector('.results-stats'), e = document.querySelector('.error-box');
      return s ? { ok: true, stats: s.textContent.replace(/\\s+/g, ' ').trim() } : e ? { ok: false, error: e.textContent.trim() } : null; })()`), 120_000);
    if (c.ui_native_text) c.ui_native_text.elapsed_ms = Date.now() - t0;
    assert.equal(await js(`document.querySelector('[role=tab][data-state=active]')?.textContent`), 'Thông tin văn bản', 'successful extraction must open metadata');
    c.metadata = await js(`({ fields: document.querySelectorAll('.metadata-field input, .metadata-field select, .metadata-field textarea').length,
      doc_id: document.querySelector('#metadata-docId').value,
      page_count: document.querySelector('#metadata-numberOfPage').value,
      stamp: document.querySelector('#metadata-isCan').value,
      confidence: document.querySelector('#metadata-confidenceLevel').value })`);
    assert.equal(c.metadata.fields, 22);
    assert.equal(c.metadata.doc_id, '');
    assert.equal(c.metadata.stamp, '');
    assert.equal(c.metadata.confidence, '02');
    await screenshot('03a_ui_metadata.png');
    const metadataBounds = mainWindow.getBounds();
    mainWindow.setSize(960, 720);
    await sleep(350);
    c.metadata.compact_no_overflow = await js(`document.documentElement.scrollWidth <= innerWidth
      && document.querySelector('.document-metadata').scrollWidth <= document.querySelector('.document-metadata').clientWidth`);
    assert.equal(c.metadata.compact_no_overflow, true, 'metadata form must not overflow a compact window');
    await screenshot('03d_ui_metadata_compact.png');
    mainWindow.setBounds(metadataBounds);
    await sleep(350);
    const metadataFile = path.join(downloads, path.basename(pdf).replace(/\.[^.]+$/, '').replace(/[\\/:*?"<>|]/g, '_') + '_native_text_metadata.json');
    await js(`document.querySelector('button[title="Xuất JSON 22 trường"]').click(); true`);
    assert.ok(await waitFor(() => js(`document.querySelector('dialog[open]')?.textContent.includes('Công khai')`), 5000), 'unclassified access mode must warn before export');
    await js(`document.querySelector('dialog .confirm-actions button:last-child').click(); true`);
    assert.ok(await waitFor(async () => fs.existsSync(metadataFile), 5000), 'metadata export was not saved');
    const metadata = JSON.parse(fs.readFileSync(metadataFile, 'utf8'));
    const metadataKeys = ['docId','arcDocCode','maintenance','typeName','codeNumber','codeNotation','issuedDate','organName','subject','language','numberOfPage','inforSign','keyword','mode','confidenceLevel','autograph','format','process','riskRecovery','riskRecoveryStatus','description','isCan'];
    assert.deepEqual(Object.keys(metadata), metadataKeys);
    assert.ok(Object.values(metadata).every(value => typeof value === 'string'));
    assert.equal(metadata.docId, ''); assert.equal(metadata.mode, '');
    assert.equal(metadata.numberOfPage, c.metadata.page_count);
    c.metadata.export_exact_schema = true;
    const manualSubject = 'Metadata tổng hợp – đã chỉnh sửa thủ công.';
    await js(`(() => { const field = document.querySelector('#metadata-subject');
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(field, ${JSON.stringify(manualSubject)});
      field.dispatchEvent(new Event('input', {bubbles:true})); })()`);
    await clickResultTab('Toàn văn');
    await clickResultTab('Thông tin văn bản');
    assert.equal(await js(`document.querySelector('#metadata-subject').value`), manualSubject, 'tabs must preserve manual edits');
    const clipboardBeforeMetadata = await clipboard.readText();
    try {
      mainWindow.focus(); wc.focus();
      await js(`Array.from(document.querySelectorAll('.metadata-actions button')).find(b => b.textContent.includes('Sao chép JSON')).click(); true`);
      assert.ok(await waitFor(() => js(`Boolean(document.querySelector('dialog[open]'))`), 5000));
      await js(`document.querySelector('dialog .confirm-actions button:last-child').click(); true`);
      c.metadata.copy_exact = Boolean(await waitFor(async () => {
        try { const copied = JSON.parse(await clipboard.readText()); return Object.keys(copied).length === 22 && copied.subject === manualSubject && copied.mode === ''; }
        catch { return false; }
      }, 5000));
      assert.equal(c.metadata.copy_exact, true, 'metadata clipboard JSON must preserve edits and schema');
    } finally { await clipboard.writeText(clipboardBeforeMetadata); }
    await js(`Array.from(document.querySelectorAll('.metadata-actions button')).find(b => b.textContent.includes('Khôi phục')).click(); true`);
    assert.ok(await waitFor(() => js(`Boolean(document.querySelector('dialog[open]'))`), 5000), 'reset must confirm loss of manual edits');
    await js(`document.querySelector('dialog .confirm-actions button:first-child').click(); true`);
    assert.equal(await js(`document.querySelector('#metadata-subject').value`), manualSubject, 'cancel reset must preserve the draft');
    await js(`Array.from(document.querySelectorAll('.metadata-actions button')).find(b => b.textContent.includes('Khôi phục')).click(); true`);
    await js(`document.querySelector('dialog .confirm-actions button:last-child').click(); true`);
    assert.equal(await js(`document.querySelector('#metadata-subject').value`), metadata.subject, 'accepted reset must restore automatic values');
    c.metadata.manual_edits_and_reset = true;
    await clickResultTab('Toàn văn');
    await screenshot('03_ui_native_text_result.png');
    await js(`document.querySelector('button[title="Tải TXT"]').click(); true`);
    await sleep(800);
    await js(`document.querySelector('button[title="Tải báo cáo JSON"]').click(); true`);
    const base = path.basename(pdf).replace(/\.[^.]+$/, '').replace(/[\\/:*?"<>|]/g, '_') + '_native_text';
    const txt = path.join(downloads, `${base}.txt`);
    const json = path.join(downloads, `${base}.json`);
    const done = await waitFor(async () => fs.existsSync(txt) && fs.existsSync(json), 15_000);
    c.export = { txt_file: path.basename(txt), json_file: path.basename(json), both_saved: Boolean(done) };
    if (done) {
      await sleep(500);
      const report = JSON.parse(fs.readFileSync(json, 'utf8'));
      const text = fs.readFileSync(txt, 'utf8');
      Object.assign(c.export, { txt_bytes: fs.statSync(txt).size, json_bytes: fs.statSync(json).size, txt_sha256: sha256(txt),
        json_method: report.method, json_pages: report.pages?.length, txt_equals_json_text: text === report.text });
      const lf = (value) => value.replace(/\r\n/g, '\n');
      c.ui_native_views = { full_text_exact: matchesTextView(await js(`document.querySelector('.text-output pre')?.textContent ?? null`), report.text) };
      assert.equal(c.ui_native_views.full_text_exact, true, 'full text must match the unmodified API/export text');
      assert.equal(await js(`Array.from(document.querySelectorAll('[role=tab]')).some(t => t.textContent === 'So sánh')`), false,
        'comparison must only appear after both independent results exist');
      mainWindow.focus();
      wc.focus();
      const clipboardBefore = await clipboard.readText();
      try {
        await js(`document.querySelector('button[title="Sao chép văn bản"]').click(); true`);
        c.native_copy = { full_text_exact: Boolean(await waitFor(async () => lf(await clipboard.readText()) === report.text, 5000)) };
        assert.equal(c.native_copy.full_text_exact, true, 'copy must preserve full text and Unicode');
        for (const item of report.pages) {
          await clickResultTab('Theo trang');
          await sleep(150);
          await js(`Array.from(document.querySelectorAll('.page-tabs button')).find(b => b.textContent === ${JSON.stringify('Trang ' + item.page)}).click(); true`);
          await sleep(150);
          const exact = matchesTextView(await js(`document.querySelector('.text-output pre')?.textContent ?? null`), item.text);
          (c.ui_native_views.pages ||= []).push({ page: item.page, exact });
          assert.equal(exact, true, 'page view must preserve page text');
        }
        if (report.pages.length) {
          const lastPage = report.pages.at(-1);
          await js(`document.querySelector('button[title="Sao chép văn bản"]').click(); true`);
          c.native_copy.page_text_exact = Boolean(await waitFor(async () => lf(await clipboard.readText()) === lastPage.text, 5000));
          assert.equal(c.native_copy.page_text_exact, true, 'copy must use the selected page');
          await screenshot('03c_ui_page_result.png');
        }
        await clickResultTab('Toàn văn');
      } finally {
        await clipboard.writeText(clipboardBefore);
      }
    }
    await js(`document.querySelector('input[name=mode][value=vietocr_ocr]').click(); true`);
    await sleep(300);
    c.ocr_allowed = Boolean(lastStatus.desktop && lastStatus.desktop.ocr_allowed);
    c.ui_ocr_run_button_disabled = await js(`document.querySelector('.run-button').disabled`);
    if (c.ocr_allowed) {
      // Real OCR through the UI, then the UI's own JSON/TXT export (compared with the A0 baseline offline).
      const t2 = Date.now();
      await js(`document.querySelector('.run-button').click(); true`);
      c.ui_vietocr_ocr = await waitFor(() => js(`(() => { const o = document.querySelector('.result-origin.ocr-origin'), e = document.querySelector('.error-box');
        return o ? { ok: true, stats: document.querySelector('.results-stats')?.textContent.replace(/\\s+/g, ' ').trim() }
          : e ? { ok: false, error: e.textContent.trim() } : null; })()`), 30 * 60_000);
      if (c.ui_vietocr_ocr) c.ui_vietocr_ocr.elapsed_ms = Date.now() - t2;
      await screenshot('03b_ui_ocr_result.png');
      await js(`document.querySelector('button[title="Tải TXT"]').click(); true`);
      await sleep(800);
      await js(`document.querySelector('button[title="Tải báo cáo JSON"]').click(); true`);
      const ocrBase = path.basename(pdf).replace(/\.[^.]+$/, '').replace(/[\\/:*?"<>|]/g, '_') + '_vietocr_ocr';
      const ocrTxt = path.join(downloads, `${ocrBase}.txt`);
      const ocrJson = path.join(downloads, `${ocrBase}.json`);
      const saved = await waitFor(async () => fs.existsSync(ocrTxt) && fs.existsSync(ocrJson), 15_000);
      c.ocr_export = { txt_file: path.basename(ocrTxt), json_file: path.basename(ocrJson), both_saved: Boolean(saved) };
      if (saved) {
        await sleep(500);
        const report = JSON.parse(fs.readFileSync(ocrJson, 'utf8'));
        Object.assign(c.ocr_export, { json_sha256: sha256(ocrJson), json_method: report.method, pages: report.page_count,
          lines: report.line_count, decoder_limit_hits: report.decoder_limit_hits, model: report.model,
          txt_equals_json_text: fs.readFileSync(ocrTxt, 'utf8') === report.text });
        // The UI's "copy text" button (navigator.clipboard, the session's only permission) copies the shown text:
        // the current page or the whole document. The Windows clipboard returns that text with CRLF line ends,
        // so it is compared with LF ends. The clipboard is overwritten by this test run.
        const lf = (text) => text.replace(/\r\n/g, '\n');
        const expected = [report.text, ...(report.pages || []).map((p) => p.text)];
        await clipboard.writeText(`vietdoc-smoke-${Date.now()}`);
        mainWindow.focus();
        wc.focus();
        await js(`document.querySelector('button[title="Sao chép văn bản"]').click(); true`);
        let last = '';
        const copied = await waitFor(async () => { last = lf(await clipboard.readText()); return expected.includes(last) ? last : null; }, 5_000);
        c.ocr_copy = { copied: Boolean(copied), chars: last.length, equals_full_text: last === report.text,
          equals_page_text: (report.pages || []).some((p) => p.text === last),
          ui_error: await js(`document.querySelector('.error-box')?.textContent.trim() || null`) };
      }
    } else {
      // Models missing: the UI disables the button; the same request straight to the API must be refused.
      const form = new FormData();
      form.append('mode', 'vietocr_ocr');
      form.append('file', new Blob([fs.readFileSync(pdf)], { type: 'application/pdf' }), path.basename(pdf));
      const t1 = Date.now();
      const r = await backend.request('/api/ocr', { method: 'POST', body: form });
      c.api_vietocr_ocr = { status: r.status, elapsed_ms: Date.now() - t1, detail: r.data && r.data.detail,
        method: r.data && r.data.method, lines: r.data && r.data.line_count };
    }
  }
  // PNG/JPG upload and preview with synthetic images (the app's own screenshot), then the 15 MB limit.
  const inputs = path.join(SMOKE_DIR, 'synthetic_inputs');
  fs.mkdirSync(inputs, { recursive: true });
  const shot = await mainWindow.capturePage({ x: 0, y: 0, width: 800, height: 500 });
  fs.writeFileSync(path.join(inputs, 'synthetic_ui.png'), shot.toPNG());
  fs.writeFileSync(path.join(inputs, 'synthetic_ui.jpg'), shot.toJPEG(85));
  c.images = {};
  for (const name of ['synthetic_ui.png', 'synthetic_ui.jpg']) {
    await setInputFile(wc, path.join(inputs, name));
    c.images[name] = await waitFor(() => js(`(() => { const img = document.querySelector('.image-view img');
      const name = document.querySelector('.selected-file strong')?.textContent;
      return img && img.complete && img.naturalWidth > 0 && name === ${JSON.stringify(name)}
        ? { preview_px: [img.naturalWidth, img.naturalHeight], mode: document.querySelector('input[name=mode]:checked')?.value,
            native_text_disabled: document.querySelector('input[name=mode][value=native_text]').disabled,
            run_disabled: document.querySelector('.run-button').disabled } : null; })()`), 10_000);
  }
  const big = path.join(inputs, 'oversize_16MB.pdf');
  fs.writeFileSync(big, Buffer.alloc(16 * 1024 * 1024, 0x20));
  await setInputFile(wc, big);
  c.ui_oversize = await waitFor(() => js(`document.querySelector('.error-box')?.textContent.trim() || null`), 5_000);
  fs.rmSync(big);  // our own 16 MB dummy; the PNG/JPG stay as evidence
  const form16 = new FormData();
  form16.append('mode', 'native_text');
  form16.append('file', new Blob([Buffer.alloc(16 * 1024 * 1024, 0x20)], { type: 'application/pdf' }), 'oversize.pdf');
  const r16 = await backend.request('/api/ocr', { method: 'POST', body: form16 });
  c.api_oversize = { status: r16.status, detail: r16.data && r16.data.detail };
  if (pdf) {
    smoke.step = 'batch-excel';
    // Clear only this smoke session's synthetic inputs using the real UI.
    while (await js(`document.querySelectorAll('.remove-document').length`)) {
      const beforeCount = await js(`document.querySelectorAll('.remove-document').length`);
      await js(`document.querySelector('.remove-document').click(); true`);
      assert.ok(await waitFor(() => js(`document.querySelectorAll('.remove-document').length < ${beforeCount} || Boolean(document.querySelector('dialog[open]'))`), 5000));
      if (await js(`Boolean(document.querySelector('dialog[open]'))`)) await js(`document.querySelector('dialog .confirm-actions button:last-child').click(); true`);
      assert.ok(await waitFor(() => js(`document.querySelectorAll('.remove-document').length < ${beforeCount}`), 5000));
    }
    const fixtureNames = ['officialLetter', 'decision', 'resolution'];
    const batchFiles = fixtureNames.map((name, index) => {
      const file = path.join(inputs, `batch_${index + 1}.pdf`);
      fs.copyFileSync(ARGS['smoke-batch-dir'] ? path.join(ARGS['smoke-batch-dir'], name + '.pdf') : pdf, file);
      return file;
    });
    await setInputFile(wc, batchFiles);
    assert.ok(await waitFor(() => js(`document.querySelectorAll('.input-queue li').length === 3`), 5000));
    assert.deepEqual(await js(`Array.from(document.querySelectorAll('.input-queue li select'), s => s.value)`), ['native_text','native_text','native_text']);
    await js(`(() => {
      const original = window.fetch;
      window.__vietdocBatchQA = {original, active:0, peak:0, requests:[]};
      window.fetch = async function(url, options) {
        if (url !== '/api/ocr') return original.call(this,url,options);
        const qa=window.__vietdocBatchQA;
        qa.peak=Math.max(qa.peak,++qa.active);
        const entry={name:options.body.get('file').name,mode:options.body.get('mode')}; qa.requests.push(entry);
        try {const response=await original.call(this,url,options); entry.status=response.status; entry.text=(await response.clone().json()).text; return response;}
        finally {qa.active--;}
      };
    })()`);
    try {
      assert.equal(await js(`document.querySelector('.batch-run-button').disabled`), false);
      await js(`document.querySelector('.batch-run-button').click(); true`);
      assert.ok(await waitFor(() => js(`document.querySelector('[role=tab][data-state=active]')?.textContent === 'Danh sách văn bản'
        && document.querySelectorAll('.batch-table tbody tr').length === 3 && document.querySelectorAll('.batch-status.review, .batch-status.extracted').length === 3`), 120_000), 'three PDFs must finish successfully');
      const requests = await js(`window.__vietdocBatchQA.requests.map(({name,mode,status})=>({name,mode,status}))`);
      c.batch = {count:3, requests, max_concurrent:await js(`window.__vietdocBatchQA.peak`), progress:await js(`document.querySelector('.queue-progress').textContent`)};
      assert.equal(c.batch.max_concurrent, 1, 'batch requests must be sequential');
      assert.deepEqual(requests, batchFiles.map(file => ({name:path.basename(file),mode:'native_text',status:200})));
      assert.ok(c.batch.progress.includes('3/3'));
      const keys = ['docId','arcDocCode','maintenance','typeName','codeNumber','codeNotation','issuedDate','organName','subject','language','numberOfPage','inforSign','keyword','mode','confidenceLevel','autograph','format','process','riskRecovery','riskRecoveryStatus','description','isCan'];
      const expected = [];
      const editedSubject = '=VietDoc kiểm thử Excel – chỉnh sửa riêng tài liệu thứ nhất';
      for (let index = 0; index < 3; index++) {
        await js(`document.querySelectorAll('.open-document')[${index}].click(); true`);
        assert.ok(await waitFor(() => js(`document.querySelectorAll('.metadata-field input, .metadata-field select, .metadata-field textarea').length === 22`), 5000));
        if (index === 0) await js(`(() => { const field=document.querySelector('#metadata-subject');
          Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(field,${JSON.stringify(editedSubject)});
          field.dispatchEvent(new Event('input',{bubbles:true})); })()`);
        expected.push(await js(`Object.fromEntries(${JSON.stringify(keys)}.map(key=>[key,document.querySelector('#metadata-'+key).value]))`));
        await clickResultTab('Toàn văn');
        assert.equal(await js(`document.querySelector('.text-output pre').textContent`), await js(`window.__vietdocBatchQA.requests[${index}].text`), 'metadata must not alter raw text');
        await clickResultTab('Danh sách văn bản');
      }
      await js(`document.querySelector('.open-document').click(); true`);
      assert.ok(await waitFor(() => js(`document.querySelector('#metadata-subject')?.value === ${JSON.stringify(editedSubject)}`), 5000), 'per-document edits must survive selection changes');
      c.batch.edits_preserved = true; c.batch.raw_text_preserved = true;
      fs.writeFileSync(path.join(SMOKE_DIR,'batch_expected.json'),JSON.stringify(expected,null,2),'utf8');
      await clickResultTab('Danh sách văn bản');
      await screenshot('06_batch_list.png');
      const bounds = mainWindow.getBounds(); mainWindow.setSize(960,720); await sleep(350);
      c.batch.compact_no_overflow = await js(`document.documentElement.scrollWidth <= innerWidth`);
      assert.equal(c.batch.compact_no_overflow,true,'batch table must scroll inside its pane');
      await screenshot('06b_batch_compact.png'); mainWindow.setBounds(bounds); await sleep(350);
      await js(`document.querySelector('.excel-export-button').click(); true`);
      assert.ok(await waitFor(() => js(`document.querySelector('dialog[open]')?.textContent.includes('Công khai')`), 5000),'draft export must warn about missing classification');
      await js(`document.querySelector('dialog .confirm-actions button:last-child').click(); true`);
      const workbook = path.join(downloads,'Danh_sach_van_ban.xlsx');
      assert.ok(await waitFor(async () => fs.existsSync(workbook) && fs.statSync(workbook).size > 0, 20_000),'Excel download was not saved');
      assert.equal(fs.readFileSync(workbook).subarray(0,2).toString(),'PK','export must be real XLSX, not renamed CSV');
      c.batch.xlsx_saved = true; c.batch.xlsx_sha256 = sha256(workbook);
    } finally {
      await js(`window.fetch=window.__vietdocBatchQA.original; delete window.__vietdocBatchQA; true`);
    }
  }
  if (ARGS['smoke-fast-pdf']) {
    smoke.step = 'fast-metadata';
    assert.ok(ARGS['smoke-batch-dir'], 'fast smoke requires the permitted batch fixtures');
    await require('./lib/smoke-fast').runFastSmoke({wc, js, clickResultTab, setInputFile, waitFor, screenshot,
      smokeDir:SMOKE_DIR, pdf:ARGS['smoke-fast-pdf'], batchDir:ARGS['smoke-batch-dir'], goldFile:ARGS['smoke-fast-gold'], checks:c});
  }
  if (ARGS['smoke-batch-dir']) {
    // The folder picker (webkitdirectory) with the real synthetic folder: its PDFs are queued with the
    // fast header mode, the other files (JSON) are reported as skipped. Nothing is processed here.
    smoke.step = 'folder-import';
    const dir = ARGS['smoke-batch-dir'];
    const supported = fs.readdirSync(dir, { recursive: true }).filter((name) => /\.(pdf|png|jpe?g)$/i.test(name)).length;
    const others = fs.readdirSync(dir, { recursive: true }).filter((name) => fs.statSync(path.join(dir, name)).isFile()).length - supported;
    const before = await js(`document.querySelectorAll('.input-queue li').length`);
    await setInputFile(wc, dir, 'input[webkitdirectory]');
    const added = await waitFor(() => js(`document.querySelectorAll('.input-queue li').length - ${before} || null`), 10_000);
    const modes = await js(`Array.from(document.querySelectorAll('.input-queue li select'), s => s.value).slice(${before})`);
    const message = await js(`document.querySelector('.import-notice')?.textContent || ''`);
    c.folder_import = { supported, others, added, fast_modes: modes.filter((m) => m === 'metadata_fast').length, message: message.slice(0, 300),
      ok: added === supported && modes.every((m) => m === 'metadata_fast') && (others === 0 || message.includes(`bỏ qua ${others} tệp`)) };
    await screenshot('07_folder_import.png');
    assert.ok(c.folder_import.ok, `folder import: ${JSON.stringify(c.folder_import)}`);
  } else {
    c.folder_import = { not_run: 'no --smoke-batch-dir' };  // the batch above then uses generated PDFs
  }
  c.backend_status = (await backend.request('/__desktop__/status')).data;
  // The status window exists only on demand (as from the menu): create it hidden, screenshot() shows it
  // without focus first.
  if (!statusWindow) await createStatusWindow({ show: false });
  if (statusWindow) {
    if (!statusWindow.isVisible()) statusWindow.showInactive();
    await sleep(500);
    await screenshot('05_status_window.png', statusWindow);
    c.status_ui = await statusWindow.webContents.executeJavaScript(`({
      summary: document.querySelector('#summary').textContent,
      background: getComputedStyle(document.body).backgroundColor,
      actions: Array.from(document.querySelectorAll('.actions button')).map(b => b.textContent),
      diagnostics: Boolean(document.querySelector('details #facts dd') && document.querySelector('details #problems li')),
      csp: document.querySelector('meta[http-equiv="Content-Security-Policy"]').content
    })`);
    assert.deepEqual(c.status_ui.actions, ['Thử lại', 'Mở log', 'Thoát']);
    assert.ok(c.status_ui.summary.includes('Văn bản có sẵn trong PDF') && c.status_ui.summary.includes('Sẵn sàng'));
    assert.ok(c.status_ui.csp.includes("default-src 'none'") && c.status_ui.csp.includes("script-src 'self'"));
  }

  c.ui_console_errors = smoke.console.filter(entry => entry.level === 'error' && entry.phase !== 'security-probes');
  assert.equal(c.ui_console_errors.length, 0, 'unexpected UI console error');
  c.ui_external_requests = (smoke.blocked_requests || []).filter(url => !url.startsWith('https://example.com/'));
  assert.equal(c.ui_external_requests.length, 0, 'the app must not request external fonts, CDN assets or models');

  // Failure handling: kill the server behind the app's back, expect the error state, then recover.
  smoke.step = 'crash-recovery';
  const oldPid = backend.child.pid;
  const oldServerPid = backend.serverPid;
  const oldPort = backend.port;
  process.kill(oldPid);
  const crashed = await waitFor(async () => lastStatus.step === 'crashed' && lastStatus, 15_000);
  c.crash = { killed_launcher_pid: oldPid, server_pid: oldServerPid, detected: Boolean(crashed), message: crashed && crashed.message,
    status_window_visible: Boolean(statusWindow && statusWindow.isVisible()) };
  await waitFor(async () => !isAlive(oldServerPid), 10_000);
  c.crash.server_alive_after = isAlive(oldServerPid);
  c.crash.port_closed_after = await portClosed(oldPort);
  c.crash.ui_health_after_kill = await js(`fetch('/api/health').then(r => r.status, () => 'network error')`);
  const recovered = await restart();
  c.recovery = { restarted: recovered, new_port: backend.port, port_changed: backend.port !== oldPort,
    ui: recovered ? await waitFor(() => uiState(js), 20_000) : null };
  await screenshot('04_ui_after_restart.png');
  app.quit();
}

// --------------------------------------------------------------- start

if (SMOKE_REFUSED) {
  process.stderr.write('VietDoc OCR: --smoke-* options are not available in this build.\n');
  app.exit(2);
} else if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    const win = mainWindow && mainWindow.isVisible() ? mainWindow : statusWindow || mainWindow;
    if (win) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    }
  });
  app.whenReady().then(async () => {
    smoke.step = 'ready';
    buildMenu();
    // One window from the start: the main window shows the startup page while the backend starts.
    createMainWindow();
    if (SMOKE_DIR) {  // evidence of the startup page (smoke only; a capture failure is a warning)
      await waitFor(async () => mainWindow.webContents.getURL().startsWith('data:') && !mainWindow.webContents.isLoading(), 10_000);
      await screenshot('00_startup.png');
    }
    smoke.step = 'startup-page';
    if (await startBackend()) {
      smoke.step = 'backend-started';
      await loadApp();
      smoke.step = 'main-window-loaded';
      if (SMOKE_DIR) {
        const visible = BrowserWindow.getAllWindows().filter((w) => w.isVisible());
        smoke.checks.startup = { visible_windows: visible.length, main_window_visible: visible.includes(mainWindow),
          status_window_created: Boolean(statusWindow), state: lastStatus.state };
        await runSmoke().catch((error) => { smoke.error = String((error && error.stack) || error); app.quit(); });
      }
    } else {
      // Startup error: the status window (Thử lại / Mở log / Thoát) replaces the startup page.
      await showStatusWindow();
      if (mainWindow) mainWindow.hide();
      if (SMOKE_DIR) {
        smoke.step = 'startup-failed';
        smoke.error = lastStatus.message;
        await sleep(1000);  // let the status page render the error before capturing it
        await screenshot('00_status_error.png', statusWindow);
        app.quit();
      }
    }
  }).catch((error) => {
    logMainError('startup', error);
    if (SMOKE_DIR) app.quit();
  });
}
