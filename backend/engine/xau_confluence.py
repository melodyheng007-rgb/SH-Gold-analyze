from __future__ import annotations

from typing import Any, Dict, Optional


class XAUPrecisionConfluenceEngine:
    """Conservative XAU agreement matrix that can veto, but never create, setups."""

    def evaluate(
        self,
        analysis: Dict[str, Any],
        key_zones: Optional[Dict[str, Any]] = None,
        session_context: Optional[Dict[str, Any]] = None,
        news_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        symbol = str(analysis.get("symbol") or analysis.get("market_symbol") or "XAUUSD").upper()
        if symbol != "XAUUSD":
            return self._not_applicable(symbol)

        signal = analysis.get("signal") or {}
        plan = analysis.get("trade_plan") or {}
        htf = analysis.get("htf_bias") or {}
        liquidity = analysis.get("liquidity_map") or {}
        crt = analysis.get("crt_range") or {}
        poi = analysis.get("poi_engine") or {}
        confirmation = analysis.get("confirmation_engine") or {}
        trust = analysis.get("trust_gate") or {}
        zones = key_zones or analysis.get("key_zones") or {}
        session = session_context or analysis.get("session_framework") or {}
        news = news_context or analysis.get("news_intelligence") or {}
        diamond_mtf = zones.get("mtf_confluence") or {}
        primary_zone = zones.get("primary_zone") or {}
        k_trend = session.get("k_trend") or {}

        direction = self._direction(plan, signal, htf)
        expected_bias = "Bullish" if direction == "BUY" else "Bearish" if direction == "SELL" else None
        has_sweep = self._has_liquidity_sweep(liquidity.get("liquidity_sweep"))
        location = str(crt.get("premium_discount_status") or crt.get("current_price_location") or "Unknown")
        price_location_aligned = bool(
            (direction == "BUY" and location == "Discount")
            or (direction == "SELL" and location == "Premium")
        ) and not bool(crt.get("mid_range_warning"))
        session_aligned = bool(
            (direction == "BUY" and session.get("buy_context"))
            or (direction == "SELL" and session.get("sell_context"))
        )
        k_trend_aligned = bool(
            k_trend.get("status") == "READY"
            and k_trend.get("confirmation") == "CONFIRMED"
            and (
                (direction == "BUY" and k_trend.get("regime") == "BULLISH")
                or (direction == "SELL" and k_trend.get("regime") == "BEARISH")
            )
        )
        diamond_direction = str(diamond_mtf.get("direction") or "MIXED").upper()
        selected_bias = str(zones.get("directional_bias") or "WAIT").upper()
        entry_event = zones.get("latest_entry_event") or {}
        diamond_aligned = bool(
            direction in {"BUY", "SELL"}
            and zones.get("execution_trusted") is True
            and zones.get("status") == "READY"
            and primary_zone.get("lifecycle") in {"FRESH", "TESTED"}
            and zones.get("execution_quality") in {"READY", "WATCH"}
            and zones.get("rejection_status") in {"STRONG", "MODERATE"}
            and zones.get("entry_event_status") == "CONFIRMED_ENTRY"
            and entry_event.get("zone_id") == primary_zone.get("id")
            and str(entry_event.get("entry_side") or "").upper() == direction
            and float(entry_event.get("quality_score") or 0) >= 80
            and zones.get("quality_grade") in {"A+", "A", "B"}
            and (
                (direction == "BUY" and (diamond_direction == "BULLISH" or selected_bias == "BUY_CONTEXT"))
                or (direction == "SELL" and (diamond_direction == "BEARISH" or selected_bias == "SELL_CONTEXT"))
            )
        )
        diamond_conflict = bool(
            (direction == "BUY" and (diamond_direction == "BEARISH" or selected_bias == "SELL_CONTEXT"))
            or (direction == "SELL" and (diamond_direction == "BULLISH" or selected_bias == "BUY_CONTEXT"))
        )
        news_open = news.get("execution_gate") != "BLOCK_NEW_ENTRIES"
        trusted = trust.get("trusted") is True

        checks = [
            self._check("data_trust", "Matched XAU Feed", trusted, 0, trust.get("reason") or "Matched XAU/USD provider history is required.", True),
            self._check("htf", "1D / 4H Direction", htf.get("bias") == expected_bias and direction != "WAIT", 14, htf.get("reason") or "Wait for aligned 1D and 4H structure.", True),
            self._check("liquidity", "Liquidity Event", has_sweep, 14, liquidity.get("reason") or "Wait for a mapped liquidity sweep.", True),
            self._check("price_location", "Premium / Discount", price_location_aligned, 8, f"{location} location; avoid mid-range entries.", False),
            self._check("poi", "15M Institutional POI", bool(poi.get("best_poi")) and bool(poi.get("premium_discount_alignment")), 14, poi.get("reason") or "Wait for an aligned FVG, order block, or OTE zone.", True),
            self._check("confirmation", "5M Closed-Candle Trigger", confirmation.get("confirmation_ready") is True, 14, confirmation.get("reason") or "Wait for BOS/CHOCH plus displacement or rejection.", True),
            self._check("session", "XAU Session Context", session_aligned and not bool(session.get("range_extension")), 8, self._session_reason(session), False),
            self._check("k_trend", "SH K-Range Trend", k_trend_aligned, 12, self._k_trend_reason(k_trend), True),
            self._check("diamond", "Diamond Zone V5", diamond_aligned and not diamond_conflict, 12, self._diamond_reason(zones, diamond_mtf), True),
            self._check("news", "Macro News Window", news_open, 4, news.get("summary") or "Scheduled USD macro risk must be clear.", True),
        ]
        validation_checks = [item for item in checks if item["weight"] > 0]
        score = sum(item["weight"] for item in validation_checks if item["pass"])
        passed = sum(1 for item in validation_checks if item["pass"])
        required_failed = [item for item in checks if item["required"] and not item["pass"]]
        blockers = [item["reason"] for item in required_failed]

        if not trusted:
            state = "RESEARCH_ONLY"
            execution_gate = "BLOCK"
        elif not news_open:
            state = "NEWS_LOCK"
            execution_gate = "BLOCK"
        elif direction == "WAIT":
            state = "WAIT_DIRECTION"
            execution_gate = "BLOCK"
        elif diamond_conflict:
            state = "CONFLUENCE_CONFLICT"
            execution_gate = "BLOCK"
        elif not required_failed and score >= 80:
            state = "PRECISION_READY"
            execution_gate = "OPEN"
        elif score >= 60:
            state = "BUILDING_CONFLUENCE"
            execution_gate = "BLOCK"
        else:
            state = "WAITING_EVIDENCE"
            execution_gate = "BLOCK"

        grade = "A+" if score >= 90 else "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D"
        next_trigger = blockers[0] if blockers else "All XAU precision checks passed; preserve the original engine risk model."
        return {
            "status": "READY",
            "engine": "XAU_PRECISION_CONFLUENCE_V1",
            "profile": "XAUUSD_PRECISION",
            "scope": "VALIDATION_AND_VETO_ONLY",
            "symbol": symbol,
            "direction": direction,
            "state": state,
            "execution_gate": execution_gate,
            "validation_score": score,
            "quality_grade": grade,
            "agreement": {"passed": passed, "total": len(validation_checks)},
            "checks": checks,
            "blockers": blockers,
            "next_trigger": next_trigger,
            "diamond_conflict": diamond_conflict,
            "trade_direction_created": False,
            "uses_existing_engine_evidence_only": True,
        }

    def apply_to_analysis(self, analysis: Dict[str, Any], confluence: Dict[str, Any]) -> None:
        analysis["xau_confluence"] = confluence
        if confluence.get("status") != "READY":
            return
        signal = analysis.setdefault("signal", {})
        plan = analysis.get("trade_plan") or {}
        signal["xau_precision_state"] = confluence.get("state")
        signal["xau_precision_score"] = confluence.get("validation_score")
        signal["xau_precision_grade"] = confluence.get("quality_grade")
        signal["xau_precision_gate"] = confluence.get("execution_gate")
        if plan:
            plan["xau_precision_state"] = confluence.get("state")
            plan["xau_precision_score"] = confluence.get("validation_score")
            plan["xau_precision_grade"] = confluence.get("quality_grade")
            plan["xau_precision_gate"] = confluence.get("execution_gate")

        explanation = analysis.setdefault("analysis_explanation", {})
        explanation["xau_precision"] = confluence.get("next_trigger")
        if confluence.get("execution_gate") == "OPEN":
            return

        signal["execution_allowed"] = False
        if str(plan.get("status") or "").upper() != "ACTIONABLE":
            return
        direction = str(plan.get("direction") or confluence.get("direction") or "WAIT").upper()
        plan["status"] = "CANDIDATE"
        plan["label"] = f"Candidate {direction.title()} Setup - XAU Precision Validation Required"
        missing = plan.setdefault("missing_conditions", [])
        for blocker in confluence.get("blockers") or []:
            if blocker not in missing:
                missing.append(blocker)
        analysis["final_decision"] = plan["label"]
        explanation["next_trigger"] = confluence.get("next_trigger")

    @staticmethod
    def _direction(plan: Dict[str, Any], signal: Dict[str, Any], htf: Dict[str, Any]) -> str:
        direction = str(plan.get("direction") or signal.get("direction") or "").upper()
        if direction in {"BUY", "SELL"}:
            return direction
        bias = str(htf.get("bias") or "").upper()
        return "BUY" if bias == "BULLISH" else "SELL" if bias == "BEARISH" else "WAIT"

    @staticmethod
    def _has_liquidity_sweep(value: Any) -> bool:
        if value is True:
            return True
        normalized = str(value or "").strip().lower().replace(" ", "_")
        return bool(normalized and normalized not in {"false", "none", "no_sweep", "no_liquidity_sweep", "waiting"})

    @staticmethod
    def _check(key: str, label: str, passed: bool, weight: int, reason: str, required: bool) -> Dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "pass": bool(passed),
            "weight": weight,
            "required": required,
            "reason": reason,
        }

    @staticmethod
    def _session_reason(session: Dict[str, Any]) -> str:
        if session.get("range_extension"):
            return "XAU is at an outer daily-range extension; wait for a reset or fresh confirmation."
        return f"Session stance is {str(session.get('stance') or 'waiting').lower()} at {str(session.get('position') or 'unknown').replace('_', ' ').lower()}."

    @staticmethod
    def _diamond_reason(zones: Dict[str, Any], mtf: Dict[str, Any]) -> str:
        primary = zones.get("primary_zone") or {}
        if zones.get("execution_trusted") is not True:
            return "Diamond Zone is research-only until XAU history matches the selected market feed."
        if zones.get("execution_quality") not in {"READY", "WATCH"}:
            return f"Diamond Zone execution quality is {str(zones.get('execution_quality') or 'waiting').replace('_', ' ').lower()}."
        return (
            f"Diamond {mtf.get('state') or 'WAITING'}; Grade {zones.get('quality_grade') or '-'}, "
            f"{primary.get('lifecycle') or '-'}, rejection {zones.get('rejection_status') or '-'} ({zones.get('rejection_score') or 0})."
        )

    @staticmethod
    def _k_trend_reason(k_trend: Dict[str, Any]) -> str:
        if k_trend.get("status") != "READY":
            return "SH K-Range Trend is waiting for at least 35 completed intraday candles."
        target = k_trend.get("next_target_label") or "no untested K target"
        return (
            f"SH K-Range is {str(k_trend.get('regime') or 'range').lower()} "
            f"({k_trend.get('score') or 0}); closed-candle confirmation is "
            f"{str(k_trend.get('confirmation') or 'waiting').replace('_', ' ').lower()}, next {target}."
        )

    @staticmethod
    def _not_applicable(symbol: str) -> Dict[str, Any]:
        return {
            "status": "NOT_APPLICABLE",
            "engine": "XAU_PRECISION_CONFLUENCE_V1",
            "profile": "XAUUSD_PRECISION",
            "scope": "VALIDATION_AND_VETO_ONLY",
            "symbol": symbol,
            "state": "NOT_APPLICABLE",
            "execution_gate": "NOT_APPLICABLE",
            "validation_score": 0,
            "agreement": {"passed": 0, "total": 0},
            "checks": [],
            "blockers": [],
            "trade_direction_created": False,
        }
