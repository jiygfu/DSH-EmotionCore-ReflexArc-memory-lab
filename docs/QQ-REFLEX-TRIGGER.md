# QQ 群聊反射弧触发

本地反射弧在 `gate-wake` 之后运行，只处理通过门禁的群消息。它不注册新的模型工具，所有判断都是本机规则；长期活动另有一个可选的 EmotionCore `/activity` 复核。

## 打开顺序

1. 设置 →「反射弧」→「总览」：填「接话群」（空 = 所有通过门禁的群），打开「启用群聊接话策略」。
2. 按需打开一个或多个模式页：
   - 相关触发
   - 随机触发
   - 高概率搭话
   - 长期活动
3. 到「调试」页发一条测试文本，或看最近决策。

总开关和各模式默认都关；不会安装完就开始抢话。门禁（屏蔽群、群内黑名单、用户白名单）仍然优先。

> **重要：先确认 gate-wake 的「群聊必须被叫才回」是开。**
> 如果它是关（`gate-wake.groupAtRequired = false`），整群会被当成持续对话，每条消息在 gate-wake 阶段就已经唤醒并回复；反射弧的相关/随机/高概率模式会被绕过，看起来像“没配置也在接话”。这不是双触发，是旧的整群对话模式。要让反射弧决定是否接话，先把它打开。

## 模式

| 模式 | 什么时候接 | 关键约束 |
| --- | --- | --- |
| 相关触发 | 本机别名、句首第二人称提问、接续词达到分数阈值 | 冷却 + 每小时上限；不调用模型 |
| 随机触发 | 每条合格消息按概率掷一次 | 冷却 + 每小时上限 + 最短字数 |
| 高概率搭话 | 最近窗口内有热聊、提问、刚接过话，按较高概率接 | 上下文分门槛 + 冷却 + 每小时上限；和随机模式建议二选一 |
| 长期活动 | 识别到开团/跑团/游戏等开始后，活动期间每条都接 | 暂停/中断/结束会先归档；暂停可继续 |

同一轮最多一个普通模式生效，优先级：相关 > 高概率 > 随机。长期活动进行中优先于所有普通模式。

## 长期活动状态机

```text
(无活动)
  └─ 开始词/EmotionCore 判定 → active
active
  ├─ 普通消息 → 每条回复并写入 transcript
  ├─ 暂停 → paused（当前段归档）
  ├─ 中断 → archived（interrupted）
  └─ 结束 → archived（ended）
paused
  ├─ 继续 → active（新段，记录 resumedFrom）
  └─ 结束/中断 → 清空暂停态
```

归档位置：

- 状态：`<dataDir>/state/reflex-trigger.json`
- 归档：`<dataDir>/state/reflex-activities/<activity-id>.json`
- 只写本地文件，不写 EmotionCore 记忆库。

## EmotionCore 联动

EmotionCore 服务新增 `POST /activity`，根据文本和当前活动返回 `start/pause/resume/interrupt/end/continue` 及置信度。反射弧只在活动相关消息上请求它；请求失败或低于置信度阈值时自动使用本地关键词，并短路 60 秒，避免活动期间每条都等超时。

## 鱼群记录

「触发/鱼群」页可选开启。群友的群名片/昵称命中 `肥鱼/机器人/AI/bot/人工智能/机械`（可改）时：

- 在 `state/reflex-fish.json` 记录成员标签；
- 每条命中成员的群消息写入 `state/fish-records.jsonl`，**只记录，不进入模型、不回复、不主动私聊**；
- 可选调用 EmotionCore `/person_tag`，把标签写进人物印象（L4）；之后 `/context` 的人物行会显示“标签：…”。

这是 gate 之前的静音，`@`、唤醒词、命令也不会触发回复。

## 调试 API

控制台隐藏动作 `reflex-arc`：

```json
{ "id": "reflex-arc", "op": "test", "groupId": "100000001", "text": "你怎么看？" }
```

可用 `op`：`status` / `test` / `start` / `pause` / `resume` / `interrupt` / `end` / `reset` / `clear-archives` / `fish-reset`。
