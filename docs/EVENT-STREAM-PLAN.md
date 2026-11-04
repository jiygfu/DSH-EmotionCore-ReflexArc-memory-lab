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
- 80% 只做本地整理，不做线上事件判断；
- 不阻塞当前回复，异步执行；
- 原生 compaction 仍负责真正的上下文压缩，我们不替代它。

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

首轮结果（2026-11-03）：

```text
78 条原始消息
6 个 chunk
1 micro / 1 normal / 4 major
```

问题：`major` 触发过宽，角色扮演里的“继续/知识”也被当成 major。  
所以 Phase 1 不启用生产写入，先校准信号和阈值。

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
