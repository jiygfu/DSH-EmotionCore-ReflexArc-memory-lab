/**
 * Pre-compaction event-snapshot trigger.
 *
 * This plugin never calls the model. At 80% pressure it sends a bounded packet
 * of recent messages to EmotionCore; the local service makes the single online
 * snapshot request and verifies anchors afterwards.
 */
import { readFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const SETTINGS_PATH = path.join(ROOT, 'data', 'soul-bridge-settings.json')

const DEFAULTS = {
  enabled: true,
  threshold: 0.80,
  hardStop: 0.95,
  cooldownMs: 10 * 60 * 1000,
  maxMessages: 80,
  baseUrl: 'http://127.0.0.1:8765/event_snapshot/request',
  handoffUrl: 'http://127.0.0.1:8765/handoff/compose',
  handoffToAdmin: true,
}

function textOf(message) {
  const content = message && message.content
  if (!Array.isArray(content)) return ''
  const parts = []
  for (const block of content) {
    if (!block || typeof block !== 'object') continue
    if (block.type === 'text' && typeof block.text === 'string') parts.push(block.text)
  }
  return parts.join('\n').trim()
}

async function liveSettings(cfg) {
  try {
    const raw = JSON.parse(await readFile(SETTINGS_PATH, 'utf8'))
    return {
      ...cfg,
      enabled: raw.snapshotEnabled ?? cfg.enabled,
      threshold: Number(raw.snapshotThreshold ?? cfg.threshold),
      hardStop: Number(raw.snapshotHardStop ?? cfg.hardStop),
      cooldownMs: Number(raw.snapshotCooldownMs ?? cfg.cooldownMs),
      maxMessages: Number(raw.snapshotMaxMessages ?? cfg.maxMessages),
    }
  } catch {
    return cfg
  }
}

function pressureOf(agent, meter) {
  try {
    const session = agent && agent.session
    if (!session || !meter || typeof meter.measure !== 'function') return null
    const measured = meter.measure(session)
    const contextWindow = Number(session.requestContext?.()?.contextWindow || 0)
    const used = Number(measured?.totalTokens || measured?.surfaceTokens || 0)
    if (!contextWindow || !used) return null
    return {
      pressureTokens: used,
      surfaceTokens: Number(measured?.surfaceTokens || 0),
      contextWindow,
      ratio: used / contextWindow,
    }
  } catch {
    return null
  }
}

export function apply(ctx, config = {}) {
  const cfg = { ...DEFAULTS, ...config }
  if (cfg.enabled !== true) return
  const meter = ctx.get('tokenMeter')
  if (!meter) return
  const last = new Map()
  let disposed = false

  /** 管理员 QQ：实例配置里的 adminQq（读不到就不发调试副本）。 */
  async function adminQqOf() {
    try {
      const home = process.env.DSH_HOME || path.join(os.homedir(), '.dsh')
      const raw = JSON.parse(await readFile(path.join(home, 'dsh-onebot-qq', 'config.json'), 'utf8'))
      return String(raw?.adminQq || '').trim()
    } catch {
      return ''
    }
  }

  /**
   * 交接便条（B3）：压缩前让本地服务生成一句话，挂到下一次 /context 上（一次性）。
   * 同时把同一条发给管理员 QQ 做调试——走 qqBot 直接出站，不写进会话上下文。
   */
  async function composeHandoff(sid) {
    if (cfg.handoffUrl === false) return
    try {
      const res = await fetch(String(cfg.handoffUrl), {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ chatKey: sid, reason: 'compaction' }),
      })
      const data = await res.json().catch(() => ({}))
      if (!data?.ok || !data?.text) return
      ctx.logger?.info?.(`[context-snapshot] handoff ${data.chars || 0} 字已挂起`)
      if (!cfg.handoffToAdmin) return
      const qqBot = ctx.get('qqBot')
      const admin = await adminQqOf()
      if (!admin || typeof qqBot?.deliver !== 'function') return
      await qqBot.deliver(`private:${admin}`, `【交接·调试】${data.text}`)
      ctx.logger?.info?.('[context-snapshot] handoff 已发管理员 QQ（不进本会话）')
    } catch (err) {
      ctx.logger?.warn?.(`[context-snapshot] handoff failed: ${err?.message || err}`)
    }
  }

  async function maybeSnapshot(agent) {
    const effective = await liveSettings(cfg)
    if (effective.enabled !== true) return
    const p = pressureOf(agent, meter)
    if (!p) return
    if (p.ratio < Number(effective.threshold) || p.ratio > Number(effective.hardStop)) return
    const sid = String(agent?.session?.id || '')
    if (!sid) return
    const now = Date.now()
    const prev = last.get(sid)
    if (prev && now - prev.at < Number(effective.cooldownMs) && p.ratio < prev.ratio + 0.05) return
    last.set(sid, { at: now, ratio: p.ratio })

    const messages = []
    try {
      const all = agent.session.deriveMessages()
      for (const message of all.slice(-Math.max(4, Number(effective.maxMessages) || 40))) {
        const role = String(message?.role || '')
        if (role !== 'user' && role !== 'assistant') continue
        const text = textOf(message)
        if (!text) continue
        messages.push({ role, text: text.slice(0, 4000) })
      }
    } catch {
      return
    }
    if (!messages.length) return
    const body = {
      session_id: sid,
      chat_key: sid,
      captured_at: new Date().toISOString(),
      trigger: 'context_pressure_80',
      pressure: p,
      messages,
    }
    try {
      const res = await fetch(String(cfg.baseUrl), {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      ctx.logger?.info?.(`[context-snapshot] ${res.status} ${data?.snapshot?.snapshot_id || data?.skipped || ''}`)
      // 快照落盘后再挂交接便条：两件事共用同一个"压缩前"时机，但互不阻塞。
      await composeHandoff(String(body.chat_key))
    } catch (err) {
      ctx.logger?.warn?.(`[context-snapshot] request failed: ${err?.message || err}`)
    }
  }

  const off = ctx.on('agent/turn-stopping', ({ agent }) => {
    if (disposed) return
    // Fire-and-forget: never delay or block the turn.
    void maybeSnapshot(agent)
  })
  // Catch pressure that crosses 80% only when the next request is derived,
  // before native compaction at 90%. The packet is copied synchronously before
  // the waterfall continues.
  const offPre = ctx.on('agent/pre-step', (payload, next) => {
    if (!disposed) void maybeSnapshot(payload?.agent)
    return typeof next === 'function' ? next() : undefined
  })
  return () => {
    disposed = true
    if (typeof off === 'function') off()
    if (typeof offPre === 'function') offPre()
    last.clear()
  }
}
