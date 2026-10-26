'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const afterPack = require('../scripts/after-pack');

for (const platform of ['win32', 'darwin']) {
  test(`afterPack removes only default_app.asar from ${platform} resources`, async (t) => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-after-pack-'));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    const resources = platform === 'darwin'
      ? path.join(root, 'VietDoc OCR.app', 'Contents', 'Resources') : path.join(root, 'resources');
    fs.mkdirSync(resources, { recursive: true });
    fs.writeFileSync(path.join(resources, 'default_app.asar'), 'unused Electron app');
    fs.writeFileSync(path.join(resources, 'app.asar'), 'VietDoc app');
    const context = { appOutDir: root, electronPlatformName: platform,
      packager: { appInfo: { productFilename: 'VietDoc OCR' } } };
    await afterPack(context);
    assert.equal(fs.existsSync(path.join(resources, 'default_app.asar')), false);
    assert.equal(fs.readFileSync(path.join(resources, 'app.asar'), 'utf8'), 'VietDoc app');
    await afterPack(context); // Electron builds that omit the default app also work.
  });
}
