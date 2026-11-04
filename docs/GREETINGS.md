# 作息问候

本地 worker 定时发送的早安/晚安消息。**不调用模型、不注入提示词、不占用对话上下文。**

## 配置

设置页 → EmotionCore → **作息问候**：

```text
morningGreetingEnabled   默认 true
morningGreetingTime      默认 08:30
morningGreetingText      默认「早，醒了。今天也慢慢来。」
nightGreetingEnabled     默认 true
nightGreetingTime        默认 23:00
nightGreetingText        默认「夜深了，我去睡了。晚安。」
```

设置写入 `data/soul-bridge-settings.json`。

## 发送规则

- worker 每 5 分钟检查一次；
- 到达时间后的 **2 小时窗口内** 发送一次；
- 过窗口不补发；
- 每类每天只发一次，状态写在 `data/greeting-state.json`；
- 发送到 OneBot 配置里的 `adminQq` 私聊；
- 通过 SnowLuma HTTP `/send_private_msg`；
- 发送失败只记日志，下一次检查重试；
- 不触发完整睡眠、不轮换会话、不写 P、不写记忆。

## 与睡眠的区别

```text
daily_cycle     记忆整理，04:00 左右；不告别、不问候
sleep           手动完整睡眠；告别/轮换属于旧 SurfCore 钩子
greeting        独立作息问候；只发消息，不做记忆整理
```

所以：

- 没有收到早安/晚安，不代表睡眠整理坏了；
- 睡眠整理看 `sleep_runs` / `consolidation_runs` / `handoff`；
- 问候看 `data/greeting-state.json` 和 worker 日志里的 `greeting` 行。
