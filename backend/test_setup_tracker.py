from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.setup_tracker import SetupTracker


def trusted_candidate(direction: str = "BUY"):
    buy = direction == "BUY"
    return {
        "symbol": "BTCUSD",
        "analysis_data_source": "BINANCE_BTCUSDT_REAL_HISTORY",
        "trust_gate": {"status": "TRUSTED", "trusted": True},
        "signal": {"score": 72, "execution_allowed": False},
        "trade_plan": {
            "status": "CANDIDATE",
            "direction": direction,
            "order_type": "LIMIT",
            "entry_price": 100,
            "stop_loss": 98 if buy else 102,
            "take_profit_levels": [104 if buy else 96],
        },
    }


def trusted_diamond_entry():
    analysis = trusted_candidate()
    analysis["signal"].update({"score": 91, "execution_allowed": True})
    analysis["trade_plan"].update({
        "status": "ACTIONABLE",
        "order_type": "MARKET",
        "position_type": "CONFIRMED_ENTRY",
        "setup_type": "Diamond V6 Precision Entry",
        "auto_entry_armed": True,
    })
    analysis["diamond_auto_entry"] = {
        "status": "AUTO_ARMED",
        "entry_model": "CONFIRMED_FOLLOW_THROUGH_CLOSE",
        "precision_grade": "A+",
    }
    return analysis


class SetupTrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tracker = SetupTracker(Path(self.temp_dir.name) / "tracker.sqlite")

    def tearDown(self):
        self.temp_dir.cleanup()

    def future_candle(self, setup, minutes: int, **prices):
        start = datetime.fromisoformat(setup["evaluation_start_at"])
        return {
            "time": (start + timedelta(minutes=minutes)).isoformat(),
            "open": prices.get("open", 101),
            "high": prices.get("high", 101.5),
            "low": prices.get("low", 99.5),
            "close": prices.get("close", 100.5),
        }

    def test_registers_trusted_setup_and_deduplicates_active_plan(self):
        first = self.tracker.register(trusted_candidate(), "5M", 1)
        second = self.tracker.register(trusted_candidate(), "5M", 2)

        self.assertTrue(first["created"])
        self.assertEqual(first["lifecycle_status"], "WAITING_ENTRY")
        self.assertFalse(second["created"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.tracker.stats("BTCUSD")["total"], 1)

    def test_untrusted_or_invalid_geometry_is_not_tracked(self):
        analysis = trusted_candidate()
        analysis["trust_gate"] = {"status": "RESEARCH_ONLY", "trusted": False}
        self.assertIsNone(self.tracker.register(analysis, "5M", 1))

        invalid = trusted_candidate()
        invalid["trade_plan"]["stop_loss"] = 105
        self.assertIsNone(self.tracker.register(invalid, "5M", 2))

    def test_entry_then_target_is_verified_as_win(self):
        setup = self.tracker.register(trusted_candidate(), "5M", 1)
        opened = self.tracker.evaluate(setup["id"], [
            self.future_candle(setup, 0, open=101, high=101.5, low=99.5, close=100.4),
        ])
        won = self.tracker.evaluate(setup["id"], [
            self.future_candle(setup, 5, open=100.5, high=104.5, low=100.2, close=104.1),
        ])

        self.assertEqual(opened["lifecycle_status"], "OPEN")
        self.assertEqual(won["lifecycle_status"], "WON")
        self.assertEqual(won["outcome_r"], 2.0)
        self.assertEqual(self.tracker.stats("BTCUSD")["verified_win_rate"], 100.0)

    def test_same_candle_entry_and_exit_is_ambiguous(self):
        setup = self.tracker.register(trusted_candidate(), "5M", 1)
        result = self.tracker.evaluate(setup["id"], [
            self.future_candle(setup, 0, open=101, high=104.5, low=97.5, close=100),
        ])

        self.assertEqual(result["lifecycle_status"], "AMBIGUOUS")
        self.assertIsNone(result["outcome_r"])
        self.assertIn("intrabar order is unknown", result["note"])

    def test_diamond_performance_is_separate_from_generic_candidates(self):
        generic = self.tracker.register(trusted_candidate(), "5M", 1)
        diamond = self.tracker.register(trusted_diamond_entry(), "5M", 2)

        self.assertEqual(generic["setup_model"], "INSTITUTIONAL_CANDIDATE")
        self.assertEqual(diamond["setup_model"], "DIAMOND_V6_AUTO")
        self.assertEqual(diamond["quality_tier"], "A+")
        self.assertEqual(self.tracker.stats("BTCUSD")["total"], 2)
        diamond_stats = self.tracker.stats("BTCUSD", "DIAMOND_V6_AUTO")
        self.assertEqual(diamond_stats["total"], 1)
        self.assertEqual(diamond_stats["setup_model"], "DIAMOND_V6_AUTO")
        self.assertEqual(len(self.tracker.list("BTCUSD", 20, "DIAMOND_V6_AUTO")), 1)


if __name__ == "__main__":
    unittest.main()
