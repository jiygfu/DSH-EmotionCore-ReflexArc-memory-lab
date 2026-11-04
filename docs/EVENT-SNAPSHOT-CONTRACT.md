# Pre-compaction event snapshot contract

Purpose: before DSH/native compaction replaces the context, ask the API for a
compact, structured event snapshot. Local EmotionCore stores it and later binds
events to raw memories. This is not a new prompt layer and does not close events
by itself.

## Trigger

```text
pressureTokens / contextWindow >= 0.80
```

Capture once per pressure epoch, before compaction. Do not send a full-context
duplicate request when a smaller event packet is enough; use the current session
context only when the event packet is insufficient.

## Request

`POST http://127.0.0.1:8765/event_snapshot`

```json
{
  "session_id": "session-...",
  "chat_key": "group:...",
  "captured_at": "2026-11-04T12:00:00+08:00",
  "trigger": "context_pressure_80",
  "pressure": {
    "pressureTokens": 820000,
    "contextWindow": 1000000,
    "ratio": 0.82
  },
  "events": [
    {
      "event_id": "api_evt_001",
      "stream_id": "",
      "title": "本地模型部署讨论",
      "summary": "讨论了 2B 模型上下文不足和后续验证方案。",
      "domain": "real",
      "participants": ["..."],
      "anchor_quotes": ["原文中的关键句"],
      "commitments": ["答应明天测试 4k 上下文"],
      "open_items": ["还需要验证长上下文表现"],
      "knowledge": ["2B 模型在 2k 上下文下会截断"],
      "confidence": 0.86,
      "is_new": true
    }
  ]
}
```

## Rules

- `domain`: `real` or `roleplay`.
- roleplay commitments/knowledge are in-fiction; local must set
  `personality_eligible=false`, `confidence_tier=low`, and keep
  `reference_weight>0`.
- `anchor_quotes` are the evidence bridge to local raw `memories`; IDs are
  optional because the API may not know local IDs.
- API output is a snapshot, not a closure decision. Local rules remain the
  authority for `thread_loops`/`anchor_at`.
- No automatic L5 injection; this table is an index.

## Storage

```text
event_snapshots
  snapshot_id, session_id, chat_key, captured_at, trigger,
  pressure_tokens, context_window, ratio, event_count,
  payload_json, created_at
```

## Local next step

1. Map `anchor_quotes` to raw memory IDs (local lexical/embedding match).
2. Write `event_memory_links` only after validation.
3. Sync real unfinished items to existing `thread_loops.anchor_at`.
4. Roleplay uses `fiction_anchor_at`; never real reminder.
