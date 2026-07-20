export function diamondReplayTimestamp(entry = {}) {
  const classification = String(entry.classification || 'CONTEXT').toUpperCase()
  const confirmed = classification === 'CONFIRMED' || classification === 'AUTO_ENTRY'
  const value = confirmed && entry.event_time ? entry.event_time : entry.origin_time
  const timestamp = Number(value)
  return Number.isFinite(timestamp) ? timestamp : null
}

export function diamondMarkerKind(classification) {
  const normalized = String(classification || 'CONTEXT').toUpperCase()
  if (normalized === 'CONFIRMED' || normalized === 'AUTO_ENTRY') return 'entry'
  if (normalized === 'QUALIFIED') return 'setup'
  return 'context'
}

export function diamondHistoricalScore(entry = {}) {
  const candidates = [
    entry.peak_diamond_score,
    entry.diamond_score,
    entry.event_quality,
    entry.evidence_snapshot?.diamond?.diamond_score,
  ]
    .map(Number)
    .filter(Number.isFinite)
  return candidates.length ? Math.max(...candidates) : 0
}

export function diamondWasVisible(entry = {}, minimumScore = null) {
  const classification = String(entry.classification || 'CONTEXT').toUpperCase()
  const peakGrade = String(entry.peak_diamond_grade || entry.diamond_grade || '').toUpperCase()
  const explicitMinimum = Number(minimumScore)
  const scoreFloor = minimumScore !== null && Number.isFinite(explicitMinimum)
    ? explicitMinimum
    : String(entry.symbol || '').toUpperCase() === 'XAUUSD' ? 45 : 50
  return entry.ever_visible === true
    || ['QUALIFIED', 'CONFIRMED', 'AUTO_ENTRY'].includes(classification)
    || ['A+', 'A', 'B', 'C', 'D'].includes(peakGrade)
    || diamondHistoricalScore(entry) >= scoreFloor
}

export function diamondIsProductionResult(classification) {
  return diamondMarkerKind(classification) === 'entry'
}

export function evidenceSampleStatus(resolved) {
  const sample = Math.max(0, Number(resolved) || 0)
  if (sample >= 100) return 'EVIDENCE_READY'
  if (sample >= 50) return 'DEVELOPING_SAMPLE'
  if (sample >= 20) return 'EARLY_SAMPLE'
  return 'INSUFFICIENT_SAMPLE'
}

export function evidenceProgress(resolved, minimum = 100) {
  const sample = Math.max(0, Number(resolved) || 0)
  const target = Math.max(1, Number(minimum) || 100)
  return Math.min(100, Math.round(sample / target * 100))
}
