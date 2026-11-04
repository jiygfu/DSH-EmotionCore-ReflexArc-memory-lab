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

- `AGENTS.local.md` 互动规则改为设置页「人格提示词」编辑；保存时同步两份来源，并保留 `.bak-settings-*` 备份。
- `handoff.py` 增加：
  - `【这是新会话的第一轮】`
  - `创建新会话 = 刚睡醒`
  - 表层语言层/本地底层关系
  - 结尾 `【不用担心睡醒后记忆模糊】人类也这样。` 改为 footer 预留，不再被截断
- `server.CONTINUITY` 从防御性措辞改为正向定位。
- `_first_wake(chat_key)` 从“全局一天一次”改为“每个 chat/day 一次”。

## 仍然存在的边界

- 同一 chat 在同一天内重建 session，目前没有 session id 可用于再次触发 handoff；下一步应从 onebot event 传入 session id，或在 `/reset` 时清理 wake 标记。
- `config/emotioncore-persona.md` 与 `AGENTS.local.md` 仍物理存在两份，但设置页保存会同步；如果要彻底单源，应让 AGENTS 成为生成文件或软链。
- 历史备份：
  - `workspace/AGENTS.local.md.before-emotioncore-persona`：旧详细蓝色大肥鱼人格（8449 bytes）
  - `personas/蓝色大肥鱼.md`：旧预设
  - `data/handoff.md` / `backups/*/handoff.md`：仍保留“记忆模糊，人类也这样”
