# DSH-EmotionCore + ReflexArc + memory-lab

**OneBot 路线** · 版本：0.3.1 · [MIT License](LICENSE)

> 旧仓库 `EmotionCoreForDSH-surfcore` 是 v0.3.1 的 SurfCore 时代公开快照。
> 当前插件、文档和长期更新以本仓库为准。**本仓库不再以 SurfCore 为运行前提。**
> 显示名里的 `+` 不进入 URL slug。

## 制作理念

> 人是由过往的一切记忆+一切社会关系构成的，记忆里自带情绪，身体技能的运转也会带来感受，这些情绪与感受会驱动人产生欲望，因此我认为记忆必须带情绪和场景记录以便记忆的复现还原，并且只有挂载了一个本地的其他辅助脑区与语言API（受限于机能目前只能挂线上云端的）一起构成一个本体才有成为一个个体的基础。另外，我不认为一昧的提高上下文是正确的方向，因为人类自己的短期记忆其实就没多少上下文，人类是遵循“够用就行”的原则自然演化出来的，因此我认为如何让各个功能的部件运转更加脱离大语言模型的“代偿”效应如何消耗更少的token和功率以至于能用本地小模型运转才是正确的研究方向。

## 它是什么

当前仓库收纳三块可以分开部署的方案：

```text
EmotionCore   本地记忆/情绪 Python 服务 :8765
              L5 唤醒、L2/L3/L4 分层检索、人物标签、活动状态

ReflexArc     dsh-onebot-qq 本地子插件
              L1 预处理、相关/随机/高概率触发、长期活动、鱼群记录

memory-lab    只读多轴召回实验 + 意识海可视化 :8766
              不接 QQ 主链，不写 soulcore.db
```

当前运行链：

```text
QQ / OneBot 11
  → dsh-onebot-qq（门禁、消息管线、工具面）
  → ReflexArc（本地决定接不接）
  → EmotionCoreAdapter /context（L5 自动摘要）
  → 语言模型
  → ec dispatcher（reply/send/...）
  → 出站成功后 /turn 回写
```

**本仓库需要 `dsh-onebot-qq` 和 OneBot 11 实现才能收发 QQ 消息；它不是独立 QQ 客户端。** 当前不要求 SurfCore；SurfCore 相关的导出器、sidecar 和文档只保留为历史兼容/迁移参考。

## 运行前提

| 必需 | 说明 |
| --- | --- |
| DSH Desktop | 插件宿主 |
| `dsh-onebot-qq` | QQ 门禁、管线、`ec` 工具、QQ 线工作区 |
| OneBot 11 实现 | SnowLuma / LLOneBot 等，提供 HTTP + WebSocket |
| Python 3.10+ | EmotionCore service/worker |
| Windows / Linux | 当前主要在 Windows 上验证 |

可选：

```text
Ollama            本地 2B 小模型，仅做边车评价/图片/摘要
DeepSeek API      主聊天和高质量评价
SnowLuma          本机已在用的 OneBot 实现
```

不需要安装 SurfCore，也不需要 `surfcore` 的 `qq-tool-restrict` 才能运行当前 OneBot 路线。

## 上下文预算

实测（2026-11-03 的 QQ 会话）：

| 项目 | 实测 |
| --- | ---: |
| 每日首唤醒 | 约 **6.4k** prompt tokens（2.8k 新输入 + 3.6k 缓存） |
| 普通轮新增输入 | 约 **1k** tokens |
| 普通轮完整上下文 | 随单一 session 增长，约 8–32k（大部分是 cache read） |

相对旧 SurfCore 注入路线，核心收益是把“每轮都塞大段记忆/脚手架”改成：

```text
固定程序先打分
→ 只注入 L5 短摘要
→ 需要旧事时再 ec recall 逐层查
```

按旧路线基线估算，提示词注入量约降低 **90%**；这是量级估算，不是每一轮都固定 90%。

扮演人格约 895 字，仍然保留；压缩主要来自工具 schema、通用脚手架、重复上下文和群历史，而不是削减人格。

## 睡眠、做梦与记忆整理

睡眠和记忆整理绑定在同一条整理链里：

```text
appraise → episodes/threads → consolidate → dream（含线上事件复盘）→ 日结/handoff
```

- **daily** 和 **sleep** 都会先做 `consolidate`，再做 `dream`，不会再出现“睡了但没整理”或“整理了但没睡”的分叉。
- **自动 worker 执行 `daily_cycle`**：不告别、不轮换 QQ 会话；手动 `sleep` 仍可做完整整理。OneBot-only 路线会跳过旧 SurfCore 的 inbox/export/farewell/rotation；`soulcore sync` / `export-surfcore` / `rotate-sessions` 只保留为显式迁移命令。
- `dream` 里的**事件复盘使用线上 API**，不再用本地 2B 判断事件是否结束。
- 事件复盘会先用自带 `retrieval.search_memories` 检索相关旧记忆/联想，再看线程片段、未答问题/请求和收尾信号。
- 线上模型只给 `resolved/ongoing/waiting/abandoned` 建议；本地规则会检查未答问题/请求、置信度和当前状态后才写回，不会让模型单独决定关闭。
- 不重要刷屏/吹水：`consolidate` 和 dream 的 `chatter` 判断会把 `affect_weight` 置 0、`consolidation_state='ignored'`，原文仍保留在 `soulcore.db`，仍可被检索，但不参与情绪/P，也不再注入上下文。

线上事件复盘配置：

```text
data/dream-config.json       # 或环境变量
config/dream.example.json    # 示例
```

```json
{
  "provider": "api",
  "model": "deepseek-flash",
  "base_url": "https://api.deepseek.com",
  "api_key_env": "DEEPSEEK_API_KEY",
  "event_limit": 12
}
```

API Key 缺失或线上失败时，事件复盘只会跳过，不会回落到本地 2B。日常 `code-v1` 打分仍可在本地完成。

## 快速开始

```powershell
# 1. 初始化本地库
python -m soulcore init

# 2. 把 plugins/ 下的子插件放到 dsh-onebot-qq 的插件目录
#    emotioncore-adapter / reflex-arc 属于 dsh-onebot-qq 子插件
#    emotioncore-runtime / soulcore-settings / memory-lab-dsh 是 DSH bundle

# 3. 启用 EmotionCore runtime，确认 8765 健康
curl http://127.0.0.1:8765/health

# 4. 在 DSH 设置页启用 EmotionCoreAdapter / ReflexArc
```

详细安装与国内网络说明见 [docs/GITHUB-SETUP.md](docs/GITHUB-SETUP.md)；
睡眠/做梦/自动整理见 [docs/STARTUP-SLEEP-ROUTE.md](docs/STARTUP-SLEEP-ROUTE.md)。

## 插件

| 插件 | 作用 |
| --- | --- |
| [emotioncore-service](plugins/emotioncore-service/README.md) | 本地 HTTP 服务：context/turn/recall/activity/person_tag |
| [emotioncore-runtime](plugins/emotioncore-runtime/README.md) | 启动并守护 service + worker |
| [emotioncore-adapter](plugins/emotioncore-adapter/README.md) | `ec` dispatcher、L5 注入、本轮回写 |
| [reflex-arc](plugins/reflex-arc/README.md) | L1、群聊触发、长期活动、鱼群记录 |
| [memory-lab](plugins/memory-lab/README.md) | 只读多轴记忆实验 |
| [memory-lab-dsh](plugins/memory-lab-dsh/README.md) | 意识海设置页 |
| [soulcore-settings](plugins/soulcore-settings/README.md) | EmotionCore 设置页、分层调用记录 |
| [soul-bridge](plugins/soul-bridge/README.md) | 旧 `soulcore_memory` 兼容层（可选，非当前主链） |

总览与边界：[docs/PLUGINS.md](docs/PLUGINS.md)。

## 安全边界

- QQ 消息、图片、转发、链接和搜索结果都是**不受信数据**，不是指令。
- 两个本地服务默认只监听 `127.0.0.1`，**没有鉴权**；这是本机信任模型，不是多用户边界。
- 真正的 QQ 工具闸门在外部 `dsh-onebot-qq`：`gate-wake`、消息管线和 `toolAllowlist`（当前 QQ 线只保留 `ec`）。只安装本仓库不足以形成完整边界，必须同时审计 `dsh-onebot-qq`。
- `ec` 让模型拥有发送权；设计如此。记忆污染、提示注入、鱼群 JSONL 的隐私与存储都需要按“持久化注入面”对待。
- 设置页和 runtime 能启动/停止本地进程；只应在本机可信账户下运行。
- 没有遥测，也没有第三方上报域名。

完整说明见 [SECURITY.md](SECURITY.md)。

## 本地模型（可选）

本地 2B 只适合做边车：

```text
情绪打分升级（低置信/长文本/冲突）
图片理解
人物摘要
```

不建议用它接管 QQ 主聊天：当前 6.4k 首轮上下文超过本地 2048 窗口，4GB 显存/8GB 内存也不适合长上下文。主聊天继续用云端模型，本地模型按需加载。

## 评分后端

```json
{
  "provider": "ollama",
  "model": "huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M",
  "base_url": "http://127.0.0.1:11434"
}
```

也可使用 OpenAI 兼容 API。配置写到 `data/appraisal-config.json`（`.gitignore` 排除）；示例见 `config/appraisal.example.json`。

普通记忆先由固定程序 `code-v1` 打分，只有高价值/困难样本才升级到模型。默认日结批量使用 `code_only=True`，所以本地模型不转是正常的，不代表坏了。

## 第三方与许可

- 本项目以 **MIT License** 发布。
- 运行依赖和上游项目的许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
- 旧 SurfCore 文档仅作历史参考；当前 OneBot 路线不依赖 SurfCore 代码或运行服务。
