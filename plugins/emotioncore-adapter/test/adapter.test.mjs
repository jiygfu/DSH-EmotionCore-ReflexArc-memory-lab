import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import adapter from '../index.js';

function fakeBot() {
  const tools = new Map();
  const stages = [];
  const delivered = [];
  const media = [];
  const afterSend = [];
  const bot = {
    cfg: {
      enabled: true,
      emotionCoreUrl: '',
      injectContext: false,
      injectInstructions: true,
      timeoutMs: 200,
      imageRoots: [],
    },
    dataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'ec-adapter-')),
    toolPrefix: 'mcp__qq__',
    shared: {},
    log: { info() {}, warn() {} },
    deliver: async (target, text) => {
      delivered.push({ target, text });
      return { target, messageId: delivered.length };
    },
    sendMedia: async (target, body, caption) => {
      media.push({ target, body, caption });
      return { target, messageId: media.length };
    },
    pipeline: { use(stage, fn) { stages.push({ stage, fn }); } },
    onAfterSend(fn) { afterSend.push(fn); return () => {}; },
    registerTool(name, def) { tools.set(name, def); },
    onebot: {
      groupList: async () => [{ group_id: 123, group_name: 'g' }],
      groupHistory: async () => [{ message_id: 1 }, { message_id: 2 }],
      recall: async () => ({ ok: true }),
      memberInfo: async () => ({ card: 'Alice', nickname: 'alice' }),
    },
  };
  return { bot, tools, stages, delivered, media, afterSend };
}

test('registers one tiny ec tool and one before-turn hook', () => {
  const { bot, tools, stages } = fakeBot();
  adapter.setup(bot);
  assert.equal(adapter.id, 'emotioncore-adapter');
  assert.equal(tools.size, 1);
  const spec = tools.get('ec');
  assert.equal(spec.parameters.action.required, true);
  assert.equal(stages.length, 1);
  assert.equal(stages[0].stage, 'before-turn');
});

test('send/reply/at dispatch locally through bot.deliver', async () => {
  const { bot, tools, delivered } = fakeBot();
  adapter.setup(bot);
  const ec = tools.get('ec');
  assert.equal((await ec.execute({ action: 'send', target: 'group:123', text: 'hi' })).ok, true);
  assert.equal((await ec.execute({ action: 'reply', target: 'private:456', message_id: 9, text: 'yo' })).ok, true);
  assert.equal((await ec.execute({ action: 'at', target: 'group:123', qq: 789, text: 'hey' })).ok, true);
  assert.equal(delivered.length, 3);
  assert.equal(delivered[0].target, 'group:123');
  assert.equal(delivered[1].target, 'private:456');
  assert.match(delivered[2].text, /\[AT:qq=789\]/);
});

test('cross-group identity and history use local onebot API', async () => {
  const { bot, tools } = fakeBot();
  adapter.setup(bot);
  const ec = tools.get('ec');
  const user = await ec.execute({ action: 'user', qq: 789 });
  assert.equal(user.ok, true);
  assert.equal(user.user.name, 'Alice');
  const hist = await ec.execute({ action: 'history', target: 'group:123', count: 2 });
  assert.equal(hist.ok, true);
  assert.equal(hist.messages.length, 2);
});

test('before-turn injects only a short local capability block, no EmotionCore call when URL empty', async () => {
  const { bot, stages } = fakeBot();
  adapter.setup(bot);
  const ev = { chatKey: 'group:123', groupId: 123, sender: { qq: 789, name: 'bob' }, text: 'hello', hint: [] };
  await stages[0].fn(ev);
  assert.equal(ev.hint.length, 1);
  assert.match(ev.hint[0], /本地QQ能力/);
  assert.match(ev.hint[0], /ec\(action="send"/);
});

test('invalid target/action fail closed without throwing', async () => {
  const { bot, tools } = fakeBot();
  adapter.setup(bot);
  const ec = tools.get('ec');
  const r = await ec.execute({ action: 'send', target: 'bad', text: 'x' });
  assert.equal(r.ok, false);
  assert.match(r.error, /target/);
  const r2 = await ec.execute({ action: 'nope' });
  assert.equal(r2.ok, false);
  assert.match(r2.error, /未知动作/);
});


test('after-send posts the current turn to EmotionCore /turn', async () => {
  const { bot, stages, afterSend } = fakeBot();
  bot.cfg.emotionCoreUrl = 'http://emotioncore.test';
  const calls = [];
  const oldFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) });
    return { ok: true, json: async () => ({ ok: true }) };
  };
  try {
    adapter.setup(bot);
    const ev = { chatKey: 'group:123', groupId: 123, isGroup: true, sender: { qq: 789, name: 'bob' }, text: 'hello', hint: [] };
    await stages[0].fn(ev);
    assert.equal(afterSend.length, 1);
    afterSend[0]({ target: 'group:123', text: 'world' });
    await new Promise((r) => setTimeout(r, 20));
    const turn = calls.find((c) => String(c.url).endsWith('/turn'));
    assert.ok(turn);
    assert.equal(turn.body.user, 'hello');
    assert.equal(turn.body.assistant, 'world');
    assert.equal(turn.body.chatKey, 'group:123');
  } finally {
    globalThis.fetch = oldFetch;
  }
});
