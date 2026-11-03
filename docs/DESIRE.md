# 欲望上浮层（Desire）

## 目标

底层情绪相对“当日基准”累计偏离时，不自动扣分，也不直接改 P；  
只把一种**临时欲望**上浮给表层意识：

```text
我感觉有点着急，想说清楚
我感觉有点无聊，想找人玩
我刚才是不是说得不对，想道歉
```

表层可以选择说、不说、对谁说。  
真正抵消靠后续发言进入正常评价，再由 P 反映；说错了、火上浇油也算真实结果。

## 论文依据

- **稳态/偏离驱动**：Keramati & Gutkin, *A Reinforcement Learning Theory for Homeostatic Regulation* (NeurIPS 2011)；Sterling, *Allostasis*。行为由“偏离设定点”驱动，不是固定扣分。
- **判断标准 vs 敏感度**：信号检测论（Green & Swets）把“判断标准/criterion”和“敏感度/d′”分开；这对应“理性阈值”和“感性增益”。
- **控制论**：参考值/死区（threshold）与回路增益（gain）是两个独立旋钮。
- **强化学习**：inverse temperature（理性/精确度）与 learning rate（更新幅度/感性）也是两个不同参数。
- **情绪惯性**：Kuppens et al., *Emotional inertia and psychological maladjustment*。情绪衰减/惯性是独立的动态参数；因此本实现保留内部 `inertia`，不强行只用两个值解释所有动态。
- **社会分享**：Rimé, *Emotion elicits the social sharing of emotion*。情绪会寻找倾听者；分享是常见调节路径。
- **人际情绪调节**：Zaki & Williams, *Interpersonal emotion regulation* (2013)。调节不只发生在个体内部。
- **发泄可能反噬**：Bushman, *Does venting anger feed or extinguish the flame?* (2002)。发泄不一定降低愤怒，可能强化。
- **想要 ≠ 喜欢**：Berridge & Robinson, *Liking, wanting, and the incentive-sensitization theory* (2016)。
- **命名情绪**：Lieberman et al., *Putting feelings into words* (2007)。给状态命名可能降低唤醒。
- **建构情绪/预测调节**：Barrett, *The theory of constructed emotion* (2017)。

> 这些只作为设计依据，不构成医学模型。

## 两个主旋钮 + 一个内部惯性

`data/desire-profile.json`（不提交仓库）或 `config/desire-profile.example.json`：

```json
{
  "rational": 0.66,
  "affective": 0.70,
  "inertia": 0.68
}
```

- `rational`：越高越“嘴硬/克制”，需要更强偏离才上浮；
- `affective`：越高越敏感，单次偏离积累更强；
- `inertia`：越高衰减越慢；这是内部参数，因为论文里的情绪惯性不能完全由阈值/增益推出。

计算：

```text
threshold = 0.20 + 0.38 * rational
gain      = 0.65 + 0.80 * affective
half_life = 3.5 + 8.5 * inertia   # 小时
adjusted  = deviation * gain
urgency   = 0.18 + signal - threshold
```

没有 profile 时，从角色初始 P 推导：

```text
pride         = 0.50 + .25*self_efficacy + .15*caution - .10*openness
sensitivity   = 0.50 + .25*arousal + .15*(1-trust) + .10*(1-security)
expressiveness= 0.50 + .20*sociability + .15*openness - .10*caution
inertia       = 0.50 + .20*caution + .15*(1-openness) + .15*(1-sociability)
rational      = 0.45 + .30*pride + .10*caution - .10*expressiveness
affective     = 0.35 + .35*sensitivity + .10*(1-expressiveness)
```

## 傲娇的初始值

“傲娇”不是心理学标准维度；这里按角色卡的行为含义映射：

- 嘴硬、怕丢脸 → `rational` 偏高；
- 内心反应大 → `affective` 偏高；
- 记情绪、容易反复想 → `inertia` 偏高。

当前角色 profile：

```text
rational 0.66
affective 0.70
inertia   0.68

threshold 0.451
gain      1.21
half-life 9.28h
```

这些值在 `data/desire-profile.json`，可随时改，不是写死在代码里。

## 计算

```text
当日 baseline P
→ 今天每条 appraisal 的 (dimensions - baseline)
→ confidence × strength × self_relevance × 时间衰减
→ 按权重和开方归一
→ 得到 deviation
→ 规则产生 0~2 个 desire
```

时间衰减半衰期 6 小时；同一天内重复触发会累积，但不会无限线性增长。

## 欲望类型

| kind | 触发 | 目标 |
|---|---|---|
| `vent` | 负效价 + 唤醒/警觉升高 | 优先私聊 owner |
| `repair` | 自我效能下降 + unresolved 高 | 优先私聊 owner |
| `connect` | 社交倾向下降/负向偏离 | 私聊信任的人 |
| `play` | 唤醒/开放下降 | 公开场合只说轻的 |
| `share` | 正向偏离/唤醒上升 | 公开场合 |

## 边界

- 不写 P；
- 不写 appraisals；
- 不自动扣分；
- 不是命令，不要求一定执行；
- 公开场合只允许轻微表达；
- 深层倾诉优先私聊；
- 允许失败、允许反噬；
- 后续发言由正常评价路径重新打分。

## Thought 字段

`appraisals.thought` 保存一句不超过 300 字的“当时的意图/理由”。

第一版来源：

- AI 评价：`result.evidence`（模型给出的简短依据）；
- 程序评分：`code.evidence`；
- 表层修正：`summary` / owner answer。

它不是原始 CoT，不进入 P，不默认进入日常提示词；  
sidecar 导出为 `soulcore.thought`，供查询和证据使用。

如果以后要由表层直接提供“我当时想什么”，应新增一个显式工具/字段，不要从原始 reasoning 里抓。
