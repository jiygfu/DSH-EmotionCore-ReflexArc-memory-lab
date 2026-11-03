// 反射弧群聊触发：纯本地判定，不依赖模型，不注册工具。
//
// 这个文件只放可单测的纯函数；网络状态、去重、归档在 index.js。
// 设计原则：
//   · 先判“长期活动”控制词，再判活动开始，最后才轮到相关/随机/高概率；
//   · 控制词只在短句/句首生效，疑问句不当作暂停/结束（避免“结束了吗”误归档）；
//   · 相关触发只认明确指向本机的证据（名字、别名、第二人称提问），不猜语义。

export const TRIGGER_DEFAULTS = Object.freeze({
  start: ['开团', '跑团', '开始游戏', '游戏开始', '来一局', '开一局', '剧本', '桌游', 'trpg', 'dnd', 'coc', '团本', '开个团'],
  pause: ['暂停', '先停', '停一下', '休息', '歇会', '等我'],
  resume: ['继续', '恢复', '接着来', '接着跑', '回来继续'],
  interrupt: ['中断', '打断', '先不跑', '退出', '取消'],
  end: ['结束', '团灭', '收尾', '不玩了', '散了', '完结', '归档', '到此为止'],
});

const QUESTION_RE = /([?？]\s*$|(吗|嘛|么|咋|怎么|为什么|为啥|什么|哪个|哪里|哪儿|谁|多少|几点|是不是|有没有|能不能|可不可以|要不要|好不好|对不对|行不行)\s*[。！!…～~]*$)/;
const CONTINUE_RE = /^(那|所以|不过|然后|而且|但是|可是|话说|对了|还有|就是说|也就是说)/;
// 只提到「剧本/桌游」不算开始；要有动作词或句首词才算，避免把讨论误判成开团。
const START_ACTION_RE = /(开始|开个|开一|来一|来把|玩|跑|搞个|整一|开团|跑团)/;
const SECOND_PERSON_RE = /(^|[\s,，。！？!?])(你|您)(觉得|说|看|会|能|要不要|是不是|怎么|为什么|在吗|呢|那边|刚才|之前)/;
const ANY_SECOND_PERSON_RE = /(你|您)/;

/** 文本列表归一：数组 / 逗号 / 分号 / 换行都吃。 */
export function splitList(raw) {
  if (Array.isArray(raw)) return raw.map((x) => String(x ?? '').trim()).filter(Boolean);
  return String(raw ?? '')
    .split(/[,，;；\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** 当前群是否在接话白名单里；空列表 = 所有通过门禁的群。 */
export function isManagedGroup(groupId, managedGroups) {
  const gid = String(groupId ?? '').trim();
  if (!gid) return false;
  const list = splitList(managedGroups);
  if (!list.length) return true;
  return list.includes('*') || list.includes(gid);
}

/** 文本归一：去首尾、压空白、转小写；保留中文标点用于疑问句判断。 */
export function normalizeText(text) {
  return String(text ?? '').replace(/\s+/g, ' ').trim().toLowerCase();
}

export function isQuestion(text) {
  return QUESTION_RE.test(normalizeText(text));
}

/** 活动词表：配置没写时用内置默认。 */
export function activityPatterns(cfg = {}) {
  const pick = (key) => {
    const own = splitList(cfg[key]);
    return own.length ? own : TRIGGER_DEFAULTS[key];
  };
  return {
    start: pick('activityStartKeywords'),
    pause: pick('activityPauseKeywords'),
    resume: pick('activityResumeKeywords'),
    interrupt: pick('activityInterruptKeywords'),
    end: pick('activityEndKeywords'),
  };
}

function hitWord(text, words) {
  const t = String(text ?? '');
  for (const raw of words || []) {
    const w = String(raw || '').trim().toLowerCase();
    if (!w) continue;
    if (w.length >= 2 && t.includes(w)) return w;
  }
  return null;
}

/**
 * 识别长期活动的控制/开始动作。
 * 控制词（暂停/继续/中断/结束）只认短句或句首；疑问句不触发。
 * 开始词允许在长句里出现（“今晚开个跑团吧”）。
 * @returns {null | {action:'start'|'pause'|'resume'|'interrupt'|'end', keyword:string}}
 */
export function detectActivityAction(text, patterns = activityPatterns({})) {
  const t = normalizeText(text);
  if (!t) return null;
  const question = isQuestion(t);

  // 结束优先于开始：一句话里同时出现“开始/结束”时不应重新开团。
  for (const action of ['end', 'interrupt', 'pause', 'resume']) {
    if (question) continue;
    const words = patterns?.[action] || TRIGGER_DEFAULTS[action];
    const hit = hitWord(t, words);
    if (!hit) continue;
    const shortEnough = t.length <= Math.max(12, hit.length + 8);
    const atStart = t.startsWith(hit);
    if (shortEnough || atStart) return { action, keyword: hit };
  }

  if (!question) {
    const hit = hitWord(t, patterns?.start || TRIGGER_DEFAULTS.start);
    if (hit && t.length <= 80 && (t.startsWith(hit) || START_ACTION_RE.test(t))) {
      return { action: 'start', keyword: hit };
    }
  }
  return null;
}

/**
 * “这条是不是在跟我说话”的本地分。
 * 只给明确证据加分；没有证据就是 0，不靠概率猜。
 * @returns {{score:number, matched:string[], question:boolean}}
 */
export function scoreRelated(text, { selfNames = [], keywords = [] } = {}) {
  const t = normalizeText(text);
  if (!t) return { score: 0, matched: [], question: false };
  const matched = [];
  let score = 0;

  const names = [...splitList(selfNames), ...splitList(keywords)]
    .map((s) => s.toLowerCase())
    .filter((s) => s.length >= 2);
  for (const name of new Set(names)) {
    if (t.includes(name)) {
      score += 3;
      matched.push(name);
      break; // 同一条消息里名字出现多次只算一次，防止刷分
    }
  }

  if (SECOND_PERSON_RE.test(t)) {
    score += 2;
    matched.push('第二人称');
  } else if (ANY_SECOND_PERSON_RE.test(t)) {
    score += 1;
    matched.push('你');
  }

  const question = isQuestion(t);
  if (question) score += 1;
  if (CONTINUE_RE.test(t)) score += 1;

  return { score: Math.min(10, score), matched, question };
}

/** “群里正在聊”的上下文分：只用于高概率模式，不用于相关模式。 */
export function highContextScore({
  recentCount = 0,
  question = false,
  textLen = 0,
  lastBotAgoMs = null,
  continued = false,
  minMessages = 3,
} = {}) {
  let score = 0;
  if (Number(recentCount) >= Math.max(1, Number(minMessages) || 3)) score += 2;
  if (question) score += 2;
  if (Number(textLen) >= 8) score += 1;
  if (lastBotAgoMs != null && Number.isFinite(Number(lastBotAgoMs)) && Number(lastBotAgoMs) <= 180000) score += 1;
  if (continued) score += 1;
  return score;
}

/** 高概率模式：上下文分越高，实际概率越高；低于 2 分不触发。 */
export function highChanceFor(score, basePercent = 65) {
  const s = Number(score) || 0;
  if (s < 2) return 0;
  const base = Math.max(1, Math.min(100, Number(basePercent) || 65));
  return Math.min(95, base + (s - 2) * 8);
}

export function probabilityHit(percent, rand = Math.random) {
  const p = Math.max(0, Math.min(100, Number(percent) || 0));
  if (p <= 0) return false;
  if (p >= 100) return true;
  return Number(rand()) * 100 < p;
}

export function isContinueLike(text) {
  return CONTINUE_RE.test(normalizeText(text));
}

/**
 * 鱼群身份识别：网名/群名片命中“肥鱼、机器人、AI、bot”等标签。
 * 纯本地、只返回命中的标签；是否静音由调用方决定。
 */
export function detectFishTags(name, tags = []) {
  const text = normalizeText(name);
  if (!text) return [];
  const out = [];
  for (const raw of splitList(tags)) {
    const tag = raw.toLowerCase();
    if (!tag) continue;
    let hit = false;
    if (/^[a-z0-9_-]+$/i.test(tag)) {
      if (tag === 'ai') {
        const re = new RegExp(`(^|[^a-z0-9])ai([^a-z0-9]|$)`, 'i');
        hit = re.test(text);
      } else {
        hit = text.includes(tag);
      }
    } else {
      hit = text.includes(tag);
    }
    if (hit) out.push(raw);
  }
  return [...new Set(out)];
}
