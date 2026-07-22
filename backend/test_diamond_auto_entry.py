from __future__ import annotations

import copy
import unittest

from engine.diamond_auto_entry import DiamondAutoEntryEngine


def actionable_analysis() -> dict:
    return {
        "symbol": "XAUUSD",
        "current_price": 100.5,
        "bias": "Bullish",
        "htf_bias": {"bias": "Bullish"},
        "trust_gate": {"trusted": True, "status": "TRUSTED", "reason": "Matched feed."},
        "confirmation_engine": {"confirmation_ready": True, "reason": "Closed bullish confirmation."},
        "market_regime": {
            "status": "READY",
            "regime": "TRENDING_BULLISH",
            "execution_gate": "OPEN",
            "reason": "Direction and location are valid.",
            "location_guard": {"status": "PASS", "allows_entry": True},
        },
        "liquidity_map": {
            "buy_side_liquidity": [103.0, 106.0, 108.0],
            "nearest_liquidity_above": 103.0,
            "previous_day_high": 106.0,
            "session_high": 108.0,
        },
        "signal": {"execution_allowed": True, "score": 88},
        "trade_plan": {
            "status": "ACTIONABLE",
            "direction": "BUY",
            "order_type": "MARKET",
            "setup_type": "Confirmed Market",
            "action": "Existing setup is validated.",
        },
    }


def qualified_zones() -> dict:
    return {
        "status": "READY",
        "execution_trusted": True,
        "execution_quality": "READY",
        "rejection_status": "STRONG",
        "directional_bias": "BUY_CONTEXT",
        "timeframe": "5M",
        "trading_style": "SCALPING",
        "execution_timeframe": "5M",
        "confirmation_timeframe": "15M",
        "required_timeframes": ["15M", "5M"],
        "precision_gate": {
            "status": "QUALIFIED",
            "minimum_entry_quality": 86,
            "minimum_location_score": 72,
        },
        "entry_event_status": "CONFIRMED_ENTRY",
        "latest_entry_event": {
            "id": "entry-buy-123-789",
            "zone_id": "buy-123",
            "entry_side": "BUY",
            "quality_score": 88,
            "precision_grade": "A",
            "precision_qualified": True,
            "confirmation_time": 789,
            "execution_entry": 100.0,
            "stop_reference": 99.5,
            "atr_14": 2.0,
            "confirmation_model": "PRECISION_ORIGIN_RETEST_REJECTION_FOLLOW_THROUGH",
        },
        "primary_zone": {
            "id": "buy-123",
            "entry_side": "BUY",
            "line": 100.0,
            "low": 99.5,
            "high": 100.5,
            "atr_14": 2.0,
            "entry_location_score": 92,
            "lifecycle": "FRESH",
        },
        "mtf_confluence": {
            "status": "READY",
            "direction": "BULLISH",
            "ready_timeframes": 2,
            "required_timeframes": ["15M", "5M"],
        },
        "next_trigger": "Diamond rejection confirmed.",
    }


def aligned_session() -> dict:
    return {
        "buy_context": True,
        "sell_context": False,
        "range_extension": False,
        "levels": {"k_plus_1": 103.5, "k_plus_2": 107.0},
        "k_trend": {"status": "READY", "confirmation": "CONFIRMED", "regime": "BULLISH"},
    }


class DiamondAutoEntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DiamondAutoEntryEngine()

    def test_arms_provider_mapped_buy_at_confirmed_entry_close(self) -> None:
        analysis = actionable_analysis()

        result = self.engine.apply(
            analysis,
            qualified_zones(),
            aligned_session(),
            {"execution_gate": "OPEN", "summary": "No scheduled lock."},
        )

        plan = analysis["trade_plan"]
        self.assertEqual(result["status"], "AUTO_ARMED")
        self.assertEqual(plan["order_type"], "MARKET")
        self.assertEqual(plan["position_type"], "CONFIRMED_ENTRY")
        self.assertEqual(plan["entry_price"], 100.0)
        self.assertEqual(plan["stop_loss"], 99.3)
        self.assertEqual(plan["take_profit_levels"], [103.0, 103.5, 106.0])
        self.assertGreaterEqual(plan["risk_reward"], 1.5)
        self.assertTrue(plan["auto_entry_armed"])
        self.assertFalse(result["broker_order_submitted"])

    def test_unmatched_feed_blocks_auto_entry_without_rewriting_plan(self) -> None:
        analysis = actionable_analysis()
        analysis["trust_gate"] = {"trusted": False, "status": "RESEARCH_ONLY", "reason": "Feed mismatch."}
        original = copy.deepcopy(analysis["trade_plan"])

        result = self.engine.apply(
            analysis,
            qualified_zones(),
            aligned_session(),
            {"execution_gate": "OPEN"},
        )

        self.assertEqual(result["status"], "BLOCKED_DATA_TRUST")
        self.assertEqual(analysis["trade_plan"], original)
        self.assertFalse(analysis["signal"]["diamond_auto_entry_armed"])

    def test_verified_opposite_smt_divergence_blocks_entry(self) -> None:
        analysis = actionable_analysis()
        analysis["smt_model"] = {
            "status": "READY",
            "state": "BEARISH_DIVERGENCE",
            "direction": "SELL",
            "confidence": 82,
            "execution_gate": "DIVERGENCE_READY",
            "reason": "XAG failed to confirm the latest higher high.",
        }

        result = self.engine.apply(
            analysis,
            qualified_zones(),
            aligned_session(),
            {"execution_gate": "OPEN"},
        )

        self.assertEqual(result["status"], "WAITING_SMT")
        self.assertFalse(analysis["signal"]["diamond_auto_entry_armed"])
        self.assertEqual(result["smt_execution_gate"], "BLOCK_CONFLICT")

    def test_arms_sell_entry_with_stop_above_rejection_swing(self) -> None:
        analysis = actionable_analysis()
        analysis.update({"current_price": 99.5, "bias": "Bearish", "htf_bias": {"bias": "Bearish"}})
        analysis["trade_plan"].update({"direction": "SELL", "setup_type": "Confirmed Sell"})
        analysis["liquidity_map"] = {
            "sell_side_liquidity": [97.0, 94.0, 92.0],
            "nearest_liquidity_below": 97.0,
            "previous_day_low": 94.0,
            "session_low": 92.0,
        }
        zones = qualified_zones()
        zones["directional_bias"] = "SELL_CONTEXT"
        zones["primary_zone"].update({"id": "sell-456", "entry_side": "SELL"})
        zones["latest_entry_event"].update({
            "id": "entry-sell-456-789",
            "zone_id": "sell-456",
            "entry_side": "SELL",
            "stop_reference": 100.5,
        })
        zones["mtf_confluence"] = {
            "status": "READY",
            "direction": "BEARISH",
            "ready_timeframes": 2,
            "required_timeframes": ["15M", "5M"],
        }
        session = aligned_session()
        session.update({"buy_context": False, "sell_context": True, "levels": {"k_minus_1": 96.5, "k_minus_2": 93.0}})
        session["k_trend"]["regime"] = "BEARISH"

        result = self.engine.apply(analysis, zones, session, {"execution_gate": "OPEN"})

        plan = analysis["trade_plan"]
        self.assertEqual(result["status"], "AUTO_ARMED")
        self.assertEqual(plan["entry_price"], 100.0)
        self.assertEqual(plan["stop_loss"], 100.7)
        self.assertEqual(plan["take_profit_levels"], [97.0, 96.5, 94.0])
        self.assertGreater(plan["stop_loss"], plan["entry_price"])
        self.assertTrue(all(target < plan["entry_price"] for target in plan["take_profit_levels"]))

    def test_stale_price_cannot_chase_a_confirmed_diamond(self) -> None:
        analysis = actionable_analysis()
        zones = qualified_zones()
        zones["primary_zone"]["line"] = 102.0
        zones["primary_zone"]["low"] = 101.5
        zones["primary_zone"]["high"] = 102.5
        zones["latest_entry_event"]["execution_entry"] = 103.0
        zones["latest_entry_event"]["stop_reference"] = 101.5

        result = self.engine.apply(
            analysis,
            zones,
            aligned_session(),
            {"execution_gate": "OPEN"},
        )

        self.assertEqual(result["status"], "WAITING_DIAMOND")
        self.assertIn("within 0.35 ATR", result["next_trigger"])
        self.assertNotIn("entry_price", analysis["trade_plan"])

    def test_overextended_market_location_blocks_auto_entry(self) -> None:
        analysis = actionable_analysis()
        analysis["market_regime"] = {
            "status": "READY",
            "regime": "TRENDING_BULLISH",
            "execution_gate": "WAIT_OVEREXTENDED",
            "reason": "BUY is 5.30 ATR above EMA20 at the upper range extreme.",
            "location_guard": {
                "status": "WAIT_OVEREXTENDED",
                "allows_entry": False,
                "directional_extension_atr": 5.3,
            },
        }

        result = self.engine.apply(
            analysis,
            qualified_zones(),
            aligned_session(),
            {"execution_gate": "OPEN"},
        )

        self.assertEqual(result["status"], "WAITING_LOCATION")
        self.assertEqual(result["regime_gate"], "WAIT_OVEREXTENDED")
        self.assertIn("5.30 ATR", result["next_trigger"])
        self.assertNotIn("entry_price", analysis["trade_plan"])

    def test_weak_or_untested_diamond_is_not_an_entry(self) -> None:
        analysis = actionable_analysis()
        zones = qualified_zones()
        zones["execution_quality"] = "WAIT_RETEST"
        zones["rejection_status"] = "UNTESTED"

        result = self.engine.apply(
            analysis,
            zones,
            aligned_session(),
            {"execution_gate": "OPEN"},
        )

        self.assertEqual(result["status"], "WAITING_DIAMOND")
        self.assertFalse(analysis["signal"]["diamond_auto_entry_armed"])

    def test_context_zone_without_confirmed_event_cannot_arm(self) -> None:
        analysis = actionable_analysis()
        zones = qualified_zones()
        zones["entry_event_status"] = "WAITING_CONFIRMATION"
        zones["latest_entry_event"] = None

        result = self.engine.apply(
            analysis,
            zones,
            aligned_session(),
            {"execution_gate": "OPEN"},
        )

        self.assertEqual(result["status"], "WAITING_DIAMOND")
        self.assertIn("closed-candle reclaim/follow-through", result["next_trigger"])
        self.assertFalse(analysis["signal"]["diamond_auto_entry_armed"])

    def test_swing_entry_requires_1h_and_4h_profile(self) -> None:
        analysis = actionable_analysis()
        zones = qualified_zones()
        zones.update({
            "timeframe": "1H",
            "trading_style": "SWING",
            "execution_timeframe": "1H",
            "confirmation_timeframe": "4H",
            "required_timeframes": ["4H", "1H"],
            "mtf_confluence": {
                "status": "READY",
                "direction": "BULLISH",
                "ready_timeframes": 2,
                "required_timeframes": ["4H", "1H"],
            },
        })

        result = self.engine.apply(
            analysis,
            zones,
            aligned_session(),
            {"execution_gate": "OPEN"},
        )

        self.assertEqual(result["status"], "AUTO_ARMED")
        self.assertEqual(result["trading_style"], "SWING")
        self.assertEqual(result["execution_timeframe"], "1H")
        self.assertEqual(result["confirmation_timeframe"], "4H")

    def test_swing_profile_blocks_scalping_timeframe_entry(self) -> None:
        analysis = actionable_analysis()
        zones = qualified_zones()
        zones.update({
            "trading_style": "SWING",
            "required_timeframes": ["4H", "1H"],
            "mtf_confluence": {
                "status": "READY",
                "direction": "BULLISH",
                "ready_timeframes": 2,
                "required_timeframes": ["4H", "1H"],
            },
        })

        result = self.engine.apply(
            analysis,
            zones,
            aligned_session(),
            {"execution_gate": "OPEN"},
        )

        self.assertEqual(result["status"], "WAITING_DIAMOND")
        self.assertIn("Swing entries require one of: 4H / 1H", result["next_trigger"])

    def test_smr_watch_is_informational_and_does_not_make_entries_sparse(self) -> None:
        analysis = actionable_analysis()
        analysis["smr_model"] = {
            "status": "READY",
            "pattern_state": "SCANNING_LIQUIDITY",
            "score": 34,
            "execution_gate": "WATCH",
            "next_trigger": "Wait for a completed-candle liquidity raid.",
            "session": {"name": "LONDON", "quality": "PRIME"},
        }

        result = self.engine.apply(
            analysis,
            qualified_zones(),
            aligned_session(),
            {"execution_gate": "OPEN"},
        )

        self.assertEqual(result["status"], "AUTO_ARMED")
        self.assertEqual(result["smr_state"], "SCANNING_LIQUIDITY")
        self.assertEqual(result["smr_session"], "LONDON")

    def test_confirmed_smr_conflict_blocks_auto_entry(self) -> None:
        analysis = actionable_analysis()
        analysis["smr_model"] = {
            "status": "READY",
            "pattern_state": "CONFIRMED",
            "direction": "SELL",
            "score": 82,
            "execution_gate": "BLOCK_CONFLICT",
            "next_trigger": "The confirmed SMR direction conflicts with the Diamond.",
            "session": {"name": "NEW_YORK", "quality": "PRIME"},
        }

        result = self.engine.apply(
            analysis,
            qualified_zones(),
            aligned_session(),
            {"execution_gate": "OPEN"},
        )

        self.assertEqual(result["status"], "WAITING_SMR")
        self.assertIn("SMR conflict", result["next_trigger"])
        self.assertFalse(analysis["signal"]["diamond_auto_entry_armed"])

    def test_dual_core_watch_does_not_make_entries_sparse(self) -> None:
        analysis = actionable_analysis()
        analysis["diamond_timeframe_model"] = {
            "status": "READY",
            "state": "CORE_BUILDING",
            "score": 64,
            "grade": "C",
            "focus_timeframe": "5M",
            "execution_gate": "WATCH",
            "next_trigger": "Wait for execution momentum to align.",
        }

        result = self.engine.apply(
            analysis,
            qualified_zones(),
            aligned_session(),
            {"execution_gate": "OPEN"},
        )

        self.assertEqual(result["status"], "AUTO_ARMED")
        self.assertEqual(result["dual_core_state"], "CORE_BUILDING")
        self.assertEqual(result["dual_core_focus_timeframe"], "5M")

    def test_dual_core_conflict_blocks_auto_entry(self) -> None:
        analysis = actionable_analysis()
        analysis["diamond_timeframe_model"] = {
            "status": "READY",
            "state": "CORE_CONFLICT",
            "score": 42,
            "grade": "D",
            "focus_timeframe": "5M",
            "execution_gate": "BLOCK_CONFLICT",
            "next_trigger": "Resolve anchor context conflict before accepting this Diamond.",
        }

        result = self.engine.apply(
            analysis,
            qualified_zones(),
            aligned_session(),
            {"execution_gate": "OPEN"},
        )

        self.assertEqual(result["status"], "WAITING_DUAL_CORE")
        self.assertIn("anchor context conflict", result["next_trigger"])
        self.assertFalse(analysis["signal"]["diamond_auto_entry_armed"])


if __name__ == "__main__":
    unittest.main()
