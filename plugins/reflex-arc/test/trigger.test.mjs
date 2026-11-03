import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import reflex from '../index.js';
import {
  detectActivityAction, detectFishTags, highChanceFor, highContextScore,
  isManagedGroup, probabilityHit, scoreRelated,
} from '../trigger-core.js';

test('fish tags match common identities', () => {
  const tags = ['肥鱼', '机器人', 'AI', 'bot'];
  assert.deepEqual(detectFishTags('肥鱼.卡珊德拉', tags), ['肥鱼']);
  assert.deepEqual(detectFishTags('AI助手', tags), ['AI']);
  assert.deepEqual(detectFishTags('小机器人', tags), ['机器人']);
  assert.deepEqual(detectFishTags('mybot', tags), ['bot']);
  assert.deepEqual(detectFishTags('普通人', tags), []);
});

test('managed group: empty means all, listed means only listed', () => {
  assert.equal(isManagedGroup('123', ''), true);
  assert.equal(isManagedGroup('123', '456,789'), false);
  assert.equal(isManagedGroup('456', '456,789'), true);
  assert.equal(isManagedGroup('123', ['123']), true);
});

test('related score requires explicit evidence', () => {
  assert.equal(scoreRelated('今天天气不错').score, 0);
  assert.ok(scoreRelated('你怎么看这件事？', { selfNames: ['阿雪'] }).score >= 2);
  assert.ok(scoreRelated('阿雪你觉得呢', { selfNames: ['阿雪'] }).score >= 3);
  assert.equal(scoreRelated('阿雪今天吃的面', { selfNames: ['阿雪'] }).question, false);
});

test('activity controls only match short/leading text and skip questions', () => {
  assert.equal(detectActivityAction('暂停一下').action, 'pause');
  assert.equal(detectActivityAction('先停，等我回来').action, 'pause');
  assert.equal(detectActivityAction('继续').action, 'resume');
  assert.equal(detectActivityAction('结束了吗？'), null);
  assert.equal(detectActivityAction('今晚开个跑团吧').action, 'start');
  assert.equal(detectActivityAction('这个剧本真不错'), null);
  assert.equal(detectActivityAction('团灭了，结束').action, 'end');
});

test('high context score and chance', () => {
  const s = highContextScore({ recentCount: 4, question: true, textLen: 12, lastBotAgoMs: 1000, continued: true, minMessages: 3 });
  assert.equal(s, 7);
  assert.equal(highChanceFor(2, 65), 65);
  assert.equal(highChanceFor(7, 65), 95);
  assert.equal(highChanceFor(1, 65), 0);
});

test('probability hit boundaries', () => {
  assert.equal(probabilityHit(0, () => 0), false);
  assert.equal(probabilityHit(100, () => 0.999), true);
  assert.equal(probabilityHit(50, () => 0.2), true);
  assert.equal(probabilityHit(50, () => 0.8), false);
});

function makeBot(dataDir) {
  const handlers = new Map();
  const bot = {
    cfg: {
      enabled: true,
      triggerEnabled: true,
      triggerGroups: ['100000001'],
      relatedEnabled: true,
      relatedMinScore: 2,
      relatedCooldownSec: 0,
      relatedHourlyMax: 100,
      activityEnabled: true,
      activityAutoStart: true,
      activityEmotionCore: false,
      activityArchive: true,
      fishTagPerson: false,
      activityReplyEvery: true,
      debugRecentLimit: 20,
    },
    core: { dataDir },
    log: { info() {}, warn() {} },
    on(stage, fn) { handlers.set(stage, fn); return () => handlers.delete(stage); },
    onAfterSend() { return () => {}; },
    onDispose() {},
    shared: {},
  };
  reflex.setup(bot);
  return { bot, wake: handlers.get('wake'), gate: handlers.get('pre-gate') };
}

function ev(text, over = {}) {
  return {
    isGroup: true,
    groupId: '100000001',
    chatKey: 'group:100000001',
    text,
    sender: { qq: '100000002', name: '管理员' },
    hint: [],
    ...over,
  };
}

test('pre-gate: tagged fish member is recorded and stopped', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'reflex-trigger-'));
  const { bot, gate } = makeBot(dir);
  bot.cfg.fishEnabled = true;
  const e = ev('今天鱼群有什么动静', { sender: { qq: '100000003', name: '肥鱼.卡珊德拉' } });
  gate(e);
  assert.equal(e.stopped, true);
  assert.equal(e.stopReason, 'reflex-arc:fish-silent');
  const status = bot.shared.reflexArc.status();
  assert.equal(status.fish.members.length, 1);
  assert.deepEqual(status.fish.members[0].tags, ['肥鱼']);
  assert.ok(fs.existsSync(path.join(dir, 'state', 'fish-records.jsonl')));
});

test('wake handler: related mode sets wake and hint', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'reflex-trigger-'));
  const { bot, wake } = makeBot(dir);
  bot.cfg.selfAliases = '阿雪';
  const e = ev('阿雪你怎么看？');
  await wake(e);
  assert.equal(e.wake?.kind, 'reflex-related');
  assert.ok(e.hint.some((x) => x.includes('反射弧/相关')));
});

test('wake handler: long activity replies every message, pause archives', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'reflex-trigger-'));
  const { wake } = makeBot(dir);
  const start = ev('今晚开个跑团吧');
  await wake(start);
  assert.equal(start.wake?.kind, 'activity-start');

  const next = ev('我掷骰子');
  await wake(next);
  assert.equal(next.wake?.kind, 'activity');

  const pause = ev('暂停一下');
  await wake(pause);
  assert.equal(pause.wake?.kind, 'activity-control');
  await new Promise((resolve) => setTimeout(resolve, 260));
  assert.ok(fs.existsSync(path.join(dir, 'state', 'reflex-trigger.json')));
  const st = JSON.parse(fs.readFileSync(path.join(dir, 'state', 'reflex-trigger.json'), 'utf8'));
  assert.ok(st.archives.some((a) => a.status === 'paused'));
});

test('wake handler: EmotionCore can supply activity title', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'reflex-trigger-'));
  const { bot, wake } = makeBot(dir);
  bot.cfg.activityEmotionCore = true;
  bot.cfg.emotionCoreUrl = 'http://emotioncore.test';
  const oldFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return {
      ok: true,
      async json() {
        return { ok: true, action: 'start', confidence: 0.9, title: '远端识别活动', reason: 'remote' };
      },
    };
  };
  try {
    const e = ev('今晚开个跑团吧');
    await wake(e);
    assert.equal(calls, 1);
    assert.equal(e.wake?.kind, 'activity-start');
    const status = bot.shared.reflexArc.status();
    assert.equal(status.active[0]?.title, '远端识别活动');
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test('wake handler: random mode respects cooldown', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'reflex-trigger-'));
  const { bot, wake } = makeBot(dir);
  bot.cfg.relatedEnabled = false;
  bot.cfg.randomEnabled = true;
  bot.cfg.randomChance = 100;
  bot.cfg.randomCooldownSec = 3600;
  bot.cfg.randomHourlyMax = 10;
  const first = ev('今天吃什么');
  await wake(first);
  assert.equal(first.wake?.kind, 'reflex-random');
  const second = ev('今天喝什么');
  await wake(second);
  assert.equal(second.wake, undefined);
});

test('wake handler: high-probability mode uses recent context', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'reflex-trigger-'));
  const { bot, wake } = makeBot(dir);
  bot.cfg.relatedEnabled = false;
  bot.cfg.highEnabled = true;
  bot.cfg.highChance = 100;
  bot.cfg.highMinScore = 2;
  bot.cfg.highMinMessages = 1;
  bot.cfg.highCooldownSec = 0;
  await wake(ev('先聊一句'));
  const e = ev('今天这个天气确实不错啊');
  await wake(e);
  assert.equal(e.wake?.kind, 'reflex-high');
});

test('wake handler: paused activity can resume or end', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'reflex-trigger-'));
  const { wake } = makeBot(dir);
  await wake(ev('开团'));
  await wake(ev('暂停'));
  const resume = ev('继续');
  await wake(resume);
  assert.equal(resume.wake?.kind, 'activity-start');
  const end = ev('结束');
  await wake(end);
  assert.equal(end.wake?.kind, 'activity-control');
});

test('wake handler: already-woken messages still count and can end activity', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'reflex-trigger-'));
  const { wake } = makeBot(dir);
  const start = ev('今晚开个跑团吧');
  await wake(start);
  assert.equal(start.wake?.kind, 'activity-start');

  // @/关键词已经唤醒的普通活动消息：不重复决策，但仍进活动记录。
  const mid = ev('我掷骰子', { wake: { kind: 'keyword', keyword: '雪风' } });
  await wake(mid);
  assert.equal(mid.wake?.kind, 'keyword');
  assert.ok(mid.hint.some((x) => x.includes('长期活动')));

  // @ 着说“结束”也必须归档，不能因为已被唤醒就漏掉控制词。
  const end = ev('结束', { wake: { kind: 'keyword', keyword: '雪风' } });
  await wake(end);
  await new Promise((resolve) => setTimeout(resolve, 260));
  const st = JSON.parse(fs.readFileSync(path.join(dir, 'state', 'reflex-trigger.json'), 'utf8'));
  assert.ok(st.archives.some((a) => a.status === 'ended'));
});
