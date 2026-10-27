'use strict';
const fs = require('node:fs');
const path = require('node:path');
// Only the packaged test flavor gets a separate name/profile. Release and development keep their identity.
function appIdentity({ packaged = false, packageJson = {} } = {}) {
  const testBuild = packaged && packageJson && packageJson.vietdocTestBuild === true;
  return testBuild
    ? { name: 'VietDoc OCR Test', userDataName: 'VietDoc OCR Test' }
    : { name: 'VietDoc OCR', userDataName: null };
}
// Opt-in data folder beside an installed app: "<app name> Data" next to the install folder (Windows/Linux) or
// next to the .app bundle (macOS). When that folder already exists, settings, desktop.config.json, logs and
// browser storage live there instead of the user's AppData folder. It sits outside the install folder, so
// uninstalling or reinstalling never removes it. Nothing creates it: without it the profile is unchanged.
function portableDataDir({ packaged = false, name, execPath = process.execPath, platform = process.platform } = {}) {
  if (!packaged || !name || !execPath || !path.isAbsolute(execPath)) return null;
  const installRoot = platform === 'darwin' ? path.resolve(execPath, '..', '..', '..') : path.dirname(execPath);
  const dir = path.join(path.dirname(installRoot), `${name} Data`);
  try {
    return fs.statSync(dir).isDirectory() ? dir : null;
  } catch {
    return null;
  }
}
function configureAppIdentity(app, packageJson, { execPath = process.execPath, platform = process.platform } = {}) {
  const identity = appIdentity({ packaged: app.isPackaged, packageJson });
  app.setName(identity.name);
  const portable = portableDataDir({ packaged: app.isPackaged, name: identity.name, execPath, platform });
  if (portable) {
    app.setPath('userData', portable);
    app.setPath('sessionData', portable);
  } else if (identity.userDataName) {
    const userData = path.join(app.getPath('appData'), identity.userDataName);
    // Electron requires overridden directories to exist, including on a first launch.
    fs.mkdirSync(userData, { recursive: true });
    app.setPath('userData', userData);
    app.setPath('sessionData', userData);
  }
  return { ...identity, portableDataDir: portable };
}
module.exports = { appIdentity, configureAppIdentity, portableDataDir };
