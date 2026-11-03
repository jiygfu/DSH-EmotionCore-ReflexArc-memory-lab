# memory-lab（只读原型）

独立于 EmotionCore / L5 / ReflexArc 的多轴记忆召回实验。

## 它做什么

```text
1. 用现有 retrieval.search_memories 做 FTS/2-gram 基线
2. 从基线的 memory 出发
3. 沿 same_thread / same_person / emotion_near 扩展
4. 打印 baseline vs lab 的对比
```

## 它不做什么

```text
不写 soulcore.db
不写 memories / appraisals / people / P
不接 L5
不接 ReflexArc
不注册 QQ 工具
不安装为 DSH bundle
```

## 运行

```bash
python plugins/memory-lab/lab.py --query "潜意识 分层" --limit 6 --json
```

只读连接：

```text
file:<soulcore.db>?mode=ro
```

## 结果怎么看

```text
baseline_ids : 纯 FTS/2-gram 召回
lab_ids      : 多轴扩展后
expanded     : 只由 same_thread/same_person/emotion_near 带出的条目
overlap      : 两者重合数量
```

如果 lab 只是把同一个 thread 的相邻消息全部拉出来，说明扩展权重过高；
如果 lab 没有新增任何条目，说明边太弱。

## 下一步门槛

在接入任何主链之前，必须回答：

```text
多轴扩展是否比 FTS 更能回答“这件事后来怎样”
是否引入跨人/跨场景误联想
扩展后的注入条数是否仍受 1–2 条限制
```

未通过前，保持 sidecar，不启用。

## boundary.py

只读事件边界对比：

```bash
python plugins/memory-lab/boundary.py --json
```

比较当前 thread 分配与更严格的相邻 episode 规则，输出：

```text
current_merged
proposed_merged
current_only
proposed_only
```

当前结果（2026-11-02）：

```text
pairs 85
current_merged 22
proposed_merged 37
current_only 1
proposed_only 16
```

说明当前启发式还不足以替换 thread_model；需要人工标注/更多特征后再改主链。

## boundary 初步评估

30 对初步样本（assistant 标注，不是生产真值）：

```text
current:  precision 0.714 / recall 0.556 / F1 0.625
proposed: precision 0.621 / recall 1.000 / F1 0.766
candidate gap<=6h & overlap>=0.05 & hard-end:
          precision 0.600 / recall 0.833 / F1 0.698
```

结论：

```text
没有规则在精度和召回上同时压倒当前方案
当前方案更保守，proposed 更容易合并
30 对样本不够，不能据此改 thread_model
```

下一步需要更多人工事件对，并明确产品偏好：宁可少合并，还是宁可多合并。

## 合并策略：recall-first，但不污染事实层

用户选择：宁可多合并，避免同一事件被拆开。

落地为三层，而不是直接把更多片段写成同一个 thread_id：

```text
hard            当前规则和候选规则都认为同一事件
soft_candidate  候选规则认为可能同一事件，但当前规则没合并
current_only    当前合并，但候选规则倾向拆开
separate        两者都不合并
```

约定：

```text
episodes.thread_id 只接受 hard
soft_candidate 只进入 memory-lab 的联想边
L5/结案/P/people 不读取 soft_candidate
```

这样召回可以先“多连”，事实层仍保持可回退。

## 功能词 / 内容串扰

新增：

```text
scope filter       群聊查询不混私聊，私聊查询不混群聊
meta score         统计功能/架构词
content mode       非 meta 查询不从高 meta 种子扩散
```

“群聊 记忆”这类查询仍可能命中“群聊功能/记忆系统”讨论。  
下一步需要正式的 `meta` / `content` 候选标记，而不是无限加关键词黑名单。

## meta/content v3

强 meta 词组优先；content 查询过滤 meta 候选；kind/meta_score 显示在评审表中。


## 可编辑 term 表

`lab_terms.py` 在自己的 `data/memory-lab.db` 里维护：

```text
lab_terms(
  term, kind, weight, action, enabled, note
)
```

`kind`：

```text
meta / entertainment / professional
```

`action`：

```text
penalty       内容查询中给功能词负权重
domain_penalty 查询意图与该域不匹配时给负权重
```

这是“负向词权重”，不是负向 embedding。  
以后可在 memory-lab 设置页加增删改；当前先用 SQL/文件维护。

人工评审只用于校准，不作为运行时流程。

## 设置入口

调试开关：

```text
plugins/memory-lab/config.json
  humanReview: false   # 默认关闭
  reviewLimit: 8
  reviewFile: ...
  termsFile: ...
```

对应设置页 schema：

```text
plugins/memory-lab/settings.schema.json
```

生成评审表（只在 humanReview=true 时）：

```bash
python plugins/memory-lab/lab.py --review
```

正常运行时保持 `humanReview=false`；人工评审只是校准工具，不是运行时依赖。

## 软边使用条件

soft_edge 只在这些查询下参与：

```text
上次 / 那次 / 之前 / 后来 / 接着 / 后续 / 然后 / 同一件 / 这件事 / 那件事
```

宽泛查询（如“群聊 记忆”）不启用 soft_edge，避免无关事件被带出。

## 本机只读 API

```bash
python plugins/memory-lab/server.py --port 8766
```

端点：

```text
GET  /health
GET  /recall?q=...&limit=6
GET  /terms
POST /terms                 修改 memory-lab 自己的 term 表
GET  /settings
POST /settings              修改 humanReview 等开关
GET  /edges                 查看 lab_edges
```

约束：

```text
soulcore.db 只读
term / settings 只写 memory-lab 自己的 DB/JSON
不注册 QQ 工具
不接 L5/ReflexArc
```

## ReflexArc 实验开关

```text
memoryLabEnabled: false   # 默认
memoryLabUrl: http://127.0.0.1:8766
memoryLabTimeoutMs: 250
```

开启后只在“上次/那次/记得/后来/那个”等线索出现时查询 `/recall`，最多注入一条 `[记忆联想·实验]`。失败不影响正常回复。

## embedding 状态

已加：

```text
lab_vectors.py
data/memory-lab.db.lab_embeddings
```

- 模型：`nomic-embed-text`
- 向量通道：RRF 的 `vector` 路，权重 0.8
- 没有模型/embedding 时自动跳过
- 下载曾卡在 44%，当前没有常驻拉取进程

## 向量通道

`lab_vectors.py` 已接入 RRF 的 `vector` 路，权重 0.8。

当前状态：

```text
nomic-embed-text 下载中（曾停顿，已恢复）
没有 embedding 时 vector 路自动为空
```

页面刷新后，settings.section 里应出现“记忆实验室”；设置页调用
`http://127.0.0.1:8766`。

## 向量实验结果

- 模型：nomic-embed-text
- 回填：861 条 / 768 维
- 结论：中文语义排序不可靠（“群聊 记忆” top 出现“斗地主”等）
- 决策：`vectorEnabled=false`，向量通道保留但默认关闭
- 候选替代：bge-m3 / 中文 embedding；未安装前不启用

## 3D 只读面板

`/graph?limit=160` 返回 thread 节点和边：

```text
节点：importance / unresolved / valence / arousal / participants
边：hard / soft_candidate / same_person
```

设置页里的“意识海 / CONSCIOUSNESS SEA（只读）”：

```text
深色星海 + 按日期分区的神经球
发光神经元 / 同人边 / 软边
沿边流动的突触脉冲
拖拽旋转、滚轮缩放、双击复位、悬停查看事件
边不参与写入，不决定 L5
```

当前（2026-11-03）：39 nodes / 561 edges / 6 day regions。
