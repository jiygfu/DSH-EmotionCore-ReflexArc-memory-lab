import test from 'node:test';
import assert from 'node:assert/strict';

import reflex, { parseDice } from '../index.js';

test('parse single die', () => {
  const r = parseDice('来 r d100', 100, 10);
  assert.equal(r.count, 1);
  assert.equal(r.sides, 100);
  assert.ok(r.total >= 1 && r.total <= 100);
});

test('parse multiple dice and clamp', () => {
  const r = parseDice('r 3d6', 100, 10);
  assert.equal(r.count, 3);
  assert.equal(r.sides, 6);
  assert.equal(r.rolls.length, 3);
  assert.equal(r.total, r.rolls.reduce((a, b) => a + b, 0));
  const huge = parseDice('r 99d99999', 100, 10);
  assert.equal(huge.count, 10);
  assert.equal(huge.sides, 100);
});

test('non-dice text has no reflex', () => {
  assert.equal(parseDice('今天吃什么', 100, 10), null);
});

test('reflex registers only a before-turn hint, no tool', () => {
  const tools = new Map();
  const stages = [];
  const bot = {
    cfg: { enabled: true, maxDice: 100, maxCount: 10 },
    log: { info() {}, warn() {} },
    pipeline: { use(stage, fn) { stages.push({ stage, fn }); } },
    registerTool(name, def) { tools.set(name, def); },
  };
  reflex.setup(bot);
  assert.equal(reflex.id, 'reflex-arc');
  assert.equal(tools.size, 0);
  assert.equal(stages.length, 1);
});
