# 运行态审计（2026-10-29 19:20）

范围：桌宠、QQ、B站、人物关系、P/人物卡注入、身份唯一性。

---

## 1. 结论

**QQ 已经在真实运行，不再是“代码加载但没验证”。**

`bridge.log` 显示 18:58–19:06 有真实群聊：

- `group:<groupQQ>` 被 @ 唤醒；
- 工具发送成功；
- 多轮对话，最后自然收尾；
- 没有被语法/加载错误阻断。

桌宠已有一次明确注入验证：

```text
你：你还记得 WindyDaylight 吗？
桌宠：当然记得，就是那个爱琢磨模型能不能模拟人类思维的人嘛…
```

B站代码已接 P-only，但 **B站账号没登录**，无法端到端验证。

---

## 2. 符合预期的部分

| 功能 | 状态 |
|---|---|
| persona 认知取向 | ✅ |
| 桌宠 P + person card + `#行动` | ✅ 实测 |
| QQ bridge 实际收发 | ✅ 日志有真实群聊 |
| QQ v1/v2 唤醒、purpose 注入 | ✅ 代码已接 |
| B站主唤醒 / 定时分享 P-only | ✅ 代码已接，未登录未实测 |
| QQ 号作为 person_id | ✅ |
| 昵称只做别名/显示名 | ✅ |
| 同名不同 QQ 号不合并 | ✅ 13/13 测试 |
| 同 QQ 号跨群/改名仍同一人 | ✅ 13/13 测试 |
| 每日人员关系刷新 | ✅ |
| daily/sleep 刷新 context 文件 | ✅ |

---

## 3. 不符合/有风险的部分

### P0：ownerQQ 未配置 → 已修复

已确认 owner QQ = `<ownerQQ>`。

已修改：

- `config.json.ownerQQ = "<ownerQQ>"`
- `config.json.purpose.ownerUin = "<ownerQQ>"`
- 本地 `people` 表 `qq:<ownerQQ>` 标记 `is_owner=1`
- bridge 重启后 **“未配置 ownerQQ”警告消失**

当前 bridge：

```text
PID 33528
owner 私聊已排程：private:<ownerQQ>
```

### P1：person card 是全局注入，存在跨群泄露风险（仍保留）当前 `soulcore-context.md` 包含当天所有触发人物卡，QQ group/private 都读同一份。

说明：

- **同一个 QQ 号跨群使用同一人物卡**是正确的，已按你的要求保留；
- 但“同一个人的卡”不等于“把其他群友的卡也带进当前群”；
- 如果多群测试时看到无关群友，需要按 `conversationKey` 过滤，只注入当前会话相关的人。

### P2：B站未登录（按你的要求暂停）

- B站 P-only patch 已加载；
- 但 B站未扫码登录；
- 暂不继续做 B站。

### P3：`#行动` 输出过滤（按你的要求不做）

保持现状：`#行动` 只作为 prompt 行为指令，不做硬过滤；漏到正文可接受。


---

## 4. 优先级

1. **ownerQQ 已修复**（`<ownerQQ>`）。
2. **记忆查询工具已补**：`soulcore_memory`，只读，支持 overview/today/search/person/range/p；可按 person/scope 过滤，结果有 `truncated` 限制。
   - 工具运行在 DSH Host / 本机 Python / SQLite，不走 QQ API。
   - QQ preset 的 `qq-tool-restrict` 原本会拒绝所有本地工具；已把 `soulcore_memory` 加入唯一例外。
   - preset/guard 是启动时加载的，需要**完整重启 DSH**才生效；只重启 QQ bridge 不够。
3. 工具目前全局可见，QQ 群友也能调用；正式群聊前应限制 owner/私聊或按 `conversationKey` 过滤。
4. **旧记忆身份已修补**：4 条 `self`、1 条 `legacy_unresolved`；查询结果带 `identity_status`，不会默认归给 owner。
5. **记忆查询已复用 SurfCore 内置召回**：普通关键词 `search` 走 `recallFullMemory()`；本地只补 person/scope/日期。
6. **工具调用已有日志**：`data/memory-tool-calls.jsonl`；当前 6 条全是测试调用，没有 QQ 会话调用记录。
7. **SurfCore sidecar 已接通**：29 条 enrichment + 6 条 extension；`recallFullMemory("情感")` 已能返回人物卡/affect 扩展。DSH 宿主重启后生效。
8. **DSH 设置页已安装**：Settings → SoulCore，支持开关/路径/导出/评价/修复/调用记录；详见 `docs/SETTINGS-UI.md`。
9. **每日记忆已带感受与偏离量**：单条只存 `felt + delta`，绝对基准在 `soulcore:affect:latest`；30 条真实记忆已回填。
10. **日初基准账本已新增**：`daily_summaries` 记录 baseline / cleaned end / cumulative delta；`soul-bridge` 启动和 `daily`/`sleep` 会抓基准。
11. **评价代码化学习已加入**：38 个模型例子归纳为 17 个模式，默认 shadow；auto 需 5 次影子对照且准确率 ≥ 70%。
12. **代码优先评分已启用**：每条记忆先 `code-v1`，仅高价值/困难升级 AI；AI 失败保留 code 分并通过 SurfCore 现有发送入口问 owner。
13. **目的机制已接 SoulCore 情绪种子**：当日 baseline 换算 drives/emotion/urgency，SurfCore 目的机制只做混合与回退。
13. **修正闭环已加入**：失败包入 `appraisal_questions`；表层 `resolve` 生成 `surface-correction`，旧记忆 superseded 并隐藏出日常卡，全量卡保留。
5. B站按你的要求暂停，等登录后再测。
6. `#行动` 按你的要求保持不过滤。

QQ 本身已经有效；当前主要剩余风险是**全局人物卡/记忆工具在多个 QQ 群之间串台**。


