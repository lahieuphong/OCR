'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { resolveConfig, serverArgs, ConfigError, REPO_ROOT, DESKTOP_DIR } = require('../electron/lib/config');

function fixture(t, { dist = true, python = true, local } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-desktop-config-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const repoRoot = path.join(root, 'repo');
  const desktopDir = path.join(repoRoot, 'desktop');
  fs.mkdirSync(path.join(desktopDir, 'python'), { recursive: true });
  fs.writeFileSync(path.join(desktopDir, 'python', 'vietdoc_desktop_server.py'), '');
  fs.writeFileSync(path.join(desktopDir, 'model_lock.json'), '{}');
  if (dist) {
    fs.mkdirSync(path.join(repoRoot, 'demo', 'local_pdf_ocr', 'frontend', 'dist'), { recursive: true });
    fs.writeFileSync(path.join(repoRoot, 'demo', 'local_pdf_ocr', 'frontend', 'dist', 'index.html'), '');
  }
  const pythonExe = path.join(root, 'venv', 'python.exe');
  if (python) {
    fs.mkdirSync(path.dirname(pythonExe), { recursive: true });
    fs.writeFileSync(pythonExe, '');
  }
  if (local !== undefined) fs.writeFileSync(path.join(desktopDir, 'desktop.config.json'), typeof local === 'string' ? local : JSON.stringify(local));
  return { root, repoRoot, desktopDir, pythonExe };
}

test('the shell sits in <repo>/desktop', () => {
  assert.equal(path.basename(DESKTOP_DIR), 'desktop');
  assert.equal(path.dirname(DESKTOP_DIR), REPO_ROOT);
});

test('environment variables win over desktop.config.json', (t) => {
  const f = fixture(t, { local: { python: 'C:\\not\\used.exe', paddlexHome: 'C:\\not\\used' } });
  const config = resolveConfig({ env: { VIETDOC_PYTHON: f.pythonExe, VIETDOC_PADDLEX_HOME: path.join(f.root, 'px') }, repoRoot: f.repoRoot, desktopDir: f.desktopDir });
  assert.equal(config.python, f.pythonExe);
  assert.equal(config.paddlexHome, path.join(f.root, 'px'));
  assert.equal(config.frontendDist, path.join(f.repoRoot, 'demo', 'local_pdf_ocr', 'frontend', 'dist'));
});

test('desktop.config.json is used when no environment variable is set', (t) => {
  const f = fixture(t);
  fs.writeFileSync(path.join(f.desktopDir, 'desktop.config.json'), JSON.stringify({ python: f.pythonExe, paddlexHome: path.join(f.root, 'px') }));
  const config = resolveConfig({ env: {}, repoRoot: f.repoRoot, desktopDir: f.desktopDir });
  assert.equal(config.python, f.pythonExe);
  assert.equal(config.paddlexHome, path.join(f.root, 'px'));
});

test('relative or missing Python is refused', (t) => {
  const f = fixture(t);
  assert.throws(() => resolveConfig({ env: { VIETDOC_PYTHON: 'python.exe' }, repoRoot: f.repoRoot, desktopDir: f.desktopDir }), ConfigError);
  assert.throws(() => resolveConfig({ env: { VIETDOC_PYTHON: path.join(f.root, 'nope.exe') }, repoRoot: f.repoRoot, desktopDir: f.desktopDir }),
    /không tồn tại/);
  // Default: <repo>/.venv-demo, which this fixture does not have.
  assert.throws(() => resolveConfig({ env: {}, repoRoot: f.repoRoot, desktopDir: f.desktopDir }), /\.venv-demo/);
});

test('a missing frontend build is reported with the build command', (t) => {
  const f = fixture(t, { dist: false });
  assert.throws(() => resolveConfig({ env: { VIETDOC_PYTHON: f.pythonExe }, repoRoot: f.repoRoot, desktopDir: f.desktopDir }), /npm run build:frontend/);
});

test('broken desktop.config.json and relative PaddleX home are refused', (t) => {
  const f = fixture(t, { local: '{not json' });
  assert.throws(() => resolveConfig({ env: { VIETDOC_PYTHON: f.pythonExe }, repoRoot: f.repoRoot, desktopDir: f.desktopDir }), /desktop.config.json/);
  const g = fixture(t);
  assert.throws(() => resolveConfig({ env: { VIETDOC_PYTHON: g.pythonExe, VIETDOC_PADDLEX_HOME: 'px' }, repoRoot: g.repoRoot, desktopDir: g.desktopDir }), /tuyệt đối/);
});

test('server arguments: isolated, no bytecode, UTF-8, no token on the command line', (t) => {
  const f = fixture(t);
  const config = resolveConfig({ env: { VIETDOC_PYTHON: f.pythonExe, VIETDOC_PADDLEX_HOME: path.join(f.root, 'px') }, repoRoot: f.repoRoot, desktopDir: f.desktopDir });
  const args = serverArgs(config);
  assert.deepEqual(args.slice(0, 4), ['-I', '-B', '-X', 'utf8']);
  assert.equal(args[4], config.serverScript);
  assert.deepEqual(args.slice(5), ['--repo-root', f.repoRoot, '--frontend-dist', config.frontendDist,
    '--model-lock', config.modelLock, '--paddlex-home', config.paddlexHome]);
  assert.ok(!args.some((a) => /token/i.test(a)));
});

test('the example config names only keys the shell reads', () => {
  const example = JSON.parse(fs.readFileSync(path.join(DESKTOP_DIR, 'desktop.config.example.json'), 'utf8'));
  assert.deepEqual(Object.keys(example).filter((k) => !k.startsWith('_')).sort(), ['paddlexHome', 'python']);
});
