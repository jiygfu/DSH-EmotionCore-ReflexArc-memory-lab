# EmotionCore local service

Local HTTP seam over `soulcore` and `data/soulcore.db`. It is **not a second
memory store**; it only exposes the existing local database to the QQ adapter
and the settings page.

```text
default: 127.0.0.1:8765
db:      data/soulcore.db
```

## Start / stop

```powershell
# from repo root; replace python with your own interpreter
python plugins/emotioncore-service/server.py --port 8765

# optional convenience wrapper
powershell -NoProfile -ExecutionPolicy Bypass -File plugins/emotioncore-service/start.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File plugins/emotioncore-service/stop.ps1
```

`start.ps1` uses `$PSScriptRoot` and `$env:SOULCORE_PYTHON`; it does not embed a
machine-specific absolute path. Normally DSH starts this process through
`@soulproject/emotioncore-runtime`.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | version + memory/person counts |
| POST | `/context` | L5 wake assembly: handoff, L3 index, L4 people/affect |
| POST | `/turn` | write one completed user/assistant turn |
| GET | `/person?qq=...` | read-only person relationship + tags |
| POST | `/person_impression` | first-contact impression |
| POST | `/recall` | L3 index, L3 episode detail, or L2 raw memory |
| POST | `/activity` | long-activity start/pause/resume/end vote |
| POST | `/person_tag` | add L4 person impression tags (fish record etc.) |

### `/context`

Request:

```json
{
  "version": 1,
  "chatKey": "group:123",
  "isGroup": true,
  "groupId": 123,
  "sender": { "qq": 456, "name": "Alice" },
  "text": "今天怎么样"
}
```

Returns `{ok, context, first_wake, persona, people, l2, ...}`. The adapter
truncates `context` to 1800 characters; it never injects raw memory rows.

`preview: true` assembles context without writing `first_wake`, person state, or
day baseline. The settings page uses this for L5 preview.

### `/recall`

```json
{ "query": "跑团", "scope": "group", "groupId": "123", "limit": 2 }
{ "episode_id": "ep_..." }
{ "memory_id": "..." }
```

Returns a level marker:

```text
index   → L3 event candidates
episode → L3 detail
memory  → L2 raw row
```

Every call appends an observability record to
`data/memory-layer-calls.jsonl`; raw memory text is not logged, only ids,
counts, query preview and result size.

### `/person_tag`

```json
{ "qq": "456", "name": "Alice", "tags": ["肥鱼", "鱼群"] }
```

Merges tags into `people.tags_json` and returns the person context. Used by
ReflexArc 鱼群记录. It does not change P values, trust, or familiarity.

### `/activity`

Returns a local vote (`start/pause/resume/interrupt/end/continue`) for the
QQ long-activity state machine. It never stores the activity; ReflexArc owns
the state and archives locally.

## Worker

`worker.py` is the maintenance loop (sleep/appraisal/rotation helpers). It is
started by `emotioncore-runtime`, not directly by the service.

## Environment

```text
EMOTIONCORE_PORT / SOULCORE_PORT       default 8765
EMOTIONCORE_DB / SOULCORE_DB           default data/soulcore.db
EMOTIONCORE_LAYER_CALL_LOG             default data/memory-layer-calls.jsonl
EMOTIONCORE_PERSONA                    optional persona file
```

## Boundaries

- Loopback only; no authentication layer because it is not exposed.
- Read/write memory only through the local DB and `soulcore` helpers.
- Does not call an online model for `/context`; `/activity` is keyword/local
  plus open loops, no model.
- Does not send QQ messages; the adapter/dispatcher owns outbound.
