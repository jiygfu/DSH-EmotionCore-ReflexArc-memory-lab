# 提示词注入审计

日期：2026-10-31

## 结论先行

真正占上下文的不只是“注入的提示词”，而是：

```text
固定 preset
+ 每次唤醒的动态 prompt
+ 记忆卡 / SoulCore context / B站简报
+ 会话历史
+ 工具 schema
+ 工具调用结果
```

当前真实 token 账本显示：QQ 今日约 **21,036,863 tokens**，其中一个 10 月 30 日 22:26 新建的 QQ session，到 10 月 31 日 15:58 已累计 **18,866,838 tokens**；单步 `cacheHit` 约 **274,688**。

所以“上下文长”主要不是记忆卡那 2k 字，而是 session 历史与工具输出。

## 当前各来源

| 来源 | 当前大小 | 场景 |
|---|---:|---|
| `qq-chat-v2` preset | 12,885 字符 | 所有 QQ 二代唤醒 |
| `qq-chat` preset | 4,438 字符 | 一代 / 其他 |
| `memory-card-prompt-qq.md` | 2,108 字符 | QQ / 桌宠 |
| `soulcore-context.md` | 274 字符（当前） | QQ / 桌宠 |
| `soulcore-context-bili.md` | 303 字符 | B站 |
| B站记忆简报 | 449 字符 | QQ 群唤醒 |
| `wakeSnapshot` 内联 | 上限 6,000 字符 | 唤醒 |
| 表情策略 + 表情列表 | 约 1–2k 字符 | 启用表情时 |
| 会话历史 | 无固定上限 | DSH session |
| 工具 schema | 未计入字符 | 所有工具 |
| body-state / desire | 约 100–500 字符 | SoulCore 注入 |

## 场景例子

### QQ 群聊唤醒

```text
qq-chat-v2 preset                 ~12.9k
记忆卡                             ~2.1k
SoulCore context                   ~0.3k
B站简报                            ~0.45k
唤醒规则/表情/状态/收尾             ~5–8k
wakeSnapshot                       0–6k
session 历史 + 工具结果             可能 200k+ tokens
```

### QQ 私聊 owner

少了群聊参与/鱼群规则，仍有：

```text
preset + 记忆卡 + SoulCore + 管理员规则 + 唤醒规则 + 历史
```

### 桌宠对话

```text
人格卡（≤4.2k 字符）
记忆卡（≤2.6k 字符）
SoulCore context
目的背景
说话规则
最近对话
```

通常比 QQ 轻，但仍会随历史增长。

### B站生物钟

`scheduler.js` 里是大量固定操作规则、额度/风控/评论/动态流程；这部分非常长，属于“教程型 prompt”，不是每次都需要全量。

### DSH Web GUI

不经过 SurfCore 的 QQ 唤醒 prompt；没有记忆卡 / SoulCore context 注入。它只有 DSH 本体的 system prompt + 工具 schema + 当前会话历史。

## 主要浪费点

1. **preset 太大**：12.9k 字符，所有 QQ 轮次都带。
2. **唤醒规则重复**：沉睡前等待、表情策略、收尾判断、反 AI、积极性和 token 规则每轮都在，但并非每轮都用得上。
3. **记忆三层重复**：记忆卡、SoulCore context、B站简报、人物卡有重叠。
4. **会话历史/工具输出失控**：单步 274k cacheHit，远大于静态 prompt。
5. **工具 schema 全量挂载**：工具越多，系统提示和选择成本越高。

## 建议先试的优化

- 按状态裁剪：只有准备潜水时才注入“沉睡前等待”；只有对话可能结束时注入收尾规则；只有接近额度时注入 token 防爆破。
- preset 压到 6–8k：保留安全/工具协议/人格核心，删除重复解释和长示例。
- 记忆卡压到 1–1.5k，其余靠 `soulcore_memory` 查。
- 保留每日 session 轮换，但增加“单会话 token/步数阈值”触发轮换，而不是只看日期。
- 工具 schema 按场景裁剪；桌宠不需要 QQ 全套工具。
- 用真实 token ledger 做 A/B，不要只看字符数。
