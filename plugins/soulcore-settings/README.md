# SoulCore / EmotionCore Settings

DSH settings section for the local EmotionCore stack. It combines a Host half
(local HTTP + Python commands) and a browser half (the settings page).

```text
settings.section id: soulcore
label: EmotionCore
order: 8
host API: /soulcore-settings/api/state
          /soulcore-settings/api/action
```

## 页面内容

- 启动链：SnowLuma、DSH OneBot 连接、EmotionCore service、worker、睡眠
- 记忆库/FTS/L2/sidecar 文件状态
- 能力开关：QQ、L2、记忆提示、桌宠、B 站
- 运行参数：Python / SQLite / Node / 超时 / 并发
- 鱼鱼找鸡（QQ 反查）运行器
- 运行与测试：保存、导出 sidecar、评价、修复身份、测试查询
- **记忆调用记录（分层）**：L5 唤醒 / L4 人物 / L3 索引 / L2 原文
- 分层手动调用：`调 L3 索引`、`调 L5 唤醒`、`调 L2 事件详情`、`调 L2 原文`、`调 L4 人物`

## 分层记录

Host 读取：

```text
data/memory-layer-calls.jsonl
```

每条包含 `layer/op/source/result_count/chars/ok`。旧文件
`data/memory-tool-calls.jsonl` 只记录已下线的 `soulcore_memory`，页面在
没有新记录时把它作为兼容回退。

L5 的「调 L5 唤醒」使用 `preview:true`：只组装上下文，不写
`first_wake`、不改人物、不推进当日状态。

详细说明：`docs/MEMORY-LAYER-CALLS.md`。

## Host action

`POST /soulcore-settings/api/action`：

```json
{ "action": "layer-call", "layer": "L3", "query": "跑团" }
```

可用 action：

```text
save / capability / rebuild-fts / episode-cards / test / export
appraise / repair / runtime / snowluma / sleep / sleep-schedule
fish / layer-call / refresh
```

`runtime` 通过 `emotioncore-runtime` service 控制 service/worker；
`layer-call` 只调用本机 `127.0.0.1:8765`。

## 安全边界

- 只接受 loopback 请求；写操作要求同源 + `application/json`。
- 不把 API Key / OneBot token 返回给前端。
- 不直接改 `soulcore.db` 的记忆内容；写入动作只通过已有的 Python CLI/服务。
- 设置文件：`data/soul-bridge-settings.json`、`data/capabilities.json`。

## 依赖

- `emotioncore-runtime`（可选，用于启动链按钮）
- 本机 `python` 和仓库根目录（`EMOTIONCORE_ROOT` 可覆盖）
- `webServer` 服务（DSH host）
