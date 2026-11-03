# SoulCore Phase 1

本地记忆 + 评价 + 情感状态原型。  
当前已通过 `soul-bridge` 向 DSH 提供只读 `soulcore_memory` 工具；不再只是离线原型。

## 做什么

- SQLite 存记忆、评价、情感快照、评价队列
- 只读同步 SurfCore 当前角色的 `memory-card.json`
- 用本地 Ollama 模型 `huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M` 做文本评价
- 每条记忆记录评价向量、`encoding_familiarity`、`unresolved`
- 计算最近评价的情感汇总：valence / arousal / stress / unresolved
- 不计算性格向量 P（Phase 4 再做）

## 命令

在 `soulproject` 目录下：

```bash
python -m soulcore init
python -m soulcore seed-demo
python -m soulcore appraise --limit 3
python -m soulcore status
python -m soulcore config
python -m soulcore affect --save
python -m soulcore consolidate --mode day_end --dry-run
python -m soulcore consolidate --mode day_end
python -m soulcore trigger demo:demo:01 --source test
python -m soulcore context --limit 12
python -m soulcore recall --text "主人说明天要考试" --limit 5
python -m soulcore shadow --text "主人说明天要考试"
python -m soulcore dream --budget 8 --seed 7
python -m soulcore dream --budget 8 --diary
python -m soulcore p
python -m soulcore person-context --id qq:<ownerQQ>
python -m soulcore memory --mode overview
python -m soulcore memory --mode search --query "AI" --person <ownerQQ>
python -m soulcore memory --mode range --date 2026-10-29
python -m soulcore memory-log --limit 20
python -m soulcore export-surfcore
python -m soulcore felt-backfill --limit 30
python -m soulcore day-summary
python -m soulcore day-baseline
python -m soulcore learn-appraisals
python -m soulcore appraisal-report
python -m soulcore appraisal-policy --mode shadow
python -m soulcore question-list
python -m soulcore question-resolve --id q_xxx --summary "..." --score-json "{}"
python -m soulcore purpose-seed
python -m soulcore body-state
python -m soulcore desire
python -m soulcore skill-manifest
python -m soulcore episode-build
python -m soulcore episodes
python -m soulcore rotate-sessions --reason manual
```

`memory` 的普通关键词搜索优先复用 SurfCore 的 `recallFullMemory()`；带 person/scope/日期时用本地索引补足。

## 评分后端

默认使用与 SurfCore/DSH 同源的 API：

```json
{
  "provider": "api",
  "model": "deepseek-flash",
  "base_url": "https://api.deepseek.com",
  "api_key_env": "DEEPSEEK_API_KEY"
}
```

本地 Ollama：

```json
{
  "provider": "ollama",
  "model": "huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M",
  "base_url": "http://127.0.0.1:11434",
  "api_key_env": ""
}
```

写到 `data/appraisal-config.json`（不提交仓库），示例见 `config/appraisal.example.json`。
  
每次 `soulcore_memory` 工具调用都会追加到 `soulproject/data/memory-tool-calls.jsonl`。

手动睡前也可以双击 `soulproject\sleep.cmd`。  
`sleep` 只做本地数值整理和 packet 导出，不生成日记；日记/明天计划最终交给 SurfCore 的高层 API。

`dream --diary` 是本地实验，不是最终路径。
```

`consolidate` 会先计算当天“不重要事件”的平均影响分（ambient），写入
`ambient_pressures`，然后再把它们的 `affect_weight` 清零；重要事件保留。
ambient 异常高只标记 `flagged=1`，不会立刻改人格。

# 只读同步（默认只导入 20 条；不传 --include-sensitive 会跳过敏感记录）
python -m soulcore sync --limit 20

# 合并全量档案 memory-card-full.jsonl（本地长期库无条数上限）
python -m soulcore sync --full --limit 1000

# 保留 senderId 的群友身份（memory-inbox.jsonl）
python -m soulcore sync-inbox --limit 200 --no-self
python -m soulcore people --refresh
python -m soulcore person-context --id qq:<ownerQQ>
python -m soulcore people-due
python -m soulcore people-profile --id qq:<ownerQQ>
python -m soulcore social
python -m soulcore skills
python -m soulcore skill-route --text "同步一下群聊记忆"
python -m soulcore skill-run --id memory.people_refresh
python -m soulcore daily --appraise-limit 30
python -m soulcore render-context --show
python -m soulcore memory --mode overview
python -m soulcore memory --mode search --query "考试" --limit 5
python -m soulcore memory --mode person --person <ownerQQ>
```

`memory` 是给表层意识的只读记忆查询：overview / today / search / person / p。

`memory` 是给表层意识的只读记忆查询：overview / today / search / person / p。

也可以双击 `soulproject\daily.cmd`。  
`render-context` 只生成本地 P/人物卡文件，尚未注入 SurfCore。
python -m soulcore appraise --limit 5
```

如果 Python 不在当前目录，设置：

```powershell
$env:PYTHONPATH = "<REPO_ROOT>"
```

## 数据

- 默认数据库：`soulproject/data/soulcore.db`
- 可用 `--db` 指定其他路径
- SurfCore 根目录默认：`<USERPROFILE>\.dsh\surfcore`
- 只读字段：`memory-card.json` 的 records

## 评价输出

模型只输出评价维度，不输出性格/诊断：

```json
{
  "dimensions": {
    "security": 0.42,
    "trust": 0.61,
    "self_efficacy": 0.38,
    "caution": 0.71,
    "sociability": 0.33,
    "openness": 0.22,
    "valence": -0.35,
    "arousal": 0.58
  },
  "unresolved": 0.44,
  "confidence": 0.71,
  "evidence": "原文中的关键片段",
  "has_impact": true
}
```

失败默认不伪造数据：job 保持 pending，等下次重试；  
加 `--fallback` 才会用低置信度启发式兜底。

## 测试

```powershell
$env:PYTHONPATH = "<REPO_ROOT>"
python -m unittest discover -s soulproject/tests -v
```
