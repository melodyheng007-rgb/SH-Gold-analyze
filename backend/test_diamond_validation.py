from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine.diamond_validation import DiamondValidationLab


class DeterministicDiamondEngine:
    def __init__(self, event_times):
        self.event_times = set(event_times)

    def calculate(self, candles, timeframe, source=None, symbol="XAUUSD"):
        current = candles[-1]
        timestamp = int(current["time"])
        zone_id = f"buy-{timestamp - 600}"
        events = []
        if timestamp in self.event_times:
            events.append({
                "id": f"entry-{timestamp}",
                "zone_id": zone_id,
                "time": timestamp,
                "available_at": timestamp,
                "entry_side": "BUY",
                "execution_entry": 100.0,
                "stop_reference": 99.0,
                "atr_14": 1.0,
                "quality_score": 92,
                "precision_grade": "A+",
                "origin_model": "SWEEP_AND_BREAK",
            })
        return {
            "status": "READY",
            "zones": [{
                "id": zone_id,
                "time": timestamp - 600,
                "entry_eligible_origin": True,
            }],
            "entry_events": events,
        }


class StrategyReplayEngine:
    def __init__(self, confirmed_times, score_only_times=()):
        self.confirmed_times = set(confirmed_times)
        self.score_only_times = set(score_only_times)

    def calculate(self, candles, timeframe, source=None, symbol="XAUUSD"):
        timestamp = int(candles[-1]["time"])
        if timestamp not in self.confirmed_times | self.score_only_times:
            return {"status": "READY", "zones": [], "entry_events": []}
        strategy_confirmed = timestamp in self.confirmed_times
        return {
            "status": "READY",
            "zones": [{
                "id": f"buy-{timestamp}",
                "time": timestamp,
                "entry_side": "BUY",
                "direction": "BULLISH",
                "line": 100.0,
                "low": 99.8,
                "high": 100.2,
                "atr_14": 1.0,
                "origin_model": "SWEEP_AND_BREAK",
                "diamond_score": 95,
                "diamond_grade": "A+",
                "entry_eligible_origin": strategy_confirmed,
                "strategy_confirmed_origin": strategy_confirmed,
                "display_as_diamond": True,
            }],
            "entry_events": [],
        }


def candles(count=270):
    rows = []
    for index in range(count):
        rows.append({
            "time": 1_700_000_000 + index * 300,
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.0,
            "is_complete": True,
            "is_partial": False,
        })
    return rows


class DiamondValidationLabTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "validation.sqlite"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_walk_forward_uses_only_later_candle_for_outcome_and_caches_run(self):
        rows = candles()
        event_time = rows[230]["time"]
        rows[231]["high"] = 102.2
        lab = DiamondValidationLab(self.db_path, DeterministicDiamondEngine({event_time}))

        result = lab.run("XAUUSD", "5M", rows, "OANDA_XAUUSD_REAL_HISTORY", horizon_bars=12)
        cached = lab.run("XAUUSD", "5M", rows, "OANDA_XAUUSD_REAL_HISTORY", horizon_bars=12)

        self.assertEqual(result["summary"]["confirmed_events"], 1)
        self.assertEqual(result["summary"]["wins"], 1)
        self.assertEqual(result["trades"][0]["resolved_at"], DiamondValidationLab._iso(rows[231]["time"]))
        self.assertFalse(result["methodology"]["look_ahead"])
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["run_id"], result["run_id"])
        self.assertEqual(result["result_integrity"]["production_results"], 1)
        self.assertTrue(result["result_integrity"]["context_excluded_from_win_loss"])

    def test_same_candle_stop_and_target_is_ambiguous_and_excluded(self):
        rows = candles()
        event_time = rows[230]["time"]
        rows[231]["high"] = 102.2
        rows[231]["low"] = 98.8
        lab = DiamondValidationLab(self.db_path, DeterministicDiamondEngine({event_time}))

        result = lab.run("XAUUSD", "5M", rows, "OANDA_XAUUSD_REAL_HISTORY", horizon_bars=12)

        self.assertEqual(result["summary"]["ambiguous"], 1)
        self.assertEqual(result["summary"]["resolved"], 0)
        self.assertIsNone(result["summary"]["win_rate"])

    def test_latest_is_not_run_until_evidence_is_generated(self):
        lab = DiamondValidationLab(self.db_path, DeterministicDiamondEngine(set()))
        self.assertEqual(lab.latest("BTCUSD", "15M")["status"], "NOT_RUN")

    def test_latest_does_not_label_a_previous_engine_run_as_current_evidence(self):
        lab = DiamondValidationLab(self.db_path, DeterministicDiamondEngine(set()))
        lab.run("XAUUSD", "5M", candles(), "OANDA_XAUUSD_REAL_HISTORY", horizon_bars=12)
        with lab.connect() as connection:
            connection.execute("UPDATE diamond_validation_runs SET engine_version = 'LEGACY_ENGINE'")

        latest = lab.latest("XAUUSD", "5M")

        self.assertEqual(latest["status"], "NOT_RUN")
        self.assertNotEqual(latest["engine_version"], "LEGACY_ENGINE")

    def test_history_replay_plots_only_strategy_confirmed_diamonds(self):
        rows = candles()
        confirmed_time = rows[230]["time"]
        score_only_time = rows[232]["time"]
        rows[231]["high"] = 101.7
        rows[231]["low"] = 99.9
        lab = DiamondValidationLab(
            self.db_path,
            StrategyReplayEngine({confirmed_time}, {score_only_time}),
        )

        result = lab.run("XAUUSD", "5M", rows, "OANDA_XAUUSD_REAL_HISTORY", horizon_bars=12)

        self.assertEqual(result["replay_summary"]["strategy_confirmed_setups"], 1)
        self.assertEqual(result["replay_summary"]["respected"], 1)
        self.assertEqual(result["replay_summary"]["failed"], 0)
        self.assertEqual(result["replay_summary"]["respect_rate"], 100.0)
        self.assertEqual(len(result["replay_zones"]), 1)
        self.assertEqual(result["replay_zones"][0]["detected_time"], confirmed_time)
        self.assertTrue(result["replay_zones"][0]["strategy_confirmed_origin"])
        self.assertFalse(result["replay_zones"][0]["score_creates_diamond"])

    def test_failure_diagnostics_preserve_terminal_zone_reasons(self):
        diagnostics = DiamondValidationLab._failure_diagnostics({
            "buy-1": {
                "zone_id": "buy-1",
                "controlled_retest": True,
                "rejection": True,
                "follow_through": False,
                "risk_quality": False,
                "blocker": "ZONE_INVALIDATED_ON_FOLLOW_THROUGH",
            },
            "sell-2": {
                "zone_id": "sell-2",
                "controlled_retest": False,
                "rejection": False,
                "follow_through": False,
                "risk_quality": False,
                "blocker": "NO_RETEST_IN_WINDOW",
            },
        }, confirmed_events=0)

        self.assertEqual(diagnostics["qualified_origins_traced"], 2)
        self.assertEqual(diagnostics["conversion_percent"], 0.0)
        self.assertEqual(diagnostics["final_blockers"][0]["id"], "ZONE_INVALIDATED_ON_FOLLOW_THROUGH")
        self.assertIn("Buy/Sell Diamond Zones remain visible", diagnostics["interpretation"])


if __name__ == "__main__":
    unittest.main()
