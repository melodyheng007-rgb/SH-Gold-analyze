from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


class DiamondAutoEntryEngine:
    """Track a confirmed Diamond entry only when every execution gate passes."""

    MIN_RISK_REWARD = 1.6

    def apply(
        self,
        analysis: Dict[str, Any],
        key_zones: Optional[Dict[str, Any]] = None,
        session_context: Optional[Dict[str, Any]] = None,
        news_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        zones = key_zones or analysis.get("key_zones") or {}
        session = session_context or analysis.get("session_framework") or {}
        news = news_context or analysis.get("news_intelligence") or {}
        regime = analysis.get("market_regime") or {}
        smr = analysis.get("smr_model") or zones.get("smr_model") or {}
        smt = analysis.get("smt_model") or zones.get("smt_model") or {}
        dual_core = analysis.get("diamond_timeframe_model") or zones.get("diamond_timeframe_model") or {}
        plan = analysis.get("trade_plan") or {}
        signal = analysis.setdefault("signal", {})
        trust = analysis.get("trust_gate") or {}
        primary = zones.get("primary_zone") or {}
        entry_event = zones.get("latest_entry_event") or {}
        mtf = zones.get("mtf_confluence") or {}
        trading_style = str(zones.get("trading_style") or mtf.get("trading_style") or "SCALPING").upper()
        selected_timeframe = str(zones.get("timeframe") or "").upper()
        required_timeframes = [str(value).upper() for value in (mtf.get("required_timeframes") or zones.get("required_timeframes") or [])]
        confirmation = analysis.get("confirmation_engine") or {}
        liquidity = analysis.get("liquidity_map") or {}
        htf = analysis.get("htf_bias") or {}
        k_trend = session.get("k_trend") or {}
        precision = zones.get("precision_gate") or {}
        symbol = str(analysis.get("symbol") or analysis.get("market_symbol") or "UNKNOWN").upper()
        confirmation_pathway = str(entry_event.get("entry_pathway") or "").upper()
        required_entry_quality = float(
            (
                precision.get("minimum_origin_reclaim_quality")
                if confirmation_pathway == "ORIGIN_RECLAIM_CLOSE"
                else precision.get("minimum_active_entry_quality")
                if confirmation_pathway == "SHALLOW_PULLBACK_CONTINUATION"
                else precision.get("minimum_reclaim_entry_quality")
                if confirmation_pathway == "RECLAIM_CLOSE"
                else precision.get("minimum_entry_quality")
            ) or (72 if symbol == "XAUUSD" else 68)
        )
        required_location_score = float(precision.get("minimum_location_score") or (65 if symbol == "XAUUSD" else 55))
        max_live_chase_atr = 0.35 if symbol == "XAUUSD" else 0.45
        minimum_risk_reward = 1.8 if symbol == "XAUUSD" else self.MIN_RISK_REWARD
        regime_gate = str(regime.get("execution_gate") or "OBSERVE").upper()
        smr_gate = str(smr.get("execution_gate") or "WATCH").upper()
        smr_reason = str(smr.get("next_trigger") or "Wait for the SMR timing guard to clear.")
        dual_core_gate = str(dual_core.get("execution_gate") or "WATCH").upper()
        dual_core_reason = str(dual_core.get("next_trigger") or "Wait for 5M / 1H core alignment.")
        smt_direction = str(smt.get("direction") or "WAIT").upper()
        smt_confidence = int(smt.get("confidence") or 0)
        if smr_gate == "WAIT_SESSION":
            smr_reason = f"SMR session: {smr_reason}"
        elif smr_gate == "BLOCK_CONFLICT":
            smr_reason = f"SMR conflict: {smr_reason}"

        direction = str(plan.get("direction") or "WAIT").upper()
        smt_conflict = bool(
            smt.get("status") == "READY"
            and str(smt.get("execution_gate") or "NEUTRAL").upper() == "DIVERGENCE_READY"
            and smt_confidence >= 66
            and smt_direction in {"BUY", "SELL"}
            and direction in {"BUY", "SELL"}
            and smt_direction != direction
        )
        zone_side = str(primary.get("entry_side") or "WAIT").upper()
        expected_htf = "BULLISH" if direction == "BUY" else "BEARISH" if direction == "SELL" else "WAIT"
        htf_bias = str(htf.get("bias") or analysis.get("bias") or "WAIT").upper()
        zone_bias = str(zones.get("directional_bias") or "WAIT").upper()
        expected_zone_bias = "BUY_CONTEXT" if direction == "BUY" else "SELL_CONTEXT" if direction == "SELL" else "WAIT"
        expected_mtf = "BULLISH" if direction == "BUY" else "BEARISH" if direction == "SELL" else "MIXED"
        session_aligned = bool(
            (direction == "BUY" and session.get("buy_context"))
            or (direction == "SELL" and session.get("sell_context"))
        )
        k_trend_aligned = bool(
            k_trend.get("status") == "READY"
            and k_trend.get("confirmation") == "CONFIRMED"
            and str(k_trend.get("regime") or "").upper() == expected_htf
        )
        confirmation_ready = confirmation.get("confirmation_ready") is True
        entry = self._number(entry_event.get("execution_entry"))
        current_price = self._number(analysis.get("current_price") or zones.get("current_price"))
        stop = self._stop_price(primary, direction, entry_event)
        targets = self._mapped_targets(direction, entry, stop, liquidity, session, minimum_risk_reward)
        atr = self._number(entry_event.get("atr_14") or primary.get("atr_14"))
        risk_atr = abs(entry - stop) / atr if entry is not None and stop is not None and atr and atr > 0 else None
        valid_entry_location = bool(
            entry is not None
            and current_price is not None
            and atr is not None
            and atr > 0
            and abs(current_price - entry) / atr <= max_live_chase_atr
        )

        checks = [
            self._check("data_trust", "Matched provider data", trust.get("trusted") is True, trust.get("reason") or "Matched provider history is required."),
            self._check("base_setup", "Validated institutional setup", str(plan.get("status") or "").upper() == "ACTIONABLE" and direction in {"BUY", "SELL"}, plan.get("action") or "Wait for the institutional engine to produce an actionable setup."),
            self._check("diamond_zone", "Qualified Diamond Zone", zones.get("status") == "READY" and zones.get("execution_trusted") is True and bool(primary), zones.get("next_trigger") or "Wait for a trusted Diamond Zone."),
            self._check("diamond_direction", "Diamond direction agreement", direction == zone_side and zone_bias == expected_zone_bias, f"Diamond context must agree with the {direction.lower()} setup."),
            self._check(
                "diamond_quality",
                "Diamond rejection quality",
                zones.get("execution_quality") == "READY"
                and (
                    zones.get("rejection_status") in {"STRONG", "MODERATE"}
                    or confirmation_pathway in {"ORIGIN_RECLAIM_CLOSE", "SHALLOW_PULLBACK_CONTINUATION"}
                )
                and primary.get("lifecycle") in {"FRESH", "TESTED"},
                zones.get("next_trigger") or "Wait for a completed-candle Diamond rejection.",
            ),
            self._check(
                "diamond_entry_event",
                "Confirmed Diamond entry",
                zones.get("entry_event_status") == "CONFIRMED_ENTRY"
                and entry_event.get("zone_id") == primary.get("id")
                and str(entry_event.get("entry_side") or "").upper() == direction
                and entry_event.get("precision_qualified") is True
                and str(entry_event.get("precision_grade") or "") in {"C", "B", "A", "A+"}
                and float(entry_event.get("quality_score") or 0) >= required_entry_quality
                and entry_event.get("confirmation_model") in {
                    "ACTIVE_ORIGIN_SWEEP_RECLAIM_CLOSE",
                    "ACTIVE_SHALLOW_PULLBACK_CONTINUATION",
                    "ACTIVE_RETEST_RECLAIM_CLOSE",
                    "ACTIVE_RETEST_MULTI_CANDLE_FOLLOW_THROUGH",
                    "PRECISION_ORIGIN_RETEST_REJECTION_FOLLOW_THROUGH",
                },
                f"Wait for a Grade C or better closed-candle reclaim/follow-through score of at least {required_entry_quality:.0f}.",
            ),
            self._check(
                "diamond_location",
                "No-chase location",
                float(primary.get("entry_location_score") or 0) >= required_location_score and valid_entry_location,
                f"The entry must stay within {max_live_chase_atr:.2f} ATR of confirmation with location score at least {required_location_score:.0f}.",
            ),
            self._check(
                "style_timeframe",
                f"{trading_style.title()} timeframe profile",
                selected_timeframe in required_timeframes and len(required_timeframes) == 2,
                f"{trading_style.title()} entries require one of: {' / '.join(required_timeframes) or 'configured profile timeframes'}.",
            ),
            self._check(
                "mtf",
                "Diamond profile confirmation",
                str(mtf.get("direction") or "MIXED").upper() == expected_mtf
                and mtf.get("status") == "READY"
                and int(mtf.get("ready_timeframes") or 0) == len(required_timeframes) == 2,
                f"The direction frame and {' / '.join(required_timeframes) or 'execution frame'} trigger must agree without an opposite conflict.",
            ),
            self._check("htf", "HTF direction", htf_bias == expected_htf, f"1D/4H direction must be {expected_htf.lower()}."),
            self._check("confirmation", "Closed-candle confirmation", confirmation_ready, confirmation.get("reason") or "Wait for 5M closed-candle confirmation."),
            self._check("session", "Session and K-Trend", session_aligned and not bool(session.get("range_extension")) and k_trend_aligned, "Session position and confirmed K-Trend must agree."),
            *([
                self._check(
                    "smr_timing",
                    "SMR timing and conflict guard",
                    smr_gate not in {"WAIT_SESSION", "BLOCK_CONFLICT"},
                    smr_reason,
                )
            ] if smr else []),
            *([
                self._check(
                    "smt_confirmation",
                    "SMT companion conflict guard",
                    not smt_conflict,
                    smt.get("reason") or "Wait until the synchronized companion market no longer conflicts.",
                )
            ] if smt else []),
            *([
                self._check(
                    "dual_core",
                    "5M / 1H Dual-Core validation",
                    dual_core_gate not in {"BLOCK_CONFLICT", "WAIT_VOLATILITY", "WAIT_SESSION"},
                    dual_core_reason,
                )
            ] if dual_core else []),
            self._check(
                "regime_location",
                "Regime and anti-chase location",
                regime_gate in {"OPEN", "OPEN_RANGE_EDGE"},
                regime.get("reason") or "Wait for a stable completed-candle regime and valid directional location.",
            ),
            self._check("news", "News risk clear", news.get("execution_gate") != "BLOCK_NEW_ENTRIES", news.get("summary") or "Wait until the high-impact news lock clears."),
            self._check(
                "risk",
                "Provider-mapped risk geometry",
                entry is not None
                and stop is not None
                and bool(targets)
                and risk_atr is not None
                and 0.30 <= risk_atr <= 1.45,
                f"Risk must be 0.30-1.45 ATR with a mapped target of at least {minimum_risk_reward:.1f}R; synthetic targets are disabled.",
            ),
        ]
        blockers = [item["reason"] for item in checks if not item["pass"]]
        passed = sum(1 for item in checks if item["pass"])
        status = self._status(checks)
        result = {
            "status": status,
            "mode": "AUTO_CLOSED_CANDLE",
            "symbol": symbol,
            "direction": direction if direction in {"BUY", "SELL"} else "WAIT",
            "trading_style": trading_style,
            "execution_timeframe": zones.get("execution_timeframe") or mtf.get("execution_timeframe"),
            "confirmation_timeframe": zones.get("confirmation_timeframe") or mtf.get("confirmation_timeframe"),
            "zone_id": primary.get("id"),
            "entry_event_id": entry_event.get("id"),
            "entry_confirmed_at": entry_event.get("confirmation_time"),
            "entry_price": entry,
            "entry_model": entry_event.get("entry_pathway") or "ACTIVE_CLOSED_CANDLE_CONFIRMATION",
            "precision_grade": entry_event.get("precision_grade"),
            "precision_score": entry_event.get("quality_score"),
            "risk_atr": round(risk_atr, 3) if risk_atr is not None else None,
            "minimum_risk_reward": minimum_risk_reward,
            "regime_gate": regime_gate,
            "location_guard": regime.get("location_guard") or {},
            "smr_state": smr.get("pattern_state"),
            "smr_score": smr.get("score"),
            "smr_session": (smr.get("session") or {}).get("name"),
            "smr_execution_gate": smr_gate if smr else None,
            "smt_state": smt.get("state"),
            "smt_direction": smt_direction if smt else None,
            "smt_confidence": smt_confidence if smt else None,
            "smt_execution_gate": "BLOCK_CONFLICT" if smt_conflict else "NEUTRAL",
            "dual_core_state": dual_core.get("state"),
            "dual_core_score": dual_core.get("score"),
            "dual_core_grade": dual_core.get("grade"),
            "dual_core_focus_timeframe": dual_core.get("focus_timeframe"),
            "dual_core_execution_gate": dual_core_gate if dual_core else None,
            "stop_loss": stop,
            "take_profit_levels": targets,
            "checks": checks,
            "agreement": {"passed": passed, "total": len(checks)},
            "blockers": blockers,
            "next_trigger": blockers[0] if blockers else "Confirmed Diamond entry is armed for automatic tracking.",
            "uses_completed_candles_only": True,
            "broker_order_submitted": False,
            "execution_scope": "TRACKED_CONFIRMED_ENTRY_ONLY",
        }
        analysis["diamond_auto_entry"] = result
        signal["diamond_auto_entry_status"] = status
        signal["diamond_auto_entry_armed"] = status == "AUTO_ARMED"

        if status != "AUTO_ARMED":
            return result

        risk = abs(float(entry) - float(stop))
        reward = abs(float(targets[0]) - float(entry))
        risk_reward = round(reward / risk, 2)
        original_setup = plan.get("setup_type")
        plan.update({
            "status": "ACTIONABLE",
            "actionable": True,
            "label": f"Auto {direction.title()} Entry - Diamond Zone",
            "direction": direction,
            "order_type": "MARKET",
            "position_type": "CONFIRMED_ENTRY",
            "setup_type": "Diamond V7 Adaptive Entry",
            "base_setup_type": original_setup,
            "entry_zone": {
                "type": "SH Diamond Zone V6.6 Signal Radar",
                "id": primary.get("id"),
                "low": primary.get("low"),
                "high": primary.get("high"),
                "line": entry,
                "entry_event_id": entry_event.get("id"),
                "confirmed_at": entry_event.get("confirmation_time"),
            },
            "entry_price": round(float(entry), 5),
            "stop_loss": round(float(stop), 5),
            "take_profit_levels": targets,
            "risk_reward": risk_reward,
            "risk_model": {
                "status": "VALID",
                "rr": risk_reward,
                "entry": round(float(entry), 5),
                "risk": round(risk, 5),
                "reward": round(reward, 5),
                "warnings": [],
            },
            "missing_conditions": [],
            "trigger": "Automatic tracking at the completed Diamond reclaim or multi-candle follow-through close.",
            "zone_source": f"Trusted {primary.get('id')} with retest, rejection, active confirmation, and direction-frame agreement.",
            "stop_model": "Diamond zone invalidation plus 0.10 ATR buffer",
            "target_model": f"Nearest provider-mapped liquidity or K-range level satisfying at least {minimum_risk_reward:.1f}R",
            "action": "Automatically tracked confirmed entry. No broker order is submitted by this application.",
            "auto_entry_armed": True,
        })
        signal["execution_allowed"] = True
        signal["trade_plan_valid"] = True
        signal["status"] = "AUTO_ARMED"
        signal["final_action"] = plan["action"]
        analysis["final_decision"] = plan["label"]
        analysis.setdefault("analysis_explanation", {})["diamond_auto_entry"] = result["next_trigger"]
        return result

    @classmethod
    def _mapped_targets(
        cls,
        direction: str,
        entry: Optional[float],
        stop: Optional[float],
        liquidity: Dict[str, Any],
        session: Dict[str, Any],
        minimum_risk_reward: Optional[float] = None,
    ) -> list[float]:
        if entry is None or stop is None or direction not in {"BUY", "SELL"}:
            return []
        risk = abs(entry - stop)
        if risk <= 0:
            return []
        minimum_rr = float(minimum_risk_reward or cls.MIN_RISK_REWARD)
        levels = session.get("levels") or {}
        raw: list[Any] = []
        if direction == "BUY":
            raw.extend(liquidity.get("buy_side_liquidity") or [])
            raw.extend([liquidity.get("nearest_liquidity_above"), liquidity.get("previous_day_high"), liquidity.get("session_high")])
            raw.extend(value for key, value in levels.items() if "plus" in str(key))
            valid = [value for value in cls._numbers(raw) if value > entry and value - entry >= risk * minimum_rr]
        else:
            raw.extend(liquidity.get("sell_side_liquidity") or [])
            raw.extend([liquidity.get("nearest_liquidity_below"), liquidity.get("previous_day_low"), liquidity.get("session_low")])
            raw.extend(value for key, value in levels.items() if "minus" in str(key))
            valid = [value for value in cls._numbers(raw) if value < entry and entry - value >= risk * minimum_rr]
        return [round(value, 5) for value in sorted(set(valid), key=lambda value: abs(value - entry))[:3]]

    @staticmethod
    def _stop_price(primary: Dict[str, Any], direction: str, entry_event: Optional[Dict[str, Any]] = None) -> Optional[float]:
        event = entry_event or {}
        entry = DiamondAutoEntryEngine._number(event.get("execution_entry"))
        atr = DiamondAutoEntryEngine._number(event.get("atr_14") or primary.get("atr_14"))
        edge = DiamondAutoEntryEngine._number(
            event.get("stop_reference")
            or primary.get("low" if direction == "BUY" else "high")
        )
        if entry is None or atr is None or edge is None or atr <= 0:
            return None
        stop = edge - atr * 0.10 if direction == "BUY" else edge + atr * 0.10
        if (direction == "BUY" and stop >= entry) or (direction == "SELL" and stop <= entry):
            return None
        return round(stop, 5)

    @staticmethod
    def _status(checks: list[Dict[str, Any]]) -> str:
        failed = next((item["id"] for item in checks if not item["pass"]), None)
        if failed is None:
            return "AUTO_ARMED"
        if failed == "data_trust":
            return "BLOCKED_DATA_TRUST"
        if failed == "base_setup":
            return "WAITING_BASE_SETUP"
        if failed in {"diamond_zone", "diamond_direction", "diamond_quality", "diamond_entry_event", "diamond_location", "style_timeframe"}:
            return "WAITING_DIAMOND"
        if failed == "regime_location":
            return "WAITING_LOCATION"
        if failed == "smr_timing":
            return "WAITING_SESSION" if any(
                item.get("id") == "smr_timing" and "session" in str(item.get("reason") or "").lower()
                for item in checks
            ) else "WAITING_SMR"
        if failed == "smt_confirmation":
            return "WAITING_SMT"
        if failed == "dual_core":
            return "WAITING_DUAL_CORE"
        if failed == "news":
            return "NEWS_LOCKED"
        return "WAITING_CONFLUENCE"

    @staticmethod
    def _check(identifier: str, label: str, passed: bool, reason: str) -> Dict[str, Any]:
        return {"id": identifier, "label": label, "pass": bool(passed), "reason": str(reason)}

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _numbers(cls, values: Iterable[Any]) -> list[float]:
        return [number for value in values if (number := cls._number(value)) is not None]
