// 反射弧（Reflex Arc）：入站预处理与"我的潜意识联想到"渲染。
//
// 边界（与 qq-master-plan.md 对齐）：
//   · R0 结构解析：纯字符串/对象判断，0 模型、0 延迟；
//   · R1 取数与摘要由调用方（桥接）去做，本模块只负责"要不要"和"怎么落成一句话"；
//   · R2 渲染：第一人称 + 只配感知动词（瞄到/看到），外部原文必须用「」包起来；
//   · 默认静默：没内容、被判定为祈使、超预算 → 返回空字符串，绝不占位。
//
// 安全红线（M2 / §10.1）：
//   外部内容一旦被改写成"我觉得/应该…"这种判断句，就等于把提示注入洗成了她自己的想法。
//   所以这里对每一条联想都做祈使句检测，命中就**整条丢弃**（不是转义、不是改写）。

export const REFLEX_DEFAULTS = Object.freeze({
  enabled: false,        // 默认关：M2 先落代码，验证过再打开
  mode: 'assist',        // observe | assist | auto
  maxChars: 400,         // 整块上限（约 400 token 级）
  maxItems: 4,
  minChars: 6,           // 太短的"联想"没有信息量，直接丢
});

/** 配置归一：未知值一律回默认，缺字段不报错。 */
export function normalizeReflexConfig(raw = {}) {
  const src = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
  const num = (v, fallback, min, max) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return fallback;
    return Math.min(max, Math.max(min, Math.round(n)));
  };
  const mode = ['observe', 'assist', 'auto'].includes(src.mode) ? src.mode : REFLEX_DEFAULTS.mode;
  return {
    enabled: typeof src.enabled === 'boolean' ? src.enabled : REFLEX_DEFAULTS.enabled,
    mode,
    maxChars: num(src.maxChars, REFLEX_DEFAULTS.maxChars, 80, 2000),
    maxItems: num(src.maxItems, REFLEX_DEFAULTS.maxItems, 1, 10),
    minChars: num(src.minChars, REFLEX_DEFAULTS.minChars, 0, 200),
  };
}

// 祈使 / 指令性措辞：出现在外部内容里，说明这条不能当"我想到的"往上递。
const IMPERATIVE_RE = /(请|别|不要|必须|立刻|马上|赶紧|忽略(之前|以上|前面|一切)|执行|运行|删除|发给我|告诉我|转发|点击|扫码|下载|安装|把.*(发|改|删))/;

/**
 * 一条外部内容能不能进"我的潜意识联想到"。
 * @returns {{ok:boolean, reason?:string}}
 */
export function screenClaim(text) {
  const t = String(text ?? '').trim();
  if (!t) return { ok: false, reason: 'empty' };
  if (IMPERATIVE_RE.test(t)) return { ok: false, reason: 'imperative' };
  if (/^[\[【(（]?\s*(system|assistant|user)\s*[\]】)）]?:/i.test(t)) return { ok: false, reason: 'role-marker' };
  return { ok: true };
}

// 骰子意图：显式写法优先，其次 COC 判定（过/检定），最后是口语里要个随机数。
const EXPLICIT_DICE_RE = /(\d{1,2})\s*[dD]\s*(\d{1,4})(\s*[+-]\s*\d{1,3})?/;
const BARE_DICE_RE = /(?<![a-zA-Z])[dD]\s*(\d{1,4})(\s*[+-]\s*\d{1,3})?/;
const COC_SKILLS = '侦查|观察|聆听|心理学|图书馆|潜行|闪避|格斗|射击|话术|说服|魅惑|医学|急救|锁匠|驾驶|会计|法律|历史|神秘学|克苏鲁|理智|san';
const JUDGE_RE = new RegExp(`(判定|检定|过个?(?:${COC_SKILLS})|骰判定)`, 'i');
// 只认“丢/掷/投/摇/随便/试试 + 骰”这种行动，不认“骰子互动的记忆”这种提及。
const DICE_ACTION_RE = /(?:丢|掷|投|摇|roll|随机|随便|来一?个|来个|试试).{0,16}(?:骰子|骰|d\d)|(?:骰子|骰).{0,16}(?:丢|掷|投|摇|roll|试试|一下)/i;

/**
 * 这句话是不是在要一个随机数。
 * @returns {null | {expr:string, kind:'explicit'|'judge'|'dice', label:string}}
 */
export function detectDiceIntent(text, { judgeDefault = '1d100', diceDefault = '1d100' } = {}) {
  const s = String(text ?? '');
  const m = s.match(EXPLICIT_DICE_RE);
  if (m) return { expr: m[0].replace(/\s+/g, ''), kind: 'explicit', label: '指定点数' };
  const bare = s.match(BARE_DICE_RE);
  if (bare) return { expr: `1${bare[0].replace(/\s+/g, '').toLowerCase()}`, kind: 'explicit', label: '指定点数' };
  if (JUDGE_RE.test(s)) return { expr: judgeDefault, kind: 'judge', label: '判定' };
  if (DICE_ACTION_RE.test(s)) return { expr: diceDefault, kind: 'dice', label: '骰子' };
  return null;
}

const PERCEPTION = {
  forward: '那条转发里有',
  image: '图里',
  ocr: '图里的字是',
  quote: '刚刚那句引的是',
  link: '那条链接是',
  name: '说话的是',
  dice: '脑子里蹦出一个数：',
  memory: '旧记忆里翻到',
  skill: '本地有个现成能力：',
  text: '瞄到一句',
};

/**
 * 把一组 R1 产物渲染成一段"我的潜意识联想到"。
 * @param {Array<{kind:string, text:string}>} items
 * @param {object} config normalizeReflexConfig 的结果
 * @returns {string} 空字符串 = 本轮没有可浮现的东西（这是常态）
 */
export function buildReflexBlock(items, config = REFLEX_DEFAULTS) {
  const cfg = normalizeReflexConfig(config);
  if (!cfg.enabled || !Array.isArray(items) || items.length === 0) return '';

  const lines = [];
  const seen = new Set();
  for (const item of items) {
    if (lines.length >= cfg.maxItems) break;
    const kind = String(item?.kind ?? 'text');
    const text = String(item?.text ?? '').trim();
    if (text.length < cfg.minChars) continue;
    if (!screenClaim(text).ok) continue;
    const head = PERCEPTION[kind] ?? PERCEPTION.text;
    const line = `- ${head}「${text}」`;
    if (seen.has(line)) continue;
    seen.add(line);
    lines.push(line);
  }
  if (lines.length === 0) return '';

  let block = `我的潜意识联想到：\n${lines.join('\n')}`;
  if (block.length > cfg.maxChars) {
    // 超预算就整条丢，不截半句（半句最容易误导）
    const kept = [];
    let len = '我的潜意识联想到：'.length;
    for (const line of lines) {
      if (len + line.length + 1 > cfg.maxChars) break;
      kept.push(line);
      len += line.length + 1;
    }
    block = kept.length ? `我的潜意识联想到：\n${kept.join('\n')}` : '';
  }
  return block;
}

/**
 * R0：从一条入站消息里抽出确定性的结构事实（不调模型、不读网络）。
 * 只返回布尔/计数/短标签，供 R1 决定去拉什么。
 */
export function classifyIncoming(msg) {
  const m = msg && typeof msg === 'object' ? msg : {};
  const text = String(m.text ?? m.plain ?? '');
  const media = Array.isArray(m.media) ? m.media : [];
  const segments = Array.isArray(m.segments) ? m.segments : [];
  const links = text.match(/https?:\/\/[^\s，。；）)】]+/g) ?? [];
  const textForwardId = (text.match(/\[转发消息\s*id=([^\]\s]+)\]/) ?? [])[1] ?? '';
  const hasForward = Boolean(m.forwardId || m.hasForward || textForwardId);
  const forwardIds = [];
  for (const seg of segments) {
    if (seg?.type !== 'forward') continue;
    const id = seg.id ?? seg.data?.id;
    if (id != null) forwardIds.push(String(id));
  }
  return {
    hasForward,
    forwardId: m.forwardId ? String(m.forwardId) : (forwardIds[0] ?? textForwardId),
    imageCount: media.filter((x) => /image|face|mface/.test(String(x?.type ?? ''))).length || (m.imageCount ?? 0),
    quoteId: m.quote?.id ? String(m.quote.id) : (m.replyTo ? String(m.replyTo) : ''),
    links: links.slice(0, 2),
    atSelf: Boolean(m.atSelf),
    length: [...text].length,
    isCommand: /^(鱼鱼找鸡|查黑话|#\S+)/.test(text.trim()),
    text,
  };
}

/**
 * R1 的本地骰子执行器：只接受 dN / NdN±M，限制规模，不访问网络。
 * 返回 null 表示表达式不可执行。
 */
export function rollDice(expr, random = Math.random) {
  const m = String(expr ?? '').trim().toLowerCase().match(/^(\d{0,2})d(\d{1,4})([+-]\d{1,3})?$/);
  if (!m) return null;
  const count = Math.max(1, Math.min(100, Number(m[1] || 1)));
  const sides = Math.max(2, Math.min(1000, Number(m[2])));
  const modifier = Number(m[3] || 0);
  if (!Number.isFinite(count) || !Number.isFinite(sides) || !Number.isFinite(modifier)) return null;
  const rolls = [];
  for (let i = 0; i < count; i += 1) rolls.push(1 + Math.floor(random() * sides));
  const total = rolls.reduce((a, b) => a + b, 0) + modifier;
  return { expr: `${count}d${sides}${modifier ? (modifier > 0 ? `+${modifier}` : modifier) : ''}`, total, rolls, modifier };
}

/**
 * 发言后检查：模型有没有把本地骰子结果改成另一组数字。
 * @returns null | {expected:string, seen:string}
 */
export function findDiceClaimMismatch(expectedText, selfText) {
  const expected = String(expectedText ?? '').match(/(\d+d\d+)\s*=\s*(\d+)/i);
  if (!expected) return null;
  const claims = [...String(selfText ?? '').matchAll(/(\d*d\d+)\s*=\s*(\d+)/gi)];
  const wrong = claims.find((m) => String(m[1]).toLowerCase().replace(/^d/, '1d') !== expected[1].toLowerCase()
    || Number(m[2]) !== Number(expected[2]));
  return wrong ? { expected: expected[0], seen: wrong[0] } : null;
}

/** 夜间/静默窗口：01:00–08:00（返回 true 表示现在不该主动浮现）。 */
export function inQuietHours(now, { startHour = 1, endHour = 8 } = {}) {
  const d = new Date(now);
  const h = d.getHours();
  if (startHour === endHour) return false;
  return startHour < endHour ? (h >= startHour && h < endHour) : (h >= startHour || h < endHour);
}
