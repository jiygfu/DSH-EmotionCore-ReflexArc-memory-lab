/**
 * EmotionCoreAdapter — dsh-onebot-qq 的本地适配子插件。
 *
 * 目标：
 *   - 不把 SurfCore 的 QQ schema 全部塞给模型；
 *   - 模型只需一个极小的 `ec` 工具 + 几行本地动作说明；
 *   - 私聊/群聊/图片/表情/@/引用/跨群身份/历史由本地 dispatcher 完成；
 *   - EmotionCore 的记忆/情绪通过本地 HTTP 注入和回写。
 *
 * 这是 dsh-onebot 的**子插件**，不是独立 DSH bundle。
 * 部署位置：<dsh-onebot-qq>/plugins/emotioncore-adapter/index.js
 * 不修改 dsh-onebot 核心；它通过官方子插件契约挂载。
 */

import fs from 'node:fs';
import path from 'node:path';

const VERSION = '0.1.0';
const DEFAULT_PREFIX = 'mcp__qq__';

const configSchema = {
  enabled: { type: 'bool', default: true, group: 'EmotionCore', label: '启用适配器', hint: '关闭后只保留通道，不注入 EmotionCore 上下文，也不提供 ec 工具。' },
  emotionCoreUrl: { type: 'str', default: '', group: 'EmotionCore', label: '本地 EmotionCore 地址', hint: '本地记忆/情绪服务的 HTTP 地址；留空则只做 QQ 本地适配，不注入记忆。' },
  timeoutMs: { type: 'int', default: 4000, min: 100, max: 10000, group: 'EmotionCore', label: '本地查询超时（ms）', hint: 'EmotionCore 查询超时时间；超时静默跳过，不阻塞聊天。' },
  injectContext: { type: 'bool', default: true, group: 'EmotionCore', label: '注入本地记忆摘要', hint: '把 EmotionCore 返回的短摘要注入本轮提示；不注入完整记忆正文。' },
  injectInstructions: { type: 'bool', default: true, group: '本地技能', label: '注入本地动作说明', hint: '每轮只注入几行 ec 动作说明，不注册几十个 QQ schema。' },
  recordTurn: { type: 'bool', default: true, group: 'EmotionCore', label: '回写本轮对话', hint: '发送成功后把用户/助手文本写入 EmotionCore；失败静默。' },
  identityFile: { type: 'str', default: '', group: '本地技能', label: '跨群身份缓存文件', hint: '留空 = <dsh-onebot 数据目录>/emotioncore-identity.json。' },
  imageRoots: { type: 'group', default: [], group: '本地技能', label: '允许发图的目录', hint: '绝对路径白名单；留空只允许 dsh-onebot 数据目录和系统临时目录。' },
};

function escapeCq(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/\[/g, '&#91;').replace(/\]/g, '&#93;').replace(/,/g, '&#44;');
}

function cqImage(file) {
  return `[CQ:image,file=${escapeCq(file)}]`;
}

function normalizeTarget(target) {
  const t = String(target ?? '').trim();
  if (/^(group|private):\d+$/.test(t)) return t;
  if (/^\d+$/.test(t)) return `group:${t}`;
  throw new Error('target 必须是 group:<群号> 或 private:<QQ号>');
}

function groupIdOf(target) {
  const m = /^group:(\d+)$/.exec(normalizeTarget(target));
  return m ? Number(m[1]) : 0;
}

function safeImagePath(file, bot, extraRoots) {
  const raw = String(file ?? '').trim();
  if (!raw) throw new Error('image 需要 path 或 url');
  if (/^https?:\/\//i.test(raw)) return raw;
  const abs = path.resolve(raw);
  const roots = [bot?.dataDir, process.env.TEMP, process.env.TMP, ...(extraRoots || [])].filter(Boolean).map((x) => path.resolve(String(x)));
  if (!roots.some((root) => abs === root || abs.startsWith(root + path.sep))) {
    throw new Error('图片路径不在允许目录内');
  }
  if (!fs.existsSync(abs)) throw new Error(`图片不存在: ${abs}`);
  return abs;
}

function truncate(s, n = 600) {
  const t = String(s ?? '').trim();
  return t.length > n ? `${t.slice(0, n)}…` : t;
}

function sharedOf(bot) {
  if (bot?.shared && typeof bot.shared === 'object') return bot.shared;
  if (!bot._emotionCoreShared) bot._emotionCoreShared = {};
  return bot._emotionCoreShared;
}

function traceAdapter(bot, msg, extra) {
  try {
    const file = path.join(bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'logs', 'emotioncore-adapter.log');
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.appendFileSync(file, JSON.stringify({ at: new Date().toISOString(), msg, extra: extra ?? null }) + '\n', 'utf8');
  } catch {}
}

function identityPath(bot) {
  return String(bot?.cfg?.identityFile || '').trim() || path.join(bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'emotioncore-identity.json');
}

function loadIdentities(bot) {
  const shared = sharedOf(bot);
  if (shared.emotionCoreIdentity instanceof Map) return shared.emotionCoreIdentity;
  const map = new Map();
  try {
    const raw = JSON.parse(fs.readFileSync(identityPath(bot), 'utf8'));
    for (const [qq, v] of Object.entries(raw?.people || {})) map.set(String(qq), v);
  } catch {}
  shared.emotionCoreIdentity = map;
  return map;
}

function saveIdentities(bot) {
  try {
    const shared = sharedOf(bot);
    const map = shared.emotionCoreIdentity instanceof Map ? shared.emotionCoreIdentity : new Map();
    const people = Object.fromEntries([...map.entries()].slice(-500));
    const file = identityPath(bot);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify({ version: 1, people }, null, 2), 'utf8');
  } catch (e) {
    bot.log?.warn?.(`[EmotionCoreAdapter] identity save: ${e.message}`);
  }
}

function localInstructions(prefix = DEFAULT_PREFIX) {
  const tool = `${prefix}ec`;
  return [
    '[本地QQ能力] 需要主动操作 QQ 时调用本地 dispatcher：',
    `${tool}(action="send", target="group:123"|"private:456", text="...")`,
    `${tool}(action="reply", target=..., message_id=..., text="...")`,
    `${tool}(action="image", target=..., path="绝对路径或URL")`,
    `${tool}(action="sticker", target=..., query="开心|#03")`,
    `${tool}(action="at", target=..., qq=123, text="...")`,
    `${tool}(action="recall", query="旧事关键词")  // 先取索引；再传 episode_id / memory_id 深入`,
    '被问到旧事、很久以前或具体细节时，先 recall(query=...) 取索引；查到多少说多少，不要用想象补。',
    '不要调用 soulcore_memory：它已下线；QQ 线的记忆查询入口只有上面的 recall。',
    '群聊里 history/recall/user/groups 默认只查本群；不要跨到私聊或其他群。',
    '普通文本回复仍可按当前通道规则输出；不要为发一句话调用多个工具。',
  ].join('\n');
}

function makeDispatcher(bot) {
  const prefix = String(bot?.toolPrefix || DEFAULT_PREFIX);

  async function identityOf(qq) {
    const k = String(qq ?? '').trim();
    if (!/^\d+$/.test(k)) return null;
    const cached = loadIdentities(bot).get(k);
    if (cached) return cached;
    try {
      const groups = await bot?.onebot?.groupList?.();
      const list = Array.isArray(groups) ? groups : [];
      const out = { qq: Number(k), name: '', groups: [] };
      for (const g of list.slice(0, 20)) {
        try {
          const info = await bot?.onebot?.memberInfo?.(g.group_id ?? g.groupId, Number(k));
          if (info?.card || info?.nickname) {
            out.name = info.card || info.nickname || out.name;
            out.groups.push(String(g.group_id ?? g.groupId));
          }
        } catch {}
      }
      const shared = sharedOf(bot);
      const ids = loadIdentities(bot);
      ids.set(k, out);
      saveIdentities(bot);
      return out;
    } catch {
      return null;
    }
  }

  async function dispatch(args = {}) {
    const action = String(args.action || '').trim().toLowerCase();
    const target = args.target ? normalizeTarget(args.target) : '';
    const text = String(args.text ?? '');
    // 当前 turn 是权限边界的唯一可信来源；target 只是模型给的意图。
    const turn = (() => { try { return bot.currentTurn?.() || null } catch { return null } })();
    const turnChat = String(turn?.chatKey || '');
    const groupTurn = Boolean(turn?.isGroup) || turnChat.startsWith('group:');
    const groupId = String(turn?.groupId || (turnChat.startsWith('group:') ? turnChat.slice(6) : '')).trim();

    if (action === 'send') {
      if (!target) throw new Error('send 需要 target');
      const r = await bot.deliver(target, text);
      return { ok: true, action, target: r.target, message_id: r.messageId };
    }

    if (action === 'reply') {
      if (!target) throw new Error('reply 需要 target');
      const messageId = Number(args.message_id || args.messageId || 0);
      if (!messageId) throw new Error('reply 需要 message_id');
      const r = await bot.deliver(target, text, { replyTo: messageId });
      return { ok: true, action, target: r.target, message_id: r.messageId };
    }

    if (action === 'image') {
      if (!target) throw new Error('image 需要 target');
      const file = safeImagePath(args.path || args.url, bot, bot?.cfg?.imageRoots);
      const r = await bot.sendMedia(target, cqImage(file), text);
      return { ok: true, action, target: r.target, message_id: r.messageId, path: file };
    }

    if (action === 'sticker') {
      if (!target) throw new Error('sticker 需要 target');
      const fn = bot?.shared?.stickerSend;
      if (typeof fn !== 'function') throw new Error('表情包子插件未启用');
      const r = await fn({ target, query: String(args.query || args.sticker || '开心'), turnCtx: null });
      return { ok: true, action, target, result: r };
    }

    if (action === 'at') {
      if (!target) throw new Error('at 需要 target');
      const qq = String(args.qq ?? '').trim();
      if (!/^\d+$/.test(qq)) throw new Error('at 需要 qq');
      const r = await bot.deliver(target, `[AT:qq=${qq}] ${text}`);
      return { ok: true, action, target: r.target, message_id: r.messageId, qq: Number(qq) };
    }

    if (action === 'user') {
      const qq = String(args.qq ?? '').trim();
      if (!/^\d+$/.test(qq)) throw new Error('user 需要 qq');
      if (groupTurn) {
        if (!groupId) throw new Error('群聊缺少 groupId，无法校验成员');
        let info = null;
        try { info = await bot.onebot.memberInfo(Number(groupId), Number(qq)) } catch {}
        if (!info) throw new Error('群聊只能查询本群成员');
        return { ok: true, action, user: { qq: Number(qq), name: String(info.card || info.nickname || '').trim(), group: groupId } };
      }
      const info = await identityOf(qq);
      return { ok: true, action, user: info || { qq: Number(qq), name: '', groups: [] } };
    }

    if (action === 'history') {
      if (!target) throw new Error('history 需要 target');
      const gid = groupIdOf(target);
      if (!gid) throw new Error('history 只支持群会话');
      if (groupTurn && (!groupId || target !== `group:${groupId}`)) {
        throw new Error('群聊只能查本群历史');
      }
      const count = Math.max(1, Math.min(50, Number(args.count) || 10));
      const rows = await bot.onebot.groupHistory(gid, count);
      return { ok: true, action, target, count, messages: Array.isArray(rows) ? rows.slice(-count) : [] };
    }

    if (action === 'recall' && !args.query && !args.episode_id && !args.memory_id && !args.person && !args.date) {
      const id = Number(args.message_id || args.messageId || 0);
      if (!id) throw new Error('recall 需要 message_id');
      if (groupTurn) {
        if (!groupId) throw new Error('群聊缺少 groupId，无法校验消息归属');
        let msg = null;
        try { msg = await bot.onebot.msgById(id) } catch {}
        const msgGroup = String(msg?.group_id ?? msg?.groupId ?? '');
        if (!msg || msgGroup !== groupId) throw new Error('群聊只能撤回本群消息');
      }
      const r = await bot.onebot.recall(id);
      return { ok: true, action, result: r };
    }

    if (action === 'recall') {
      const base = String(bot?.cfg?.emotionCoreUrl || process.env.EMOTIONCORE_URL || '').trim();
      if (!base) throw new Error('recall 需要配置 emotionCoreUrl');
      if (groupTurn && !groupId) throw new Error('群聊缺少 groupId，无法隔离记忆');
      const timeout = Math.max(100, Math.min(10000, Number(bot?.cfg?.timeoutMs) || 4000));
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), timeout);
      try {
        const res = await fetch(base.replace(/\/+$/, '') + '/recall', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            query: String(args.query || ''),
            episode_id: String(args.episode_id || ''),
            memory_id: String(args.memory_id || ''),
            person: String(args.person || ''),
            date: String(args.date || ''),
            limit: Number(args.limit || args.count || 2),
            source: 'ec',
            ...(groupTurn ? { scope: 'group', groupId } : {}),
          }),
          signal: ac.signal,
        });
        if (!res.ok) throw new Error(`recall HTTP ${res.status}`);
        return await res.json();
      } finally { clearTimeout(timer); }
    }

    if (action === 'groups') {
      const rows = await bot.onebot.groupList();
      const list = Array.isArray(rows) ? rows : [];
      if (groupTurn) {
        const only = list.filter((g) => String(g.group_id ?? g.groupId ?? '') === groupId);
        return { ok: true, action, groups: only.slice(0, 1) };
      }
      return { ok: true, action, groups: list.slice(0, 100) };
    }

    throw new Error(`未知动作: ${action}`);
  }

  return { prefix, dispatch, identityOf };
}

async function postTurn(bot, rec, pending) {
  const base = String(bot?.cfg?.emotionCoreUrl || process.env.EMOTIONCORE_URL || '').trim();
  if (!base || bot?.cfg?.recordTurn === false || !pending) return;
  const timeout = Math.max(100, Math.min(10000, Number(bot?.cfg?.timeoutMs) || 1500));
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeout);
  try {
    await fetch(base.replace(/\/+$/, '') + '/turn', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        version: 1,
        chatKey: pending.chatKey,
        isGroup: pending.isGroup,
        groupId: pending.groupId || null,
        sender: pending.sender,
        user: pending.text,
        assistant: String(rec?.text || ''),
        ts: new Date().toISOString(),
      }),
      signal: ac.signal,
    });
  } catch (e) {
    bot.log?.warn?.(`[EmotionCoreAdapter] turn write failed: ${e.message}`);
  } finally {
    clearTimeout(timer);
  }
}

async function fetchContext(bot, ev) {
  const base = String(bot?.cfg?.emotionCoreUrl || process.env.EMOTIONCORE_URL || '').trim();
  if (!base) return '';
  const url = base.replace(/\/+$/, '') + '/context';
  const timeout = Math.max(100, Math.min(10000, Number(bot?.cfg?.timeoutMs) || 1500));
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeout);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        version: 1,
        chatKey: ev.chatKey,
        isGroup: ev.isGroup,
        groupId: ev.groupId || null,
        sender: ev.sender,
        text: ev.text,
        images: (ev.images || []).slice(0, 4),
        replyToId: ev.replyToId || null,
      }),
      signal: ac.signal,
    });
    if (!res.ok) return '';
    const data = await res.json();
    return truncate(data?.context || data?.summary || '', 1800);
  } catch {
    return '';
  } finally {
    clearTimeout(timer);
  }
}

export default {
  id: 'emotioncore-adapter',
  title: 'EmotionCore 适配器',
  order: 35,
  version: VERSION,
  configSchema,

  setup(bot) {
    traceAdapter(bot, 'setup', { enabled: bot?.cfg?.enabled !== false });
    if (!bot?.cfg?.enabled) {
      bot.log?.info?.('[EmotionCoreAdapter] disabled');
      return;
    }

    const { dispatch } = makeDispatcher(bot);

    bot.registerTool?.('ec', {
      description: 'EmotionCore 本地动作：send/reply/image/sticker/at/user/history/recall/groups。recall 先返回事件索引，再用 episode_id/memory_id 逐层深入。群聊里 history/recall/user/groups 只查本群；私聊可跨群。',
      parameters: {
        action: { type: 'string', required: true, description: 'send/reply/image/sticker/at/user/history/groups；recall=记忆索引/详情，recall+message_id=撤回' },
        target: { type: 'string', description: 'group:<群号> 或 private:<QQ号>；send/reply/image/sticker/at/history 需要' },
        text: { type: 'string', description: '文本内容；send/reply/image 可用' },
        path: { type: 'string', description: 'image 的本地绝对路径或 http(s) URL' },
        query: { type: 'string', description: 'sticker 的心情/关键词，如 开心、无语、#03' },
        qq: { type: 'string', description: 'at 的目标 QQ；user 的查询 QQ' },
        message_id: { type: 'integer', description: 'reply 引用的消息 ID；recall 的消息 ID' },
        episode_id: { type: 'string', description: 'recall 深入：事件 id' },
        memory_id: { type: 'string', description: 'recall 深入：单条记忆 id' },
        person: { type: 'string', description: 'recall 过滤：人物/QQ' },
        date: { type: 'string', description: 'recall 过滤：YYYY-MM-DD' },
        limit: { type: 'integer', description: 'recall 索引条数，默认 2，最大 3' },
        count: { type: 'integer', description: 'history 条数，默认 10，最大 50' },
      },
      async execute(args) {
        try {
          return await dispatch(args);
        } catch (e) {
          return { ok: false, error: String(e?.message || e) };
        }
      },
    });

    traceAdapter(bot, 'tool-registered');
    const onBefore = (stage, fn) => (typeof bot.on === 'function'
      ? bot.on(stage, fn)
      : bot.pipeline?.use?.(stage, fn));
    traceAdapter(bot, 'registering-before-turn', { on: typeof bot.on, pipeline: !!bot.pipeline });
    try {
      onBefore('before-turn', async (ev) => {
      traceAdapter(bot, 'before-turn', { chatKey: ev.chatKey, text: String(ev.text || '').slice(0, 80), hasOn: typeof bot.on });
      try {
        if (bot.cfg.injectInstructions !== false) ev.hint.push(localInstructions(String(bot.toolPrefix || DEFAULT_PREFIX)));
        const who = ev.sender || {};
        if (who.qq) {
          const shared = sharedOf(bot);
          const ids = loadIdentities(bot);
          const old = ids.get(String(who.qq)) || { qq: Number(who.qq), groups: [] };
          const groups = new Set(old.groups || []);
          if (ev.groupId) groups.add(String(ev.groupId));
          ids.set(String(who.qq), { ...old, name: who.card || who.name || old.name || '', groups: [...groups].slice(-20) });
          saveIdentities(bot);
          traceAdapter(bot, 'identity-saved', { qq: who.qq, groups: [...groups] });
        }
        const pendingMap = pendingOf();
        pendingMap.set(String(ev.chatKey || ''), { chatKey: ev.chatKey, isGroup: ev.isGroup, groupId: ev.groupId, sender: ev.sender, text: ev.text });
        if (bot.cfg.injectContext !== false && (bot.cfg.emotionCoreUrl || process.env.EMOTIONCORE_URL)) {
          const ctx = await fetchContext(bot, ev);
          traceAdapter(bot, 'context-result', { chars: ctx.length });
          if (ctx) ev.hint.push(`[EmotionCore] ${ctx}`);
        }
      } catch (e) {
        bot.log?.warn?.(`[EmotionCoreAdapter] before-turn: ${e.message}`);
      }
      });
      traceAdapter(bot, 'before-turn-registered');
    } catch (e) {
      traceAdapter(bot, 'before-turn-register-error', { message: String(e?.message || e), stack: String(e?.stack || '') });
      throw e;
    }

    const pendingOf = () => {
      const shared = sharedOf(bot);
      shared.emotionCorePending = shared.emotionCorePending || new Map();
      return shared.emotionCorePending;
    };

    // before-turn 只记录待回写的一轮；真正落库等出站成功后，避免“模型没发出去也记了”。
    const pendingMap = pendingOf();
    bot.onAfterSend?.((rec) => {
      traceAdapter(bot, 'after-send', { target: rec?.target, chars: String(rec?.text || '').length });
      try {
        const key = String(rec?.target || '');
        const pending = pendingMap.get(key) || [...pendingMap.values()].slice(-1)[0];
        if (!pending) return;
        pendingMap.delete(key);
        void postTurn(bot, rec, pending);
      } catch (e) {
        bot.log?.warn?.(`[EmotionCoreAdapter] after-send: ${e.message}`);
      }
    });

    traceAdapter(bot, 'after-send-registered');
    bot.log?.info?.(`[EmotionCoreAdapter] ready (prefix=${bot.toolPrefix || DEFAULT_PREFIX})`);
  },
};
