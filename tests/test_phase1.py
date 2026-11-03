from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from soulcore import affect, appraise, appraisal_learning, body_state, consolidate, correction, daybook, db, desire, dream, episodes, handoff, inbox, local_assist, people, personality, purpose_seed, retrieval, skill_manifest, skills, social, surfcore_export


DIMS = {
    "security": 0.5,
    "trust": 0.6,
    "self_efficacy": 0.4,
    "caution": 0.7,
    "sociability": 0.3,
    "openness": 0.2,
    "valence": -0.2,
    "arousal": 0.5,
}


class Phase1Tests(unittest.TestCase):
    def test_seed_and_affect(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            n = db.seed_demo(conn)
            self.assertEqual(n, 8)
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"], 8)
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM appraisal_jobs").fetchone()["c"], 8)
            a = affect.compute_affect(conn, window=20)
            self.assertEqual(a["memory_count"], 0)
            self.assertIn("stress", a)
            conn.close()

    def test_sync_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "surfcore"
            char = root / "characters" / "char-test"
            (char / "memory").mkdir(parents=True)
            (root / "characters" / "current.json").write_text(
                json.dumps({"id": "char-test", "name": "test", "dir": str(char)}),
                encoding="utf-8",
            )
            card = {
                "records": [
                    {"id": "m1", "text": "主人夸我做得不错", "scope": "pet",
                     "createdAt": "2026-10-29T00:00:00Z", "importance": 30,
                     "sensitive": False},
                    {"id": "m2", "text": "一条敏感记录", "scope": "pet",
                     "createdAt": "2026-10-29T00:01:00Z", "importance": 10,
                     "sensitive": True},
                ]
            }
            (char / "memory" / "memory-card.json").write_text(
                json.dumps(card, ensure_ascii=False), encoding="utf-8"
            )
            (char / "memory" / "memory-card-full.jsonl").write_text(
                json.dumps({"id": "m3", "text": "全量档案里的一条记录", "scope": "pet",
                            "createdAt": "2026-10-29T00:02:00Z", "importance": 20},
                           ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            result = db.sync_surfcore(conn, surfcore_root=root, limit=10, full=True)
            self.assertEqual(result["from_full"], 1)
            self.assertEqual(result["imported_new"], 2)
            self.assertEqual(result["skipped_sensitive"], 1)
            count = conn.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"]
            self.assertEqual(count, 2)
            conn.close()

    def test_validate_result(self):
        obj = {
            "dimensions": DIMS,
            "unresolved": 0.4,
            "confidence": 0.7,
            "evidence": "a short quote",
            "has_impact": False,
        }
        out = appraise.validate_result(obj)
        self.assertEqual(out["dimensions"]["valence"], -0.2)
        bad = dict(obj)
        bad["dimensions"] = dict(DIMS, valence=2.0)
        with self.assertRaises(appraise.AppraisalError):
            appraise.validate_result(bad)

    def test_save_appraisal_updates_job(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.upsert_memory(conn, source="demo", source_record_id="x",
                             text="测试记忆", scope="pet")
            mid = "demo:x"
            db.save_appraisal(
                conn, mid, DIMS, 0.4, 0.7, "evidence", False, 100, "{}",
            )
            self.assertEqual(
                conn.execute("SELECT appraisal_status FROM memories WHERE id=?", (mid,)).fetchone()[0],
                "done",
            )
            self.assertEqual(
                conn.execute("SELECT status FROM appraisal_jobs WHERE memory_id=?", (mid,)).fetchone()[0],
                "done",
            )
            conn.close()

    def test_ambient_flag_for_high_unimportant_impact(self):
        high = dict(DIMS, security=0.0, caution=1.0, valence=0.5, arousal=0.6)
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            for i in range(3):
                mid = f"demo:amb{i}"
                db.upsert_memory(conn, source="demo", source_record_id=f"amb{i}",
                                 text=f"一条不重要但影响很大的事件 {i}", scope="pet")
                conn.execute("UPDATE memories SET self_relevance=0.9 WHERE id=?", (mid,))
                conn.commit()
                db.save_appraisal(conn, mid, high, 0.4, 0.9, "ambient evidence", False, 10, "{}")
            result = consolidate.run(conn, mode="day_end")
            self.assertEqual(result["ambient"]["count"], 3)
            self.assertTrue(result["ambient"]["flagged"])
            self.assertGreaterEqual(result["ambient"]["mean"], 0.40)
            conn.close()

    def test_trigger_and_daily_context(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.seed_demo(conn)
            n = db.mark_triggered(conn, ["demo:demo:01", "demo:demo:02"], source="test")
            self.assertEqual(n, 2)
            rows = db.daily_context(conn)
            self.assertEqual(len(rows), 2)
            self.assertEqual({r["id"] for r in rows}, {"demo:demo:01", "demo:demo:02"})
            self.assertEqual(len(db.daily_context(conn, day="1999-01-01")), 0)
            conn.close()

    def test_dream_samples_and_saves_p(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            for i in range(3):
                mid = f"demo:d{i}"
                db.upsert_memory(conn, source="demo", source_record_id=f"d{i}",
                                 text=f"今天的重要事件 {i}", scope="pet")
                db.save_appraisal(conn, mid, DIMS, 0.3, 0.8, "e", True, 10, "{}")
            db.upsert_memory(conn, source="demo", source_record_id="old",
                             text="很久以前的重要事件", scope="pet",
                             ts="2020-01-01T00:00:00+08:00")
            db.save_appraisal(conn, "demo:old", DIMS, 0.3, 0.8, "e", True, 10, "{}")
            consolidate.run(conn, mode="day_end")
            result = dream.run(conn, budget=4, seed=1)
            self.assertGreaterEqual(result["sampled"], 3)
            self.assertGreater(result["p_memory_count"], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) c FROM p_snapshots").fetchone()["c"], 1
            )
            p = personality.compute_p(conn)
            self.assertIn("security", p["p"])
            conn.close()

    def test_retrieval_updates_familiarity_and_context(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.seed_demo(conn)
            result = retrieval.retrieve(conn, "主人夸我记事清楚", limit=3)
            self.assertTrue(result)
            hit = next(r for r in result if r["hit"])
            self.assertEqual(hit["id"], "demo:demo:01")
            self.assertGreater(hit["familiarity_after"], hit["familiarity_before"])
            row = conn.execute(
                "SELECT current_familiarity, last_triggered_at FROM memories WHERE id=?",
                (hit["id"],),
            ).fetchone()
            self.assertGreater(row["current_familiarity"], 0)
            self.assertIsNotNone(row["last_triggered_at"])
            self.assertGreaterEqual(len(db.daily_context(conn)), 1)
            conn.close()

    def test_inbox_people_daily_refresh(self):
        today = db.localnow()[:10]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "surfcore"
            char = root / "characters" / "char-test"
            (char / "memory").mkdir(parents=True)
            (root / "characters" / "current.json").write_text(
                json.dumps({"id": "char-test", "name": "test", "dir": str(char)}),
                encoding="utf-8",
            )
            events = [
                {"at": f"{today}T10:00:00+08:00", "platform": "qq", "kind": "group",
                 "sender": "小鱼", "senderId": "10001", "groupId": "90001",
                 "isOwner": False, "isSelf": False, "conversationKey": "group:90001",
                 "private": False, "direct": True, "text": "今天一起整理记忆吧"},
                {"at": f"{today}T10:01:00+08:00", "platform": "qq", "kind": "group",
                 "sender": "角色", "senderId": "20002", "groupId": "90001",
                 "isOwner": False, "isSelf": True, "conversationKey": "group:90001",
                 "private": False, "direct": False, "text": "好，我来记"},
            ]
            (char / "memory" / "memory-inbox.jsonl").write_text(
                "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
                encoding="utf-8",
            )
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            result = inbox.sync_inbox(conn, surfcore_root=root, limit=100)
            self.assertEqual(result["new"], 2)
            self.assertEqual(result["people"], 1)
            person = conn.execute("SELECT * FROM people WHERE id='qq:10001'").fetchone()
            self.assertEqual(person["display_name"], "小鱼")
            memory = conn.execute(
                "SELECT * FROM memories WHERE person_id='qq:10001'"
            ).fetchone()
            self.assertEqual(memory["speaker_id"], "10001")
            db.save_appraisal(conn, memory["id"], DIMS, 0.2, 0.8, "e", False, 10, "{}")
            refreshed = people.refresh(conn, day=today)
            self.assertEqual(refreshed["updated"], 1)
            ctx = people.context(conn, "qq:10001", day=today)
            self.assertIsNotNone(ctx)
            self.assertGreater(ctx["trust"], 0.5)
            self.assertIsNotNone(ctx["today"])
            conn.close()

    def test_person_stance_and_action(self):
        build, build_action = people.derive_stance(
            trust=0.7, valence=0.3, familiarity=0.8, unresolved=0.2
        )
        self.assertEqual(build, "build")
        self.assertTrue(build_action.startswith("#行动："))
        cautious, cautious_action = people.derive_stance(
            trust=0.3, valence=-0.2, familiarity=0.3, unresolved=0.7
        )
        self.assertEqual(cautious, "cautious")
        self.assertIn("不主动透露", cautious_action)
        casual, _ = people.derive_stance(
            trust=0.5, valence=0.0, familiarity=0.3, unresolved=0.3
        )
        self.assertEqual(casual, "casual")

    def test_skill_registry_and_failure_request(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            self.assertEqual(skills.register_builtins(conn), 4)
            ok = skills.run(conn, "memory.people_refresh", {})
            self.assertTrue(ok["ok"])
            self.assertTrue(ok["outcome_memory"].startswith("skill:"))
            for _ in range(3):
                bad = skills.run(conn, "memory.recall", {})
                self.assertFalse(bad["ok"])
            self.assertIsNotNone(bad["request_id"])
            requests = conn.execute("SELECT COUNT(*) c FROM skill_requests").fetchone()["c"]
            self.assertEqual(requests, 1)
            conn.close()

    def test_qq_identity_is_sender_id_not_nickname(self):
        today = db.localnow()[:10]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "surfcore"
            char = root / "characters" / "char-test"
            (char / "memory").mkdir(parents=True)
            (root / "characters" / "current.json").write_text(
                json.dumps({"id": "char-test", "name": "test", "dir": str(char)}),
                encoding="utf-8",
            )
            events = [
                {"at": f"{today}T11:00:00+08:00", "platform": "qq", "kind": "group",
                 "sender": "同名", "senderId": "10001", "groupId": "g1",
                 "isOwner": False, "isSelf": False, "conversationKey": "group:g1",
                 "private": False, "direct": True, "text": "完全一样的话"},
                {"at": f"{today}T11:01:00+08:00", "platform": "qq", "kind": "group",
                 "sender": "同名", "senderId": "10002", "groupId": "g1",
                 "isOwner": False, "isSelf": False, "conversationKey": "group:g1",
                 "private": False, "direct": True, "text": "完全一样的话"},
                {"at": f"{today}T11:02:00+08:00", "platform": "qq", "kind": "group",
                 "sender": "改名后", "senderId": "10001", "groupId": "g2",
                 "isOwner": False, "isSelf": False, "conversationKey": "group:g2",
                 "private": False, "direct": True, "text": "换了昵称还是我"},
            ]
            (char / "memory" / "memory-inbox.jsonl").write_text(
                "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
                encoding="utf-8",
            )
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            result = inbox.sync_inbox(conn, surfcore_root=root, limit=100)
            self.assertEqual(result["new"], 3)
            self.assertEqual(result["people"], 2)
            rows = conn.execute(
                "SELECT person_id, COUNT(*) c FROM memories GROUP BY person_id ORDER BY person_id"
            ).fetchall()
            by_person = {r["person_id"]: r["c"] for r in rows}
            self.assertEqual(by_person.get("qq:10001"), 2)
            self.assertEqual(by_person.get("qq:10002"), 1)
            ctx = people.context(conn, "qq:10001", day=today)
            self.assertEqual(ctx["display_name"], "改名后")
            self.assertIn("同名", ctx["aliases"])
            self.assertIn("改名后", ctx["aliases"])
            conn.close()

    def test_memory_range_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.upsert_memory(conn, source="demo", source_record_id="r1",
                             text="早上的一条", scope="pet", ts="2026-10-29T09:00:00+08:00")
            db.upsert_memory(conn, source="demo", source_record_id="r2",
                             text="晚上的另一条", scope="pet", ts="2026-10-29T20:00:00+08:00")
            res = db.query_memories_range(
                conn,
                start="2026-10-29T00:00:00+08:00",
                end="2026-10-30T00:00:00+08:00",
                limit=1,
            )
            self.assertEqual(res["matched"], 2)
            self.assertEqual(res["returned"], 1)
            self.assertTrue(res["truncated"])
            exact = db.query_memories_range(
                conn,
                start="2026-10-29T08:00:00+08:00",
                end="2026-10-29T10:00:00+08:00",
            )
            self.assertEqual(exact["matched"], 1)
            self.assertEqual(exact["items"][0]["text"], "早上的一条")
            conn.close()

    def test_surfcore_sidecar_merge_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "surfcore"
            char = root / "characters" / "char1"
            (char / "memory").mkdir(parents=True)
            (root / "characters" / "current.json").write_text(
                json.dumps({"id": "char1", "dir": str(char)}), encoding="utf-8"
            )
            full_record = {
                "id": "mem_test_1",
                "createdAt": "2026-10-29T10:00:00Z",
                "platform": "qq",
                "scope": "qq",
                "kind": "event",
                "title": "群友：AI 记忆",
                "text": "AI 记忆测试",
                "speaker": "群友",
                "tags": ["qq"],
                "isSelf": False,
            }
            (char / "memory" / "memory-card-full.jsonl").write_text(
                json.dumps(full_record, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.upsert_memory(
                conn, source="surfcore-inbox", source_record_id="evt1",
                text="AI 记忆测试", ts="2026-10-29T10:00:00Z",
                scope="group", speaker="群友", person_id=None,
                identity_status="resolved",
            )
            result = surfcore_export.export_surfcore(conn, surfcore_root=root)
            self.assertEqual(result["enrichment"], 1)
            sidecar = char / "memory" / "memory-card-full.soulcore.jsonl"
            lines = [json.loads(x) for x in sidecar.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertEqual(lines[0]["schema"], "soulcore.enrichment.v1")
            self.assertEqual(lines[0]["record_id"], "mem_test_1")
            self.assertEqual(lines[0]["soulcore"]["schema"], "soulcore.enrichment.v1")
            self.assertTrue(any(x.get("schema") == "soulcore.extension.v1" for x in lines))
            conn.close()

    def test_routine_memory_is_scored_by_code_without_model(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.upsert_memory(conn, source="demo", source_record_id="routine",
                             text="收到，哈哈哈", scope="pet")
            stats = appraise.appraise_pending(conn, limit=1)
            self.assertEqual(stats["code"], 1)
            self.assertEqual(stats["ok"], 0)
            row = conn.execute("SELECT appraiser_id FROM appraisals").fetchone()
            self.assertEqual(row["appraiser_id"], "code-v1")
            conn.close()

    def test_body_state_is_ephemeral_hint(self):
        states = {
            "stress": 0.2, "arousal": 0.2, "fatigue": 0.2,
            "cognitive_load": 0.2, "sleepiness": 0.2,
            "resource_need": 0.8, "thermal_load": 0.0, "recovery": 0.2,
        }
        hint = body_state._surface_hint(states, {"balance": 3.2})
        self.assertIn("资源余额偏低", hint)
        self.assertIn("不要把它写进记忆、P", hint)
        self.assertGreater(body_state._night_factor(__import__("datetime").datetime(2026, 10, 30, 23, 30)), 0.5)

    def test_local_assist_disabled_is_noop(self):
        self.assertIsNone(local_assist.summarize("测试", timeout=0.1))

    def test_fts_search_memories(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.upsert_memory(conn, source="surfcore", source_record_id="f1",
                             text="主人说今天想聊记忆分层和上下文预算",
                             ts="2026-10-31T10:00:00+08:00",
                             speaker="主人", scope="private")
            db.upsert_memory(conn, source="surfcore", source_record_id="f2",
                             text="今天吃了番茄炒蛋",
                             ts="2026-10-31T10:01:00+08:00",
                             speaker="主人", scope="private")
            hits = retrieval.search_memories(conn, "记忆分层", limit=3)
            self.assertTrue(hits)
            self.assertIn("记忆", hits[0]["text"])
            self.assertNotIn("番茄", hits[0]["text"])
            conn.close()

    def test_episode_build_keeps_raw_ids(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            day = "2026-10-31"
            db.upsert_memory(conn, source="surfcore", source_record_id="e1",
                             text="今天有点累", ts=f"{day}T10:00:00+08:00",
                             scope="pet", speaker="主人", conversation_key="private:1")
            db.upsert_memory(conn, source="surfcore", source_record_id="e2",
                             text="那先休息一下", ts=f"{day}T10:05:00+08:00",
                             scope="pet", speaker="她", conversation_key="private:1")
            dims = {"security": 0.6, "trust": 0.6, "self_efficacy": 0.5, "caution": 0.4,
                    "sociability": 0.4, "openness": 0.4, "valence": -0.5, "arousal": 0.6}
            db.save_appraisal(conn, "surfcore:e1", dimensions=dims, unresolved=0.6,
                              confidence=0.8, evidence="累", has_impact=True,
                              latency_ms=1, raw_response="", felt="有点累")
            db.save_appraisal(conn, "surfcore:e2", dimensions=dims, unresolved=0.6,
                              confidence=0.8, evidence="休息", has_impact=True,
                              latency_ms=1, raw_response="", felt="被安慰")
            result = episodes.build_day(conn, day=day)
            self.assertEqual(result["episodes"], 1)
            rows = episodes.list_day(conn, day=day)
            self.assertEqual(len(rows), 1)
            self.assertEqual(set(rows[0]["raw_ids"]), {"surfcore:e1", "surfcore:e2"})
            self.assertIn("休息", rows[0]["key_quote"])
            cards = episodes.render_cards(conn, day=day)
            self.assertIn("事件索引", cards)
            self.assertIn("关键", cards)
            self.assertGreater(float(rows[0]["importance"]), 0.0)
            conn.close()

    def test_body_pressure_damps_purpose_without_touching_p(self):
        drives = {"share": 0.8, "connect": 0.8, "consume": 0.8, "learn": 0.8}
        body = {"states": {"fatigue": 0.8, "sleepiness": 0.7, "cognitive_load": 0.7,
                           "stress": 0.7, "thermal_load": 0.0, "resource_need": 0.8, "recovery": 0.0}}
        out, pending = purpose_seed._apply_body(drives, 0.5, body)
        self.assertLess(out["share"], drives["share"])
        self.assertLess(out["connect"], drives["connect"])
        self.assertLess(out["consume"], drives["consume"])
        self.assertLess(out["learn"], drives["learn"])
        self.assertLess(pending, 0.5)

    def test_skill_manifest_filters_disabled_capabilities(self):
        data = skill_manifest.build()
        self.assertTrue(data["capabilities"]["qq"])
        self.assertFalse(data["capabilities"]["bili"])
        self.assertIn("QQ 对话", data["text"])
        self.assertNotIn("B站生物钟", data["text"])
        self.assertNotIn("桌宠对话", data["text"])
        self.assertLessEqual(len(data["text"]), 1500)

    def test_desire_surfaces_from_negative_deviation(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.upsert_memory(conn, source="demo", source_record_id="desire",
                             text="你刚才那句话让我有点难过，也没说清楚", scope="pet")
            daybook.ensure_day_baseline(conn)
            dims = dict(DIMS)
            dims.update({"valence": -0.8, "arousal": 0.8, "caution": 0.8})
            db.save_appraisal(conn, "demo:desire", dims, 0.7, 0.9, "负向且未解决",
                              True, 1, "{}", thought="我其实有点着急，想把话说清楚")
            result = desire.compute(conn)
            self.assertGreater(result["used"], 0)
            self.assertTrue(result["desires"])
            self.assertIn("surface_hint", result)
            row = conn.execute("SELECT thought FROM appraisals").fetchone()
            self.assertIn("着急", row["thought"])
            conn.close()

    def test_purpose_seed_uses_day_baseline_and_writes_json(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.upsert_memory(conn, source="demo", source_record_id="seed",
                             text="今天和主人聊得很开心", scope="pet")
            db.save_appraisal(conn, "demo:seed", DIMS, 0.2, 0.8, "开心", True, 1, "{}")
            daybook.ensure_day_baseline(conn)
            data = purpose_seed.build(conn)
            self.assertEqual(data["p_source"], "day_baseline")
            self.assertIn("connect", data["drives"])
            self.assertIn("share", data["drives"])
            self.assertIn(data["emotion"], {"lonely", "worried", "proud", "affectionate", "bored", "content"})
            out = Path(td) / "seed.json"
            written = purpose_seed.write(conn, out=out)
            self.assertTrue(out.exists())
            self.assertEqual(written["path"], str(out))
            conn.close()

    def test_surface_correction_supersedes_old_memory(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.upsert_memory(conn, source="demo", source_record_id="old",
                             text="我对你有点失望", scope="pet")
            db.save_appraisal(conn, "demo:old", DIMS, 0.4, 0.7, "旧评价", True, 1, "{}")
            qid = correction.enqueue(conn, memory_id="demo:old", package={
                "text": "我对你有点失望", "error": "parse", "code": {"dimensions": DIMS},
            })
            result = correction.resolve(
                conn, question_id=qid, answer="我只是当时有点累",
                score={**DIMS, "valence": 0.1}, summary="不是失望，是疲惫",
            )
            self.assertEqual(result["new_memory_id"], f"surface-correction:{qid}")
            self.assertEqual(correction.superseded_by(conn, "demo:old"), result["new_memory_id"])
            old = conn.execute("SELECT affect_weight, consolidation_state FROM memories WHERE id='demo:old'").fetchone()
            self.assertEqual(old["affect_weight"], 0)
            self.assertEqual(old["consolidation_state"], "superseded")
            q = conn.execute("SELECT status FROM appraisal_questions WHERE id=?", (qid,)).fetchone()
            self.assertEqual(q["status"], "resolved")
            conn.close()

    def test_appraisal_failure_keeps_code_score_and_asks_owner(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.upsert_memory(conn, source="demo", source_record_id="hard",
                             text="我对你有点失望，也不想再猜了", scope="pet",
                             importance=1.0)
            with patch.object(appraise, "appraise_text", side_effect=RuntimeError("cannot parse")), \
                 patch.object(appraise.feedback, "ask_owner", return_value={"ok": True}) as asked:
                stats = appraise.appraise_pending(conn, limit=1)
            self.assertEqual(stats["failed"], 1)
            self.assertEqual(stats["asked"], 1)
            self.assertEqual(stats["code"], 1)
            self.assertTrue(asked.called)
            row = conn.execute("SELECT appraiser_id, felt FROM appraisals").fetchone()
            self.assertEqual(row["appraiser_id"], "code-v1")
            self.assertTrue(row["felt"])
            conn.close()

    def test_appraisal_learning_extracts_and_predicts(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            texts = [
                "主人夸我记事清楚，我很开心",
                "主人夸我记得清楚，我有点高兴",
            ]
            for i, text in enumerate(texts):
                mid = f"demo:learn{i}"
                db.upsert_memory(conn, source="demo", source_record_id=f"learn{i}",
                                 text=text, scope="pet")
                db.save_appraisal(conn, mid, DIMS, 0.2, 0.8, "夸我", False, 1, "{}",
                                  feature=appraisal_learning.extract(text))
            appraisal_learning.ensure_policy(conn)
            learned = appraisal_learning.learn(conn)
            self.assertGreaterEqual(learned["patterns"], 1)
            pred = appraisal_learning.predict(conn, "主人夸我记事清楚")
            self.assertIsNotNone(pred)
            self.assertIn("trust", pred["dimensions"])
            conn.close()

    def test_daybook_baseline_delta_after_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.upsert_memory(conn, source="demo", source_record_id="b1",
                             text="日初的一件小事", scope="pet")
            db.save_appraisal(conn, "demo:b1", DIMS, 0.1, 0.7, "b1", False, 10, "{}")
            baseline = daybook.ensure_day_baseline(conn, day="2026-10-29")
            self.assertIn("baseline_json", baseline)
            db.upsert_memory(conn, source="demo", source_record_id="b2",
                             text="后来发生的重要冲突", scope="pet")
            db.save_appraisal(conn, "demo:b2", {**DIMS, "valence": 0.9}, 0.8, 0.9, "b2", True, 10, "{}")
            summary = daybook.finalize_day(conn, day="2026-10-29")
            delta = json.loads(summary["delta_json"])
            self.assertNotEqual(delta["valence"], 0.0)
            self.assertEqual(summary["day_key"], "2026-10-29")
            conn.close()

    def test_consolidation_keeps_only_important(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.upsert_memory(conn, source="demo", source_record_id="low",
                             text="普通的一天", scope="pet")
            db.upsert_memory(conn, source="demo", source_record_id="high",
                             text="一次重要的冲突", scope="pet")
            db.save_appraisal(conn, "demo:low", DIMS, 0.1, 0.7, "low", False, 10, "{}")
            db.save_appraisal(conn, "demo:high", DIMS, 0.9, 0.9, "high", True, 10, "{}")
            result = consolidate.run(conn, mode="day_end")
            self.assertEqual(result["kept"], 1)
            self.assertEqual(result["ignored"], 1)
            self.assertEqual(result["ambient"]["count"], 1)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) c FROM ambient_pressures").fetchone()["c"],
                1,
            )
            a = affect.compute_affect(conn)
            self.assertEqual(a["memory_count"], 1)
            conn.close()


    def test_sleep_handoff_uses_local_facts(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.connect(Path(td) / "test.db")
            db.init_db(conn)
            db.upsert_memory(conn, source="surfcore", source_record_id="h1",
                             text="睡前说到一半的事", ts="2026-10-31T10:00:00+08:00",
                             speaker="主人", scope="private",
                             conversation_key="private:1")
            day = db.localnow()[:10]
            db.record_sleep(conn, day_key=day, reason="sleep", rotated=True)
            brief = handoff.build(conn)
            self.assertEqual(brief["sleep"]["count_today"], 1)
            self.assertIn("【交接｜刚睡醒】", brief["text"])
            self.assertIn("第 1 次睡眠", brief["text"])
            self.assertIn("上次停在", brief["text"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
