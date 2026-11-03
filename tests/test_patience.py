"""耐心模型的单元测试（M6）。纯函数，不依赖真实库。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from soulcore import patience


class PatienceTests(unittest.TestCase):
    def test_floor_and_ceiling(self):
        low = patience.compute({"pending_load": 1, "sleep_debt": 1, "negative_affect": 1})
        self.assertEqual(low["patience"], 0.15)  # 下限保护：不会被压成冷淡
        high = patience.compute({
            "positive_affect": 1, "resonance": 1, "rest_done": 1,
            "pending_load": 0, "sleep_debt": 0, "negative_affect": 0,
        })
        self.assertEqual(high["patience"], 1.0)

    def test_more_load_lower_patience(self):
        a = patience.compute({"pending_load": 0.2})
        b = patience.compute({"pending_load": 0.8})
        self.assertGreater(a["patience"], b["patience"])

    def test_relief_offsets_load(self):
        base = patience.compute({"pending_load": 0.6})
        lifted = patience.compute({"pending_load": 0.6, "positive_affect": 0.9, "resonance": 0.5})
        self.assertGreater(lifted["patience"], base["patience"])

    def test_pending_load_counts_deadline_more(self):
        now = 1_800_000_000_000
        plain = [{"status": "waiting", "importance": 0.5}]
        due = [{"status": "paused", "importance": 0.5, "anchor_at": now - 1000}]
        self.assertGreater(
            patience.pending_load(due, now),
            patience.pending_load(plain, now),
        )

    def test_done_loops_do_not_count(self):
        now = 1_800_000_000_000
        loops = [
            {"status": "done", "importance": 1.0},
            {"status": "archived", "importance": 1.0},
        ]
        self.assertEqual(patience.pending_load(loops, now), 0.0)

    def test_load_loops_replays_events(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "loops.jsonl"
            f.write_text(
                json.dumps({"op": "upsert", "loop": {"id": "a", "status": "waiting", "importance": 0.5}}) + "\n"
                + json.dumps({"op": "event", "id": "a", "type": "close"}) + "\n",
                encoding="utf-8",
            )
            loops = patience._load_loops(f)
            self.assertEqual(loops[0]["status"], "done")

    def test_bad_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "loops.jsonl"
            f.write_text("{坏行\n" + json.dumps({"op": "upsert", "loop": {"id": "b"}}) + "\n", encoding="utf-8")
            self.assertEqual(len(patience._load_loops(f)), 1)


if __name__ == "__main__":
    unittest.main()
