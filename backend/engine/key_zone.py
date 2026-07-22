from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, Iterable, Optional


class DiamondZoneEngine:
    """Detect context zones and non-repainting entries from completed candles."""

    MIN_VISIBLE_DIAMOND_SCORE = 50
    XAU_MIN_VISIBLE_DIAMOND_SCORE = 45
    MIN_ENTRY_DIAMOND_SCORE = 60

    def __init__(
        self,
        strategy_name: str = "SH_DIAMOND_ZONE_V8_6_REGIME_ADAPTIVE",
        engine_version: str = "DIAMOND_V8_6_SETUP_REGIME_GUARDED",
        profile_adjustments: Optional[Dict[str, float]] = None,
        profile_suffix: str = "",
    ) -> None:
        self.strategy_name = strategy_name
        self.engine_version = engine_version
        self.profile_adjustments = dict(profile_adjustments or {})
        self.profile_suffix = str(profile_suffix or "").strip().upper()

    def calculate(
        self,
        candles: Iterable[Dict[str, Any]],
        timeframe: str,
        source: Optional[str] = None,
        session_context: Optional[Dict[str, Any]] = None,
        analysis_context: Optional[Dict[str, Any]] = None,
        symbol: str = "XAUUSD",
        trading_style: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows = self._candles(candles)
        if len(rows) < 30:
            return self._empty("INSUFFICIENT_CLOSED_CANDLES", timeframe, source, len(rows), symbol)

        profile = self._adaptive_profile(self._profile(symbol, timeframe), rows, symbol, timeframe)
        profile = self._style_adjusted_profile(profile, trading_style, timeframe)
        visible_score_floor = int(profile.get("min_visible_diamond_score", self.MIN_VISIBLE_DIAMOND_SCORE))
        expected = self._expected_direction(session_context or {}, analysis_context or {})
        news_context = dict((analysis_context or {}).get("news_intelligence") or {})
        news_guard_active = news_context.get("execution_gate") == "BLOCK_NEW_ENTRIES"
        news_guard_bars = 3 if str(timeframe or "").upper() in {"1M", "5M", "15M"} else 2

        candidates: list[Dict[str, Any]] = []
        funnel_counts: Counter[str] = Counter()
        funnel_blockers: Counter[str] = Counter()
        # Keep a wider completed-candle discovery window so older, still valid
        # structural origins remain available to the chart and audit ledger.
        start = max(15, len(rows) - 260)
        for index in range(start, len(rows)):
            funnel_counts["scanned"] += 1
            row = rows[index]
            candle_range = row["high"] - row["low"]
            if candle_range <= 0:
                funnel_blockers["INVALID_RANGE"] += 1
                continue
            atr = self._atr_at(rows, index, 14)
            if atr is None or atr <= 0:
                funnel_blockers["ATR_NOT_READY"] += 1
                continue
            funnel_counts["volatility_ready"] += 1

            body = abs(row["close"] - row["open"])
            body_ratio = body / candle_range
            range_ratio = candle_range / atr
            direction = "BULLISH" if row["close"] > row["open"] else "BEARISH" if row["close"] < row["open"] else "NEUTRAL"
            if direction == "NEUTRAL":
                funnel_blockers["NO_DIRECTION"] += 1
                continue
            funnel_counts["directional"] += 1
            close_strength = (
                (row["close"] - row["low"]) / candle_range
                if direction == "BULLISH"
                else (row["high"] - row["close"]) / candle_range
            )
            prior = rows[max(0, index - 8):index]
            wider_prior = rows[max(0, index - int(profile["location_window_bars"])):index]
            prior_low = min(item["low"] for item in prior)
            prior_high = max(item["high"] for item in prior)
            wider_low = min(item["low"] for item in wider_prior)
            wider_high = max(item["high"] for item in wider_prior)
            dealing_range = max(prior_high - prior_low, 1e-9)
            wider_dealing_range = max(wider_high - wider_low, 1e-9)
            entry_line = row["low"] if direction == "BULLISH" else row["high"]
            dealing_position = max(0.0, min(1.0, (entry_line - prior_low) / dealing_range))
            wider_dealing_position = max(0.0, min(1.0, (entry_line - wider_low) / wider_dealing_range))
            local_location_score = round(
                (1.0 - dealing_position) * 100
                if direction == "BULLISH"
                else dealing_position * 100
            )
            wider_location_score = round(
                (1.0 - wider_dealing_position) * 100
                if direction == "BULLISH"
                else wider_dealing_position * 100
            )
            entry_location_score = round(local_location_score * 0.42 + wider_location_score * 0.58)
            liquidity_sweep = bool(
                (direction == "BULLISH" and row["low"] < prior_low and row["close"] > prior_low)
                or (direction == "BEARISH" and row["high"] > prior_high and row["close"] < prior_high)
            )
            structure_break = bool(
                prior
                and (
                    (direction == "BULLISH" and row["close"] > max(item["high"] for item in prior))
                    or (direction == "BEARISH" and row["close"] < min(item["low"] for item in prior))
                )
            )
            wider_structure_break = bool(
                wider_prior
                and (
                    (direction == "BULLISH" and row["close"] > wider_high)
                    or (direction == "BEARISH" and row["close"] < wider_low)
                )
            )
            continuation = bool(
                index > 0
                and (
                    (direction == "BULLISH" and row["close"] > rows[index - 1]["close"])
                    or (direction == "BEARISH" and row["close"] < rows[index - 1]["close"])
                )
            )
            compression_window = prior[-4:]
            compression_average = (
                sum(item["high"] - item["low"] for item in compression_window) / len(compression_window)
                if compression_window else atr
            )
            compression_break = bool(
                len(compression_window) == 4
                and compression_average <= atr * profile["max_compression_atr"]
                and range_ratio >= profile["min_compression_break_atr"]
                and (
                    (direction == "BULLISH" and row["close"] > max(item["high"] for item in compression_window))
                    or (direction == "BEARISH" and row["close"] < min(item["low"] for item in compression_window))
                )
            )
            trend_window = prior[-6:]
            trend_direction = (
                "BULLISH" if len(trend_window) >= 4 and trend_window[-1]["close"] > trend_window[0]["close"] + atr * 0.20
                else "BEARISH" if len(trend_window) >= 4 and trend_window[-1]["close"] < trend_window[0]["close"] - atr * 0.20
                else "MIXED"
            )
            fast_mean = sum(item["close"] for item in prior[-5:]) / max(1, len(prior[-5:]))
            slow_sample = wider_prior[-20:]
            slow_mean = sum(item["close"] for item in slow_sample) / max(1, len(slow_sample))
            wider_trend_direction = (
                "BULLISH" if fast_mean > slow_mean + atr * 0.08
                else "BEARISH" if fast_mean < slow_mean - atr * 0.08
                else "MIXED"
            )
            trend_guard = self._trend_context_at(rows, index, atr, profile)
            scalp_rejection = self._scalp_wick_rejection_candidate(
                rows,
                index,
                atr,
                profile,
                expected,
                trend_guard,
            )
            if scalp_rejection:
                candidates.append(scalp_rejection)
                funnel_counts["context_zones"] += 1
                funnel_counts["scalp_rejection_origins"] += 1
                if scalp_rejection.get("entry_eligible_origin"):
                    funnel_counts["qualified_origins"] += 1
            previous = rows[index - 1]
            previous_direction = "BULLISH" if previous["close"] > previous["open"] else "BEARISH" if previous["close"] < previous["open"] else "NEUTRAL"
            trend_pullback_reclaim = bool(
                trend_direction == direction
                and previous_direction not in {direction, "NEUTRAL"}
                and (
                    (direction == "BULLISH" and row["close"] > previous["high"])
                    or (direction == "BEARISH" and row["close"] < previous["low"])
                )
            )
            active_structure = bool(structure_break or compression_break or trend_pullback_reclaim)
            structure_score = 20 if structure_break else 16 if compression_break else 14 if trend_pullback_reclaim else 0
            score = round(min(100, (
                min(body_ratio, 1) * 30
                + min(range_ratio / 2, 1) * 25
                + min(close_strength, 1) * 20
                + structure_score
                + (5 if continuation else 0)
            )))
            impulse_failures = []
            if body_ratio < profile["min_body_ratio"]:
                impulse_failures.append("WEAK_BODY")
            if range_ratio < profile["min_range_ratio"]:
                impulse_failures.append("LOW_RANGE_EXPANSION")
            if close_strength < profile["min_close_strength"]:
                impulse_failures.append("WEAK_CLOSE")
            if score < profile["min_score"]:
                impulse_failures.append("LOW_IMPULSE_SCORE")
            if impulse_failures:
                funnel_blockers.update(impulse_failures)
                continue
            funnel_counts["impulse_quality"] += 1
            if wider_location_score < profile["min_macro_location_score"]:
                funnel_blockers["POOR_WIDER_RANGE_LOCATION"] += 1
                continue
            if entry_location_score < profile["min_entry_location_score"]:
                funnel_blockers["POOR_CONTEXT_LOCATION"] += 1
                continue
            funnel_counts["location_quality"] += 1
            if not (active_structure or range_ratio >= profile["expansion_override"]):
                funnel_blockers["NO_STRUCTURE_OR_EXPANSION"] += 1
                continue
            funnel_counts["structural_context"] += 1

            half_width = max(atr * profile["atr_band"], candle_range * profile["range_band"])
            news_spike_risk = range_ratio >= profile["max_clean_expansion"]
            origin_model = (
                "SWEEP_AND_BREAK"
                if liquidity_sweep and structure_break
                else "LIQUIDITY_SWEEP"
                if liquidity_sweep
                else "COMPRESSION_BREAK"
                if compression_break
                else "TREND_PULLBACK_RECLAIM"
                if trend_pullback_reclaim
                else "STRUCTURE_DISPLACEMENT"
                if structure_break and continuation
                else "EXPANSION_CONTEXT"
            )
            htf_direction_aligned = expected not in {"BULLISH", "BEARISH"} or direction == expected
            strong_trend_direction = str(trend_guard.get("direction") or "MIXED")
            counter_trend = bool(
                trend_guard.get("is_strong")
                and strong_trend_direction in {"BULLISH", "BEARISH"}
                and strong_trend_direction != direction
            )
            counter_trend_reversal_confirmed = bool(
                counter_trend
                and liquidity_sweep
                and structure_break
                and close_strength >= float(profile["counter_trend_min_close_strength"])
                and range_ratio >= float(profile["counter_trend_min_range_atr"])
            )
            trend_guard_allows = bool(not counter_trend or counter_trend_reversal_confirmed)
            direction_aligned = bool(htf_direction_aligned and trend_guard_allows)
            execution_impulse_failures = []
            if body_ratio < profile["entry_min_body_ratio"]:
                execution_impulse_failures.append("ENTRY_BODY_BELOW_FLOOR")
            if range_ratio < profile["entry_min_range_ratio"]:
                execution_impulse_failures.append("ENTRY_RANGE_BELOW_FLOOR")
            if close_strength < profile["entry_min_close_strength"]:
                execution_impulse_failures.append("ENTRY_CLOSE_BELOW_FLOOR")
            if score < profile["entry_min_score"]:
                execution_impulse_failures.append("ENTRY_IMPULSE_SCORE_BELOW_FLOOR")
            execution_impulse_ready = not execution_impulse_failures
            origin_disqualifiers = []
            if not execution_impulse_ready:
                origin_disqualifiers.extend(execution_impulse_failures)
            if entry_location_score < profile["min_execution_location_score"]:
                origin_disqualifiers.append("WEAK_PREMIUM_DISCOUNT_LOCATION")
            if wider_location_score < profile["min_macro_execution_location_score"]:
                origin_disqualifiers.append("WEAK_WIDER_RANGE_LOCATION")
            if not (liquidity_sweep or (active_structure and continuation)):
                origin_disqualifiers.append("NO_STRUCTURAL_OR_LIQUIDITY_EVENT")
            if news_spike_risk:
                origin_disqualifiers.append("OVERSIZED_NEWS_SPIKE")
            if not direction_aligned:
                origin_disqualifiers.append(
                    "COUNTER_TREND_WITHOUT_REVERSAL"
                    if not trend_guard_allows
                    else "HTF_DIRECTION_CONFLICT"
                )
            origin_quality = round(max(0, min(100, (
                score * 0.40
                + entry_location_score * 0.24
                + wider_location_score * 0.12
                + (10 if liquidity_sweep else 0)
                + (7 if structure_break else 0)
                + (6 if compression_break else 0)
                + (5 if trend_pullback_reclaim else 0)
                + (5 if wider_structure_break else 0)
                + (3 if continuation else 0)
                + (4 if direction_aligned and expected in {"BULLISH", "BEARISH"} else 0)
                + (4 if trend_guard.get("is_strong") and strong_trend_direction == direction else 0)
                + (6 if counter_trend_reversal_confirmed else 0)
                - (18 if news_spike_risk else 0)
                - (8 if origin_model == "EXPANSION_CONTEXT" else 0)
                - (14 if not direction_aligned else 0)
            ))))
            if origin_quality < profile["min_origin_quality_for_entry"]:
                origin_disqualifiers.append("ORIGIN_QUALITY_BELOW_ENTRY_FLOOR")
            entry_eligible_origin = bool(
                execution_impulse_ready
                and entry_location_score >= profile["min_execution_location_score"]
                and wider_location_score >= profile["min_macro_execution_location_score"]
                and origin_quality >= profile["min_origin_quality_for_entry"]
                and (liquidity_sweep or (active_structure and continuation))
                and direction_aligned
                and not news_spike_risk
            )
            strategy_confirmed_origin = bool(
                execution_impulse_ready
                and direction_aligned
                and not news_spike_risk
                and (
                    liquidity_sweep
                    or structure_break
                    or compression_break
                    or trend_pullback_reclaim
                )
            )
            funnel_counts["context_zones"] += 1
            if entry_eligible_origin:
                funnel_counts["qualified_origins"] += 1
            else:
                funnel_blockers.update(origin_disqualifiers or ["CONTEXT_ONLY_ORIGIN"])
            candidates.append({
                "id": f"{'buy' if direction == 'BULLISH' else 'sell'}-{row['time']}",
                "time": row["time"],
                "direction": direction,
                "entry_side": "BUY" if direction == "BULLISH" else "SELL",
                "signal_label": "DIAMOND_BUY" if direction == "BULLISH" else "DIAMOND_SELL",
                "entry_anchor": "CANDLE_LOW" if direction == "BULLISH" else "CANDLE_HIGH",
                "line": entry_line,
                "low": entry_line - half_width,
                "high": entry_line + half_width,
                "score": score,
                "atr_14": atr,
                "body_ratio": body_ratio,
                "range_ratio": range_ratio,
                "close_strength": close_strength,
                "impulse_open": row["open"],
                "impulse_close": row["close"],
                "impulse_high": row["high"],
                "impulse_low": row["low"],
                "dealing_range_position": dealing_position,
                "wider_dealing_range_position": wider_dealing_position,
                "local_entry_location_score": local_location_score,
                "wider_entry_location_score": wider_location_score,
                "entry_location_score": entry_location_score,
                "liquidity_sweep": liquidity_sweep,
                "structure_break": structure_break,
                "wider_structure_break": wider_structure_break,
                "compression_break": compression_break,
                "trend_pullback_reclaim": trend_pullback_reclaim,
                "wider_trend_direction": wider_trend_direction,
                "trend_regime": trend_guard.get("regime"),
                "trend_direction": strong_trend_direction,
                "trend_strength": trend_guard.get("strength"),
                "trend_metrics": trend_guard.get("metrics") or {},
                "strong_trend_guard": "PASS" if trend_guard_allows else "BLOCK_COUNTER_TREND",
                "counter_trend": counter_trend,
                "counter_trend_reversal_confirmed": counter_trend_reversal_confirmed,
                "active_structure": active_structure,
                "continuation": continuation,
                "expected_direction_at_origin": expected,
                "direction_aligned": direction_aligned,
                "origin_model": origin_model,
                "origin_quality_score": origin_quality,
                "origin_quality_grade": self._quality_grade(origin_quality),
                "context_quality_passed": True,
                "execution_impulse_ready": execution_impulse_ready,
                "execution_impulse_failures": execution_impulse_failures,
                "entry_eligible_origin": entry_eligible_origin,
                "strategy_confirmed_origin": strategy_confirmed_origin,
                "origin_disqualifiers": origin_disqualifiers,
                "news_spike_risk": news_spike_risk,
                "bar_index": index,
            })

        zones = self._distinct_recent(candidates, int(profile["context_zone_limit"]), profile)
        if not zones:
            result = self._empty("NO_DIAMOND_ZONE", timeframe, source, len(rows), symbol)
            result["current_price"] = round(rows[-1]["close"], 5)
            result["gate_funnel"] = self._gate_funnel(funnel_counts, funnel_blockers, [])
            return result

        current = rows[-1]
        candle_color = "BULLISH" if current["close"] > current["open"] else "BEARISH" if current["close"] < current["open"] else "NEUTRAL"
        current_atr = self._atr_at(rows, len(rows) - 1, 14) or zones[0]["atr_14"]
        for zone in zones:
            zone["retests"] = self._retests(rows, zone)
            zone["age_bars"] = max(0, len(rows) - 1 - zone["bar_index"])
            zone["price_side"] = self._price_side(current["close"], zone)
            zone["role"] = (
                "SUPPORT" if zone["price_side"] == "ABOVE"
                else "RESISTANCE" if zone["price_side"] == "BELOW"
                else "TESTING"
            )
            zone["origin_broken"] = self._origin_broken(rows, zone)
            zone["lifecycle"] = self._lifecycle(zone)
            age_penalty = min(14, max(0, zone["age_bars"] - 48) // 12 * 2)
            retest_penalty = max(0, zone["retests"] - 1) * 4
            flip_penalty = 10 if zone["origin_broken"] else 0
            zone["effective_score"] = max(0, round(zone["score"] - age_penalty - retest_penalty - flip_penalty))
            zone["quality_grade"] = self._quality_grade(zone["effective_score"])
            zone["distance_atr"] = abs(current["close"] - zone["line"]) / max(current_atr, 1e-9)
            zone["zone_context"] = (
                "BUY_CONTEXT" if zone["price_side"] == "ABOVE"
                else "SELL_CONTEXT" if zone["price_side"] == "BELOW"
                else "WAIT"
            )
            zone["confirmation_state"] = self._confirmation_state(zone["price_side"], candle_color)
            zone["direction_holding"] = bool(
                (zone["direction"] == "BULLISH" and current["close"] >= zone["line"])
                or (zone["direction"] == "BEARISH" and current["close"] <= zone["line"])
            )
            rejection = self._rejection_metrics(rows, zone)
            zone.update(rejection)
            zone["zone_strength_score"] = self._zone_strength(zone)
            zone["execution_quality"] = self._execution_quality(zone)

        entry_diagnostics = [self._entry_event_with_diagnostics(rows, zone, profile) for zone in zones]
        for zone, diagnostic in zip(zones, entry_diagnostics):
            trace = diagnostic["trace"]
            zone.update(self._zone_signal_state(zone, trace, diagnostic.get("event"), profile))
            zone.update(self._diamond_confidence(zone, trace, diagnostic.get("event"), profile))
            diamond_score = int(zone.get("diamond_score") or 0)
            invalidated = bool(
                zone.get("diamond_confidence_tier") == "INVALIDATED"
                or zone.get("lifecycle") == "FLIPPED"
                or str(zone.get("entry_blocker") or "").startswith("ZONE_INVALIDATED")
                or zone.get("entry_blocker") == "RETEST_FATIGUE"
            )
            entry_confidence_score = int(zone.get("entry_confidence_score") or 0)
            strategy_confirmed_origin = bool(
                diagnostic.get("event")
                or zone.get("strategy_confirmed_origin")
            )
            display_as_diamond = bool(
                not invalidated
                and strategy_confirmed_origin
                and diamond_score >= visible_score_floor
            )
            entry_score_qualified = bool(
                display_as_diamond
                and entry_confidence_score >= self.MIN_ENTRY_DIAMOND_SCORE
                and zone.get("entry_eligible_origin")
            )
            signal_tier = (
                "CONFIRMED" if diagnostic.get("event")
                else "QUALIFIED" if strategy_confirmed_origin and display_as_diamond
                else "EARLY"
            )
            zone.update({
                "display_as_diamond": display_as_diamond,
                "entry_score_qualified": entry_score_qualified,
                "strategy_confirmed_origin": strategy_confirmed_origin,
                "diamond_creation_gate": (
                    "ENTRY_CONFIRMED" if diagnostic.get("event")
                    else "STRATEGY_SETUP_CONFIRMED" if strategy_confirmed_origin
                    else "WAITING_STRATEGY_SETUP"
                ),
                "score_role": "QUALITY_GRADE_ONLY",
                "score_creates_diamond": False,
                "signal_tier": signal_tier,
                "closed_candle_proof": self._closed_candle_proof(zone.get("time"), profile),
                "minimum_visible_diamond_score": visible_score_floor,
                "minimum_entry_diamond_score": self.MIN_ENTRY_DIAMOND_SCORE,
            })
            if not diagnostic.get("event") and not display_as_diamond:
                waiting_for_strategy = not strategy_confirmed_origin and not invalidated
                zone.update({
                    "entry_stage": "INTERNAL_REJECTED",
                    "display_role": "INTERNAL_REJECTED",
                    "zone_health": "REJECTED",
                    "entry_blocker": (
                        "STRATEGY_SETUP_NOT_CONFIRMED" if waiting_for_strategy
                        else "DIAMOND_SCORE_BELOW_DISPLAY_FLOOR" if not invalidated
                        else zone.get("entry_blocker")
                    ),
                    "entry_blocker_label": (
                        "Waiting for a confirmed structural setup" if waiting_for_strategy
                        else f"Confirmed setup is below the {visible_score_floor}% quality floor" if not invalidated
                        else zone.get("entry_blocker_label")
                    ),
                    "actionable_entry": False,
                })
            elif not diagnostic.get("event") and not entry_score_qualified:
                zone.update({
                    "entry_stage": "SETUP_CONFIRMED_WATCH",
                    "display_role": "SETUP_WATCH",
                    "zone_health": "WATCH_ONLY",
                    "entry_blocker": "ENTRY_CONFIRMATION_PENDING",
                    "entry_blocker_label": "Strategy setup confirmed; waiting for closed-candle entry confirmation",
                    "actionable_entry": False,
                })
            if diagnostic.get("event"):
                diagnostic["event"].update({
                    "diamond_score": max(
                        int(zone.get("diamond_score") or 0),
                        int(diagnostic["event"].get("quality_score") or 0),
                    ),
                    "diamond_grade": zone.get("diamond_grade") or diagnostic["event"].get("precision_grade") or diagnostic["event"].get("quality_grade"),
                    "grade_model": zone.get("grade_model"),
                    "score_components": zone.get("score_components") or {},
                    "signal_tier": "CONFIRMED",
                    "closed_candle_proof": self._closed_candle_proof(
                        diagnostic["event"].get("confirmation_time") or diagnostic["event"].get("time"),
                        profile,
                    ),
                })
            for stage in ["controlled_retest", "rejection", "follow_through", "risk_quality"]:
                if trace.get(stage):
                    funnel_counts[stage] += 1
            if not diagnostic.get("event") and trace.get("blocker"):
                funnel_blockers[str(trace["blocker"])] += 1
        suppressed_zones = []
        if news_guard_active:
            for zone in zones:
                if int(zone.get("age_bars") or 0) > news_guard_bars:
                    continue
                zone.update({
                    "display_as_diamond": False,
                    "entry_score_qualified": False,
                    "actionable_entry": False,
                    "news_guard_suppressed": True,
                    "entry_stage": "NEWS_GUARD",
                    "entry_blocker": "HIGH_IMPACT_NEWS_WINDOW",
                    "entry_blocker_label": "Waiting for the high-impact news window to clear",
                })
                suppressed_zones.append(zone)
        raw_entry_events = [diagnostic["event"] for diagnostic in entry_diagnostics if diagnostic.get("event")]
        suppressed_entry_events = [
            event for event in raw_entry_events
            if news_guard_active and int(event.get("age_bars") or 0) <= news_guard_bars
        ]
        entry_events = self._distinct_entry_events(
            [event for event in raw_entry_events if event not in suppressed_entry_events],
            profile,
        )
        funnel_counts["confirmed_entries"] = len(entry_events)
        gate_funnel = self._gate_funnel(funnel_counts, funnel_blockers, entry_diagnostics)
        latest_entry = entry_events[-1] if entry_events else None
        recent_entry = latest_entry if latest_entry and latest_entry["age_bars"] <= profile["max_entry_age_bars"] else None
        visible_zones = [zone for zone in zones if zone.get("display_as_diamond")]
        entry_grade_zones = [zone for zone in visible_zones if zone.get("entry_score_qualified")]
        lead_zone = None if news_guard_active else self._lead_diamond_zone(zones, entry_events, expected, profile)
        for zone in zones:
            zone["is_lead_diamond"] = bool(lead_zone and zone.get("id") == lead_zone.get("id"))
        live_zones = [lead_zone] if lead_zone else []
        lead_event = next((
            event for event in reversed(entry_events)
            if lead_zone and event.get("zone_id") == lead_zone.get("id")
        ), None)
        signal_integrity = {
            "version": "DIAMOND_RESULT_INTEGRITY_V5_SIGNAL_TIERS",
            "confirmed_entries": len(entry_events),
            "qualified_watch": sum(1 for zone in visible_zones if zone.get("display_role") == "QUALIFIED_WATCH"),
            "setup_watch": sum(1 for zone in visible_zones if zone.get("display_role") == "SETUP_WATCH"),
            "market_context": sum(1 for zone in visible_zones if zone.get("display_role") == "MARKET_CONTEXT"),
            "invalidated_context": sum(1 for zone in zones if zone.get("display_role") == "INVALIDATED_CONTEXT"),
            "rejected_internal": len(zones) - len(visible_zones),
            "production_signal_rule": "A Diamond is created only by a confirmed structural strategy setup; score only grades and ranks that setup.",
            "qualified_rule": f"After setup confirmation, the live Lead Diamond requires {profile['lead_diamond_score']}+ quality and an intact lifecycle; closed-candle entry confirmation remains separate.",
            "context_rule": f"Unconfirmed strategy observations, sub-{visible_score_floor} setups, and invalidated zones stay in the evidence audit but are hidden from the live chart.",
            "grade_rule": "Visible Diamond grades are A+, A, B, C, or D. Grade D is watch-only; C or better is entry-grade.",
            "tier_rule": "EARLY is internal context, QUALIFIED has a confirmed strategy setup, and CONFIRMED passed a closed-candle entry pathway.",
            "repaint_policy": "Signal timestamps and grades are locked from completed candles only; later invalidation changes lifecycle, not historical evidence.",
            "news_guard_suppressed": len(suppressed_zones) + len(suppressed_entry_events),
        }
        recent_entry_pool = [
            zone for zone in zones
            if recent_entry and zone.get("id") == recent_entry.get("zone_id")
        ]
        primary_pool = live_zones or recent_entry_pool or visible_zones or zones
        primary = min(primary_pool, key=lambda zone: self._primary_rank(zone, expected))
        context_is_close = primary["distance_atr"] <= profile["max_context_distance_atr"]
        context_is_usable = bool(
            lead_zone
            and primary.get("display_as_diamond")
            and primary["execution_quality"] not in {"INVALID", "CONTEXT_ONLY"}
        )
        rejection_confirmed = primary["rejection_status"] in {"STRONG", "MODERATE"}
        if primary["price_side"] == "ABOVE" and candle_color == "BULLISH" and context_is_close and context_is_usable and rejection_confirmed:
            directional_bias = "BUY_CONTEXT"
        elif primary["price_side"] == "BELOW" and candle_color == "BEARISH" and context_is_close and context_is_usable and rejection_confirmed:
            directional_bias = "SELL_CONTEXT"
        else:
            directional_bias = "WAIT"

        context_aligned = (
            directional_bias == "BUY_CONTEXT" and expected == "BULLISH"
        ) or (
            directional_bias == "SELL_CONTEXT" and expected == "BEARISH"
        )
        zone_control = (
            "BULLISH_CONTROL" if primary["price_side"] == "ABOVE"
            else "BEARISH_CONTROL" if primary["price_side"] == "BELOW"
            else "TESTING_ZONE"
        )
        strategy_state = (
            "BULLISH_HOLD" if directional_bias == "BUY_CONTEXT"
            else "BEARISH_REJECTION" if directional_bias == "SELL_CONTEXT"
            else "DISTANT_ZONE" if not context_is_close
            else "INVALIDATED_ZONE" if primary["execution_quality"] == "INVALID"
            else "ZONE_TEST" if primary["price_side"] == "INSIDE"
            else "WAIT_CONFIRMATION"
        )
        risk_filter = (
            "ALIGNED" if context_aligned
            else "CONFLICT" if directional_bias in {"BUY_CONTEXT", "SELL_CONTEXT"} and expected in {"BULLISH", "BEARISH"}
            else "WAIT"
        )
        invalidation_level = (
            primary["low"] if primary["price_side"] == "ABOVE"
            else primary["high"] if primary["price_side"] == "BELOW"
            else primary["low"] if expected == "BULLISH"
            else primary["high"] if expected == "BEARISH"
            else primary["line"]
        )
        next_trigger = (
            news_context.get("summary") or "Wait for the high-impact news window and a new completed candle"
            if news_guard_active
            else
            self._next_trigger(primary, candle_color)
            if lead_zone
            else "Scanning for a completed-candle strategy setup; score is applied only after setup confirmation"
        )
        return {
            "status": "READY",
            "strategy": self.strategy_name,
            "engine_version": self.engine_version,
            "profile": profile["name"],
            "adaptive_profile": self._adaptive_profile_summary(profile),
            "symbol": str(symbol or "XAUUSD").upper(),
            "scope": "CONFIRMED_STRATEGY_ZONES_AND_ENTRY_EVENTS",
            "timeframe": timeframe,
            "source": source,
            "closed_candles_used": len(rows),
            "current_price": round(current["close"], 5),
            "current_candle_color": candle_color,
            "directional_bias": directional_bias,
            "zone_control": zone_control,
            "strategy_state": strategy_state,
            "risk_filter": risk_filter,
            "expected_direction": expected,
            "context_aligned": context_aligned if expected in {"BULLISH", "BEARISH"} else None,
            "quality_grade": primary["quality_grade"],
            "diamond_score": primary.get("diamond_score"),
            "diamond_grade": primary.get("diamond_grade"),
            "grade_model": primary.get("grade_model"),
            "diamond_display_status": "READY" if lead_zone else "NO_QUALIFIED_DIAMOND",
            "diamond_creation_policy": "STRATEGY_SETUP_FIRST_SCORE_GRADES_ONLY",
            "strategy_setup_confirmed": primary.get("strategy_confirmed_origin") is True,
            "score_creates_diamond": False,
            "lead_diamond_status": "CONFIRMED" if lead_event else "ARMED" if lead_zone else "SCANNING",
            "lead_diamond_score_floor": profile["lead_diamond_score"],
            "minimum_visible_diamond_score": visible_score_floor,
            "minimum_entry_diamond_score": self.MIN_ENTRY_DIAMOND_SCORE,
            "score_components": primary.get("score_components") or {},
            "confirmation_state": primary["confirmation_state"],
            "rejection_status": primary["rejection_status"],
            "rejection_score": primary["rejection_score"],
            "zone_strength_score": primary["zone_strength_score"],
            "execution_quality": primary["execution_quality"],
            "invalidation_level": round(invalidation_level, 5),
            "distance_atr": round(primary["distance_atr"], 3),
            "primary_zone": self._public_zone(primary),
            "zones": [self._public_zone(zone) for zone in zones],
            "visible_zones": [self._public_zone(zone) for zone in visible_zones],
            "live_zones": [self._public_zone(zone) for zone in live_zones],
            "lead_diamond_zone": self._public_zone(lead_zone) if lead_zone else None,
            "entry_events": [self._public_entry_event(event) for event in entry_events],
            "latest_entry_event": self._public_entry_event(latest_entry) if latest_entry else None,
            "entry_event_status": (
                "CONFIRMED_ENTRY" if recent_entry
                else "HISTORICAL_CONFIRMED" if latest_entry
                else "WAITING_CONFIRMATION"
            ),
            "gate_funnel": gate_funnel,
            "signal_frequency": {
                "internal_observations": len(zones),
                "visible_diamonds": len(visible_zones),
                "live_diamonds": len(live_zones),
                "context_zones": len(visible_zones),
                "qualified_origins": len(entry_grade_zones),
                "confirmed_entries": len(entry_events),
                "visible_entry_limit": profile["max_daily_entries"],
                "context_zone_limit": profile["context_zone_limit"],
                "same_side_cooldown_bars": profile["entry_cooldown_bars"],
            },
            "signal_tiers": {
                "early": sum(1 for zone in visible_zones if zone.get("signal_tier") == "EARLY"),
                "qualified": sum(1 for zone in visible_zones if zone.get("signal_tier") == "QUALIFIED"),
                "confirmed": len(entry_events),
            },
            "signal_integrity": signal_integrity,
            "news_shock_guard": {
                "status": "LOCKED" if news_guard_active else "CLEAR",
                "suppressed_current_zones": len(suppressed_zones),
                "suppressed_current_entries": len(suppressed_entry_events),
                "history_preserved": True,
                "event": (news_context.get("primary_event") or {}).get("title"),
            },
            "precision_gate": {
                "status": "QUALIFIED" if primary.get("entry_score_qualified") else "WATCH_ONLY" if primary.get("display_as_diamond") else "REJECTED",
                "origin_model": primary.get("origin_model"),
                "origin_quality_score": primary.get("origin_quality_score"),
                "minimum_entry_quality": profile["min_entry_quality"],
                "minimum_reclaim_entry_quality": profile["min_reclaim_entry_quality"],
                "minimum_origin_reclaim_quality": profile["min_origin_reclaim_quality"],
                "minimum_active_entry_quality": profile["min_active_entry_quality"],
                "minimum_origin_quality": profile["min_origin_quality_for_entry"],
                "entry_impulse_ready": primary.get("execution_impulse_ready"),
                "entry_impulse_failures": primary.get("execution_impulse_failures") or [],
                "minimum_location_score": profile["min_execution_location_score"],
                "minimum_wider_location_score": profile["min_macro_execution_location_score"],
                "minimum_visible_diamond_score": visible_score_floor,
                "minimum_entry_diamond_score": self.MIN_ENTRY_DIAMOND_SCORE,
                "lead_diamond_score_floor": profile["lead_diamond_score"],
                "disqualifiers": primary.get("origin_disqualifiers") or [],
            },
            "next_trigger": next_trigger,
            "formulas": {
                "context_zone": (
                    f"{profile['name']} completed candle: body >= {profile['min_body_ratio']:.0%}, "
                    f"range >= {profile['min_range_ratio']:.2f} ATR14, close strength >= "
                    f"{profile['min_close_strength']:.0%}, score >= {profile['min_score']}, plus structure break "
                    f"or >= {profile['expansion_override']:.2f} ATR expansion; context location >= "
                    f"{profile['min_entry_location_score']}/100. Entry-grade origins additionally require a "
                    f"body >= {profile['entry_min_body_ratio']:.0%}, range >= {profile['entry_min_range_ratio']:.2f} ATR, "
                    f"close strength >= {profile['entry_min_close_strength']:.0%}, impulse score >= {profile['entry_min_score']}, "
                    f"liquidity sweep or structure break with continuation and location >= "
                    f"{profile['min_execution_location_score']}/100 locally, >= "
                    f"{profile['min_macro_execution_location_score']}/100 across the wider dealing range, "
                    f"origin quality >= {profile['min_origin_quality_for_entry']}, and HTF direction agreement"
                ),
                "diamond_event": (
                    "A Diamond is confirmed after a precision structural origin using an origin reclaim, a shallow "
                    "pullback continuation, an aligned XAU 5M first reaction, a strong deep-retest reclaim, or "
                    "1-3 candle directional follow-through"
                ),
                "diamond_line": "BUY uses the bullish origin low; SELL uses the bearish origin high",
                "zone_band": f"Diamond line +/- max({profile['atr_band']:.2f} ATR14, {profile['range_band']:.2f} candle range)",
                "direction": "BUY requires a discount-side bullish origin; SELL requires a premium-side bearish origin",
                "quality": f"A structural strategy setup creates the Diamond candidate first; 0-100 score then grades it. Sub-{visible_score_floor} confirmed setups remain internal audit, and confirmed entry gates remain stricter",
                "primary_zone": "One Lead Diamond selected by zone quality, intact lifecycle, ATR distance, freshness, and confirmation state",
            },
            "uses_completed_candles_only": True,
            "proprietary_formula_claimed": False,
        }

    def _distinct_recent(
        self,
        candidates: list[Dict[str, Any]],
        limit: int,
        profile: Optional[Dict[str, Any]] = None,
    ) -> list[Dict[str, Any]]:
        selected: list[Dict[str, Any]] = []
        if not candidates:
            return selected
        latest_index = int(candidates[-1].get("bar_index") or 0)
        protected_age = int((profile or {}).get("entry_window_bars") or 0) + int((profile or {}).get("follow_window_bars") or 0)
        protected = [
            candidate for candidate in reversed(candidates)
            if candidate.get("entry_eligible_origin")
            and latest_index - int(candidate.get("bar_index") or 0) <= protected_age
        ]
        ordered = protected + [candidate for candidate in reversed(candidates) if candidate not in protected]
        merge_distance_atr = float((profile or {}).get("zone_merge_distance_atr") or 0.20)
        merge_window_bars = int((profile or {}).get("zone_merge_window_bars") or 8)
        origin_cooldown_bars = int((profile or {}).get("origin_cooldown_bars") or merge_window_bars)
        flip_cluster_bars = int((profile or {}).get("flip_cluster_bars") or 4)
        flip_cluster_distance_atr = float((profile or {}).get("flip_cluster_distance_atr") or 0.65)
        for candidate in ordered:
            duplicate_index = next((
                index for index, item in enumerate(selected)
                if item["direction"] == candidate["direction"]
                and abs(item["line"] - candidate["line"]) <= max(item["atr_14"], candidate["atr_14"]) * merge_distance_atr
                and (
                    abs(int(item.get("bar_index") or 0) - int(candidate.get("bar_index") or 0)) <= merge_window_bars
                    or abs(item["line"] - candidate["line"]) <= max(item["atr_14"], candidate["atr_14"]) * 0.08
                )
            ), None)
            cooldown_index = next((
                index for index, item in enumerate(selected)
                if item["direction"] == candidate["direction"]
                and abs(int(item.get("bar_index") or 0) - int(candidate.get("bar_index") or 0)) <= origin_cooldown_bars
            ), None)
            flip_index = next((
                index for index, item in enumerate(selected)
                if item["direction"] != candidate["direction"]
                and abs(int(item.get("bar_index") or 0) - int(candidate.get("bar_index") or 0)) <= flip_cluster_bars
                and abs(float(item["line"]) - float(candidate["line"])) <= max(
                    float(item.get("atr_14") or 0),
                    float(candidate.get("atr_14") or 0),
                    1e-9,
                ) * flip_cluster_distance_atr
            ), None)
            if duplicate_index is None:
                if cooldown_index is not None:
                    if self._zone_candidate_rank(candidate) > self._zone_candidate_rank(selected[cooldown_index]):
                        selected[cooldown_index] = dict(candidate)
                elif flip_index is not None:
                    if self._zone_candidate_rank(candidate) > self._zone_candidate_rank(selected[flip_index]):
                        selected[flip_index] = dict(candidate)
                else:
                    selected.append(dict(candidate))
            elif self._zone_candidate_rank(candidate) > self._zone_candidate_rank(selected[duplicate_index]):
                selected[duplicate_index] = dict(candidate)
            if len(selected) >= limit:
                break
        return sorted(selected, key=lambda item: int(item.get("time") or 0), reverse=True)

    @staticmethod
    def _scalp_wick_rejection_candidate(
        rows: list[Dict[str, Any]],
        index: int,
        atr: float,
        profile: Dict[str, Any],
        expected: str,
        trend_guard: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Capture one closed-candle key high/low after a 5M expansion rejection."""
        if not profile.get("scalp_wick_rejection_enabled") or index < 15 or atr <= 0:
            return None
        row = rows[index]
        candle_range = float(row["high"]) - float(row["low"])
        if candle_range <= 0:
            return None
        range_ratio = candle_range / atr
        body_ratio = abs(float(row["close"]) - float(row["open"])) / candle_range
        upper_wick = (float(row["high"]) - max(float(row["open"]), float(row["close"]))) / candle_range
        lower_wick = (min(float(row["open"]), float(row["close"])) - float(row["low"])) / candle_range
        minimum_wick = float(profile.get("min_scalp_rejection_wick_ratio") or 0.40)
        if range_ratio < float(profile.get("min_scalp_rejection_range_atr") or 1.70):
            return None
        if max(upper_wick, lower_wick) < minimum_wick or body_ratio < 0.18:
            return None

        if upper_wick >= lower_wick:
            direction = "BEARISH"
            entry_side = "SELL"
            entry_line = float(row["high"])
            wick_ratio = upper_wick
        else:
            direction = "BULLISH"
            entry_side = "BUY"
            entry_line = float(row["low"])
            wick_ratio = lower_wick

        local_trend = dict(trend_guard or {})
        trend_direction = str(local_trend.get("direction") or "MIXED")
        counter_trend = bool(
            local_trend.get("is_strong")
            and trend_direction in {"BULLISH", "BEARISH"}
            and direction != trend_direction
        )
        # A single wick against an established trend is observation, not a
        # reversal setup. The standard origin path can still qualify later
        # after a sweep and completed-candle structure break.
        if counter_trend:
            return None

        prior = rows[max(0, index - 8):index]
        wider_prior = rows[max(0, index - int(profile["location_window_bars"])):index]
        if not prior or not wider_prior:
            return None
        prior_low = min(float(item["low"]) for item in prior)
        prior_high = max(float(item["high"]) for item in prior)
        wider_low = min(float(item["low"]) for item in wider_prior)
        wider_high = max(float(item["high"]) for item in wider_prior)
        local_span = max(prior_high - prior_low, 1e-9)
        wider_span = max(wider_high - wider_low, 1e-9)
        local_position = max(0.0, min(1.0, (entry_line - prior_low) / local_span))
        wider_position = max(0.0, min(1.0, (entry_line - wider_low) / wider_span))
        local_location = round((1.0 - local_position) * 100 if direction == "BULLISH" else local_position * 100)
        wider_location = round((1.0 - wider_position) * 100 if direction == "BULLISH" else wider_position * 100)
        location = round(local_location * 0.42 + wider_location * 0.58)
        if (
            location < int(profile.get("min_scalp_rejection_location_score") or 68)
            or wider_location < int(profile.get("min_scalp_rejection_wider_location_score") or 60)
        ):
            return None

        swept_extreme = bool(
            entry_line > prior_high if direction == "BEARISH" else entry_line < prior_low
        )
        score = round(min(100.0, (
            min(wick_ratio / 0.60, 1.0) * 25
            + min(range_ratio / 2.0, 1.0) * 18
            + location / 100 * 18
            + min(body_ratio / 0.50, 1.0) * 10
            + (7 if swept_extreme else 3)
        )))
        if score < int(profile.get("min_scalp_rejection_score") or 66):
            return None

        recent_closes = [float(item["close"]) for item in wider_prior[-20:]]
        fast_mean = sum(recent_closes[-5:]) / max(1, len(recent_closes[-5:]))
        slow_mean = sum(recent_closes) / max(1, len(recent_closes))
        wider_trend = (
            "BULLISH" if fast_mean > slow_mean + atr * 0.08
            else "BEARISH" if fast_mean < slow_mean - atr * 0.08
            else "MIXED"
        )
        direction_aligned = expected not in {"BULLISH", "BEARISH"} or direction == expected
        news_spike_risk = range_ratio >= float(profile.get("max_clean_expansion") or 3.4)
        origin_quality = round(min(100.0, (
            score * 0.55
            + location * 0.22
            + wider_location * 0.10
            + min(wick_ratio / 0.60, 1.0) * 8
            + (5 if swept_extreme else 2)
        )))
        execution_ready = score >= int(profile.get("min_scalp_rejection_entry_score") or 70)
        entry_eligible = bool(
            execution_ready
            and origin_quality >= int(profile.get("min_scalp_rejection_origin_quality") or 68)
            and direction_aligned
            and not news_spike_risk
        )
        strategy_confirmed = bool(
            swept_extreme
            and execution_ready
            and direction_aligned
            and not news_spike_risk
        )
        half_width = max(atr * float(profile["atr_band"]), candle_range * float(profile["range_band"]))
        disqualifiers = []
        if not execution_ready:
            disqualifiers.append("ENTRY_IMPULSE_SCORE_BELOW_FLOOR")
        if not direction_aligned:
            disqualifiers.append("HTF_DIRECTION_CONFLICT")
        if news_spike_risk:
            disqualifiers.append("OVERSIZED_NEWS_SPIKE")
        return {
            "id": f"{'buy' if direction == 'BULLISH' else 'sell'}-{row['time']}-wick",
            "time": row["time"],
            "direction": direction,
            "entry_side": entry_side,
            "signal_label": "DIAMOND_BUY" if direction == "BULLISH" else "DIAMOND_SELL",
            "entry_anchor": "CANDLE_LOW" if direction == "BULLISH" else "CANDLE_HIGH",
            "line": entry_line,
            "low": entry_line - half_width,
            "high": entry_line + half_width,
            "score": score,
            "atr_14": atr,
            "body_ratio": body_ratio,
            "range_ratio": range_ratio,
            "close_strength": wick_ratio,
            "impulse_open": row["open"],
            "impulse_close": row["close"],
            "impulse_high": row["high"],
            "impulse_low": row["low"],
            "dealing_range_position": local_position,
            "wider_dealing_range_position": wider_position,
            "local_entry_location_score": local_location,
            "wider_entry_location_score": wider_location,
            "entry_location_score": location,
            "liquidity_sweep": False,
            "rejection_sweep": swept_extreme,
            "scalp_key_zone": True,
            "structure_break": False,
            "wider_structure_break": False,
            "compression_break": False,
            "trend_pullback_reclaim": False,
            "wider_trend_direction": wider_trend,
            "trend_regime": local_trend.get("regime"),
            "trend_direction": trend_direction,
            "trend_strength": local_trend.get("strength"),
            "trend_metrics": local_trend.get("metrics") or {},
            "strong_trend_guard": "PASS",
            "counter_trend": False,
            "counter_trend_reversal_confirmed": False,
            "active_structure": True,
            "continuation": False,
            "expected_direction_at_origin": expected,
            "direction_aligned": direction_aligned,
            "origin_model": "SCALP_WICK_REJECTION",
            "origin_quality_score": origin_quality,
            "origin_quality_grade": DiamondZoneEngine._quality_grade(origin_quality),
            "context_quality_passed": True,
            "execution_impulse_ready": execution_ready,
            "execution_impulse_failures": [] if execution_ready else ["ENTRY_IMPULSE_SCORE_BELOW_FLOOR"],
            "entry_eligible_origin": entry_eligible,
            "strategy_confirmed_origin": strategy_confirmed,
            "origin_disqualifiers": disqualifiers,
            "news_spike_risk": news_spike_risk,
            "bar_index": index,
        }

    @staticmethod
    def _trend_context_at(
        rows: list[Dict[str, Any]],
        index: int,
        atr: float,
        profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Measure the trend that existed at an origin without future candles."""
        start = max(0, index - 55)
        closes = [float(item["close"]) for item in rows[start:index + 1]]
        if len(closes) < 21 or atr <= 0:
            return {
                "regime": "WARMING_UP",
                "direction": "MIXED",
                "strength": 0,
                "is_strong": False,
                "metrics": {},
            }

        def ema(values: list[float], period: int) -> list[float]:
            alpha = 2.0 / (period + 1.0)
            result = [values[0]]
            for value in values[1:]:
                result.append(alpha * value + (1.0 - alpha) * result[-1])
            return result

        fast = ema(closes, 13)
        slow = ema(closes, 34)
        sample = closes[-21:]
        path = sum(abs(right - left) for left, right in zip(sample, sample[1:]))
        efficiency = abs(sample[-1] - sample[0]) / path if path > 0 else 0.0
        spread_atr = (fast[-1] - slow[-1]) / max(atr, 1e-9)
        slope_lookback = min(5, len(fast) - 1)
        slope_atr = (fast[-1] - fast[-1 - slope_lookback]) / max(atr * slope_lookback, 1e-9)
        efficiency_floor = float(profile.get("strong_trend_efficiency") or 0.42)
        spread_floor = float(profile.get("strong_trend_spread_atr") or 0.30)
        slope_floor = float(profile.get("strong_trend_slope_atr") or 0.035)
        bullish = efficiency >= efficiency_floor and spread_atr >= spread_floor and slope_atr >= slope_floor
        bearish = efficiency >= efficiency_floor and spread_atr <= -spread_floor and slope_atr <= -slope_floor
        direction = "BULLISH" if bullish else "BEARISH" if bearish else "MIXED"
        strength = round(min(100.0, (
            min(efficiency / max(efficiency_floor, 1e-9), 1.5) * 40
            + min(abs(spread_atr) / max(spread_floor, 1e-9), 1.5) * 35
            + min(abs(slope_atr) / max(slope_floor, 1e-9), 1.5) * 25
        ) / 1.5)) if direction != "MIXED" else round(min(49.0, efficiency * 100))
        return {
            "regime": f"STRONG_{direction}" if direction != "MIXED" else "BALANCED",
            "direction": direction,
            "strength": strength,
            "is_strong": direction != "MIXED",
            "metrics": {
                "efficiency": round(efficiency, 4),
                "ema_spread_atr": round(spread_atr, 4),
                "ema_slope_atr": round(slope_atr, 4),
            },
        }

    @staticmethod
    def _zone_candidate_rank(zone: Dict[str, Any]) -> tuple:
        return (
            1 if zone.get("entry_eligible_origin") else 0,
            int(zone.get("origin_quality_score") or 0),
            int(zone.get("score") or 0),
            int(zone.get("bar_index") or 0),
        )

    def _entry_event(
        self,
        rows: list[Dict[str, Any]],
        zone: Dict[str, Any],
        profile: Dict[str, Any],
        trace: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Confirm a zone from an origin reclaim, active pullback, or deep retest."""
        trace = trace if trace is not None else {}
        trace.update({
            "zone_id": zone.get("id"),
            "entry_side": zone.get("entry_side"),
            "confirmation_pathways": [
                "ORIGIN_RECLAIM_CLOSE",
                "SHALLOW_PULLBACK_CONTINUATION",
                "SCALP_FIRST_REACTION",
                "RECLAIM_CLOSE",
                "MULTI_CANDLE_FOLLOW_THROUGH",
            ],
            "touches": 0,
            "controlled_retest": False,
            "rejection": False,
            "follow_through": False,
            "risk_quality": False,
            "blocker": None,
        })
        if not zone.get("entry_eligible_origin"):
            trace["blocker"] = "ORIGIN_NOT_ENTRY_ELIGIBLE"
            return None
        origin_index = int(zone["bar_index"])
        origin_event = self._origin_reclaim_event(rows, zone, origin_index, profile)
        if origin_event:
            trace.update({
                "blocker": None,
                "origin_reclaim": True,
                "rejection": True,
                "risk_quality": True,
                "quality_score": origin_event["quality_score"],
                "required_quality": profile["min_origin_reclaim_quality"],
                "confirmed": True,
                "confirmation_pathway": "ORIGIN_RECLAIM_CLOSE",
            })
            return origin_event
        active_event = self._shallow_pullback_continuation_event(rows, zone, origin_index, profile)
        if active_event:
            trace.update({
                "blocker": None,
                "active_pullback": True,
                "controlled_retest": True,
                "rejection": True,
                "follow_through": True,
                "risk_quality": True,
                "quality_score": active_event["quality_score"],
                "required_quality": profile["min_active_entry_quality"],
                "confirmed": True,
                "confirmation_pathway": "SHALLOW_PULLBACK_CONTINUATION",
            })
            return active_event
        scalp_event = self._scalp_first_reaction_event(rows, zone, origin_index, profile)
        if scalp_event:
            trace.update({
                "blocker": None,
                "scalp_first_reaction": True,
                "controlled_retest": True,
                "rejection": True,
                "follow_through": True,
                "risk_quality": True,
                "quality_score": scalp_event["quality_score"],
                "required_quality": profile["min_scalp_reaction_quality"],
                "confirmed": True,
                "confirmation_pathway": "SCALP_FIRST_REACTION",
            })
            return scalp_event
        end = min(len(rows) - 1, origin_index + int(profile["entry_window_bars"]) + 1)
        for index in range(origin_index + 1, end):
            trigger = rows[index]
            if self._closed_beyond_zone(trigger, zone):
                trace["blocker"] = "ZONE_INVALIDATED_BEFORE_ENTRY"
                return None
            if not (trigger["low"] <= zone["high"] and trigger["high"] >= zone["low"]):
                continue
            trace["touches"] += 1
            if trace["touches"] > int(profile["max_retest_touches"]):
                trace["blocker"] = "RETEST_FATIGUE"
                return None
            if index - origin_index < profile["min_retest_delay_bars"]:
                trace["blocker"] = "RETEST_TOO_EARLY"
                continue
            if zone.get("news_spike_risk") and index - origin_index < profile["min_spike_retest_delay_bars"]:
                trace["blocker"] = "SPIKE_COOLDOWN"
                continue

            candle_range = max(trigger["high"] - trigger["low"], 1e-9)
            retest_range_atr = candle_range / max(float(zone["atr_14"]), 1e-9)
            if retest_range_atr > profile["max_retest_range_atr"]:
                trace["blocker"] = "RETEST_TOO_VOLATILE"
                continue
            trace["controlled_retest"] = True
            body_ratio = abs(trigger["close"] - trigger["open"]) / candle_range
            if zone["entry_side"] == "BUY":
                wick_ratio = (min(trigger["open"], trigger["close"]) - trigger["low"]) / candle_range
                close_strength = (trigger["close"] - trigger["low"]) / candle_range
                directional_rejection = trigger["close"] > trigger["open"] and trigger["close"] > zone["high"]
            else:
                wick_ratio = (trigger["high"] - max(trigger["open"], trigger["close"])) / candle_range
                close_strength = (trigger["high"] - trigger["close"]) / candle_range
                directional_rejection = trigger["close"] < trigger["open"] and trigger["close"] < zone["low"]
            rejection_ready = bool(
                directional_rejection
                and close_strength >= profile["min_retest_close_strength"]
                and (wick_ratio >= profile["min_rejection_wick"] or body_ratio >= profile["min_rejection_body"])
            )
            if not rejection_ready:
                trace["blocker"] = "WEAK_REJECTION"
                continue
            trace["rejection"] = True
            reclaim_ready = bool(
                close_strength >= profile["min_reclaim_close_strength"]
                and (wick_ratio >= profile["min_reclaim_wick"] or body_ratio >= profile["min_reclaim_body"])
                and (zone.get("liquidity_sweep") or zone.get("active_structure"))
            )
            if reclaim_ready:
                direct_event = self._reclaim_close_event(
                    rows, zone, trigger, index, profile,
                    wick_ratio, close_strength, body_ratio, retest_range_atr,
                )
                if direct_event:
                    trace.update({
                        "blocker": None,
                        "risk_quality": True,
                        "quality_score": direct_event["quality_score"],
                        "required_quality": profile["min_reclaim_entry_quality"],
                        "confirmed": True,
                        "confirmation_pathway": "RECLAIM_CLOSE",
                    })
                    return direct_event

            follow_end = min(len(rows), index + 1 + int(profile["follow_window_bars"]))
            for follow_index in range(index + 1, follow_end):
                follow = rows[follow_index]
                if self._closed_beyond_zone(follow, zone):
                    trace["blocker"] = "ZONE_INVALIDATED_ON_FOLLOW_THROUGH"
                    return None
                if zone["entry_side"] == "BUY":
                    follow_ready = bool(
                        follow["close"] > zone["high"]
                        and follow["close"] > follow["open"]
                        and follow["close"] > trigger["close"]
                    )
                else:
                    follow_ready = bool(
                        follow["close"] < zone["low"]
                        and follow["close"] < follow["open"]
                        and follow["close"] < trigger["close"]
                    )
                if not follow_ready:
                    trace["blocker"] = "NO_DIRECTIONAL_FOLLOW_THROUGH"
                    continue

                event = self._follow_through_event(
                    rows, zone, trigger, follow, follow_index, profile,
                    wick_ratio, close_strength, body_ratio, retest_range_atr,
                    follow_index - index,
                )
                if not event:
                    trace["blocker"] = "FOLLOW_THROUGH_QUALITY_REJECTED"
                    continue
                trace.update({
                    "blocker": None,
                    "follow_through": True,
                    "risk_quality": True,
                    "quality_score": event["quality_score"],
                    "required_quality": profile["min_entry_quality"],
                    "confirmed": True,
                    "confirmation_pathway": "MULTI_CANDLE_FOLLOW_THROUGH",
                })
                return event
        if trace["blocker"] is None:
            trace["blocker"] = "NO_RETEST_IN_WINDOW" if trace["touches"] == 0 else "NO_VALID_ENTRY_SEQUENCE"
        return None

    def _origin_reclaim_event(
        self,
        rows: list[Dict[str, Any]],
        zone: Dict[str, Any],
        origin_index: int,
        profile: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not (zone.get("liquidity_sweep") or zone.get("trend_pullback_reclaim")):
            return None
        if profile.get("origin_reclaim_trend_only") and not zone.get("trend_pullback_reclaim"):
            return None
        if zone.get("news_spike_risk") or zone.get("direction_aligned") is False:
            return None
        origin = rows[origin_index]
        atr = max(float(zone["atr_14"]), 1e-9)
        candle_range = max(origin["high"] - origin["low"], 1e-9)
        body_ratio = abs(origin["close"] - origin["open"]) / candle_range
        close_strength = float(zone.get("close_strength") or 0)
        if close_strength < float(profile.get("min_origin_reclaim_close_strength") or 0):
            return None
        wick_ratio = (
            (min(origin["open"], origin["close"]) - origin["low"]) / candle_range
            if zone["entry_side"] == "BUY"
            else (origin["high"] - max(origin["open"], origin["close"])) / candle_range
        )
        stop_reference = zone["low"] if zone["entry_side"] == "BUY" else zone["high"]
        risk_atr = abs(origin["close"] - stop_reference) / atr
        displacement = abs(origin["close"] - zone["line"]) / atr
        if not profile["min_event_risk_atr"] <= risk_atr <= profile["max_origin_entry_displacement_atr"]:
            return None
        if displacement > profile["max_origin_entry_displacement_atr"]:
            return None
        quality = (
            float(zone["origin_quality_score"]) * 0.44
            + float(zone["entry_location_score"]) * 0.20
            + float(zone.get("wider_entry_location_score") or zone["entry_location_score"]) * 0.10
            + close_strength * 100 * 0.20
            + (6 if zone.get("liquidity_sweep") else 4)
        )
        quality_score = round(max(0, min(100, quality)))
        if quality_score < profile["min_origin_reclaim_quality"] or quality_score < self.MIN_ENTRY_DIAMOND_SCORE:
            return None
        marker_price = origin["low"] - atr * 0.14 if zone["entry_side"] == "BUY" else origin["high"] + atr * 0.14
        event = self._entry_payload(
            rows, zone, origin, origin, origin_index, marker_price, stop_reference,
            quality_score, risk_atr, displacement, wick_ratio, close_strength,
            candle_range / atr, body_ratio, candle_range / atr, close_strength, 0.0,
            "ACTIVE_ORIGIN_SWEEP_RECLAIM_CLOSE", "ORIGIN_RECLAIM_CLOSE", 0,
        )
        event["origin_confirmation"] = True
        return event

    def _shallow_pullback_continuation_event(
        self,
        rows: list[Dict[str, Any]],
        zone: Dict[str, Any],
        origin_index: int,
        profile: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if zone.get("news_spike_risk") or zone.get("direction_aligned") is False:
            return None
        if not zone.get("active_structure"):
            return None
        if (
            profile.get("active_continuation_trend_only")
            and zone.get("origin_model") != "TREND_PULLBACK_RECLAIM"
        ):
            return None
        if (
            str(profile.get("name") or "").startswith("XAU_")
            and zone.get("origin_model") not in {
                "SWEEP_AND_BREAK",
                "LIQUIDITY_SWEEP",
                "COMPRESSION_BREAK",
                "TREND_PULLBACK_RECLAIM",
            }
        ):
            return None
        atr = max(float(zone["atr_14"]), 1e-9)
        origin = rows[origin_index]
        end = min(len(rows), origin_index + 1 + int(profile["active_follow_window_bars"]))
        for index in range(origin_index + 1, end):
            confirmation = rows[index]
            if self._closed_beyond_zone(confirmation, zone):
                return None
            sequence = rows[origin_index + 1:index + 1]
            candle_range = max(confirmation["high"] - confirmation["low"], 1e-9)
            body_ratio = abs(confirmation["close"] - confirmation["open"]) / candle_range
            if zone["entry_side"] == "BUY":
                pullback_extreme = min(item["low"] for item in sequence)
                pullback_atr = max(0.0, origin["close"] - pullback_extreme) / atr
                close_strength = (confirmation["close"] - confirmation["low"]) / candle_range
                directional_ready = bool(
                    confirmation["close"] > confirmation["open"]
                    and confirmation["close"] > rows[index - 1]["close"]
                    and confirmation["close"] > origin["open"]
                )
                breaks_previous_extreme = confirmation["close"] > rows[index - 1]["high"]
                shallow_only = pullback_extreme > zone["high"]
                directional_progress = max(0.0, confirmation["close"] - pullback_extreme) / atr
            else:
                pullback_extreme = max(item["high"] for item in sequence)
                pullback_atr = max(0.0, pullback_extreme - origin["close"]) / atr
                close_strength = (confirmation["high"] - confirmation["close"]) / candle_range
                directional_ready = bool(
                    confirmation["close"] < confirmation["open"]
                    and confirmation["close"] < rows[index - 1]["close"]
                    and confirmation["close"] < origin["open"]
                )
                breaks_previous_extreme = confirmation["close"] < rows[index - 1]["low"]
                shallow_only = pullback_extreme < zone["low"]
                directional_progress = max(0.0, pullback_extreme - confirmation["close"]) / atr
            profile_name = str(profile.get("name") or "")
            xau_higher_timeframe_continuation = bool(
                profile_name.startswith("XAU_")
                and profile_name.endswith(("_15M", "_1H", "_4H"))
                and zone.get("origin_model") in {"COMPRESSION_BREAK", "TREND_PULLBACK_RECLAIM"}
            )
            if not shallow_only or not directional_ready or not (
                breaks_previous_extreme or xau_higher_timeframe_continuation
            ):
                continue
            line_displacement = abs(confirmation["close"] - zone["line"]) / atr
            displacement = abs(confirmation["close"] - origin["close"]) / atr
            risk_atr = abs(confirmation["close"] - pullback_extreme) / atr
            range_atr = candle_range / atr
            if (
                pullback_atr < profile["min_active_pullback_atr"]
                or pullback_atr > profile["max_active_pullback_atr"]
                or body_ratio < profile["min_active_body_ratio"]
                or close_strength < profile["min_active_close_strength"]
                or range_atr > profile["max_follow_range_atr"]
                or not profile["min_event_risk_atr"] <= risk_atr <= profile["max_event_risk_atr"]
                or displacement > profile["max_active_entry_displacement_atr"]
                or line_displacement > profile["max_active_origin_line_displacement_atr"]
            ):
                continue
            trigger_quality = min(100.0, body_ratio * 45 + close_strength * 45 + min(directional_progress, 1.0) * 10)
            pullback_quality = max(0.0, 100 - abs(pullback_atr - profile["ideal_active_pullback_atr"]) * 90)
            quality = (
                float(zone["origin_quality_score"]) * 0.40
                + float(zone["entry_location_score"]) * 0.14
                + float(zone.get("wider_entry_location_score") or zone["entry_location_score"]) * 0.08
                + trigger_quality * 0.25
                + pullback_quality * 0.09
                + (4 if zone.get("liquidity_sweep") else 3)
                - max(0, index - origin_index - 1) * 1.5
            )
            quality_score = round(max(0, min(100, quality)))
            if quality_score < profile["min_active_entry_quality"] or quality_score < self.MIN_ENTRY_DIAMOND_SCORE:
                continue
            marker_price = (
                pullback_extreme - atr * 0.14
                if zone["entry_side"] == "BUY"
                else pullback_extreme + atr * 0.14
            )
            event = self._entry_payload(
                rows, zone, confirmation, confirmation, index, marker_price, pullback_extreme,
                quality_score, risk_atr, displacement, 0.0, close_strength,
                range_atr, body_ratio, range_atr, close_strength, directional_progress,
                "ACTIVE_SHALLOW_PULLBACK_CONTINUATION", "SHALLOW_PULLBACK_CONTINUATION",
                index - origin_index,
            )
            event["origin_line_displacement_atr"] = round(line_displacement, 3)
            return event
        return None

    def _scalp_first_reaction_event(
        self,
        rows: list[Dict[str, Any]],
        zone: Dict[str, Any],
        origin_index: int,
        profile: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Confirm an aligned 5M continuation after its first controlled reaction."""
        if not profile.get("scalp_first_reaction_enabled"):
            return None
        if zone.get("news_spike_risk") or zone.get("direction_aligned") is False:
            return None
        if not zone.get("active_structure"):
            return None
        if (
            zone.get("origin_model") == "COMPRESSION_BREAK"
            and float(zone.get("entry_location_score") or 0)
            < float(profile.get("min_scalp_compression_location_score") or 0)
        ):
            return None

        expected_trend = "BULLISH" if zone["entry_side"] == "BUY" else "BEARISH"
        wider_trend = str(zone.get("wider_trend_direction") or "MIXED")
        if wider_trend not in {expected_trend, "MIXED"}:
            return None

        atr = max(float(zone["atr_14"]), 1e-9)
        origin = rows[origin_index]
        window = int(profile["scalp_reaction_window_bars"])
        end = min(len(rows), origin_index + 1 + window)
        for index in range(origin_index + 1, end):
            confirmation = rows[index]
            if self._closed_beyond_zone(confirmation, zone):
                return None

            sequence = rows[origin_index + 1:index + 1]
            previous = rows[index - 1]
            candle_range = max(confirmation["high"] - confirmation["low"], 1e-9)
            body_ratio = abs(confirmation["close"] - confirmation["open"]) / candle_range
            range_atr = candle_range / atr
            if zone["entry_side"] == "BUY":
                pullback_extreme = min(item["low"] for item in sequence)
                pullback_atr = max(0.0, origin["close"] - pullback_extreme) / atr
                close_strength = (confirmation["close"] - confirmation["low"]) / candle_range
                wick_ratio = (min(confirmation["open"], confirmation["close"]) - confirmation["low"]) / candle_range
                directional_ready = bool(
                    confirmation["close"] > confirmation["open"]
                    and confirmation["close"] > previous["high"]
                )
                directional_progress = max(0.0, confirmation["close"] - previous["close"]) / atr
                stop_reference = pullback_extreme
                marker_price = pullback_extreme - atr * 0.14
            else:
                pullback_extreme = max(item["high"] for item in sequence)
                pullback_atr = max(0.0, pullback_extreme - origin["close"]) / atr
                close_strength = (confirmation["high"] - confirmation["close"]) / candle_range
                wick_ratio = (confirmation["high"] - max(confirmation["open"], confirmation["close"])) / candle_range
                directional_ready = bool(
                    confirmation["close"] < confirmation["open"]
                    and confirmation["close"] < previous["low"]
                )
                directional_progress = max(0.0, previous["close"] - confirmation["close"]) / atr
                stop_reference = pullback_extreme
                marker_price = pullback_extreme + atr * 0.14

            risk_atr = (abs(confirmation["close"] - stop_reference) + atr * 0.10) / atr
            displacement = abs(confirmation["close"] - zone["line"]) / atr
            if (
                not directional_ready
                or pullback_atr < profile["min_scalp_pullback_atr"]
                or pullback_atr > profile["max_scalp_pullback_atr"]
                or body_ratio < profile["min_scalp_reaction_body_ratio"]
                or close_strength < profile["min_scalp_reaction_close_strength"]
                or directional_progress < profile["min_scalp_reaction_progress_atr"]
                or range_atr > profile["max_scalp_reaction_range_atr"]
                or risk_atr < profile["min_event_risk_atr"]
                or risk_atr > profile["max_scalp_reaction_risk_atr"]
                or displacement > profile["max_scalp_reaction_displacement_atr"]
            ):
                continue

            trigger_quality = min(
                100.0,
                body_ratio * 35
                + close_strength * 40
                + min(directional_progress / 0.25, 1.0) * 25,
            )
            pullback_quality = max(
                0.0,
                100 - abs(pullback_atr - profile["ideal_scalp_pullback_atr"]) * 75,
            )
            quality = (
                float(zone["origin_quality_score"]) * 0.45
                + float(zone["entry_location_score"]) * 0.10
                + float(zone.get("wider_entry_location_score") or zone["entry_location_score"]) * 0.10
                + trigger_quality * 0.25
                + pullback_quality * 0.10
                + (4 if wider_trend == expected_trend else 2)
            )
            quality_score = round(max(0, min(100, quality)))
            if quality_score < max(self.MIN_ENTRY_DIAMOND_SCORE, profile["min_scalp_reaction_quality"]):
                continue

            event = self._entry_payload(
                rows, zone, confirmation, confirmation, index, marker_price, stop_reference,
                quality_score, risk_atr, displacement, wick_ratio, close_strength,
                range_atr, body_ratio, range_atr, close_strength, directional_progress,
                "ACTIVE_SCALP_FIRST_REACTION_CLOSE", "SCALP_FIRST_REACTION",
                index - origin_index,
            )
            event.update({
                "scalp_confirmation": True,
                "pullback_atr": round(pullback_atr, 3),
                "wider_trend_confirmation": wider_trend,
            })
            return event
        return None

    def _reclaim_close_event(
        self,
        rows: list[Dict[str, Any]],
        zone: Dict[str, Any],
        trigger: Dict[str, Any],
        trigger_index: int,
        profile: Dict[str, Any],
        wick_ratio: float,
        close_strength: float,
        body_ratio: float,
        retest_range_atr: float,
    ) -> Optional[Dict[str, Any]]:
        atr = max(float(zone["atr_14"]), 1e-9)
        stop_reference = min(zone["low"], trigger["low"]) if zone["entry_side"] == "BUY" else max(zone["high"], trigger["high"])
        risk_atr = abs(trigger["close"] - stop_reference) / atr
        displacement = abs(trigger["close"] - zone["line"]) / atr
        if not profile["min_event_risk_atr"] <= risk_atr <= profile["max_event_risk_atr"]:
            return None
        if displacement > profile["max_entry_displacement_atr"]:
            return None
        rejection_quality = min(100.0, wick_ratio * 150 + close_strength * 45 + body_ratio * 20)
        quality = (
            float(zone["origin_quality_score"]) * 0.38
            + float(zone["entry_location_score"]) * 0.20
            + float(zone.get("wider_entry_location_score") or zone["entry_location_score"]) * 0.10
            + rejection_quality * 0.27
            + (5 if zone.get("liquidity_sweep") else 4 if zone.get("active_structure") else 0)
        )
        quality_score = round(max(0, min(100, quality)))
        if quality_score < profile["min_reclaim_entry_quality"] or quality_score < self.MIN_ENTRY_DIAMOND_SCORE:
            return None
        marker_price = trigger["low"] - atr * 0.14 if zone["entry_side"] == "BUY" else trigger["high"] + atr * 0.14
        return self._entry_payload(
            rows, zone, trigger, trigger, trigger_index, marker_price, stop_reference,
            quality_score, risk_atr, displacement, wick_ratio, close_strength,
            retest_range_atr, body_ratio, retest_range_atr, close_strength, 0.0,
            "ACTIVE_RETEST_RECLAIM_CLOSE", "RECLAIM_CLOSE", 0,
        )

    def _follow_through_event(
        self,
        rows: list[Dict[str, Any]],
        zone: Dict[str, Any],
        trigger: Dict[str, Any],
        follow: Dict[str, Any],
        follow_index: int,
        profile: Dict[str, Any],
        wick_ratio: float,
        close_strength: float,
        trigger_body_ratio: float,
        retest_range_atr: float,
        delay_bars: int,
    ) -> Optional[Dict[str, Any]]:
        atr = max(float(zone["atr_14"]), 1e-9)
        follow_range = max(follow["high"] - follow["low"], 1e-9)
        follow_body_ratio = abs(follow["close"] - follow["open"]) / follow_range
        follow_range_atr = follow_range / atr
        follow_strength = (
            (follow["close"] - follow["low"]) / follow_range
            if zone["entry_side"] == "BUY"
            else (follow["high"] - follow["close"]) / follow_range
        )
        directional_progress = (
            follow["close"] - trigger["close"]
            if zone["entry_side"] == "BUY"
            else trigger["close"] - follow["close"]
        ) / atr
        stop_reference = (
            min(zone["low"], trigger["low"], follow["low"])
            if zone["entry_side"] == "BUY"
            else max(zone["high"], trigger["high"], follow["high"])
        )
        risk_atr = abs(follow["close"] - stop_reference) / atr
        displacement = abs(follow["close"] - zone["line"]) / atr
        if (
            follow_body_ratio < profile["min_follow_body_ratio"]
            or follow_strength < profile["min_follow_close_strength"]
            or directional_progress < profile["min_follow_progress_atr"]
            or follow_range_atr > profile["max_follow_range_atr"]
            or not profile["min_event_risk_atr"] <= risk_atr <= profile["max_event_risk_atr"]
            or displacement > profile["max_entry_displacement_atr"]
        ):
            return None
        quality = (
            float(zone["origin_quality_score"]) * 0.32
            + float(zone["entry_location_score"]) * 0.16
            + min(100.0, wick_ratio * 170 + close_strength * 35) * 0.22
            + min(100.0, follow_strength * 70 + follow_body_ratio * 30) * 0.20
            + min(100.0, directional_progress / max(profile["min_follow_progress_atr"], 1e-9) * 50) * 0.06
            + (4 if zone.get("liquidity_sweep") else 3 if zone.get("active_structure") else 0)
            - max(0, delay_bars - 1) * 1.5
        )
        quality_score = round(max(0, min(100, quality)))
        if quality_score < profile["min_entry_quality"] or quality_score < self.MIN_ENTRY_DIAMOND_SCORE:
            return None
        marker_price = min(trigger["low"], follow["low"]) - atr * 0.16 if zone["entry_side"] == "BUY" else max(trigger["high"], follow["high"]) + atr * 0.16
        return self._entry_payload(
            rows, zone, trigger, follow, follow_index, marker_price, stop_reference,
            quality_score, risk_atr, displacement, wick_ratio, close_strength,
            retest_range_atr, follow_body_ratio, follow_range_atr, follow_strength,
            directional_progress, "ACTIVE_RETEST_MULTI_CANDLE_FOLLOW_THROUGH",
            "PULLBACK_FOLLOW_THROUGH", delay_bars,
        )

    def _entry_payload(
        self,
        rows: list[Dict[str, Any]],
        zone: Dict[str, Any],
        trigger: Dict[str, Any],
        confirmation: Dict[str, Any],
        confirmation_index: int,
        marker_price: float,
        stop_reference: float,
        quality_score: int,
        risk_atr: float,
        displacement: float,
        wick_ratio: float,
        close_strength: float,
        retest_range_atr: float,
        follow_body_ratio: float,
        follow_range_atr: float,
        follow_strength: float,
        directional_progress: float,
        confirmation_model: str,
        entry_pathway: str,
        confirmation_delay_bars: int,
    ) -> Dict[str, Any]:
        precision_grade = self._diamond_grade(quality_score) or "D"
        return {
            "id": f"entry-{zone['id']}-{confirmation['time']}",
            "zone_id": zone["id"],
            "time": confirmation["time"],
            "available_at": confirmation["time"],
            "trigger_time": trigger["time"],
            "confirmation_time": confirmation["time"],
            "direction": zone["direction"],
            "entry_side": zone["entry_side"],
            "signal_label": zone["signal_label"],
            "line": zone["line"],
            "marker_price": marker_price,
            "execution_entry": confirmation["close"],
            "stop_reference": stop_reference,
            "zone_low": zone["low"],
            "zone_high": zone["high"],
            "atr_14": zone["atr_14"],
            "quality_score": quality_score,
            "quality_grade": precision_grade,
            "precision_grade": precision_grade,
            "precision_qualified": precision_grade in {"A+", "A", "B", "C"},
            "rejection_wick_ratio": wick_ratio,
            "rejection_close_strength": close_strength,
            "retest_range_atr": retest_range_atr,
            "follow_body_ratio": follow_body_ratio,
            "follow_range_atr": follow_range_atr,
            "follow_through_strength": follow_strength,
            "follow_progress_atr": directional_progress,
            "risk_atr": risk_atr,
            "entry_displacement_atr": displacement,
            "entry_location_score": zone["entry_location_score"],
            "origin_model": zone.get("origin_model"),
            "origin_quality_score": zone.get("origin_quality_score"),
            "liquidity_sweep": zone.get("liquidity_sweep", False),
            "structure_break": zone.get("structure_break", False),
            "compression_break": zone.get("compression_break", False),
            "trend_pullback_reclaim": zone.get("trend_pullback_reclaim", False),
            "wider_trend_direction": zone.get("wider_trend_direction", "MIXED"),
            "news_spike_filtered": bool(zone.get("news_spike_risk")),
            "age_bars": max(0, len(rows) - 1 - confirmation_index),
            "confirmation_model": confirmation_model,
            "entry_pathway": entry_pathway,
            "confirmation_delay_bars": confirmation_delay_bars,
        }

    def _entry_event_with_diagnostics(
        self,
        rows: list[Dict[str, Any]],
        zone: Dict[str, Any],
        profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        trace: Dict[str, Any] = {}
        event = self._entry_event(rows, zone, profile, trace)
        return {"event": event, "trace": trace}

    @staticmethod
    def _zone_signal_state(
        zone: Dict[str, Any],
        trace: Dict[str, Any],
        event: Optional[Dict[str, Any]],
        profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        blocker = str(trace.get("blocker") or "")
        invalidated = blocker in {
            "ZONE_INVALIDATED_BEFORE_ENTRY",
            "ZONE_INVALIDATED_ON_FOLLOW_THROUGH",
            "RETEST_FATIGUE",
        } or zone.get("origin_broken") is True
        if event:
            stage, role, health = "CONFIRMED_ENTRY", "CONFIRMED_ENTRY", "CONFIRMED"
        elif invalidated:
            stage, role, health = "INVALIDATED", "INVALIDATED_CONTEXT", "INVALIDATED"
        elif not zone.get("entry_eligible_origin"):
            stage, role, health = "CONTEXT_ONLY", "MARKET_CONTEXT", "CONTEXT_ONLY"
        elif trace.get("follow_through"):
            stage, role, health = "RISK_REVIEW", "QUALIFIED_WATCH", "WATCH"
        elif trace.get("rejection"):
            stage, role, health = "REJECTION_CONFIRMED", "QUALIFIED_WATCH", "WATCH"
        elif trace.get("controlled_retest"):
            stage, role, health = "RETEST_ACTIVE", "QUALIFIED_WATCH", "WATCH"
        elif blocker == "NO_RETEST_IN_WINDOW" and int(zone.get("age_bars") or 0) > int(profile.get("entry_window_bars") or 0):
            stage, role, health = "STALE_NO_RETEST", "INVALIDATED_CONTEXT", "STALE"
        else:
            stage, role, health = "WAITING_RETEST", "QUALIFIED_WATCH", "WATCH"
        return {
            "entry_stage": stage,
            "display_role": role,
            "zone_health": health,
            "entry_blocker": blocker or None,
            "entry_blocker_label": DiamondZoneEngine._blocker_label(blocker) if blocker else None,
            "actionable_entry": bool(event),
        }

    @staticmethod
    def _diamond_confidence(
        zone: Dict[str, Any],
        trace: Dict[str, Any],
        event: Optional[Dict[str, Any]],
        profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build an auditable lifecycle-aware grade for every visible Diamond Zone."""
        origin = float(zone.get("origin_quality_score") or 0)
        location = float(zone.get("entry_location_score") or 0)
        wider_location = float(zone.get("wider_entry_location_score") or location)
        rejection = float(zone.get("rejection_score") or 0)
        structure_points = 0.0
        reasons: list[str] = []
        if zone.get("liquidity_sweep") and zone.get("structure_break") and zone.get("wider_structure_break"):
            structure_points = 15.0
            reasons.append("SWEEP_AND_WIDER_STRUCTURE")
        elif zone.get("liquidity_sweep") and zone.get("structure_break"):
            structure_points = 13.0
            reasons.append("SWEEP_AND_STRUCTURE")
        elif zone.get("liquidity_sweep"):
            structure_points = 11.0
            reasons.append("LIQUIDITY_SWEEP")
        elif zone.get("structure_break"):
            structure_points = 9.0
            reasons.append("STRUCTURE_BREAK")
        elif zone.get("compression_break"):
            structure_points = 8.0
            reasons.append("COMPRESSION_BREAK")
        elif zone.get("trend_pullback_reclaim"):
            structure_points = 7.0
            reasons.append("TREND_PULLBACK_RECLAIM")
        elif zone.get("scalp_key_zone") and zone.get("rejection_sweep"):
            structure_points = 10.0
            reasons.append("SCALP_WICK_REJECTION")
        else:
            structure_points = 4.0

        lifecycle = str(zone.get("lifecycle") or "")
        lifecycle_points = {"FRESH": 10.0, "TESTED": 7.0, "WEAKENED": 2.0, "FLIPPED": 0.0}.get(lifecycle, 3.0)
        if event:
            confirmation_points = 10.0
            reasons.append("CONFIRMED_CLOSED_CANDLE_ENTRY")
        elif trace.get("follow_through"):
            confirmation_points = 8.0
            reasons.append("FOLLOW_THROUGH")
        elif trace.get("rejection"):
            confirmation_points = 6.0
            reasons.append("REJECTION_CONFIRMED")
        elif trace.get("controlled_retest"):
            confirmation_points = 4.0
            reasons.append("CONTROLLED_RETEST")
        elif zone.get("entry_eligible_origin"):
            confirmation_points = 2.0
            reasons.append("ENTRY_GRADE_ORIGIN")
        else:
            confirmation_points = 0.0

        components = {
            "origin": round(min(30.0, origin * 0.30), 1),
            "location": round(min(20.0, (location * 0.42 + wider_location * 0.58) * 0.20), 1),
            "structure": round(structure_points, 1),
            "discovery": round(min(8.0, (
                (3.0 if zone.get("liquidity_sweep") or zone.get("wider_structure_break") else 0.0)
                + (2.5 if zone.get("compression_break") or zone.get("trend_pullback_reclaim") else 0.0)
                + (3.0 if zone.get("scalp_key_zone") and zone.get("rejection_sweep") else 0.0)
                + (2.0 if zone.get("continuation") and zone.get("direction_aligned") is not False else 0.0)
                + (1.5 if lifecycle == "FRESH" else 0.5 if lifecycle == "TESTED" else 0.0)
            )), 1),
            "lifecycle": round(lifecycle_points, 1),
            "rejection": round(min(10.0, rejection * 0.10), 1),
            "confirmation": round(confirmation_points, 1),
            "risk": (
                5.0 if trace.get("risk_quality")
                else 2.0 if zone.get("entry_eligible_origin")
                else 1.0 if zone.get("execution_impulse_ready")
                else 0.0
            ),
        }
        penalties: Dict[str, float] = {}

        blocker = str(trace.get("blocker") or "")
        if zone.get("news_spike_risk"):
            penalties["news_spike"] = 12.0
            reasons.append("NEWS_SPIKE_PENALTY")
        if lifecycle == "WEAKENED":
            penalties["retest_fatigue"] = 10.0
            reasons.append("RETEST_FATIGUE")
        if lifecycle == "FLIPPED" or blocker.startswith("ZONE_INVALIDATED") or blocker == "RETEST_FATIGUE":
            penalties["invalidated"] = 35.0
            reasons.append("ZONE_INVALIDATED")
        if zone.get("direction_aligned") is False:
            if zone.get("scalp_key_zone"):
                penalties["htf_conflict"] = 6.0
                reasons.append("SCALP_COUNTERTREND_WATCH")
            else:
                penalties["htf_conflict"] = 15.0
                reasons.append("HTF_DIRECTION_CONFLICT")
        distance = float(zone.get("distance_atr") or 0)
        max_distance = float(profile.get("max_context_distance_atr") or 2.25)
        if distance > max_distance:
            penalties["distance"] = round(min(18.0, (distance - max_distance) * 6), 1)
            reasons.append("DISTANCE_PENALTY")

        key_zone_score = sum(components.values())
        entry_confidence_score = key_zone_score - sum(penalties.values())
        if event:
            event_score = float(event.get("quality_score") or 0)
            key_zone_score = max(key_zone_score, event_score)
            entry_confidence_score = max(entry_confidence_score, event_score)
            tier = "ENTRY_READY"
        else:
            entry_confidence_score = max(0, min(100, entry_confidence_score))
            if lifecycle == "FLIPPED" or blocker.startswith("ZONE_INVALIDATED") or blocker == "RETEST_FATIGUE":
                tier = "INVALIDATED"
            elif entry_confidence_score >= 84 and zone.get("entry_eligible_origin"):
                tier = "HIGH_CONVICTION"
            elif entry_confidence_score >= 72 and zone.get("entry_eligible_origin"):
                tier = "QUALIFIED"
            elif entry_confidence_score >= 60:
                tier = "DEVELOPING"
            else:
                tier = "CONTEXT"
        key_zone_score = round(max(0, min(100, key_zone_score)))
        entry_confidence_score = round(max(0, min(100, entry_confidence_score)))
        invalidated = lifecycle == "FLIPPED" or blocker.startswith("ZONE_INVALIDATED") or blocker == "RETEST_FATIGUE"
        visible_floor = int(profile.get("min_visible_diamond_score", DiamondZoneEngine.MIN_VISIBLE_DIAMOND_SCORE))
        grade = DiamondZoneEngine._diamond_grade(key_zone_score, invalidated, visible_floor)
        return {
            "diamond_score": key_zone_score,
            "diamond_grade": grade,
            "diamond_confidence_score": key_zone_score,
            "key_zone_score": key_zone_score,
            "entry_confidence_score": entry_confidence_score,
            "diamond_confidence_tier": tier,
            "diamond_confidence_reasons": reasons,
            "score_components": components,
            "score_penalties": penalties,
            "grade_model": "DIAMOND_GRADE_V2_SCORE_GATED",
            "diamond_ranking_model": "ZONE_INTELLIGENCE_V4_SCORE_GATED",
        }

    @staticmethod
    def _blocker_label(value: str) -> str:
        labels = {
            "ORIGIN_NOT_ENTRY_ELIGIBLE": "Context origin is not entry-grade",
            "ZONE_INVALIDATED_BEFORE_ENTRY": "Zone invalidated before retest",
            "ZONE_INVALIDATED_ON_FOLLOW_THROUGH": "Zone invalidated on follow-through",
            "NO_RETEST_IN_WINDOW": "No controlled retest in the entry window",
            "WEAK_REJECTION": "Retest rejection is too weak",
            "NO_DIRECTIONAL_FOLLOW_THROUGH": "No directional closed follow-through",
            "RISK_WIDTH_OUT_OF_RANGE": "Stop width is outside the ATR policy",
            "ENTRY_TOO_DISPLACED": "Entry is too far from the Diamond line",
            "QUALITY_SCORE_BELOW_MINIMUM": "Entry quality is below the required floor",
            "RETEST_FATIGUE": "Zone has been tested too many times",
            "COUNTER_TREND_WITHOUT_REVERSAL": "Strong-trend conflict needs a sweep and structure reversal",
        }
        return labels.get(value, value.replace("_", " ").title())

    @staticmethod
    def _gate_funnel(
        counts: Counter[str],
        blockers: Counter[str],
        diagnostics: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        stage_definitions = [
            ("scanned", "Closed candles scanned"),
            ("volatility_ready", "ATR and range ready"),
            ("directional", "Directional candles"),
            ("impulse_quality", "Impulse quality"),
            ("location_quality", "Premium/discount location"),
            ("structural_context", "Structure or expansion"),
            ("context_zones", "Diamond context zones"),
            ("qualified_origins", "Entry-grade origins"),
            ("controlled_retest", "Controlled retest"),
            ("rejection", "Directional rejection"),
            ("follow_through", "Closed follow-through"),
            ("risk_quality", "Risk geometry"),
            ("confirmed_entries", "Confirmed Diamond entries"),
        ]
        blocker_labels = {
            "INVALID_RANGE": "Invalid candle range",
            "ATR_NOT_READY": "ATR history not ready",
            "NO_DIRECTION": "No candle direction",
            "WEAK_BODY": "Body is too small",
            "LOW_RANGE_EXPANSION": "Range expansion is too low",
            "WEAK_CLOSE": "Close strength is too weak",
            "LOW_IMPULSE_SCORE": "Impulse score is below minimum",
            "POOR_CONTEXT_LOCATION": "Poor premium/discount location",
            "POOR_WIDER_RANGE_LOCATION": "Poor location in the wider dealing range",
            "NO_STRUCTURE_OR_EXPANSION": "No structure break or clean expansion",
            "WEAK_PREMIUM_DISCOUNT_LOCATION": "Execution location is not precise enough",
            "WEAK_WIDER_RANGE_LOCATION": "Wider-range execution location is not precise enough",
            "ORIGIN_QUALITY_BELOW_ENTRY_FLOOR": "Origin grade is below the entry floor",
            "HTF_DIRECTION_CONFLICT": "Origin direction conflicts with higher-timeframe context",
            "COUNTER_TREND_WITHOUT_REVERSAL": "Counter-trend origin lacks sweep plus structure reversal proof",
            "NO_STRUCTURAL_OR_LIQUIDITY_EVENT": "No structural or liquidity event",
            "OVERSIZED_NEWS_SPIKE": "Oversized spike is filtered",
            "CONTEXT_ONLY_ORIGIN": "Context-only origin",
            "ORIGIN_NOT_ENTRY_ELIGIBLE": "Origin is context-only",
            "ZONE_INVALIDATED_BEFORE_ENTRY": "Zone invalidated before retest",
            "RETEST_TOO_EARLY": "Retest arrived too early",
            "SPIKE_COOLDOWN": "Spike cooldown is active",
            "RETEST_TOO_VOLATILE": "Retest is too volatile",
            "WEAK_REJECTION": "Retest rejection is too weak",
            "ZONE_INVALIDATED_ON_FOLLOW_THROUGH": "Zone failed on follow-through",
            "NO_DIRECTIONAL_FOLLOW_THROUGH": "No directional follow-through",
            "WEAK_FOLLOW_BODY": "Follow-through body is too small",
            "WEAK_FOLLOW_CLOSE": "Follow-through close is too weak",
            "LOW_DIRECTIONAL_PROGRESS": "Directional progress is too low",
            "FOLLOW_CANDLE_TOO_VOLATILE": "Follow-through candle is too volatile",
            "RISK_WIDTH_OUT_OF_RANGE": "Stop width is outside the ATR range",
            "ENTRY_TOO_DISPLACED": "Entry is too far from the Diamond line",
            "QUALITY_SCORE_BELOW_MINIMUM": "Entry quality score is below minimum",
            "RETEST_FATIGUE": "Zone has too many retests for a fresh entry",
            "NO_RETEST_IN_WINDOW": "No retest inside the confirmation window",
            "NO_VALID_ENTRY_SEQUENCE": "No valid retest-to-follow-through sequence",
        }
        scanned = int(counts.get("scanned", 0))
        stages = []
        deepest = -1
        for index, (identifier, label) in enumerate(stage_definitions):
            count = int(counts.get(identifier, 0))
            if count > 0:
                deepest = index
            stages.append({
                "id": identifier,
                "label": label,
                "count": count,
                "percent_of_scan": round(count / scanned * 100, 1) if scanned else 0.0,
                "reached": count > 0,
            })
        next_index = min(len(stages) - 1, deepest + 1) if deepest >= 0 else 0
        top_blockers = [
            {
                "id": identifier,
                "label": blocker_labels.get(identifier, identifier.replace("_", " ").title()),
                "count": int(count),
                "percent_of_scan": round(int(count) / scanned * 100, 1) if scanned else 0.0,
            }
            for identifier, count in blockers.most_common(6)
        ]
        return {
            "status": "CONFIRMED" if counts.get("confirmed_entries", 0) else "WAITING_AT_GATE",
            "current_gate": stages[deepest]["id"] if deepest >= 0 else "scanned",
            "next_gate": None if counts.get("confirmed_entries", 0) else stages[next_index]["id"],
            "stages": stages,
            "top_blockers": top_blockers,
            "zone_traces": [dict(item.get("trace") or {}) for item in diagnostics],
            "uses_completed_candles_only": True,
            "changes_signal_logic": False,
        }

    @staticmethod
    def _closed_beyond_zone(row: Dict[str, Any], zone: Dict[str, Any]) -> bool:
        return bool(
            row["close"] < zone["low"]
            if zone["entry_side"] == "BUY"
            else row["close"] > zone["high"]
        )

    @staticmethod
    def _distinct_entry_events(events: list[Dict[str, Any]], profile: Dict[str, Any]) -> list[Dict[str, Any]]:
        selected: list[Dict[str, Any]] = []
        cooldown_seconds = int(profile["entry_cooldown_bars"]) * int(profile["timeframe_seconds"])
        dedupe_distance_atr = float(profile.get("entry_dedupe_distance_atr") or 0.35)
        for event in sorted(events, key=lambda item: int(item["time"])):
            nearby_index = next((
                index for index in range(len(selected) - 1, -1, -1)
                if selected[index]["entry_side"] == event["entry_side"]
                and int(event["time"]) - int(selected[index]["time"]) <= cooldown_seconds
                and abs(float(event["line"]) - float(selected[index]["line"])) <= max(
                    float(event.get("atr_14") or 0),
                    float(selected[index].get("atr_14") or 0),
                    1e-9,
                ) * dedupe_distance_atr
            ), None)
            if nearby_index is None:
                selected.append(event)
            elif event["quality_score"] >= selected[nearby_index]["quality_score"] + 8:
                selected[nearby_index] = event
        max_daily = int(profile.get("max_daily_entries") or 3)
        daily: Dict[int, list[Dict[str, Any]]] = {}
        for event in selected:
            daily.setdefault(int(event["time"]) // 86400, []).append(event)
        capped = []
        for day_events in daily.values():
            strongest = sorted(day_events, key=lambda item: (-int(item.get("quality_score") or 0), int(item["time"])))[:max_daily]
            capped.extend(strongest)
        return sorted(capped, key=lambda item: int(item["time"]))[-max_daily:]

    def _retests(self, rows: list[Dict[str, Any]], zone: Dict[str, Any]) -> int:
        after = [row for row in rows if row["time"] > zone["time"]]
        retests = 0
        was_inside = False
        for row in after:
            inside = row["low"] <= zone["high"] and row["high"] >= zone["low"]
            if inside and not was_inside:
                retests += 1
            was_inside = inside
        return retests

    @staticmethod
    def _origin_broken(rows: list[Dict[str, Any]], zone: Dict[str, Any]) -> bool:
        consecutive = 0
        for row in rows:
            if row["time"] <= zone["time"]:
                continue
            broken = (
                row["close"] < zone["low"]
                if zone["direction"] == "BULLISH"
                else row["close"] > zone["high"]
            )
            consecutive = consecutive + 1 if broken else 0
            if consecutive >= 2:
                return True
        return False

    @staticmethod
    def _lifecycle(zone: Dict[str, Any]) -> str:
        if zone.get("origin_broken"):
            return "FLIPPED"
        if zone.get("retests", 0) == 0:
            return "FRESH"
        if zone.get("retests", 0) <= 2:
            return "TESTED"
        return "WEAKENED"

    @staticmethod
    def _quality_grade(score: float) -> str:
        if score >= 90:
            return "A+"
        if score >= 82:
            return "A"
        if score >= 74:
            return "B"
        return "C"

    @staticmethod
    def _diamond_grade(score: float, invalidated: bool = False, minimum_d_score: float = 50) -> Optional[str]:
        if invalidated:
            return None
        if score >= 90:
            return "A+"
        if score >= 80:
            return "A"
        if score >= 70:
            return "B"
        if score >= 60:
            return "C"
        if score >= minimum_d_score:
            return "D"
        return None

    @staticmethod
    def _confirmation_state(price_side: str, candle_color: str) -> str:
        if price_side == "INSIDE":
            return "TESTING"
        if price_side == "ABOVE":
            return "CONFIRMED_HOLD" if candle_color == "BULLISH" else "HOLDING_ABOVE"
        return "CONFIRMED_REJECTION" if candle_color == "BEARISH" else "HOLDING_BELOW"

    @staticmethod
    def _primary_rank(zone: Dict[str, Any], expected: str) -> tuple:
        expected_side = "ABOVE" if expected == "BULLISH" else "BELOW" if expected == "BEARISH" else None
        expected_direction = expected if expected in {"BULLISH", "BEARISH"} else None
        role_rank = {
            "CONFIRMED_ENTRY": 0,
            "QUALIFIED_WATCH": 1,
            "MARKET_CONTEXT": 2,
            "INVALIDATED_CONTEXT": 3,
        }.get(zone.get("display_role"), 4)
        lifecycle_rank = {"FRESH": 0, "TESTED": 1, "WEAKENED": 2, "FLIPPED": 3}.get(zone.get("lifecycle"), 4)
        execution_rank = {"READY": 0, "WATCH": 1, "WAIT_RETEST": 2, "CONTEXT_ONLY": 3, "INVALID": 4}.get(zone.get("execution_quality"), 5)
        return (
            role_rank,
            execution_rank,
            0 if expected_direction and zone.get("direction") == expected_direction else 1,
            0 if expected_side and zone.get("price_side") == expected_side else 1,
            0 if zone.get("price_side") == "INSIDE" else 1,
            -float(zone.get("diamond_confidence_score") or 0),
            round(float(zone.get("distance_atr") or 0), 4),
            lifecycle_rank,
            -float(zone.get("zone_strength_score") or 0),
            -float(zone.get("effective_score") or 0),
            -int(zone.get("time") or 0),
        )

    @classmethod
    def _lead_diamond_zone(
        cls,
        zones: list[Dict[str, Any]],
        entry_events: list[Dict[str, Any]],
        expected: str,
        profile: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Select one fresh, strategy-confirmed zone for the live chart."""
        score_floor = int(profile.get("lead_diamond_score") or 70)
        max_age = int(profile.get("lead_zone_max_age_bars") or profile.get("entry_window_bars") or 12)
        event_by_zone = {
            str(event.get("zone_id")): event
            for event in entry_events
            if int(event.get("quality_score") or 0) >= score_floor
        }
        scalp_watch_enabled = bool(
            str(profile.get("trading_style") or "").upper() == "SCALPING"
            and profile.get("scalp_wick_rejection_enabled")
        )
        candidates = [
            zone for zone in zones
            if zone.get("display_as_diamond")
            and zone.get("strategy_confirmed_origin") is True
            and int(zone.get("diamond_score") or 0) >= score_floor
            and str(zone.get("lifecycle") or "") in {"FRESH", "TESTED"}
            and str(zone.get("zone_health") or "") not in {"INVALIDATED", "STALE", "REJECTED"}
            and str(zone.get("execution_quality") or "") in {"READY", "WATCH", "WAIT_RETEST"}
            and zone.get("origin_broken") is not True
            and zone.get("direction_holding") is True
            and int(zone.get("age_bars") or 0) <= max_age
            and float(zone.get("distance_atr") or 0) <= float(profile.get("max_context_distance_atr") or 2.5)
            and (
                expected not in {"BULLISH", "BEARISH"}
                or zone.get("direction") == expected
                or (scalp_watch_enabled and zone.get("scalp_key_zone"))
            )
        ]
        if not candidates:
            return None

        def rank(zone: Dict[str, Any]) -> tuple:
            event = event_by_zone.get(str(zone.get("id")))
            return (
                0 if event else 1,
                -int((event or {}).get("quality_score") or zone.get("diamond_score") or 0),
                cls._primary_rank(zone, expected),
            )

        return min(candidates, key=rank)

    def combine_timeframes(
        self,
        results: Dict[str, Dict[str, Any]],
        trading_style: str = "SCALPING",
    ) -> Dict[str, Any]:
        style = self._normalize_trading_style(trading_style)
        style_profile = self.trading_style_profile(style)
        weights = style_profile["weights"]
        quality_weights = {"A+": 1.0, "A": 0.92, "B": 0.80, "C": 0.65, "D": 0.50}
        confirmation_weights = {
            "CONFIRMED_HOLD": 1.0,
            "CONFIRMED_REJECTION": 1.0,
            "HOLDING_ABOVE": 0.80,
            "HOLDING_BELOW": 0.80,
            "TESTING": 0.45,
        }
        lifecycle_weights = {"FRESH": 1.0, "TESTED": 0.90, "WEAKENED": 0.65, "FLIPPED": 0.45}
        execution_weights = {"READY": 1.0, "WATCH": 0.82, "WAIT_RETEST": 0.62, "CONTEXT_ONLY": 0.38, "INVALID": 0.15}
        snapshots: Dict[str, Any] = {}
        weighted_score = 0.0
        total_weight = 0
        expected = "MIXED"
        trusted_ready = 0
        for timeframe, weight in weights.items():
            item = results.get(timeframe) or {}
            primary = item.get("primary_zone") or {}
            if item.get("expected_direction") in {"BULLISH", "BEARISH"}:
                expected = item["expected_direction"]
            trusted = item.get("feed_matched", item.get("execution_trusted") is not False) is not False
            bias = item.get("directional_bias") or "WAIT"
            execution_quality = str(item.get("execution_quality") or primary.get("execution_quality") or "WAITING")
            primary_grade = str(primary.get("diamond_grade") or item.get("diamond_grade") or item.get("quality_grade") or "")
            score_gate_present = "diamond_display_status" in item or "entry_score_qualified" in primary
            entry_grade_ready = bool(
                primary.get("entry_score_qualified")
                if score_gate_present
                else primary_grade in {"A+", "A", "B", "C"}
            )
            frame_role = "DIRECTION" if timeframe == style_profile["confirmation_timeframe"] else "TRIGGER"
            base_ready = bool(
                item.get("status") == "READY"
                and item.get("execution_trusted", trusted) is not False
                and bias in {"BUY_CONTEXT", "SELL_CONTEXT"}
                and str(primary.get("lifecycle") or "FRESH") != "FLIPPED"
            )
            ready = bool(
                base_ready
                and (
                    execution_quality not in {"INVALID", "CONTEXT_ONLY"}
                    if frame_role == "DIRECTION"
                    else execution_quality == "READY" and entry_grade_ready
                )
            )
            quality_factor = quality_weights.get(primary_grade, 0.35)
            confirmation_factor = confirmation_weights.get(str(item.get("confirmation_state") or "WAITING"), 0.35)
            lifecycle_factor = lifecycle_weights.get(str(primary.get("lifecycle") or "WEAKENED"), 0.65)
            execution_factor = execution_weights.get(execution_quality, 0.15)
            strength = quality_factor * confirmation_factor * lifecycle_factor * execution_factor
            contribution = (100 if bias == "BUY_CONTEXT" else -100 if bias == "SELL_CONTEXT" else 0) * strength
            if ready:
                trusted_ready += 1
                weighted_score += contribution * weight
                total_weight += weight
            snapshots[timeframe] = {
                "status": item.get("status") or "WAITING",
                "trusted": trusted,
                "directional_bias": bias,
                "entry_grade_ready": entry_grade_ready,
                "frame_role": frame_role,
                "strategy_state": item.get("strategy_state") or "WAITING",
                "confirmation_state": item.get("confirmation_state") or "WAITING",
                "quality_grade": item.get("quality_grade") or "-",
                "diamond_grade": primary.get("diamond_grade") or item.get("diamond_grade") or "-",
                "diamond_score": primary.get("diamond_score") or item.get("diamond_score"),
                "line": primary.get("line"),
                "role": primary.get("role"),
                "lifecycle": primary.get("lifecycle"),
                "rejection_status": item.get("rejection_status") or primary.get("rejection_status"),
                "execution_quality": item.get("execution_quality") or primary.get("execution_quality"),
                "precision_ready": ready,
                "zone_strength_score": item.get("zone_strength_score") or primary.get("zone_strength_score"),
                "weighted_contribution": round(contribution),
            }

        score = round(weighted_score / total_weight) if total_weight else 0
        required_ready = len(weights)
        direction_frame = snapshots.get(style_profile["confirmation_timeframe"]) or {}
        trigger_frame = snapshots.get(style_profile["execution_timeframe"]) or {}
        direction_bias = direction_frame.get("directional_bias")
        trigger_bias = trigger_frame.get("directional_bias")
        frames_agree = bool(
            direction_bias in {"BUY_CONTEXT", "SELL_CONTEXT"}
            and trigger_bias == direction_bias
        )
        alignment_floor = int(style_profile["minimum_alignment_score"])
        if trusted_ready == required_ready and frames_agree:
            state = "ALIGNED_BULLISH" if score >= alignment_floor else "ALIGNED_BEARISH" if score <= -alignment_floor else "MIXED"
        elif trusted_ready:
            state = "PARTIAL_BULLISH" if score > 0 else "PARTIAL_BEARISH" if score < 0 else "PARTIAL_WAIT"
        else:
            state = "WAITING"
        direction = "BULLISH" if state == "ALIGNED_BULLISH" else "BEARISH" if state == "ALIGNED_BEARISH" else "MIXED"
        risk_filter = (
            "ALIGNED" if direction == expected and direction in {"BULLISH", "BEARISH"}
            else "CONFLICT" if direction in {"BULLISH", "BEARISH"} and expected in {"BULLISH", "BEARISH"}
            else "WAIT"
        )
        return {
            "status": "READY" if trusted_ready == required_ready else "PARTIAL" if trusted_ready else "WAITING",
            "trading_style": style,
            "profile_label": style_profile["label"],
            "execution_timeframe": style_profile["execution_timeframe"],
            "confirmation_timeframe": style_profile["confirmation_timeframe"],
            "structure_timeframe": style_profile["structure_timeframe"],
            "required_timeframes": list(weights),
            "state": state,
            "score": score,
            "confidence": abs(score),
            "direction": direction,
            "expected_direction": expected,
            "risk_filter": risk_filter,
            "ready_timeframes": trusted_ready,
            "style_confirmation": {
                "status": "CONFIRMED" if state in {"ALIGNED_BULLISH", "ALIGNED_BEARISH"} else "WAITING",
                "direction_timeframe": style_profile["confirmation_timeframe"],
                "trigger_timeframe": style_profile["execution_timeframe"],
                "direction_bias": direction_bias or "WAIT",
                "trigger_bias": trigger_bias or "WAIT",
                "frames_agree": frames_agree,
                "minimum_alignment_score": alignment_floor,
                "completed_candles_only": True,
            },
            "timeframes": snapshots,
            "uses_completed_candles_only": True,
            "formula": (
                f"{style_profile['label']}: {style_profile['structure_timeframe']} anchors market structure, "
                f"{style_profile['confirmation_timeframe']} provides trusted direction "
                f"without an opposite conflict; {style_profile['execution_timeframe']} must provide the Grade C or better "
                "closed-candle trigger before alignment can arm an entry"
            ),
        }

    @staticmethod
    def _normalize_trading_style(value: str) -> str:
        return "SWING" if str(value or "").strip().upper() == "SWING" else "SCALPING"

    @classmethod
    def trading_style_profile(cls, trading_style: str) -> Dict[str, Any]:
        style = cls._normalize_trading_style(trading_style)
        if style == "SWING":
            return {
                "style": style,
                "label": "1H Intraday / Swing Core",
                "execution_timeframe": "1H",
                "confirmation_timeframe": "4H",
                "structure_timeframe": "1D",
                "weights": {"4H": 60, "1H": 40},
                "minimum_alignment_score": 55,
            }
        return {
            "style": style,
            "label": "5M Scalp Core",
            "execution_timeframe": "5M",
            "confirmation_timeframe": "15M",
            "structure_timeframe": "1H",
            "weights": {"15M": 58, "5M": 42},
            "minimum_alignment_score": 50,
        }

    def _profile(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        profile = dict(self._threshold_profile(symbol, timeframe))
        for key, adjustment in self.profile_adjustments.items():
            current = profile.get(key)
            if isinstance(current, (int, float)):
                profile[key] = round(float(current) + float(adjustment), 6)
        if self.profile_suffix:
            profile["name"] = f"{profile['name']}_{self.profile_suffix}"
        return profile

    @staticmethod
    def _adaptive_profile(
        profile: Dict[str, Any],
        rows: list[Dict[str, Any]],
        symbol: str,
        timeframe: str,
    ) -> Dict[str, Any]:
        """Adapt timing and safety gates without weakening the production score floor."""
        runtime = dict(profile)
        normalized_symbol = str(symbol or "XAUUSD").upper()
        normalized_timeframe = str(timeframe or "15M").upper()
        ranges = [max(0.0, float(row["high"]) - float(row["low"])) for row in rows]
        recent = ranges[-24:]
        baseline = ranges[-96:-24] or ranges[:-24][-48:]
        recent_median = median(recent) if recent else 0.0
        baseline_median = median(baseline) if baseline else recent_median
        volatility_ratio = recent_median / baseline_median if baseline_median > 0 else 1.0
        regime = "ELEVATED" if volatility_ratio >= 1.45 else "QUIET" if volatility_ratio <= 0.72 else "NORMAL"
        recent_closes = [float(row["close"]) for row in rows[-36:]]
        directional_path = sum(abs(right - left) for left, right in zip(recent_closes, recent_closes[1:]))
        directional_efficiency = (
            abs(recent_closes[-1] - recent_closes[0]) / directional_path
            if len(recent_closes) > 1 and directional_path > 0
            else 0.0
        )
        structure = "TRENDING" if directional_efficiency >= 0.42 else "CHOPPY" if directional_efficiency <= 0.22 else "BALANCED"
        adjustments: list[str] = []
        runtime["zone_merge_distance_atr"] = {
            "5M": 0.22,
            "15M": 0.20,
            "1H": 0.18,
            "4H": 0.16,
        }.get(normalized_timeframe, 0.20)
        runtime["zone_merge_window_bars"] = {
            "5M": 10,
            "15M": 8,
            "1H": 6,
            "4H": 5,
        }.get(normalized_timeframe, 8)
        runtime["origin_cooldown_bars"] = {
            "5M": 12,
            "15M": 8,
            "1H": 4,
            "4H": 3,
        }.get(normalized_timeframe, 8)
        runtime["flip_cluster_bars"] = {
            "5M": 6,
            "15M": 4,
            "1H": 3,
            "4H": 2,
        }.get(normalized_timeframe, 4)
        runtime["flip_cluster_distance_atr"] = 0.65

        if regime == "ELEVATED" and normalized_timeframe in {"5M", "15M"}:
            runtime["min_entry_quality"] = min(100, int(runtime["min_entry_quality"]) + 2)
            runtime["min_active_entry_quality"] = min(100, int(runtime["min_active_entry_quality"]) + 2)
            runtime["min_scalp_reaction_quality"] = min(100, int(runtime["min_scalp_reaction_quality"]) + 2)
            runtime["max_live_chase_atr"] = round(max(0.20, float(runtime["max_live_chase_atr"]) - 0.05), 3)
            runtime["entry_cooldown_bars"] = int(runtime["entry_cooldown_bars"]) + 1
            runtime["zone_merge_distance_atr"] = round(float(runtime["zone_merge_distance_atr"]) + 0.08, 3)
            runtime["zone_merge_window_bars"] = int(runtime["zone_merge_window_bars"]) + 2
            runtime["max_daily_entries"] = max(2, int(runtime["max_daily_entries"]) - 1)
            adjustments.extend(["STRONGER_CONFIRMATION", "TIGHTER_ANTI_CHASE", "LONGER_DEDUPE"])
        elif regime == "QUIET":
            runtime["entry_window_bars"] = int(runtime["entry_window_bars"]) + 2
            runtime["lead_zone_max_age_bars"] = int(runtime["lead_zone_max_age_bars"]) + 2
            runtime["context_zone_limit"] = int(runtime["context_zone_limit"]) + (4 if normalized_timeframe == "5M" else 2)
            adjustments.extend(["LONGER_RETEST_WINDOW", "LONGER_ZONE_PATIENCE"])

        if structure == "CHOPPY":
            runtime["zone_merge_distance_atr"] = round(float(runtime["zone_merge_distance_atr"]) + 0.07, 3)
            runtime["zone_merge_window_bars"] = int(runtime["zone_merge_window_bars"]) + 2
            runtime["entry_cooldown_bars"] = int(runtime["entry_cooldown_bars"]) + 1
            adjustments.extend(["CHOP_DUPLICATE_MERGE", "CHOP_COOLDOWN"])
        elif structure == "TRENDING" and normalized_timeframe in {"5M", "15M"}:
            runtime["active_follow_window_bars"] = int(runtime["active_follow_window_bars"]) + 1
            runtime["lead_zone_max_age_bars"] = int(runtime["lead_zone_max_age_bars"]) + 1
            runtime["origin_cooldown_bars"] = int(runtime["origin_cooldown_bars"]) + 2
            adjustments.extend(["TREND_CONTINUATION_WINDOW", "TREND_ZONE_PATIENCE", "STRONG_TREND_ANTI_SPAM"])

        runtime["adaptive_regime"] = regime
        runtime["adaptive_volatility_ratio"] = round(volatility_ratio, 3)
        runtime["adaptive_structure"] = structure
        runtime["adaptive_directional_efficiency"] = round(directional_efficiency, 3)
        runtime["adaptive_adjustments"] = adjustments or ["BASELINE_GATES"]
        runtime["asset_model"] = runtime.get("asset_model") or (
            "XAU_PRECISION" if normalized_symbol == "XAUUSD" else "BTC_CONTINUATION" if normalized_symbol == "BTCUSD" else "CROSS_ASSET"
        )
        return runtime

    @staticmethod
    def _adaptive_profile_summary(profile: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "version": "ADAPTIVE_PROFILE_V8_DUAL_CORE",
            "asset_model": profile.get("asset_model") or "CROSS_ASSET",
            "regime": profile.get("adaptive_regime") or "WAITING",
            "structure": profile.get("adaptive_structure") or "WAITING",
            "volatility_ratio": profile.get("adaptive_volatility_ratio"),
            "directional_efficiency": profile.get("adaptive_directional_efficiency"),
            "adjustments": list(profile.get("adaptive_adjustments") or []),
            "density": {
                "target_per_100_bars": profile.get("target_diamonds_per_100_bars"),
                "merge_distance_atr": profile.get("zone_merge_distance_atr"),
                "merge_window_bars": profile.get("zone_merge_window_bars"),
                "origin_cooldown_bars": profile.get("origin_cooldown_bars"),
                "flip_cluster_bars": profile.get("flip_cluster_bars"),
            },
            "core_focus": {
                "execution_timeframe": profile.get("core_execution_timeframe"),
                "structure_timeframe": profile.get("core_structure_timeframe"),
            },
            "closed_candles_only": True,
            "quality_floor_preserved": True,
        }

    @staticmethod
    def _style_adjusted_profile(
        profile: Dict[str, Any],
        trading_style: Optional[str],
        timeframe: str,
    ) -> Dict[str, Any]:
        runtime = dict(profile)
        normalized_timeframe = str(timeframe or "15M").upper()
        style = str(trading_style or ("SWING" if normalized_timeframe in {"1H", "4H"} else "SCALPING")).upper()
        if style == "SWING":
            runtime["trading_style"] = "SWING"
            runtime["core_execution_timeframe"] = "1H"
            runtime["core_structure_timeframe"] = "1D"
            runtime["target_diamonds_per_100_bars"] = "3-5" if normalized_timeframe == "1H" else "2-4"
            runtime["entry_window_bars"] = int(runtime["entry_window_bars"]) + (2 if normalized_timeframe == "1H" else 1)
            runtime["lead_zone_max_age_bars"] = int(runtime["lead_zone_max_age_bars"]) + (3 if normalized_timeframe == "1H" else 2)
            runtime["entry_cooldown_bars"] = int(runtime["entry_cooldown_bars"]) + 1
            if normalized_timeframe == "1H":
                asset_model = str(runtime.get("asset_model") or "")
                quality_floor = 72 if asset_model == "XAU_PRECISION" else 70
                runtime["lead_diamond_score"] = {
                    "QUIET": 66,
                    "NORMAL": 68,
                    "ELEVATED": 72,
                }.get(str(runtime.get("adaptive_regime") or "NORMAL"), 68)
                runtime["active_follow_window_bars"] = int(runtime["active_follow_window_bars"]) + 1
                runtime["min_entry_quality"] = max(int(runtime["min_entry_quality"]), quality_floor)
                runtime["min_active_entry_quality"] = max(int(runtime["min_active_entry_quality"]), quality_floor - 4)
                runtime["min_reclaim_entry_quality"] = max(int(runtime["min_reclaim_entry_quality"]), quality_floor - 4)
                runtime["max_retest_touches"] = min(2, int(runtime["max_retest_touches"]))
                runtime["max_daily_entries"] = max(3, int(runtime["max_daily_entries"]))
            return runtime

        runtime["trading_style"] = "SCALPING"
        runtime["core_execution_timeframe"] = "5M"
        runtime["core_structure_timeframe"] = "1H"
        runtime["target_diamonds_per_100_bars"] = "4-6"
        if normalized_timeframe == "5M":
            regime = str(runtime.get("adaptive_regime") or "NORMAL")
            runtime["lead_diamond_score"] = {
                "QUIET": 64,
                "NORMAL": 66,
                "ELEVATED": 70,
            }.get(regime, 66)
            runtime["entry_window_bars"] = int(runtime["entry_window_bars"]) + 2
            runtime["active_follow_window_bars"] = int(runtime["active_follow_window_bars"]) + 1
            runtime["lead_zone_max_age_bars"] = int(runtime["lead_zone_max_age_bars"]) + 1
            runtime["entry_cooldown_bars"] = max(5, int(runtime["entry_cooldown_bars"]) - 1)
            runtime["max_daily_entries"] = min(4, int(runtime["max_daily_entries"]))
        return runtime

    @staticmethod
    def _threshold_profile(symbol: str, timeframe: str) -> Dict[str, Any]:
        normalized_symbol = str(symbol or "XAUUSD").upper()
        normalized_timeframe = str(timeframe or "15M").upper()
        if normalized_symbol == "XAUUSD":
            entry_profiles = {
                "5M": (0.48, 0.98, 0.64, 62, 1.45, 28, 8, 56, 74),
                "15M": (0.52, 1.08, 0.67, 66, 1.42, 18, 8, 65, 72),
                "1H": (0.50, 1.06, 0.66, 65, 1.40, 12, 6, 64, 70),
                "4H": (0.50, 1.05, 0.65, 65, 1.38, 9, 4, 64, 70),
            }
            context_profiles = {
                "5M": (0.44, 0.92, 0.60, 58, 1.23),
                "15M": (0.43, 0.90, 0.59, 56, 1.20),
                "1H": (0.42, 0.88, 0.58, 55, 1.18),
                "4H": (0.42, 0.87, 0.57, 55, 1.16),
            }
            entry_body, entry_range, entry_close, entry_score, _, window, cooldown, execution_location, entry_quality = entry_profiles.get(normalized_timeframe, entry_profiles["15M"])
            body, range_ratio, close, score, expansion = context_profiles.get(normalized_timeframe, context_profiles["15M"])
            location_window = {"5M": 36, "15M": 32, "1H": 24, "4H": 20}.get(normalized_timeframe, 32)
            wider_execution_location = 54 if normalized_timeframe == "5M" else 64 if normalized_timeframe == "15M" else 62
            origin_quality_floor = 64 if normalized_timeframe == "5M" else 74 if normalized_timeframe == "15M" else 72
            return {
                "name": f"XAU_ADAPTIVE_PRECISION_V7_{normalized_timeframe}",
                "asset_model": "XAU_PRECISION",
                "min_visible_diamond_score": DiamondZoneEngine.XAU_MIN_VISIBLE_DIAMOND_SCORE,
                "min_body_ratio": body,
                "min_range_ratio": range_ratio,
                "min_close_strength": close,
                "min_score": score,
                "entry_min_body_ratio": entry_body,
                "entry_min_range_ratio": entry_range,
                "entry_min_close_strength": entry_close,
                "entry_min_score": entry_score,
                "expansion_override": expansion,
                "atr_band": 0.12,
                "range_band": 0.07,
                "max_context_distance_atr": 2.25,
                "location_window_bars": location_window,
                "min_entry_location_score": 45,
                "min_macro_location_score": 42,
                "min_execution_location_score": execution_location,
                "min_macro_execution_location_score": wider_execution_location,
                "min_origin_quality_for_entry": origin_quality_floor,
                "min_entry_quality": entry_quality,
                "min_retest_close_strength": 0.55,
                "min_rejection_wick": 0.12,
                "min_rejection_body": 0.48,
                "min_retest_delay_bars": 1,
                "max_retest_range_atr": 2.00,
                "min_follow_body_ratio": 0.32,
                "min_follow_close_strength": 0.60,
                "min_follow_progress_atr": 0.06,
                "max_follow_range_atr": 2.00,
                "follow_window_bars": 3,
                "min_reclaim_close_strength": 0.70,
                "min_reclaim_wick": 0.24,
                "min_reclaim_body": 0.62,
                "min_reclaim_entry_quality": 74 if normalized_timeframe == "5M" else 68 if normalized_timeframe == "15M" else 66,
                "min_origin_reclaim_quality": 70 if normalized_timeframe == "5M" else 70 if normalized_timeframe == "15M" else 68,
                "origin_reclaim_trend_only": normalized_timeframe == "5M",
                "min_origin_reclaim_close_strength": 0.88 if normalized_timeframe == "5M" else 0.0,
                "max_origin_entry_displacement_atr": 1.30 if normalized_timeframe == "5M" else 1.05 if normalized_timeframe == "15M" else 1.15,
                "active_follow_window_bars": 6 if normalized_timeframe == "5M" else 3,
                "active_continuation_trend_only": normalized_timeframe == "5M",
                "min_active_pullback_atr": 0.08,
                "max_active_pullback_atr": 1.25 if normalized_timeframe == "5M" else 1.05 if normalized_timeframe == "15M" else 1.15,
                "ideal_active_pullback_atr": 0.42,
                "min_active_body_ratio": 0.32 if normalized_timeframe == "5M" else 0.34,
                "min_active_close_strength": 0.58 if normalized_timeframe == "5M" else 0.60,
                "min_active_entry_quality": 72 if normalized_timeframe == "5M" else 66 if normalized_timeframe == "15M" else 64,
                "max_active_entry_displacement_atr": 1.05 if normalized_timeframe == "5M" else 0.85 if normalized_timeframe == "15M" else 0.95,
                "max_active_origin_line_displacement_atr": 1.55 if normalized_timeframe == "5M" else 1.45,
                "scalp_first_reaction_enabled": normalized_timeframe == "5M",
                "scalp_wick_rejection_enabled": normalized_timeframe == "5M",
                "min_scalp_rejection_range_atr": 1.70,
                "min_scalp_rejection_wick_ratio": 0.40,
                "min_scalp_rejection_location_score": 68,
                "min_scalp_rejection_wider_location_score": 60,
                "min_scalp_rejection_score": 66,
                "min_scalp_rejection_entry_score": 70,
                "min_scalp_rejection_origin_quality": 68,
                "scalp_reaction_window_bars": 6,
                "min_scalp_pullback_atr": 0.04,
                "max_scalp_pullback_atr": 1.45,
                "ideal_scalp_pullback_atr": 0.45,
                "min_scalp_reaction_body_ratio": 0.32,
                "min_scalp_reaction_close_strength": 0.58,
                "min_scalp_reaction_progress_atr": 0.02,
                "max_scalp_reaction_range_atr": 2.00,
                "max_scalp_reaction_risk_atr": 1.65,
                "max_scalp_reaction_displacement_atr": 1.55,
                "min_scalp_reaction_quality": 70 if normalized_timeframe == "5M" else 60,
                "min_scalp_compression_location_score": 70 if normalized_timeframe == "5M" else 0,
                "min_event_risk_atr": 0.20,
                "max_event_risk_atr": 1.50 if normalized_timeframe in {"5M", "15M"} else 1.65,
                "max_entry_displacement_atr": 1.15 if normalized_timeframe in {"5M", "15M"} else 1.30,
                "max_live_chase_atr": 0.35,
                "max_clean_expansion": 3.40,
                "strong_trend_efficiency": 0.42,
                "strong_trend_spread_atr": 0.30,
                "strong_trend_slope_atr": 0.035,
                "counter_trend_min_close_strength": 0.76,
                "counter_trend_min_range_atr": 1.20,
                "min_spike_retest_delay_bars": 3,
                "max_retest_touches": 3,
                "max_compression_atr": 0.82,
                "min_compression_break_atr": 1.02,
                "entry_window_bars": window,
                "entry_cooldown_bars": cooldown,
                "entry_dedupe_distance_atr": 0.35,
                "max_daily_entries": 5 if normalized_timeframe == "5M" else 3,
                "context_zone_limit": 24 if normalized_timeframe == "5M" else 14,
                "lead_diamond_score": 70,
                "lead_zone_max_age_bars": 24 if normalized_timeframe == "5M" else 12,
                "max_entry_age_bars": 2,
                "timeframe_seconds": {"5M": 300, "15M": 900, "1H": 3600, "4H": 14400}.get(normalized_timeframe, 900),
            }
        profile = {
            "name": f"STANDARD_ADAPTIVE_DISCOVERY_V7_{normalized_timeframe}",
            "asset_model": "CROSS_ASSET",
            "min_visible_diamond_score": DiamondZoneEngine.MIN_VISIBLE_DIAMOND_SCORE,
            "min_body_ratio": 0.40,
            "min_range_ratio": 0.88,
            "min_close_strength": 0.58,
            "min_score": 56,
            "entry_min_body_ratio": 0.48,
            "entry_min_range_ratio": 1.05,
            "entry_min_close_strength": 0.65,
            "entry_min_score": 64,
            "expansion_override": 1.20,
            "atr_band": 0.10,
            "range_band": 0.06,
            "max_context_distance_atr": 2.50,
            "location_window_bars": 28,
            "min_entry_location_score": 38,
            "min_macro_location_score": 38,
            "min_execution_location_score": 55,
            "min_macro_execution_location_score": 55,
            "min_origin_quality_for_entry": 70,
            "min_entry_quality": 68,
            "min_retest_close_strength": 0.54,
            "min_rejection_wick": 0.12,
            "min_rejection_body": 0.46,
            "min_retest_delay_bars": 1,
            "max_retest_range_atr": 2.00,
            "min_follow_body_ratio": 0.30,
            "min_follow_close_strength": 0.58,
            "min_follow_progress_atr": 0.05,
            "max_follow_range_atr": 2.15,
            "follow_window_bars": 3,
            "min_reclaim_close_strength": 0.68,
            "min_reclaim_wick": 0.22,
            "min_reclaim_body": 0.58,
            "min_reclaim_entry_quality": 66,
            "min_origin_reclaim_quality": 66,
            "origin_reclaim_trend_only": False,
            "min_origin_reclaim_close_strength": 0.0,
            "max_origin_entry_displacement_atr": 1.15,
            "active_follow_window_bars": 3,
            "active_continuation_trend_only": False,
            "min_active_pullback_atr": 0.06,
            "max_active_pullback_atr": 1.20,
            "ideal_active_pullback_atr": 0.45,
            "min_active_body_ratio": 0.32,
            "min_active_close_strength": 0.58,
            "min_active_entry_quality": 64,
            "max_active_entry_displacement_atr": 0.95,
            "max_active_origin_line_displacement_atr": 1.55,
            "scalp_first_reaction_enabled": False,
            "scalp_wick_rejection_enabled": normalized_timeframe == "5M",
            "min_scalp_rejection_range_atr": 1.75,
            "min_scalp_rejection_wick_ratio": 0.42,
            "min_scalp_rejection_location_score": 68,
            "min_scalp_rejection_wider_location_score": 60,
            "min_scalp_rejection_score": 68,
            "min_scalp_rejection_entry_score": 72,
            "min_scalp_rejection_origin_quality": 70,
            "scalp_reaction_window_bars": 0,
            "min_scalp_pullback_atr": 0.04,
            "max_scalp_pullback_atr": 1.45,
            "ideal_scalp_pullback_atr": 0.45,
            "min_scalp_reaction_body_ratio": 0.32,
            "min_scalp_reaction_close_strength": 0.58,
            "min_scalp_reaction_progress_atr": 0.02,
            "max_scalp_reaction_range_atr": 2.00,
            "max_scalp_reaction_risk_atr": 1.65,
            "max_scalp_reaction_displacement_atr": 1.55,
            "min_scalp_reaction_quality": 60,
            "min_scalp_compression_location_score": 0,
            "min_event_risk_atr": 0.20,
            "max_event_risk_atr": 1.60,
            "max_entry_displacement_atr": 1.25,
            "max_live_chase_atr": 0.45,
            "max_clean_expansion": 3.75,
            "strong_trend_efficiency": 0.42,
            "strong_trend_spread_atr": 0.30,
            "strong_trend_slope_atr": 0.035,
            "counter_trend_min_close_strength": 0.76,
            "counter_trend_min_range_atr": 1.20,
            "min_spike_retest_delay_bars": 3,
            "max_retest_touches": 3,
            "max_compression_atr": 0.85,
            "min_compression_break_atr": 1.00,
            "entry_window_bars": 20,
            "entry_cooldown_bars": 6,
            "entry_dedupe_distance_atr": 0.35,
            "max_daily_entries": 3,
            "context_zone_limit": 14,
            "lead_diamond_score": 70,
            "lead_zone_max_age_bars": 18,
            "max_entry_age_bars": 2,
            "timeframe_seconds": {"5M": 300, "15M": 900, "1H": 3600, "4H": 14400}.get(normalized_timeframe, 900),
        }
        if normalized_symbol == "BTCUSD":
            profile.update({
                "name": f"BTC_ADAPTIVE_CONTINUATION_V7_{normalized_timeframe}",
                "asset_model": "BTC_CONTINUATION",
                "entry_min_body_ratio": 0.46 if normalized_timeframe == "5M" else profile["entry_min_body_ratio"],
                "entry_min_range_ratio": 1.00 if normalized_timeframe == "5M" else profile["entry_min_range_ratio"],
                "entry_min_close_strength": 0.63 if normalized_timeframe == "5M" else profile["entry_min_close_strength"],
                "entry_min_score": 62 if normalized_timeframe == "5M" else profile["entry_min_score"],
                "min_execution_location_score": 52 if normalized_timeframe == "5M" else profile["min_execution_location_score"],
                "min_macro_execution_location_score": 52 if normalized_timeframe == "5M" else profile["min_macro_execution_location_score"],
                "min_origin_quality_for_entry": 68 if normalized_timeframe == "5M" else profile["min_origin_quality_for_entry"],
                "scalp_first_reaction_enabled": normalized_timeframe == "5M",
                "min_scalp_reaction_quality": 68 if normalized_timeframe == "5M" else profile["min_scalp_reaction_quality"],
                "min_scalp_compression_location_score": 60 if normalized_timeframe == "5M" else 0,
                "entry_cooldown_bars": 7 if normalized_timeframe == "5M" else profile["entry_cooldown_bars"],
                "max_daily_entries": 4 if normalized_timeframe == "5M" else profile["max_daily_entries"],
                "context_zone_limit": 18 if normalized_timeframe == "5M" else profile["context_zone_limit"],
            })
        return profile

    def _rejection_metrics(self, rows: list[Dict[str, Any]], zone: Dict[str, Any]) -> Dict[str, Any]:
        recent = [row for row in rows if row["time"] > zone["time"]][-12:]
        touched = [row for row in recent if row["low"] <= zone["high"] and row["high"] >= zone["low"]]
        if not touched:
            return {
                "rejection_status": "UNTESTED",
                "rejection_score": 0,
                "rejection_wick_ratio": 0.0,
                "follow_through_bars": 0,
            }

        touch = touched[-1]
        touch_index = rows.index(touch)
        candle_range = max(touch["high"] - touch["low"], 1e-9)
        upper_wick = touch["high"] - max(touch["open"], touch["close"])
        lower_wick = min(touch["open"], touch["close"]) - touch["low"]
        role = zone.get("role")
        if role == "SUPPORT":
            wick_ratio = lower_wick / candle_range
            close_strength = max(0.0, min(1.0, (touch["close"] - touch["low"]) / candle_range))
            follow = [item for item in rows[touch_index + 1:] if item["close"] > zone["high"]]
        elif role == "RESISTANCE":
            wick_ratio = upper_wick / candle_range
            close_strength = max(0.0, min(1.0, (touch["high"] - touch["close"]) / candle_range))
            follow = [item for item in rows[touch_index + 1:] if item["close"] < zone["low"]]
        else:
            wick_ratio = max(upper_wick, lower_wick) / candle_range
            close_strength = 0.35
            follow = []
        follow_through = min(3, len(follow))
        score = round(min(100, wick_ratio * 45 + close_strength * 35 + (follow_through / 3) * 20))
        status = "STRONG" if score >= 75 else "MODERATE" if score >= 55 else "WEAK" if score >= 35 else "NO_REJECTION"
        return {
            "rejection_status": status,
            "rejection_score": score,
            "rejection_wick_ratio": round(wick_ratio, 3),
            "follow_through_bars": follow_through,
        }

    @staticmethod
    def _zone_strength(zone: Dict[str, Any]) -> int:
        lifecycle_bonus = {"FRESH": 12, "TESTED": 8, "WEAKENED": 2, "FLIPPED": -12}.get(zone.get("lifecycle"), 0)
        holding_bonus = 6 if zone.get("direction_holding") else -4
        score = float(zone.get("effective_score") or 0) * 0.68 + float(zone.get("rejection_score") or 0) * 0.22
        return round(max(0, min(100, score + lifecycle_bonus + holding_bonus)))

    @staticmethod
    def _execution_quality(zone: Dict[str, Any]) -> str:
        lifecycle = zone.get("lifecycle")
        strength = float(zone.get("zone_strength_score") or 0)
        distance = float(zone.get("distance_atr") or 999)
        rejection = zone.get("rejection_status")
        if lifecycle == "FLIPPED":
            return "INVALID"
        if lifecycle == "WEAKENED" or distance > 2.75 or strength < 64:
            return "CONTEXT_ONLY"
        if lifecycle == "FRESH" and rejection == "UNTESTED":
            return "WAIT_RETEST"
        if strength >= 80 and distance <= 1.50 and rejection in {"STRONG", "MODERATE"}:
            return "READY"
        return "WATCH"

    @staticmethod
    def _price_side(price: float, zone: Dict[str, Any]) -> str:
        if price > zone["high"]:
            return "ABOVE"
        if price < zone["low"]:
            return "BELOW"
        return "INSIDE"

    @staticmethod
    def _expected_direction(session: Dict[str, Any], analysis: Dict[str, Any]) -> str:
        bias = str(analysis.get("bias") or analysis.get("htf_bias", {}).get("bias") or "").upper()
        if bias in {"BULLISH", "BEARISH"}:
            return bias
        stance = str(session.get("stance") or "").upper()
        return stance if stance in {"BULLISH", "BEARISH"} else "MIXED"

    @staticmethod
    def _next_trigger(zone: Dict[str, Any], candle_color: str) -> str:
        if zone.get("execution_quality") == "INVALID":
            return "The selected Diamond Zone is invalidated; wait for a new qualified impulse zone."
        if float(zone.get("distance_atr") or 0) > 2.25:
            return "Price is too far from the Diamond Zone; wait for a controlled retest instead of chasing."
        if zone.get("execution_quality") == "WAIT_RETEST":
            return "Wait for the first completed-candle retest and rejection of the fresh Diamond Zone."
        if zone.get("rejection_status") in {"WEAK", "NO_REJECTION"}:
            return "Wait for a stronger wick rejection and closed-candle follow-through at the Diamond Zone."
        if zone["price_side"] == "INSIDE":
            return "Wait for a completed candle to close outside the Diamond Zone."
        if zone["price_side"] == "ABOVE" and candle_color != "BULLISH":
            return "Wait for a bullish completed candle to hold above the Diamond Line."
        if zone["price_side"] == "BELOW" and candle_color != "BEARISH":
            return "Wait for a bearish completed candle to hold below the Diamond Line."
        return f"Monitor the next completed candle for a {zone['role'].lower()} retest of the Diamond Zone."

    @staticmethod
    def _public_zone(zone: Dict[str, Any]) -> Dict[str, Any]:
        rounded = dict(zone)
        rounded.pop("bar_index", None)
        for key in ["line", "low", "high", "atr_14", "impulse_open", "impulse_close", "impulse_high", "impulse_low"]:
            rounded[key] = round(float(rounded[key]), 5)
        for key in [
            "body_ratio", "range_ratio", "close_strength", "distance_atr", "rejection_wick_ratio",
            "dealing_range_position", "wider_dealing_range_position",
        ]:
            rounded[key] = round(float(rounded[key]), 3)
        return rounded

    @staticmethod
    def _closed_candle_proof(timestamp: Any, profile: Dict[str, Any]) -> Dict[str, Any]:
        source_bar_time = int(timestamp or 0)
        timeframe_seconds = int(profile.get("timeframe_seconds") or 0)
        return {
            "status": "VERIFIED",
            "source_bar_time": source_bar_time,
            "locked_after": source_bar_time + timeframe_seconds if source_bar_time and timeframe_seconds else source_bar_time,
            "completed_candle_only": True,
            "non_repainting": True,
            "policy": "CLOSED_CANDLE_LOCKED",
        }

    @staticmethod
    def _public_entry_event(event: Dict[str, Any]) -> Dict[str, Any]:
        rounded = dict(event)
        for key in ["line", "marker_price", "execution_entry", "stop_reference", "zone_low", "zone_high", "atr_14"]:
            rounded[key] = round(float(rounded[key]), 5)
        for key in [
            "rejection_wick_ratio", "rejection_close_strength", "retest_range_atr",
            "follow_body_ratio", "follow_range_atr", "follow_through_strength",
            "follow_progress_atr", "risk_atr", "entry_displacement_atr", "origin_line_displacement_atr",
            "pullback_atr",
        ]:
            if key in rounded:
                rounded[key] = round(float(rounded[key]), 3)
        return rounded

    def _atr_at(self, rows: list[Dict[str, Any]], index: int, period: int) -> Optional[float]:
        start = max(1, index - period + 1)
        ranges = []
        for position in range(start, index + 1):
            row = rows[position]
            previous_close = rows[position - 1]["close"]
            ranges.append(max(
                row["high"] - row["low"],
                abs(row["high"] - previous_close),
                abs(row["low"] - previous_close),
            ))
        return sum(ranges) / len(ranges) if len(ranges) >= min(8, period) else None

    def _candles(self, candles: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
        normalized = []
        for item in candles or []:
            if item.get("is_complete") is False or item.get("is_partial") is True:
                continue
            timestamp = self._timestamp(item.get("time") or item.get("timestamp"))
            values = [self._number(item.get(key)) for key in ("open", "high", "low", "close")]
            if timestamp is None or any(value is None for value in values):
                continue
            open_value, high, low, close = values
            if min(open_value, high, low, close) <= 0 or high < max(open_value, low, close) or low > min(open_value, high, close):
                continue
            normalized.append({
                "time": timestamp,
                "open": open_value,
                "high": high,
                "low": low,
                "close": close,
            })
        unique = {row["time"]: row for row in normalized}
        return sorted(unique.values(), key=lambda row: row["time"])

    def _empty(self, status: str, timeframe: str, source: Optional[str], count: int, symbol: str = "XAUUSD") -> Dict[str, Any]:
        profile = self._adaptive_profile(self._profile(symbol, timeframe), [], symbol, timeframe)
        visible_score_floor = int(profile.get("min_visible_diamond_score", self.MIN_VISIBLE_DIAMOND_SCORE))
        return {
            "status": status,
            "strategy": self.strategy_name,
            "engine_version": self.engine_version,
            "profile": profile["name"],
            "adaptive_profile": self._adaptive_profile_summary(profile),
            "symbol": str(symbol or "XAUUSD").upper(),
            "scope": "CONFIRMED_STRATEGY_ZONES_AND_ENTRY_EVENTS",
            "timeframe": timeframe,
            "source": source,
            "closed_candles_used": count,
            "directional_bias": "WAIT",
            "primary_zone": None,
            "zones": [],
            "visible_zones": [],
            "live_zones": [],
            "lead_diamond_zone": None,
            "entry_events": [],
            "latest_entry_event": None,
            "entry_event_status": "WAITING_CONFIRMATION",
            "diamond_score": None,
            "diamond_grade": None,
            "grade_model": "DIAMOND_GRADE_V2_SCORE_GATED",
            "diamond_display_status": "NO_QUALIFIED_DIAMOND",
            "diamond_creation_policy": "STRATEGY_SETUP_FIRST_SCORE_GRADES_ONLY",
            "strategy_setup_confirmed": False,
            "score_creates_diamond": False,
            "lead_diamond_status": "SCANNING",
            "lead_diamond_score_floor": profile["lead_diamond_score"],
            "minimum_visible_diamond_score": visible_score_floor,
            "minimum_entry_diamond_score": self.MIN_ENTRY_DIAMOND_SCORE,
            "signal_integrity": {
                "version": "DIAMOND_RESULT_INTEGRITY_V5_SIGNAL_TIERS",
                "confirmed_entries": 0,
                "qualified_watch": 0,
                "market_context": 0,
                "invalidated_context": 0,
                "production_signal_rule": f"Structural context origins scoring {visible_score_floor} or higher are visible; strict execution gates remain separate.",
                "qualified_rule": "Grade C or better (60+) is required before entry confirmation.",
                "context_rule": "Rejected observations remain internal audit evidence and are hidden from the live chart.",
                "grade_rule": "Visible grades are A+, A, B, C, and D; D is watch-only.",
            },
            "signal_frequency": {
                "internal_observations": 0,
                "visible_diamonds": 0,
                "live_diamonds": 0,
                "context_zones": 0,
                "qualified_origins": 0,
                "confirmed_entries": 0,
                "visible_entry_limit": profile["max_daily_entries"],
                "context_zone_limit": profile["context_zone_limit"],
                "same_side_cooldown_bars": profile["entry_cooldown_bars"],
            },
            "precision_gate": {
                "status": "WAITING",
                "origin_model": None,
                "origin_quality_score": None,
                "minimum_entry_quality": profile["min_entry_quality"],
                "minimum_reclaim_entry_quality": profile["min_reclaim_entry_quality"],
                "minimum_origin_reclaim_quality": profile["min_origin_reclaim_quality"],
                "minimum_active_entry_quality": profile["min_active_entry_quality"],
                "minimum_origin_quality": profile["min_origin_quality_for_entry"],
                "entry_impulse_ready": False,
                "entry_impulse_failures": [status],
                "minimum_location_score": profile["min_execution_location_score"],
                "minimum_wider_location_score": profile["min_macro_execution_location_score"],
                "minimum_visible_diamond_score": visible_score_floor,
                "minimum_entry_diamond_score": self.MIN_ENTRY_DIAMOND_SCORE,
                "lead_diamond_score_floor": profile["lead_diamond_score"],
                "disqualifiers": [status],
            },
            "gate_funnel": DiamondZoneEngine._gate_funnel(
                Counter(),
                Counter({status: 1}),
                [],
            ),
            "uses_completed_candles_only": True,
            "proprietary_formula_claimed": False,
        }

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _timestamp(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
