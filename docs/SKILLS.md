# 本地 Skill / 程序性记忆设计

日期：2026-10-29  
定位：SoulCore 的“本地技能层”，不是 DSH Agent Skill 的替代品。

---

## 1. 先分清两个 Skill

### 1.1 DSH Skill

DSH 的 Skill 是给**高性能表层意识**读的提示词/流程包：

- 以 markdown/资源形式被发现；
- 进入高层模型的上下文；
- 改变“怎么想/怎么做”；
- 不是本地可执行程序；
- 不适合直接塞给 2B 本地模型当代码执行。

### 1.2 本地 Skill

SoulCore 的本地 Skill 是：

```text
manifest（意图、输入、前置条件、执行器、成功标准）
+ deterministic executor（代码/内置函数）
+ outcome（成功/失败/延迟/错误）
```

本地模型只输出：

```json
{ "skill_id": "memory.sync_surfcore", "args": {}, "confidence": 0.82 }
```

然后由代码校验、执行、记录。  
**不是让 2B 模型自由写步骤或写代码。**

---

## 2. 本地模型只做“主观/歧义”部分

| 工作 | 谁做 |
|---|---|
| 同步、去重、索引、检索、清洗、计数、schema 校验 | 确定性代码 |
| 明确意图路由（关键词/状态/规则） | 规则优先 |
| 歧义意图选择 | 本地模型，低置信度则回退/询问 |
| 评价维度赋值（security/trust/...） | 本地模型 |
| 日记、计划、复杂叙事 | 高性能 API |
| 写新 skill / 改 skill 流程 | 高性能 API 起草，用户批准 |

这样弱模型只做它相对擅长的“判断”，不做长链执行。

---

## 3. 本地 Skill Manifest

示例：

```json
{
  "id": "memory.sync_surfcore",
  "version": 1,
  "title": "同步 SurfCore 记忆",
  "intent_examples": ["同步一下记忆", "把新记录读进来"],
  "when": { "source": "surfcore", "min_interval_s": 60 },
  "inputs": {
    "limit": { "type": "integer", "default": 20, "maximum": 1000 }
  },
  "executor": "builtin:sync_surfcore",
  "success": ["no_exception", "records_read >= 0"],
  "cost": "low",
  "fallback": "report_only"
}
```

约束：

- `executor` 只能引用**已注册的内置执行器**；
- 新执行器需要代码审查，不允许模型运行时生成；
- `success` 是可验证条件，不是模型自评；
- 每个 skill 有 `version`、`parent_version`、`approved_by`；
- 失败有结构化 `error_code`，不是一句“失败了”。

---

## 4. 成功/失败如何影响心情

不要写死“成功=开心”。  
把 skill 结果当成一条**事件记忆**，走同一套评价：

```text
skill outcome memory:
  "用 sync_surfcore v1 完成同步，新增 5 条，耗时 0.3s"

appraisal:
  self_efficacy ↑
  processing_fluency ↑
  unresolved ↓
  valence 略正
```

失败：

```text
"sync_surfcore v1 连续 3 次超时"

appraisal:
  self_efficacy ↓
  unresolved ↑
  caution ↑
```

然后由 `affect` / `P` 自然吸收。  
这样“技能有效提高自信”不是奖励函数，而是记忆评价的结果。

---

## 5. 失败 → 主动提出改进请求

当同一 skill 在窗口内失败次数/错误率超过阈值：

```json
{
  "type": "skill_improvement_request",
  "skill_id": "memory.sync_surfcore",
  "current_version": 1,
  "failures": 3,
  "last_error": "timeout",
  "evidence_ids": ["skillrun:..."],
  "requested_by": "local",
  "status": "pending"
}
```

本地只提出请求，不自动改 skill。  
高性能 API 收到后：

1. 读失败 trace / 输入输出 / 现有 manifest；
2. 起草 `v2` 候选（DSL 或新执行器提案）；
3. 附带回滚点和测试用例；
4. 交给用户批准；
5. 本地跑回归测试；
6. 通过后安装为 `v2`，保留 `v1`。

---

## 6. 什么才算“学习”

不是模型权重变了，也不是本地模型自己改了代码。  
在本项目里，“学习”是：

> **经过用户批准、带版本、可回滚、通过回归测试的程序性记忆更新。**

记录：

- `parent_version`
- `diff`
- `tests`
- `approved_by`
- `learned_at`
- `rollback_to`

这更接近人：学到的是“做法”，不是把大脑重写。

---

## 7. 和 DSH Skill 的关系

- DSH Skill 给表层意识用；
- 本地 Skill 给潜意识执行层用；
- 高性能 API 可以同时：
  - 读 DSH Skill 来写更好的候选本地 Skill；
  - 读本地 Skill 的失败 trace 来提出改进；
- 两者不混用：本地不直接执行 markdown 指令，DSH 不直接执行本地代码。

---

## 8. 分阶段

### Phase A（现在可做）

- skill registry（id/version/executor/success）；
- 规则路由 + 本地模型歧义路由；
- skill outcome -> 事件记忆 -> 评价；
- 失败计数 + `skill_improvement_request` 记录。

### Phase B

- 用户批准界面；
- 候选 skill 的回归测试；
- 版本回滚。

### Phase C

- 高性能 API 起草候选 skill；
- 本地只读 trace，不自动安装；
- 技能统计进入 P/affect。

---

## 9. 安全边界

- 本地模型不能写文件、不能执行任意命令、不能安装 skill；
- skill 执行器白名单；
- 所有参数 schema 校验；
- 所有网络/文件操作有 scope；
- 改进请求必须用户批准；
- 失败不能触发无限重试或自责循环；
- 不把“技能失败”解释成临床意义上的抑郁/创伤。
