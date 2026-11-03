# DSH-EmotionCore + ReflexArc + memory-lab：GitHub 初始化

当前仓库 slug：

```text
DSH-EmotionCore-ReflexArc-memory-lab
```

显示名：

```text
DSH-EmotionCore + ReflexArc + memory-lab
```

GitHub 仓库名只能用字母、数字、`.`、`-`、`_`；显示名里的 `+` 不能放进 URL。
内部 Python 包仍叫 `soulcore`，不要改。

## 当前方案与旧仓库

```text
旧：EmotionCoreForDSH-surfcore  (v0.3.1 公开快照，逐步退役)
新：DSH-EmotionCore-ReflexArc-memory-lab (当前插件/文档/长期更新)
```

新仓库是隐私清理后的快照提交，不带旧仓库的长期提交历史；数据、日志、
备份、个人 persona、真实 QQ 号和本机绝对路径都不进入仓库。

## 国内网络：优先 SSH over 443

```text
ssh://git@ssh.github.com:443/jiygfu/DSH-EmotionCore-ReflexArc-memory-lab.git
```

本地配置：

```powershell
git remote add origin ssh://git@ssh.github.com:443/jiygfu/DSH-EmotionCore-ReflexArc-memory-lab.git
git config core.sshCommand "ssh -i C:/Users/<你>/.ssh/id_ed25519_github -p 443 -o IdentitiesOnly=yes"
git fetch origin
git push -u origin main
```

低带宽建议：

```powershell
git config --global http.version HTTP/1.1
git config --global http.postBuffer 524288000
git config --global http.lowSpeedLimit 1000
git config --global http.lowSpeedTime 600
```

- push 不走镜像；国内网络优先 SSH 443，避免 HTTPS 被中断。
- fetch 可以用镜像/代理，但不要把 token 写进仓库。
- 大文件不要提交：`downloads/`、`data/`、模型文件、数据库、日志。

## 首次上传 / 后续更新

```powershell
git clone ssh://git@ssh.github.com:443/jiygfu/DSH-EmotionCore-ReflexArc-memory-lab.git
cd DSH-EmotionCore-ReflexArc-memory-lab
git add README.md docs plugins soulcore
git commit -m "Update plugins and docs"
git push
```

如果 push 卡住：

1. 先确认 SSH key 已在 GitHub `Settings → SSH and GPG keys`。
2. 用 `ssh -T -p 443 git@ssh.github.com` 测试；失败时不要反复重试大包。
3. 仍失败再换 HTTPS + Credential Manager；不要把 PAT 贴到聊天或提交进文件。

## 仓库结构

```text
plugins/emotioncore-service/     本地 HTTP 服务
plugins/emotioncore-runtime/     启动/守护 service + worker
plugins/emotioncore-adapter/     QQ ec dispatcher / L5 注入
plugins/reflex-arc/              L1、群聊触发、长期活动、鱼群记录
plugins/memory-lab/              只读记忆实验 sidecar
plugins/memory-lab-dsh/          意识海设置页
plugins/soulcore-settings/       EmotionCore 设置页
plugins/soul-bridge/             旧 soulcore_memory 工具（可选）
docs/PLUGINS.md                  插件总览
```

插件总览：[PLUGINS.md](PLUGINS.md)。
