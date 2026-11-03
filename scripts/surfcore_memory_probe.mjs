// Read-only probe: reuse SurfCore's own full-memory recall.
// Run with: node scripts/surfcore_memory_probe.mjs "AI" 3
import { activeMemoryPaths } from 'file:///C:/Users/li/surfcore/src/character-persona.js'
import { resolveMemoryCardPaths, recallFullMemory } from 'file:///C:/Users/li/surfcore/src/memory-card.js'

const q = process.argv[2] || ''
const limit = Math.max(1, Math.min(50, Number(process.argv[3]) || 10))
const paths = resolveMemoryCardPaths(activeMemoryPaths().dir)
const records = recallFullMemory(paths, q, { limit })
console.log(JSON.stringify({
  q,
  limit,
  count: records.length,
  identity_notice: 'identity_status=legacy_unresolved/self 的旧记录不代表主人；未确认说话人的旧记忆不要归给 owner。',
  records: records.map((r) => ({
    id: r.id,
    date: r.createdAt,
    platform: r.platform,
    scope: r.scope,
    speaker: r.speaker,
    title: r.title,
    text: r.text,
    tags: r.tags,
    matchScore: r.matchScore,
    isSelf: r.isSelf === true,
    identity_status: r.soulcore?.identity_status || (r.isSelf === true ? 'self' : 'legacy_unresolved'),
    person_id: r.soulcore?.person_id || null,
    soulcore: r.soulcore || null,
  })),
}, null, 2))
