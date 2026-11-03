# Appraisal Learning（评价代码化）

## 目标

**每条记忆都必须有评分。**  
普通记忆用固定程序评分；有价值、难理解、或程序无法处理的才升级本地 2B。

```text
每条新记忆
  → 固定程序评分（必做）
  → 是否值得升级？
      - 普通闲聊：程序分，结束
      - 有价值/困难：本地 2B 重评
      - AI 失败：保留程序分 + 通过 SurfCore 现有入口问 owner
  → 程序分/模型分都进入同一套 appraisal / P
```

不是跳过评分，是切换评分器。

## 数据流

### 0. 代码优先（当前主路径）

`appraise_pending` 先执行 `heuristic()`：

- 每条记忆都有 8 维评分、unresolved、confidence、has_impact、felt；
- 普通寒暄/复读/短句直接落 `code-v1`；
- owner、高 importance、长文本、冲突、强负向、承诺、不确定提问才升级 AI；
- 程序分 confidence 较低，P 中权重不会压过 AI。

### 1. 收集

每次本地评价会保存：

- `appraisals.feature_json`：文本特征
- 评价维度 / confidence / unresolved / has_impact
- felt / baseline / delta / adjusted

只有 `appraiser_id LIKE 'ollama:%'` 的评价会进入学习。  
`pattern-v1` 自己产生的评价被排除，防止自我强化。

### 2. 归纳

`learn-appraisals`：

- 对中文取 2/3-gram，英文取词；
- 过滤只出现一次的特征，避免 39 个样本出 37 个模式；
- 按余弦相似度聚类；
- 每个模式保存：
  - centroid
  - 平均维度
  - 维度方差
  - support
  - impact_rate
  - 代表性 tokens

当前结果：

```text
examples 38
patterns 17
top support 11
```

### 3. 影子模式（默认）

```text
pattern 先预测
model 仍然运行
两者结果写入 appraisal_shadow
```

只有满足：

```text
support >= min_support
similarity >= min_similarity
max_variance <= max_variance
```

才会产生 pattern 预测。

### 4. 代码接管

`auto` 模式需要先满足安全门槛：

```text
至少 5 次影子对照
shadow_accuracy >= 0.70
```

不满足时 `appraisal-policy --mode auto` 会拒绝。

满足后：

```text
pattern 命中 → 不调用本地模型
pattern 未命中/方差大/支持低 → 回退本地模型
```

## AI 失败时

不是让记忆无评分：

```text
AI 失败
  → 保存 code-v1 评分
  → 通过 SurfCore 现有 /api/test-send 私聊 owner
  → 附原文片段 + 错误 + “这条记忆该怎么理解”
  → 若 bridge 不可用，写入 data/appraisal-questions.jsonl
```

没有新建交流模块；复用 SurfCore bridge 已有的控制台发送入口。

## 修正闭环

AI 失败/不确定会生成 `appraisal_questions`：

```text
question id / 原记忆 id / 原文 / 程序分 / AI 错误 / 规则
```

表层 API 有两种方式处理：

1. owner 回答后，把 owner 原话一并提交；
2. owner 没答完，表层 API 自己给出结论和 8 维评分。

工具入口（现有 `soulcore_memory`）：

```text
mode=questions  查看待确认问题
mode=resolve    提交表层结论/评分
```

resolve 会：

- 新建 `surface-correction` 记忆；
- 用 `appraiser_id=surface-v1` 直接写入评分，不调用本地 AI；
- 旧记忆 `affect_weight=0`、`consolidation_state=superseded`；
- 旧记忆 sidecar 标 `superseded_by`；
- 新修正记录作为 sidecar `soulcore.correction` extension；
- `loadMemoryCard` 从日常卡移除旧记录并加入修正记录。

因此日常 prompt 不会同时出现新旧两套结论；全量档案仍可追溯。


## 命令

```powershell
python -m soulcore learn-appraisals
python -m soulcore appraisal-report
python -m soulcore appraisal-policy --mode shadow
python -m soulcore appraisal-policy --mode auto
python -m soulcore appraisal-policy --mode off
```

`appraise` 结束时也会自动重建模式。

## 报告字段

- `patterns`：模式数
- `examples`：参与学习的模型评价数
- `model_calls` / `pattern_calls`：实际路由
- `coverage`：代码接管比例
- `shadow_checked` / `shadow_match`
- `shadow_accuracy`
- `top_patterns`：support、confidence、代表性 tokens

## 当前限制

- 数据少时模式仍偏碎；
- 特征是可解释的 n-gram，不是语义嵌入；
- 模式是“相似文本的均值”，不是因果规则；
- 方差大或 support 低的模式不会接管；
- 影子计数从本功能上线后才开始，旧评价没有 shadow 记录；
- 默认 `shadow`，不会静默切换 `auto`。

## 设计原则

> 先用模型当老师，再用代码当学徒；  
> 学徒必须先在影子模式下证明自己，才能接管。
