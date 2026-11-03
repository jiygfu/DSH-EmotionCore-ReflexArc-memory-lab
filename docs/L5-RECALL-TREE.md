# L5 + 本地回忆树契约

时间：2026-11-02
目的：明确“绝大多数层在本地跑、API 只做表层意识”的边界；同时保证 API 能通过本地层级逐层回忆过去。

## 1. 总原则

```text
L0–L5：本地固定程序
L6：API 语言层
```

API 不拥有记忆、情绪、人格或检索算法。  
API 只拿到：

```text
一小段 L5 上浮内容
+ 一个极小的本地 recall 入口
```

记忆重建由本地程序完成，不由模型“凭上下文想象”。

## 2. 分层职责

| 层 | 职责 | 是否进 prompt | 是否由 API 决策 |
|---|---|---|---|
| L0 身体 / 内感受 | 负载、余额、时间感、临时身体状态 | 只进自然语言一行 | 否 |
| L1 感知 / 反射弧 | 入站结构、骰子、OCR、引用、转发、链接 | 只进短 hint | 否 |
| L2 原始记忆 | 原文、说话人、时间、来源 | 默认不进 | 否 |
| L3 事件记忆 | episode 摘要、关键引语、感受、未解决度、raw_ids | 只进 1–2 条索引 | 否 |
| L4 情绪 / 欲望 / 人物 | P、affect、desire、patience、人物关系 | 只进自然语言 | 否 |
| L5 唤醒组装 | 这次醒来注入什么 | 是 | 否 |
| L6 表层语言 | 推理、发言、调用 recall | 否 | 只决定“要不要往深查” |

## 3. 回忆树

```text
第一层：索引
  query / 当前消息 / 人物 / 日期
  → L3 episode candidates
  → 返回最多 2 条：时间、参与者、事件概述、episode_id

第二层：事件详情
  episode_id
  → summary / key_quote / felt / unresolved / raw_ids
  → 仍不返回整段原文

第三层：原始记忆
  memory_id
  → 单条原文
  → 仍受隐私、身份、长度限制
```

这就是“树形记忆”的最小实现。  
以后可以在第一层加本地向量召回，但**候选选择仍由本地做**。

## 4. L5 只负责第一层

### 首次唤醒

```text
handoff
+ P/身体/欲望自然语言
+ 当前对象/今日人物
+ 最多 2 条按当前消息选中的 L3 索引
+ 连续性契约
```

### 后续唤醒

```text
当前消息
+ P/人物短摘要
+ 最多 2 条 L3 索引
+ 连续性契约
```

L5 **不直接塞原文列表**，只塞“可以继续查的索引”。

## 5. API 的 recall 入口

保持一个极小的 `ec` 工具，增加 recall 动作：

```text
ec(action="recall", query?, episode_id?, memory_id?, person?, date?, limit?)
```

返回规则：

```text
无 episode_id / memory_id：
  最多 2 条 L3 索引
  每条：时间 + 参与者 + 一句话概述 + episode_id

有 episode_id：
  1 条事件详情
  summary + key_quote + felt + unresolved + raw_ids（最多 3 个）

有 memory_id：
  1 条原文
  最长 1200 字符
```

约束：

```text
不返回 SQL
不返回整库
不返回 20 条列表
不返回 P 数值
不返回 overview 统计
不写记忆
```

## 6. 与 `soulcore_memory` 的关系

`L5` 和 `soulcore_memory` 不应同时承担“唤醒组装”。

最终：

```text
L5 = 预注入第一层索引
ec recall = 模型主动往深查
soulcore_memory = 管理端/调试，不再进 QQ 工具面
```

旧的 `overview`、`p`、`questions`、`resolve`、`surfcore` 不再出现在 QQ schema。

## 7. 角色卡约束

角色卡必须保留：

```text
你对自己的记忆不是全知的
一次查询只能看到有限条
先出概述/索引，需要时再往深查
查不到、被截断就承认
```

不能说：

```text
所有记忆都能一次查完
```

否则会和 L5“只给索引”及 recall“逐层返回”冲突，导致 API 怀疑或补洞。

## 8. 当前实现差距

| 能力 | 当前 | 缺口 |
|---|---|---|
| L5 第一层索引 | 有，但用 `search_memories` 文本片段 | 没有稳定 episode_id / 树形指针 |
| episode 详情 | 有表 `episodes` | 未接 recall 接口 |
| raw memory 详情 | 有 `memories` | 未接按 id 单条读取 |
| recall 工具 | 只有 `ec` 的 send/image/sticker/at/... | 缺 `recall` 动作 |
| 向量召回 | 无 | 可后续加本地 embedding |
| L3 新鲜度 | 依赖旧 episodes | appraisal/episode 管线未定时 |
| L0/L4 上浮 | 部分 | 身体/欲望/耐心未稳定进入 L5 |

## 9. 落地顺序

```text
1. EmotionCore 服务增加 /recall
2. ec 增加 recall 动作
3. L5 的 l2 改为返回 episode 索引（带 episode_id）
4. QQ 线移除 soulcore_memory，保留管理端
5. 接 appraisal/episode 定时管线
6. 再接 L0 身体 / L4 desire/patience
7. 最后再加本地向量召回
```

## 10. 一句话

```text
L5 不是“把记忆都塞给 API”
L5 是“把这次该浮现的索引递给 API”
API 想深入，再让本地按索引逐层重建
```
