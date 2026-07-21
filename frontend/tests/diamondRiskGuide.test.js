import test from 'node:test'
import assert from 'node:assert/strict'

import { deriveDiamondRiskGuide } from '../src/utils/diamondRiskGuide.js'

const framework = {
  levels: {
    k_plus_2: 120,
    k_plus_1: 110,
    op: 100,
    mlp: 98,
    pivot: 95,
    k_minus_1: 90,
  },
}

test('buy Diamond uses engine invalidation and the next higher structural level', () => {
  const guide = deriveDiamondRiskGuide(
    { entry_side: 'BUY', line: 102 },
    { invalidation_level: 99 },
    framework,
    104,
  )

  assert.equal(guide.invalidation, 99)
  assert.equal(guide.targetLabel, 'K+1')
  assert.equal(guide.target, 110)
  assert.equal(guide.riskReward, 2.67)
  assert.equal(guide.ready, true)
})

test('sell Diamond uses engine invalidation and the next lower structural level', () => {
  const guide = deriveDiamondRiskGuide(
    { direction: 'BEARISH', line: 108 },
    { invalidation_level: 112 },
    framework,
    107,
  )

  assert.equal(guide.invalidation, 112)
  assert.equal(guide.targetLabel, 'OP')
  assert.equal(guide.target, 100)
  assert.equal(guide.riskReward, 2)
  assert.equal(guide.ready, true)
})

test('risk guide never invents an invalidation level', () => {
  const guide = deriveDiamondRiskGuide(
    { entry_side: 'BUY', line: 102 },
    {},
    framework,
    104,
  )

  assert.equal(guide.invalidation, null)
  assert.equal(guide.ready, false)
})

test('risk guide skips a structural objective already passed by live price', () => {
  const guide = deriveDiamondRiskGuide(
    { entry_side: 'BUY', line: 102 },
    { invalidation_level: 99 },
    framework,
    112,
  )

  assert.equal(guide.targetLabel, 'K+2')
  assert.equal(guide.target, 120)
})
