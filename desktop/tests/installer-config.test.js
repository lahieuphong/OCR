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

test('installer script: per-user forced, Desktop shortcut opt-in, nothing downloaded or executed', () => {
  const nsh = read('build-resources/installer.nsh');
  assert.match(nsh, /!macro customInstallMode\n {2}StrCpy \$isForceCurrentInstall "1"\n!macroend/);
  assert.match(nsh, /!macro customInit\n {2}StrCpy \$VietDocDesktopShortcut "0"\n!macroend/);
  assert.match(nsh, /\$\{If\} \$VietDocDesktopShortcut == "1"\n {4}CreateShortCut "\$DESKTOP\\/);
  const code = nsh.split('\n').filter((line) => !/^\s*;/.test(line)).join('\n');
  assert.doesNotMatch(code, /inetc|NSISdl|INetC|http:|https:|ExecWait|nsExec|ExecShell|UAC_RunElevated|RequestExecutionLevel/i);
  const notice = read('build-resources/INTERNAL_NOTICE.txt');
  assert.match(notice, /INTERNAL \/ NOT FOR DISTRIBUTION/);
});
