import test from 'node:test'
import assert from 'node:assert/strict'

import { mergeDiamondHistorySnapshot } from '../src/utils/diamondHistory.js'

test('live history merge preserves older Diamond markers', () => {
  const current = {
    entries: [
      { zone_key: 'old', origin_time: 100, diamond_score: 70 },
      { zone_key: 'shared', origin_time: 200, diamond_score: 65 },
    ],
    stats: { total: 2 },
  }
  const incoming = {
    entries: [
      { zone_key: 'shared', origin_time: 200, diamond_score: 80 },
      { zone_key: 'new', origin_time: 300, diamond_score: 75 },
    ],
    stats: { total: 3 },
  }

  const result = mergeDiamondHistorySnapshot(current, incoming)

  assert.deepEqual(result.entries.map(entry => entry.zone_key), ['new', 'shared', 'old'])
  assert.equal(result.entries.find(entry => entry.zone_key === 'shared').diamond_score, 80)
  assert.equal(result.stats.total, 3)
})

test('missing live history leaves the current snapshot unchanged', () => {
  const current = { entries: [{ zone_key: 'kept', origin_time: 100 }] }
  assert.equal(mergeDiamondHistorySnapshot(current, null), current)
})
