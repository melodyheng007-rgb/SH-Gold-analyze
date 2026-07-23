from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import requests


DEFAULT_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
OFFICIAL_USD_CALENDAR_URL = "https://api.fxmacrodata.com/api/v1/calendar/USD"
TRADINGVIEW_CALENDAR_URL = "https://economic-calendar.tradingview.com/events"


class EconomicNewsIntelligence:
    """Turn scheduled macro releases into an asset-aware risk filter."""

    IMPACT_SCORE = {"HOLIDAY": 0, "LOW": 30, "MEDIUM": 65, "HIGH": 100}
    ASSET_CURRENCY_WEIGHT = {
        "XAUUSD": {"USD": 1.0, "CNY": 0.50, "EUR": 0.25, "JPY": 0.20, "GBP": 0.20},
        "BTCUSD": {"USD": 1.0, "CNY": 0.55, "EUR": 0.35, "JPY": 0.30, "GBP": 0.30, "CAD": 0.20},
    }
    CATEGORY_RULES = (
        ("INFLATION", ("cpi", "ppi", "inflation", "price index", "pce")),
        ("CENTRAL_BANK", ("fomc", "fed ", "fed chairman", "rate statement", "interest rate", "monetary policy", "press conference", "central bank")),
        ("LABOR", ("payroll", "employment", "unemployment", "jobless", "adp ", "claims", "wage")),
        ("GROWTH", ("gdp", "retail sales", "pmi", "industrial production", "manufacturing", "consumer sentiment")),
        ("LIQUIDITY", ("treasury", "bond auction", "money supply", "budget balance")),
    )
    CATEGORY_WEIGHT = {
        "INFLATION": 1.0,
        "CENTRAL_BANK": 1.0,
        "LABOR": 0.92,
        "LIQUIDITY": 0.85,
        "GROWTH": 0.80,
        "MACRO": 0.70,
    }

    def __init__(
        self,
        calendar_url: Optional[str] = None,
        cache_seconds: int = 1800,
        timeout_seconds: int = 8,
        persist_cache: bool = True,
        cache_path: Optional[str] = None,
        enable_official_fallback: bool = True,
    ):
        self.calendar_url = calendar_url or os.getenv("ECONOMIC_CALENDAR_URL") or DEFAULT_CALENDAR_URL
        self.official_calendar_url = os.getenv("OFFICIAL_USD_CALENDAR_URL") or OFFICIAL_USD_CALENDAR_URL
        self.actual_calendar_url = os.getenv("ACTUAL_CALENDAR_URL") or TRADINGVIEW_CALENDAR_URL
        self.cache_seconds = max(60, int(cache_seconds))
        self.timeout_seconds = max(2, int(timeout_seconds))
        configured_cache = cache_path or os.getenv("ECONOMIC_CALENDAR_CACHE_PATH")
        self.cache_path = Path(configured_cache) if configured_cache else Path(__file__).resolve().parents[1] / "data" / "news_calendar_cache.json"
        self.persist_cache = bool(persist_cache)
        self.enable_official_fallback = bool(enable_official_fallback)
        self._active_source_name = "Fair Economy weekly economic calendar"
        self._active_source_url = self.calendar_url
        self._lock = threading.Lock()
        self._events: list[Dict[str, Any]] = []
        self._fetched_at: Optional[datetime] = None
        self._last_attempt_at: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._hydrate_disk_cache()

    def snapshot(
        self,
        symbol: str,
        now: Optional[datetime] = None,
        events: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        asset = str(symbol or "XAUUSD").upper()
        if asset not in self.ASSET_CURRENCY_WEIGHT:
            raise ValueError(f"Unsupported news-intelligence symbol: {symbol}")
        current = self._utc(now or datetime.now(timezone.utc))
        if events is None:
            raw_events, feed_status, feed_error, fetched_at = self._load_events(current)
        else:
            raw_events = list(events)
            feed_status, feed_error, fetched_at = "TEST_FIXTURE", None, current

        relevant = []
        for raw in raw_events:
            item = self._normalize_event(raw, asset, current)
            if not item or item["relevance_score"] < 20:
                continue
            if item["minutes_to_event"] < -180 or item["minutes_to_event"] > 7 * 24 * 60:
                continue
            relevant.append(item)
        relevant.sort(key=lambda item: (item["timestamp"], -item["relevance_score"], item["title"]))

        blocking = [
            item for item in relevant
            if item["relevance_score"] >= 70
            and item["impact"] == "HIGH"
            and -20 <= item["minutes_to_event"] <= 45
        ]
        caution = [
            item for item in relevant
            if (
                item["relevance_score"] >= 70 and -20 <= item["minutes_to_event"] <= 180
            ) or (
                item["relevance_score"] >= 50 and -10 <= item["minutes_to_event"] <= 30
            )
        ]
        upcoming = [item for item in relevant if item["minutes_to_event"] >= 0]
        next_event = upcoming[0] if upcoming else None
        next_high = next((item for item in upcoming if item["impact"] == "HIGH" and item["relevance_score"] >= 60), None)
        risk_event = self._risk_event(blocking or caution) or next_high or next_event

        if blocking:
            risk_level = "HIGH"
            execution_gate = "BLOCK_NEW_ENTRIES"
            state = "NEWS_LOCK"
        elif caution:
            risk_level = "ELEVATED"
            execution_gate = "REDUCE_RISK"
            state = "NEWS_CAUTION"
        elif relevant:
            risk_level = "CLEAR"
            execution_gate = "OPEN"
            state = "CALENDAR_CLEAR"
        else:
            risk_level = "UNKNOWN" if feed_status == "UNAVAILABLE" else "CLEAR"
            execution_gate = "OPEN"
            state = "CALENDAR_UNAVAILABLE" if feed_status == "UNAVAILABLE" else "NO_RELEVANT_EVENTS"

        summary = self._summary(asset, state, risk_event, feed_status)
        return {
            "status": "READY" if feed_status in {"LIVE", "SECONDARY_LIVE", "CACHED", "TEST_FIXTURE"} else feed_status,
            "state": state,
            "symbol": asset,
            "risk_level": risk_level,
            "execution_gate": execution_gate,
            "summary": summary,
            "primary_event": risk_event,
            "next_event": next_event,
            "next_high_impact_event": next_high,
            "upcoming_event_count": len(upcoming),
            "blocking_event_count": len(blocking),
            "events": relevant[:12],
            "feed": {
                "status": feed_status,
                "source": self._active_source_name,
                "url": self._active_source_url,
                "fetched_at": fetched_at.isoformat() if fetched_at else None,
                "error": feed_error,
            },
            "analysis_scope": "SCHEDULED_MACRO_RISK_FILTER_ONLY",
            "directional_signal": "TWO_SIDED_UNTIL_RELEASE_AND_PRICE_CONFIRMATION",
            "trade_direction_created": False,
            "generated_at": current.isoformat(),
            "limitations": "Scheduled macro calendar only; unscheduled breaking news is not covered.",
        }

    def weekly_calendar(
        self,
        symbol: str,
        now: Optional[datetime] = None,
        events: Optional[Iterable[Dict[str, Any]]] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Return the complete source week without weakening the execution risk filter."""
        asset = str(symbol or "XAUUSD").upper()
        if asset not in self.ASSET_CURRENCY_WEIGHT:
            raise ValueError(f"Unsupported news-calendar symbol: {symbol}")
        current = self._utc(now or datetime.now(timezone.utc))
        if events is None:
            if force_refresh:
                with self._lock:
                    self._fetched_at = None
                    self._last_attempt_at = None
            raw_events, feed_status, feed_error, fetched_at = self._load_events(current)
        else:
            raw_events = list(events)
            feed_status, feed_error, fetched_at = "TEST_FIXTURE", None, current

        calendar_events = []
        for raw in raw_events:
            item = self._normalize_event(raw, asset, current)
            if not item:
                continue
            item["is_relevant"] = item["relevance_score"] >= 20
            item["risk_window"] = self._calendar_risk_window(item)
            calendar_events.append(item)
        calendar_events.sort(key=lambda item: (item["timestamp"], -item["relevance_score"], item["title"]))

        timestamps = [datetime.fromisoformat(item["timestamp"]) for item in calendar_events]
        relevant_events = [item for item in calendar_events if item["is_relevant"]]
        upcoming_events = [item for item in calendar_events if item["minutes_to_event"] >= 0]
        released_events = [item for item in calendar_events if item["release_status"] == "RELEASED"]
        status = "READY" if feed_status in {"LIVE", "SECONDARY_LIVE", "CACHED", "TEST_FIXTURE"} else feed_status
        return {
            "status": status,
            "symbol": asset,
            "scope": "ROLLING_7_DAY_OFFICIAL_FALLBACK" if feed_status == "OFFICIAL_FALLBACK" else "FULL_SOURCE_WEEK",
            "week_start": min(timestamps).date().isoformat() if timestamps else None,
            "week_end": max(timestamps).date().isoformat() if timestamps else None,
            "events": calendar_events,
            "stats": {
                "total": len(calendar_events),
                "relevant": len(relevant_events),
                "high_impact": sum(item["impact"] == "HIGH" for item in calendar_events),
                "medium_impact": sum(item["impact"] == "MEDIUM" for item in calendar_events),
                "upcoming": len(upcoming_events),
                "released": len(released_events),
                "actual_available": sum(bool(item.get("actual")) for item in released_events),
            },
            "feed": {
                "status": feed_status,
                "source": self._active_source_name,
                "url": self._active_source_url,
                "fetched_at": fetched_at.isoformat() if fetched_at else None,
                "error": feed_error,
            },
            "display_note": "All source events are preserved. Asset relevance is an analysis aid, not a directional trade signal.",
            "generated_at": current.isoformat(),
        }

    def apply_to_analysis(self, analysis: Dict[str, Any], news: Dict[str, Any]) -> Dict[str, Any]:
        signal = analysis.setdefault("signal", {})
        plan = analysis.get("trade_plan")
        event = news.get("primary_event") or {}
        signal["news_state"] = news.get("state")
        signal["news_risk_level"] = news.get("risk_level")
        signal["news_execution_gate"] = news.get("execution_gate")
        signal["news_event"] = event.get("title")
        signal["news_minutes_to_event"] = event.get("minutes_to_event")
        explanation = analysis.setdefault("analysis_explanation", {})
        explanation["news_intelligence"] = news.get("summary")
        if not isinstance(plan, dict):
            return analysis

        plan["news_context"] = news.get("state")
        plan["news_risk_level"] = news.get("risk_level")
        plan["news_event"] = event.get("title")
        plan["news_release_at"] = event.get("timestamp")
        plan["news_scenario"] = event.get("scenario")
        if news.get("execution_gate") != "BLOCK_NEW_ENTRIES":
            return analysis

        direction = str(plan.get("direction") or signal.get("direction") or "WAIT").upper()
        status = str(plan.get("status") or "").upper()
        if direction not in {"BUY", "SELL"} or status not in {"ACTIONABLE", "CANDIDATE"}:
            return analysis

        title = event.get("title") or "high-impact macro news"
        countdown = event.get("countdown") or "active release window"
        reason = f"High-impact news lock: {title} ({countdown}). Wait for the release window and a new completed-candle confirmation."
        missing = plan.setdefault("missing_conditions", [])
        if reason not in missing:
            missing.append(reason)
        plan["technical_status"] = status
        plan["status"] = "NEWS_LOCKED"
        plan["label"] = f"News Lock - {title}"
        plan["action"] = reason
        signal["execution_allowed"] = False
        signal["trade_plan_valid"] = False
        signal["status"] = "NEWS_LOCKED"
        signal["final_action"] = reason
        analysis["final_decision"] = plan["label"]
        explanation["news_risk"] = reason
        explanation["next_trigger"] = reason
        return analysis

    def _load_events(self, now: datetime) -> tuple[list[Dict[str, Any]], str, Optional[str], Optional[datetime]]:
        with self._lock:
            if self._events and self._fetched_at and (now - self._fetched_at).total_seconds() < self.cache_seconds:
                return list(self._events), "CACHED", self._last_error, self._fetched_at
            if not self._events and self._last_attempt_at and (now - self._last_attempt_at).total_seconds() < self.cache_seconds:
                return [], "UNAVAILABLE", self._last_error, None
            self._last_attempt_at = now
            try:
                response = requests.get(
                    self.calendar_url,
                    timeout=self.timeout_seconds,
                    headers={"User-Agent": "SH-Market-Analyzer/3.2.0"},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError("Economic calendar returned a non-list payload.")
                source_events = [item for item in payload if isinstance(item, dict)]
                self._events = self._enrich_actual_values(source_events, now)
                self._fetched_at = now
                self._last_attempt_at = now
                self._last_error = None
                self._active_source_name = "Fair Economy weekly economic calendar"
                self._active_source_url = self.calendar_url
                self._persist_disk_cache()
                return list(self._events), "LIVE", None, self._fetched_at
            except (requests.RequestException, ValueError) as exc:
                primary_error = str(exc)
                if self.enable_official_fallback:
                    try:
                        secondary_events = self._load_tradingview_events(now)
                        if secondary_events:
                            self._events = secondary_events
                            self._fetched_at = now
                            self._last_attempt_at = now
                            self._last_error = f"Primary calendar unavailable: {primary_error}"
                            self._active_source_name = "TradingView economic calendar"
                            self._active_source_url = self.actual_calendar_url
                            self._persist_disk_cache()
                            return list(self._events), "SECONDARY_LIVE", self._last_error, self._fetched_at
                    except (requests.RequestException, ValueError) as secondary_exc:
                        self._last_error = f"Primary: {primary_error}; secondary: {secondary_exc}"
                    try:
                        fallback_events = self._load_official_usd_events(now)
                        if fallback_events:
                            self._events = fallback_events
                            self._fetched_at = now
                            self._last_attempt_at = now
                            self._last_error = f"Primary calendar unavailable: {primary_error}"
                            self._active_source_name = "Official USD release schedule fallback"
                            self._active_source_url = self.official_calendar_url
                            self._persist_disk_cache()
                            return list(self._events), "OFFICIAL_FALLBACK", self._last_error, self._fetched_at
                    except (requests.RequestException, ValueError) as fallback_exc:
                        secondary_error = self._last_error or f"Primary: {primary_error}"
                        self._last_error = f"{secondary_error}; official fallback: {fallback_exc}"
                else:
                    self._last_error = primary_error
                if self._events:
                    return list(self._events), "STALE_CACHE", self._last_error, self._fetched_at
                self._hydrate_disk_cache()
                if self._events:
                    return list(self._events), "STALE_DISK_CACHE", self._last_error, self._fetched_at
                return [], "UNAVAILABLE", self._last_error, None

    def _load_tradingview_events(self, now: datetime) -> list[Dict[str, Any]]:
        start = (now - timedelta(days=2)).strftime("%Y-%m-%dT00:00:00.000Z")
        end = (now + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59.999Z")
        response = requests.get(
            self.actual_calendar_url,
            params={
                "from": start,
                "to": end,
                "countries": "US,CA,EU,GB,JP,CN,AU,NZ,CH",
            },
            timeout=self.timeout_seconds,
            headers={
                "User-Agent": "Mozilla/5.0 SH-Market-Analyzer/3.8.7",
                "Origin": "https://www.tradingview.com",
            },
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("TradingView calendar returned an invalid payload.")

        events = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            timestamp = self._datetime(row.get("date"))
            title = str(row.get("title") or row.get("indicator") or "").strip()
            currency = str(row.get("currency") or "").upper().strip()
            if timestamp is None or not title or not currency:
                continue
            importance = row.get("importance")
            impact = {
                -1: "HOLIDAY",
                0: "LOW",
                1: "LOW",
                2: "MEDIUM",
                3: "HIGH",
            }.get(importance, str(importance or "LOW").upper())
            events.append({
                "title": title,
                "country": currency,
                "date": timestamp.isoformat(),
                "impact": impact,
                "forecast": row.get("forecast"),
                "previous": row.get("previous"),
                "actual": self._format_actual_value(row),
                "source": "TradingView Economic Calendar",
            })
        return events

    def _load_official_usd_events(self, now: datetime) -> list[Dict[str, Any]]:
        response = requests.get(
            self.official_calendar_url,
            timeout=self.timeout_seconds,
            headers={"User-Agent": "SH-Market-Analyzer/3.2.0"},
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Official USD calendar returned an invalid payload.")
        window_start = now - timedelta(hours=3)
        window_end = now + timedelta(days=7)
        events = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            timestamp = self._datetime(row.get("announcement_datetime_utc") or row.get("announcement_datetime"))
            if timestamp is None or timestamp < window_start or timestamp > window_end:
                continue
            events.append({
                "title": row.get("name") or row.get("release"),
                "country": "USD",
                "date": timestamp.isoformat(),
                "impact": row.get("event_importance") or "Low",
                "forecast": "",
                "previous": "",
                "actual": "",
                "source": row.get("source"),
                "source_url": row.get("source_url"),
                "release_date_confirmed": bool(row.get("release_date_confirmed")),
            })
        return events

    def _enrich_actual_values(self, events: list[Dict[str, Any]], now: datetime) -> list[Dict[str, Any]]:
        """Merge released values from TradingView without inventing missing results."""
        if not events or not any((self._datetime(item.get("date")) or now) <= now for item in events):
            return events
        start = (now - timedelta(days=2)).strftime("%Y-%m-%dT00:00:00.000Z")
        end = (now + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59.999Z")
        try:
            response = requests.get(
                self.actual_calendar_url,
                params={
                    "from": start,
                    "to": end,
                    "countries": "US,CA,EU,GB,JP,CN,AU,NZ,CH",
                },
                timeout=self.timeout_seconds,
                headers={"User-Agent": "Mozilla/5.0 SH-Market-Analyzer/3.7", "Origin": "https://www.tradingview.com"},
            )
            response.raise_for_status()
            payload = response.json()
            actual_rows = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(actual_rows, list):
                return events
        except (requests.RequestException, ValueError):
            return events

        candidates = []
        for row in actual_rows:
            if not isinstance(row, dict) or row.get("actual") is None:
                continue
            timestamp = self._datetime(row.get("date"))
            currency = str(row.get("currency") or "").upper().strip()
            title = str(row.get("title") or row.get("indicator") or "").strip()
            if timestamp and currency and title:
                candidates.append((timestamp, currency, title, row))

        enriched = []
        for event in events:
            item = dict(event)
            if self._text(item.get("actual")):
                enriched.append(item)
                continue
            timestamp = self._datetime(item.get("date"))
            currency = str(item.get("country") or item.get("currency") or "").upper().strip()
            title = str(item.get("title") or item.get("event") or "").strip()
            if timestamp is None or timestamp > now or not currency or not title:
                enriched.append(item)
                continue
            nearby = [
                row for row in candidates
                if row[1] == currency and abs((row[0] - timestamp).total_seconds()) <= 90 * 60
            ]
            if not nearby:
                enriched.append(item)
                continue
            title_key = self._title_key(title)
            ranked = sorted(
                nearby,
                key=lambda row: (
                    self._title_similarity(title_key, self._title_key(row[2])),
                    -abs((row[0] - timestamp).total_seconds()),
                ),
                reverse=True,
            )
            match = ranked[0]
            similarity = self._title_similarity(title_key, self._title_key(match[2]))
            if similarity < 0.34 and len(nearby) > 1:
                enriched.append(item)
                continue
            value = self._format_actual_value(match[3])
            if value:
                item["actual"] = value
                item["actual_source"] = "TradingView Economic Calendar"
                item["actual_updated_at"] = now.isoformat()
            enriched.append(item)
        return enriched

    @staticmethod
    def _title_key(value: str) -> str:
        aliases = {"year": "y", "month": "m", "balanceoftrade": "tradebalance"}
        compact = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
        for source, target in aliases.items():
            compact = compact.replace(source, target)
        return compact

    @staticmethod
    def _title_similarity(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        score = SequenceMatcher(None, left, right).ratio()
        left_numbers = set(re.findall(r"\d+", left))
        right_numbers = set(re.findall(r"\d+", right))
        if left_numbers and right_numbers:
            score += 0.30 if left_numbers == right_numbers else -0.35
        return max(0.0, min(1.0, score))

    @staticmethod
    def _format_actual_value(row: Dict[str, Any]) -> Optional[str]:
        value = row.get("actual")
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        unit = str(row.get("unit") or "").strip()
        scale = str(row.get("scale") or "").strip()
        if unit == "%":
            return f"{text}%"
        if scale and scale not in text:
            text = f"{text}{scale}"
        return f"{unit}{text}" if unit and unit not in text else text

    def _hydrate_disk_cache(self) -> None:
        if not self.persist_cache or self._events or not self.cache_path.exists():
            return
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            events = payload.get("events") if isinstance(payload, dict) else None
            fetched_at = self._datetime(payload.get("fetched_at")) if isinstance(payload, dict) else None
            if isinstance(events, list):
                self._events = [item for item in events if isinstance(item, dict)]
                self._fetched_at = fetched_at
                self._active_source_name = str(payload.get("source_name") or self._active_source_name)
                self._active_source_url = str(payload.get("source_url") or self._active_source_url)
        except (OSError, ValueError, TypeError):
            return

    def _persist_disk_cache(self) -> None:
        if not self.persist_cache or not self._events or not self._fetched_at:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(f"{self.cache_path.suffix}.tmp")
            temporary.write_text(json.dumps({
                "fetched_at": self._fetched_at.isoformat(),
                "source_name": self._active_source_name,
                "source_url": self._active_source_url,
                "events": self._events,
            }, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
            temporary.replace(self.cache_path)
        except OSError:
            return

    def _normalize_event(self, raw: Dict[str, Any], symbol: str, now: datetime) -> Optional[Dict[str, Any]]:
        title = str(raw.get("title") or raw.get("event") or raw.get("Event") or "").strip()
        currency = str(raw.get("country") or raw.get("currency") or raw.get("Currency") or "").upper().strip()
        timestamp = self._datetime(raw.get("date") or raw.get("time") or raw.get("Date"))
        if not title or not currency or timestamp is None:
            return None
        impact = str(raw.get("impact") or raw.get("Importance") or "LOW").upper().strip()
        if impact.isdigit():
            impact = {"1": "LOW", "2": "MEDIUM", "3": "HIGH"}.get(impact, "LOW")
        if impact not in self.IMPACT_SCORE:
            impact = "LOW"
        category = self._category(title)
        currency_weight = self.ASSET_CURRENCY_WEIGHT[symbol].get(currency, 0.0)
        relevance = round(self.IMPACT_SCORE[impact] * currency_weight * self.CATEGORY_WEIGHT[category])
        minutes = round((timestamp - now).total_seconds() / 60)
        forecast = raw.get("forecast") if "forecast" in raw else raw.get("Forecast")
        previous = raw.get("previous") if "previous" in raw else raw.get("Previous")
        actual = raw.get("actual") if "actual" in raw else raw.get("Actual")
        released = minutes <= 0
        actual_text = self._text(actual)
        return {
            "id": hashlib.sha1(f"{title}|{currency}|{timestamp.isoformat()}".encode("utf-8")).hexdigest()[:14],
            "title": title,
            "currency": currency,
            "timestamp": timestamp.isoformat(),
            "impact": impact,
            "category": category,
            "forecast": self._text(forecast),
            "previous": self._text(previous),
            "actual": actual_text,
            "minutes_to_event": minutes,
            "countdown": self._countdown(minutes),
            "release_phase": self._release_phase(minutes),
            "release_status": "RELEASED" if released else "UPCOMING",
            "actual_status": (
                "AVAILABLE" if actual_text
                else "UPDATING" if released
                else "SCHEDULED"
            ),
            "relevance_score": relevance,
            "asset_relevance": "DIRECT" if currency == "USD" else "CROSS_MARKET" if currency_weight > 0 else "UNRELATED",
            "source": self._text(raw.get("source")),
            "source_url": self._text(raw.get("source_url")),
            "actual_source": self._text(raw.get("actual_source")),
            "actual_updated_at": self._text(raw.get("actual_updated_at")),
            "release_date_confirmed": raw.get("release_date_confirmed"),
            "scenario": self._scenario(symbol, currency, category),
            "directional_signal": "NONE_BEFORE_RELEASE",
        }

    @staticmethod
    def _calendar_risk_window(event: Dict[str, Any]) -> str:
        minutes = int(event.get("minutes_to_event") or 0)
        relevance = int(event.get("relevance_score") or 0)
        impact = str(event.get("impact") or "LOW")
        if impact == "HIGH" and relevance >= 70 and -20 <= minutes <= 45:
            return "LOCK"
        if (relevance >= 70 and -20 <= minutes <= 180) or (relevance >= 50 and -10 <= minutes <= 30):
            return "CAUTION"
        return "CLEAR"

    @staticmethod
    def _risk_event(events: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not events:
            return None
        return max(
            events,
            key=lambda item: (
                item["relevance_score"],
                -abs(item["minutes_to_event"]),
                -int(datetime.fromisoformat(item["timestamp"]).timestamp()),
            ),
        )

    @classmethod
    def _category(cls, title: str) -> str:
        lowered = title.lower()
        for category, keywords in cls.CATEGORY_RULES:
            if any(keyword in lowered for keyword in keywords):
                return category
        return "MACRO"

    @staticmethod
    def _scenario(symbol: str, currency: str, category: str) -> str:
        if currency != "USD":
            return "Cross-market liquidity can raise volatility; wait for price confirmation before changing direction."
        asset = "gold and Bitcoin" if symbol in {"XAUUSD", "BTCUSD"} else symbol
        scenarios = {
            "INFLATION": f"Above-forecast US inflation can lift USD/yields and pressure {asset}; softer inflation can do the opposite.",
            "CENTRAL_BANK": f"Hawkish Fed language can lift USD/yields and pressure {asset}; dovish language can do the opposite.",
            "LABOR": f"A stronger US labor surprise can lift USD/yields and pressure {asset}; a weaker surprise can do the opposite.",
            "GROWTH": f"A strong US growth surprise can lift USD/yields; {asset} direction still requires a confirmed price reaction.",
            "LIQUIDITY": f"A liquidity or Treasury surprise can move yields quickly; wait for {asset} price confirmation.",
            "MACRO": f"A USD macro surprise can increase {asset} volatility in either direction; wait for release and confirmation.",
        }
        return scenarios[category]

    @staticmethod
    def _summary(symbol: str, state: str, event: Optional[Dict[str, Any]], feed_status: str) -> str:
        if feed_status == "UNAVAILABLE":
            return "Scheduled-news feed is unavailable. Technical analysis remains active without a news veto."
        if not event:
            return f"No relevant scheduled macro event is currently mapped for {symbol}."
        if state == "NEWS_LOCK":
            return f"New entries locked around {event['title']} ({event['countdown']})."
        if state == "NEWS_CAUTION":
            return f"Elevated event risk from {event['title']} ({event['countdown']})."
        return f"Next relevant event: {event['title']} ({event['countdown']})."

    @staticmethod
    def _release_phase(minutes: int) -> str:
        if minutes > 45:
            return "SCHEDULED"
        if minutes >= 0:
            return "PRE_RELEASE_WINDOW"
        if minutes >= -20:
            return "POST_RELEASE_VOLATILITY"
        return "RELEASE_PASSED"

    @staticmethod
    def _countdown(minutes: int) -> str:
        if minutes == 0:
            return "now"
        if minutes < 0:
            return f"{abs(minutes)}m after release"
        hours, remaining = divmod(minutes, 60)
        return f"in {hours}h {remaining}m" if hours else f"in {remaining}m"

    @staticmethod
    def _text(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        try:
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return EconomicNewsIntelligence._utc(parsed)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
