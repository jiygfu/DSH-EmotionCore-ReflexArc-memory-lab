/**
 * EmotionCore runtime supervisor.
 *
 * Starts the local service and maintenance worker when DSH starts, and exposes
 * a small host service so the existing EmotionCore settings page can inspect
 * and control the same two processes. No chat/memory writes here.
 */
import { spawn } from 'node:child_process'
import { closeSync, mkdirSync, openSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { Service } from '@deepseek-ai/cordis'

export const name = 'emotioncore-runtime'
export const inject = []

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..')
const WORKER_PID = path.join(ROOT, 'data', 'emotioncore-worker.pid')

function pidAlive(pid) {
  const n = Number(pid)
  if (!Number.isFinite(n) || n <= 0) return false
  try { process.kill(n, 0); return true } catch { return false }
}

function readPid(file) {
  try { return Number(String(readFileSync(file, 'utf8')).trim()) || 0 } catch { return 0 }
}

class EmotionCoreRuntime extends Service {
  constructor(ctx, config = {}) {
    super(ctx, 'emotioncoreRuntime')
    this.config = config
    this.python = String(config.pythonPath || process.env.SOULCORE_PYTHON || 'python')
    this.port = Number(config.port) || 8765
    this.base = `http://127.0.0.1:${this.port}`
    this.logDir = path.join(ROOT, 'logs')
    this.children = new Map()
    this.desired = { service: true, worker: true }
    this.lastAction = ''
    this.lastError = ''
    mkdirSync(this.logDir, { recursive: true })

    ctx.effect(() => () => {
      for (const child of this.children.values()) {
        try { child.kill() } catch {}
      }
      this.children.clear()
      clearInterval(this.watchdog)
    }, 'emotioncore-runtime: service/worker lifecycle')

    void this.boot()
    this.watchdog = setInterval(() => { void this.reconcile() }, 20000)
  }

  logFd(name) {
    return openSync(path.join(this.logDir, `emotioncore-${name}.out.log`), 'a')
  }

  startChild(role, script, args = []) {
    const out = this.logFd(role)
    try {
      const child = spawn(this.python, [path.join(ROOT, 'plugins', 'emotioncore-service', script), ...args], {
        cwd: ROOT, windowsHide: true, stdio: ['ignore', out, out],
      })
      this.children.set(role, child)
      child.on('error', (e) => { this.lastError = `${role}: ${e.message}` })
      child.on('exit', (code) => {
        if (this.children.get(role) === child) this.children.delete(role)
        if (code && this.desired[role]) this.lastError = `${role} exited ${code}`
      })
      return child
    } finally {
      closeSync(out)
    }
  }

  async healthy() {
    try {
      const ac = new AbortController()
      const t = setTimeout(() => ac.abort(), 800)
      try {
        const res = await fetch(this.base + '/health', { signal: ac.signal })
        return res.ok
      } finally { clearTimeout(t) }
    } catch { return false }
  }

  workerPid() {
    const child = this.children.get('worker')
    if (child?.pid && pidAlive(child.pid)) return child.pid
    const fromFile = readPid(WORKER_PID)
    return pidAlive(fromFile) ? fromFile : 0
  }

  async startService() {
    this.desired.service = true
    if (await this.healthy()) return { ok: true, already: true }
    const child = this.startChild('service', 'server.py', ['--port', String(this.port)])
    this.lastAction = 'service start'
    return { ok: true, pid: child.pid }
  }

  async stopService() {
    this.desired.service = false
    const child = this.children.get('service')
    if (child) {
      try { child.kill() } catch {}
      this.children.delete('service')
    }
    // The service may have been started by an older supervisor instance.
    await this.killPort(this.port)
    this.lastAction = 'service stop'
    return { ok: true }
  }

  async startWorker() {
    this.desired.worker = true
    const pid = this.workerPid()
    if (pid) return { ok: true, already: true, pid }
    const child = this.startChild('worker', 'worker.py', [])
    this.lastAction = 'worker start'
    return { ok: true, pid: child.pid }
  }

  async stopWorker() {
    this.desired.worker = false
    const child = this.children.get('worker')
    if (child) {
      try { child.kill() } catch {}
      this.children.delete('worker')
    }
    const pid = readPid(WORKER_PID)
    if (pidAlive(pid)) await this.killPid(pid)
    this.lastAction = 'worker stop'
    return { ok: true }
  }

  async stopAll() {
    await this.stopWorker()
    await this.stopService()
  }

  async restart(target = 'all') {
    const out = {}
    if (target === 'all' || target === 'service') {
      await this.stopService()
      out.service = await this.startService()
    }
    if (target === 'all' || target === 'worker') {
      await this.stopWorker()
      out.worker = await this.startWorker()
    }
    this.lastAction = `restart ${target}`
    return { ok: true, ...out }
  }

  async killPid(pid) {
    if (!pidAlive(pid)) return
    await new Promise((resolve) => {
      if (process.platform === 'win32') {
        const child = spawn('taskkill', ['/pid', String(pid), '/f', '/t'], { windowsHide: true, stdio: 'ignore' })
        child.on('exit', resolve)
        child.on('error', resolve)
      } else {
        try { process.kill(pid, 'SIGTERM') } catch {}
        resolve()
      }
    })
  }

  async portPid(port) {
    if (process.platform !== 'win32') return 0
    return await new Promise((resolve) => {
      const child = spawn('netstat', ['-ano'], { windowsHide: true })
      let out = ''
      child.stdout.on('data', (b) => { out += String(b) })
      child.on('error', () => resolve(0))
      child.on('exit', () => {
        const line = out.split(/\r?\n/).find((l) => l.includes(`:${port}`) && /LISTENING/i.test(l))
        const fields = String(line || '').trim().split(/\s+/)
        resolve(Number(fields[fields.length - 1]) || 0)
      })
    })
  }

  async killPort(port) {
    const pid = await this.portPid(port)
    if (pid) await this.killPid(pid)
  }

  async status() {
    const serviceHealth = await this.healthy()
    const workerPid = this.workerPid()
    return {
      ok: true,
      enabled: this.config.enabled !== false,
      port: this.port,
      python: this.python,
      service: { healthy: serviceHealth, pid: this.children.get('service')?.pid || 0 },
      worker: { alive: Boolean(workerPid), pid: workerPid || 0 },
      desired: { ...this.desired },
      lastAction: this.lastAction,
      lastError: this.lastError,
    }
  }

  async boot() {
    if (this.config.enabled === false) return
    if (await this.healthy()) {
      console.info('[emotioncore-runtime] service already healthy')
    } else {
      console.info('[emotioncore-runtime] starting service')
      await this.startService()
    }
    console.info('[emotioncore-runtime] starting worker')
    await this.startWorker()
  }

  async reconcile() {
    if (this.config.enabled === false) return
    if (this.desired.service && !(await this.healthy())) {
      console.warn('[emotioncore-runtime] service down; restarting')
      await this.startService()
    }
    if (this.desired.worker && !this.workerPid()) {
      console.warn('[emotioncore-runtime] worker down; restarting')
      await this.startWorker()
    }
  }
}

export function apply(ctx, config = {}) {
  ctx.plugin(EmotionCoreRuntime, config)
}

export { EmotionCoreRuntime }
