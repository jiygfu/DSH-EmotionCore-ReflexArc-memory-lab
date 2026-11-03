# ReflexArc

`dsh-onebot-qq` 的本地反射弧子插件。它只做确定性判断和本地提示，不注册
模型工具；QQ 动作仍然走 EmotionCoreAdapter 的 `ec` dispatcher。

```text
<dsh-onebot-qq>/plugins/reflex-arc/index.js
```

## 能力

- L1 预处理：骰子、首次接触人物印象、图片理解、memory-lab 联想
- 群聊触发（设置页下级标签）：
  - 相关触发
  - 随机触发
  - 高概率搭话
  - 长期活动
  - 鱼群记录
  - 调试
- 长期活动：开团/跑团等开始 → 活动期间每条都接 → 暂停/中断/结束归档
- 鱼群记录：识别 `肥鱼/机器人/AI/bot` 等群友，只记录不搭话，并给 L4
  人物印象打标签

骰子结果以 `[反射弧/骰]` 注入本轮；其余触发只写 `ev.wake` / `ev.hint`，
不额外发消息。

## 设置页

`REFLEX_TABS`（client.js）在「反射弧」设置页内部渲染：

```text
总览 / 相关触发 / 随机触发 / 高概率搭话 / 长期活动 / 鱼群记录 / 调试
```

总开关 `triggerEnabled` 默认关闭。群聊触发只有在 `gate-wake` 的
「群聊必须被叫才回」打开时才是决定者；如果 gate-wake 把整群当对话态，
每条消息已经唤醒，反射弧模式会被绕过。

## 状态与归档

```text
state/reflex-impressions.json   首次接触人物印象
state/reflex-trigger.json       每群最近消息/计数/活动/决策
state/reflex-activities/        长期活动归档 JSON
state/reflex-fish.json          鱼群成员标签
state/fish-records.jsonl        鱼群只记录消息
```

归档只写本地文件，不写 EmotionCore 记忆库。

## 鱼群记录边界

`pre-gate` 在 gate-wake/commands 之前运行：

```text
命中标签 → 追加 fish-records.jsonl
        → ev.stopped = true
        → 不进入模型、不 @、不回复、不主动私聊
        → 可选 POST EmotionCore /person_tag 写 L4 标签
```

标签默认 `肥鱼,机器人,AI,bot,人工智能,机械`，可在「触发/鱼群」修改。
「清空鱼群标记」只清本地状态，不删已写入 JSONL，也不删 EmotionCore 人物标签。

## 配置

`pluginConfig['reflex-arc']`，主要字段：

```json
{
  "enabled": true,
  "triggerEnabled": false,
  "triggerGroups": [],
  "relatedEnabled": false,
  "randomEnabled": false,
  "highEnabled": false,
  "activityEnabled": false,
  "fishEnabled": false,
  "fishTags": "肥鱼,机器人,AI,bot,人工智能,机械",
  "fishTagPerson": true
}
```

完整 schema 在 `plugins/reflex-arc/index.js` 的 `configSchema`。

## 测试

```bash
node --test test/reflex.test.mjs test/trigger.test.mjs
```

当前覆盖 18 项：骰子、相关/随机/高概率、长期活动暂停/继续/归档、
EmotionCore 远端标题、已唤醒消息、鱼群拦截与记录。
