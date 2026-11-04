/**
 * Pre-compaction event-snapshot trigger.
 *
 * This plugin never calls the model. At 80% pressure it sends a bounded packet
 * of recent messages to EmotionCore; the local service makes the single online
 * snapshot request and verifies anchors afterwards.
 */
const DEFAULTS = {
  enabled: true,
  threshold: 0.80,
  hardStop: 0.95,
  cooldownMs: 10 * 60 * 1000,
  maxMessages: 80,
  baseUrl: 'http://127.0.0.1:8765/event_snapshot/request',
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

  async function maybeSnapshot(agent) {
    const p = pressureOf(agent, meter)
    if (!p) return
    if (p.ratio < Number(cfg.threshold) || p.ratio > Number(cfg.hardStop)) return
    const sid = String(agent?.session?.id || '')
    if (!sid) return
    const now = Date.now()
    const prev = last.get(sid)
    if (prev && now - prev.at < Number(cfg.cooldownMs) && p.ratio < prev.ratio + 0.05) return
    last.set(sid, { at: now, ratio: p.ratio })

    const messages = []
    try {
      const all = agent.session.deriveMessages()
      for (const message of all.slice(-Math.max(4, Number(cfg.maxMessages) || 40))) {
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
    } catch (err) {
      ctx.logger?.warn?.(`[context-snapshot] request failed: ${err?.message || err}`)
    }
  }

  const off = ctx.on('agent/turn-stopping', ({ agent }) => {
    if (disposed) return
    // Fire-and-forget: never delay or block the turn.
    void maybeSnapshot(agent)
  })
  return () => {
    disposed = true
    if (typeof off === 'function') off()
    last.clear()
  }
}
