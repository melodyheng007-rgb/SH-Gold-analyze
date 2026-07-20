import test from 'node:test'
import assert from 'node:assert/strict'

import { confidenceEngineSummary, confidenceStageState, decisionPlanVisible, executionReadinessGates } from '../src/utils/confidenceEngine.js'

const stages = [
  { id: 'scanned', count: 500, reached: true },
  { id: 'qualified_origins', count: 8, reached: true },
  { id: 'confirmed_entries', count: 0, reached: false },
]

test('confidence stays in research mode when the feed is not reconciled', () => {
  const summary = confidenceEngineSummary({
    key_zones: { gate_funnel: { stages, current_gate: 'qualified_origins', next_gate: 'confirmed_entries' } },
    feed_reconciliation: { status: 'SOURCE_MISMATCH', trusted: false },
  })
  assert.equal(summary.status, 'RESEARCH_ONLY')
  assert.equal(summary.trusted, false)
  assert.equal(summary.brokerExecutable, false)
})

test('confirmed confidence requires both a trusted feed and confirmed closed-candle entry', () => {
  const confirmedStages = stages.map(stage => stage.id === 'confirmed_entries' ? { ...stage, count: 1, reached: true } : stage)
  const summary = confidenceEngineSummary({
    key_zones: { gate_funnel: { stages: confirmedStages, current_gate: 'confirmed_entries' } },
    feed_reconciliation: { status: 'MATCHED_RECONCILED', trusted: true },
    execution_reality: { broker_executable: false },
  })
  assert.equal(summary.status, 'CONFIRMED')
  assert.equal(summary.brokerExecutable, false)
})

test('gate stage state identifies the current and next blockers', () => {
  const summary = { currentGate: 'qualified_origins', nextGate: 'confirmed_entries' }
  assert.equal(confidenceStageState(stages[1], summary), 'current')
  assert.equal(confidenceStageState(stages[2], summary), 'next')
  assert.equal(confidenceStageState(stages[0], summary), 'reached')
})

test('backend Decision Quality status and conservative ceiling drive the summary', () => {
  const summary = confidenceEngineSummary({
    key_zones: { gate_funnel: { stages } },
    feed_reconciliation: { status: 'MATCHED_RECONCILED', trusted: true },
    decision_quality: {
      status: 'HISTORICAL_CONTEXT',
      score: 59,
      score_ceiling: 59,
      grade: 'C',
      data_confidence: 100,
      evidence_confidence: 42,
      setup_confidence: 55,
      event_freshness: 'HISTORICAL_CONTEXT',
      next_best_action: 'Wait for a new current-candle confirmation.',
    },
  })
  assert.equal(summary.status, 'HISTORICAL_CONTEXT')
  assert.equal(summary.decisionScore, 59)
  assert.equal(summary.scoreCeiling, 59)
  assert.equal(summary.tone, 'warn')
  assert.equal(summary.eventFreshness, 'HISTORICAL_CONTEXT')
})

test('execution levels stay hidden until Decision Quality allows the current setup', () => {
  assert.equal(decisionPlanVisible({}), true)
  assert.equal(decisionPlanVisible({ status: 'HISTORICAL_CONTEXT', decision_allowed: false }), false)
  assert.equal(decisionPlanVisible({ status: 'CONTEXT_ONLY', decision_allowed: false }), false)
  assert.equal(decisionPlanVisible({ status: 'TRACKABLE_SETUP', decision_allowed: true }), true)
})

test('Regime Guard conflict is exposed as a blocking confidence state', () => {
  const summary = confidenceEngineSummary({
    key_zones: { gate_funnel: { stages } },
    feed_reconciliation: { status: 'MATCHED_RECONCILED', trusted: true },
    market_regime: {
      regime: 'TRENDING_BEARISH',
      execution_gate: 'BLOCK_DIRECTION_CONFLICT',
      strength: 78,
    },
    decision_quality: {
      status: 'REGIME_CONFLICT',
      score: 54,
      score_ceiling: 54,
    },
  })

  assert.equal(summary.tone, 'bad')
  assert.equal(summary.regime, 'TRENDING_BEARISH')
  assert.equal(summary.regimeGate, 'BLOCK_DIRECTION_CONFLICT')
  assert.equal(summary.regimeStrength, 78)
  assert.equal(decisionPlanVisible({ status: 'REGIME_CONFLICT', decision_allowed: false }), false)
})

test('execution readiness exposes the next critical gate and anti-chase location', () => {
  const summary = confidenceEngineSummary({
    key_zones: { gate_funnel: { stages } },
    feed_reconciliation: { status: 'MATCHED_RECONCILED', trusted: true },
    market_regime: {
      regime: 'TRENDING_BULLISH',
      execution_gate: 'WAIT_OVEREXTENDED',
      location_guard: { status: 'WAIT_OVEREXTENDED', directional_extension_atr: 5.2 },
    },
    decision_quality: {
      status: 'LOCATION_GUARD',
      score: 54,
      score_ceiling: 54,
      primary_blocker: { id: 'location', label: 'Location Guard', reason: 'Do not chase price.' },
      execution_readiness: {
        status: 'FORMING',
        passed: 3,
        total: 6,
        percent: 50,
        next_gate_label: 'Location Guard',
      },
    },
  })

  assert.equal(summary.tone, 'bad')
  assert.equal(summary.readinessPercent, 50)
  assert.equal(summary.readinessPassed, 3)
  assert.equal(summary.primaryBlocker.label, 'Location Guard')
  assert.equal(summary.locationGuard.directional_extension_atr, 5.2)
  assert.equal(decisionPlanVisible({ status: 'LOCATION_GUARD', decision_allowed: false }), false)
})

test('action dock uses the same authoritative six readiness gates', () => {
  const gates = executionReadinessGates({
    key_zones: {
      timeframe: '15M',
      confirmation_timeframe: '5M',
      required_timeframes: ['15M', '5M'],
    },
    decision_quality: {
      execution_readiness: {
        gates: [
          { id: 'data', label: 'Data Trust', pass: true, reason: 'Matched.' },
          { id: 'origin', label: 'Diamond Origin', pass: false, reason: 'Wait.' },
          { id: 'mtf', label: 'MTF Agreement', pass: false, reason: 'Wait.' },
          { id: 'location', label: 'Location Guard', pass: false, reason: 'Wait.' },
          { id: 'trigger', label: 'Closed Trigger', pass: false, reason: 'Wait.' },
          { id: 'risk', label: 'Risk Geometry', pass: false, reason: 'Wait.' },
        ],
      },
    },
  })

  assert.equal(gates.length, 6)
  assert.equal(gates.find(gate => gate.id === 'mtf').timeframe, '15M / 5M')
  assert.equal(gates.find(gate => gate.id === 'trigger').timeframe, '5M')
  assert.equal(gates.find(gate => !gate.pass).label, 'Diamond Origin')
})
