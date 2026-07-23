from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pandas as pd

from .data_loader import candles_to_records
from .xauusd_provider import (
    BINANCE_HISTORY_SOURCE,
    CSV_SOURCE,
    HISTORY_GAP_WARNING,
    ARCHIVED_STALE_SOURCE,
    LIVE_BUILDER_SOURCE,
    LIVE_SOURCE,
    OANDA_HISTORY_SOURCE,
    PRELOADED_SOURCE,
    RECENT_CSV_SOURCE,
    REAL_CSV_HISTORY_SOURCE,
    TABLES,
    TEST_HISTORY_LIVE_ANCHORED_SOURCE,
    TEST_HISTORY_SOURCES,
    TEST_HISTORY_SOURCE,
    TWELVE_DATA_HISTORY_SOURCE,
    USER_RECENT_CSV_SOURCE,
    WARMUP_SOURCE,
    SQLiteCandleStore,
    normalize_timeframe,
)

LIVE_SOURCES = {LIVE_SOURCE, LIVE_BUILDER_SOURCE}
REAL_HISTORY_SOURCES = {
    PRELOADED_SOURCE,
    CSV_SOURCE,
    WARMUP_SOURCE,
    RECENT_CSV_SOURCE,
    USER_RECENT_CSV_SOURCE,
    REAL_CSV_HISTORY_SOURCE,
    TWELVE_DATA_HISTORY_SOURCE,
    OANDA_HISTORY_SOURCE,
    BINANCE_HISTORY_SOURCE,
}
HISTORY_SOURCES = REAL_HISTORY_SOURCES | TEST_HISTORY_SOURCES
ALIGNMENT_MAX_AGE_MINUTES = {"1M": 3, "5M": 15, "15M": 45, "1H": 180, "4H": 480, "1D": 4320}


class CandleHistoryAlignmentEngine:
    PRICE_WARN_PERCENT = 0.15
    PRICE_GAP_PERCENT = 0.40
    PRICE_CRITICAL_PERCENT = 1.00
    ABS_WARN_GAP = 5.0
    ABS_PRICE_GAP = 10.0
    ABS_CRITICAL_GAP = 20.0

    def __init__(
        self,
        store: SQLiteCandleStore,
        preferred_source: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.store = store
        self.preferred_source = preferred_source

    def _configured_source(self) -> Optional[str]:
        if not self.preferred_source:
            return None
        try:
            return self.preferred_source()
        except Exception:
            return None

    def check(self, timeframe: str = "15M", limit: int = 1000, cleaned: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        tf = normalize_timeframe(timeframe)
        df = cleaned if cleaned is not None else self.store.get_candles_df(tf, limit)
        df = df.copy()
        if not df.empty:
            df = df.sort_index()
        provider_status = self.store.load_status().to_dict()
        live_price = self._number(provider_status.get("latest_price"))
        latest_live_time = self._timestamp(provider_status.get("last_updated")) or pd.Timestamp.now(tz="UTC")
        history = self._preferred_history(df, tf)
        live = self._source_slice(df, LIVE_SOURCES)
        source = self._source(history)
        source_group = self._source_group(source)
        latest_history_close = self._number(history["close"].iloc[-1]) if not history.empty else None
        latest_history_time = self._timestamp(history.index[-1]) if not history.empty else None
        same_source_live = False
        if source in {OANDA_HISTORY_SOURCE, BINANCE_HISTORY_SOURCE, TWELVE_DATA_HISTORY_SOURCE}:
            source_live_candle = self.store.latest_candle_for_sources(tf, {source}) or {}
            source_live_price = self._number(source_live_candle.get("close"))
            source_live_time = self._timestamp(source_live_candle.get("timestamp"))
            if source_live_price is not None and source_live_time is not None:
                live_price = source_live_price
                latest_live_time = source_live_time
                same_source_live = True

        if history.empty:
            status = "LIVE_ONLY" if live_price is not None or not live.empty else "NO_HISTORY"
            return self._payload(tf, status, live_price, latest_live_time, None, None, None, None, source, source_group)

        price_gap = abs(live_price - latest_history_close) if live_price is not None and latest_history_close is not None else None
        price_gap_percent = (price_gap / abs(live_price) * 100) if price_gap is not None and live_price else None
        price_status = self._price_status(price_gap, price_gap_percent)
        time_status = self._time_status(tf, latest_history_time, latest_live_time)
        if time_status == "ALIGNED" and (same_source_live or self._provider_matches_source(provider_status.get("provider_name"), source)):
            price_status = "ALIGNED"

        if source in TEST_HISTORY_SOURCES:
            aligned = price_status == "ALIGNED" and time_status == "ALIGNED"
            status = "TEST_MODE" if aligned or source == TEST_HISTORY_LIVE_ANCHORED_SOURCE else "TEST_MODE"
        elif time_status == "FUTURE_HISTORY":
            status = "FUTURE_HISTORY"
        elif price_status == "CRITICAL_PRICE_GAP":
            status = "CRITICAL_PRICE_GAP"
        elif price_status not in {"ALIGNED", None} and time_status not in {"ALIGNED", None}:
            status = "PRICE_AND_TIME_GAP"
        elif price_status not in {"ALIGNED", None}:
            status = price_status
        elif time_status not in {"ALIGNED", None}:
            status = time_status
        else:
            status = "ALIGNED"

        return self._payload(tf, status, live_price, latest_live_time, latest_history_close, latest_history_time, price_gap, price_gap_percent, source, source_group)

    def _provider_matches_source(self, provider_name: Optional[str], source: Optional[str]) -> bool:
        provider = str(provider_name or "").lower()
        matches = {
            OANDA_HISTORY_SOURCE: "oanda",
            BINANCE_HISTORY_SOURCE: "binance",
            TWELVE_DATA_HISTORY_SOURCE: "twelve data",
        }
        expected = matches.get(source)
        return bool(expected and expected in provider)

    def _payload(
        self,
        timeframe: str,
        status: str,
        live_price: Optional[float],
        latest_live_time: Optional[pd.Timestamp],
        latest_history_close: Optional[float],
        latest_history_time: Optional[pd.Timestamp],
        price_gap: Optional[float],
        price_gap_percent: Optional[float],
        source: Optional[str],
        source_group: str,
    ) -> Dict[str, Any]:
        healthy = status == "ALIGNED"
        test_aligned = status == "TEST_MODE" and source == TEST_HISTORY_LIVE_ANCHORED_SOURCE and price_gap is not None and price_gap <= self.ABS_WARN_GAP
        analysis_allowed = healthy or test_aligned
        recommended_action = self._recommended_action(status, source_group)
        warning_message = self._message(status, live_price, latest_history_close, price_gap, price_gap_percent)
        return {
            "timeframe": timeframe,
            "status": status,
            "alignment_status": status,
            "live_price": round(live_price, 3) if live_price is not None else None,
            "latest_live_price": round(live_price, 3) if live_price is not None else None,
            "latest_history_close": round(latest_history_close, 3) if latest_history_close is not None else None,
            "price_gap": round(price_gap, 3) if price_gap is not None else None,
            "price_gap_percent": round(price_gap_percent, 3) if price_gap_percent is not None else None,
            "latest_history_time": latest_history_time.isoformat() if latest_history_time is not None else None,
            "latest_live_time": latest_live_time.isoformat() if latest_live_time is not None else None,
            "source": source,
            "source_group": source_group,
            "healthy": bool(healthy),
            "analysis_allowed": bool(analysis_allowed),
            "recommended_action": recommended_action,
            "required_action": recommended_action,
            "warning_message": warning_message,
            "message": warning_message,
        }

    def _preferred_history(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        if df.empty or "source" not in df.columns:
            return pd.DataFrame(columns=df.columns)
        live_price = self._number(self.store.load_status().latest_price)
        live_time = self._timestamp(self.store.load_status().last_updated) or pd.Timestamp.now(tz="UTC")
        configured_source = self._configured_source()
        configured_history = self._source_slice(df, {configured_source}) if configured_source else pd.DataFrame(columns=df.columns)
        if not configured_history.empty:
            return configured_history
        aligned_test = self._source_slice(df, {TEST_HISTORY_LIVE_ANCHORED_SOURCE})
        if self._candidate_is_aligned(aligned_test, timeframe, live_price, live_time):
            return aligned_test
        priority = [
            {OANDA_HISTORY_SOURCE},
            {BINANCE_HISTORY_SOURCE},
            {TWELVE_DATA_HISTORY_SOURCE},
            {REAL_CSV_HISTORY_SOURCE},
            {USER_RECENT_CSV_SOURCE},
            {RECENT_CSV_SOURCE},
            {CSV_SOURCE},
            {WARMUP_SOURCE},
            {PRELOADED_SOURCE},
            {TEST_HISTORY_LIVE_ANCHORED_SOURCE},
            {TEST_HISTORY_SOURCE},
            LIVE_SOURCES,
        ]
        best_candidate = pd.DataFrame(columns=df.columns)
        best_score = float("inf")
        for sources in priority:
            sliced = self._source_slice(df, sources)
            if self._candidate_is_aligned(sliced, timeframe, live_price, live_time):
                return sliced
            score = self._candidate_score(sliced, timeframe, live_price, live_time)
            if score < best_score:
                best_score = score
                best_candidate = sliced
        if not best_candidate.empty:
            return best_candidate
        for sources in priority:
            sliced = self._source_slice(df, sources)
            if not sliced.empty:
                return sliced
        return pd.DataFrame(columns=df.columns)

    def _candidate_is_aligned(self, df: pd.DataFrame, timeframe: str, live_price: Optional[float], live_time: Optional[pd.Timestamp]) -> bool:
        if df.empty or live_price is None:
            return False
        close = self._number(df["close"].iloc[-1])
        history_time = self._timestamp(df.index[-1])
        if close is None or history_time is None:
            return False
        time_aligned = self._time_status(timeframe, history_time, live_time) == "ALIGNED"
        if timeframe == "1D":
            # Daily provider candles close at provider-specific session times. Their
            # close may be far from the current intraday price without being stale.
            return time_aligned
        price_gap = abs(live_price - close)
        price_gap_percent = price_gap / abs(live_price) * 100 if live_price else 999
        if price_gap > self.ABS_WARN_GAP or price_gap_percent > self.PRICE_WARN_PERCENT:
            return False
        return time_aligned

    def _candidate_score(self, df: pd.DataFrame, timeframe: str, live_price: Optional[float], live_time: Optional[pd.Timestamp]) -> float:
        if df.empty:
            return float("inf")
        close = self._number(df["close"].iloc[-1])
        history_time = self._timestamp(df.index[-1])
        if close is None or history_time is None:
            return float("inf")
        price_score = abs((live_price or close) - close)
        age_minutes = abs(((live_time or pd.Timestamp.now(tz="UTC")) - history_time).total_seconds()) / 60
        max_age = ALIGNMENT_MAX_AGE_MINUTES[timeframe]
        return price_score + max(0.0, age_minutes - max_age) * 0.25

    def _source_slice(self, df: pd.DataFrame, sources: set[str]) -> pd.DataFrame:
        if df.empty or "source" not in df.columns:
            return pd.DataFrame(columns=df.columns)
        return df[df["source"].isin(sources)].copy()

    def _source(self, df: pd.DataFrame) -> Optional[str]:
        if df.empty or "source" not in df.columns:
            return None
        return str(df["source"].iloc[-1])

    def _source_group(self, source: Optional[str]) -> str:
        if source in {OANDA_HISTORY_SOURCE, BINANCE_HISTORY_SOURCE}:
            return "MATCHED_MARKET_API"
        if source == TWELVE_DATA_HISTORY_SOURCE:
            return "API_HISTORY"
        if source in REAL_HISTORY_SOURCES:
            return "REAL_CSV_HISTORY" if source == REAL_CSV_HISTORY_SOURCE else "API_HISTORY"
        if source in TEST_HISTORY_SOURCES:
            return source
        if source in LIVE_SOURCES:
            return "LIVE_BUILDER"
        return "NO_HISTORY"

    def _price_status(self, price_gap: Optional[float], price_gap_percent: Optional[float]) -> Optional[str]:
        if price_gap is None or price_gap_percent is None:
            return None
        if price_gap > self.ABS_CRITICAL_GAP or price_gap_percent > self.PRICE_CRITICAL_PERCENT:
            return "CRITICAL_PRICE_GAP"
        if price_gap > self.ABS_PRICE_GAP or price_gap_percent > self.PRICE_GAP_PERCENT:
            return "PRICE_GAP"
        if price_gap > self.ABS_WARN_GAP or price_gap_percent > self.PRICE_WARN_PERCENT:
            return "WARNING_PRICE_GAP"
        return "ALIGNED"

    def _time_status(self, timeframe: str, history_time: Optional[pd.Timestamp], live_time: Optional[pd.Timestamp]) -> Optional[str]:
        if history_time is None:
            return "NO_HISTORY"
        live_time = live_time or pd.Timestamp.now(tz="UTC")
        if history_time > live_time + pd.Timedelta(seconds=60):
            return "FUTURE_HISTORY"
        age_minutes = (live_time - history_time).total_seconds() / 60
        if age_minutes > ALIGNMENT_MAX_AGE_MINUTES[timeframe]:
            return "STALE_HISTORY"
        return "ALIGNED"

    def _recommended_action(self, status: str, source_group: str) -> str:
        if status == "ALIGNED":
            return "NONE"
        if status == "TEST_MODE":
            return "TEST_MODE"
        if status == "LIVE_ONLY":
            return "IMPORT_RECENT_HISTORY"
        if status == "NO_HISTORY":
            return "IMPORT_RECENT_HISTORY"
        if status == "FUTURE_HISTORY":
            return "CLEAR_MISALIGNED_HISTORY"
        if source_group == "LIVE_BUILDER":
            return "KEEP_LIVE_BUILDER_RUNNING"
        return "IMPORT_RECENT_HISTORY"

    def _message(
        self,
        status: str,
        live_price: Optional[float],
        history_close: Optional[float],
        price_gap: Optional[float],
        price_gap_percent: Optional[float],
    ) -> str:
        if status == "ALIGNED":
            return "History candles are aligned with current live price."
        if status == "TEST_MODE":
            return "TEST MODE: generated candle history is not real market history."
        if status == "LIVE_ONLY":
            return "Live price is available, but aligned candle history is missing."
        if status == "NO_HISTORY":
            return "No candle history is available."
        if live_price is not None and history_close is not None and price_gap is not None:
            pct = f"{price_gap_percent:.3f}%" if price_gap_percent is not None else "-"
            return f"History close {history_close:.2f} is not aligned with live price {live_price:.2f}. Gap: ${price_gap:.2f} ({pct})."
        return "History candles are not aligned with current live price."

    def _timestamp(self, value: Any) -> Optional[pd.Timestamp]:
        if value is None:
            return None
        try:
            ts = pd.Timestamp(value)
            if ts.tzinfo is None:
                return ts.tz_localize("UTC")
            return ts.tz_convert("UTC")
        except Exception:
            return None

    def _number(self, value: Any) -> Optional[float]:
        try:
            number = float(value)
            return number if pd.notna(number) else None
        except Exception:
            return None


class RecentHistoryWarmupService:
    def __init__(self, store: SQLiteCandleStore):
        self.store = store

    def status(self, timeframe: str = "15M") -> Dict[str, Any]:
        tf = normalize_timeframe(timeframe)
        latest = self.store.latest_any_timestamp(tf)
        source_summary = self.store.source_summary(tf)
        local_recent = self._is_recent(latest, tf)
        counts = self.store.counts()
        provider_status = self.store.load_status().to_dict()
        priorities = [
            self._priority("Local recent history from SQLite", local_recent, source_summary),
            self._priority("User CSV recent history", self.store.has_source(tf, CSV_SOURCE), CSV_SOURCE),
            self._priority("Optional Twelve Data recent candles", bool(os.getenv("TWELVE_DATA_API_KEY")), "TWELVE_DATA_API_KEY"),
            self._priority("Optional OANDA demo candles", bool(os.getenv("OANDA_API_TOKEN")), "OANDA_API_TOKEN"),
            self._priority("Gold-API live price builder only", bool(provider_status.get("latest_price")), LIVE_SOURCE),
        ]
        active = next((item for item in priorities if item["available"]), None)
        return {
            "timeframe": tf,
            "active_source": active["name"] if active else None,
            "source_summary": source_summary,
            "latest_candle_time": latest,
            "latest_live_price": provider_status.get("latest_price"),
            "candle_count": counts.get(tf, 0),
            "priorities": priorities,
            "message": "Recent history source detected." if active else "No recent history source is available.",
        }

    def _priority(self, name: str, available: bool, detail: str) -> Dict[str, Any]:
        return {"name": name, "available": bool(available), "detail": detail}

    def _is_recent(self, timestamp: Optional[str], timeframe: str) -> bool:
        if not timestamp:
            return False
        try:
            ts = pd.Timestamp(timestamp)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
        except Exception:
            return False
        max_age_minutes = {"1M": 10, "5M": 45, "15M": 120, "1H": 360, "4H": 1440, "1D": 4320}.get(timeframe, 120)
        return (pd.Timestamp.now(tz="UTC") - ts).total_seconds() / 60 <= max_age_minutes


class DataIntegrityEngine:
    def __init__(
        self,
        store: SQLiteCandleStore,
        preferred_source: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.store = store
        self.warmup = RecentHistoryWarmupService(store)
        self.alignment = CandleHistoryAlignmentEngine(store, preferred_source)

    def data_integrity(self, timeframe: str = "15M", limit: int = 300) -> Dict[str, Any]:
        return self._build(timeframe, limit)["data_integrity"]

    def chart_data(self, timeframe: str = "15M", limit: int = 300) -> Dict[str, Any]:
        return self._build(timeframe, limit)

    def chart_bundle(self, timeframe: str = "15M", limit: int = 300) -> Dict[str, Any]:
        """Build chart, overlays, and indicators from one matched candle frame."""
        built = self._build(timeframe, limit)
        chart = {key: value for key, value in built.items() if key != "frames"}
        return {
            "chart_data": chart,
            "overlays": self._overlays_from_built(built),
            "panels": self._indicator_panels_from_built(built),
        }

    def history_alignment(self, timeframe: str = "15M", limit: int = 1000) -> Dict[str, Any]:
        return self.alignment.check(timeframe, limit)

    def preferred_real_history(self, timeframe: str = "15M", limit: int = 1000) -> pd.DataFrame:
        tf = normalize_timeframe(timeframe)
        raw = self.store.get_candles_df(tf, limit)
        cleaned, _ = self._clean(raw)
        real_only = self._source_slice(cleaned, REAL_HISTORY_SOURCES)
        return self.alignment._preferred_history(real_only, tf)

    def timeframe_snapshot(self, timeframe: str, limit: int = 220) -> Dict[str, Any]:
        tf = normalize_timeframe(timeframe)
        frame = self.preferred_real_history(tf, limit)
        if "is_complete" in frame.columns:
            frame = frame[pd.to_numeric(frame["is_complete"], errors="coerce").fillna(0) == 1]
        frame = frame.tail(limit)
        source = str(frame["source"].iloc[-1]) if not frame.empty and "source" in frame.columns else None
        if len(frame) < 50:
            return {
                "timeframe": tf,
                "status": "WAITING",
                "source": source,
                "candle_count": len(frame),
                "trend": "WAITING",
                "score": 0,
            }
        close = pd.to_numeric(frame["close"], errors="coerce")
        high = pd.to_numeric(frame["high"], errors="coerce")
        low = pd.to_numeric(frame["low"], errors="coerce")
        ema_20 = close.ewm(span=20, adjust=False).mean()
        ema_50 = close.ewm(span=50, adjust=False).mean()
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        macd_histogram = macd - macd.ewm(span=9, adjust=False).mean()
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        rsi = (100 - 100 / (1 + gain / loss.mask(loss == 0))).astype(float)
        rsi = rsi.mask((loss == 0) & (gain > 0), 100.0)
        rsi = rsi.mask((gain == 0) & (loss > 0), 0.0)
        rsi = rsi.fillna(50.0)
        previous_close = close.shift(1)
        true_range = pd.concat([
            (high - low).abs(),
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ], axis=1).max(axis=1)
        atr = true_range.rolling(14, min_periods=1).mean()
        latest_close = float(close.iloc[-1])
        latest_ema_20 = float(ema_20.iloc[-1])
        latest_ema_50 = float(ema_50.iloc[-1])
        latest_rsi = float(rsi.iloc[-1])
        latest_macd = float(macd_histogram.iloc[-1])
        latest_atr = float(atr.iloc[-1])
        trend_score = 1 if latest_close > latest_ema_20 > latest_ema_50 else -1 if latest_close < latest_ema_20 < latest_ema_50 else 0
        rsi_score = 1 if latest_rsi >= 55 else -1 if latest_rsi <= 45 else 0
        macd_score = 1 if latest_macd > 0 else -1 if latest_macd < 0 else 0
        score = round((trend_score + rsi_score + macd_score) / 3 * 100)
        trend = "BULLISH" if score >= 34 else "BEARISH" if score <= -34 else "RANGE"
        latest_time = pd.Timestamp(frame.index[-1])
        return {
            "timeframe": tf,
            "status": "READY",
            "source": source,
            "candle_count": len(frame),
            "last_complete_time": latest_time.isoformat(),
            "close": round(latest_close, 3),
            "ema_20": round(latest_ema_20, 3),
            "ema_50": round(latest_ema_50, 3),
            "rsi_14": round(latest_rsi, 2),
            "macd_histogram": round(latest_macd, 6),
            "atr_14": round(latest_atr, 3),
            "atr_percent": round(latest_atr / latest_close * 100, 3) if latest_close else None,
            "trend": trend,
            "score": score,
            "components": {
                "ema_trend": trend_score,
                "rsi": rsi_score,
                "macd": macd_score,
            },
        }

    def overlays(self, timeframe: str = "15M", limit: int = 300) -> Dict[str, Any]:
        built = self._build(timeframe, limit)
        return self._overlays_from_built(built)

    def _overlays_from_built(self, built: Dict[str, Any]) -> Dict[str, Any]:
        df = built["frames"]["analysis"]
        levels = self._overlay_levels(df, built)
        return {
            "symbol": "XAUUSD",
            "timeframe": built["timeframe"],
            "status": "NO_CANDLES" if df.empty else "READY",
            "overlays": levels,
            "chart_overlays": {key: item["price"] for key, item in levels.items() if item.get("price") is not None and item.get("ready")},
            "overlay_status": self._overlay_status(levels),
            "data_integrity": built["data_integrity"],
        }

    def indicator_panels(self, timeframe: str = "15M", limit: int = 300) -> Dict[str, Any]:
        built = self._build(timeframe, limit)
        return self._indicator_panels_from_built(built)

    def _indicator_panels_from_built(self, built: Dict[str, Any]) -> Dict[str, Any]:
        df = built["frames"]["analysis"]
        if not df.empty and "is_complete" in df.columns:
            complete = pd.to_numeric(df["is_complete"], errors="coerce").fillna(0) == 1
            if "is_partial" in df.columns:
                complete &= pd.to_numeric(df["is_partial"], errors="coerce").fillna(0) == 0
            df = df.loc[complete].copy()
        available_candles = len(df)
        chart_source = built["data_integrity"].get("chart_source")

        def readiness(status: str, reason: str) -> Dict[str, Any]:
            return {
                "status": status,
                "reason": reason,
                "available_closed_candles": available_candles,
                "required_closed_candles": 35,
                "source": chart_source,
                "uses_cached_matched_history": bool(chart_source),
                "independent_from_full_analysis": True,
            }

        def waiting_response(status: str, message: str, reason: str) -> Dict[str, Any]:
            indicator_readiness = readiness("WAITING", reason)
            return {
                "symbol": "XAUUSD",
                "timeframe": built["timeframe"],
                "status": status,
                "message": message,
                "readiness": indicator_readiness,
                "indicator_panels": {
                    "boys_selling": [],
                    "bearishness": [],
                    "indicator_snapshot": {"status": "WAITING", "source": "CLOSED_PROVIDER_CANDLES"},
                    "indicator_readiness": indicator_readiness,
                    "market_pressure_score": {"bullish": 0, "bearish": 0, "neutral": 100},
                },
                "data_integrity": built["data_integrity"],
            }

        data_mode = built["data_integrity"].get("data_mode")
        if data_mode == "GAP_WARNING":
            return waiting_response("FIX_GAP_REQUIRED", "Fix gap required", "DATA_GAP")
        if data_mode == "LIVE_ONLY":
            return waiting_response("WAITING_FOR_HISTORY", "Waiting for candle history", "LIVE_ONLY")
        if df.empty or len(df) < 35:
            return waiting_response("WAITING_FOR_HISTORY", "Waiting for candle history", "INSUFFICIENT_CLOSED_CANDLES")
        boys_selling, bearishness, pressure = self._indicator_data(df)
        indicator_readiness = readiness("READY", "CACHED_MATCHED_HISTORY_READY")
        return {
            "symbol": "XAUUSD",
            "timeframe": built["timeframe"],
            "status": "NO_CANDLES" if df.empty else "READY",
            "badge": "TEST DATA" if built["data_integrity"].get("test_data_present") else None,
            "readiness": indicator_readiness,
            "indicator_panels": {
                "boys_selling": boys_selling,
                "bearishness": bearishness,
                "indicator_snapshot": self._indicator_snapshot(boys_selling, bearishness),
                "indicator_readiness": indicator_readiness,
                "market_pressure_score": pressure,
                "engine_version": "MOMENTUM_V3_8_7_CONFLUENCE",
            },
            "data_integrity": built["data_integrity"],
        }

    def clear_invalid_candles(self) -> Dict[str, Any]:
        removed: Dict[str, int] = {}
        with self.store.connect() as conn:
            for timeframe, table in TABLES.items():
                before = conn.total_changes
                conn.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                       OR timestamp IS NULL OR TRIM(timestamp) = ''
                       OR high < open OR high < close OR high < low
                       OR low > open OR low > close OR low > high
                    """
                )
                removed[timeframe] = conn.total_changes - before
        return {"ok": True, "removed": removed, "candle_counts": self.store.counts()}

    def import_recent_history(self, csv_path: str, timeframe: str = "15M", source: str = USER_RECENT_CSV_SOURCE) -> Dict[str, Any]:
        candles = self._load_csv_candles(csv_path)
        tf = normalize_timeframe(timeframe)
        imported = self.store.insert_candles(tf, candles, source)
        integrity = self.data_integrity(tf, 300)
        return {
            "ok": True,
            "timeframe": tf,
            "source": source,
            "imported": imported,
            "last_imported_candle_time": candles[-1]["timestamp"] if candles else None,
            "gap_detected": integrity.get("gap_detected"),
            "data_status": integrity.get("data_status"),
            "candle_counts": self.store.counts(),
        }

    def import_real_recent_history(self, csv_path: str, default_timeframe: str = "15M", source: str = USER_RECENT_CSV_SOURCE) -> Dict[str, Any]:
        path = Path(csv_path)
        df = pd.read_csv(path)
        df.columns = [col.strip().lower() for col in df.columns]
        imported: Dict[str, int] = {}
        errors: Dict[str, str] = {}
        last_imported: Dict[str, Optional[str]] = {}
        if "timeframe" in df.columns:
            for raw_tf, group in df.groupby("timeframe"):
                try:
                    tf = normalize_timeframe(str(raw_tf))
                    candles = self._records_from_csv_frame(group.drop(columns=["timeframe"]), path.name)
                    imported[tf] = self.store.insert_candles(tf, candles, source)
                    last_imported[tf] = candles[-1]["timestamp"] if candles else None
                except Exception as exc:
                    errors[str(raw_tf)] = str(exc)
        else:
            tf = normalize_timeframe(default_timeframe)
            candles = self._records_from_csv_frame(df, path.name)
            imported[tf] = self.store.insert_candles(tf, candles, source)
            last_imported[tf] = candles[-1]["timestamp"] if candles else None
        integrity = {tf: self.data_integrity(tf, 300) for tf in imported}
        return {
            "ok": not errors,
            "source": source,
            "imported": imported,
            "errors": errors,
            "last_imported_candle_time": last_imported,
            "data_integrity": integrity,
            "candle_counts": self.store.counts(),
        }

    def _build(self, timeframe: str, limit: int) -> Dict[str, Any]:
        tf = normalize_timeframe(timeframe)
        raw = self.store.get_candles_df(tf, max(limit * 4, limit))
        cleaned, quality = self._clean(raw)
        test_history = self._source_slice(cleaned, TEST_HISTORY_SOURCES)
        all_real_history = self._source_slice(cleaned, REAL_HISTORY_SOURCES)
        real_history = self.alignment._preferred_history(all_real_history, tf)
        archived_history = self._source_slice(cleaned, {ARCHIVED_STALE_SOURCE})
        live = self._source_slice(cleaned, LIVE_SOURCES)
        has_real_history = not real_history.empty
        has_test_history = not test_history.empty
        alignment = self.alignment.check(tf, max(limit * 4, limit), cleaned)
        alignment_status = alignment.get("alignment_status")
        using_test_history = has_test_history and (alignment.get("source") in TEST_HISTORY_SOURCES or not has_real_history)
        history = test_history if using_test_history else real_history if has_real_history else test_history
        latest_live_price = alignment.get("latest_live_price")
        latest_history_close = alignment.get("latest_history_close")
        latest_live_close = latest_live_price
        gap_statuses = {"WARNING_PRICE_GAP", "PRICE_GAP", "CRITICAL_PRICE_GAP", "PRICE_AND_TIME_GAP", "TIME_GAP", "STALE_HISTORY", "FUTURE_HISTORY"}
        raw_gap_detected = alignment_status in gap_statuses
        active_gap_detected = raw_gap_detected and not using_test_history
        gap_reason = alignment.get("warning_message") if active_gap_detected else None
        gap_pct = alignment.get("price_gap_percent")
        archived_segment = pd.DataFrame(columns=cleaned.columns)
        if using_test_history:
            archived_segment = real_history
            display_source = pd.concat([test_history, live]).sort_index()
            display = display_source.tail(limit)
        elif active_gap_detected:
            archived_segment = real_history
            display = live.tail(limit) if len(live) >= 20 else history.tail(limit)
        else:
            display_source = real_history if has_real_history else cleaned
            display = display_source.tail(limit)
        test_data_present = any(self.store.has_source(tf, source) for source in TEST_HISTORY_SOURCES)
        recent_csv_present = self.store.has_source(tf, RECENT_CSV_SOURCE) or self.store.has_source(tf, USER_RECENT_CSV_SOURCE) or self.store.has_source(tf, REAL_CSV_HISTORY_SOURCE)
        twelve_data_present = self.store.has_source(tf, TWELVE_DATA_HISTORY_SOURCE)
        matched_sources = [OANDA_HISTORY_SOURCE, BINANCE_HISTORY_SOURCE]
        configured_source = self.alignment._configured_source()
        matched_provider_source = next(
            (
                source
                for source in [configured_source, *matched_sources]
                if source and self.store.has_source(tf, source)
            ),
            None,
        )
        matched_provider_present = matched_provider_source is not None
        real_recent_history_present = bool(has_real_history and (recent_csv_present or twelve_data_present or matched_provider_present or self.store.has_source(tf, PRELOADED_SOURCE) or self.store.has_source(tf, WARMUP_SOURCE)))
        if cleaned.empty:
            status = "NO_HISTORY"
            warning = "No candle data available. Start live builder or import recent history."
        elif using_test_history:
            status = "TEST_DATA_MODE"
            warning = "Test history is for development only."
        elif active_gap_detected:
            status = "READY_WITH_GAP_WARNING"
            warning = alignment.get("warning_message") or "Historical data is not aligned with current live price. Live segment started separately."
        elif recent_csv_present:
            status = "RECENT_HISTORY_READY"
            warning = None
        elif history.empty and not live.empty:
            status = "LIVE_ONLY"
            warning = "Only live segment is available. Full MTF analysis requires recent candle history."
        elif history.empty:
            status = "NO_HISTORY"
            warning = "No candle data available. Start live builder or import recent history."
        else:
            status = "READY"
            warning = None
        data_mode = self._data_mode(status, active_gap_detected)
        archived_hidden = bool(not archived_segment.empty and (using_test_history or active_gap_detected))
        integrity = {
            "status": status,
            "chart_status": "READY_WITH_GAP_WARNING" if active_gap_detected else "READY" if not cleaned.empty else "NO_HISTORY",
            "gap_detected": active_gap_detected,
            "raw_gap_detected": raw_gap_detected,
            "gap_reason": gap_reason if active_gap_detected else None,
            "gap_warning": warning if active_gap_detected else None,
            "latest_history_close": round(latest_history_close, 3) if latest_history_close else None,
            "latest_live_price": round(float(latest_live_close), 3) if latest_live_close else None,
            "price_gap": alignment.get("price_gap"),
            "price_gap_percent": round(float(gap_pct), 3) if gap_pct is not None else None,
            "latest_history_time": alignment.get("latest_history_time"),
            "latest_live_time": alignment.get("latest_live_time"),
            "alignment_status": alignment_status,
            "alignment": alignment,
            "analysis_allowed": alignment.get("analysis_allowed"),
            "warning_message": alignment.get("warning_message") if active_gap_detected else None,
            "recommended_action": alignment.get("recommended_action"),
            "invalid_candles_removed": quality["invalid_removed"],
            "duplicate_candles_removed": quality["duplicates_removed"],
            "abnormal_candles_flagged": quality["abnormal_count"],
            "warnings": quality["warnings"] + ([warning] if warning else []),
            "recent_history_warmup": self.warmup.status(tf),
            "data_status": status,
            "source_labels": self._source_labels(tf),
            "chart_source": str(real_history["source"].iloc[-1]) if not real_history.empty and "source" in real_history.columns else None,
            "mixed_chart_sources": bool(not real_history.empty and "source" in real_history.columns and real_history["source"].nunique() > 1),
            "test_data_present": test_data_present,
            "live_anchored_test_present": self.store.has_source(tf, TEST_HISTORY_LIVE_ANCHORED_SOURCE),
            "recent_csv_history_present": recent_csv_present,
            "twelve_data_history_present": twelve_data_present,
            "matched_provider_history_present": matched_provider_present,
            "matched_provider_source": matched_provider_source,
            "real_recent_history_present": real_recent_history_present,
            "user_recent_csv_present": self.store.has_source(tf, USER_RECENT_CSV_SOURCE),
            "real_csv_history_present": self.store.has_source(tf, REAL_CSV_HISTORY_SOURCE),
            "data_mode": data_mode["data_mode"],
            "data_mode_label": data_mode["label"],
            "data_mode_description": data_mode["description"],
            "test_data_rule": "TEST_HISTORY is chart/testing data only and is never treated as live data.",
        }
        return {
            "symbol": "XAUUSD",
            "timeframe": tf,
            "status": integrity["chart_status"],
            "candles": candles_to_records(display, limit),
            "segments": {
                "history": candles_to_records(history.tail(limit), limit),
                "live": candles_to_records(live.tail(limit), limit),
                "stale": candles_to_records(archived_segment.tail(limit), limit),
                "active": candles_to_records(display.tail(limit), limit),
            },
            "archived_stale_history_hidden": archived_hidden,
            "archived_stale_label": "Archived stale history hidden" if archived_hidden else None,
            "gap_marker": self._gap_marker(history, live) if active_gap_detected else None,
            "data_integrity": integrity,
            "alignment": alignment,
            "latest_live_price": alignment.get("latest_live_price"),
            "latest_history_close": alignment.get("latest_history_close"),
            "alignment_status": alignment_status,
            "analysis_allowed": alignment.get("analysis_allowed"),
            "warning_message": alignment.get("warning_message") if active_gap_detected else None,
            "health_status": "HEALTHY" if alignment.get("healthy") and not cleaned.empty else alignment_status,
            "frames": {
                "cleaned": cleaned,
                "history": history,
                "real_history": real_history,
                "test_history": test_history,
                "archived_history": archived_history,
                "live": live,
                "analysis": display if using_test_history else live if active_gap_detected and not live.empty else real_history if has_real_history else cleaned,
            },
        }

    def _clean(self, df: pd.DataFrame) -> tuple[pd.DataFrame, Dict[str, Any]]:
        warnings: list[str] = []
        if df.empty:
            return df.copy(), {"invalid_removed": 0, "duplicates_removed": 0, "abnormal_count": 0, "warnings": ["No candles available."]}
        work = df.copy()
        work.index = pd.to_datetime(work.index, errors="coerce", utc=True)
        missing_timestamp = int(work.index.isna().sum())
        work = work[~work.index.isna()]
        duplicates = int(work.index.duplicated(keep="last").sum())
        work = work[~work.index.duplicated(keep="last")].sort_index()
        for col in ["open", "high", "low", "close"]:
            work[col] = pd.to_numeric(work[col], errors="coerce")
        invalid_mask = (
            work[["open", "high", "low", "close"]].isna().any(axis=1)
            | (work[["open", "high", "low", "close"]] <= 0).any(axis=1)
            | (work["high"] < work[["open", "close", "low"]].max(axis=1))
            | (work["low"] > work[["open", "close", "high"]].min(axis=1))
        )
        invalid_removed = int(invalid_mask.sum()) + missing_timestamp
        work = work[~invalid_mask]
        if work.empty:
            warnings.append("All candles were invalid after OHLC validation.")
            return work, {"invalid_removed": invalid_removed, "duplicates_removed": duplicates, "abnormal_count": 0, "warnings": warnings}
        candle_range = (work["high"] - work["low"]).abs()
        median_range = float(candle_range[candle_range > 0].median() or 0)
        abnormal_mask = pd.Series(False, index=work.index)
        if median_range > 0:
            abnormal_mask = abnormal_mask | (candle_range > median_range * 10)
        abnormal_mask = abnormal_mask | ((candle_range / work["close"].replace(0, pd.NA)).fillna(0) > 0.03)
        abnormal_count = int(abnormal_mask.sum())
        if abnormal_count:
            work["is_abnormal"] = abnormal_mask
            warnings.append(f"{abnormal_count} high-volatility candles flagged but retained after valid OHLC checks.")
        return work, {
            "invalid_removed": invalid_removed,
            "duplicates_removed": duplicates,
            "abnormal_count": abnormal_count,
            "warnings": warnings,
        }

    def _source_slice(self, df: pd.DataFrame, sources: set[str]) -> pd.DataFrame:
        if df.empty or "source" not in df.columns:
            return pd.DataFrame(columns=df.columns)
        return df[df["source"].isin(sources)].copy()

    def _gap_marker(self, history: pd.DataFrame, live: pd.DataFrame) -> Optional[Dict[str, Any]]:
        if history.empty and live.empty:
            return None
        marker_time = live.index[0] if not live.empty else history.index[-1]
        timestamp = pd.Timestamp(marker_time)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        return {"time": int(timestamp.timestamp()), "label": "History Gap"}

    def _overlay_levels(self, df: pd.DataFrame, built: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        integrity = built["data_integrity"]
        live_price = integrity.get("latest_live_price")
        current = float(df["close"].iloc[-1]) if not df.empty else live_price
        levels = {
            "price_line": self._level("Price Line", current, "#f3f4f6", group="Core", ready=current is not None, default_visible=True),
            "pivot_line": self._disabled_level("Pivot", "#36d1dc", "Core", "Waiting for recent session history."),
            "ma_30": self._disabled_level("30MA", "#7CFC00", "Moving Average", "Waiting for at least 30 candles."),
            "ktr_plus_3": self._disabled_level("KTR+3", "#facc15", "Core", "Waiting for recent candle range data.", "dashed"),
            "previous_day_high": self._disabled_level("Previous Day High", "#60a5fa", "Liquidity", "Waiting for previous day data.", default_visible=False),
            "previous_day_low": self._disabled_level("Previous Day Low", "#60a5fa", "Liquidity", "Waiting for previous day data.", default_visible=False),
            "equal_high": self._disabled_level("Equal High", "#36d1dc", "Liquidity", "Waiting for swing data.", default_visible=False),
            "equal_low": self._disabled_level("Equal Low", "#36d1dc", "Liquidity", "Waiting for swing data.", default_visible=False),
            "liquidity_sweep": self._disabled_level("Liquidity Sweep", "#f97316", "Liquidity", "No sweep detected.", default_visible=False),
            "session_high": self._disabled_level("Session High", "#a78bfa", "Session", "Waiting for session candles.", default_visible=False),
            "session_low": self._disabled_level("Session Low", "#a78bfa", "Session", "Waiting for session candles.", default_visible=False),
            "entry_zone_low": self._disabled_level("Entry Zone Low", "#22c55e", "Setup", "Waiting for valid setup.", default_visible=False),
            "entry_zone_high": self._disabled_level("Entry Zone High", "#22c55e", "Setup", "Waiting for valid setup.", default_visible=False),
            "invalidation": self._disabled_level("Invalidation", "#ff5630", "Setup", "Waiting for valid setup.", default_visible=False),
            "target_1": self._disabled_level("Target 1", "#7CFC00", "Setup", "Waiting for valid setup.", default_visible=False),
            "target_2": self._disabled_level("Target 2", "#7CFC00", "Setup", "Waiting for valid setup.", default_visible=False),
            "target_3": self._disabled_level("Target 3", "#7CFC00", "Setup", "Waiting for valid setup.", default_visible=False),
        }
        if df.empty:
            return levels
        history_ready = len(df) >= 8 and not integrity.get("gap_detected")
        if history_ready:
            previous = df.iloc[-2]
            pivot = float((previous["high"] + previous["low"] + previous["close"]) / 3)
            levels["pivot_line"] = self._level("Pivot", pivot, "#36d1dc", group="Core", default_visible=True)
        if len(df) >= 30:
            ma_30 = float(df["close"].rolling(30).mean().iloc[-1])
            levels["ma_30"] = self._level("30MA", ma_30, "#7CFC00", group="Moving Average", default_visible=True)
        if len(df) >= 14:
            candle_range = (df["high"] - df["low"]).abs()
            atr = float(candle_range.rolling(14).mean().iloc[-1])
            if atr > 0 and current is not None:
                levels["ktr_plus_3"] = self._level("KTR+3", float(current) + atr * 0.75, "#facc15", "dashed", group="Core", default_visible=True)
        unique_days = pd.Index(pd.to_datetime(df.index).date).unique()
        if len(unique_days) >= 2:
            previous_day = unique_days[-2]
            previous_day_df = df[pd.Index(pd.to_datetime(df.index).date) == previous_day]
            if not previous_day_df.empty:
                levels["previous_day_high"] = self._level("Previous Day High", float(previous_day_df["high"].max()), "#60a5fa", group="Liquidity", default_visible=False)
                levels["previous_day_low"] = self._level("Previous Day Low", float(previous_day_df["low"].min()), "#60a5fa", group="Liquidity", default_visible=False)
        if len(df) >= 50:
            swing = df.tail(50)
            levels["equal_high"] = self._level("Equal High", float(swing["high"].tail(20).max()), "#36d1dc", group="Liquidity", default_visible=False)
            levels["equal_low"] = self._level("Equal Low", float(swing["low"].tail(20).min()), "#36d1dc", group="Liquidity", default_visible=False)
            previous_high = float(swing["high"].iloc[:-1].max())
            previous_low = float(swing["low"].iloc[:-1].min())
            last = swing.iloc[-1]
            if float(last["high"]) > previous_high and float(last["close"]) < previous_high:
                levels["liquidity_sweep"] = self._level("Liquidity Sweep", previous_high, "#f97316", group="Liquidity", default_visible=False)
            elif float(last["low"]) < previous_low and float(last["close"]) > previous_low:
                levels["liquidity_sweep"] = self._level("Liquidity Sweep", previous_low, "#f97316", group="Liquidity", default_visible=False)
        if len(df) >= 20:
            session = df.tail(min(len(df), 96))
            levels["session_high"] = self._level("Session High", float(session["high"].max()), "#a78bfa", group="Session", default_visible=False)
            levels["session_low"] = self._level("Session Low", float(session["low"].min()), "#a78bfa", group="Session", default_visible=False)
        return levels

    def _level(
        self,
        label: str,
        price: Optional[float],
        color: str,
        style: str = "solid",
        group: str = "Debug",
        ready: bool = True,
        default_visible: bool = True,
        reason: str = "Ready",
    ) -> Dict[str, Any]:
        valid_price = price is not None and pd.notna(price)
        return {
            "label": label,
            "price": round(float(price), 3) if valid_price else None,
            "color": color,
            "style": style,
            "group": group,
            "ready": bool(ready and valid_price),
            "visible": bool(default_visible and ready and valid_price),
            "default_visible": bool(default_visible),
            "reason": reason if ready and valid_price else "Waiting for Data",
        }

    def _disabled_level(self, label: str, color: str, group: str, reason: str, style: str = "solid", default_visible: bool = True) -> Dict[str, Any]:
        return {
            "label": label,
            "price": None,
            "color": color,
            "style": style,
            "group": group,
            "ready": False,
            "visible": False,
            "default_visible": default_visible,
            "reason": reason,
        }

    def _overlay_status(self, levels: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        groups: Dict[str, Dict[str, int]] = {}
        for item in levels.values():
            group = item.get("group", "Debug")
            groups.setdefault(group, {"ready": 0, "waiting": 0})
            if item.get("ready"):
                groups[group]["ready"] += 1
            else:
                groups[group]["waiting"] += 1
        return {
            "ready_count": sum(1 for item in levels.values() if item.get("ready")),
            "waiting_count": sum(1 for item in levels.values() if not item.get("ready")),
            "groups": groups,
        }

    def _source_labels(self, timeframe: str) -> Dict[str, Any]:
        tf = normalize_timeframe(timeframe)
        with self.store.connect() as conn:
            rows = conn.execute(f"SELECT source, COUNT(*) AS count FROM {TABLES[tf]} GROUP BY source ORDER BY source").fetchall()
        return {"timeframe": tf, "sources": [dict(row) for row in rows], "summary": self.store.source_summary(tf)}

    def _data_mode(self, status: str, gap_detected: bool) -> Dict[str, str]:
        if status == "TEST_DATA_MODE":
            return {"data_mode": "TEST", "label": "TEST", "description": "Generated test history + live price"}
        if gap_detected or status == "READY_WITH_GAP_WARNING":
            return {"data_mode": "GAP_WARNING", "label": "GAP WARNING", "description": "History does not match current price"}
        if status == "LIVE_ONLY":
            return {"data_mode": "LIVE_ONLY", "label": "LIVE ONLY", "description": "Only live price, not enough candles"}
        if status in {"RECENT_HISTORY_READY", "READY"}:
            return {"data_mode": "REAL", "label": "REAL", "description": "Recent real history + live price"}
        return {"data_mode": "NO_DATA", "label": "NO DATA", "description": "No live price or candle history"}

    def _indicator_data(self, df: pd.DataFrame) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]], Dict[str, Any]]:
        if df.empty or len(df) < 35:
            return [], [], {"bullish": 0, "bearish": 0, "neutral": 100}
        frame = df.sort_index().tail(240).copy()
        close = pd.to_numeric(frame["close"], errors="coerce")
        high = pd.to_numeric(frame["high"], errors="coerce")
        low = pd.to_numeric(frame["low"], errors="coerce")
        ema_12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
        ema_26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
        macd = ema_12 - ema_26
        macd_signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
        macd_histogram = macd - macd_signal
        histogram_delta = macd_histogram.diff()

        previous_close = close.shift(1)
        true_range = pd.concat([
            (high - low).abs(),
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ], axis=1).max(axis=1)
        atr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

        delta = close.diff()
        average_gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        average_loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        relative_strength = average_gain / average_loss.mask(average_loss == 0)
        rsi = (100 - (100 / (1 + relative_strength))).astype(float)
        rsi = rsi.mask((average_loss == 0) & (average_gain > 0), 100.0)
        rsi = rsi.mask((average_gain == 0) & (average_loss > 0), 0.0)
        rsi = rsi.fillna(50.0)
        rsi_average = rsi.ewm(span=9, adjust=False, min_periods=3).mean()
        rsi_slope = rsi.diff(3)

        macd_records: list[Dict[str, Any]] = []
        rsi_records: list[Dict[str, Any]] = []
        for time in frame.index:
            timestamp = pd.Timestamp(time)
            if timestamp.tzinfo is not None:
                timestamp = timestamp.tz_convert("UTC").tz_localize(None)
            histogram_value = macd_histogram.loc[time]
            macd_value = macd.loc[time]
            signal_value = macd_signal.loc[time]
            delta_value = histogram_delta.loc[time]
            rsi_value = rsi.loc[time]
            atr_value = atr.loc[time]
            if pd.notna(histogram_value) and pd.notna(macd_value) and pd.notna(signal_value):
                value = float(histogram_value)
                delta_number = float(delta_value) if pd.notna(delta_value) else 0.0
                if value >= 0:
                    phase = "BULLISH_EXPANSION" if delta_number >= 0 else "BULLISH_FADE"
                else:
                    phase = "BEARISH_EXPANSION" if delta_number <= 0 else "BEARISH_FADE"
                atr_number = float(atr_value) if pd.notna(atr_value) and float(atr_value) > 0 else 0.0
                strength = min(100.0, abs(value) / (atr_number * 0.12) * 100.0) if atr_number else 0.0
                macd_records.append({
                    "time": int(timestamp.timestamp()),
                    "value": round(value, 6),
                    "macd_line": round(float(macd_value), 6),
                    "signal_line": round(float(signal_value), 6),
                    "delta": round(delta_number, 6),
                    "strength": round(strength, 1),
                    "phase": phase,
                    "close": round(float(close.loc[time]), 6),
                    "high": round(float(high.loc[time]), 6),
                    "low": round(float(low.loc[time]), 6),
                    "color": "bull-strong" if phase == "BULLISH_EXPANSION" else "bull-fade" if phase == "BULLISH_FADE" else "bear-strong" if phase == "BEARISH_EXPANSION" else "bear-fade",
                })
            if pd.notna(rsi_value):
                centered_rsi = float(rsi_value) - 50
                slope_value = float(rsi_slope.loc[time]) if pd.notna(rsi_slope.loc[time]) else 0.0
                average_value = float(rsi_average.loc[time]) if pd.notna(rsi_average.loc[time]) else float(rsi_value)
                raw_rsi = float(rsi_value)
                zone = "OVERBOUGHT" if raw_rsi >= 70 else "OVERSOLD" if raw_rsi <= 30 else "BULLISH" if raw_rsi >= 55 else "BEARISH" if raw_rsi <= 45 else "NEUTRAL"
                rsi_records.append({
                    "time": int(timestamp.timestamp()),
                    "value": round(centered_rsi, 4),
                    "raw_value": round(raw_rsi, 4),
                    "average": round(average_value, 4),
                    "slope": round(slope_value, 4),
                    "zone": zone,
                    "close": round(float(close.loc[time]), 6),
                    "high": round(float(high.loc[time]), 6),
                    "low": round(float(low.loc[time]), 6),
                    "color": "overbought" if raw_rsi >= 70 else "oversold" if raw_rsi <= 30 else "bullish" if raw_rsi >= 55 else "bearish" if raw_rsi <= 45 else "neutral",
                })

        valid_pressure = pd.DataFrame({
            "histogram": macd_histogram,
            "macd_spread": macd - macd_signal,
            "atr": atr,
            "rsi": rsi,
            "rsi_slope": rsi_slope,
        }).dropna().tail(5)
        if valid_pressure.empty:
            composite = 0.0
        else:
            atr_scale = (valid_pressure["atr"] * 0.12).replace(0, pd.NA)
            histogram_score = (valid_pressure["histogram"] / atr_scale).clip(-1, 1).fillna(0)
            spread_score = (valid_pressure["macd_spread"] / atr_scale).clip(-1, 1).fillna(0)
            rsi_score = ((valid_pressure["rsi"] - 50) / 20).clip(-1, 1)
            slope_score = (valid_pressure["rsi_slope"] / 8).clip(-1, 1)
            composite_series = histogram_score * 0.35 + spread_score * 0.20 + rsi_score * 0.30 + slope_score * 0.15
            composite = float(composite_series.mean())
        composite = max(-1.0, min(1.0, composite))
        neutral = max(8.0, 38.0 * (1.0 - abs(composite)))
        directional = 100.0 - neutral
        bullish = directional * (composite + 1.0) / 2.0
        bearish = directional - bullish
        pressure = {
            "bullish": round(bullish, 2),
            "bearish": round(bearish, 2),
            "neutral": round(neutral, 2),
            "score": round(composite * 100),
            "state": "BULLISH" if composite >= 0.18 else "BEARISH" if composite <= -0.18 else "BALANCED",
        }
        return macd_records, rsi_records, pressure

    @staticmethod
    def _indicator_snapshot(
        macd_records: list[Dict[str, Any]],
        rsi_records: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not macd_records or not rsi_records:
            return {"status": "WAITING", "source": "CLOSED_PROVIDER_CANDLES"}

        latest_macd = float(macd_records[-1]["value"])
        previous_macd = float(macd_records[-2]["value"]) if len(macd_records) > 1 else latest_macd
        latest_macd_line = float(macd_records[-1].get("macd_line", latest_macd))
        previous_macd_line = float(macd_records[-2].get("macd_line", latest_macd_line)) if len(macd_records) > 1 else latest_macd_line
        latest_signal_line = float(macd_records[-1].get("signal_line", 0.0))
        previous_signal_line = float(macd_records[-2].get("signal_line", latest_signal_line)) if len(macd_records) > 1 else latest_signal_line
        latest_rsi = float(rsi_records[-1].get("raw_value", 50.0))
        previous_rsi = float(rsi_records[-2].get("raw_value", latest_rsi)) if len(rsi_records) > 1 else latest_rsi
        latest_rsi_average = float(rsi_records[-1].get("average", latest_rsi))
        latest_rsi_slope = float(rsi_records[-1].get("slope", latest_rsi - previous_rsi))
        macd_strength = float(macd_records[-1].get("strength", 0.0))
        macd_phase = str(macd_records[-1].get("phase") or "NEUTRAL")
        macd_divergence = DataIntegrityEngine._indicator_divergence(macd_records, "macd_line")
        rsi_divergence = DataIntegrityEngine._indicator_divergence(rsi_records, "raw_value", 2.0)

        if previous_macd_line <= previous_signal_line and latest_macd_line > latest_signal_line:
            macd_cross = "BULLISH_CROSS"
        elif previous_macd_line >= previous_signal_line and latest_macd_line < latest_signal_line:
            macd_cross = "BEARISH_CROSS"
        else:
            macd_cross = "ABOVE_SIGNAL" if latest_macd_line > latest_signal_line else "BELOW_SIGNAL" if latest_macd_line < latest_signal_line else "AT_SIGNAL"

        if latest_rsi >= 70:
            rsi_zone = "OVERBOUGHT"
        elif latest_rsi <= 30:
            rsi_zone = "OVERSOLD"
        elif latest_rsi >= 55:
            rsi_zone = "BULLISH"
        elif latest_rsi <= 45:
            rsi_zone = "BEARISH"
        else:
            rsi_zone = "NEUTRAL"

        if latest_macd > 0 and latest_rsi >= 52:
            confluence = "ALIGNED_BULLISH"
            direction = "BULLISH"
        elif latest_macd < 0 and latest_rsi <= 48:
            confluence = "ALIGNED_BEARISH"
            direction = "BEARISH"
        else:
            confluence = "MIXED"
            direction = "MIXED"

        bullish_quality = (
            (25 if latest_macd > 0 else 0)
            + (20 if latest_macd_line > latest_signal_line else 0)
            + (15 if macd_phase == "BULLISH_EXPANSION" else 6 if macd_phase == "BULLISH_FADE" else 0)
            + (20 if latest_rsi >= 52 else 8 if latest_rsi >= 48 else 0)
            + (10 if latest_rsi > latest_rsi_average else 0)
            + (10 if latest_rsi_slope > 0 else 0)
        )
        bearish_quality = (
            (25 if latest_macd < 0 else 0)
            + (20 if latest_macd_line < latest_signal_line else 0)
            + (15 if macd_phase == "BEARISH_EXPANSION" else 6 if macd_phase == "BEARISH_FADE" else 0)
            + (20 if latest_rsi <= 48 else 8 if latest_rsi <= 52 else 0)
            + (10 if latest_rsi < latest_rsi_average else 0)
            + (10 if latest_rsi_slope < 0 else 0)
        )
        if macd_divergence == "BULLISH" or rsi_divergence == "BULLISH":
            bullish_quality += 5
        if macd_divergence == "BEARISH" or rsi_divergence == "BEARISH":
            bearish_quality += 5
        quality_score = min(100, max(bullish_quality, bearish_quality))
        quality_grade = "A" if quality_score >= 80 else "B" if quality_score >= 70 else "C" if quality_score >= 60 else "D"
        opposing_divergence = (
            direction == "BULLISH" and "BEARISH" in {macd_divergence, rsi_divergence}
        ) or (
            direction == "BEARISH" and "BULLISH" in {macd_divergence, rsi_divergence}
        )
        confirmation = (
            "CAUTION_DIVERGENCE" if opposing_divergence
            else f"CONFIRMED_{direction}" if direction != "MIXED" and quality_score >= 60
            else "WAIT"
        )
        macd_acceleration = latest_macd - previous_macd
        rsi_impulse = latest_rsi - previous_rsi
        momentum_state = (
            "BULLISH_EXPANSION"
            if latest_macd > 0 and macd_acceleration > 0 and latest_rsi >= 52 and rsi_impulse >= 0
            else "BEARISH_EXPANSION"
            if latest_macd < 0 and macd_acceleration < 0 and latest_rsi <= 48 and rsi_impulse <= 0
            else "BULLISH_PULLBACK"
            if latest_macd >= 0 and latest_rsi >= 48
            else "BEARISH_PULLBACK"
            if latest_macd <= 0 and latest_rsi <= 52
            else "TRANSITION"
        )

        return {
            "status": "READY",
            "source": "CLOSED_PROVIDER_CANDLES",
            "latest_time": max(int(macd_records[-1]["time"]), int(rsi_records[-1]["time"])),
            "macd": {
                "histogram": round(latest_macd, 6),
                "previous": round(previous_macd, 6),
                "line": round(latest_macd_line, 6),
                "signal": round(latest_signal_line, 6),
                "bias": "BULLISH" if latest_macd > 0 else "BEARISH" if latest_macd < 0 else "NEUTRAL",
                "momentum": "RISING" if latest_macd > previous_macd else "FALLING" if latest_macd < previous_macd else "FLAT",
                "strength": round(macd_strength, 1),
                "acceleration": round(macd_acceleration, 6),
                "phase": macd_phase,
                "cross": macd_cross,
                "divergence": macd_divergence,
            },
            "rsi": {
                "value": round(latest_rsi, 2),
                "previous": round(previous_rsi, 2),
                "average": round(latest_rsi_average, 2),
                "slope": round(latest_rsi_slope, 2),
                "impulse": round(rsi_impulse, 2),
                "zone": rsi_zone,
                "momentum": "RISING" if latest_rsi_slope > 0 else "FALLING" if latest_rsi_slope < 0 else "FLAT",
                "divergence": rsi_divergence,
            },
            "confluence": confluence,
            "direction": direction,
            "momentum_state": momentum_state,
            "confirmation": confirmation,
            "quality_score": quality_score,
            "quality_grade": quality_grade,
            "decision_use": "CONFIRMATION_ONLY",
            "engine_version": "MOMENTUM_V3_8_7_CONFLUENCE",
        }

    @staticmethod
    def _indicator_divergence(
        records: list[Dict[str, Any]],
        indicator_key: str,
        minimum_indicator_gap: float = 0.0,
    ) -> str:
        sample = records[-40:]
        if len(sample) < 20:
            return "NONE"
        midpoint = len(sample) // 2
        previous, current = sample[:midpoint], sample[midpoint:]
        try:
            previous_low = min(previous, key=lambda item: float(item["low"]))
            current_low = min(current, key=lambda item: float(item["low"]))
            previous_high = max(previous, key=lambda item: float(item["high"]))
            current_high = max(current, key=lambda item: float(item["high"]))
            indicator_values = [float(item[indicator_key]) for item in sample]
        except (KeyError, TypeError, ValueError):
            return "NONE"
        indicator_range = max(indicator_values) - min(indicator_values)
        indicator_gap = max(float(minimum_indicator_gap), indicator_range * 0.08)
        price_reference = max(abs(float(previous_low["low"])), abs(float(previous_high["high"])), 1.0)
        price_gap = price_reference * 0.00015
        bullish = (
            float(current_low["low"]) < float(previous_low["low"]) - price_gap
            and float(current_low[indicator_key]) > float(previous_low[indicator_key]) + indicator_gap
        )
        bearish = (
            float(current_high["high"]) > float(previous_high["high"]) + price_gap
            and float(current_high[indicator_key]) < float(previous_high[indicator_key]) - indicator_gap
        )
        return "BULLISH" if bullish else "BEARISH" if bearish else "NONE"

    def _load_csv_candles(self, csv_path: str) -> list[Dict[str, Any]]:
        path = Path(csv_path)
        df = pd.read_csv(path)
        return self._records_from_csv_frame(df, path.name)

    def _records_from_csv_frame(self, df: pd.DataFrame, name: str = "CSV") -> list[Dict[str, Any]]:
        df.columns = [col.strip().lower() for col in df.columns]
        if "timestamp" not in df.columns and "time" in df.columns:
            df = df.rename(columns={"time": "timestamp"})
        required = ["timestamp", "open", "high", "low", "close"]
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(f"{name} missing columns: {', '.join(missing)}")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        valid = (
            (df[["open", "high", "low", "close"]] > 0).all(axis=1)
            & (df["high"] >= df[["open", "close", "low"]].max(axis=1))
            & (df["low"] <= df[["open", "close", "high"]].min(axis=1))
        )
        df = df[valid].drop_duplicates(subset=["timestamp"])
        return [
            {
                "timestamp": row["timestamp"].isoformat(),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
            }
            for _, row in df.iterrows()
        ]
