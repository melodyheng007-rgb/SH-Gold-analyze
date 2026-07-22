import test from 'node:test'
import assert from 'node:assert/strict'

import { normalizeChartCandles, normalizeChartSeries } from '../src/utils/chartSeries.js'

test('chart candles are numeric, ordered, unique, and OHLC safe', () => {
  const result = normalizeChartCandles([
    { time: 300, open: '12', high: '10', low: '15', close: '13' },
    { time: 100, open: 8, high: 9, low: 7, close: 8.5 },
    { time: 300, open: 13, high: 16, low: 12, close: 15 },
    { time: 'bad', open: 1, high: 2, low: 0, close: 1 },
  ])

  assert.deepEqual(result.map(item => item.time), [100, 300])
  assert.equal(result[1].open, 13)
  assert.equal(result[1].high, 16)
  assert.equal(result[1].low, 12)
})

test('indicator rows are deduplicated and sorted for the chart engine', () => {
  const result = normalizeChartSeries([
    { time: 200, score: 2 },
    { time: 100, score: 1 },
    { time: 200, score: 3 },
  ], item => ({ time: item.time, value: item.score, color: '#fff' }))

  assert.deepEqual(result, [
    { time: 100, value: 1, color: '#fff' },
    { time: 200, value: 3, color: '#fff' },
  ])
})
