/**
 * Live context accounting for the QQ agent line.
 *
 * Reads the DSH session log of the QQ workspace (multi-frame zstd JSONL),
 * rebuilds per-request token usage from the recorded `usage` blocks, and
 * estimates what the last request was made of (scaffolding vs human text).
 *
 * Read-only: never writes a session, never calls a model.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import zlib from 'node:zlib'

const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
const HOME = process.env.USERPROFILE || os.homedir()
const DSH_HOME = process.env.DSH_HOME || path.join(HOME, '.dsh')
const SESSIONS_ROOT = path.join(DSH_HOME, 'sessions')

/** file -> { mtimeMs, size, summary } */
const summaryCache = new Map()
let thresholdsCache = { at: 0, value: null }

function decompressFrames(buf) {
  const chunks = []
  let off = 0
  for (;;) {
    const start = buf.indexOf(ZSTD_MAGIC, off)
    if (start < 0) break
    const next = buf.indexOf(ZSTD_MAGIC, start + 4)
    const end = next < 0 ? buf.length : next
    try {
      chunks.push(zlib.zstdDecompressSync(buf.subarray(start, end)))
    } catch {
      // A torn trailing frame is normal while the host is writing.
    }
    off = end > start ? end : start + 4
  }
  return Buffer.concat(chunks)
}

function readRecords(file) {
  const records = []
  for (const line of decompressFrames(fs.readFileSync(file)).toString('utf8').split(/\r?\n/)) {
    if (!line.trim()) continue
    try { records.push(JSON.parse(line)) } catch {}
  }
  return records
}

function textOf(content) {
  if (!Array.isArray(content)) return ''
  const parts = []
  for (const block of content) {
    if (!block || typeof block !== 'object') continue
    if (typeof block.text === 'string') parts.push(block.text)
    else if (block.type === 'tool-call') parts.push(block.arguments || '')
  }
  return parts.join('\n')
}

function humanOf(text) {
  const capIdx = text.indexOf('[本地QQ能力]')
  if (capIdx < 0) return text
  return text.slice(0, capIdx)
    .replace(/^\[QQ线[^\]]*\]\s*/, '')
    .replace(/^\[本条消息ID[^\]]*\]\s*/, '')
    .replace(/^\[QQ会话[^\]]*\]\s*/, '')
}

function summarise(file) {
  const stat = fs.statSync(file)
  const cached = summaryCache.get(file)
  if (cached && cached.mtimeMs === stat.mtimeMs && cached.size === stat.size) return cached.summary

  let turn = 0
  let contextWindow = 0
  let model = ''
  let systemChars = 0
  let toolsChars = 0
  let userChars = 0
  let scaffoldChars = 0
  let assistantChars = 0
  let reasoningChars = 0
  let toolResultChars = 0
  const requests = []

  for (const record of readRecords(file)) {
    const data = record.data || {}
    if (record.type === 'turn/start') turn = data.turn || turn
    if (record.type === 'request/context') {
      contextWindow = data.contextWindow || contextWindow
      model = data.model || model
    }
    if (record.type === 'request/header' && !toolsChars) {
      toolsChars = JSON.stringify(data.header?.tools || []).length
    }
    if (record.type === 'system/message' && !systemChars) systemChars = textOf(data.message?.content).length
    if (record.type === 'user/message' || record.type === 'developer/message') {
      const text = textOf(data.content || data.message?.content)
      userChars += text.length
      scaffoldChars += Math.max(0, text.length - humanOf(text).length)
    }
    if (record.type === 'assistant/message') {
      for (const block of data.message?.content || []) {
        if (block?.type === 'reasoning') reasoningChars += (block.text || '').length
        else if (block?.type === 'text') assistantChars += (block.text || '').length
        else if (block?.type === 'tool-call') assistantChars += (block.arguments || '').length
      }
      const usage = data.usage || {}
      requests.push({
        turn,
        step: data.step,
        time: record.time,
        input: usage.inputTokens || 0,
        cacheRead: usage.cacheReadTokens || 0,
        output: usage.outputTokens || 0,
        prompt: (usage.inputTokens || 0) + (usage.cacheReadTokens || 0),
      })
    }
    if (record.type === 'tool/result') toolResultChars += textOf(data.message?.content).length
  }

  const last = requests[requests.length - 1] || null
  const totalChars = userChars + assistantChars + reasoningChars + toolResultChars + systemChars + toolsChars
  const tokensPerChar = last && totalChars ? last.prompt / totalChars : 0
  const tokens = chars => Math.round(chars * tokensPerChar)

  const summary = {
    file,
    sessionId: path.basename(path.dirname(file)).replace(/^session-/, ''),
    model,
    contextWindow,
    turns: turn || requests.length,
    requests: requests.length,
    updatedAt: last?.time || stat.mtimeMs,
    last,
    requestList: requests.slice(-12),
    maxPrompt: requests.reduce((max, r) => Math.max(max, r.prompt), 0),
    sumPrompt: requests.reduce((sum, r) => sum + r.prompt, 0),
    sumInput: requests.reduce((sum, r) => sum + r.input, 0),
    sumCache: requests.reduce((sum, r) => sum + r.cacheRead, 0),
    sumOutput: requests.reduce((sum, r) => sum + r.output, 0),
    chars: {
      scaffold: scaffoldChars,
      human: Math.max(0, userChars - scaffoldChars),
      assistant: assistantChars,
      reasoning: reasoningChars,
      toolResult: toolResultChars,
      systemTools: systemChars + toolsChars,
    },
    tokens: {
      scaffold: tokens(scaffoldChars),
      human: tokens(Math.max(0, userChars - scaffoldChars)),
      assistant: tokens(assistantChars),
      reasoning: tokens(reasoningChars),
      toolResult: tokens(toolResultChars),
      systemTools: tokens(systemChars + toolsChars),
    },
  }

  summaryCache.set(file, { mtimeMs: stat.mtimeMs, size: stat.size, summary })
  if (summaryCache.size > 16) {
    const oldest = [...summaryCache.entries()].sort((a, b) => a[1].mtimeMs - b[1].mtimeMs)[0]
    if (oldest) summaryCache.delete(oldest[0])
  }
  return summary
}

function findLatestSession() {
  const override = process.env.DSH_QQ_SESSION_DIR
  const dirs = override
    ? [override]
    : (fs.existsSync(SESSIONS_ROOT) ? fs.readdirSync(SESSIONS_ROOT) : [])
        .filter(name => /onebot-qq/i.test(name))
        .map(name => path.join(SESSIONS_ROOT, name))
  let best = null
  for (const dir of dirs) {
    if (!fs.existsSync(dir)) continue
    for (const entry of fs.readdirSync(dir)) {
      const file = path.join(dir, entry, 'session.v4.jsonl.zstd')
      if (!fs.existsSync(file)) continue
      const stat = fs.statSync(file)
      if (!best || stat.mtimeMs > best.mtimeMs) best = { file, mtimeMs: stat.mtimeMs }
    }
  }
  return best?.file || null
}

function readThresholds() {
  if (thresholdsCache.value && Date.now() - thresholdsCache.at < 60_000) return thresholdsCache.value
  const value = { snapshot: 0.8, compaction: 0.9 }
  try {
    const patch = path.join(DSH_HOME, 'profiles', 'desktop', 'node_modules', '@local',
      'context-snapshot-trigger', 'cordis.patch.yml')
    const match = fs.readFileSync(patch, 'utf8').match(/threshold:\s*([\d.]+)/)
    if (match) value.snapshot = Number(match[1])
  } catch {}
  try {
    const patch = path.join(DSH_HOME, 'profiles', 'desktop', 'cordis.patch.yml')
    const match = fs.readFileSync(patch, 'utf8').match(/thresholdRatio:\s*([\d.]+)/)
    if (match) value.compaction = Number(match[1])
  } catch {}
  thresholdsCache = { at: Date.now(), value }
  return value
}

export function contextStats() {
  const file = findLatestSession()
  if (!file) return { ok: false, error: '还没有 QQ 线会话记录' }
  try {
    const summary = summarise(file)
    const thresholds = readThresholds()
    const window = summary.contextWindow || 0
    const last = summary.last
    const prompt = last?.prompt || 0
    const growth = summary.turns ? Math.round(prompt / summary.turns) : 0
    const perTurn = summary.requests ? Math.round(summary.sumPrompt / summary.requests) : 0
    return {
      ok: true,
      sessionId: summary.sessionId,
      model: summary.model,
      contextWindow: window,
      turns: summary.turns,
      requests: summary.requests,
      updatedAt: summary.updatedAt,
      last,
      pressure: window ? prompt / window : null,
      growthPerTurn: growth,
      avgPrompt: perTurn,
      maxPrompt: summary.maxPrompt,
      totals: {
        prompt: summary.sumPrompt,
        input: summary.sumInput,
        cache: summary.sumCache,
        output: summary.sumOutput,
        cacheHitRate: summary.sumPrompt ? summary.sumCache / summary.sumPrompt : null,
      },
      tokens: summary.tokens,
      chars: summary.chars,
      share: prompt ? {
        scaffold: summary.tokens.scaffold / prompt,
        human: summary.tokens.human / prompt,
        assistant: summary.tokens.assistant / prompt,
        reasoning: summary.tokens.reasoning / prompt,
        toolResult: summary.tokens.toolResult / prompt,
        systemTools: summary.tokens.systemTools / prompt,
      } : null,
      thresholds: {
        snapshot: thresholds.snapshot,
        compaction: thresholds.compaction,
        snapshotTokens: Math.round(window * thresholds.snapshot),
        compactionTokens: Math.round(window * thresholds.compaction),
        turnsToSnapshot: growth > 0 ? Math.max(0, Math.ceil((window * thresholds.snapshot - prompt) / growth)) : null,
      },
      recent: summary.requestList,
      at: Date.now(),
    }
  } catch (error) {
    return { ok: false, error: String(error?.message || error) }
  }
}
