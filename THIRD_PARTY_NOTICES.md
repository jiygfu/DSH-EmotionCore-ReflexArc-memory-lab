# Third-party notices

**DSH-EmotionCore + ReflexArc + memory-lab** 以 **MIT License** 发布（见
[`LICENSE`](LICENSE)）；第三方项目仍归其作者所有，并按各自许可证使用。

## 直接依赖（Python）

| 项目 | 许可证 | 用途 | 链接 |
|---|---|---|---|
| psutil | BSD-3-Clause | CPU/内存/磁盘/电池等临时身体状态 | https://github.com/giampaolo/psutil |
| Pillow | HPND / MIT-CMU | 长图切块与图片处理 | https://github.com/python-pillow/Pillow |
| rapidocr_onnxruntime | Apache-2.0 | 长图 OCR（本地 ONNX，不调用视觉模型） | https://github.com/RapidAI/RapidOCR |
| NumPy | BSD-3-Clause | RapidOCR/图像处理依赖 | https://github.com/numpy/numpy |

SQLite / FTS5 为 SQLite 公共领域实现，随 Python 运行时提供；本仓库只使用 SQL
接口，不附带 SQLite 源码。

## 运行平台

| 项目 | 许可证/状态 | 说明 |
|---|---|---|
| DeepSeek Harness (DSH) | 由 DeepSeek 提供 | 插件运行平台，不随本仓库分发 |
| `dsh-onebot-qq` | 由各自项目提供 | 当前 QQ 门禁、消息管线和 `ec` 所在的宿主；不在本仓库内 |
| SnowLuma / OneBot 11 | 由各自项目提供 | QQ 网关/协议实现；本仓库不包含其源码 |
| Ollama | MIT | 可选的本地小模型运行时；本仓库不包含其源码 |

## 历史参考

| 项目 | 许可证/状态 | 说明 |
|---|---|---|
| SurfCore | 上游未声明 SPDX 许可证（GitHub 识别为 NOASSERTION） | **不是当前运行依赖**。旧边车/同步/提示词路线仅作历史参考；本仓库不重新分发 SurfCore 源码。 |
| dsh-mnemosyne | AGPL-3.0-or-later | 参考 observation/evidence/version/status、FTS5 与降级检索思路；未复制源码 |
| DeepSeek-Balance-Whale-Widget | MIT | 余额挂件与 `.dshw-usage.json` 约定；以独立外部插件安装，未纳入本仓库 |
| dsh-plugin-kit | Apache-2.0 | DSH 插件/打包参考资料；未纳入本仓库 |

如果后续把上述项目的代码片段并入本仓库，必须保留对应版权与许可证声明，并
重新评估 AGPL/Apache-2.0 的兼容性。

## 图标

`plugins/soul-bridge/icon.svg` 与 `plugins/soulcore-settings/icon.svg` 为本项目
自绘的简单 SVG，不包含第三方图标资源。
