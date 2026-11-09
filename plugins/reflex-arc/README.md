# ReflexArc

独立反射弧子插件，挂载在：

```text
<dsh-onebot-qq>/plugins/reflex-arc/index.js
```

当前部署：

```text
~/.dsh/plugins/dsh-onebot-qq-yu/plugins/reflex-arc/
```

## 当前能力

- **骰子指令通道**（`.r` / `.ra`）：本地直接回，**不叫模型、0 token**，随机数进不了模型上下文
- 本地骰子意图：`掷个骰子` / `r d100` 这类口语 → `[反射弧/骰]` 一行注入本轮
- 骰子回执：模型报的数字和本地不一致 → 下一轮 `【反射弧回执】` 点出来
- **长图本地粗看**：收到的截图又长又大时，先在本地 OCR 出文字，
  只把文字以 `【反射弧/粗看】` 注入本轮，**原图不发给模型**（见下方 token 账）
- 模型要图：`mcp__qq__ec(action="look")` 把 QQ 默认画质那张回灌进下一轮
- 夜间静默（可选）：静默期内不主动接话
- **不注册任何模型工具**
- 不调用模型，不产生额外 token（OCR / 骰子都在本机）

## 骰子指令（dice-command.js）

移植自 `surfcore/src/dice-command.js`，挂在 `intercept`（order 10，斜杠命令之后、门禁之前）：

```text
.r / 。r / !r / 掷 / 骰              默认骰（diceCommandDefault，默认 1d6）
.r 3d6+2                             多骰加值
.r 3#1d6                             重复 3 次
.r 1d100<=60                         比较判定
.ra 侦查 60 / .ra 60                 COC 7 版检定（大成功/极难/困难/常规/失败/大失败）
```

为什么值得单独开一条通道：随机数一旦进了模型上下文，它就有机会照着这个数编一段。
命令通道直接 `bot.deliver()` + `ev.stopped = true`，模型根本不知道这次掷了什么，也就没法作弊；
同时省掉一整轮模型调用。

**回执**：模型在这轮里自己报了个不一致的数字（例如 `1d100 = 99` 而本地是 29），
出站后用 `findDiceClaimMismatch` 抓出来，下一轮注入
`【反射弧回执】上一轮本地掷的是「…」，你报成了「…」；本地结果优先`。

## 迁移对照（surfcore → onebot）

| 能力 | surfcore | 本插件 | 状态 |
|---|---|---|---|
| 骰子意图识别 `detectDiceIntent` | `src/reflex.js` | `reflex-core.js` | 已移植 |
| 骰子执行 `rollDice` | `src/dice.js` | `reflex-core.js` | 已移植 |
| **骰子指令通道** `runDiceCommand` | `src/dice-command.js` | `dice-command.js` | **本次补回** |
| **骰子回执** `findDiceClaimMismatch` | `src/reflex.js` | 早已移植但**从未调用** | **本次接线** |
| 夜间静默 `inQuietHours` | `src/reflex.js` | 早已移植但**从未调用** | **本次接线（默认关）** |
| 注入筛选 `screenClaim` | `src/reflex.js` | 早已移植但**从未调用** | **本次接进 memory-lab** |
| 长图 OCR | `soulcore/long_image.py` | 内联 OCR 脚本 | 上次补回 |
| 本地视觉摘要 | 多模态直发 | `analyzeOneImage` | 在（默认关，一张 24 秒） |
| 人物印象 | — | `injectFirstContactImpression` | 在（线上 11 次命中） |
| memory-lab 联想 | surfcore 无此功能 | `injectMemoryLabHint` | 在（默认关） |

`inQuietHours` / `screenClaim` / `findDiceClaimMismatch` 这三个属于「代码移植过来了但没人调用」——
功能上等于不存在，这次一并接上。

## 长图粗看（coarseVision）

### 为什么必须晚于内核

内核在 `before-turn` 的 **order 50** 才把图片下载/缩图成 `ev.imageParts` + `ev.imagePaths`。
本插件的全局 order 是 36，钩子如果按默认顺序跑，这时候两个数组都还是空的 —— 这就是
「功能明明写了却从来不动」的原因。所以粗看钩子显式注册为 **order 60**：

```js
onBefore('before-turn', fn, { order: 60 })
```

### 判定与产出

- 判定：`高/宽 ≥ coarseVisionLongRatio/100`（默认 2.5）或 `宽×高 > coarseVisionPixels`
- 处理：切 1600px 高的块（最多 `coarseVisionMaxTiles` 块）丢给 rapidocr，
  行内去重（块间 160px 重叠会重复），按 `coarseVisionMaxChars` 截断
- 结果：`ev.hint` 里加一段 `【反射弧/粗看】…`，并把对应 `ev.imageParts` 摘掉

### 失败即退回

python 缺失 / 没装 rapidocr / 超时 / 没读到字 → **保留原图**，只在日志里留一行 warn。
也就是说：粗看只可能在「确实读到了字」时才省图，不会出现模型什么都看不到的情况。

### 模型要「看一眼」怎么办

被粗看摘掉的那张图（**QQ 默认画质，不是原图**）会留在内存里 10 分钟，按会话索引。
模型想要画面时调用：

```text
mcp__qq__ec(action="look")
```

反射弧内部（`bot.shared.lookAtImage`）把它作为图片块回灌到下一轮：

```js
const sid = await bot.dsh.ensureSession(chatKey)
await bot.dsh.prompt(sid, '（反射弧回灌）…', [{ mediaType, data, name: 'qq-image' }])
```

- 不重下 QQ 原图、不新增任何工具（`ec` 本来就是 QQ 线唯一工具）
- 同一张图只回灌一次；过期 / 已看过 → 返回 `{ok:false,error}`，模型自己会改用文字回答
- 代价：这一轮多 ~986 tokens（只有真要图时才花）

### 依赖

`rapidocr_onnxruntime`（装到 DSH 运行时 python 里即可，约 100MB）：

```powershell
& "$env:USERPROFILE\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" `
  -m pip install rapidocr_onnxruntime
```

python 路径可用 `coarseVisionPython` 覆盖（留空自动找 DSH 运行时 → 系统 python）。

### 延迟

每块约 3 秒；4 块 ≈ 13 秒（含模型加载）。长图消息会因此慢十几秒。

### token 账

| 图 | 原图 token | 粗看后 | 差 |
|---|---:|---:|---:|
| 1080×1920 手机截图 | 986 | 400–600（按字算） | −40% |
| 1080×6000 长图 | 1,010 | 800（截断上限） | −20% |
| 小图 / 表情（不触发） | 184–206 | 不变 | 0 |

省 token 不是主要收益：**长图被压到 1024 token 上限后模型本来就基本读不出字**，
OCR 给的是准确、可引用的原文。要更省就把 `coarseVisionMaxChars` 调到 400。

## 后续扩展点

```text
before-turn:
  表情联想
  EmotionCore 记忆指针
  跨群身份提示

after-turn:
  发话回执
  本地结果是否被使用
  反思队列
```

## 配置

`pluginConfig['reflex-arc']`：

```json
{
  "enabled": true,
  "maxDice": 100,
  "maxCount": 10,
  "diceCommand": true,
  "diceCommandDefault": "1d6",
  "diceCommandMaxDice": 20,
  "diceCommandMaxSides": 1000,
  "diceCommandMaxRepeat": 10,
  "diceIntent": true,
  "diceReceipt": true,
  "impressionEnabled": true,
  "emotionCoreUrl": "http://127.0.0.1:8765",
  "impressionTimeoutMs": 1500,
  "visionModel": "huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M",
  "localVision": false,
  "visionTimeoutMs": 20000,
  "memoryLabEnabled": false,
  "memoryLabUrl": "http://127.0.0.1:8766",
  "memoryLabTimeoutMs": 250,
  "quietHours": "",
  "quietHoursEnabled": false,
  "coarseVision": true,
  "coarseVisionKeepOriginal": false,
  "coarseLookBack": true,
  "coarseVisionLongRatio": 250,
  "coarseVisionPixels": 4000000,
  "coarseVisionMaxChars": 800,
  "coarseVisionTimeoutMs": 60000,
  "coarseVisionMaxTiles": 4,
  "coarseVisionPython": ""
}
```

### 开关一览（每个功能都能单独勾掉）

| 开关 | 默认 | 关掉之后 |
|---|---|---|
| `enabled` | 开 | 整个反射弧停摆 |
| `diceCommand` | 开 | `.r` / `.ra` 不再本地直回（走模型那条老路） |
| `diceIntent` | 开 | 口语「掷个骰子」不再注入 `[反射弧/骰]` |
| `diceReceipt` | 开 | 不报「上次掷了什么」、不点模型改数字 |
| `impressionEnabled` | 开 | 不再请求 8765 取人物印象 |
| `localVision` | **关** | 不再调本地 qwen3-vl 出图描述 |
| `memoryLabEnabled` | **关** | 不再请求 8766 做记忆联想 |
| `coarseVision` | 开 | 长图不再本地 OCR，原图照发 |
| `coarseLookBack` | 开 | `ec look` 拒绝回灌，只给 OCR 文字 |
| `quietHoursEnabled` | **关** | 夜间照常主动接话（勾上才按 `quietHours` 静默） |

控制台位置：**设置 → 反射弧**，子标签 **基础**（19 项）和 **长图粗看**（9 项）；
夜间静默在 **总览** 页。改完热生效；改插件代码才需要重启 DSH。

## 测试

```bash
node --test test/reflex.test.mjs
```
