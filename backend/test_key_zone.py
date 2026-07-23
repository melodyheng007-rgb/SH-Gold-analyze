import unittest

from engine.key_zone import DiamondZoneEngine


def base_candles(count: int = 36):
    candles = []
    for index in range(count):
        close = 100.10 if index % 2 == 0 else 99.90
        candles.append({
            "time": 1_700_000_000 + index * 300,
            "open": 100.0,
            "high": 100.55,
            "low": 99.45,
            "close": close,
            "is_complete": True,
        })
    return candles


class DiamondZoneEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DiamondZoneEngine()

    def test_detects_bullish_reversal_origin_and_ignores_partial_candle(self) -> None:
        candles = base_candles()
        impulse_time = candles[30]["time"]
        candles[30].update(open=100.0, high=102.40, low=99.80, close=102.20)
        for index in range(31, len(candles)):
            candles[index].update(open=102.10, high=102.65, low=101.80, close=102.35)
        candles.append({
            "time": candles[-1]["time"] + 300,
            "open": 102.35,
            "high": 110.0,
            "low": 90.0,
            "close": 90.0,
            "is_complete": False,
            "is_partial": True,
        })

        result = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER")

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["primary_zone"]["direction"], "BULLISH")
        self.assertEqual(result["primary_zone"]["entry_side"], "BUY")
        self.assertEqual(result["primary_zone"]["entry_anchor"], "CANDLE_LOW")
        self.assertEqual(result["primary_zone"]["line"], 99.8)
        self.assertLess(result["primary_zone"]["line"], result["primary_zone"]["impulse_close"])
        self.assertEqual(result["primary_zone"]["time"], impulse_time)
        self.assertEqual(result["current_price"], 102.35)
        self.assertTrue(result["uses_completed_candles_only"])
        self.assertFalse(result["proprietary_formula_claimed"])
        self.assertIn(result["primary_zone"]["lifecycle"], {"FRESH", "TESTED"})
        self.assertIn(result["quality_grade"], {"A+", "A", "B", "C"})
        self.assertEqual(result["confirmation_state"], "CONFIRMED_HOLD")
        self.assertEqual(result["strategy"], "SH_DIAMOND_ZONE_V8_7_DUAL_LANE")
        self.assertEqual(result["profile"], "XAU_ADAPTIVE_DUAL_LANE_V8_7_5M")
        self.assertEqual(result["adaptive_profile"]["asset_model"], "XAU_PRECISION")
        self.assertTrue(result["adaptive_profile"]["quality_floor_preserved"])
        self.assertIn(result["primary_zone"]["signal_tier"], {"EARLY", "QUALIFIED", "CONFIRMED"})
        self.assertTrue(result["primary_zone"]["closed_candle_proof"]["non_repainting"])
        self.assertEqual(result["primary_zone"]["closed_candle_proof"]["locked_after"], impulse_time + 300)
        self.assertIn(result["execution_quality"], {"READY", "WATCH", "WAIT_RETEST", "CONTEXT_ONLY"})
        self.assertIn(result["rejection_status"], {"STRONG", "MODERATE", "WEAK", "NO_REJECTION", "UNTESTED"})

    def test_detects_bearish_zone_and_context_alignment(self) -> None:
        candles = base_candles()
        candles[30].update(open=100.0, high=100.20, low=97.60, close=97.80)
        candles[31].update(open=100.10, high=100.35, low=99.40, close=99.55)
        for index in range(32, len(candles)):
            candles[index].update(open=99.70, high=99.85, low=99.25, close=99.40)

        result = self.engine.calculate(
            candles,
            "5M",
            "MATCHED_PROVIDER",
            session_context={"stance": "BEARISH"},
        )

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["primary_zone"]["direction"], "BEARISH")
        self.assertEqual(result["primary_zone"]["entry_side"], "SELL")
        self.assertEqual(result["primary_zone"]["entry_anchor"], "CANDLE_HIGH")
        self.assertEqual(result["primary_zone"]["line"], 100.2)
        self.assertGreater(result["primary_zone"]["line"], result["primary_zone"]["impulse_close"])
        self.assertEqual(result["directional_bias"], "SELL_CONTEXT")
        self.assertTrue(result["context_aligned"])

    def test_places_buy_at_low_and_sell_at_high_instead_of_impulse_closes(self) -> None:
        candles = base_candles(40)
        buy_time = candles[30]["time"]
        sell_time = candles[31]["time"]
        candles[30].update(open=100.0, high=104.0, low=99.20, close=103.80)
        candles[31].update(open=104.0, high=104.20, low=100.50, close=100.70)
        for index in range(32, len(candles)):
            candles[index].update(open=101.5, high=102.0, low=101.0, close=101.4)

        result = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER")
        zones = {zone["time"]: zone for zone in result["zones"]}
        buy = zones[buy_time]
        sell = zones[sell_time]

        self.assertEqual(buy["entry_side"], "BUY")
        self.assertEqual(buy["line"], 99.2)
        self.assertEqual(sell["entry_side"], "SELL")
        self.assertEqual(sell["line"], 104.2)
        self.assertLess(buy["line"], sell["line"])
        self.assertEqual(result["entry_events"], [])
        self.assertIsNone(result["latest_entry_event"])
        self.assertEqual(result["entry_event_status"], "WAITING_CONFIRMATION")

    def test_confirms_buy_after_strong_closed_retest_reclaim(self) -> None:
        candles = base_candles(35)
        origin_time = candles[30]["time"]
        candles[30].update(open=100.0, high=103.20, low=99.0, close=103.0)
        candles[31].update(open=102.8, high=103.2, low=102.2, close=102.6)
        candles[32].update(open=102.5, high=102.8, low=101.7, close=102.1)
        candles[33].update(open=99.20, high=99.90, low=98.95, close=99.75)
        candles[34].update(open=99.70, high=100.40, low=99.60, close=100.25)

        result = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER")
        event = result["latest_entry_event"]

        self.assertEqual(result["entry_event_status"], "CONFIRMED_ENTRY")
        self.assertEqual(len(result["entry_events"]), 1)
        self.assertEqual(event["zone_id"], f"buy-{origin_time}")
        self.assertEqual(event["entry_side"], "BUY")
        self.assertEqual(event["time"], candles[33]["time"])
        self.assertEqual(event["available_at"], candles[33]["time"])
        self.assertEqual(event["signal_tier"], "CONFIRMED")
        self.assertEqual(event["closed_candle_proof"]["policy"], "CLOSED_CANDLE_LOCKED")
        self.assertTrue(event["closed_candle_proof"]["completed_candle_only"])
        self.assertLess(event["marker_price"], candles[33]["low"])
        self.assertGreaterEqual(event["quality_score"], 68)
        self.assertTrue(event["precision_qualified"])
        self.assertIn(event["precision_grade"], {"C", "B", "A", "A+"})
        self.assertEqual(event["confirmation_model"], "ACTIVE_RETEST_RECLAIM_CLOSE")
        self.assertEqual(event["entry_pathway"], "RECLAIM_CLOSE")
        funnel = result["gate_funnel"]
        self.assertEqual(funnel["status"], "CONFIRMED")
        self.assertEqual(funnel["current_gate"], "confirmed_entries")
        self.assertEqual(funnel["stages"][-1]["count"], 1)
        self.assertTrue(funnel["zone_traces"][0]["confirmed"])
        self.assertFalse(funnel["changes_signal_logic"])
        self.assertEqual(result["primary_zone"]["display_role"], "CONFIRMED_ENTRY")
        self.assertEqual(result["primary_zone"]["entry_stage"], "CONFIRMED_ENTRY")
        self.assertTrue(result["primary_zone"]["actionable_entry"])
        self.assertEqual(result["primary_zone"]["diamond_confidence_tier"], "ENTRY_READY")
        self.assertGreaterEqual(result["primary_zone"]["diamond_confidence_score"], 86)
        self.assertEqual(result["signal_integrity"]["confirmed_entries"], 1)

    def test_confirms_sell_after_strong_closed_retest_reclaim(self) -> None:
        candles = base_candles(35)
        origin_time = candles[30]["time"]
        candles[30].update(open=100.0, high=101.0, low=96.8, close=97.0)
        candles[31].update(open=97.2, high=97.8, low=96.9, close=97.4)
        candles[32].update(open=97.5, high=98.2, low=97.2, close=97.8)
        candles[33].update(open=100.80, high=101.05, low=100.10, close=100.25)
        candles[34].update(open=100.30, high=100.40, low=99.60, close=99.75)

        result = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER")
        event = result["latest_entry_event"]

        self.assertEqual(result["entry_event_status"], "CONFIRMED_ENTRY")
        self.assertEqual(event["zone_id"], f"sell-{origin_time}")
        self.assertEqual(event["entry_side"], "SELL")
        self.assertEqual(event["time"], candles[33]["time"])
        self.assertGreater(event["marker_price"], candles[33]["high"])
        self.assertGreaterEqual(event["quality_score"], 68)

    def test_weak_follow_through_remains_context_only(self) -> None:
        candles = base_candles(35)
        candles[30].update(open=100.0, high=101.0, low=96.8, close=97.0)
        candles[31].update(open=97.2, high=97.8, low=96.9, close=97.4)
        candles[32].update(open=97.5, high=98.2, low=97.2, close=97.8)
        candles[33].update(open=100.80, high=101.05, low=100.10, close=100.45)
        candles[34].update(open=100.45, high=100.55, low=100.20, close=100.35)

        result = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER")

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["entry_events"], [])
        self.assertEqual(result["entry_event_status"], "WAITING_CONFIRMATION")
        funnel = result["gate_funnel"]
        self.assertEqual(funnel["status"], "WAITING_AT_GATE")
        self.assertEqual(funnel["stages"][-1]["count"], 0)
        self.assertTrue(funnel["top_blockers"])
        self.assertFalse(result["primary_zone"]["actionable_entry"])
        self.assertIn(result["primary_zone"]["display_role"], {"QUALIFIED_WATCH", "SCORE_WATCH", "INVALIDATED_CONTEXT", "INTERNAL_REJECTED"})
        self.assertNotEqual(result["primary_zone"]["display_role"], "CONFIRMED_ENTRY")
        self.assertIn(result["primary_zone"]["diamond_confidence_tier"], {"QUALIFIED", "HIGH_CONVICTION", "INVALIDATED"})
        self.assertEqual(result["signal_integrity"]["confirmed_entries"], 0)

    def test_confirms_follow_through_on_second_closed_candle(self) -> None:
        candles = base_candles(36)
        origin_time = candles[30]["time"]
        candles[30].update(open=100.0, high=103.20, low=99.0, close=103.0)
        candles[31].update(open=102.8, high=103.2, low=102.2, close=102.6)
        candles[32].update(open=102.5, high=102.8, low=101.7, close=102.1)
        candles[33].update(open=99.20, high=99.90, low=98.95, close=99.55)
        candles[34].update(open=99.55, high=99.80, low=99.30, close=99.50)
        candles[35].update(open=99.50, high=100.35, low=99.45, close=100.25)

        result = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER")
        event = result["latest_entry_event"]

        self.assertEqual(event["zone_id"], f"buy-{origin_time}")
        self.assertEqual(event["time"], candles[35]["time"])
        self.assertEqual(event["confirmation_delay_bars"], 2)
        self.assertEqual(event["entry_pathway"], "PULLBACK_FOLLOW_THROUGH")
        self.assertEqual(event["confirmation_model"], "ACTIVE_RETEST_MULTI_CANDLE_FOLLOW_THROUGH")
        self.assertGreaterEqual(event["quality_score"], 72)

    def test_origin_reclaim_is_available_on_its_own_closed_candle(self) -> None:
        rows = base_candles(31)
        rows[30].update(open=100.0, high=100.80, low=99.80, close=100.60)
        zone = {
            "id": f"buy-{rows[30]['time']}",
            "time": rows[30]["time"],
            "direction": "BULLISH",
            "entry_side": "BUY",
            "signal_label": "DIAMOND_BUY",
            "line": 99.80,
            "low": 99.68,
            "high": 99.92,
            "atr_14": 1.0,
            "entry_location_score": 90,
            "wider_entry_location_score": 90,
            "origin_quality_score": 90,
            "origin_model": "TREND_PULLBACK_RECLAIM",
            "liquidity_sweep": True,
            "structure_break": False,
            "compression_break": False,
            "trend_pullback_reclaim": True,
            "news_spike_risk": False,
            "direction_aligned": True,
            "close_strength": 0.92,
        }

        event = self.engine._origin_reclaim_event(
            rows,
            zone,
            30,
            self.engine._profile("XAUUSD", "5M"),
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["time"], rows[30]["time"])
        self.assertEqual(event["available_at"], rows[30]["time"])
        self.assertEqual(event["trigger_time"], rows[30]["time"])
        self.assertEqual(event["confirmation_delay_bars"], 0)
        self.assertEqual(event["entry_pathway"], "ORIGIN_RECLAIM_CLOSE")
        self.assertEqual(event["confirmation_model"], "ACTIVE_ORIGIN_SWEEP_RECLAIM_CLOSE")
        self.assertTrue(event["origin_confirmation"])
        self.assertGreaterEqual(event["quality_score"], 70)

    def test_xau_5m_fast_origin_reclaim_rejects_pure_liquidity_sweep(self) -> None:
        rows = base_candles(31)
        rows[30].update(open=100.0, high=100.80, low=99.80, close=100.60)
        zone = {
            "id": f"buy-{rows[30]['time']}",
            "time": rows[30]["time"],
            "direction": "BULLISH",
            "entry_side": "BUY",
            "signal_label": "DIAMOND_BUY",
            "line": 99.80,
            "low": 99.68,
            "high": 99.92,
            "atr_14": 1.0,
            "entry_location_score": 90,
            "wider_entry_location_score": 90,
            "origin_quality_score": 90,
            "origin_model": "LIQUIDITY_SWEEP",
            "liquidity_sweep": True,
            "structure_break": False,
            "compression_break": False,
            "trend_pullback_reclaim": False,
            "news_spike_risk": False,
            "direction_aligned": True,
            "close_strength": 0.92,
        }

        event = self.engine._origin_reclaim_event(
            rows,
            zone,
            30,
            self.engine._profile("XAUUSD", "5M"),
        )

        self.assertIsNone(event)

    def test_xau_5m_fast_origin_reclaim_requires_strong_close(self) -> None:
        rows = base_candles(31)
        rows[30].update(open=100.0, high=100.80, low=99.80, close=100.60)
        zone = {
            "id": f"buy-{rows[30]['time']}",
            "time": rows[30]["time"],
            "direction": "BULLISH",
            "entry_side": "BUY",
            "signal_label": "DIAMOND_BUY",
            "line": 99.80,
            "low": 99.68,
            "high": 99.92,
            "atr_14": 1.0,
            "entry_location_score": 90,
            "wider_entry_location_score": 90,
            "origin_quality_score": 90,
            "origin_model": "TREND_PULLBACK_RECLAIM",
            "liquidity_sweep": False,
            "structure_break": True,
            "compression_break": False,
            "trend_pullback_reclaim": True,
            "news_spike_risk": False,
            "direction_aligned": True,
            "close_strength": 0.84,
        }

        event = self.engine._origin_reclaim_event(
            rows,
            zone,
            30,
            self.engine._profile("XAUUSD", "5M"),
        )

        self.assertIsNone(event)

    def test_confirms_active_shallow_pullback_without_waiting_for_deep_retest(self) -> None:
        rows = base_candles(33)
        rows[30].update(open=100.0, high=101.60, low=99.8, close=101.40)
        rows[31].update(open=101.0, high=101.05, low=100.50, close=100.70)
        rows[32].update(open=100.70, high=101.30, low=100.65, close=101.25)
        zone = {
            "id": f"buy-{rows[30]['time']}",
            "time": rows[30]["time"],
            "direction": "BULLISH",
            "entry_side": "BUY",
            "signal_label": "DIAMOND_BUY",
            "line": 99.80,
            "low": 99.68,
            "high": 99.93,
            "atr_14": 0.95,
            "entry_location_score": 68,
            "wider_entry_location_score": 68,
            "origin_quality_score": 81,
            "origin_model": "TREND_PULLBACK_RECLAIM",
            "liquidity_sweep": False,
            "structure_break": True,
            "compression_break": False,
            "trend_pullback_reclaim": True,
            "active_structure": True,
            "news_spike_risk": False,
            "direction_aligned": True,
        }

        event = self.engine._shallow_pullback_continuation_event(
            rows,
            zone,
            30,
            self.engine._profile("XAUUSD", "5M"),
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["zone_id"], zone["id"])
        self.assertEqual(event["time"], rows[32]["time"])
        self.assertEqual(event["available_at"], rows[32]["time"])
        self.assertEqual(event["confirmation_delay_bars"], 2)
        self.assertEqual(event["entry_pathway"], "SHALLOW_PULLBACK_CONTINUATION")
        self.assertEqual(event["confirmation_model"], "ACTIVE_SHALLOW_PULLBACK_CONTINUATION")
        self.assertGreater(event["marker_price"], zone["high"])
        self.assertLess(event["entry_displacement_atr"], 1.05)
        self.assertGreater(event["origin_line_displacement_atr"], 1.0)
        self.assertLessEqual(event["origin_line_displacement_atr"], 1.55)
        self.assertGreaterEqual(event["quality_score"], 72)

    def test_shallow_pullback_rejects_a_late_chasing_confirmation(self) -> None:
        rows = base_candles(33)
        rows[30].update(open=100.0, high=101.60, low=99.8, close=101.40)
        rows[31].update(open=101.0, high=101.05, low=100.50, close=100.70)
        rows[32].update(open=100.70, high=101.65, low=100.65, close=101.60)
        zone = {
            "id": f"buy-{rows[30]['time']}",
            "time": rows[30]["time"],
            "direction": "BULLISH",
            "entry_side": "BUY",
            "signal_label": "DIAMOND_BUY",
            "line": 99.80,
            "low": 99.68,
            "high": 99.93,
            "atr_14": 0.95,
            "entry_location_score": 68,
            "wider_entry_location_score": 68,
            "origin_quality_score": 81,
            "origin_model": "TREND_PULLBACK_RECLAIM",
            "liquidity_sweep": False,
            "structure_break": True,
            "compression_break": False,
            "trend_pullback_reclaim": True,
            "active_structure": True,
            "news_spike_risk": False,
            "direction_aligned": True,
        }

        event = self.engine._shallow_pullback_continuation_event(
            rows,
            zone,
            30,
            self.engine._profile("XAUUSD", "5M"),
        )

        self.assertIsNone(event)

    def test_news_spike_origin_cannot_emit_an_immediate_diamond(self) -> None:
        candles = base_candles(33)
        candles[30].update(open=100.0, high=109.0, low=99.0, close=108.8)
        candles[31].update(open=99.35, high=100.8, low=98.95, close=100.65)
        candles[32].update(open=100.6, high=101.8, low=100.45, close=101.65)

        result = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER")

        self.assertEqual(result["status"], "READY")
        self.assertTrue(result["primary_zone"]["news_spike_risk"])
        self.assertEqual(result["entry_events"], [])
        self.assertEqual(result["entry_event_status"], "WAITING_CONFIRMATION")

    def test_rejects_buy_origin_in_premium_and_sell_origin_in_discount(self) -> None:
        premium_buy = base_candles()
        premium_buy[30].update(open=100.80, high=102.80, low=100.60, close=102.60)
        discount_sell = base_candles()
        discount_sell[30].update(open=99.20, high=99.40, low=97.20, close=97.40)

        buy_result = self.engine.calculate(premium_buy, "5M", "MATCHED_PROVIDER")
        sell_result = self.engine.calculate(discount_sell, "5M", "MATCHED_PROVIDER")

        self.assertEqual(buy_result["status"], "NO_DIAMOND_ZONE")
        self.assertEqual(sell_result["status"], "NO_DIAMOND_ZONE")

    def test_rejects_local_discount_when_wider_range_is_still_premium(self) -> None:
        candles = base_candles(40)
        candles[15].update(open=91.0, high=91.3, low=90.0, close=90.8)
        candles[30].update(open=100.0, high=103.2, low=99.0, close=103.0)
        for index in range(31, len(candles)):
            candles[index].update(open=102.8, high=103.2, low=102.2, close=102.7)

        result = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER")

        self.assertEqual(result["status"], "NO_DIAMOND_ZONE")
        blockers = {item["id"] for item in result["gate_funnel"]["top_blockers"]}
        self.assertIn("POOR_WIDER_RANGE_LOCATION", blockers)

    def test_htf_direction_conflict_cannot_become_entry_grade(self) -> None:
        candles = base_candles(35)
        candles[30].update(open=100.0, high=103.20, low=99.0, close=103.0)
        candles[31].update(open=102.8, high=103.2, low=102.2, close=102.6)
        candles[32].update(open=102.5, high=102.8, low=101.7, close=102.1)
        candles[33].update(open=99.20, high=99.90, low=98.95, close=99.75)
        candles[34].update(open=99.70, high=100.40, low=99.60, close=100.25)

        result = self.engine.calculate(
            candles,
            "5M",
            "MATCHED_PROVIDER",
            session_context={"stance": "BEARISH"},
        )

        self.assertEqual(result["entry_events"], [])
        bullish = next(zone for zone in result["zones"] if zone["direction"] == "BULLISH")
        self.assertFalse(bullish["entry_eligible_origin"])
        self.assertFalse(bullish["direction_aligned"])
        self.assertIn("HTF_DIRECTION_CONFLICT", bullish["origin_disqualifiers"])

    def test_every_observation_has_auditable_score_and_only_gradeable_zones_are_visible(self) -> None:
        candles = base_candles(40)
        candles[30].update(open=100.0, high=104.0, low=99.20, close=103.80)
        candles[31].update(open=104.0, high=104.20, low=100.50, close=100.70)
        for index in range(32, len(candles)):
            candles[index].update(open=101.5, high=102.0, low=101.0, close=101.4)

        result = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER")

        self.assertTrue(result["zones"])
        for zone in result["zones"]:
            self.assertGreaterEqual(zone["diamond_score"], 0)
            self.assertLessEqual(zone["diamond_score"], 100)
            self.assertEqual(zone["grade_model"], "DIAMOND_GRADE_V2_SCORE_GATED")
            self.assertEqual(
                set(zone["score_components"]),
                {"origin", "location", "structure", "discovery", "lifecycle", "rejection", "confirmation", "risk"},
            )
            if zone["display_as_diamond"]:
                self.assertTrue(zone["strategy_confirmed_origin"])
                self.assertGreaterEqual(zone["diamond_score"], result["minimum_visible_diamond_score"])
                self.assertIn(zone["diamond_grade"], {"A+", "A", "B", "C", "D"})
            else:
                self.assertTrue(
                    not zone["strategy_confirmed_origin"]
                    or zone["diamond_score"] < result["minimum_visible_diamond_score"]
                    or zone["diamond_confidence_tier"] == "INVALIDATED"
                )
            if zone["entry_score_qualified"]:
                self.assertGreaterEqual(zone["diamond_score"], 60)
                self.assertIn(zone["diamond_grade"], {"A+", "A", "B", "C"})

        self.assertTrue(all(zone["display_as_diamond"] for zone in result["visible_zones"]))

    def test_diamond_grade_boundaries_enforce_watch_and_entry_floors(self) -> None:
        self.assertIsNone(self.engine._diamond_grade(49))
        self.assertIsNone(self.engine._diamond_grade(44, minimum_d_score=45))
        self.assertEqual(self.engine._diamond_grade(45, minimum_d_score=45), "D")
        self.assertEqual(self.engine._diamond_grade(50), "D")
        self.assertEqual(self.engine._diamond_grade(59), "D")
        self.assertEqual(self.engine._diamond_grade(60), "C")
        self.assertEqual(self.engine._diamond_grade(70), "B")
        self.assertEqual(self.engine._diamond_grade(80), "A")
        self.assertEqual(self.engine._diamond_grade(90), "A+")
        self.assertIsNone(self.engine._diamond_grade(95, invalidated=True))

    def test_recent_context_cannot_evict_an_active_entry_qualified_origin(self) -> None:
        candidates = [
            {"id": "qualified", "time": 100, "bar_index": 20, "direction": "BULLISH", "line": 100.0, "atr_14": 1.0, "entry_eligible_origin": True},
            {"id": "context-1", "time": 101, "bar_index": 21, "direction": "BEARISH", "line": 104.0, "atr_14": 1.0, "entry_eligible_origin": False},
            {"id": "context-2", "time": 102, "bar_index": 22, "direction": "BULLISH", "line": 108.0, "atr_14": 1.0, "entry_eligible_origin": False},
        ]

        selected = self.engine._distinct_recent(
            candidates,
            2,
            {"entry_window_bars": 4, "follow_window_bars": 2},
        )

        self.assertIn("qualified", {item["id"] for item in selected})
        self.assertEqual(len(selected), 2)

    def test_weak_candles_do_not_create_synthetic_zone(self) -> None:
        result = self.engine.calculate(base_candles(), "5M", "MATCHED_PROVIDER")

        self.assertEqual(result["status"], "NO_DIAMOND_ZONE")
        self.assertEqual(result["zones"], [])
        self.assertIsNone(result["primary_zone"])
        self.assertEqual(result["gate_funnel"]["status"], "WAITING_AT_GATE")
        self.assertGreater(result["gate_funnel"]["stages"][0]["count"], 0)
        self.assertTrue(result["gate_funnel"]["top_blockers"])
        self.assertIn("scoring 45 or higher", result["signal_integrity"]["production_signal_rule"])

    def test_adaptive_xau_impulse_still_requires_a_closed_reaction_before_entry(self) -> None:
        candles = base_candles()
        candles[30].update(open=100.42, high=102.40, low=99.80, close=101.75)
        for index in range(31, len(candles)):
            candles[index].update(open=101.70, high=102.05, low=101.45, close=101.82)

        xau = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER", symbol="XAUUSD")
        standard = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER", symbol="BTCUSD")

        self.assertEqual(xau["status"], "READY")
        self.assertTrue(xau["primary_zone"]["display_as_diamond"])
        self.assertIn(xau["primary_zone"]["diamond_grade"], {"C", "D"})
        self.assertTrue(xau["primary_zone"]["execution_impulse_ready"])
        self.assertTrue(xau["primary_zone"]["entry_eligible_origin"])
        self.assertTrue(xau["primary_zone"]["entry_score_qualified"])
        self.assertEqual(xau["primary_zone"]["entry_stage"], "WAITING_RETEST")
        self.assertFalse(xau["primary_zone"]["actionable_entry"])
        self.assertEqual(xau["entry_events"], [])
        self.assertEqual(standard["status"], "READY")
        self.assertTrue(standard["primary_zone"]["execution_impulse_ready"])

    def test_xau_5m_confirms_first_controlled_scalp_reaction(self) -> None:
        rows = base_candles(33)
        rows[30].update(open=100.80, high=101.80, low=100.70, close=101.60)
        rows[31].update(open=101.60, high=101.70, low=101.15, close=101.25)
        rows[32].update(open=101.25, high=101.82, low=101.20, close=101.76)
        zone = {
            "id": f"buy-{rows[30]['time']}",
            "time": rows[30]["time"],
            "direction": "BULLISH",
            "entry_side": "BUY",
            "signal_label": "DIAMOND_BUY",
            "line": 100.70,
            "low": 100.58,
            "high": 100.82,
            "atr_14": 1.0,
            "entry_location_score": 70,
            "wider_entry_location_score": 72,
            "origin_quality_score": 70,
            "origin_model": "COMPRESSION_BREAK",
            "liquidity_sweep": False,
            "structure_break": False,
            "compression_break": True,
            "trend_pullback_reclaim": False,
            "active_structure": True,
            "wider_trend_direction": "BULLISH",
            "news_spike_risk": False,
            "direction_aligned": True,
        }

        event = self.engine._scalp_first_reaction_event(
            rows,
            zone,
            30,
            self.engine._profile("XAUUSD", "5M"),
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["time"], rows[32]["time"])
        self.assertEqual(event["entry_pathway"], "SCALP_FIRST_REACTION")
        self.assertEqual(event["confirmation_model"], "ACTIVE_SCALP_FIRST_REACTION_CLOSE")
        self.assertEqual(event["confirmation_delay_bars"], 2)
        self.assertTrue(event["scalp_confirmation"])
        self.assertGreaterEqual(event["quality_score"], 70)
        self.assertLessEqual(event["risk_atr"], 1.65)

    def test_scalp_reaction_rejects_opposite_wider_trend(self) -> None:
        rows = base_candles(33)
        rows[30].update(open=100.80, high=101.80, low=100.70, close=101.60)
        rows[31].update(open=101.60, high=101.70, low=101.15, close=101.25)
        rows[32].update(open=101.25, high=101.82, low=101.20, close=101.76)
        zone = {
            "id": f"buy-{rows[30]['time']}",
            "time": rows[30]["time"],
            "direction": "BULLISH",
            "entry_side": "BUY",
            "signal_label": "DIAMOND_BUY",
            "line": 100.70,
            "low": 100.58,
            "high": 100.82,
            "atr_14": 1.0,
            "entry_location_score": 70,
            "wider_entry_location_score": 72,
            "origin_quality_score": 70,
            "origin_model": "COMPRESSION_BREAK",
            "liquidity_sweep": False,
            "structure_break": False,
            "compression_break": True,
            "trend_pullback_reclaim": False,
            "active_structure": True,
            "wider_trend_direction": "BEARISH",
            "news_spike_risk": False,
            "direction_aligned": True,
        }

        event = self.engine._scalp_first_reaction_event(
            rows,
            zone,
            30,
            self.engine._profile("XAUUSD", "5M"),
        )

        self.assertIsNone(event)

    def test_scalp_reaction_rejects_compression_at_weak_location(self) -> None:
        rows = base_candles(33)
        rows[30].update(open=100.80, high=101.80, low=100.70, close=101.60)
        rows[31].update(open=101.60, high=101.70, low=101.15, close=101.25)
        rows[32].update(open=101.25, high=101.82, low=101.20, close=101.76)
        zone = {
            "id": f"buy-{rows[30]['time']}",
            "time": rows[30]["time"],
            "direction": "BULLISH",
            "entry_side": "BUY",
            "signal_label": "DIAMOND_BUY",
            "line": 100.70,
            "low": 100.58,
            "high": 100.82,
            "atr_14": 1.0,
            "entry_location_score": 69,
            "wider_entry_location_score": 82,
            "origin_quality_score": 84,
            "origin_model": "COMPRESSION_BREAK",
            "active_structure": True,
            "wider_trend_direction": "BULLISH",
            "news_spike_risk": False,
            "direction_aligned": True,
        }

        event = self.engine._scalp_first_reaction_event(
            rows,
            zone,
            30,
            self.engine._profile("XAUUSD", "5M"),
        )

        self.assertIsNone(event)

    def test_scalp_fast_path_uses_asset_specific_5m_profiles(self) -> None:
        self.assertTrue(self.engine._profile("XAUUSD", "5M")["scalp_first_reaction_enabled"])
        self.assertFalse(self.engine._profile("XAUUSD", "15M")["scalp_first_reaction_enabled"])
        self.assertTrue(self.engine._profile("BTCUSD", "5M")["scalp_first_reaction_enabled"])
        self.assertEqual(self.engine._profile("BTCUSD", "5M")["asset_model"], "BTC_CONTINUATION")
        self.assertEqual(self.engine._profile("XAUUSD", "5M")["entry_cooldown_bars"], 8)
        self.assertEqual(self.engine._profile("XAUUSD", "5M")["min_scalp_compression_location_score"], 70)

    def test_v7_adaptive_profile_adds_patience_without_lowering_quiet_market_quality(self) -> None:
        rows = base_candles(110)
        for index, row in enumerate(rows):
            width = 1.4 if index < 86 else 0.55
            row.update(high=100 + width / 2, low=100 - width / 2)
        base = self.engine._profile("XAUUSD", "5M")
        adaptive = self.engine._adaptive_profile(base, rows, "XAUUSD", "5M")

        self.assertEqual(adaptive["adaptive_regime"], "QUIET")
        self.assertEqual(adaptive["min_entry_quality"], base["min_entry_quality"])
        self.assertGreater(adaptive["entry_window_bars"], base["entry_window_bars"])

    def test_v7_elevated_regime_tightens_confirmation_and_anti_chase(self) -> None:
        rows = base_candles(110)
        for index, row in enumerate(rows):
            width = 0.65 if index < 86 else 1.6
            row.update(high=100 + width / 2, low=100 - width / 2)
        base = self.engine._profile("BTCUSD", "5M")
        adaptive = self.engine._adaptive_profile(base, rows, "BTCUSD", "5M")

        self.assertEqual(adaptive["adaptive_regime"], "ELEVATED")
        self.assertGreater(adaptive["min_entry_quality"], base["min_entry_quality"])
        self.assertLess(adaptive["max_live_chase_atr"], base["max_live_chase_atr"])

    def test_adaptive_density_keeps_only_strongest_nearby_flip_cluster(self) -> None:
        profile = self.engine._profile("XAUUSD", "5M") | {
            "zone_merge_distance_atr": 0.30,
            "zone_merge_window_bars": 8,
        }
        candidates = [
            {"id": "weak", "direction": "BULLISH", "line": 100.0, "atr_14": 2.0, "bar_index": 30, "time": 30, "score": 62, "origin_quality_score": 64, "entry_eligible_origin": True},
            {"id": "strong", "direction": "BULLISH", "line": 100.2, "atr_14": 2.0, "bar_index": 34, "time": 34, "score": 72, "origin_quality_score": 78, "entry_eligible_origin": True},
            {"id": "separate", "direction": "BEARISH", "line": 100.1, "atr_14": 2.0, "bar_index": 35, "time": 35, "score": 68, "origin_quality_score": 70, "entry_eligible_origin": True},
        ]

        selected = self.engine._distinct_recent(candidates, 10, profile)

        self.assertEqual({item["id"] for item in selected}, {"strong"})

    def test_strong_trend_guard_blocks_single_wick_countertrend_origin(self) -> None:
        candles = []
        for index in range(64):
            opened = 100.0 + index * 0.45
            close = opened + 0.32
            candles.append({
                "time": 1_700_000_000 + index * 300,
                "open": opened,
                "high": close + 0.10,
                "low": opened - 0.10,
                "close": close,
                "is_complete": True,
            })
        candles[-1].update(open=129.1, high=132.6, low=128.7, close=129.0)
        rows = self.engine._candles(candles)
        profile = self.engine._style_adjusted_profile(
            self.engine._profile("XAUUSD", "5M"),
            "SCALPING",
            "5M",
        )
        atr = self.engine._atr_at(rows, len(rows) - 1, 14)
        trend = self.engine._trend_context_at(rows, len(rows) - 1, atr, profile)

        candidate = self.engine._scalp_wick_rejection_candidate(
            rows,
            len(rows) - 1,
            atr,
            profile,
            "MIXED",
            trend,
        )

        self.assertTrue(trend["is_strong"])
        self.assertEqual(trend["direction"], "BULLISH")
        self.assertIsNone(candidate)

    def test_scalp_and_swing_profiles_adjust_timing_without_lowering_quality(self) -> None:
        base_5m = self.engine._profile("XAUUSD", "5M")
        scalp = self.engine._style_adjusted_profile(base_5m, "SCALPING", "5M")
        base_1h = self.engine._profile("XAUUSD", "1H")
        swing = self.engine._style_adjusted_profile(base_1h, "SWING", "1H")

        self.assertEqual(scalp["target_diamonds_per_100_bars"], "5-8")
        self.assertEqual(scalp["core_execution_timeframe"], "5M")
        self.assertEqual(scalp["core_structure_timeframe"], "1H")
        self.assertLess(scalp["entry_cooldown_bars"], base_5m["entry_cooldown_bars"])
        self.assertEqual(scalp["min_entry_quality"], base_5m["min_entry_quality"])
        self.assertEqual(swing["target_diamonds_per_100_bars"], "3-5")
        self.assertEqual(swing["core_execution_timeframe"], "1H")
        self.assertEqual(swing["core_structure_timeframe"], "1D")
        self.assertGreater(swing["lead_zone_max_age_bars"], base_1h["lead_zone_max_age_bars"])
        self.assertGreaterEqual(swing["min_entry_quality"], base_1h["min_entry_quality"])

    def test_scalp_lead_floor_adapts_without_lowering_confirmed_entry_quality(self) -> None:
        base = self.engine._profile("XAUUSD", "5M")

        quiet = self.engine._style_adjusted_profile(
            base | {"adaptive_regime": "QUIET"},
            "SCALPING",
            "5M",
        )
        normal = self.engine._style_adjusted_profile(
            base | {"adaptive_regime": "NORMAL"},
            "SCALPING",
            "5M",
        )
        elevated = self.engine._style_adjusted_profile(
            base | {"adaptive_regime": "ELEVATED"},
            "SCALPING",
            "5M",
        )

        self.assertEqual((quiet["lead_diamond_score"], normal["lead_diamond_score"], elevated["lead_diamond_score"]), (62, 64, 67))
        self.assertEqual(quiet["min_entry_quality"], base["min_entry_quality"])
        self.assertEqual(normal["min_entry_quality"], base["min_entry_quality"])
        self.assertEqual(elevated["min_entry_quality"], base["min_entry_quality"])

    def test_countertrend_scalp_wick_stays_internal_until_strategy_confirms(self) -> None:
        candles = base_candles(38)
        origin_time = candles[30]["time"]
        candles[30].update(open=100.0, high=104.0, low=99.8, close=102.0)
        for index in range(31, len(candles)):
            candles[index].update(open=101.8, high=102.4, low=101.4, close=101.9)

        result = self.engine.calculate(
            candles,
            "5M",
            "MATCHED_PROVIDER",
            session_context={"stance": "BULLISH"},
            symbol="XAUUSD",
            trading_style="SCALPING",
        )
        rejection_zones = [
            zone for zone in result["zones"]
            if zone.get("origin_model") == "SCALP_WICK_REJECTION"
        ]

        self.assertEqual(len(rejection_zones), 1)
        zone = rejection_zones[0]
        self.assertEqual(zone["time"], origin_time)
        self.assertEqual(zone["entry_side"], "SELL")
        self.assertEqual(zone["line"], 104.0)
        self.assertFalse(zone["strategy_confirmed_origin"])
        self.assertFalse(zone["display_as_diamond"])
        self.assertFalse(zone["is_lead_diamond"])
        self.assertFalse(zone["entry_eligible_origin"])
        self.assertEqual(zone["entry_blocker"], "STRATEGY_SETUP_NOT_CONFIRMED")
        self.assertIn("SCALP_COUNTERTREND_WATCH", zone["diamond_confidence_reasons"])
        self.assertEqual(result["entry_events"], [])

    def test_scalp_wick_rejection_ignores_small_or_weak_wick_candles(self) -> None:
        rows = self.engine._candles(base_candles(38))
        profile = self.engine._style_adjusted_profile(
            self.engine._profile("XAUUSD", "5M"),
            "SCALPING",
            "5M",
        )
        rows[30].update(open=100.0, high=101.1, low=99.9, close=101.0)

        candidate = self.engine._scalp_wick_rejection_candidate(
            rows,
            30,
            1.1,
            profile,
            "MIXED",
        )

        self.assertIsNone(candidate)

    def test_news_shock_guard_suppresses_new_entry_but_preserves_history_policy(self) -> None:
        candles = base_candles(35)
        candles[30].update(open=100.0, high=103.20, low=99.0, close=103.0)
        candles[31].update(open=102.8, high=103.2, low=102.2, close=102.6)
        candles[32].update(open=102.5, high=102.8, low=101.7, close=102.1)
        candles[33].update(open=99.20, high=99.90, low=98.95, close=99.75)
        candles[34].update(open=99.70, high=100.40, low=99.60, close=100.25)

        result = self.engine.calculate(
            candles,
            "5M",
            "MATCHED_PROVIDER",
            analysis_context={
                "news_intelligence": {
                    "execution_gate": "BLOCK_NEW_ENTRIES",
                    "summary": "High-impact release window",
                    "primary_event": {"title": "US CPI"},
                },
            },
        )

        self.assertEqual(result["news_shock_guard"]["status"], "LOCKED")
        self.assertTrue(result["news_shock_guard"]["history_preserved"])
        self.assertEqual(result["lead_diamond_status"], "SCANNING")
        self.assertEqual(result["entry_events"], [])
        self.assertIn("High-impact", result["next_trigger"])

    def test_same_side_cooldown_keeps_spatially_distinct_zones(self) -> None:
        profile = self.engine._profile("XAUUSD", "5M")
        events = [
            {"id": "first", "time": 1_700_000_000, "entry_side": "BUY", "line": 100.0, "atr_14": 10.0, "quality_score": 65},
            {"id": "distinct", "time": 1_700_000_300, "entry_side": "BUY", "line": 106.0, "atr_14": 10.0, "quality_score": 66},
            {"id": "replacement", "time": 1_700_000_600, "entry_side": "BUY", "line": 100.5, "atr_14": 10.0, "quality_score": 74},
        ]

        selected = self.engine._distinct_entry_events(events, profile)

        self.assertEqual({item["id"] for item in selected}, {"distinct", "replacement"})

    def test_lead_diamond_publishes_only_one_fresh_grade_b_zone(self) -> None:
        profile = self.engine._profile("XAUUSD", "5M")
        base = {
            "display_as_diamond": True,
            "strategy_confirmed_origin": True,
            "entry_eligible_origin": True,
            "lifecycle": "FRESH",
            "zone_health": "WATCH",
            "origin_broken": False,
            "direction_holding": True,
            "distance_atr": 0.8,
            "direction": "BULLISH",
            "display_role": "QUALIFIED_WATCH",
            "execution_quality": "WATCH",
            "price_side": "ABOVE",
        }
        zones = [
            {**base, "id": "weak-c", "diamond_score": 68, "age_bars": 2, "time": 100},
            {**base, "id": "lead-b", "diamond_score": 75, "age_bars": 4, "time": 200},
            {**base, "id": "stale-a", "diamond_score": 84, "age_bars": 25, "time": 300},
        ]

        lead = self.engine._lead_diamond_zone(zones, [], "BULLISH", profile)

        self.assertEqual(lead["id"], "lead-b")

    def test_lead_diamond_rejects_opposite_or_invalidated_zone(self) -> None:
        profile = self.engine._profile("XAUUSD", "5M")
        zones = [{
            "id": "opposite",
            "display_as_diamond": True,
            "strategy_confirmed_origin": True,
            "entry_eligible_origin": True,
            "diamond_score": 82,
            "lifecycle": "FRESH",
            "zone_health": "WATCH",
            "origin_broken": False,
            "direction_holding": True,
            "age_bars": 2,
            "distance_atr": 0.5,
            "direction": "BEARISH",
            "display_role": "QUALIFIED_WATCH",
            "execution_quality": "READY",
            "price_side": "BELOW",
            "time": 100,
        }]

        self.assertIsNone(self.engine._lead_diamond_zone(zones, [], "BULLISH", profile))

    def test_lead_diamond_rejects_context_only_zone(self) -> None:
        profile = self.engine._profile("XAUUSD", "5M")
        zones = [{
            "id": "context-only",
            "display_as_diamond": True,
            "strategy_confirmed_origin": True,
            "entry_eligible_origin": True,
            "diamond_score": 78,
            "lifecycle": "FRESH",
            "zone_health": "WATCH",
            "origin_broken": False,
            "direction_holding": True,
            "age_bars": 2,
            "distance_atr": 0.5,
            "direction": "BULLISH",
            "display_role": "QUALIFIED_WATCH",
            "execution_quality": "CONTEXT_ONLY",
            "price_side": "ABOVE",
            "time": 100,
        }]

        self.assertIsNone(self.engine._lead_diamond_zone(zones, [], "BULLISH", profile))

    def test_high_score_without_confirmed_strategy_never_becomes_lead_diamond(self) -> None:
        profile = self.engine._profile("XAUUSD", "5M")
        zone = {
            "id": "score-only",
            "display_as_diamond": True,
            "strategy_confirmed_origin": False,
            "entry_eligible_origin": True,
            "diamond_score": 99,
            "lifecycle": "FRESH",
            "zone_health": "WATCH",
            "origin_broken": False,
            "direction_holding": True,
            "age_bars": 1,
            "distance_atr": 0.2,
            "direction": "BULLISH",
            "display_role": "QUALIFIED_WATCH",
            "execution_quality": "READY",
            "price_side": "ABOVE",
            "time": 100,
        }

        self.assertIsNone(self.engine._lead_diamond_zone([zone], [], "BULLISH", profile))

    def test_historical_confirmed_event_survives_after_live_zone_flips_without_staying_visible(self) -> None:
        candles = base_candles(40)
        candles[30].update(open=100.0, high=103.20, low=99.0, close=103.0)
        candles[31].update(open=102.8, high=103.2, low=102.2, close=102.6)
        candles[32].update(open=102.5, high=102.8, low=101.7, close=102.1)
        candles[33].update(open=99.20, high=99.90, low=98.95, close=99.75)
        candles[34].update(open=99.70, high=100.40, low=99.60, close=100.25)
        for index in range(35, len(candles)):
            candles[index].update(open=98.6, high=98.9, low=97.9, close=98.2)

        result = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER")
        event = result["latest_entry_event"]
        origin = next(zone for zone in result["zones"] if zone["id"] == event["zone_id"])

        self.assertEqual(event["signal_tier"], "CONFIRMED")
        self.assertIn(event["diamond_grade"], {"A+", "A", "B", "C"})
        self.assertEqual(origin["lifecycle"], "FLIPPED")
        self.assertFalse(origin["display_as_diamond"])
        self.assertNotIn(origin["id"], {zone["id"] for zone in result["visible_zones"]})

    def test_combines_trusted_1h_15m_5m_without_inventing_a_signal(self) -> None:
        def frame(bias: str, trusted: bool = True):
            return {
                "status": "READY",
                "execution_trusted": trusted,
                "directional_bias": bias,
                "expected_direction": "BEARISH",
                "strategy_state": "BEARISH_REJECTION" if bias == "SELL_CONTEXT" else "WAIT_CONFIRMATION",
                "confirmation_state": "CONFIRMED_REJECTION" if bias == "SELL_CONTEXT" else "HOLDING_ABOVE",
                "quality_grade": "A",
                "execution_quality": "READY",
                "primary_zone": {
                    "line": 100.0,
                    "role": "RESISTANCE",
                    "lifecycle": "FRESH",
                },
            }

        result = self.engine.combine_timeframes({
            "1H": frame("SELL_CONTEXT"),
            "15M": frame("SELL_CONTEXT"),
            "5M": frame("WAIT"),
        })

        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["state"], "PARTIAL_BEARISH")
        self.assertEqual(result["score"], -92)
        self.assertEqual(result["risk_filter"], "WAIT")
        self.assertEqual(result["ready_timeframes"], 1)
        self.assertEqual(result["trading_style"], "SCALPING")
        self.assertEqual(result["required_timeframes"], ["15M", "5M"])
        self.assertFalse(result["style_confirmation"]["frames_agree"])
        self.assertEqual(result["style_confirmation"]["status"], "WAITING")

    def test_untrusted_timeframe_is_excluded_from_mtf_score(self) -> None:
        def frame(bias: str, trusted: bool):
            return {
                "status": "READY",
                "execution_trusted": trusted,
                "directional_bias": bias,
                "expected_direction": "BULLISH",
                "quality_grade": "A",
                "execution_quality": "READY",
                "confirmation_state": "CONFIRMED_HOLD",
                "primary_zone": {"line": 100.0, "lifecycle": "FRESH"},
            }

        result = self.engine.combine_timeframes({
            "1H": frame("SELL_CONTEXT", False),
            "15M": frame("BUY_CONTEXT", True),
            "5M": frame("BUY_CONTEXT", True),
        })

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["score"], 92)
        self.assertEqual(result["state"], "ALIGNED_BULLISH")
        self.assertTrue(result["style_confirmation"]["frames_agree"])
        self.assertEqual(result["style_confirmation"]["status"], "CONFIRMED")
        self.assertNotIn("1H", result["timeframes"])

    def test_single_ready_timeframe_cannot_claim_mtf_alignment(self) -> None:
        result = self.engine.combine_timeframes({
            "15M": {
                "status": "READY",
                "execution_trusted": True,
                "directional_bias": "BUY_CONTEXT",
                "expected_direction": "BULLISH",
                "quality_grade": "A+",
                "execution_quality": "READY",
                "confirmation_state": "CONFIRMED_HOLD",
                "primary_zone": {"line": 100.0, "lifecycle": "FRESH"},
            },
            "5M": {"status": "NO_DIAMOND_ZONE", "execution_trusted": False},
        })

        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["state"], "PARTIAL_BULLISH")
        self.assertEqual(result["direction"], "MIXED")
        self.assertEqual(result["risk_filter"], "WAIT")

    def test_grade_d_watch_does_not_count_as_mtf_entry_confirmation(self) -> None:
        def frame(grade: str, score: int, entry_ready: bool):
            return {
                "status": "READY",
                "execution_trusted": True,
                "diamond_display_status": "READY",
                "directional_bias": "BUY_CONTEXT",
                "expected_direction": "BULLISH",
                "quality_grade": grade,
                "execution_quality": "READY",
                "confirmation_state": "CONFIRMED_HOLD",
                "primary_zone": {
                    "line": 100.0,
                    "lifecycle": "FRESH",
                    "diamond_grade": grade,
                    "diamond_score": score,
                    "entry_score_qualified": entry_ready,
                },
            }

        result = self.engine.combine_timeframes({
            "15M": frame("C", 64, True),
            "5M": frame("D", 58, False),
        })

        self.assertTrue(result["timeframes"]["15M"]["entry_grade_ready"])
        self.assertFalse(result["timeframes"]["5M"]["entry_grade_ready"])
        self.assertEqual(result["ready_timeframes"], 1)
        self.assertEqual(result["risk_filter"], "WAIT")

    def test_swing_profile_requires_4h_and_1h_confirmation(self) -> None:
        def frame(bias: str):
            return {
                "status": "READY",
                "execution_trusted": True,
                "directional_bias": bias,
                "expected_direction": "BULLISH",
                "quality_grade": "A",
                "execution_quality": "READY",
                "confirmation_state": "CONFIRMED_HOLD",
                "primary_zone": {"line": 100.0, "lifecycle": "FRESH"},
            }

        result = self.engine.combine_timeframes({
            "4H": frame("BUY_CONTEXT"),
            "1H": frame("BUY_CONTEXT"),
            "15M": frame("SELL_CONTEXT"),
            "5M": frame("SELL_CONTEXT"),
        }, "SWING")

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["state"], "ALIGNED_BULLISH")
        self.assertEqual(result["trading_style"], "SWING")
        self.assertEqual(result["required_timeframes"], ["4H", "1H"])
        self.assertEqual(result["execution_timeframe"], "1H")
        self.assertEqual(result["confirmation_timeframe"], "4H")
        self.assertEqual(result["style_confirmation"]["direction_timeframe"], "4H")
        self.assertEqual(result["style_confirmation"]["trigger_timeframe"], "1H")
        self.assertTrue(result["style_confirmation"]["frames_agree"])
        self.assertNotIn("15M", result["timeframes"])


if __name__ == "__main__":
    unittest.main()
