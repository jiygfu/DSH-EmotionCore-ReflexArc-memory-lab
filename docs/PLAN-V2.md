# EmotionCore / SoulCore 计划 v2（讨论稿）

## 执行状态（2026-10-31）

- P0 余额：已接通 DeepSeek `/user/balance`；当前余额 11.46 CNY，今日已用 0.147。
- P0 记忆同步：已修复 full-card fallback；同步 426 条，426 条评价。
- P1 episode importance：已从 appraisal 派生，不再全为 0；L2 卡片已重建。
- P1 查询相关性：尚未接，当前按 importance/recency 排序。
- P2 身体→目的：已接 `purpose_seed`，只调制 drives/pending_chance，不写 P。
- P4 preset 行为回归：待真实聊天验证。
- P3 2B 定位：已按“只做摘要/标签/重排”执行。

## 一、今天实际改变了什么

### 已完成

| 项 | 现状 |
|---|---|
| 记忆同步 | 修复 `memory-inbox.jsonl` 缺失时的 full-card fallback；`daily` 同步上限 500 |
| 记忆数量 | 426 条原始记忆，未删除 |
| 评价 | 426 条全部有 appraisal；386 code-v1，40 AI |
| 事件层 | 68 个 episodes：10-29 31、10-30 22、10-31 15 |
| L2 注入 | 运行时确认 prompt 使用 `事件索引（L2）`，原记忆卡不再注入 |
| preset | 10,502 → 9,087 字符；旧章节运行时已消失；备份与回滚脚本存在 |
| 会话预算 | `tool-result-pruner` / `compaction-basic` active；手动/自动阈值已接 |
| 本地 2B | 摘要可用；情绪评价不可靠；confidence 几乎固定 0.7 |
| 余额 | `dsh-whale-widget 0.4.2` 已安装，但页面未刷新，`.dshw-usage.json` 尚未生成 |
| 睡眠晚安 | 已开启，尚未实际触发 |

### 仍然只是“半成品”的部分

1. **L2 不是查询相关的**
   - 现在按 `importance DESC, start_at DESC` 选 5 张卡；
   - 但同步进来的记忆 `importance=0`，所以实际几乎按时间选；
   - 没有根据当前消息做相关性排序。

2. **事件卡的 importance / felt 质量有限**
   - 426 条中 386 条是 code-v1；
   - episode importance 直接取 memory importance，当前基本为 0；
   - 事件卡能看，但不是“重要事件优先”。

3. **身体状态没有接进 P / 目的**
   - 当前只注入 surface hint；
   - 不写 P、不写 memories、不写 daily baseline；
   - 原计划里的“身体压力影响行为”没有实现。

4. **余额监控还没真正产生数据**
   - widget 已安装；
   - 当前 `body-state.json` 仍是 `balance:null`；
   - 需要刷新页面，或补 DSH 账号余额 fallback。

5. **preset 裁剪后的行为只测了 bootstrap**
   - 没有真实聊天回归；
   - 低频率章节删了，行为质量未知。

## 二、重写后的原则

```text
1. 原始记忆永远保留，L2 只是索引。
2. 固定程序优先；2B 只做低风险辅助。
3. 身体状态只做“短期压力”，不直接改写长期人格。
4. 任何裁剪都必须能回滚、能对比。
5. 不用“更多 prompt”解决上下文问题。
```

## 三、计划结构

### P0：把监控与记忆新鲜度收口

- 刷新页面，确认 `.dshw-usage.json` 生成；
- `body-state` 读到 balance / today_usage；
- 如果 widget 仍不写，补 DSH 账号余额 fallback；
- `daily` 每次固定同步 500 条，避免再次出现“39 条”；
- 检查 `episode-cards` 是否只包含当天，避免旧卡注入。

验收：

```text
balance 非 null
daily 后 memories 数不下降
L2 卡片日期正确
```

### P1：L2 从“最近”改成“相关 + 重要”

- episode importance 改为：
  ```text
  importance = max(
    code/appraisal 的 |delta| 和 unresolved,
    memory importance,
    情绪强度
  )
  ```
- 增加当前消息相关性：
  ```text
  score = 0.35*relevance + 0.25*importance + 0.20*recency
        + 0.10*abs(affect) + 0.10*unresolved
  ```
- 只取 top 3–5，低于阈值返回空；
- 不做随机；
- 没有相关卡时回退原记忆卡。

验收：

```text
同一句“你还记得昨晚吗”能召回昨晚事件
无关闲聊不强行塞旧事件
L2 注入不超过 1.5k 字符
```

### P2：身体状态 → 目的调制（不是直接改 P）

推荐方案：

```text
body_state
→ 临时 body_pressure
→ 只调制 purpose seed / 主动性 / 回复长度
→ 会话结束即失效
```

映射：

```text
stress / thermal / cognitive_load 高 → 降低主动分享、缩短回复
fatigue / sleepiness 高             → 降低主动频率
resource_need 高                    → 少烧 token、先询问
recovery 高                         → 恢复正常分享
```

不做：

- 不直接用设备值覆盖 P；
- 不写 memories；
- 不写 daily baseline；
- 不把“电量低”说成人类疲劳。

可选的第二阶段：低权重 P 偏移（0.02–0.05），但需要单独 A/B；默认不做。

验收：

```text
余额低时，主动搭话/长回复减少
恢复后行为回到基线
P 没有因 body_state 被改写
```

### P3：本地 2B 的岗位重新定义

保留：

- episode 摘要；
- 标签/关键词；
- 候选重排；
- 失败可回退的润色。

取消：

- 不作为唯一 appraisal；
- 不用固定 confidence 0.7 升权；
- 不用它决定“有没有技能/要不要注入”。

评价策略：

```text
code-v1 主评分
→ 高影响/高不确定才升级
→ 2B 只做草稿
→ 云端或更大本地模型做复核（可选）
```

验收：

```text
AI 评价有质量门
confidence 不再恒定
失败不产生批量 owner 问题
```

### P4：preset 行为回归

- 保留当前 9,087 版本；
- 用 3–5 条真实消息测试：普通聊天、图片、引用、表情、收尾；
- 观察是否变笨、变客服、漏工具；
- 不行就还原备份；
- 通过后再考虑继续裁。

验收：

```text
不出现明显客服腔
引用/表情/收尾仍正常
token 不回升
```

### P5：预算与运维

- 自动 session 阈值继续开；
- `daily` 同步 500；
- appraise 批量用 code-only，AI 只做定向；
- 睡眠晚安仍可选；
- 每周检查一次 backlog。

## 四、执行顺序

```text
P0 余额 + 记忆新鲜度
P1 L2 相关性/重要性
P2 身体→目的调制
P3 2B 质量门
P4 preset 行为回归
P5 预算运维
```

先做 P0/P1，因为它们直接决定“记忆优化是否真的有效”。  
P2 是昨晚真正想做但没做的“硅基身体”，建议单独一轮，不要和 memory/preset 混在一起。

## 五、需要你拍板

### 决策 1：身体状态影响哪里？

- A（推荐）：只调制 purpose/主动性/回复长度，不写 P；
- B：低权重 P 偏移，持久影响人格；
- C：只做 surface hint，保持现状。

### 决策 2：本地 2B 的定位？

- A（推荐）：只做摘要/标签/重排；
- B：继续做 appraisal，但加质量门；
- C：换更大本地模型或云端做高影响评价。

### 决策 3：preset 是否继续裁？

- A（推荐）：先跑行为回归，不再裁；
- B：继续裁到 7k 左右；
- C：恢复部分被删章节。

## 六、一句话

今天的成果是“记忆层和 preset 层真正开始工作”；  
昨晚没完成的是“身体压力真正影响行为”。  
v2 计划先保证记忆索引正确，再把身体压力接到目的层，最后才继续动 preset。
