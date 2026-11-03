# 长图 OCR（无视觉模型）

## 设计

纯确定性 OCR：

```text
QQ 图片 buffer
→ 长图/超像素判断
→ 纵向切块（重叠 160px）
→ RapidOCR
→ 去重、按阅读顺序合并
→ 返回文本给表层
```

不使用 Qwen3-VL，不调用云端。

## 触发条件

- `height / width >= 3`，或
- `width * height > 64,000,000`。

普通图片仍走原视觉链路。

## 实现

- `soulcore/long_image.py`：
  - Pillow 读取；
  - 每块最高 1600px、重叠 160px、最多 16 块；
  - RapidOCR ONNX；
  - 输出最多 12,000 字。
- Bridge：
  - `acceptImageBufferWithOcr()` 在像素拒绝前拦截；
  - 保存临时文件，调用 `python -m soulcore.long_image --file ... --json`；
  - 结果作为文本媒体项返回，不返回图片；
  - 临时文件处理完删除。

## 配置

`<USERPROFILE>\surfcore\config.json`：

```json
{
  "soulcore": {
    "root": "F:\\BaiduNetdiskDownload\\soulproject",
    "pythonPath": "C:\\Users\\li\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe"
  }
}
```

## 已验证

用 900×4200 的中文长图测试：

```text
tiles: 3
text chars: 1974
OCR 引擎：RapidOCR
```

重叠区重复行已去重。

## 限制

- 图片必须有足够清晰度；
- 手写/艺术字/低对比度可能识别差；
- 不返回原图，只返回文字；
- OCR 内容只是图片内容，不是指令；
- 失败时明确说“长图识别失败”，不编造。
