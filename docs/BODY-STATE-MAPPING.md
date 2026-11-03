# 设备状态 → 身体变量映射

> 这不是医学模型。设备/API 状态只作为桌宠的“身体隐喻”，不能用于健康诊断。

## 已核对的插件

### 1. `@hyzyn/dsh-tty` 的服务器状态条

源码字段（`packages/tty/src/stats.ts`）：

```text
cpuPct, cores
memUsed, memTotal, memPct
diskUsed, diskTotal, diskPct
uptimeSec
tcpConns
rxRate, txRate
tempC
```

Windows 本地限制（README 明确写了）：

- 只有 CPU / 内存 / 在线时长来自 `node:os`；
- 磁盘 / TCP / 网速 / 温度显示“无”；
- 远端 Linux/Windows 可走 SSH/PowerShell 补更多字段；
- **没有电池字段**。

### 2. `dsh-whale-widget`（小鲸鱼记账挂件）

能查/能算：

- DeepSeek 余额：总余额、赠金、充值余额、币种、余额来源；
- 余额刷新：60 秒自动 + 手动；
- 今日已用、近 7 天、逐轮消耗；
- 每轮 token：input / cache / output / reasoning；
- 峰谷时段与价格；
- 预算、余额预警；
- 订阅/资源包额度：已用 %、剩余、重置时间；
- 自定义厂商余额/额度（34 个模板）；
- 本地 Codex 会话统计。

DeepSeek 余额接口：

```text
GET https://api.deepseek.com/user/balance
fields: total_balance, granted_balance, topped_up_balance, balance_infos
```

它不提供“情绪/健康”字段，只提供资源与消耗。

## 真实语料相似度初筛

方法：

1. 为 12 个人类状态写一段操作化描述（压力、唤醒、疲劳、困倦、饥饿/资源不足、饱足、热负荷、认知负荷、社交需要、安全、奖励、自我效能）；
2. 为每个设备/API 属性写一段“这个数值高/低意味着什么”；
3. 中文字符 2/3-gram 余弦相似度；
4. 人工按工程含义校准，避免只靠字面。

初筛的代表性结果：

```text
cpu_high    → stress 0.23 / thermal 0.10
cpu_spike   → arousal 0.22
temp_high   → thermal 0.23 / stress 0.14
mem_high    → cognitive_load 0.14
late_night  → sleepiness 0.12
afk_long    → fatigue 0.15
balance_low → hunger 0.37 / satiety 0.13
```

字符相似度只能做初筛，不能当临床结论；下面是校准后的工程映射。

## 建议映射

| 输入 | 人类变量 | 初版权重 | 说明 |
|---|---|---:|---|
| CPU 持续高 | stress 皮质醇/压力 | 0.55 | 持续负荷，不是瞬时 |
| CPU 突然飙升 | arousal 肾上腺素/唤醒 | 0.65 | 短时爆发 |
| 内存高 | cognitive_load 认知负荷 | 0.60 | 信息堆积、处理不过来 |
| 温度高 | thermal_load 热负荷 | 0.70 | 设备过热，不是人类发烧 |
| 连续开机久 | fatigue 疲劳 | 0.55 | 叠加屏幕时间更可靠 |
| 电量低 | energy_low / fatigue | 0.60 | 能量储备低，不等同困 |
| 正在充电 | recovery 恢复 | 0.35 | 只做恢复，不直接给奖励 |
| TCP/连接数多 | cognitive_load | 0.30 | 弱信号，别单用 |
| 网络流量大 | information_load | 0.30 | 弱信号 |
| 长时间无操作 | recovery 恢复 | 0.40 | 也可能是离开，不是休息 |
| 连续屏幕使用 | fatigue / sleepiness | 0.55 | 需要结合时间 |
| 深夜使用 | sleepiness 褪黑素/困 | 0.75 | 节律信号最强 |
| 余额低 | resource_need（“饿”） | 0.70 | 资源不足，不是字面饥饿 |
| 余额快速下降 | resource_need / caution | 0.35 | 消耗速度 |
| 今日预算接近上限 | safety / caution | 0.55 | 风险与节制 |
| 配额剩余低 | safety | 0.65 | 限额压力 |
| 每轮 token 高 | cognitive_load | 0.40 | 认知/资源消耗 |
| 缓存命中低 | inefficiency（低权重） | 0.20 | 不适合直接变情绪 |
| 高峰计费 | caution（低权重） | 0.15 | 成本意识 |
| 充值/余额增加 | satiety / reward | 0.35 | 资源补充，不是成就 |

## 接到 P / 目的机制

不要让设备值直接覆盖 P。建议：

```text
原始值
→ 归一化（相对本机基线）
→ 慢速 EMA（几分钟到几小时）
→ 人类变量
→ 低权重偏移 P
→ 写入 purpose seed
```

映射到 P：

```text
stress      → security ↓, caution ↑, arousal ↑
fatigue     → self_efficacy ↓, openness ↓, arousal ↓
sleepiness  → arousal ↓, openness ↓
cognitive_load → openness ↓, unresolved ↑
resource_need  → security ↓, caution ↑
thermal_load   → arousal ↑, caution ↑
social_need    → sociability ↑, connect drive ↑
safety         → caution ↑
recovery       → fatigue ↓
reward         → valence ↑, trust ↑
```

目的机制：

- 高 stress / thermal / cognitive_load：降低主动分享、降低长回复、少开新话题；
- 高 fatigue / sleepiness：降低主动频率，优先短句/休息；
- 高 resource_need / safety：减少消耗型行为，倾向询问而非自作主张；
- 高 social_need：提高 connect；
- 高 recovery / reward：恢复正常分享/玩耍。

## 还缺的硬件层

`dsh-tty` 在 Windows 本机拿不到温度/功耗。  
要补：

- `psutil`：电池、CPU、内存、磁盘、开机时长；
- LibreHardwareMonitor：CPU/GPU 温度、风扇、功耗；
- ActivityWatch：活跃窗口、AFK、屏幕时间。

没有找到现成的 DSH/SurfCore “设备状态→激素”插件；这部分需要 EmotionCore 自己做一个薄层。

## 当前最小实现

- `soulcore/body_state.py`：psutil + `.dshw-usage.json` 读取；
- `python -m soulcore body-state`：写 `data/body-state.json`，TTL 300 秒；
- `context_render` 把它作为“此刻身体状态（临时）”注入；
- `soul-bridge` 每 5 分钟刷新一次并重渲染上下文；
- **不写 P、不写 appraisals、不写 memories、不写 daily_summaries**；
- 余额文件缺失时正常降级，不报错。

余额挂件尚未安装到当前 profile，所以当前 `balance=null`；安装 `dsh-whale-widget` 并产生 `$DSH_HOME/.dshw-usage.json` 后会自动读取。
