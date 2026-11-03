# 启动链与睡眠整理

本文只描述本机当前实际使用的启动路线和设置入口。实现全部复用现有组件，没有第二套 supervisor 或第二份记忆库。

## 一、实际启动顺序

```
DSH 主进程
  ├─ emotioncore-runtime（supervisor，DSH 启动时自动加载）
  │    ├─ EmotionCore service  :8765  server.py
  │    └─ EmotionCore worker   每日维护  worker.py
  ├─ memory-lab sidecar       :8766  memory-lab/server.py（只读实验，独立生命周期）
  ├─ dsh-onebot-qq            OneBot 连接 / QQ 会话
  └─ SnowLuma（协议端，独立进程）
       ├─ HTTP :3000
       ├─ WS   :3001  ← dsh-onebot-qq 连接这里
       └─ WebUI:5099
```

消息链路是反向的：

```
QQ → SnowLuma → OneBot WS :3001 → dsh-onebot-qq → DSH 会话
                                      ↓
                              EmotionCore :8765
```

SnowLuma 不由 DSH 的 `emotioncore-runtime` 托管。`soulcore-settings` 只负责在 DSH 启动时检测 :3000；如果没响应且 `snowlumaAutoStart=true`，就把它作为独立进程拉起。DSH 退出不会杀掉 SnowLuma。

## 二、设置页入口

位置：设置 → 插件设置 → **EmotionCore 记忆与潜意识** → **启动链 / 运行与睡眠**。

| 行 | 检测标示 | 控制 |
|---|---|---|
| SnowLuma 协议端 | 进程/HTTP、QQ 在线 | 启动 / 停止 |
| DSH OneBot 连接 | 已连接 / QQ 已登录 | 只读；重连在「QQ 控制台 → OneBot」 |
| EmotionCore 服务 | `healthy` / `down`、端口 | 启动 / 停止 / 重启 |
| EmotionCore 维护 worker | pid、运行状态 | 启动 / 停止 |
| memory-lab | 在线 / 离线 | 只读；由记忆实验室设置管理 |
| DSH 启动时自动拉起 SnowLuma | 开关 | 写入 `data/soul-bridge-settings.json` |
| 自动睡眠整理 | 开关 + 0–23 点 | 写入 `data/emotioncore-schedule.json` |
| 立即整理 | 最近一次睡眠、今日次数 | 日结 daily / 完整睡眠 sleep |

所有停止操作都会二次确认。服务/worker 停止后，runtime 的 watchdog 不会自动把它们拉回来（这是有意让“停止”真的停止）；手动启动或重启 DSH 后恢复。

## 三、睡眠整理的两种模式

都是现有 `soulcore` CLI，设置页只是调用它。两条路径都固定为：

```text
评价 → episodes/threads → consolidate → dream（含线上事件复盘）→ 日结/handoff
```

- **日结 daily**：`python -m soulcore daily`
  - 评价 → people → 事件 → consolidate → dream（线上事件复盘）→ 日结。
  - OneBot-only 路线跳过旧 SurfCore 的 inbox/export/farewell/rotation；它们只保留为显式迁移命令。
- **完整睡眠 sleep**：`python -m soulcore sleep`
  - 在 daily 的整理能力之外，额外走现有 `sleep` 流程：loop 维护、人物卡、handoff、`sleep_runs(reason="sleep")` 等。
  - OneBot-only 不执行 SurfCore farewell/session rotation；需要旧迁移时手动跑 `sync` / `export-surfcore` / `rotate-sessions`。
  - 仍是显式动作，所以按钮有确认。

自动整理由 `worker.py` 执行，不是设置页自己起定时器：

1. 设置页写 `data/emotioncore-schedule.json`；
2. worker 每轮读取该文件；
3. `auto=true` 时，到点执行现有 `daily_cycle(...)`；
4. `auto=false` 时跳过自动执行，但手动“立即整理”仍然可用。

自动执行的是 `worker.daily_cycle(...)`：做 `consolidate + dream（线上事件复盘）+ daybook`，不调用 `sleep_farewell`，也不做 `session_rotation`。**记忆整理和 dream 不再拆成两条独立链。**

因此改时间不需要重启 worker。

### 事件复盘（dream）

`dream.run(..., review_events=True)` 会：

1. 用现有 `retrieval.search_memories` 找相关旧记忆/联想；
2. 读取 `episodes` / `thread_loops` / 最后消息信号；
3. 调用**线上 API** 输出 `resolved/ongoing/waiting/abandoned`；
4. 本地规则复核后才写 `closed/archived`，不会让模型单独决定关闭；
5. 对 `chatter=true` 且低重要度的记忆设 `affect_weight=0`、`consolidation_state='ignored'`，原文仍可检索，但不参与情绪/P 和后续注入。

线上配置：

```text
data/dream-config.json
config/dream.example.json
```

默认 `provider=api`、`model=deepseek-flash`、`api_key_env=DEEPSEEK_API_KEY`。API Key 缺失/线上失败只跳过 event review，**不回落到本地 2B**；`episode_review.py` 的本地 2B 复核不再被 worker 调用。

### 睡眠绑定

- `consolidate` 负责“去情绪权重但保留可查”：`affect_weight=0`，不删原文。
- `dream` 负责事件复盘和抽样联想。
- 两者在 `daily` / `sleep` / `daily_cycle` 里按固定顺序执行；不再有只做梦不整理、或只整理不做梦的路径。

## 四、失败时先看哪里

| 现象 | 先检查 |
|---|---|
| QQ 完全没反应 | SnowLuma 是否在 :3000/:3001；DSH OneBot 是否显示已连接 |
| QQ 能连但记忆工具报错 | EmotionCore 服务 :8765 `/health` |
| 自动睡眠没跑 | worker 是否运行；`data/emotioncore-schedule.json` 的 `auto/hour` |
| 设置页显示 worker 离线 | `data/emotioncore-worker.pid` 与日志 `logs/emotioncore-worker.out.log` |
| 服务重启后短暂 down | 启动需要 1–2 秒，刷新状态即可 |

## 五、相关文件

- `plugins/emotioncore-runtime/index.js`：supervisor、service/worker 生命周期、watchdog
- `plugins/soulcore-settings/index.js`：状态检测与动作 API
- `plugins/soulcore-settings/client.js`：设置页「启动链 / 运行与睡眠」
- `plugins/emotioncore-service/worker.py`：每日维护与 schedule 读取
- `data/emotioncore-schedule.json`：自动睡眠时间
- `data/soul-bridge-settings.json`：SnowLuma 自动拉起等设置
