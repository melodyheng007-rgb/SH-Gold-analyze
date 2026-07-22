import test from 'node:test'
import assert from 'node:assert/strict'

import {
  diamondIsProductionResult,
  diamondHistoricalScore,
  diamondMarkerKind,
  diamondReplayTimestamp,
  diamondWasVisible,
  evidenceProgress,
  evidenceSampleStatus,
} from '../src/utils/diamondEvidence.js'

test('confirmed Diamond replays at event time', () => {
  assert.equal(diamondReplayTimestamp({ classification: 'CONFIRMED', origin_time: 100, event_time: 200 }), 200)
  assert.equal(diamondReplayTimestamp({ classification: 'AUTO_ENTRY', origin_time: 100, event_time: 250 }), 250)
})

test('context and qualified Diamond replay at origin time', () => {
  assert.equal(diamondReplayTimestamp({ classification: 'CONTEXT', origin_time: 100, event_time: 200 }), 100)
  assert.equal(diamondReplayTimestamp({ classification: 'QUALIFIED', origin_time: 150 }), 150)
})

test('only confirmed Diamond classification is a production entry state', () => {
  assert.equal(diamondMarkerKind('CONTEXT'), 'context')
  assert.equal(diamondMarkerKind('INVALIDATED_CONTEXT'), 'context')
  assert.equal(diamondMarkerKind('QUALIFIED'), 'setup')
  assert.equal(diamondMarkerKind('CONFIRMED'), 'entry')
  assert.equal(diamondMarkerKind('AUTO_ENTRY'), 'entry')
  assert.equal(diamondIsProductionResult('CONTEXT'), false)
  assert.equal(diamondIsProductionResult('QUALIFIED'), false)
  assert.equal(diamondIsProductionResult('CONFIRMED'), true)
})

test('evidence thresholds remain conservative', () => {
  assert.equal(evidenceSampleStatus(19), 'INSUFFICIENT_SAMPLE')
  assert.equal(evidenceSampleStatus(20), 'EARLY_SAMPLE')
  assert.equal(evidenceSampleStatus(50), 'DEVELOPING_SAMPLE')
  assert.equal(evidenceSampleStatus(100), 'EVIDENCE_READY')
  assert.equal(evidenceProgress(50), 50)
  assert.equal(evidenceProgress(125), 100)
})

test('saved Diamond visibility survives a later score downgrade', () => {
  const entry = {
    classification: 'CONTEXT',
    diamond_score: 31,
    peak_diamond_score: 55,
    peak_diamond_grade: 'D',
    ever_visible: true,
  }
  assert.equal(diamondHistoricalScore(entry), 55)
  assert.equal(diamondWasVisible(entry), true)
})

test('legacy evidence restores a previously visible Diamond', () => {
  const entry = {
    classification: 'CONTEXT',
    diamond_score: 24,
    evidence_snapshot: { diamond: { diamond_score: 61 } },
  }
  assert.equal(diamondHistoricalScore(entry), 61)
  assert.equal(diamondWasVisible(entry), true)
  assert.equal(diamondWasVisible({ classification: 'CONTEXT', diamond_score: 49 }), false)
  assert.equal(diamondWasVisible({ symbol: 'XAUUSD', classification: 'CONTEXT', diamond_score: 46 }), true)
})

test('new score-only observations never become historical Diamonds', () => {
  const scoreOnly = {
    classification: 'CONTEXT',
    strategy_confirmed_origin: false,
    diamond_score: 95,
    peak_diamond_grade: 'A+',
    ever_visible: false,
  }
  assert.equal(diamondWasVisible(scoreOnly), false)
  assert.equal(diamondWasVisible({ ...scoreOnly, strategy_confirmed_origin: true }), true)
})
