import { execFile } from 'node:child_process'
import { appendFile, readFile } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'soul-bridge'
export const inject = ['tools']

const ROOT = process.env.EMOTIONCORE_ROOT
  ? path.resolve(process.env.EMOTIONCORE_ROOT)
  : path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const SETTINGS_PATH = process.env.SOULCORE_SETTINGS_PATH
  || path.join(ROOT, 'data', 'soul-bridge-settings.json')

function overviewEnabled() {
  try {
    const raw = JSON.parse(readFileSync(SETTINGS_PATH, 'utf8'))
    return raw?.memoryOverview === true
  } catch {
    return false
  }
}

async function runtimeConfig(base) {
  try {
    const raw = JSON.parse(await readFile(SETTINGS_PATH, 'utf8'))
    return { ...base, ...(raw && typeof raw === 'object' ? raw : {}) }
  } catch {
    return { ...base }
  }
}

function retrySessionRotation(config) {
  const dshHome = process.env.DSH_HOME || path.join(process.env.USERPROFILE || '.', '.dsh')
  const pending = path.join(dshHome, 'surfcore', 'session-rotate-pending.json')
  return readFile(pending, 'utf8').then(() => new Promise((resolve) => {
    const env = { ...process.env, PYTHONPATH: path.dirname(path.dirname(config.dbPath)) }
    execFile(
      config.pythonPath,
      ['-m', 'soulcore', '--db', config.dbPath, 'rotate-sessions', '--reason', 'retry'],
      { timeout: 30000, windowsHide: true, maxBuffer: 256 * 1024, env },
      () => resolve(true),
    )
  })).catch(() => false)
}

function rotateOverBudget(config) {
  const file = path.join(path.dirname(SETTINGS_PATH), 'session-budget.json')
  return readFile(file, 'utf8').then((raw) => {
    const cfg = JSON.parse(raw)
    if (!cfg || cfg.enabled !== true) return false
    const env = { ...process.env, PYTHONPATH: path.dirname(path.dirname(config.dbPath)) }
    const max = Math.max(1000, Number(cfg.maxCacheHit) || 120000)
    return new Promise((resolve) => {
      execFile(
        config.pythonPath,
        ['-m', 'soulcore', '--db', config.dbPath, 'rotate-over-budget', '--max-cache-hit', String(max)],
        { timeout: 30000, windowsHide: true, maxBuffer: 256 * 1024, env },
        () => resolve(true),
      )
    })
  }).catch(() => false)
}

function refreshBodyState(config) {
  const env = { ...process.env, PYTHONPATH: path.dirname(path.dirname(config.dbPath)) }
  execFile(
    config.pythonPath,
    ['-m', 'soulcore', '--db', config.dbPath, 'body-state'],
    { timeout: 15000, windowsHide: true, maxBuffer: 256 * 1024, env },
    () => {
      // Re-render the injected context so the surface layer sees a fresh,
      // short-lived body hint. This never writes P/memories.
      execFile(
        config.pythonPath,
        ['-m', 'soulcore', '--db', config.dbPath, 'episode-cards'],
        { timeout: 20000, windowsHide: true, maxBuffer: 256 * 1024, env },
        () => {
          execFile(
            config.pythonPath,
            ['-m', 'soulcore', '--db', config.dbPath, 'render-context'],
            { timeout: 20000, windowsHide: true, maxBuffer: 256 * 1024, env },
            () => {},
          )
        },
      )
    },
  )
}

function ensureDayBaseline(config) {
  if (config.baselineOnStart === false) return
  const env = { ...process.env, PYTHONPATH: path.dirname(path.dirname(config.dbPath)) }
  execFile(
    config.pythonPath,
    ['-m', 'soulcore', '--db', config.dbPath, 'day-baseline'],
    { timeout: 15000, windowsHide: true, maxBuffer: 128 * 1024, env },
    () => {
      // 顺手刷新 SurfCore 目的机制读取的当日情绪种子；失败不影响记忆工具。
      execFile(
        config.pythonPath,
        ['-m', 'soulcore', '--db', config.dbPath, 'purpose-seed'],
        { timeout: 15000, windowsHide: true, maxBuffer: 128 * 1024, env },
        () => {
          execFile(
            config.pythonPath,
            ['-m', 'soulcore', '--db', config.dbPath, 'skill-manifest'],
            { timeout: 15000, windowsHide: true, maxBuffer: 128 * 1024, env },
            () => refreshBodyState(config),
          )
        },
      )
    },
  )
}

const SURFCORE_PROBE = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../scripts/surfcore_memory_probe.mjs',
)

function textOf(content) {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content
    .filter((block) => block && block.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
}

function lastUserText(options) {
  const messages = Array.isArray(options?.messages) ? options.messages : []
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i]
    if (message?.role !== 'user') continue
    const text = textOf(message.content).trim()
    if (text) return text
  }
  return ''
}

function normalize(config = {}) {
  return {
    enabled: config.enabled !== false,
    mark: config.mark === true,
    pythonPath: config.pythonPath || process.env.SOULCORE_PYTHON || 'python',
    nodePath: config.nodePath || process.env.SOULCORE_NODE || 'node',
    dbPath: config.dbPath || path.join(ROOT, 'data', 'soulcore.db'),
    logPath: config.logPath || path.join(ROOT, 'data', 'shadow-bridge.jsonl'),
    timeoutMs: Math.max(500, Number(config.timeoutMs) || 4000),
    maxInflight: Math.max(0, Number(config.maxInflight) || 2),
  }
}

function runShadow(text, config) {
  return new Promise((resolve) => {
    const args = [
      '-m', 'soulcore',
      '--db', config.dbPath,
      'shadow',
      '--text', text.slice(0, 8000),
      '--limit', '6',
    ]
    if (config.mark) args.push('--mark')
    execFile(
      config.pythonPath,
      args,
      {
        timeout: config.timeoutMs,
        windowsHide: true,
        maxBuffer: 512 * 1024,
        env: { ...process.env, PYTHONPATH: path.dirname(path.dirname(config.dbPath)) },
      },
      (error, stdout) => {
        if (error) {
          resolve({ ok: false, error: String(error.message || error).slice(0, 240) })
          return
        }
        try {
          resolve({ ok: true, data: JSON.parse(String(stdout || '{}')) })
        } catch (parseError) {
          resolve({ ok: false, error: `bad json: ${String(parseError).slice(0, 160)}` })
        }
      },
    )
  })
}

function runSurfcoreSearch(query, limit, config) {
  return new Promise((resolve) => {
    execFile(
      config.nodePath || 'node',
      [SURFCORE_PROBE, String(query || ''), String(Math.max(1, Math.min(50, Number(limit) || 8)))],
      {
        timeout: Math.max(1000, Number(config.timeoutMs) || 4000),
        windowsHide: true,
        maxBuffer: 1024 * 1024,
        env: { ...process.env },
      },
      (error, stdout, stderr) => {
        if (error) {
          resolve({ ok: false, text: String(stderr || error.message || error).slice(0, 2000) })
          return
        }
        try {
          const data = JSON.parse(String(stdout || '{}'))
          resolve({
            ok: true,
            text: JSON.stringify({ source: 'surfcore_recallFullMemory', ...data }, null, 2),
            resultCount: Number(data.count) || 0,
          })
        } catch (parseError) {
          resolve({ ok: false, text: `builtin recall bad json: ${String(parseError).slice(0, 160)}` })
        }
      },
    )
  })
}

function memoryToolLogPath(config) {
  return path.join(path.dirname(config.dbPath), 'memory-tool-calls.jsonl')
}

async function logMemoryToolCall(config, record) {
  try {
    await appendFile(memoryToolLogPath(config), JSON.stringify(record) + '\n', 'utf8')
  } catch {
    // never affect the tool
  }
}

function runMemory(args, config) {
  return new Promise((resolve) => {
    const cli = [
      '-m', 'soulcore',
      '--db', config.dbPath,
      'memory',
      '--mode', String(args.mode || 'overview'),
      '--limit', String(Math.max(1, Math.min(20, Number(args.limit) || 8))),
    ]
    if (args.query) cli.push('--query', String(args.query).slice(0, 500))
    if (args.person) cli.push('--person', String(args.person).slice(0, 80))
    if (args.scope) cli.push('--scope', String(args.scope).slice(0, 20))
    if (args.date) cli.push('--date', String(args.date).slice(0, 40))
    if (args.from) cli.push('--from', String(args.from).slice(0, 40))
    if (args.to) cli.push('--to', String(args.to).slice(0, 40))
    if (args.question_id) cli.push('--question-id', String(args.question_id).slice(0, 80))
    if (args.answer) cli.push('--answer', String(args.answer).slice(0, 2000))
    if (args.summary) cli.push('--summary', String(args.summary).slice(0, 2000))
    if (args.felt) cli.push('--felt', String(args.felt).slice(0, 300))
    if (args.score && typeof args.score === 'object') {
      cli.push('--score-json', JSON.stringify(args.score))
    }
    execFile(
      config.pythonPath,
      cli,
      {
        timeout: String(args.mode) === 'resolve' ? Math.max(15000, config.timeoutMs) : config.timeoutMs,
        windowsHide: true,
        maxBuffer: 512 * 1024,
        env: { ...process.env, PYTHONPATH: path.dirname(path.dirname(config.dbPath)) },
      },
      (error, stdout, stderr) => {
        if (error) {
          resolve({ ok: false, text: String(stdout || stderr || error.message || error).slice(0, 4000) })
          return
        }
        resolve({ ok: true, text: String(stdout || '').slice(0, 12000) })
      },
    )
  })
}

export function apply(ctx, config = {}) {
  const cfg = normalize(config)
  let inflight = 0
  void runtimeConfig(cfg).then((live) => {
    ensureDayBaseline(live)
    void retrySessionRotation(live)
  }).catch(() => {})

  const modes = overviewEnabled()
    ? ['overview', 'today', 'search', 'person', 'range']
    : ['today', 'search', 'person', 'range']

  ctx.effect(() => ctx.tools.register({
    name: 'soulcore_memory',
    description: '查询本地长期记忆（只读）。today=今天触发；search=关键词检索；person=某人的关系卡与最近记忆；range=按日期/时间查；overview 仅在设置页开启调试后出现。一次最多 8 条；truncated=true 表示只是抽样，不要声称完整记忆，也不要用想象补漏洞。identity_status=legacy_unresolved/self 的旧记录不代表主人。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        mode: {
          type: 'string',
          enum: modes,
          description: '查询模式，默认 today；search 查全局本地库；overview 仅在调试开关开启且重载 soul-bridge 后出现',
        },
        query: { type: 'string', description: 'search 模式的关键词' },
        person: { type: 'string', description: 'person/range 模式的 QQ 号、qq:<id> 或显示名；也可用于 search/today 过滤' },
        scope: { type: 'string', description: '可选范围：group / private / pet / skill' },
        date: { type: 'string', description: 'range 模式：YYYY-MM-DD（本地整天）' },
        from: { type: 'string', description: 'range 模式：起始 ISO 日期/时间' },
        to: { type: 'string', description: 'range 模式：结束 ISO 日期/时间（不含）' },
        limit: { type: 'integer', minimum: 1, maximum: 8, description: '返回条数，默认 5，最多 8' },
      },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: { ok: { type: 'boolean' }, text: { type: 'string' } },
        required: ['ok', 'text'],
      },
      render: (_args, value) => [
        { type: 'text', text: String(value?.text ?? '') },
      ],
    },
    isConcurrencySafe: () => true,
    async execute(args) {
      const live = await runtimeConfig(cfg)
      if (live.memoryTool === false) {
        return { ok: false, text: 'soulcore_memory 已在 SoulCore 设置中关闭。' }
      }
      const raw = args && typeof args === 'object' ? args : {}
      const mode = String(raw.mode || 'today')
      // DSH may pass frozen/sealed args; never mutate them.
      const input = { ...raw, mode }
      if (!modes.includes(mode)) {
        return { ok: false, text: `soulcore_memory 不支持该模式：${mode}（可用：${modes.join('/')}）` }
      }
      if (String(input.mode || '') === 'resolve' && live.memoryResolve !== true) {
        return { ok: false, text: 'resolve 写修正记忆默认关闭；需要 owner 在 EmotionCore 设置页开启“允许模型写修正记忆”。' }
      }
      let result
      let backend = 'local'
      if (String(input.mode || '') === 'surfcore') {
        const q = String(input.query || '').trim()
        if (!q) {
          result = { ok: false, text: 'surfcore 模式需要 query' }
        } else {
          result = await runSurfcoreSearch(q, input.limit, live)
          backend = 'surfcore_builtin'
        }
      } else if (
        String(input.mode || '') === 'search'
        && String(input.query || '').trim()
        && !input.person
        && !input.scope
      ) {
        // SoulCore local DB is the cross-conversation source of truth.
        // SurfCore built-in recall is conversation-scoped; never use it as the
        // default for "do you remember" across private/group chats.
        result = await runMemory(input, live);
        backend = 'local_global';
      } else {
        result = await runMemory(input, live)
      }
      await logMemoryToolCall(live, {
        at: new Date().toISOString(),
        backend,
        mode: String(input.mode || 'overview'),
        query: String(input.query || '').slice(0, 200),
        person: input.person || null,
        scope: input.scope || null,
        date: input.date || null,
        from: input.from || null,
        to: input.to || null,
        ok: result?.ok === true,
        result_count: result?.resultCount ?? null,
      })
      return { ok: result?.ok === true, text: String(result?.text ?? '') }
    },
  }))

  // Body state is ephemeral: refresh every 5 minutes, never persisted as P.
  ctx.effect(() => {
    const timer = setInterval(() => {
      void runtimeConfig(cfg).then((live) => refreshBodyState(live)).catch(() => {})
    }, 5 * 60 * 1000)
    timer.unref?.()
    return () => clearInterval(timer)
  })

  // Fixed-program session budget guard: rotates only over-budget sessions.
  // Disabled by default; data/session-budget.json can opt in.
  ctx.effect(() => {
    const timer = setInterval(() => {
      void runtimeConfig(cfg).then((live) => rotateOverBudget(live)).catch(() => {})
    }, 15 * 60 * 1000)
    timer.unref?.()
    return () => clearInterval(timer)
  })

  const shadow = async (options) => {
    const live = await runtimeConfig(cfg)
    if (!live.enabled || live.shadowEnabled === false) return
    if (inflight >= live.maxInflight) return
    const text = lastUserText(options)
    if (!text) return
    inflight += 1
    try {
      const result = await runShadow(text, live)
      const record = {
        at: new Date().toISOString(),
        provider: options.provider,
        model: options.model,
        text_chars: text.length,
        marked: live.mark,
        result,
      }
      await appendFile(live.logPath, JSON.stringify(record) + '\n', 'utf8')
    } catch {
      // Shadow must never affect the request.
    } finally {
      inflight -= 1
    }
  }

  ctx.on('llm/stream', (options, next) => {
    void shadow(options)
    // LOOP requests are frozen and must not be rewritten. Always pass through.
    return next()
  })
}
