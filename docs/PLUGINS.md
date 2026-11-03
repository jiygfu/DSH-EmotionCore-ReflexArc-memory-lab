# 插件索引

本仓库的 DSH/EmotionCore 插件。每个目录都有独立 README。

| 插件 | 类型 | 作用 | 当前状态 |
| --- | --- | --- | --- |
| [`emotioncore-service`](../plugins/emotioncore-service/README.md) | Python sidecar | 本地记忆/情绪 HTTP 服务：context、turn、recall、activity、person_tag | 运行中 |
| [`emotioncore-runtime`](../plugins/emotioncore-runtime/README.md) | DSH host bundle | 启动并守护 service + worker | 运行中 |
| [`emotioncore-adapter`](../plugins/emotioncore-adapter/README.md) | dsh-onebot 子插件 | `ec` dispatcher、L5 上下文注入、本轮回写 | 运行中 |
| [`reflex-arc`](../plugins/reflex-arc/README.md) | dsh-onebot 子插件 | 本地骰子/L1、群聊四模式、长期活动、鱼群记录 | 运行中 |
| [`memory-lab`](../plugins/memory-lab/README.md) | Python sidecar | 只读多轴记忆召回实验 + 3D 图数据 | 实验 |
| [`memory-lab-dsh`](../plugins/memory-lab-dsh/README.md) | DSH host + client | 启停 memory-lab，渲染「意识海」设置页 | 实验 |
| [`soulcore-settings`](../plugins/soulcore-settings/README.md) | DSH host + client | EmotionCore 设置页、启动链、分层记忆调用记录 | 运行中 |
| [`soul-bridge`](../plugins/soul-bridge/README.md) | DSH host 工具 | 旧 `soulcore_memory` 工具；当前 QQ 线通常不用 | 可选/兼容 |

## 数据流

```text
QQ 消息
  → dsh-onebot-qq gate-wake / reflex-arc
  → EmotionCoreAdapter /context   (L5 自动唤醒摘要)
  → 模型
  → ec(action="reply")
  → 发送成功后 /turn              (写回一轮)

需要旧事时
  → ec(action="recall", query=...)   (L3 索引)
  → episode_id / memory_id           (L3 详情 / L2 原文)
```

## 边界

- `emotioncore-service` 是唯一直接访问 `soulcore.db` 的 HTTP 层；其他插件走本机 HTTP。
- `memory-lab` / `memory-lab-dsh` 只读，不接 QQ 主链，不写 `soulcore.db`。
- `reflex-arc` 不注册模型工具；QQ 动作仍由 `ec` dispatcher 完成。
- 所有插件默认只监听 `127.0.0.1`，不暴露到局域网。
- `data/`、`logs/`、`backups/`、数据库、API Key 不进入仓库。

## 文档

- [分层记忆调用记录](MEMORY-LAYER-CALLS.md)
- [QQ 反射弧触发与鱼群记录](QQ-REFLEX-TRIGGER.md)
- [层级地图](LAYERS.md)
- [L5 回忆树](L5-RECALL-TREE.md)
