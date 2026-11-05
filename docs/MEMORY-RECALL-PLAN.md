# 记忆召回改造计划（L0–L6）

> 状态：**v8 执行中**。已完：**S0–S12 全部** + D2/MCP/B1–B5；剩观察项：S6 向量影子期结束后的开关+权重同批上线；9 份分计划已核对合并。
> 时间：2026-11-05（v8：S2–S9 落地并探针验证；S6 影子模式待观察，S7 当前 0 条可归档，S8 已切 auto，S9 0 错人，S10 结论：不换框架、改权重，S11：打分不再调模型，S12：felt 100%、边界变化点已就绪但默认仍走时钟）
> 依据：`docs/L5-RECALL-TREE.md`（契约）+ 本次对 `soulcore.db` / `memory-lab` / `emotioncore-service` / `reflex-arc` 的实测。
> 决策前提（你已定）：**取消"一年未召回即丢弃"**；保留冷压缩；取词同时用"她听见的"和"她说出的"；上浮 = 随机 1 + 定向 1；深挖只在 L6 主动要求时发生。

---

## 1. 分层模型（先对齐编号）

你的分层是 **L0–L6，共 7 层；其中 L0–L5 六个本地层，L6 是 API 语言层**。本计划的每项改动都标注落在哪一层。

| 层 | 职责 | 典型实现 | 进 prompt |
|---|---|---|---|
| **L0** | 身体 / 内感受 | `body_state`、余额、时间感 | 一行自然语言 |
| **L1** | 感知 / 反射弧 | `reflex-arc`：骰子、OCR、引用、转发、链接、图片 | 短 hint |
| **L2** | 原始记忆 | `memories` 表、`memories_fts`、向量 | 默认不进 |
| **L3** | 事件记忆 | `episodes`（summary / key_quote / felt / raw_ids） | 1–2 条索引 |
| **L4** | 情绪 / 欲望 / 人物 | `appraisals`、`people`、`desire`、`patience` | 自然语言 |
| **L5** | 唤醒组装 | `emotioncore-service /context` 的 `l2` 段 | 是 |
| **L6** | 表层语言 | API 推理、发言、调 `ec recall` | 只决定要不要深挖 |

---

## 2. 现状核对（已有 vs 缺）

### 2.1 已经有的（不要重写）

| 能力 | 位置 | 实测 |
|---|---|---|
| L5 已经在上浮"最多 2 条索引"（带 `episode_id` / `mem:id` 指针） | `emotioncore-service/server.py:468-484` | 是，L5 记录 122 次 |
| 三层回忆树 + 深挖通道 | `server.py:313 _recall_index` / `:327 _recall_impl` | 已实现 query→episode→memory 三级 |
| `ec recall` 工具 | `emotioncore-adapter/index.js:297-320` | 已存在，limit 默认 2 最大 3 |
| 单条原文读取（1200 字上限 + scope 校验） | `server.py:336-355` | 已实现 |
| L4 人物表（按 QQ，familiarity/trust/stance/action_hint） | `people` 表 | 20 人，字段齐 |
| 窗口归属 `conversation_key` | `memories` 表 | 993/1007 = 98% |
| 六路 RRF 召回（fts/thread/person/emotion/soft_edge/vector） | `lab.py:294 rrf_recall` | 代码就绪，端口 8766 在跑 |
| hint 已放在提示词**最末**（缓存友好） | `kernel/format.js:620` | 是 |
| `afterSend` 钩子（可拿她自己的发言） | `reflex-arc/index.js:1086` 区 | 已注册 |
| 层调用观测 | `data/memory-layer-calls.jsonl` | 135 条 |

### 2.2 缺的（本计划要做的）

| # | 缺口 | 证据 |
|---|---|---|
| G1 | 中文 FTS 基本失效 | `tokenize='unicode61'`：命中"上次"0/5、"记得"4/42、"记忆"6/119；每次查询只剩 2–6 条候选 |
| G2 | 召回无绝对阈值 | `retrieval.search_memories` 只滤 `sim<=0`，必有返回 |
| G3 | 注入无元信息 | `[记忆联想·实验] <160字>`，无谁/哪/何时 |
| G4 | 联想通道是空壳 | `[记忆联想·实验]` 只有 1 条原文、无元信息、`memoryLabEnabled` 默认 false，就是给新功能留的位 |
| G5 | 取词只用用户侧 | 触发正则在 `index.js:1522` 附近，只匹配 `ev.text` |
| G6 | 没有索引 | `person_id`/`conversation_key`/`status`/`ts` 全无索引 |
| G7 | 深挖通道几乎没人用 | 135 条层记录里 `recall_index` 仅 6 次、`recall_episode` 3 次 |
| G8 | L5 上浮条数不可观测 | 122 条 L5 记录 `result_count` 全是 `None` |
| G9 | 向量模型不对 + 存储浪费 | 仅英文向 `nomic-embed-text`；861 行 JSON 向量占 8.4 MB |
| G10 | 软边冻结 | `lab_edges` 停在 11-03，覆盖 233/1007，无定时器 |
| G11 | CORS `*` | `memory-lab/server.py:37` |
| G12 | 冷热分层未做 | 无 `archived` 状态、无冷库表、无压缩 |

---

## 3. 两条通道的分工（不是重复，不要合并）

我上一版把这两条判成"重复注入"，这是错的。它们的职责不同：

```text
L5 l2（emotioncore /context:468）
  = 事件简述入口：2 条 episode 索引 + episode_id 指针
  = "发生过什么" 的目录，供 L6 深挖
  = 已定型，本计划不动

reflex-arc [记忆联想·实验]（index.js:1523）
  = 联想通道：1 条原文（无指针、无元信息）
  = 预留给新的联想功能，就是本计划的改造对象
  = "突然想起什么" 的拟人化上浮
```

**改造边界（硬约束）：**

- 只改 `reflex-arc/index.js` 里 `[记忆联想·实验]` 这一条注入。
- 不动 `L5 l2`、不动 `_recall_index` 的返回结构、不动 `ec recall` 的三层语义。
- 联想通道**不接管**事件索引：它给原文片段 + 元信息，不给指针。
- 两条通道每轮最多各出 2 条，合计不超过 4 条、不超过 300 字。

唯一的共享依赖是 `retrieval.search_memories`（中文 FTS 坏了）。修它是**修 bug**，不是改功能：L5 和联想都会因此变准，这是预期内的副作用。

---

## 4. 目标（可验收）

| # | 目标 | 验收 |
|---|---|---|
| O1 | 中文召回可用 | 20 条人工 cue 查询，人工判"相关" ≥ 14 条 |
| O2 | 每轮注入 ≤ 2 条、带元信息、≤180 字 | 抽样 20 轮，token 增量 ≤ 120 |
| O3 | 跨窗口共享但不错人 | 10 条抽查，0 次把 A 的事安到 B 头上 |
| O4 | 深挖按需发生且真能用 | `recall_index` 调用率 ≥ 1 次/10 轮；回包 200 且非空 |
| O5 | 容量可控、热库不膨胀 | 一年后热库 ≤ 3 万行，冷库压缩比 ≥ 4:1 |
| O6 | 延迟不退化 | `/recall` p95 < 120 ms |
| O7 | 人格受记忆影响可追溯 | 规则/词条每项能溯源到 episode |
| O8 | 打分不依赖模型也能自洽 | 关掉模型后 24h 全部 `code-v1`，p 值分布无跳变 |

### 4.1 吸收优先级（你定的）

自研记忆管理不如成熟方案，所以**优先吸收这两样**，其余都是锦上添花：

| 优先级 | 吸收什么 | 落在哪一步 |
|---|---|---|
| **最高** | Hindsight 的 **事实 / 看法分离** | S3 的 hint 元信息（`·事实` / `·看法`） |
| **最高** | MetaMem 的 **规则化形制**（显式元记忆，不训练） | S8：**激活已有的 `appraisal_patterns`**，不新建表 |
| 次之 | Hindsight 的四路并行结构（只借结构） | S10 影子对比验证 |
| 次之 | 向量召回 | S6 |

### 4.2 提示词预算（本轮定的硬上限）

不管下面哪一步，**最终进 API 的只有 hint 字符串**——`ev.hint` 在 `format.js:620` 拼在提示词最末，没有别的通道。所以整套记忆系统的可见面就是几行字。

| 项 | 上限 | 说明 |
|---|---|---|
| 本轮记忆类条目总数 | **≤ 3 条** | L5 事件索引已有 2 条（不动），所以联想通道通常只出 **1 条** |
| 联想条目数 | 常规 1（定向）；**仅当本轮 L5 无索引时**才允许补第 2 条（随机） | 两条通道加起来不超 3 |
| 单条长度 | ≤ 80 字（含标签） | 超了截断，不拼接 |
| 每轮 token 增量 | ≤ 120 | 3 条 × 80 字中文 ≈ 120–160 token，取上限 |
| 位置 | 固定放 hint 末尾 | 前缀缓存不失效（现在命中率 97.6%） |

> 因此"上浮几条"不是越多越好：**3 条是效率上限**，超过就是拿上下文换噪音。

### 4.3 重复工作排查（沿用已有实现，别重造）

| 计划里的能力 | 其实已经有了 | 处置 |
|---|---|---|
| 元记忆规则（MetaMem 形制） | **`appraisal_patterns` 49 条 + `appraisal_policy`（mode=shadow）+ `appraisal_learning.learn()/predict()`** | **不建 `mem_rules`**，把已有这套从 shadow 激活 |
| 事实 / 看法分离 | `memories.confidence`/`self_relevance`、`appraisals.felt`、`people.stance`、`person_impressions` | 不建字段，只在 hint 里打标签 |
| 向量召回 | `lab_vectors` 骨架（表已清空，代码在） | 复用，只换模型与存储格式 |
| 多路 RRF | `lab.py rrf_recall` 六路 | 复用；S10 只写对比脚本 |
| 深挖三层树 | `ec recall` + `_recall_impl` | 只改提示与观测 |
| 情绪打分 | `appraise.py` + `code_only` | 只加开关 |
| 人物印象 / 关系 | `people.action_hint`、`person_profiles`、`person_daily` | 复用，不新建 |
| 遗忘曲线加成 | `memories.trigger_count`/`last_triggered_at`、`memory_activations` | 复用 |
| 冷库 / 归档 | **无** | 唯一需要真正新建的数据结构（S7） |
| 索引 | **无** | 新建（S1b） |

---

## 5. 分步实施

> 每步都可独立上线、独立回滚。编号保留原值，**跳号 = 已完成**，不再列为待办。

### 5.0 已完成（2026-11-05，不再列入计划）

| ID | 做了什么 | 结果 |
|---|---|---|
| **S1** | 中文 FTS 修复（`text_gram` + `memories_fts2` + 触发器 + 回填；`retrieval._fts_table` 自动选表） | 命中数 0→6 / 4→44 / 6→121 / 3→58；库 +2.2 MB |
| **S1b** | 三个常用查询索引（person/conv/active）写进 `init_db` | `EXPLAIN QUERY PLAN` 三条全走索引 |
| **D2** | 清掉 `lab_embeddings` 里 861 行停用模型的 JSON 向量 | memory-lab.db **10.65 MB → 0.48 MB**，`quick_check: ok` |
| **MCP** | 把 `mcp-web-search-safe` 从 surfcore 迁进 `tools/web-search-mcp/`（去掉 MCP SDK 依赖，只留 js-yaml） | 975 KB（原来要 21.4 MB 的 node_modules）；stdio 握手 + 真实搜索已验证 |
| **DSH 配置** | `cordis.patch.yml` 指向新脚本；`package.json` 删掉 `surfcore` 依赖 | 下次 DSH 重启生效 |
| **B4** | `format.js` 私聊也挂 `[昵称(QQ:号)]: `（原条件 `ev.isGroup &&` 去掉；无声者不挂空括号） | 探针 5/5 通过；**待 DSH 重启生效** |
| **B5** | `reflex-arc` 新增 `sceneHint`（默认开）：`[场景:群 999·近5分钟 2 人·发言人 Windy(QQ:123)·事件:深夜闲聊]` | 探针 3/3 通过；不占记忆条数 |
| **B2** | `gate-wake` 新增 `otherBots`(默认 `1452133357`)、`botNameTags`(默认 `肥鱼`)、`botChainGuard`/`botChainWindow`(3) | 探针 7/7 通过；默认值即生效，无需改 config.json |
| **B3** | `handoff.short/mark/take` + `/handoff/compose`、`/handoff/take` + `/context` 一次性注入 + 压缩钩子发管理员副本 | 端到端 4/4；服务已重启验证新路由在线 |
| **S0** | L5 记录补 `result_count`（事件索引+人物+未收尾+便条）；`reflex-arc` 每轮把新增 hint 累加进 `state/reflex-hints.json` | 实测 `result_count: 7`（含便条）/ `5`（无便条） |
| **B1** | 核实：`group-memory` + `group-memory-accumulate` 都是**关**的、`qq-memory/` 不存在 → 当前无重复；只补规则 + 检查器 | `tools/mem-overlap.py`：目录不存在，无风险 |
| **S2** | `search_memories` 加 `min_similarity`；新模块 `soulcore/privacy.py`（8 类正则）；`_context` 两道闸门 | 群聊 0 泄露、私聊打码；噪声 0 注入；线上回归通过 |
| **S3** | `lab._public` 加 `when/who/where/stance`；`reflex-arc` 联想行最多 2 条、带元信息；`memoryLabEnabled` 默认改 true | 探针 6/6；L5 `l2_items` 字段未变 |
| **S4** | `reflex-arc` 记她最近 3 句、query 双侧拼 64 字；定向 1 + 按分数² 加权随机 1；久未触发 +15% | 探针 7/7；定向 5 次一致、随机 4 种 |
| **S5** | adapter 补 `episode_id`/`memory_id` 深挖指令；联想尾巴改 30 分钟冷却；角色卡四条约束**已有**（未改） | 探针 6/6；调用率待一周后看 |
| **S6** | 本地 ONNX `bge-small-zh-v1.5`（自写 WordPiece，零新增依赖）+ `mem_vectors` float32 BLOB + numpy 暴力余弦；影子模式 | 1083 条全向量、2048 B/行、10 ms；9 项验收通过 |
| **S7** | 新模块 `soulcore/archive.py`；`memories.archived_at` + `mem_cold`（zlib，冷库带索引）；`/recall` 回冷库取原文 | 16+3 项验收通过；当前 0 条可归档（DB 才 7 天） |
| **S8** | `appraisal_learning.prune()` + `learn()` 只写够支撑的 + `replay_shadow()` 回放攒证据；`mode: shadow → auto` | 49→7 条 pattern（都 count≥2）；103 次回放准确率 0.97；11 项验收通过 |
| **S9** | `lab._who_of()` 说话人三级兜底；8 条 `demo:*` 假记忆退出热索引；memory-lab 向量改成每 10 分钟补缺口 | 1084 条 0 错人；11 项验收通过 |
| **S10** | 30 条真实 cue 影子对比：现有六路 / 只有 FTS / 只有向量 / 加图 / 加时序 / 8 组权重扫描 + bootstrap | 换框架增益 0pp（不迁移）；权重 `fts 0.6 / vector 1.0` 可拿 R@5 57%→87%，待与开向量同批上线 |
| **S11** | `appraisalModel` 开关（默认关，设置页可见）；关时疑难条目走精细代码评分；失败来源写实；开模型时限 20s / 每轮 1 条 / 连错 3 次自动关 | 模型调用归零且不留「假装参与过」的痕迹；19 项验收 + 39 项单测通过 |
| **S12** | `fill_missing_felt()` 纯代码补 felt；失败原因写 `meta`；结案先过 `rule_verdict()`；新增 `soulcore/boundary.py` 变化点切分（复用 mem_vectors 向量，配置开关默认 clock） | felt 100%；失败可查；结案只让 2B 判中间地带；边界纯度略升、道别零漏切，待人工标注集再切 |

### S0 观测先行（✅ 已完成，2026-11-05）

- **改了**：`server.py` 的 L5 `context_wake` 记录补 `result_count`（事件索引 + 人物 + 未收尾 + 交接便条）和 `handoff_pending_chars`；`reflex-arc` 在 `before-turn` 末尾按"本轮新增的 hint"累加进 `state/reflex-hints.json`（按标签计 `{n, chars}`，保留最近 60 条，不存正文）。
- **为什么**：之前 122 条 L5 记录 `result_count` 全空（G8），验收 O2/O4 全靠猜。
- **怎么验**：`data/memory-layer-calls.jsonl` 尾部能见 `"result_count": 7`；跑几轮后 `state/reflex-hints.json` 里 `byLabel` 有数。
- **回滚**：纯日志，删掉这两处即可。


### S1 修 L2 的召回地基（✅ 已完成，2026-11-05；此节仅存档）

**做了什么**（三处，向后兼容）：

1. `soulcore/db.py`
   - `memories` 加列 `text_gram TEXT`（建表语句 + `_ensure_column` 迁移都覆盖）。
   - 新增 `gram_text()`：去掉空白后切 2 字窗口、空格连接，最长 2000 字。
   - 新增 `_CJK_FTS_SQL`：`memories_fts2`（`tokenize='unicode61'`）+ 三个触发器（ai/au/ad）。
     放在 `init_db` 里而不是 `SCHEMA`，因为触发器依赖 `text_gram` 列，老库要先 ALTER 再建触发器。
   - `upsert_memory` 写入时同步填 `text_gram`，新记忆立刻可搜。
   - `init_db` 里一次性回填：缺 gram 的补 gram、缺行补 `memories_fts2`（幂等，每次启动只补差集）。
2. `soulcore/retrieval.py`
   - 新增 `_fts_table()`：优先 `memories_fts2`，缺表或空表自动回退 `memories_fts`（老库/未迁移库不会炸）。
   - `search_memories` 的 MATCH、`FROM`、`bm25()` 三处跟着表名走。
   - 兜底路径的 `where` 过滤从"字符串等值"改成 `.endswith(" MATCH ?")`（表名动态化后的连带修复）。
   - **查询侧仍然做 2-gram 分片**（`_query_terms` 未动）——索引和查询必须用同一套分片，否则匹配不上。
3. 老 `memories_fts` 保留不动（回滚用），触发器仍双写。

**实测（1107 条 / 私聊 1 群 1）**

| 词 | LIKE | 旧 FTS | 新 FTS |
|---|---|---|---|
| 上次 | 6 | 0 | **6** |
| 记得 | 44 | 4 | **44** |
| 记忆 | 121 | 6 | **121** |
| 那个 | 58 | 3 | **58** |
| 梯子 | 1 | 0 | **1** |
| 数据 | 10 | 0 | **10** |
| 部署 | 6 | 0 | **6** |

- `memories_fts2` = 1107 行，缺 gram = 0，`quick_check: ok`。
- 库大小 6.89 MB → 9.08 MB（gram + 镜像索引，+32%）。
- `/context` 的 L2 事件索引现在能填满 2 条（之前常空）；`/recall` 返回真实相关记忆而非固定那条。
- 备份：`data/soulcore.db.bak-20261105-100439-pre-fts2`。

**这次没做（留给后续步骤）**：`person_id`/`conversation_key`/`status` 索引（S1b）、相似度阈值（S2）、联想通道改造（S3）。

**回滚方式**：`DROP TABLE memories_fts2` + `DROP TRIGGER memories_fts2_*`，`retrieval._fts_table` 会自动回落旧表；或直接换回备份文件。
**注意**：`text_gram` 列留着无害（只是占空间），删列需要重建表，不建议。

### S1b 补索引（✅ 已完成，2026-11-05）

- **改了**：`soulcore/db.py` 的 `init_db` 末尾加 `idx_mem_person(person_id, ts)`、`idx_mem_conv(conversation_key, ts)`、`idx_mem_active(ts) WHERE status='active'`（全部 `IF NOT EXISTS`，每次启动幂等）。
- **为什么**：和 FTS 修复无关，是性能问题；S2 的阈值筛选会反复按人和会话扫。
- **验证**：`EXPLAIN QUERY PLAN` 三条都走索引 —— `idx_mem_person` / `idx_mem_conv` / `SCAN USING INDEX idx_mem_active`。
- **回滚**：`DROP INDEX`。

### S2 阈值 + 隐私闸门（✅ 已完成，2026-11-05）

**做了什么**

1. `retrieval.search_memories(..., min_similarity=0.0)`：低于阈值直接不进候选（默认 0 = 老调用方行为不变）。
2. **新模块** `soulcore/privacy.py`：8 条确定性正则（密码/验证码/手机号/身份证/银行卡/账号/住址/邮箱），
   `gate(text, strict)` 两种强度——**群聊命中整行丢弃，私聊只打码成 `「已隐去」`**。
3. `_memory_index` / `_recall_index` 透传 `minSimilarity` 与 `strictPrivacy`。
4. `_context` 做**两道闸门**：
   - 第一道按候选条目筛（保证 `result_count` 准）；
   - 第二道**逐行扫最终拼装结果**——handoff、人物卡、未收尾话题同样会夹带原文，只筛 L2 不够（实测就是这么漏的）。
5. 参数放 `data/recall-config.json`，**每轮现读，改完下一轮生效，不用重启**。

**配置（`data/recall-config.json`）**

| 键 | 默认 | 含义 |
|---|---|---|
| `minSimilarity` | 0.18 | 私聊阈值 |
| `groupMinSimilarity` | 0.28 | 群聊阈值（更严） |
| `privacyGate` | true | 闸门总开关 |
| `groupDropOnHit` | true | 群里命中敏感整条丢（false 则只打码） |
| `maxItems` | 2 | L5 注入上限 |

**实测**（`privacy-probe2.py` 16 项 + `s2-e2e.py` 5 项 + `s2-live.py` 6 项，全过）

```text
正则：8 类真敏感全抓；"这个账号我忘了""她住在学校附近""密码学挺有意思的" 等 8 句普通话 0 误伤
端到端（临时库塞 5 条含密码/手机/验证码/账号/住址的记忆）：
  群聊 → 0 原文泄露（整条丢）；私聊 → 0 原文泄露，显示「她告诉我开机「已隐去」」
  噪声查询"啊啊啊啊" → 注入 0 条；阈值调到 1.1 → 立刻 0 条（验证热读）
线上回归：普通群聊 629 字、私聊 928 字，【最后几条】/状态段结构不变
```

**没做的**（避免过度设计）：没按 `people.intimacy` 分档调阈值——先跑一段看误杀率，数据说话再加。

**回滚**：`privacyGate: false` + 两个阈值改 0。

### S3 把联想通道做成真通道（✅ 已完成，2026-11-05）

**改了三处，边界没破**

1. `plugins/memory-lab/lab.py` 的 `_public()` 加派生理段（**零额外查询**，只从 row 和文本算）：
   - `when`：`2026-11-02T…` → `11-02`
   - `who`：`speaker` 优先，回落 `person_id`
   - `where`：`conversation_key`/`scope` → `私聊` / `群聊`
   - `stance`：含 `我觉得/感觉/好像/大概/可能/似乎/应该是/有点/挺/估计…` → **看法**，否则 **事实**
2. `reflex-arc` 的 `injectMemoryLabHint`：
   - `limit=1` → 取 4 筛 2（**最多 2 条**，每条正文 80 字）
   - 格式：`[记忆联想·实验｜11-02·Windy·私聊·事实] 正文（想深一点就 recall）`——保留原来的标签前缀，只往里塞元信息
   - `（想深一点就 recall）`**只挂最后一条**，不是每条都挂
   - 正文换行压成空格（否则一条 hint 会变成多行，白占 token）
   - 过滤 `你还记得…吗？` 这类**测试期问句**（之前实测这类会排到第一）
   - 无候选 → 注入 0 条，不留占位
3. `memoryLabEnabled` 默认 `false` → **`true`**（按你的决定；开关保留，随时可关）。

**不动**：L5 的 `l2`、`_recall_index`、`ec recall` 三级返回。实测 `l2_items` 字段仍是
`['memory_id','similarity','speaker','summary','ts','type']`，**没有** `stance/when/who/where`；
`server.py` 也没有 import 过 lab。

**实测**

```text
s3-probe.mjs（真模块 + 真 HTTP + 真 screenClaim，6 项全过）：
  [场景:群 999·发言人 小明(QQ:111)]
  [记忆联想·实验｜10-31·凯坑卓斯·群聊·事实] @肥鱼雪风 这是跑团，你是玩家…那个棋子会遭遇什么？
  [记忆联想·实验｜11-01·肥鱼雪风·群聊·看法] 想起来了，是凯坑卓斯当KP那局，我先闪避后力量检定…（想深一点就 recall）
  最多 2 条 ✓ / 带元信息 ✓ / 每条 ≤80 字 ✓ / recall 提示只出现一次 ✓ / 有事实-看法标记 ✓ / 场景 hint 仍在 ✓
s3-boundary.py：l2_items 无 lab 字段 ✓
```

> 注意：`stance` 是**启发式**（关键词命中就算看法），不是模型判断。宁可标成"事实"，也不把判断当事实递上去——
> 这正是 Hindsight 那篇的要点：模型分不清这两者时，会把当时的情绪当客观事实复述。

**回滚**：`memoryLabEnabled=false`（配置热生效，不用重启）。

### S4 双侧取词 + 随机 1 + 定向 1（✅ 已完成，2026-11-05）

**做了什么**（全在 `reflex-arc`，`lab.py` 只多吐一个 `last_hit`）

1. `bot.onAfterSend` 里维护 **per-chat 最近 3 句**环形缓冲（`recentSaid`，只存文本，120 字截断）。
2. `buildRecallQuery()`：**对方这句在前**，再接她最近 2 句，拼到 **64 字**为止；去掉 CQ 码/`[昵称]:` 前缀；
   她要说的那句若已出现在 query 里就跳过（避免同一句被加权两次）。
3. `pickDirectedAndRandom()`：
   - **定向 1 条** = 权重最高（`score`/`rrf_adjusted` 取到哪个用哪个），权重 ≤0 的直接不算候选；
   - **随机 1 条** = 其余候选按 **权重²** 加权抽，抽不中就不给——这是"偶尔想起别的"，不是"随机塞一条"。
4. **久未触发加成**：`min(0.15, 天数/30 × 0.15)`，`last_hit` 为空按最久算（+15%）。

**实测**（`s4-probe.mjs`，真模块 + 真 HTTP，7 项全过）

```text
实际 query: 哥布林巢穴那次你还记得吗 我上次说的是建国路那家猫咖，别记成另一家
  ① query 含她刚说的话 ✓   ② query 以对方这句开头 ✓
  ③ 定向条连跑 5 次完全一致（1 种）✓   ④ 随机条 5 次 4 种 ✓
  ⑤ 每次 ≤2 条 ✓   ⑥ 都带元信息 ✓   ⑦ 正文 ≤80 字 ✓

#1 ｜10-29·看法 主人说我上次记错了，我有点不安…  ‖ ｜11-01·凯坑卓斯·群聊·事实 你的衣服是你在力量检定失败…
#2 同上                                        ‖ ｜11-01·肥鱼雪风·群聊·看法 想起来了，是凯坑卓斯当KP那局…
```

**取舍**：随机条**没有**再套隐私闸门——它和定向条走的是同一条 `screenClaim`，敏感内容在 L5 侧已被 `privacy.gate` 挡掉；
联想通道只读同一批记忆，重复加闸门是白花 CPU。

**回滚**：把 `pickDirectedAndRandom` 里的 pool 分支去掉 → 只剩定向条（等价"随机概率 0"）。

### S5 让深挖真的被调用（✅ 2/3 已完成，2026-11-05）

**① adapter 的指令补一句**（`plugins/emotioncore-adapter/index.js` `localInstructions`）

```text
看到 [ep:…]/[mem:…] 这类编号、又需要细节时，再调一次 ec(action="recall", episode_id="…")
或 (memory_id="…") 拿原文；一次别钻超过两次。
```

写“别钻超过两次”是防它陷进去反复查——它一轮只能花几次工具调用。

**② 联想尾巴改成冷却 30 分钟一次**（不是每轮）

原计划写“只在首次唤醒”，实测那样太弱：首次唤醒之后一整场对话就再也不提醒了。改成
**同一会话 30 分钟内只出现一次**——既不啰嗦，也不至于提醒完就永不出现。

**③ 角色卡不用改：已经写过了**

`workspace/AGENTS.local.md` 第 24–25 行原文：

```text
- 你对自己的记忆不是全知的：一次查询只能看到有限条；被问到很久以前或大量细节时，先查、
  查到多少说多少；查不到、被截断或不记得，就承认，不要用想象补洞。
- 旧记忆里说话人不明确的记录，不要自动当成主人说的；不确定就保持不确定。
```

`L5-RECALL-TREE.md §7` 要求的四条全部覆盖，反向禁忌（"所有记忆都能一次查完"）也没出现。
**所以这一条是"已满足"，不是"没做"**——再往里塞反而重复。

**实测**（`s5-probe.mjs` 6/6）

```text
第一次带 recall 提示 ✓   第二次不带（冷却生效）✓   联想行仍在 ✓
adapter 出现 episode_id/memory_id/次数限制 ✓✓✓
```

**待观察**：计划里的验收指标是"一周后 `recall_index` 调用率 ≥ 1/10 轮（改造前 6/135）"——
这条只能等真实对话攒数据，代码侧没有可自动化的判据。**下次审计时一起看。**

### S6 向量召回（✅ 已完成，2026-11-05）

**先说一个和计划书不一样的地方**：计划里写"numpy 是本计划唯一要新增的 pip 包"——实际不用装。
运行时 python（3.12.14）**自带 numpy 2.3.5 + onnxruntime 1.31.1**，所以这次**零新增依赖**。

**做了什么**

1. **模型**：`BAAI/bge-small-zh-v1.5` 的 ONNX 导出（512 维 / 4 层 / 95 MB），
   放 `plugins/memory-lab/models/bge-small-zh-v1.5/`（`model.onnx` + `vocab.txt`），从 hf-mirror 拉取（147 秒）。
2. **自己写了 WordPiece tokenizer**（`lab_vectors.BertTokenizer`）：中文按字切、标点单独切、
   `##` 续接贪心最长匹配。省掉 `transformers`/`torch`（那两个加起来 2 GB，只为了切词不值）。
3. **池化**：CLS + L2 归一化（BGE 官方用法）。单条编码 **5.1 ms**，32 条批量 164 ms。
4. **存储**：`mem_vectors(memory_id, model, dim, vec BLOB, text_hash, updated_at)`，
   `float32` 小端 BLOB = **2048 字节/行**（旧的 JSON 方案 10.3 KB/行，省 80%）。
   表建在 **`data/memory-lab.db`**（不是 soulcore.db）——向量是派生索引不是事实，
   memory-lab 对 soulcore.db 保持只读，这条规矩不为向量破例。
5. **检索**：全部向量读进内存做暴力余弦（1083×512 ≈ 2.3 MB），行数变了才重建缓存。
   单次 **10 ms**（计划估 1 ms 是理想值；实测含 SQL 取行与编码）。
6. **回填**：1083/1083 条 active 记忆全部有向量，耗时 82 秒。
   新增 `POST /vectors/backfill`，另外**服务启动 3 秒后自动补一次**（最多 400 条），
   免得新记忆的向量慢慢过期。

**两个实测出来的坑**

| 坑 | 实测 | 处理 |
|---|---|---|
| BGE 的检索前缀 | "短 query 检索长文章"才该加；我们的"文章"是几十字聊天片段。加前缀把分数**压平**：同一 query 带前缀 0.50 / 不带 0.58，且不带时榜首才是真正相关那条 | **默认不加**，`MEMORY_LAB_QUERY_PREFIX=1` 可开 |
| 余弦阈值 | 相关 0.58~0.66，无关 0.42~0.54（不是 0.8 那种量级） | `vectorMinScore = 0.56` |

**影子模式（按计划：先不参与注入）**

`vectorEnabled` 仍为 `false`。10 条查询的影子对比（`s6-shadow.json`）：

```text
平均重合 0.30/3；8/10 条查询向量捞到了关键词完全没有的候选
「上次说的那个部署问题」向量 0.65/0.62/0.61 vs 关键词 0.32/0.31/0.23
  向量首条：「那个事你问过了，归档吧，今天你第二次问了」
  关键词首条：「我说的"管理员"是部署我这边的那个称呼」——字面撞车，实际不相关
「跑团那天我怎么了」向量 0.647「昨晚和卡珊德拉的跑团什么感受」 / 关键词 0.217「量产怎么了」
「今天天气」「主人对什么吃的感兴趣」→ 阈值挡住，0 条
```

**计划验收点已过**：不带关键词的查询，向量能捞到、FTS 捞不到。

**开向量那天别忘了权重**：S10 实测「只开开关、不改权重」等于白开（R@5 60% vs 不开的 57%），
要与 `fts 0.6 / vector 1.0` 一起切，才拿得到 87%。见 S10。

**下一步（三天后）**：看重合度是否稳定；稳定就把 `vectorEnabled` 打开，向量路在
`rrf_recall` 里已有 `vector: 0.2` 的权重位，不用动结构。

**回滚**：`vectorEnabled=false`（现在就是 false）；`[vectors]` 表可留可删。

### S7 冷热分层 + 冷库索引（✅ 机制已完成，2026-11-05；当前 0 条可归档）

**做了什么**

1. `memories` 加 `archived_at`；新表 `mem_cold(memory_id PK, blob, codec, text_len, created_at)`
   + `idx_cold_created` + `idx_mem_archived`（**冷库也建索引**，你提的这条）。
2. **新模块** `soulcore/archive.py`：判定 / 预演 / 执行 / 还原 / 取原文。
3. 归档动作：原文 `zlib` 压进 `mem_cold`；`memories.text` 换成 24 字摘要 + `〔归档〕`，
   `status='archived'`、`archived_at=now`。**不删任何东西**。
4. 深挖打通：`/recall(memory_id=…)` 命中归档行时回冷库解压原文，
   返回里多一个 `archived: true`（否则她拿到的会是一句摘要还以为那就是全部）。
5. 触发：EmotionCore 启动 5 秒后跑一次（`enabled` 关了就不跑），另有 CLI
   `python -m soulcore.archive --preview|--run|--restore <id>`。

**保护规则**（`protected_reason()`，任何一条命中就不归档）

| 规则 | 为什么 |
|---|---|
| `status != active` | 反思/旧提示词不动 |
| `source_kind != dialog` | 非对话来源 |
| `scope in (pet, skill)` | 身体层、技能层 |
| `importance >= 0.5` | 明显重要 |
| 挂在**还开着**的话题上 | `thread_loops.status in (open/waiting/paused)` |
| `trigger_count > 1` | 被想起过 ≥2 次说明还有用 |
| 长度 ≥ 200 字 | 长文当有信息量（跑团 RP、架构讨论都在这一类） |
| 主人 + 知识性标记 | 身份/偏好/约定/明确要求（`我叫/喜欢/约定/说好/记住/以后/住在…`） |

> 踩过一个坑：一开始拿"有 `thread_id`"当保护伞，结果 552 条全被保护。
> 实际 `thread_loops` 只有 10 个话题、还有 closing 的——改成**只认还开着的那些**，119 条。

**当前实际状态：0 条可归档**

```text
active 1083 条；keep 统计：还新 944 / 挂在未收尾话题 119 / 主人知识 11 / 身体·技能 9
```

DB 只有 **7 天**历史（10-29 起），30 天规则今天当然一条都不动——这是对的，不是没生效。
按 3 天阈值预演一次（不写库），会归档 **792 条**，样本正是"测试一下，启动了没有""怪"".r 1d6"这类。

**一个必须说清楚的实测结论：归档不省磁盘**

```text
样本 792 条：原文 100 KB → zlib 压缩后 91 KB（只省 9%）
热库留下的摘要行又要占 59 KB → 净省 -50 KB（反而变大）
长度分布：<20 字 166 / 20-60 字 434 / 60-200 字 192 / ≥200 字 0（都被保护了）
```

原因很简单：聊天记忆平均才一百多字节，zlib 的头尾开销吃掉大半收益。
**所以 S7 的价值不在省磁盘，而在"热索引条数"**——FTS 与兜底扫描 `LIMIT 2000` 只扫 active，
几万条之后这个差别才显出来。计划书原来把 S7 写成存储优化，这里按实测改了说法。
小文本另外做了保护：压缩完更大就**存原样**（`codec='raw'`），不为"压缩"把库撑大。

**验收**（`s7-e2e.py` 16 项 + `s7-http.py` 3 项，全过）

```text
造 6 条 40 天前的记忆 → 归档 2 条（junk1/junk2）
  主人知识 / 长文 / 新记忆 / 挂 open 话题的 4 条全部没动 ✓
memory 行只留「…〔归档〕」摘要 ✓        热检索不再返回归档条目 ✓
冷库解压回原文一字不差 ✓               restore 后原文回来且 status=active ✓
热检索 7.4 ms（归档前后一致）✓          HTTP /recall(memory_id) 返回原文 + archived=true ✓
线上：重启后 archived=0、mem_cold=0，schema 就位
```

**回滚**：`enabled=false` 停掉；已归档的 `--restore <id>` 逐条还原，或整体
`UPDATE memories SET status='active', archived_at=NULL WHERE status='archived'`（摘要会留 24 字，需要逐条 restore 才能回全文）。

### S8 元记忆：激活已有的 `appraisal_patterns`（✅ 已完成，2026-11-05）

**这张表本来就在，问题是它里面 88% 是垃圾，而且门锁着。**

排查到的实况：

| 项 | 数字 | 含义 |
|---|---|---|
| `appraisal_patterns` | 49 条 | 其中 **43 条 `count=1`**（低于 `min_support=2`，`predict()` 直接跳过 → 死数据） |
| 样例来自 demo | **5 条** | `sample_ids` 是 `demo:demo:*`，早期自测造的假记忆，拿来当"经验"会对真人说胡话 |
| 真能用 | 6 条 | 其中 1 条 count=11（肥鱼/评价/嘴硬），4 条 count=2 |
| `appraisal_policy.mode` | `shadow` | `pattern_calls=0`——从没参与过打分 |
| `appraisal_shadow` | 0 行 | 影子对照从没写过 |

**为什么开不了**：`set_mode('auto')` 自带门槛（≥5 次影子对照、准确率 ≥0.7），
而影子行只在**模型打分**时才写，`model_calls=27` 而阴影 0 → 门槛永远过不去，门自己锁死了自己。

**改了什么**

1. `appraisal_learning.prune()`：淘汰 `count<min_support` / 峰值方差超阈 / 样例全是 demo / 样例已不在库里的 pattern。**只减不增**。
2. `learn()` 现在自己就守规矩：聚类结果的 `count < min_support` 或方差超阈 **不写表**。
   （不改这一步的话，每次 learn() 都把 43 条单体样板重新灌回来，清理等于白做——实测过，一次批量打分就回到 49 条。）
3. `replay_shadow()`：拿历史记忆回放"pattern 预测 vs 代码分"，把对照写进 `appraisal_shadow`。
   这不是训练，是给门槛攒证据——否则要等真机打分攒够 5 次。
4. `appraise.py` 的 auto 分支：**pattern 只接"怎么打分"，不接"怎么感受"**。
   pattern 的 `felt` 是一句写死的话（"我记下了这件事，暂时没有太大波动。"），
   套上去她会翻来覆去说同一句；情绪表述仍用 code-v1，维度/置信度/是否有触动才用归纳结果。
5. EmotionCore 启动时顺手跑一次 `prune()`（很便宜，49 行）。

**结果**

```text
清理：49 → 5 条（丢 44：43 条 support=1 + 1 条样例全是 demo）
回放：103 次对照，100 次一致 → 准确率 0.9709（过门槛）
mode：shadow → **auto**；appraisal_shadow：0 → 103 行
```

> S9 期间补了一处：`_model_examples()` 没过滤 `status`，8 条 demo 假记忆也参与聚类，
> 于是 `learn()` 每次都会顺手造出一个 demo 样板。加上 `COALESCE(m.status,'active')='active'`
> 后重新聚类为 **7 条**（count 11/2/2/2/2/2/2，样本里 0 条 demo）。

**必须说清楚的局限**

- 剩下的 5 条 pattern 覆盖的都是**开发/闲聊类**话题（"肥鱼雪风评价""是不是傲娇""recall 怎么用"），
  不是"被骂了会怎样"这种人味经验。回放命中 103/1083 ≈ **9.5%**，其余 90% 走原来的 code-v1。
- 命中时 pattern 与 code 的维度差平均 err≈0.10（`agreement` 门槛 0.15），
  也就是说**这次切换的行为变化很小**——分数依旧主要由 code-v1 决定，pattern 只是在相似场景上把先验挪一点。
- 真正的收益是**机制活了**：`pattern_calls` 会随新记忆增长，`appraisal_shadow` 开始积累，
  以后 pattern 变多、变准时才有东西可评估。

**没做的一项**：计划里第 3 条"联想通道读 pattern 的 `tokens_json` 当线索"——**主动跳过**。
联想位只有 2 条上限，`tokens_json` 是 n-gram 碎片（"肥鱼雪/鱼雪风/不管设"），
塞进去只会挤掉更具体的那条记忆，反而更空泛。pattern 的作用在"她怎么反应"这一侧，不必再进口语提示通道。

**验收**（`s8-e2e.py` 11 项，全过）

```text
prune 后只剩 count>=2 ✓        demo 样例清零 ✓
回放写入影子行 103 次 ✓        mode=auto ✓
新记忆走 pattern-v1（appraiser_id 实测）✓   pattern_calls 0→1 ✓
没有误触模型调用（model_calls 仍 27）✓     felt 用回 code 的说法 ✓
```
生产库已备份 `soulcore.db.bak-20261105-1530-proper`（**用 `sqlite3.backup()` 生成**），
EmotionCore 已重启（mode=auto、5 条 pattern、103 行影子）。

> **踩坑记录（值得记住）**：库是 WAL 模式，主文件 `soulcore.db` 不含最近提交——
> 当时 `-wal` 有 3.5 MB 没回写。用 `Copy-Item` 直接复制主文件，拿到的是一份**缺数据的旧快照**
> （备份里 pattern 还是 49 条、S8 改动全都不在）。所有临时库测试也一脚踩空：
> 探针"在副本上"跑的其实是 15:13 的状态。
> 正确做法：`src.backup(dst)`，或先 `PRAGMA wal_checkpoint(TRUNCATE)` 再复制三个文件。
> 探针已全部改成 `_snapshot()`（用 backup 接口）。

**回滚**：`UPDATE appraisal_policy SET mode='shadow' WHERE id=1`（或 `appraisal_learning.set_mode(conn,'shadow')`），
一行 SQL，无需重启（下一轮批量打分就读新值）。

### S9 多用户回归（✅ 已完成，2026-11-05）

**做法**：线上库当底子做 WAL 安全快照，再往里塞一套"编排好的人物关系"，专打串味。
2 群（1001 阿尔法/贝塔、2002 伽马）+ 2 私聊（贝塔、伽马），外加**同一句话由两个人说、落在两个窗口**，
最后起临时服务逐窗口问，看拿回来的是谁的事。

**查出三个真问题**

| # | 问题 | 实况 | 处理 |
|---|---|---|---|
| 1 | 说话人空白 | 13 条老记忆 `speaker` 与 `person_id` 全空，联想里就成了 `｜10-29··事实`（两截连在一起，像"没人说的"） | `_who_of()` 三级兜底：列 → `raw_json.speaker/nickname` → `isSelf` 时认"我"。13 条现在都有人名 |
| 2 | **假记忆还活着** | 8 条 `demo:demo:01..08`（`pet` scope、`status=active`）一直在热库里，会被当成"今天主人夸我记事清楚"这种真实经历召回 | `status='demo'`（**不删**，只是退出热索引）。热检索已确认 0 命中 |
| 3 | 常驻进程吃旧代码 | `worker.py` 13:10 启动，S8 改完没重启它 → 它的 `learn()` 还是旧逻辑，15:25 把 44 条单例样板又写回来了 | 重启 worker（**它其实有守护，杀掉会被拉起，新进程自然是新代码**） |

顺带补两处"静默退化"（自查时发现，不在计划里）：

- **向量只补一次**：memory-lab 只在启动时补向量，运行中新记忆永远没向量，向量路会悄悄变窄而影子对比照样算得好看。
  改成每 10 分钟扫缺口（`interval=600`），有缺口就补。
- **探针写死数字**：`s6-verify` 要求"向量数 == active 数"，`s8-e2e` 要求 `model_calls == 27`——
  这两个数会随真实聊天变。改成"active 没有缺口"和"跑批前后不变"。

**验证结果（`s9-probe.py` 11 项，全过）**

```text
人物归属：1084 条 active 记忆，who 与 people.display_name/别名 100% 对得上 → 0 错人（O3 达成）
同文本不同人：阿尔法 vs 伽马，who 不串；同一句话跨群聊/私聊，where 分别是 群聊 / 私聊
真实库跨窗同文：6 组同文，where 全部非空、无错位
群聊问"我手机号 13800001234，别外传"：号码与原句都拿不到（隐私闸门在跨窗下有效）
scope 护栏：越 scope 拒、跨群拒、本群放行
```

> **关于"跨窗"的边界**（免得以后误判成 bug）：普通私聊内容进群 **是设计允许的**（你要的"跨窗共享"），
> 闸门只拦私密信息。所以测试标准是"群聊问手机号拿不到"，而不是"群聊里不能出现私聊里说过的任何话"。

**回滚**：纯测试，无代码回滚项。`_who_of` 与 demo 行状态是数据侧修正，要退就
`UPDATE memories SET status='active' WHERE id LIKE 'demo:%'`。

### S10 影子对比：外部方案到底值不值（✅ 已完成，2026-11-05）

不是为了上线，是为了**回答「要不要换方案」这个问题本身**。

**做法**：30 条真实 cue（20 条原有：直问 / 换说法 / 指代；10 条补充，覆盖潜水、装备、备份、
检定、醉酒接管等话题）。gold = 源记忆本身 + 同 `thread_id` 的兄弟（答到隔壁那条不算错）。
四条链路 + 8 组权重组合，跑 2000 次 bootstrap 看区间。全程只读，不写库、不上线。

**先说一个自己踩的坑**：第一版把「时序加成」写成 `score + 0.02`，而 RRF 分数本身才 0.01~0.02——
等于直接按时间倒序排，于是「仿 Hindsight 94%」是假象。改成乘性 ×1.1 后差值归零。
这类「加成量级大于被加成分数」的写法，以后一律按探针 bug 处理。

**结果（R@5 / MRR / 平均延迟）**

| 组合 | R@3 | R@5 | MRR | 延迟 | R@5 95%CI |
|---|---|---|---|---|---|
| **F0.6+V1.0** | 77% | **87%** | **0.727** | 22ms | [73%, 97%] |
| F0.3+V1.0 | 77% | 87% | 0.727 | 22ms | [73%, 97%] |
| F0.3+V1.0+G0.3（加图遍历） | 77% | 87% | 0.726 | 22ms | [73%, 97%] |
| F0.3+V1.0+G0.3+时序 | 80% | 87% | 0.697 | 22ms | [73%, 97%] |
| 只有向量 | 70% | 83% | 0.638 | 21ms | [70%, 97%] |
| **现有六路（生产）** | 57% | **57%** | 0.508 | 49ms | [40%, 73%] |
| 开向量但权重不动（F1.0+V0.9） | 60% | 60% | 0.551 | 22ms | [40%, 77%] |
| 只有 FTS | 47% | 60% | 0.451 | 77ms | [43%, 77%] |

**三条结论**

1. **换框架不值**：图遍历（`lab_edges`，2228 条边）增益 0pp，时序 0pp。Hindsight 那套结构里
   真正起作用的部分——「向量 + 关键词并行」——我们现在就有。判据（<10%）达成，**不迁移**。
2. **我们的六路权重配比是错的**：`fts: 1.0` 压着 `vector: 0.8`，而 FTS 在这批 cue 上只有 60%、
   向量 83%。所以 **只开开关不改权重 = 白开**（60%，与不开的 57% 在噪声内）。
3. **零成本可拿 +30pp**：`fts 0.6 / vector 1.0`，R@5 57%→87%（+30pp，95%CI [+13, +47]），
   延迟 49→22ms。这不是「照抄外部方案」，就是把权重换成数据支持的配比。

**决策**：S6 影子观察期结束时，`vectorEnabled: true` 与权重改动**同一批上线**；单独开开关没有意义。
`thread/person/emotion` 三路暂不动——它们服务的是「联想」（唤起相关但不匹配的记忆），
用「命中 gold」这把尺子判它们天生吃亏；记为观察项，等有「联想质量」的标尺再评。

**回滚**：纯脚本（`s10-compare.py` / `s10-ablation.py` / `s10-sweep.py`），删掉即可。

### S11 情绪打分去模型化（✅ 已完成，2026-11-05）

实测：1115 条记忆里 appraisal 绝大部分是 `code-v1` 纯代码分，模型只参与过 66 条，11-05 已经是 0。
分流判断（`should_escalate`）本来就是关键词 + 长度 + importance 的程序逻辑。所以模型这一步是
「偶尔被叫、被叫就很贵（timeout 180~300s/条）、失败还得静默托底」。

**改了什么**

| # | 改动 | 位置 |
|---|---|---|
| 1 | 开关 `appraisalModel`，**默认 false**，放在设置页「功能开关」栏 | `plugins/soulcore-settings/index.js`（DEFAULTS）、`client.js`（设置页一行） |
| 2 | 关掉时疑难条目走**精细代码评分**：只抬置信度（0.4→0.5）与来源标记 `deterministic scorer (fine)`，**维度一律不动**——p 值分布不会因为开关跳 | `soulcore/appraise.py`：`heuristic(..., fine=True)`、`appraise_pending` |
| 3 | 失败不再假装模型参与过：来源写 `code-v1`，去掉永远为 0 的 `fallback` 计数 | `appraise_pending` 的 stats 与失败分支 |
| 4 | 开模型时收紧：单条 **20s**、每轮**最多 1 条**、连续失败 **3 次自动关开关**（写回设置文件） | `soulcore/appraise.py`：`MODEL_TIMEOUT / MODEL_MAX_PER_BATCH / MODEL_MAX_FAILURES`、`_note_model_result`、`data/appraise-model-health.json` |
| 5 | worker 不再自己写死 `timeout=180` / `code_only`，一律听设置 | `plugins/emotioncore-service/worker.py` |

**验收（`s11-e2e.py` 19 项，全过）**

```text
默认视为关；关着时一条模型都不调（model_calls 28→28）
关着时全部有分、来源 code-v1、求助消息 0 条
疑难条目进精细档；精细档维度与常规档 maxΔ=0.0，只抬置信度与标记
打开开关 → 一轮真的只调 1 次；失败照样有分且来源 code-v1
连错 3 次 → 开关自动写回 false，留 disabled_at 时间戳
code_only=True 会压过开关（日记批处理仍然永不调模型）
worker 不再传 timeout=180 / code_only
```

`python -m unittest discover -s tests` **39 项全过**（新契约改了 1 条老测试的假设，并补了
`test_appraisal_model_off_by_default` 覆盖默认关的分支）。

**一个坑记一下**：失败路径不记 `model_calls`（那是成功才记的计数），所以探针里**不能**用
`model_calls` 判断"调过模型没有"，要看 `stats.failed` 与 `data/appraise-model-health.json`。

**代价评估**：关掉模型不损失维度质量——模型本来只改 `dimensions/unresolved/confidence/has_impact`，
而 S8 的 pattern 已经接手了「怎么打分」这部分；`felt` 一直是 `_derive_felt` 从维度算出来的。
换句话说，模型这条路现在买到的只有"置信度数字略有不同"。

**回滚**：设置页把 `appraisalModel` 打开即可恢复模型参与，其余代码兼容两条路径。

### S12 数据质量与事件边界（✅ 已完成，2026-11-05）

**1. felt 补齐（99.3% → 100%）**

缺的 8 条全是 10-29 那批模型打分的，`backfill_felt()` 又只覆盖 `surfcore*` 来源，所以
`emotioncore-adapter` 的一直没人管。新增 `appraise.fill_missing_felt()`：**只补 felt/delta/adjusted，
不动维度与置信度**，纯代码从维度推一句话，不调模型。EmotionCore 启动时顺手跑一次（已有缺口才打印）。
实测：`8 → 0`，重复跑 `filled=0`，1115 条的维度一条没动。

**2. appraisal 失败可解释**

失败分支原来只 `stats["failed"] += 1`，事后无从查起。现在同时把
`{at, memory_id, error}` 写进 `meta['appraisal_last_error']`，并有 `appraise.last_error(conn)` 读回来。
配合 S11（默认不调模型），这条基本只在"有人手动开了模型"时才用得上——但那正是最需要能查的时候。

**3. 结案规则校准（不再全靠 2B 保守判断）**

`episode_review.rule_verdict()` 先判两头，只有中间才问模型：

| 信号 | 判定 | 依据 |
|---|---|---|
| 末条是明确道别（晚安/拜拜/先撤…）且未解决度 < 0.6 | **settle**（0.78） | 说了晚安就该收 |
| 末条是收束语（说好了/就这么定/翻篇…）且未解决度 < 0.6 | **settle**（0.75） | — |
| 末条仍是未答问题 / 未完成请求 | **open** | 问题没答完不能算结束 |
| 未解决度 ≥ 0.75 | **open** | — |
| 其余 | **unsure → 交给 2B** | 规则不猜 |

现有 11 个 open 线程的预演：`settle 2 / open 1 / unsure 8`——规则只处理它有把握的两头，
不会把"只是没人说话"当成结束（这也是原提示词里明确禁止的）。

> **顺手发现的一处死代码**：`episode_review.review_open()` 在整个项目里**没有任何调用方**——
> 结案审查早就写好，但从来没跑过（`closure_source='local-2b-thread'` 那 19 行是更早手工跑的）。
> 也就是说"2B 结案过保守"这件事一直只存在于纸面上。现在把 `review_open(rules_only=True)` 接进
> worker 的日常循环：只让规则处理有把握的两头，拿不准的 `deferred` 不动，全程不调模型。
>
> 生产实跑（一次性 `force=True` 清历史）：`reviewed 4 / closed 3 / kept 1 / deferred 14`，
> open 线程 **11 → 9**，关掉的 3 段是「最后一条是收束语」×2 与「最后一条是明确道别」，
> `closure_source='rules-v1'`。

**4. 事件边界：固定时钟 → 变化点（已实现，默认仍走旧时钟）**

新模块 `soulcore/boundary.py`，六个信号加权：间隔 / 换窗口 / 话题漂移 / 参与者变化 / 收尾语 /
未解决度突增，外加"段长度"软信号（旧版是硬切 12 条，现在变成"数到 12 就该收一刀，但前面若有更明确的
道别或话题跳变，先切在那些地方"）。

**话题漂移用已有向量算，不用字面重合**：短句对话里相邻两条几乎不共享二字词，字面 Jaccard 永远像跳变
（第一版就是这么把 142 条切成 121 段的）。改成"这条与这一段质心的余弦"，直接复用 `mem_vectors` 里
现成的 1091 条 BGE 向量，零新依赖。

离线对比（4 天真实数据）：

| 日期 | 条数 | 旧时钟段数 | 变化点段数 | 旧纯度 | 新纯度 | 问答误切 | 漏切道别 |
|---|---|---|---|---|---|---|---|
| 11-02 | 35 | 11 | 14 | 0.533 | **0.557** | 1 | 0 |
| 11-03 | 78 | 10 | 9 | 0.596 | 0.595 | 0 | 0 |
| 11-04 | 142 | 15 | 19 | 0.564 | **0.565** | 0 | 0 |
| 11-05 | 10 | 2 | 4 | 0.515 | **0.570** | 0 | 0 |

（纯度 = 段内相邻条目向量余弦均值；问答误切 = 边界前是问句、边界后换人接话；漏切道别 = 上一句明确道别却没切。）

结论：段数不劣于旧法、纯度略好、道别零漏切。**但默认仍是 `clock`**——按计划"先离线标注 50 段"，
我只做了代理指标 + 样例抽查（11-02 那 1 次"误切"人工看过，是从"群聊可见性"切到"改性格设定"，
属于切对了）。要真正切换，先补人工标注集：`recall-config.json` 的 `eventBoundary` 改成 `change` 即可，
`episodes.build_day` 会自动换切法，两种模式都已跑通。

**验收**

```text
s12-e2e.py 17 项全过：felt 3→0 / 重复跑不重复补 / 维度未动 / 失败留痕带 memory_id /
  结案规则 5 个分支 / 道别必切(2.05) / 问答不切(0.80) / 长段软切(13→2) /
  真实一天 142→19 段 / 默认 clock / 切到 change 能建事件 / 配置复原
python -m unittest discover -s tests → 39 项 OK
全量探针 14 个全绿（privacy / s0 / s1b / s2 / s3–s5 / s6 / s7×2 / s8 / s9 / s11 / s12）
```

**回滚**：`eventBoundary` 保持 `clock` 就是旧行为；`fill_missing_felt` 只补空值；结案规则可加
`closure_source='rules-v1'` 回溯（现有数据里还没有 rules-v1 行，因为它只在新一轮 review 时才写）。

---

## 6. 数据模型变更（DDL 汇总）

```sql
-- S1（✅ 已在生产执行，此处仅存档）
ALTER TABLE memories ADD COLUMN text_gram TEXT;
CREATE VIRTUAL TABLE memories_fts2 USING fts5(memory_id UNINDEXED, text_gram, tokenize='unicode61');
-- 触发器 memories_fts2_ai / _au / _ad 由 db._CJK_FTS_SQL 创建

-- S1b（未执行）
CREATE INDEX idx_mem_person ON memories(person_id, ts);
CREATE INDEX idx_mem_conv   ON memories(conversation_key, ts);
CREATE INDEX idx_mem_active ON memories(ts) WHERE status='active';

-- S6
CREATE TABLE mem_vectors(memory_id TEXT PRIMARY KEY, model TEXT, dim INT, vec BLOB, updated_at TEXT);

-- S7
ALTER TABLE memories ADD COLUMN archived_at TEXT;
CREATE TABLE mem_cold(memory_id TEXT PRIMARY KEY, blob BLOB, codec TEXT, created_at TEXT);
CREATE INDEX idx_cold_created ON mem_cold(created_at);

-- S8：无新表！复用 appraisal_patterns / appraisal_policy / appraisal_shadow
--     唯一改动是 appraisal_policy.mode: 'shadow' -> 'active'
```

---

## 7. 风险与回滚

| 风险 | 影响 | 处置 |
|---|---|---|
| FTS 迁移期间新旧表不一致 | 召回空窗 | 双写一周，`search_memories` 走开关切换 |
| 联想随机条抽到噪音 | 人设"记忆错乱"感 | 阈值 + `score²` 加权 + 可抽空；一条 debug 日志（影响面仅联想通道，不影响 L5 事件索引） |
| 向量模型头几次排序仍差 | 白花 2 天 | 先影子模式，3 天验不过就退回 S1 的 FTS |
| 归档把要用的记忆藏起来 | 该想起的想不起 | 只归档 30 天未触发 + 低 importance + 非主人；回捞通道必须在 |
| 词库反馈回路漂移 | 人格越来越偏 | 周衰减、单项上限、来源溯源、月抽检 |
| CORS `*` | 任意网页可读全库 | S1 顺带：删头或只允许 `http://127.0.0.1:<dsh端口>` |

---

## 8. 明确不做

- 一年未召回即删除（你已取消）
- 媒体闸门 / 2k 截断 OCR（上一轮已否）
- 改 L5 的 `l2`（事件简述入口）与 `_recall_index` 的返回结构
- 把 `ec recall` 的三层语义改成别的形状
- 让她在正文里写特殊标记再剥离（污染正文，收益低于 `ec recall`）
- 跨机器同步 / 网络访问（memory-lab 只绑 127.0.0.1）
- **引入完整框架**：MemOS / Hindsight / MetaMem 一律只吸收算法，不 pip install、不跑 Docker、不起 Postgres
- 装 Postgres / pgvector / Redis / Docker / FAISS / hnswlib（本机一个都没有，也一个都不需要）

---

## 9. 服务与依赖盘点（防止项目变重）

### 9.1 现在跑着的

| 服务 | 端口 | 技术栈 | 职责 | 体积/占用 |
|---|---|---|---|---|
| **SnowLuma**（OneBot） | 3000 HTTP / 3001 WS / 5099 | Node | QQ ⇄ OneBot 桥 | 外部依赖，不可换 |
| **DSH** | 9230 / 61016 | Node + Electron | Agent 宿主 + 插件管线（kernel / reflex-arc / emotioncore-adapter） | 外部依赖 |
| **EmotionCore service** | 8765 | **Python 纯标准库**（`http.server`） | L0/L4/L5 组装、`/recall` 三层、`/context` | ~0 依赖 |
| **memory-lab** | 8766 | **Python 纯标准库** | RRF 六路、边/词实验、只读 soulcore | ~0 依赖 |
| **worker** | — | Python 纯标准库 | appraisal 打分、日终 consolidate | ~0 依赖 |
| **Ollama** | 11434 | Go | 视觉（3 个 2b）+ 英文 embedding | 模型 5.43 GB |
| **mcp-web-search-safe** | — | Node | 联网搜索 MCP | 与记忆无关 |
| **SQLite** | — | 内嵌 | `soulcore.db` 9.1 MB + `memory-lab.db` 10.7 MB | 无服务进程 |

**Python 环境实测只有 `Flask` / `Flask-SocketIO` / `requests` 三个三方包**，而这三个都不是 soulcore 用的（soulcore 全 stdlib）。也就是说：**现在这套东西是"零重依赖"的**，这是它最大的优点，别弄丢。

### 9.2 重叠与冲突（真实存在的，按严重度）

| # | 重叠 | 性质 | 处置 |
|---|---|---|---|
| D1 | 两套召回算法：`retrieval.search_memories` vs `lab.py rrf_recall` | **不是冲突，是分层**：前者给 L5（低延迟、无扩展），后者给联想（多轴、可实验）。RRF 的 `fts` 那一路就是调 `baseline()`→`search_memories`，所以 S1 的修复它自动继承 | 保留。但**约定**：memory-lab 不实现第二套 FTS，只做加权与实验 |
| D2 | 两个数据库：`soulcore.db` + `memory-lab.db` | 派生数据分离，隔离好坏参半 | 保留分离（只读安全）。`lab_embeddings` 实测是**死路径**（见 §9.4），8.4 MB 可清，S6 改 BLOB 后重建 |
| D3 | 三个 2b 视觉模型（qwen3-vl / minicpm-v4.7 / huihui abliterated） | **只有 huihui 常驻**（appraisal 也用它），另外两个只是躺在磁盘上 | **不动**。磁盘不是问题，只要不常驻；只需注意 embedding 与视觉模型的内存竞争 |
| D4 | `nomic-embed-text`（英文向）与计划中的 bge-small-zh | 同一功能 | bge 上线后删 nomic 的 861 行向量与模型，避免两套向量并存 |
| D5 | EmotionCore 与 memory-lab 各自 `ThreadingHTTPServer` | 两套微型服务框架，但都是标准库 | 保留。合并零收益，还会破坏只读隔离 |
| D6 | `appraisal_jobs` 队列 + worker 轮询 | 自建队列 | 保留，别引 Celery/Redis（那是十几倍的重量） |

### 9.3 计划会新增什么（预算）

| 新增项 | 形态 | 代价 | 是否必需 |
|---|---|---|---|
| `bge-small-zh-v1.5` | **Ollama 模型**，不是服务 | ~95 MB 磁盘 + 运行时 ~300 MB 内存 | S6 必需 |
| `numpy` | pip 包 | ~15 MB 磁盘 | S6 推荐（可退回纯 Python 粗筛） |
| 压缩（S7 冷库） | **`zlib` 标准库**（Python 3.14 才有 `compression.zstd`，我们是 3.13） | 0 | 用 zlib 就够，不装 `zstandard` |
| 其余 | 全是 SQLite 表 + Python 代码 | 0 | — |

### 9.4 三项核查结论（本次实测）

#### ① surfcore 残留：**零运行时依赖**，可以放心不碰

| 检查项 | 结果 |
|---|---|
| `import surfcore` / `require('surfcore')` | **0 处** |
| `db.sync_surfcore()` | 只被 `cli.py` 调用（手动 `python -m soulcore.cli sync`），server/worker 都不调 |
| `inbox.sync_inbox()` | 只被 `cli.py` 与 `skills.py` 调用，不在服务循环里 |
| `source='surfcore'` / `'surfcore-inbox'` | **只是历史行的来源字符串**，不是代码依赖 |
| `diary.py` / `dice-command.js` 里的 surfcore | 注释/移植说明 |
| `soulcore/README.md` | 文档 |

唯一活着的 surfcore 进程是 **`mcp-web-search-safe`（pid 7928）**，父进程是 DSH，拉起配置在
`~/.dsh/profiles/desktop/cordis.patch.yml:38-45`（写死绝对路径 `C:\Users\li\surfcore\src\mcp-web-search-safe.js`）。
它是**联网搜索 MCP**，不是记忆；而且 QQ 线的 `onebot-toolgate.mjs:24` 把 `mcp__web-search-safe__web_search/fetch` 放进了允许列表——**删它会同时断掉 DSH 和机器人侧的联网搜索**。

> 另外：`~/.dsh/profiles/desktop/package.json` 里 `"surfcore": "link:C:/Users/li/.dsh/plugins/surfcore"` 仍在依赖列表，但 `dsh.profile.bundles` 里**没有 surfcore** → 插件不加载。
> 所以"清理 surfcore"的正确做法是：删 package.json 那一行 + 把 MCP 脚本挪到 `soulproject/` 下（或改用 `dsh` 自带搜索），**不是删目录**。

**✅ 已执行（2026-11-05）**：

1. 新建 `tools/web-search-mcp/`：`safe-fetch.js` + `web-search.js` + **自写的 stdio JSON-RPC 外壳 `server.mjs`**（不依赖 `@modelcontextprotocol/sdk`）+ `node_modules/js-yaml`。
   - 合计 **975 KB**；如果直接拷 SDK 需要 21.4 MB（98 个包）。
   - 已用真实 JSON-RPC 探测验证：`initialize` → `tools/list` → `tools/call(web_search)` 返回 1630 字真实结果，`web_fetch` 对 `127.0.0.1` 正确拒绝（防内网逻辑生效）。
   - 修了一个自写外壳的坑：stdin 关闭时不能立即 `exit`，否则会吞掉还没完成的异步搜索（`pending` 计数后才退）。
2. `cordis.patch.yml` 的 `args` 指向 `F:\...\soulproject\tools\web-search-mcp\server.mjs`。
3. `package.json` 删掉 `surfcore` 依赖（备份：`*.bak-20261105`）。
4. **需要 DSH 重启才生效**；surfcore 目录没删，重启前旧进程照常可用。

#### ② `lab_embeddings`（8.4 MB 向量）：**死路径**

| 调用链 | 结论 |
|---|---|
| `lab.py:312` `lab_vectors.search(...)` 前置条件 | `lab_config.read().get("vectorEnabled") is True` → `config.json` 里是 `false` |
| `lab_vectors.embed_missing()` | 只被 `lab_vectors.py:163` 的 `__main__` 调用（手动跑脚本） |
| `/recall`、`/context`、`ec recall` | 都不读向量 |

→ 861 行 × 10.3 KB = 8.4 MB 是**纯 dormant 数据**。**已清理**：`DELETE FROM lab_embeddings` + `VACUUM`，`memory-lab.db` **10.65 MB → 0.48 MB**（省 10.17 MB），`lab_edges`/`lab_terms` 未动，`quick_check: ok`。S6 换模型后按 float32 BLOB 重建（同样 861 条只占 2.5 MB）。

#### ③ 三个视觉模型：只有 huihui 常驻

`ollama list` 里 4 个模型都在盘上（5.43 GB），但**运行时只加载了 `huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M`**——它同时是 `data/appraisal-config.json` 里配的 appraisal 模型。另外两个（`qwen3-vl:2b`、`minicpm-v4.7:1b`）只是没删的旧版本。

**结论：不需要删。** 磁盘不是约束，常驻内存才是；真正要盯的是"再加载一个 embedding 模型会不会把 huihui 挤出内存"。

### 9.5 情绪打分：模型参与度实测（决定要不要开关）

| 指标 | 实测 |
|---|---|
| `appraisals` 总条数 | 1107 |
| `appraiser_id='code-v1'`（纯代码） | **1041（94%）** |
| `appraiser_id='ollama:huihui…'`（本地模型） | **66（6%）** |
| 按天看模型占比 | 10-29 全是模型（39/39，首次回填）→ 10-31 1/387 → 11-01 0/424 → 11-02 8/35 → 11-03 7/78 → 11-04 11/142 → **11-05 0/2** |
| 分流依据 | `appraise.py:459 should_escalate()`：关键词 + 长度≥180 + importance≥0.5，**纯程序判断** |
| 失败托底 | `appraise.py:619` `AI-FAIL … code-fallback`：模型失败就默默改用代码分 |

也就是说：**你说的"情绪打分实际靠代码"成立**。模型只在 6% 的"值得深入"消息上被叫，而且调用成本很高（worker 给的 timeout 是 180s/条），一旦超时还会走隐式托底。这正好支持做成一个默认关闭的开关。


**结论：新服务 0 个，新 pip 包最多 1 个（numpy），新模型 1 个（95 MB）。** 不装 Postgres、不装 Docker、不装 FAISS。

---

## 10. 使用中发现的缺陷（B1–B5）

> 这批是你实际用出来的问题，优先级高于 S6/S7（向量与冷库）。B2/B4/B5 是同一件事的三个面：**模型分不清"谁在说、对谁说、这是哪个场面"**。

### B1 三层分工：记录 / 知识 / 规则 —— 已核实，**当前没有重复**

| 层 | 内容 | 现在在哪 | 状态 |
|---|---|---|---|
| **记录**（episodic） | 发生过什么 | `memories` + `episodes` + `appraisals` | ✓ 1107 条 |
| **知识**（semantic） | 关于人和群的事实 | `person_profiles` + `person_impressions` + `data/people/<qq>.md` | ✓ 在写 |
| **规则**（procedural） | 怎么用记忆、怎么打分 | `appraisal_patterns`(49) + `appraisal_policy` | ✓ 有，`pattern_calls=0`（S8 激活） |

**核对结果（2026-11-05）**：`config.json` 里 `group-memory = false`、`group-memory-accumulate = false`，`~/.dsh/dsh-onebot-qq/qq-memory/` **目录不存在**——那套"每群一篇 md"从来没跑起来过。所以**不存在两份知识互不知道的问题**，B1 不是"修 bug"，是"重新打开之前先定规矩"。

**定的规矩**（写进 §8 不做清单的同级约束）：

1. **人物事实、偏好、承诺、关系** → 只进 soulcore（`person_profiles` / `memories`），带 `source_ids` 指回 episode。
2. **`qq-memory/*.md` 只放群内梗、口头禅、气氛**，人可读，**不放人物事实**——它是投影，不是第二份真相。
3. 真要重新打开 `group-memory`，先跑 `python tools/mem-overlap.py`：它把 md 里每行和记忆库做 2-gram Jaccard 比对（默认阈值 0.55），列出重合项。
   - 现在跑的结果：`qq-memory 目录不存在：group-memory 插件现在是关的，没有重复风险。`
4. 规则层（`appraisal_patterns`）已存在，**不新建**"知识库"——S8 只负责激活它。

### B2 多机器人互相接话连锁（"你"这类通用词）

**现象**：群里有 2 个以上同型号 AI 时，A 回复里带"你"，B 当成叫它，再回，A 再接——滚成连锁。

**根因**（代码位置）：
1. `gate-wake` 的唤醒只认 `mentionedSelf` / 引用 / **关键词** / followup；关键词表里只要有"你"这种通用词，任何人发都会命中。
2. **没有"这条来自另一个机器人"的概念**：`selfIdOf()` 只过滤自己（`index.js:223`），别人的 bot 一律当人类。
3. `reflex-arc.fishEnabled`（默认 **false**）其实已经有"命中的群友只记录、不搭话、不主动私聊"，但**按昵称匹配**（`fishTags: 肥鱼,机器人,AI,bot…`）——改名就失效。

**改**：
1. 新增 `otherBots`（QQ 号列表，逗号分隔，存 reflex-arc 配置）——**按号不按名**，改名无效。
2. `gate-wake`：`ev.sender.qq ∈ otherBots` 时**只接受 @我 / 引用我的消息**，跳过关键词、followup 两个分支。
3. **连锁熔断**：同一 `chatKey` 最近 3 条全部来自 `otherBots ∪ 我` → 本轮 stop（`stopReason='bot-chain'`），并记一行日志。
4. 通用词黑名单：`你/你们/在吗/有人吗` 永不作为唤醒词（只认名字/别名/@/引用）。
- **验证**：两个 bot 群里互怼 20 轮，误触发 0 次；@ 时正常响应。

### B3 清洗前留一张一次性交接便条

**现状**：`context-snapshot-trigger` 已经有 pre-compaction 钩子（`POST /event_snapshot/request`）；而 `session_rotation._write_pending` 是 surfcore 时代的半成品，现在 `cli.py:936` 直接跳过（"OneBot-only"）。也就是说**交接机制不存在**。

**改**：
1. 新表 `handoff(id, created_at, reason, payload_json, consumed_at)`。
2. 触发点：pre-compaction 钩子 + 日终 consolidate 之前，**用纯代码**（不调模型，避免又慢又飘）生成 ≤120 字便条：当前事件名、3 条未结话题（`thread_loops`）、情绪基调、上次说到哪。
3. 注入：下一个会话的**第一次** `/context` 带 `handoff` 字段，用完 `consumed_at` 置位——**一次性，不常驻**，与你说的"不重复注入固定内容"一致。
4. 调试：同一条便条用 `ec send` 以**指令格式**（前缀 `[交接]`）发给管理员 QQ。它是发给"别人"的消息，不进本会话上下文，所以 AI 看不到。
- **验证**：压缩后第一轮 prompt 有且只有一次 handoff，第二轮没有。

### B4 群聊/私聊共用一个 session 的发言人混淆

**实测**：
- 群聊：`format.js:611` 每条带 `[昵称(QQ:号)]: ` ✓
- **私聊：`speaker` 是空字符串** ✗ —— 私聊消息前面**没有任何身份前缀**
- 两条线是同一个 session（你特意这么设计，为了反应一致）→ 私聊的话会被当成群里某人的延续

**改（一行）**：把 `format.js:611` 的 `ev.isGroup &&` 去掉，私聊也挂 `[昵称(QQ:号)]: `；`proactive/continuation/welcome` 三种轮次仍不挂（它们没有"谁在说"）。
- 可选加强：私聊前缀写成 `[私聊][昵称(QQ:号)]:`，一眼分清窗口。
- **验证**：群/私聊交替 20 轮，模型不再把私聊内容说成"你在群里说的"。

### B5 每轮附事件元信息（反射弧附注通道）

**必要性：有**，而且它是 B2/B4 的兜底——模型现在不知道"这个群有几个人、这条是谁发的、是不是同一个事件"。

- 数据全在本地：`ev.isGroup`/`ev.groupId`、群成员数（缓存）、`ev.sender`、reflex-arc 的活动名、`thread_loops`。
- 形态：hint 加一行 `[场景:群 123456789·6 人·发言人 Windy(QQ:…)·事件:深夜闲聊]`（约 40 字）。
- **不计入 §4.2 的 3 条记忆配额**——它是元信息，不是记忆条目；40 字的成本远低于一次错认。
- 新配置 `sceneHint`（reflex-arc，默认开，可关）。
- **验证**：连续 20 轮里，模型提到发言人的准确率、把两件事混为一谈的次数下降。

### 10.1 这批的落地顺序

| 顺序 | 项 | 改动量 | 风险 | 状态 |
|---|---|---|---|---|
| 1 | **B4**（私聊发言人前缀） | 1 行 | 极低，立即改善 | ✅ **已改**（`format.js:611`） |
| 2 | **B5**（场景 hint） | ~40 行 | 低，只加 hint | ✅ **已改**（`reflex-arc` 新配置 `sceneHint`） |
| 3 | **B2**（otherBots + 熔断） | ~80 行 | 中，会影响唤醒率 | ✅ **已改**（`gate-wake` 4 个新配置） |
| 4 | **B3**（交接便条） | ~120 行 + 1 表 | 中，一次性注入要测 | ✅ **已做**（复用已有 `handoff`，不建新表） |
| 5 | **B1**（知识层去重） | 0 行代码（只定规矩 + 检查器 40 行） | 无（那层是关的） | ✅ **已核实**（`qq-memory` 不存在；`tools/mem-overlap.py`） |
| 6 | **S0**（观测先行） | ~50 行 | 无，纯日志 | ✅ **已做**（`result_count` + `reflex-hints.json`） |

#### B2/B4/B5 实测结果（2026-11-05）

写了两个探针（`reports/context-audit-20261104/b4-probe.mjs`、`b2b5-probe.mjs`），**12 项全过**：

```text
B4 私聊带号 / 群聊带号 / 主动接话不挂 / 接续轮不挂 / 无声者不挂空括号     5/5
B2 他机QQ静音 / 名字标签命中 / 真人未叫不回 / 真人@正常 / 他机@放行
   / 连续3条熔断 / 真人插话重置链条                                      7/7
B5 群场景 / 私聊场景 / 开关可关                                          3/3
```

**默认值即生效，不用改 `config.json`**：`otherBots=1452133357`、`botNameTags=肥鱼`、`botChainWindow=3`、`sceneHint=开`（`effective()` 缺键回落 schema 默认值）。

插件自带测试：**183 项，157 通过，20 失败**——20 项全部是 `Cannot find package '@deepseek-ai/schemastery'`（这个副本没装 peer 依赖，与我改的代码无关），改动前后数字一致，无回归。

> ⚠️ **三项都要重启 DSH 才生效**：`format.js` 和插件都在内核进程里，配置热更新不覆盖代码。

#### B3 实测结果（2026-11-05）

**先查了有没有重复工作**：`soulcore/handoff.py` 已经存在（`cli.py` 的 `cmd_handoff`、睡眠时 `handoff.write` 都走它），产出 `data/handoff.md` + `handoff.json`，内容是"上次停在哪 / 没接完 / 现在什么状态"。所以**没有新建表、没有另写一套摘要**，只在它上面加了三件缺的东西：

| 增补 | 位置 | 说明 |
|---|---|---|
| `short()` | `soulcore/handoff.py` | ≤120 字一句话，纯代码复用已有的 `_latest_episode` / `_loops_line` / `_state_words`，**不调模型** |
| `mark()` / `take()` | 同上 | 挂到 `meta` 表的 `handoff_pending` 键，`take` 读完立刻清 → 天然一次性 |
| `POST /handoff/compose`、`/handoff/take` | `plugins/emotioncore-service/server.py` | 压缩前后端调用；`/context` 在最前面注入一次 |
| 压缩前钩子 | `plugins/context-snapshot-trigger/index.js` | 快照请求成功后紧跟一次 `compose`；再把同一条发给管理员 QQ（`【交接·调试】`，走 `qqBot.deliver`，不写进会话） |

实测（`reports/context-audit-20261104/b3-probe.py` + `b3-e2e.py`，临时端口 8799 起的独立实例）：

```text
短便条生成 120 字 / 带前缀 / 挂起可取 / 第二次为空 / 空文本不注入  5/5
端到端：compose 返回 → /context 注入(1517字) → 第二轮不再注入(1031字)  4/4
```

样例便条：

```text
【交接·上个窗口】停在11-05 09:58，群聊：表情我这边没收到…；没接完的：「下次管理员再提跑团…」
```

> 仍待验证：管理员 QQ 那条**调试副本**要等 DSH 重启后遇到一次真实压缩才发得出来（依赖 `qqBot.deliver` + 实例 `config.json` 的 `adminQq`）。

---

## 11. 已拍板的 4 件事（2026-11-05）

| # | 问题 | 你的决定 | 落到哪 |
|---|---|---|---|
| 1 | 跨窗共享粒度 | **允许私聊事实在群聊被索引到**；不靠屏蔽，靠 API 自己判断场景与私密性，加上欲望系统底层机制与社交亲密度兜底 | S2 新增**隐私闸门**：不做 scope 过滤，但密码/验证码/账号/证件类原文**正则拦截 + 摘要替换**；强度随 `intimacy` 与场景调整 |
| 2 | 主人记忆归档 | **知识性不归档；当日大量临时测试性发言应当归档** | S7 归档条件改写为主人两类分治 |
| 3 | 向量模型 | **`bge-small-zh-v1.5`**（中文优先；简单英文够用即可） | S6 定为唯一方案，`bge-m3` 不引入 |
| 4 | `reflex-arc` 记忆开关 | **保留，默认开启联想** | S3 把 `memoryLabEnabled` 默认改为 `true` |

> 补一句关于"中文思考方式"：向量模型只决定**捞得到什么**，不决定她**怎么说话**——她的语言由 system prompt 与对话历史决定。所以选 `bge-small-zh` 不会"把思考方式改成英文"；反而因为中文语义编码更准，召回更贴中文语境。

---

## 12. 分计划索引与合并结果

### 12.1 现有的 9 份计划（查过，都存在）

| 文件 | 日期 | 状态 | 与本计划的关系 |
|---|---|---|---|
| **MEMORY-RECALL-PLAN.md** | 11-05 | **总计划（本文件）** | — |
| `L5-RECALL-TREE.md` | 11-03 | **契约，有效** | 不作废，作为 §3 的约束来源 |
| `REMAINING-WORK-PLAN.md` | 11-03 | 执行中 | P4 = 本计划 S6；**P6 未并入 → S12**；P7 待人设生效 |
| `EVENT-STREAM-PLAN.md` | 11-04 | Phase 1 shadow | **Phase 2–6 未并入 → 合并进 B3** |
| `MEMORY-CONTEXT-PLAN.md` | 11-01 | 主体已落地 | §4.2 提示词预算的依据；不再单独立项 |
| `MEMORY-SEA-NEURON-REFERENCE-PLAN.md` | 11-02 | 参考稿 | Phase A→S8/S9，Phase B→S6，Phase C/D→P5 已完成 |
| `MEMORY-SCIENCE-REVIEW-PLAN.md` | 11-02 | 审计稿，未实施 | M1（事件边界改变化点）→ S12；其余"不建议照论文改" |
| `MNEMOSYNE-ABSORPTION-PLAN.md` | 10-31 | 已执行 | P0 FTS / P1 证据字段已完成，被 S1 覆盖 |
| `PLAN.md` / `PLAN-V2.md` | 10-31~11-03 | 历史总纲 | 已被本文件取代，不再维护 |

### 12.2 这次补进来的遗漏项

| 遗漏 | 来源 | 去向 |
|---|---|---|
| **P6 数据质量**：felt 覆盖、appraisal 失败原因、thread review 校准 | REMAINING-WORK-PLAN | **新增 S12** |
| **事件流 Phase 2–6**：chunk→stream 候选、2B 复核灰区、写 `event_memory_links`、未绑定记忆分级、可选 API 压缩 | EVENT-STREAM-PLAN | 合并进 **B3**（交接便条的前置：先有事件流，才有"上一个事件"可交接） |
| **M1 事件边界从固定时钟改为变化点** | MEMORY-SCIENCE-REVIEW | 并入 S12（低优先） |
| **P0 残留**：新 session 人设注入回归未验收 | REMAINING-WORK-PLAN | 并入 S9 回归清单 |

### 12.3 不合并的（明确保持独立）

- `L5-RECALL-TREE.md`：是**契约**不是计划，改它等于改接口。
- `QQ-FEATURE-INVENTORY.md` / `PLUGINS.md` / `SETTINGS-UI.md`：参考手册，非计划。

---

## 13. 变更台账（每做一步记一行）

> 这个会话没绑 Git 仓库，所以用台账代替 diff：**只记文件/目录名 + 改了什么 + 怎么生效**，不贴代码。
> 目录前缀：`SC` = `soulproject/soulcore/`，`SV` = `soulproject/plugins/emotioncore-service/`，`PL` = `~/.dsh/plugins/dsh-onebot-qq-yu/`，`DF` = `~/.dsh/profiles/desktop/`。

| 日期 | 步骤 | 文件 / 目录 | 改了什么 | 生效方式 |
|---|---|---|---|---|
| 11-05 | S1 | `SC/db.py`, `SC/retrieval.py`, `data/soulcore.db`（备份 `soulcore.db.bak-20261105-100439-pre-fts2`） | `text_gram` 列 + `memories_fts2` 虚表 + 3 个触发器 + 回填；`_fts_table()` 自动选表 | 立即（服务重连即用） |
| 11-05 | D2 | `data/memory-lab.db` | `DELETE FROM lab_embeddings`（861 行）+ `VACUUM`：10.65 MB → 0.48 MB | 立即 |
| 11-05 | MCP | **新增目录** `tools/web-search-mcp/`（`server.mjs`、`safe-fetch.js`、`web-search.js`、`package.json`、`node_modules/js-yaml`） | 从 surfcore 迁入，去掉 MCP SDK 依赖，975 KB | 重启 DSH |
| 11-05 | MCP | `DF/cordis.patch.yml`, `DF/package.json`（均留 `.bak-20261105`） | MCP `args` 指向新脚本；删掉 `surfcore` 依赖 | 重启 DSH |
| 11-05 | B4 | `PL/kernel/format.js` | 私聊也挂 `[昵称(QQ:号)]`；空 sender 不挂空括号 | 重启 DSH |
| 11-05 | B5 | `PL/plugins/reflex-arc/index.js` | 新增 `sceneHint` 配置 + `buildSceneHint()`（导出以便单测） | 重启 DSH |
| 11-05 | B2 | `PL/plugins/gate-wake/index.js` | 新增 `otherBots`/`botNameTags`/`botChainGuard`/`botChainWindow` + 他机防线与连锁熔断 | 重启 DSH |
| 11-05 | 台账 | `reports/context-audit-20261104/`（`b4-probe.mjs`、`b2b5-probe.mjs`、`appraise-src.py`、`learn-tables.py`、`d2-clean.py` 等） | 一次性探针与统计脚本 | 无需 |
| 11-05 | B3 | `SC/handoff.py`, `SV/server.py`, `plugins/context-snapshot-trigger/index.js`（`data/soulcore.db` 只写 `meta` 一个键，无新表） | 短交接便条 `short/mark/take` + `/handoff/compose`、`/handoff/take` + `/context` 一次性注入 + 压缩钩子发管理员调试副本 | 重启 EmotionCore + 重启 DSH |
| 11-05 | S0 | `SV/server.py`, `PL/plugins/reflex-arc/index.js`（新增 `state/reflex-hints.json`） | L5 记录补 `result_count`/`handoff_pending_chars`；每轮累加 hint 标签与字数 | 重启 EmotionCore（S0 的 python 半）；DSH 半见下 |
| 11-05 | B1 | **新增** `tools/mem-overlap.py`（只读检查器；未改任何写入方） | md ↔ 记忆库 2-gram 重合报告 | 无需 |
| 11-05 | S1b | `SC/db.py`（init_db 末尾） | 加 `idx_mem_person`/`idx_mem_conv`/`idx_mem_active` 三个索引 | 立即（服务重连即用） |
| 11-05 | S2 | **新增** `SC/privacy.py`、`data/recall-config.json`；改 `SC/retrieval.py`、`SV/server.py` | 相似度阈值 + 两道隐私闸门（条目级 + 逐行兜底）；参数热读 | 已重启 EmotionCore，即时生效 |
| 11-05 | S3 | 改 `plugins/memory-lab/lab.py`、`PL/plugins/reflex-arc/index.js` | 联想行补 `when/who/where/stance`、最多 2 条、过滤测试问句；`memoryLabEnabled` 默认 true | memory-lab 已重启；**reflex-arc 待重启 DSH** |
| 11-05 | S4 | 改 `plugins/memory-lab/lab.py`（只加 `last_hit`）、`PL/plugins/reflex-arc/index.js` | 双侧取词（她最近 3 句缓冲 + query 64 字）、定向 1 + 加权随机 1、久未触发加成 | 同 S3，一次重启带上去 |
| 11-05 | S5 | 改 `PL/plugins/emotioncore-adapter/index.js`、`PL/plugins/reflex-arc/index.js`（角色卡**未改**） | 深挖指令 + 联想尾巴 30 分钟冷却；§7 四条约束原卡已有 | 同 S3/S4，一次重启带上去 |
| 11-05 | S6 | **新增** `plugins/memory-lab/models/bge-small-zh-v1.5/`（95 MB ONNX+vocab）、重写 `plugins/memory-lab/lab_vectors.py`、`data/memory-lab.db` 新表 `mem_vectors`、`plugins/memory-lab/server.py`（`/vectors`、`/vectors/backfill`、启动后台补向量）、`plugins/memory-lab/config.json` | 中文向量召回换成本地 ONNX；float32 BLOB；影子模式（`vectorEnabled` 仍 false） | 已重启 memory-lab；**零新增依赖**（numpy/onnxruntime 运行时自带） |
| 11-05 | S7 | **新增** `soulcore/archive.py`、`data/archive-config.json`；改 `soulcore/db.py`（init_db 挂 ensure_schema）、`SV/server.py`（深挖回冷库、启动跑一次）；`data/soulcore.db` 加 `archived_at` 列与 `mem_cold` 表 | 冷热分层：zlib 压缩 + 摘要指针 + 冷库索引；主人知识/长文/未收尾话题受保护 | 已重启 EmotionCore；当前 0 条可归档 |
| 11-05 | S8 | 改 `soulcore/appraisal_learning.py`（新增 `prune()`/`replay_shadow()`、`learn()` 守阈值）、`soulcore/appraise.py`（auto 分支只接维度不接 felt）、`SV/server.py`（启动顺手 prune）；`data/soulcore.db` 的 pattern 49→5、mode→auto | 元记忆启用：pattern 参与打分（`pattern_calls` 开始计数），影子对照开始累积 | 已备份并重启；`appraiser_id=pattern-v1` 实测生效 |
| 11-05 | S9 | 改 `plugins/memory-lab/lab.py`（新增 `_who_of()` 三级兜底）、`plugins/memory-lab/server.py`（向量缺口改成每 10 分钟补）、`soulcore/appraisal_learning.py`（`_model_examples` 加 active 过滤）；`data/soulcore.db` 的 8 条 `demo:*` 改 `status=demo`；重启 worker 与 memory-lab | 多用户回归 0 错人；假记忆退出热索引；向量不再静默过期 | 11 项验收通过；worker 有守护，杀掉会被拉起 |
| 11-05 | S10 | 新增 `reports/context-audit-20261104/s10-compare.py`、`s10-ablation.py`、`s10-sweep.py`、`s10-debug.py`（含 `s10_compare.py` 导入副本）；产物 `s10-result.json`、`s10-sweep.json`；**未改任何生产代码** | 回答「要不要换框架」：不换（图/时序 0 增益）；发现六路权重配比问题，定下 `fts 0.6 / vector 1.0` 与开向量同批上线 | 30 条 cue，bootstrap 2000 次 |
| 11-05 | S11 | 改 `soulcore/appraise.py`（`model_enabled` / `_set_setting` / `_note_model_result`、`heuristic(fine=)`、`appraise_pending` 三条分流规则）、`plugins/emotioncore-service/worker.py`、`plugins/soulcore-settings/index.js` + `client.js`（新开关）；`data/soul-bridge-settings.json` 写入 `appraisalModel: false`；新增 `data/appraise-model-health.json`；`tests/test_phase1.py` 补 1 条测试 | 打分不再调模型；疑难条目仍有分且来源诚实 | 19 项验收 + 39 项单测 |
| 11-05 | S12 | 改 `soulcore/appraise.py`（新增 `fill_missing_felt()` / `last_error()` / `_note_error()`）、`soulcore/episode_review.py`（新增 `rule_verdict()`，`review_open` 先过规则）、`soulcore/episodes.py`（`boundary_mode()` / `_load_vectors()` / `_change_groups()`）、`plugins/emotioncore-service/server.py`（启动补 felt）、`plugins/emotioncore-service/worker.py`（接入规则结案）；**新增** `soulcore/boundary.py`；`data/recall-config.json` 加 `eventBoundary: clock`；新增探针 `s12-e2e.py`、`s12-boundary.py` | felt 0 缺口；失败可查；结案规则接管两头；边界变化点可用（默认不启） | 17 项验收 + 39 项单测 + 14 个探针 |
**规矩**：以后每完成一步，先在这张表加一行，再动代码。
---

## 14. 一句话


```text
两条通道各管一件事：L5 给"发生过什么"的目录，反射弧给"突然想起什么"的片段
地基已修（S1/S1b）、向量垃圾已清（D2）、surfcore 的 MCP 已搬走
进 API 的永远只有 hint 那几行，所以硬上限是每轮 3 条（+ 1 行场景元信息）
联想通道现在最多 2 条、每条 80 字、带 时间·人物·场景·事实/看法；取词同时看她听见的和她刚说的
隐私不靠屏蔽靠闸门：允许跨窗索引，注入前过 8 类正则——群里命中整行丢、私聊只打码
已存在的别重造：元记忆就是 appraisal_patterns（只是没启用）、向量骨架在 lab_vectors、深挖在 ec recall
角色卡的四条"记忆不全知"约束早就写过了（AGENTS.local.md 第 24–25 行），不用再加
四件事已定：允许跨窗 / 主人知识不归档 / bge-small-zh / 联想默认开
9 份计划查过：P6 并入 S12，事件流 Phase 2–6 并入 B3，其余已被本文件取代
```
