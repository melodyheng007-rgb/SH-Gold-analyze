const TRUSTED_RECONCILIATION = new Set([
  'MATCHED_RECONCILED',
  'MATCHED_AWAITING_COMPARABLE_CLOSE',
  'MATCHED_MARKET_CLOSED',
])

export function confidenceEngineSummary(analysis = {}, governance = {}, alerts = {}) {
  const funnel = analysis?.key_zones?.gate_funnel || {}
  const reconciliation = analysis?.feed_reconciliation || {}
  const execution = analysis?.execution_reality || {}
  const quality = analysis?.decision_quality || {}
  const regime = analysis?.market_regime || {}
  const readiness = quality?.execution_readiness || {}
  const locationGuard = quality?.location_guard || regime?.location_guard || {}
  const stages = Array.isArray(funnel.stages) ? funnel.stages : []
  const confirmed = Number(stages.find(stage => stage.id === 'confirmed_entries')?.count) || 0
  const trusted = reconciliation.trusted === true || TRUSTED_RECONCILIATION.has(reconciliation.status)
  const unresolvedAlerts = Number(alerts?.stats?.unread) || 0

  let status = quality.status || 'WAITING_DATA'
  if (!quality.status && trusted && confirmed > 0) status = 'CONFIRMED'
  else if (!quality.status && trusted && execution.research_trackable === true) status = 'TRACKABLE'
  else if (!quality.status && trusted && stages.length) status = 'SCANNING'
  else if (!quality.status && stages.length) status = 'RESEARCH_ONLY'

  const goodStatuses = new Set(['CONFIRMED', 'TRACKABLE', 'TRACKABLE_SETUP', 'TRACKABLE_LIMITED_EVIDENCE'])
  const badStatuses = new Set(['DATA_BLOCKED', 'NEWS_LOCKED', 'VOLATILITY_LOCKED', 'REGIME_CONFLICT', 'LOCATION_GUARD'])

  return {
    status,
    tone: goodStatuses.has(status) ? 'good' : badStatuses.has(status) || !trusted ? 'bad' : 'warn',
    stages,
    reached: stages.filter(stage => stage.reached).length,
    total: stages.length,
    currentGate: funnel.current_gate || 'scanned',
    nextGate: funnel.next_gate || null,
    trusted,
    brokerExecutable: execution.broker_executable === true,
    decisionScore: Number.isFinite(Number(quality.score)) ? Number(quality.score) : null,
    decisionGrade: quality.grade || '-',
    scoreCeiling: Number(quality.score_ceiling) || 0,
    dataConfidence: Number(quality.data_confidence) || 0,
    evidenceConfidence: Number(quality.evidence_confidence) || 0,
    setupConfidence: Number(quality.setup_confidence) || 0,
    qualityComponents: Array.isArray(quality.components) ? quality.components : [],
    nextBestAction: quality.next_best_action || 'Waiting for Decision Quality diagnostics.',
    eventFreshness: quality.event_freshness || 'WAITING_DATA',
    executionReadiness: readiness,
    readinessPercent: Number(readiness.percent) || 0,
    readinessPassed: Number(readiness.passed) || 0,
    readinessTotal: Number(readiness.total) || 6,
    primaryBlocker: quality.primary_blocker || readiness.current_gate || null,
    locationGuard,
    regime: regime.regime || 'UNKNOWN',
    regimeGate: regime.execution_gate || 'OBSERVE',
    regimeStrength: Number(regime.strength) || 0,
    unresolvedAlerts,
    challengerResolved: Number(governance?.challenger?.summary?.resolved) || 0,
    promotionMinimum: Number(governance?.policy?.minimum_resolved_sample) || 100,
  }
}

export function confidenceStageState(stage = {}, summary = {}) {
  if (stage.id === 'confirmed_entries' && Number(stage.count) > 0) return 'confirmed'
  if (stage.id === summary.currentGate) return 'current'
  if (stage.id === summary.nextGate) return 'next'
  return stage.reached ? 'reached' : 'waiting'
}

export function decisionPlanVisible(decisionQuality = {}) {
  return !decisionQuality.status || decisionQuality.decision_allowed === true
}

export function executionReadinessGates(analysis = {}) {
  const readiness = analysis?.decision_quality?.execution_readiness || {}
  const gates = Array.isArray(readiness.gates) ? readiness.gates : []
  if (!gates.length) return []
  const zones = analysis?.key_zones || {}
  const frames = Array.isArray(zones?.required_timeframes) ? zones.required_timeframes : []
  const timeframeByGate = {
    data: 'All',
    origin: zones.timeframe || 'Closed',
    mtf: frames.join(' / ') || 'Profile',
    location: zones.timeframe || 'Closed',
    trigger: zones.confirmation_timeframe || zones.timeframe || 'Closed',
    risk: 'Mapped',
  }
  return gates.map(gate => ({
    ...gate,
    compactLabel: gate.label,
    timeframe: timeframeByGate[gate.id] || 'Closed',
  }))
}
