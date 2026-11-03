/**
 * ReflexArc — 独立反射弧子插件。
 *
 * 只做本地、确定性的入站预处理：
 *   - 识别骰子指令并在本地结算；
 *   - 生成极短 hint，不注册模型 tool；
 *   - 后续接 OCR / 表情联想 / 记忆指针。
 *
 * 部署：<dsh-onebot-qq>/plugins/reflex-arc/index.js
 */

import fs from 'node:fs';
import path from 'node:path';
import { detectDiceIntent, rollDice, classifyIncoming } from './reflex-core.js';
import {
  activityPatterns, detectActivityAction, detectFishTags, highChanceFor, highContextScore,
  isContinueLike, isManagedGroup, isQuestion, probabilityHit, scoreRelated, splitList,
} from './trigger-core.js';

const VERSION = '0.1.1';
const DEFAULT_FISH_TAGS = ['肥鱼', '机器人', 'AI', 'bot', '人工智能', '机械'];

const configSchema = {
  enabled: { type: 'bool', default: true, group: '反射弧', label: '启用反射弧', hint: '本地骰子/提示；不注册模型工具。' },
  maxDice: { type: 'int', default: 100, min: 2, max: 10000, group: '反射弧', label: '骰子上限', hint: '单次骰子的面数上限，防止异常大数。' },
  maxCount: { type: 'int', default: 10, min: 1, max: 20, group: '反射弧', label: '骰子个数上限', hint: '一次最多掷几个骰子。' },
  emotionCoreUrl: { type: 'str', default: 'http://127.0.0.1:8765', group: '反射弧', label: 'EmotionCore 地址', hint: '人物印象、长期活动判断共用；留空关闭对应联动。' },
  impressionTimeoutMs: { type: 'int', default: 1500, min: 100, max: 10000, group: '反射弧', label: '人物印象超时（ms）' },
  visionModel: { type: 'str', default: 'huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M', group: '反射弧', label: '本地视觉模型' },
  visionTimeoutMs: { type: 'int', default: 20000, min: 1000, max: 120000, group: '反射弧', label: '图片理解超时（ms）' },
  memoryLabEnabled: { type: 'bool', default: false, group: '反射弧', label: '启用 memory-lab 联想（实验）', hint: '默认关闭；只读查询，失败不影响回复。' },
  memoryLabUrl: { type: 'str', default: 'http://127.0.0.1:8766', group: '反射弧', label: 'memory-lab 地址' },
  memoryLabTimeoutMs: { type: 'int', default: 250, min: 100, max: 3000, group: '反射弧', label: 'memory-lab 超时（ms）' },

  // ── 群聊触发：每个模式一个下级页；总开关默认关，避免装完就抢话 ──
  triggerEnabled: {
    type: 'bool', default: false, group: '触发/总览', label: '启用群聊接话策略',
    hint: '总开关。开：受管理群里没被 @ 的消息也会进入本地反射弧判断；关：只保留原有的骰子/图片等预处理，不主动接话。'
      + '门禁（屏蔽群、群内黑名单、用户白名单）仍然优先，反射弧只处理通过门禁的消息。',
  },
  triggerGroups: {
    type: 'group', default: [], group: '触发/总览', label: '接话群（空 = 所有通过门禁的群）',
    hint: '群号列表，逗号分隔。只在这些群里启用相关/随机/高概率/长期活动判断；留空 = 所有通过 gate-wake 门禁的群。'
      + '群号可在「群聊」页查看。',
  },
  selfAliases: {
    type: 'str', default: '', group: '触发/总览', label: '本机别名（逗号分隔，可留空）',
    hint: '用于「相关触发」判断，例如群里叫你的名字/外号。留空时自动使用当前 QQ 昵称；唤醒词不会自动算作别名，避免和关键词唤醒重复。',
  },
  relatedKeywords: {
    type: 'str', default: '', group: '触发/总览', label: '额外相关词（逗号分隔，可留空）',
    hint: '除了本机别名，出现这些词也算「在说你」。适合「雪风」「小鱼」这类只有你们知道的称呼；别填「你」这种泛词。',
  },

  relatedEnabled: {
    type: 'bool', default: false, group: '触发/相关', label: '相关触发',
    hint: '只有本地判断「这条和本机有关」才接话。判断依据：本机别名、第二人称提问、「那/所以」这类接续词；不调用模型。',
  },
  relatedMinScore: {
    type: 'int', default: 3, min: 1, max: 10, group: '触发/相关', label: '触发分数阈值',
    hint: '分数越高越严格。默认 3：本机别名（3 分），或句首第二人称提问（2+1 分）可触发；句中泛泛的「你」加问句只有 2 分，不触发。',
  },
  relatedRequireQuestion: {
    type: 'bool', default: false, group: '触发/相关', label: '只接提问/请求',
    hint: '开：即使出现本机别名，也必须是疑问句/请求才触发；关：别名出现即可。',
  },
  relatedCooldownSec: {
    type: 'int', default: 90, min: 0, max: 3600, group: '触发/相关', label: '冷却（秒）',
    hint: '同一群相邻两次相关触发的最小间隔；0 = 只受每小时上限约束。',
  },
  relatedHourlyMax: {
    type: 'int', default: 8, min: 1, max: 100, group: '触发/相关', label: '每小时上限',
    hint: '防止有人反复叫你导致连续烧模型。',
  },

  randomEnabled: {
    type: 'bool', default: false, group: '触发/随机', label: '随机触发',
    hint: '按概率随机接一句；不判断内容，适合冷清群或测试。默认关。',
  },
  randomChance: {
    type: 'int', default: 8, min: 1, max: 100, group: '触发/随机', label: '概率（%）',
    hint: '每条符合条件的消息独立掷一次。建议 2–10%；100% 等于每条都接。',
  },
  randomCooldownSec: {
    type: 'int', default: 180, min: 0, max: 7200, group: '触发/随机', label: '冷却（秒）',
    hint: '同一群相邻两次随机触发的最小间隔；0 = 不限制间隔。',
  },
  randomHourlyMax: {
    type: 'int', default: 3, min: 1, max: 100, group: '触发/随机', label: '每小时上限',
    hint: '硬上限，防止随机概率在高频群里失控。',
  },
  randomMinChars: {
    type: 'int', default: 4, min: 0, max: 200, group: '触发/随机', label: '最短字数',
    hint: '太短的消息（「？」「嗯」）不参与随机，避免接废话。',
  },

  highEnabled: {
    type: 'bool', default: false, group: '触发/高概率', label: '高概率搭话',
    hint: '群里正在热聊、有提问或刚接过话时，用较高概率接一句。它不判断「是不是叫你」，只看对话热度；和随机模式二选一即可。',
  },
  highChance: {
    type: 'int', default: 65, min: 1, max: 100, group: '触发/高概率', label: '基础概率（%）',
    hint: '上下文分 ≥2 才进入掷骰；实际概率会随上下文分提高（最高 95%）。',
  },
  highMinScore: {
    type: 'int', default: 3, min: 2, max: 7, group: '触发/高概率', label: '最低上下文分',
    hint: '低于此分不触发。默认 3：通常要「最近消息数够 + 有提问」或「刚接过话 + 有接续词」。',
  },
  highWindowSec: {
    type: 'int', default: 180, min: 30, max: 3600, group: '触发/高概率', label: '热度窗口（秒）',
    hint: '统计最近多少秒内的群消息来判断「正在聊」。',
  },
  highMinMessages: {
    type: 'int', default: 3, min: 1, max: 50, group: '触发/高概率', label: '窗口内最少消息数',
    hint: '窗口内至少这么多条（含当前这条）才加「热聊」分。',
  },
  highRequireQuestion: {
    type: 'bool', default: false, group: '触发/高概率', label: '只接提问',
    hint: '开：只在高概率模式里接疑问句；关：陈述句、接续句也可以。',
  },
  highCooldownSec: {
    type: 'int', default: 90, min: 0, max: 3600, group: '触发/高概率', label: '冷却（秒）',
    hint: '同一群相邻两次高概率触发的最小间隔。',
  },
  highHourlyMax: {
    type: 'int', default: 6, min: 1, max: 100, group: '触发/高概率', label: '每小时上限',
    hint: '硬上限，防止热群连续触发。',
  },

  activityEnabled: {
    type: 'bool', default: false, group: '触发/长期活动', label: '长期活动接管',
    hint: '识别聊天游戏/跑团等长期活动；活动进行中每条消息都接，直到暂停/中断/结束并归档。默认关。',
  },
  activityAutoStart: {
    type: 'bool', default: true, group: '触发/长期活动', label: '自动识别活动开始',
    hint: '开：消息命中开始词（开团/跑团/来一局…）就进入活动状态；关：只能在调试页手动开始。',
  },
  activityEmotionCore: {
    type: 'bool', default: true, group: '触发/长期活动', label: 'EmotionCore 联动判断',
    hint: '开：活动开始/控制消息会请求本机 EmotionCore `/activity` 复核；服务不可用时自动回落本地规则，不影响聊天。',
  },
  activityMinConfidence: {
    type: 'int', default: 55, min: 0, max: 100, group: '触发/长期活动', label: 'EmotionCore 最低置信度（%）',
    hint: '低于此值的远端判断不采纳，改用本地关键词。',
  },
  activityEmotionCoreTimeoutMs: {
    type: 'int', default: 500, min: 100, max: 5000, group: '触发/长期活动', label: 'EmotionCore 超时（ms）',
    hint: '只影响活动开始/控制判断；超时立即回落本地，不阻塞消息。',
  },
  activityStartKeywords: {
    type: 'text', default: '', group: '触发/长期活动', label: '开始词（一行/逗号分隔）',
    hint: '留空 = 内置：开团,跑团,开始游戏,游戏开始,来一局,开一局,剧本,桌游,TRPG,DND,COC,团本。',
  },
  activityPauseKeywords: {
    type: 'text', default: '', group: '触发/长期活动', label: '暂停词',
    hint: '留空 = 内置：暂停,先停,停一下,休息,歇会,等我。暂停会归档当前段，之后可继续。',
  },
  activityResumeKeywords: {
    type: 'text', default: '', group: '触发/长期活动', label: '继续词',
    hint: '留空 = 内置：继续,恢复,接着来,接着跑,回来继续。',
  },
  activityInterruptKeywords: {
    type: 'text', default: '', group: '触发/长期活动', label: '中断词',
    hint: '留空 = 内置：中断,打断,先不跑,退出,取消。中断会归档并结束当前活动。',
  },
  activityEndKeywords: {
    type: 'text', default: '', group: '触发/长期活动', label: '结束词',
    hint: '留空 = 内置：结束,团灭,收尾,不玩了,散了,完结,归档,到此为止。',
  },
  activityIdleEndMin: {
    type: 'int', default: 0, min: 0, max: 1440, group: '触发/长期活动', label: '静默自动结束（分钟）',
    hint: '0 = 不自动结束，必须收到暂停/中断/结束；大于 0 时，超过这么久没消息，下一条消息前自动归档。',
  },
  activityMaxTranscript: {
    type: 'int', default: 200, min: 20, max: 500, group: '触发/长期活动', label: '归档最多保留消息数',
    hint: '只影响归档文件大小；超出后保留最近 N 条。',
  },
  activityArchive: {
    type: 'bool', default: true, group: '触发/长期活动', label: '结束时写入归档文件',
    hint: '写到 dataDir/state/reflex-activities/，并在调试页显示最近归档；不写 EmotionCore 记忆库。',
  },
  activityReplyEvery: {
    type: 'bool', default: true, group: '触发/长期活动', label: '活动进行中每条都接',
    hint: '默认开。关：只记录活动，不自动接话（调试/旁观模式）。',
  },

  fishEnabled: {
    type: 'bool', default: false, group: '触发/鱼群', label: '启用鱼群记录',
    hint: '开：群友的群名片/昵称命中“肥鱼、机器人、AI、bot”等标签时，自动给其人物印象打标签；之后该群友的群消息只记录，不进入模型、不搭话、不主动私聊。默认关。',
  },
  fishTags: {
    type: 'text', default: '肥鱼,机器人,AI,bot,人工智能,机械', group: '触发/鱼群', label: '鱼群身份标签',
    hint: '逗号/换行分隔，匹配群名片和昵称。AI/bot 按英文词边界匹配；中文按包含匹配。',
  },
  fishTagPerson: {
    type: 'bool', default: true, group: '触发/鱼群', label: '写入 EmotionCore 人物印象标签',
    hint: '开：命中时调用本机 /person_tag，把标签写进人物印象（L4），之后注入上下文会带“标签：…”。服务不可用时只保留本地鱼群记录。',
  },

  debugLog: {
    type: 'bool', default: false, group: '触发/调试', label: '控制台打印触发决策',
    hint: '开：每次相关/随机/高概率/活动判断都会写一行日志，方便调阈值。',
  },
  debugRecentLimit: {
    type: 'int', default: 20, min: 5, max: 100, group: '触发/调试', label: '调试页保留最近决策数',
    hint: '只保留最近 N 条判定记录，不存完整聊天。',
  },
};

function parseDice(text, maxDice = 100, maxCount = 10) {
  const intent = detectDiceIntent(text, { judgeDefault: '1d100', diceDefault: '1d100' });
  if (!intent) return null;
  const r = rollDice(intent.expr);
  if (!r) return null;
  // 保持旧测试/调用方使用的字段名；上限由本地 rollDice 再兜一次。
  const count = Math.max(1, Math.min(maxCount, r.rolls.length));
  const sides = Math.max(2, Math.min(maxDice, Number((r.expr.match(/d(\d+)/i) || [])[1]) || 100));
  return { count, sides, rolls: r.rolls.slice(0, count), total: r.total, expr: r.expr, intent };
}

export default {
  id: 'reflex-arc',
  title: 'ReflexArc 反射弧',
  order: 36,
  version: VERSION,
  configSchema,

  setup(bot) {
    if (!bot?.cfg?.enabled) {
      bot.log?.info?.('[ReflexArc] disabled');
      return;
    }

    const onBefore = (stage, fn) => (typeof bot.on === 'function'
      ? bot.on(stage, fn)
      : bot.pipeline?.use?.(stage, fn));
    function stateFile() {
      return path.join(bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'state', 'reflex-impressions.json');
    }

    function readState() {
      try {
        const raw = JSON.parse(fs.readFileSync(stateFile(), 'utf8'));
        if (raw && raw.day === new Date().toLocaleDateString('en-CA')) return raw;
      } catch {}
      return { day: new Date().toLocaleDateString('en-CA'), seen: {} };
    }

    function saveState(state) {
      try {
        const file = stateFile();
        fs.mkdirSync(path.dirname(file), { recursive: true });
        fs.writeFileSync(file, JSON.stringify(state, null, 2), 'utf8');
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] impression state: ${e.message}`);
      }
    }

    // ═══════════════════════════════════════════════════════════════════
    // 群聊触发（本地反射弧）
    // ═══════════════════════════════════════════════════════════════════
    // 只处理通过 gate-wake 的消息；门禁、黑名单、用户白名单仍然优先。
    // 状态落盘到 state/reflex-trigger.json；归档单独写 state/reflex-activities/。
    const triggerFile = () => path.join(
      bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'state', 'reflex-trigger.json',
    );
    const archiveDir = () => path.join(
      bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'state', 'reflex-activities',
    );
    let trigState = null;
    let trigSaveTimer = null;
    let trigDisposed = false;
    let activityRemoteDownUntil = 0;

    const nowIso = () => new Date().toISOString();
    const numOf = (v, fallback, min, max) => {
      const n = Number(v);
      if (!Number.isFinite(n)) return fallback;
      return Math.min(max, Math.max(min, Math.round(n)));
    };
    const hourKey = (ts = Date.now()) => {
      const d = new Date(ts);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}-${String(d.getHours()).padStart(2, '0')}`;
    };
    const oneLine = (v, n = 80) => String(v ?? '').replace(/\s+/g, ' ').trim().slice(0, n);

    function defaultTriggerState() {
      return { version: 1, groups: {}, archives: [], events: [] };
    }

    function readTriggerState() {
      try {
        const raw = JSON.parse(fs.readFileSync(triggerFile(), 'utf8'));
        if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
          if (!raw.groups || typeof raw.groups !== 'object') raw.groups = {};
          if (!Array.isArray(raw.archives)) raw.archives = [];
          if (!Array.isArray(raw.events)) raw.events = [];
          return raw;
        }
      } catch {}
      return defaultTriggerState();
    }

    function ensureTriggerState() {
      if (!trigState) trigState = readTriggerState();
      return trigState;
    }

    function writeJsonAtomic(file, value) {
      const dir = path.dirname(file);
      fs.mkdirSync(dir, { recursive: true });
      const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(value, null, 2), 'utf8');
      try {
        fs.renameSync(tmp, file);
      } catch {
        try { fs.copyFileSync(tmp, file) } finally { try { fs.rmSync(tmp, { force: true }) } catch {} }
      }
    }

    function saveTriggerStateNow() {
      if (trigDisposed || !trigState) return;
      try {
        writeJsonAtomic(triggerFile(), trigState);
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] trigger state: ${e.message}`);
      }
    }

    function scheduleTriggerSave() {
      if (trigDisposed || trigSaveTimer) return;
      trigSaveTimer = setTimeout(() => {
        trigSaveTimer = null;
        saveTriggerStateNow();
      }, 200);
    }

    // ── 鱼群记录：命中的群友只记账，不进模型 ──
    const fishFile = () => path.join(
      bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'state', 'reflex-fish.json',
    );
    const fishLogFile = () => path.join(
      bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'state', 'fish-records.jsonl',
    );
    let fishState = null;
    let fishSaveTimer = null;

    function defaultFishState() {
      return { version: 1, members: {}, recordCount: 0, recent: [] };
    }

    function ensureFishState() {
      if (fishState) return fishState;
      try {
        const raw = JSON.parse(fs.readFileSync(fishFile(), 'utf8'));
        fishState = raw && typeof raw === 'object' ? raw : defaultFishState();
      } catch {
        fishState = defaultFishState();
      }
      if (!fishState.members || typeof fishState.members !== 'object') fishState.members = {};
      if (!Array.isArray(fishState.recent)) fishState.recent = [];
      if (!Number.isFinite(Number(fishState.recordCount))) fishState.recordCount = 0;
      return fishState;
    }

    function saveFishNow() {
      if (!fishState) return;
      try {
        writeJsonAtomic(fishFile(), fishState);
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] fish state: ${e.message}`);
      }
    }

    function scheduleFishSave() {
      if (fishSaveTimer) return;
      fishSaveTimer = setTimeout(() => {
        fishSaveTimer = null;
        saveFishNow();
      }, 200);
    }

    function fishTagsOf(cfg = bot.cfg || {}) {
      const tags = splitList(cfg.fishTags);
      return tags.length ? tags : DEFAULT_FISH_TAGS;
    }

    function fishMember(qq) {
      const st = ensureFishState();
      const key = String(qq);
      if (!st.members[key]) {
        st.members[key] = { qq: key, name: '', tags: [], count: 0, firstAt: null, lastAt: null, taggedAt: null, tagAttemptAt: 0 };
      }
      return st.members[key];
    }

    function recordFish(ev, tags, name, now) {
      const st = ensureFishState();
      const qq = String(ev.sender?.qq ?? '');
      const member = fishMember(qq);
      member.name = name || member.name || '';
      member.tags = [...new Set([...(member.tags || []), ...tags])].slice(-10);
      member.count = Number(member.count || 0) + 1;
      member.firstAt = member.firstAt || nowIso();
      member.lastAt = nowIso();
      const text = String(ev.text || '').trim() || `[${(ev.images || []).length || 1} 个非文本消息]`;
      const row = {
        at: nowIso(),
        groupId: String(ev.groupId || ''),
        qq,
        name: oneLine(name, 40),
        tags,
        messageId: ev.messageId ?? null,
        text: oneLine(text, 2000),
      };
      try {
        fs.mkdirSync(path.dirname(fishLogFile()), { recursive: true });
        fs.appendFileSync(fishLogFile(), `${JSON.stringify(row)}\n`, 'utf8');
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] fish record: ${e.message}`);
      }
      st.recordCount = Number(st.recordCount || 0) + 1;
      st.recent.unshift({
        at: row.at, groupId: row.groupId, qq, name: row.name, tags, preview: oneLine(text, 100),
      });
      st.recent = st.recent.slice(0, 30);
      scheduleFishSave();
      bot.log?.info?.(`[ReflexArc] fish record qq=${qq} tags=${tags.join(',')} group=${ev.groupId}`);
    }

    async function tagFishPerson(ev, tags, name) {
      if (bot.cfg?.fishTagPerson === false) return;
      const member = fishMember(ev.sender?.qq);
      const now = Date.now();
      if (member.taggedAt || now - Number(member.tagAttemptAt || 0) < 60_000) return;
      member.tagAttemptAt = now;
      scheduleFishSave();
      const base = String(bot.cfg?.emotionCoreUrl || process.env.EMOTIONCORE_URL || '').trim().replace(/\/+$/, '');
      if (!base) return;
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), 1500);
      try {
        const res = await fetch(`${base}/person_tag`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ qq: String(ev.sender?.qq ?? ''), name: name || '', tags, note: 'fish-record' }),
          signal: ac.signal,
        });
        if (!res.ok) return;
        const data = await res.json();
        if (data?.ok !== false) {
          member.taggedAt = nowIso();
          member.remoteTags = data?.person?.tags || tags;
          scheduleFishSave();
          bot.log?.info?.(`[ReflexArc] fish person tagged qq=${member.qq} tags=${tags.join(',')}`);
        }
      } catch {
        // 本地记录已落盘；EmotionCore 恢复后下一次消息再补标签。
      } finally {
        clearTimeout(timer);
      }
    }

    function onFishGate(ev) {
      const cfg = bot.cfg || {};
      if (cfg.fishEnabled !== true) return;
      if (!ev?.isGroup || !ev.groupId) return;
      if (ev.stopped) return;
      const qq = String(ev.sender?.qq ?? '').trim();
      if (!/^\d+$/.test(qq)) return;
      if (String(bot?.onebot?.selfId ?? '') === qq) return;
      const cached = ensureFishState().members[qq] || null;
      const names = [ev.sender?.card, ev.sender?.name, cached?.name].filter(Boolean).join(' ');
      const tags = (cached?.tags && cached.tags.length)
        ? cached.tags
        : detectFishTags(names, fishTagsOf(cfg));
      if (!tags.length) return;

      const member = fishMember(qq);
      const name = String(ev.sender?.card || ev.sender?.name || cached?.name || '').trim();
      recordFish(ev, tags, name, Date.now());
      ev.stopped = true;
      ev.stopReason = 'reflex-arc:fish-silent';
      if (!member.taggedAt) void tagFishPerson(ev, tags, name);
    }

    function fishStatus() {
      const st = ensureFishState();
      return {
        enabled: bot.cfg?.fishEnabled === true,
        tags: fishTagsOf(),
        recordCount: Number(st.recordCount || 0),
        members: Object.values(st.members || {})
          .sort((a, b) => String(b.lastAt || '').localeCompare(String(a.lastAt || '')))
          .slice(0, 50),
        recent: (st.recent || []).slice(0, 20),
        paths: { state: fishFile(), records: fishLogFile() },
      };
    }

    function groupState(gid) {
      const st = ensureTriggerState();
      const key = String(gid);
      if (!st.groups[key] || typeof st.groups[key] !== 'object') {
        st.groups[key] = {
          recent: [], counters: {}, last: null, lastBotAt: 0,
          activity: null, paused: null,
        };
      }
      const g = st.groups[key];
      if (!Array.isArray(g.recent)) g.recent = [];
      if (!g.counters || typeof g.counters !== 'object') g.counters = {};
      return g;
    }

    function pruneRecent(g, now) {
      const windowMs = Math.max(60_000, numOf(bot.cfg?.highWindowSec, 180, 30, 3600) * 1000);
      g.recent = (Array.isArray(g.recent) ? g.recent : [])
        .filter((m) => m && now - Number(m.ts || 0) <= windowMs)
        .slice(-40);
    }

    function remember(g, ev, text, now) {
      const item = {
        ts: now,
        qq: String(ev.sender?.qq ?? ''),
        name: oneLine(ev.sender?.name || ev.sender?.card || '', 24),
        text: oneLine(text, 240),
      };
      g.recent.push(item);
      if (g.recent.length > 40) g.recent = g.recent.slice(-40);
      return item;
    }

    function pushEvent(e) {
      const st = ensureTriggerState();
      const limit = numOf(bot.cfg?.debugRecentLimit, 20, 5, 100);
      st.events.unshift(e);
      if (st.events.length > Math.max(limit, 100)) st.events = st.events.slice(0, Math.max(limit, 100));
      const g = e?.groupId ? groupState(e.groupId) : null;
      if (g) g.last = e;
      scheduleTriggerSave();
    }

    function canFire(g, mode, cooldownSec, hourlyMax, now) {
      const c = g.counters?.[mode];
      if (c?.lastAt && now - Number(c.lastAt) < Math.max(0, numOf(cooldownSec, 0, 0, 7200)) * 1000) return false;
      if (c?.hour === hourKey(now) && Number(c.count || 0) >= Math.max(1, numOf(hourlyMax, 1, 1, 100))) return false;
      return true;
    }

    function markFire(g, mode, now) {
      const c = g.counters?.[mode] || {};
      g.counters[mode] = {
        hour: hourKey(now),
        count: c.hour === hourKey(now) ? Number(c.count || 0) + 1 : 1,
        lastAt: now,
      };
    }

    function selfNames() {
      const names = splitList(bot.cfg?.selfAliases);
      const n = String(bot?.onebot?.selfNickname || bot?.selfNickname || '').trim();
      if (n) names.push(n);
      return [...new Set(names.map((x) => x.trim()).filter((x) => x.length >= 2))];
    }

    function beginActivity(gid, g, title, from = null) {
      const safeGid = String(gid).replace(/[^\d]/g, '').slice(-12) || 'group';
      const id = `act-${Date.now().toString(36)}-${safeGid}`;
      g.activity = {
        id,
        title: oneLine(title || '长期活动', 60) || '长期活动',
        status: 'active',
        startedAt: nowIso(),
        updatedAt: nowIso(),
        messageCount: 0,
        transcript: [],
        resumedFrom: from,
      };
      g.paused = null;
      scheduleTriggerSave();
      return g.activity;
    }

    function appendActivity(g, ev, text, now) {
      const a = g.activity;
      if (!a) return;
      const max = numOf(bot.cfg?.activityMaxTranscript, 200, 20, 500);
      a.transcript.push({
        ts: nowIso(),
        qq: String(ev.sender?.qq ?? ''),
        name: oneLine(ev.sender?.name || ev.sender?.card || '', 24),
        text: oneLine(text, 600),
      });
      if (a.transcript.length > max) a.transcript = a.transcript.slice(-max);
      a.messageCount = Number(a.messageCount || 0) + 1;
      a.updatedAt = nowIso();
      scheduleTriggerSave();
    }

    function archiveActivity(gid, g, status, reason) {
      const a = g.activity;
      if (!a) return null;
      const record = {
        id: a.id,
        groupId: String(gid),
        title: a.title,
        status,
        reason: String(reason || ''),
        startedAt: a.startedAt,
        endedAt: nowIso(),
        messageCount: Number(a.messageCount || 0),
        resumedFrom: a.resumedFrom || null,
        participants: [...new Set((a.transcript || []).map((m) => m.qq).filter(Boolean))],
        transcript: Array.isArray(a.transcript) ? a.transcript : [],
      };
      let file = null;
      if (bot.cfg?.activityArchive !== false) {
        try {
          file = path.join(archiveDir(), `${a.id}.json`);
          writeJsonAtomic(file, record);
        } catch (e) {
          bot.log?.warn?.(`[ReflexArc] activity archive: ${e.message}`);
          file = null;
        }
      }
      const st = ensureTriggerState();
      st.archives.unshift({
        id: record.id,
        groupId: record.groupId,
        title: record.title,
        status: record.status,
        reason: record.reason,
        startedAt: record.startedAt,
        endedAt: record.endedAt,
        messageCount: record.messageCount,
        file,
      });
      st.archives = st.archives.slice(0, 50);
      g.activity = null;
      g.paused = status === 'paused'
        ? { id: record.id, title: record.title, at: record.endedAt, messageCount: record.messageCount }
        : null;
      scheduleTriggerSave();
      return { ...record, file };
    }

    function maybeIdleEnd(gid, g) {
      if (!g.activity) return false;
      const min = numOf(bot.cfg?.activityIdleEndMin, 0, 0, 1440);
      if (!min) return false;
      const last = Date.parse(g.activity.updatedAt || g.activity.startedAt || '') || 0;
      if (!last || Date.now() - last < min * 60_000) return false;
      archiveActivity(gid, g, 'ended', 'idle');
      return true;
    }

    async function remoteActivity(ev, gid, action, g) {
      if (bot.cfg?.activityEmotionCore === false) return null;
      if (Date.now() < activityRemoteDownUntil) return null;
      const base = String(bot.cfg?.emotionCoreUrl || process.env.EMOTIONCORE_URL || '').trim().replace(/\/+$/, '');
      if (!base) return null;
      const timeout = numOf(bot.cfg?.activityEmotionCoreTimeoutMs, 500, 100, 5000);
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), timeout);
      try {
        const res = await fetch(`${base}/activity`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            text: String(ev.text || ''),
            chatKey: String(ev.chatKey || ''),
            groupId: String(gid),
            sender: { qq: String(ev.sender?.qq ?? ''), name: String(ev.sender?.name || '') },
            active: g.activity ? {
              title: g.activity.title,
              status: g.activity.status,
              messageCount: g.activity.messageCount,
            } : null,
            localAction: action?.action || null,
          }),
          signal: ac.signal,
        });
        if (!res.ok) return null;
        const data = await res.json();
        if (!data?.ok || !data.action) return null;
        const raw = Number(data.confidence);
        const pct = Number.isFinite(raw) ? (raw <= 1 ? raw * 100 : raw) : 100;
        if (pct < numOf(bot.cfg?.activityMinConfidence, 55, 0, 100)) return null;
        activityRemoteDownUntil = 0;
        return { ...data, confidence: pct };
      } catch {
        // 本地服务不可用/超时：60 秒内直接走本地规则，避免活动期间每条都等超时。
        activityRemoteDownUntil = Date.now() + 60_000;
        return null;
      } finally {
        clearTimeout(timer);
      }
    }

    function wakeHint(ev, text) {
      ev.hint = Array.isArray(ev.hint) ? ev.hint : [];
      if (text) ev.hint.push(text);
    }

    function setWake(ev, kind, reason, extra = {}) {
      if (ev.wake) return;
      ev.wake = { kind, reason, ...extra };
      ev.stopReason = `reflex-arc:${kind}`;
    }

    function triggerStatus() {
      const st = ensureTriggerState();
      const cfg = bot.cfg || {};
      const now = Date.now();
      const active = [];
      const paused = [];
      let counters = { related: 0, random: 0, high: 0, activity: 0 };
      for (const [groupId, g] of Object.entries(st.groups || {})) {
        if (g?.activity) {
          active.push({
            groupId,
            id: g.activity.id,
            title: g.activity.title,
            status: g.activity.status,
            startedAt: g.activity.startedAt,
            updatedAt: g.activity.updatedAt,
            messageCount: g.activity.messageCount,
            idleSec: Math.round((now - (Date.parse(g.activity.updatedAt) || now)) / 1000),
          });
        }
        if (g?.paused) {
          paused.push({ groupId, ...g.paused });
        }
        for (const [mode, c] of Object.entries(g?.counters || {})) {
          if (Object.hasOwn(counters, mode) && c?.hour === hourKey(now)) counters[mode] += Number(c.count || 0);
        }
      }
      return {
        enabled: cfg.triggerEnabled === true,
        groups: splitList(cfg.triggerGroups),
        modes: {
          related: cfg.relatedEnabled === true,
          random: cfg.randomEnabled === true,
          high: cfg.highEnabled === true,
          activity: cfg.activityEnabled === true,
        },
        active,
        paused,
        counters,
        archiveCount: Array.isArray(st.archives) ? st.archives.length : 0,
        archives: (Array.isArray(st.archives) ? st.archives : []).slice(0, 5),
        recent: (Array.isArray(st.events) ? st.events : []).slice(0, numOf(cfg.debugRecentLimit, 20, 5, 100)),
        selfNames: selfNames(),
        paths: { state: triggerFile(), archives: archiveDir() },
        fish: fishStatus(),
        debugLog: cfg.debugLog === true,
      };
    }

    async function triggerControl(op, payload = {}) {
      const st = ensureTriggerState();
      const gid = String(payload.groupId || payload.group_id || payload.gid || '').trim();
      const g = gid ? groupState(gid) : null;
      const action = String(op || payload.op || 'status').trim();
      if (action === 'status') return { ok: true, status: triggerStatus() };
      if (action === 'test') {
        const text = String(payload.text || '');
        const cfg = bot.cfg || {};
        const related = scoreRelated(text, {
          selfNames: selfNames(),
          keywords: splitList(cfg.relatedKeywords),
        });
        const highScore = highContextScore({
          recentCount: g ? g.recent.length : 0,
          question: isQuestion(text),
          textLen: text.length,
          lastBotAgoMs: g?.lastBotAt ? Date.now() - g.lastBotAt : null,
          continued: isContinueLike(text),
          minMessages: cfg.highMinMessages,
        });
        return {
          ok: true,
          groupId: gid,
          managed: gid ? isManagedGroup(gid, cfg.triggerGroups) : false,
          activity: detectActivityAction(text, activityPatterns(cfg)),
          related: { ...related, minScore: numOf(cfg.relatedMinScore, 3, 1, 10) },
          high: { score: highScore, chance: highChanceFor(highScore, cfg.highChance) },
          randomChance: numOf(cfg.randomChance, 8, 1, 100),
        };
      }
      if (action === 'fish-reset') {
        fishState = defaultFishState();
        saveFishNow();
        return { ok: true, status: triggerStatus() };
      }
      if (action === 'clear-archives') {
        const st2 = ensureTriggerState();
        st2.archives = [];
        scheduleTriggerSave();
        return { ok: true, status: triggerStatus() };
      }
      if (!gid) return { ok: false, error: '缺少 groupId' };
      if (!g) return { ok: false, error: '群状态未初始化' };
      const cfg = bot.cfg || {};
      if (action === 'reset') {
        g.recent = [];
        g.counters = {};
        g.last = null;
        g.lastBotAt = 0;
        g.activity = null;
        g.paused = null;
        const st2 = ensureTriggerState();
        st2.events = (Array.isArray(st2.events) ? st2.events : []).filter((e) => String(e.groupId) !== gid);
        scheduleTriggerSave();
        return { ok: true, status: triggerStatus() };
      }
      if (action === 'pause') {
        if (!g.activity) return { ok: false, error: '当前没有进行中的活动' };
        const rec = archiveActivity(gid, g, 'paused', 'manual');
        return { ok: true, archived: rec ? { id: rec.id, title: rec.title, file: rec.file } : null, status: triggerStatus() };
      }
      if (action === 'resume') {
        if (!g.paused) return { ok: false, error: '没有已暂停的活动' };
        const from = g.paused;
        beginActivity(gid, g, from.title || '长期活动', from.id);
        scheduleTriggerSave();
        return { ok: true, status: triggerStatus() };
      }
      if (action === 'end' || action === 'interrupt') {
        const rec = g.activity ? archiveActivity(gid, g, action === 'interrupt' ? 'interrupted' : 'ended', 'manual') : null;
        g.paused = null;
        scheduleTriggerSave();
        return { ok: true, archived: rec ? { id: rec.id, title: rec.title, file: rec.file } : null, status: triggerStatus() };
      }
      if (action === 'start') {
        if (g.activity) return { ok: false, error: '已经有进行中的活动' };
        const a = beginActivity(gid, g, payload.title || '手动活动');
        return { ok: true, activity: { id: a.id, title: a.title }, status: triggerStatus() };
      }
      return { ok: false, error: `未知操作：${action}` };
    }

    async function onTriggerWake(ev) {
      const cfg = bot.cfg || {};
      if (cfg.triggerEnabled !== true) return;
      if (!ev || ev.isGroup === false || !ev.groupId) return;
      if (ev.stopped) return;
      const gid = String(ev.groupId);
      if (!isManagedGroup(gid, cfg.triggerGroups)) return;

      const now = Date.now();
      const g = groupState(gid);
      const text = String(ev.text || '').trim();
      const preview = oneLine(text || `[${(ev.images || []).length || 1} 个非文本消息]`, 80);
      pruneRecent(g, now);
      maybeIdleEnd(gid, g);

      const beforeRecent = g.recent.length;
      const alreadyWoken = Boolean(ev.wake);
      remember(g, ev, text, now);

      const patterns = activityPatterns(cfg);
      let action = detectActivityAction(text, patterns);
      let remote = null;
      const touchedActivity = cfg.activityEnabled === true
        && (g.activity || g.paused || action);
      if (touchedActivity && cfg.activityEmotionCore !== false) {
        remote = await remoteActivity(ev, gid, action, g);
        if (remote?.action && remote.action !== 'none' && remote.action !== 'continue') {
          const allowed = ['start', 'pause', 'resume', 'interrupt', 'end'];
          if (allowed.includes(remote.action)) action = { action: remote.action, keyword: action.keyword };
        }
      }

      // ── 活动进行中：优先处理控制词；其余每条都接 ──
      if (g.activity) {
        if (action && ['pause', 'resume', 'interrupt', 'end'].includes(action.action)) {
          // 活动已经在进行中：再说“继续”只是普通发言，不应该被当成控制词跳过。
          if (action.action !== 'resume') {
          const title = g.activity.title;
          appendActivity(g, ev, text, now);
          const rec = archiveActivity(gid, g, action.action === 'pause' ? 'paused' : (action.action === 'interrupt' ? 'interrupted' : 'ended'), remote?.reason || action.keyword);
          setWake(ev, 'activity-control', `activity-${action.action}`, { groupId: gid, activityId: rec?.id });
          wakeHint(ev, `[反射弧/长期活动] 本地把活动「${title}」标记为${action.action === 'pause' ? '暂停' : (action.action === 'interrupt' ? '中断' : '结束')}并归档；这一条只回应用户的这个意图，不要继续推进活动。`);
          pushEvent({
            ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
            mode: 'activity-control', action: 'wake', reason: action.action, score: null,
          });
          bot.log?.info?.(`[ReflexArc] activity ${action.action} group=${gid} ${title}`);
          return;
          }
        }

        appendActivity(g, ev, text, now);
        if (cfg.activityReplyEvery !== false) {
          setWake(ev, 'activity', 'long-activity', { groupId: gid, activityId: g.activity.id, title: g.activity.title });
          wakeHint(ev, `[反射弧/长期活动] 当前活动「${g.activity.title}」进行中（第 ${g.activity.messageCount} 条）；本地判断这一轮该接。接着聊/推进，不要把它当成系统命令；收到暂停/中断/结束会由本地归档。`);
          pushEvent({
            ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
            mode: 'activity', action: 'wake', reason: 'every-message', score: null,
          });
        } else {
          pushEvent({
            ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
            mode: 'activity', action: 'skip', reason: 'monitor-only', score: null,
          });
        }
        return;
      }

      // ── 已暂停：只认继续/结束，不自动接其他消息 ──
      if (g.paused) {
        if (action?.action === 'resume') {
          const from = g.paused;
          const a = beginActivity(gid, g, from.title || '长期活动', from.id);
          appendActivity(g, ev, text, now);
          setWake(ev, 'activity-start', 'activity-resume', { groupId: gid, activityId: a.id });
          wakeHint(ev, `[反射弧/长期活动] 本地收到继续，活动「${a.title}」重新开始（新段 ${a.id}）；这一条可以自然接上。`);
          pushEvent({
            ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
            mode: 'activity', action: 'wake', reason: 'resume', score: null,
          });
          return;
        }
        if (action?.action === 'end' || action?.action === 'interrupt') {
          const title = g.paused.title;
          g.paused = null;
          scheduleTriggerSave();
          setWake(ev, 'activity-control', `activity-${action.action}`, { groupId: gid });
          wakeHint(ev, `[反射弧/长期活动] 本地确认活动「${title}」${action.action === 'end' ? '结束' : '中断'}；之前暂停的段已归档，不要继续推进。`);
          pushEvent({
            ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
            mode: 'activity-control', action: 'wake', reason: action.action, score: null,
          });
          return;
        }
        pushEvent({
          ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
          mode: 'activity', action: 'skip', reason: 'paused', score: null,
        });
        return;
      }

      // ── 自动开始活动 ──
      if (cfg.activityEnabled === true && cfg.activityAutoStart !== false && action?.action === 'start') {
        const a = beginActivity(gid, g, remote?.title || text.slice(0, 40));
        appendActivity(g, ev, text, now);
        setWake(ev, 'activity-start', remote?.reason || 'start-keyword', { groupId: gid, activityId: a.id });
        wakeHint(ev, `[反射弧/长期活动] 本地/EmotionCore 识别到活动开始「${a.title}」；活动期间每条都会接，直到暂停/中断/结束。这一条按开场回应即可。`);
        pushEvent({
          ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
          mode: 'activity', action: 'wake', reason: remote?.reason || action.keyword, score: null,
        });
        bot.log?.info?.(`[ReflexArc] activity start group=${gid} ${a.title}`);
        return;
      }

      // gate-wake 已经因为 @/引用/关键词唤醒：不再叠加普通模式，避免重复计数。
      if (alreadyWoken) {
        pushEvent({
          ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
          mode: 'none', action: 'skip', reason: 'already-woken', score: null,
        });
        return;
      }

      // ── 普通模式：相关 > 高概率 > 随机（每轮最多一个）──
      let decision = null;
      if (cfg.relatedEnabled === true) {
        const rel = scoreRelated(text, {
          selfNames: selfNames(),
          keywords: splitList(cfg.relatedKeywords),
        });
        const min = numOf(cfg.relatedMinScore, 3, 1, 10);
        if (rel.score >= min
          && (cfg.relatedRequireQuestion !== true || rel.question)
          && canFire(g, 'related', cfg.relatedCooldownSec, cfg.relatedHourlyMax, now)) {
          decision = { mode: 'related', score: rel.score, reason: rel.matched.join('+') || 'score' };
        }
      }
      if (!decision && cfg.highEnabled === true) {
        const hscore = highContextScore({
          recentCount: beforeRecent,
          question: isQuestion(text),
          textLen: text.length,
          lastBotAgoMs: g.lastBotAt ? now - g.lastBotAt : null,
          continued: isContinueLike(text),
          minMessages: cfg.highMinMessages,
        });
        const chance = highChanceFor(hscore, cfg.highChance);
        if (hscore >= numOf(cfg.highMinScore, 3, 2, 7)
          && (cfg.highRequireQuestion !== true || isQuestion(text))
          && canFire(g, 'high', cfg.highCooldownSec, cfg.highHourlyMax, now)
          && probabilityHit(chance)) {
          decision = { mode: 'high', score: hscore, chance, reason: 'hot-context' };
        }
      }
      if (!decision && cfg.randomEnabled === true) {
        const minChars = numOf(cfg.randomMinChars, 4, 0, 200);
        const chance = numOf(cfg.randomChance, 8, 1, 100);
        if (text.length >= minChars
          && !text.startsWith('/')
          && canFire(g, 'random', cfg.randomCooldownSec, cfg.randomHourlyMax, now)
          && probabilityHit(chance)) {
          decision = { mode: 'random', score: null, chance, reason: 'dice' };
        }
      }

      if (!decision) {
        if (cfg.debugLog === true) bot.log?.info?.(`[ReflexArc] skip group=${gid} ${preview}`);
        pushEvent({
          ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
          mode: 'none', action: 'skip', reason: 'no-mode-hit', score: null,
        });
        return;
      }

      markFire(g, decision.mode, now);
      setWake(ev, `reflex-${decision.mode}`, decision.reason, { groupId: gid, score: decision.score });
      if (decision.mode === 'related') {
        wakeHint(ev, `[反射弧/相关] 本地判断这条和你有关（score=${decision.score}，${decision.reason}）；可以自然接话，不想接就短回。`);
      } else if (decision.mode === 'high') {
        wakeHint(ev, `[反射弧/高概率] 本地判断群里正在热聊（score=${decision.score}，p=${decision.chance}%）；可以接一句，别抢话。`);
      } else {
        wakeHint(ev, `[反射弧/随机] 本地随机抽到这一轮接话（p=${decision.chance}%）；没有特别理由，短句即可。`);
      }
      pushEvent({
        ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
        mode: decision.mode, action: 'wake', reason: decision.reason, score: decision.score,
      });
      if (cfg.debugLog === true) bot.log?.info?.(`[ReflexArc] wake ${decision.mode} group=${gid} score=${decision.score} ${preview}`);
    }

    // 鱼群拦截必须在 gate-wake/commands 之前；只记录，不建立模型回合。
    const offFishGate = typeof bot.on === 'function'
      ? bot.on('pre-gate', (ev) => {
        try { onFishGate(ev) } catch (e) { bot.log?.warn?.(`[ReflexArc] fish gate: ${e.message}`) }
      }, { order: 1 })
      : null;
    const offTriggerWake = typeof bot.on === 'function'
      ? bot.on('wake', onTriggerWake, { order: 26 })
      : null;
    const offAfterSend = bot.onAfterSend?.((out) => {
      try {
        const target = String(out?.target || '');
        const m = target.match(/^group:(\d+)$/);
        if (!m) return;
        const g = groupState(m[1]);
        g.lastBotAt = Date.now();
        scheduleTriggerSave();
      } catch {}
    });
    bot.onDispose?.(() => {
      try { offFishGate?.() } catch {}
      try { offTriggerWake?.() } catch {}
      try { offAfterSend?.() } catch {}
      if (trigSaveTimer) clearTimeout(trigSaveTimer);
      trigSaveTimer = null;
      if (fishSaveTimer) clearTimeout(fishSaveTimer);
      fishSaveTimer = null;
      saveFishNow();
      saveTriggerStateNow();
      trigDisposed = true;
    });
    if (bot.shared && typeof bot.shared === 'object') {
      bot.shared.reflexArc = { status: triggerStatus, control: triggerControl };
    }

    function readImageUrl(img) {
      const url = String(img?.url || '').trim();
      if (/^https?:\/\//i.test(url)) return url;
      return '';
    }

    async function analyzeOneImage(ev) {
      const images = Array.isArray(ev?.images) ? ev.images : [];
      const first = images.find((x) => x && !x.isSticker && readImageUrl(x));
      if (!first) return;
      const base = String(bot?.cfg?.emotionCoreUrl || process.env.EMOTIONCORE_URL || '').trim();
      const model = String(bot?.cfg?.visionModel || '').trim();
      if (!base || !model) return;
      const timeout = Math.max(1000, Math.min(120000, Number(bot?.cfg?.visionTimeoutMs) || 20000));
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), timeout);
      try {
        const imgRes = await fetch(readImageUrl(first), { signal: ac.signal });
        if (!imgRes.ok) return;
        const buf = Buffer.from(await imgRes.arrayBuffer());
        if (buf.length > 8 * 1024 * 1024) return;
        const body = {
          model,
          prompt: '用中文简短描述这张图片的内容，并尽量读出图中可见文字。不超过120字；看不清就直说看不清，不要猜。',
          images: [buf.toString('base64')],
          stream: false,
          options: { temperature: 0.1, num_predict: 140 },
        };
        const aiRes = await fetch('http://127.0.0.1:11434/api/generate', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(body),
          signal: ac.signal,
        });
        if (!aiRes.ok) return;
        const data = await aiRes.json();
        const text = String(data?.response || '').replace(/\s+/g, ' ').trim();
        if (text) {
          ev.hint.push(`[反射弧/视觉] ${text.slice(0, 260)}（本地只做粗略看；要细看细节，请调用你自己的多模态能力）`);
          ev._scratch = ev._scratch || Object.create(null);
          ev._scratch['reflex-arc:vision'] = true;
          bot.log?.info?.(`[ReflexArc] vision ${text.slice(0, 80)}`);
        }
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] vision failed: ${e.message}`);
      } finally {
        clearTimeout(timer);
      }
    }

    async function injectMemoryLabHint(ev) {
      if (bot?.cfg?.memoryLabEnabled !== true) return;
      const text = String(ev?.text || '').trim();
      if (text.length < 4 || !/(上次|那次|之前|后来|记得|还记得|那个|那件事|后来呢)/.test(text)) return;
      const base = String(bot?.cfg?.memoryLabUrl || '').trim();
      if (!base) return;
      const timeout = Math.max(100, Math.min(3000, Number(bot?.cfg?.memoryLabTimeoutMs) || 250));
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), timeout);
      try {
        const url = base.replace(/\/+$/, '') + '/recall?q=' + encodeURIComponent(text) + '&limit=1';
        const res = await fetch(url, { signal: ac.signal });
        if (!res.ok) return;
        const data = await res.json();
        const item = Array.isArray(data?.items) ? data.items[0] : null;
        if (!item?.text) return;
        ev.hint.push(`[记忆联想·实验] ${String(item.text).slice(0, 160)}`);
        ev._scratch = ev._scratch || Object.create(null);
        ev._scratch['reflex-arc:memoryLab'] = true;
        bot.log?.info?.(`[ReflexArc] memory-lab hinted ${item.memory_id}`);
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] memory-lab failed: ${e.message}`);
      } finally {
        clearTimeout(timer);
      }
    }

    async function injectFirstContactImpression(ev) {
      const base = String(bot?.cfg?.emotionCoreUrl || process.env.EMOTIONCORE_URL || '').trim();
      const qq = String(ev?.sender?.qq || '').trim();
      if (!base || !qq || qq === String(bot.selfId || '')) return;
      const session = String(ev?.turnCtx?.sessionId || ev?.chatKey || '');
      const state = readState();
      const key = `${session}|${qq}`;
      if (state.seen[key]) return;
      // Mark after one attempt, so a missing impression does not retry every turn.
      state.seen[key] = true;
      saveState(state);
      const timeout = Math.max(100, Math.min(10000, Number(bot?.cfg?.impressionTimeoutMs) || 1500));
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), timeout);
      try {
        const res = await fetch(base.replace(/\/+$/, '') + '/person_impression', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ qq }),
          signal: ac.signal,
        });
        if (!res.ok) return;
        const data = await res.json();
        const text = String(data?.text || '').trim();
        if (text) {
          ev.hint.push(`【人物印象·当天首次接触】${text.slice(0, 500)}`);
          ev._scratch = ev._scratch || Object.create(null);
          ev._scratch['reflex-arc:personImpression'] = true;
          bot.log?.info?.(`[ReflexArc] first-contact impression qq=${qq}`);
        }
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] impression failed: ${e.message}`);
      } finally {
        clearTimeout(timer);
      }
    }

    onBefore('before-turn', async (ev) => {
      try {
        const maxDice = Number(bot.cfg.maxDice) || 100;
        const maxCount = Number(bot.cfg.maxCount) || 10;
        const r = parseDice(ev.text, maxDice, maxCount);
        if (r) {
          const body = r.count === 1
            ? `[反射弧/骰] d${r.sides} = ${r.total}`
            : `[反射弧/骰] ${r.count}d${r.sides} = ${r.rolls.join(' + ')} = ${r.total}`;
          ev.hint.push(body);
          ev._scratch = ev._scratch || Object.create(null);
          ev._scratch['reflex-arc:dice'] = r;
          bot.log?.info?.(`[ReflexArc] ${body}`);
        }
        const incoming = classifyIncoming({
          text: ev.text,
          media: ev.images,
          segments: ev.rawSegments,
          forwardId: ev.forwardId,
          hasForward: ev.hasForward,
          quote: ev.replyToId,
          atSelf: ev.mentionedSelf,
        });
        if (incoming.quoteId) {
          ev._scratch = ev._scratch || Object.create(null);
          ev._scratch['reflex-arc:quoteId'] = incoming.quoteId;
        }
        const forwards = Array.isArray(ev.forwards) ? ev.forwards : (Array.isArray(ev._scratch?.forwards) ? ev._scratch.forwards : []);
        const forwardTexts = [];
        for (const f of forwards) {
          const content = Array.isArray(f?.content) ? f.content : [];
          for (const item of content) {
            const sender = String(item?.sender?.name || item?.sender?.card || item?.sender?.nickname || item?.sender?.user_id || '').trim();
            const text = String(item?.text || item?.message || '').replace(/\s+/g, ' ').trim();
            if (!text) continue;
            forwardTexts.push(`${sender ? sender + '：' : ''}${text}`);
            if (forwardTexts.length >= 3) break;
          }
          if (forwardTexts.length >= 3) break;
        }
        if (forwardTexts.length) {
          ev.hint.push(`[反射弧/转发] 合并转发摘要：${forwardTexts.join(' / ').slice(0, 500)}`);
        } else if (incoming.hasForward || incoming.forwardId) {
          ev.hint.push('[反射弧/转发] 收到合并转发；没有 inline 内容，需要细节时走本地转发索引');
        }
        if (incoming.imageCount) {
          ev.hint.push(`[反射弧/图片] 本地收到 ${incoming.imageCount} 张图片/表情；OCR/视觉内容尚未解析`);
        }
        if (incoming.links?.length) {
          ev.hint.push(`[反射弧/链接] ${incoming.links.slice(0, 2).join(' ')}（仅本地记录，不自动抓取）`);
        }
        await injectFirstContactImpression(ev);
        await analyzeOneImage(ev);
        await injectMemoryLabHint(ev);
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] before-turn: ${e.message}`);
      }
    });

    bot.log?.info?.('[ReflexArc] ready');
  },
};

export { parseDice };

