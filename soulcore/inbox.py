"""Read-only sync of SurfCore's memory-inbox.jsonl, preserving sender identity.

The active memory card keeps only `speaker` display text and drops `senderId`.
This module imports the inbox events into the local store with:

    source = 'surfcore-inbox'
    speaker_id / person_id / group_id / conversation_key
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import deque
from pathlib import Path

from . import db, people


def _char_dir(surfcore_root: str | Path | None = None) -> Path:
    root = Path(surfcore_root) if surfcore_root else db.DEFAULT_SURFCORE_ROOT
    current_file = root / "characters" / "current.json"
    if not current_file.exists():
        raise FileNotFoundError(f"current character file not found: {current_file}")
    current = json.loads(current_file.read_text(encoding="utf-8"))
    d = Path(current.get("dir")) if current.get("dir") else root / "characters" / str(current.get("id", ""))
    if not d.exists():
        d = root / "characters" / str(current.get("id", ""))
    return d


def _event_id(event: dict) -> str:
    key = "|".join(str(event.get(k) or "") for k in ("at", "createdAt", "senderId", "groupId", "conversationKey", "text"))
    return hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:20]


def sync_inbox(
    conn: sqlite3.Connection,
    *,
    surfcore_root: str | Path | None = None,
    limit: int = 500,
    include_self: bool = True,
) -> dict[str, int]:
    char = _char_dir(surfcore_root)
    inbox = char / "memory" / "memory-inbox.jsonl"
    # Newer SurfCore no longer writes memory-inbox.jsonl; the durable full card
    # is the source of truth. Keep the old path first for compatibility.
    if not inbox.exists():
        inbox = char / "memory" / "memory-card-full.jsonl"
    if not inbox.exists():
        raise FileNotFoundError(f"memory inbox/full card not found under {char / 'memory'}")
    lines: deque[str] = deque(maxlen=max(1, int(limit)) if limit else None)  # type: ignore[arg-type]
    with inbox.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.strip():
                lines.append(line)

    new = 0
    seen = 0
    skipped_self = 0
    people_seen: set[str] = set()
    for line in lines:
        try:
            event = json.loads(line)
        except Exception:
            continue
        text = str(event.get("text") or "").strip()
        if not text:
            continue
        is_self = bool(event.get("isSelf"))
        if is_self and not include_self:
            skipped_self += 1
            continue
        sender_id = str(event.get("senderId") or "").strip()
        sender = str(event.get("speaker") or event.get("sender") or "").strip()
        owner = bool(event.get("isOwner"))
        pid = None
        if sender_id and not is_self:
            pid = people.upsert_person(
                conn,
                user_id=sender_id,
                display_name=sender or sender_id,
                is_owner=owner,
                seen_at=str(event.get("at") or event.get("createdAt") or "") or None,
                increment=False,
            )
            people_seen.add(pid)
        scope = "private" if event.get("private") or event.get("kind") == "private" else "group"
        _, created = db.upsert_memory(
            conn,
            source="surfcore-inbox",
            source_record_id=_event_id(event),
            text=text,
            ts=event.get("at") or event.get("createdAt") or event.get("lastSeenAt"),
            scope=scope,
            sensitive=False,
            importance=0.0,
            speaker=sender or ("角色" if is_self else "群友"),
            speaker_id=sender_id or None,
            person_id=pid,
            identity_confidence=1.0 if sender_id and not is_self else 0.0,
            identity_status=("self" if is_self else ("resolved" if pid else "unresolved")),
            group_id=str(event.get("groupId") or "") or None,
            conversation_key=str(event.get("conversationKey") or "") or None,
            dedupe=True,
            raw=event,
        )
        if created:
            new += 1
            if pid:
                people.upsert_person(
                    conn,
                    user_id=sender_id,
                    display_name=sender or sender_id,
                    is_owner=owner,
                    seen_at=str(event.get("at") or event.get("createdAt") or "") or None,
                    increment=True,
                )
        else:
            seen += 1
    return {
        "new": new,
        "seen": seen,
        "skipped_self": skipped_self,
        "people": len(people_seen),
        "inbox": str(inbox),
    }
