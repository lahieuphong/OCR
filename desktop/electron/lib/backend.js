'use strict';
// The local OCR server owned by the Electron main process: start, talk to it, stop it.
const crypto = require('node:crypto');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const { spawn, execFile } = require('node:child_process');
const { serverArgs } = require('./config');
const { backendEnv } = require('./backend-env');

const READY_TIMEOUT_MS = 120_000;
const GRACEFUL_STOP_MS = 8_000;

class BackendProcess extends EventEmitter {
  constructor(config, { logDir, spawnImpl = spawn, sourceEnv = process.env } = {}) {
    super();
    this.config = config;
    this.logDir = logDir;
    this.spawnImpl = spawnImpl;
    this.sourceEnv = sourceEnv;
    this.child = null;
    this.port = null;
    this.token = null;
    this.ready = null;
    this.stopping = false;
    this.exitInfo = null;
  }

  get origin() {
    return this.port ? `http://127.0.0.1:${this.port}` : null;
  }

  get running() {
    return Boolean(this.child) && this.exitInfo === null;
  }

  start() {
    if (this.child) throw new Error('backend already started');
    this.token = crypto.randomBytes(32).toString('hex');
    fs.mkdirSync(this.logDir, { recursive: true });
    this.logFile = path.join(this.logDir, `backend-${new Date().toISOString().replace(/[:.]/g, '-')}.log`);
    const log = fs.createWriteStream(this.logFile, { flags: 'a' });
    this.log = log;
    this.emit('status', { step: 'starting', message: 'Đang khởi động backend OCR…' });
    // A minimal environment built from scratch (see backend-env.js), never the user's whole environment;
    // VIETDOC_MODEL_ROOT reaches the server only as the validated config value.
    const env = backendEnv(this.config, { sourceEnv: this.sourceEnv });
    const child = this.spawnImpl(this.config.command || this.config.python, serverArgs(this.config), {
      cwd: this.config.repoRoot,
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
      env,
    });
    this.child = child;
    child.stdin.on('error', () => { /* the server already exited; reported through 'exit' */ });
    // The token travels on stdin, not on the command line or in the environment. stdin then stays
    // open: the server stops by itself when it closes, i.e. when this process is gone.
    child.stdin.write(`${this.token}\n`);
    child.stderr.pipe(log);
    this.ready = new Promise((resolve, reject) => {
      let buffer = '';
      const timer = setTimeout(() => reject(new Error('Backend không sẵn sàng sau 120 giây.')), READY_TIMEOUT_MS);
      child.stdout.on('data', (chunk) => {
        log.write(chunk);
        buffer += chunk.toString('utf8');
        let index;
        while ((index = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, index).trim();
          buffer = buffer.slice(index + 1);
          if (line.startsWith('VIETDOC_READY ')) {
            const info = JSON.parse(line.slice('VIETDOC_READY '.length));
            this.port = info.port;
            this.serverPid = info.pid;  // the interpreter itself; a venv python.exe is only a launcher
            clearTimeout(timer);
            resolve(info);
          } else if (line.startsWith('VIETDOC_ERROR ')) {
            clearTimeout(timer);
            reject(new Error(line.slice('VIETDOC_ERROR '.length)));
          }
        }
      });
      child.on('error', (error) => {
        clearTimeout(timer);
        reject(error);
      });
      child.on('exit', (code, signal) => {
        clearTimeout(timer);
        this.exitInfo = { code, signal, expected: this.stopping };
        log.end();
        reject(new Error(`Backend dừng trước khi sẵn sàng (mã ${code}).`));
        this.emit('exit', this.exitInfo);
      });
    });
    return this.ready;
  }

  async request(pathname, { method = 'GET', body, headers = {}, timeoutMs = 600_000 } = {}) {
    if (!this.origin) throw new Error('backend not ready');
    const response = await fetch(this.origin + pathname, {
      method, body, headers: { ...headers, 'X-VietDoc-Token': this.token }, signal: AbortSignal.timeout(timeoutMs),
    });
    const type = response.headers.get('content-type') || '';
    const data = type.includes('application/json') ? await response.json() : await response.text();
    return { status: response.status, data };
  }

  waitForExit(ms) {
    if (!this.child || this.exitInfo) return Promise.resolve(true);
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve(false), ms);
      this.child.once('exit', () => {
        clearTimeout(timer);
        resolve(true);
      });
    });
  }

  // Graceful shutdown first; if the server does not exit in time, end its whole process tree.
  async stop() {
    if (!this.child || this.exitInfo) return { graceful: true, alreadyStopped: true };
    this.stopping = true;
    let graceful = false;
    if (this.port) {
      try {
        await this.request('/__desktop__/shutdown', { method: 'POST', timeoutMs: 2_000 });
        graceful = await this.waitForExit(GRACEFUL_STOP_MS);
      } catch {
        graceful = false;
      }
    }
    if (!graceful) {
      await killTree(this.child.pid);
      await this.waitForExit(3_000);
    }
    return { graceful, exit: this.exitInfo };
  }
}

function killTree(pid) {
  return new Promise((resolve) => {
    if (process.platform === 'win32') {
      execFile('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true }, () => resolve());
    } else {
      try { process.kill(pid, 'SIGKILL'); } catch { /* already gone */ }
      resolve();
    }
  });
}

module.exports = { BackendProcess };
