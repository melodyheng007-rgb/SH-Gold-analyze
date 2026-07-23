import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createChartSnapshotRecord,
  isIndicatorSnapshotReady,
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
  const result = snapshot(40, {
    diamond_history: {
      status: 'OK',
      entries: [{ zone_key: 'XAUUSD:5M:zone-1', timeframe: '5M', entry_side: 'BUY' }],
    },
  })
  assert.equal(writeChartSnapshot(storage, result, 'XAUUSD', '5M', 10_000), true)
  const restored = readChartSnapshot(storage, 'XAUUSD', '5M', { now: 11_000 })
  assert.equal(restored.chart_data.candles.length, 40)
  assert.equal(restored.panels.indicator_panels.indicator_snapshot.status, 'READY')
  assert.equal(restored.diamond_history.entries[0].zone_key, 'XAUUSD:5M:zone-1')
})

test('rejects tick-sized, unmatched, stale, and wrong-view snapshots', () => {
  assert.equal(createChartSnapshotRecord(snapshot(12), 'XAUUSD', '5M', 10_000), null)
  assert.equal(createChartSnapshotRecord(snapshot(40, { provider_alignment: { matched: false } }), 'XAUUSD', '5M', 10_000), null)

  const storage = memoryStorage()
  writeChartSnapshot(storage, snapshot(), 'XAUUSD', '5M', 10_000)
  assert.equal(readChartSnapshot(storage, 'BTCUSD', '5M', { now: 11_000 }), null)
  assert.equal(readChartSnapshot(storage, 'XAUUSD', '5M', { now: 20_001, maxAgeMs: 10_000 }), null)
})

test('cached indicator readiness is independent from full analysis warmup', () => {
  assert.equal(isIndicatorSnapshotReady(snapshot().panels), true)
  assert.equal(isIndicatorSnapshotReady({ readiness: { status: 'READY' } }), true)
  assert.equal(isIndicatorSnapshotReady({
    status: 'WAITING_FOR_HISTORY',
    indicator_panels: { indicator_snapshot: { status: 'WAITING' } },
  }), false)
})

test('keeps warm snapshots for more than one market view', () => {
  const storage = memoryStorage()
  const xau = snapshot()
  const btc = snapshot(40, {
    symbol: 'BTCUSD',
    timeframe: '1H',
    chart_data: {
      ...snapshot().chart_data,
      symbol: 'BTCUSD',
      timeframe: '1H',
    },
  })
  assert.equal(writeChartSnapshot(storage, xau, 'XAUUSD', '5M', 10_000), true)
  assert.equal(writeChartSnapshot(storage, btc, 'BTCUSD', '1H', 10_100), true)
  assert.equal(readChartSnapshot(storage, 'XAUUSD', '5M', { now: 11_000 }).symbol, 'XAUUSD')
  assert.equal(readChartSnapshot(storage, 'BTCUSD', '1H', { now: 11_000 }).symbol, 'BTCUSD')
})
