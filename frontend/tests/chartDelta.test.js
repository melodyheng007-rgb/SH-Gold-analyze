import test from 'node:test'
import assert from 'node:assert/strict'

import { mergeCandles, mergeChartDelta } from '../src/utils/chartDelta.js'

test('live candle update replaces the forming candle without losing history', () => {
  const current = [{ time: 100, close: 10 }, { time: 200, close: 20 }]
  const result = mergeCandles(current, [{ time: 200, close: 21, high: 22 }], 2)
  assert.deepEqual(result, [{ time: 100, close: 10 }, { time: 200, close: 21, high: 22 }])
})

test('closed candle tick appends and keeps the existing chart window size', () => {
  const result = mergeCandles(
    [{ time: 100, close: 10 }, { time: 200, close: 20 }],
    [{ time: 300, close: 30 }],
    2,
  )
  assert.deepEqual(result, [{ time: 200, close: 20 }, { time: 300, close: 30 }])
})

test('chart delta preserves overlays and updates active chart candles', () => {
  const current = {
    symbol: 'XAUUSD',
    candles: [{ time: 100, close: 10 }, { time: 200, close: 20 }],
    segments: { active: [{ time: 100, close: 10 }, { time: 200, close: 20 }] },
    data_integrity: { status: 'READY' },
    gap_marker: { time: 50 },
  }
  const result = mergeChartDelta(current, {
    symbol: 'XAUUSD',
    candles: [{ time: 200, close: 22 }],
    latest_live_price: 22,
  })
  assert.equal(result.candles.at(-1).close, 22)
  assert.equal(result.segments.active.at(-1).close, 22)
  assert.deepEqual(result.data_integrity, { status: 'READY' })
  assert.deepEqual(result.gap_marker, { time: 50 })
})
