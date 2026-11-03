# Purpose 机制 × SoulCore 情绪种子

## 定位

SurfCore 的目的机制是唯一的主动执行器：

```text
素材 → 驱动 → 目标假设 → 选择 → 发送 → 回执
```

SoulCore 不复制调度/发送，只提供**当日情绪种子**。

## P 的正确语义

当前实现里：

- `personality.compute_p()` 是**长期累计 P**；
- `daily_summaries.baseline` 是**当日初始基准**；
- 目的机制读取后者，不用长期 P 直接覆盖当日状态。

这样：

- 当日 P 稳定，不会因为一条新对话立刻变；
- SurfCore 仍可用对话素材/目标置信度产生短期变化；
- 每天整理后，下一天的 baseline 重新捕获。

## 种子文件

默认：

```text
~/.dsh/surfcore/characters/<当前角色 id>/soulcore-purpose.json
```

当前角色 id 从 `character.json` 和 `current-role.json` 选出；  
不再写全局 `state/soulcore-purpose.json`。

由：

```text
python -m soulcore purpose-seed
```

写入，内容：

```json
{
  "schema": "soulcore.purpose.v1",
  "day_key": "2026-10-30",
  "p_source": "day_baseline",
  "p": { "...": 0.0 },
  "drives": { "connect": 0.0, "...": 0.0 },
  "emotion": "affectionate",
  "urgency": 0.43,
  "pending_chance": 0.39
}
```

## SurfCore 侧

`purpose-engine.js` 新增可选 `affectSeed`：

- `deriveDrives`：当日 drives 与种子 45% 混合，保留素材的短期变化；
- `appraiseMaterial`：无正负线索时用种子 emotion 作底色；
- `selectPurpose`：pending 优先级由 `pending_chance` 决定，不再固定 0.5；
- `planNextFire`：`urgency` 越高，间隔越短；没有种子仍用原随机间隔。

`bridge.js` 和 `pet-purpose.js` 都读同一个种子文件，当前载体互斥不变。

## 回退

以下情况完全回到旧行为：

- 文件不存在；
- schema 不匹配；
- `day_key` 不是今天；
- 超过 36 小时；
- `drives` 全是非法值。

## 性能

- 种子只读一个 JSON，不调用模型；
- 不增加 2B/云端回合；
- 只替代 SurfCore 内部的关键词情绪/固定先验。

## 注意

这是 SurfCore 上游修改，必须纳入 fork / patch 层；  
不要把它直接留在未提交的 main 上等下一次更新覆盖。
