from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class FeedReconciliationEngine:
    """Explain whether the analysis chart and provider sync represent the same market feed."""

    TIMEFRAME_SECONDS = {"1M": 60, "5M": 300, "15M": 900, "1H": 3600, "4H": 14400, "1D": 86400}

    def evaluate(
        self,
        symbol: str,
        timeframe: str,
        chart: Dict[str, Any],
        expected_source: str,
        provider_sync: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        normalized_symbol = str(symbol or "XAUUSD").upper()
        normalized_timeframe = str(timeframe or "15M").upper()
        integrity = chart.get("data_integrity") or {}
        candles = self._candles(chart.get("candles") or [])
        sync = provider_sync or {}
        sync_candle = sync.get("last_candle") or {}
        chart_source = integrity.get("chart_source")
        source_matched = chart_source == expected_source
        mixed_sources = bool(integrity.get("mixed_chart_sources"))
        gap_detected = bool(integrity.get("gap_detected"))
        invalid_count = int(integrity.get("invalid_candles_removed") or 0)
        duplicate_count = int(integrity.get("duplicate_candles_removed") or 0)
        latest = candles[-1] if candles else {}
        chart_close = self._number(latest.get("close"))
        chart_time = self._timestamp(latest.get("time"))
        sync_close = self._number(sync_candle.get("close"))
        sync_time = self._timestamp(sync_candle.get("timestamp") or sync_candle.get("time"))
        sync_is_forming = bool(sync.get("forming_candle") or sync_candle.get("is_partial"))
        comparable = bool(
            chart_time is not None
            and sync_time is not None
            and chart_time == sync_time
            and chart_close is not None
            and sync_close is not None
        )
        drift = abs(chart_close - sync_close) if comparable else None
        drift_percent = drift / abs(sync_close) * 100 if drift is not None and sync_close else None
        tolerance_percent = 0.002 if normalized_symbol == "XAUUSD" else 0.005
        drift_ok = drift_percent is None or drift_percent <= tolerance_percent
        now_utc = now or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        market_session = self._market_session(normalized_symbol, now_utc)
        market_open = market_session["status"] == "OPEN"
        age_seconds = None
        stale = False
        if chart_time is not None:
            expected_close_time = chart_time + self.TIMEFRAME_SECONDS.get(normalized_timeframe, 900)
            age_seconds = max(0, int(now_utc.timestamp()) - expected_close_time)
            stale_limit = max(self.TIMEFRAME_SECONDS.get(normalized_timeframe, 900) * 3, 1800)
            stale = age_seconds > stale_limit and not sync_is_forming and market_open

        freshness_reason = (
            "Scheduled XAU/USD market closure; the last completed candle remains valid historical context."
            if not market_open
            else f"Latest completed candle is {age_seconds or 0} seconds behind its expected close."
        )

        checks = [
            self._check("source", "Matched provider source", source_matched, f"Expected {expected_source}, received {chart_source or 'no source'}."),
            self._check("single_source", "Single chart source", not mixed_sources, "Multiple providers are mixed in the active chart window."),
            self._check("ohlc", "Clean OHLC", invalid_count == 0, f"{invalid_count} invalid candles were removed."),
            self._check("duplicates", "No duplicate timestamps", duplicate_count == 0, f"{duplicate_count} duplicate candles were removed."),
            self._check("gaps", "No active data gap", not gap_detected, integrity.get("gap_reason") or "An active candle gap was detected."),
            self._check("freshness", "Closed candle freshness", not stale, freshness_reason),
            self._check("close_drift", "REST/chart close agreement", drift_ok, f"Provider close drift is {drift_percent:.4f}%." if drift_percent is not None else "No comparable provider close is available."),
        ]
        failed = [check for check in checks if not check["pass"]]
        if not candles:
            status = "NO_CLOSED_CANDLES"
        elif not source_matched or mixed_sources:
            status = "SOURCE_MISMATCH"
        elif gap_detected or invalid_count:
            status = "INTEGRITY_BLOCK"
        elif stale:
            status = "STALE"
        elif not drift_ok:
            status = "CLOSE_DRIFT"
        elif not market_open:
            status = "MATCHED_MARKET_CLOSED"
        elif comparable:
            status = "MATCHED_RECONCILED"
        else:
            status = "MATCHED_AWAITING_COMPARABLE_CLOSE"
        trusted = status in {"MATCHED_RECONCILED", "MATCHED_AWAITING_COMPARABLE_CLOSE", "MATCHED_MARKET_CLOSED"}
        return {
            "status": status,
            "trusted": trusted,
            "symbol": normalized_symbol,
            "timeframe": normalized_timeframe,
            "expected_source": expected_source,
            "chart_source": chart_source,
            "closed_candles": len(candles),
            "latest_closed_time": chart_time,
            "provider_sync_time": sync_time,
            "chart_close": chart_close,
            "provider_close": sync_close,
            "close_drift": round(drift, 6) if drift is not None else None,
            "close_drift_percent": round(drift_percent, 6) if drift_percent is not None else None,
            "tolerance_percent": tolerance_percent,
            "forming_candle": sync_is_forming,
            "market_session": market_session,
            "age_after_expected_close_seconds": age_seconds,
            "checks": checks,
            "blockers": [check["reason"] for check in failed],
            "reconciled_at": now_utc.isoformat(),
        }

    @staticmethod
    def _market_session(symbol: str, now_utc: datetime) -> Dict[str, Any]:
        if symbol != "XAUUSD":
            return {
                "status": "OPEN",
                "schedule": "24/7",
                "timezone": "UTC",
                "reason": "The configured BTC spot market trades continuously.",
            }
        try:
            exchange_zone = ZoneInfo("America/New_York")
            zone_source = "IANA"
        except ZoneInfoNotFoundError:
            exchange_zone = timezone(timedelta(hours=-5))
            zone_source = "UTC-05_FALLBACK"
        local = now_utc.astimezone(exchange_zone)
        weekday = local.weekday()
        minute = local.hour * 60 + local.minute
        daily_close = 16 * 60 + 59
        daily_open = 18 * 60 + 5
        if weekday == 5:
            market_open = False
        elif weekday == 6:
            market_open = minute >= daily_open
        elif weekday == 4:
            market_open = minute < daily_close
        else:
            market_open = minute < daily_close or minute >= daily_open
        return {
            "status": "OPEN" if market_open else "CLOSED",
            "schedule": "SUN-FRI_18:05-16:59_NEW_YORK",
            "timezone": "America/New_York",
            "timezone_source": zone_source,
            "exchange_time": local.isoformat(),
            "reason": (
                "XAU/USD is inside the configured market-data session."
                if market_open
                else "XAU/USD is inside the scheduled weekend or daily maintenance closure."
            ),
        }

    @staticmethod
    def _check(identifier: str, label: str, passed: bool, reason: str) -> Dict[str, Any]:
        return {"id": identifier, "label": label, "pass": bool(passed), "reason": reason}

    @classmethod
    def _candles(cls, candles: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
        normalized = []
        for candle in candles or []:
            if candle.get("is_complete") is False or candle.get("is_partial") is True:
                continue
            timestamp = cls._timestamp(candle.get("time") or candle.get("timestamp"))
            close = cls._number(candle.get("close"))
            if timestamp is not None and close is not None:
                normalized.append({"time": timestamp, "close": close})
        return sorted({candle["time"]: candle for candle in normalized}.values(), key=lambda candle: candle["time"])

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


class ExecutionRealityEngine:
    """Grade research setups without pretending midpoint candles are executable quotes."""

    def evaluate(
        self,
        analysis: Dict[str, Any],
        reconciliation: Dict[str, Any],
    ) -> Dict[str, Any]:
        symbol = str(analysis.get("symbol") or analysis.get("market_symbol") or "XAUUSD").upper()
        plan = analysis.get("trade_plan") or {}
        zones = analysis.get("key_zones") or {}
        auto_entry = analysis.get("diamond_auto_entry") or {}
        news = analysis.get("news_intelligence") or {}
        entry = self._number(plan.get("entry_price") or auto_entry.get("entry_price"))
        stop = self._number(plan.get("stop_loss") or auto_entry.get("stop_loss"))
        targets = plan.get("take_profit_levels") or auto_entry.get("take_profit_levels") or []
        target = self._number(targets[0]) if targets else None
        primary = zones.get("primary_zone") or {}
        atr = self._number((zones.get("latest_entry_event") or {}).get("atr_14") or primary.get("atr_14"))
        risk = abs(entry - stop) if entry is not None and stop is not None else None
        reward = abs(target - entry) if target is not None and entry is not None else None
        risk_reward = reward / risk if risk and reward is not None else None
        slippage_budget_atr = 0.04 if symbol == "XAUUSD" else 0.03
        slippage_budget = atr * slippage_budget_atr if atr is not None else None
        setup_ready = str(plan.get("status") or "").upper() == "ACTIONABLE" and entry is not None
        quote_available = False
        checks = [
            self._check("feed", "Reconciled market feed", reconciliation.get("trusted") is True, (reconciliation.get("blockers") or ["Feed reconciliation is required."])[0]),
            self._check("setup", "Actionable closed-candle setup", setup_ready, "No actionable closed-candle setup is available."),
            self._check("news", "News entry gate clear", news.get("execution_gate") != "BLOCK_NEW_ENTRIES", news.get("summary") or "High-impact news lock is active."),
            self._check("risk", "Mapped stop and target", risk is not None and risk > 0 and risk_reward is not None and risk_reward >= (1.8 if symbol == "XAUUSD" else 1.6), "A provider-mapped stop and minimum reward target are required."),
            self._check("quote", "Live Bid/Ask quote", quote_available, "Midpoint candles do not contain executable Bid/Ask spread."),
        ]
        research_ready = all(check["pass"] for check in checks if check["id"] != "quote")
        broker_ready = all(check["pass"] for check in checks)
        if broker_ready:
            status = "BROKER_EXECUTABLE"
        elif research_ready:
            status = "TRACKABLE_NOT_BROKER_READY"
        elif not setup_ready:
            status = "WAITING_SETUP"
        else:
            status = "RESEARCH_BLOCKED"
        return {
            "status": status,
            "symbol": symbol,
            "research_trackable": research_ready,
            "broker_executable": broker_ready,
            "pricing_mode": "MIDPOINT_RESEARCH",
            "spread": None,
            "spread_source": "NOT_AVAILABLE_FROM_CANDLE_HISTORY",
            "entry": entry,
            "stop": stop,
            "target": target,
            "risk_reward": round(risk_reward, 2) if risk_reward is not None else None,
            "atr": atr,
            "modelled_slippage_budget_atr": slippage_budget_atr,
            "modelled_slippage_budget": round(slippage_budget, 6) if slippage_budget is not None else None,
            "checks": checks,
            "blockers": [check["reason"] for check in checks if not check["pass"]],
            "broker_order_submitted": False,
            "message": (
                "Setup is valid for research tracking, but a live Bid/Ask quote is required before broker execution."
                if status == "TRACKABLE_NOT_BROKER_READY"
                else "Waiting for a fully reconciled, risk-mapped closed-candle setup."
            ),
        }

    @staticmethod
    def apply_to_analysis(analysis: Dict[str, Any], result: Dict[str, Any]) -> None:
        analysis["execution_reality"] = result
        signal = analysis.setdefault("signal", {})
        signal["research_trackable"] = result.get("research_trackable") is True
        signal["broker_execution_allowed"] = result.get("broker_executable") is True
        signal["execution_reality_status"] = result.get("status")

    @staticmethod
    def _check(identifier: str, label: str, passed: bool, reason: str) -> Dict[str, Any]:
        return {"id": identifier, "label": label, "pass": bool(passed), "reason": str(reason)}

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
