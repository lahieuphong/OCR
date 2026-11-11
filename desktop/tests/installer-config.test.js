'use strict';
// The offline installer proof of concept (electron-builder.installer.yml): one full offline NSIS file, per-user,
// no download of any kind, release behaviour inherited, the smoke test only in the separate internal test
// installer. YAML text is compared with LF endings (a Windows checkout has CRLF).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const DESKTOP = path.resolve(__dirname, '..');
const read = (name) => fs.readFileSync(path.join(DESKTOP, name), 'utf8').replace(/^﻿/, '').replace(/\r\n/g, '\n');
// The YAML without comments, so a commented-out line never satisfies or breaks a check.
const settings = (name) => read(name).split('\n').filter((line) => !/^\s*#/.test(line)).map((line) => line.replace(/\s+#.*$/, '')).join('\n');

test('installer: extends the release config, refuses the smoke test, never publishes or updates', () => {
  const yml = settings('electron-builder.installer.yml');
  assert.match(yml, /^extends: electron-builder\.yml$/m);
  assert.match(yml, /^extraMetadata:\n {2}vietdocSmokeTest: false$/m);
  assert.doesNotMatch(yml, /vietdocSmokeTest: true/);
  assert.match(yml, /^publish: null$/m);
  assert.match(yml, /^ {2}differentialPackage: false$/m);
  assert.doesNotMatch(yml, /nsis-web|appx|squirrel|electron-updater|autoUpdate/i);
});

test('installer: one offline NSIS x64 file, per-user, never elevated', () => {
  const yml = settings('electron-builder.installer.yml');
  assert.match(yml, /^win:\n {2}target:\n {4}- target: nsis\n {6}arch: \[x64\]$/m);
  for (const line of ['oneClick: false', 'perMachine: false', 'allowElevation: false', 'packElevateHelper: false',
    'createStartMenuShortcut: true', 'createDesktopShortcut: false', 'deleteAppDataOnUninstall: false', 'warningsAsErrors: true']) {
    assert.match(yml, new RegExp(`^ {2}${line}$`, 'm'), line);
  }
  assert.match(yml, /^ {2}artifactName: VietDoc OCR Setup\.\$\{ext\}$/m);
  assert.match(yml, /^ {2}requestedExecutionLevel: asInvoker$/m);
});

test('installer: the executables name the project as author, never Electron\'s or GitHub\'s identity', () => {
  const yml = settings('electron-builder.installer.yml');
  assert.match(yml, /^extraMetadata:\n {2}vietdocSmokeTest: false\n {2}author:\n {4}name: VietDoc OCR project \(internal\)\n {2}description: .*NOT FOR DISTRIBUTION\)$/m);
  assert.doesNotMatch(yml, /GitHub|Electron Community|OpenJS/i);
});

test('installer: adds exactly the bundled models to the parent resources (no duplicate of the parent list)', () => {
  const yml = settings('electron-builder.installer.yml');
  const block = yml.match(/^extraResources:\n((?: {2}.*\n?)+)/m)[1];
  assert.deepEqual([...block.matchAll(/- from: (\S+)\n {4}to: (\S+)/g)].map((m) => [m[1], m[2]]),
    [['out/models', 'models'], ['out/paddlex', 'paddlex']]);
  // The release folder build stays model-free.
  const release = settings('electron-builder.yml');
  assert.doesNotMatch(release, /out\/models|out\/paddlex|to: models|to: paddlex/);
});

test('internal smoke-test installer: only the smoke switch and its own name differ', () => {
  const yml = settings('electron-builder.installer-smoke.yml');
  assert.match(yml, /^extends: electron-builder\.installer\.yml$/m);
  assert.match(yml, /^ {2}vietdocSmokeTest: true$/m);
  assert.match(yml, /^ {2}artifactName: VietDoc OCR Setup INTERNAL-SMOKE-TEST\.\$\{ext\}$/m);
  const keys = yml.split('\n').filter((line) => /^\S/.test(line)).map((line) => line.split(':')[0]);
  assert.deepEqual(keys, ['extends', 'extraMetadata', 'nsis']);
});

test('release: one per-user NSIS Setup with the bundled models and notices, GitHub update feed, internal by default', () => {
  const yml = settings('electron-builder.release.yml');
  assert.match(yml, /^extends: electron-builder\.yml$/m);
  assert.match(yml, /^appId: vn\.vietdoc\.ocr\.desktop$/m);
  assert.match(yml, /^productName: VietDoc OCR$/m);
  // The installed Setup updates itself from this repository's Releases (latest.yml + blockmap); nothing else is fetched.
  assert.match(yml, /^publish:\n {2}provider: github\n {2}owner: lahieuphong\n {2}repo: OCR\n {2}releaseType: release$/m);
  assert.match(yml, /^extraMetadata:\n {2}vietdocSmokeTest: false\n {2}vietdocUpdates: true$/m);
  assert.doesNotMatch(yml, /vietdocSmokeTest: true|nsis-web|appx|squirrel|target: portable/i);
  assert.match(yml, /^win:\n {2}target:\n {4}- target: nsis\n {6}arch: \[x64\]$/m);
  for (const line of ['oneClick: false', 'perMachine: false', 'allowElevation: false', 'packElevateHelper: false',
    'allowToChangeInstallationDirectory: false', 'createStartMenuShortcut: true', 'createDesktopShortcut: false',
    'deleteAppDataOnUninstall: false', 'differentialPackage: true', 'include: build-resources/installer.nsh',
    'warningsAsErrors: true', 'shortcutName: VietDoc OCR']) {
    assert.match(yml, new RegExp(`^ {2}${line}$`, 'm'), line);
  }
  assert.match(yml, /^ {2}requestedExecutionLevel: asInvoker$/m);
  const block = yml.match(/^extraResources:\n((?: {2}.*\n?)+)/m)[1];
  assert.deepEqual([...block.matchAll(/- from: (\S+)\n {4}to: (\S+)/g)].map((m) => [m[1], m[2]]),
    [['out/models', 'models'], ['out/paddlex', 'paddlex'], ['out/licenses', 'licenses']]);
  // Internal unless the public variant is used: names and the licence page say so.
  assert.match(yml, /^ {2}artifactName: VietDoc-OCR-v\$\{version\}-INTERNAL-Windows-\$\{arch\}-Setup\.\$\{ext\}$/m);
  assert.match(yml, /^ {2}uninstallDisplayName: \$\{productName\} \$\{version\} \(INTERNAL TEST\)$/m);
  assert.match(yml, /^ {2}license: build-resources\/INTERNAL_NOTICE\.txt$/m);
  // Its own appId (own uninstall entry). The test build ("VietDoc OCR Test") also has its own folder and profile; the
  // older internal offline installer (electron-builder.installer.yml) shares the name "VietDoc OCR", so its default
  // install folder, shortcut and %APPDATA% profile: uninstall that one first (release/PHAT_HANH_WINDOWS.md).
  for (const other of ['electron-builder.yml', 'electron-builder.windows.yml']) {
    const appId = settings(other).match(/^appId: (\S+)$/m)[1];
    assert.notEqual(appId, 'vn.vietdoc.ocr.desktop', other);
  }
});

test('public release: only the names, the licence page and the metadata change', () => {
  const yml = settings('electron-builder.release-public.yml');
  assert.match(yml, /^extends: electron-builder\.release\.yml$/m);
  const keys = yml.split('\n').filter((line) => /^\S/.test(line)).map((line) => line.split(':')[0]);
  assert.deepEqual(keys, ['extends', 'copyright', 'extraMetadata', 'nsis']);
  const nsis = yml.match(/^nsis:\n((?: {2}.*\n?)+)/m)[1].trim().split('\n').map((line) => line.trim().split(':')[0]);
  assert.deepEqual(nsis, ['uninstallDisplayName', 'artifactName', 'license']);
  assert.match(yml, /^ {2}artifactName: VietDoc-OCR-v\$\{version\}-Windows-\$\{arch\}-Setup\.\$\{ext\}$/m);
  assert.match(yml, /^ {2}license: build-resources\/PUBLIC_LICENSE\.txt$/m);
  assert.match(yml, /^ {2}vietdocSmokeTest: false\n {2}vietdocUpdates: true$/m);
  assert.doesNotMatch(yml, /INTERNAL|vietdocSmokeTest: true/);
});

test('release smoke-test variant: only the smoke switch and its internal names differ', () => {
  const yml = settings('electron-builder.release-smoke.yml');
  assert.match(yml, /^extends: electron-builder\.release\.yml$/m);
  const keys = yml.split('\n').filter((line) => /^\S/.test(line)).map((line) => line.split(':')[0]);
  assert.deepEqual(keys, ['extends', 'extraMetadata', 'nsis']);
  assert.match(yml, /^ {2}vietdocSmokeTest: true$/m);
  assert.match(yml, /^ {2}artifactName: VietDoc-OCR-v\$\{version\}-INTERNAL-SMOKE-TEST-Windows-\$\{arch\}-Setup\.\$\{ext\}$/m);
});

test('installer script: keeps the installer copy the auto-updater needs for a differential update', () => {
  const nsh = read('build-resources/installer.nsh');
  const code = nsh.split('\n').filter((line) => !/^\s*;/.test(line)).join('\n');
  assert.doesNotMatch(code, /APP_INSTALLER_STORE_FILE/);
  assert.doesNotMatch(nsh, /RMDir \/r/i);
});

test('installer script: per-user forced, Desktop shortcut opt-in, nothing downloaded or executed', () => {
  const nsh = read('build-resources/installer.nsh');
  assert.match(nsh, /!macro customInstallMode\n {2}StrCpy \$isForceCurrentInstall "1"\n!macroend/);
  assert.match(nsh, /!macro customInit\n {2}StrCpy \$VietDocDesktopShortcut "0"\n/);
  // Off by default; on only when the user already has the shortcut (upgrade keeps it).
  assert.match(nsh, /\$\{If\} \$\{FileExists\} "\$DESKTOP\\\$\{SHORTCUT_NAME\}\.lnk"\n {4}StrCpy \$VietDocDesktopShortcut "1"/);
  const uninstall = nsh.match(/!macro customUnInstall\n([\s\S]*?)!macroend/)[1];
  assert.match(uninstall, /^ {2}\$\{ifNot\} \$\{isUpdated\}\n[\s\S]*Delete "\$DESKTOP\\/m);
  assert.match(nsh, /\$\{If\} \$VietDocDesktopShortcut == "1"\n {4}CreateShortCut "\$DESKTOP\\/);
  const code = nsh.split('\n').filter((line) => !/^\s*;/.test(line)).join('\n');
  assert.doesNotMatch(code, /inetc|NSISdl|INetC|http:|https:|ExecWait|nsExec|ExecShell|UAC_RunElevated|RequestExecutionLevel/i);
  const notice = read('build-resources/INTERNAL_NOTICE.txt');
  assert.match(notice, /INTERNAL \/ NOT FOR DISTRIBUTION/);
});
