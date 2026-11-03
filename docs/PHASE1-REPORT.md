# Phase 1 真实记忆测试报告

日期：2026-10-29  
范围：本地记忆 + 本地评价 + 情感汇总  
模型：`huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M`  
数据：8 条合成记忆 + 5 条 SurfCore 当前角色最近的非敏感记忆  
约束：只读 SurfCore、不注入云端、不改 persona、不计算/注入 P

---

## 1. 结果概览

| 指标 | 结果 |
|---|---|
| 记忆总数 | 13（demo 8 + surfcore 5） |
| 评价成功 | **13/13** |
| 评价失败 | 0 |
| JSON 合法率 | **100%** |
| `has_impact=true` | 3/13（约 23%） |
| 冷启动延迟 | 12.6s |
| 热态延迟 | 2.1–4.7s |
| 热态中位数 | 4.5s |
| 含冷启动 p95 | 12.6s |

只读同步结果：

```text
imported_new: 5
skipped_sensitive: 0
skipped_empty: 0
character: 傲娇助手
```

没有导入敏感记录；没有写 SurfCore；没有调用云端。

---

## 2. 情感汇总（13 条加权）

| 维度 | 值 |
|---|---:|
| security | 0.719 |
| trust | 0.643 |
| self_efficacy | 0.605 |
| caution | 0.365 |
| sociability | 0.330 |
| openness | 0.414 |
| valence | 0.399 |
| arousal | 0.331 |
| stress | 0.325 |
| unresolved | 0.281 |

这组数值只能说明“这批样例整体偏安全、偏正面、低唤醒”，**不能当成人格已经成立**。

---

## 3. 好的地方

1. **流程闭环成立**：只读同步 → 评价 → 入库 → 情感汇总，全部跑通。
2. **JSON 稳定**：13/13 通过，`format` + schema 有效。
3. **影响稀疏**：大多数事件 `has_impact=false`，符合“日常不轻易改人格”。
4. **速度可接受（热态）**：2–5 秒/条，适合闲时潜意识维护，不阻塞说话。
5. **没有越界**：没有写 SurfCore，没有把记忆发给云端。

---

## 4. 问题：评价有“安全模板”倾向

维度分布：

| 维度 | 均值 | 最小 | 最大 | 标准差 |
|---|---:|---:|---:|---:|
| security | 0.715 | 0.50 | 1.00 | 0.117 |
| trust | 0.638 | 0.50 | 1.00 | 0.121 |
| self_efficacy | 0.600 | 0.50 | 1.00 | 0.141 |
| caution | 0.369 | 0.00 | 0.60 | 0.132 |
| sociability | 0.331 | 0.00 | 0.50 | 0.120 |
| openness | 0.415 | 0.00 | 0.60 | 0.135 |
| valence | 0.385 | 0.00 | 1.00 | 0.298 |
| arousal | 0.331 | 0.00 | 0.70 | 0.154 |

问题：

- 很多记录落在 `0.7 / 0.6 / 0.5 / 0.4 / 0.2 / 0.3` 这套固定组合附近；
- `security` 偏高、`caution` 偏低，哪怕文本里有一些冲突/不确定；
- `valence` 偶尔被拉到 1.0，例如一条玩笑式的群聊文本；
- `evidence` 有时是解释/推测，而不是直接引用原文；
- 真实记录缺少“谁说的 / 是不是她自己说的”上下文，模型可能把她的发言当成外部事件评价。

**结论：现在可以用作“流程验证”，还不能用作 P 的可靠输入。**

---

## 5. 下一步修正

1. **给评价器加 context**：
   - `source`、`scope`、`speaker`、`isSelf`、`createdAt`、`tags`、`importance`
   - 让模型知道“这是她自己的发言 / 别人对她说的话 / 群聊背景”
2. **加校准集**：
   - 明确正向、负向、冲突、陌生、成功、失败各 2–3 条；
   - 检查维度排序是否符合直觉，而不只看 JSON 合法。
3. **限制 evidence**：
   - 必须是原文短句，不允许解释；
   - 无直接证据 → 降低 confidence，而不是编。
4. **重跑 5 条真实记录**，对比加 context 前后差异。
5. 通过后再做 P 的 shadow 计算。

---

## 6. 结论

Phase 1 的**管道**已经成立：  
本地记忆、只读同步、本地评价、情感汇总、失败回退都跑通了。

但 Phase 1 的**测量质量**还不只差一点：  
评价器倾向于给出安全、正面、低冲突的模板值，真实记录又缺少说话者上下文。

所以现在不应进入人格实装；先做 **context + 校准**，让评价有区分度，再谈 P。

---

## 7. Context 重测（5 条真实记录）

给评价器加上 `source / scope / speaker / isSelf / tags / importance / createdAt` 后，在数据库副本上重跑 5 条真实记录：

- 5/5 成功，0 失败。
- 最明显的变化：一条“她自己说的群聊玩笑”从 `valence=1.0` 降到 `0.2`，不再被当成极端正面事件。
- 平均变化：
  ```text
  security -0.02
  trust    -0.02
  efficacy +0.04
  caution  +0.02
  valence  -0.18
  arousal  -0.04
  ```
- 结论：context 能修正“谁说的/是不是她自己说的”造成的误判，但**维度区分度仍然偏低**，还没有解决模板化问题。

---

## 8. 日终巩固测试

在副本上执行 `consolidate --mode day_end`：

```text
scanned 13
kept     6
ignored  7
```

- 6 条保留：主要是有 `has_impact`、较高 importance 或较高 unresolved 的合成事件。
- 7 条忽略：2 条低影响合成事件 + **全部 5 条真实休闲对话**。
- 忽略的事件**不删除文本**，只把 `affect_weight=0`；之后不再参与情感聚合。
- 巩固后的情感汇总 `memory_count=6`，不是 13。

这说明“睡眠只保留重要/上心事件”的机制已经生效。  
但也暴露了一个校准问题：

> 当前 `importance_min=0.50` 对 SurfCore 的记忆重要度刻度可能偏高；5 条真实休闲对话全部被忽略。  
> 这可能正确（它们确实只是闲聊），也可能过严。需要一条“真实重要事件”作为对照，再决定是否降到 0.30 或改用来源内相对分位。

下一步应加校准集，包含明确“重要/上心”的真实或合成事件，确认这个阈值不会把真正重要的事也一起睡掉。

---

## 9. SurfCore 条数上限与全量档案

只读检查确认：

- 活动卡 `maxRecords` 默认 **600**，可配 100–2000；
- 超限会淘汰最不重要、最老的非 pinned / 非 initial / 非 owner 重要记忆；
- 全量档案 `fullMaxRecords` 默认 **0（不限）**，默认字节上限 10GB。

所以：

- **不能只同步活动卡**；活动卡会截断；
- 用 `sync --full` 合并 `memory-card-full.jsonl`；
- 本地 `soulcore` 不设条数上限，只设字节软预算；
- 重要/pinned/initial/高 unresolved 记忆不因容量淘汰；
- 低重要度旧文本未来可移到 cold archive，但不删除。

已在新库验证：

```text
sync --full --limit 1000
→ imported_new: 47
→ from_full: 47
→ 本地 memories: 47
```

这说明本地长期库已经绕开 600 条限制，同时没有改 SurfCore。

---

## 10. 日终 ambient 影响分

清洗前先计算当天“不重要事件”的平均影响：

```text
impact_i = 0.30*|valence| + 0.25*caution + 0.20*unresolved
         + 0.15*arousal + 0.10*(1-security)
         × confidence_factor × self_relevance_factor
```

当前副本结果：

```text
count 7
sum   1.0518
mean  0.1503
flagged false
```

这 7 条低影响事件被清零情感权重，保留文本；6 条重要事件继续参与 affect。

高影响合成测试：

```text
count 3
mean  0.4204
flagged true
reason daily_mean_high
```

说明“普通日常”和“异常高的环境压力”可以区分。  
flag 目前只是**人格复核信号**，不会直接改 P。

---

## 11. 每日上下文与 dream

手动触发 2 条记忆后：

```text
daily context count 2
ids: demo:demo:01, surfcore:mem_f35eea143461a5
```

当天 context 没有把 13 条记忆全部端上来，只包含今天触发过的 2 条。

日终 dream：

```text
today_important 6
random_untriggered 2
sampled 8
P memory_count 6
```

P shadow：

```text
security 0.6166   trust 0.6213   self_efficacy 0.5441
caution 0.4213    sociability 0.4029   openness 0.4606
valence 0.1412    arousal 0.2931
```

P 只存储、只预览，没有注入 SurfCore，也没有改变说话行为。

这组结果验证了：

- 发言层只需要当天触发过的少量记忆；
- 长期重要记忆不被删除，只是平时不进入上下文；
- dream 能把“今天的重要”与“随机旧记忆”一起整理；
- 第二天 context 重置，但 P 与长期记忆保留。

当前仍是数据层，未接 `llm/stream` 注入。

---

## 12. SurfCore 日终整理与日记检查

只读检查结论：

- SurfCore 有每日遗忘整理：`dailyHour=4`，插件每 10 分钟 tick；
- 这是记忆衰减，不是通用睡前日记；
- B站 有独立 `whale-diary.md` / `diary.mjs`，数据源是 B站，不是桌宠；
- `purpose-engine` 有计划/承诺，但没有“第二天计划”文件。

复用结论：

- **复用时机**：可以在 SurfCore 日终维护后/DSH 关闭前跑我们的 dream；
- **不复用数据**：不写 B站 `whale-diary.md`，不混 B站 发言账；
- **复用呈现思路**：日记 + 明天计划 + 可见文件。

本地已实现 `dream --diary`：

```text
数据：6 条今天重要 + 2 条随机旧记忆
模型：本地 Huihui 2B
输出：soulproject/diary/2026-10-29.md
状态：ok
```

样例内容（基于合成 kept 记忆）：

```text
今天我记错了主人说的那件事，有点担心……
明天：确认记错的事 / 整理聊天记录 / 记下新软件
```

质量警告：2B 会把不同记忆揉在一起，甚至补细节。  
当前日记是“可读初稿”，不是事实记录；下一步要加事实约束和一致性检查。

---

## 13. 日终触发与本地/API 边界

### 13.1 实际触发

SurfCore 日终记忆衰减不是“关闭时触发”：

1. 插件启动 8 秒后第一次维护，之后每 10 分钟 tick；
2. 只有 `hour >= 4` 且今天未衰减过，才执行每日衰减；
3. 下次启动若已过 4 点，按错过天数补跑，最多 30 天；
4. 设置页「记忆卡 → 立即整理」只做摄取/归档/压缩，UI 不传 `forceDecay`，**不保证强制衰减**；
5. DSH 关闭时只 `memoryCardTimer.stop()`，**没有退出前最终整理钩子**；
6. B站 `whale-diary.md` 不跟关闭绑定。

结论：

- 4 点前关电脑：本次不会在关闭时整理；下次启动过 4 点会补跑；
- 4 点后关：如果 10 分钟 tick 已经跑过，则已整理；否则可能没跑；
- “立即整理”不是睡前按钮。
- 手动可靠入口：`soulproject\sleep.cmd`（本地数值层），然后关 DSH。

### 13.2 本地/API 边界

本地只做：
- 情感/评价数值；
- 记忆索引、触发、daily context；
- 清洗、ambient、dream 抽样、P shadow；
- sleep packet。

高层 API 做：
- 日记、明天计划、复杂叙事；
- 规划和目的推理；
- 最终人格措辞。

所以 `dream --diary` 只是实验；最终应由 SurfCore API 消费 sleep packet 后生成。

---

## 14. 预发送检索与熟悉感

之前只有字段，没有召回逻辑；现在补了 `retrieval.py`。

实测：

```text
query: 主人夸我记事清楚
id: demo:demo:01
similarity: 0.8031
familiarity: 0.0 → 0.2008
fluency: 0.4718
```

这条旧记忆被标记为今天触发，进入当天 context。  
没有调用模型，没有云端。

当前仍是“可调用模块”，还没有挂到 SurfCore 的 `llm/stream` 预发送钩子；  
下一步用真实待发送文本调用 `retrieve()`，再验证熟悉感是否影响上下文选择。

---

## 15. llm/stream shadow bridge

已安装独立 bundle `@soulproject/soul-bridge`，不改 SurfCore。

验证日志：

```json
{
  "provider": "deepseek-official",
  "model": "deepseek-flash",
  "text_chars": 16,
  "marked": false,
  "result": {
    "ok": true,
    "p_memory_count": 13
  }
}
```

说明：

- 钩子已激活；
- 只记录，不修改请求；
- 没有记录原文；
- shadow 失败不会影响说话；
- `mark:false`，暂不更新 familiarity。

日志位置：`soulproject/data/shadow-bridge.jsonl`。  
下一步用更长文本验证检索命中，再比较 `mark:true`。

---

## 16. 群成员身份与每日关系

真实 inbox：

```text
总行数 69
本人 44
非本人 25
不同发送者 5
```

主库合并后：

```text
memories 38
people 5
```

人物卡示例：

```text
WindyDaylight  15 条  familiarity 0.85  trust 0.59  valence +0.20
凯坑卓斯        5 条  familiarity 0.46  trust 0.60  valence +0.18
露卡            3 条  familiarity 0.31  trust 0.50  valence +0.17
```

触发一条人物记忆后，daily context 自动带出该人物卡。  
关系值来自该人物相关记忆的 appraisal，不是写死的“好友/陌生人”。

仍待：

- 主人识别（inbox 的 `isOwner` 全为 false）；
- 跨群/私聊分别关系；
- 语义印象（当前只有每日数值摘要）；
- person card 注入发言层。

---

## 17. 人物侧写、关系姿态与 #行动

累计 10 条后生成草稿侧写。真实样本：

```text
WindyDaylight
15 条
familiarity 0.85 / trust 0.59 / valence +0.20 / unresolved 0.37
stance build
profile v1, draft, confidence 0.6
```

侧写字段：

- personality
- speaking_style
- hobbies
- summary
- confidence

关系姿态：

```text
build    → #行动：主动接住对方的话，记住他提过的小事，适度延展；不刻意讨好。
casual   → #行动：自然回应，保持礼貌；不主动深挖对方私事，也不冷淡。
cautious → #行动：简短回应，先观察；不主动透露自己的私事，不轻易承诺。
```

`#行动` 不直接说态度，而是通过行动侧写表达。  
侧写是 `draft`，不是永久标签；后续由高层 API 复核/改写。  
已有草稿后，新增 10 条证据才重新标记 `due`；当天只刷新数值与每日摘要。

---

## 18. Skill Phase A 与社会 shadow

4 个确定性技能：

```text
memory.sync_inbox
memory.people_refresh
memory.consolidate
memory.recall
```

已验证：

```text
skill-route "同步一下群聊记忆" → memory.sync_inbox
skill-run memory.people_refresh → ok, updated 5
```

连续 3 次失败会生成 `skill_improvement_request`，但不会自动修改技能。

社会 shadow：

```text
people_count 5
weighted_trust 0.58
weighted_valence +0.23
unresolved 0.37
stances build 1 / casual 4
```

单测 12/12。  
仍不自动注入发言层。

---

## 19. 本地 daily 管线

```text
sync-inbox → appraise → people.refresh → consolidate → dream → social
```

实测（people 副本，skip appraise）：

```text
inbox new 44 / seen 25
people updated 5
ambient count 22 / mean 0.1391 / flagged false
dream today_important 3 / random 5
P memory_count 3
social build 1 / casual 4
```

不生成日记、不调用高层 API、不写 SurfCore。  
用户入口 `soulproject\daily.cmd`。

---

## 20. Persona 修改与接入边界

`persona.md` 已加“认知取向”：

- 自发偏向人类式思考；
- 讨论相关话题会学习/查证/对照；
- 平时不口头说，只在日记/总结/复盘里写；
- 不宣称意识/灵魂。

`render-context` 已能生成本地：

```text
P 数值
当天触发人物卡
关系姿态 + #行动
侧写草稿
```

文件：`soulproject/data/soulcore-context.md`。

但 **P/person card 还没有进入 SurfCore**。  
`llm/stream` 不能改冻结请求；真正注入需要在 `pet-chat.js` 的 `buildChatSystemPrompt` 加一个读取口，这会改 SurfCore 代码并需要重载，所以停在待批准处。

---

## 21. 桌宠 prompt 注入已上线

用户确认可以关闭重开后，已打最小补丁：

- `pet-chat.js` 增加只读 `soulCoreContext()`；
- `buildChatSystemPrompt` 追加 P/person card/`#行动`；
- 安装版和源码版同步，备份保留；
- `node --check` 通过；
- SurfCore 插件禁用再启用，日志显示重新激活；
- `~/.dsh/surfcore/soulcore-context.md` 已生成；
- `daily` / `sleep` 会自动刷新这个文件。

桌宠实测：

```text
你：你还记得 WindyDaylight 吗？他最近在聊什么？
桌宠：哼，当然记得，就是那个爱琢磨模型能不能模拟人类思维的人嘛…
```

回复引用了人物侧写，说明注入链路生效。

范围：

- ✅ 桌宠
- ✅ QQ（bridge v1/v2 唤醒、角色提示、purpose）
- ✅ B站（主唤醒 + 定时分享，P-only）
- ❌ 没写 SurfCore 记忆卡

QQ bridge 已重启：

```text
PID 34832
SnowLuma 已连接
DSH 已就绪（reserved2）
```

未做真实 QQ 消息端到端测试；已验证语法、启动、连接。

---

## 22. QQ 身份唯一性修复

旧问题：

```text
inbox 去重 = text_hash + speaker(昵称)
```

同名不同 QQ 号 + 同文本，可能被误合并。

现在：

```text
speaker_id 相同才合并
昵称只在没有 senderId 时弱匹配
person_id = qq:<userId>
改名只追加 aliases
```

测试覆盖：

- 同名不同 QQ 号 + 同文本 → 2 个 person；
- 同 QQ 号跨群 + 改名 → 1 个 person，aliases 保留两个名字。

B站：

- `scheduler.js` 主唤醒注入 P；
- `bili-share-scheduler.js` 定时分享注入 P；
- 不注入 QQ 人物卡，避免公开平台隐私串台。

---

## 23. owner 配置完成

用户确认 owner QQ = `<ownerQQ>`。

已设置：

- `config.json.ownerQQ`
- `config.json.purpose.ownerUin`
- 本地 `qq:<ownerQQ>` → `is_owner=1`

bridge 重启后：

- “未配置 ownerQQ”警告消失；
- `private:<ownerQQ>` 被识别为 owner 私聊；
- 当前 bridge PID 33528。

B站按用户要求暂停；`#行动` 输出不过滤。

---

## 24. 表层意识记忆查询工具

新增 `soulcore_memory`：

```text
overview / today / search / person / range / p
```

`range` 支持：

- `date=YYYY-MM-DD`
- `from` / `to`
- `person`（QQ 号/显示名）
- `scope`（group/private/pet）

一次最多 20 条；返回 `matched/returned/truncated`，截断时明确提示不能声称完整。

实现：

- Python `soulcore memory`
- `soul-bridge` 注册为 DSH 工具
- 只读，不写库
- 已实测 overview / person

示例结果：

```text
overview: memories 39, p_memory_count 38
person qq:<ownerQQ>: is_owner true, stance build, profile v1
```

安全边界：工具是全局注册，QQ 群友也能调用；正式群聊前应限制 owner/私聊或按会话过滤。

工具在本机 DSH Host → Python → SQLite 执行，不走 QQ API。  
`soulcore_memory` 现在：

- 普通关键词 `search`（无 person/scope）复用 SurfCore 内置 `recallFullMemory()`；
- 带 person/scope/日期时用本地 SQLite 索引补足；
- 每次调用写 `data/memory-tool-calls.jsonl`；
- `memory-log` 可查看。

截至 2026-10-29 20:25，日志里 6 条全是验证调用，没有 QQ 会话调用记录。

---

## 26. SurfCore sidecar 接通

`export-surfcore` 写出：

```text
<character>/memory/memory-card-full.soulcore.jsonl
```

当前：

```text
enrichment 29
extension   6（5 人物卡 + 1 affect/P）
lines      35
```

SurfCore 读取层已合并 sidecar；  
`recallFullMemory("情感")` 已返回 `soulcore:affect:latest`，  
`recallFullMemory("人物卡")` 已返回人物卡扩展。

DSH 宿主需要重启才能加载最新 `memory-card.js`。

---

## 27. DSH 设置页

已安装 `@soulproject/soulcore-settings`，位置：

```text
Settings → SoulCore
```

包含：

- 状态卡片：工具/DB/sidecar/调用数
- 开关：记忆查询、影子检索、写回标记
- 路径/超时/并发
- 按钮：保存、导出 sidecar、运行评价、修复旧身份、测试查询
- 最近调用记录

已验证开关真实生效：关闭 `memoryTool` 后，`soulcore_memory` 会返回“已在设置中关闭”。

---

## 28. 每日记忆的感受与 delta

评价改为两段式：

```text
第一段：事件评价（无基准数值）
第二段：知道自己精确基准 -> 只生成 felt
delta：控制器计算 第一段 − 基准
```

单条记忆只写：

```text
felt + delta
```

绝对基准只写全局：

```text
soulcore:affect:latest
```

SurfCore 日常记忆卡已能显示：

```text
（当时的感受：……）
（相对基准：信任 -0.30；效价 -0.23；警觉 +0.21）
```

并新增 `## 最近的情绪附注`，避免被记忆条数上限截掉。

已回填 30 条真实记忆的 felt + delta。  
P 仍使用第一段事件评价，不让基准重复加权。

---

## 29. 日初基准与日累计偏移

SurfCore 每日整理不记录 P；SoulCore 原来也只有当前 `p_snapshots`。

新增 `daily_summaries`：

```text
baseline_json   日初 P
end_json        清洗后 P
delta_json      end - baseline
kept/ignored
```

`daily` / `sleep`：

```text
soul-bridge 启动时先抓 baseline（本日第一次登录）
→ daily/sleep 兜底
→ consolidate（affect_weight 清零）
→ dream
→ 写 end / delta
```

`day-summary` 可查。  
当前还没有历史基线；下一次 DSH 启动 / daily / sleep 开始记录。

---

## 30. 评价代码化学习

新增 `appraisal_learning`：

```text
model appraisals
→ feature extraction
→ pattern induction
→ shadow comparison
→ auto only after 5 checks + 70% accuracy
```

当前：

```text
examples 38
patterns 17
mode shadow
```

`pattern-v1` 的产出不进入训练，防止自我强化。  
详见 `docs/APPRAISAL-LEARNING.md`。

---

## 31. 代码优先评分

`appraise_pending` 改成：

```text
每条记忆先 code-v1 评分
→ 普通闲聊直接完成
→ 有价值/困难才升级本地 2B
→ AI 失败保留 code-v1，并通过 SurfCore 现有 /api/test-send 问 owner
```

已测：`收到，哈哈哈` 只产生 `code-v1`，不调用模型。  
AI 失败测试：保留 code 分、调用 owner 反馈。  
19/19 单测通过。

---

## 32. 修正闭环

`appraisal_questions` 保存失败包；`soulcore_memory` 支持：

```text
mode=questions
mode=resolve
```

resolve 新建 `surface-correction` 记忆，表层直接给 8 维评分，不调用本地 AI。  
旧记忆 `affect_weight=0` / `superseded`，sidecar 标 `superseded_by`。  
新修正作为 `soulcore.correction` extension，日常卡隐藏旧记录，全量卡保留。  
20/20 单测通过。

---

## 33. 目的机制情绪种子

`purpose-seed` 把 SoulCore 当日 baseline P 导出为 drive/emotion/urgency；  
SurfCore 目的机制按 45% 混合，缺失/过期时回退原逻辑。  
不新增调度器，不新增模型调用。  
详见 `docs/PURPOSE-INTEGRATION.md`。








---

## 25. 旧记忆身份修补

旧 SurfCore 记忆卡里 5 条没有 senderId/speaker：

```text
4 条 isSelf=true   → self
1 条 isSelf=false  → legacy_unresolved
```

回填后：

```text
self               4
legacy_unresolved  1
resolved          25
synthetic          8
system             1
```

查询结果会带 `identity_status` 和 `identity_notice`。  
`soulcore-context` / persona 也明确：旧记录说话人不明时不要归给主人。




















