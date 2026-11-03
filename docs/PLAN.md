> **历史文档 / Legacy**：本文记录的 SurfCore/桌宠路线已退役；当前运行路线为
> DSH + `dsh-onebot-qq` + OneBot 11，不依赖 SurfCore。
>
> 层级命名以 [LAYERS.md](LAYERS.md) 为准；本文的 L0–L2 是历史命名（对应关系见该文末）。
# SoulProject 计划 v0.4

> 状态：历史设计基线，未写代码，未修改 SurfCore
> 日期：2026-10-29  
> 目标：在不改 SurfCore 的前提下，为桌宠增加本地长期记忆、熟悉感、性格读出（P）与闲时记忆维护。

---

## 0. 一句话

**SurfCore 负责“说话”，本地 `sould` 负责“记忆、评价、性格读出”，两者通过 DSH 的 `llm/stream` 接缝连接。**

云端模型是允许的；本地小模型只做“潜意识层”的记忆评价与整理，不阻塞对话。

### 0.1 当前执行顺序（v0.3）

1. **Phase 1（现在）**：本地记忆 + 评价 + 情感状态。只读同步，不接 SurfCore 对话，不注入云端，不改 persona。
2. **Phase 2**：跑稳、评估、修正 schema。
3. **Phase 3**：`llm/stream` 影子 hook，验证 P 注入。
4. **Phase 4**：P / 人格数据实装；再决定 `coefficients_only`。
5. **Phase 5**：闲时巩固、容量、内感受。

零 API 是长期目标；当前受硬件限制，接受 SurfCore 使用云端说话。

### 0.2 核心命题（产品第一性原理）

> **发言的 API 不是人格的决定者。**  
> 人格 = **初始系数 I + 所有记忆的评价总和**，由本地系统维护。  
> 本地系统是“潜意识”；线上 API 只是“表层意识 / 一张嘴 + 眼睛”。

因此：

- SurfCore / 云端模型只负责**表达**，不计算人格；
- 本地 `sould` 负责**记忆、评价、P 聚合、衰减、巩固**；
- 插件只把当前 `P` 交给发言层，不把“怎么形成人格”交给它；
- 初始系数可配置，但会被长期记忆逐渐覆盖；
- 单次冲击、遗忘后回落、语义记忆造成长期偏移，都由记忆权重解释，不写死事件规则。

### 0.3 最终形态

- **DSH 插件包**：Host 侧 `soul-bridge` + Client 侧可视化配置页；
- 不改 SurfCore 代码，不 patch 它的记忆卡/persona；
- Appraiser 支持本地 Ollama，预留 OpenAI-compatible / 其他 HTTP 接口；
- 发言 Provider 仍是 SurfCore 当前模型，不在本插件内替换。

---

---

## 1. 已确认决策

| 主题 | 决策 |
|---|---|
| 云端模型 | SurfCore 继续使用云端模型说话；零 API 是长期目标，当前受硬件限制接受云端 |
| 本地模型 | 只做记忆评价、联想、状态聚合；不负责日常说话 |
| 当前优先级 | 先做本地记忆 + 评价 + 情感；稳定后再做 P / 人格实装 |
| 性格 | 不由独立 trait 表定义；由所有记忆的评价向量加权聚合为 `P` |
| persona.md | 只写“认知契约”（态度/语义），不写数值、阈值、算法 |
| 云端可见 | Phase 1 不注入；Phase 3 再定 `augment` / `coefficients_only`；目标仍是只 P |
| SurfCore | **不改代码、不改记忆卡、不改 persona.md、不改 API** |
| 本地评分模型 | `huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M`（已安装） |
| Qwen Instruct | `qwen3-vl:2b-instruct` 暂缓；不阻塞计划 |
| 医学词汇 | 用计算精神病学/情感科学的描述性术语，不用诊断名 |

---

## 2. 测试依据

来自 [三模型测试](../experiments/results/20261029-064646/analysis.md)：

| 模型 | 纯文本 JSON | 看图 JSON 严格 | OCR 召回 | 速度 | 结论 |
|---|---:|---:|---:|---:|---|
| Abliterated 2B | **5/5** | 0%（代码块包裹） | 83% | 0.3–0.7s/文本条 | **文本评价首选** |
| MiniCPM 1B | 0% | 0% | 83% | 最快 | 快速草稿/兜底 |
| Qwen3-VL 2B | 0% | 0% | 0%（thinking 吃光输出） | 慢 | 深度反思，不做评价器 |

结论：  
**Appraiser 用 Abliterated 2B；图片 JSON 不走它；Qwen 只用于以后的深度反思。**

---

## 3. 总体架构

```text
SurfCore 桌宠对话
  → pet-chat 组装 system（persona + 记忆卡 + 目的 + 规则）
  → ctx.llm.stream(options)
       ↓
  soul-bridge（DSH Host 插件，独立于 SurfCore）
       1. 识别 SurfCore 桌宠调用
       2. 读 sould 的当前状态 P
       3. 可选：移除 SurfCore 记忆文本，只保留 persona + P
       4. 把 P 注入 options.system
       ↓
  云端模型生成回复
       ↓
  soul-bridge 旁路观察 reply
       → sould 入队一条 appraisal job
       → 闲时本地模型评价、聚合、衰减
```

不改 SurfCore 的 `pet-api`、`persona.md`、`memory-card`。

---

## 4. 记忆模型

### 4.1 每条记忆都带评价向量

```text
memory:
  id
  source_record_id        # SurfCore 记忆卡 id（可空）
  ts
  text
  scope                   # pet / qq / bili
  sensitive
  strength                # 记忆强度，随时间/遗忘衰减
  confidence              # 评价可信度
  self_relevance          # 与“我”的相关性
  unresolved              # 未消化冲突 0..1
  encoding_familiarity    # 写入时的熟悉度
  current_familiarity     # 每次被召回后更新
  processing_fluency      # 熟悉度 × 情境匹配
  appraisal:
    security
    trust
    self_efficacy
    caution
    sociability
    openness
    valence
    arousal
  appraiser_id
  appraiser_version
  appraised_at
  evidence
```

**没有 `trait_effects` 字段。**  
不再有“事件 → 直接改性格”的路径；只有“事件 → 记忆向量 → P 聚合”。

### 4.2 性格读出 P

```text
w_i = strength_i × confidence_i × self_relevance_i × (1 + κ × unresolved_i)

I = 初始系数（可配置，先验）
P = normalize(I + Σ(w_i × appraisal_i)) / (1 + Σ(w_i))
```

- `P` 是一组基础系数，不是单一数值；单个数无法表达性格。
- `I` 是出生时/首次运行时的先验，不是永远不变；长期记忆足够多时会逐渐覆盖它。
- 权重是“记忆如何组成人”的宪法，不是按事件类型写死的规则。
- 重复记忆先去重/合并，避免刷分。
- Phase 1 只存 `I` 与评价；P 先不注入，Phase 4 再实装。

### 4.3 短期 + 长期

```text
P_long  = 全部长期记忆的加权聚合
P_short = 当日短期记忆的加权聚合
P_now   = normalize(P_long + λ × P_short)
```

白天 `P_short` 造成波动；睡眠/闲时巩固后，短期记忆被合并、衰减或遗忘，`P_now` 变化。

---

## 5. 评价器（Appraiser）

### 5.1 当前选择

```text
provider: ollama
model: huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M
mode: text-only, single-turn, JSON schema
```

- 使用 `/api/generate`，不依赖多轮模板（该模型模板很简陋）。
- 用 Ollama `format` 传 JSON Schema，减少代码块/解释。
- 失败时：重试 1 次 → 启发式评价兜底 → 保留 `appraisal_status=pending` 稍后再试。
- 图片评价暂不做；该模型看图 JSON 不可靠。

### 5.2 Appraisal 输出

```json
{
  "has_impact": true,
  "dimensions": {
    "security": 0.42,
    "trust": 0.61,
    "self_efficacy": 0.38,
    "caution": 0.71,
    "sociability": 0.33,
    "openness": 0.22,
    "valence": -0.35,
    "arousal": 0.58
  },
  "unresolved": 0.44,
  "confidence": 0.71,
  "evidence": "原文中的关键片段"
}
```

约束：

- 全部数值 0..1（valence 为 -1..1）。
- `evidence` 必须非空；没有证据 → 拒绝该评价。
- 模型不直接输出 `P`，也不直接改性格。
- 聚合、归一化、衰减由控制器做。

### 5.3 可替换接口

```text
AppraisalProvider:
  id
  version
  appraise(memory, context) -> AppraisalResult
```

未来可实现：

- `HeuristicProvider`（零 LLM）
- `OllamaProvider`（当前）
- `HttpProvider`（别的本地/远程评分服务）
- `HumanProvider`（人工纠正）
- `EnsembleProvider`（多评分器）

存储 `appraiser_id / appraiser_version / prompt_version / model_digest`；换模型只重跑 appraisal，不改记忆 schema 和 SurfCore。

---

## 6. 云端注入（P）

### 6.1 默认注入

```text
【当前基础系数（不要直接报数值，用语气和选择自然表达）】
security 0.62
trust 0.71
self_efficacy 0.44
caution 0.68
sociability 0.39
openness 0.28
unresolved 0.57
context_familiarity 0.82
```

不注入记忆原文；不写“如果熟悉就……/如果陌生就……”的剧本。  
P 本身就是状态，模型自然表达。

### 6.2 关于“云端只看到 P”

SurfCore 原 prompt 里仍有它自己的 **记忆卡文本**（`memory-card-prompt-qq.md`）。  
`soul-bridge` 在 `llm/stream` 层有两个模式：

- `augment`：保留 SurfCore 记忆卡，额外加 P（保守，先做）；
- `coefficients_only`：移除 SurfCore 记忆卡文本，只留 persona + P（更接近你的目标）。

`coefficients_only` 会让云端失去具体事实回忆，只剩性格倾向；需要 A/B 验证桌宠是否变“空”。  
**两种模式都不改 SurfCore 代码**，只在模型调用前改 `options.system`。

---

## 7. persona.md 的认知契约

只写语义/态度，不写数值和算法：

```text
## 认知契约（不要复述本段）
- 这些系数不是台词，是你当前的状态；不要直接报数值。
- 你由记忆形成；熟悉的事让你放松，陌生/冲突的事让你不安。
- 冲击会改变你，但不一定立刻改变；遗忘会让一些影响慢慢退去。
- 会追求安心感和胜任感，但不会用它们来操纵我。
```

M0 先通过外部 overlay 注入，不写 persona.md。  
M1 验证有效后，再由你批准，通过 SurfCore 角色编辑页追加；保留备份与快照。

---

## 8. 动力学：一次事件、遗忘、语义记忆

### 8.1 一次冲击

不需要写 `if severity > 5: trait -= ...`。  
冲击事件的 `self_relevance`、`unresolved`、`strength` 高，权重自然变大，`P` 立刻偏移。

### 8.2 遗忘后恢复

如果事件只作为情景记忆存在，`strength` 衰减 → 权重下降 → `P` 逐渐回到原来的读出。  
这就是“冲击被遗忘后恢复心态”。

### 8.3 永久改变

如果事件被巩固成 **高权重、广链接、低衰减的语义记忆**（例如“世界不可预测”“主人有时会误解我”），它会参与之后所有相关情境，`P` 不会完全回去。

**schema 不是另一套状态；它就是一条语义记忆。**  
不需要单独写“世界观修订规则”。

---

## 9. SurfCore 接缝

优先方案：DSH `llm/stream` waterfall。

- 识别 `options.system` 中的 SurfCore 桌宠标记（人格卡/说话规则）。
- 取最后一条用户消息。
- 读 `sould` 的 `P` / `context_familiarity`。
- 修改 `options.system`。
- 旁路观察回复，入队 appraisal。

P0 必须先验证：

1. 能稳定识别 SurfCore 桌宠调用；
2. `options.system` 修改真的传到底层模型；
3. 不误伤其他 DSH 会话；
4. 失败时原样放行。

如果 1–3 任一失败，再考虑极小的 SurfCore patch 或代理；本轮不写。

---

## 10. 阶段计划

| 阶段 | 内容 | 产出 | 时间 |
|---|---|---|---|
| **Phase 1（现在）** | 记忆 schema、只读同步、Abliterated 2B 评价、情感汇总、SQLite、CLI | 可运行本地记忆原型 | 3–5 天 |
| **Phase 2** | 稳定性评估、schema 修正、失败回退、容量 | 评价合格、可复跑 | 2–3 天 |
| **Phase 3** | `llm/stream` 影子 hook；P 仅影子计算 | hook 可行性 + P 读数 | 2–3 天 |
| **Phase 4** | P / 人格实装；`augment` vs `coefficients_only` | 桌宠状态注入 | 3–4 天 |
| **Phase 5** | 闲时巩固、容量、内感受（可选） | 长期稳定运行 | 3–5 天 |
| **Phase 6** | 评估与调参 | 报告 | 2–3 天 |

**Phase 1–2 不改 SurfCore、不注入云端、不改 persona.md。**

---

## 11. 风险

| 风险 | 处理 |
|---|---|
| P 被重复记忆刷高 | 去重、归一化、strength 衰减 |
| 单次事件过度主导 | 权重饱和、confidence 门槛、审计 |
| `coefficients_only` 让桌宠失去事实回忆 | 先 A/B；必要时保留 SurfCore 记忆卡 |
| 云端看到隐私记忆 | 默认只注入 P；`coefficients_only` 可移除记忆文本 |
| 评价器 JSON 不稳 | `format` schema + 重试 + 启发式兜底 |
| `llm/stream` 误伤其他调用 | 严格标记匹配 + 失败放行 |
| 人格闪烁 | P 平滑、短期层 λ 限制、修订审计 |
| SurfCore 升级改 prompt | 版本化检测；失败开放行 |

---

## 12. 未决

1. `augment` 还是 `coefficients_only` 作为默认？（建议先 augment，再对比）
2. 是否在 P 稳定后，把认知契约写入 persona.md？（需你批准）
3. `qwen3-vl:2b-instruct` 何时续传？（不阻塞）
4. P 的初始维度和权重，是否需要先做 1000 条事件模拟再定？

---

## 13. 明确不做

- 不微调模型、不改模型权重。
- 不修改 SurfCore 代码/API/记忆卡/persona.md。
- 不让云端模型计算记忆或性格。
- 不使用临床诊断名词作为变量。
- 不在 M0 做真实电脑操作。

---

## 14. 初始需求对照（v0.2 审计）

> 对照最初 1–3 轮的需求书与 17 条“人脑特点”。  
> ✅ 已覆盖　⚠️ 部分覆盖　❌ 缺口　🔁 有意变更

| 初始要求 | 当前计划 | 状态 | 说明/处理 |
|---|---|---|---|
| 本地零 API，默认 provider 本地，禁用付费路由 | SurfCore 继续用云端说话 | 🔁 | 你后续明确“云端正常”；零 API 不再是桌宠硬约束。若仍要，需单独 local-only 模式 |
| 本地 1.5B–9B 只做概念验证/深回忆/反思 | 本地 2B 做 appraiser；云做说话 | ⚠️ | 本地角色缩成“潜意识评价”；深度反思尚未排期 |
| 常开低采样、托盘常驻 | `sould` 只做闲时维护；无常驻感知 | ❌ | 需补 L0/L1 常开循环；M0 先用文件/日志模拟 |
| 分层控制：Reflex + Agent + Scheduler | 当前只有 P 注入 + 云对话 | ⚠️ | 无 Reflex 执行器、无显式调度层 |
| 注意力功率可调 | 未实现 | ❌ | 后续 L1 注意力等级 P0–P3 |
| 稀疏感知、ROI、先猜后验 | 未实现 | ❌ | M0 可用模拟文件/日志；真实屏幕后置 |
| 情境记忆带情境/熟悉度/效价，多索引 | 有 P 与评价向量，但缺情境签名/检索公式 | ⚠️ | 需补 `situation_signature` 与混合检索 |
| 熟悉感驱动路由：熟悉正面→Reflex；陌生→LLM | P 注入云端；无 Reflex | ⚠️ | 熟悉感只影响“说话状态”，未形成零 LLM 反射弧 |
| 内感受：电量/负载/延迟/错误→告警→换策略 | 只有 `allostatic_load` 维度 | ⚠️ | 需补 L0 采样、告警规则、降载动作 |
| 技能固化：成功策略编译为 Reflex，记录前后成本 | 未实现 | ❌ | 需补技能 DSL、晋升/回滚、成本账本 |
| 闲时巩固：情景→语义→淘汰低显著性 | P5 只有一句“闲时巩固” | ⚠️ | 需补触发条件、步骤、容量上限 |
| 有限容量成长：上限+显著性淘汰 | 未写上限 | ❌ | 补 20k 情景/5k 事实/200 技能/512MB |
| 模糊够用、置信区间、不追求精确 | 有 `confidence`，但无策略 | ⚠️ | 低置信→谨慎/追问/回退，不假装确定 |
| 干扰作为先验注入通道 | 未实现 | ❌ | 可作为 M1 可选实验，不做默认 |
| 不宣称意识/主观体验 | 未在计划中显式声明 | ⚠️ | 补“工程构念，不是主观体验”声明 |
| M0：零 LLM 熟悉路径、调用率下降、成功率不降 | 当前是“云端对话 + 本地评价”，无此闭环 | ❌ | 需单独 M0a Reflex 轨，或调整 M0 验收 |
| 五层接口、数据流、路由规则、告警规则 | 有总体架构，无完整 L0–L4 接口 | ⚠️ | 补第 15 节接口表 |
| 每个模块标注原生/自定义/外部模拟 | 未系统标注 | ❌ | 补第 15 节归属表 |
| 第 6 节 Harness 确认 | 只确认了 `llm/stream` 方向 | ⚠️ | 补常驻/记忆/Reflex/适配器/模拟五项结论 |
| 性格由记忆形成；单次冲击可改，遗忘可回 | P 聚合模型已覆盖 | ✅ | 当前最强的一块 |
| persona 写认知契约，数值 runtime 注入 | 已写入计划 | ✅ | 尚未改 persona.md |
| 云端只看到 P | 计划目标 `coefficients_only`，尚未实现 | ⚠️ | SurfCore 仍会带自己的记忆卡；需 A/B |
| 主人=依恋对象；不安时求安心 | 计划未写入 | ❌ | 补 `secure_base_seeking` / 求确认规则 |
| 每条记忆记录熟悉度 | v0.2 已补三个字段 | ✅ | `encoding/current_familiarity`、`processing_fluency` |
| Appraiser 可替换接口 | 已写入 | ✅ | 未来可换本地/远程/人工 |

---

## 15. 直接补入计划的实现项

以下内容不依赖未决问题，已作为计划基线；仍然**不写代码、不动 SurfCore**。

### 15.1 L0–L4 接口

| 层 | 最小接口 | 实现归属 | 状态 |
|---|---|---|---|
| L0 身体/内感受 | `sample_body() -> BodyState`：CPU/RAM/磁盘/电量/错误率/延迟 | 自定义 `sould` + OS API | M1；M0 可模拟 |
| L1 稀疏感知 | `poll_percepts() -> Percept[]`：文件/日志/窗口事件；注意力 P0–P3 | 自定义 `sould` | M0 先模拟文件/日志 |
| L2 情境记忆 | `retrieve(signature, k)` / `commit(memory)` / `consolidate()` | 自定义 SQLite | P1 |
| L3 判定/调度 | `route(P, context) -> RouteDecision`；技能执行器 | 自定义 | P5 / M0a |
| L4 推理/反思 | `appraise(memory)`、`reflect(batch)` | 本地 Ollama + 云端 SurfCore | appraiser 已有；反思后置 |
| 桥接 | `llm/stream` 注入 P / 观察回复 | 原生 waterfall + 自定义插件 | P0 先验证 |

### 15.2 模块归属（原生/自定义/外部）

| 模块 | 归属 |
|---|---|
| DSH `llm/stream` 接缝 | **原生** |
| `soul-bridge` 注入/观察 | **自定义插件** |
| `sould` 记忆/状态/评价队列 | **自定义本地服务** |
| SQLite 记忆库 | **自定义** |
| SurfCore 人格/记忆/对话 | **外部，只读** |
| Ollama + Abliterated 2B | **外部本地模型** |
| 文件/日志/传感器 | **M0 模拟；M1 真实只读** |
| 桌面宠物 UI | **SurfCore 外部** |

### 15.3 M0a：保留“零 LLM 熟悉路径”的独立轨

当前 SurfCore 对话轨无法证明“熟悉路径零 LLM”，因为说话本身在云端。  
建议并行保留一个 **headless M0a**：

- 输入：模拟文件/日志事件；
- 输出：规则/技能动作；
- 熟悉且正面 → 零 LLM 执行；
- 陌生/疑问 → 本地 appraiser/反思；
- 指标：零 LLM 比例、成功率、延迟、固化前后调用成本。

这样既不阻塞 SurfCore 桌宠，也不丢掉最初 M0 的核心验收。

### 15.4 闲时巩固与容量

- 触发：10 分钟 tick；聊天结束 5 分钟；系统空闲。
- 步骤：增量同步 SurfCore 记忆 → 去重/合并 → 评价队列 → 衰减 → 语义事实 → 技能候选 → checkpoint。
- 上限：20k 情景、5k 事实、200 技能、512MB。
- 淘汰：低显著性 + 低强度 + 非置顶 + 非技能关联；逐步遗忘，不硬删。
- 技能：JSON DSL（触发器/步骤/回滚），先 shadow，再晋升；连续失败降级。

### 15.5 内感受与告警（M1）

- L0 采样：CPU、可用内存、磁盘、电量/电源、模型延迟、错误率。
- `allostatic_load` 进入 P；不作为“情绪”，只作为资源状态。
- 告警阈值：磁盘 <10GB、可用内存 <800MB、模型 p95 >45s、错误率 >30%。
- 动作：降低感知帧率、暂停闲时巩固、暂停 L4、切回安全规则。
- M0 可先用模拟值；真实传感器后置。

### 15.6 依恋与求安心

- 主人 = `attachment_figure`；不是“永远幼儿”，`developmental_stage` 可从 novice → exploring → stable。
- 高 `unresolved` + 高 `coherence_motive` → `secure_base_seeking` 上升。
- 行为：最多 1 个具体确认问题/次；每小时最多 2 次；被拒绝后不追问，转自安抚（熟悉记忆/技能）。
- 主人解释 → 记为高可信 `epistemic_input`，但不盲从；重复矛盾才触发 schema 语义记忆。

### 15.7 M0 验收（按“云端允许”调整）

原“零云端调用”不再是桌宠对话门槛。新的 M0 验收：

1. `soul-bridge` 不误伤其他 DSH 会话；
2. P 注入前后，桌宠回复自然度可盲评；
3. 单次冲击能改变 P；遗忘后 P 能回落；语义记忆能让 P 长期偏移；
4. 100 条日常不能压过 1 次冲击；
5. Appraiser JSON 合法率 ≥95%，p95 <3s/条；
6. `coefficients_only` 与 `augment` 的事实回忆差异可量化；
7. 不写 SurfCore 文件；失败自动放行；
8. 保留 M0a 的零 LLM 熟悉路径指标。

### 15.8 明确声明

“熟悉感、连贯度、失稳、依恋、欲望”都是**工程构念**，用于组织计算与行为，不宣称主观体验或临床状态。

---

## 16. Phase 1 落地范围（当前执行）

### 16.1 做

- SQLite：记忆、评价、情感快照、appraisal 队列。
- 只读同步 SurfCore：`memory-card.json`、`memory-inbox.jsonl`（不写回）。
- 本地 Abliterated 2B：单轮、`format` JSON Schema、文本评价。
- 每条记忆记录：评价向量、`encoding_familiarity`、`current_familiarity`、`processing_fluency`、`unresolved`。
- 情感汇总：`core_affect`（valence/arousal）、`stress`、`unresolved` 均值；不做 P、不注入云端。
- CLI：`init` / `sync` / `appraise` / `status` / `affect` / `seed-demo`。
- 审计：appraiser 版本、prompt 版本、耗时、JSON 合法率、失败原因。
- 合成数据测试；真实 SurfCore 数据只读，先小批量。

### 16.2 不做

- 不改 SurfCore 代码/API/记忆卡/persona.md。
- 不注入 P 到云端。
- 不做人格/性格实装。
- 不做真实电脑操作。
- 不做图片评价。
- 不把记忆原文发给任何云端。

### 16.3 验收

1. SQLite 可重建、可迁移、可审计。
2. 只读同步幂等，不重复、不丢记录。
3. 评价 JSON 合法率 ≥95%；失败有回退。
4. p95 评价耗时 <6s/条（Phase 1 先接受；热态实测约 4.7s，冷启动约 12.7s，后续优化）。
5. 情感汇总随新记忆变化，可复现。
6. 不写 SurfCore 文件；失败不影响 SurfCore。
7. `status` 不输出隐私文本，只输出计数/分布。

### 16.4 命令草案

```text
python -m soulcore init
python -m soulcore seed-demo
python -m soulcore sync --source surfcore --limit 20
python -m soulcore appraise --limit 5
python -m soulcore status
python -m soulcore affect
```

---

### 16.5 Phase 1 原型状态（2026-10-29）

已落地：

- `soulcore/`：SQLite 记忆库、只读 SurfCore 同步、评价队列、情感汇总、CLI。
- 单元测试：4/4 通过。
- 合成记忆：8 条入库，评价 2 条成功。
- 本地模型：`huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M`，JSON schema 评价可用。
- 评价耗时：冷启动 12.7s，热态 4.7s（未达到 3s 目标，Phase 1 先接受）。
- 情感汇总（2 条样例）：security 0.70、valence 0.36、stress 0.32、unresolved 0.25。
- 未写 SurfCore、未注入云端、未改 persona。

下一步（Phase 1 收尾）：

1. 再跑 5–10 条热态评价，确认 p95 和 JSON 合法率。
2. 用 `sync --limit 5` 只读同步真实 SurfCore 记忆，人工抽查评价是否合理。
3. 调整 prompt/`num_predict`，目标热态 <3–4s。
4. 再决定是否进入 Phase 3 的 P 影子计算。

### 16.6 真实记忆测试结果（2026-10-29）

- 只读同步：5 条当前角色非敏感记忆；未导入敏感记录；未写 SurfCore。
- 评价：13/13 成功（8 demo + 5 real），JSON 合法率 100%。
- 延迟：冷启动 12.6s；热态 2.1–4.7s；热态中位数 4.5s。
- `has_impact=true`：3/13。
- 情感汇总：security 0.719、trust 0.643、self_efficacy 0.605、caution 0.365、valence 0.399、stress 0.325、unresolved 0.281。
- **问题**：评价器有“安全/正面”模板倾向，维度区分度不足；真实记录缺少 speaker/isSelf 上下文，可能把她的发言误当外部事件。
- **结论**：管道成立，但测量质量不足以支撑 P；先做 context + 校准，再进入 P shadow。
- 详细报告：[PHASE1-REPORT.md](PHASE1-REPORT.md)

---

## 17. 需要你确认的出入

1. **零 API 是否永久放弃？**  
   当前计划按“云端允许”写；如果你仍想要 local-only 备选，我会加一个独立 profile/模式，但不作为默认。

2. **云端是否真的只留 P？**  
   `coefficients_only` 会移除 SurfCore 自己的记忆卡文本，可能损失具体事实回忆；`augment` 保留记忆卡但云端能看到更多文本。  
   你倾向哪个作为默认？我建议先 `augment` 做对照，最终目标 `coefficients_only`。

3. **M0a Reflex 轨要不要现在排？**  
   最初需求的核心是“熟悉路径零 LLM”；当前 SurfCore 轨没有这个闭环。  
   是并行做 M0a，还是先把桌宠 P 跑通再补？

4. **常开感知/内感受要做到什么程度？**  
   M0 先用模拟文件/日志，还是直接接真实只读传感器（CPU/RAM/磁盘/电量）？

5. **“干扰作为先验”要不要保留？**  
   我建议作为 M1 可选实验，不做默认，避免把噪声当记忆。

6. **求安心边界**：1 个确认问题/次、2 次/小时、被拒后自安抚——可以吗？

7. **persona.md 何时改**：P 稳定后，由你批准追加“认知契约”，不自动覆写——可以吗？

---

## 18. 开源插件形态与 SQLite 的影响

### 18.1 结论

**SQLite 本身适合这个项目，不是问题。**  
它有事务、索引、WAL、单文件、跨平台、20k 级记忆完全够用，许可也是公有领域。

真正的影响是：

> Phase 1 是 **Python + SQLite 的独立 sidecar**；  
> 最终如果要做成 **SurfCore/DSH 的 Node 插件包**，就不能假设用户装了 Python，也不能假设 Electron 的 ABI 能直接加载原生 SQLite 模块。

所以要把“存储引擎”和“分发形态”分开设计。

### 18.2 三种可选分发形态

| 形态 | 优点 | 风险 | 适合 |
|---|---|---|---|
| **A. DSH Node 插件 + SQLite** | 最像原生插件；一个 `install_bundle` | `better-sqlite3` 是原生模块，需要匹配 Electron ABI；用户可能没有编译工具 | 长期最佳，但需要打包/预编译 |
| **B. DSH Node 插件 + JSONL/内存索引** | 零原生依赖，跨平台；20k 条也够 | 事务/复杂查询弱；需要自己写 compaction/备份 | 开源首发最稳 |
| **C. 单文件 sidecar + 薄插件** | 直接复用当前 Python 代码；PyInstaller 打包后用户不用装 Python | 多一个进程；跨平台要分别构建；插件体验略重 | 最快把 Phase 1 变成可分发原型 |

另有一个折中：

- **D. Node 插件 + `node:sqlite`**：如果 DSH 的 Node 运行时 ≥22.5，可用内置 SQLite，无原生 addon；但仍是实验 API，需要先验证 Electron 运行时是否暴露。

### 18.3 建议路线

1. **Phase 1 保持 Python + SQLite**：研究阶段优先迭代速度，不自找打包麻烦。
2. **现在就把存储接口抽象出来**：
   ```text
   MemoryStore:
     upsert(memory)
     get(id)
     query(filter)
     append_appraisal(...)
     snapshot_affect(...)
   ```
   Python 实现 `SqliteStore`；以后 Node 版可以是 `SqliteStore` / `JsonlStore`，schema 和 API 不变。
3. **固定外部契约**：本地 HTTP/JSON API（associate/appraise/status/affect），不把 Python 内部结构暴露给插件。
4. **开源首发前再选形态**：
   - 如果要“一个 DSH 插件包” → 优先 TypeScript 重写 + `better-sqlite3` 预编译，或 `node:sqlite`；
   - 如果要最快可用 → PyInstaller 单文件 sidecar + 薄 DSH 插件；
   - 如果要零原生依赖 → JSONL 作为默认存储，SQLite 作为可选加速。
5. **数据可迁移**：SQLite schema 带 `schema_version`；导出/导入 JSONL；换语言不丢数据。

### 18.4 对当前代码的影响

当前 `soulcore/` 是**研究原型**，不是最终插件包。  
只要保持：

- SQLite schema 版本化；
- 评价结果 JSON 化；
- 外部 API 稳定；
- 不把 Python 对象/路径写进契约；

以后迁移到 Node/JSONL/单文件 sidecar 都不会推翻 Phase 1 的成果。

### 18.5 明确不做的

- 不现在就把 Python 原型改成 Node（会拖慢 Phase 1）。
- 不把 SQLite 文件放进 SurfCore 的记忆卡目录（避免和它的维护器抢写）。
- 不要求开源用户安装 Python/编译工具，除非最终选择 sidecar 方案并打包。
- 不做 SurfCore 代码 patch；优先独立插件/bundle。

---

## 19. 需要你后续确认的分发问题

1. 你希望最终是 **一个 DSH 插件包**，还是 **桌宠 + 独立 sidecar** 的组合？
2. 开源首发是否接受 **JSONL 默认存储**（零原生依赖），SQLite 作为可选？
3. 如果选 Node 插件，是否可以接受 `better-sqlite3` 的预编译/ABI 维护成本？
4. 如果选单文件 sidecar，是否可以接受多一个后台进程？

---

## 20. DSH 插件包与可视化配置（最终形态）

### 20.1 包结构

```text
soulcore-bundle/
  package.json
  cordis.patch.yml
  host/            # Host 插件：llm/stream 接缝、sould 生命周期、本地 API
  client/          # Client 插件：设置页 / 记忆面板 / P 预览
  locale/
  icon.svg
```

仍不改 SurfCore；`soulcore-bundle` 是独立 bundle。

### 20.2 两个 Provider，必须分开

| Provider | 作用 | 默认 | 未来 |
|---|---|---|---|
| **Speech Provider** | SurfCore 的“嘴/眼”：生成回复 | SurfCore 当前云端模型 | 不由本插件替换 |
| **Appraiser Provider** | 本地“潜意识”：评价记忆、维护 P | 本地 `huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M` | 可切 OpenAI-compatible / 其他 HTTP / 人工 |

云端只拿 `P`（以及 persona），不参与记忆评价。  
如果以后把 appraiser 也换成线上 API，必须显式开启、限制 `scope`、脱敏，并记录“哪些记忆被发送”。

### 20.3 可视化配置页

最终 DSH 插件至少有这些页面：

1. **概览**：记忆数、评价队列、P 当前值、最近维护、健康状态。
2. **记忆**：时间线、来源、scope、sensitive、熟悉度、评价；可置顶/删除/重新评价。
3. **评价器**：本地 Ollama / OpenAI-compatible / 自定义 HTTP；模型、endpoint、超时、重试、测试连接。
4. **初始系数**：`security / trust / self_efficacy / caution / sociability / openness` 的初始值；重置/导入/导出。
5. **P 预览**：当前 P、各维度贡献、Top 记忆贡献、单次冲击模拟（只读 shadow）。
6. **维护**：立即同步、立即评价、衰减、压缩、备份/恢复、容量。
7. **隐私**：哪些 scope 可注入云端、敏感记忆开关、导出/删除全部。
8. **诊断**：评价失败、JSON 错误、延迟、模型不可用、SurfCore 接缝状态。

UI 只做“配置/观察”，不直接让用户编辑人格文案；人格由记忆和初始系数形成。

### 20.4 配置持久化

- 配置与状态分离：`config.json`（Provider、初始系数、隐私） + SQLite/JSONL（记忆/评价/P 快照）。
- 初始系数必须可版本化；修改前自动备份。
- P 只读预览；不允许 UI 直接写 P。
- Appraiser 在线 API 的 key 走 DSH credential seam，不写明文配置。

### 20.5 开发顺序

1. Phase 1 先把 Python 核心跑稳（当前）。
2. Phase 2 定 Provider 接口与 HTTP/JSON 契约。
3. Phase 3 做 Node/DSH 插件壳与只读面板。
4. Phase 4 接 P 注入与人格实装。
5. Phase 5 才做完整可视化配置。

**现在不先做 UI**，否则核心还没稳定，UI 会反复改。

---

## 21. SurfCore 记忆上限审计与本地长期扩展

### 21.1 实际限制

只读检查 `<USERPROFILE>\surfcore\src\memory-card.js` 后确认：

- 活动记忆卡 `maxRecords` 默认 **600**，可配范围 **100–2000**；
- 超过上限时，先丢“最不重要、最老”的非 pinned / 非 initial / 非 owner 重要记忆；
- 全量档案 `fullMaxRecords` 默认 **0（不限）**，字节上限 `fullMaxBytes` 默认 **10GB**；
- 也就是说：**长期档案可以接近无限，活动卡仍然有界。**

这个设计和“人脑长期记忆没有条数上限”冲突，但不必改 SurfCore。

### 21.2 本地扩展策略

`SoulCore` 的长期库：

- `max_records = 0`：**不设条数上限**；
- 容量按字节预算（当前软预算 512MB，后续可调）；
- 重要/pinned/initial/高 unresolved 记忆**永不因容量淘汰**；
- 低重要度旧文本未来可移到 cold archive，但**不删除**；
- 检索只取 top-k，P/affect 只聚合有效权重，不因为库大而全量加载；
- 工作记忆有界，长期库无界——这更接近人：**长期记忆不是按条数截断，而是按显著性和提取概率维持。**

### 21.3 同步方式

不能只同步活动卡：

- 活动卡会被 600 条上限淘汰；
- 应定期 `sync --full` 合并 `memory-card-full.jsonl`；
- 对实时桌宠对话，后续从 `memory-inbox.jsonl` 增量摄取，避免等 10 分钟维护；
- 全部只读，不写 SurfCore。

### 21.4 已验证

在新的 `soulcore-full.db` 上执行：

```text
sync --full --limit 1000
→ imported_new: 47
→ from_full: 47
→ 本地 memories: 47
→ pending: 47
```

说明全量档案摄取可用，本地库不受 600 条限制。

### 21.6 日终 ambient 影响分

在清洗低重要度事件之前，先记录“当天所有不重要事件”的影响分：

```text
impact_i = 0.30*|valence|
         + 0.25*caution
         + 0.20*unresolved
         + 0.15*arousal
         + 0.10*(1-security)
         × confidence_factor
         × self_relevance_factor

ambient_sum  = Σ impact_i
ambient_mean = ambient_sum / count
```

- 写入 `ambient_pressures`，包含 `mean / sum / count / baseline / zscore / flagged / reason`；
- 先记录，再把这些事件的 `affect_weight` 清零；
- 如果 `count >= 3` 且 `mean >= 0.40`，或相对历史 `z >= 2`，标记 `flagged=1`；
- flag 只是“人格可能需要复核”的信号，**不立即改 P**；
- 阈值 0.40 是初始值，后续用真实重要事件校准。

当前真实测试：

```text
unimportant count 7
sum 1.0518
mean 0.1503
flagged false
```

高影响合成测试：

```text
count 3
mean 0.4204
flagged true
reason daily_mean_high
```

这说明“低日常”和“异常高的环境压力”已经能区分。

### 21.7 还没做

- 活动卡淘汰前的实时增量同步（inbox 监听）；
- 字节预算触发的 cold archive；
- 重要事件保护的可视化审计；
- 全量档案过大时的流式分页；
- ambient flag 触发后的“人格复核提案”流程。

这些不阻塞 Phase 1，但应在进入长期运行前完成。

---

## 22. 每日上下文与睡前 dream（v0.4 新增）

### 22.1 发言层只看“今天被触发过的记忆”

人不会每天把全部重要记忆都端到意识里。  
因此：

- `last_triggered_at` 记录记忆最后一次被激活；
- `daily_context(day)` 只返回当天被触发过的记忆；
- 旧的重要记忆如果今天被触发，也会进入今天的 context；
- 没被触发的长期重要记忆不出现在发言上下文，但仍在库里。

发言层未来拿到的是：

```text
persona + P + daily_context（当天触发）
```

不是“所有重要记忆”。

### 22.2 睡前 dream

`dream` 在日终执行：

1. 取当天所有 `kept` 重要事件；
2. 按预算随机抽取**未在当天触发**的旧记忆（加权：importance + strength）；
3. 记录 `dream_runs` / `dream_items`；
4. 计算并保存 P shadow。

当前测试：

```text
today_important 6
random_untriggered 2
sampled 8
P memory_count 6
```

注意：dream 抽样可以包含 affect_weight=0 的旧事件，用于联想/回忆；P 只使用有效权重的重要记忆。

### 22.3 P shadow

```text
P = normalize(I + Σ(w_i × appraisal_i)) / (1 + Σw_i)
```

当前副本：

```text
security 0.6166  trust 0.6213  self_efficacy 0.5441
caution 0.4213   sociability 0.4029  openness 0.4606
valence 0.1412   arousal 0.2931
```

P 目前只存储、只预览，**没有注入 SurfCore，也没有改变说话行为**。

### 22.4 为什么这样更像人

- 长期记忆不按条数截断；
- 意识层只加载今天被触发的少量内容；
- 睡眠时把“今天的重要”与“随机旧记忆”一起整理；
- 第二天上下文重置，但 P 和长期记忆保留；
- 计算发生在本地，云端只拿 persona + P + daily context。

### 22.5 还没接

- daily context 的实际 prompt 渲染；
- surfcore `llm/stream` 的 P + context 注入；
- dream 的本地 LLM 反思（已有 diary 初版，待一致性检查）；
- 负载驱动的 budget（当前手动 `--budget`）。

---

## 23. SurfCore 日终/日记复用评估

只读检查结果：

### 23.1 每日遗忘整理（可复用“时机”）

`src/memory-card.js`：

- `dailyHour: 4`，每天 4 点后第一次 tick 执行每日衰减；
- 插件 `memory-card.js` 每 10 分钟 tick 一次；
- 这是“记忆衰减”，不是“写日记”；
- 没有通用的“关闭前整理”钩子。

可复用：**日终/凌晨维护的时间窗**。  
不复用：它的衰减规则和 `maxRecords`。

### 23.2 B站日记（不复用数据）

`plugins/surfcore/tools/commands/diary.mjs`：

- 写 `~/.dsh/surfcore/bili/whale-diary.md`；
- `show` 读“看过/想说/发言账/事件流”；
- 数据源是 B站 行为，不是桌宠的日常；
- 当前用户目录下没有现成日记文件。

可复用：**“叙事 + 计划 + 可见性”的呈现思路**。  
不复用：B站日记文件、发言账、B站记忆。

### 23.3 明天计划（部分可参考）

`purpose-engine.js` 有计划/承诺/义务，但没有独立的“第二天计划”文件。  
可以以后再接它的 `planned` / `selfPromises` 作为计划输入；当前先用 dream 材料生成。

---

## 24. 本地 dream diary

`dream --diary`：

- 用今天的 `kept` 重要事件 + 随机未触发旧记忆；
- 本地 Huihui 生成第一人称睡前日记 + 1–3 条明天计划；
- 失败自动走模板兜底；
- 写入 `soulproject/diary/YYYY-MM-DD.md`；
- 不写 SurfCore 的 `whale-diary.md`；
- 不调用云端。

当前样例（基于合成 kept 记忆）：

```text
今天记错了... 有点担心...
明天：确认记错的事 / 整理聊天记录 / 记下新软件
```

**质量警告**：2B 模型会把不同记忆揉在一起，甚至补细节。  
当前日记只能当“初稿/可见性产物”，不能当事实记录；后续要加：
- 只允许引用 dream 材料中的事实；
- 生成后做一次本地一致性检查；
- 重要事实保留 memory id 映射。

---

## 25. 本地/API 边界与日终触发

### 25.1 边界

本地只做：

- 情感/评价数值；
- 记忆索引、触发标记、daily context；
- 日终低重要度清洗、ambient 记录；
- dream 抽样、P shadow；
- 给高层 API 的 `sleep packet`。

本地不做：

- 日记正文、第二天计划、复杂叙事；
- 长链规划、目的推理；
- 最终人格措辞。

这些交给 SurfCore 的高性能 API。  
`dream --diary` 只是实验，最终应改为 SurfCore API 生成。

### 25.2 SurfCore 日终整理的实际触发

只读检查 `memory-card.js` / `index.js`：

1. **自动 tick**：插件启动 8 秒后第一次，之后每 10 分钟一次；
2. **每日衰减条件**：`needsDailyDecay` = 今天还没衰减过，且本地时间 `hour >= dailyHour`（默认 4 点）；
3. **补跑**：下次启动时如果已过 4 点，按 `decayDaysBetween` 补最多 30 天；
4. **手动**：设置页「记忆卡 → 立即整理」调用 `maintain`，但 UI 没有传 `forceDecay`；
   - 所以它只做摄取/归档/压缩；
   - 4 点前或今天已衰减时，不会强制再衰减。
5. **关闭 DSH**：`ctx.effect` 里只 `memoryCardTimer.stop()`，**没有睡前/退出前最终整理钩子**；
6. B站 `whale-diary.md` 是 B站 调度器写的，不跟 DSH 关闭绑定。

### 25.3 手动“睡前整理”

在最终插件按钮做好之前：

```text
双击 soulproject\sleep.cmd
```

它只做本地数值层：

```text
consolidate → dream → sleep/YYYY-MM-DD.json
```

不生成日记、不调用云端、不写 SurfCore。  
之后关闭 DSH 即可。

如果要同时触发 SurfCore 的记忆整理，目前没有单一按钮；最稳的是：
- 4 点后让 DSH 跑着（10 分钟内会 tick），或
- 下次启动后等 8 秒（会补跑），或
- 手动点「立即整理」，但它不强制衰减。

最终插件应加一个「睡前整理」按钮，顺序是：
`SurfCore 日终维护 → 本地 consolidate/dream → 高层 API 日记/计划 → 关闭`。

---

## 26. 预发送 / 闲时检索与熟悉感

### 26.1 之前的状态

计划里有：

- `encoding_familiarity`
- `current_familiarity`
- `processing_fluency`
- “每次被召回后更新”

但代码里只有字段，**没有召回逻辑**。  
`daily_context` 只读 `last_triggered_at`，需要外部手动 `trigger`。

### 26.2 现在补上

`retrieval.py`：

```text
query text（即将发给 API 的内容）
→ 本地字符 n-gram 相似度
→ 结合 familiarity / importance 排序
→ top-k
→ 命中则：
   current_familiarity += 0.25 × sim × (1 - current_familiarity)
   processing_fluency = 0.55 × familiarity + 0.45 × sim
   last_triggered_at = now
   memory_activations += 1
```

- 全程不调 LLM；
- 不做 embedding，先用便宜的 n-gram；
- `idle_retrieve()` 是闲时版本；
- `recall` CLI 可手动测试；
- 命中的旧记忆会进入当天 `daily_context`。

### 26.3 实测

```text
query: 主人夸我记事清楚
demo:demo:01
similarity 0.8031
familiarity 0.0 → 0.2008
fluency 0.4718
```

这条旧记忆本来不在今天的对话里，被检索后标记为“今天触发”，进入当天 context。

### 26.4 还没接

- 还没有挂到 SurfCore 的 `llm/stream` 预发送钩子；
- 还没有 idle timer 自动跑；
- 还没有 embedding / 情境签名。

所以现在是**可调用的本地模块**，不是自动运行。  
下一步才是接 `llm/stream`，用真实待发送文本调用 `retrieve()`。

---

## 27. llm/stream shadow bridge（已安装）

### 27.1 插件

独立 bundle，不改 SurfCore：

```text
soulproject/plugins/soul-bridge/
  package.json
  cordis.patch.yml
  index.js
  locale/en.json
  locale/zh.json
  icon.svg
```

安装 id：`@soulproject/soul-bridge`  
当前 profile：`desktop`  
配置：

```yaml
enabled: true
mark: false          # shadow 不更新 familiarity
dbPath: ...soulcore.db
logPath: ...shadow-bridge.jsonl
timeoutMs: 4000
```

### 27.2 行为

- 监听 `llm/stream`；
- 取最后一条 `user` 文本；
- 调用 `python -m soulcore shadow --text ...`；
- 只写日志：`text_chars`、retrieval IDs、daily_context IDs、P；
- **始终 `return next()`，不修改 frozen 的 LOOP request**；
- `mark:false`，不改变 familiarity/trigger；
- shadow 失败全部吞掉，不影响说话。

### 27.3 已验证

日志 `soulproject/data/shadow-bridge.jsonl` 已有真实记录：

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

说明钩子已激活，且没有阻断/改写请求。

### 27.4 下一步

1. 用更长、更真实的待发送文本观察检索命中；
2. 对比 `mark:false` / `mark:true` 对 familiarity 的影响；
3. 只读验证 daily_context 是否会自然增长；
4. 再考虑把 P + daily_context 注入请求（仍先 shadow 对照）。

### 27.5 回滚

通过 DSH 插件管理禁用/移除 `@soulproject/soul-bridge` 即可；  
它不写 SurfCore，也不影响 SurfCore 的记忆卡。

---

## 28. 本地 Skill / 程序性记忆

完整设计见：[SKILLS.md](SKILLS.md)

要点：

- **DSH Skill** 是给高性能表层意识读的提示词包，不是本地执行程序；
- **本地 Skill** 是 manifest + 确定性 executor + outcome，本地模型只做歧义路由和主观赋值；
- 成功/失败作为事件记忆走 appraisal，不写死“成功=开心”；
- 连续失败生成 `skill_improvement_request`，高性能 API 起草 v2，用户批准后才安装；
- “学习”= 用户批准、版本化、可回滚、通过回归测试的程序性记忆更新；
- 本地模型不能写文件、执行任意命令或自动安装 skill。

Phase A 可先做：skill registry、规则路由、skill outcome 记忆、失败计数。

---

## 29. 群成员 / 关系记忆（Phase 2.5）

### 29.1 现状审计

只读检查 `memory-card.js`：

- 记忆记录有 `speaker`（显示名，40 字）和 `groupId`；
- `memory-inbox.jsonl` 有 `senderId`，但 `ingestInboxLines()` **没有把它传给 `addMemoryRecord`**；
- 记忆记录里没有 `senderId` / `personId`；
- 没有人物表、关系表、按人聚合的印象；
- `touchMemories()` 只按文本召回，不按说话人；
- 群成员名字缓存只用于工具，不进入记忆。

结论：

> **SurfCore 没有“对群内高发言者分别记忆/构建关系”的功能。**  
> 现在只有“某条记忆的说话人显示名”，没有稳定身份，也没有人物长期画像。

### 29.2 为什么不能直接按昵称合并

- 昵称会改；
- 不同群可能有同名；
- 同一个人在不同群/私聊出现；
- 主人、群友、陌生人、自己必须分开；
- 一条“群友说”的记录不能直接变成“这个人的人设”。

所以身份键必须是：

```text
platform + user_id
```

显示名只做别名，不做主键。

### 29.3 本地数据层

新增：

```text
people
  id                  qq:<user_id>
  platform            qq
  user_id
  display_name
  aliases_json
  first_seen
  last_seen
  message_count
  familiarity
  trust
  valence
  unresolved
  is_owner
  notes

person_impressions
  id
  person_id
  scope               group:<id> / private / global
  text                可读印象
  evidence_memory_ids
  confidence
  importance
  created_at
  updated_at

memories
  + person_id
  + speaker_id
  + identity_confidence
```

原则：

- 一条记忆只**链接**人物，不复制一份；
- 人物印象由多条证据记忆聚合，不是单条；
- 关系数值来自对该人物相关记忆的评价，不写死“熟人=友好”；
- 高发言者达到阈值才建/刷新人物卡，不是每句话都建。

### 29.4 分步实施

#### Step 1：保留身份（最先做）

- 同步 `memory-inbox.jsonl`，保留 `senderId / sender / groupId / conversationKey / isOwner / isSelf`；
- 给本地 memories 加 `speaker_id` / `person_id`；
- 旧 memory-card 记录只有显示名，先低置信度回填，不强行合并。

#### Step 2：人物身份

- 以 `qq:<userId>` 为主键；
- 别名表处理改名；
- 主人单独标记；
- 同名跨群不自动合并，除非有稳定 userId。

#### Step 3：人物卡与关系

- 统计 message_count / last_seen；
- 对高频发言者生成 person profile；
- `familiarity` 由互动频率和召回更新；
- `trust/valence/unresolved` 由该人物相关记忆的评价聚合；
- 区分“这个人在这个群”与“这个人在私聊”的 context。

#### Step 4：人物印象

- 只有多条一致证据才写“印象”；
- 单次事件只做 episodic memory，不升级成人格判断；
- 印象必须带 evidence memory ids 和 confidence；
- 可被新证据修正，不永久钉死。

#### Step 5：进入上下文

- 当天触发了某个人 → daily context 才带这个人的人物卡；
- 没触发的人不进入发言上下文；
- 不把全部群成员塞进提示词。

#### Step 6：进入 P / affect

- 人物关系作为 P 的一个子项，但避免和记忆评价重复计权；
- 先做 shadow：观察“人物信任/熟悉度”是否稳定，再决定注入；
- 不把“对某人的态度”写成固定性格。

#### Step 7：UI / 隐私

- 人物列表、别名、印象、证据；
- 可删除/导出某人的全部数据；
- 敏感记录不进入人物卡；
- 不展示临床/诊断标签。

### 29.5 放置位置

放在 **Phase 2（记忆同步稳定）之后、Phase 4（P 实装）之前**。  
理由：

- 没有稳定 person_id，P 的 trust/sociability 会被同名/群聊噪音污染；
- 人物层本身依赖 inbox 身份，必须先补同步；
- 人物印象需要 appraisal 已经稳定。

### 29.6 不做的

- 不改 SurfCore 的记忆卡结构；
- 不把人物数据写进 SurfCore；
- 不按昵称做全局合并；
- 不因为一个人发言多就自动认定“关系好”；
- 不把群友印象写成永久标签。

### 29.7 实装状态（2026-10-29）

已落地：

- `sync-inbox` 只读导入 `memory-inbox.jsonl`，保留 `senderId/sender/groupId/conversationKey/isOwner/isSelf`；
- 主库合并后：**38 条记忆、5 个人物**；25 条非本人消息，44 条本人消息按 `--no-self` 跳过；
- `people` / `person_daily` / `person_impressions` / `person_feedback` 表；
- `memories` 增加 `speaker_id / person_id / identity_confidence / group_id / conversation_key / speaker`；
- 用 text+speaker 做 card/inbox 去重，避免同一事件两份；
- `people.refresh`：按 appraisal 聚合 trust/valence/unresolved，按天写 `person_daily`，并用 EMA 刷新人物长期值；
- `sleep` 现在会先刷新人物日结；
- `context` / `shadow` 会带 `person_cards`；
- 单测 10/10。

真实人物结果（示例）：

```text
WindyDaylight  15 条  familiarity 0.85  trust 0.59  valence +0.20
凯坑卓斯        5 条  familiarity 0.46  trust 0.60  valence +0.18
露卡            3 条  familiarity 0.31  trust 0.50  valence +0.17
```

触发一条该人物记忆后，daily context 自动带出这个 person card。  
person card **还没有注入请求**，目前只在 `context` / shadow 中可见。

### 29.8 还没做

- `is_owner` 目前 inbox 全为 false，主人识别要单独接；
- 同一人物在不同群的 group-specific 关系；
- 多条一致证据生成语义印象（当前只有每日数值摘要）；
- 人物关系进入 P/affect 的 shadow；
- 可视化人物页；
- 把 person card 注入发言层。

### 29.9 侧写、关系姿态与 #行动（已实装）

累计发言 **>= 10** 后：

- `people-due` 标记需要侧写；
- `people-profile` 用本地模型生成 **草稿**：
  - `personality`
  - `speaking_style`
  - `hobbies`
  - `summary`
  - `confidence`
- 写入 `person_profiles`，`status=draft`，不覆盖旧版本；
- 高层 API 以后可复核/改写，本地不自动当事实；
- 已有草稿后，**新增 10 条证据**才再次标记 `due`，不是每天强行重写；
- `profile_basis_count` 记录这份侧写基于多少条消息。

关系姿态由数值推导，不写死：

```text
trust >= 0.55 且 valence >= 0.12 且 familiarity >= 0.50
→ build（维护关系）

trust <= 0.45 或 valence <= -0.15 或 unresolved >= 0.55
→ cautious（谨慎）

其余
→ casual（自然相处）
```

每个姿态都配一个诚实的 `#行动`：

```text
build    #行动：主动接住对方的话，记住他提过的小事，适度延展；不刻意讨好。
casual   #行动：自然回应，保持礼貌；不主动深挖对方私事，也不冷淡。
cautious #行动：简短回应，先观察；不主动透露自己的私事，不轻易承诺。
```

真实样本：

```text
WindyDaylight
15 条
familiarity 0.85 / trust 0.59 / valence +0.20
stance build
profile_version 1 (draft, confidence 0.6)
```

侧写内容示例：

```text
理性思考者，注重内在认知，对 AI 有批判性……
口语化，自省和调侃，常用比喻和对比……
兴趣：探索 AI 与人类认知边界、研究记忆与人格成长……
```

注意：这是 2B 的草稿，可能过度概括；必须保留 `draft` 状态，不能当永久标签。

---

## 30. 本地 Skill Phase A（已实装）

实现 `soulcore/skills.py`：

- `skills` / `skill_runs` / `skill_requests` 表；
- 4 个白名单确定性 executor：
  - `memory.sync_inbox`
  - `memory.people_refresh`
  - `memory.consolidate`
  - `memory.recall`
- 规则路由：`route(text)`，不做自由生成；
- 每次运行记录 `ok / latency / input / result / error`；
- 成功/失败都写一条 `source='skill'` 的事件记忆，进入 appraisal；
- 连续 3 次失败生成 `skill_improvement_request`，不自动改 skill；
- CLI：`skills` / `skill-route` / `skill-run` / `skill-requests`。

真实运行：

```text
skill-route "同步一下群聊记忆"
→ memory.sync_inbox (rule:同步)

skill-run memory.people_refresh
→ ok, updated 5, outcome_memory skill:run:1
```

社会 shadow：

```text
people_count 5
weighted_trust 0.58
weighted_valence +0.23
unresolved 0.37
stances build 1 / casual 4
```

注意：

- 本地模型暂时不参与路由；规则优先；
- 还没有 skill outcome 的专门 appraisal 权重；
- `skill_improvement_request` 还没有 UI/高层 API 处理；
- 不自动安装/改 skill。

---

## 31. 本地日常管线（daily）

新增：

```text
soulcore daily
```

顺序：

```text
sync-inbox
→ appraise pending（可 --skip-appraise）
→ people.refresh
→ consolidate
→ dream
→ social shadow
```

不生成日记，不调用高层 API，不写 SurfCore。  
用户入口：`soulproject\daily.cmd`。

实测（people 副本）：

```text
inbox new 44 / seen 25
people updated 5
ambient count 22 / mean 0.1391 / flagged false
dream today_important 3 / random 5
P memory_count 3
social build 1 / casual 4
```

注意：

- daily 默认包含 self 消息；需要只建人物关系时用 `--no-self`；
- `--skip-appraise` 可用于只同步/巩固；
- 日记/计划仍应由 SurfCore 高层 API 生成。

---

## 32. 接入面与当前阻断（2026-10-29）

### 32.1 已做

- `persona.md` 已加“认知取向”：
  - 自发偏向人类式思考；
  - 讨论相关话题会学习/查证/对照；
  - 平时不口头说，只在日记/总结/复盘里写；
  - 不宣称意识/灵魂。
- 本地 `render-context` 可生成：
  - P 数值；
  - 当天触发人物卡；
  - 关系姿态 + `#行动`；
  - 侧写草稿。
- 文件：`soulproject/data/soulcore-context.md`。
- 未注入 SurfCore。

### 32.2 真实接入面

不是“只改 persona + 记忆后处理”：

1. `persona.md` 是静态的，能改说话原则；
2. `memory-card-prompt-qq.md` 是 SurfCore 维护的记忆块，不能可靠塞 P；
3. `llm/stream` 的 LOOP request 是深冻结的，只能读，不能改 system/messages；
4. 真正的 P/person card 注入需要 SurfCore 的 prompt 组装点：
   - 桌宠：`lib/pet-chat.js` 的 `buildChatSystemPrompt`；
   - QQ/B站：各自的 prompt/agent 组装点，需另接。

### 32.3 对运行中的 SurfCore 的影响

- `persona.md`：`pet-chat.js` 的 `roleInfo()` 每轮 `textFile(personaFile)` 读取，下一轮桌宠对话生效；不需要重启。
- 如果改 `pet-chat.js`：运行中的模块不会自动换代码，需要重载 SurfCore 插件/重启 DSH。
- `memory-card-prompt-qq.md`：按 mtime 缓存；改文件后下一次读取生效，但 SurfCore 维护会重写。
- 目前 P/person card **没有进入提示词**，所以对当前说话行为没有影响。

### 32.4 待批准的最小补丁

在 `pet-chat.js` 增加一个只读函数：

```js
function soulCoreContext() {
  const file = process.env.SOULCORE_CONTEXT_FILE
    || path.join(STATE_DIR, 'soulcore-context.md');
  try { return fs.readFileSync(file, 'utf8').trim().slice(0, 1800); } catch { return ''; }
}
```

在 `buildChatSystemPrompt` 的 memory 后面追加：

```js
const soul = soulCoreContext();
if (soul) {
  lines.push('【SoulCore 当前状态（背景，不主动解释）】');
  lines.push(soul);
  lines.push('');
}
```

然后：
- `render-context` 写到该文件；
- 重载 SurfCore 插件/DSH；
- 先用 shadow 对照，再决定是否注入。

**这一步会改 SurfCore 代码，所以我停在这里等确认。**

### 32.5 已应用并验证（2026-10-29）

用户确认可以关闭重开后，已打补丁：

- 安装版与源码版 `pet-chat.js` 同步修改；
- 原文件备份在 `soulproject/backups/`；
- `node --check` 通过；
- `render-context` 写入 `~/.dsh/surfcore/soulcore-context.md`；
- `daily` / `sleep` 结束时会自动刷新这个文件；
- SurfCore 插件禁用再启用，日志显示已重新激活；
- 桌宠 `/chat` 实测成功。

验证回复：

```text
“哼，当然记得，就是那个爱琢磨模型能不能模拟人类思维的人嘛…”
```

这句话来自 `WindyDaylight` 的 person profile，说明 P/人物卡/`#行动` 已进入桌宠 system prompt，而不是只停在 shadow。

范围：

- ✅ 桌宠 `pet-chat.js`
- ✅ QQ `src/bridge.js`（v1/v2 唤醒、角色提示、purpose 上下文）
- ✅ B站 `scheduler.js`（主唤醒）+ `bili-share-scheduler.js`（定时分享）
- ✅ B站只注入 P，不携带 QQ 人物卡
- ❌ 还没有把 surfcore 记忆卡写成人物卡

QQ 补丁点：

- `roleHintForMode()` 追加 SoulCore block；
- `purposeContextBlocks()` 追加；
- `buildWakePromptV2()` 的 `base` 追加。

QQ bridge 已重启：

```text
PID 34832
SnowLuma 已连接
DSH 已就绪（reserved2）
```

尚未做“真实 QQ 消息端到端”测试；只验证了语法、启动和无加载错误。

### 32.6 QQ 身份修复（2026-10-29）

发现并修复：

- 旧 inbox 去重条件是 `text_hash + speaker(昵称)`；
- 同名不同 QQ 号、同文本时可能被误合并；
- 现在改为 **senderId 优先**：
  - `speaker_id` 相同才合并；
  - 昵称只在没有 senderId 时做弱匹配；
  - `person_id = qq:<userId>` 不变；
  - 昵称改名只追加到 `aliases`，不改 person_id。

新增测试覆盖：

- 同名不同 QQ 号 + 同文本 → 2 个 person，不合并；
- 同 QQ 号跨群 + 改名 → 1 个 person，aliases 保留两个名字。

### 32.7 owner 配置（2026-10-29）

用户确认 owner QQ = `<ownerQQ>`，已设置：

- `config.json.ownerQQ = "<ownerQQ>"`
- `config.json.purpose.ownerUin = "<ownerQQ>"`
- 本地 `qq:<ownerQQ>` → `is_owner=1`
- bridge 重启后警告消失
- 当前 bridge PID 33528

B站按用户要求暂停；`#行动` 漏正文按用户要求不过滤。

---

## 33. 表层意识的记忆查询工具

之前缺口：

- 表层意识只拿到预注入的 P/人物卡/记忆卡；
- 它不能主动查“自己的长期记忆”；
- 问“你还记得……”时只能依赖当前 prompt。

现在新增只读工具：

```text
soulcore_memory
```

模式：

- `overview`：记忆数、P、top people、今日 context 数
- `today`：今天触发的记忆；可按 person/scope 过滤
- `search`：按关键词检索；可按 person/scope 过滤
- `person`：某个 QQ 的人物卡 + 最近原文
- `range`：按日期/时间范围查；支持 `date` 或 `from`/`to`，可按 person/scope 过滤
- `p`：当前 P

有限性：

- 一次最多 20 条；
- 返回 `matched / returned / truncated`；
- `truncated=true` 时明确提示“只是抽样，不要声称完整记忆”；
- 固定日期/时间也必须接受这个上限，不能假装全知。

实现：

- Python `soulcore memory --mode ...`
- `soul-bridge` Host 插件注册 `ctx.tools.register`
- 普通 `search`（无 person/scope）复用 SurfCore 内置 `recallFullMemory()`，不再重写一份关键词召回
- 带 person/scope/日期时用本地 SQLite 索引补足（内置召回不支持这些过滤）
- 每次工具调用写 `data/memory-tool-calls.jsonl`
- `memory-log` 可查
- 已实测 `overview` / `person` / `search` / `surfcore`

安全边界：

- 当前是全局工具，QQ 群友也能让模型调用；
- QQ preset `qq-tool-restrict` 原本拒绝所有本地工具；已把 `soulcore_memory` 加入唯一例外；
- preset/guard 启动时加载，必须完整重启 DSH；
- 工具仍在本机 DSH Host/Python/SQLite 执行，不经过 QQ API；
- 正式使用前建议限制 owner/私聊，或按 `conversationKey` 过滤 person/text。

### 33.1 旧记忆身份修补（2026-10-29）

旧 SurfCore 记忆卡里 5 条没有 senderId/speaker：

```text
4 条 isSelf=true   → self
1 条 isSelf=false  → legacy_unresolved
```

绝不能默认归给主人。

已加：

- `memories.identity_status`：
  - `resolved`：有 senderId/person_id
  - `self`：她自己说的
  - `legacy_unresolved`：旧记录，说话人不明
  - `synthetic`：demo
  - `system`：skill
- `repair-identities` 回填；
- 查询结果带 `identity_status`；
- `memory` 输出带 `identity_notice`；
- `soulcore-context` / persona 明确“旧记录说话人不明时不要归给主人”；
- `daily` 会先跑回填。

### 33.2 SurfCore sidecar 已接通

`export-surfcore` 生成：

```text
<character>/memory/memory-card-full.soulcore.jsonl
```

内容：

- enrichment：29 条已有 SurfCore 记录的评价/身份/索引
- extension：5 条人物卡 + 1 条 affect/P 快照

SurfCore `memory-card.js` 读取层已合并：

- `scanFullRecords` / `readAllFullRecords` 读 sidecar
- enrichment 按 `record_id` 合并
- extension 作为额外记录
- `fullMemoryCardSnapshot` 返回 `soulcore`

实测 `recallFullMemory("情感")` 能返回 `soulcore:affect:latest`。  
DSH 宿主需重启才会加载最新 `memory-card.js`。

### 33.3 DSH 设置页

已安装 `@soulproject/soulcore-settings`：

- Settings → **SoulCore**
- 功能开关：记忆查询、影子检索、写回标记
- 运行参数：Python/SQLite/Node 路径、超时、并发
- 操作：导出 sidecar、运行评价、修复身份、测试查询
- 调用记录：`memory-tool-calls.jsonl`

详见 `docs/SETTINGS-UI.md`。

### 33.4 每日记忆的感受与偏离量

本地评价改成两段式：

1. **第一段**：只评价事件本身（没有基准数值，避免 2B 抄基准）。
2. **第二段**：把精确基准喂给本地模型，只生成第一人称 `felt`。
3. **delta**：由控制器按 `第一段评价 − 当日基准` 确定性计算。
4. **adjusted**：`baseline + delta`，仅作审计；P 仍用第一段事件评价，避免基准重复加权。

每日记忆卡：

- 单条记录只展示 `felt + delta`，不再显示绝对基准；
- `renderMemoryCard` 从 sidecar 合并 `soulcore`；
- 新增 `## 最近的情绪附注（当时的感受）`，确保有限 prompt 里也能看到近期感受；
- 绝对基准只在 `soulcore:affect:latest` / P 快照中记录。

已回填 30 条真实记忆的 `felt + delta`；15/15 单测通过。

### 33.5 日初基准与日累计偏移

SurfCore 自己的每日整理只维护记忆卡，不记录 P/基准；SoulCore 原来也只有当前 `p_snapshots`。

新增 `daily_summaries`：

- `baseline_json`：日初 P
- `baseline_at`：基准记录时间
- `end_json`：consolidate/dream 清洗后的 P
- `delta_json`：`end − baseline`
- `kept` / `ignored`
- `ambient_json`

账本公式：

```text
清洗后 P = 日初基准 + 当日累计偏移
当日累计偏移 = 清洗后 P − 日初基准
```

`delta` 是带符号的；如果你想把“偏移”当正数幅度，则是 `end = baseline + signed_delta`，负向事件会自然得到负 delta。

抓取时机：

- `soul-bridge` 启动时调用一次 `day-baseline`（本日第一次登录）；
- `daily` / `sleep` 在当天新评价前再兜底一次；
- `daily` / `sleep` 在 consolidate/dream 之后写 `end / delta`。

`soulcore:daily:<day>` 会作为 SurfCore sidecar 扩展出现，可直接查询。

注意：当前还没有历史日初基准；从下一次 DSH 启动 / `daily` / `sleep` 开始记录。`day-summary` 可查看。

### 33.6 评价模式学习（代码化）

新增 `appraisal_learning`：

- 只从 `ollama:*` 评价学习，排除 `pattern-v1` 自产数据；
- 中文 2/3-gram + 英文词特征；
- 过滤单次特征，避免小样本碎片化；
- 余弦聚类成 pattern；
- `shadow` 模式：模型仍跑，pattern 影子对照；
- `auto` 门槛：至少 5 次对照、shadow accuracy ≥ 0.70；
- 未命中/低 support/高方差自动回退本地模型。

命令：

```text
learn-appraisals
appraisal-report
appraisal-policy --mode shadow|auto|off
```

当前：38 个例子、17 个模式、默认 shadow。  
详见 `docs/APPRAISAL-LEARNING.md`。

#### 33.6.1 代码优先主路径

`appraise_pending` 现在先执行固定程序评分：

- 每条记忆都生成完整 appraisal，不会跳过；
- 普通闲聊/复读/短句使用 `code-v1`；
- owner、高 importance、长文本、冲突、强负向、承诺、不确定提问才升级本地 2B；
- AI 失败时保留 `code-v1` 评分，并复用 SurfCore 现有 `/api/test-send` 私聊 owner 询问；
- bridge 不可用时落 `data/appraisal-questions.jsonl`；
- 没有新建交流模块。

#### 33.6.2 修正闭环

`appraisal_questions` 保存失败包。表层可用 `soulcore_memory`：

```text
questions  查看待确认
resolve    提交 owner 答案 + 表层 8 维评分
```

resolve 新建 `surface-correction` 记忆，`appraiser_id=surface-v1`，不调用本地 AI；  
旧记忆 `affect_weight=0`、`consolidation_state=superseded`，sidecar 标 `superseded_by`；  
新修正作为 `soulcore.correction` extension，`loadMemoryCard` 隐藏旧记录并显示新记录。  
全量档案保留旧记录，可追溯。

#### 33.6.3 目的机制情绪种子

SurfCore 目的机制继续做唯一执行器；SoulCore 写 `soulcore-purpose.json`：

- 用当日 `daily_summaries.baseline`，不用长期累计 P 直接覆盖；
- P 八维换算成 9 个 drive；
- `pending_chance`、`urgency` 动态化；
- 缺文件/过期/非当日时完全回退旧逻辑。

详见 `docs/PURPOSE-INTEGRATION.md`。









运行中的影响：

- 桌宠下一轮对话即生效；
- 重载插件后旧代码已替换，不需要整机重启；
- `persona.md` 仍然每轮热读。

















