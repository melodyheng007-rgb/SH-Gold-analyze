export function signalScore(signal) {
  const value = Number(
    signal?.diamond_score
      ?? signal?.quality_score
      ?? signal?.diamond_confidence_score
      ?? signal?.event_quality
      ?? signal?.origin_quality
      ?? signal?.zone_strength,
  )
  return Number.isFinite(value) ? Math.max(0, Math.min(100, Math.round(value))) : 0
}

export function signalTier(signal) {
  const explicit = String(signal?.signal_tier || '').toUpperCase()
  if (['EARLY', 'QUALIFIED', 'CONFIRMED'].includes(explicit)) return explicit
  const classification = String(signal?.classification || signal?.display_classification || '').toUpperCase()
  if (['CONFIRMED', 'AUTO_ENTRY'].includes(classification) || signal?.marker_kind === 'entry') return 'CONFIRMED'
  if (
    classification === 'QUALIFIED'
    || signal?.entry_score_qualified
    || (signalScore(signal) >= 60 && signal?.entry_eligible_origin)
    || signal?.marker_kind === 'setup'
  ) return 'QUALIFIED'
  return 'EARLY'
}
