# EmotionCore 版本与兼容性基线

> **历史文档 / Legacy**：文中旧仓库链接和 SurfCore 兼容性属于 v0.3.1 时期；
> 当前新仓库为 OneBot-only，不依赖 SurfCore。

时间：2026-11-02
目的：区分 GitHub 稳定快照与本地 L5 WIP，避免把未完成的 L5 当成 v0.3.1 正式语义。

## 1. GitHub 事实

### v0.3.0

```text
tag:    v0.3.0
commit: e303e089ede25a19e45107b4595a76f93d316750
日期:   2026-10-31
```

GitHub tag 页面：

https://github.com/jiygfu/EmotionCoreForDSH-surfcore/tree/v0.3.0

`v0.3.0` 的 CHANGELOG 明确包含：

```text
FTS5
source_kind/status/version/valid_from/...
correction 版本链
事件索引 + 原始记忆 ID
sleep_runs
handoff
L2 静态卡
```

所以 v0.3.0 **不是只有 L0–L2**。

`v0.3.0` 已有：

```text
soulcore/handoff.py
soulcore/episodes.py
soulcore/context_render.py
```

其中 `context_render.py` 原文：

```text
This file is prepared for a future SurfCore prompt seam.
It is not injected into SurfCore yet...
```

即：

```text
v0.3.0 已有 handoff/L2 代码
context_render 只是准备好，未注入
```

### v0.3.1

```text
tag:    v0.3.1
commit: d1ea88856c6c0190a7871266f2d54d071dafe862
日期:   2026-11-01
```

GitHub compare：

https://github.com/jiygfu/EmotionCoreForDSH-surfcore/compare/v0.3.0...v0.3.1

只有 13 个文件，主要是：

```text
CHANGELOG
LICENSE
README
SECURITY
THIRD_PARTY_NOTICES
VERSION
docs/SETTINGS-UI
plugins/soul-bridge
plugins/soulcore-settings
soulcore/balance.py
```

没有：

```text
context_render.py
handoff.py
episodes.py
people.py
docs/LAYERS.md
```

所以：

```text
v0.3.1 = MIT 许可证 + 安全加固
v0.3.1 ≠ L5 版本
```

### GitHub main

GitHub main 的 CHANGELOG 仍停在 v0.3.1；`docs/LAYERS.md` 返回 404：

https://github.com/jiygfu/EmotionCoreForDSH-surfcore/tree/main

说明 L5 文档与 L5 代码只存在于本地 WIP，没有推到 GitHub main。

## 2. 本地 L5 的真实来源

本地 commit：

```text
42649c9 WIP: preserve M4/M5/M6 memory-chain work before repair
2026-11-01 16:55
```

它才加入：

```text
docs/LAYERS.md
docs/PLAN.md
context_render 改动
handoff/episodes/people_card/patience 改动
```

随后：

```text
b784c5e Fix memory pipeline
4f77e96 Fix farewell owner config fallback
```

所以：

```text
L5 = v0.3.1 之后的本地 WIP
不是 v0.3.1 发布内容
也不是 GitHub 稳定快照
```

## 3. 兼容性基线

### 必须遵守

```text
GitHub v0.3.0 的表结构 = 稳定数据契约
GitHub v0.3.1 = 安全/许可证补丁
本地 L5 = 只读投影/WIP
```

### 禁止

```text
1. 不把 L5 当作 v0.3.1 正式语义
2. 不让 L5 新增持久化真相
3. 不用 L5 改写 v0.3.0 的 memories/episodes/people 所有权
4. 不向 API 承诺“记忆都能查”
5. 不在没有兼容测试前把 WIP 推成正式 tag
```

## 4. 记忆与角色卡契约

稳定人格原文：

```text
你对自己的记忆不是全知的：
一次查询只能看到有限条；
被问到很久以前或大量细节时，先查、查到多少说多少；
查不到、被截断或不记得，就承认，不要用想象补洞。
```

`【最后几条】`：

```text
本地记忆库是连续性的底座；窗口清空不等于记忆消失，查得到。
L2 事件卡只是索引，不是全部；不确定就查，不要用想象补。
私聊和群聊共用同一套长期记忆。
连续性由本地库维持，不需要靠宣告证明。
```

正确解释：

```text
可查 ≠ 全知
连续 ≠ 全部记得
```

禁止把它扩写成：

```text
所有记忆都能查
```

否则和“有限条/可能截断”的实现冲突，API 会产生怀疑或补洞。

## 5. 当前推荐的运行时规则

```text
L5：
  只读投影
  按当前消息检索最多 2 条 L2
  首次唤醒才注入 handoff
  不承诺全知

soulcore_memory：
  只保留 today/search/person/range
  默认不暴露 overview
  p/questions/resolve/surfcore 不进入 QQ 工具面
  overview 作为设置页调试项，默认关闭

角色卡：
  保留“不全知、有限条、查不到承认”
```

## 6. 待做的兼容测试

```text
1. 复制 v0.3.0 的 SQLite DB
2. 用当前 EmotionCore /context 跑只读测试
3. 确认不依赖 post-v0.3.1 才有的表/列
4. 确认 handoff 仍能生成
5. 确认 episodes/people 读取不报错
6. 再把 L5 标成“可用”而不是“稳定”
```

## 7. 结论

```text
GitHub v0.3.0：稳定公开快照，已有 handoff/L2，context_render 未注入
GitHub v0.3.1：安全/许可证补丁，没有 L5
本地 42649c9+：L5 WIP，不完整，未上 GitHub
```

后续所有 L5 改动都应视为 **WIP 投影层**，不得反向污染 v0.3.0 稳定数据契约。
