'use strict';
// Where the desktop shell finds its backend, the built frontend and the model lock.
//
// Development (default): the project's Python runs desktop/python/vietdoc_desktop_server.py from the
// checkout; VIETDOC_BACKEND_EXE may point at a packaged backend executable to try it from a checkout.
// Packaged (an installed app): everything comes from Electron's resources folder; Python, Node and the
// checkout are not used, and the backend executable cannot be redirected by environment variables.
//
// Machine-specific data locations (detector cache, model root) come from the environment or a
// desktop.config.json (git-ignored in the checkout; in the user's app-data folder when packaged).
// An offline installer build may also carry the verified models in its resources folder
// (resources/models: the VietOCR B1024 files in the <repo>/models layout; resources/paddlex: a PaddleX
// home holding official_models/PP-OCRv6_medium_det). A packaged app uses them when nothing else is
// configured; development never looks there. The SHA-256 checks of contract.py and model_lock.json apply
// unchanged to bundled files. Nothing is downloaded, copied or linked here.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const DESKTOP_DIR = path.resolve(__dirname, '..', '..');
const REPO_ROOT = path.resolve(DESKTOP_DIR, '..');
const PACKAGED_BACKEND = path.join('backend', 'vietdoc-backend', 'vietdoc-backend.exe');
const BUNDLED_MODEL_ROOT = 'models';
const BUNDLED_PADDLEX_HOME = 'paddlex';

class ConfigError extends Error {}

function readLocalConfig(file) {
  if (!file || !fs.existsSync(file)) return {};
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

// A folder inside the packaged resources, or null when this build does not carry it.
function bundledDir(resourcesPath, name) {
  const dir = path.join(resourcesPath, name);
  return fs.existsSync(dir) && fs.statSync(dir).isDirectory() ? dir : null;
}

function resolveConfig({ env = process.env, repoRoot = REPO_ROOT, desktopDir = DESKTOP_DIR,
  packaged = false, resourcesPath = null, userConfigDir = null } = {}) {
  if (packaged && !(resourcesPath && path.isAbsolute(resourcesPath))) {
    throw new ConfigError('Bản đóng gói thiếu thư mục resources.');
  }
  const local = readLocalConfig(packaged ? (userConfigDir && path.join(userConfigDir, 'desktop.config.json'))
    : path.join(desktopDir, 'desktop.config.json'));
  let backendExe = null;
  if (packaged) {
    backendExe = absoluteFile('Backend đóng gói', path.join(resourcesPath, PACKAGED_BACKEND));
  } else if (env.VIETDOC_BACKEND_EXE) {
    backendExe = absoluteFile('Backend (VIETDOC_BACKEND_EXE)', env.VIETDOC_BACKEND_EXE);
  }
  const python = backendExe ? null : absoluteFile('Python (VIETDOC_PYTHON hoặc desktop.config.json "python")',
    env.VIETDOC_PYTHON || local.python || path.join(repoRoot, '.venv-demo', 'Scripts', 'python.exe'));
  const frontendDist = packaged ? path.join(resourcesPath, 'frontend')
    : path.join(repoRoot, 'demo', 'local_pdf_ocr', 'frontend', 'dist');
  if (!fs.existsSync(path.join(frontendDist, 'index.html'))) {
    throw new ConfigError(packaged ? `Bản cài thiếu giao diện (${frontendDist}).`
      : `Chưa build frontend (${frontendDist}). Chạy: npm run build:frontend`);
  }
  // Order: environment, desktop.config.json, the build's bundled folder (packaged only), the default.
  const bundledPaddlex = packaged ? bundledDir(resourcesPath, BUNDLED_PADDLEX_HOME) : null;
  const paddlexHome = env.VIETDOC_PADDLEX_HOME || local.paddlexHome || bundledPaddlex || path.join(os.homedir(), '.paddlex');
  if (!path.isAbsolute(paddlexHome)) throw new ConfigError(`Thư mục PaddleX phải tuyệt đối: ${paddlexHome}`);
  // Optional folder with the frozen VietOCR files outside the checkout (same layout as <repo>/models).
  // It only moves the location; contract.py still checks every SHA-256 and blocks OCR on any difference.
  const bundledModels = packaged ? bundledDir(resourcesPath, BUNDLED_MODEL_ROOT) : null;
  const modelRoot = env.VIETDOC_MODEL_ROOT || local.modelRoot || bundledModels || null;
  if (modelRoot && (!path.isAbsolute(modelRoot) || !fs.existsSync(modelRoot) || !fs.statSync(modelRoot).isDirectory())) {
    throw new ConfigError(`Thư mục model (VIETDOC_MODEL_ROOT hoặc "modelRoot") phải là thư mục tuyệt đối đã tồn tại: ${modelRoot}`);
  }
  return {
    packaged,
    repoRoot: packaged ? resourcesPath : repoRoot,
    desktopDir,
    python,
    backendExe,
    command: backendExe || python,
    serverScript: backendExe ? null : absoluteFile('Server script', path.join(desktopDir, 'python', 'vietdoc_desktop_server.py')),
    modelLock: absoluteFile('model_lock.json', packaged ? path.join(resourcesPath, 'model_lock.json') : path.join(desktopDir, 'model_lock.json')),
    frontendDist,
    paddlexHome,
    modelRoot,
    sources: {
      paddlexHome: env.VIETDOC_PADDLEX_HOME ? 'env' : local.paddlexHome ? 'config' : bundledPaddlex ? 'bundled' : 'default',
      modelRoot: env.VIETDOC_MODEL_ROOT ? 'env' : local.modelRoot ? 'config' : bundledModels ? 'bundled' : 'default',
    },
  };
}

// Arguments for the server process. The Python form runs isolated (-I: no PYTHON* variables, no user
// site), without writing .pyc files (-B), and in UTF-8 mode (-X utf8, since -I also ignores
// PYTHONIOENCODING). The packaged backend is built with the same options.
function serverArgs(config) {
  const common = ['--repo-root', config.repoRoot, '--frontend-dist', config.frontendDist,
    '--model-lock', config.modelLock, '--paddlex-home', config.paddlexHome];
  return config.backendExe ? common : ['-I', '-B', '-X', 'utf8', config.serverScript, ...common];
}

module.exports = { ConfigError, resolveConfig, serverArgs, DESKTOP_DIR, REPO_ROOT, PACKAGED_BACKEND,
  BUNDLED_MODEL_ROOT, BUNDLED_PADDLEX_HOME };
