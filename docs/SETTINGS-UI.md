# EmotionCore DSH 设置页

## 位置

DSH Web UI → Settings → **EmotionCore**（order 8，在 SurfCore 与 Models 之间）。

> 可见名称统一为 **EmotionCore**。内部包名、插件 ID、Python 包名和数据库路径仍保留 `soulcore`，避免破坏已有安装、配置、import 和会话。

## 页面内容

### 状态卡片

- 长期记忆条数
- FTS5 索引条数
- episode 事件索引数量
- L2 事件卡是否生成
- API 余额
- 鱼鱼找鸡运行状态

### 运行状态

- 记忆分布：`private / group / pet / 其他`
- FTS5 索引状态 + 重建按钮
- L2 事件索引状态 + 重建按钮
- 身体状态（临时；只影响语气，不写 P）
- 睡眠收尾
- 会话预算
- 本地数据库
- 技能清单
- 评价/待确认问题队列

### 上下文与能力

- L2 事件卡注入
- EmotionCore 上下文注入
- 记忆卡回退
- QQ 能力
- 桌宠能力
- B 站能力

能力开关写入：

```text
data/capabilities.json
```

### 功能开关

- 记忆查询工具（`soulcore_memory`）
- 允许模型写修正记忆（`resolve`，默认关闭）
- 影子检索日志
- 影子检索写回标记

保存后，`soul-bridge` 在下一次调用时读取新值，不需要重装插件。
记忆查询默认走 **EmotionCore 全局本地库**，跨私聊/群聊；只有显式 `mode=surfcore` 才走 SurfCore 当前会话召回。

### 运行参数

- Python 路径
- SQLite 路径
- Node 路径（仅 `mode=surfcore` 时需要）
- 单次超时
- 影子最大并发

### 操作按钮

- 保存设置
- 导出增强 sidecar（`export-surfcore`）
- 运行一次本地评价（`appraise --limit 1`）
- 修复旧身份（`repair-identities`）
- 重建 FTS（`fts-rebuild`）
- 重建 L2 事件卡（`episode-cards`）
- 刷新状态
- 测试记忆查询

这些操作都在本机 Python/SQLite 中执行，不经过 QQ API，也不调用 AI。

### 最近调用

读取：

```text
data/memory-tool-calls.jsonl
```

显示时间、backend、模式和结果数。

## 持久化

```text
data/soul-bridge-settings.json   # 工具/影子/路径
data/capabilities.json           # 能力开关
data/body-state.json             # 临时身体状态
data/balance.json                # API 余额
data/session-budget.json         # 会话轮换
data/sleep-farewell.json         # 睡前收尾
```

## Host API

仅本机回环；写操作要求同源 + `application/json`。

```text
GET  /soulcore-settings/api/state
POST /soulcore-settings/api/action
```

`action`：

```text
save / test / export / appraise / repair / fish / refresh
capability       { key, value }   更新能力开关
rebuild-fts      {}               重建 FTS5
episode-cards    {}               重建 L2 卡
```

## 安装与验证

bundle：

```text
@soulproject/soulcore-settings
```

已安装并 applied。

已验证：

- `settings.section` occupant：`soulcore` active
- `GET /soulcore-settings/api/state` 返回 `ok=true`、记忆/FTS/L2/capabilities/body/balance
- `memory-stats` 返回 426 条记忆、426 条 FTS、68 个 episodes
- `POST action=rebuild-fts` 返回 `memories=426`、`fts_rows=426`
- `POST action=capability` 可以更新 `l2/inject/memory_prompt/qq/pet/bili`

## 注意

- 页面改的是本地设置文件，不改 `cordis.patch.yml`。
- 可见名称改了，但插件 ID / 包名保留 `soulcore-*`；这是兼容性选择，不是遗漏。
- 当前浏览器页面若没有立即出现新标签或新文案，刷新 DSH Web UI 一次。
