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
        self.assertEqual(result["strategy"], "SH_DIAMOND_ZONE_V6_SIMPLE_DISCOVERY")
        self.assertEqual(result["profile"], "XAU_SIMPLE_DISCOVERY_V6_7_5M")
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
            "origin_model": "LIQUIDITY_SWEEP",
            "liquidity_sweep": True,
            "structure_break": False,
            "compression_break": False,
            "trend_pullback_reclaim": False,
            "news_spike_risk": False,
            "direction_aligned": True,
            "close_strength": 0.80,
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

    def test_confirms_active_shallow_pullback_without_waiting_for_deep_retest(self) -> None:
        candles = base_candles(33)
        origin_time = candles[30]["time"]
        candles[30].update(open=100.0, high=102.40, low=99.0, close=102.20)
        candles[31].update(open=102.20, high=102.30, low=101.40, close=101.60)
        candles[32].update(open=101.60, high=102.50, low=101.50, close=102.40)

        result = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER")
        event = result["latest_entry_event"]

        self.assertEqual(event["zone_id"], f"buy-{origin_time}")
        self.assertEqual(event["time"], candles[32]["time"])
        self.assertEqual(event["available_at"], candles[32]["time"])
        self.assertEqual(event["confirmation_delay_bars"], 2)
        self.assertEqual(event["entry_pathway"], "SHALLOW_PULLBACK_CONTINUATION")
        self.assertEqual(event["confirmation_model"], "ACTIVE_SHALLOW_PULLBACK_CONTINUATION")
        self.assertGreater(event["marker_price"], result["primary_zone"]["high"])
        self.assertLess(event["entry_displacement_atr"], 0.85)
        self.assertGreater(event["origin_line_displacement_atr"], 1.0)
        self.assertGreaterEqual(event["quality_score"], 66)

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
                self.assertGreaterEqual(zone["diamond_score"], result["minimum_visible_diamond_score"])
                self.assertIn(zone["diamond_grade"], {"A+", "A", "B", "C", "D"})
            else:
                self.assertTrue(zone["diamond_score"] < result["minimum_visible_diamond_score"] or zone["diamond_confidence_tier"] == "INVALIDATED")
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

    def test_marginal_xau_impulse_is_context_only_and_cannot_become_an_entry(self) -> None:
        candles = base_candles()
        candles[30].update(open=100.42, high=102.40, low=99.80, close=101.75)
        for index in range(31, len(candles)):
            candles[index].update(open=101.70, high=102.05, low=101.45, close=101.82)

        xau = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER", symbol="XAUUSD")
        standard = self.engine.calculate(candles, "5M", "MATCHED_PROVIDER", symbol="BTCUSD")

        self.assertEqual(xau["status"], "READY")
        self.assertTrue(xau["primary_zone"]["display_as_diamond"])
        self.assertIn(xau["primary_zone"]["diamond_grade"], {"C", "D"})
        self.assertFalse(xau["primary_zone"]["execution_impulse_ready"])
        self.assertIn("ENTRY_BODY_BELOW_FLOOR", xau["primary_zone"]["execution_impulse_failures"])
        self.assertFalse(xau["primary_zone"]["entry_eligible_origin"])
        self.assertFalse(xau["primary_zone"]["entry_score_qualified"])
        self.assertEqual(xau["entry_events"], [])
        self.assertEqual(standard["status"], "READY")
        self.assertTrue(standard["primary_zone"]["execution_impulse_ready"])

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
