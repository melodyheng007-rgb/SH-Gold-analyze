import test from 'node:test'
import assert from 'node:assert/strict'

import {
  signalScore,
  signalTier,
} from '../src/utils/signalRadar.js'

test('signal tiers never promote a score-only context origin', () => {
  assert.equal(signalTier({ diamond_score: 82, entry_eligible_origin: false }), 'EARLY')
  assert.equal(signalTier({ diamond_score: 64, entry_eligible_origin: true }), 'QUALIFIED')
  assert.equal(signalTier({ marker_kind: 'entry' }), 'CONFIRMED')
})

test('Diamond scores stay inside the public 0-100 grade range', () => {
  assert.equal(signalScore({ diamond_score: 55.6 }), 56)
  assert.equal(signalScore({ diamond_score: 140 }), 100)
  assert.equal(signalScore({ diamond_score: -8 }), 0)
})
