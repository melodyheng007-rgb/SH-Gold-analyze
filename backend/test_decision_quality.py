import unittest

from engine.decision_quality import DecisionQualityEngine


def feed(trusted=True, latest=1000):
    return {
        "status": "MATCHED_RECONCILED" if trusted else "SOURCE_MISMATCH",
        "trusted": trusted,
        "latest_closed_time": latest,
        "checks": [
            {"id": key, "pass": trusted}
            for key in ("source", "single_source", "ohlc", "duplicates", "gaps", "freshness", "close_drift")
        ],
    }


def validation(resolved=100):
    return {
        "status": "READY",
        "summary": {
            "resolved": resolved,
            "expectancy_r": 0.22,
            "profit_factor": 1.4,
            "max_drawdown_r": 4.0,
        },
        "sample_confidence": {"status": "EVIDENCE_READY" if resolved >= 100 else "EARLY_SAMPLE"},
    }


def ready_analysis(event_time=1000):
    return {
        "symbol": "XAUUSD",
        "bias": "Bullish",
        "feed_reconciliation": feed(latest=1000),
        "key_zones": {
            "status": "READY",
            "execution_trusted": True,
            "entry_event_status": "CONFIRMED_ENTRY",
            "primary_zone": {"id": "buy-1", "entry_eligible_origin": True},
            "latest_entry_event": {"id": "event-1", "available_at": event_time, "quality_score": 92},
            "precision_gate": {"status": "QUALIFIED", "minimum_entry_quality": 86},
            "mtf_confluence": {
                "status": "READY",
                "direction": "BULLISH",
                "ready_timeframes": 2,
                "required_timeframes": ["15M", "5M"],
            },
        },
        "htf_bias": {"bias": "Bullish"},
        "liquidity_map": {"liquidity_sweep": True},
        "poi_engine": {"best_poi": {"type": "FVG"}},
        "confirmation_engine": {"confirmation_ready": True},
        "session_framework": {"k_trend": {"status": "READY", "confirmation": "CONFIRMED", "regime": "BULLISH"}},
        "xau_confluence": {"execution_gate": "OPEN"},
        "market_regime": {
            "status": "READY",
            "regime": "TRENDING_BULLISH",
            "execution_gate": "OPEN",
            "reason": "BUY agrees with the completed-candle trend.",
            "location_guard": {"status": "PASS", "allows_entry": True, "directional_extension_atr": 0.8},
        },
        "news_intelligence": {"execution_gate": "ALLOW"},
        "trade_plan": {
            "status": "ACTIONABLE",
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 99.0,
            "take_profit_levels": [102.0],
            "risk_reward": 2.0,
        },
        "execution_reality": {
            "status": "TRACKABLE_NOT_BROKER_READY",
            "research_trackable": True,
            "broker_executable": False,
            "pricing_mode": "MIDPOINT_RESEARCH",
            "entry": 100.0,
            "stop": 99.0,
            "target": 102.0,
            "risk_reward": 2.0,
        },
    }


class DecisionQualityEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = DecisionQualityEngine()

    def test_untrusted_feed_caps_decision_and_blocks_action(self):
        analysis = ready_analysis()
        analysis["feed_reconciliation"] = feed(trusted=False)
        result = self.engine.evaluate(analysis, validation())

        self.assertEqual(result["status"], "DATA_BLOCKED")
        self.assertLessEqual(result["score"], 24)
        self.assertFalse(result["decision_allowed"])
        self.assertFalse(result["changes_signal_logic"])

    def test_historical_confirmed_event_is_not_a_current_entry(self):
        result = self.engine.evaluate(ready_analysis(event_time=900), validation())

        self.assertEqual(result["status"], "HISTORICAL_CONTEXT")
        self.assertEqual(result["event_freshness"], "HISTORICAL_CONTEXT")
        self.assertLessEqual(result["score"], 59)
        self.assertFalse(result["decision_allowed"])

    def test_current_setup_can_be_research_trackable_without_broker_claim(self):
        analysis = ready_analysis()
        result = self.engine.evaluate(analysis, validation())
        self.engine.apply_to_analysis(analysis, result)

        self.assertEqual(result["status"], "TRACKABLE_SETUP")
        self.assertGreaterEqual(result["score"], 85)
        self.assertTrue(result["decision_allowed"])
        self.assertTrue(result["research_trackable"])
        self.assertFalse(result["broker_executable"])
        self.assertFalse(result["broker_order_submitted"])
        self.assertEqual(analysis["signal"]["decision_quality_status"], "TRACKABLE_SETUP")
        self.assertEqual(result["execution_readiness"]["status"], "READY")
        self.assertEqual(result["execution_readiness"]["passed"], 6)
        self.assertIsNone(result["primary_blocker"])
        self.assertEqual(result["signal_integrity"]["result_scope"], "EVIDENCE_READY_CONFIRMED_ENTRY")
        self.assertFalse(result["signal_integrity"]["context_is_entry"])
        self.assertFalse(result["signal_integrity"]["qualified_watch_is_entry"])

    def test_opposing_regime_vetoes_current_setup(self):
        analysis = ready_analysis()
        analysis["market_regime"] = {
            "status": "READY",
            "regime": "TRENDING_BEARISH",
            "execution_gate": "BLOCK_DIRECTION_CONFLICT",
            "reason": "BUY conflicts with the bearish regime.",
        }

        result = self.engine.evaluate(analysis, validation())

        self.assertEqual(result["status"], "REGIME_CONFLICT")
        self.assertLessEqual(result["score"], 54)
        self.assertFalse(result["decision_allowed"])

    def test_volatility_shock_locks_new_decision(self):
        analysis = ready_analysis()
        analysis["market_regime"] = {
            "status": "READY",
            "regime": "VOLATILITY_SHOCK",
            "execution_gate": "BLOCK_VOLATILITY",
            "reason": "Latest range is outside the ATR baseline.",
        }

        result = self.engine.evaluate(analysis, validation())

        self.assertEqual(result["status"], "VOLATILITY_LOCKED")
        self.assertLessEqual(result["score"], 45)
        self.assertFalse(result["decision_allowed"])

    def test_anti_chase_location_guard_blocks_current_setup(self):
        analysis = ready_analysis()
        analysis["market_regime"] = {
            "status": "READY",
            "regime": "TRENDING_BULLISH",
            "execution_gate": "WAIT_OVEREXTENDED",
            "reason": "BUY is extended above EMA20 at the upper range extreme.",
            "location_guard": {
                "status": "WAIT_OVEREXTENDED",
                "allows_entry": False,
                "side": "BUY_HIGH",
                "directional_extension_atr": 5.2,
            },
        }

        result = self.engine.evaluate(analysis, validation())

        self.assertEqual(result["status"], "LOCATION_GUARD")
        self.assertLessEqual(result["score"], 54)
        self.assertFalse(result["decision_allowed"])
        self.assertEqual(result["execution_readiness"]["next_gate_id"], "location")
        self.assertEqual(result["primary_blocker"]["label"], "Location Guard")
        self.assertEqual(result["top_blockers"][0]["priority"], "CRITICAL")

    def test_asset_profile_conflict_caps_decision_and_blocks_mtf_readiness(self):
        analysis = ready_analysis()
        analysis["asset_intelligence"] = {
            "profile": "XAU_PRECISION",
            "execution_gate": "BLOCK_MTF_CONFLICT",
            "reason": "Weighted MTF consensus conflicts with BUY.",
        }

        result = self.engine.evaluate(analysis, validation())

        self.assertEqual(result["status"], "ASSET_PROFILE_GUARD")
        self.assertLessEqual(result["score"], 54)
        self.assertFalse(result["decision_allowed"])
        self.assertEqual(result["execution_readiness"]["next_gate_id"], "mtf")
        self.assertEqual(result["asset_profile"], "XAU_PRECISION")


if __name__ == "__main__":
    unittest.main()
