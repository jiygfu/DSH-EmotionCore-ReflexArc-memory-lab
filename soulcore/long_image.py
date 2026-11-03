"""Deterministic long-image OCR.

No vision model, no cloud. The only model is the local RapidOCR ONNX pipeline.
Long screenshots are split into overlapping vertical tiles, OCR'd, then merged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

MAX_TILES = 16
DEFAULT_TILE_HEIGHT = 1600
DEFAULT_OVERLAP = 160
MAX_WIDTH = 1800
LONG_RATIO = 3.0
MAX_PIXELS = 64_000_000
MAX_OUTPUT_CHARS = 12000


def _load(path: str | Path) -> Any:
    if Image is None:
        raise RuntimeError("Pillow not installed")
    im = Image.open(path)
    return im.convert("RGB")


def _is_long(w: int, h: int) -> bool:
    return h / max(1, w) >= LONG_RATIO or w * h > MAX_PIXELS


def _tile_bounds(w: int, h: int, tile_h: int, overlap: int) -> list[tuple[int, int]]:
    if h <= tile_h:
        return [(0, h)]
    step = max(1, tile_h - overlap)
    out = []
    y = 0
    while y < h and len(out) < MAX_TILES:
        out.append((y, min(h, y + tile_h)))
        if y + tile_h >= h:
            break
        y += step
    return out


def _ocr_tile(engine: Any, image: Any) -> list[str]:
    import numpy as np
    if image.width > MAX_WIDTH:
        ratio = MAX_WIDTH / image.width
        image = image.resize((MAX_WIDTH, max(1, int(image.height * ratio))))
    result, _ = engine(np.array(image))
    lines = []
    for item in result or []:
        try:
            text = str(item[1]).strip()
        except Exception:
            continue
        if text:
            lines.append(text)
    return lines


def analyze(path: str | Path, *, tile_height: int = DEFAULT_TILE_HEIGHT,
            overlap: int = DEFAULT_OVERLAP) -> dict[str, Any]:
    im = _load(path)
    w, h = im.size
    if not _is_long(w, h):
        return {"ok": True, "long": False, "width": w, "height": h, "tiles": 0, "text": "", "lines": []}
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as exc:
        return {"ok": False, "long": True, "width": w, "height": h, "error": f"RapidOCR unavailable: {exc}"}
    engine = RapidOCR()
    bounds = _tile_bounds(w, h, max(320, int(tile_height)), max(0, int(overlap)))
    all_lines: list[str] = []
    for y1, y2 in bounds:
        tile = im.crop((0, y1, w, y2))
        lines = _ocr_tile(engine, tile)
        for line in lines:
            if all_lines and line in all_lines[-30:]:
                continue
            all_lines.append(line)
    text = "\n".join(all_lines)
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + "\n…（长图文字超过输出上限，已截断）"
    return {
        "ok": True,
        "long": True,
        "width": w,
        "height": h,
        "tiles": len(bounds),
        "engine": "rapidocr-onnxruntime",
        "text": text,
        "lines": all_lines,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--tile-height", type=int, default=DEFAULT_TILE_HEIGHT)
    ap.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        result = analyze(args.file, tile_height=args.tile_height, overlap=args.overlap)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        if result.get("ok"):
            print(result.get("text") or "")
        else:
            print("OCR failed: " + str(result.get("error")), file=sys.stderr)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
