# 从 Mnemosyne 吸收什么：SoulCore 低上下文改造计划

## 执行状态（2026-10-31）

- P0 FTS5：已完成，426 条已建立索引；中文查询与 LIKE fallback 验证。
- P1 证据字段：完成 `source_kind`、`episodes.raw_ids` 保留、correction 版本链。
- P2 status/version：完成 `status/version/valid_from/valid_to/last_confirmed_at` 字段；旧记录默认 active。
- P3 L2 查询相关性：已实现 episode-index + 桥接按当前消息选卡；bootstrap 无消息时回退静态卡。
- P4 幂等：复用现有 `UNIQUE(source, source_record_id)`；未新增队列。
- 全程未新增常驻 prompt、未新增 AI 调用。

## 结论

Mnemosyne 值得借的是：

1. **FTS5 全文检索 + 中文降级**；
2. **证据链/来源标识**；
3. **版本与状态语义**；
4. **幂等写入**。

不值得直接搬的是：

- 独立 FastAPI/Python 子进程；
- 每条消息自动写 working memory；
- 它很薄的 consolidation/promotion；
- Graphiti/向量库；
- 它的情绪/时间 README 愿景（代码没落地）。

原则：

```text
不替换 SoulCore
不新增常驻 prompt
不增加每轮模型调用
不复制 AGPL 代码
只加本地表/索引/查询，复用现有 memories/appraisals/episodes
```

---

## 一、现状对照

| 能力 | SoulCore 现状 | Mnemosyne | 是否吸收 |
|---|---|---|---|
| 原始记忆 | `memories` 426 条 | `observations` + `memories` | 不复制，`memories` 就是 observation |
| 事件索引 | `episodes` 68 个，`raw_ids_json` | `episodic` 候选 | 已有，保留 |
| 评价 | `appraisals` 426 条 | 无同等情绪评价 | 我们更强，保留 |
| 证据链 | `episodes.raw_ids_json` + `correction_id` | `memory_evidence` | 轻量补强 |
| 版本 | correction 侧车 `superseded_by` | `memory_versions` | 轻量补强 |
| 状态 | `affect_weight` / `consolidation_state` | `candidate/active/superseded/invalidated` | 复用现有字段，不新建大表 |
| 全文检索 | SQL/LIKE 为主 | FTS5 + LIKE + 中文 2-gram | **优先吸收** |
| 异步任务 | daily/sleep 批处理 | outbox/tasks | 暂不吸收 |
| 自动采集 | SurfCore 已有 | DSH session hook | 已有，不重复 |
| 上下文注入 | L2 自动注入 | 无自动注入 | 我们更强，保留 |

---

## 二、吸收项与优先级

### P0：FTS5 检索（最高收益，零 prompt 影响）

**借什么**

- `memories_fts` 虚表；
- FTS5 查询；
- 中文 2 字滑窗 fallback；
- 失败降级 LIKE。

**怎么复用**

- `soulcore/db.py`：建 `memories_fts`，写入时同步；
- `soulcore/retrieval.py`：`search` 先 FTS，失败 LIKE；
- `soulcore/cli.py`：`memory search` 使用新检索；
- 不改 `context_render.py`，不改 L2 prompt。

**上下文影响**

```text
0：只有主动查记忆时才走 FTS
```

**验收**

- 中文自然语言查询能命中旧记忆；
- FTS 损坏时自动 LIKE；
- 现有 27 个测试通过；
- L2 prompt 字符数不变。

---

### P1：证据链最小化（不新增第二套存储）

**借什么**

- 每条 episode 能追溯到原始 memory IDs；
- 每条 correction 能追溯到旧记忆；
- 来源类型 `source_kind`。

**怎么复用**

- `episodes.raw_ids_json` 已经存在，补一个 `episode_evidence` 视图/表不是必须；
- 给 `episodes` 增加可选 `source_kind`（dialog/video/user_statement）；
- `correction.py` 已有 `superseded_by`/`correction_of`，补 `version` 字段；
- 不迁移 426 条旧数据，只对新写入生效。

**上下文影响**

```text
0：证据只在 soulcore_memory 详情里返回，不进 L2 卡片
```

**验收**

- 任一 episode 能列出 raw memory IDs；
- correction 能列出旧记忆与新记忆；
- L2 卡片不增加字符。

---

### P2：版本/状态轻量补强

**借什么**

- `status`：`active / superseded / invalidated`；
- `version`；
- `last_confirmed_at`。

**怎么复用**

- 复用 `memories.consolidation_state` 与 `affect_weight`；
- 只给 correction/superseded 记录写 `version`；
- 不新建 `memory_versions` 全量历史表；先存 JSON 快照到 `raw_json` 或侧车。

**上下文影响**

```text
0：状态不进入常驻 prompt
```

**暂不做**

- 全量版本历史；
- 乐观锁；
- 自动冲突检测；
- 这些等真实冲突出现再加。

---

### P3：L2 查询相关性（下一步，不急着做）

**借什么**

- 先用程序检索，再选 top 3–5；
- 不做随机；
- 低于阈值返回空。

**怎么复用**

- `episodes.render_cards` 增加可选 `query`；
- `context_render`/bridge 只在有新消息时传入；
- 仍然只写 `episode-cards.md`，不新增 prompt 段。

**上下文影响**

```text
可能下降：不相关的事件卡不再注入
```

**验收**

- “你还记得昨晚吗”能召回昨晚；
- 无关闲聊不硬塞旧事件；
- L2 仍 ≤1.5k 字符。

---

### P4：幂等与失败恢复（只做最小）

**借什么**

- `source_record_id` 已有唯一约束；
- episode build 用 `day + conversation + start` 幂等；
- correction 用 `question_id` 幂等。

**暂不吸收**

- outbox/inbox；
- 后台 worker；
- 多进程任务队列。

原因：单用户、本地 SQLite、daily 批处理已经够；引入队列会增加运维和上下文外的复杂度。

---

## 三、明确不吸收

| 项 | 原因 |
|---|---|
| 独立 Python 服务/FastAPI | 我们已有 CLI + SQLite，增加进程和端口没有收益 |
| 每条消息一条 working memory | QQ 群聊会快速膨胀 |
| `consolidate.py` 的 `对话片段：{content[:400]}` | 比我们 episodes 更薄 |
| `promote.py` 的证据计数 | 太粗，不能替代 appraisal |
| Graphiti/向量库 | 当前 426 条记忆不需要 |
| 它的情绪/时间 README 愿景 | 代码未落地，不能当现成能力 |
| AGPL 代码复制 | 许可风险；只做模式借鉴 |

---

## 四、实施顺序

```text
P0 FTS5 + 中文 fallback
P1 episode/correction 证据字段
P2 status/version 轻量字段
P3 L2 查询相关性
P4 幂等补齐
```

先做 P0，因为它：

- 不改 prompt；
- 不改 L2；
- 不增加模型调用；
- 直接提升 `soulcore_memory` 的查询质量；
- 可以随时回退。

---

## 五、验收指标

| 指标 | 目标 |
|---|---|
| L2 注入字符 | 不增加，最好下降 |
| 每轮模型调用 | 不增加 |
| 本地 API/进程 | 不增加 |
| 中文记忆查询 | 能命中 426 条中的相关记录 |
| 旧记忆 | 不删除、不重写 |
| 现有测试 | 27/27 通过 |
| 公开仓库 | 不引入私人数据 |

---

## 六、需要你确认

1. 是否先只做 **P0 FTS5**？
2. 是否接受 **不做全量版本历史**，只保留 correction 的最小版本？
3. 是否把 L2 查询相关性放到 P3，而不是现在动？
