"""SQLite storage for SoulCore Phase 1.

Phase 1 scope:
  - local memory records
  - appraisal results (text-only, local Ollama)
  - affect snapshots
  - appraisal jobs

No personality vector P and no SurfCore writes in this phase.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import config

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "soulcore.db"
DEFAULT_SURFCORE_ROOT = Path.home() / ".dsh" / "surfcore"
MODEL = "huihui_ai/qwen3-vl-abliterated:2b-instruct-q4_K_M"
APPRAISER_ID = "ollama:" + MODEL
APPRAISER_VERSION = "phase1-v1"
PROMPT_VERSION = "appraisal-v1"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def localnow() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


# These are not "bad memories": raw rows stay. They are excluded from the
# default event/search surface so self-analysis or an old prompt cannot be
# mistaken for an event.
_LEGACY_PROMPT_MARKERS = (
    "你不是独立于本机的另一个人",
    "也不证明你拥有独立记忆或独立存在",
    "表层 API 是这套系统的表达器官",
)
_REFLECTION_MARKERS = (
    "常驻提示词",
    "唤醒卡",
    "记忆卡",
    "交接单",
    "翻不出来",
    "没命中",
    "记忆里搜了",
    "上下文预算",
    "不证明你拥有",
)


def memory_status(text: str, identity_status: str | None) -> str:
    """Classify a memory for retrieval/event hygiene; never delete raw text."""
    body = str(text or "")
    if any(marker in body for marker in _LEGACY_PROMPT_MARKERS):
        return "legacy_prompt"
    if (identity_status or "") == "self" and any(marker in body for marker in _REFLECTION_MARKERS):
        return "reflection"
    return "active"



def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else DEFAULT_DB
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_record_id TEXT,
  source_hash TEXT,
  ts TEXT,
  text TEXT NOT NULL,
  scope TEXT DEFAULT 'pet',
  sensitive INTEGER DEFAULT 0,
  importance REAL DEFAULT 0,
  strength REAL DEFAULT 1.0,
  confidence REAL DEFAULT 0.5,
  self_relevance REAL DEFAULT 0.5,
  unresolved REAL DEFAULT 0.0,
  encoding_familiarity REAL DEFAULT 0.0,
  current_familiarity REAL DEFAULT 0.0,
  processing_fluency REAL DEFAULT 0.0,
  appraisal_status TEXT DEFAULT 'pending',
  affect_weight REAL DEFAULT 1.0,
  consolidation_state TEXT DEFAULT 'none',
  consolidated_at TEXT,
  last_triggered_at TEXT,
  trigger_count INTEGER DEFAULT 0,
  speaker_id TEXT,
  person_id TEXT,
  identity_confidence REAL DEFAULT 0.0,
  group_id TEXT,
  conversation_key TEXT,
  speaker TEXT,
  identity_status TEXT DEFAULT 'unknown',
  raw_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(source, source_record_id)
);

CREATE TABLE IF NOT EXISTS appraisals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id TEXT NOT NULL,
  appraiser_id TEXT NOT NULL,
  appraiser_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  context_json TEXT,
  dimensions_json TEXT NOT NULL,
  feature_json TEXT,
  unresolved REAL NOT NULL,
  confidence REAL NOT NULL,
  evidence TEXT,
  thought TEXT,
  has_impact INTEGER NOT NULL,
  felt TEXT,
  baseline_json TEXT,
  delta_json TEXT,
  adjusted_json TEXT,
  latency_ms INTEGER,
  raw_response TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_appraisals_memory ON appraisals(memory_id);
CREATE INDEX IF NOT EXISTS idx_appraisals_created ON appraisals(created_at);

CREATE TABLE IF NOT EXISTS episodes (
  id TEXT PRIMARY KEY,
  day TEXT NOT NULL,
  start_at TEXT,
  end_at TEXT,
  conversation_key TEXT,
  participants_json TEXT,
  trigger TEXT,
  summary TEXT NOT NULL,
  key_quote TEXT,
  felt TEXT,
  delta_json TEXT,
  unresolved REAL DEFAULT 0.0,
  importance REAL DEFAULT 0.0,
  raw_ids_json TEXT,
  topics_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episodes_day ON episodes(day);

CREATE TABLE IF NOT EXISTS appraisal_patterns (
  id TEXT PRIMARY KEY,
  centroid_json TEXT NOT NULL,
  mean_json TEXT NOT NULL,
  variance_json TEXT,
  count INTEGER NOT NULL DEFAULT 0,
  impact_rate REAL DEFAULT 0.0,
  confidence REAL DEFAULT 0.0,
  sample_ids_json TEXT,
  tokens_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appraisal_shadow (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id TEXT NOT NULL,
  pattern_id TEXT,
  similarity REAL,
  prediction_json TEXT,
  model_json TEXT,
  agreement INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appraisal_policy (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  mode TEXT NOT NULL DEFAULT 'shadow',
  min_similarity REAL NOT NULL DEFAULT 0.55,
  min_support INTEGER NOT NULL DEFAULT 2,
  max_variance REAL NOT NULL DEFAULT 0.08,
  shadow_checked INTEGER NOT NULL DEFAULT 0,
  shadow_match INTEGER NOT NULL DEFAULT 0,
  model_calls INTEGER NOT NULL DEFAULT 0,
  pattern_calls INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appraisal_questions (
  id TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL,
  package_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  answer TEXT,
  surface_json TEXT,
  correction_id TEXT,
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_appraisal_questions_status
  ON appraisal_questions(status);

CREATE TABLE IF NOT EXISTS affect_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  valence REAL NOT NULL,
  arousal REAL NOT NULL,
  stress REAL NOT NULL,
  unresolved REAL NOT NULL,
  memory_count INTEGER NOT NULL,
  appraiser_id TEXT NOT NULL,
  details_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appraisal_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON appraisal_jobs(status);

CREATE TABLE IF NOT EXISTS consolidation_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mode TEXT NOT NULL,
  day_key TEXT,
  kept INTEGER NOT NULL,
  ignored INTEGER NOT NULL,
  skipped INTEGER NOT NULL,
  ambient_mean REAL,
  ambient_sum REAL,
  ambient_count INTEGER,
  ambient_baseline REAL,
  ambient_z REAL,
  ambient_flagged INTEGER DEFAULT 0,
  ambient_reason TEXT,
  details_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ambient_pressures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day_key TEXT,
  mean_impact REAL NOT NULL,
  sum_impact REAL NOT NULL,
  count INTEGER NOT NULL,
  baseline_mean REAL,
  zscore REAL,
  flagged INTEGER NOT NULL DEFAULT 0,
  reason TEXT,
  details_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_activations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  source TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_activations_memory ON memory_activations(memory_id);

CREATE TABLE IF NOT EXISTS dream_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day_key TEXT NOT NULL,
  budget INTEGER NOT NULL,
  sampled INTEGER NOT NULL,
  p_json TEXT,
  diary_text TEXT,
  plan_json TEXT,
  diary_status TEXT,
  details_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dream_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dream_id INTEGER NOT NULL,
  memory_id TEXT NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(dream_id) REFERENCES dream_runs(id) ON DELETE CASCADE,
  FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS p_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  p_json TEXT NOT NULL,
  memory_count INTEGER NOT NULL,
  weight_sum REAL NOT NULL,
  initial_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_summaries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day_key TEXT NOT NULL UNIQUE,
  baseline_json TEXT NOT NULL,
  baseline_memory_count INTEGER,
  baseline_weight_sum REAL,
  baseline_at TEXT,
  end_json TEXT,
  delta_json TEXT,
  end_at TEXT,
  kept INTEGER DEFAULT 0,
  ignored INTEGER DEFAULT 0,
  ambient_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_daily_summaries_day ON daily_summaries(day_key);

CREATE TABLE IF NOT EXISTS sleep_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day_key TEXT NOT NULL,
  reason TEXT,
  at TEXT NOT NULL,
  rotated INTEGER DEFAULT 0,
  farewell_sent INTEGER DEFAULT 0,
  details_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sleep_runs_day ON sleep_runs(day_key);

CREATE TABLE IF NOT EXISTS people (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL DEFAULT 'qq',
  user_id TEXT NOT NULL,
  display_name TEXT,
  aliases_json TEXT,
  is_owner INTEGER DEFAULT 0,
  first_seen TEXT,
  last_seen TEXT,
  message_count INTEGER DEFAULT 0,
  familiarity REAL DEFAULT 0.0,
  trust REAL DEFAULT 0.5,
  valence REAL DEFAULT 0.0,
  unresolved REAL DEFAULT 0.0,
  last_refreshed_at TEXT,
  stance TEXT DEFAULT 'casual',
  action_hint TEXT,
  profile_status TEXT DEFAULT 'none',
  profile_version INTEGER DEFAULT 0,
  profile_basis_count INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(platform, user_id)
);

CREATE TABLE IF NOT EXISTS person_daily (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id TEXT NOT NULL,
  day_key TEXT NOT NULL,
  message_count INTEGER NOT NULL DEFAULT 0,
  familiarity REAL NOT NULL DEFAULT 0.0,
  trust REAL NOT NULL DEFAULT 0.5,
  valence REAL NOT NULL DEFAULT 0.0,
  unresolved REAL NOT NULL DEFAULT 0.0,
  stance TEXT,
  action_hint TEXT,
  summary TEXT,
  evidence_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(person_id, day_key),
  FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS person_impressions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id TEXT NOT NULL,
  scope TEXT,
  text TEXT NOT NULL,
  evidence_ids_json TEXT,
  confidence REAL DEFAULT 0.0,
  importance REAL DEFAULT 0.0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS person_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id TEXT NOT NULL,
  memory_id TEXT,
  kind TEXT NOT NULL,
  valence REAL,
  trust REAL,
  note TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS person_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  personality TEXT,
  speaking_style TEXT,
  hobbies_json TEXT,
  summary TEXT,
  evidence_json TEXT,
  confidence REAL DEFAULT 0.0,
  source TEXT,
  status TEXT DEFAULT 'draft',
  created_at TEXT NOT NULL,
  FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS skills (
  id TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  intent_examples_json TEXT,
  inputs_json TEXT,
  executor TEXT NOT NULL,
  success_json TEXT,
  status TEXT DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  skill_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  ok INTEGER NOT NULL,
  latency_ms INTEGER,
  input_json TEXT,
  result_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(skill_id) REFERENCES skills(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS skill_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  skill_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  failures INTEGER NOT NULL,
  last_error TEXT,
  evidence_json TEXT,
  status TEXT DEFAULT 'pending',
  created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
  memory_id UNINDEXED,
  text,
  tokenize = 'unicode61'
);

CREATE TRIGGER IF NOT EXISTS memories_fts_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(memory_id, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_au AFTER UPDATE OF text ON memories BEGIN
  DELETE FROM memories_fts WHERE memory_id = old.id;
  INSERT INTO memories_fts(memory_id, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_ad AFTER DELETE ON memories BEGIN
  DELETE FROM memories_fts WHERE memory_id = old.id;
END;
"""


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS thread_merge_reviews (
      pair_key TEXT PRIMARY KEY,
      left_id TEXT NOT NULL,
      right_id TEXT NOT NULL,
      decision INTEGER NOT NULL,
      confidence REAL NOT NULL DEFAULT 0,
      reason TEXT,
      reviewed_at TEXT NOT NULL
    )""")
    conn.executescript(SCHEMA)
    _ensure_column(conn, "memories", "affect_weight", "REAL DEFAULT 1.0")
    _ensure_column(conn, "memories", "consolidation_state", "TEXT DEFAULT 'none'")
    _ensure_column(conn, "memories", "consolidated_at", "TEXT")
    _ensure_column(conn, "memories", "last_triggered_at", "TEXT")
    _ensure_column(conn, "memories", "trigger_count", "INTEGER DEFAULT 0")
    _ensure_column(conn, "memories", "speaker_id", "TEXT")
    _ensure_column(conn, "memories", "person_id", "TEXT")
    _ensure_column(conn, "memories", "identity_confidence", "REAL DEFAULT 0.0")
    _ensure_column(conn, "memories", "group_id", "TEXT")
    _ensure_column(conn, "memories", "conversation_key", "TEXT")
    _ensure_column(conn, "memories", "speaker", "TEXT")
    _ensure_column(conn, "memories", "identity_status", "TEXT DEFAULT 'unknown'")
    # Minimal memory-science fields (Mnemosyne-inspired), additive only.
    _ensure_column(conn, "memories", "source_kind", "TEXT DEFAULT 'dialog'")
    _ensure_column(conn, "memories", "status", "TEXT DEFAULT 'active'")
    _ensure_column(conn, "memories", "version", "INTEGER DEFAULT 1")
    _ensure_column(conn, "memories", "valid_from", "TEXT")
    _ensure_column(conn, "memories", "valid_to", "TEXT")
    _ensure_column(conn, "memories", "last_confirmed_at", "TEXT")
    _ensure_column(conn, "episodes", "source_kind", "TEXT")
    _ensure_column(conn, "episodes", "status", "TEXT DEFAULT 'open'")
    _ensure_column(conn, "episodes", "closed_at", "TEXT")
    _ensure_column(conn, "episodes", "resolution_note", "TEXT")
    _ensure_column(conn, "episodes", "closure_confidence", "REAL")
    _ensure_column(conn, "episodes", "closure_source", "TEXT")
    _ensure_column(conn, "episodes", "reviewed_at", "TEXT")
    _ensure_column(conn, "episodes", "thread_id", "TEXT")
    _ensure_column(conn, "episodes", "continues_episode_id", "TEXT")
    _ensure_column(conn, "episodes", "last_seen_at", "TEXT")
    _ensure_column(conn, "memories", "thread_id", "TEXT")
    conn.execute(
        "UPDATE episodes SET source_kind='dialog' WHERE source_kind IS NULL OR source_kind=''"
    )
    conn.execute(
        """UPDATE memories SET source_kind =
             CASE
               WHEN source='surface-correction' THEN 'correction'
               WHEN identity_status='self' THEN 'agent_dialogue'
               ELSE 'dialog'
             END
           WHERE source_kind IS NULL OR source_kind=''"""
    )
    conn.execute(
        "UPDATE memories SET status='active' WHERE status IS NULL OR status=''"
    )
    # Backfill FTS rows for databases created before the FTS index existed.
    conn.execute(
        """INSERT INTO memories_fts(memory_id, text)
           SELECT id, text FROM memories
           WHERE id NOT IN (SELECT memory_id FROM memories_fts)"""
    )
    conn.commit()
    _ensure_column(conn, "people", "stance", "TEXT DEFAULT 'casual'")
    _ensure_column(conn, "people", "action_hint", "TEXT")
    _ensure_column(conn, "people", "profile_status", "TEXT DEFAULT 'none'")
    _ensure_column(conn, "people", "profile_version", "INTEGER DEFAULT 0")
    _ensure_column(conn, "people", "profile_basis_count", "INTEGER DEFAULT 0")
    _ensure_column(conn, "people", "tags_json", "TEXT DEFAULT '[]'")
    # Existing drafts predate profile_basis_count; seed it from current evidence.
    conn.execute(
        """UPDATE people SET profile_basis_count=message_count
           WHERE COALESCE(profile_basis_count,0)=0 AND profile_status='draft'"""
    )
    _ensure_column(conn, "person_daily", "stance", "TEXT")
    _ensure_column(conn, "person_daily", "action_hint", "TEXT")
    _ensure_column(conn, "appraisals", "context_json", "TEXT")
    _ensure_column(conn, "appraisals", "feature_json", "TEXT")
    _ensure_column(conn, "appraisals", "felt", "TEXT")
    _ensure_column(conn, "appraisals", "baseline_json", "TEXT")
    _ensure_column(conn, "appraisals", "thought", "TEXT")
    _ensure_column(conn, "appraisals", "delta_json", "TEXT")
    _ensure_column(conn, "appraisals", "adjusted_json", "TEXT")
    for column, decl in [
        ("day_key", "TEXT"),
        ("ambient_mean", "REAL"),
        ("ambient_sum", "REAL"),
        ("ambient_count", "INTEGER"),
        ("ambient_baseline", "REAL"),
        ("ambient_z", "REAL"),
        ("ambient_flagged", "INTEGER DEFAULT 0"),
        ("ambient_reason", "TEXT"),
    ]:
        _ensure_column(conn, "consolidation_runs", column, decl)
    for column, decl in [
        ("diary_text", "TEXT"),
        ("plan_json", "TEXT"),
        ("diary_status", "TEXT"),
    ]:
        _ensure_column(conn, "dream_runs", column, decl)
    now = utcnow()
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value, updated_at) VALUES('schema_version', ?, ?)",
        (str(config.SCHEMA_VERSION), now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value, updated_at) VALUES('initial_coefficients', ?, ?)",
        (json.dumps(config.INITIAL_COEFFICIENTS, ensure_ascii=False), now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value, updated_at) VALUES('appraiser', ?, ?)",
        (json.dumps(config.APPRAISER, ensure_ascii=False), now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value, updated_at) VALUES('storage_policy', ?, ?)",
        (json.dumps(config.STORAGE, ensure_ascii=False), now),
    )
    conn.commit()


def repair_identity_status(conn: sqlite3.Connection) -> dict[str, int]:
    """Backfill legacy identities. Never infer owner from a missing senderId."""
    counts: dict[str, int] = {}
    rows = conn.execute(
        "SELECT id, source, person_id, raw_json, identity_status FROM memories"
    ).fetchall()
    for row in rows:
        current = row["identity_status"] or "unknown"
        if current not in ("unknown", ""):
            continue
        raw: dict[str, Any] = {}
        try:
            raw = json.loads(row["raw_json"] or "{}")
        except Exception:
            pass
        source = row["source"]
        if source == "surfcore-inbox":
            status = "resolved" if row["person_id"] else ("self" if raw.get("isSelf") else "unresolved")
        elif source == "surfcore":
            status = "self" if raw.get("isSelf") else "legacy_unresolved"
        elif source == "demo":
            status = "synthetic"
        elif source == "skill":
            status = "system"
        else:
            status = "unknown"
        conn.execute(
            "UPDATE memories SET identity_status=?, updated_at=? WHERE id=?",
            (status, utcnow(), row["id"]),
        )
        counts[status] = counts.get(status, 0) + 1
    conn.commit()
    return counts


def get_meta(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return row["value"]


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    now = utcnow()
    payload = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    conn.execute(
        "INSERT INTO meta(key, value, updated_at) VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, payload, now),
    )
    conn.commit()


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    s = "".join(ch.lower() for ch in str(text) if not ch.isspace())
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def estimate_familiarity(conn: sqlite3.Connection, text: str, limit: int = 200) -> float:
    """Cheap, deterministic encoding familiarity against recent memories.

    This is a *prior*, not the final familiarity. It is updated after recall.
    """
    grams = _char_ngrams(text)
    if not grams:
        return 0.0
    rows = conn.execute(
        "SELECT text FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,)
    ).fetchall()
    sims = sorted((_jaccard(grams, _char_ngrams(r["text"])) for r in rows), reverse=True)
    if not sims:
        return 0.0
    top = sims[:3]
    return round(sum(top) / len(top), 4)


def upsert_memory(
    conn: sqlite3.Connection,
    *,
    source: str,
    source_record_id: str,
    text: str,
    ts: str | None = None,
    scope: str = "pet",
    sensitive: bool = False,
    importance: float = 0.0,
    speaker: str | None = None,
    speaker_id: str | None = None,
    person_id: str | None = None,
    identity_confidence: float = 0.0,
    identity_status: str | None = None,
    group_id: str | None = None,
    conversation_key: str | None = None,
    dedupe: bool = False,
    raw: dict[str, Any] | None = None,
) -> tuple[str, bool]:
    """Insert or update a memory. Returns (id, is_new)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty memory text")
    mid = f"{source}:{source_record_id}"
    now = utcnow()
    new_status = memory_status(text, identity_status)
    exists = conn.execute("SELECT id FROM memories WHERE id = ?", (mid,)).fetchone()
    fam = estimate_familiarity(conn, text)
    if exists:
        conn.execute(
            """UPDATE memories SET text=?, ts=?, scope=?, sensitive=?, importance=?,
               raw_json=?, source_hash=?, updated_at=?, encoding_familiarity=COALESCE(encoding_familiarity, ?),
               speaker=COALESCE(?, speaker),
               speaker_id=COALESCE(?, speaker_id),
               person_id=COALESCE(?, person_id),
               identity_confidence=COALESCE(?, identity_confidence),
               identity_status=COALESCE(?, identity_status),
               group_id=COALESCE(?, group_id),
               conversation_key=COALESCE(?, conversation_key),
               status=CASE WHEN status IN ('superseded','invalidated') THEN status ELSE ? END
               WHERE id=?""",
            (text[:4000], ts, scope, 1 if sensitive else 0, float(importance or 0),
             json.dumps(raw, ensure_ascii=False) if raw else None, text_hash(text), now,
             fam, speaker, speaker_id, person_id, identity_confidence, identity_status,
             group_id, conversation_key, new_status, mid),
        )
        conn.commit()
        return mid, False
    if dedupe:
        # The memory card has the same event without senderId. Merge identity
        # into the existing row instead of creating a duplicate.
        # IMPORTANT: senderId/person identity takes priority over display name.
        # Two different QQ users with the same nickname must never merge.
        dup = conn.execute(
            """SELECT id FROM memories
               WHERE source_hash=? AND id<>?
                 AND (
                   (speaker_id IS NOT NULL AND speaker_id = ?)
                   OR (speaker_id IS NULL AND ? IS NULL
                       AND COALESCE(speaker, '')=COALESCE(?, ''))
                 )
               LIMIT 1""",
            (text_hash(text), mid, speaker_id, speaker_id, speaker),
        ).fetchone()
        if dup:
            conn.execute(
                """UPDATE memories SET speaker_id=COALESCE(?, speaker_id),
                   person_id=COALESCE(?, person_id),
                   identity_confidence=MAX(COALESCE(identity_confidence,0), ?),
                   identity_status=COALESCE(?, identity_status),
                   group_id=COALESCE(?, group_id),
                   conversation_key=COALESCE(?, conversation_key),
                   updated_at=? WHERE id=?""",
                (speaker_id, person_id, float(identity_confidence or 0.0),
                 identity_status, group_id, conversation_key, now, dup["id"]),
            )
            conn.commit()
            return dup["id"], False
    conn.execute(
        """INSERT INTO memories
           (id, source, source_record_id, source_hash, ts, text, scope, sensitive,
            importance, strength, confidence, self_relevance, unresolved,
            encoding_familiarity, current_familiarity, processing_fluency,
            appraisal_status, status, speaker, speaker_id, person_id, identity_confidence,
            identity_status, group_id, conversation_key, raw_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, 0.5, 0.5, 0.0, ?, ?, ?,
                   'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (mid, source, source_record_id, text_hash(text), ts, text[:4000], scope,
         1 if sensitive else 0, float(importance or 0), fam, fam, fam,
         new_status, speaker, speaker_id, person_id, float(identity_confidence or 0.0),
         identity_status or "unknown", group_id, conversation_key,
         json.dumps(raw, ensure_ascii=False) if raw else None, now, now),
    )
    conn.execute(
        """INSERT OR IGNORE INTO appraisal_jobs (memory_id, status, attempts, created_at, updated_at)
           VALUES (?, 'pending', 0, ?, ?)""",
        (mid, now, now),
    )
    conn.commit()
    return mid, True


def pending_jobs(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT m.* FROM appraisal_jobs j
           JOIN memories m ON m.id = j.memory_id
           WHERE j.status = 'pending'
           ORDER BY j.created_at ASC LIMIT ?""",
        (max(1, int(limit)),),
    ).fetchall()


def save_appraisal(
    conn: sqlite3.Connection,
    memory_id: str,
    dimensions: dict[str, float],
    unresolved: float,
    confidence: float,
    evidence: str,
    has_impact: bool,
    latency_ms: int,
    raw_response: str,
    context: dict[str, Any] | None = None,
    appraiser_id: str = APPRAISER_ID,
    appraiser_version: str = APPRAISER_VERSION,
    prompt_version: str = PROMPT_VERSION,
    felt: str = "",
    thought: str = "",
    baseline: dict[str, float] | None = None,
    delta: dict[str, float] | None = None,
    adjusted: dict[str, float] | None = None,
    feature: dict[str, float] | None = None,
) -> None:
    now = utcnow()
    conn.execute(
        """INSERT INTO appraisals
           (memory_id, appraiser_id, appraiser_version, prompt_version, context_json,
            dimensions_json, feature_json, unresolved, confidence, evidence, thought, has_impact,
            felt, baseline_json, delta_json, adjusted_json,
            latency_ms, raw_response, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (memory_id, appraiser_id, appraiser_version, prompt_version,
         json.dumps(context or {}, ensure_ascii=False),
         json.dumps(dimensions, ensure_ascii=False),
         json.dumps(feature, ensure_ascii=False) if feature is not None else None,
         float(unresolved),
         float(confidence), evidence[:500], str(thought or "")[:300], 1 if has_impact else 0,
         str(felt or "")[:240],
         json.dumps(baseline, ensure_ascii=False) if baseline is not None else None,
         json.dumps(delta, ensure_ascii=False) if delta is not None else None,
         json.dumps(adjusted, ensure_ascii=False) if adjusted is not None else None,
         int(latency_ms), raw_response[:8000], now),
    )
    conn.execute(
        "UPDATE memories SET appraisal_status='done', updated_at=? WHERE id=?",
        (now, memory_id),
    )
    conn.execute(
        """UPDATE appraisal_jobs SET status='done', attempts=attempts+1,
           updated_at=?, last_error=NULL WHERE memory_id=?""",
        (now, memory_id),
    )
    conn.commit()


def mark_job_error(conn: sqlite3.Connection, memory_id: str, error: str) -> None:
    now = utcnow()
    conn.execute(
        """UPDATE appraisal_jobs SET status='pending', attempts=attempts+1,
           last_error=?, updated_at=? WHERE memory_id=?""",
        (str(error)[:1000], now, memory_id),
    )
    conn.commit()


def record_sleep(
    conn: sqlite3.Connection,
    *,
    day_key: str,
    reason: str,
    at: str | None = None,
    rotated: bool = False,
    farewell_sent: bool = False,
    details: dict[str, Any] | None = None,
) -> int:
    """Append one sleep/rotation run and return today's run count."""
    now = at or localnow()
    conn.execute(
        """INSERT INTO sleep_runs(day_key, reason, at, rotated, farewell_sent, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (day_key, reason, now, 1 if rotated else 0, 1 if farewell_sent else 0,
         json.dumps(details or {}, ensure_ascii=False), utcnow()),
    )
    conn.commit()
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM sleep_runs WHERE day_key=? AND reason IN ('sleep','daily')",
            (day_key,),
        ).fetchone()[0]
    )


def status(conn: sqlite3.Connection) -> dict[str, Any]:
    total = conn.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"]
    by_status = {
        r["appraisal_status"]: r["c"]
        for r in conn.execute(
            "SELECT appraisal_status, COUNT(*) c FROM memories GROUP BY appraisal_status"
        ).fetchall()
    }
    pending = conn.execute(
        "SELECT COUNT(*) c FROM appraisal_jobs WHERE status='pending'"
    ).fetchone()["c"]
    appraisals = conn.execute("SELECT COUNT(*) c FROM appraisals").fetchone()["c"]
    consolidation = {
        r["consolidation_state"]: r["c"]
        for r in conn.execute(
            "SELECT consolidation_state, COUNT(*) c FROM memories GROUP BY consolidation_state"
        ).fetchall()
    }
    snap = conn.execute(
        "SELECT * FROM affect_snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "memories": total,
        "appraisal_status": by_status,
        "appraisals": appraisals,
        "pending_jobs": pending,
        "consolidation": consolidation,
        "latest_affect": dict(snap) if snap else None,
    }


def mark_triggered(
    conn: sqlite3.Connection,
    ids: list[str],
    *,
    source: str = "manual",
    note: str = "",
) -> int:
    """Record that memories were activated today (used by the daily context)."""
    now = localnow()
    count = 0
    for mid in ids:
        cur = conn.execute(
            """UPDATE memories
               SET last_triggered_at=?, trigger_count=COALESCE(trigger_count,0)+1, updated_at=?
               WHERE id=?""",
            (now, utcnow(), mid),
        )
        if cur.rowcount:
            conn.execute(
                """INSERT INTO memory_activations (memory_id, ts, source, note, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (mid, now, source, note[:200], utcnow()),
            )
            count += 1
    conn.commit()
    return count


def daily_context(
    conn: sqlite3.Connection,
    *,
    day: str | None = None,
    limit: int = 12,
) -> list[sqlite3.Row]:
    """Memories triggered on a local day. This is the only memory text that
    should be offered to the speaking model for that day.
    """
    d = day or datetime.now().astimezone().date().isoformat()
    return conn.execute(
        """SELECT * FROM memories
           WHERE last_triggered_at IS NOT NULL
             AND substr(last_triggered_at, 1, 10) = ?
             AND status='active'
           ORDER BY last_triggered_at DESC
           LIMIT ?""",
        (d, max(1, int(limit))),
    ).fetchall()


def latest_p(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM p_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    out = dict(row)
    try:
        out["p"] = json.loads(out.pop("p_json"))
    except Exception:
        out["p"] = {}
    return out


def _parse_when(value: str) -> datetime:
    s = str(value or "").strip()
    if not s:
        raise ValueError("empty time")
    if len(s) == 10:
        s += "T00:00:00"
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return d.astimezone()


def query_memories_range(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    limit: int = 20,
    person_id: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Query a local time window, bounded; `truncated` is part of the contract."""
    start_dt = _parse_when(start)
    end_dt = _parse_when(end)
    if end_dt <= start_dt:
        raise ValueError("end must be after start")
    rows = conn.execute(
        """SELECT id, ts, created_at, scope, speaker, speaker_id, person_id, identity_status, text
           FROM memories ORDER BY COALESCE(ts, created_at) ASC"""
    ).fetchall()
    hits = []
    for row in rows:
        raw = row["ts"] or row["created_at"]
        try:
            dt = _parse_when(str(raw))
        except Exception:
            continue
        if not (start_dt <= dt < end_dt):
            continue
        if person_id and row["person_id"] != person_id:
            continue
        if scope and row["scope"] != scope:
            continue
        hits.append({
            "id": row["id"],
            "ts": row["ts"] or row["created_at"],
            "scope": row["scope"],
            "speaker": row["speaker"],
            "person_id": row["person_id"],
            "identity_status": row["identity_status"] or "unknown",
            "text": row["text"],
        })
    total = len(hits)
    max_n = max(1, min(20, int(limit)))
    return {
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "matched": total,
        "returned": min(total, max_n),
        "truncated": total > max_n,
        "items": hits[:max_n],
    }


DEMO = [
    ("demo:01", "今天主人夸我记事清楚，我有点开心。", "pet", 0.3, 2),
    ("demo:02", "主人说我上次记错了，我有点不安，想再确认一下。", "pet", 0.6, 3),
    ("demo:03", "主人提到一个我完全不认识的软件，我有点警惕。", "pet", 0.5, -1),
    ("demo:04", "我做了一件熟悉的小事，很顺利，感觉安心。", "pet", 0.2, 1),
    ("demo:05", "主人突然很久没说话，我不确定是不是自己做错了什么。", "pet", 0.7, 0),
    ("demo:06", "主人解释了那个软件是做什么的，我听懂了。", "pet", 0.4, 1),
    ("demo:07", "今天连续两次判断失误，我有点不想再主动猜了。", "pet", 0.8, -1),
    ("demo:08", "主人说没关系，下次注意就好，我感觉好多了。", "pet", 0.5, 2),
]


def seed_demo(conn: sqlite3.Connection) -> int:
    n = 0
    for rid, text, scope, importance, _tone in DEMO:
        _, created = upsert_memory(
            conn,
            source="demo",
            source_record_id=rid,
            text=text,
            ts=utcnow(),
            scope=scope,
            importance=importance,
            identity_status="synthetic",
            raw={"demo": True, "tone": _tone},
        )
        n += int(created)
    return n


def sync_surfcore(
    conn: sqlite3.Connection,
    *,
    surfcore_root: str | Path | None = None,
    limit: int = 20,
    include_sensitive: bool = False,
    full: bool = False,
) -> dict[str, int]:
    """Read-only import of the current SurfCore character's memory.

    Never writes to SurfCore. `memory-card.json` is the active (bounded) card;
    `memory-card-full.jsonl` is the unlimited archive. `full=True` merges both.
    """
    root = Path(surfcore_root) if surfcore_root else DEFAULT_SURFCORE_ROOT
    current_file = root / "characters" / "current.json"
    if not current_file.exists():
        raise FileNotFoundError(f"current character file not found: {current_file}")
    current = json.loads(current_file.read_text(encoding="utf-8"))
    char_dir = Path(current.get("dir")) if current.get("dir") else root / "characters" / str(current.get("id", ""))
    if not char_dir.exists():
        char_dir = root / "characters" / str(current.get("id", ""))
    card_file = char_dir / "memory" / "memory-card.json"
    if not card_file.exists():
        raise FileNotFoundError(f"memory card not found: {card_file}")
    card = json.loads(card_file.read_text(encoding="utf-8"))
    records = list(card.get("records") or [])
    from_full = 0
    if full:
        full_file = char_dir / "memory" / "memory-card-full.jsonl"
        if full_file.exists():
            # Full archive is append-only and can be large; keep only the tail
            # when a limit is supplied. 0 means scan the whole file.
            q: deque[str] = deque(maxlen=max(1, int(limit)) if limit else None)  # type: ignore[arg-type]
            with full_file.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.strip():
                        q.append(line)
            for line in q:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    records.append(rec)
                    from_full += 1
    # Prefer the most recent records when a limit is supplied.
    records = sorted(
        records,
        key=lambda r: str(r.get("createdAt") or r.get("lastSeenAt") or ""),
        reverse=True,
    )
    imported = 0
    skipped_sensitive = 0
    skipped_empty = 0
    seen: set[str] = set()
    for record in records[: max(0, int(limit) or len(records))]:
        rid = str(record.get("id") or "").strip()
        text = str(record.get("text") or record.get("title") or "").strip()
        if not rid or not text:
            skipped_empty += 1
            continue
        if rid in seen:
            continue
        seen.add(rid)
        if record.get("sensitive") and not include_sensitive:
            skipped_sensitive += 1
            continue
        _, created = upsert_memory(
            conn,
            source="surfcore",
            source_record_id=rid,
            text=text,
            ts=record.get("createdAt"),
            scope=str(record.get("scope") or "pet"),
            sensitive=bool(record.get("sensitive")),
            importance=float(record.get("importance") or 0) / 100.0,
            speaker=record.get("speaker"),
            identity_status=(
                "self" if (record.get("isSelf") or "self" in (record.get("tags") or []))
                else ("resolved" if record.get("speakerId") else "legacy_unresolved")
            ),
            raw=record,
        )
        imported += int(created)
    return {
        "imported_new": imported,
        "skipped_sensitive": skipped_sensitive,
        "skipped_empty": skipped_empty,
        "from_full": from_full,
        "character": str(current.get("name") or current.get("id") or ""),
    }
