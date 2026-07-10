from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from .data_loader import candles_to_records
from .xauusd_provider import (
    CSV_SOURCE,
    HISTORY_GAP_WARNING,
    ARCHIVED_STALE_SOURCE,
    LIVE_BUILDER_SOURCE,
    LIVE_SOURCE,
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
REAL_HISTORY_SOURCES = {PRELOADED_SOURCE, CSV_SOURCE, WARMUP_SOURCE, RECENT_CSV_SOURCE, USER_RECENT_CSV_SOURCE, REAL_CSV_HISTORY_SOURCE, TWELVE_DATA_HISTORY_SOURCE}
HISTORY_SOURCES = REAL_HISTORY_SOURCES | TEST_HISTORY_SOURCES
ALIGNMENT_MAX_AGE_MINUTES = {"1M": 3, "5M": 15, "15M": 45, "1H": 180, "4H": 480, "1D": 4320}


class CandleHistoryAlignmentEngine:
    PRICE_WARN_PERCENT = 0.15
    PRICE_GAP_PERCENT = 0.40
    PRICE_CRITICAL_PERCENT = 1.00
    ABS_WARN_GAP = 5.0
    ABS_PRICE_GAP = 10.0
    ABS_CRITICAL_GAP = 20.0

    def __init__(self, store: SQLiteCandleStore):
        self.store = store

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

        if history.empty:
            status = "LIVE_ONLY" if live_price is not None or not live.empty else "NO_HISTORY"
            return self._payload(tf, status, live_price, latest_live_time, None, None, None, None, source, source_group)

        price_gap = abs(live_price - latest_history_close) if live_price is not None and latest_history_close is not None else None
        price_gap_percent = (price_gap / abs(live_price) * 100) if price_gap is not None and live_price else None
        price_status = self._price_status(price_gap, price_gap_percent)
        time_status = self._time_status(tf, latest_history_time, latest_live_time)

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
        aligned_test = self._source_slice(df, {TEST_HISTORY_LIVE_ANCHORED_SOURCE})
        if self._candidate_is_aligned(aligned_test, timeframe, live_price, live_time):
            return aligned_test
        priority = [
            {TWELVE_DATA_HISTORY_SOURCE},
            {REAL_CSV_HISTORY_SOURCE},
            {USER_RECENT_CSV_SOURCE},
            {RECENT_CSV_SOURCE},
            {CSV_SOURCE, WARMUP_SOURCE, PRELOADED_SOURCE},
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
        price_gap = abs(live_price - close)
        price_gap_percent = price_gap / abs(live_price) * 100 if live_price else 999
        if price_gap > self.ABS_WARN_GAP or price_gap_percent > self.PRICE_WARN_PERCENT:
            return False
        return self._time_status(timeframe, history_time, live_time) == "ALIGNED"

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
    def __init__(self, store: SQLiteCandleStore):
        self.store = store
        self.warmup = RecentHistoryWarmupService(store)
        self.alignment = CandleHistoryAlignmentEngine(store)

    def data_integrity(self, timeframe: str = "15M", limit: int = 300) -> Dict[str, Any]:
        return self._build(timeframe, limit)["data_integrity"]

    def chart_data(self, timeframe: str = "15M", limit: int = 300) -> Dict[str, Any]:
        return self._build(timeframe, limit)

    def history_alignment(self, timeframe: str = "15M", limit: int = 1000) -> Dict[str, Any]:
        return self.alignment.check(timeframe, limit)

    def overlays(self, timeframe: str = "15M", limit: int = 300) -> Dict[str, Any]:
        built = self._build(timeframe, limit)
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
        df = built["frames"]["analysis"]
        data_mode = built["data_integrity"].get("data_mode")
        if data_mode == "GAP_WARNING":
            return {
                "symbol": "XAUUSD",
                "timeframe": built["timeframe"],
                "status": "FIX_GAP_REQUIRED",
                "message": "Fix gap required",
                "indicator_panels": {
                    "boys_selling": [],
                    "bearishness": [],
                    "market_pressure_score": {"bullish": 0, "bearish": 0, "neutral": 100},
                },
                "data_integrity": built["data_integrity"],
            }
        if data_mode == "LIVE_ONLY":
            return {
                "symbol": "XAUUSD",
                "timeframe": built["timeframe"],
                "status": "WAITING_FOR_HISTORY",
                "message": "Waiting for candle history",
                "indicator_panels": {
                    "boys_selling": [],
                    "bearishness": [],
                    "market_pressure_score": {"bullish": 0, "bearish": 0, "neutral": 100},
                },
                "data_integrity": built["data_integrity"],
            }
        if df.empty or len(df) < 5:
            return {
                "symbol": "XAUUSD",
                "timeframe": built["timeframe"],
                "status": "WAITING_FOR_HISTORY",
                "message": "Waiting for candle history",
                "indicator_panels": {
                    "boys_selling": [],
                    "bearishness": [],
                    "market_pressure_score": {"bullish": 0, "bearish": 0, "neutral": 100},
                },
                "data_integrity": built["data_integrity"],
            }
        boys_selling, bearishness, pressure = self._indicator_data(df)
        return {
            "symbol": "XAUUSD",
            "timeframe": built["timeframe"],
            "status": "NO_CANDLES" if df.empty else "READY",
            "badge": "TEST DATA" if built["data_integrity"].get("test_data_present") else None,
            "indicator_panels": {
                "boys_selling": boys_selling,
                "bearishness": bearishness,
                "market_pressure_score": pressure,
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
        real_history = self._source_slice(cleaned, REAL_HISTORY_SOURCES)
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
        real_recent_history_present = bool(has_real_history and (recent_csv_present or twelve_data_present or self.store.has_source(tf, PRELOADED_SOURCE) or self.store.has_source(tf, WARMUP_SOURCE)))
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
            "test_data_present": test_data_present,
            "live_anchored_test_present": self.store.has_source(tf, TEST_HISTORY_LIVE_ANCHORED_SOURCE),
            "recent_csv_history_present": recent_csv_present,
            "twelve_data_history_present": twelve_data_present,
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
            warnings.append(f"{abnormal_count} abnormal candles flagged.")
            work = work[~abnormal_mask]
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

    def _indicator_data(self, df: pd.DataFrame) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]], Dict[str, float]]:
        if df.empty:
            return [], [], {"bullish": 0, "bearish": 0, "neutral": 100}
        boys_selling: list[Dict[str, Any]] = []
        bearishness: list[Dict[str, Any]] = []
        bullish_total = 0.0
        bearish_total = 0.0
        frame = df.tail(120)
        for time, row in frame.iterrows():
            timestamp = pd.Timestamp(time)
            if timestamp.tzinfo is not None:
                timestamp = timestamp.tz_convert("UTC").tz_localize(None)
            rng = max(float(row["high"] - row["low"]), 0.001)
            body = float(row["close"] - row["open"])
            momentum = body / rng
            value = momentum * 5
            bullish_total += max(value, 0)
            bearish_total += abs(min(value, 0))
            boys_selling.append({
                "time": int(timestamp.timestamp()),
                "value": round(value, 3),
                "color": "green" if value >= 0 else "red",
            })
            sell_pressure = max(float(row["open"] - row["close"]), 0.0) / rng
            bearishness.append({"time": int(timestamp.timestamp()), "value": round(-80 - sell_pressure * 260, 3)})
        total = bullish_total + bearish_total
        if total <= 0:
            pressure = {"bullish": 0, "bearish": 0, "neutral": 100}
        else:
            bullish = bullish_total / total * 100
            bearish = bearish_total / total * 100
            pressure = {"bullish": round(bullish, 2), "bearish": round(bearish, 2), "neutral": round(max(0, 100 - bullish - bearish), 2)}
        return boys_selling, bearishness, pressure

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
