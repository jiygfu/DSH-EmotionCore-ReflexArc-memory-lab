# 记忆分层与上下文预算方案

## 当前执行状态

- P0 能力开关/条件注入：已落地。
- P1 技能清单：已落地（每会话 bootstrap 注入一次）。
- P2 episodes 事件表 + 确定性睡眠摘要：已落地。
- P3 L2 事件卡注入：已落地；有卡片时替代原记忆卡，无卡片自动回退。
- P5 手动 session 预算轮换：已落地（`rotate-over-budget`）。
- P5 工具结果裁剪/自动压缩：已启用 DSH `tool-result-pruner` + `compaction-basic`。
- P5 自动 session 阈值：已接入 `soul-bridge` 15 分钟检查（`data/session-budget.json`）。
- P6 条件注入：表情教程/清单只在有匹配时注入；无匹配时只保留技能清单入口。
- P4 低风险 2B：`episode-polish` 可选润色事件摘要，默认关闭，失败回退抽取式摘要，原文不动。
- 仍待：静态 preset 核心/技能拆分。

## 结论

你的判断基本成立：

- 人类不会把每次对话逐字回放；
- 会把一段经历分成“事件”，保留摘要、关键片段、情绪和未解决点；
- 睡眠/休息后更偏向保存 gist 和重要细节，而不是原始全文；
- 回忆是线索驱动、重构式的，不是每次都全量读取。

但“纯随机浮现”证据不足。更合适的是：

```text
按 相关性 + 重要性 + 情绪显著度 + 未解决度 + 时间
做加权采样，随机只作为扰动/多样性
```

## 论文依据

### 事件分段

Zacks et al. 2007, *Event Segmentation*：  
人会把连续经历切成事件，事件边界影响注意和记忆。

[PubMed](https://pubmed.ncbi.nlm.nih.gov/22468032/)

### 睡眠巩固

Rasch & Born, *About sleep's role in memory*；Stickgold & Walker：  
睡眠不是简单回放，而是重组、概括、保留重要内容。

### 互补学习系统

McClelland, McNaughton & O'Reilly 1995：  
快速海马负责具体经历，慢速新皮层负责语义/统计结构；  
对应到系统：原始记忆是海马，摘要是新皮层索引。

### 遗忘是功能

Richards & Frankland 2017, *The Persistence and Transience of Memory*：  
遗忘不是失败，而是适应性的；保留所有细节会降低泛化。

[PubMed](https://pubmed.ncbi.nlm.nih.gov/28641107/)

### 回忆是线索驱动

Tulving & Thomson 1973, encoding specificity；  
Godden & Baddeley 1975, context-dependent memory：  
回忆需要合适线索，不是均匀随机抽取。

### 智能体记忆的成熟实现

- **Generative Agents**（Park et al. 2023）：memory stream + reflection + retrieval，检索按 recency / importance / relevance。  
  [arXiv](https://arxiv.org/abs/2304.03442)
- **RAPTOR**（Sarthi et al. 2024）：递归摘要树，多级摘要检索。  
  [arXiv](https://arxiv.org/abs/2401.18059)
- **MemGPT / Letta**（Packer et al. 2023）：主上下文 + 外部记忆分页。  
  [arXiv](https://arxiv.org/abs/2310.08560)
- **Lost in the Middle**（Liu et al. 2023）：长上下文中间信息容易被忽略，支持“短而结构化”。  
  [arXiv](https://arxiv.org/abs/2307.03172)

## 推荐架构：三层

```text
L0 原始层：memories / memory-card-full.jsonl / 完整工具输出
L1 事件层：episode 摘要 + 关键引语 + 情绪/未解决点 + 原始 id
L2 唤醒层：本次真正注入的短上下文
```

### L0 原始层

保留全文，但默认不注入。  
用于：

- `soulcore_memory search`；
- 事后审计；
- 被摘要后仍然可以展开原文。

### L1 事件层

新增 `episodes`：

```json
{
  "id": "ep_...",
  "day": "2026-10-31",
  "start_at": "...",
  "end_at": "...",
  "participants": ["owner", "qq:..."],
  "trigger": "wake|purpose|pet|bili",
  "summary": "2~4 句事件总结",
  "key_quote": "最具代表性的一句原话",
  "felt": "...",
  "delta": {"valence": -0.2},
  "unresolved": 0.4,
  "importance": 0.7,
  "raw_ids": ["mem_...", "mem_..."],
  "topics": ["..."],
  "embedding": null
}
```

生成时机：

- 睡眠 / daily 清洗；
- session 轮换前；
- 一次主动搭话结束后；
- 单次对话超过阈值。

摘要失败时用抽取式兜底：第一条 + 最后一条 + 情绪最强一条。

### L2 唤醒层

每次唤醒只组装：

```text
稳定核心（压缩后的角色/安全/工具协议）
+ 当前消息 + 最近 3~5 条
+ 3~5 张事件卡（每条 1~2 行 + 1 句关键引语）
+ 当前身体/欲望提示
+ 只加载这次可能用到的工具说明
```

原始记录不默认进上下文；  
模型要细节时调用 `soulcore_memory` 展开 `episode_id` 或 `raw_id`。

## 随机浮现怎么做

不要 `random.choice(全部记忆)`。推荐：

```text
score = 0.30*relevance
      + 0.25*importance
      + 0.20*recency
      + 0.15*abs(affect_delta)
      + 0.10*unresolved
```

然后：

- 取 top-k；
- 在 top-k 内按 softmax 采样；
- 每次最多 1 条“旧事件”随机浮现；
- 同一天不重复同一条；
- 随机种子可复现，方便调试。

这比纯随机更接近“线索回忆 + 偶发联想”，也能节约上下文。

## 静态 preset 的成熟做法

### 1. 上下文工程

Anthropic 2025, *Effective context engineering for AI agents*：

- 最小必要上下文；
- just-in-time 检索；
- 结构化分段；
- compaction；
- subagent 隔离；
- 外部笔记。

[Anthropic](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

### 2. 渐进披露 / Skills

只在需要时加载完整技能说明；  
常驻的只是“技能名称 + 何时使用”的短卡片。  
DSH 的 skill 机制正适合把 B站长教程、QQ 表情规则、睡眠规则移出常驻 preset。

### 3. 工具结果遮罩 / 裁剪

工具输出保留全文到文件，只注入：

```text
status + 前 3 行 + 后 3 行 + handle
```

需要细节时再读。  
这类 observation masking 已被用于 agent 上下文压缩。

### 4. prompt 压缩

LLMLingua 等可以压缩长 prompt，但有信息损失风险；  
适合压缩“规则/示例”，不适合压缩当前消息和关键引语。

[LLMLingua](https://arxiv.org/abs/2310.05736)

### 5. 子代理隔离

把 B站长流程、终端长输出、搜索长结果交给子代理，  
主对话只收摘要，不把全过程塞进主 session。

## 对当前 SurfCore 的具体建议

1. **preset 12.9k → 6~8k**
   - 保留身份/安全/工具协议/关键行为；
   - B站长教程、表情策略、睡眠细节按需加载。

2. **唤醒 prompt 条件化**
   - 沉睡前等待：只在准备潜水时注入；
   - 表情策略：只在有表情匹配/相关时注入；
   - 收尾规则：只在对话可能结束时注入；
   - token 防爆破：只在接近额度时注入。

3. **工具输出摘要化**
   - 完整结果落盘；
   - 上下文只留摘要 + handle。

4. **会话轮换加阈值**
   - 不只按天；
   - 单 session 超过 N tokens / N turns 也轮换。

5. **SoulCore 新增 episodes**
   - 睡眠时生成；
   - 唤醒时只读事件卡；
   - 需要细节再展开原文。

## 不建议现在做的

- 不要直接删原始记忆；
- 不要纯随机浮现全部记忆；
- 不要用摘要替代原文审计；
- 不要一次性重写全部 prompt；
- 不要在没有 A/B 指标前大改。

## 技能清单：每会话一次，而不是每轮

主模型需要知道“自己有什么功能”，否则会漏用能力；  
但不需要每轮都看到完整清单。

```text
睡眠/换会话后的第一次唤醒
  → 注入一次紧凑技能清单（只含启用的能力）
  → 同一会话后续轮次不再注入清单
  → 需要细节时，主模型用极简 gateway 打开某个技能
  → 能力开关变化时，清单版本变化，才重新注入一次
```

清单只放：

```text
技能名 + 一句话用途 + 什么时候用
```

不放完整教程、长示例、工具参数。

示例：

```text
【可用技能（本次会话已加载清单；需要细节再打开）】
- qq_send_message：发 QQ 消息；私聊/群聊
- qq_send_sticker：发表情包；接梗/安慰/告别
- soulcore_memory：查长期记忆；questions/resolve
- ...
```

规则：

- 只列当前 capability 启用的技能；
- B站/桌宠关掉时，不出现它们的技能；
- 清单总长控制在 1~1.5k 字符；
- 同一会话不重复；
- 清单版本 = capability 集合 + 技能表版本；
- 版本不变就不重注入。

这比“每轮零技能名”更合理：  
主模型知道能力，但清单只付一次成本。

## 固定程序优先，2B 只做低风险辅助

硬判断不要交给 2B：

- 是否需要某个关键技能；
- 是否安全/授权；
- 是否删除/覆盖记忆；
- 是否切换人格/发送消息。

这些由固定程序 + 主模型显式工具调用决定。

2B 只做“错了也不致命”的事：

- 给检索加同义词/关键词；
- 给候选卡打粗略主题标签；
- 对候选卡做重排；
- 把长工具输出压成短摘要（全文仍保留）。

2B 失败/低精度时：

- 回退固定程序的 FTS/BM25/加权规则；
- 不阻塞主流程；
- 不因为 2B 说“没技能”就拒绝能力。

## 技能注入：清单一次，之后零重复

主模型在新会话第一次唤醒时收到一次**紧凑技能清单**；  
同一会话后续轮次不再注入技能名。

```text
新会话第一次唤醒
→ 固定程序读取 capability + 技能表
→ 只生成启用技能的 1 行清单
→ 注入一次，记下 manifest_version

后续轮次
→ 不重复注入清单
→ 需要技能细节：主模型调用极简 gateway
→ 选中后只加载那一张技能卡
```

这样：

- 主模型知道自己有什么功能；
- 清单只付一次成本；
- 不需要每轮注入技能名；
- B站/桌宠关闭时清单里不会出现；
- 技能详情仍然按需加载。

如果主模型在生成中才发现需要技能，保留一个**极简 gateway**：

```text
soulcore_skill_search(query)
```

它的描述只有一行，不列全部技能；命中后再加载完整技能卡。  
它是 fallback，不是默认注入项。

## 固定程序优先

技能清单、能力过滤、记忆召回、事件卡选择、session 轮换，全部优先用固定程序：

- 程序读 capability；
- 程序读技能注册表；
- 程序做 FTS/BM25/加权排序；
- 程序决定清单版本；
- 程序决定是否为空。

2B 不负责“有没有技能/要不要注入”的硬门控；  
它只做同义词扩展、候选重排、粗略标签这类错了可回退的工作。

## 加权浮现：确定性、允许空

不做随机浮现。  
按权重排序，低于阈值就不注入；不为了填满配额硬凑。

```text
score = 0.35*relevance
      + 0.25*importance
      + 0.20*recency
      + 0.10*abs(affect_delta)
      + 0.10*unresolved
```

规则：

- top-k；
- `min_score` 阈值；
- 同分按时间/ID 稳定排序；
- 没有候选 → 返回空；
- 每次最多 1~3 张事件卡；
- 不做 `random.choice`。

这样“浮现”是**精度优先**，不是为了多样性牺牲上下文预算。

## 最小落地顺序

```text
1. episodes 表 + 睡眠摘要
2. 唤醒只取 3~5 张事件卡
3. 工具输出摘要 + 全文落盘
4. preset 条件化/压缩
5. 加权随机浮现
6. 单会话 token 阈值轮换
```

## 本地 2B 的正确角色

不要让 2B 顺序扫描整张技能表/事件表。  
正确分工：

```text
最近一条消息 + 最近 2 轮
  → 2B（轻量）：判断“需不需要查记忆/技能”，生成查询词
  → 程序：SQLite FTS / BM25 / 可选 embedding，召回 top-k
  → 2B（轻量）：只看 10~20 张候选卡，重排/判断是否上浮
  → 程序：把 3~5 张卡放进 L2
  → 需要细节时，再由工具展开 raw
```

### 为什么不是“2B 扫表”

- 2B 上下文小，扫长表会截断/漏项；
- 顺序扫表有表序偏差；
- 延迟和成本比程序索引高；
- 纯语言模型不擅长穷举比对；
- 程序检索可以确定性、可缓存、可测试。

### “少量多次”怎么落地

可以，但每次不是“下一段表”，而是**下一轮更聚焦的候选**：

```text
round 1: 关键词/向量召回 top 20
round 2: 2B 从 top 20 里选 3~5 个，或改写查询再召回
```

停止条件：

- 找到足够高置信的候选；
- 达到 max 2 轮；
- 达到 token/时间预算；
- 没有候选就明确“不注入”，不要硬凑。

### 论文对应

- **Self-RAG**：模型决定何时检索、并对检索结果自我评估。  
  [arXiv](https://arxiv.org/abs/2310.11511)
- **Adaptive-RAG**：按问题复杂度决定检索强度。  
  [ACL](https://aclanthology.org/2024.naacl-long.389/)
- **FLARE**：低置信时主动检索。  
  [arXiv](https://arxiv.org/abs/2305.06983)
- **IRCoT**：检索与推理交替进行，适合多跳。  
  [arXiv](https://arxiv.org/abs/2212.10509)
- **Generative Agents**：记忆检索按 recency/importance/relevance。  
  [arXiv](https://arxiv.org/abs/2304.03442)
- **Voyager**：技能库检索与复用。  
  [arXiv](https://arxiv.org/abs/2305.16291)
- **ToolLLM**：大规模工具/API 检索，而不是把 16k API 全塞进 prompt。  
  [arXiv](https://arxiv.org/abs/2307.16789)

## 功能开关与技能渐进披露

能力清单：

```json
{
  "qq": true,
  "pet": false,
  "bili": false
}
```

规则：

- `bili=false`：不注入 B站简报、B站技能、B站 prompt 段、B站工具说明；
- `pet=false`：不注入桌宠对话规则、桌宠工具、桌宠目的段；
- 只加载当前能力需要的 skill 卡片；
- 完整 skill 说明按需加载；
- cache key 必须包含 capability 集合，避免把“关掉 B站”的短 prompt 和旧长 prompt 混用。

## L2 预算建议

```text
核心角色/安全/工具协议     4~6k 字符
当前消息 + 最近 2~3 轮     1~2k
事件卡 3~5 张              1.5~3k
身体/欲望提示              0.2~0.5k
本次技能卡                 0.5~1.5k
```

原始记忆不进 L2；  
需要时通过 `soulcore_memory` 展开 episode/raw。

## 实施阶段

```text
P0 能力开关 + 条件注入（先减 B站/桌宠）
P1 episodes 表 + 睡眠摘要
P2 L2 只注入事件卡
P3 本地 2B 查询规划 + 候选重排
P4 工具输出遮罩 + session 阈值
P5 静态 preset 压缩/技能化
```

