# EmotionCoreAdapter

`dsh-onebot-qq` 的独立适配子插件。它不修改 dsh-onebot 核心，只占用其
`plugins/emotioncore-adapter/` 扩展目录。

## 目标

```text
模型只看到 1 个极小的 ec 工具 + 几行动作说明
QQ 私聊/群聊/图片/表情/@/引用/身份/历史由本地 dispatcher 完成
EmotionCore 记忆通过本地 HTTP 注入，不再把完整记忆塞进 prompt
```

## 支持的动作

```text
send     发群聊/私聊文本
reply    引用回复
image    发图片（本地白名单路径或 URL）
sticker  发收藏表情
at       @ 指定 QQ 后发文本
user     查跨群身份缓存/群成员信息
history  拉群历史
recall   分层记忆查询；带 message_id 时才是撤回
groups   列群
```

`recall` 的三种形态：

```text
ec(action="recall", query="跑团")          → L3 事件索引
ec(action="recall", episode_id="ep_...")   → L3 事件详情
ec(action="recall", memory_id="...")       → L2 原始记忆
ec(action="recall", message_id=123)        → 撤回本群消息
```

工具 schema 只有：

```text
ec(action, target?, text?, path?, query?, qq?, message_id?,
   episode_id?, memory_id?, person?, date?, limit?, count?)
```

不是几十个 QQ schema；`toolAllowlist` 只保留 `ec` 时也不影响 recall。

## 部署

```text
<dsh-onebot-qq>/plugins/emotioncore-adapter/index.js
```

安装示例：

```text
<dsh-onebot-qq>/plugins/emotioncore-adapter/
```

`dsh-onebot-qq` 会自动发现 `plugins/*/index.js`。不需要改它的 `index.js`。

## 配置

`dsh-onebot-qq` 实例配置的 `pluginConfig['emotioncore-adapter']`：

```json
{
  "enabled": true,
  "emotionCoreUrl": "http://127.0.0.1:8765",
  "timeoutMs": 1500,
  "injectContext": true,
  "injectInstructions": true,
  "imageRoots": []
}
```

`emotionCoreUrl` 留空 = 不调用本地记忆服务，只保留 QQ 本地技能。

## EmotionCore 接口契约

`POST <emotionCoreUrl>/context`

请求：

```json
{
  "version": 1,
  "chatKey": "group:123",
  "isGroup": true,
  "groupId": 123,
  "sender": { "qq": 789, "name": "..." },
  "text": "...",
  "images": [],
  "replyToId": null
}
```

响应：

```json
{ "context": "L5 唤醒摘要，最多 1800 字" }
```

适配器会截断到 1800 字，超时静默跳过。每轮注入的内容包括：

```text
L5 自动唤醒：交接、L3 事件索引、L4 人物/情绪/耐心
不是 L2 原文；需要细节时模型应调用 ec recall
```

`localInstructions` 会明确提示：

```text
旧事/具体细节 → 先 ec(action="recall", query=...)
不要调用已下线的 soulcore_memory
```

`/context` 和 `/recall` 的每次调用都会写入
`data/memory-layer-calls.jsonl`，不是只记录旧的 `soulcore_memory`。

## 回写

出站成功后，适配器用 `bot.onAfterSend` 把本轮的 user/assistant 文本
写到 `POST /turn`。只有真正发到 QQ 才落库，模型没发出去不会记假账。

跨群身份默认落盘到：

```text
<dsh-onebot 数据目录>/emotioncore-identity.json
```

可用 `identityFile` 覆盖。

## 测试

```bash
node --test test/adapter.test.mjs
```

## 边界

- 不负责 dsh-onebot 的连接/唤醒/命令；那些由通道核心和 `gate-wake` 负责。
- 不直接读 EmotionCore 数据库；只通过本地 HTTP。
- 不把 EmotionCore 原始记忆正文注入 prompt，只注入短摘要。
