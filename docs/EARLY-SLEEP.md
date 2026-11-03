# 主动提前睡眠与 token 测试

## 现在能手动触发

### 日常完整整理

```powershell
cd <REPO_ROOT>
.\daily.cmd
```

`daily` 会：

```text
day baseline
→ sync inbox
→ appraise
→ episode-build
→ consolidate
→ dream
→ finalize day
→ export
→ purpose-seed
→ rotate-sessions
→ render-context
```

跑完当前 QQ 会话会被归档，下一条消息新建 session。

### 只做睡前整理

```powershell
cd <REPO_ROOT>
.\sleep.cmd
```

注意：`sleep` 不会自己 `sync inbox` / `appraise`。  
如果当天还有未处理消息，先 `daily.cmd` 或 `python -m soulcore appraise`。

## 提前测试 token

1. 记录当前 token：

```powershell
Get-Content <USERPROFILE>\.dsh\surfcore\token-usage-state.json -Raw
Get-Content <USERPROFILE>\surfcore\state\token-usage.jsonl -Tail 5
```

2. 跑一次 `daily.cmd`。

3. 确认旧会话被归档：

```powershell
Get-Content <USERPROFILE>\surfcore\state\sessions.json
Get-Content <USERPROFILE>\surfcore\state\bridge.log -Tail 20
```

4. 在 QQ 里发一条新消息，生成新 session。

5. 再对比：

```powershell
Get-Content <USERPROFILE>\.dsh\surfcore\token-usage-state.json -Raw
Get-Content <USERPROFILE>\surfcore\state\token-usage.jsonl -Tail 10
```

重点看新 session 的 `cacheHit`/`cacheMiss`，而不是全天累计。

## 要不要重启

- 只换会话：不需要重启 DSH。
- 改了桥接/SoulCore 代码：需要重启桥接。
  - `restart.bat` 只重启 bridge。
  - DSH 本体重启需要关闭/重开应用。
- 想测“完全冷启动”：先 `daily.cmd`，再完全退出 DSH，重开，再发消息。

## 自动压缩/裁剪

已启用 DSH：

```text
tool-result-pruner
compaction-basic
```

自动 session 预算：

```text
data/session-budget.json
```

当前配置：

```json
{
  "enabled": true,
  "maxCacheHit": 120000,
  "intervalMs": 900000
}
```

每 15 分钟检查一次；累计 cacheHit 超阈值的 QQ 会话会被归档。  
想只手动测试，把 `enabled` 改成 false，再执行：

```powershell
python -m soulcore rotate-over-budget --max-cache-hit 120000
```

手动预算轮换已实测：2026-10-31 17:14 将 group/private 两个超阈值会话归档，`sessions.json` 清空；下一条 QQ 消息会新建短会话。

## 睡前晚安

`data/sleep-farewell.json` 控制：

```json
{
  "enabled": true,
  "message": "哼，我去睡了。晚安，明天再说。"
}
```

`sleep.cmd` / `daily.cmd` 会在归档会话前通过桥接 `/api/test-send` 私聊 owner；桥接不可用时写入反馈文件，不阻塞睡眠。

## 注意

- 提前 `daily` 会把“今天”提前结算；之后的新评价仍会记录，但日账已经收口。
- 会中断当前 QQ 对话的上下文，这是测试目的。
- 不要在重要聊天进行中跑。
