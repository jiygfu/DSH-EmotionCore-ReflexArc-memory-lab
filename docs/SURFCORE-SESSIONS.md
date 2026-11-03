# SurfCore 会话与上下文

## 现状

SurfCore 给每个 QQ 会话维护一个持久 DSH session：

```text
<USERPROFILE>\surfcore\state\sessions.json
```

示例：

```json
{
  "sessions": {
    "private:<ownerQQ>": "session-...",
    "group:<groupQQ>": "session-..."
  }
}
```

- 桥接重启后继续复用同一个 session；
- DSH 的对话历史/上下文也跟着 session 保留；
- `ensureSession(key)` 只在没有映射时创建新会话。

## 清除上下文

现有控制台接口：

```text
GET  /api/sessions
POST /api/session/reset { "key": "private:<ownerQQ>" }
```

`session/reset` 会：

1. 删除 `sessions.json` 里的映射；
2. 停止并归档旧 DSH session；
3. 清理该会话的队列、pending、social 状态；
4. 下一条消息由 `ensureSession` 新建空上下文会话。

**记忆卡、sidecar、`soulcore-context.md` 不会被删除。**  
新会话仍然会读到当前记忆/人格上下文，但不会带昨天那串对话。

## 睡眠后轮换

`python -m soulcore sleep` / `daily` 在以下步骤完成后调用：

```text
baseline → appraisal → consolidate → finalize → export → purpose-seed
→ rotate-sessions
```

只轮换 SurfCore 管理的 QQ 会话：

- `private:<owner>`
- `group:<群号>`

不轮换：

- 当前 DSH Web GUI 会话；
- `pet-chat` 桌宠会话；
- `bili-whale` B站生物钟会话。

如果桥接没开，失败记录写到：

```text
<USERPROFILE>\.dsh\surfcore\session-rotate-pending.json
```

`soul-bridge` 下次启动会重试。

## 为什么不是“删历史”

旧 session 是**归档**，不是删除 DSH 记录；需要时仍可在 DSH 归档里查。  
新会话从空上下文开始，只通过记忆卡/当前 P/人物卡获得“昨天保留下来的东西”。

这正符合：

```text
睡眠清洗 = 只保留被记忆系统重新加权的东西
新会话 = 不继承昨天的短期上下文
```
