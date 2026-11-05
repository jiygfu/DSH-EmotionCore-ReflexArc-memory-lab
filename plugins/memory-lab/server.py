#!/usr/bin/env python3
"""memory-lab local sidecar API.

Reads soulcore.db read-only. Writes only data/memory-lab.db and the plugin's
own config.json. No QQ tools, no L5/ReflexArc integration.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import lab  # noqa: E402
import lab_config  # noqa: E402
import lab_edges  # noqa: E402
import lab_graph  # noqa: E402
import lab_terms  # noqa: E402
import lab_vectors  # noqa: E402

DEFAULT_DB = ROOT / "data" / "soulcore.db"


def _send(handler, status: int, data) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("content-length", str(len(body)))
    handler.send_header("access-control-allow-origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "memory-lab/0.1"

    def log_message(self, fmt, *args):
        return

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET,POST,OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/health":
            return _send(self, 200, {"ok": True, "service": "memory-lab", "db": str(DEFAULT_DB)})
        if u.path == "/settings":
            return _send(self, 200, {"ok": True, "settings": lab_config.read()})
        if u.path == "/review":
            if not lab_config.human_review_enabled():
                return _send(self, 400, {"ok": False, "error": "humanReview is disabled"})
            c = lab.connect_ro(str(DEFAULT_DB))
            try:
                out = lab.write_review_sheet(c, limit=int(lab_config.read().get("reviewLimit") or 8))
                return _send(self, 200, {"ok": True, "path": str(out)})
            finally:
                c.close()
        if u.path == "/terms":
            c = lab_terms.connect()
            try:
                return _send(self, 200, {"ok": True, "terms": lab_terms.terms(c)})
            finally:
                c.close()
        if u.path == "/edges":
            c = lab_edges.connect()
            try:
                rows = c.execute("SELECT * FROM lab_edges ORDER BY src,weight DESC LIMIT 200").fetchall()
                return _send(self, 200, {"ok": True, "edges": [dict(x) for x in rows]})
            finally:
                c.close()
        if u.path == "/graph":
            main = lab.connect_ro(str(DEFAULT_DB))
            try:
                return _send(self, 200, {"ok": True, **lab_graph.graph(main, limit=int((qs.get("limit") or ["120"])[0]))})
            finally:
                main.close()
        if u.path == "/recall":
            q = (qs.get("q") or [""])[0].strip()
            if not q:
                return _send(self, 400, {"ok": False, "error": "q required"})
            limit = int((qs.get("limit") or ["6"])[0])
            c = lab.connect_ro(str(DEFAULT_DB))
            try:
                return _send(self, 200, {"ok": True, **lab.rrf_recall(c, q, limit=limit)})
            finally:
                c.close()
        if u.path == "/vectors":
            # S6 影子模式：看向量路现在能捞出什么，不参与注入
            q = (qs.get("q") or [""])[0].strip()
            if not q:
                return _send(self, 400, {"ok": False, "error": "q required"})
            limit = int((qs.get("limit") or ["5"])[0])
            min_score = float((qs.get("min") or [lab_config.read().get("vectorMinScore") or 0.55])[0])
            c = lab.connect_ro(str(DEFAULT_DB))
            try:
                hits = lab_vectors.search(c, q, limit=limit, min_score=min_score)
                return _send(self, 200, {"ok": True, "q": q, "minScore": min_score,
                                         "available": lab_vectors.available(), "items": hits})
            finally:
                c.close()
        return _send(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("content-length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return _send(self, 400, {"ok": False, "error": "invalid json"})
        if u.path == "/settings":
            allowed = {k: payload[k] for k in ("humanReview", "reviewLimit", "reviewFile", "termsFile",
                                               "vectorEnabled", "vectorMinScore") if k in payload}
            return _send(self, 200, {"ok": True, "settings": lab_config.write(allowed)})
        if u.path == "/vectors/backfill":
            # 新记忆进来之后补向量；只处理 active 且非 sensitive
            limit = int(payload.get("limit") or 256)
            c = lab.connect_ro(str(DEFAULT_DB))
            try:
                return _send(self, 200, {"ok": True, **lab_vectors.embed_missing(c, limit=limit)})
            finally:
                c.close()
        if u.path == "/terms":
            term = str(payload.get("term") or "").strip()
            kind = str(payload.get("kind") or "meta").strip()
            if not term:
                return _send(self, 400, {"ok": False, "error": "term required"})
            c = lab_terms.connect()
            try:
                import datetime
                now = datetime.datetime.now().astimezone().isoformat()
                c.execute(
                    """INSERT OR REPLACE INTO lab_terms(term,kind,weight,action,enabled,note,updated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (term, kind, float(payload.get("weight") or 0.5), str(payload.get("action") or "penalty"),
                     1 if payload.get("enabled", True) else 0, str(payload.get("note") or ""), now),
                )
                c.commit()
                return _send(self, 200, {"ok": True, "term": dict(c.execute("SELECT * FROM lab_terms WHERE term=? AND kind=?", (term, kind)).fetchone())})
            finally:
                c.close()
        return _send(self, 404, {"ok": False, "error": "not found"})


def _boot_backfill(delay: float = 3.0, interval: float = 600.0) -> None:
    """定期补向量。

    S9 顺手补的：原来只在启动时补一次，运行中新进来的记忆永远没有向量——
    向量路会悄悄变窄，而影子对比还照旧算得"挺好"，看不出缺人。
    现在每 10 分钟扫一遍缺口的，补上就停。
    """
    import threading
    import time

    def run() -> None:
        time.sleep(delay)
        while True:
            if lab_vectors.available():
                conn = None
                try:
                    conn = lab.connect_ro(str(DEFAULT_DB))
                    out = lab_vectors.embed_missing(conn, limit=400)
                    if out.get("written"):
                        print(f"[memory-lab] backfill: {out}", flush=True)
                except Exception as exc:  # 补不上不影响主流程
                    print(f"[memory-lab] backfill failed: {exc}", flush=True)
                finally:
                    if conn is not None:
                        conn.close()
            time.sleep(max(60.0, float(interval)))

    threading.Thread(target=run, name="memlab-backfill", daemon=True).start()


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"memory-lab listening http://{args.host}:{args.port}")
    _boot_backfill()
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
