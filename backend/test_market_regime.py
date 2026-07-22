import math
import unittest

from engine.market_regime import MarketRegimeEngine


def candles_from_closes(closes, incomplete_last=False):
    rows = []
    for index, close in enumerate(closes):
        previous = closes[index - 1] if index else close
        opened = previous
        padding = max(0.2, abs(close - opened) * 0.2)
        rows.append({
            "time": 1_700_000_000 + index * 300,
            "open": opened,
            "high": max(opened, close) + padding,
            "low": min(opened, close) - padding,
            "close": close,
            "is_complete": not (incomplete_last and index == len(closes) - 1),
        })
    return rows


class MarketRegimeEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = MarketRegimeEngine()

    def test_bullish_trend_opens_buy_and_blocks_sell(self):
        rows = candles_from_closes([100.0 + index * 0.35 for index in range(100)])

        buy = self.engine.evaluate("XAUUSD", "15M", rows, "BUY")
        sell = self.engine.evaluate("XAUUSD", "15M", rows, "SELL")

        self.assertEqual(buy["regime"], "TRENDING_BULLISH")
        self.assertEqual(buy["execution_gate"], "OPEN")
        self.assertTrue(buy["allows_new_entry"])
        self.assertEqual(sell["execution_gate"], "BLOCK_DIRECTION_CONFLICT")
        self.assertFalse(sell["allows_new_entry"])

    def test_large_closed_candle_creates_volatility_lock(self):
        closes = [100.0 + math.sin(index / 5.0) * 0.3 for index in range(99)] + [108.0]
        rows = candles_from_closes(closes)

        result = self.engine.evaluate("BTCUSD", "5M", rows, "BUY")

        self.assertEqual(result["regime"], "VOLATILITY_SHOCK")
        self.assertEqual(result["execution_gate"], "BLOCK_VOLATILITY")
        self.assertFalse(result["allows_new_entry"])

    def test_directional_overextension_blocks_buy_high(self):
        rows = candles_from_closes([100.0 + index for index in range(100)])

        result = self.engine.evaluate("XAUUSD", "15M", rows, "BUY")

        self.assertEqual(result["regime"], "TRENDING_BULLISH")
        self.assertEqual(result["execution_gate"], "WAIT_OVEREXTENDED")
        self.assertEqual(result["location_guard"]["side"], "BUY_HIGH")
        self.assertGreater(result["metrics"]["directional_extension_atr"], 4.75)
        self.assertFalse(result["allows_new_entry"])

    def test_range_requires_directional_outer_edge(self):
        rows = candles_from_closes([100.0 + math.sin(index / 2.0) for index in range(100)])

        result = self.engine.evaluate("XAUUSD", "15M", rows, "BUY")

        self.assertEqual(result["regime"], "RANGE")
        self.assertIn(result["execution_gate"], {"WAIT_RANGE_EDGE", "OPEN_RANGE_EDGE"})
        if result["metrics"]["range_location"] == "MID_RANGE":
            self.assertEqual(result["execution_gate"], "WAIT_RANGE_EDGE")

    def test_incomplete_forming_candle_is_excluded(self):
        base = [100.0 + index * 0.25 for index in range(100)]
        rows = candles_from_closes(base + [80.0], incomplete_last=True)

        result = self.engine.evaluate("XAUUSD", "15M", rows, "BUY")

        self.assertEqual(result["completed_candles"], 100)
        self.assertEqual(result["regime"], "TRENDING_BULLISH")
        self.assertEqual(result["execution_gate"], "OPEN")
        self.assertTrue(result["uses_completed_candles_only"])

    def test_v3_exposes_strength_and_pullback_state(self):
        rows = candles_from_closes([100.0 + index * 0.35 for index in range(100)])

        result = self.engine.evaluate("XAUUSD", "5M", rows, "BUY")

        self.assertIn(result["strength_band"], {"STRONG", "ESTABLISHED", "DEVELOPING", "WEAK"})
        self.assertIn(result["pullback_state"], {"EXTENDED", "PULLBACK_READY", "TREND_CONTINUATION"})
        self.assertTrue(result["changes_signal_logic"])


if __name__ == "__main__":
    unittest.main()
