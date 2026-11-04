# API source switch

## UI

EmotionCore 设置页 → **API 来源**：

- provider 来自 `ctx.llm.listProviders()`；
- model 来自 `ctx.llm.listModels(provider)`；
- 当前值来自 `ctx.agentDefaultModel.currentSelection()`。

## 切换顺序

```text
1. python -m soulcore sleep
2. agentDefaultModel.saveSelection({provider, model})
3. POST /wake/reset
4. qq-console action clear-qq-sessions（confirm=true）
5. 写 state/emotioncore-context-epoch.json
```

这样做的原因：

- 先压缩/整理旧记忆并写 handoff；
- 旧 DSH session 仍绑定旧模型，必须清空 QQ 线映射；
- 下一条 QQ 消息新建 session，才会读取新的默认模型；
- epoch 让 adapter 的 L5 cache 失效，新 session 会重新注入一次交接；
- wake reset 让新 session 不是“今天已经醒过”。

## 测试记录

2026-11-04：

```text
provider: ark-code-latest
model: deepseek-v4.1-flash
selection: 已保存
sleep: true
clear-qq-sessions: cleared=1, archived=1
sessions.json: {}
wake state: {}
```

当前默认模型：

```text
ark-code-latest / deepseek-v4.1-flash
```

下一条 QQ 消息会开新会话；旧 QQ 会话已归档，不会继续沿用旧模型。
