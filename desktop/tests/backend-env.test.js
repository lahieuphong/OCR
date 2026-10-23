'use strict';
// The OCR server's environment is built from an allowlist, never inherited (electron/lib/backend-env.js).
const test = require('node:test');
const assert = require('node:assert/strict');
const { backendEnv, WINDOWS_KEEP } = require('../electron/lib/backend-env');

const PACKAGED = { backendExe: 'C:\\Program Files\\VietDoc OCR\\resources\\backend\\vietdoc-backend\\vietdoc-backend.exe',
  modelRoot: null };
const DEV = { python: 'E:\\repo\\.venv-demo\\Scripts\\python.exe', modelRoot: null };

// A realistic user environment: Windows essentials plus everything that must NOT reach the backend.
function userEnv() {
  return {
    SystemRoot: 'C:\\WINDOWS', SystemDrive: 'C:', windir: 'C:\\WINDOWS', ComSpec: 'C:\\WINDOWS\\system32\\cmd.exe',
    PATHEXT: '.COM;.EXE;.BAT', TEMP: 'C:\\Users\\u\\AppData\\Local\\Temp', TMP: 'C:\\Users\\u\\AppData\\Local\\Temp',
    USERPROFILE: 'C:\\Users\\u', APPDATA: 'C:\\Users\\u\\AppData\\Roaming', LOCALAPPDATA: 'C:\\Users\\u\\AppData\\Local',
    ProgramData: 'C:\\ProgramData', NUMBER_OF_PROCESSORS: '16', PROCESSOR_ARCHITECTURE: 'AMD64', OS: 'Windows_NT',
    Path: 'C:\\Python312;C:\\Python312\\Scripts;C:\\Program Files\\nodejs;C:\\Users\\u\\evil-dlls',
    PYTHONPATH: 'C:\\evil', PYTHONHOME: 'C:\\evil', PYTHONSTARTUP: 'C:\\evil\\start.py', PYTHONINSPECT: '1',
    PYTHONVERBOSE: '1', PYTHONUTF8: '0', PYTHONIOENCODING: 'latin-1',
    NODE_OPTIONS: '--require C:\\evil\\hook.js', ELECTRON_RUN_AS_NODE: '1',
    VIETDOC_MODEL_ROOT: 'C:\\attacker-models', VIETDOC_BACKEND_EXE: 'C:\\evil.exe', VIETDOC_PYTHON: 'C:\\evil\\python.exe',
    VIETDOC_PADDLEX_HOME: 'C:\\evil-paddlex',
    PADDLE_PDX_MODEL_SOURCE: 'huggingface', PADDLE_PDX_CACHE_HOME: 'C:\\evil-cache', PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK: 'False',
    FLAGS_use_mkldnn: '0', FLAGS_fraction_of_cpu_memory_to_use: '0.01', OMP_NUM_THREADS: '1', KMP_DUPLICATE_LIB_OK: 'TRUE',
    MKL_NUM_THREADS: '1', CUDA_VISIBLE_DEVICES: '0', HF_ENDPOINT: 'https://evil.example',
    HTTP_PROXY: 'http://evil:8080', HTTPS_PROXY: 'http://evil:8080', ALL_PROXY: 'socks5://evil:1080', NO_PROXY: '*',
    SSL_CERT_FILE: 'C:\\evil\\ca.pem', REQUESTS_CA_BUNDLE: 'C:\\evil\\ca.pem',
    GITHUB_TOKEN: 'ghp_secret', AWS_SECRET_ACCESS_KEY: 'secret', SOME_TOOL_MESSAGING_TOKEN: 'secret',
    LD_PRELOAD: '/evil.so', LD_LIBRARY_PATH: '/evil', DYLD_INSERT_LIBRARIES: '/evil.dylib',
  };
}

const ALLOWED = new Set([...WINDOWS_KEEP, 'PATH', 'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'VIETDOC_MODEL_ROOT']);

test('packaged backend: only allowlisted names reach the server', () => {
  const env = backendEnv(PACKAGED, { sourceEnv: userEnv(), platform: 'win32' });
  for (const name of Object.keys(env)) assert.ok(ALLOWED.has(name), `unexpected variable ${name}`);
  for (const name of ['SystemRoot', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'PROCESSOR_ARCHITECTURE']) {
    assert.equal(env[name], userEnv()[name], name);
  }
});

test('packaged backend: PATH is the bundle folder first, then Windows only (no user entries)', () => {
  const env = backendEnv(PACKAGED, { sourceEnv: userEnv(), platform: 'win32' });
  const dir = 'C:\\Program Files\\VietDoc OCR\\resources\\backend\\vietdoc-backend';
  assert.equal(env.PATH, [dir, `${dir}\\_internal`, 'C:\\WINDOWS\\System32', 'C:\\WINDOWS', 'C:\\WINDOWS\\System32\\Wbem'].join(';'));
  assert.equal(Object.keys(env).filter((k) => k.toUpperCase() === 'PATH').length, 1, 'exactly one PATH key');
  assert.ok(!/Python|nodejs|evil/i.test(env.PATH));
});

test('negative: import, loader, Paddle, proxy, model-source and secret variables are all dropped', () => {
  const env = backendEnv(PACKAGED, { sourceEnv: userEnv(), platform: 'win32' });
  for (const name of ['PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONINSPECT', 'PYTHONVERBOSE', 'PYTHONUTF8',
    'PYTHONIOENCODING', 'NODE_OPTIONS', 'ELECTRON_RUN_AS_NODE', 'VIETDOC_BACKEND_EXE', 'VIETDOC_PYTHON',
    'VIETDOC_PADDLEX_HOME', 'PADDLE_PDX_MODEL_SOURCE', 'PADDLE_PDX_CACHE_HOME', 'FLAGS_use_mkldnn',
    'FLAGS_fraction_of_cpu_memory_to_use', 'OMP_NUM_THREADS', 'KMP_DUPLICATE_LIB_OK', 'MKL_NUM_THREADS',
    'CUDA_VISIBLE_DEVICES', 'HF_ENDPOINT', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'SSL_CERT_FILE',
    'REQUESTS_CA_BUNDLE', 'GITHUB_TOKEN', 'AWS_SECRET_ACCESS_KEY', 'SOME_TOOL_MESSAGING_TOKEN', 'LD_PRELOAD',
    'LD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'Path']) {
    assert.equal(env[name], undefined, `${name} must not reach the backend`);
  }
  for (const value of Object.values(env)) assert.ok(!/evil|secret|ghp_/.test(value), `leaked value ${value}`);
});

test('negative: the model-source check cannot be re-enabled and VIETDOC_MODEL_ROOT only comes from config', () => {
  const none = backendEnv(PACKAGED, { sourceEnv: userEnv(), platform: 'win32' });
  assert.equal(none.PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK, 'True');
  assert.equal(none.VIETDOC_MODEL_ROOT, undefined, 'an environment value alone is ignored');
  const set = backendEnv({ ...PACKAGED, modelRoot: 'D:\\VietDoc\\models' }, { sourceEnv: userEnv(), platform: 'win32' });
  assert.equal(set.VIETDOC_MODEL_ROOT, 'D:\\VietDoc\\models');
});

test('Windows names are matched case-insensitively and written in canonical form', () => {
  const env = backendEnv(PACKAGED, { sourceEnv: { SYSTEMROOT: 'D:\\Win', temp: 'D:\\t', userprofile: 'D:\\u' }, platform: 'win32' });
  assert.equal(env.SystemRoot, 'D:\\Win');
  assert.equal(env.TEMP, 'D:\\t');
  assert.equal(env.USERPROFILE, 'D:\\u');
  assert.ok(env.PATH.endsWith('D:\\Win\\System32;D:\\Win;D:\\Win\\System32\\Wbem'));
});

test('missing Windows variables are not invented; empty values are not copied', () => {
  const env = backendEnv(PACKAGED, { sourceEnv: { TEMP: '' }, platform: 'win32' });
  assert.equal(env.TEMP, undefined);
  assert.ok(env.PATH.includes('C:\\Windows\\System32'), 'falls back to C:\\Windows for the system folders');
});

test('development backend: the project interpreter folder first, then Windows', () => {
  const env = backendEnv(DEV, { sourceEnv: userEnv(), platform: 'win32' });
  assert.equal(env.PATH, ['E:\\repo\\.venv-demo\\Scripts', 'C:\\WINDOWS\\System32', 'C:\\WINDOWS', 'C:\\WINDOWS\\System32\\Wbem'].join(';'));
  assert.equal(env.PYTHONPATH, undefined);
});

test('Linux/macOS development: POSIX essentials and system PATH only', () => {
  const env = backendEnv({ python: '/opt/venv/bin/python', modelRoot: null }, {
    sourceEnv: { HOME: '/home/u', LANG: 'C.UTF-8', PATH: '/home/u/evil:/usr/bin', LD_PRELOAD: '/evil.so', PYTHONPATH: '/evil',
      DYLD_INSERT_LIBRARIES: '/evil.dylib', LD_LIBRARY_PATH: '/opt/hostedtoolcache/Python/3.12/x64/lib' },
    platform: 'linux' });
  assert.deepEqual(Object.keys(env).sort(), ['HOME', 'LANG', 'LD_LIBRARY_PATH', 'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'PATH']);
  assert.equal(env.PATH, '/opt/venv/bin:/usr/local/bin:/usr/bin:/bin');
  assert.equal(env.LD_LIBRARY_PATH, '/opt/hostedtoolcache/Python/3.12/x64/lib', 'a shared CPython needs it on Linux');
});

test('Unicode, spaces and long paths are passed through unchanged', () => {
  const longDir = `C:\\Users\\Nguyễn Văn An\\AppData\\Local\\Temp\\${'thư mục dài '.repeat(25)}`;
  assert.ok(longDir.length > 260);
  const exe = 'D:\\Ứng dụng\\VietDoc OCR (thử)\\resources\\backend\\vietdoc-backend\\vietdoc-backend.exe';
  const env = backendEnv({ backendExe: exe, modelRoot: 'E:\\Mô hình\\VietDoc models' }, {
    sourceEnv: { SystemRoot: 'C:\\WINDOWS', USERPROFILE: 'C:\\Users\\Nguyễn Văn An', TEMP: longDir, TMP: longDir },
    platform: 'win32' });
  assert.equal(env.USERPROFILE, 'C:\\Users\\Nguyễn Văn An');
  assert.equal(env.TEMP, longDir);
  assert.equal(env.VIETDOC_MODEL_ROOT, 'E:\\Mô hình\\VietDoc models');
  assert.ok(env.PATH.startsWith('D:\\Ứng dụng\\VietDoc OCR (thử)\\resources\\backend\\vietdoc-backend;'));
});

test('negative: a folder containing the PATH separator is left out instead of splitting PATH', () => {
  const env = backendEnv({ backendExe: 'C:\\odd;C:\\evil\\backend\\vietdoc-backend.exe', modelRoot: null },
    { sourceEnv: { SystemRoot: 'C:\\WINDOWS' }, platform: 'win32' });
  assert.equal(env.PATH, 'C:\\WINDOWS\\System32;C:\\WINDOWS;C:\\WINDOWS\\System32\\Wbem');
  const posix = backendEnv({ python: '/opt/a:b/bin/python' }, { sourceEnv: {}, platform: 'linux' });
  assert.equal(posix.PATH, '/usr/local/bin:/usr/bin:/bin');
});

test('missing configuration or environment does not throw and adds nothing optional', () => {
  for (const config of [undefined, {}, { modelRoot: null }, { modelRoot: '' }]) {
    const env = backendEnv(config, { sourceEnv: {}, platform: 'win32' });
    assert.deepEqual(Object.keys(env).sort(), ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'PATH']);
    assert.equal(env.PATH, 'C:\\Windows\\System32;C:\\Windows;C:\\Windows\\System32\\Wbem');
  }
});

test('a real child process receives exactly the minimal environment (values round-trip)', () => {
  const { spawnSync } = require('node:child_process');
  const tempKey = process.platform === 'win32' ? 'TEMP' : 'TMPDIR';
  const tempValue = process.platform === 'win32' ? 'C:\\Thư mục tạm\\VietDoc ①' : '/tmp/thư mục tạm ①';
  const sourceEnv = { ...process.env, [tempKey]: tempValue, PYTHONPATH: 'evil', VIETDOC_CANARY: 'leak', HTTPS_PROXY: 'http://evil:1' };
  const env = backendEnv({ python: process.execPath, modelRoot: null }, { sourceEnv });
  const out = spawnSync(process.execPath, ['-e', 'process.stdout.write(JSON.stringify(process.env))'], { env, encoding: 'utf8' });
  assert.equal(out.status, 0, out.stderr);
  const seen = JSON.parse(out.stdout);
  const upper = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k.toUpperCase(), v]));
  const got = upper(seen);
  assert.equal(got[tempKey.toUpperCase()], tempValue);
  for (const name of ['PYTHONPATH', 'VIETDOC_CANARY', 'HTTPS_PROXY']) assert.equal(got[name], undefined, name);
  // Only what backendEnv produced, plus the identity variables libuv adds on Windows.
  const allowed = new Set([...Object.keys(env).map((k) => k.toUpperCase()), 'USERNAME', 'USERDOMAIN', 'LOGONSERVER']);
  for (const name of Object.keys(got)) assert.ok(allowed.has(name), `unexpected variable in the child: ${name}`);
});

test('negative: LD_LIBRARY_PATH is a POSIX development allowance only, never passed on Windows', () => {
  const env = backendEnv(PACKAGED, { sourceEnv: { ...userEnv(), LD_LIBRARY_PATH: 'C:\\evil' }, platform: 'win32' });
  assert.equal(env.LD_LIBRARY_PATH, undefined);
});
