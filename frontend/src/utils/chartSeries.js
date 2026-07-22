function normalizedTime(value) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return null
  const seconds = parsed > 10_000_000_000 ? parsed / 1000 : parsed
  return Math.trunc(seconds)
}

export function normalizeChartCandles(source, limit = 500) {
  const byTime = new Map()

  for (const item of Array.isArray(source) ? source : []) {
    const time = normalizedTime(item?.time)
    const open = Number(item?.open)
    const high = Number(item?.high)
    const low = Number(item?.low)
    const close = Number(item?.close)
    if (time === null || ![open, high, low, close].every(Number.isFinite)) continue

    const volume = Number(item?.volume)
    byTime.set(time, {
      ...item,
      time,
      open,
      high: Math.max(open, high, low, close),
      low: Math.min(open, high, low, close),
      close,
      ...(Number.isFinite(volume) ? { volume } : {}),
    })
  }

  return [...byTime.values()]
    .sort((left, right) => left.time - right.time)
    .slice(-Math.max(1, Number(limit) || 500))
}

export function normalizeChartSeries(source, mapper, limit = 500) {
  const byTime = new Map()
  if (typeof mapper !== 'function') return []

  for (const item of Array.isArray(source) ? source : []) {
    const mapped = mapper(item)
    const time = normalizedTime(mapped?.time)
    const value = Number(mapped?.value)
    if (time === null || !Number.isFinite(value)) continue
    byTime.set(time, { ...mapped, time, value })
  }

  return [...byTime.values()]
    .sort((left, right) => left.time - right.time)
    .slice(-Math.max(1, Number(limit) || 500))
}
