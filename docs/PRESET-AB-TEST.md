# Preset A/B 测试模式

## 不关整个 SoulCore

只关“注入层”：

```json
{
  "qq": true,
  "pet": false,
  "bili": false,
  "l2": true,
  "inject": false,
  "memory_prompt": false
}
```

效果：

- `inject=false`：不注入 SoulCore context、skill manifest、episode cards；
- `memory_prompt=false`：不注入原记忆卡；
- 插件仍加载，`soulcore_memory` 仍可查询；
- 因此能单独测 preset，不被记忆/技能清单干扰。

改完必须：

1. 重启桥接（读 capability）；
2. 清空/归档当前 QQ 会话（新会话才重新组装 prompt）；
3. 发测试消息。

恢复：

```json
"inject": true,
"memory_prompt": true
```

## 已发现的运行时事实

- 2026-10-31 新会话测试：`skill-manifest` 已出现在 DSH session prompt 中（解码日志可检索到“可用技能（本会话只加载一次”）。
- 同一次会话没有 L2 事件卡，按设计回退原记忆卡。
- 源码 preset 已从 10,502 字符裁到 9,087 字符，但**已运行 DSH 的新会话仍使用启动时缓存的旧 preset**；session prompt 里仍能检索到被删的“学习群友策略/群管家/发语音”等段落。
- 因此 preset 裁剪必须重启 DSH（不是只重启桥接）才生效；不能只凭源码文件判断。

## 如果要彻底关 SoulCore

不推荐用于 A/B，因为会把记忆工具也关掉。  
真的要做 stock baseline，才：

```text
plugin_manager set_plugin include:soul-bridge false
```

并把 `episode-cards.md`、`skill-manifest.md` 移走。

## Preset 拆分测试顺序

1. 备份当前 `qq-chat-v2`（控制台/API 已有备份）。
2. 只减少低频率说明：图片、语音、转发、拍一拍、收藏。
3. 保留：安全规则、工具协议、发送/引用、睡眠/收尾、群聊主体性。
4. 用 `inject=false` 跑 3~5 条测试消息。
5. 对比：回复质量、工具错误、`cacheHit`。
6. 通过后再恢复 `inject=true` 做集成测试。
