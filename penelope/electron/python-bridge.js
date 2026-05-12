'use strict';

const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const readline = require('node:readline');

// JSON-RPC over stdio. Each line of stdout is one JSON object.
// Requests sent to stdin look like {"id": N, "method": "...", "params": {...}}
// Replies look like {"id": N, "result": ...} or {"id": N, "error": "..."}
// Server-pushed events look like {"event": "...", "data": {...}}.
class PythonBridge {
  constructor({ cwd, onEvent, onLog }) {
    this.cwd = cwd;
    this.onEvent = onEvent || (() => {});
    this.onLog = onLog || (() => {});
    this.proc = null;
    this.nextId = 1;
    this.pending = new Map();
  }

  resolvePython() {
    // In packaged app, prefer bundled venv. In dev, prefer ./.venv/bin/python.
    const candidates = [
      path.join(this.cwd, '.venv', 'bin', 'python'),
      path.join(process.resourcesPath || '', 'python_venv', 'bin', 'python'),
      'python3.11',
      'python3',
    ];
    for (const c of candidates) {
      if (c.startsWith('/') || c.includes(path.sep)) {
        if (fs.existsSync(c)) return c;
      } else {
        return c; // rely on PATH
      }
    }
    return 'python3';
  }

  resolveScript() {
    // Packaged app FIRST — its app.asar.unpacked is the runnable copy.
    // (fs.existsSync returns true for paths inside app.asar too, so we
    // must check the unpacked path first or we silently end up trying
    // to spawn a script that lives inside the asar archive.)
    if (process.resourcesPath) {
      const u = path.join(process.resourcesPath, 'app.asar.unpacked',
                          'python', 'penelope_server.py');
      if (fs.existsSync(u)) return u;
    }
    // Dev mode
    return path.join(this.cwd, 'python', 'penelope_server.py');
  }

  resolveCwd() {
    if (process.resourcesPath) {
      const unpacked = path.join(process.resourcesPath, 'app.asar.unpacked');
      if (fs.existsSync(path.join(unpacked, 'python', 'penelope_server.py'))) {
        return unpacked;
      }
    }
    return this.cwd;
  }

  start() {
    const py = this.resolvePython();
    const script = this.resolveScript();
    const cwd = this.resolveCwd();
    this.onLog(`spawning ${py} ${script} (cwd=${cwd})`);
    this.proc = spawn(py, ['-u', script], {
      cwd,
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    const rl = readline.createInterface({ input: this.proc.stdout });
    rl.on('line', (line) => this.handleLine(line));

    this.proc.stderr.on('data', (buf) => {
      const s = buf.toString();
      s.split('\n').filter(Boolean).forEach((l) => this.onLog(l));
    });

    this.proc.on('exit', (code) => {
      this.onLog(`python exited (${code})`);
      this.onEvent({ event: 'python_exit', data: { code } });
    });
  }

  handleLine(line) {
    line = line.trim();
    if (!line) return;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      this.onLog(`[bad json] ${line}`);
      return;
    }
    if (msg.event) {
      this.onEvent(msg);
      return;
    }
    if (typeof msg.id === 'number') {
      const p = this.pending.get(msg.id);
      if (!p) return;
      this.pending.delete(msg.id);
      if (msg.error) p.reject(new Error(msg.error));
      else p.resolve(msg.result);
    }
  }

  call(method, params) {
    return new Promise((resolve, reject) => {
      if (!this.proc) return reject(new Error('python not running'));
      const id = this.nextId++;
      this.pending.set(id, { resolve, reject });
      this.proc.stdin.write(JSON.stringify({ id, method, params: params || {} }) + '\n');
    });
  }

  stop() {
    if (!this.proc) return;
    try { this.proc.stdin.end(); } catch {}
    try { this.proc.kill('SIGTERM'); } catch {}
    this.proc = null;
  }
}

module.exports = PythonBridge;
