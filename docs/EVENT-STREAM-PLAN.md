# 事件流与上下文压力整理计划

状态：Phase 1 shadow 已开始；只读，不写生产库，不调用 API。  
目标：在不改变现有 L0–L5 记忆层级和现有 `episodes`/L5 注入的前提下，增加一层可选的“session chunk → event stream”派生索引，并把 API 上下文压力作为本地整理触发点。

## 1. 结论

可行。新结构只做**增量派生表**，不替换：

- 原始 memories；
- 现有 `episodes` / L2 事件索引；
- 现有 L3/L4/L5 检索与注入；
- 现有 people / affect / handoff。

新增的 `session_chunks`、`event_streams`、`event_memory_links`、`event_summaries`、`memory_lifecycle` 都是**可关闭、可回滚的索引层**，不进入新的提示词层。

## 2. API 上下文指标

不需要自己实现 tokenizer。DSH 已有：

- `ctx.tokenMeter.measure(session)`：返回 `totalTokens`、`surfaceTokens`、baseline、surface nodes；
- session projection `contextPressure`：
  - `surfaceTokens`
  - `contextWindow`
  - `pressureTokens`
  - `sampledSurfaceTokens`
- `contextBreakdown`：system / tools / message tokens。

原始 DeepSeek API 的 `usage` 只有 token 计数，**不直接给上下文百分比**；DSH 的 `contextPressure` 已经是归一化后的压力指标，直接用。

触发建议：

```text
ratio = pressureTokens / contextWindow
ratio >= 0.80  -> 记录 context_pressure，触发本地整理检查点
ratio >= 0.90  -> 交给 DSH 原生 compaction，不重复造轮子
```

约束：

- 以 `pressureTokens` 为准，`surfaceTokens` 只做诊断；
- `contextWindow` 从当前 route 读取，不写死；
- 每个 session 只触发一次，或每 N tokens/10 分钟去抖；
- 80% 是**原生 compaction 之前的事件快照点**，不是另起一套压缩；
- 不阻塞当前回复，异步执行；
- 原生 compaction 仍负责真正的上下文压缩，我们不替代它。

### 80% 预压缩事件快照

利用 API 自己即将压缩的时机，在压缩前留下事件判定材料：

```text
80% pressure
  → 本地收集：当前未完成项、最近 chunks、pinned memories
  → 可选：一次性 structured event snapshot（小包，不是全量 context）
  → 原生 compaction（API 自己压缩）
  → 本地用 compaction summary + 快照整理事件
```

原则：

- **不做一个 80% 全量上下文的额外调用**；用事件包，避免把上下文费用翻倍；
- 事件包只含最近相关 chunks、未完成项、具体记忆摘录；
- 如果原生 compaction summary 可用，优先复用；事件包调用只是补充；
- 事件快照要记录 `domain`、`confidence_tier`、`reference_weight`；
- 快照失败不阻塞 compaction；本地 extractive summary 兜底。

### 不让快照撑爆上下文

在发快照请求前先留预算：

```text
input_budget = contextWindow - pressureTokens - output_reserve
```

- `output_reserve` 至少 1–2k tokens；
- 事件包按预算裁剪，只保留最相关的 chunks / 未完成项 / 锚点；
- 预算不足就跳过结构化快照，使用本地摘要；
- 80% 之后不再发大请求，避免把上下文推到 overflow；
- 每个压力 epoch 只发一次，失败不重试风暴。

## 3. 事件定义

### session chunk

同一 `conversation_key` 内，按时间间隔（默认 20 分钟）和最大条数切出的连续聊天串。

### event stream

跨 chunk、跨天可能属于同一件事的事件串。一个 stream 可由一个或多个 chunk 组成。

### 分类

```text
micro   一两句、表情、复读、纯吹水；不进入长期事件
normal  普通多轮事件；本地摘要
major   承诺、长期需求、知识问题、决策、冲突、重要情绪；可进入可选 API 压缩
```

### 事件优先：扮演/跑团/情景模拟

如果判定为 `roleplay_entertainment`：

```text
content_class       roleplay_entertainment
long_term_eligible  false
signal_scope        fiction
event_class         最多 normal（娱乐归档）
```

其中出现的“答应/明天/继续/承诺”是 **in-fiction commitment**：

- 只作为该娱乐事件的内部状态；
- 不升级为长期人格承诺；
- 不进入长期待办/好奇跟进；
- 不因为角色扮演里的“知识问题”变成 major；
- 只保留事件摘要和可查文本。

判定必须同时避免误伤技术讨论：出现较多 `模型/代码/API/上下文/数据库/配置` 时，不按扮演处理。

### 游戏记忆字段

游戏/跑团内容仍然要可回忆，但降低置信度和人格效力：

```text
domain             real / roleplay
content_class      roleplay_entertainment
signal_scope       fiction
confidence_tier    比普通对话低一级
reference_weight   0.5–0.7（仍可检索、可回忆）
long_term_eligible false
personality_eligible false
emotion_boost      fun / curiosity（适度提高，不变成长期人格承诺）
```

解释：

- 游戏里的承诺、好奇、知识、长期待办，**不是完全丢弃**；
- 检索时可以回忆起“这是在游戏里发生的”；
- 置信度比现实事件低一级，避免把虚构承诺当成现实承诺；
- 保留参考权重，保证将来能准确调出；
- 游戏期间的快乐/好奇可以适度提升情绪权重，但不改变长期人格方向。

绑定表建议加：

```text
domain
confidence_tier
reference_weight
personality_eligible
signal_scope
```

## 3.5 跨天与未完成标记

不新增第二套定时器。跨天仍复用现有：

```text
thread_loops
  thread_id
  status        waiting / paused / closing
  anchor_text
  anchor_at
```

- `event_stream` 只做派生索引，**thread_id 与现有 thread_loops 对齐**；
- 未完成事项写入/更新 `thread_loops` 的 `status` / `anchor_at`；
- 现有跨日再触发继续读 `anchor_at`，行为不变；
- 一个 stream 对应一个 loop，避免重复提醒；
- 若 stream 没有未完成项，不创建 loop；
- 旧 `episodes`/L5 仍读 `thread_loops`，不需要新注入层。

游戏/扮演线程额外约束：

```text
thread_loops.domain = roleplay
anchor_at = NULL              # 不进入现实定时提醒
fiction_anchor_at = ...       # 仅用于游戏内回忆
real_followup_allowed = false
```

现有跨日定时器只处理 `domain=real` 且 `anchor_at` 到期的 loop；游戏内“明天/下次”不会在现实中提醒。

## 3.6 快照落地前的本地校验

API 快照不是直接入账，先做本地证据校验：

```text
event.anchor_quotes
  → retrieval.search_memories
  → 本地 exact / token / embedding 分数
  → verified / weak / unmatched
```

- `verified`：quote 能在 raw memory 中找到，才允许写 `event_memory_links`；
- `weak`：保留为候选，不自动绑定；
- `unmatched`：只存快照，不写事件；
- roleplay 的 effective_confidence 再降一级，reference_weight=0.60；
- API 摘要不能替代 anchor 证据。

已新增只读 shadow：

```text
soulcore/event_snapshot_bind.py
scripts/event_snapshot_shadow.py
```

单条 fixture 测试中，exact quote 的绑定分数为 1.00，状态 `verified`；没有写生产绑定。

### 快照落地（默认 dry-run）

```text
soulcore/event_snapshot_apply.py
scripts/event_snapshot_apply.py
```

- 只有 `verified` 的锚点才会生成 `event_streams` / `event_summaries` / `event_memory_links`；
- 默认只打印计划，`--write` 才写库；
- 仍不更新 `thread_loops`，不自动关闭事件；
- roleplay stream 写 `personality_eligible=0`、`reference_weight=0.60`。

临时库验证通过：1 个 verified fixture → 1 stream / 1 summary / 1 link。

## 4. 本地匹配

先规则/向量，2B 只做模糊候选复核。

候选条件：

- 同 `conversation_key`；
- 14 天内；
- 至少一个共同参与者；
- 共享罕见词/实体/项目名；
- 或存在显式回指（上次/昨天/继续/还没/说好的）；
- 或旧 stream 有未完成事项，当前 chunk 像回应。

打分：

```text
0.30 embedding
+0.20 罕见词/实体
+0.20 未完成事项
+0.10 参与者
+0.10 显式回指
+0.10 时间接近
```

阈值：

```text
>=0.75       自动拼接
0.55–0.75    2B 复核
<0.55        新 stream
```

原则：不确定就不拼；不跨私聊/群聊自动拼；一条 chunk 默认只属于一个 stream。

## 5. 2B 的边界

适合：

- 两个短 chunk 是否同一事件；
- 输入只有旧 stream 摘要 + 未完成事项 + 新 chunk 摘要/引语；
- 输出 `same_event` / `confidence` / `reason`；
- 仅灰区候选。

不适合：

- 一次看全天；
- 自主决定事件边界；
- 可靠写长摘要；
- 判断事件是否完成；
- 替代事实绑定。

## 6. 本地摘要与绑定

默认使用抽取式摘要：

- 首条、末条、最高重要度引语；
- 承诺句、知识问题；
- `event_memory_links` 绑定具体记忆。

绑定角色：

```text
commitment
long_term_need
knowledge_gap
decision
anchor
participant_context
normal
```

先绑定，再压缩。API 只能重写已整理好的事件包，不能删除绑定。

## 7. 可选 API 压缩

只对 `major`：

- 一个事件一次调用；
- 输入只含事件摘要 + pinned memories + 关键引语；
- 输出 summary / key_points / commitments / open_items；
- 每晚 0–2 次或 token 上限；
- 失败/无 Key 回退本地摘要；
- 不让 API 决定 `closed/open`。

## 8. 未绑定记忆

事件绑定后仍未归属的记忆，按本地规则分级：

```text
long    30–90 天
medium  14–30 天
low     7–14 天，affect_weight=0
micro   1–3 天，affect_weight=0
```

只改状态/权重/保留期；不删除原文；过期后 archived，仍可检索。

## 9. 与现有层级的关系

```text
原始 memories                        不变
  ↓
session_chunks / event_streams       新增派生索引
  ↓
event_memory_links                   新增绑定
  ↓
episodes / L2                        继续存在；可选的 stream_id
  ↓
现有 L3/L4/L5                        不变
```

- 不新增提示词层；
- 不改变 L5 选择逻辑；
- event summary 只作为现有 L2/L5 可选的摘要来源；
- 所有新表可通过 feature flag 关闭；
- 旧数据不迁移、不改写。

## 10. Phase 1 shadow

脚本：

```text
scripts/event_stream_shadow.py
```

只读当前 `soulcore.db`，按 conversation + 20 分钟间隔切 chunk，输出 micro/normal/major 和本地抽取摘要。

首轮结果（2026-11-03，校准前）：

```text
78 条原始消息
6 个 chunk
1 micro / 1 normal / 4 major
```

问题：`major` 触发过宽，角色扮演里的“继续/知识”也被当成 major。

加入 `roleplay_entertainment` 优先判定和技术讨论防误伤后：

```text
1 micro / 3 normal / 2 major
roleplay chunks:
  domain=roleplay
  content_class=roleplay_entertainment
  confidence_tier=low
  reference_weight=0.60
  long_term_eligible=false
  personality_eligible=false
  emotion_boost=fun/curiosity
技术讨论 chunk: major + domain=real + long_term_eligible=true
```

仍不启用生产写入；先继续校准和做候选匹配。

### Phase 2 shadow：本地候选匹配

新增：

```text
soulcore/event_streams.py
  load_loops()          读取现有 thread_loops（跨日标记仍以它为准）
  match_chunk()         同 conversation_key、跨日、同 domain 的本地候选
  classify_match()      auto / gray / new_stream
```

2026-11-03 结果：

```text
6 个 chunk
2 个 gray_candidate / 4 个 new_stream
0 个 auto_candidate
roleplay chunk 只匹配 roleplay loop
real chunk 只匹配 real loop
没有跨域误配
```

本地 `nomic-embed-text` 已接入，但仅作为候选分数的一部分；没有自动合并任何 stream。  
下一轮需要加入：

- 未完成事项匹配；
- 显式回指（上次/继续/还没/说好的）；
- 罕见实体/项目名权重；
- 2B 只复核 gray candidate。

在加入这些之前，**不会自动合并任何 stream**。

## 11. 执行顺序

1. Phase 1：shadow 切 chunk，校准 micro/normal/major。
2. Phase 2：本地候选匹配，输出 stream 候选，不写生产。
3. Phase 3：2B 只复核灰区，和规则对比。
4. Phase 4：写 `event_memory_links` + 本地摘要。
5. Phase 5：未绑定记忆分级与过期。
6. Phase 6：可选 API 压缩；默认关闭，先 shadow 对比。
7. 用人工标签和 shadow 结果评估后，再逐项启用。

## 12. 评估指标

```text
chunk 数量 / micro 比例
important 记忆绑定覆盖率
stream 合并 precision（人工抽检）
错误合并率
摘要反查 raw memory 成功率
每晚 API 调用数 / tokens
80% contextPressure 触发次数
触发后整理是否在下一轮前完成
```
