# EmotionCore for SurfCore：GitHub 初始化

仓库名建议：

```text
EmotionCoreForDSH-surfcore
```

显示名：

```text
EmotionCore for SurfCore
```

内部 Python 包仍叫 `soulcore`，不要改。

## 已完成

本地 SoulCore 已经是 git 仓库：

```text
<REPO_ROOT>
```

提交：

```text
4c57280 Document low-bandwidth GitHub setup
71744b0 Add configurable appraisal backend and per-character purpose seed
97208e4 Initial SoulCore emotion and memory layer
```

另有本地裸仓库备份：

```text
<REPO_ROOT>-local-backup.git
```

不提交：`data/`、数据库、备份、日志、下载、`*.bak-*`。

## Git 低网速设置

```powershell
git config --global http.version HTTP/1.1
git config --global http.postBuffer 524288000
git config --global http.lowSpeedLimit 1000
git config --global http.lowSpeedTime 600
```

## 1. 创建 EmotionCore 公开仓库

在 Edge 打开：

```text
https://github.com/new
```

- Repository name: `EmotionCoreForDSH-surfcore`
- Description: `EmotionCore for SurfCore`
- 选 **Public**
- 不要勾选 README / .gitignore / license

然后：

```powershell
cd <REPO_ROOT>
git remote add origin https://github.com/jiygfu/EmotionCoreForDSH-surfcore.git
git push -u origin main
```

## 2. Fork SurfCore

在 Edge 打开：

```text
https://github.com/Mieksido/surfcore/fork
```

创建后，把本地 `<USERPROFILE>\surfcore` 的 `origin` 指向 fork：

```powershell
cd <USERPROFILE>\surfcore
git remote rename origin upstream
git remote add origin https://github.com/jiygfu/surfcore.git
git add -A
git commit -m "SoulCore integration: sidecar, appraisal learning, purpose seed"
git push -u origin main
```

之后上游更新：

```powershell
git fetch upstream
git merge upstream/main
git push origin main
```

## 3. 国内网络说明

- 读取/fetch 可以用镜像：

```text
https://ghfast.top/https://github.com/Mieksido/surfcore.git
https://gh-proxy.com/https://github.com/Mieksido/surfcore.git
```

- **push 走镜像不一定可用**；国内网络优先用 SSH over 443：

```text
ssh://git@ssh.github.com:443/jiygfu/EmotionCoreForDSH-surfcore.git
```

- 公钥需要加到 GitHub `Settings → SSH and GPG keys`；不要把 token 写进仓库。
- 如果 push 卡住，先确认 Git Credential Manager 已登录；不要把 token 写进仓库。
- 大文件不要提交：`downloads/`、`data/`、模型文件、数据库。

## 4. 当前 SurfCore 修改

SurfCore 的 15 个文件修改还未提交；干净补丁：

```text
<REPO_ROOT>\backups\surfcore-soulcore-20261030-clean.patch
```

在 fork 的 `main` 上提交并 push 后，SurfCore 更新器会从 fork 检查更新；不要再直接点原仓库更新。
