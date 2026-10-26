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
function configureAppIdentity(app, packageJson) {
  const identity = appIdentity({ packaged: app.isPackaged, packageJson });
  app.setName(identity.name);
  if (identity.userDataName) {
    const userData = path.join(app.getPath('appData'), identity.userDataName);
    // Electron requires overridden directories to exist, including on a first launch.
    fs.mkdirSync(userData, { recursive: true });
    app.setPath('userData', userData);
    app.setPath('sessionData', userData);
  }
  return identity;
}
module.exports = { appIdentity, configureAppIdentity };
