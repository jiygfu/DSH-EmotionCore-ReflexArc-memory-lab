# Soul Bridge （可选旧工具层）

可选的 DSH host 工具插件，向模型注册只读的 `soulcore_memory` 工具。它主要
保留给旧会话/旧 preset；当前 QQ 线的首选入口是 `plugins/emotioncore-adapter`
暴露的 `mcp__qq__ec(action="recall", ...)`。

## 模式

| mode | 用途 |
| --- | --- |
| `today` | 今天被触发/写入的记忆 |
| `search` | 关键词检索本地长期库 |
| `person` | 某人的关系卡与最近记忆 |
| `range` | 按日期/时间范围查 |
| `overview` | 调试用总览；需要设置页打开 `memoryOverview` 并重载插件 |

默认最多返回 8 条。`truncated=true` 表示只是抽样，模型不应声称看到了
完整记忆。

## 配置

`cordis.patch.yml` / `data/soul-bridge-settings.json`：

```yaml
- insert:
    - id: soul-bridge
      name: '@soulproject/soul-bridge'
      config:
        enabled: true
        mark: false
        pythonPath: python
        dbPath: ./data/soulcore.db
        logPath: ./data/shadow-bridge.jsonl
        timeoutMs: 4000
```

`memoryTool=false` 会拒绝工具调用；`memoryResolve` 默认关闭，不向模型开放
写修正记忆；`mark` 默认关闭。

## 日志

旧的工具调用写：

```text
data/memory-tool-calls.jsonl
```

它只记录 `soulcore_memory`。当前分层记忆（L5 自动 `/context`、L3/L2 recall、
L4 人物）的观测日志是：

```text
data/memory-layer-calls.jsonl
```

详见 `docs/MEMORY-LAYER-CALLS.md`。

## 边界

- 只读本地记忆；默认不写、不改 P、不做召回重排。
- 不是 QQ 通道、不处理消息、不注册 QQ 动作。
- 当前 QQ 栈中通常不启用它；启用前先确认 preset 是否仍需要
  `soulcore_memory` 这个工具名。
