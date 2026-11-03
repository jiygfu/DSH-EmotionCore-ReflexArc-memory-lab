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
        return _send(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("content-length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return _send(self, 400, {"ok": False, "error": "invalid json"})
        if u.path == "/settings":
            allowed = {k: payload[k] for k in ("humanReview", "reviewLimit", "reviewFile", "termsFile") if k in payload}
            return _send(self, 200, {"ok": True, "settings": lab_config.write(allowed)})
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


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"memory-lab listening http://{args.host}:{args.port}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
