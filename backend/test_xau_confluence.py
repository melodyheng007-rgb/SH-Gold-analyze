import copy
import unittest

from engine.xau_confluence import XAUPrecisionConfluenceEngine


def strong_analysis():
    return {
        "symbol": "XAUUSD",
        "trust_gate": {"trusted": True, "reason": "Matched provider."},
        "htf_bias": {"bias": "Bullish", "reason": "1D and 4H are bullish."},
        "liquidity_map": {"liquidity_sweep": "Sell-side sweep", "reason": "Sell-side liquidity swept."},
        "crt_range": {"premium_discount_status": "Discount", "mid_range_warning": False},
        "poi_engine": {
            "best_poi": {"type": "OrderBlock", "low": 4000, "high": 4005},
            "premium_discount_alignment": True,
            "reason": "Bullish order block in discount.",
        },
        "confirmation_engine": {"confirmation_ready": True, "reason": "Bullish CHOCH and displacement."},
        "signal": {"direction": "BUY", "execution_allowed": True},
        "trade_plan": {
            "status": "ACTIONABLE",
            "label": "Actionable Buy Setup",
            "direction": "BUY",
            "entry_price": 4005,
            "stop_loss": 3995,
            "take_profit_levels": [4025],
            "missing_conditions": [],
        },
        "analysis_explanation": {},
    }


def strong_zones():
    return {
        "status": "READY",
        "execution_trusted": True,
        "directional_bias": "BUY_CONTEXT",
        "quality_grade": "A",
        "execution_quality": "READY",
        "rejection_status": "STRONG",
        "rejection_score": 84,
        "entry_event_status": "CONFIRMED_ENTRY",
        "latest_entry_event": {
            "zone_id": "buy-123",
            "entry_side": "BUY",
            "quality_score": 88,
        },
        "primary_zone": {"id": "buy-123", "lifecycle": "TESTED"},
        "mtf_confluence": {"direction": "BULLISH", "state": "ALIGNED_BULLISH"},
    }


class XAUPrecisionConfluenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = XAUPrecisionConfluenceEngine()
        self.session = {
            "status": "READY",
            "stance": "BULLISH",
            "position": "ABOVE_OP_AND_MLP",
            "buy_context": True,
            "sell_context": False,
            "range_extension": False,
            "k_trend": {
                "status": "READY",
                "regime": "BULLISH",
                "score": 82,
                "confirmation": "CONFIRMED",
                "next_target_label": "K+1",
            },
        }
        self.news = {"execution_gate": "OPEN", "summary": "No high-impact event nearby."}

    def test_strong_xau_evidence_opens_precision_gate(self):
        result = self.engine.evaluate(strong_analysis(), strong_zones(), self.session, self.news)

        self.assertEqual(result["state"], "PRECISION_READY")
        self.assertEqual(result["execution_gate"], "OPEN")
        self.assertGreaterEqual(result["validation_score"], 80)
        self.assertEqual(result["agreement"], {"passed": 9, "total": 9})
        self.assertFalse(result["trade_direction_created"])

    def test_unmatched_feed_is_research_only(self):
        analysis = strong_analysis()
        analysis["trust_gate"] = {"trusted": False, "reason": "OANDA feed is not matched."}

        result = self.engine.evaluate(analysis, strong_zones(), self.session, self.news)

        self.assertEqual(result["state"], "RESEARCH_ONLY")
        self.assertEqual(result["execution_gate"], "BLOCK")
        self.assertIn("OANDA feed is not matched.", result["blockers"])

    def test_diamond_conflict_blocks_actionable_plan_without_changing_prices(self):
        analysis = strong_analysis()
        zones = strong_zones()
        zones["directional_bias"] = "SELL_CONTEXT"
        zones["mtf_confluence"] = {"direction": "BEARISH", "state": "ALIGNED_BEARISH"}
        original_prices = copy.deepcopy({key: analysis["trade_plan"][key] for key in ("entry_price", "stop_loss", "take_profit_levels")})

        result = self.engine.evaluate(analysis, zones, self.session, self.news)
        self.engine.apply_to_analysis(analysis, result)

        self.assertEqual(result["state"], "CONFLUENCE_CONFLICT")
        self.assertEqual(analysis["trade_plan"]["status"], "CANDIDATE")
        self.assertFalse(analysis["signal"]["execution_allowed"])
        self.assertEqual(
            {key: analysis["trade_plan"][key] for key in original_prices},
            original_prices,
        )

    def test_news_lock_cannot_be_overridden_by_technical_confluence(self):
        news = {"execution_gate": "BLOCK_NEW_ENTRIES", "summary": "CPI release window is active."}

        result = self.engine.evaluate(strong_analysis(), strong_zones(), self.session, news)

        self.assertEqual(result["state"], "NEWS_LOCK")
        self.assertEqual(result["execution_gate"], "BLOCK")
        self.assertIn("CPI release window is active.", result["blockers"])

    def test_k_range_must_confirm_the_same_direction(self):
        session = copy.deepcopy(self.session)
        session["k_trend"].update(regime="RANGE", score=12, confirmation="WAIT_CLOSED_CANDLE")

        result = self.engine.evaluate(strong_analysis(), strong_zones(), session, self.news)

        self.assertEqual(result["execution_gate"], "BLOCK")
        self.assertTrue(any("k-range" in blocker.lower() for blocker in result["blockers"]))

    def test_btc_is_explicitly_outside_xau_profile(self):
        analysis = strong_analysis()
        analysis["symbol"] = "BTCUSD"

        result = self.engine.evaluate(analysis, strong_zones(), self.session, self.news)

        self.assertEqual(result["status"], "NOT_APPLICABLE")
        self.assertEqual(result["execution_gate"], "NOT_APPLICABLE")


if __name__ == "__main__":
    unittest.main()
