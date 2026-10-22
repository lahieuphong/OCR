'use strict';
// Where the desktop shell finds Python, the server script, the built frontend and the model lock.
// Machine-specific paths come from the environment or desktop/desktop.config.json (git-ignored);
// nothing is downloaded, copied or linked here.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const DESKTOP_DIR = path.resolve(__dirname, '..', '..');
const REPO_ROOT = path.resolve(DESKTOP_DIR, '..');

class ConfigError extends Error {}

function readLocalConfig(file) {
  if (!fs.existsSync(file)) return {};
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    throw new ConfigError(`desktop.config.json không đọc được: ${error.message}`);
  }
}

function absoluteFile(label, value) {
  if (!value || !path.isAbsolute(value)) {
    throw new ConfigError(`${label} phải là đường dẫn tuyệt đối (hiện: ${value || 'chưa đặt'}).`);
  }
  if (!fs.existsSync(value) || !fs.statSync(value).isFile()) {
    throw new ConfigError(`${label} không tồn tại: ${value}`);
  }
  return value;
}

function resolveConfig({ env = process.env, repoRoot = REPO_ROOT, desktopDir = DESKTOP_DIR } = {}) {
  const local = readLocalConfig(path.join(desktopDir, 'desktop.config.json'));
  const python = absoluteFile('Python (VIETDOC_PYTHON hoặc desktop.config.json "python")',
    env.VIETDOC_PYTHON || local.python || path.join(repoRoot, '.venv-demo', 'Scripts', 'python.exe'));
  const frontendDist = path.join(repoRoot, 'demo', 'local_pdf_ocr', 'frontend', 'dist');
  if (!fs.existsSync(path.join(frontendDist, 'index.html'))) {
    throw new ConfigError(`Chưa build frontend (${frontendDist}). Chạy: npm run build:frontend`);
  }
  const paddlexHome = env.VIETDOC_PADDLEX_HOME || local.paddlexHome || path.join(os.homedir(), '.paddlex');
  if (!path.isAbsolute(paddlexHome)) throw new ConfigError(`Thư mục PaddleX phải tuyệt đối: ${paddlexHome}`);
  return {
    repoRoot,
    desktopDir,
    python,
    serverScript: absoluteFile('Server script', path.join(desktopDir, 'python', 'vietdoc_desktop_server.py')),
    modelLock: absoluteFile('model_lock.json', path.join(desktopDir, 'model_lock.json')),
    frontendDist,
    paddlexHome,
  };
}

// Arguments for the server process. Run isolated (-I: no PYTHON* variables, no user site), without
// writing .pyc files (-B), so nothing lands in the repository or in other checkouts it imports from,
// and in UTF-8 mode (-X utf8), since -I also ignores PYTHONIOENCODING.
function serverArgs(config) {
  return ['-I', '-B', '-X', 'utf8', config.serverScript, '--repo-root', config.repoRoot, '--frontend-dist', config.frontendDist,
    '--model-lock', config.modelLock, '--paddlex-home', config.paddlexHome];
}

module.exports = { ConfigError, resolveConfig, serverArgs, DESKTOP_DIR, REPO_ROOT };
