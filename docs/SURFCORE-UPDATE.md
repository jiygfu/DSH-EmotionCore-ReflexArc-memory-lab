# SurfCore 更新与 SoulCore 修改保护

日期：2026-10-30

## 现状

SurfCore 是 git 仓库：

```text
<USERPROFILE>\surfcore
origin = https://ghfast.top/https://github.com/Mieksido/surfcore.git
branch = main
```

当前有 15 个上游文件被修改，全部**未提交**。

更新器行为：

- git 安装：`git fetch` + `git merge --ff-only origin/main`
- zip 安装：robocopy `/MIR` 覆盖源码（只排除 state/config/node_modules 等）

## 直接更新的风险

### git 通道

`--ff-only` 遇到未提交改动/同文件上游改动会失败；  
即使成功更新其他文件，本地 13 个修改也不会自动成为上游提交。  
结果是“更新失败”或“版本和补丁半混合”。

### zip 通道

会覆盖：

- `src/memory-card.js`（sidecar、felt/delta、修正记忆）
- `src/bridge.js`（SoulCore 注入）
- `src/token-guard.js`（owner 豁免）
- `plugins/surfcore/qq-tool-restrict.mjs`
- QQ preset / patch
- `pet-chat.js`、`scheduler.js`、`client.js`

**zip 更新会直接丢掉这些 SoulCore 集成。**

## 不会被 SurfCore 更新影响的部分

- `<REPO_ROOT>`（Python、SQLite、sidecar 导出器）
- `@soulproject/soul-bridge`
- `@soulproject/soulcore-settings`
- `characters/` 下的记忆、sidecar、config、state

但这些插件依赖 SurfCore 内部的注入点；上游代码被覆盖后，它们还在，注入点没了。

## 推荐方案：fork + upstream

这是最稳妥的长期方案。

1. 在 GitHub 创建 `surfcore` 的 fork（私有也可以）。
2. 当前 13 个修改提交到 fork 的 `main`。
3. 把本地 `origin` 指向 fork，新增原仓库为 `upstream`。
4. SurfCore 更新器检查/更新的是 fork；上游更新通过：

```text
git fetch upstream
git merge upstream/main
# 解决冲突
git push origin main
```

5. 这样更新器仍然工作，但更新源是“带 SoulCore 修改的 fork”。

注意：fork 后要自己定期合并 upstream，否则会落后。

## 退而求其次：patch 层

如果不想维护 fork：

- 保留当前 clean patch；
- 每次上游更新后 `git apply --3way`；
- 冲突时人工处理；
- 不使用 zip 更新。

缺点：上游改动同文件时仍要手动解决；不是永久自动方案。

## 长期最优：上游化

把 sidecar 合并、SoulCore 注入做成 SurfCore 官方扩展点或 PR。  
这样本地不需要 patch，但取决于上游是否接受。

## 当前备份

```text
<REPO_ROOT>\backups\surfcore-soulcore-20261030-clean.patch
```

已归一化行尾，内容改动 15 文件 / 约 345 行，而不是整文件重写。

## 结论

- 现在**不要点更新**。
- 直接更新可能失败或丢 SoulCore 集成。
- 长久做法：**fork + upstream merge**；  
  临时做法：patch 层；  
  最优但不可控：上游化。
