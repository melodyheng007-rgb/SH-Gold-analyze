import math
import unittest

from engine.smt_model import SMTModelEngine


def candles(mode="normal", size=80, scale=1.0):
    rows = []
    previous = 100.0 * scale
    for index in range(size):
        base = (100.0 + index * 0.08 + math.sin(index / 4.0) * 0.25) * scale
        if index >= size - 10:
            step = index - (size - 11)
            if mode == "up":
                base += step * 0.75 * scale
            elif mode == "down":
                base -= step * 0.75 * scale
            elif mode == "flat":
                base = (100.0 + (size - 11) * 0.08) * scale
        open_value = previous
        close = base
        high = max(open_value, close) + 0.22 * scale
        low = min(open_value, close) - 0.22 * scale
        rows.append({
            "time": 1_720_000_000 + index * 300,
            "open": open_value,
            "high": high,
            "low": low,
            "close": close,
            "is_complete": True,
        })
        previous = close
    return rows


class SMTModelEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = SMTModelEngine()

    def snapshot(self, rows):
        return {
            "status": "READY",
            "companion_symbol": "XAGUSD",
            "provider_symbol": "OANDA:XAGUSD",
            "source_status": "OANDA_XAGUSD_MATCHED",
            "candles": rows,
        }

    def test_higher_high_failure_is_bearish_divergence(self):
        result = self.engine.evaluate("XAUUSD", "5M", candles("up"), self.snapshot(candles("flat", scale=0.5)))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["state"], "BEARISH_DIVERGENCE")
        self.assertEqual(result["direction"], "SELL")
        self.assertGreaterEqual(result["confidence"], 66)
        self.assertFalse(result["creates_diamond_zone"])

    def test_lower_low_failure_is_bullish_divergence(self):
        result = self.engine.evaluate("XAUUSD", "5M", candles("down"), self.snapshot(candles("flat", scale=0.5)))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["state"], "BULLISH_DIVERGENCE")
        self.assertEqual(result["direction"], "BUY")

    def test_unavailable_companion_is_neutral_and_never_creates_zone(self):
        result = self.engine.evaluate(
            "XAUUSD",
            "5M",
            candles("up"),
            {"status": "UNAVAILABLE", "reason": "No verified feed."},
        )
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["execution_gate"], "NEUTRAL")
        self.assertEqual(result["direction"], "WAIT")
        self.assertFalse(result["creates_diamond_zone"])

    def test_strong_opposite_divergence_blocks_entry_but_keeps_zone(self):
        zones = {
            "zones": [{"id": "sell", "entry_side": "SELL"}, {"id": "buy", "entry_side": "BUY"}],
            "primary_zone": {"id": "buy", "entry_side": "BUY"},
        }
        model = {
            "status": "READY",
            "state": "BEARISH_DIVERGENCE",
            "direction": "SELL",
            "confidence": 80,
            "execution_gate": "DIVERGENCE_READY",
            "companion_symbol": "XAGUSD",
        }
        self.engine.apply_to_key_zones(zones, model)
        self.assertEqual(len(zones["zones"]), 2)
        self.assertEqual(zones["primary_zone"]["smt_execution_gate"], "BLOCK_CONFLICT")
        self.assertEqual(zones["zones"][0]["smt_execution_gate"], "CONFIRM")


if __name__ == "__main__":
    unittest.main()
