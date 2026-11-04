// 骰子指令（命令通道）——移植自 surfcore/src/dice-command.js。
//
// 为什么要绕过模型：如果随机数先给模型看，它就有机会"照着这个数编一段"。
// 命令通道直接出结果，模型根本看不到这次掷骰，也就没法作弊；而且这一轮完全零 token。
//
// 支持（够用的最小集）：
//   .r 1d100            → 掷一次
//   .r 3d6+2            → 多骰加值
//   .r 3#1d6            → 重复 3 次
//   .r 1d100<=60        → 比较
//   .ra 侦查 60         → COC 7 版技能检定（大成功/极难/困难/常规/失败/大失败）
//   .ra 60              → 只给数值的检定
//   。r / !r / 掷 / 骰  → 同上（中文输入法常见前缀）

export const DICE_COMMAND_DEFAULTS = Object.freeze({
  enabled: true,
  judgeDefault: '1d100',
  diceDefault: '1d6',
  maxRepeat: 10,
  maxDice: 20,
  maxSides: 1000,
})

export function normalizeDiceCommand(raw = {}) {
  const src = raw && typeof raw === 'object' ? raw : {}
  const num = (v, d, min, max) => {
    const n = Number(v)
    if (!Number.isFinite(n)) return d
    return Math.min(max, Math.max(min, Math.round(n)))
  }
  return {
    enabled: typeof src.enabled === 'boolean' ? src.enabled : DICE_COMMAND_DEFAULTS.enabled,
    judgeDefault: String(src.judgeDefault || DICE_COMMAND_DEFAULTS.judgeDefault),
    diceDefault: String(src.diceDefault || DICE_COMMAND_DEFAULTS.diceDefault),
    maxRepeat: num(src.maxRepeat, DICE_COMMAND_DEFAULTS.maxRepeat, 1, 10),
    maxDice: num(src.maxDice, DICE_COMMAND_DEFAULTS.maxDice, 1, 20),
    maxSides: num(src.maxSides, DICE_COMMAND_DEFAULTS.maxSides, 2, 1000),
  }
}

/** 单个骰子表达式：NdM(+K|-K) 或 NaN；返回 null 表示不是骰子。 */
export function parseDiceExpr(expr, cfg = DICE_COMMAND_DEFAULTS) {
  const s = String(expr ?? '').trim().replace(/\s+/g, '')
  const m = s.match(/^(\d{0,2})[dD](\d{1,4})([+-]\d{1,3})?$/)
  if (!m) return null
  const count = m[1] ? Number(m[1]) : 1
  const sides = Number(m[2])
  const mod = m[3] ? Number(m[3]) : 0
  if (count < 1 || count > cfg.maxDice || sides < 1 || sides > cfg.maxSides) return null
  return { count, sides, mod, text: `${count}d${sides}${mod ? (mod > 0 ? `+${mod}` : mod) : ''}` }
}

/** COC 7 版成功等级。先判大成功，再判大失败，最后按技能值分档。 */
export function cocLevel(roll, skill) {
  if (roll <= 5) return { key: 'crit', label: '大成功' }
  const fumble = skill < 50 ? roll >= 96 : roll === 100
  if (fumble) return { key: 'fumble', label: '大失败' }
  if (roll <= Math.floor(skill / 5)) return { key: 'extreme', label: '极难成功' }
  if (roll <= Math.floor(skill / 2)) return { key: 'hard', label: '困难成功' }
  if (roll <= skill) return { key: 'regular', label: '常规成功' }
  return { key: 'fail', label: '失败' }
}

function rollOnce(spec, rng) {
  const faces = []
  for (let i = 0; i < spec.count; i += 1) faces.push(1 + Math.floor(rng() * spec.sides))
  const sum = faces.reduce((a, b) => a + b, 0) + spec.mod
  return { faces, sum }
}

function stripPrefix(text) {
  return String(text ?? '').trim().replace(/^[.。!！]\s*/, '').trim()
}

/**
 * 识别并执行一条骰子指令。
 * @returns {null | {ok:boolean, reply:string, kind:'roll'|'judge', expr?:string, total?:number}}
 */
export function runDiceCommand(text, options = {}) {
  const cfg = normalizeDiceCommand(options)
  const raw = String(text ?? '').trim()
  // 只有以 . 。 ! ！ 开头才算指令——避免把闲聊里的"骰子"当成命令
  if (!/^[.。!！]/.test(raw)) return null
  const body = stripPrefix(raw)
  if (!body) return null

  // ① 显式前缀：ra/rc/判定/检定、r/roll/掷/骰
  let judge = false
  let rest = ''
  let m = body.match(/^(ra|rc|判定|检定)\s*(.*)$/i)
  if (m) {
    judge = true
    rest = m[2].trim()
  } else {
    m = body.match(/^(r|roll|掷骰|掷|骰子|骰)\s*(.*)$/i)
    if (m) rest = m[2].trim()
  }

  if (!m) return null

  // "掷个骰子" 这种：前缀吃掉"掷"之后只剩"个骰子"，按默认骰处理
  if (!judge && rest && !/[dD]\d/.test(rest) && /骰/.test(rest)) rest = cfg.diceDefault

  if (!rest) {
    if (judge) return null
    rest = cfg.diceDefault
  }

  if (judge) {
    // 技能名 + 数值：侦查 60 / 侦查60 / 60 / 侦查：60
    const sm = rest.match(/^([^\d\s:：]+)?\s*[:：]?\s*(\d{1,3})?$/)
    const name = (sm?.[1] || '').trim()
    const skill = Number(sm?.[2])
    const rng = options.rng ?? Math.random
    const die = rollOnce({ count: 1, sides: 100, mod: 0, text: '1d100' }, rng)
    if (!Number.isFinite(skill) || skill <= 0) {
      return {
        ok: true,
        kind: 'judge',
        expr: '1d100',
        total: die.sum,
        reply: `🎲 ${name || '判定'}：1d100 = ${die.sum}（没给技能值，只报点数）`,
      }
    }
    const lv = cocLevel(die.sum, skill)
    return {
      ok: true,
      kind: 'judge',
      expr: `1d100/${skill}`,
      total: die.sum,
      reply: `🎲 ${name || '判定'}检定：1d100 = ${die.sum} / ${skill} → ${lv.label}（困难 ${Math.floor(skill / 2)} · 极难 ${Math.floor(skill / 5)}）`,
    }
  }

  // 重复：3#1d6
  const rm = rest.match(/^(\d{1,2})#(.+)$/)
  const repeat = rm ? Math.min(cfg.maxRepeat, Math.max(1, Number(rm[1]))) : 1
  let expr = rm ? rm[2].trim() : rest

  // 比较：1d100<=60
  let cmp = null
  const cm = expr.match(/^(.+?)(<=|>=|<|>)(\d{1,3})$/)
  if (cm) {
    expr = cm[1].trim()
    cmp = { op: cm[2], value: Number(cm[3]) }
  }

  const spec = parseDiceExpr(expr, cfg)
  if (!spec) return null

  const rng = options.rng ?? Math.random
  const results = []
  for (let i = 0; i < repeat; i += 1) results.push(rollOnce(spec, rng))

  if (repeat > 1) {
    return {
      ok: true,
      kind: 'roll',
      expr: spec.text,
      total: results[0].sum,
      reply: `🎲 ${spec.text} ×${repeat}：${results.map((r) => r.sum).join(' / ')}`,
    }
  }

  const one = results[0]
  const detail = spec.count > 1
    ? `${spec.text} = [${one.faces.join(',')}]${spec.mod ? (spec.mod > 0 ? `+${spec.mod}` : spec.mod) : ''} = ${one.sum}`
    : `${spec.text} = ${one.sum}`
  if (cmp) {
    const pass = cmp.op === '<=' ? one.sum <= cmp.value
      : cmp.op === '>=' ? one.sum >= cmp.value
        : cmp.op === '<' ? one.sum < cmp.value
          : one.sum > cmp.value
    return {
      ok: true,
      kind: 'roll',
      expr: spec.text,
      total: one.sum,
      reply: `🎲 ${detail} ${cmp.op} ${cmp.value} → ${pass ? '成功' : '失败'}`,
    }
  }
  return { ok: true, kind: 'roll', expr: spec.text, total: one.sum, reply: `🎲 ${detail}` }
}
