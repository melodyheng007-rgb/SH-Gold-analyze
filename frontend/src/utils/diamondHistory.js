function safeEntries(value) {
  return Array.isArray(value?.entries) ? value.entries : []
}

function entryKey(entry) {
  return String(
    entry?.zone_key
      || entry?.event_id
      || `${entry?.symbol || ''}:${entry?.timeframe || ''}:${entry?.zone_id || ''}:${entry?.origin_time || ''}`,
  )
}

function entryTimestamp(entry) {
  const numeric = Number(entry?.event_time || entry?.origin_time || entry?.id)
  if (Number.isFinite(numeric)) return numeric
  const parsed = Date.parse(entry?.updated_at || entry?.first_seen_at || '')
  return Number.isFinite(parsed) ? parsed / 1000 : 0
}

export function mergeDiamondHistorySnapshot(current, incoming, limit = 500) {
  if (!incoming || typeof incoming !== 'object') return current
  const previousEntries = safeEntries(current)
  const incomingEntries = safeEntries(incoming)
  if (!previousEntries.length) return incoming

  const merged = new Map()
  previousEntries.forEach(entry => merged.set(entryKey(entry), entry))
  incomingEntries.forEach(entry => merged.set(entryKey(entry), entry))

  return {
    ...(current || {}),
    ...incoming,
    stats: {
      ...(current?.stats || {}),
      ...(incoming?.stats || {}),
    },
    entries: [...merged.values()]
      .sort((left, right) => entryTimestamp(right) - entryTimestamp(left))
      .slice(0, Math.max(1, Number(limit) || 500)),
  }
}
