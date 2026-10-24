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

// Windows reports a process killed by the loader or the CPU with an NTSTATUS exit code. The ones a missing
// runtime, a damaged install or an unsupported CPU produce get an explanation the user can act on; the
// detail stays in the backend log.
const WINDOWS_EXIT_REASONS = new Map([
  [0xC0000135, 'thiếu một thư viện DLL cần thiết (STATUS_DLL_NOT_FOUND). Hãy cài lại VietDoc OCR; nếu vẫn lỗi, '
    + 'máy có thể thiếu thành phần Windows (Media Feature Pack trên bản N/KN) hoặc Microsoft Visual C++ Redistributable x64.'],
  [0xC0000139, 'một DLL không có hàm cần thiết (STATUS_ENTRYPOINT_NOT_FOUND): phiên bản Windows hoặc DLL hệ thống không tương thích.'],
  [0xC000007B, 'một DLL sai kiến trúc hoặc bị hỏng (STATUS_INVALID_IMAGE_FORMAT). Hãy cài lại VietDoc OCR (bản x64).'],
  [0xC0000142, 'một DLL không khởi tạo được (STATUS_DLL_INIT_FAILED). Hãy cài lại VietDoc OCR.'],
  [0xC000001D, 'CPU không hỗ trợ tập lệnh mà OCR cần (STATUS_ILLEGAL_INSTRUCTION, thường là AVX).'],
  [0xC0000005, 'lỗi truy cập bộ nhớ (STATUS_ACCESS_VIOLATION).'],
  [0xC0000409, 'tiến trình tự dừng khẩn cấp (STATUS_STACK_BUFFER_OVERRUN / fail-fast).'],
  [0xC0000017, 'không đủ bộ nhớ (STATUS_NO_MEMORY).'],
]);

// "mã <code>" plus, for a known Windows status, what it means. code is null when a signal ended the process.
function describeExit(code) {
  if (code === null || code === undefined) return 'không có mã thoát';
  const status = Number(code) >>> 0;
  const reason = WINDOWS_EXIT_REASONS.get(status);
  const hex = `0x${status.toString(16).toUpperCase().padStart(8, '0')}`;
  return reason ? `mã ${code} = ${hex}: ${reason}` : `mã ${code}`;
}

// A backend executable that cannot be started at all (removed by an antivirus, damaged install).
function describeSpawnError(error) {
  if (error && (error.code === 'ENOENT' || error.code === 'EACCES' || error.code === 'EPERM')) {
    return `Không chạy được backend (${error.code}): tệp backend bị thiếu hoặc bị chặn (ví dụ bởi phần mềm diệt virus). Hãy cài lại VietDoc OCR.`;
  }
  return String((error && error.message) || error);
}

class BackendProcess extends EventEmitter {
  // sourceEnv/platform: the environment and OS the server's environment is built for (tests pass them explicitly).
  constructor(config, { logDir, spawnImpl = spawn, sourceEnv = process.env, platform = process.platform } = {}) {
    super();
    this.config = config;
    this.logDir = logDir;
    this.spawnImpl = spawnImpl;
    this.sourceEnv = sourceEnv;
    this.platform = platform;
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
    const env = backendEnv(this.config, { sourceEnv: this.sourceEnv, platform: this.platform });
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
        reject(new Error(describeSpawnError(error)));
      });
      child.on('exit', (code, signal) => {
        clearTimeout(timer);
        this.exitInfo = { code, signal, expected: this.stopping };
        log.end();
        reject(new Error(`Backend dừng trước khi sẵn sàng (${describeExit(code)}).`));
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

module.exports = { BackendProcess, describeExit, describeSpawnError };
