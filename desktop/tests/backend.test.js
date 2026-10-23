'use strict';
// BackendProcess against a fake child process (the real server is covered by the Python tests and the
// Electron smoke test). No real process is started or killed here.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter, once } = require('node:events');
const { PassThrough } = require('node:stream');
const { BackendProcess } = require('../electron/lib/backend');

function fakeSpawn() {
  const calls = [];
  const spawnImpl = (command, args, options) => {
    const child = new EventEmitter();
    child.stdin = new PassThrough();
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    child.pid = 999999;
    child.written = '';
    child.stdin.on('data', (d) => { child.written += d.toString(); });
    calls.push({ command, args, options, child });
    return child;
  };
  return { calls, spawnImpl };
}

function makeBackend(t) {
  const logDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-desktop-backend-'));
  const config = { python: 'C:\\py\\python.exe', repoRoot: 'C:\\repo', serverScript: 'C:\\repo\\desktop\\python\\s.py',
    frontendDist: 'C:\\repo\\dist', modelLock: 'C:\\repo\\desktop\\model_lock.json', paddlexHome: 'C:\\px' };
  const fake = fakeSpawn();
  const backend = new BackendProcess(config, { logDir, spawnImpl: fake.spawnImpl });
  backend.on('error', () => {});
  t.after(async () => {
    // Let the fake child "exit" and the log stream close before removing its folder.
    if (fake.calls[0] && !backend.exitInfo) fake.calls[0].child.emit('exit', 0, null);
    if (backend.log && !backend.log.closed) await once(backend.log, 'close');
    fs.rmSync(logDir, { recursive: true, force: true });
  });
  return { backend, fake, logDir };
}

test('token goes over stdin, never argv or env; READY sets the loopback origin', async (t) => {
  const { backend, fake } = makeBackend(t);
  const ready = backend.start();
  const { args, options, child } = fake.calls[0];
  assert.match(backend.token, /^[0-9a-f]{64}$/);
  assert.ok(!args.join(' ').includes(backend.token));
  assert.ok(!Object.values(options.env).includes(backend.token));
  assert.equal(options.cwd, 'C:\\repo');
  assert.equal(options.windowsHide, true);
  assert.equal(options.env.PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK, 'True');
  child.stdout.write('INFO: noise\nVIETDOC_READY {"port": 51234, "pid": 7, "ocr_allowed": false}\n');
  const info = await ready;
  assert.equal(info.port, 51234);
  assert.equal(backend.origin, 'http://127.0.0.1:51234');
  assert.equal(child.written, `${backend.token}\n`);
  assert.equal(backend.running, true);
  child.emit('exit', 0, null);
});

test('the spawned server gets the minimal environment, not the parent environment', async (t) => {
  const logDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vietdoc-desktop-backend-'));
  const fake = fakeSpawn();
  const sourceEnv = { SystemRoot: 'C:\\WINDOWS', TEMP: 'C:\\t', PYTHONPATH: 'C:\\evil', NODE_OPTIONS: '--inspect',
    PADDLE_PDX_MODEL_SOURCE: 'huggingface', VIETDOC_MODEL_ROOT: 'C:\\attacker', GITHUB_TOKEN: 'ghp_secret' };
  const backend = new BackendProcess({ backendExe: 'C:\\app\\resources\\backend\\vietdoc-backend\\vietdoc-backend.exe',
    command: 'C:\\app\\resources\\backend\\vietdoc-backend\\vietdoc-backend.exe', repoRoot: 'C:\\app\\resources',
    frontendDist: 'C:\\app\\resources\\frontend', modelLock: 'C:\\app\\resources\\model_lock.json', paddlexHome: 'C:\\px',
    modelRoot: 'D:\\models' }, { logDir, spawnImpl: fake.spawnImpl, sourceEnv });
  backend.on('error', () => {});
  t.after(async () => {
    if (fake.calls[0] && !backend.exitInfo) fake.calls[0].child.emit('exit', 0, null);
    if (backend.log && !backend.log.closed) await once(backend.log, 'close');
    fs.rmSync(logDir, { recursive: true, force: true });
  });
  backend.start().catch(() => {});
  const { env } = fake.calls[0].options;
  for (const name of ['PYTHONPATH', 'NODE_OPTIONS', 'PADDLE_PDX_MODEL_SOURCE', 'GITHUB_TOKEN']) assert.equal(env[name], undefined, name);
  assert.equal(env.VIETDOC_MODEL_ROOT, 'D:\\models', 'the validated config value, not the environment value');
  assert.equal(env.TEMP, 'C:\\t');
  assert.equal(env.PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK, 'True');
  assert.ok(!Object.values(env).includes(backend.token));
});

test('VIETDOC_ERROR rejects start with the server message', async (t) => {
  const { backend, fake } = makeBackend(t);
  const ready = backend.start();
  fake.calls[0].child.stdout.write('VIETDOC_ERROR Thiếu frontend dist\n');
  await assert.rejects(ready, /Thiếu frontend dist/);
});

test('an early exit rejects start and is reported as unexpected', async (t) => {
  const { backend, fake } = makeBackend(t);
  const exits = [];
  backend.on('exit', (info) => exits.push(info));
  const ready = backend.start();
  fake.calls[0].child.emit('exit', 3, null);
  await assert.rejects(ready, /mã 3/);
  assert.deepEqual(exits, [{ code: 3, signal: null, expected: false }]);
  assert.equal(backend.running, false);
});

test('stderr and stdout go to the log file; start twice is refused', async (t) => {
  const { backend, fake } = makeBackend(t);
  const ready = backend.start();
  const { child } = fake.calls[0];
  child.stderr.write('Traceback: boom\n');
  child.stdout.write('VIETDOC_READY {"port": 1, "pid": 2}\n');
  await ready;
  assert.throws(() => backend.start(), /already started/);
  child.emit('exit', 0, null);
  await new Promise((r) => setTimeout(r, 50));
  const log = fs.readFileSync(backend.logFile, 'utf8');
  assert.match(log, /Traceback: boom/);
  assert.match(log, /VIETDOC_READY/);
  assert.ok(!log.includes(backend.token));
});

test('stop on an already stopped backend does nothing', async (t) => {
  const { backend } = makeBackend(t);
  assert.deepEqual(await backend.stop(), { graceful: true, alreadyStopped: true });
});
