const CACHE_KEY = 'sh_market_chart_bootstrap_v2'
const CACHE_VERSION = 2
const DEFAULT_MAX_AGE_MS = 12 * 60 * 60 * 1000
const MIN_HISTORY_CANDLES = 30

function normalizedAsset(value) {
  return String(value || '').trim().toUpperCase()
}

function normalizedTimeframe(value) {
  return String(value || '').trim().toUpperCase()
}

function chartCandles(chartData) {
  const active = chartData?.segments?.active
  if (Array.isArray(active) && active.length) return active
  return Array.isArray(chartData?.candles) ? chartData.candles : []
}

export function isIndicatorSnapshotReady(panelState) {
  return panelState?.status === 'READY'
    || panelState?.readiness?.status === 'READY'
    || panelState?.indicator_panels?.indicator_snapshot?.status === 'READY'
}

export function createChartSnapshotRecord(result, asset, timeframe, now = Date.now()) {
  const chartData = result?.chart_data
  const expectedAsset = normalizedAsset(asset)
  const expectedTimeframe = normalizedTimeframe(timeframe)
  const actualAsset = normalizedAsset(chartData?.symbol || result?.symbol)
  const actualTimeframe = normalizedTimeframe(chartData?.timeframe || result?.timeframe)
  const integrity = chartData?.data_integrity || {}

  if (!chartData || actualAsset !== expectedAsset || actualTimeframe !== expectedTimeframe) return null
  if (result?.provider_alignment?.matched !== true || integrity?.mixed_chart_sources === true) return null
  if (chartCandles(chartData).length < MIN_HISTORY_CANDLES) return null

  return {
    version: CACHE_VERSION,
    saved_at: Number(now),
    asset: expectedAsset,
    timeframe: expectedTimeframe,
    snapshot: {
      status: 'BROWSER_SNAPSHOT',
      symbol: expectedAsset,
      timeframe: expectedTimeframe,
      chart_data: chartData,
      overlays: result?.overlays || { overlays: {} },
      panels: result?.panels || { indicator_panels: {} },
      provider_alignment: result.provider_alignment,
      history_provenance: result?.history_provenance || null,
    },
  }
}

export function writeChartSnapshot(storage, result, asset, timeframe, now = Date.now()) {
  if (!storage?.setItem) return false
  const record = createChartSnapshotRecord(result, asset, timeframe, now)
  if (!record) return false
  try {
    const current = JSON.parse(storage.getItem(CACHE_KEY) || 'null')
    const records = current?.version === CACHE_VERSION && current?.records && typeof current.records === 'object'
      ? { ...current.records }
      : {}
    records[`${record.asset}:${record.timeframe}`] = record
    const pruned = Object.fromEntries(
      Object.entries(records)
        .sort(([, left], [, right]) => Number(right?.saved_at || 0) - Number(left?.saved_at || 0))
        .slice(0, 12),
    )
    storage.setItem(CACHE_KEY, JSON.stringify({ version: CACHE_VERSION, records: pruned }))
    return true
  } catch (_) {
    return false
  }
}

export function readChartSnapshot(storage, asset, timeframe, options = {}) {
  if (!storage?.getItem) return null
  const now = Number(options.now ?? Date.now())
  const maxAgeMs = Number(options.maxAgeMs ?? DEFAULT_MAX_AGE_MS)
  try {
    const container = JSON.parse(storage.getItem(CACHE_KEY) || 'null')
    const record = container?.version === CACHE_VERSION
      ? container?.records?.[`${normalizedAsset(asset)}:${normalizedTimeframe(timeframe)}`]
      : null
    if (record?.version !== CACHE_VERSION) return null
    if (normalizedAsset(record.asset) !== normalizedAsset(asset)) return null
    if (normalizedTimeframe(record.timeframe) !== normalizedTimeframe(timeframe)) return null
    if (!Number.isFinite(record.saved_at) || now - record.saved_at > maxAgeMs || record.saved_at > now + 60_000) return null

    const validated = createChartSnapshotRecord(record.snapshot, asset, timeframe, record.saved_at)
    return validated?.snapshot || null
  } catch (_) {
    return null
  }
}

export function clearChartSnapshot(storage) {
  try {
    storage?.removeItem?.(CACHE_KEY)
  } catch (_) {
    // Storage access is optional; the network snapshot remains available.
  }
}
