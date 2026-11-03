# EmotionCore for SurfCore

**版本：0.3.1** · [MIT License](LICENSE)

## 制作理念

> 人是由过往的一切记忆+一切社会关系构成的，记忆里自带情绪，身体技能的运转也会带来感受，这些情绪与感受会驱动人产生欲望，因此我认为记忆必须带情绪和场景记录以便记忆的复现还原，并且只有挂载了一个本地的其他辅助脑区与语言API（受限于机能目前只能挂线上云端的）一起构成一个本体才有成为一个个体的基础。另外，我不认为一昧的提高上下文是正确的方向，因为人类自己的短期记忆其实就没多少上下文，人类是遵循“够用就行”的原则自然演化出来的，因此我认为如何让各个功能的部件运转更加脱离大语言模型的“代偿”效应如何消耗更少的token和功率以至于能用本地小模型运转才是正确的研究方向。

## 项目简介

EmotionCore 是运行在 SurfCore 之上的情绪与记忆层：本地评价、P 基线、每日账本、记忆修正，以及给 SurfCore 目的机制的情绪种子。

> 内部 Python 包名暂时保留 `soulcore`，避免破坏插件 ID、数据库路径和已有 import；仓库与产品名统一为 **EmotionCore for SurfCore**。

## 目录

```text
soulcore/                          Python 核心
plugins/emotioncore-service/       本地 HTTP 服务
plugins/emotioncore-runtime/       启动/守护 service + worker
plugins/emotioncore-adapter/       QQ ec dispatcher / L5 注入
plugins/reflex-arc/                L1、群聊触发、长期活动、鱼群记录
plugins/memory-lab/                只读记忆实验 sidecar
plugins/memory-lab-dsh/            记忆实验室设置页 / 意识海
plugins/soulcore-settings/         EmotionCore 设置页
plugins/soul-bridge/               旧 soulcore_memory 工具（可选）
config/                            示例配置
docs/                              设计与审计
tests/                             单元测试
scripts/                           探针/工具脚本
experiments/                       离线实验
```

插件总览与边界见 [docs/PLUGINS.md](docs/PLUGINS.md)。

## 第三方与参考

- 本项目以 **MIT License** 发布；可自由使用、修改、分发和商用，保留版权与许可证声明即可。
- 安全边界、QQ 注入与余额探测说明见 [SECURITY.md](SECURITY.md)。
- 参考过 `DSH-Raising-Plan/dsh-mnemosyne` 的公开架构概念（observation/evidence/version/status、FTS5 思路），**未复制其源代码**；其许可证为 AGPL-3.0-or-later。
- 运行依赖（psutil、Pillow、RapidOCR、NumPy）和上游 SurfCore/DSH 的许可证状态见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 快速开始

```powershell
python -m soulcore init
python -m soulcore daily
python -m soulcore purpose-seed
python -m soulcore export-surfcore
```

## 身体状态（临时）

`body-state` 读取 psutil（CPU/内存/磁盘/电池/开机时长）和余额挂件的账本文件，生成 5 分钟有效的 `data/body-state.json`：

```powershell
python -m soulcore body-state
```

它**只进入表层对话提示**，不写 P、不写评价、不写记忆、不进入每日 baseline。余额文件不存在时自动降级为无余额状态。

睡眠清洗后会调用 `rotate-sessions`，归档旧 QQ 会话；下一条消息新建空上下文会话，只保留记忆卡/当前 P/人物卡。详见 `docs/SURFCORE-SESSIONS.md`。

欲望上浮层用当日 baseline 与累计偏离产生临时提示，不自动扣分、不写 P；详见 `docs/DESIRE.md`。

能力开关在 `data/capabilities.json`（示例 `config/capabilities.example.json`）；技能清单由 `skill-manifest` 生成，主模型只在新会话 bootstrap 时收到一次。

睡眠会构建 `episodes` 事件索引（`episode-build` / `episodes` 可手动查看），原始记忆仍保存在本地。提前睡眠和 token 测试见 `docs/EARLY-SLEEP.md`。

`episode-polish` 是可选的低风险本地 2B 摘要润色；默认关闭，失败时保留抽取式摘要，原始记忆不变。

睡眠前可选给 owner 发一条私聊晚安：`data/sleep-farewell.json`；`sleep`/`daily` 在归档会话前发送，失败不阻塞。

## 评分后端

默认使用与 SurfCore/DSH 同源的 API：

```json
{
  "provider": "api",
  "model": "deepseek-flash",
  "base_url": "https://api.deepseek.com",
  "api_key_env": "DEEPSEEK_API_KEY"
}
```

也可以完全使用本地 Ollama：

```json
{
  "provider": "ollama",
  "model": "huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M",
  "base_url": "http://127.0.0.1:11434",
  "api_key_env": ""
}
```

把配置写到 `data/appraisal-config.json`（已被 `.gitignore` 排除）。  
示例见 `config/appraisal.example.json`，也可用环境变量覆盖：

```text
SOULCORE_APPRAISER_PROVIDER
SOULCORE_APPRAISER_MODEL
SOULCORE_APPRAISER_BASE_URL
SOULCORE_APPRAISER_API_KEY_ENV
```

## 原则

- 不训练/修改模型权重；
- 每条记忆仍必须有评分；
- 普通记忆先由固定程序评分，高价值/困难才升级模型；
- 模型失败保留程序分，并进入表层修正闭环；
- 本地数据、数据库、备份不进入仓库。
