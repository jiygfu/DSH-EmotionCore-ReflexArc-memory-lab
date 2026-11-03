# SurfCore × SoulCore 记忆整合方案

> 状态：sidecar 导出与 SurfCore 读取合并已实现（2026-10-29）。
> 当前导出：29 条 enrichment、6 条 extension（5 人物卡 + 1 情感/P），共 35 行。
> SurfCore 读取层已支持 `soulcore` 字段；DSH 宿主需重启才会加载最新 `memory-card.js`。

## 1. 现在的冲突是什么

不是运行时冲突，是**数据模型重叠**。

| 数据 | SurfCore | SoulCore | 问题 |
|---|---|---|---|
| 原文记忆 | `memory-card-full.jsonl` | `memories.text` 又存一份 | 双真相，可能漂移 |
| 身份 | 衰减卡只有 `speaker` 显示名 | `people` / `person_id` | 旧记录无法对齐 |
| 评价 | 无 | `appraisals` | 只存在本地，SurfCore 查不到 |
| 情感 | P 不存 | `affect_snapshots` / P | 只存在本地 |
| 索引 | 无 | `current_familiarity` 等 | 只存在本地 |

所以：

```text
SurfCore = 事实与原文的 canonical store
SoulCore = 对事实的增强索引
```

SoulCore 不应该再拥有第二份“事实原文”。

---

## 2. 统一格式

以 SurfCore 的记录为核心，只增加一个 `soulcore` 命名空间：

```json
{
  "schema": "surfcore.memory.v1",
  "id": "mem_xxx",
  "createdAt": "2026-10-29T09:58:25.505Z",
  "platform": "qq",
  "scope": "qq",
  "kind": "event",
  "title": "<群友A>：现在的ai…",
  "text": "原文……",
  "speaker": "<群友A>",
  "importance": 16,
  "tags": ["qq"],
  "isSelf": false,

  "soulcore": {
    "schema": "soulcore.enrichment.v1",
    "person_id": "qq:<ownerQQ>",
    "identity_status": "resolved",
    "felt": "我那时觉得被认真对待了，也有点意外。",
    "delta": {
      "security": -0.13,
      "trust": -0.30,
      "self_efficacy": -0.18,
      "caution": 0.21,
      "sociability": -0.16,
      "openness": -0.16,
      "valence": -0.23,
      "arousal": 0.06
    },
    "appraisal": {
      "security": 0.50,
      "trust": 0.30,
      "self_efficacy": 0.40,
      "caution": 0.60,
      "sociability": 0.20,
      "openness": 0.30,
      "valence": 0.00,
      "arousal": 0.40,
      "unresolved": 0.34,
      "confidence": 0.71,
      "has_impact": true
    },
    "affect_weight": 1.0,
    "consolidation_state": "none",
    "last_triggered_at": null,
    "index": {
      "current_familiarity": 0.35,
      "processing_fluency": 0.42
    }
  }
}
```

规则：

- `id / createdAt / text / speaker / tags` 等核心字段，完全沿用 SurfCore。
- 所有本地增强只放在 `soulcore` 下，不污染 SurfCore 字段。
- SurfCore 不认识的 `soulcore` 字段会被忽略，不会破坏原逻辑。
- 单条记忆只记录 `delta`（相对当日基准的偏离量）和 `felt`；绝对基准只出现在当日 `soulcore:affect:latest` / P 快照。
- 旧记录不猜 owner：`identity_status=legacy_unresolved/self` 保持明确。

---

## 3. 落盘结构

不覆盖 SurfCore 原文件，新增一个只追加 sidecar：

```text
<character>/memory/
  memory-card-full.jsonl              # SurfCore 原文，canonical
  memory-card-full.soulcore.jsonl     # SoulCore 增强，sidecar
  memory-card-full-stats.json
```

sidecar 只允许两种行：

### enrichment：给已有 SurfCore 记录加增强

```json
{"schema":"soulcore.enrichment.v1","record_id":"mem_xxx","soulcore":{...}}
```

### extension：SoulCore 自己产生的、SurfCore 没有的本地信息

```json
{"schema":"soulcore.extension.v1","record":{...SurfCore 兼容记录...},"soulcore":{...}}
```

适合放：

- 人物卡快照
- affect 快照
- 重要索引事件
- 手动 pin 的本地信息

这些 extension 记录用 `kind: "soulcore.person" / "soulcore.affect" / "soulcore.index"` 标记，避免混进普通聊天记忆。

---

## 4. SurfCore 怎么自然查到

在 `memory-card.js` 的读取层加一个合并器，不改变原存储：

```text
readAllFullRecords / scanFullRecords
  ├─ 读 memory-card-full.jsonl
  ├─ 读 sidecar
  ├─ enrichment 按 record_id 合并到主记录
  └─ extension 作为额外记录追加
```

然后：

```text
recallFullMemory()     → 同时召回主记录 + sidecar 扩展
fullMemoryCardSnapshot() → 返回统一格式
控制台「全量记忆卡」 → 直接能搜到增强信息
```

这样 SurfCore 的原有查询语法不变，但能看到：

- 这条记忆是谁说的
- 当时的评价
- 当前情感权重
- 人物关系
- 是否被今天触发

---

## 5. SoulCore 端怎么配合

### 保留

- `memories` 作为**可重建的本地缓存/索引**，不是唯一真相。
- `appraisals`、`affect_snapshots`、`people`、`p_snapshots` 作为增强数据。

### 修改

- 新记录优先按 SurfCore `id` 建索引，不再按文本另造一套主键。
- 每条评价必须挂在 SurfCore 记录 id 上；找不到主记录就不产生孤儿评价。
- 导出器负责写 sidecar；SurfCore 只读。
- `soulcore_memory` 的全文搜索继续用 `recallFullMemory()`；本地只补 person / date / affect / index。

### 不再做

- 不再把“全文搜索”实现成第二套 SQLite LIKE/相似度检索。
- 不再让旧记录因为缺 senderId 被默认归给 owner。
- 不再把 sync 当“复制一份记忆”，而是“建立增强索引”。

---

## 6. 本地小模型的角色

本地 2B 模型只做：

```text
SurfCore record
  → 本地评价（valence/trust/...）
  → soulcore.appraisal
```

它不创建新的“事实记忆”，也不覆盖原文。

所以不会和 SurfCore 抢记忆所有权：

- SurfCore 决定“发生过什么”
- SoulCore 决定“这件事对人格/关系意味着什么”
- 高层 API 决定“现在怎么扮演、怎么说”

---

## 7. 分步落地

1. ✅ 写 `export_surfcore.py`，从本地 DB 生成 sidecar（enrichment + extension）。
2. ✅ 给 `memory-card.js` 加 sidecar 合并器。
3. ✅ `recallFullMemory()` 验证能返回 `soulcore` 字段。
4. ✅ `soulcore_memory` 返回统一格式（built-in search）。
5. ⏳ 逐步停止在新记录上复制全文，只保留索引/缓存。
6. ⏳ 加一致性测试：
   - 主记录 + enrichment 合并后不重复
   - 缺主记录的 enrichment 不生效
   - identity_status 不被覆盖
   - 删除本地缓存后可由 SurfCore + sidecar 重建

---

## 8. 一句话

> SurfCore 管“记忆是什么”，SoulCore 管“这段记忆意味着什么”。  
> 两边用同一份 record id 和同一个 `soulcore` 扩展字段对接，就不冲突，也不需要重复发明全文记忆。
