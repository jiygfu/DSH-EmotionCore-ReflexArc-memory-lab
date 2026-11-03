# EmotionCore 记忆分层调用记录

设置 →「EmotionCore」→ 页面底部「记忆调用记录（分层）」。

## 层级

| 层级 | 记录内容 | 触发 |
| --- | --- | --- |
| L5 | 唤醒组装：本轮注入了多少 L3 索引、人物、未收尾项、交接 | adapter 每轮 `/context` 自动 |
| L4 | 人物关系查询 | 设置页「L4 人物」或 `/person` |
| L3 | 事件索引 / 事件详情 | `ec recall(query)` / 设置页「L3 索引」 |
| L2 | 单条原始记忆或单条事件详情 | `ec recall(memory_id / episode_id)` / 设置页「L2 …」 |

## 记录文件

- `data/memory-layer-calls.jsonl`：新分层记录，含 `layer/op/source/result_count/chars/ok`。
- `data/memory-tool-calls.jsonl`：旧 `soulcore_memory` 工具日志，只作为兼容回退；它没有 L5 自动注入记录，不能拿来判断“今天没查记忆”。

## 设置页按钮

- 「调 L3 索引」：按关键词取索引。
- 「调 L5 唤醒」：以预览模式组装一次上下文，不写 `first_wake`、不更新人物。
- 「调 L2 事件详情」：用 `episode_id`。
- 「调 L2 原文」：用 `memory_id`。
- 「调 L4 人物」：用 QQ 号读取人物关系与标签。

`/context` 的预览模式只用于查看注入内容，不会把管理员改名或写入当日人物状态。
