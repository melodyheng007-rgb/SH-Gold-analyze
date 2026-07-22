from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine.diamond_history import DiamondHistory
from engine.setup_tracker import SetupTracker


def diamond_analysis(with_event: bool = False) -> dict:
    zone = {
        "id": "buy-1000",
        "time": 1000,
        "direction": "BULLISH",
        "entry_side": "BUY",
        "line": 100.0,
        "low": 99.8,
        "high": 100.2,
        "atr_14": 1.0,
        "origin_model": "SWEEP_AND_BREAK",
        "origin_quality_score": 92,
        "origin_quality_grade": "A+",
        "entry_eligible_origin": True,
        "strategy_confirmed_origin": True,
        "display_as_diamond": True,
        "lifecycle": "FRESH",
        "execution_quality": "READY",
        "rejection_status": "STRONG",
        "zone_strength_score": 91,
    }
    events = []
    if with_event:
        events.append({
            "id": "entry-buy-1000-1200",
            "zone_id": "buy-1000",
            "time": 1200,
            "entry_side": "BUY",
            "execution_entry": 100.5,
            "stop_reference": 99.8,
            "atr_14": 1.0,
            "quality_score": 93,
            "precision_grade": "A+",
        })
    return {
        "symbol": "XAUUSD",
        "trading_style": "SCALPING",
        "analysis_data_source": "OANDA_XAUUSD_REAL_HISTORY",
        "trust_gate": {"status": "TRUSTED", "trusted": True},
        "feed_reconciliation": {"status": "MATCHED_RECONCILED", "latest_closed_time": 1200 if with_event else 1000},
        "market_regime": {
            "regime": "TRENDING_BULLISH",
            "execution_gate": "OPEN",
            "strength": 78,
            "metrics": {"range_location": "LOWER_EDGE", "volatility_ratio": 0.9},
        },
        "decision_quality": {
            "status": "TRACKABLE_SETUP" if with_event else "WAITING_CONFIRMATION",
            "score": 88 if with_event else 62,
            "grade": "A" if with_event else "C",
            "score_ceiling": 100 if with_event else 64,
            "current_event": with_event,
            "top_blockers": [],
        },
        "news_intelligence": {"risk_level": "CLEAR", "execution_gate": "OPEN"},
        "session_framework": {
            "stance": "BULLISH",
            "position": "ABOVE_OP_AND_MLP",
            "confluence_score": 72,
            "k_trend": {"regime": "BULLISH", "score": 80},
        },
        "key_zones": {
            "status": "READY",
            "symbol": "XAUUSD",
            "timeframe": "5M",
            "source": "OANDA_XAUUSD_REAL_HISTORY",
            "feed_matched": True,
            "zones": [zone],
            "entry_events": events,
        },
    }


class DiamondHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "journal.sqlite"
        SetupTracker(self.db_path)
        self.history = DiamondHistory(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_upgrades_qualified_zone_to_confirmed_without_duplicate(self):
        self.assertEqual(self.history.record(diamond_analysis(False), "5M"), 1)
        first = self.history.list("XAUUSD", 10)[0]
        self.assertEqual(first["classification"], "QUALIFIED")
        self.assertEqual(first["verification_status"], "MONITORING")
        self.assertEqual(first["strategy"], "SH_DIAMOND_ZONE_V6_PRECISION")
        self.assertEqual(first["engine_version"], "DIAMOND_V6.1")
        self.assertEqual(first["diamond_score"], 91)
        self.assertEqual(first["diamond_grade"], "A+")
        self.assertEqual(first["display_classification"], "QUALIFIED")
        self.assertEqual(len(first["configuration_fingerprint"]), 16)

        self.assertEqual(self.history.record(diamond_analysis(True), "5M"), 1)
        entries = self.history.list("XAUUSD", 10)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["classification"], "CONFIRMED")
        self.assertEqual(entries[0]["diamond_score"], 93)
        self.assertEqual(entries[0]["diamond_grade"], "A+")
        self.assertEqual(entries[0]["event_id"], "entry-buy-1000-1200")
        self.assertEqual(entries[0]["evidence_snapshot"]["schema"], "DIAMOND_EVIDENCE_V1")
        self.assertEqual(entries[0]["evidence_snapshot"]["regime"]["name"], "TRENDING_BULLISH")
        self.assertEqual(entries[0]["evidence_snapshot"]["decision"]["score"], 88)
        self.assertEqual(
            [item["stage"] for item in entries[0]["lifecycle_events"]],
            ["DETECTED", "QUALIFIED", "CONFIRMED"],
        )

    def test_verifies_confirmed_entry_on_later_completed_candle(self):
        self.history.record(diamond_analysis(True), "5M")
        updates = self.history.reconcile("XAUUSD", {
            "5M": [
                {"time": 1300, "open": 100.6, "high": 102.1, "low": 100.3, "close": 101.9, "is_complete": True},
            ],
        })

        entry = self.history.list("XAUUSD", 10)[0]
        stats = self.history.stats("XAUUSD")
        self.assertEqual(updates, 1)
        self.assertEqual(entry["verification_status"], "WON")
        self.assertEqual(entry["outcome_r"], 1.8)
        self.assertEqual(stats["won"], 1)
        self.assertEqual(stats["verified_accuracy"], 100.0)
        calibration = self.history.calibration("XAUUSD")
        self.assertEqual(calibration["overall"]["resolved"], 1)
        self.assertEqual(calibration["overall"]["expectancy_r"], 1.8)
        self.assertEqual(calibration["profiles"][0]["style"], "SCALPING")
        self.assertEqual(calibration["profiles"][0]["sample_status"], "INSUFFICIENT_SAMPLE")

        later = [
            {
                "time": 1300 + index * 300,
                "open": 101.9,
                "high": 102.1,
                "low": 100.3,
                "close": 101.9,
                "is_complete": True,
            }
            for index in range(20)
        ]
        self.history.reconcile("XAUUSD", {"5M": later})
        matured = self.history.list("XAUUSD", 10)[0]
        self.assertTrue(matured["forward_returns"]["horizons"]["20"]["available"])

    def test_context_zone_is_never_counted_as_a_trade(self):
        analysis = diamond_analysis(False)
        zone = analysis["key_zones"]["zones"][0]
        zone["entry_eligible_origin"] = False
        zone["strategy_confirmed_origin"] = False
        zone["display_as_diamond"] = False
        zone["origin_model"] = "EXPANSION_CONTEXT"
        self.history.record(analysis, "5M")

        entry = self.history.list("XAUUSD", 10)[0]
        self.assertEqual(entry["classification"], "CONTEXT")
        self.assertEqual(entry["verification_status"], "NOT_AN_ENTRY")
        self.assertEqual(self.history.stats("XAUUSD")["confirmed"], 0)

    def test_score_only_context_is_saved_for_audit_but_never_marked_visible(self):
        analysis = diamond_analysis(False)
        zone = analysis["key_zones"]["zones"][0]
        zone.update(
            strategy_confirmed_origin=False,
            display_as_diamond=False,
            entry_eligible_origin=False,
            diamond_score=99,
            diamond_grade="A+",
        )

        self.history.record(analysis, "5M")
        entry = self.history.list("XAUUSD", 10)[0]

        self.assertEqual(entry["classification"], "CONTEXT")
        self.assertFalse(entry["strategy_confirmed_origin"])
        self.assertFalse(entry["ever_visible"])

    def test_invalidated_qualified_zone_is_exposed_as_rejected_audit_context(self):
        self.history.record(diamond_analysis(False), "5M")
        self.history.reconcile("XAUUSD", {
            "5M": [
                {"time": 1300, "open": 99.7, "high": 99.9, "low": 99.4, "close": 99.5, "is_complete": True},
                {"time": 1600, "open": 99.5, "high": 99.7, "low": 99.2, "close": 99.4, "is_complete": True},
            ],
        })

        entry = self.history.list("XAUUSD", 10)[0]
        stats = self.history.stats("XAUUSD")
        self.assertEqual(entry["verification_status"], "INVALIDATED_NO_ENTRY")
        self.assertEqual(entry["display_classification"], "INVALIDATED_CONTEXT")
        self.assertEqual(entry["grade_status"], "REJECTED_CONTEXT")
        self.assertIsNone(entry["diamond_grade"])
        self.assertEqual(entry["diamond_score"], 49)
        self.assertTrue(entry["ever_visible"])
        self.assertEqual(entry["peak_diamond_score"], 91)
        self.assertEqual(entry["peak_diamond_grade"], "A+")
        self.assertEqual(stats["qualified"], 0)
        self.assertEqual(stats["context"], 1)
        self.assertEqual(stats["grade_distribution"]["D"], 0)
        self.assertEqual(stats["rejected_observations"], 1)

    def test_grade_d_is_watch_only_and_grade_c_can_qualify(self):
        watch = diamond_analysis(False)
        watch_zone = watch["key_zones"]["zones"][0]
        watch_zone.update(diamond_score=55, diamond_grade="D")
        self.history.record(watch, "5M")
        watch_entry = self.history.list("XAUUSD", 10)[0]

        self.assertEqual(watch_entry["diamond_grade"], "D")
        self.assertEqual(watch_entry["classification"], "CONTEXT")

        qualified = diamond_analysis(False)
        qualified_zone = qualified["key_zones"]["zones"][0]
        qualified_zone.update(id="buy-2000", time=2000, diamond_score=60, diamond_grade="C")
        self.history.record(qualified, "5M")
        qualified_entry = next(item for item in self.history.list("XAUUSD", 10) if item["zone_id"] == "buy-2000")

        self.assertEqual(qualified_entry["diamond_grade"], "C")
        self.assertEqual(qualified_entry["classification"], "QUALIFIED")

    def test_visible_context_keeps_peak_score_after_later_downgrade(self):
        analysis = diamond_analysis(False)
        zone = analysis["key_zones"]["zones"][0]
        zone.update(
            entry_eligible_origin=False,
            diamond_score=46,
            diamond_grade="D",
            display_as_diamond=True,
        )
        self.history.record(analysis, "5M")

        zone.update(
            diamond_score=31,
            diamond_grade=None,
            display_as_diamond=False,
        )
        self.history.record(analysis, "5M")
        entry = self.history.list("XAUUSD", 10)[0]

        self.assertEqual(entry["classification"], "CONTEXT")
        self.assertEqual(entry["diamond_score"], 31)
        self.assertTrue(entry["ever_visible"])
        self.assertEqual(entry["peak_diamond_score"], 46)
        self.assertEqual(entry["peak_diamond_grade"], "D")

    def test_default_history_never_prunes_older_unique_zones(self):
        analysis = diamond_analysis(False)
        template = analysis["key_zones"]["zones"][0]
        analysis["key_zones"]["zones"] = [
            {
                **template,
                "id": f"buy-{index}",
                "time": 1000 + index * 300,
                "line": 100.0 + index * 0.01,
                "low": 99.8 + index * 0.01,
                "high": 100.2 + index * 0.01,
            }
            for index in range(125)
        ]

        self.assertEqual(self.history.record(analysis, "5M"), 125)
        self.assertEqual(self.history.stats("XAUUSD")["total"], 125)
        self.assertEqual(len(self.history.list("XAUUSD", 200)), 125)

    def test_forward_returns_mature_only_after_required_closed_candles(self):
        self.history.record(diamond_analysis(True), "5M")
        candles = []
        for index in range(20):
            close = 100.5 + (index + 1) * 0.04
            candles.append({
                "time": 1300 + index * 300,
                "open": close - 0.02,
                "high": close + 0.08,
                "low": close - 0.08,
                "close": close,
                "is_complete": True,
            })

        self.history.reconcile("XAUUSD", {"5M": candles})
        entry = self.history.list("XAUUSD", 10)[0]
        horizons = entry["forward_returns"]["horizons"]

        self.assertTrue(horizons["5"]["available"])
        self.assertTrue(horizons["10"]["available"])
        self.assertTrue(horizons["20"]["available"])
        self.assertGreater(horizons["20"]["directional_pct"], horizons["5"]["directional_pct"])
        self.assertTrue(entry["forward_returns"]["uses_completed_candles_only"])


if __name__ == "__main__":
    unittest.main()
