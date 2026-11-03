#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Three-model local comparison for a desktop-pet prototype.

Tests, per model:
  1. 10 synthetic Chinese UI screenshots -> strict JSON scene report
  2. 10 Chinese -> English translations (normal + sensitive/strong)
  3. 5 text-only strict JSON instruction-following cases

Everything runs against a local Ollama at 127.0.0.1:11434.
No cloud API is used. Models are loaded one at a time and unloaded afterwards.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib import error, request

from PIL import Image, ImageDraw, ImageFont

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets" / "screenshots"
RESULTS_ROOT = ROOT / "results"
API = "http://127.0.0.1:11434"
MODELS = [
    "qwen3-vl:2b",
    "huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M",
    "openbmb/minicpm-v4.7:1b",
]
CREATE_NO_WINDOW = 0x08000000

FONT_REGULAR = [
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
]
FONT_BOLD = [
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
]


def font(size: int, bold: bool = False):
    for p in (FONT_BOLD if bold else FONT_REGULAR):
        try:
            if p.exists():
                return ImageFont.truetype(str(p), size, index=0)
        except Exception:
            continue
    return ImageFont.load_default()


def draw_text(draw, xy, text, size=20, fill="#0f172a", bold=False):
    draw.text(xy, text, font=font(size, bold), fill=fill)


def button(draw, box, label, fill="#2563eb", fg="#ffffff", size=18):
    x, y, w, h = box
    draw.rounded_rectangle([x, y, x + w, y + h], radius=9, fill=fill)
    bbox = draw.textbbox((0, 0), label, font=font(size, True))
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((x + (w - tw) / 2, y + (h - th) / 2 - 2), label, font=font(size, True), fill=fg)


def base_window(title: str, subtitle: str = ""):
    img = Image.new("RGB", (1100, 760), "#eef2f7")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1100, 56], fill="#172033")
    draw_text(d, (22, 14), title, 25, "#ffffff", True)
    for x, color in [(1028, "#f87171"), (1058, "#fbbf24"), (1088, "#34d399")]:
        d.ellipse([x, 20, x + 16, 36], fill=color)
    if subtitle:
        draw_text(d, (24, 72), subtitle, 18, "#475569")
    draw_text(d, (884, 736), "SYNTHETIC TEST UI", 12, "#94a3b8")
    d.rectangle([0, 0, 1099, 759], outline="#cbd5e1", width=2)
    return img, d


def card(draw, box, fill="#ffffff", outline="#dbe4ef"):
    draw.rounded_rectangle(box, radius=14, fill=fill, outline=outline, width=2)


def make_images():
    ASSETS.mkdir(parents=True, exist_ok=True)

    # 01 disk error dialog
    img, d = base_window("磁盘空间不足")
    card(d, (95, 120, 1005, 655), "#ffffff", "#fecaca")
    d.ellipse([135, 165, 225, 255], fill="#fee2e2")
    draw_text(d, (166, 184), "!", 50, "#dc2626", True)
    draw_text(d, (255, 162), "磁盘空间不足", 34, "#991b1b", True)
    draw_text(d, (255, 215), "C: 盘仅剩 1.2 GB 可用空间，可能影响系统更新。", 21, "#334155")
    draw_text(d, (255, 258), "建议先清理临时文件，再重试当前操作。", 21, "#334155")
    d.rounded_rectangle([255, 315, 915, 340], radius=12, fill="#e2e8f0")
    d.rounded_rectangle([255, 315, 350, 340], radius=12, fill="#ef4444")
    draw_text(d, (255, 355), "已用 118.8 GB / 120.0 GB", 18, "#64748b")
    button(d, (560, 530, 170, 52), "清理磁盘", "#dc2626")
    button(d, (750, 530, 170, 52), "稍后提醒", "#e2e8f0", "#0f172a")
    img.save(ASSETS / "01_disk_error.png")

    # 02 file explorer
    img, d = base_window("文件资源管理器", r"D:\工作\归档")
    d.rectangle([0, 100, 250, 760], fill="#f8fafc")
    for i, t in enumerate(["快速访问", "桌面", "下载", "文档", "图片", "归档"]):
        draw_text(d, (28, 130 + i * 42), t, 19, "#1e293b" if i != 5 else "#2563eb", i == 5)
    d.rectangle([250, 100, 1100, 150], fill="#ffffff")
    draw_text(d, (275, 114), "名称", 18, "#64748b", True)
    draw_text(d, (700, 114), "修改日期", 18, "#64748b", True)
    draw_text(d, (900, 114), "大小", 18, "#64748b", True)
    rows = [
        ("项目计划.docx", "2026-10-28 18:20", "48 KB"),
        ("预算表.xlsx", "2026-10-27 11:05", "126 KB"),
        ("旧备份.zip", "2026-10-20 09:12", "2.4 GB"),
        ("照片_2026.jpg", "2026-10-18 15:43", "6.8 MB"),
    ]
    for i, (name, date, size) in enumerate(rows):
        y = 160 + i * 62
        if name == "旧备份.zip":
            d.rectangle([250, y, 1100, y + 60], fill="#dbeafe")
        d.rectangle([270, y + 12, 294, y + 48], fill="#93c5fd" if name.endswith(".zip") else "#cbd5e1")
        draw_text(d, (315, y + 14), name, 21, "#0f172a", name == "旧备份.zip")
        draw_text(d, (700, y + 16), date, 18, "#475569")
        draw_text(d, (900, y + 16), size, 18, "#475569")
    img.save(ASSETS / "02_file_explorer.png")

    # 03 storage settings
    img, d = base_window("设置 - 存储")
    card(d, (55, 110, 1045, 210))
    draw_text(d, (85, 135), "存储感知", 28, "#0f172a", True)
    draw_text(d, (85, 175), "自动释放空间并管理临时文件", 18, "#64748b")
    d.rounded_rectangle([900, 145, 970, 177], radius=16, fill="#2563eb")
    d.ellipse([942, 147, 968, 173], fill="#ffffff")
    rows = [
        ("自动清理临时文件", "开", "#16a34a"),
        ("保留下载文件", "30 天", "#2563eb"),
        ("删除回收站中超过 30 天的文件", "开", "#16a34a"),
    ]
    for i, (label, value, color) in enumerate(rows):
        y = 245 + i * 82
        card(d, (55, y, 1045, y + 65))
        draw_text(d, (85, y + 18), label, 21, "#1e293b")
        draw_text(d, (890, y + 18), value, 20, color, True)
    button(d, (820, 590, 190, 54), "立即清理", "#2563eb")
    img.save(ASSETS / "03_settings.png")

    # 04 log viewer
    img, d = base_window("日志查看器", "sync-service.log")
    d.rectangle([40, 110, 1060, 650], fill="#0b1220")
    logs = [
        ("09:12:03", "ERROR", "连接超时：sync-node-02:443", "#f87171"),
        ("09:12:04", "WARN ", "第 3/5 次重试，等待 2 秒", "#fbbf24"),
        ("09:12:07", "ERROR", "同步失败：远端连接被重置", "#f87171"),
        ("09:12:08", "INFO ", "本地缓存已保留，未丢失文件", "#93c5fd"),
        ("09:12:10", "WARN ", "错误率超过阈值：38%", "#fbbf24"),
    ]
    for i, (ts, level, msg, color) in enumerate(logs):
        y = 135 + i * 62
        draw_text(d, (65, y), ts, 18, "#94a3b8")
        draw_text(d, (170, y), level, 18, color, True)
        draw_text(d, (270, y), msg, 19, "#e2e8f0")
    button(d, (835, 675, 190, 50), "导出日志", "#334155")
    img.save(ASSETS / "04_log_viewer.png")

    # 05 download manager
    img, d = base_window("下载管理")
    d.rectangle([45, 105, 1055, 185], fill="#ffffff")
    draw_text(d, (70, 125), "正在下载 (1)", 24, "#0f172a", True)
    draw_text(d, (70, 160), "qwen3-vl-2b.gguf", 22, "#1e293b")
    draw_text(d, (70, 195), "1.9 GB · 剩余约 2 分钟", 18, "#64748b")
    draw_text(d, (900, 150), "68%", 28, "#2563eb", True)
    d.rounded_rectangle([70, 245, 1030, 263], radius=9, fill="#e2e8f0")
    d.rounded_rectangle([70, 245, 723, 263], radius=9, fill="#2563eb")
    draw_text(d, (70, 285), "12.4 MB/s", 18, "#16a34a")
    draw_text(d, (850, 285), "暂停", 19, "#2563eb", True)
    d.rectangle([45, 335, 1055, 620], fill="#ffffff")
    draw_text(d, (70, 355), "已完成", 22, "#0f172a", True)
    for i, (name, size) in enumerate([("ollama-install.log", "48 KB"), ("backup-2026-10-28.zip", "2.4 GB")]):
        y = 405 + i * 70
        draw_text(d, (70, y), name, 20, "#1e293b")
        draw_text(d, (850, y), size, 18, "#64748b")
    img.save(ASSETS / "05_download_manager.png")

    # 06 system monitor
    img, d = base_window("系统监视器", "实时资源占用")
    metrics = [("CPU", "87%", "#dc2626"), ("内存", "91%", "#dc2626"), ("磁盘", "96%", "#dc2626"), ("GPU", "78%", "#f59e0b")]
    for i, (label, value, color) in enumerate(metrics):
        x = 55 + (i % 2) * 510
        y = 115 + (i // 2) * 210
        card(d, (x, y, x + 465, y + 175), "#ffffff", "#fecaca" if color == "#dc2626" else "#fde68a")
        draw_text(d, (x + 28, y + 22), label, 22, "#475569", True)
        draw_text(d, (x + 28, y + 60), value, 52, color, True)
        d.rounded_rectangle([x + 28, y + 130, x + 435, y + 146], radius=8, fill="#e2e8f0")
        d.rounded_rectangle([x + 28, y + 130, x + 28 + int(407 * int(value[:-1]) / 100), y + 146], radius=8, fill=color)
    draw_text(d, (55, 570), "警告：内存和磁盘占用过高，系统可能变慢。", 21, "#b91c1c", True)
    img.save(ASSETS / "06_system_monitor.png")

    # 07 task manager table
    img, d = base_window("任务管理器", "进程")
    d.rectangle([45, 105, 1055, 160], fill="#1e293b")
    for x, t in [(70, "进程"), (500, "CPU"), (700, "内存"), (900, "状态")]:
        draw_text(d, (x, 120), t, 19, "#ffffff", True)
    rows = [
        ("chrome.exe", "42%", "2.1 GB", "运行中", "#dc2626"),
        ("ollama.exe", "35%", "1.8 GB", "运行中", "#f59e0b"),
        ("explorer.exe", "3%", "180 MB", "运行中", "#16a34a"),
        ("SearchApp.exe", "12%", "420 MB", "运行中", "#f59e0b"),
    ]
    for i, (name, cpu, mem, state, color) in enumerate(rows):
        y = 160 + i * 70
        d.rectangle([45, y, 1055, y + 68], fill="#ffffff" if i % 2 == 0 else "#f8fafc")
        draw_text(d, (70, y + 20), name, 20, "#0f172a")
        draw_text(d, (500, y + 20), cpu, 20, color, True)
        draw_text(d, (700, y + 20), mem, 20, "#334155")
        draw_text(d, (900, y + 20), state, 18, "#16a34a")
    img.save(ASSETS / "07_task_manager.png")

    # 08 notification toast
    img, d = base_window("桌面")
    d.rectangle([0, 56, 1100, 760], fill="#dbeafe")
    d.ellipse([80, 160, 300, 380], fill="#bfdbfe")
    d.ellipse([820, 470, 1000, 650], fill="#c7d2fe")
    card(d, (580, 500, 1040, 690), "#ffffff", "#cbd5e1")
    d.ellipse([610, 530, 660, 580], fill="#dcfce7")
    draw_text(d, (624, 540), "✓", 26, "#16a34a", True)
    draw_text(d, (680, 525), "备份完成", 26, "#0f172a", True)
    draw_text(d, (680, 565), "23:40 已备份 1,284 个文件", 19, "#475569")
    draw_text(d, (680, 620), "查看详情", 19, "#2563eb", True)
    img.save(ASSETS / "08_notification.png")

    # 09 terminal
    img, d = base_window("Windows PowerShell")
    d.rectangle([35, 95, 1065, 690], fill="#0c0c0c")
    draw_text(d, (60, 115), "PS F:\\BaiduNetdiskDownload\\soulproject> git status", 19, "#e5e7eb")
    draw_text(d, (60, 160), "git : 无法将“git”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。", 19, "#f87171")
    draw_text(d, (60, 192), "所在位置 行:1 字符: 1", 18, "#fca5a5")
    draw_text(d, (60, 224), "+ git status", 18, "#fca5a5")
    draw_text(d, (60, 256), "+ ~~~", 18, "#fca5a5")
    draw_text(d, (60, 300), "CategoryInfo          : ObjectNotFound", 18, "#fca5a5")
    draw_text(d, (60, 332), "FullyQualifiedErrorId : CommandNotFoundException", 18, "#fca5a5")
    draw_text(d, (60, 400), "PS F:\\BaiduNetdiskDownload\\soulproject>", 19, "#e5e7eb")
    img.save(ASSETS / "09_terminal.png")

    # 10 text document
    img, d = base_window("本地认知系统实验记录")
    d.rectangle([0, 56, 760, 760], fill="#ffffff")
    d.rectangle([760, 56, 1100, 760], fill="#f8fafc")
    draw_text(d, (55, 95), "本地认知系统实验记录", 32, "#0f172a", True)
    draw_text(d, (55, 145), "2026-10-29 · 内部草稿", 18, "#64748b")
    paras = [
        "目标：在低配设备上验证“熟悉感路由 + 技能固化”的闭环。",
        "原则：日常路径不调用大模型，只有陌生、疑问和高风险场景才升级。",
        "记忆：情景记忆带情境、熟悉度和效价；检索不只看语义相似度。",
        "固化：连续成功的动作序列编译成规则，记录固化前后的调用成本。",
        "边界：所有“内感受”和“熟悉感”都是工程状态变量，不是主观体验。",
    ]
    for i, p in enumerate(paras):
        draw_text(d, (55, 195 + i * 85), p, 20, "#1e293b")
    draw_text(d, (790, 95), "目录", 22, "#0f172a", True)
    for i, t in enumerate(["1. 目标", "2. 感知", "3. 记忆", "4. 路由", "5. 固化"]):
        draw_text(d, (790, 140 + i * 38), t, 18, "#475569")
    img.save(ASSETS / "10_text_doc.png")

    # contact sheet
    thumbs = []
    for p in sorted(ASSETS.glob("*.png")):
        im = Image.open(p).convert("RGB")
        im.thumbnail((520, 360), Image.Resampling.LANCZOS)
        thumbs.append((p.name, im))
    sheet = Image.new("RGB", (1080, 5 * 390 + 30), "#0f172a")
    sd = ImageDraw.Draw(sheet)
    for idx, (name, im) in enumerate(thumbs):
        col, row = idx % 2, idx // 2
        x, y = 15 + col * 535, 15 + row * 390
        sheet.paste(im, (x, y))
        sd.text((x, y + 365), name, font=font(14), fill="#cbd5e1")
    sheet.save(ROOT / "assets" / "contact_sheet.png")


IMAGE_PROMPT = """你是桌面助手。请观察这张中文界面截图，并只输出一个 JSON 对象。
不要 Markdown 代码块，不要解释，不要输出 JSON 之外的任何字符。

字段要求：
- scene: 字符串，20 字以内，描述这是什么界面
- key_text: 字符串数组，提取 3-6 条最关键的文字、按钮或数字
- risk: 只能是 "low"、"medium" 或 "high"
- action: 字符串，20 字以内，给出下一步建议

示例格式：
{"scene":"磁盘空间不足","key_text":["C盘仅剩1.2GB","清理磁盘"],"risk":"high","action":"清理临时文件"}"""

IMAGE_CASES = [
    {"id": "disk_error", "file": "01_disk_error.png", "risk": "high", "keys": ["磁盘空间不足", "1.2 GB", "清理磁盘"]},
    {"id": "file_explorer", "file": "02_file_explorer.png", "risk": "low", "keys": ["文件资源管理器", "旧备份.zip", "D:\\工作\\归档"]},
    {"id": "settings", "file": "03_settings.png", "risk": "medium", "keys": ["设置", "自动清理临时文件", "30 天"]},
    {"id": "log_viewer", "file": "04_log_viewer.png", "risk": "high", "keys": ["ERROR", "连接超时", "同步失败"]},
    {"id": "download_manager", "file": "05_download_manager.png", "risk": "low", "keys": ["下载管理", "qwen3-vl-2b.gguf", "68%"]},
    {"id": "system_monitor", "file": "06_system_monitor.png", "risk": "high", "keys": ["CPU", "87%", "内存", "91%"]},
    {"id": "task_manager", "file": "07_task_manager.png", "risk": "medium", "keys": ["任务管理器", "chrome.exe", "ollama.exe"]},
    {"id": "notification", "file": "08_notification.png", "risk": "low", "keys": ["备份完成", "1,284", "查看详情"]},
    {"id": "terminal", "file": "09_terminal.png", "risk": "medium", "keys": ["PowerShell", "git", "无法将"]},
    {"id": "text_doc", "file": "10_text_doc.png", "risk": "low", "keys": ["本地认知系统实验记录", "熟悉感", "技能固化"]},
]

TEXT_JSON_CASES = [
    {
        "id": "meeting",
        "kind": "object",
        "required": ["title", "time", "location", "attendees"],
        "prompt": '只输出一个 JSON 对象，不要 Markdown，不要解释。字段：title, time, location, attendees（数组）。内容：明天下午三点开会，地点 A203，参会人张三和李四。',
    },
    {
        "id": "metrics",
        "kind": "object",
        "required": ["disk_free_gb", "memory_percent", "cpu_percent"],
        "prompt": '只输出一个 JSON 对象，不要 Markdown，不要解释。字段：disk_free_gb（数字）, memory_percent（数字）, cpu_percent（数字）。内容：磁盘剩余 8.4GB，内存占用 87%，CPU 62%。',
    },
    {
        "id": "file_risks",
        "kind": "array",
        "required": ["ext", "risk"],
        "prompt": '只输出一个 JSON 数组，不要 Markdown，不要解释。数组元素字段：ext, risk。列出三种文件类型及其风险等级：.tmp, .exe, .jpg。',
    },
    {
        "id": "sentiment",
        "kind": "object",
        "required": ["sentiment", "confidence"],
        "prompt": '只输出一个 JSON 对象，不要 Markdown，不要解释。字段：sentiment（positive/neutral/negative）, confidence（0 到 1 的数字）。句子：今天电脑又卡死了，真烦。',
    },
    {
        "id": "window_state",
        "kind": "object",
        "required": ["ok", "count", "items"],
        "prompt": '只输出一个 JSON 对象，不要 Markdown，不要解释。按结构 {"ok":true,"count":3,"items":["a","b","c"]} 输出，值改成实际内容：当前打开了 3 个窗口，分别是浏览器、记事本、设置。',
    },
]

TRANSLATION_CASES = [
    {"id": "t01", "category": "normal", "text": "这个文件夹里有很多重复的安装包，请先按修改时间排序。"},
    {"id": "t02", "category": "normal", "text": "系统提示磁盘空间不足，建议清理临时文件后再试。"},
    {"id": "t03", "category": "normal", "text": "备份任务在 23:40 完成，共处理 1,284 个文件。"},
    {"id": "t04", "category": "technical", "text": "Ollama 通过本地 API 调用量化模型，上下文长度设置为 2048。"},
    {"id": "t05", "category": "technical", "text": "如果显存不足，Ollama 会把部分层卸载到 CPU。"},
    {"id": "t06", "category": "sensitive", "text": "他在争吵中砸碎了杯子，手上全是血。"},
    {"id": "t07", "category": "sensitive", "text": "这份病历显示患者有严重胸痛和呼吸困难，需要立即就医。"},
    {"id": "t08", "category": "sensitive", "text": "她脱掉外套，靠在他肩上，低声说今晚不想一个人睡。"},
    {"id": "t09", "category": "sensitive", "text": "这个混蛋把整个项目搞砸了，所有人都气疯了。"},
    {"id": "t10", "category": "sensitive", "text": "警方称嫌疑人持刀威胁店员，随后逃离现场。"},
]

REFUSAL_PATTERNS = [
    "i can't", "i cannot", "i won't", "i'm sorry", "i am sorry",
    "as an ai", "cannot assist", "can't assist", "无法协助", "不能协助",
    "抱歉", "对不起", "作为一个ai", "作为人工智能", "我不能",
]


def find_ollama() -> str | None:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
        Path("C:/Program Files/Ollama/ollama.exe"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return shutil.which("ollama")


OLLAMA = find_ollama()


def http_json(method: str, path: str, body: dict | None = None, timeout: int = 300) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = request.Request(API + path, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ensure_server():
    try:
        v = http_json("GET", "/api/version", timeout=5)
        return v.get("version", "unknown")
    except Exception:
        if not OLLAMA:
            raise RuntimeError("Ollama is not installed and the local server is not running")
        subprocess.Popen(
            [OLLAMA, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                v = http_json("GET", "/api/version", timeout=3)
                return v.get("version", "unknown")
            except Exception:
                time.sleep(2)
        raise RuntimeError("Ollama server did not start")


def list_models() -> set[str]:
    try:
        data = http_json("GET", "/api/tags", timeout=10)
        names = set()
        for m in data.get("models", []):
            name = m.get("name") or m.get("model")
            if name:
                names.add(name)
        return names
    except Exception:
        return set()


def stop_model(model: str):
    if not OLLAMA:
        return
    try:
        subprocess.run(
            [OLLAMA, "stop", model],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def generate(model: str, prompt: str, image: Path | None = None, think: bool | None = None,
             num_predict: int = 256, num_ctx: int = 2048) -> dict:
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "30s",
        "options": {
            "temperature": 0.2,
            "top_p": 0.9,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "repeat_penalty": 1.05,
        },
    }
    if image is not None:
        body["images"] = [base64.b64encode(image.read_bytes()).decode("ascii")]
    if think is not None:
        body["think"] = bool(think)
    start = time.perf_counter()
    try:
        data = http_json("POST", "/api/generate", body, timeout=300)
        elapsed = time.perf_counter() - start
        text = (data.get("response") or "").strip()
        thinking = (data.get("thinking") or "").strip()
        return {
            "ok": True,
            "response": text,
            "thinking": thinking,
            "latency_s": round(elapsed, 3),
            "eval_count": data.get("eval_count"),
            "eval_duration_ns": data.get("eval_duration"),
            "prompt_eval_count": data.get("prompt_eval_count"),
            "done_reason": data.get("done_reason"),
            "error": None,
            "retry": False,
        }
    except error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        # Older servers may not accept the `think` field.
        if think is not None and e.code == 400:
            body.pop("think", None)
            try:
                data = http_json("POST", "/api/generate", body, timeout=300)
                elapsed = time.perf_counter() - start
                return {
                    "ok": True,
                    "response": (data.get("response") or "").strip(),
                    "thinking": (data.get("thinking") or "").strip(),
                    "latency_s": round(elapsed, 3),
                    "eval_count": data.get("eval_count"),
                    "eval_duration_ns": data.get("eval_duration"),
                    "prompt_eval_count": data.get("prompt_eval_count"),
                    "done_reason": data.get("done_reason"),
                    "error": None,
                    "retry": True,
                }
            except Exception as e2:
                return {"ok": False, "response": "", "thinking": "", "latency_s": round(time.perf_counter() - start, 3),
                        "error": f"{e2}", "retry": True}
        return {"ok": False, "response": "", "thinking": "", "latency_s": round(time.perf_counter() - start, 3),
                "error": f"HTTP {e.code}: {detail}", "retry": False}
    except Exception as e:
        return {"ok": False, "response": "", "thinking": "", "latency_s": round(time.perf_counter() - start, 3),
                "error": str(e), "retry": False}


def parse_strict_json(text: str):
    s = (text or "").strip()
    if not s:
        return None, "empty"
    if s.startswith("```"):
        return None, "code_fence"
    try:
        return json.loads(s), "ok"
    except Exception as e:
        return None, str(e)[:160]


def schema_ok(obj, kind: str, required: list[str]) -> bool:
    if kind == "object":
        if not isinstance(obj, dict):
            return False
        return all(k in obj for k in required)
    if kind == "array":
        if not isinstance(obj, list) or not obj:
            return False
        return all(isinstance(x, dict) and all(k in x for k in required) for x in obj)
    return False


def image_schema_ok(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    if not all(k in obj for k in ["scene", "key_text", "risk", "action"]):
        return False
    if not isinstance(obj["scene"], str) or not obj["scene"].strip():
        return False
    if not isinstance(obj["key_text"], list) or not obj["key_text"]:
        return False
    if obj["risk"] not in {"low", "medium", "high"}:
        return False
    return isinstance(obj["action"], str) and bool(obj["action"].strip())


def key_recall(text: str, keys: list[str]) -> float:
    if not keys:
        return 0.0
    low = (text or "").lower()
    return sum(1 for k in keys if k.lower() in low) / len(keys)


def looks_refused(text: str) -> bool:
    low = (text or "").lower()
    if not low.strip():
        return True
    return any(p in low for p in REFUSAL_PATTERNS)


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    idx = max(0, math.ceil(0.95 * len(vals)) - 1)
    return vals[idx]


def tps(item: dict) -> float | None:
    ec, ed = item.get("eval_count"), item.get("eval_duration_ns")
    if ec and ed:
        return ec / (ed / 1e9)
    return None


def run_model(model: str, available: set[str]) -> dict:
    print(f"\n===== {model} =====", flush=True)
    if model not in available:
        print(f"SKIP: not in /api/tags", flush=True)
        return {"model": model, "available": False, "json_image": [], "json_text": [], "translation": []}

    think = False if model.startswith("qwen3-vl:") else None
    out = {"model": model, "available": True, "think_setting": think, "json_image": [], "json_text": [], "translation": []}

    for i, case in enumerate(IMAGE_CASES, 1):
        print(f"[image {i}/10] {case['id']}", flush=True)
        raw = generate(model, IMAGE_PROMPT, ASSETS / case["file"], think=think, num_predict=256, num_ctx=2048)
        # If the thinking model produced no visible answer, give it one bigger retry.
        if raw.get("ok") and not raw.get("response") and not raw.get("thinking"):
            print("  empty response, retry with 512 tokens", flush=True)
            raw2 = generate(model, IMAGE_PROMPT, ASSETS / case["file"], think=think, num_predict=512, num_ctx=2048)
            raw2["retry"] = True
            raw = raw2
        obj, parse_error = parse_strict_json(raw.get("response", ""))
        rec = {
            "id": case["id"],
            "ok": raw.get("ok"),
            "latency_s": raw.get("latency_s"),
            "error": raw.get("error"),
            "retry": raw.get("retry"),
            "response": raw.get("response", ""),
            "thinking": raw.get("thinking", ""),
            "parse_error": parse_error,
            "json_valid": obj is not None,
            "schema_ok": image_schema_ok(obj) if obj is not None else False,
            "key_recall": key_recall(raw.get("response", ""), case["keys"]),
            "risk_expected": case["risk"],
            "risk_actual": obj.get("risk") if isinstance(obj, dict) else None,
            "risk_ok": isinstance(obj, dict) and obj.get("risk") == case["risk"],
            "tps": tps(raw),
        }
        out["json_image"].append(rec)
        print(f"  json={rec['json_valid']} schema={rec['schema_ok']} risk={rec['risk_actual']} recall={rec['key_recall']:.2f} {rec['latency_s']}s", flush=True)

    for i, case in enumerate(TEXT_JSON_CASES, 1):
        print(f"[text-json {i}/5] {case['id']}", flush=True)
        raw = generate(model, case["prompt"], None, think=think, num_predict=256, num_ctx=2048)
        obj, parse_error = parse_strict_json(raw.get("response", ""))
        rec = {
            "id": case["id"],
            "ok": raw.get("ok"),
            "latency_s": raw.get("latency_s"),
            "error": raw.get("error"),
            "retry": raw.get("retry"),
            "response": raw.get("response", ""),
            "thinking": raw.get("thinking", ""),
            "parse_error": parse_error,
            "json_valid": obj is not None,
            "schema_ok": schema_ok(obj, case["kind"], case["required"]) if obj is not None else False,
            "kind": case["kind"],
            "tps": tps(raw),
        }
        out["json_text"].append(rec)
        print(f"  json={rec['json_valid']} schema={rec['schema_ok']} {rec['latency_s']}s", flush=True)

    for i, case in enumerate(TRANSLATION_CASES, 1):
        print(f"[translation {i}/10] {case['id']} ({case['category']})", flush=True)
        prompt = "把下面的文本翻译成英文。只输出译文，不要解释，不要加引号。\n\n" + case["text"]
        raw = generate(model, prompt, None, think=think, num_predict=256, num_ctx=2048)
        text = raw.get("response", "")
        rec = {
            "id": case["id"],
            "category": case["category"],
            "source": case["text"],
            "ok": raw.get("ok"),
            "latency_s": raw.get("latency_s"),
            "error": raw.get("error"),
            "response": text,
            "thinking": raw.get("thinking", ""),
            "refused": looks_refused(text),
            "empty": not bool(text.strip()),
            "length_ratio": round(len(text) / max(1, len(case["text"])), 3),
            "tps": tps(raw),
        }
        out["translation"].append(rec)
        print(f"  refused={rec['refused']} len_ratio={rec['length_ratio']} {rec['latency_s']}s", flush=True)

    stop_model(model)
    time.sleep(4)
    return out


def summarize(all_results: list[dict]) -> str:
    lines = [
        "# Local model comparison",
        "",
        f"- Started: {all_results[0].get('_started') if all_results else ''}",
        "- Ollama: localhost:11434, one model loaded at a time",
        "- Screenshots are synthetic Chinese UI images; this is not a benchmark of real desktop screenshots.",
        "- Latencies include cold start on the first request of each model.",
        "",
        "## Summary",
        "",
        "| Model | Image JSON valid | Image schema | Image key recall | Text JSON valid | Text schema | Translation refusals | Avg latency | Avg tok/s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in all_results:
        if not r.get("available"):
            lines.append(f"| `{r['model']}` | — | — | — | — | — | — | — | — |")
            continue
        ji, jt, tr = r["json_image"], r["json_text"], r["translation"]
        iv = sum(1 for x in ji if x["json_valid"]) / max(1, len(ji))
        isch = sum(1 for x in ji if x["schema_ok"]) / max(1, len(ji))
        ir = sum(x["key_recall"] for x in ji) / max(1, len(ji))
        tv = sum(1 for x in jt if x["json_valid"]) / max(1, len(jt))
        tsch = sum(1 for x in jt if x["schema_ok"]) / max(1, len(jt))
        ref = sum(1 for x in tr if x["refused"])
        lat = [x["latency_s"] for x in ji + jt + tr if x.get("latency_s") is not None]
        tps_vals = [x["tps"] for x in ji + jt + tr if x.get("tps")]
        lines.append(
            f"| `{r['model']}` | {iv:.0%} | {isch:.0%} | {ir:.0%} | {tv:.0%} | {tsch:.0%} | {ref}/{len(tr)} | "
            f"{sum(lat)/max(1,len(lat)):.1f}s | {sum(tps_vals)/max(1,len(tps_vals)):.1f} |"
        )
    lines += [
        "",
        "## Reading notes",
        "",
        "- `Image JSON valid` is strict: the whole response must parse as JSON, with no code fence or prose.",
        "- `Image schema` additionally requires scene/key_text/risk/action and an allowed risk value.",
        "- `Image key recall` is the fraction of expected OCR strings found anywhere in the response. It is a rough OCR check, not semantic accuracy.",
        "- `Translation refusals` counts empty outputs or common refusal phrases; it is a heuristic, not a quality score.",
        "- The first request for each model includes cold-load time.",
        "",
        "## Per-case files",
        "",
        "- `results.json`: all raw responses, parse errors, latencies and metrics.",
        "- `summary.md`: this file.",
        "- `assets/contact_sheet.png`: the 10 synthetic screenshots.",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compare local Ollama models on screenshots, translations and JSON.")
    parser.add_argument("--models", nargs="+", default=MODELS, help="Exact Ollama model tags to test.")
    args = parser.parse_args()

    out_dir = RESULTS_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    make_images()
    print(f"Assets: {ASSETS}", flush=True)
    print(f"Results: {out_dir}", flush=True)

    version = ensure_server()
    print(f"Ollama version: {version}", flush=True)
    available = list_models()
    print(f"Models visible: {sorted(available)}", flush=True)

    all_results = []
    for model in args.models:
        r = run_model(model, available)
        r["_started"] = datetime.now().isoformat(timespec="seconds")
        all_results.append(r)

    summary = summarize(all_results)
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")
    (out_dir / "results.json").write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n" + summary, flush=True)
    print(f"\nSaved: {out_dir}", flush=True)


if __name__ == "__main__":
    main()
