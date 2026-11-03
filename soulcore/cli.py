"""SoulCore Phase 1 CLI.

Commands:
  init       create the SQLite database
  seed-demo  insert synthetic memories (no personal data)
  sync       read-only import of SurfCore's current memory card
  appraise   run pending memories through the local Ollama appraiser
  status     counts and latest affect (no memory text)
  affect     compute and optionally save the current affect snapshot
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import (affect, appraise, appraisal_learning, balance, body_state, consolidate, context_render, correction, daybook, db, desire, dream, handoff,
               episodes, inbox, local_assist, people, personality, purpose_seed, retrieval, session_rotation, skill_manifest, skills, sleep_farewell, social, surfcore_export)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def _db_path(args) -> Path:
    return Path(args.db).resolve() if args.db else db.DEFAULT_DB


def cmd_init(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    print(f"initialized: {_db_path(args)}")
    return 0


def cmd_seed(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    n = db.seed_demo(conn)
    print(f"seeded new demo memories: {n}")
    return 0


def cmd_sync(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = db.sync_surfcore(
        conn,
        surfcore_root=args.surfcore_root,
        limit=args.limit,
        include_sensitive=args.include_sensitive,
        full=args.full,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_sync_inbox(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = inbox.sync_inbox(
        conn,
        surfcore_root=args.surfcore_root,
        limit=args.limit,
        include_self=not args.no_self,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_appraise(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    stats = appraise.appraise_pending(
        conn,
        limit=args.limit,
        model=args.model,
        fallback=args.fallback,
        timeout=args.timeout,
        code_only=args.code_only,
    )
    stats["export"] = surfcore_export.export_surfcore(conn)
    context_render.write(conn)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if stats["failed"] == 0 else 1


def cmd_export_surfcore(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = surfcore_export.export_surfcore(conn, include_global=not args.no_global)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_status(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = db.status(conn)
    result["db"] = str(_db_path(args))
    result["model"] = args.model or db.MODEL
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_handoff(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = handoff.write(conn)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_memory_stats(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    def grouped(sql: str) -> dict[str, int]:
        return {str(r[0] or "unknown"): int(r[1]) for r in conn.execute(sql).fetchall()}
    latest = conn.execute(
        """SELECT id, day, start_at, end_at, conversation_key, importance, source_kind,
                  summary FROM episodes ORDER BY COALESCE(start_at, created_at) DESC LIMIT 1"""
    ).fetchone()
    path = _db_path(args)
    result = {
        "memories": conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
        "fts_rows": conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0],
        "episodes": conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0],
        "sleep_runs_today": conn.execute(
            "SELECT COUNT(*) FROM sleep_runs WHERE day_key=date('now','localtime')"
        ).fetchone()[0],
        "pending_appraisals": conn.execute(
            "SELECT COUNT(*) FROM memories WHERE appraisal_status != 'done'"
        ).fetchone()[0],
        "pending_questions": conn.execute(
            "SELECT COUNT(*) FROM appraisal_questions WHERE status='pending'"
        ).fetchone()[0],
        "by_scope": grouped("SELECT scope, COUNT(*) FROM memories GROUP BY scope"),
        "by_status": grouped("SELECT status, COUNT(*) FROM memories GROUP BY status"),
        "by_source_kind": grouped("SELECT source_kind, COUNT(*) FROM memories GROUP BY source_kind"),
        "episodes_by_scope": grouped("SELECT conversation_key, COUNT(*) FROM episodes GROUP BY conversation_key"),
        "latest_episode": dict(latest) if latest else None,
        "db_bytes": path.stat().st_size if path.exists() else 0,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_fts_rebuild(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    conn.execute("DELETE FROM memories_fts")
    conn.execute("INSERT INTO memories_fts(memory_id, text) SELECT id, text FROM memories")
    conn.commit()
    print(json.dumps({
        "ok": True,
        "memories": conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
        "fts_rows": conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_config(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = {
        "schema_version": db.get_meta(conn, "schema_version"),
        "initial_coefficients": db.get_meta(conn, "initial_coefficients"),
        "appraiser": db.get_meta(conn, "appraiser"),
        "effective_appraiser": {
            "provider": appraise.appraiser_config().get("provider"),
            "model": appraise.appraiser_config().get("model"),
            "base_url": appraise.appraiser_config().get("base_url"),
            "api_key_env": appraise.appraiser_config().get("api_key_env"),
        },
        "storage_policy": db.get_meta(conn, "storage_policy"),
        "db": str(_db_path(args)),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_affect(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = affect.compute_affect(conn, window=args.window)
    if args.save:
        affect.save_snapshot(conn, result)
        result["saved"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_consolidate(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = consolidate.run(conn, mode=args.mode, dry_run=args.dry_run)
    # Do not print per-memory details by default; keep the CLI privacy-safe.
    summary = {k: v for k, v in result.items() if k != "details"}
    summary["detail_count"] = len(result.get("details", []))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_trigger(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    n = db.mark_triggered(conn, args.ids, source=args.source, note=args.note or "")
    print(json.dumps({"triggered": n, "ids": args.ids}, ensure_ascii=False, indent=2))
    return 0


def cmd_context(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    rows = db.daily_context(conn, day=args.day, limit=args.limit)
    out = {
        "day": args.day or None,
        "count": len(rows),
        "ids": [r["id"] for r in rows],
        "people": people.today_people(conn, day=args.day, limit=8),
    }
    if args.show_text:
        out["items"] = [
            {"id": r["id"], "scope": r["scope"], "text": r["text"]}
            for r in rows
        ]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_people(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    if args.refresh:
        refreshed = people.refresh(conn, day=args.day)
    else:
        refreshed = None
    rows = conn.execute(
        """SELECT id, display_name, is_owner, message_count, familiarity,
                  trust, valence, unresolved, stance, action_hint,
                  profile_status, profile_version, last_seen
           FROM people ORDER BY message_count DESC, id LIMIT ?""",
        (max(1, int(args.limit)),),
    ).fetchall()
    out = {
        "count": len(rows),
        "refreshed": refreshed,
        "items": [dict(r) for r in rows],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_people_due(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    print(json.dumps({"items": people.profile_due(conn, limit=args.limit)},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_people_profile(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    try:
        result = people.generate_profile(conn, args.id, timeout=args.timeout)
    except Exception as exc:
        print(json.dumps({"error": str(exc)[:500], "id": args.id},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_person_context(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    out = people.context(conn, args.id, day=args.day)
    if out is None:
        print(json.dumps({"error": "person not found", "id": args.id}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_social(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    print(json.dumps(social.compute(conn, day=args.day), ensure_ascii=False, indent=2))
    return 0


def cmd_skills(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    skills.register_builtins(conn)
    print(json.dumps({"items": skills.list_skills(conn)}, ensure_ascii=False, indent=2))
    return 0


def cmd_skill_route(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    skills.register_builtins(conn)
    print(json.dumps(skills.route(conn, args.text) or {"skill_id": None},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_skill_run(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    skills.register_builtins(conn)
    try:
        payload = json.loads(args.args or "{}")
    except Exception as exc:
        print(json.dumps({"error": f"bad args json: {exc}"}, ensure_ascii=False, indent=2))
        return 1
    result = skills.run(conn, args.id, payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def cmd_skill_requests(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    rows = conn.execute(
        """SELECT id, skill_id, version, failures, last_error, status, created_at
           FROM skill_requests ORDER BY id DESC LIMIT ?""",
        (max(1, int(args.limit)),),
    ).fetchall()
    print(json.dumps({"items": [dict(r) for r in rows]}, ensure_ascii=False, indent=2))
    return 0


def cmd_render_context(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    out = args.out or str(context_render.DEFAULT_CONTEXT_FILE)
    path = context_render.write(conn, out, day=args.day)
    bili_path = None
    if not args.out:
        bili_path = context_render.write_bili(conn, day=args.day)
    if args.show:
        print(open(path, encoding="utf-8").read())
        if bili_path:
            print("\n--- B站 P-only ---\n")
            print(open(bili_path, encoding="utf-8").read())
    else:
        print(json.dumps({
            "path": path,
            "chars": len(open(path, encoding="utf-8").read()),
            "bili_path": bili_path,
        }, ensure_ascii=False, indent=2))
    return 0


def _resolve_person_id(conn, value: str) -> str | None:
    s = (value or "").strip()
    if not s:
        return None
    if s.startswith("qq:"):
        return s
    if s.isdigit():
        return f"qq:{s}"
    row = conn.execute(
        "SELECT id FROM people WHERE display_name=? OR aliases_json LIKE ? LIMIT 1",
        (s, f'%"{s}"%'),
    ).fetchone()
    return row["id"] if row else s


def cmd_day_summary(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = daybook.latest(conn, day=args.day)
    print(json.dumps(result or {"error": "no daily summary"}, ensure_ascii=False, indent=2))
    return 0


def cmd_day_baseline(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = daybook.ensure_day_baseline(conn, day=args.day)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_learn_appraisals(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    learned = appraisal_learning.learn(conn, similarity=args.similarity)
    try:
        if args.mode:
            appraisal_learning.set_mode(conn, args.mode)
        report = appraisal_learning.report(conn)
    except Exception as exc:
        print(json.dumps({"error": str(exc), "report": appraisal_learning.report(conn)},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"learned": learned, "report": report},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_appraisal_report(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    print(json.dumps(appraisal_learning.report(conn), ensure_ascii=False, indent=2))
    return 0


def cmd_appraisal_policy(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    try:
        report = appraisal_learning.set_mode(conn, args.mode)
    except Exception as exc:
        print(json.dumps({"error": str(exc), "report": appraisal_learning.report(conn)},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_question_list(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    items = correction.pending(conn, limit=args.limit)
    print(json.dumps({"count": len(items), "items": items}, ensure_ascii=False, indent=2))
    return 0


def cmd_question_resolve(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    try:
        score = json.loads(args.score_json) if args.score_json else None
    except Exception as exc:
        print(json.dumps({"error": f"bad score json: {exc}"}, ensure_ascii=False, indent=2))
        return 1
    try:
        result = correction.resolve(
            conn,
            question_id=args.id,
            answer=args.answer or "",
            score=score,
            summary=args.summary or "",
            felt=args.felt or "",
        )
        result["export"] = surfcore_export.export_surfcore(conn)
        context_render.write(conn)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_purpose_seed(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = purpose_seed.write(conn, out=args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_body_state(args) -> int:
    balance.refresh()
    result = body_state.snapshot(write=not args.no_write)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_balance(args) -> int:
    result = balance.refresh()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def cmd_rotate_sessions(args) -> int:
    result = session_rotation.rotate_all(reason=args.reason)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def cmd_rotate_over_budget(args) -> int:
    result = session_rotation.rotate_over_budget(
        max_cache_hit=args.max_cache_hit,
        max_day_tokens=args.max_day_tokens,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def cmd_desire(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = desire.compute(conn)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_skill_manifest(args) -> int:
    result = skill_manifest.write()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_episodes(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    print(json.dumps({
        "day": args.day,
        "episodes": episodes.list_day(conn, day=args.day, limit=args.limit),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_episode_build(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = episodes.build_day(conn, day=args.day)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_episode_cards(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    path = episodes.write_cards(conn, day=args.day)
    print(json.dumps({"ok": bool(path), "path": path or None}, ensure_ascii=False, indent=2))
    return 0


def cmd_episode_polish(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    day = args.day or datetime.now().astimezone().date().isoformat()
    result = local_assist.polish_day(conn, day=day)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_repair_identities(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = db.repair_identity_status(conn)
    print(json.dumps({"updated": result}, ensure_ascii=False, indent=2))
    return 0


def cmd_felt_backfill(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = appraise.backfill_felt(conn, limit=args.limit, model=args.model, timeout=args.timeout)
    exported = surfcore_export.export_surfcore(conn)
    print(json.dumps({"felt": result, "export": exported}, ensure_ascii=False, indent=2))
    return 0


def cmd_memory_log(args) -> int:
    path = db.ROOT / "data" / "memory-tool-calls.jsonl"
    lines = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                try:
                    lines.append(json.loads(line))
                except Exception:
                    pass
    print(json.dumps({"path": str(path), "count": len(lines), "items": lines[-max(1, int(args.limit)):]},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_memory(args) -> int:
    """Read-only memory query for the speaking layer."""
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    mode = args.mode
    limit = max(1, int(args.limit))
    scope = str(args.scope or "").strip() or None
    pid = _resolve_person_id(conn, args.person) if args.person else None
    out: dict[str, Any] = {
        "mode": mode,
        "person_id": pid,
        "scope": scope,
        "identity_notice": (
            "identity_status=legacy_unresolved/self 的旧记录不代表主人；"
            "未确认说话人的旧记忆不要归给 owner，也不要用想象补。"
        ),
    }
    if mode == "p":
        out["p"] = personality.compute_p(conn)
    elif mode == "overview":
        out["status"] = db.status(conn)
        p_result = personality.compute_p(conn)
        out["p"] = p_result["p"]
        out["p_memory_count"] = p_result["memory_count"]
        out["identity_counts"] = {
            r["identity_status"]: r["c"]
            for r in conn.execute(
                "SELECT identity_status, COUNT(*) c FROM memories GROUP BY identity_status"
            ).fetchall()
        }
        people_rows = conn.execute(
            """SELECT id, display_name, is_owner, message_count, familiarity,
                      trust, valence, unresolved, stance
               FROM people ORDER BY message_count DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        out["people"] = [dict(r) for r in people_rows]
        out["today_context_count"] = len(db.daily_context(conn, limit=limit))
    elif mode == "today":
        rows = db.daily_context(conn, limit=200)
        if pid:
            rows = [r for r in rows if r["person_id"] == pid]
        if scope:
            rows = [r for r in rows if r["scope"] == scope]
        total = len(rows)
        rows = rows[:limit]
        out["matched"] = total
        out["truncated"] = total > len(rows)
        out["items"] = [
            {"id": r["id"], "scope": r["scope"], "speaker": r["speaker"],
             "person_id": r["person_id"], "identity_status": r["identity_status"] or "unknown",
             "ts": r["ts"], "text": r["text"]}
            for r in rows
        ]
        if out["truncated"]:
            out["notice"] = "只返回了有限条；不要声称这是完整记忆。"
    elif mode == "search":
        query = str(args.query or "").strip()
        if not query:
            print(json.dumps({"error": "search requires --query"}, ensure_ascii=False, indent=2))
            return 1
        fetch_limit = limit if not (pid or scope) else max(20, limit * 4)
        hits = retrieval.search_memories(
            conn, query, limit=fetch_limit,
            scope=scope or None, person_id=pid or None,
        )
        if pid:
            hits = [h for h in hits if h.get("person_id") == pid]
        if scope:
            hits = [h for h in hits if h.get("scope") == scope]
        total = len(hits)
        hits = hits[:limit]
        out["matched"] = total
        out["truncated"] = total > len(hits)
        out["items"] = hits
        if out["truncated"]:
            out["notice"] = "只返回了有限条；不要声称这是完整记忆。"
    elif mode == "person":
        person = str(args.person or "").strip()
        if not person:
            print(json.dumps({"error": "person requires --person"}, ensure_ascii=False, indent=2))
            return 1
        ctx = people.context(conn, pid or person)
        out["person"] = ctx
        if ctx:
            rows = conn.execute(
                """SELECT id, ts, scope, identity_status, text FROM memories
                   WHERE person_id=? ORDER BY COALESCE(ts, created_at) DESC LIMIT ?""",
                (ctx["id"], limit),
            ).fetchall()
            out["recent"] = [dict(r) for r in rows]
    elif mode == "range":
        fro = str(args.from_ or "").strip()
        to = str(args.to or "").strip()
        if args.date:
            if fro or to:
                print(json.dumps({"error": "use --date OR --from/--to, not both"}, ensure_ascii=False, indent=2))
                return 1
            fro = str(args.date).strip()
            from datetime import timedelta
            to = (db._parse_when(fro) + timedelta(days=1)).isoformat()
        if not fro or not to:
            print(json.dumps({"error": "range requires --date or --from/--to"}, ensure_ascii=False, indent=2))
            return 1
        try:
            out.update(db.query_memories_range(
                conn, start=fro, end=to, limit=limit, person_id=pid, scope=scope
            ))
        except Exception as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        if out.get("truncated"):
            out["notice"] = "只返回了有限条；不要声称这是完整记忆。"
    elif mode == "questions":
        items = correction.pending(conn, limit=limit)
        out["count"] = len(items)
        out["items"] = items
    elif mode == "resolve":
        if not args.question_id:
            print(json.dumps({"error": "resolve requires --question-id"}, ensure_ascii=False, indent=2))
            return 1
        try:
            score = json.loads(args.score_json) if args.score_json else None
        except Exception as exc:
            print(json.dumps({"error": f"bad score json: {exc}"}, ensure_ascii=False, indent=2))
            return 1
        try:
            result = correction.resolve(
                conn,
                question_id=args.question_id,
                answer=args.answer or "",
                score=score,
                summary=args.summary or "",
                felt=args.felt or "",
            )
            result["export"] = surfcore_export.export_surfcore(conn)
            context_render.write(conn)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        out.update(result)
    else:
        print(json.dumps({"error": f"unknown mode: {mode}"}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_recall(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = retrieval.retrieve(
        conn,
        args.text,
        limit=args.limit,
        min_similarity=args.min_similarity,
        mark=not args.no_mark,
        include_text=args.show_text,
        source=args.source,
    )
    print(json.dumps({"query": args.text, "count": len(result), "items": result},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_shadow(args) -> int:
    """Shadow snapshot for the llm/stream bridge: no mutation by default."""
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    hits = retrieval.retrieve(
        conn,
        args.text,
        limit=args.limit,
        min_similarity=args.min_similarity,
        mark=args.mark,
        include_text=False,
        source="shadow_bridge",
    )
    context = db.daily_context(conn, limit=args.context_limit)
    p = personality.compute_p(conn)
    person_ids = []
    for hit in hits:
        pid = hit.get("person_id")
        if pid and pid not in person_ids:
            person_ids.append(pid)
    person_cards = [people.context(conn, pid) for pid in person_ids]
    person_cards = [c for c in person_cards if c]
    out = {
        "text_chars": len(args.text or ""),
        "retrieval": hits,
        "daily_context_ids": [r["id"] for r in context],
        "daily_context_count": len(context),
        "person_cards": person_cards,
        "social": social.compute(conn),
        "p": p["p"],
        "p_memory_count": p["memory_count"],
        "marked": bool(args.mark),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_dream(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = dream.run(
        conn,
        day=args.day,
        budget=args.budget,
        seed=args.seed,
        write_diary=args.diary,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_p(args) -> int:
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    result = personality.compute_p(conn)
    if args.save:
        personality.save_p(conn, result)
        result["saved"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_sleep(args) -> int:
    """Manual sleep: numeric consolidation + dream sample + export packet.

    Deliberately does NOT generate diary/plan; that belongs to the high-level API.
    """
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    baseline = daybook.ensure_day_baseline(conn, day=args.day)
    ep = episodes.build_day(conn, day=args.day)
    episode_cards = episodes.write_cards(conn, day=args.day)
    cons = consolidate.run(conn, mode=args.mode)
    dr = dream.run(conn, day=args.day, budget=args.budget, seed=args.seed)
    person_refresh = people.refresh(conn, day=dr["day_key"])
    person_cards = people.today_people(conn, day=dr["day_key"])
    summary = daybook.finalize_day(conn, day=dr["day_key"], ambient=cons.get("ambient"))
    surfcore_exported = surfcore_export.export_surfcore(conn)
    seed = purpose_seed.write(conn)
    farewell = sleep_farewell.maybe_send("sleep")
    rotated = session_rotation.rotate_all(reason="sleep")
    sleep_count = db.record_sleep(
        conn, day_key=dr["day_key"], reason="sleep",
        rotated=bool(rotated.get("ok")), farewell_sent=bool(farewell.get("sent")),
        details={"dream_id": dr["dream_id"], "rotation": rotated},
    )
    brief = handoff.write(conn)
    packet = {
        "day_key": dr["day_key"],
        "daily_baseline": baseline,
        "daily_summary": summary,
        "p": dr["p"],
        "p_memory_count": dr["p_memory_count"],
        "ambient": cons.get("ambient"),
        "today_important": dr["today_important"],
        "random_untriggered": dr["random_untriggered"],
        "sampled": dr["sampled"],
        "dream_id": dr["dream_id"],
        "people_refresh": person_refresh,
        "person_cards": person_cards,
        "surfcore_export": surfcore_exported,
        "purpose_seed": seed,
        "sleep_farewell": farewell,
        "session_rotation": rotated,
        "sleep_count": sleep_count,
        "handoff": brief.get("path"),
        "generated_at": db.utcnow(),
    }
    out_dir = db.ROOT / "sleep"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{dr['day_key']}.json"
    out_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    context_path = context_render.write(conn, day=dr["day_key"])
    bili_context_path = context_render.write_bili(conn, day=dr["day_key"])
    packet["path"] = str(out_path)
    packet["context_path"] = context_path
    packet["bili_context_path"] = bili_context_path
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0


def cmd_daily(args) -> int:
    """Local daily pipeline: inbox -> appraisal -> people -> consolidate -> dream.

    Does not write diary, does not call cloud, does not touch SurfCore.
    """
    conn = db.connect(_db_path(args))
    db.init_db(conn)
    baseline = daybook.ensure_day_baseline(conn)
    repaired = db.repair_identity_status(conn)
    synced = inbox.sync_inbox(
        conn,
        surfcore_root=args.surfcore_root,
        limit=args.sync_limit,
        include_self=not args.no_self,
    )
    appraised = None
    if not args.skip_appraise:
        appraised = appraise.appraise_pending(
            conn,
            limit=args.appraise_limit,
            model=args.model,
            fallback=args.fallback,
            timeout=args.timeout,
        )
    refreshed = people.refresh(conn)
    ep = episodes.build_day(conn, day=baseline.get("day_key"))
    episode_cards = episodes.write_cards(conn, day=baseline.get("day_key"))
    cons = consolidate.run(conn, mode="day_end")
    dr = dream.run(conn, budget=args.budget, seed=args.seed)
    summary = daybook.finalize_day(conn, day=dr["day_key"], ambient=cons.get("ambient"))
    exported = surfcore_export.export_surfcore(conn)
    seed = purpose_seed.write(conn)
    farewell = sleep_farewell.maybe_send("daily")
    rotated = session_rotation.rotate_all(reason="daily")
    sleep_count = db.record_sleep(
        conn, day_key=dr["day_key"], reason="daily",
        rotated=bool(rotated.get("ok")), farewell_sent=bool(farewell.get("sent")),
        details={"rotation": rotated},
    )
    brief = handoff.write(conn)
    out = {
        "day_key": dr["day_key"],
        "identity_repaired": repaired,
        "daily_baseline": baseline,
        "episodes": ep,
        "episode_cards": episode_cards,
        "daily_summary": summary,
        "inbox": synced,
        "appraised": appraised,
        "people": refreshed,
        "surfcore_export": exported,
        "purpose_seed": seed,
        "sleep_farewell": farewell,
        "session_rotation": rotated,
        "sleep_count": sleep_count,
        "handoff": brief.get("path"),
        "ambient": cons.get("ambient"),
        "dream": {
            "today_important": dr["today_important"],
            "random_untriggered": dr["random_untriggered"],
            "sampled": dr["sampled"],
            "p": dr["p"],
            "p_memory_count": dr["p_memory_count"],
        },
        "social": social.compute(conn),
    }
    out["context_path"] = context_render.write(conn, day=dr["day_key"])
    out["bili_context_path"] = context_render.write_bili(conn, day=dr["day_key"])
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="soulcore", description="SoulCore Phase 1 local memory/appraisal")
    p.add_argument("--db", default=None, help="SQLite path (default: soulproject/data/soulcore.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create/migrate the database")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("seed-demo", help="insert synthetic demo memories")
    s.set_defaults(func=cmd_seed)

    s = sub.add_parser("sync", help="read-only import from SurfCore")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--surfcore-root", default=None)
    s.add_argument("--include-sensitive", action="store_true")
    s.add_argument("--full", action="store_true", help="also merge memory-card-full.jsonl (unlimited archive)")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("sync-inbox", help="read-only import of memory-inbox.jsonl / full card with senderId")
    s.add_argument("--limit", type=int, default=500)
    s.add_argument("--surfcore-root", default=None)
    s.add_argument("--no-self", action="store_true")
    s.set_defaults(func=cmd_sync_inbox)

    s = sub.add_parser("appraise", help="appraise pending memories with the configured backend")
    s.add_argument("--limit", type=int, default=3)
    s.add_argument("--model", default=None)
    s.add_argument("--timeout", type=int, default=300)
    s.add_argument("--fallback", action="store_true", help="use low-confidence heuristic on failure")
    s.add_argument("--code-only", action="store_true", help="skip AI escalation during bulk backfill")
    s.set_defaults(func=cmd_appraise)

    s = sub.add_parser("status", help="show counts and latest affect")
    s.add_argument("--model", default=db.MODEL)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("memory-stats", help="local memory/episode/FTS counts as JSON")
    s.set_defaults(func=cmd_memory_stats)

    s = sub.add_parser("handoff", help="write deterministic sleep handoff brief")
    s.set_defaults(func=cmd_handoff)

    s = sub.add_parser("fts-rebuild", help="rebuild the local FTS5 memory index")
    s.set_defaults(func=cmd_fts_rebuild)

    s = sub.add_parser("config", help="show schema, initial coefficients, appraiser config")
    s.set_defaults(func=cmd_config)

    s = sub.add_parser("affect", help="compute current affect over recent appraisals")
    s.add_argument("--window", type=int, default=20)
    s.add_argument("--save", action="store_true")
    s.set_defaults(func=cmd_affect)

    s = sub.add_parser("consolidate", help="day-end / shutdown consolidation")
    s.add_argument("--mode", choices=["day_end", "shutdown"], default="day_end")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_consolidate)

    s = sub.add_parser("trigger", help="mark memories as activated today")
    s.add_argument("ids", nargs="+")
    s.add_argument("--source", default="manual")
    s.add_argument("--note", default="")
    s.set_defaults(func=cmd_trigger)

    s = sub.add_parser("context", help="show today's triggered memories")
    s.add_argument("--day", default=None)
    s.add_argument("--limit", type=int, default=12)
    s.add_argument("--show-text", action="store_true")
    s.set_defaults(func=cmd_context)

    s = sub.add_parser("people", help="list people and optionally refresh daily relationship state")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--day", default=None)
    s.add_argument("--refresh", action="store_true")
    s.set_defaults(func=cmd_people)

    s = sub.add_parser("person-context", help="relationship card for one person")
    s.add_argument("--id", required=True)
    s.add_argument("--day", default=None)
    s.set_defaults(func=cmd_person_context)

    s = sub.add_parser("people-due", help="people with >=10 messages but no profile")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_people_due)

    s = sub.add_parser("people-profile", help="generate a draft person profile with local model")
    s.add_argument("--id", required=True)
    s.add_argument("--timeout", type=int, default=180)
    s.set_defaults(func=cmd_people_profile)

    s = sub.add_parser("social", help="read-only social relationship shadow")
    s.add_argument("--day", default=None)
    s.set_defaults(func=cmd_social)

    s = sub.add_parser("skills", help="list local deterministic skills")
    s.set_defaults(func=cmd_skills)

    s = sub.add_parser("skill-route", help="rule-first skill routing")
    s.add_argument("--text", required=True)
    s.set_defaults(func=cmd_skill_route)

    s = sub.add_parser("skill-run", help="run a registered local skill")
    s.add_argument("--id", required=True)
    s.add_argument("--args", default="{}")
    s.set_defaults(func=cmd_skill_run)

    s = sub.add_parser("skill-requests", help="pending skill improvement requests")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_skill_requests)

    s = sub.add_parser("render-context", help="render compact P/person context for a future prompt seam")
    s.add_argument("--out", default=None)
    s.add_argument("--day", default=None)
    s.add_argument("--show", action="store_true")
    s.set_defaults(func=cmd_render_context)

    s = sub.add_parser("repair-identities", help="backfill legacy identity_status without guessing owner")
    s.set_defaults(func=cmd_repair_identities)

    s = sub.add_parser("day-summary", help="show day-start baseline and cleaned cumulative delta")
    s.add_argument("--day", default=None)
    s.set_defaults(func=cmd_day_summary)

    s = sub.add_parser("day-baseline", help="capture today's P before new appraisals")
    s.add_argument("--day", default=None)
    s.set_defaults(func=cmd_day_baseline)

    s = sub.add_parser("learn-appraisals", help="induce patterns from model appraisals")
    s.add_argument("--mode", choices=["shadow", "auto", "off"], default=None)
    s.add_argument("--similarity", type=float, default=0.4)
    s.set_defaults(func=cmd_learn_appraisals)

    s = sub.add_parser("appraisal-report", help="show learning coverage and shadow accuracy")
    s.set_defaults(func=cmd_appraisal_report)

    s = sub.add_parser("appraisal-policy", help="set appraisal routing policy")
    s.add_argument("--mode", choices=["shadow", "auto", "off"], required=True)
    s.set_defaults(func=cmd_appraisal_policy)

    s = sub.add_parser("question-list", help="list pending appraisal questions")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_question_list)

    s = sub.add_parser("question-resolve", help="resolve a question with surface score")
    s.add_argument("--id", required=True)
    s.add_argument("--answer", default="")
    s.add_argument("--summary", default="")
    s.add_argument("--felt", default="")
    s.add_argument("--score-json", default="")
    s.set_defaults(func=cmd_question_resolve)

    s = sub.add_parser("purpose-seed", help="export SoulCore affect seed for SurfCore purpose")
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_purpose_seed)

    s = sub.add_parser("body-state", help="sample ephemeral device/balance state for surface dialogue")
    s.add_argument("--no-write", action="store_true")
    s.set_defaults(func=cmd_body_state)

    s = sub.add_parser("balance", help="probe DeepSeek balance and write data/balance.json")
    s.set_defaults(func=cmd_balance)

    s = sub.add_parser("rotate-sessions", help="archive SurfCore conversations after sleep cleanup")
    s.add_argument("--reason", default="manual")
    s.set_defaults(func=cmd_rotate_sessions)

    s = sub.add_parser("rotate-over-budget", help="rotate sessions above token budget")
    s.add_argument("--max-cache-hit", type=int, default=120000)
    s.add_argument("--max-day-tokens", type=int, default=0)
    s.set_defaults(func=cmd_rotate_over_budget)

    s = sub.add_parser("desire", help="show ephemeral surface desire from today's deviation")
    s.set_defaults(func=cmd_desire)

    s = sub.add_parser("skill-manifest", help="write the fixed per-session skill manifest")
    s.set_defaults(func=cmd_skill_manifest)

    s = sub.add_parser("episodes", help="list episode index cards")
    s.add_argument("--day", default=None)
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_episodes)

    s = sub.add_parser("episode-build", help="build episode cards for a day")
    s.add_argument("--day", default=None)
    s.set_defaults(func=cmd_episode_build)

    s = sub.add_parser("episode-cards", help="write L2 episode cards for prompt injection")
    s.add_argument("--day", default=None)
    s.set_defaults(func=cmd_episode_cards)

    s = sub.add_parser("episode-polish", help="optional local-2B polish of episode summaries")
    s.add_argument("--day", default=None)
    s.set_defaults(func=cmd_episode_polish)

    s = sub.add_parser("felt-backfill", help="generate first-person felt notes for existing appraisals")
    s.add_argument("--limit", type=int, default=30)
    s.add_argument("--model", default=None)
    s.add_argument("--timeout", type=int, default=300)
    s.set_defaults(func=cmd_felt_backfill)

    s = sub.add_parser("memory-log", help="show soulcore_memory tool call log")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_memory_log)

    s = sub.add_parser("export-surfcore", help="write SurfCore-compatible SoulCore sidecar")
    s.add_argument("--no-global", action="store_true")
    s.set_defaults(func=cmd_export_surfcore)

    s = sub.add_parser("memory", help="read-only memory query for the speaking layer")
    s.add_argument("--mode", choices=["overview", "today", "search", "person", "range", "questions", "resolve", "p"], default="overview")
    s.add_argument("--query", default=None)
    s.add_argument("--person", default=None)
    s.add_argument("--scope", default=None, help="group / private / pet / skill")
    s.add_argument("--date", default=None, help="range mode: YYYY-MM-DD (local day)")
    s.add_argument("--question-id", default=None)
    s.add_argument("--answer", default=None)
    s.add_argument("--summary", default=None)
    s.add_argument("--felt", default=None)
    s.add_argument("--score-json", default=None)
    s.add_argument("--from", dest="from_", default=None, help="range mode start ISO/date")
    s.add_argument("--to", default=None, help="range mode end ISO/date (exclusive)")
    s.add_argument("--limit", type=int, default=8)
    s.set_defaults(func=cmd_memory)

    s = sub.add_parser("recall", help="pre-send/idle retrieval and familiarity update")
    s.add_argument("--text", required=True)
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--min-similarity", type=float, default=0.12)
    s.add_argument("--source", default="pre_send")
    s.add_argument("--no-mark", action="store_true")
    s.add_argument("--show-text", action="store_true")
    s.set_defaults(func=cmd_recall)

    s = sub.add_parser("shadow", help="llm/stream shadow snapshot")
    s.add_argument("--text", required=True)
    s.add_argument("--limit", type=int, default=6)
    s.add_argument("--min-similarity", type=float, default=0.12)
    s.add_argument("--context-limit", type=int, default=12)
    s.add_argument("--mark", action="store_true")
    s.set_defaults(func=cmd_shadow)

    s = sub.add_parser("dream", help="sleep/dream sampling and P shadow")
    s.add_argument("--day", default=None)
    s.add_argument("--budget", type=int, default=12)
    s.add_argument("--seed", type=int, default=None)
    s.add_argument("--diary", action="store_true", help="also generate local diary + next-day plan")
    s.set_defaults(func=cmd_dream)

    s = sub.add_parser("p", help="compute P shadow (not injected)")
    s.add_argument("--save", action="store_true")
    s.set_defaults(func=cmd_p)

    s = sub.add_parser("sleep", help="manual day-end: consolidate + dream + packet")
    s.add_argument("--day", default=None)
    s.add_argument("--budget", type=int, default=12)
    s.add_argument("--seed", type=int, default=None)
    s.add_argument("--mode", choices=["day_end", "shutdown"], default="day_end")
    s.set_defaults(func=cmd_sleep)

    s = sub.add_parser("daily", help="local daily pipeline: inbox/appraise/people/consolidate/dream")
    s.add_argument("--sync-limit", type=int, default=500)
    s.add_argument("--appraise-limit", type=int, default=30)
    s.add_argument("--budget", type=int, default=12)
    s.add_argument("--seed", type=int, default=None)
    s.add_argument("--model", default=None)
    s.add_argument("--timeout", type=int, default=300)
    s.add_argument("--fallback", action="store_true")
    s.add_argument("--no-self", action="store_true")
    s.add_argument("--skip-appraise", action="store_true")
    s.add_argument("--surfcore-root", default=None)
    s.set_defaults(func=cmd_daily)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
