'use strict';
// Automatic updates of the INSTALLED release (NSIS Setup) from this repository's GitHub Releases (electron-updater).
//
// Never in development, during the smoke test, for the Portable ZIP (it keeps its own data folder and has no
// uninstaller), for the internal test builds, or for a build whose package.json lacks "vietdocUpdates": true (only
// electron-builder.release*.yml set it). An update is downloaded over HTTPS from GitHub, checked against the SHA-512
// listed in latest.yml and installed when the app quits. The builds are not code-signed yet, so no publisher signature
// can be checked (release/PHAT_HANH_WINDOWS.md, section 7).
const fs = require('node:fs');
const path = require('node:path');

function updatesAllowed({ packaged = false, smoke = false, packageJson = {}, execPath = '', resourcesPath = '',
  productName = '', portableDataDir = null } = {}) {
  const no = (reason) => ({ allowed: false, reason });
  if (!packaged) return no('development run');
  if (smoke) return no('smoke test');
  if (portableDataDir) return no('portable copy');
  if (!packageJson || packageJson.vietdocUpdates !== true) return no('build without updates');
  if (packageJson.vietdocTestBuild === true || packageJson.vietdocSmokeTest === true) return no('test build');
  if (!resourcesPath || !fs.existsSync(path.join(resourcesPath, 'app-update.yml'))) return no('no update feed');
  if (!execPath || !productName || !fs.existsSync(path.join(path.dirname(execPath), `Uninstall ${productName}.exe`))) {
    return no('not an installed copy');
  }
  return { allowed: true, reason: 'installed release' };
}

const EVENTS = ['checking-for-update', 'update-available', 'update-not-available', 'update-downloaded', 'error'];

// Checks once, a little after start-up; a found update downloads in the background and installs on quit.
function startUpdates({ updater, log, delayMs = 10_000, schedule = setTimeout } = {}) {
  updater.autoDownload = true;
  updater.autoInstallOnAppQuit = true;
  updater.logger = { info: (m) => log('update', m), warn: (m) => log('update warning', m), error: (m) => log('update error', m),
    debug: () => {} };
  for (const event of EVENTS) {
    updater.on(event, (info) => log(`update ${event}`, info && info.version ? `version ${info.version}`
      : (info && info.message) || ''));
  }
  const timer = schedule(() => {
    Promise.resolve().then(() => updater.checkForUpdatesAndNotify()).catch((error) => log('update error', error));
  }, delayMs);
  if (timer && typeof timer.unref === 'function') timer.unref();
  return timer;
}

// The answer the "Kiểm tra cập nhật" menu shows.
async function checkNow({ updater, currentVersion }) {
  try {
    const result = await updater.checkForUpdates();
    const latest = result && result.updateInfo && result.updateInfo.version;
    const newer = Boolean(latest) && latest !== currentVersion && (!result || result.isUpdateAvailable !== false);
    return newer
      ? { type: 'info', message: `Đang tải VietDoc OCR ${latest}. Bản mới được cài khi bạn đóng ứng dụng.` }
      : { type: 'info', message: `Bạn đang dùng bản mới nhất (${currentVersion}).` };
  } catch (error) {
    return { type: 'warning', message: 'Không kiểm tra được bản cập nhật. Cần kết nối Internet tới GitHub.',
      detail: String((error && error.message) || error) };
  }
}

module.exports = { updatesAllowed, startUpdates, checkNow };
