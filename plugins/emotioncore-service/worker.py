#!/usr/bin/env python3
"""EmotionCore local maintenance worker.

Runs only local fixed programs:
  appraise pending memories
  -> rebuild today's episodes
  -> refresh people
  -> ensure daily baseline
  -> write patience snapshot

It never calls the chat API and never writes a second memory store.
"""

from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from soulcore import appraise, body_state, consolidate, daybook, db, dream, episode_review, episodes, handoff, patience, people, purpose_seed, thread_loops, thread_model  # noqa: E402

LOG = Path(os.environ.get("EMOTIONCORE_WORKER_LOG") or (ROOT / "logs" / "emotioncore-worker.log"))
SCHEDULE = Path(os.environ.get("EMOTIONCORE_SCHEDULE") or (ROOT / "data" / "emotioncore-schedule.json"))


def read_schedule(default_hour: int) -> dict:
    """UI writes this file; worker reads it every loop so no restart is needed."""
    try:
        raw = json.loads(SCHEDULE.read_text(encoding="utf-8"))
        return {
            "auto": raw.get("auto", True) is not False,
            "hour": max(0, min(23, int(raw.get("hour", default_hour)))),
        }
    except Exception:
        return {"auto": True, "hour": max(0, min(23, int(default_hour)))}


def log(msg: str) -> None:
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def close_episodes(conn, *, close_after_hours: int = 6, archive_days: int = 30, threshold: float = 0.15) -> dict[str, int]:
    """Deterministic local lifecycle; never reopens a closed event."""
    now = datetime.now().astimezone()
    stats = {"closed": 0, "archived": 0}
    rows = conn.execute("SELECT id,day,end_at,start_at,unresolved,status FROM episodes").fetchall()
    for r in rows:
        status = str(r["status"] or "open")
        if status in ("closed", "archived"):
            continue
        end_raw = str(r["end_at"] or r["start_at"] or "")
        try:
            end = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
            if end.tzinfo is None:
                end = end.astimezone()
        except Exception:
            end = now
        age_days = max(0.0, (now - end).total_seconds() / 86400)
        if age_days >= archive_days:
            conn.execute("UPDATE episodes SET status='archived', closed_at=COALESCE(closed_at, ?), resolution_note=COALESCE(resolution_note, 'auto: archived after 30d') WHERE id=?", (now.isoformat(), r["id"]))
            stats["archived"] += 1
        elif age_days >= close_after_hours / 24 and float(r["unresolved"] or 0) <= threshold:
            conn.execute("UPDATE episodes SET status='closed', closed_at=COALESCE(closed_at, ?), resolution_note=COALESCE(resolution_note, 'auto: unresolved <= 0.15 after 6h') WHERE id=?", (now.isoformat(), r["id"]))
            stats["closed"] += 1
    conn.commit()
    return stats


def refresh_impressions(conn) -> int:
    """Build one local impression per person from their highest-signal memories."""
    now = db.localnow()
    people_rows = conn.execute("SELECT id, display_name FROM people").fetchall()
    written = 0
    for p in people_rows:
        try:
            rows = conn.execute(
                """SELECT m.id, m.text, m.importance, a.felt, a.confidence
                   FROM memories m
                   JOIN appraisals a ON a.id = (
                     SELECT id FROM appraisals WHERE memory_id=m.id ORDER BY id DESC LIMIT 1
                   )
                   WHERE m.person_id=? AND m.sensitive=0 AND m.status='active'
                   ORDER BY m.importance DESC, a.confidence DESC, m.ts DESC
                   LIMIT 3""",
                (p["id"],),
            ).fetchall()
            if not rows:
                continue
            bits = []
            evidence = []
            confs = []
            imps = []
            for r in rows:
                evidence.append(r["id"])
                confs.append(float(r["confidence"] or 0))
                imps.append(float(r["importance"] or 0))
                felt = str(r["felt"] or "").strip()
                text = str(r["text"] or "").replace("\n", " ").strip()
                bits.append((felt or text)[:120])
            text = f"关于{p['display_name'] or p['id']}：" + "；".join(bits)
            conn.execute("DELETE FROM person_impressions WHERE person_id=?", (p["id"],))
            conn.execute(
                """INSERT INTO person_impressions
                   (person_id, scope, text, evidence_ids_json, confidence, importance, created_at, updated_at)
                   VALUES (?, 'qq', ?, ?, ?, ?, ?, ?)""",
                (p["id"], text[:800], json.dumps(evidence, ensure_ascii=False),
                 sum(confs) / max(1, len(confs)), max(max(imps), max(confs), 0.1), now, now),
            )
            written += 1
        except Exception as e:
            log(f"impression failed person={p['id']}: {e}")
    conn.commit()
    return written


def _daily_due(conn, *, hour: int) -> bool:
    now = datetime.now().astimezone()
    if now.hour < hour:
        return False
    day = now.date().isoformat()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM sleep_runs WHERE day_key=? AND reason IN ('daily','sleep')",
            (day,),
        ).fetchone()[0]
    except Exception:
        n = 0
    return int(n or 0) == 0


def daily_cycle(db_path: str, *, hour: int, force: bool = False) -> bool:
    """Local daily consolidation. No farewell, no session rotation, no cloud API."""
    conn = db.connect(db_path)
    try:
        db.init_db(conn)
        if not force and not _daily_due(conn, hour=hour):
            return False
        log("daily start")
        baseline = daybook.ensure_day_baseline(conn)
        appraised = appraise.appraise_pending(conn, limit=500, code_only=True)
        people.refresh(conn)
        impressions = refresh_impressions(conn)
        ep = episodes.build_day(conn, day=baseline.get("day_key"))
        threads = thread_model.assign_threads(conn)
        loops = thread_loops.sync_thread_loops(conn)
        reviewed = episode_review.review_open(conn, limit=max(1, int(os.environ.get("EMOTIONCORE_REVIEW_LIMIT") or 10)))
        episodes.write_cards(conn, day=baseline.get("day_key"))
        lifecycle = close_episodes(conn)
        cons = consolidate.run(conn, mode="day_end")
        dr = dream.run(conn)
        summary = daybook.finalize_day(conn, day=dr["day_key"], ambient=cons.get("ambient"))
        patience.write(conn)
        purpose_seed.write(conn)
        handoff.write(conn)
        db.record_sleep(conn, day_key=dr["day_key"], reason="daily", rotated=False, farewell_sent=False,
                        details={"local_worker": True, "dream_id": dr.get("dream_id")})
        log(f"daily done day={dr.get('day_key')} appraised={appraised.get('tried')} episodes={ep.get('episodes')} impressions={impressions} threads={threads} loops={loops} reviewed={reviewed} lifecycle={lifecycle} summary={bool(summary)}")
        return True
    except Exception as e:
        log(f"daily failed: {e}")
        return False
    finally:
        conn.close()


def cycle(db_path: str, *, appraise_limit: int = 5, review_limit: int = 2) -> None:
    conn = db.connect(db_path)
    try:
        db.init_db(conn)
        try:
            stats = appraise.appraise_pending(conn, limit=max(1, min(20, appraise_limit)), timeout=180)
            log(f"appraise {stats}")
        except Exception as e:
            log(f"appraise failed: {e}")
        try:
            bs = body_state.snapshot(write=True)
            log(f"body refresh ok stress={bs.get('states', {}).get('stress')}")
        except Exception as e:
            log(f"body refresh failed: {e}")
        try:
            built = episodes.build_day(conn)
            threads = thread_model.assign_threads(conn)
            loops = thread_loops.sync_thread_loops(conn)
            log(f"episodes built={built.get('episodes', '?')} day={built.get('day', '?')} threads={threads} loops={loops}")
        except Exception as e:
            log(f"episodes failed: {e}")
        try:
            rev = episode_review.review_open(conn, limit=review_limit)
            log(f"episode_review {rev}")
        except Exception as e:
            log(f"episode_review failed: {e}")
        for name, fn in (
            ("episodes.write_cards", lambda: episodes.write_cards(conn)),
            ("people.refresh", lambda: people.refresh(conn)),
            ("daybook.ensure_day_baseline", lambda: daybook.ensure_day_baseline(conn)),
            ("patience.write", lambda: patience.write(conn)),
        ):
            try:
                fn()
                log(f"{name} ok")
            except Exception as e:
                log(f"{name} failed: {e}")
    finally:
        conn.close()


WORKER_LOCK = ROOT / "data" / "emotioncore-worker.pid"


def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _acquire_worker_lock() -> bool:
    WORKER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        if WORKER_LOCK.exists():
            old = int(WORKER_LOCK.read_text(encoding="utf-8").strip() or "0")
            if old and old != os.getpid() and _pid_alive(old):
                return False
    except Exception:
        pass
    WORKER_LOCK.write_text(str(os.getpid()), encoding="utf-8")
    def release():
        try:
            if WORKER_LOCK.read_text(encoding="utf-8").strip() == str(os.getpid()):
                WORKER_LOCK.unlink(missing_ok=True)
        except Exception:
            pass
    atexit.register(release)
    return True


def main(argv: list[str] | None = None) -> int:
    if not _acquire_worker_lock():
        print("worker already running; exiting", flush=True)
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("EMOTIONCORE_DB") or os.environ.get("SOULCORE_DB") or str(ROOT / "data" / "soulcore.db"))
    ap.add_argument("--interval", type=int, default=int(os.environ.get("EMOTIONCORE_WORKER_INTERVAL") or 300))
    ap.add_argument("--appraise-limit", type=int, default=int(os.environ.get("EMOTIONCORE_APPRAISE_LIMIT") or 5))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daily-hour", type=int, default=int(os.environ.get("EMOTIONCORE_DAILY_HOUR") or 4))
    ap.add_argument("--daily-now", action="store_true")
    ap.add_argument("--review-limit", type=int, default=int(os.environ.get("EMOTIONCORE_REVIEW_LIMIT") or 2))
    args = ap.parse_args(argv)
    log(f"worker start db={args.db} interval={args.interval}s limit={args.appraise_limit}")
    while True:
        try:
            cycle(args.db, appraise_limit=args.appraise_limit, review_limit=args.review_limit)
        except Exception:
            log("cycle crashed:\n" + traceback.format_exc())
        sched = read_schedule(args.daily_hour)
        if args.daily_now or (sched["auto"] and _daily_due(db.connect(args.db), hour=sched["hour"])):
            daily_cycle(args.db, hour=sched["hour"], force=bool(args.daily_now))
        if args.once:
            return 0
        time.sleep(max(30, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
