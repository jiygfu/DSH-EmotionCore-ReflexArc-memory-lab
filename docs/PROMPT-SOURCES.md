# Prompt sources audit

## 当前实际来源

| 来源 | 实际作用 |
| --- | --- |
| `workspace/AGENTS.local.md` | DSH 新会话真正加载的人格/互动规则 |
| `config/emotioncore-persona.md` | `/context` 的 `persona` 字段；**adapter 只取 `context`，没有把它注入** |
| `data/handoff.md` | 睡眠交接，只在 `first_wake` 时由 `/context` 注入 |
| `server.CONTINUITY` | 每轮 `/context` 的固定连续性说明 |

所以之前是**两份人格 + 一份交接**，而真正生效的只有 `AGENTS.local.md`。这是调用混乱的根源。

## 已修复

- `config/emotioncore-persona.md` 作为唯一可编辑源；`AGENTS.local.md` 由设置页生成，保留 `.bak-settings-*` 备份。
- 设置页可列出 `personas/*.md`，支持载入/另存；旧「蓝色大肥鱼」预设可切换，但不会自动覆盖当前人格。
- `AGENTS.local.md` 互动规则改为设置页「人格提示词」编辑；保存时同步两份来源。
- `handoff.py` 增加：
  - `【这是新会话的第一轮】`
  - `刚睡醒：窗口清空，本地记忆和关系还在`
  - 结尾 `【不用担心睡醒后记忆模糊】人类也这样。` 改为 footer 预留，不再被截断
- 表层语言层定位只放在人格源，handoff 和 CONTINUITY 不再重复。
- 设置页人格管理：载入、另存、新建模板、重命名；旧「蓝色大肥鱼」可选。
- `_first_wake(chat_key)` 从“全局一天一次”改为“每个 chat/day 一次”。

## L5 注入策略

`emotioncore-adapter` 新增：

```text
injectContextMode = first_wake | on_change | every_turn
默认 first_wake
```

- `first_wake`：每个 chat/day 只 fetch + inject 一次；
- `on_change`：每轮 fetch，但只按稳定摘要 hash 变化注入；身体/耐心/念头不参与 hash；
- `every_turn`：兼容旧行为；
- 本地动作说明 `[本地QQ能力]` 默认也只注入一次；`every_turn` 才重复；
- 首次注入的 L5 会留在会话历史里，后续用 `ec recall`。

QQ 会话实测：49 次 `[EmotionCore]` 注入，约 55k 字符，平均 1.1k/次。改成
`first_wake` 后，正常情况下只保留 1 次。

## 仍然存在的边界

- 同一 chat 在同一天内重建 session，目前没有 session id 可用于再次触发 handoff；下一步应从 onebot event 传入 session id，或在 `/reset` 时清理 wake 标记。
- `config/emotioncore-persona.md` 是唯一编辑源；`AGENTS.local.md` 是 DSH 启动需要的生成副本。不要直接编辑 AGENTS，统一走设置页。
- 历史备份：
  - `workspace/AGENTS.local.md.before-emotioncore-persona`：旧详细蓝色大肥鱼人格（8449 bytes）
  - `personas/蓝色大肥鱼.md`：旧预设
  - `data/handoff.md` / `backups/*/handoff.md`：仍保留“记忆模糊，人类也这样”
