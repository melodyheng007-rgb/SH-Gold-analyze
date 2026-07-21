function candleTime(value) {
  const numeric = Number(value)
  if (Number.isFinite(numeric)) return numeric
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function mergeCandles(current = [], updates = [], limit = 1000) {
  const indexed = new Map()
  for (const candle of Array.isArray(current) ? current : []) {
    const key = candleTime(candle?.time)
    if (key !== null) indexed.set(key, candle)
  }
  for (const candle of Array.isArray(updates) ? updates : []) {
    const key = candleTime(candle?.time)
    if (key !== null) indexed.set(key, { ...(indexed.get(key) || {}), ...candle })
  }
  const merged = [...indexed.entries()]
    .sort(([left], [right]) => left - right)
    .map(([, candle]) => candle)
  const safeLimit = Math.max(1, Number(limit) || 1000)
  return merged.length > safeLimit ? merged.slice(-safeLimit) : merged
}

export function mergeChartDelta(current, delta) {
  if (!delta || typeof delta !== 'object') return current
  const base = current && typeof current === 'object' ? current : {}
  const currentCandles = Array.isArray(base.candles) ? base.candles : []
  const updates = Array.isArray(delta.candles) ? delta.candles : []
  const historyLimit = Math.max(currentCandles.length, updates.length, 1)
  const candles = mergeCandles(currentCandles, updates, historyLimit)
  const segments = base.segments && typeof base.segments === 'object' ? base.segments : {}
  const active = mergeCandles(segments.active || currentCandles, updates, historyLimit)
  const source = delta.source
  const sourceUpdates = source ? updates.filter(candle => !candle?.source || candle.source === source) : updates
  const history = mergeCandles(segments.history || [], sourceUpdates, Math.max((segments.history || []).length, sourceUpdates.length, 1))

  return {
    ...base,
    ...delta,
    candles,
    segments: {
      ...segments,
      active,
      history,
      live: mergeCandles(segments.live || [], updates, Math.max((segments.live || []).length, updates.length, 1)),
    },
    data_integrity: {
      ...(base.data_integrity || {}),
      ...(delta.data_integrity || {}),
    },
    alignment: {
      ...(base.alignment || {}),
      ...(delta.alignment || {}),
    },
  }
}
