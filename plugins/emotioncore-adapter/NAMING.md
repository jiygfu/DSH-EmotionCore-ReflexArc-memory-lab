# EmotionCore 命名约定

## 规范名

```text
产品/系统：EmotionCore
适配插件：EmotionCoreAdapter
反射弧插件：ReflexArc
```

包/目录：

```text
emotioncore-adapter
reflex-arc
```

## 旧名兼容

`soulcore` 仍然作为**兼容别名**存在：

- 旧数据库：`data/soulcore.db`
- 旧环境变量：`SOULCORE_*`
- 旧插件：`@soulproject/soul-bridge`

这些不要立刻全局重命名。原因：

1. 现有 SQLite 表、JSON、路径、备份都以 soulcore 命名；
2. 一次性改名会造成历史数据不可读；
3. 先在新插件/API 层使用 EmotionCore 命名，再迁移数据。

## 迁移顺序

```text
1. 新代码/新插件只用 EmotionCore 命名
2. 环境变量读取：EMOTIONCORE_* 优先，SOULCORE_* 回退
3. 数据库：新增 emotioncore.db，从 soulcore.db 迁移/复制
4. 确认旧数据可读后，再改旧路径
5. 最后才移除 soulcore 别名
```

## 禁止

- 不要删除 `soulcore.db`；
- 不要在没有备份时重命名旧表/目录；
- 不要同时运行 `soulcore` 和 `emotioncore` 两套写入同一数据库。
