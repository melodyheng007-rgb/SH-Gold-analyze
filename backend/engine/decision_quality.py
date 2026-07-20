from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


class DecisionQualityEngine:
    """Score current decision evidence without creating or relaxing a signal."""

    VERSION = "DECISION_QUALITY_V3_RESULT_INTEGRITY"

    def evaluate(
        self,
        analysis: Dict[str, Any],
        champion_validation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        symbol = str(analysis.get("symbol") or analysis.get("market_symbol") or "XAUUSD").upper()
        reconciliation = analysis.get("feed_reconciliation") or {}
        execution = analysis.get("execution_reality") or {}
        zones = analysis.get("key_zones") or {}
        primary = zones.get("primary_zone") or {}
        event = zones.get("latest_entry_event") or {}
        mtf = zones.get("mtf_confluence") or {}
        htf = analysis.get("htf_bias") or {}
        liquidity = analysis.get("liquidity_map") or {}
        poi = analysis.get("poi_engine") or {}
        confirmation = analysis.get("confirmation_engine") or {}
        session = analysis.get("session_framework") or {}
        k_trend = session.get("k_trend") or {}
        precision = analysis.get("xau_confluence") or {}
        regime = analysis.get("market_regime") or {}
        location_guard = regime.get("location_guard") or {}
        asset_intelligence = analysis.get("asset_intelligence") or {}
        news = analysis.get("news_intelligence") or {}
        plan = analysis.get("trade_plan") or {}
        validation = champion_validation or {}
        validation_summary = validation.get("summary") or {}
        sample_confidence = validation.get("sample_confidence") or {}

        feed_checks = {item.get("id"): item for item in reconciliation.get("checks") or []}
        data_checks = [
            self._check("trusted_feed", "Feed reconciliation trusted", reconciliation.get("trusted") is True, 8, "A matched and reconciled provider feed is required."),
            self._check("source", "Expected provider source", self._feed_pass(feed_checks, "source"), 4, "Chart source must match the configured provider."),
            self._check("single_source", "Single-source chart", self._feed_pass(feed_checks, "single_source"), 3, "Mixed provider candles are not accepted."),
            self._check("ohlc", "Clean OHLC", self._feed_pass(feed_checks, "ohlc"), 3, "Invalid OHLC rows must be removed and investigated."),
            self._check("duplicates", "Unique timestamps", self._feed_pass(feed_checks, "duplicates"), 2, "Duplicate candle timestamps reduce confidence."),
            self._check("gaps", "No active gap", self._feed_pass(feed_checks, "gaps"), 2, "An active history gap blocks reliable comparison."),
            self._check("freshness", "Closed-candle freshness", self._feed_pass(feed_checks, "freshness"), 2, "The latest completed candle is stale."),
            self._check("close_drift", "Comparable-close agreement", self._feed_pass(feed_checks, "close_drift") and reconciliation.get("status") == "MATCHED_RECONCILED", 1, "A comparable provider close is still pending or outside tolerance."),
        ]

        resolved = int(validation_summary.get("resolved") or 0)
        expectancy = self._number(validation_summary.get("expectancy_r"))
        profit_factor = validation_summary.get("profit_factor")
        numeric_profit_factor = float("inf") if profit_factor == "INF" else self._number(profit_factor)
        drawdown = self._number(validation_summary.get("max_drawdown_r"))
        evidence_progress = min(1.0, resolved / 100.0)
        evidence_checks = [
            self._check("validation_run", "Matched-feed validation run", validation.get("status") in {"READY", "NO_CONFIRMED_EVENTS"}, 2, "Run matched-provider walk-forward validation."),
            self._check("resolved_sample", "100 resolved events", resolved >= 100, 5, "A minimum of 100 resolved events is required for evidence-ready status.", earned=5 * evidence_progress),
            self._check("expectancy", "Positive expectancy", expectancy is not None and expectancy >= 0.10, 3, "Validated expectancy must be at least 0.10R."),
            self._check("profit_factor", "Profit factor", numeric_profit_factor is not None and numeric_profit_factor >= 1.20, 2, "Validated profit factor must be at least 1.20."),
            self._check("drawdown", "Controlled drawdown", drawdown is not None and drawdown <= 12.0, 1, "Validated maximum drawdown must not exceed 12R."),
            self._check("sample_status", "Evidence-ready sample", sample_confidence.get("status") == "EVIDENCE_READY", 2, "The validation sample is still developing."),
        ]

        event_time = self._timestamp(event.get("confirmation_time") or event.get("available_at") or event.get("time"))
        latest_closed_time = self._timestamp(reconciliation.get("latest_closed_time"))
        current_event = bool(event_time is not None and latest_closed_time is not None and event_time == latest_closed_time)
        confirmed_event = zones.get("entry_event_status") == "CONFIRMED_ENTRY" and bool(event)
        precision_gate = zones.get("precision_gate") or {}
        qualified_origin = bool(
            primary.get("entry_eligible_origin") is True
            or precision_gate.get("status") == "QUALIFIED"
        )
        required_frames = mtf.get("required_timeframes") or zones.get("required_timeframes") or []
        asset_gate = str(asset_intelligence.get("execution_gate") or "LEGACY_OPEN").upper()
        asset_ready = not asset_intelligence or asset_gate == "OPEN"
        mtf_ready = bool(
            mtf.get("status") == "READY"
            and int(mtf.get("ready_timeframes") or 0) >= max(1, len(required_frames))
            and str(mtf.get("direction") or "MIXED").upper() != "MIXED"
            and asset_ready
        )
        event_quality = self._number(event.get("quality_score")) or 0.0
        minimum_quality = self._number(precision_gate.get("minimum_entry_quality")) or (86.0 if symbol == "XAUUSD" else 82.0)
        diamond_checks = [
            self._check("context_zone", "Current Diamond context", zones.get("status") == "READY" and bool(primary), 4, "Wait for a completed-candle Diamond context zone."),
            self._check("qualified_origin", "Entry-grade origin", qualified_origin, 4, "The current origin remains context-only."),
            self._check("execution_trust", "Trusted Diamond source", zones.get("execution_trusted") is True, 3, "Diamond execution requires a matched provider source."),
            self._check("mtf", "Profile timeframe agreement", mtf_ready, 4, "Both profile timeframes must be trusted and aligned."),
            self._check("current_confirmation", "Current closed-candle confirmation", confirmed_event and current_event, 7, "Historical Diamonds cannot be reused as current entries." if confirmed_event else "Wait for retest, rejection, and closed follow-through."),
            self._check("event_quality", "Precision event quality", current_event and event_quality >= minimum_quality, 3, f"Current event quality must be at least {minimum_quality:.0f}."),
        ]

        bias = str(htf.get("bias") or analysis.get("bias") or "WAIT").upper()
        has_sweep = self._has_sweep(liquidity.get("liquidity_sweep"))
        direction = str(plan.get("direction") or analysis.get("signal", {}).get("direction") or "WAIT").upper()
        k_trend_aligned = bool(
            k_trend.get("status") == "READY"
            and k_trend.get("confirmation") == "CONFIRMED"
            and (
                (direction == "BUY" and k_trend.get("regime") == "BULLISH")
                or (direction == "SELL" and k_trend.get("regime") == "BEARISH")
            )
        )
        precision_ready = symbol != "XAUUSD" or precision.get("execution_gate") == "OPEN"
        news_clear = news.get("execution_gate") != "BLOCK_NEW_ENTRIES"
        regime_gate = str(regime.get("execution_gate") or "OBSERVE").upper()
        regime_ready = regime_gate in {"OPEN", "OPEN_RANGE_EDGE"}
        confluence_checks = [
            self._check("htf", "Clear HTF direction", bias in {"BULLISH", "BEARISH"}, 3, "A clear higher-timeframe direction is required."),
            self._check("liquidity", "Mapped liquidity sweep", has_sweep, 3, "Wait for a clean mapped liquidity sweep."),
            self._check("poi", "Valid directional POI", bool(poi.get("best_poi")), 3, "No valid directional POI is active."),
            self._check("confirmation", "Institutional confirmation", confirmation.get("confirmation_ready") is True, 4, confirmation.get("reason") or "Closed-candle confirmation is waiting."),
            self._check("k_trend", "K-Trend direction agreement", k_trend_aligned, 2, "K-Trend is not confirmed in the intended direction."),
            self._check("asset_profile", "Asset-specific MTF profile", asset_ready, 2, asset_intelligence.get("reason") or "The Pro Analyze asset profile is not open."),
            self._check("regime", "Completed-candle regime agreement", regime_ready, 2, regime.get("reason") or "The market regime gate is not open."),
            self._check("precision", "XAU precision matrix", precision_ready, 1, "The XAU precision matrix is not open."),
            self._check("news", "News entry window clear", news_clear, 2, news.get("summary") or "A high-impact news lock is active."),
        ]

        targets = plan.get("take_profit_levels") or []
        entry = self._number(plan.get("entry_price") or execution.get("entry"))
        stop = self._number(plan.get("stop_loss") or execution.get("stop"))
        target = self._number(targets[0]) if targets else self._number(execution.get("target"))
        risk_reward = self._number(execution.get("risk_reward") or plan.get("risk_reward"))
        minimum_rr = 1.8 if symbol == "XAUUSD" else 1.6
        actionable = str(plan.get("status") or "").upper() == "ACTIONABLE" and direction in {"BUY", "SELL"}
        risk_checks = [
            self._check("actionable", "Actionable engine plan", actionable, 3, "The institutional plan is not actionable."),
            self._check("entry", "Mapped entry", entry is not None, 2, "No current entry is mapped."),
            self._check("stop", "Mapped invalidation stop", stop is not None, 2, "No provider-based stop is mapped."),
            self._check("target", "Mapped liquidity target", target is not None, 2, "No provider-based target is mapped."),
            self._check("risk_reward", "Minimum reward-to-risk", risk_reward is not None and risk_reward >= minimum_rr, 3, f"Reward-to-risk must be at least {minimum_rr:.1f}."),
            self._check("research", "Research-trackable setup", execution.get("research_trackable") is True, 2, "Execution Reality has not approved research tracking."),
            self._check("pricing", "Pricing reality disclosed", bool(execution.get("pricing_mode")), 1, "Execution pricing mode is unavailable."),
        ]

        components = [
            self._component("data", "Data Confidence", data_checks),
            self._component("evidence", "Strategy Evidence", evidence_checks),
            self._component("diamond", "Diamond Quality", diamond_checks),
            self._component("confluence", "Market Agreement", confluence_checks),
            self._component("risk", "Risk Geometry", risk_checks),
        ]
        raw_score = round(sum(component["score"] for component in components))
        feed_trusted = reconciliation.get("trusted") is True
        has_context = zones.get("status") == "READY" and bool(primary)
        research_trackable = execution.get("research_trackable") is True
        if not feed_trusted:
            status, ceiling = "DATA_BLOCKED", 24
        elif not news_clear:
            status, ceiling = "NEWS_LOCKED", 45
        elif regime_gate == "BLOCK_VOLATILITY":
            status, ceiling = "VOLATILITY_LOCKED", 45
        elif asset_intelligence and not asset_ready:
            status, ceiling = "ASSET_PROFILE_GUARD", 54
        elif not has_context:
            status, ceiling = "SCANNING", 39
        elif not qualified_origin:
            status, ceiling = "CONTEXT_ONLY", 49
        elif confirmed_event and not current_event:
            status, ceiling = "HISTORICAL_CONTEXT", 59
        elif not current_event:
            status, ceiling = "WAITING_CONFIRMATION", 64
        elif regime_gate == "BLOCK_DIRECTION_CONFLICT":
            status, ceiling = "REGIME_CONFLICT", 54
        elif regime_gate == "WAIT_OVEREXTENDED":
            status, ceiling = "LOCATION_GUARD", 54
        elif regime_gate == "WAIT_RANGE_EDGE":
            status, ceiling = "RANGE_GUARD", 59
        elif regime_gate in {"WAIT_TRANSITION", "OBSERVE"}:
            status, ceiling = "REGIME_TRANSITION", 59
        elif not actionable:
            status, ceiling = "WAITING_ENGINE_AGREEMENT", 69
        elif not research_trackable:
            status, ceiling = "RISK_REVIEW", 79
        else:
            status, ceiling = "TRACKABLE_SETUP", 100
        if status == "TRACKABLE_SETUP" and resolved < 20:
            status, ceiling = "TRACKABLE_LIMITED_EVIDENCE", min(ceiling, 84)
        score = min(raw_score, ceiling)
        blockers = self._rank_blockers(components)
        risk_ready = bool(
            actionable
            and entry is not None
            and stop is not None
            and target is not None
            and risk_reward is not None
            and risk_reward >= minimum_rr
            and research_trackable
        )
        readiness = self._execution_readiness(
            feed_trusted=feed_trusted,
            qualified_origin=qualified_origin,
            mtf_ready=mtf_ready,
            mtf_reason=(
                asset_intelligence.get("reason")
                if not asset_ready
                else "Both timeframes in the selected trade profile must align."
            ),
            regime_ready=regime_ready,
            regime_reason=regime.get("reason"),
            confirmed_current=confirmed_event and current_event and event_quality >= minimum_quality,
            confirmation_reason=confirmation.get("reason"),
            risk_ready=risk_ready,
            risk_reward=risk_reward,
            minimum_rr=minimum_rr,
        )
        result = {
            "status": status,
            "version": self.VERSION,
            "symbol": symbol,
            "score": score,
            "raw_score": raw_score,
            "score_ceiling": ceiling,
            "grade": self._grade(score),
            "data_confidence": self._normalized(components[0]["score"], components[0]["max_score"]),
            "evidence_confidence": self._normalized(components[1]["score"], components[1]["max_score"]),
            "setup_confidence": self._normalized(
                sum(component["score"] for component in components[2:]),
                sum(component["max_score"] for component in components[2:]),
            ),
            "components": components,
            "top_blockers": blockers[:5],
            "primary_blocker": readiness.get("current_gate"),
            "execution_readiness": readiness,
            "next_best_action": self._next_action(status),
            "current_event": current_event,
            "event_freshness": "CURRENT_CLOSED_CANDLE" if current_event else "HISTORICAL_CONTEXT" if confirmed_event else "NO_CONFIRMED_EVENT",
            "signal_integrity": {
                "version": "DIAMOND_RESULT_INTEGRITY_V1",
                "result_scope": (
                    "EVIDENCE_READY_CONFIRMED_ENTRY"
                    if current_event and sample_confidence.get("status") == "EVIDENCE_READY"
                    else "RESEARCH_CONFIRMED_ENTRY"
                    if current_event
                    else "HISTORICAL_CONFIRMED_CONTEXT"
                    if confirmed_event
                    else "NO_PRODUCTION_ENTRY"
                ),
                "confirmed_event_required": True,
                "context_is_entry": False,
                "qualified_watch_is_entry": False,
                "validation_status": validation.get("status") or "NOT_RUN",
                "resolved_evidence": resolved,
                "sample_status": sample_confidence.get("status") or "INSUFFICIENT_SAMPLE",
            },
            "decision_allowed": status in {"TRACKABLE_SETUP", "TRACKABLE_LIMITED_EVIDENCE"},
            "research_trackable": research_trackable,
            "broker_executable": execution.get("broker_executable") is True,
            "regime": regime.get("regime") or "UNKNOWN",
            "regime_gate": regime_gate,
            "asset_profile": asset_intelligence.get("profile"),
            "asset_profile_gate": asset_gate,
            "location_guard": location_guard,
            "uses_completed_candles_only": True,
            "changes_signal_logic": False,
            "broker_order_submitted": False,
        }
        return result

    @staticmethod
    def apply_to_analysis(analysis: Dict[str, Any], result: Dict[str, Any]) -> None:
        analysis["decision_quality"] = result
        signal = analysis.setdefault("signal", {})
        signal["decision_quality_score"] = result.get("score")
        signal["decision_quality_status"] = result.get("status")
        signal["decision_quality_allowed"] = result.get("decision_allowed") is True
        signal["market_regime_gate"] = result.get("regime_gate")

    @staticmethod
    def _feed_pass(checks: Dict[str, Dict[str, Any]], identifier: str) -> bool:
        return (checks.get(identifier) or {}).get("pass") is True

    @staticmethod
    def _has_sweep(value: Any) -> bool:
        if value is True:
            return True
        normalized = str(value or "").strip().lower().replace(" ", "_")
        return bool(normalized and normalized not in {"false", "none", "no_sweep", "no_liquidity_sweep", "waiting"})

    @staticmethod
    def _check(
        identifier: str,
        label: str,
        passed: bool,
        points: float,
        reason: str,
        earned: Optional[float] = None,
    ) -> Dict[str, Any]:
        awarded = points if passed else 0.0
        if earned is not None:
            awarded = max(0.0, min(float(points), float(earned)))
        return {
            "id": identifier,
            "label": label,
            "pass": bool(passed),
            "points": float(points),
            "earned": round(awarded, 2),
            "reason": reason,
        }

    @staticmethod
    def _component(identifier: str, label: str, checks: list[Dict[str, Any]]) -> Dict[str, Any]:
        maximum = sum(float(check["points"]) for check in checks)
        score = round(sum(float(check["earned"]) for check in checks), 2)
        return {
            "id": identifier,
            "label": label,
            "score": score,
            "max_score": maximum,
            "percent": DecisionQualityEngine._normalized(score, maximum),
            "checks": checks,
        }

    @staticmethod
    def _normalized(value: float, maximum: float) -> int:
        return round(max(0.0, min(100.0, float(value) / float(maximum) * 100))) if maximum else 0

    @staticmethod
    def _grade(score: int) -> str:
        if score >= 85:
            return "A"
        if score >= 70:
            return "B"
        if score >= 55:
            return "C"
        if score >= 40:
            return "D"
        return "E"

    @staticmethod
    def _next_action(status: str) -> str:
        actions = {
            "DATA_BLOCKED": "Restore a matched, fresh provider feed before evaluating a setup.",
            "NEWS_LOCKED": "Wait for the high-impact news lock and post-event volatility window to clear.",
            "VOLATILITY_LOCKED": "Wait for closed-candle volatility to normalize before evaluating a new entry.",
            "ASSET_PROFILE_GUARD": "Wait for the asset-specific MTF profile, volatility, and trigger direction to align.",
            "SCANNING": "Wait for a completed-candle Diamond context to form at a valid location.",
            "CONTEXT_ONLY": "Wait for an entry-grade origin; do not trade a context marker.",
            "HISTORICAL_CONTEXT": "The last Diamond is historical. Wait for a new current-candle confirmation.",
            "WAITING_CONFIRMATION": "Wait for controlled retest, rejection, and closed follow-through.",
            "REGIME_CONFLICT": "Reject the current direction and wait for a setup aligned with the completed-candle trend.",
            "LOCATION_GUARD": "Do not chase price. Wait for a controlled mean-reversion retest and a new closed Diamond confirmation.",
            "RANGE_GUARD": "Do not enter in the middle of the range; wait for the matching outer 25% edge.",
            "REGIME_TRANSITION": "Wait for trend, range, and volatility measurements to stabilize.",
            "WAITING_ENGINE_AGREEMENT": "Wait for the institutional plan and direction engines to agree.",
            "RISK_REVIEW": "Wait for provider-mapped entry, invalidation stop, target, and minimum reward-to-risk.",
            "TRACKABLE_LIMITED_EVIDENCE": "Track as research only while the resolved validation sample develops.",
            "TRACKABLE_SETUP": "Research tracking is allowed; broker execution still requires a live Bid/Ask quote.",
        }
        return actions.get(status, "Continue scanning completed candles.")

    @staticmethod
    def _rank_blockers(components: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        critical = {
            ("data", "trusted_feed"),
            ("diamond", "current_confirmation"),
            ("diamond", "event_quality"),
            ("confluence", "regime"),
            ("confluence", "asset_profile"),
            ("confluence", "news"),
            ("risk", "entry"),
            ("risk", "stop"),
            ("risk", "target"),
            ("risk", "risk_reward"),
        }
        high = {
            ("diamond", "qualified_origin"),
            ("diamond", "execution_trust"),
            ("diamond", "mtf"),
            ("confluence", "htf"),
            ("confluence", "liquidity"),
            ("confluence", "confirmation"),
            ("risk", "actionable"),
            ("risk", "research"),
        }
        ranked = []
        for component_index, component in enumerate(components):
            for check_index, check in enumerate(component.get("checks") or []):
                if check.get("pass") is True:
                    continue
                key = (str(component.get("id")), str(check.get("id")))
                priority = "CRITICAL" if key in critical else "HIGH" if key in high else "STANDARD"
                ranked.append({
                    **check,
                    "component": component.get("id"),
                    "component_label": component.get("label"),
                    "priority": priority,
                    "_rank": 0 if priority == "CRITICAL" else 1 if priority == "HIGH" else 2,
                    "_order": component_index * 100 + check_index,
                })
        ranked.sort(key=lambda item: (item["_rank"], -float(item.get("points") or 0), item["_order"]))
        for item in ranked:
            item.pop("_rank", None)
            item.pop("_order", None)
        return ranked

    @staticmethod
    def _execution_readiness(
        *,
        feed_trusted: bool,
        qualified_origin: bool,
        mtf_ready: bool,
        mtf_reason: Any,
        regime_ready: bool,
        regime_reason: Any,
        confirmed_current: bool,
        confirmation_reason: Any,
        risk_ready: bool,
        risk_reward: Optional[float],
        minimum_rr: float,
    ) -> Dict[str, Any]:
        gates = [
            {"id": "data", "label": "Data Trust", "pass": feed_trusted, "reason": "Restore a matched and reconciled provider feed."},
            {"id": "origin", "label": "Diamond Origin", "pass": qualified_origin, "reason": "Wait for an entry-grade Diamond origin at a valid structural location."},
            {"id": "mtf", "label": "MTF Agreement", "pass": mtf_ready, "reason": str(mtf_reason)},
            {"id": "location", "label": "Location Guard", "pass": regime_ready, "reason": str(regime_reason or "Wait for a stable regime and a non-chasing entry location.")},
            {"id": "trigger", "label": "Closed Trigger", "pass": confirmed_current, "reason": str(confirmation_reason or "Wait for retest, rejection, and closed-candle follow-through.")},
            {
                "id": "risk",
                "label": "Risk Geometry",
                "pass": risk_ready,
                "reason": (
                    f"Map provider entry, stop, target, and at least {minimum_rr:.1f}R."
                    if risk_reward is None
                    else f"Current reward-to-risk is {risk_reward:.2f}R; at least {minimum_rr:.1f}R is required."
                ),
            },
        ]
        passed = sum(1 for gate in gates if gate["pass"])
        current = next((gate for gate in gates if not gate["pass"]), None)
        return {
            "status": "READY" if current is None else "FORMING" if passed else "LOCKED",
            "passed": passed,
            "total": len(gates),
            "percent": round(passed / len(gates) * 100),
            "current_gate": current,
            "next_gate_id": current.get("id") if current else None,
            "next_gate_label": current.get("label") if current else "Research Tracking Ready",
            "gates": gates,
            "hard_ready": current is None,
            "uses_completed_candles_only": True,
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
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
