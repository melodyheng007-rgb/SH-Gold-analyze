const numberOrNull = value => {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number : null
}

const diamondSide = signal => {
  const raw = String(signal?.entry_side || signal?.direction || '').toUpperCase()
  if (raw === 'BUY' || raw === 'BULLISH') return 'BUY'
  if (raw === 'SELL' || raw === 'BEARISH') return 'SELL'
  return 'WAIT'
}

export function deriveDiamondRiskGuide(signal, keyZones, sessionFramework, latestPrice) {
  const side = diamondSide(signal)
  const reference = numberOrNull(signal?.execution_entry ?? signal?.line ?? latestPrice)
  const marketPrice = numberOrNull(latestPrice)
  const targetThreshold = side === 'BUY'
    ? Math.max(reference || 0, marketPrice || 0)
    : side === 'SELL'
      ? Math.min(reference || Number.POSITIVE_INFINITY, marketPrice || Number.POSITIVE_INFINITY)
      : reference
  const rawInvalidation = numberOrNull(keyZones?.invalidation_level ?? signal?.invalidation_level)
  const invalidation = reference && rawInvalidation && (
    (side === 'BUY' && rawInvalidation < reference)
    || (side === 'SELL' && rawInvalidation > reference)
  ) ? rawInvalidation : null

  const levels = sessionFramework?.levels || {}
  const kTrend = sessionFramework?.k_trend || {}
  const candidates = [
    ['K+3', levels.k_plus_3],
    ['K+2', levels.k_plus_2 ?? levels.dr_plus_2],
    ['K+1', levels.k_plus_1 ?? levels.dr_plus_1],
    ['OP', levels.op],
    ['MLP', levels.mlp],
    ['PIVOT', levels.pivot],
    ['K-1', levels.k_minus_1 ?? levels.dr_minus_1],
    ['K-2', levels.k_minus_2 ?? levels.dr_minus_2],
    ['K-3', levels.k_minus_3],
    [kTrend.next_target_label || 'K Target', kTrend.next_target],
  ]
    .map(([label, value]) => ({ label, price: numberOrNull(value) }))
    .filter(item => item.price && reference && (
      (side === 'BUY' && item.price > targetThreshold)
      || (side === 'SELL' && item.price < targetThreshold)
    ))
    .sort((left, right) => Math.abs(left.price - targetThreshold) - Math.abs(right.price - targetThreshold))

  const target = candidates[0] || null
  const risk = invalidation && reference ? Math.abs(reference - invalidation) : null
  const reward = target && reference ? Math.abs(target.price - reference) : null
  const riskReward = risk && reward ? reward / risk : null

  return {
    side,
    reference,
    invalidation,
    target: target?.price ?? null,
    targetLabel: target?.label ?? null,
    riskReward: Number.isFinite(riskReward) ? Math.round(riskReward * 100) / 100 : null,
    ready: Boolean(side !== 'WAIT' && reference && invalidation && target),
    method: 'Diamond invalidation plus the next directional OP, MLP, Pivot, or K-Range level.',
  }
}
