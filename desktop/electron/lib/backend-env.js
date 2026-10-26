'use strict';
// The environment of the local OCR server process, built from scratch instead of inherited.
//
// The user's environment can carry variables that change what the backend imports, which native
// libraries it loads, where it downloads from or how Paddle computes (PYTHONPATH/PYTHONHOME/PYTHONSTARTUP,
// PATH entries of other Python or Node installs, PADDLE_PDX_* model sources and caches, FLAGS_* Paddle
// flags, OMP/KMP/MKL threading knobs, proxies, CUDA settings), plus unrelated secrets of other tools.
// The server only needs OS essentials, a PATH it controls and two settings of its own, so it
// gets exactly that:
//   - an allowlist of OS variables (loader, temp folders, user profile folders, CPU description),
//   - PATH = the backend's own folder(s) first, then the Windows system folders (no user entries),
//   - PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True (no model-hoster probing),
//   - VIETDOC_MODEL_ROOT only from the validated configuration (contract.py still checks every SHA-256).
// Everything else (VIETDOC_* switches of the shell included) is dropped. The server sets
// PADDLE_PDX_CACHE_HOME itself from --paddlex-home.
const path = require('node:path');

const WINDOWS_KEEP = [
  'SystemRoot', 'SystemDrive', 'windir', 'ComSpec', 'PATHEXT', 'TEMP', 'TMP',
  'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'APPDATA', 'LOCALAPPDATA', 'ProgramData', 'ALLUSERSPROFILE', 'PUBLIC',
  'ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432',
  'CommonProgramFiles', 'CommonProgramFiles(x86)', 'CommonProgramW6432',
  'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'PROCESSOR_IDENTIFIER', 'PROCESSOR_LEVEL', 'PROCESSOR_REVISION',
  'OS',
];
// Development and packaged runs on Linux/macOS keep POSIX essentials. A development CPython on Linux
// (actions/setup-python on Ubuntu) may need LD_LIBRARY_PATH; packaged runtimes never inherit it.
// LD_PRELOAD and DYLD_* are never passed.
const POSIX_KEEP = ['HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG', 'LC_ALL', 'LC_CTYPE'];
const POSIX_SYSTEM_PATH = ['/usr/local/bin', '/usr/bin', '/bin'];

// Windows variable names are case-insensitive; a plain object copy of process.env is not.
function lookup(env, name, platform) {
  if (Object.prototype.hasOwnProperty.call(env, name)) return env[name];
  if (platform !== 'win32') return undefined;
  const upper = name.toUpperCase();
  const key = Object.keys(env).find((k) => k.toUpperCase() === upper);
  return key === undefined ? undefined : env[key];
}

function systemPath(env, platform) {
  if (platform !== 'win32') return POSIX_SYSTEM_PATH;
  const root = lookup(env, 'SystemRoot', platform) || lookup(env, 'windir', platform) || 'C:\\Windows';
  return [path.win32.join(root, 'System32'), root, path.win32.join(root, 'System32', 'Wbem')];
}

// config: the validated result of resolveConfig() (backendExe or python, modelRoot).
function backendEnv(config = {}, { sourceEnv = process.env, platform = process.platform } = {}) {
  const p = platform === 'win32' ? path.win32 : path.posix;
  const separator = platform === 'win32' ? ';' : ':';
  const env = {};
  for (const name of platform === 'win32' ? WINDOWS_KEEP : POSIX_KEEP) {
    const value = lookup(sourceEnv, name, platform);
    if (value !== undefined && value !== '') env[name] = value;
  }
  if (platform === 'linux' && !config.backendExe && sourceEnv.LD_LIBRARY_PATH) {
    env.LD_LIBRARY_PATH = sourceEnv.LD_LIBRARY_PATH;
  }
  const own = [];
  if (config.backendExe) {
    const dir = p.dirname(config.backendExe);
    own.push(dir, p.join(dir, '_internal'));  // PyInstaller onedir: the exe and its bundled DLLs
  } else if (config.python) {
    own.push(p.dirname(config.python));  // the project's interpreter (a venv launcher finds its base itself)
  }
  // A folder name containing the PATH separator would split into unrelated entries: leave it out (the frozen
  // backend finds its own DLLs without PATH) rather than corrupt PATH.
  env.PATH = [...own, ...systemPath(sourceEnv, platform)].filter((dir) => !dir.includes(separator)).join(separator);
  env.PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True';
  if (config.modelRoot) env.VIETDOC_MODEL_ROOT = config.modelRoot;
  return env;
}

module.exports = { backendEnv, WINDOWS_KEEP, POSIX_KEEP };
