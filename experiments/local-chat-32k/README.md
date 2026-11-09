# Local Chat 32k

独立本地聊天页：IQ2_XXS + 32k 上下文。

## 启动

```powershell
cd <仓库根>\experiments\local-chat-32k
node server.mjs
```

打开：

```text
http://127.0.0.1:8790
```

## 注入内容

- 人格：`config/emotioncore-persona.md`
- 记忆：`memory-lab /recall` 的 1–2 条结果，格式仿 reflex-arc 的
  `[记忆联想·实验｜时间·人物·位置·事实/看法]`
- 触发词：`上次 / 那次 / 之前 / 后来 / 记得 / 还记得 / 那个 / 那件事 / 后来呢 / 记忆 / 以前`
- 不注入 L5 事件索引、人物卡、身体状态、handoff 或工具定义

## 模型参数

```text
model: deepseek-v4-pro-qwen3.5-9b-heretic:iq2_xxs
num_ctx: 32768
think: false
num_predict: 256
temperature: 0.55
repeat_penalty: 1.1
keep_alive: 5m
```

## 注意

- 这是实验页，不是 QQ 通道。
- 32k 下 IQ2 约 3–4 tok/s，长回答会慢，且低比特模型可能重复或跑偏。
- 页面是流式输出，生成中可以继续看到字。
- 记忆联想只在触发词命中时查询，避免每轮都打 memory-lab。
