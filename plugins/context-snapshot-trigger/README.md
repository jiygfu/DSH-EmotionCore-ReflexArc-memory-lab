# context-snapshot-trigger

DSH host bundle. At `pressureTokens / contextWindow >= 0.80`, it sends a bounded
packet of recent messages to EmotionCore:

```text
POST http://127.0.0.1:8765/event_snapshot/request
```

EmotionCore makes one online event-snapshot request, stores it in
`event_snapshots`, and leaves all event linking to local anchor verification.

## Safety

- fire-and-forget; never delays the turn;
- one snapshot per session per cooldown (default 10 min), and only if pressure
  rises by at least 0.05;
- hard stop at 95%, so it never pushes toward overflow;
- no full-context duplicate request; max 80 messages / 40k chars by default;
- no event closure, no L5 change.

## Disable

Set `enabled: false` in the bundle config or disable the plugin row.
