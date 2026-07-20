from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from engine.session_framework import SessionFramework


class SessionFrameworkTests(unittest.TestCase):
    def setUp(self):
        self.engine = SessionFramework()

    def test_calculates_public_session_formulas_and_bullish_context(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        daily = []
        for index in range(16):
            open_value = 100 + index
            daily.append({
                "time": (start + timedelta(days=index)).isoformat(),
                "open": open_value,
                "high": open_value + 4,
                "low": open_value - 3,
                "close": open_value + 2,
            })
        session_day = start + timedelta(days=16)
        intraday = [
            {"time": session_day.isoformat(), "open": 120, "high": 122, "low": 119, "close": 121},
            {"time": (session_day + timedelta(minutes=5)).isoformat(), "open": 121, "high": 123, "low": 120, "close": 122},
        ]

        result = self.engine.calculate(daily, intraday, {"score": 60}, "MATCHED_SOURCE")

        previous = daily[-1]
        expected_mlp = (previous["open"] + previous["close"]) / 2
        expected_pivot = (previous["high"] + previous["low"] + previous["close"]) / 3
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["levels"]["op"], 120)
        self.assertEqual(result["levels"]["mlp"], expected_mlp)
        self.assertAlmostEqual(result["levels"]["pivot"], expected_pivot, places=5)
        self.assertAlmostEqual(result["levels"]["k_plus_1"], 123.5, places=5)
        self.assertAlmostEqual(result["levels"]["k_plus_2"], 127.0, places=5)
        self.assertAlmostEqual(result["levels"]["k_plus_3"], 130.5, places=5)
        self.assertAlmostEqual(result["levels"]["k_minus_3"], 109.5, places=5)
        self.assertEqual(result["stance"], "BULLISH")
        self.assertTrue(result["buy_context"])
        self.assertFalse(result["proprietary_formula_claimed"])

    def test_k_range_trend_uses_completed_candles_and_finds_next_target(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        daily = []
        for index in range(16):
            open_value = 100 + index
            daily.append({
                "time": (start + timedelta(days=index)).isoformat(),
                "open": open_value,
                "high": open_value + 4,
                "low": open_value - 3,
                "close": open_value + 2,
                "is_complete": True,
            })
        session_day = start + timedelta(days=16)
        intraday = []
        for index in range(50):
            open_value = 120 + index * 0.1
            intraday.append({
                "time": (session_day + timedelta(minutes=index * 5)).isoformat(),
                "open": open_value,
                "high": open_value + 0.14,
                "low": open_value - 0.04,
                "close": open_value + 0.1,
                "is_complete": True,
            })
        intraday.append({
            "time": (session_day + timedelta(minutes=250)).isoformat(),
            "open": 125,
            "high": 126,
            "low": 90,
            "close": 91,
            "is_complete": False,
            "is_partial": True,
        })

        result = self.engine.calculate(daily, intraday, {"score": 60}, "MATCHED_SOURCE")
        trend = result["k_trend"]

        self.assertEqual(trend["status"], "READY")
        self.assertEqual(trend["regime"], "BULLISH")
        self.assertEqual(trend["confirmation"], "CONFIRMED")
        self.assertEqual(trend["next_target_label"], "K+2")
        self.assertEqual(trend["completed_candles_used"], 50)
        self.assertTrue(trend["uses_completed_candles_only"])
        self.assertFalse(trend["trade_direction_created"])
        self.assertAlmostEqual(result["current_price"], 125.0, places=5)

    def test_waits_when_previous_daily_session_is_missing(self):
        intraday = [{
            "time": "2026-01-02T00:00:00+00:00",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100.5,
        }]
        result = self.engine.calculate([], intraday)
        self.assertEqual(result["status"], "NO_PREVIOUS_SESSION")
        self.assertEqual(result["stance"], "WAITING")


if __name__ == "__main__":
    unittest.main()
