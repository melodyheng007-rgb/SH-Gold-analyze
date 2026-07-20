import tempfile
import unittest
from pathlib import Path

from engine.strategy_governance import CHALLENGER_VERSION, StrategyGovernance


def candle(timestamp, open_=100.0, high=101.0, low=99.0, close=100.5):
    return {
        "time": timestamp,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "is_complete": True,
    }


def result(version, event=None, gate="qualified_origins"):
    events = [event] if event else []
    return {
        "strategy": f"SH_{version}",
        "profile": f"{version}_15M",
        "status": "READY",
        "engine_version": version,
        "entry_events": events,
        "latest_entry_event": event,
        "signal_frequency": {
            "context_zones": 2,
            "qualified_origins": 1,
            "confirmed_entries": len(events),
        },
        "gate_funnel": {
            "current_gate": "confirmed_entries" if event else gate,
            "next_gate": None if event else "controlled_retest",
            "top_blockers": [],
        },
    }


class StrategyGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.lab = StrategyGovernance(Path(self.temp.name) / "governance.sqlite")

    def tearDown(self):
        self.temp.cleanup()

    def test_records_and_resolves_shadow_event_only_on_later_candle(self):
        event = {
            "id": "shadow-buy-300",
            "time": 300,
            "available_at": 300,
            "entry_side": "BUY",
            "execution_entry": 100.0,
            "stop_reference": 99.0,
            "atr_14": 2.0,
        }
        first = self.lab.record(
            "XAUUSD",
            "15M",
            [candle(100), candle(200), candle(300)],
            "OANDA_XAUUSD_REAL_HISTORY",
            True,
            result("DIAMOND_V6.1"),
            result(CHALLENGER_VERSION, event),
        )
        self.assertEqual(first["challenger"]["summary"]["monitoring"], 1)
        self.assertEqual(first["challenger"]["summary"]["resolved"], 0)

        second = self.lab.record(
            "XAUUSD",
            "15M",
            [candle(100), candle(200), candle(300), candle(400, 100.5, 102.5, 99.5, 102.2)],
            "OANDA_XAUUSD_REAL_HISTORY",
            True,
            result("DIAMOND_V6.1"),
            result(CHALLENGER_VERSION, event),
        )
        self.assertEqual(second["challenger"]["summary"]["resolved"], 1)
        self.assertEqual(second["challenger"]["summary"]["wins"], 1)
        self.assertEqual(second["challenger"]["summary"]["expectancy_r"], 1.8)
        self.assertEqual(second["promotion_gate"]["status"], "BLOCKED")
        self.assertFalse(second["promotion_gate"]["automatic_promotion"])

    def test_unmatched_feed_records_observation_but_not_trade(self):
        event = {
            "id": "untrusted",
            "time": 300,
            "available_at": 300,
            "entry_side": "SELL",
            "execution_entry": 100.0,
            "stop_reference": 101.0,
            "atr_14": 2.0,
        }
        snapshot = self.lab.record(
            "BTCUSD",
            "15M",
            [candle(100), candle(200), candle(300)],
            "FALLBACK",
            False,
            result("DIAMOND_V6.1"),
            result(CHALLENGER_VERSION, event),
        )
        self.assertEqual(snapshot["challenger"]["observations"], 1)
        self.assertEqual(snapshot["challenger"]["matched_observations"], 0)
        self.assertEqual(snapshot["challenger"]["summary"]["events"], 0)
        self.assertFalse(snapshot["feed_matched"])


if __name__ == "__main__":
    unittest.main()
