import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..')
const PERSONA_PATH = path.join(ROOT, 'config', 'emotioncore-persona.md')
const AGENTS_PATH = path.join(process.env.USERPROFILE || '', '.dsh', 'dsh-onebot-qq', 'workspace', 'AGENTS.local.md')
const OLLAMA = 'http://127.0.0.1:11434'
const LAB = 'http://127.0.0.1:8766'
const MODEL = process.env.LOCAL_CHAT_MODEL || 'deepseek-v4-pro-qwen3.5-9b-heretic:iq2_xxs'
const PORT = Number(process.env.PORT || 8790)
const NUM_CTX = 32768
const MAX_HISTORY_CHARS = 24000
const CHAT_LOG = path.join(HERE, 'chat-log.jsonl')

const RECALL_TRIGGER = /(上次|那次|之前|后来|记得|还记得|那个|那件事|后来呢|记忆|以前)/

function personaText() {
  try { return fs.readFileSync(PERSONA_PATH, 'utf8').trim() }
  catch { return fs.readFileSync(AGENTS_PATH, 'utf8').trim() }
}

function clip(s, n) {
  const t = String(s ?? '').replace(/\s+/g, ' ').trim()
  return t.length > n ? t.slice(0, n) + '…' : t
}

function appendLog(entry) {
  try {
    fs.appendFileSync(CHAT_LOG, JSON.stringify({ at: new Date().toISOString(), ...entry }) + '\n', 'utf8')
  } catch {}
}

function trimHistory(messages) {
  const out = []
  let used = 0
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i]
    const text = clip(m.text, 4000)
    const cost = text.length + 32
    if (out.length && used + cost > MAX_HISTORY_CHARS) break
    out.unshift({ role: m.role, content: text })
    used += cost
  }
  return out
}

async function recall(query) {
  if (!query || query.length < 4) return []
  try {
    const ac = new AbortController()
    const timer = setTimeout(() => ac.abort(), 1200)
    const res = await fetch(`${LAB}/recall?q=${encodeURIComponent(query)}&limit=2`, { signal: ac.signal })
    clearTimeout(timer)
    if (!res.ok) return []
    const data = await res.json()
    return (Array.isArray(data.items) ? data.items : [])
      .filter((x) => x?.text)
      .slice(0, 2)
      .map((x) => ({
        when: x.when || '',
        who: x.who || x.speaker || '某人',
        where: x.where || '',
        stance: x.stance || '事实',
        text: clip(x.text, 160),
      }))
  } catch {
    return []
  }
}

function memoryBlock(items) {
  if (!items.length) return ''
  const lines = items.map((x) =>
    `- [记忆联想·实验｜${x.when || '某时'}·${x.who}·${x.where || '某处'}·${x.stance}] ${x.text}`)
  return [
    '[本地记忆联想]',
    ...lines,
    '这些是本地记忆联想，不是全知记忆；只用于自然接话，不要逐条复述，不确定就承认。',
  ].join('\n')
}

async function prepareChat(messages, memoryEnabled) {
  const persona = personaText()
  const lastUser = [...messages].reverse().find((m) => m.role === 'user')?.text || ''
  const items = memoryEnabled && RECALL_TRIGGER.test(lastUser) ? await recall(lastUser) : []
  const system = [persona, memoryBlock(items)].filter(Boolean).join('\n\n')
  return {
    items,
    system,
    history: trimHistory(messages),
  }
}

function ollamaPayload(prepared, stream) {
  return {
    model: MODEL,
    messages: [
      { role: 'system', content: prepared.system },
      ...prepared.history.map((m) => ({ role: m.role, content: m.content })),
    ],
    stream,
    think: false,
    keep_alive: '5m',
    options: {
      num_ctx: NUM_CTX,
      temperature: 0.55,
      num_predict: 256,
      top_p: 0.9,
      top_k: 40,
      repeat_penalty: 1.1,
      repeat_last_n: 128,
    },
  }
}

async function chat(messages, memoryEnabled) {
  const prepared = await prepareChat(messages, memoryEnabled)
  const ac = new AbortController()
  const timer = setTimeout(() => ac.abort(), 180000)
  const started = Date.now()
  try {
    const res = await fetch(`${OLLAMA}/api/chat`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(ollamaPayload(prepared, false)),
      signal: ac.signal,
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok || data?.error) throw new Error(data?.error || `Ollama HTTP ${res.status}`)
    const content = String(data?.message?.content || '').trim()
    const evalCount = Number(data?.eval_count || 0)
    const evalNs = Number(data?.eval_duration || 0)
    const result = {
      ok: true,
      reply: content || '（模型返回了空内容）',
      memory: prepared.items,
      systemPreview: prepared.system.slice(0, 1200),
      elapsedMs: Date.now() - started,
      loadMs: data?.load_duration ? Math.round(data.load_duration / 1e6) : null,
      evalCount,
      tokPerSec: evalCount && evalNs ? Number((evalCount / (evalNs / 1e9)).toFixed(2)) : null,
      numCtx: NUM_CTX,
    }
    appendLog({ stream: false, messages, memory: prepared.items, reply: result.reply, elapsedMs: result.elapsedMs, tokPerSec: result.tokPerSec })
    return result
  } finally {
    clearTimeout(timer)
  }
}

async function streamChat(res, messages, memoryEnabled) {
  const prepared = await prepareChat(messages, memoryEnabled)
  const ac = new AbortController()
  const timer = setTimeout(() => ac.abort(), 180000)
  const started = Date.now()
  res.writeHead(200, {
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-cache',
    connection: 'keep-alive',
  })
  const send = (obj) => res.write(`data: ${JSON.stringify(obj)}\n\n`)
  send({ type: 'meta', memory: prepared.items, systemPreview: prepared.system.slice(0, 1200), numCtx: NUM_CTX })
  let content = ''
  let evalCount = 0
  let evalNs = 0
  try {
    const upstream = await fetch(`${OLLAMA}/api/chat`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(ollamaPayload(prepared, true)),
      signal: ac.signal,
    })
    if (!upstream.ok) throw new Error(`Ollama HTTP ${upstream.status}`)
    const reader = upstream.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.trim()) continue
        let obj
        try { obj = JSON.parse(line) } catch { continue }
        if (obj.error) throw new Error(obj.error)
        const delta = String(obj?.message?.content || '')
        if (delta) {
          content += delta
          send({ type: 'delta', text: delta })
        }
        if (obj?.done) {
          evalCount = Number(obj.eval_count || 0)
          evalNs = Number(obj.eval_duration || 0)
        }
      }
    }
    const reply = content.trim() || '（模型返回了空内容）'
    const elapsedMs = Date.now() - started
    const tokPerSec = evalCount && evalNs ? Number((evalCount / (evalNs / 1e9)).toFixed(2)) : null
    appendLog({ stream: true, messages, memory: prepared.items, reply, elapsedMs, tokPerSec })
    send({
      type: 'done',
      reply,
      elapsedMs,
      evalCount,
      tokPerSec,
      numCtx: NUM_CTX,
    })
  } catch (e) {
    send({ type: 'error', error: String(e?.message || e) })
  } finally {
    clearTimeout(timer)
    res.end()
  }
}

function json(res, code, data) {
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(data))
}

async function body(req) {
  let raw = ''
  for await (const chunk of req) raw += chunk
  return raw ? JSON.parse(raw) : {}
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === 'GET' && (req.url === '/' || req.url === '/index.html')) {
      const html = fs.readFileSync(path.join(HERE, 'index.html'), 'utf8')
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
      return res.end(html)
    }
    if (req.method === 'GET' && req.url === '/api/status') {
      return json(res, 200, {
        ok: true, model: MODEL, numCtx: NUM_CTX,
        personaChars: personaText().length,
      })
    }
    if (req.method === 'POST' && req.url === '/api/chat') {
      const data = await body(req)
      const messages = Array.isArray(data.messages) ? data.messages : []
      if (!messages.length) return json(res, 400, { ok: false, error: 'messages required' })
      if (data.stream === true) return streamChat(res, messages, data.memory !== false)
      const result = await chat(messages, data.memory !== false)
      return json(res, 200, result)
    }
    json(res, 404, { ok: false, error: 'not found' })
  } catch (e) {
    json(res, 500, { ok: false, error: String(e?.message || e) })
  }
})

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[local-chat-32k] http://127.0.0.1:${PORT}  model=${MODEL}  ctx=${NUM_CTX}`)
})
