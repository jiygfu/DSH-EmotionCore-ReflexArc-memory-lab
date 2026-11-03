/**
 * memory-lab host shell.
 *
 * Starts/stops the read-only memory-lab sidecar when enabled. It never
 * registers QQ tools and never writes soulcore.db.
 */
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'memory-lab'
export const inject = []


const HERE = path.dirname(fileURLToPath(import.meta.url))

export function apply(ctx, config = {}) {
  let child = null
  let stopped = false

  if (config.enabled === true) {
    const python = String(config.pythonPath || process.env.MEMORY_LAB_PYTHON || process.env.SOULCORE_PYTHON || 'python')
    const server = String(config.serverPath || process.env.MEMORY_LAB_SERVER || path.resolve(HERE, '..', 'memory-lab', 'server.py'))
    const port = String(Number(config.port) || 8766)
    try {
      child = spawn(python, [server, '--host', '127.0.0.1', '--port', port], {
        cwd: path.resolve(HERE, '..', '..'),
        windowsHide: true,
        stdio: 'ignore',
      })
      child.on('error', (e) => console.warn(`[memory-lab] spawn failed: ${e.message}`))
      child.on('exit', (code) => {
        if (!stopped) console.warn(`[memory-lab] sidecar exited: ${code}`)
        child = null
      })
      console.info(`[memory-lab] started ${python} ${server} :${port}`)
    } catch (e) {
      console.warn(`[memory-lab] start failed: ${e.message}`)
    }
  }

  const stop = () => {
    if (stopped) return
    stopped = true
    if (child) {
      try { child.kill() } catch {}
      child = null
    }
  }
  // Register with the plugin fiber. Returning a bare cleanup function is not
  // enough for this Host: HMR/disable must see a registered disposer.
  if (typeof ctx?.effect === 'function') {
    ctx.effect(() => stop, 'memory-lab: sidecar lifecycle')
  } else if (typeof ctx?.on === 'function') {
    ctx.on('dispose', stop)
  }
}
