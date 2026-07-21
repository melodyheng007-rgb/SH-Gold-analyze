import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createChartSnapshotRecord,
  readChartSnapshot,
  writeChartSnapshot,
} from '../src/utils/chartSnapshotCache.js'

function snapshot(count = 40, overrides = {}) {
  const candles = Array.from({ length: count }, (_, index) => ({
    time: 1_700_000_000 + index * 300,
    open: 2000 + index,
    high: 2002 + index,
    low: 1999 + index,
    close: 2001 + index,
  }))
  return {
    symbol: 'XAUUSD',
    timeframe: '5M',
    chart_data: {
      symbol: 'XAUUSD',
      timeframe: '5M',
      candles,
      segments: { active: candles },
      data_integrity: { chart_source: 'OANDA_XAUUSD_REAL_HISTORY' },
    },
    panels: { indicator_panels: { indicator_snapshot: { status: 'READY' } } },
    provider_alignment: { matched: true },
    ...overrides,
  }
}

function memoryStorage() {
  const values = new Map()
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  }
}

test('stores and restores matched full chart history for the same view', () => {
  const storage = memoryStorage()
  const result = snapshot()
  assert.equal(writeChartSnapshot(storage, result, 'XAUUSD', '5M', 10_000), true)
  const restored = readChartSnapshot(storage, 'XAUUSD', '5M', { now: 11_000 })
  assert.equal(restored.chart_data.candles.length, 40)
  assert.equal(restored.panels.indicator_panels.indicator_snapshot.status, 'READY')
})

test('rejects tick-sized, unmatched, stale, and wrong-view snapshots', () => {
  assert.equal(createChartSnapshotRecord(snapshot(12), 'XAUUSD', '5M', 10_000), null)
  assert.equal(createChartSnapshotRecord(snapshot(40, { provider_alignment: { matched: false } }), 'XAUUSD', '5M', 10_000), null)

  const storage = memoryStorage()
  writeChartSnapshot(storage, snapshot(), 'XAUUSD', '5M', 10_000)
  assert.equal(readChartSnapshot(storage, 'BTCUSD', '5M', { now: 11_000 }), null)
  assert.equal(readChartSnapshot(storage, 'XAUUSD', '5M', { now: 20_001, maxAgeMs: 10_000 }), null)
})
