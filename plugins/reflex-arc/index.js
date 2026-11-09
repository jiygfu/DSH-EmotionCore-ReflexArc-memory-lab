/**
 * ReflexArc — 独立反射弧子插件。
 *
 * 只做本地、确定性的入站预处理：
 *   - 识别骰子指令并在本地结算；
 *   - 生成极短 hint，不注册模型 tool；
 *   - 后续接 OCR / 表情联想 / 记忆指针。
 *
 * 部署：<dsh-onebot-qq>/plugins/reflex-arc/index.js
 */

import fs from 'node:fs';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { detectDiceIntent, rollDice, classifyIncoming, findDiceClaimMismatch, inQuietHours, screenClaim } from './reflex-core.js';
import { runDiceCommand } from './dice-command.js';
import {
  activityPatterns, detectActivityAction, detectFishTags, highChanceFor, highContextScore,
  isContinueLike, isManagedGroup, isQuestion, probabilityHit, scoreRelated, splitList,
} from './trigger-core.js';

const VERSION = '0.1.1';
const DEFAULT_FISH_TAGS = ['肥鱼', '机器人', 'AI', 'bot', '人工智能', '机械'];

const configSchema = {
  enabled: { type: 'bool', default: true, group: '反射弧', label: '启用反射弧', hint: '本地骰子/提示；不注册模型工具。' },
  maxDice: { type: 'int', default: 100, min: 2, max: 10000, group: '反射弧', label: '骰子上限', hint: '单次骰子的面数上限，防止异常大数。' },
  maxCount: { type: 'int', default: 10, min: 1, max: 20, group: '反射弧', label: '骰子个数上限', hint: '一次最多掷几个骰子。' },

  // 骰子指令通道（本地直回，不叫模型；随机数模型看不到，也没法照着编）
  diceCommand: {
    type: 'bool', default: true, group: '反射弧', label: '骰子指令（本地直回）',
    hint: '.r 3d6 / .ra 侦查60 这类指令由本地直接回，零 token、不唤醒模型；关掉就退回"本地掷骰→把点数塞给模型让模型报"的老路子。',
  },
  diceCommandDefault: {
    type: 'str', default: '1d6', group: '反射弧', label: '默认骰（只打 .r）',
    hint: '只打 ".r" / "。r" 时掷什么；.ra 检定固定用 1d100。',
  },
  diceCommandMaxDice: { type: 'int', default: 20, min: 1, max: 20, group: '反射弧', label: '指令：单次最多骰数' },
  diceCommandMaxSides: { type: 'int', default: 1000, min: 2, max: 1000, group: '反射弧', label: '指令：面数上限' },
  diceCommandMaxRepeat: { type: 'int', default: 10, min: 1, max: 10, group: '反射弧', label: '指令：3#1d6 最多重复' },
  diceIntent: {
    type: 'bool', default: true, group: '反射弧', label: '骰子意图提示',
    hint: '口语里的「掷个骰子」识别后以 [反射弧/骰] 一行注入本轮（数字由模型转述，会花这一轮的钱）。'
      + '关掉 = 只有 .r / .ra 指令通道能掷。',
  },
  diceReceipt: {
    type: 'bool', default: true, group: '反射弧', label: '骰子回执（防改数字）',
    hint: '模型报的骰子数字和本地掷的不一致时，下一轮用 【反射弧回执】 点出来。',
  },
  impressionEnabled: {
    type: 'bool', default: true, group: '反射弧', label: '首次接触人物印象',
    hint: '当天第一次和某人说话时，向 EmotionCore 取一句人物印象注入本轮（每人每天一次）。关掉后不再请求 8765。',
  },
  emotionCoreUrl: { type: 'str', default: 'http://127.0.0.1:8765', group: '反射弧', label: 'EmotionCore 地址', hint: '人物印象、长期活动判断共用；留空关闭对应联动。' },
  impressionTimeoutMs: { type: 'int', default: 1500, min: 100, max: 10000, group: '反射弧', label: '人物印象超时（ms）' },
  visionModel: { type: 'str', default: 'huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M', group: '反射弧', label: '本地视觉模型' },
  localVision: {
    type: 'bool', default: false, group: '反射弧', label: '本地视觉描述（慢）',
    hint: '把图丢给本地 qwen3-vl 出 120 字描述：实测每张约 24 秒（CPU 2B），会明显拖慢回复，默认关。'
      + '只有图片没有 url（QQ 只给本地文件）时这项本来也不会触发。',
  },
  visionTimeoutMs: { type: 'int', default: 20000, min: 1000, max: 120000, group: '反射弧', label: '图片理解超时（ms）' },

  // ── 本地粗看：过长/过大的截图先在本地 OCR，只把文字交给模型（省 token）──
  coarseVision: {
    type: 'bool', default: true, group: '反射弧/粗看', label: '长图本地粗看',
    hint: '收到的截图过高/过大时先在本地 OCR 出文字，只把文字交给模型，原图不发送。'
      + '省一半左右 token（1080×1920 截图 ≈ 986 → 400–600），更重要的是长图压缩后模型本来就看不清。'
      + 'OCR 不可用时自动退回原图，不会让模型看不到内容。',
  },
  coarseVisionKeepOriginal: {
    type: 'bool', default: false, group: '反射弧/粗看', label: '粗看后仍发原图',
    hint: '打开 = 不省 token，只额外多一段 OCR 文本（调试用）。',
  },
  coarseLookBack: {
    type: 'bool', default: true, group: '反射弧/粗看', label: '模型可调 ec look 取图',
    hint: '粗看之后模型想细看时，可以用 mcp__qq__ec(action="look") 把 QQ 默认画质那张回灌进下一轮'
      + '（多花 200–1000 token）。关掉 = 只给 OCR 文字，永远不再给图。',
  },
  coarseVisionLongRatio: {
    type: 'int', default: 250, min: 120, max: 1000, group: '反射弧/粗看', label: '长图判定（高/宽 ×100）',
    hint: '250 = 高是宽的 2.5 倍以上算长图（聊天记录截图、网页长图）。',
  },
  coarseVisionPixels: {
    type: 'int', default: 4000000, min: 100000, max: 64000000, group: '反射弧/粗看', label: '像素上限（超过按大图处理）',
    hint: '宽×高超过这个值也走粗看；0 = 只看长宽比。',
  },
  coarseVisionMaxChars: {
    type: 'int', default: 800, min: 80, max: 4000, group: '反射弧/粗看', label: '粗看文本上限（字）',
    hint: 'OCR 结果截断长度；长图全量文字通常上万字，截断后每轮只多 ~500 tokens。',
  },
  coarseVisionTimeoutMs: {
    type: 'int', default: 60000, min: 2000, max: 300000, group: '反射弧/粗看', label: '粗看超时（ms）',
  },
  coarseVisionMaxTiles: {
    type: 'int', default: 4, min: 1, max: 16, group: '反射弧/粗看', label: '最多切几块 OCR',
    hint: '每块 1600px 高、约 3 秒；4 块 ≈ 13 秒，超出的下半部分不读（长图通常前几屏才是重点）。',
  },
  coarseVisionPython: {
    type: 'str', default: '', group: '反射弧/粗看', label: 'OCR Python 路径',
    hint: '留空自动找：DSH 运行时 python → 系统 python。需要该解释器装了 rapidocr-onnxruntime。',
  },
  memoryLabEnabled: { type: 'bool', default: true, group: '反射弧', label: '启用 memory-lab 联想（实验）', hint: '默认开启；最多 2 条、每条 80 字，带时间·人物·场景·事实/看法。只读查询，失败不影响回复；不想看把它关掉即可。' },
  memoryLabUrl: { type: 'str', default: 'http://127.0.0.1:8766', group: '反射弧', label: 'memory-lab 地址' },
  memoryLabTimeoutMs: { type: 'int', default: 250, min: 100, max: 3000, group: '反射弧', label: 'memory-lab 超时（ms）' },
  holdEnabled: { type: 'bool', default: true, group: '反射弧', label: '停等 3 秒再交 API', hint: '本地先把场景/约束/联想都建好但不急着进模型；3 秒内同会话又来消息就并成一条，重新计时；期间被撤回就整条作废。关掉则恢复「到即处理」。' },
  holdMs: { type: 'int', default: 3000, min: 0, max: 15000, step: 100, group: '反射弧', label: '停等时长', unit: '毫秒', hint: '默认 3000。调大更能攒住连发，代价是每条回复晚这么多。' },
  shadowLog: { type: 'bool', default: true, group: '调试/审计', label: 'V9-A 影子日志', hint: '每轮往 state/reflex-shadow.jsonl 写一行「如果我是外壳会怎么决定」，只落盘不动行为；攒 1–2 天用来判断合批/绑定该怎么改。' },
  sendTargetLock: { type: 'bool', default: true, group: '反射弧', label: '发送绑 chatKey（弱约束）', hint: '在 hint 里写明本轮只准往这个 target 发；群就发群号、私聊就回那个 QQ。零成本的口头约束，内核工具不受插件控制，所以是提示不是强制。' },
  secondPassMinScore: { type: 'num', default: 0.55, min: 0, max: 2, step: 0.01, group: '反射弧', label: '二次联想分数下限（全库）', hint: '第一遍没捞到时，用她自己刚说的话再查一次全库；只有 rrf 分数不低于这个值才注入，最多补 1 条。调高=更保守，调低=更爱联想。' },

  // ── 群聊触发：每个模式一个下级页；总开关默认关，避免装完就抢话 ──
  triggerEnabled: {
    type: 'bool', default: false, group: '触发/总览', label: '启用群聊接话策略',
    hint: '总开关。开：受管理群里没被 @ 的消息也会进入本地反射弧判断；关：只保留原有的骰子/图片等预处理，不主动接话。'
      + '门禁（屏蔽群、群内黑名单、用户白名单）仍然优先，反射弧只处理通过门禁的消息。',
  },
  triggerGroups: {
    type: 'group', default: [], group: '触发/总览', label: '接话群（空 = 所有通过门禁的群）',
    hint: '群号列表，逗号分隔。只在这些群里启用相关/随机/高概率/长期活动判断；留空 = 所有通过 gate-wake 门禁的群。'
      + '群号可在「群聊」页查看。',
  },
  selfAliases: {
    type: 'str', default: '', group: '触发/总览', label: '本机别名（逗号分隔，可留空）',
    hint: '用于「相关触发」判断，例如群里叫你的名字/外号。留空时自动使用当前 QQ 昵称；唤醒词不会自动算作别名，避免和关键词唤醒重复。',
  },
  relatedKeywords: {
    type: 'str', default: '', group: '触发/总览', label: '额外相关词（逗号分隔，可留空）',
    hint: '除了本机别名，出现这些词也算「在说你」。适合「阿黑」「小鱼」这类只有你们知道的称呼；别填「你」这种泛词。',
  },
  quietHours: {
    type: 'str', default: '', group: '触发/总览', label: '夜间静默时段（可留空）',
    hint: '例 01:00-08:00；留空 = 不静默。静默期内只挡「主动接话」（相关/随机/高概率/长期活动自动开始），'
      + '被 @、引用、唤醒词叫到时照常回，骰子这类指令也照常。',
  },
  quietHoursEnabled: {
    type: 'bool', default: false, group: '触发/总览', label: '启用夜间静默',
    hint: '勾上才按上面的时段静默；不勾 = 行为和以前完全一样。',
  },

  relatedEnabled: {
    type: 'bool', default: false, group: '触发/相关', label: '相关触发',
    hint: '只有本地判断「这条和本机有关」才接话。判断依据：本机别名、第二人称提问、「那/所以」这类接续词；不调用模型。',
  },
  relatedMinScore: {
    type: 'int', default: 3, min: 1, max: 10, group: '触发/相关', label: '触发分数阈值',
    hint: '分数越高越严格。默认 3：本机别名（3 分），或句首第二人称提问（2+1 分）可触发；句中泛泛的「你」加问句只有 2 分，不触发。',
  },
  relatedRequireQuestion: {
    type: 'bool', default: false, group: '触发/相关', label: '只接提问/请求',
    hint: '开：即使出现本机别名，也必须是疑问句/请求才触发；关：别名出现即可。',
  },
  relatedCooldownSec: {
    type: 'int', default: 90, min: 0, max: 3600, group: '触发/相关', label: '冷却（秒）',
    hint: '同一群相邻两次相关触发的最小间隔；0 = 只受每小时上限约束。',
  },
  relatedHourlyMax: {
    type: 'int', default: 8, min: 1, max: 100, group: '触发/相关', label: '每小时上限',
    hint: '防止有人反复叫你导致连续烧模型。',
  },

  randomEnabled: {
    type: 'bool', default: false, group: '触发/随机', label: '随机触发',
    hint: '按概率随机接一句；不判断内容，适合冷清群或测试。默认关。',
  },
  randomChance: {
    type: 'int', default: 8, min: 1, max: 100, group: '触发/随机', label: '概率（%）',
    hint: '每条符合条件的消息独立掷一次。建议 2–10%；100% 等于每条都接。',
  },
  randomCooldownSec: {
    type: 'int', default: 180, min: 0, max: 7200, group: '触发/随机', label: '冷却（秒）',
    hint: '同一群相邻两次随机触发的最小间隔；0 = 不限制间隔。',
  },
  randomHourlyMax: {
    type: 'int', default: 3, min: 1, max: 100, group: '触发/随机', label: '每小时上限',
    hint: '硬上限，防止随机概率在高频群里失控。',
  },
  randomMinChars: {
    type: 'int', default: 4, min: 0, max: 200, group: '触发/随机', label: '最短字数',
    hint: '太短的消息（「？」「嗯」）不参与随机，避免接废话。',
  },

  highEnabled: {
    type: 'bool', default: false, group: '触发/高概率', label: '高概率搭话',
    hint: '群里正在热聊、有提问或刚接过话时，用较高概率接一句。它不判断「是不是叫你」，只看对话热度；和随机模式二选一即可。',
  },
  highChance: {
    type: 'int', default: 65, min: 1, max: 100, group: '触发/高概率', label: '基础概率（%）',
    hint: '上下文分 ≥2 才进入掷骰；实际概率会随上下文分提高（最高 95%）。',
  },
  highMinScore: {
    type: 'int', default: 3, min: 2, max: 7, group: '触发/高概率', label: '最低上下文分',
    hint: '低于此分不触发。默认 3：通常要「最近消息数够 + 有提问」或「刚接过话 + 有接续词」。',
  },
  highWindowSec: {
    type: 'int', default: 180, min: 30, max: 3600, group: '触发/高概率', label: '热度窗口（秒）',
    hint: '统计最近多少秒内的群消息来判断「正在聊」。',
  },
  highMinMessages: {
    type: 'int', default: 3, min: 1, max: 50, group: '触发/高概率', label: '窗口内最少消息数',
    hint: '窗口内至少这么多条（含当前这条）才加「热聊」分。',
  },
  highRequireQuestion: {
    type: 'bool', default: false, group: '触发/高概率', label: '只接提问',
    hint: '开：只在高概率模式里接疑问句；关：陈述句、接续句也可以。',
  },
  highCooldownSec: {
    type: 'int', default: 90, min: 0, max: 3600, group: '触发/高概率', label: '冷却（秒）',
    hint: '同一群相邻两次高概率触发的最小间隔。',
  },
  highHourlyMax: {
    type: 'int', default: 6, min: 1, max: 100, group: '触发/高概率', label: '每小时上限',
    hint: '硬上限，防止热群连续触发。',
  },

  activityEnabled: {
    type: 'bool', default: false, group: '触发/长期活动', label: '长期活动接管',
    hint: '识别聊天游戏/跑团等长期活动；活动进行中每条消息都接，直到暂停/中断/结束并归档。默认关。',
  },
  activityAutoStart: {
    type: 'bool', default: true, group: '触发/长期活动', label: '自动识别活动开始',
    hint: '开：消息命中开始词（开团/跑团/来一局…）就进入活动状态；关：只能在调试页手动开始。',
  },
  activityEmotionCore: {
    type: 'bool', default: true, group: '触发/长期活动', label: 'EmotionCore 联动判断',
    hint: '开：活动开始/控制消息会请求本机 EmotionCore `/activity` 复核；服务不可用时自动回落本地规则，不影响聊天。',
  },
  activityMinConfidence: {
    type: 'int', default: 55, min: 0, max: 100, group: '触发/长期活动', label: 'EmotionCore 最低置信度（%）',
    hint: '低于此值的远端判断不采纳，改用本地关键词。',
  },
  activityEmotionCoreTimeoutMs: {
    type: 'int', default: 500, min: 100, max: 5000, group: '触发/长期活动', label: 'EmotionCore 超时（ms）',
    hint: '只影响活动开始/控制判断；超时立即回落本地，不阻塞消息。',
  },
  activityStartKeywords: {
    type: 'text', default: '', group: '触发/长期活动', label: '开始词（一行/逗号分隔）',
    hint: '留空 = 内置：开团,跑团,开始游戏,游戏开始,来一局,开一局,剧本,桌游,TRPG,DND,COC,团本。',
  },
  activityPauseKeywords: {
    type: 'text', default: '', group: '触发/长期活动', label: '暂停词',
    hint: '留空 = 内置：暂停,先停,停一下,休息,歇会,等我。暂停会归档当前段，之后可继续。',
  },
  activityResumeKeywords: {
    type: 'text', default: '', group: '触发/长期活动', label: '继续词',
    hint: '留空 = 内置：继续,恢复,接着来,接着跑,回来继续。',
  },
  activityInterruptKeywords: {
    type: 'text', default: '', group: '触发/长期活动', label: '中断词',
    hint: '留空 = 内置：中断,打断,先不跑,退出,取消。中断会归档并结束当前活动。',
  },
  activityEndKeywords: {
    type: 'text', default: '', group: '触发/长期活动', label: '结束词',
    hint: '留空 = 内置：结束,团灭,收尾,不玩了,散了,完结,归档,到此为止。',
  },
  activityIdleEndMin: {
    type: 'int', default: 0, min: 0, max: 1440, group: '触发/长期活动', label: '静默自动结束（分钟）',
    hint: '0 = 不自动结束，必须收到暂停/中断/结束；大于 0 时，超过这么久没消息，下一条消息前自动归档。',
  },
  activityMaxTranscript: {
    type: 'int', default: 200, min: 20, max: 500, group: '触发/长期活动', label: '归档最多保留消息数',
    hint: '只影响归档文件大小；超出后保留最近 N 条。',
  },
  activityArchive: {
    type: 'bool', default: true, group: '触发/长期活动', label: '结束时写入归档文件',
    hint: '写到 dataDir/state/reflex-activities/，并在调试页显示最近归档；不写 EmotionCore 记忆库。',
  },
  activityReplyEvery: {
    type: 'bool', default: true, group: '触发/长期活动', label: '活动进行中每条都接',
    hint: '默认开。关：只记录活动，不自动接话（调试/旁观模式）。',
  },

  sceneHint: {
    type: 'bool', default: true, group: '触发/长期活动', label: '每轮附场景元信息',
    hint: '在提示词末尾加一行 `[场景:群 123456·近5分钟 4 人·发言人 名字(QQ:1)·事件:标题]`：'
      + '让模型分得清「谁在说、对谁说、这是哪个场面」，群与私聊共用一个 session 时不至于串人。约 40 字，不占记忆条数。',
  },

  reinjectEveryTurns: {
    type: 'int', default: 20, min: 0, max: 200, group: '触发/长期活动', label: '每 N 轮重述一次工具约定',
    hint: '默认 20，填 0 关闭。单会话跑久了、上下文被压缩之后，工具清单和输出格式最先丢；'
      + '每 N 轮把同一段固定约定（逐字不变）追加一轮，比堆一堆"禁止…"更省也更稳。',
  },

  fishEnabled: {
    type: 'bool', default: false, group: '触发/鱼群', label: '启用鱼群记录',
    hint: '开：群友的群名片/昵称命中“肥鱼、机器人、AI、bot”等标签时，自动给其人物印象打标签；之后该群友的群消息只记录，不进入模型、不搭话、不主动私聊。默认关。',
  },
  fishTags: {
    type: 'text', default: '肥鱼,机器人,AI,bot,人工智能,机械', group: '触发/鱼群', label: '鱼群身份标签',
    hint: '逗号/换行分隔，匹配群名片和昵称。AI/bot 按英文词边界匹配；中文按包含匹配。',
  },
  fishTagPerson: {
    type: 'bool', default: true, group: '触发/鱼群', label: '写入 EmotionCore 人物印象标签',
    hint: '开：命中时调用本机 /person_tag，把标签写进人物印象（L4），之后注入上下文会带“标签：…”。服务不可用时只保留本地鱼群记录。',
  },

  debugLog: {
    type: 'bool', default: false, group: '触发/调试', label: '控制台打印触发决策',
    hint: '开：每次相关/随机/高概率/活动判断都会写一行日志，方便调阈值。',
  },
  debugRecentLimit: {
    type: 'int', default: 20, min: 5, max: 100, group: '触发/调试', label: '调试页保留最近决策数',
    hint: '只保留最近 N 条判定记录，不存完整聊天。',
  },
};

function parseDice(text, maxDice = 100, maxCount = 10) {
  const intent = detectDiceIntent(text, { judgeDefault: '1d100', diceDefault: '1d100' });
  if (!intent) return null;
  const r = rollDice(intent.expr);
  if (!r) return null;
  // 保持旧测试/调用方使用的字段名；上限由本地 rollDice 再兜一次。
  const count = Math.max(1, Math.min(maxCount, r.rolls.length));
  const sides = Math.max(2, Math.min(maxDice, Number((r.expr.match(/d(\d+)/i) || [])[1]) || 100));
  return { count, sides, rolls: r.rolls.slice(0, count), total: r.total, expr: r.expr, intent };
}

/**
 * 场景元信息（约 40 字）：谁在说、对谁说、这是哪个场面。
 * 群与私聊共用同一个 session，模型只能靠这行分清窗口；数据全取本地状态，不发网络请求。
 * 抽成模块级函数是为了能单测（setup 里的闭包拿不到）。
 */
export function buildSceneHint(ev, { bot, groupState, oneLine } = {}) {
  if (bot?.cfg?.sceneHint === false) return '';
  const qq = String(ev?.sender?.qq ?? '').trim();
  const name = oneLine ? oneLine(ev?.sender?.name || ev?.sender?.card || '', 20) : String(ev?.sender?.name || '');
  const who = qq ? `${name || '某人'}(QQ:${qq})` : name;
  if (!ev?.isGroup) return who ? `[场景:私聊·对象 ${who}]` : '';
  const gid = String(ev?.groupId ?? '');
  let people = 0;
  let title = '';
  try {
    const g = groupState ? groupState(gid) : null;
    const since = Date.now() - 5 * 60 * 1000;
    const seen = new Set();
    for (const r of Array.isArray(g?.recent) ? g.recent : []) {
      if (Number(r?.ts || 0) >= since && r?.qq) seen.add(String(r.qq));
    }
    people = seen.size;
    if (g?.activity?.status === 'active' && g.activity?.title) {
      title = oneLine ? oneLine(g.activity.title, 20) : String(g.activity.title);
    }
  } catch {}
  const bits = [`群 ${gid}`];
  if (people > 0) bits.push(`近5分钟 ${people} 人`);
  if (who) bits.push(`发言人 ${who}`);
  if (title) bits.push(`事件:${title}`);
  return `[场景:${bits.join('·')}]`;
}

export default {
  id: 'reflex-arc',
  title: 'ReflexArc 反射弧',
  order: 36,
  version: VERSION,
  configSchema,

  setup(bot) {
    if (!bot?.cfg?.enabled) {
      bot.log?.info?.('[ReflexArc] disabled');
      return;
    }

    const onBefore = (stage, fn, opts) => (typeof bot.on === 'function'
      ? bot.on(stage, fn, opts)
      : bot.pipeline?.use?.(stage, fn, opts));

    // ── 骰子指令通道（.r / .ra）：本地直接回，零 token，模型看不到随机数 ──
    // 移植自 surfcore 的 dice-command：随机数一旦进了模型上下文，它就有机会照着编；
    // 命令通道直接出结果 + 本轮 stopped，模型根本不知道这次掷了什么。
    const lastRoll = new Map();   // chatKey -> { expr, total, at }
    const diceMismatch = new Map(); // chatKey -> { expected, seen }

    /** "01:00-08:00" → {startHour, endHour}；空/格式不对 → null（= 不静默）。 */
    function parseQuietHours(spec) {
      const m = String(spec || '').trim().match(/^(\d{1,2})(?::\d{2})?\s*[-~到]\s*(\d{1,2})(?::\d{2})?$/);
      if (!m) return null;
      const startHour = Math.min(23, Math.max(0, Number(m[1])));
      const endHour = Math.min(23, Math.max(0, Number(m[2])));
      if (!Number.isFinite(startHour) || !Number.isFinite(endHour) || startHour === endHour) return null;
      return { startHour, endHour };
    }

    function diceOptions() {
      const c = bot?.cfg || {};
      return {
        enabled: c.diceCommand !== false, // 缺键按默认开
        judgeDefault: '1d100',
        diceDefault: String(c.diceCommandDefault || '1d6'),
        maxDice: Number(c.diceCommandMaxDice) || 20,
        maxSides: Number(c.diceCommandMaxSides) || 1000,
        maxRepeat: Number(c.diceCommandMaxRepeat) || 10,
      };
    }

    if (typeof bot.on === 'function') {
      // order 10：排在斜杠命令（5）之后、门禁之前；私聊群聊都认
      bot.on('intercept', async (ev) => {
        try {
          if (ev?.stopped) return;
          const opts = diceOptions();
          if (opts.enabled !== true) return;
          const cmd = runDiceCommand(ev.text, opts);
          if (!cmd) return;
          await bot.deliver(ev.chatKey, cmd.reply);
          ev.stopped = true;
          ev.stopReason = 'reflex-arc:dice';
          const key = String(ev.chatKey || '');
          if (key && cmd.expr) lastRoll.set(key, { expr: cmd.expr, total: cmd.total, at: Date.now() });
          bot.log?.info?.(`[ReflexArc] 骰子指令 ${ev.chatKey}：${cmd.reply}`);
        } catch (e) {
          bot.log?.warn?.(`[ReflexArc] 骰子指令失败: ${e.message}`);
        }
      }, { order: 10 });
    }
    function stateFile() {
      return path.join(bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'state', 'reflex-impressions.json');
    }

    function readState() {
      try {
        const raw = JSON.parse(fs.readFileSync(stateFile(), 'utf8'));
        if (raw && raw.day === new Date().toLocaleDateString('en-CA')) return raw;
      } catch {}
      return { day: new Date().toLocaleDateString('en-CA'), seen: {} };
    }

    function saveState(state) {
      try {
        const file = stateFile();
        fs.mkdirSync(path.dirname(file), { recursive: true });
        fs.writeFileSync(file, JSON.stringify(state, null, 2), 'utf8');
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] impression state: ${e.message}`);
      }
    }

    // ═══════════════════════════════════════════════════════════════════
    // 群聊触发（本地反射弧）
    // ═══════════════════════════════════════════════════════════════════
    // 只处理通过 gate-wake 的消息；门禁、黑名单、用户白名单仍然优先。
    // 状态落盘到 state/reflex-trigger.json；归档单独写 state/reflex-activities/。
    const triggerFile = () => path.join(
      bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'state', 'reflex-trigger.json',
    );
    const archiveDir = () => path.join(
      bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'state', 'reflex-activities',
    );
    let trigState = null;
    let trigSaveTimer = null;
    let trigDisposed = false;
    let activityRemoteDownUntil = 0;

    const nowIso = () => new Date().toISOString();
    const numOf = (v, fallback, min, max) => {
      const n = Number(v);
      if (!Number.isFinite(n)) return fallback;
      return Math.min(max, Math.max(min, Math.round(n)));
    };
    const hourKey = (ts = Date.now()) => {
      const d = new Date(ts);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}-${String(d.getHours()).padStart(2, '0')}`;
    };
    const oneLine = (v, n = 80) => String(v ?? '').replace(/\s+/g, ' ').trim().slice(0, n);

    function defaultTriggerState() {
      return { version: 1, groups: {}, archives: [], events: [] };
    }

    function readTriggerState() {
      try {
        const raw = JSON.parse(fs.readFileSync(triggerFile(), 'utf8'));
        if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
          if (!raw.groups || typeof raw.groups !== 'object') raw.groups = {};
          if (!Array.isArray(raw.archives)) raw.archives = [];
          if (!Array.isArray(raw.events)) raw.events = [];
          return raw;
        }
      } catch {}
      return defaultTriggerState();
    }

    function ensureTriggerState() {
      if (!trigState) trigState = readTriggerState();
      return trigState;
    }

    function writeJsonAtomic(file, value) {
      const dir = path.dirname(file);
      fs.mkdirSync(dir, { recursive: true });
      const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(value, null, 2), 'utf8');
      try {
        fs.renameSync(tmp, file);
      } catch {
        try { fs.copyFileSync(tmp, file) } finally { try { fs.rmSync(tmp, { force: true }) } catch {} }
      }
    }

    function saveTriggerStateNow() {
      if (trigDisposed || !trigState) return;
      try {
        writeJsonAtomic(triggerFile(), trigState);
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] trigger state: ${e.message}`);
      }
    }

    function scheduleTriggerSave() {
      if (trigDisposed || trigSaveTimer) return;
      trigSaveTimer = setTimeout(() => {
        trigSaveTimer = null;
        saveTriggerStateNow();
      }, 200);
    }

    // ── 鱼群记录：命中的群友只记账，不进模型 ──
    const fishFile = () => path.join(
      bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'state', 'reflex-fish.json',
    );
    const fishLogFile = () => path.join(
      bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'state', 'fish-records.jsonl',
    );
    let fishState = null;
    let fishSaveTimer = null;

    function defaultFishState() {
      return { version: 1, members: {}, recordCount: 0, recent: [] };
    }

    function ensureFishState() {
      if (fishState) return fishState;
      try {
        const raw = JSON.parse(fs.readFileSync(fishFile(), 'utf8'));
        fishState = raw && typeof raw === 'object' ? raw : defaultFishState();
      } catch {
        fishState = defaultFishState();
      }
      if (!fishState.members || typeof fishState.members !== 'object') fishState.members = {};
      if (!Array.isArray(fishState.recent)) fishState.recent = [];
      if (!Number.isFinite(Number(fishState.recordCount))) fishState.recordCount = 0;
      return fishState;
    }

    function saveFishNow() {
      if (!fishState) return;
      try {
        writeJsonAtomic(fishFile(), fishState);
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] fish state: ${e.message}`);
      }
    }

    function scheduleFishSave() {
      if (fishSaveTimer) return;
      fishSaveTimer = setTimeout(() => {
        fishSaveTimer = null;
        saveFishNow();
      }, 200);
    }

    function fishTagsOf(cfg = bot.cfg || {}) {
      const tags = splitList(cfg.fishTags);
      return tags.length ? tags : DEFAULT_FISH_TAGS;
    }

    function fishMember(qq) {
      const st = ensureFishState();
      const key = String(qq);
      if (!st.members[key]) {
        st.members[key] = { qq: key, name: '', tags: [], count: 0, firstAt: null, lastAt: null, taggedAt: null, tagAttemptAt: 0 };
      }
      return st.members[key];
    }

    function recordFish(ev, tags, name, now) {
      const st = ensureFishState();
      const qq = String(ev.sender?.qq ?? '');
      const member = fishMember(qq);
      member.name = name || member.name || '';
      member.tags = [...new Set([...(member.tags || []), ...tags])].slice(-10);
      member.count = Number(member.count || 0) + 1;
      member.firstAt = member.firstAt || nowIso();
      member.lastAt = nowIso();
      const text = String(ev.text || '').trim() || `[${(ev.images || []).length || 1} 个非文本消息]`;
      const row = {
        at: nowIso(),
        groupId: String(ev.groupId || ''),
        qq,
        name: oneLine(name, 40),
        tags,
        messageId: ev.messageId ?? null,
        text: oneLine(text, 2000),
      };
      try {
        fs.mkdirSync(path.dirname(fishLogFile()), { recursive: true });
        fs.appendFileSync(fishLogFile(), `${JSON.stringify(row)}\n`, 'utf8');
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] fish record: ${e.message}`);
      }
      st.recordCount = Number(st.recordCount || 0) + 1;
      st.recent.unshift({
        at: row.at, groupId: row.groupId, qq, name: row.name, tags, preview: oneLine(text, 100),
      });
      st.recent = st.recent.slice(0, 30);
      scheduleFishSave();
      bot.log?.info?.(`[ReflexArc] fish record qq=${qq} tags=${tags.join(',')} group=${ev.groupId}`);
    }

    async function tagFishPerson(ev, tags, name) {
      if (bot.cfg?.fishTagPerson === false) return;
      const member = fishMember(ev.sender?.qq);
      const now = Date.now();
      if (member.taggedAt || now - Number(member.tagAttemptAt || 0) < 60_000) return;
      member.tagAttemptAt = now;
      scheduleFishSave();
      const base = String(bot.cfg?.emotionCoreUrl || process.env.EMOTIONCORE_URL || '').trim().replace(/\/+$/, '');
      if (!base) return;
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), 1500);
      try {
        const res = await fetch(`${base}/person_tag`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ qq: String(ev.sender?.qq ?? ''), name: name || '', tags, note: 'fish-record' }),
          signal: ac.signal,
        });
        if (!res.ok) return;
        const data = await res.json();
        if (data?.ok !== false) {
          member.taggedAt = nowIso();
          member.remoteTags = data?.person?.tags || tags;
          scheduleFishSave();
          bot.log?.info?.(`[ReflexArc] fish person tagged qq=${member.qq} tags=${tags.join(',')}`);
        }
      } catch {
        // 本地记录已落盘；EmotionCore 恢复后下一次消息再补标签。
      } finally {
        clearTimeout(timer);
      }
    }

    function onFishGate(ev) {
      const cfg = bot.cfg || {};
      if (cfg.fishEnabled !== true) return;
      if (!ev?.isGroup || !ev.groupId) return;
      if (ev.stopped) return;
      const qq = String(ev.sender?.qq ?? '').trim();
      if (!/^\d+$/.test(qq)) return;
      if (String(bot?.onebot?.selfId ?? '') === qq) return;
      const cached = ensureFishState().members[qq] || null;
      const names = [ev.sender?.card, ev.sender?.name, cached?.name].filter(Boolean).join(' ');
      const tags = (cached?.tags && cached.tags.length)
        ? cached.tags
        : detectFishTags(names, fishTagsOf(cfg));
      if (!tags.length) return;

      const member = fishMember(qq);
      const name = String(ev.sender?.card || ev.sender?.name || cached?.name || '').trim();
      recordFish(ev, tags, name, Date.now());
      ev.stopped = true;
      ev.stopReason = 'reflex-arc:fish-silent';
      if (!member.taggedAt) void tagFishPerson(ev, tags, name);
    }

    function fishStatus() {
      const st = ensureFishState();
      return {
        enabled: bot.cfg?.fishEnabled === true,
        tags: fishTagsOf(),
        recordCount: Number(st.recordCount || 0),
        members: Object.values(st.members || {})
          .sort((a, b) => String(b.lastAt || '').localeCompare(String(a.lastAt || '')))
          .slice(0, 50),
        recent: (st.recent || []).slice(0, 20),
        paths: { state: fishFile(), records: fishLogFile() },
      };
    }

    function groupState(gid) {
      const st = ensureTriggerState();
      const key = String(gid);
      if (!st.groups[key] || typeof st.groups[key] !== 'object') {
        st.groups[key] = {
          recent: [], counters: {}, last: null, lastBotAt: 0,
          activity: null, paused: null,
        };
      }
      const g = st.groups[key];
      if (!Array.isArray(g.recent)) g.recent = [];
      if (!g.counters || typeof g.counters !== 'object') g.counters = {};
      return g;
    }

    function pruneRecent(g, now) {
      const windowMs = Math.max(60_000, numOf(bot.cfg?.highWindowSec, 180, 30, 3600) * 1000);
      g.recent = (Array.isArray(g.recent) ? g.recent : [])
        .filter((m) => m && now - Number(m.ts || 0) <= windowMs)
        .slice(-40);
    }

    function remember(g, ev, text, now) {
      const item = {
        ts: now,
        qq: String(ev.sender?.qq ?? ''),
        name: oneLine(ev.sender?.name || ev.sender?.card || '', 24),
        text: oneLine(text, 240),
      };
      g.recent.push(item);
      if (g.recent.length > 40) g.recent = g.recent.slice(-40);
      return item;
    }

    function pushEvent(e) {
      const st = ensureTriggerState();
      const limit = numOf(bot.cfg?.debugRecentLimit, 20, 5, 100);
      st.events.unshift(e);
      if (st.events.length > Math.max(limit, 100)) st.events = st.events.slice(0, Math.max(limit, 100));
      const g = e?.groupId ? groupState(e.groupId) : null;
      if (g) g.last = e;
      scheduleTriggerSave();
    }

    function canFire(g, mode, cooldownSec, hourlyMax, now) {
      const c = g.counters?.[mode];
      if (c?.lastAt && now - Number(c.lastAt) < Math.max(0, numOf(cooldownSec, 0, 0, 7200)) * 1000) return false;
      if (c?.hour === hourKey(now) && Number(c.count || 0) >= Math.max(1, numOf(hourlyMax, 1, 1, 100))) return false;
      return true;
    }

    function markFire(g, mode, now) {
      const c = g.counters?.[mode] || {};
      g.counters[mode] = {
        hour: hourKey(now),
        count: c.hour === hourKey(now) ? Number(c.count || 0) + 1 : 1,
        lastAt: now,
      };
    }

    function selfNames() {
      const names = splitList(bot.cfg?.selfAliases);
      const n = String(bot?.onebot?.selfNickname || bot?.selfNickname || '').trim();
      if (n) names.push(n);
      return [...new Set(names.map((x) => x.trim()).filter((x) => x.length >= 2))];
    }

    function beginActivity(gid, g, title, from = null) {
      const safeGid = String(gid).replace(/[^\d]/g, '').slice(-12) || 'group';
      const id = `act-${Date.now().toString(36)}-${safeGid}`;
      g.activity = {
        id,
        title: oneLine(title || '长期活动', 60) || '长期活动',
        status: 'active',
        startedAt: nowIso(),
        updatedAt: nowIso(),
        messageCount: 0,
        transcript: [],
        resumedFrom: from,
      };
      g.paused = null;
      scheduleTriggerSave();
      return g.activity;
    }

    function appendActivity(g, ev, text, now) {
      const a = g.activity;
      if (!a) return;
      const max = numOf(bot.cfg?.activityMaxTranscript, 200, 20, 500);
      a.transcript.push({
        ts: nowIso(),
        qq: String(ev.sender?.qq ?? ''),
        name: oneLine(ev.sender?.name || ev.sender?.card || '', 24),
        text: oneLine(text, 600),
      });
      if (a.transcript.length > max) a.transcript = a.transcript.slice(-max);
      a.messageCount = Number(a.messageCount || 0) + 1;
      a.updatedAt = nowIso();
      scheduleTriggerSave();
    }

    function archiveActivity(gid, g, status, reason) {
      const a = g.activity;
      if (!a) return null;
      const record = {
        id: a.id,
        groupId: String(gid),
        title: a.title,
        status,
        reason: String(reason || ''),
        startedAt: a.startedAt,
        endedAt: nowIso(),
        messageCount: Number(a.messageCount || 0),
        resumedFrom: a.resumedFrom || null,
        participants: [...new Set((a.transcript || []).map((m) => m.qq).filter(Boolean))],
        transcript: Array.isArray(a.transcript) ? a.transcript : [],
      };
      let file = null;
      if (bot.cfg?.activityArchive !== false) {
        try {
          file = path.join(archiveDir(), `${a.id}.json`);
          writeJsonAtomic(file, record);
        } catch (e) {
          bot.log?.warn?.(`[ReflexArc] activity archive: ${e.message}`);
          file = null;
        }
      }
      const st = ensureTriggerState();
      st.archives.unshift({
        id: record.id,
        groupId: record.groupId,
        title: record.title,
        status: record.status,
        reason: record.reason,
        startedAt: record.startedAt,
        endedAt: record.endedAt,
        messageCount: record.messageCount,
        file,
      });
      st.archives = st.archives.slice(0, 50);
      g.activity = null;
      g.paused = status === 'paused'
        ? { id: record.id, title: record.title, at: record.endedAt, messageCount: record.messageCount }
        : null;
      scheduleTriggerSave();
      return { ...record, file };
    }

    function maybeIdleEnd(gid, g) {
      if (!g.activity) return false;
      const min = numOf(bot.cfg?.activityIdleEndMin, 0, 0, 1440);
      if (!min) return false;
      const last = Date.parse(g.activity.updatedAt || g.activity.startedAt || '') || 0;
      if (!last || Date.now() - last < min * 60_000) return false;
      archiveActivity(gid, g, 'ended', 'idle');
      return true;
    }

    async function remoteActivity(ev, gid, action, g) {
      if (bot.cfg?.activityEmotionCore === false) return null;
      if (Date.now() < activityRemoteDownUntil) return null;
      const base = String(bot.cfg?.emotionCoreUrl || process.env.EMOTIONCORE_URL || '').trim().replace(/\/+$/, '');
      if (!base) return null;
      const timeout = numOf(bot.cfg?.activityEmotionCoreTimeoutMs, 500, 100, 5000);
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), timeout);
      try {
        const res = await fetch(`${base}/activity`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            text: String(ev.text || ''),
            chatKey: String(ev.chatKey || ''),
            groupId: String(gid),
            sender: { qq: String(ev.sender?.qq ?? ''), name: String(ev.sender?.name || '') },
            active: g.activity ? {
              title: g.activity.title,
              status: g.activity.status,
              messageCount: g.activity.messageCount,
            } : null,
            localAction: action?.action || null,
          }),
          signal: ac.signal,
        });
        if (!res.ok) return null;
        const data = await res.json();
        if (!data?.ok || !data.action) return null;
        const raw = Number(data.confidence);
        const pct = Number.isFinite(raw) ? (raw <= 1 ? raw * 100 : raw) : 100;
        if (pct < numOf(bot.cfg?.activityMinConfidence, 55, 0, 100)) return null;
        activityRemoteDownUntil = 0;
        return { ...data, confidence: pct };
      } catch {
        // 本地服务不可用/超时：60 秒内直接走本地规则，避免活动期间每条都等超时。
        activityRemoteDownUntil = Date.now() + 60_000;
        return null;
      } finally {
        clearTimeout(timer);
      }
    }

    function wakeHint(ev, text) {
      ev.hint = Array.isArray(ev.hint) ? ev.hint : [];
      if (text) ev.hint.push(text);
    }

    function setWake(ev, kind, reason, extra = {}) {
      if (ev.wake) return;
      ev.wake = { kind, reason, ...extra };
      ev.stopReason = `reflex-arc:${kind}`;
    }

    function triggerStatus() {
      const st = ensureTriggerState();
      const cfg = bot.cfg || {};
      const now = Date.now();
      const active = [];
      const paused = [];
      let counters = { related: 0, random: 0, high: 0, activity: 0 };
      for (const [groupId, g] of Object.entries(st.groups || {})) {
        if (g?.activity) {
          active.push({
            groupId,
            id: g.activity.id,
            title: g.activity.title,
            status: g.activity.status,
            startedAt: g.activity.startedAt,
            updatedAt: g.activity.updatedAt,
            messageCount: g.activity.messageCount,
            idleSec: Math.round((now - (Date.parse(g.activity.updatedAt) || now)) / 1000),
          });
        }
        if (g?.paused) {
          paused.push({ groupId, ...g.paused });
        }
        for (const [mode, c] of Object.entries(g?.counters || {})) {
          if (Object.hasOwn(counters, mode) && c?.hour === hourKey(now)) counters[mode] += Number(c.count || 0);
        }
      }
      return {
        enabled: cfg.triggerEnabled === true,
        groups: splitList(cfg.triggerGroups),
        modes: {
          related: cfg.relatedEnabled === true,
          random: cfg.randomEnabled === true,
          high: cfg.highEnabled === true,
          activity: cfg.activityEnabled === true,
        },
        active,
        paused,
        counters,
        archiveCount: Array.isArray(st.archives) ? st.archives.length : 0,
        archives: (Array.isArray(st.archives) ? st.archives : []).slice(0, 5),
        recent: (Array.isArray(st.events) ? st.events : []).slice(0, numOf(cfg.debugRecentLimit, 20, 5, 100)),
        selfNames: selfNames(),
        paths: { state: triggerFile(), archives: archiveDir() },
        fish: fishStatus(),
        debugLog: cfg.debugLog === true,
      };
    }

    async function triggerControl(op, payload = {}) {
      const st = ensureTriggerState();
      const gid = String(payload.groupId || payload.group_id || payload.gid || '').trim();
      const g = gid ? groupState(gid) : null;
      const action = String(op || payload.op || 'status').trim();
      if (action === 'status') return { ok: true, status: triggerStatus() };
      if (action === 'test') {
        const text = String(payload.text || '');
        const cfg = bot.cfg || {};
        const related = scoreRelated(text, {
          selfNames: selfNames(),
          keywords: splitList(cfg.relatedKeywords),
        });
        const highScore = highContextScore({
          recentCount: g ? g.recent.length : 0,
          question: isQuestion(text),
          textLen: text.length,
          lastBotAgoMs: g?.lastBotAt ? Date.now() - g.lastBotAt : null,
          continued: isContinueLike(text),
          minMessages: cfg.highMinMessages,
        });
        return {
          ok: true,
          groupId: gid,
          managed: gid ? isManagedGroup(gid, cfg.triggerGroups) : false,
          activity: detectActivityAction(text, activityPatterns(cfg)),
          related: { ...related, minScore: numOf(cfg.relatedMinScore, 3, 1, 10) },
          high: { score: highScore, chance: highChanceFor(highScore, cfg.highChance) },
          randomChance: numOf(cfg.randomChance, 8, 1, 100),
        };
      }
      if (action === 'fish-reset') {
        fishState = defaultFishState();
        saveFishNow();
        return { ok: true, status: triggerStatus() };
      }
      if (action === 'clear-archives') {
        const st2 = ensureTriggerState();
        st2.archives = [];
        scheduleTriggerSave();
        return { ok: true, status: triggerStatus() };
      }
      if (!gid) return { ok: false, error: '缺少 groupId' };
      if (!g) return { ok: false, error: '群状态未初始化' };
      const cfg = bot.cfg || {};
      if (action === 'reset') {
        g.recent = [];
        g.counters = {};
        g.last = null;
        g.lastBotAt = 0;
        g.activity = null;
        g.paused = null;
        const st2 = ensureTriggerState();
        st2.events = (Array.isArray(st2.events) ? st2.events : []).filter((e) => String(e.groupId) !== gid);
        scheduleTriggerSave();
        return { ok: true, status: triggerStatus() };
      }
      if (action === 'pause') {
        if (!g.activity) return { ok: false, error: '当前没有进行中的活动' };
        const rec = archiveActivity(gid, g, 'paused', 'manual');
        return { ok: true, archived: rec ? { id: rec.id, title: rec.title, file: rec.file } : null, status: triggerStatus() };
      }
      if (action === 'resume') {
        if (!g.paused) return { ok: false, error: '没有已暂停的活动' };
        const from = g.paused;
        beginActivity(gid, g, from.title || '长期活动', from.id);
        scheduleTriggerSave();
        return { ok: true, status: triggerStatus() };
      }
      if (action === 'end' || action === 'interrupt') {
        const rec = g.activity ? archiveActivity(gid, g, action === 'interrupt' ? 'interrupted' : 'ended', 'manual') : null;
        g.paused = null;
        scheduleTriggerSave();
        return { ok: true, archived: rec ? { id: rec.id, title: rec.title, file: rec.file } : null, status: triggerStatus() };
      }
      if (action === 'start') {
        if (g.activity) return { ok: false, error: '已经有进行中的活动' };
        const a = beginActivity(gid, g, payload.title || '手动活动');
        return { ok: true, activity: { id: a.id, title: a.title }, status: triggerStatus() };
      }
      return { ok: false, error: `未知操作：${action}` };
    }

    async function onTriggerWake(ev) {
      const cfg = bot.cfg || {};
      if (cfg.triggerEnabled !== true) return;
      if (!ev || ev.isGroup === false || !ev.groupId) return;
      if (ev.stopped) return;
      const gid = String(ev.groupId);
      if (!isManagedGroup(gid, cfg.triggerGroups)) return;

      const now = Date.now();
      const g = groupState(gid);
      const text = String(ev.text || '').trim();
      const preview = oneLine(text || `[${(ev.images || []).length || 1} 个非文本消息]`, 80);
      pruneRecent(g, now);
      maybeIdleEnd(gid, g);

      const beforeRecent = g.recent.length;
      const alreadyWoken = Boolean(ev.wake);
      remember(g, ev, text, now);

      const patterns = activityPatterns(cfg);
      let action = detectActivityAction(text, patterns);
      let remote = null;
      const touchedActivity = cfg.activityEnabled === true
        && (g.activity || g.paused || action);
      if (touchedActivity && cfg.activityEmotionCore !== false) {
        remote = await remoteActivity(ev, gid, action, g);
        if (remote?.action && remote.action !== 'none' && remote.action !== 'continue') {
          const allowed = ['start', 'pause', 'resume', 'interrupt', 'end'];
          if (allowed.includes(remote.action)) action = { action: remote.action, keyword: action.keyword };
        }
      }

      // ── 活动进行中：优先处理控制词；其余每条都接 ──
      if (g.activity) {
        if (action && ['pause', 'resume', 'interrupt', 'end'].includes(action.action)) {
          // 活动已经在进行中：再说“继续”只是普通发言，不应该被当成控制词跳过。
          if (action.action !== 'resume') {
          const title = g.activity.title;
          appendActivity(g, ev, text, now);
          const rec = archiveActivity(gid, g, action.action === 'pause' ? 'paused' : (action.action === 'interrupt' ? 'interrupted' : 'ended'), remote?.reason || action.keyword);
          setWake(ev, 'activity-control', `activity-${action.action}`, { groupId: gid, activityId: rec?.id });
          wakeHint(ev, `[反射弧/长期活动] 本地把活动「${title}」标记为${action.action === 'pause' ? '暂停' : (action.action === 'interrupt' ? '中断' : '结束')}并归档；这一条只回应用户的这个意图，不要继续推进活动。`);
          pushEvent({
            ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
            mode: 'activity-control', action: 'wake', reason: action.action, score: null,
          });
          bot.log?.info?.(`[ReflexArc] activity ${action.action} group=${gid} ${title}`);
          return;
          }
        }

        appendActivity(g, ev, text, now);
        if (cfg.activityReplyEvery !== false) {
          setWake(ev, 'activity', 'long-activity', { groupId: gid, activityId: g.activity.id, title: g.activity.title });
          wakeHint(ev, `[反射弧/长期活动] 当前活动「${g.activity.title}」进行中（第 ${g.activity.messageCount} 条）；本地判断这一轮该接。接着聊/推进，不要把它当成系统命令；收到暂停/中断/结束会由本地归档。`);
          pushEvent({
            ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
            mode: 'activity', action: 'wake', reason: 'every-message', score: null,
          });
        } else {
          pushEvent({
            ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
            mode: 'activity', action: 'skip', reason: 'monitor-only', score: null,
          });
        }
        return;
      }

      // ── 已暂停：只认继续/结束，不自动接其他消息 ──
      if (g.paused) {
        if (action?.action === 'resume') {
          const from = g.paused;
          const a = beginActivity(gid, g, from.title || '长期活动', from.id);
          appendActivity(g, ev, text, now);
          setWake(ev, 'activity-start', 'activity-resume', { groupId: gid, activityId: a.id });
          wakeHint(ev, `[反射弧/长期活动] 本地收到继续，活动「${a.title}」重新开始（新段 ${a.id}）；这一条可以自然接上。`);
          pushEvent({
            ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
            mode: 'activity', action: 'wake', reason: 'resume', score: null,
          });
          return;
        }
        if (action?.action === 'end' || action?.action === 'interrupt') {
          const title = g.paused.title;
          g.paused = null;
          scheduleTriggerSave();
          setWake(ev, 'activity-control', `activity-${action.action}`, { groupId: gid });
          wakeHint(ev, `[反射弧/长期活动] 本地确认活动「${title}」${action.action === 'end' ? '结束' : '中断'}；之前暂停的段已归档，不要继续推进。`);
          pushEvent({
            ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
            mode: 'activity-control', action: 'wake', reason: action.action, score: null,
          });
          return;
        }
        pushEvent({
          ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
          mode: 'activity', action: 'skip', reason: 'paused', score: null,
        });
        return;
      }

      // ── 自动开始活动 ──
      if (cfg.activityEnabled === true && cfg.activityAutoStart !== false && action?.action === 'start') {
        const a = beginActivity(gid, g, remote?.title || text.slice(0, 40));
        appendActivity(g, ev, text, now);
        setWake(ev, 'activity-start', remote?.reason || 'start-keyword', { groupId: gid, activityId: a.id });
        wakeHint(ev, `[反射弧/长期活动] 本地/EmotionCore 识别到活动开始「${a.title}」；活动期间每条都会接，直到暂停/中断/结束。这一条按开场回应即可。`);
        pushEvent({
          ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
          mode: 'activity', action: 'wake', reason: remote?.reason || action.keyword, score: null,
        });
        bot.log?.info?.(`[ReflexArc] activity start group=${gid} ${a.title}`);
        return;
      }

      // gate-wake 已经因为 @/引用/关键词唤醒：不再叠加普通模式，避免重复计数。
      if (alreadyWoken) {
        pushEvent({
          ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
          mode: 'none', action: 'skip', reason: 'already-woken', score: null,
        });
        return;
      }

      // ── 普通模式：相关 > 高概率 > 随机（每轮最多一个）──
      // 夜间静默只挡主动接话；上面 alreadyWoken（@/引用/关键词）已经提前 return，不受影响。
      const quiet = cfg.quietHoursEnabled === true ? parseQuietHours(cfg.quietHours) : null;
      if (quiet && inQuietHours(now, quiet)) {
        pushEvent({
          ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
          mode: 'none', action: 'skip', reason: 'quiet-hours',
        });
        return;
      }

      let decision = null;
      if (cfg.relatedEnabled === true) {
        const rel = scoreRelated(text, {
          selfNames: selfNames(),
          keywords: splitList(cfg.relatedKeywords),
        });
        const min = numOf(cfg.relatedMinScore, 3, 1, 10);
        if (rel.score >= min
          && (cfg.relatedRequireQuestion !== true || rel.question)
          && canFire(g, 'related', cfg.relatedCooldownSec, cfg.relatedHourlyMax, now)) {
          decision = { mode: 'related', score: rel.score, reason: rel.matched.join('+') || 'score' };
        }
      }
      if (!decision && cfg.highEnabled === true) {
        const hscore = highContextScore({
          recentCount: beforeRecent,
          question: isQuestion(text),
          textLen: text.length,
          lastBotAgoMs: g.lastBotAt ? now - g.lastBotAt : null,
          continued: isContinueLike(text),
          minMessages: cfg.highMinMessages,
        });
        const chance = highChanceFor(hscore, cfg.highChance);
        if (hscore >= numOf(cfg.highMinScore, 3, 2, 7)
          && (cfg.highRequireQuestion !== true || isQuestion(text))
          && canFire(g, 'high', cfg.highCooldownSec, cfg.highHourlyMax, now)
          && probabilityHit(chance)) {
          decision = { mode: 'high', score: hscore, chance, reason: 'hot-context' };
        }
      }
      if (!decision && cfg.randomEnabled === true) {
        const minChars = numOf(cfg.randomMinChars, 4, 0, 200);
        const chance = numOf(cfg.randomChance, 8, 1, 100);
        if (text.length >= minChars
          && !text.startsWith('/')
          && canFire(g, 'random', cfg.randomCooldownSec, cfg.randomHourlyMax, now)
          && probabilityHit(chance)) {
          decision = { mode: 'random', score: null, chance, reason: 'dice' };
        }
      }

      if (!decision) {
        if (cfg.debugLog === true) bot.log?.info?.(`[ReflexArc] skip group=${gid} ${preview}`);
        pushEvent({
          ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
          mode: 'none', action: 'skip', reason: 'no-mode-hit', score: null,
        });
        return;
      }

      markFire(g, decision.mode, now);
      setWake(ev, `reflex-${decision.mode}`, decision.reason, { groupId: gid, score: decision.score });
      if (decision.mode === 'related') {
        wakeHint(ev, `[反射弧/相关] 本地判断这条和你有关（score=${decision.score}，${decision.reason}）；可以自然接话，不想接就短回。`);
      } else if (decision.mode === 'high') {
        wakeHint(ev, `[反射弧/高概率] 本地判断群里正在热聊（score=${decision.score}，p=${decision.chance}%）；可以接一句，别抢话。`);
      } else {
        wakeHint(ev, `[反射弧/随机] 本地随机抽到这一轮接话（p=${decision.chance}%）；没有特别理由，短句即可。`);
      }
      pushEvent({
        ts: nowIso(), groupId: gid, qq: String(ev.sender?.qq ?? ''), preview,
        mode: decision.mode, action: 'wake', reason: decision.reason, score: decision.score,
      });
      if (cfg.debugLog === true) bot.log?.info?.(`[ReflexArc] wake ${decision.mode} group=${gid} score=${decision.score} ${preview}`);
    }

    // 鱼群拦截必须在 gate-wake/commands 之前；只记录，不建立模型回合。
    const offFishGate = typeof bot.on === 'function'
      ? bot.on('pre-gate', (ev) => {
        try { onFishGate(ev) } catch (e) { bot.log?.warn?.(`[ReflexArc] fish gate: ${e.message}`) }
      }, { order: 1 })
      : null;
    const offTriggerWake = typeof bot.on === 'function'
      ? bot.on('wake', onTriggerWake, { order: 26 })
      : null;
    const offAfterSend = bot.onAfterSend?.((out) => {
      try {
        const target = String(out?.target || '');
        // 模型自己报的骰子数字和本地掷的不一致 → 记下来，下一轮提醒（本地为准）
        const roll = target ? lastRoll.get(target) : null;
        if (roll && out?.text) {
          const mm = findDiceClaimMismatch(`${roll.expr} = ${roll.total}`, String(out.text));
          if (mm) diceMismatch.set(target, mm);
        }
        const m = target.match(/^group:(\d+)$/);
        if (!m) return;
        const g = groupState(m[1]);
        g.lastBotAt = Date.now();
        scheduleTriggerSave();
      } catch {}
    });
    bot.onDispose?.(() => {
      try { offFishGate?.() } catch {}
      try { offTriggerWake?.() } catch {}
      try { offAfterSend?.() } catch {}
      if (trigSaveTimer) clearTimeout(trigSaveTimer);
      trigSaveTimer = null;
      if (fishSaveTimer) clearTimeout(fishSaveTimer);
      fishSaveTimer = null;
      saveFishNow();
      saveTriggerStateNow();
      trigDisposed = true;
    });
    if (bot.shared && typeof bot.shared === 'object') {
      bot.shared.reflexArc = { status: triggerStatus, control: triggerControl };
    }

    function readImageUrl(img) {
      const url = String(img?.url || '').trim();
      if (/^https?:\/\//i.test(url)) return url;
      return '';
    }

    async function analyzeOneImage(ev) {
      // 实测本地 qwen3-vl 2B 一张图约 24 秒（CPU），默认关；要开请在控制台打开 localVision。
      if (bot?.cfg?.localVision !== true) return;
      const images = Array.isArray(ev?.images) ? ev.images : [];
      const first = images.find((x) => x && !x.isSticker && readImageUrl(x));
      if (!first) return;
      const base = String(bot?.cfg?.emotionCoreUrl || process.env.EMOTIONCORE_URL || '').trim();
      const model = String(bot?.cfg?.visionModel || '').trim();
      if (!base || !model) return;
      const timeout = Math.max(1000, Math.min(120000, Number(bot?.cfg?.visionTimeoutMs) || 20000));
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), timeout);
      try {
        const imgRes = await fetch(readImageUrl(first), { signal: ac.signal });
        if (!imgRes.ok) return;
        const buf = Buffer.from(await imgRes.arrayBuffer());
        if (buf.length > 8 * 1024 * 1024) return;
        const body = {
          model,
          prompt: '用中文简短描述这张图片的内容，并尽量读出图中可见文字。不超过120字；看不清就直说看不清，不要猜。',
          images: [buf.toString('base64')],
          stream: false,
          options: { temperature: 0.1, num_predict: 140 },
        };
        const aiRes = await fetch('http://127.0.0.1:11434/api/generate', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(body),
          signal: ac.signal,
        });
        if (!aiRes.ok) return;
        const data = await aiRes.json();
        const text = String(data?.response || '').replace(/\s+/g, ' ').trim();
        if (text) {
          ev.hint.push(`[反射弧/视觉] ${text.slice(0, 260)}（本地只做粗略看；要细看细节，请调用你自己的多模态能力）`);
          ev._scratch = ev._scratch || Object.create(null);
          ev._scratch['reflex-arc:vision'] = true;
          bot.log?.info?.(`[ReflexArc] vision ${text.slice(0, 80)}`);
        }
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] vision failed: ${e.message}`);
      } finally {
        clearTimeout(timer);
      }
    }

    // ── 本地粗看：过长/过大的截图先本地 OCR，只把文字交给模型 ──────────────
    // 运行顺序很关键：本钩子必须排在 kernel:context（order 50）之后，否则 ev.imagePaths
    // 还没被内核填好，插件拿不到图。reflex-arc 自己的 order 是 36，所以这里显式写 60。
    const COARSE_OCR_SCRIPT = [
      'import sys, json',
      'try:',
      '    from PIL import Image',
      '    from rapidocr_onnxruntime import RapidOCR',
      'except Exception as e:',
      '    print(json.dumps({"ok": False, "error": "deps: %s" % e}))',
      '    raise SystemExit(0)',
      'import numpy as np',
      'path = sys.argv[1]',
      'try:',
      '    im = Image.open(path).convert("RGB")',
      'except Exception as e:',
      '    print(json.dumps({"ok": False, "error": "open: %s" % e}))',
      '    raise SystemExit(0)',
      'w, h = im.size',
      'max_tiles = int(sys.argv[2]) if len(sys.argv) > 2 else 4',
      'tile_h, overlap, max_w = 1600, 160, 1600',
      'engine = RapidOCR()',
      'lines, prev, tiles, y = [], [], 0, 0',
      'while y < h and tiles < max_tiles:',
      '    tile = im.crop((0, y, w, min(h, y + tile_h)))',
      '    if tile.width > max_w:',
      '        r = max_w / tile.width',
      '        tile = tile.resize((max_w, max(1, int(tile.height * r))))',
      '    res, _ = engine(np.array(tile))',
      '    for item in (res or []):',
      '        t = str(item[1]).strip()',
      '        if t and t not in prev:',
      '            lines.append(t)',
      '            prev = (prev + [t])[-3:]',
      '    tiles += 1',
      '    if y + tile_h >= h:',
      '        break',
      '    y += tile_h - overlap',
      'print(json.dumps({"ok": True, "width": w, "height": h, "tiles": tiles, "text": "\\n".join(lines)}))',
    ].join('\n');

    /** 读文件头（不解码整图）。 */
    function readHead(file, bytes = 65536) {
      const fd = fs.openSync(file, 'r');
      try {
        const buf = Buffer.alloc(bytes);
        const n = fs.readSync(fd, buf, 0, bytes, 0);
        return buf.subarray(0, n);
      } finally {
        fs.closeSync(fd);
      }
    }

    /** 从文件头拿宽高：PNG / GIF / WebP / JPEG。拿不到返回 null。 */
    function readImageSize(buf) {
      try {
        if (buf.length > 24 && buf[0] === 0x89 && buf[1] === 0x50) {
          return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
        }
        if (buf.length > 10 && buf.toString('ascii', 0, 3) === 'GIF') {
          return { width: buf.readUInt16LE(6), height: buf.readUInt16LE(8) };
        }
        if (buf.length > 30 && buf.toString('ascii', 0, 4) === 'RIFF' && buf.toString('ascii', 8, 12) === 'WEBP') {
          const kind = buf.toString('ascii', 12, 16);
          if (kind === 'VP8X') return { width: 1 + buf.readUIntLE(24, 3), height: 1 + buf.readUIntLE(27, 3) };
          if (kind === 'VP8 ') return { width: buf.readUInt16LE(26) & 0x3fff, height: buf.readUInt16LE(28) & 0x3fff };
          if (kind === 'VP8L') {
            const b = buf.readUInt32LE(21);
            return { width: (b & 0x3fff) + 1, height: ((b >> 14) & 0x3fff) + 1 };
          }
        }
        if (buf.length > 4 && buf[0] === 0xff && buf[1] === 0xd8) {
          let i = 2;
          while (i + 9 < buf.length) {
            if (buf[i] !== 0xff) { i += 1; continue; }
            const marker = buf[i + 1];
            if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd9)) { i += 2; continue; }
            const len = buf.readUInt16BE(i + 2);
            if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
              return { height: buf.readUInt16BE(i + 5), width: buf.readUInt16BE(i + 7) };
            }
            i += 2 + len;
          }
        }
      } catch { /* 头不完整 → 当未知 */ }
      return null;
    }

    function ocrPython() {
      const configured = String(bot?.cfg?.coarseVisionPython || '').trim();
      if (configured) return configured;
      const fromEnv = String(process.env.SOULCORE_PYTHON || process.env.DSH_PYTHON || '').trim();
      if (fromEnv) return fromEnv;
      const runtime = path.join(process.env.USERPROFILE || '', '.dsh', 'dsh-runtimes',
        'dsh-primary-runtime', 'dependencies', 'python', 'python.exe');
      if (runtime && fs.existsSync(runtime)) return runtime;
      return 'python';
    }

    /** 跑本地 OCR。任何时候都 resolve，失败带 error，绝不拖死这一轮。 */
    function runOcr(file, timeoutMs, maxTiles) {
      return new Promise((resolve) => {
        execFile(
          ocrPython(),
          ['-c', COARSE_OCR_SCRIPT, file, String(maxTiles)],
          { timeout: timeoutMs, windowsHide: true, maxBuffer: 4 * 1024 * 1024 },
          (error, stdout) => {
            const raw = String(stdout || '').trim();
            if (!raw) return resolve({ ok: false, error: error ? String(error.message || error) : '无输出' });
            try {
              resolve(JSON.parse(raw));
            } catch {
              resolve({ ok: false, error: 'OCR 输出不是 JSON' });
            }
          },
        );
      });
    }

    // 粗看摘掉的那张图（QQ 默认画质，不是原图）留个路径；模型要"看一眼"时本地回灌，
    // 不用让主人重发，也不额外调用任何外部服务。
    const pendingLook = new Map(); // chatKey -> { path, mediaType, at }
    const LOOK_TTL_MS = 10 * 60 * 1000;

    function rememberLook(chatKey, file, mediaType) {
      const key = String(chatKey || '').trim();
      if (!key || !file) return;
      pendingLook.set(key, { path: file, mediaType: mediaType || 'image/jpeg', at: Date.now() });
      if (pendingLook.size > 50) {
        for (const [k, v] of pendingLook) {
          if (Date.now() - v.at > LOOK_TTL_MS) pendingLook.delete(k);
        }
      }
    }

    /**
     * 把上次粗看摘掉的图以图片块回灌到下一轮（内核 dsh 驱动直接 prompt）。
     * 返回 { ok, queued } 或 { ok:false, error }。供 ec 的 look 动作调用。
     */
    async function lookAtImage(chatKey, note) {
      const key = String(chatKey || '').trim();
      if (bot?.cfg?.coarseLookBack === false) return { ok: false, error: '取原图功能已关闭（反射弧 → 长图粗看）' };
      // P0-2：先查本地队列（普通截图也在里面），再退回旧的 pendingLook
      const queue = readImageQueue(key);
      if (queue.length) {
        const rec0 = queue[Number(note?.index || 0)] || queue[0];
        try {
          const buf0 = fs.readFileSync(rec0.path);
          const dsh0 = bot?.dsh;
          if (!dsh0 || typeof dsh0.ensureSession !== 'function' || typeof dsh0.prompt !== 'function') {
            return { ok: false, error: '内核不支持回灌图片' };
          }
          const sid0 = await dsh0.ensureSession(key);
          const head0 = '（反射弧回灌）这是本地队列里的图（QQ 默认画质），直接看图即可，不用复述收到。';
          const noteText = typeof note === 'string' ? note : String(note?.note || '');
          await dsh0.prompt(sid0, noteText ? head0 + '\n' + noteText : head0, [{
            mediaType: rec0.mediaType || 'image/jpeg',
            data: buf0.toString('base64'),
            name: 'qq-image',
          }]);
          return { ok: true, queued: true, bytes: buf0.length, from: 'queue' };
        } catch (e) {
          return { ok: false, error: '队列里的图读不出来：' + e.message };
        }
      }
      const rec = pendingLook.get(key);
      if (!rec) return { ok: false, error: '本地队列里没有图（30 分钟内没收到图，或已被清理）' };
      if (Date.now() - rec.at > LOOK_TTL_MS) {
        pendingLook.delete(key);
        return { ok: false, error: '待看的图已过期（超过 10 分钟）' };
      }
      let buf = null;
      try {
        buf = fs.readFileSync(rec.path);
      } catch (e) {
        pendingLook.delete(key);
        return { ok: false, error: `图已不在：${e.message}` };
      }
      const dsh = bot?.dsh;
      if (!dsh || typeof dsh.ensureSession !== 'function' || typeof dsh.prompt !== 'function') {
        return { ok: false, error: '内核不支持回灌图片' };
      }
      const sid = await dsh.ensureSession(key);
      pendingLook.delete(key);
      const head = '（反射弧回灌）这是上一张图的 QQ 默认画质版本，直接看图即可，不用复述"收到"。';
      await dsh.prompt(sid, note ? `${head}\n${note}` : head, [{
        mediaType: rec.mediaType || 'image/jpeg',
        data: buf.toString('base64'),
        name: 'qq-image',
      }]);
      return { ok: true, queued: true, bytes: buf.length };
    }

    // 暴露给其它插件（ec 的 look 动作）：功能仍归反射弧所有。
    try {
      if (bot?.shared) bot.shared.lookAtImage = lookAtImage;
    } catch { /* shared 只读时忽略 */ }

    async function coarseLookLongImages(ev) {
      const cs = bot?.cfg || {};
      // 只有显式关掉才关：老配置里没有这个键时按 schema 默认（开）走。
      if (cs.coarseVision === false) return;
      const parts = Array.isArray(ev?.imageParts) ? ev.imageParts : [];
      const paths = Array.isArray(ev?.imagePaths) ? ev.imagePaths : [];
      if (!parts.length || !paths.length) return;
      const ratio = Math.max(120, Number(cs.coarseVisionLongRatio) || 250) / 100;
      const maxPixels = Math.max(0, Number(cs.coarseVisionPixels) || 0);
      const maxChars = Math.max(80, Math.min(4000, Number(cs.coarseVisionMaxChars) || 800));
      const timeout = Math.max(2000, Number(cs.coarseVisionTimeoutMs) || 60000);
      const maxTiles = Math.max(1, Math.min(16, Number(cs.coarseVisionMaxTiles) || 4));
      const keep = cs.coarseVisionKeepOriginal === true;
      const drop = new Set();
      const notes = [];
      for (let i = 0; i < paths.length; i += 1) {
        if (!parts[i]) continue;
        const file = String(paths[i] || '');
        if (!file) continue;
        let size = 0;
        let head = null;
        try {
          size = fs.statSync(file).size;
          head = readHead(file);
        } catch {
          continue;
        }
        const dims = readImageSize(head);
        if (!dims?.width || !dims?.height) continue;
        const { width, height } = dims;
        const long = height / width >= ratio;
        const huge = maxPixels > 0 && width * height > maxPixels;
        if (!long && !huge) continue;
        const res = await runOcr(file, timeout, maxTiles);
        const text = String(res?.text || '').trim();
        if (!res?.ok || !text) {
          bot.log?.warn?.(`[ReflexArc] 粗看跳过 ${width}x${height}：${res?.error || 'OCR 无结果'}（保留原图）`);
          continue;
        }
        const clipped = text.replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').slice(0, maxChars).trim();
        notes.push(`【反射弧/粗看】${width}×${height}（${Math.max(1, Math.round(size / 1024))}KB）本地 OCR 只读了文字：\n${clipped}`);
        if (!keep) drop.add(i);
      }
      if (!notes.length) return;
      const chatKey = String(ev?.chatKey || (ev?.groupId ? `group:${ev.groupId}` : ''));
      ev.hint.push(`${notes.join('\n---\n')}\n（这是本地 OCR 粗看，不是完整画面；要看图就说一声，直接调用 mcp__qq__ec(action="look") 调出这张图，不用让主人重发。）`);
      if (drop.size) {
        ev.imageParts = parts.filter((_, i) => !drop.has(i));
        ev._scratch = ev._scratch || Object.create(null);
        ev._scratch['reflex-arc:coarse'] = drop.size;
        const first = [...drop][0];
        rememberLook(chatKey, paths[first], parts[first]?.mediaType);
        rememberImage(chatKey, paths[first], parts[first]?.mediaType, { ocrText: notes[0] || '', status: 'coarse' });
      }
      bot.log?.info?.(`[ReflexArc] 粗看 ${notes.length} 张长图（省掉原图 ${drop.size} 张）`);
    }

    // ── S4：双侧取词 + 定向 1 + 随机 1 ────────────────────────────────
    // 只拿对方这句当 query，会漏掉"她刚说过什么"；而只用她的话，又会跑题。
    // 所以 query = 对方这句 + 她最近 2 句，拼到 64 字为止。
    const recentSaid = new Map();   // chatKey -> [{text, at}] 最多 3 条
    const SAID_MAX = 3;
    const QUERY_MAX = 64;
    // S5：recall 提示的冷却，避免每轮都出现同一句
    const RECALL_TIP_GAP_MS = 30 * 60 * 1000;
    const recallTipSeen = new Map();   // chatKey -> 上次提示时刻

    // ── P1-2 本地格式检查 ────────────────────────────────────────────
    // 出站链路（内核 deliver）只管脱敏/拆长/引用，不管"她说了不该说的东西"。
    // 这里在发送后本地查一遍，只记"真发生过"的那一条；下一轮开头用一句回执点出来，
    // 说完就清——不是每轮都说，也不改内核。
    const formatIssues = new Map();   // chatKey -> {reason, at}
    const FORMAT_ISSUE_TTL_MS = 30 * 60 * 1000;

    function checkOutgoingFormat(text) {
      const s = String(text || '');
      if (!s.trim()) return '空消息';
      if (/\[CQ:|\[\[(reply|send|at|image)|mcp__qq__ec|"action"\s*:\s*"/i.test(s)) return '内部标记/工具语法漏进了消息';
      if (/^\[(记忆联想|场景|反射弧)/.test(s.trim()) || /【反射弧/.test(s)) return '把本地提示当成要说的话发出来了';
      if (/（想深一点就 recall）|\(想深一点就 recall\)/.test(s)) return '把 recall 提示当正文了';
      if (/\n{3,}/.test(s)) return '空行太多';
      if (s.length > 600) return `单条太长（${s.length} 字，应该拆成 ≤3 条）`;
      return '';
    }

    /** 下一轮开头：如果上一条格式出过问题，只说一次，然后清掉。 */
    function injectFormatFix(ev) {
      const key = String(ev?.chatKey || (ev?.groupId ? 'group:' + ev.groupId : '') || 'default');
      const issue = formatIssues.get(key);
      if (!issue) return;
      if (Date.now() - Number(issue.at || 0) > FORMAT_ISSUE_TTL_MS) {
        formatIssues.delete(key);
        return;
      }
      formatIssues.delete(key);
      ev.hint.push('[反射弧/格式] 上一条发出去的样子有问题：' + issue.reason
        + '。这条按「先结论、再细节、不超过 3 条、不留内部标记」来。');
      bot.log?.info?.('[ReflexArc] 格式回执: ' + issue.reason);
    }

    function noteSaid(rec) {
      try {
        const key = String(rec?.target || '');
        const spoken = String(rec?.text || '').replace(/\s+/g, ' ').trim();
        if (!key || !spoken) return;
        const fmtIssue = checkOutgoingFormat(spoken);
        if (fmtIssue) {
          formatIssues.set(key, { reason: fmtIssue, at: Date.now() });
          bot.log?.info?.('[ReflexArc] 上一条格式有问题: ' + fmtIssue);
        }
        const list = recentSaid.get(key) || [];
        list.push({ text: spoken.slice(0, 120), at: Date.now() });
        while (list.length > SAID_MAX) list.shift();
        recentSaid.set(key, list);
      } catch (e) {
        bot.log?.debug?.(`[ReflexArc] noteSaid 失败: ${e.message}`);
      }
    }
    if (typeof bot.onAfterSend === 'function') bot.onAfterSend(noteSaid);

    /** 去掉 CQ 码/@/方括号前缀，压缩空白。 */
    function cleanForQuery(text) {
      return String(text || '')
        .replace(/\[CQ:[^\]]*\]/g, ' ')
        .replace(/^\[[^\]]+\]:\s*/, '')
        .replace(/\s+/g, ' ')
        .trim();
    }

    /** 问句去框架：把"你还记得…吗/那个叫什么来着"这层壳剥掉，只留内容词。
     *  留着壳会让 query 撞上一堆"你还记得…"的元问句，捞回来的都是问句不是事实。 */
    function deFrameQuery(text) {
      const raw = String(text || '').trim();
      if (!raw) return '';
      let s = raw
        .replace(/[？?]+$/g, '')
        .replace(/(吗|么|嘛|吧)\s*\$/g, '')
        .replace(/^你(还)?记得\s*/g, ' ')
        .replace(/^(那个|那件事|那次|上次(说的|讲的)?)\s*/g, ' ')
        .replace(/叫什么来着|叫啥来着|来着|忘记了|忘了/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
      // 剥空了就退回原句——宁可带壳，也别让 query 变成空串
      return s.length >= 2 ? s : raw;
    }

    /** 时间锚：认"昨天/前天/今天/上个月/10月4日/10号"这类，给召回做本地路由。
     *  只做"同一口径的优先"，不硬过滤——锚猜错了不该把记忆全掐掉。 */
    function parseTimeAnchor(text) {
      const t = String(text || '');
      const now = new Date();
      const day = 86400000;
      const shift = (n) => {
        const d = new Date(now.getTime() - n * day);
        return { y: d.getFullYear(), m: d.getMonth() + 1, d: d.getDate() };
      };
      if (/今天/.test(t)) return { label: '今天', ...shift(0) };
      if (/昨天/.test(t)) return { label: '昨天', ...shift(1) };
      if (/前天/.test(t)) return { label: '前天', ...shift(2) };
      const md = /(\d{1,2})\s*月\s*(?:(\d{1,2})\s*[日号]?)?/.exec(t);
      if (md) {
        const m = Number(md[1]);
        if (m >= 1 && m <= 12) {
          if (md[2]) {
            const d = Number(md[2]);
            if (d >= 1 && d <= 31) return { label: `${m}月${d}日`, y: null, m, d };
          }
          return { label: `${m}月`, y: null, m, d: null };
        }
      }
      const dd = /(\d{1,2})\s*[日号]/.exec(t);
      if (dd) {
        const d = Number(dd[1]);
        if (d >= 1 && d <= 31) return { label: `${d}日`, y: null, m: null, d };
      }
      if (/上(个)?月/.test(t)) {
        const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
        return { label: '上个月', y: d.getFullYear(), m: d.getMonth() + 1, d: null };
      }
      return null;
    }

    /** item.when 形如 "10-04" / "2026-10-04 12:00"；只比较月/日这一段。 */
    function anchorMatches(whenStr, anchor) {
      if (!anchor) return false;
      const w = String(whenStr || '');
      if (!w) return false;
      const mmdd = /(\d{1,2})-(\d{1,2})/.exec(w);
      if (!mmdd) return false;
      const m = Number(mmdd[1]);
      const d = Number(mmdd[2]);
      if (anchor.m && m !== anchor.m) return false;
      if (anchor.d && d !== anchor.d) return false;
      return true;
    }

    function buildRecallQuery(ev) {
      // P1-3：先剥问句框架再拼 query（带壳会撞上一堆元问句）
      const head = cleanForQuery(deFrameQuery(ev?.text));
      if (!head) return '';
      const tails = (recentSaid.get(String(ev?.chatKey || '')) || [])
        .slice(-2)
        .map((x) => cleanForQuery(x.text))
        .filter((x) => x.length >= 2);
      let query = head.slice(0, QUERY_MAX);
      for (const tail of tails) {
        if (query.length >= QUERY_MAX) break;
        // 她说过的话已经在 query 里就跳过（避免同一句加权两次）
        if (query.includes(tail.slice(0, 6))) continue;
        const room = QUERY_MAX - query.length - 1;
        if (room < 4) break;
        query += ' ' + tail.slice(0, room);
      }
      return query.trim();
    }

    /** 久未触发加成：越久没被想起，越容易被随机抽到；上限 +15%。 */
    function stalenessBonus(lastHit, nowMs) {
      if (!lastHit) return 0.15;
      const then = Date.parse(String(lastHit).replace(/\s/, 'T'));
      if (!Number.isFinite(then)) return 0.15;
      const days = Math.max(0, (nowMs - then) / 86400000);
      return Math.min(0.15, (days / 30) * 0.15);
    }

    /**
     * 定向 1（最高分，必须有分）+ 随机 1（其余按 分数² 加权抽，可能抽空）。
     * 随机那条是"偶尔想起别的"，不是"随机给一条"——所以池子空了就不给。
     */
    function pickDirectedAndRandom(items, nowMs) {
      const weighted = items.map((it) => {
        const base = Number(it.score ?? it.rrf_adjusted ?? it.rrf_score ?? 0) || 0;
        const w = Math.max(0, base) * (1 + stalenessBonus(it.last_hit, nowMs));
        return { it, w };
      }).filter((x) => x.w > 0);
      if (!weighted.length) return [];
      weighted.sort((a, b) => b.w - a.w);
      const picked = [weighted[0].it];
      const pool = weighted.slice(1);
      if (pool.length) {
        const total = pool.reduce((sum, x) => sum + x.w * x.w, 0);
        if (total > 0) {
          let roll = Math.random() * total;
          for (const cell of pool) {
            roll -= cell.w * cell.w;
            if (roll <= 0) { picked.push(cell.it); break; }
          }
          if (picked.length === 1) picked.push(pool[pool.length - 1].it);
        }
      }
      return picked;
    }

    // ── 消费睡眠整理的轮换标记 ────────────────────────────────────────
    // 睡眠/日结跑完会写 state/session-rotate-pending.json；这里在下一轮开始时
    // 归档旧会话并删掉映射。放到下一轮而不是睡眠当时，是因为睡眠是独立 python 进程，
    // 它拿不到内核的 archive()。
    function rotateMarkerFile() {
      return path.join(arcDataDir(), 'state', 'session-rotate-pending.json');
    }

    function sessionOfKey(key) {
      const d = bot?.dsh || {};
      try {
        return String(d.sessionOf?.(key) ?? d.getSession?.(key)
          ?? (typeof d.sessions?.get === 'function' ? d.sessions.get(key) : '') ?? '');
      } catch {
        return '';
      }
    }

    async function forgetKey(key) {
      const d = bot?.dsh || {};
      try {
        if (typeof d.forget === 'function') { await d.forget(key); return true; }
        if (typeof d.resetSession === 'function') { await d.resetSession(key); return true; }
        if (typeof d.sessions?.delete === 'function') { d.sessions.delete(key); d.saveSessions?.(); return true; }
      } catch (e) {
        bot.log?.warn?.('[ReflexArc] 删会话映射失败 ' + key + ': ' + e.message);
      }
      return false;
    }

    function clearLineState(key) {
      const st = bot.state?.get?.(key);
      if (!st) return;
      st.followUpUntil = 0;
      st.followUpCache = null;
      st.lastContextId = null;
      if (st._scratch) delete st._scratch['group-memory:seen'];
    }

    async function consumeSessionRotate(ev) {
      const file = rotateMarkerFile();
      let marker = null;
      try {
        marker = JSON.parse(fs.readFileSync(file, 'utf8'));
      } catch {
        return;   // 没有标记就是常态
      }
      const d = bot?.dsh || {};
      let keys = [];
      try {
        if (typeof d.listChatKeys === 'function') keys = d.listChatKeys().map(String);
      } catch { keys = []; }
      if (!keys.length) {
        const cur = String(ev?.chatKey || '');
        keys = cur ? [cur] : ['__single__'];
        if (!keys.includes('__single__')) keys.push('__single__');
      }
      const oldSid = String(marker?.sid || '') || sessionOfKey(keys[0]);
      let archived = false;
      if (oldSid && typeof d.archive === 'function') {
        try {
          await d.archive(oldSid);
          archived = true;
        } catch (e) {
          bot.log?.warn?.('[ReflexArc] 归档旧会话失败 ' + oldSid + ': ' + e.message);
        }
      }
      let forgot = 0;
      for (const key of keys) {
        if (await forgetKey(key)) forgot += 1;
        clearLineState(key);
      }
      try {
        fs.unlinkSync(file);
      } catch { /* 已删就算了 */ }
      bot.log?.info?.('[ReflexArc] 睡眠轮换：旧会话 ' + (oldSid || '无') + ' 归档=' + archived
        + ' 清映射 ' + forgot + '/' + keys.length + ' 原因=' + String(marker?.reason || ''));
      ev._scratch = ev._scratch || Object.create(null);
      ev._scratch['reflex-arc:rotated'] = true;
    }

    // ── P0-3：每 N 轮重述一次固定约定 ──────────────────────────────────
    // 只数轮次，不估 token：单会话跑到几十轮后，先丢的总是工具清单和格式约定，
    // 而它们是逐字不变的，所以到点原样再说一遍最省。
    const TOOL_CARD = '[反射弧/维护] 固定约定（每 N 轮重述，内容不变）：工具是 mcp__qq__ec；动作只有 '
      + 'send/reply/image/sticker/at/look/user/history/groups；群里回群、私聊回人（以本轮场景行为准）；'
      + 'reply 带上 message_id；长内容拆成不超过 3 条，先给结论再给细节。';

    function turnCountFile() {
      return path.join(arcDataDir(), 'state', 'reflex-turncount.json');
    }

    function readTurnCounts() {
      try {
        const raw = JSON.parse(fs.readFileSync(turnCountFile(), 'utf8'));
        return raw && typeof raw === 'object' ? raw : {};
      } catch {
        return {};
      }
    }

    function saveTurnCounts(state) {
      try {
        const file = turnCountFile();
        fs.mkdirSync(path.dirname(file), { recursive: true });
        fs.writeFileSync(file, JSON.stringify(state), 'utf8');
      } catch (e) {
        bot.log?.warn?.('[ReflexArc] turncount: ' + e.message);
      }
    }

    function maybeReinjectToolCard(ev) {
      const every = Number(bot?.cfg?.reinjectEveryTurns);
      if (!Number.isFinite(every) || every <= 0) return 0;
      const key = String(ev?.chatKey || (ev?.groupId ? 'group:' + ev.groupId : '') || 'default');
      const state = readTurnCounts();
      const rec = state[key] || { n: 0 };
      rec.n = Number(rec.n || 0) + 1;
      state[key] = rec;
      if (rec.n % Math.round(every) !== 0) {
        saveTurnCounts(state);
        return rec.n;
      }
      ev.hint.push(TOOL_CARD + '（本窗口第 ' + rec.n + ' 轮）');
      saveTurnCounts(state);
      bot.log?.info?.('[ReflexArc] 第 ' + rec.n + ' 轮重述工具约定 ' + key);
      return rec.n;
    }

    // ── 联想去重（盲点修补）──────────────────────────────────────────
    // 如果这轮要给的联想跟最近给过的（或跟对方刚说的那句）语义相同，
    // 她只会顺着同一句打转。规则：候选池里换一条；池里全重复就不给。
    const MEMORY_HINT_KEEP_MS = 24 * 60 * 60 * 1000;
    const MEMORY_HINT_MAX = 8;

    function arcDataDir() {
      return bot?.core?.dataDir || bot?.dataDir || process.cwd();
    }

    function memoryHintFile() {
      return path.join(arcDataDir(), 'state', 'reflex-memory-hints.json');
    }

    function readMemoryHints() {
      try {
        const raw = JSON.parse(fs.readFileSync(memoryHintFile(), 'utf8'));
        return raw && typeof raw === 'object' ? raw : {};
      } catch {
        return {};
      }
    }

    function saveMemoryHints(state) {
      try {
        const file = memoryHintFile();
        fs.mkdirSync(path.dirname(file), { recursive: true });
        fs.writeFileSync(file, JSON.stringify(state), 'utf8');
      } catch (e) {
        bot.log?.warn?.('[ReflexArc] memory hint state: ' + e.message);
      }
    }

    function normHintText(s) {
      return String(s || '').replace(/[^0-9a-zA-Z\u4e00-\u9fff]/g, '').toLowerCase();
    }

    function hintSimilar(a, b) {
      const na = normHintText(a);
      const nb = normHintText(b);
      if (!na || !nb) return false;
      if (na === nb) return true;
      if (na.length < 8 || nb.length < 8) return false;
      const ga = new Set();
      for (let i = 0; i < na.length - 1; i += 1) ga.add(na.slice(i, i + 2));
      const gb = new Set();
      for (let i = 0; i < nb.length - 1; i += 1) gb.add(nb.slice(i, i + 2));
      if (!ga.size || !gb.size) return false;
      let hit = 0;
      for (const x of ga) if (gb.has(x)) hit += 1;
      return hit / (ga.size + gb.size - hit) >= 0.85;
    }

    function recentHints(state, chatKey) {
      const now = Date.now();
      const rec = state[chatKey] || { items: [] };
      return (rec.items || [])
        .filter((x) => x && now - Number(x.at || 0) < MEMORY_HINT_KEEP_MS)
        .slice(-MEMORY_HINT_MAX);
    }

    function hintAlreadyUsed(state, chatKey, item, incomingText) {
      const items = recentHints(state, chatKey);
      const text = String(item?.text || '');
      if (items.some((x) => x.id && x.id === String(item?.memory_id || ''))) return 'same-id';
      if (items.some((x) => hintSimilar(x.text, text))) return 'same-text';
      if (incomingText && hintSimilar(incomingText, text)) return 'echo-user';
      return '';
    }

    function rememberHint(state, chatKey, item) {
      const items = recentHints(state, chatKey);
      items.push({ id: String(item?.memory_id || ''), text: String(item?.text || '').slice(0, 240), at: Date.now() });
      state[chatKey] = { items: items.slice(-MEMORY_HINT_MAX) };
      saveMemoryHints(state);
    }

    // ── 图片本地队列（P0-2）───────────────────────────────────────────
    // 以前只有"长图被摘掉"才留路径；普通截图既不落盘也不留档，
    // 而 QQ 给的是临时文件，不复制就会消失——那是"重发也不行"的物理原因。
    const IMAGE_QUEUE_MAX = 5;
    const IMAGE_QUEUE_TTL_MS = 30 * 60 * 1000;

    function imageQueueDir(chatKey) {
      // Windows 目录名不能带冒号：chatKey 形如 group:999，这里全换成下划线
      const safe = String(chatKey || 'unknown').replace(/[^0-9a-zA-Z_.-]/g, '_');
      return path.join(arcDataDir(), 'state', 'qq-images', safe);
    }

    function readImageQueue(chatKey) {
      const dir = imageQueueDir(chatKey);
      let names = [];
      try {
        names = fs.readdirSync(dir);
      } catch {
        return [];
      }
      const now = Date.now();
      const items = [];
      for (const name of names) {
        if (!name.endsWith('.json')) continue;
        try {
          const rec = JSON.parse(fs.readFileSync(path.join(dir, name), 'utf8'));
          if (!rec || now - Number(rec.at || 0) > IMAGE_QUEUE_TTL_MS) continue;
          if (!fs.existsSync(String(rec.path || ''))) continue;
          items.push(rec);
        } catch { /* 坏记录忽略 */ }
      }
      items.sort((a, b) => Number(b.at || 0) - Number(a.at || 0));
      return items.slice(0, IMAGE_QUEUE_MAX);
    }

    function rememberImage(chatKey, file, mediaType, extra) {
      try {
        if (!file || !fs.existsSync(file)) return null;
        const dir = imageQueueDir(chatKey);
        fs.mkdirSync(dir, { recursive: true });
        // 同一张图只留一条：OCR 写回时更新旧记录，不重复复制文件
        const prev = readImageQueue(chatKey).find((x) => String(x.source || '') === String(file));
        if (prev) {
          const merged = {
            ...prev,
            ocrText: String(extra?.ocrText || prev.ocrText || '').slice(0, 2000),
            status: extra?.status || prev.status || 'queued',
          };
          const base = String(path.basename(String(prev.path || ''))).replace(/[^0-9]/g, '');
          fs.writeFileSync(path.join(dir, base + '.json'), JSON.stringify(merged), 'utf8');
          return merged;
        }
        const at = Date.now();
        const ext = String(path.extname(file) || '.jpg').toLowerCase();
        const target = path.join(dir, String(at) + ext);
        fs.copyFileSync(file, target);
        const rec = {
          path: target,
          mediaType: mediaType || 'image/jpeg',
          bytes: fs.statSync(target).size,
          at,
          source: String(file),
          ocrText: String(extra?.ocrText || '').slice(0, 2000),
          status: extra?.status || 'queued',
        };
        fs.writeFileSync(path.join(dir, String(at) + '.json'), JSON.stringify(rec), 'utf8');
        return rec;
      } catch (e) {
        bot.log?.warn?.('[ReflexArc] 图片入队失败: ' + e.message);
        return null;
      }
    }

    async function enqueueIncomingImages(ev) {
      const paths = Array.isArray(ev?.imagePaths) ? ev.imagePaths : [];
      const parts = Array.isArray(ev?.imageParts) ? ev.imageParts : [];
      const images = Array.isArray(ev?.images) ? ev.images : [];
      if (!paths.length) return;
      const chatKey = String(ev?.chatKey || (ev?.groupId ? 'group:' + ev.groupId : ''));
      if (!chatKey) return;
      for (let i = 0; i < paths.length; i += 1) {
        if (images[i]?.isSticker) continue;
        const file = String(paths[i] || '');
        if (!file) continue;
        const rec = rememberImage(chatKey, file, parts[i]?.mediaType, {});
        if (rec) bot.log?.info?.('[ReflexArc] 图片入队 ' + chatKey + ' ' + rec.bytes + 'B');
      }
    }

    // OCR 一律跑（普通截图也跑）：以前只有长图才跑，于是普通截图整轮等于没图。
    async function ocrAllImages(ev) {
      const cs = bot?.cfg || {};
      if (cs.coarseVision === false) return;
      const paths = Array.isArray(ev?.imagePaths) ? ev.imagePaths : [];
      const images = Array.isArray(ev?.images) ? ev.images : [];
      if (!paths.length) return;
      const chatKey = String(ev?.chatKey || (ev?.groupId ? 'group:' + ev.groupId : ''));
      if (!chatKey) return;
      const maxChars = Math.max(80, Math.min(4000, Number(cs.coarseVisionMaxChars) || 800));
      // RapidOCR 冷启动一次要 4~8s，3s 会把它杀掉；跟粗看共用同一个超时配置
      const ocrTimeout = Math.max(3000, Number(cs.coarseVisionTimeoutMs) || 60000);
      for (let i = 0; i < paths.length; i += 1) {
        if (images[i]?.isSticker) continue;
        const file = String(paths[i] || '');
        if (!file) continue;
        let dims = null;
        try {
          dims = readImageSize(readHead(file));
        } catch { /* 读不到头就当普通图 */ }
        // 长图交给 coarseLookLongImages（它会多切几块 OCR），这里不重复跑
        if (dims?.width && dims?.height && dims.height / dims.width >= 2.5) continue;
        const queued = readImageQueue(chatKey).find((x) => String(x.source || '') === file);
        if (queued?.ocrText) continue;   // 已经入过队并 OCR 过，不重复
        const res = await runOcr(file, ocrTimeout, 1);
        const text = String(res?.text || '').trim();
        if (!res?.ok || !text) {
          bot.log?.warn?.('[ReflexArc] 识图 OCR 未出结果：' + (res?.error || '空'));
          continue;
        }
        const clipped = text.replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').slice(0, maxChars).trim();
        ev.hint.push('【反射弧/识图】本地 OCR 读到的文字（不是完整画面）：\n' + clipped);
        rememberImage(chatKey, file, 'image/jpeg', { ocrText: clipped, status: 'ocr' });
        bot.log?.info?.('[ReflexArc] 识图 OCR ' + chatKey);
      }
    }

    async function injectMemoryLabHint(ev) {
      if (bot?.cfg?.memoryLabEnabled !== true) return;
      const text = String(ev?.text || '').trim();
      if (text.length < 4 || !/(上次|那次|之前|后来|记得|还记得|那个|那件事|后来呢)/.test(text)) return;
      const base = String(bot?.cfg?.memoryLabUrl || '').trim();
      if (!base) return;
      const timeout = Math.max(100, Math.min(3000, Number(bot?.cfg?.memoryLabTimeoutMs) || 250));
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), timeout);
      try {
        // S4：query 带上她最近两句（双侧取词）；取回后定向 1 + 随机 1
        const query = buildRecallQuery(ev) || text;
        const url = base.replace(/\/+$/, '') + '/recall?q=' + encodeURIComponent(query) + '&limit=6';
        const res = await fetch(url, { signal: ac.signal });
        if (!res.ok) return;
        const data = await res.json();
        const raw = Array.isArray(data?.items) ? data.items : [];
        const candidates = [];
        const hintState = readMemoryHints();
        const hintKey = String(ev?.chatKey || (ev?.groupId ? 'group:' + ev.groupId : '') || 'default');
        let skipDup = 0;
        for (const item of raw) {
          if (!item?.text) continue;
          // ③ 跳过"测试/复述型"问句（她自己问"你还记得…吗"的那种，不是记忆内容）
          if (/^(你)?还记得[^。！？]{0,24}(吗|么|嘛)[？?]?\s*$/.test(String(item.text).trim())) continue;
          // 外部记忆文本进 hint 前先过一道祈使/注入筛选（surfcore screenClaim 的用法）
          const scr = screenClaim(item.text);
          if (!scr.ok) {
            bot.log?.warn?.(`[ReflexArc] memory-lab 文本被筛掉（${scr.reason}）`);
            continue;
          }
          if (hintAlreadyUsed(hintState, hintKey, item, text)) { skipDup += 1; continue; }
          candidates.push(item);
        }
        // P1-3 时间锚路由：候选里只要有同口径的，就优先那批（不硬过滤）
        const anchor = parseTimeAnchor(text);
        let pool = candidates;
        if (anchor) {
          const matched = candidates.filter((it) => anchorMatches(it.when, anchor));
          if (matched.length) pool = matched;
        }
        const lines = [];
        const chosen = [];
        for (const item of pickDirectedAndRandom(pool, Date.now())) {
          const meta = [item.when, item.who, item.where, item.stance].filter(Boolean).join('·');
          const body = String(item.text).replace(/\s*\n+\s*/g, ' ').trim().slice(0, 80);
          lines.push('[记忆联想·实验' + (meta ? '｜' + meta : '') + '] ' + body);
          chosen.push(item);
          if (lines.length >= 2) break;
        }
        if (!lines.length) return;   // 无候选就一条都不写，不留占位
        for (const item of chosen) rememberHint(hintState, hintKey, item);
        // S5："想深一点就 recall" 同一个会话 30 分钟内只提醒一次，别每轮都念
        const tipKey = String(ev?.chatKey || '');
        if (Date.now() - (recallTipSeen.get(tipKey) || 0) > RECALL_TIP_GAP_MS) {
          lines[lines.length - 1] += '（想深一点就 recall）';
          recallTipSeen.set(tipKey, Date.now());
        }
        ev.hint.push(...lines);
        ev._scratch = ev._scratch || Object.create(null);
        ev._scratch['reflex-arc:memoryLab'] = true;
        bot.log?.info?.('[ReflexArc] memory-lab hinted ' + lines.length + ' 条（跳过重复 ' + skipDup + '）');
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] memory-lab failed: ${e.message}`);
      } finally {
        clearTimeout(timer);
      }
    }

    // ── P1-1 二次联想 ─────────────────────────────────────────────────
    // 第一遍没捞到时，别用"用户的原话"再问一遍（那只会捞回同一批），
    // 改用她自己刚说的那句作为 query——她描述的角度不同，命中的常是另一批记忆。
    // 这条只在"翻旧账/被指出答错"时触发，不掺和日常闲聊。
    const CORRECTION_CUE = /(不对|不是这个|错了|记错|再想想|确定吗|你确定|想不起来|没想起来)/;
    const DENIAL_TEXT = /(不记得|记不清|没印象|想不起|没想起来|不太清楚|不确定)/;

    // ── P0-4 停等：先本地处理，攒够/静下来再交 API ──────────────────
    // 她这条要不要进模型，由这里决定：
    //   · 3 秒内同会话又来消息 → 前一条并进新的（前一条 stopped，管线跳过），新的重新计时；
    //   · 3 秒内收到撤回 → 这条作废，绝不进模型；
    //   · 3 秒后没有变化 → 放行，交给内核判唤醒/主动接话。
    const settleHeld = new Map();   // chatKey -> { ev, name, at, text }

    function settleMs() {
      const v = Number(bot.cfg.holdMs);
      return Number.isFinite(v) && v >= 0 ? Math.min(v, 15000) : 3000;
    }

    function settleName(ev) {
      return String(ev?.sender?.card || ev?.sender?.name || ev?.sender?.qq || '?');
    }

    /** 撤回通知：把同会话还在等的那条作废（OneBot 的召回通知不带 message_id，按人+时间卡） */
    function settleAbortByRecall(ev) {
      const type = String(ev?._scratch?.notice?.type || '');
      if (!/recall/i.test(type)) return false;
      const key = String(ev?.chatKey || '');
      const held = settleHeld.get(key);
      if (!held) return false;
      const who = Number(ev?._scratch?.notice?.userId ?? ev?.sender?.qq ?? 0);
      const samePerson = !who || Number(held.ev?.sender?.qq ?? 0) === who;
      if (!samePerson || Date.now() - held.at > 15000) return false;
      held.ev.stopped = true;
      held.ev.stopReason = '撤回作废（停等窗口内被撤回）';
      settleHeld.delete(key);
      bot.log?.info?.(`[ReflexArc] 停等作废：${key} 的消息被撤回，不进模型`);
      return true;
    }

    /** 并进上一条：正文 + 图片 + hint（正文用内核合批同一套「[名]: 内容」格式） */
    function settleAbsorb(prev, ev) {
      const head = `[${prev.name}]: ${prev.text}`.trim();
      const cur = String(ev?.text || '');
      ev.text = cur ? `${head}\n${cur}` : head;
      const hints = []
      for (const h of (prev.ev?.hint || [])) if (!hints.includes(h)) hints.push(h)
      for (const h of (ev.hint || [])) if (!hints.includes(h)) hints.push(h)
      ev.hint = hints
      const paths = [
        ...(Array.isArray(ev.imagePaths) ? ev.imagePaths : []),
        ...(Array.isArray(prev.ev?.imagePaths) ? prev.ev.imagePaths : []),
      ]
      if (paths.length) ev.imagePaths = [...new Set(paths)]
      const parts = [
        ...(Array.isArray(ev.imageParts) ? ev.imageParts : []),
        ...(Array.isArray(prev.ev?.imageParts) ? prev.ev.imageParts : []),
      ]
      if (parts.length) ev.imageParts = parts
      ev._scratch.mergedCount = Number(ev._scratch?.mergedCount || 1) + Number(prev.ev?._scratch?.mergedCount || 1)
      ev._scratch.settleMerged = true
      // 继承唤醒信号：前一条被 @/被回复时，整批仍然是"叫到她了"。
      // 不继承的话，后一条普通消息会把 @ 吞掉，合并结果变成"没人叫"（实测 11:52 就踩了这个坑：
      // 两条并成一条却 wake=none，最后靠 3 分钟后的主动接话才回话）。
      if (!ev.wake && prev.ev?.wake) {
        ev.wake = prev.ev.wake
        ev._scratch.settleWakeInherited = true
      }
      if (ev.mentionedSelf !== true && prev.ev?.mentionedSelf === true) ev.mentionedSelf = true
      if (ev.replyToId == null && prev.ev?.replyToId != null) ev.replyToId = prev.ev.replyToId
      prev.ev.stopped = true
      prev.ev.stopReason = '停等合并：并进后一条'
    }

    async function settleHold(ev) {
      if (settleAbortByRecall(ev)) return;
      if (ev?._scratch?.notice) return;              // 其它通知不参与停等
      if (bot.cfg.holdEnabled === false) return;
      if (!ev?.chatKey || !String(ev.text || '').trim()) return;
      const key = String(ev.chatKey);
      const prev = settleHeld.get(key);
      if (prev && prev.ev !== ev) settleAbsorb(prev, ev);
      const self = { ev, name: settleName(ev), at: Date.now(), text: String(ev.text || '') };
      settleHeld.set(key, self);
      await new Promise((r) => setTimeout(r, settleMs()));
      // 期间被后来的消息吸收过：保持 stopped，由管线跳过
      if (settleHeld.get(key) === self) settleHeld.delete(key);
    }

    // ── V9-A 影子 ──────────────────────────────────────────────────────
    // 每轮落一行：这一轮如果由"外壳"来决定，会怎么决定。只写文件，不碰 hint/发送。
    // 攒够数据再决定 V9-B 怎么改（现在的怀疑是：合批窗口里根本没有"两条都被唤醒"的情况）。
    const SHADOW_MAX_LINES = 2000;
    const shadowLast = new Map();   // chatKey -> 上一轮到达时间（进程内）

    function shadowFile() {
      return path.join(arcDataDir(), 'state', 'reflex-shadow.jsonl');
    }

    function shadowDecision(ev) {
      const wake = String(ev?.wake?.kind || 'none');
      const key = String(ev?.chatKey || '');
      const mentioned = ev?.mentionedSelf === true;
      const quoted = Boolean(ev?.replyToId);
      // 本地可判的部分：被点名/被回复 → 回本人；主动接话 → 想回但不确定；其余 → 静默。
      if (wake === 'proactive') {
        return { action: 'maybe', target: key, why: 'proactive：本地只能给候选，接不接由模型定' };
      }
      if (wake === 'welcome') return { action: 'welcome', target: key, why: '入群欢迎轮' };
      if (mentioned) return { action: 'reply', target: key, why: '@我' };
      if (quoted) return { action: 'reply', target: key, why: '回复我' };
      if (wake === 'none') return { action: 'silent', target: '', why: '没唤醒：不该开口' };
      return { action: 'reply', target: key, why: 'wake=' + wake };
    }

    function recordShadow(ev, hints) {
      try {
        const key = String(ev?.chatKey || '');
        const now = Date.now();
        const prev = shadowLast.get(key) || 0;
        shadowLast.set(key, now);
        const rec = {
          at: new Date(now).toISOString(),
          chatKey: key,
          textLen: String(ev?.text || '').length,
          textHead: String(ev?.text || '').replace(/\s+/g, ' ').slice(0, 40),
          gapMs: prev ? now - prev : null,
          wake: String(ev?.wake?.kind || 'none'),
          merged: Number(ev?._scratch?.mergedCount || 1),
          hints: (Array.isArray(hints) ? hints : []).map((h) => String(h).slice(0, 24)),
          images: Array.isArray(ev?.images) ? ev.images.length : 0,
          decide: shadowDecision(ev),
        };
        const file = shadowFile();
        fs.mkdirSync(path.dirname(file), { recursive: true });
        fs.appendFileSync(file, JSON.stringify(rec) + '\n', 'utf8');
        // 环形：超了就只留最后 SHADOW_MAX_LINES 行（重写而不是无限涨）
        const raw = fs.readFileSync(file, 'utf8');
        const lines = raw.split('\n').filter(Boolean);
        if (lines.length > SHADOW_MAX_LINES) {
          fs.writeFileSync(file, lines.slice(-SHADOW_MAX_LINES).join('\n') + '\n', 'utf8');
        }
      } catch (e) {
        bot.log?.debug?.(`[ReflexArc] 影子记录失败: ${e.message}`);
      }
    }

    async function injectSecondPassHint(ev) {
      if (bot?.cfg?.memoryLabEnabled !== true) return;
      const text = String(ev?.text || '').trim();
      if (text.length < 3) return;
      const base = String(bot?.cfg?.memoryLabUrl || '').trim();
      if (!base) return;
      const corrected = CORRECTION_CUE.test(text);
      // 第一遍已经给过联想，且这句不是"答错了/再想想" → 不叠第二遍
      if (ev?._scratch?.['reflex-arc:memoryLab'] && !corrected) return;
      const key = String(ev?.chatKey || (ev?.groupId ? 'group:' + ev.groupId : '') || 'default');
      const said = (recentSaid.get(key) || []).slice(-1);
      const ownRaw = said.length ? String(said[0].text || '') : '';
      const own = cleanForQuery(ownRaw);
      // 她还没说过话 / 那句话太短 → 没得联想
      if (own.length < 4) return;
      // 她自己那句就是否认/不确定 → 用它做 query 只会漂回"我不记得"，跳过
      if (DENIAL_TEXT.test(ownRaw) && !corrected) return;
      const minScore = Number(bot?.cfg?.secondPassMinScore);
      const floor = Number.isFinite(minScore) && minScore > 0 ? minScore : 0.55;
      const timeout = Math.max(100, Math.min(3000, Number(bot?.cfg?.memoryLabTimeoutMs) || 250));
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), timeout);
      try {
        // query 用"她的话为主、本句为辅"：她的描述决定了召回方向
        const head = own.slice(0, 60);
        const tail = corrected ? cleanForQuery(text).slice(0, 40) : '';
        const query = (head + (tail ? ' ' + tail : '')).trim();
        if (query.length < 4) return;
        const url = base.replace(/\/+$/, '') + '/recall?q=' + encodeURIComponent(query) + '&limit=6';
        const res = await fetch(url, { signal: ac.signal });
        if (!res.ok) return;
        const data = await res.json();
        const raw = Array.isArray(data?.items) ? data.items : [];
        const hintState = readMemoryHints();
        const usable = [];
        for (const item of raw) {
          if (!item?.text) continue;
          // ① 候选本身是"不记得/没印象"这种否认句 → 注入进去就是自我否定漂移
          if (DENIAL_TEXT.test(String(item.text))) continue;
          // ② 和 query 几乎一字不差 → 那是回声，不是记忆
          if (hintSimilar(normHintText(item.text), own)) continue;
          // ③ 已经用过（含本轮第一遍给的）→ 换一条；池子空了就不给
          if (hintAlreadyUsed(hintState, key, item, text)) continue;
          const score = Number(item.rrf_adjusted ?? item.rrf_score ?? 0);
          if (!(score >= floor)) continue;   // 阈值卡住：全库也可能是噪声
          if (Array.isArray(item.axes) && item.axes.includes('denial')) continue;
          usable.push({ item, score });
        }
        if (!usable.length) return;
        usable.sort((a, b) => b.score - a.score);
        const best = usable[0].item;
        const meta = [best.when, best.who, best.where, best.stance].filter(Boolean).join('·');
        const body = String(best.text).replace(/\s*\n+\s*/g, ' ').trim().slice(0, 80);
        const line = '[记忆联想·实验｜补' + (meta ? '｜' + meta : '') + '] ' + body;
        rememberHint(hintState, key, best);
        ev.hint.push(line);
        ev._scratch = ev._scratch || Object.create(null);
        ev._scratch['reflex-arc:secondPass'] = { score: Number(best.rrf_adjusted ?? best.rrf_score ?? 0) };
        bot.log?.info?.('[ReflexArc] 第二次联想命中（她的话 → 全库）：score=' + usable[0].score.toFixed(2)
          + ' 候选=' + usable.length + (corrected ? '（答错后）' : ''));
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] 二次联想失败: ${e.message}`);
      } finally {
        clearTimeout(timer);
      }
    }

    async function injectFirstContactImpression(ev) {
      const base = String(bot?.cfg?.emotionCoreUrl || process.env.EMOTIONCORE_URL || '').trim();
      const qq = String(ev?.sender?.qq || '').trim();
      if (!base || !qq || qq === String(bot.selfId || '')) return;
      const session = String(ev?.turnCtx?.sessionId || ev?.chatKey || '');
      const state = readState();
      const key = `${session}|${qq}`;
      if (state.seen[key]) return;
      // Mark after one attempt, so a missing impression does not retry every turn.
      state.seen[key] = true;
      saveState(state);
      const timeout = Math.max(100, Math.min(10000, Number(bot?.cfg?.impressionTimeoutMs) || 1500));
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), timeout);
      try {
        const res = await fetch(base.replace(/\/+$/, '') + '/person_impression', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ qq }),
          signal: ac.signal,
        });
        if (!res.ok) return;
        const data = await res.json();
        const text = String(data?.text || '').trim();
        if (text) {
          ev.hint.push(`【人物印象·当天首次接触】${text.slice(0, 500)}`);
          ev._scratch = ev._scratch || Object.create(null);
          ev._scratch['reflex-arc:personImpression'] = true;
          bot.log?.info?.(`[ReflexArc] first-contact impression qq=${qq}`);
        }
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] impression failed: ${e.message}`);
      } finally {
        clearTimeout(timer);
      }
    }

    /**
     * 场景元信息（约 40 字）：谁在说、对谁说、这是哪个场面。
     * 群与私聊共用同一个 session，模型只能靠这行分清窗口；数据全取本地状态，不发网络请求。
     */
    const sceneOf = (ev) => buildSceneHint(ev, { bot, groupState, oneLine });

    // ── S0 观测：这一轮到底往提示词里塞了什么（只记标签和字数，不存正文）──
    const hintStatsPath = path.join(
      bot?.core?.dataDir || bot?.dataDir || process.cwd(), 'state', 'reflex-hints.json',
    );
    let hintStatsCache = null;

    function hintLabelOf(line) {
      const text = String(line || '');
      const m = /^\[反射弧\/([^\]]+)\]/.exec(text)
        || /^\[记忆联想·实验\]/.exec(text)
        || /^\[场景:/.exec(text)
        || /^【([^】]+)】/.exec(text);
      if (!m) return 'other';
      if (m[1]) return m[1].slice(0, 16);
      return text.startsWith('[记忆联想') ? '记忆联想' : text.startsWith('[场景') ? '场景' : 'other';
    }

    /** 每轮结束时把"本轮新增的 hint"累加进 state/reflex-hints.json（给验收用，失败不打扰聊天）。 */
    function recordHints(ev, added) {
      if (!Array.isArray(added) || !added.length) return;
      try {
        if (!hintStatsCache) {
          try { hintStatsCache = JSON.parse(fs.readFileSync(hintStatsPath, 'utf8')) } catch { hintStatsCache = null }
        }
        const stats = hintStatsCache && typeof hintStatsCache === 'object'
          ? hintStatsCache
          : { since: new Date().toISOString(), total: 0, turns: 0, byLabel: {}, recent: [] };
        stats.byLabel = stats.byLabel && typeof stats.byLabel === 'object' ? stats.byLabel : {};
        stats.recent = Array.isArray(stats.recent) ? stats.recent : [];
        for (const line of added) {
          const label = hintLabelOf(line);
          const chars = String(line).length;
          const cell = stats.byLabel[label] || { n: 0, chars: 0 };
          cell.n += 1;
          cell.chars += chars;
          stats.byLabel[label] = cell;
          stats.total += 1;
          stats.recent.push({ at: new Date().toISOString(), chatKey: String(ev?.chatKey || ''), label, chars });
        }
        stats.turns += 1;
        if (stats.recent.length > 60) stats.recent = stats.recent.slice(-60);
        hintStatsCache = stats;
        fs.mkdirSync(path.dirname(hintStatsPath), { recursive: true });
        fs.writeFileSync(hintStatsPath, JSON.stringify(stats, null, 2) + '\n', 'utf8');
      } catch (e) {
        bot.log?.debug?.(`[ReflexArc] hint 统计失败: ${e.message}`);
      }
    }

    onBefore('before-turn', async (ev) => {
      const hintStart = Array.isArray(ev.hint) ? ev.hint.length : 0;
      try {
        const scene = sceneOf(ev);
        if (scene) ev.hint.push(scene);
        // 弱约束：把她这一轮"能往哪发"钉在场景行旁边。
        // 发送工具在内核里，插件改不了 target 解析，所以只能讲规矩——
        // 但讲得越靠近场景行越不容易被压缩吃掉。
        if (bot.cfg.sendTargetLock !== false) {
          const bindKey = String(ev.chatKey || '');
          if (bindKey) {
            const where = bindKey.startsWith('group:') ? '这个群' : '这个人';
            ev.hint.push('[反射弧/发送] 本轮只准往 ' + bindKey + ' 发（' + where
              + '）；群消息发群里、私聊回本人，别用别的窗口的地址。拿不准就别发。');
          }
        }
        const maxDice = Number(bot.cfg.maxDice) || 100;
        const maxCount = Number(bot.cfg.maxCount) || 10;
        const r = bot.cfg.diceIntent === false ? null : parseDice(ev.text, maxDice, maxCount);
        if (r) {
          const body = r.count === 1
            ? `[反射弧/骰] d${r.sides} = ${r.total}`
            : `[反射弧/骰] ${r.count}d${r.sides} = ${r.rolls.join(' + ')} = ${r.total}`;
          ev.hint.push(body);
          ev._scratch = ev._scratch || Object.create(null);
          ev._scratch['reflex-arc:dice'] = r;
          bot.log?.info?.(`[ReflexArc] ${body}`);
        }
        // 本地骰子指令刚回过（.r/.ra）：这是既成事实，告诉模型别重复报、更别改数字
        const receiptOn = bot.cfg.diceReceipt !== false;
        const rollKey = String(ev.chatKey || '');
        const roll = rollKey ? lastRoll.get(rollKey) : null;
        if (receiptOn && roll && Date.now() - roll.at < 10 * 60 * 1000) {
          ev.hint.push(`[反射弧/骰·上次] 刚才 ${roll.expr} = ${roll.total}（已经由本地直接回过；不要重复报这个数，也不要改）`);
          lastRoll.delete(rollKey);
        }
        const mm = receiptOn && rollKey ? diceMismatch.get(rollKey) : null;
        if (mm) {
          ev.hint.push(`【反射弧回执】上一轮本地掷的是「${mm.expected}」，你报成了「${mm.seen}」；本地结果优先，不要自行改骰子。`);
          diceMismatch.delete(rollKey);
        }
        const incoming = classifyIncoming({
          text: ev.text,
          media: ev.images,
          segments: ev.rawSegments,
          forwardId: ev.forwardId,
          hasForward: ev.hasForward,
          quote: ev.replyToId,
          atSelf: ev.mentionedSelf,
        });
        if (incoming.quoteId) {
          ev._scratch = ev._scratch || Object.create(null);
          ev._scratch['reflex-arc:quoteId'] = incoming.quoteId;
        }
        const forwards = Array.isArray(ev.forwards) ? ev.forwards : (Array.isArray(ev._scratch?.forwards) ? ev._scratch.forwards : []);
        const forwardTexts = [];
        for (const f of forwards) {
          const content = Array.isArray(f?.content) ? f.content : [];
          for (const item of content) {
            const sender = String(item?.sender?.name || item?.sender?.card || item?.sender?.nickname || item?.sender?.user_id || '').trim();
            const text = String(item?.text || item?.message || '').replace(/\s+/g, ' ').trim();
            if (!text) continue;
            forwardTexts.push(`${sender ? sender + '：' : ''}${text}`);
            if (forwardTexts.length >= 3) break;
          }
          if (forwardTexts.length >= 3) break;
        }
        if (forwardTexts.length) {
          ev.hint.push(`[反射弧/转发] 合并转发摘要：${forwardTexts.join(' / ').slice(0, 500)}`);
        } else if (incoming.hasForward || incoming.forwardId) {
          ev.hint.push('[反射弧/转发] 收到合并转发；没有 inline 内容，需要细节时走本地转发索引');
        }
        if (incoming.imageCount && bot?.cfg?.localVision === true) {
          ev.hint.push(`[反射弧/图片] 本地收到 ${incoming.imageCount} 张图片/表情；本地视觉正在解析`);
        }
        if (incoming.links?.length) {
          ev.hint.push(`[反射弧/链接] ${incoming.links.slice(0, 2).join(' ')}（仅本地记录，不自动抓取）`);
        }
        if (bot.cfg.impressionEnabled !== false) await injectFirstContactImpression(ev);
        await analyzeOneImage(ev);
        await injectMemoryLabHint(ev);
        await injectSecondPassHint(ev);
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] before-turn: ${e.message}`);
      }
      await settleHold(ev);
      recordHints(ev, Array.isArray(ev.hint) ? ev.hint.slice(hintStart) : []);
      if (bot.cfg.shadowLog !== false) recordShadow(ev, Array.isArray(ev.hint) ? ev.hint.slice(hintStart) : []);
    });

    // 粗看必须晚于 kernel:context（order 50）——那时 ev.imagePaths / ev.imageParts 才填好；
    // 本插件自身 order 是 36，所以这里显式抬到 60。
    onBefore('before-turn', async (ev) => {
      try {
        await consumeSessionRotate(ev);
        injectFormatFix(ev);
        maybeReinjectToolCard(ev);
        await enqueueIncomingImages(ev);
        await coarseLookLongImages(ev);
        await ocrAllImages(ev);
      } catch (e) {
        bot.log?.warn?.(`[ReflexArc] 粗看失败: ${e.message}`);
      }
    }, { order: 60 });

    bot.log?.info?.('[ReflexArc] ready');
  },
};

export { parseDice };

