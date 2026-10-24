'use strict';
// Packaged mode of the config: everything from Electron's resources folder, nothing from the checkout,
// Python or Node; the backend executable cannot be redirected through the environment.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { resolveConfig, serverArgs, ConfigError, PACKAGED_BACKEND, BUNDLED_MODEL_ROOT, BUNDLED_PADDLEX_HOME } = require('../electron/lib/config');
const { backendEnv } = require('../electron/lib/backend-env');

function resources(t, { backend = true, frontend = true, lock = true } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-packaged-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const res = path.join(root, 'resources');
  const userData = path.join(root, 'userData');
  fs.mkdirSync(userData, { recursive: true });
  if (backend) {
    fs.mkdirSync(path.dirname(path.join(res, PACKAGED_BACKEND)), { recursive: true });
    fs.writeFileSync(path.join(res, PACKAGED_BACKEND), '');
  }
  if (frontend) {
    fs.mkdirSync(path.join(res, 'frontend'), { recursive: true });
    fs.writeFileSync(path.join(res, 'frontend', 'index.html'), '');
  }
  if (lock) fs.writeFileSync(path.join(res, 'model_lock.json'), '{}');
  return { root, res, userData };
}

test('packaged: backend, frontend and lock come from resources; no Python, no checkout', (t) => {
  const r = resources(t);
  const config = resolveConfig({ env: { VIETDOC_PADDLEX_HOME: path.join(r.root, 'px') }, packaged: true, resourcesPath: r.res, userConfigDir: r.userData });
  assert.equal(config.packaged, true);
  assert.equal(config.backendExe, path.join(r.res, PACKAGED_BACKEND));
  assert.equal(config.command, config.backendExe);
  assert.equal(config.python, null);
  assert.equal(config.serverScript, null);
  assert.equal(config.frontendDist, path.join(r.res, 'frontend'));
  assert.equal(config.modelLock, path.join(r.res, 'model_lock.json'));
  assert.equal(config.repoRoot, r.res);
  assert.deepEqual(serverArgs(config), ['--repo-root', r.res, '--frontend-dist', path.join(r.res, 'frontend'),
    '--model-lock', path.join(r.res, 'model_lock.json'), '--paddlex-home', path.join(r.root, 'px')]);
});

test('packaged: environment cannot swap the backend or Python', (t) => {
  const r = resources(t);
  const other = path.join(r.root, 'evil.exe');
  fs.writeFileSync(other, '');
  const config = resolveConfig({ env: { VIETDOC_BACKEND_EXE: other, VIETDOC_PYTHON: other }, packaged: true,
    resourcesPath: r.res, userConfigDir: r.userData });
  assert.equal(config.command, path.join(r.res, PACKAGED_BACKEND));
  assert.equal(config.python, null);
});

test('packaged: user config lives in the app-data folder, model root still validated', (t) => {
  const r = resources(t);
  const models = path.join(r.root, 'models');
  fs.mkdirSync(models);
  fs.writeFileSync(path.join(r.userData, 'desktop.config.json'), JSON.stringify({ modelRoot: models, paddlexHome: path.join(r.root, 'px') }));
  const config = resolveConfig({ env: {}, packaged: true, resourcesPath: r.res, userConfigDir: r.userData });
  assert.equal(config.modelRoot, models);
  assert.equal(config.paddlexHome, path.join(r.root, 'px'));
  fs.writeFileSync(path.join(r.userData, 'desktop.config.json'), JSON.stringify({ modelRoot: 'relative/models' }));
  assert.throws(() => resolveConfig({ env: {}, packaged: true, resourcesPath: r.res, userConfigDir: r.userData }), /modelRoot/);
});

test('packaged: a broken install is reported, not worked around', (t) => {
  for (const missing of ['backend', 'frontend', 'lock']) {
    const r = resources(t, { [missing]: false });
    assert.throws(() => resolveConfig({ env: {}, packaged: true, resourcesPath: r.res, userConfigDir: r.userData }), ConfigError, missing);
  }
  assert.throws(() => resolveConfig({ env: {}, packaged: true, resourcesPath: null }), /resources/);
});

test('development: VIETDOC_BACKEND_EXE runs a packaged backend from a checkout without Python flags', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-devexe-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const repoRoot = path.join(root, 'repo');
  const desktopDir = path.join(repoRoot, 'desktop');
  fs.mkdirSync(path.join(repoRoot, 'demo', 'local_pdf_ocr', 'frontend', 'dist'), { recursive: true });
  fs.writeFileSync(path.join(repoRoot, 'demo', 'local_pdf_ocr', 'frontend', 'dist', 'index.html'), '');
  fs.mkdirSync(desktopDir, { recursive: true });
  fs.writeFileSync(path.join(desktopDir, 'model_lock.json'), '{}');
  const exe = path.join(root, 'vietdoc-backend.exe');
  fs.writeFileSync(exe, '');
  const config = resolveConfig({ env: { VIETDOC_BACKEND_EXE: exe, VIETDOC_PADDLEX_HOME: path.join(root, 'px') }, repoRoot, desktopDir });
  assert.equal(config.command, exe);
  assert.equal(serverArgs(config)[0], '--repo-root');
  assert.throws(() => resolveConfig({ env: { VIETDOC_BACKEND_EXE: 'relative.exe' }, repoRoot, desktopDir }), /tuyệt đối/);
});

// Offline installer build: the verified models travel in resources/models and resources/paddlex.
test('packaged: bundled models and detector in resources are found without any configuration', (t) => {
  const r = resources(t);
  fs.mkdirSync(path.join(r.res, BUNDLED_MODEL_ROOT));
  fs.mkdirSync(path.join(r.res, BUNDLED_PADDLEX_HOME));
  const config = resolveConfig({ env: {}, packaged: true, resourcesPath: r.res, userConfigDir: r.userData });
  assert.equal(config.modelRoot, path.join(r.res, 'models'));
  assert.equal(config.paddlexHome, path.join(r.res, 'paddlex'));
  assert.deepEqual(config.sources, { modelRoot: 'bundled', paddlexHome: 'bundled' });
  assert.ok(serverArgs(config).join('\n').includes(`--paddlex-home\n${path.join(r.res, 'paddlex')}`));
  // The backend receives the bundled model root as the validated config value; contract.py checks its SHA-256.
  const env = backendEnv(config, { sourceEnv: { SystemRoot: 'C:\Windows', VIETDOC_MODEL_ROOT: 'C:\attacker' }, platform: 'win32' });
  assert.equal(env.VIETDOC_MODEL_ROOT, path.join(r.res, 'models'));
});

test('packaged: a build without bundled folders keeps the external behaviour (no model root, ~/.paddlex)', (t) => {
  const r = resources(t);
  fs.writeFileSync(path.join(r.res, BUNDLED_MODEL_ROOT), '');  // a file is not a model folder
  const config = resolveConfig({ env: {}, packaged: true, resourcesPath: r.res, userConfigDir: r.userData });
  assert.equal(config.modelRoot, null);
  assert.equal(config.paddlexHome, path.join(os.homedir(), '.paddlex'));
  assert.deepEqual(config.sources, { modelRoot: 'default', paddlexHome: 'default' });
});

test('packaged: an explicit environment or user config still wins over the bundled folders', (t) => {
  const r = resources(t);
  fs.mkdirSync(path.join(r.res, BUNDLED_MODEL_ROOT));
  fs.mkdirSync(path.join(r.res, BUNDLED_PADDLEX_HOME));
  const models = path.join(r.root, 'other-models');
  fs.mkdirSync(models);
  const fromEnv = resolveConfig({ env: { VIETDOC_MODEL_ROOT: models, VIETDOC_PADDLEX_HOME: path.join(r.root, 'px') },
    packaged: true, resourcesPath: r.res, userConfigDir: r.userData });
  assert.equal(fromEnv.modelRoot, models);
  assert.equal(fromEnv.paddlexHome, path.join(r.root, 'px'));
  assert.deepEqual(fromEnv.sources, { modelRoot: 'env', paddlexHome: 'env' });
  fs.writeFileSync(path.join(r.userData, 'desktop.config.json'), JSON.stringify({ modelRoot: models }));
  const fromConfig = resolveConfig({ env: {}, packaged: true, resourcesPath: r.res, userConfigDir: r.userData });
  assert.equal(fromConfig.modelRoot, models);
  assert.equal(fromConfig.paddlexHome, path.join(r.res, 'paddlex'));
  // An override is validated like before: a missing folder stops the start instead of falling back.
  assert.throws(() => resolveConfig({ env: { VIETDOC_MODEL_ROOT: path.join(r.root, 'missing') }, packaged: true,
    resourcesPath: r.res, userConfigDir: r.userData }), /VIETDOC_MODEL_ROOT/);
});

test('development never looks for bundled folders', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-devbundle-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const repoRoot = path.join(root, 'repo');
  const desktopDir = path.join(repoRoot, 'desktop');
  fs.mkdirSync(path.join(repoRoot, 'demo', 'local_pdf_ocr', 'frontend', 'dist'), { recursive: true });
  fs.writeFileSync(path.join(repoRoot, 'demo', 'local_pdf_ocr', 'frontend', 'dist', 'index.html'), '');
  for (const dir of [path.join(desktopDir, 'models'), path.join(desktopDir, 'paddlex'), path.join(repoRoot, 'paddlex')]) {
    fs.mkdirSync(dir, { recursive: true });
  }
  fs.writeFileSync(path.join(desktopDir, 'model_lock.json'), '{}');
  const exe = path.join(root, 'vietdoc-backend.exe');
  fs.writeFileSync(exe, '');
  const config = resolveConfig({ env: { VIETDOC_BACKEND_EXE: exe }, repoRoot, desktopDir, resourcesPath: desktopDir });
  assert.equal(config.modelRoot, null);
  assert.equal(config.paddlexHome, path.join(os.homedir(), '.paddlex'));
});
