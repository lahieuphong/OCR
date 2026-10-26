'use strict';
// electron-builder afterPack hook: remove Electron's default_app.asar from the packaged app. The app always
// loads its own resources/app.asar (fuse OnlyLoadAppFromAsar), so the default app can never run; nothing
// else is touched.
const fs = require('node:fs');
const path = require('node:path');

module.exports = async function afterPack(context) {
  const resources = context.electronPlatformName === 'darwin'
    ? path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`, 'Contents', 'Resources')
    : path.join(context.appOutDir, 'resources');
  const file = path.join(resources, 'default_app.asar');
  if (fs.existsSync(file)) fs.rmSync(file);
};
