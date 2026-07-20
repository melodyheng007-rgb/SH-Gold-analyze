from __future__ import annotations

from typing import Any, Dict, Optional

from .xauusd_provider import (
    LIVE_SOURCES,
    MIN_ANALYSIS_CANDLES,
    REAL_RECENT_SOURCES,
    REAL_CSV_HISTORY_SOURCE,
    SUPPORTED_TIMEFRAMES,
    TEST_HISTORY_LIVE_ANCHORED_SOURCE,
    TEST_HISTORY_SOURCES,
    ProviderSettings,
    SQLiteCandleStore,
)


class DataModeLockService:
    """Single truth table for chart, HUD, and analysis mode."""

    MODES = {
        "REAL_MODE",
        "TEST_MODE",
        "LIVE_ONLY_MODE",
        "NO_DATA_MODE",
        "GAP_WARNING_MODE",
        "BACKEND_OFFLINE_MODE",
    }

    def __init__(self, store: SQLiteCandleStore, settings: ProviderSettings, symbol: str = "XAUUSD"):
        self.store = store
        self.settings = settings
        self.symbol = str(symbol or "XAUUSD").upper()

    def locked_mode(
        self,
        integrity: Optional[Dict[str, Any]] = None,
        diagnosis: Optional[Dict[str, Any]] = None,
        backend_online: bool = True,
    ) -> Dict[str, Any]:
        provider_status = self.store.load_status().to_dict() if backend_online else {}
        counts = self.store.counts() if backend_online else {}
        source_counts = self.store.source_counts() if backend_online else {}
        selected_mode = self.settings.data_mode() if backend_online else "BACKEND_OFFLINE"
        source_summary = self._source_summary(source_counts)
        has_live_price = provider_status.get("latest_price") is not None
        has_test = self._has_any_source(source_counts, TEST_HISTORY_SOURCES)
        has_real = self._has_any_source(source_counts, REAL_RECENT_SOURCES)
        has_live_candles = self._has_any_source(source_counts, LIVE_SOURCES)
        has_any_candles = any(counts.values())
        enough = self._has_enough_analysis_history(counts)
        diagnosis_status = (diagnosis or {}).get("status")
        alignment_status = (integrity or {}).get("alignment_status") or ((integrity or {}).get("alignment") or {}).get("alignment_status")
        alignment_allowed = (integrity or {}).get("analysis_allowed")
        gap_statuses = {"WARNING_PRICE_GAP", "PRICE_GAP", "CRITICAL_PRICE_GAP", "PRICE_AND_TIME_GAP", "TIME_GAP", "STALE_HISTORY", "FUTURE_HISTORY"}
        active_gap = (
            bool((integrity or {}).get("gap_detected"))
            or diagnosis_status in {"PRICE_GAP", "STALE_HISTORY", "CRITICAL_GAP", "CRITICAL_PRICE_GAP", "PRICE_AND_TIME_GAP"}
            or alignment_status in gap_statuses
            or alignment_allowed is False
        )

        if not backend_online:
            mode = "BACKEND_OFFLINE_MODE"
            reason = "Frontend cannot connect to backend."
        elif selected_mode == "TEST" and has_test and not active_gap:
            mode = "TEST_MODE"
            reason = "TEST mode is selected and TEST_HISTORY candles are loaded."
        elif has_real and has_live_price and not active_gap:
            mode = "REAL_MODE"
            reason = "Real recent candle history exists, latest live price exists, and no critical gap is active."
        elif (has_real or has_any_candles) and active_gap:
            mode = "GAP_WARNING_MODE"
            reason = f"Historical candles and latest live {self.symbol} price are not aligned."
        elif has_test:
            mode = "TEST_MODE"
            reason = "Only TEST_HISTORY candles are available. Test data is not real market history."
        elif has_live_price or has_live_candles:
            mode = "LIVE_ONLY_MODE"
            reason = "Only live price/building live candles are available. Full candle history is missing."
        else:
            mode = "NO_DATA_MODE"
            reason = "No usable live price or candle history is available."

        label = self._label(mode)
        analysis_ready = mode in {"REAL_MODE", "TEST_MODE"} and enough
        real_signal_allowed = mode == "REAL_MODE" and enough
        full_analysis_ready = real_signal_allowed
        if mode == "TEST_MODE":
            analysis_state = "Test Mode Analysis" if enough else "Waiting for Data"
        elif mode == "REAL_MODE":
            analysis_state = "Full Analysis Ready" if enough else "Waiting for Data"
        elif mode == "LIVE_ONLY_MODE":
            analysis_state = "Live Only"
        elif mode == "GAP_WARNING_MODE":
            analysis_state = "Waiting for Recent History"
        elif mode == "BACKEND_OFFLINE_MODE":
            analysis_state = "Backend Offline"
        else:
            analysis_state = "Waiting for Data"

        return {
            "symbol": self.symbol,
            "locked_mode": mode,
            "mode": mode,
            "data_mode": mode,
            "data_mode_label": label,
            "description": reason,
            "lock_reason": reason,
            "selected_data_mode": selected_mode,
            "selected_mode_ignored": selected_mode not in {"AUTO", mode.replace("_MODE", "")} and mode != "BACKEND_OFFLINE_MODE",
            "backend_status": "ONLINE" if backend_online else "BACKEND_OFFLINE",
            "provider_status": provider_status.get("status") if backend_online else "OFFLINE",
            "provider_name": provider_status.get("provider_name") if backend_online else "-",
            "candle_source": source_summary["primary_source"],
            "candle_source_detail": source_summary,
            "chart_ready": bool(has_any_candles or has_live_price) and mode != "BACKEND_OFFLINE_MODE",
            "analysis_ready": bool(analysis_ready),
            "full_analysis_ready": bool(full_analysis_ready),
            "real_signal_allowed": bool(real_signal_allowed),
            "can_analyze": bool(analysis_ready) and mode != "BACKEND_OFFLINE_MODE",
            "can_refresh": mode != "BACKEND_OFFLINE_MODE",
            "can_smart_setup": mode != "BACKEND_OFFLINE_MODE",
            "analysis_state": analysis_state,
            "is_real_mode": mode == "REAL_MODE",
            "is_test_mode": mode == "TEST_MODE",
            "is_live_only_mode": mode == "LIVE_ONLY_MODE",
            "is_gap_warning_mode": mode == "GAP_WARNING_MODE",
            "is_no_data_mode": mode == "NO_DATA_MODE",
            "is_backend_offline_mode": mode == "BACKEND_OFFLINE_MODE",
            "counts": counts,
            "source_counts": source_counts,
            "minimum_required": MIN_ANALYSIS_CANDLES,
            "data_integrity": integrity or {},
            "gap_diagnosis": diagnosis or {},
            "truth_table": self.truth_table(),
            "warnings": self._warnings(mode, enough, active_gap),
        }

    def offline_mode(self) -> Dict[str, Any]:
        return self.locked_mode(backend_online=False)

    def truth_table(self) -> Dict[str, str]:
        return {
            "REAL_MODE": "Real recent candles + latest live price + no active gap. Real analysis can run.",
            "TEST_MODE": "TEST_HISTORY source is present. Analysis may run as clearly marked test analysis only.",
            "LIVE_ONLY_MODE": "Only latest live price/building candles exist. Full analysis disabled.",
            "GAP_WARNING_MODE": "History exists but is stale or price-misaligned. Full analysis disabled.",
            "NO_DATA_MODE": "No candles and no live price. Chart empty state.",
            "BACKEND_OFFLINE_MODE": "Frontend cannot reach backend. Actions disabled and last chart is stale.",
        }

    def _has_any_source(self, source_counts: Dict[str, Dict[str, int]], sources: set[str]) -> bool:
        return any(count > 0 for counts in source_counts.values() for source, count in counts.items() if source in sources)

    def _has_enough_analysis_history(self, counts: Dict[str, int]) -> bool:
        return all(counts.get(tf, 0) >= MIN_ANALYSIS_CANDLES[tf] for tf in ["5M", "15M", "1H", "4H", "1D"])

    def _source_summary(self, source_counts: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        totals: Dict[str, int] = {}
        for counts in source_counts.values():
            for source, count in counts.items():
                totals[source] = totals.get(source, 0) + int(count)
        if totals.get(REAL_CSV_HISTORY_SOURCE):
            primary = REAL_CSV_HISTORY_SOURCE
        elif any(source in totals for source in REAL_RECENT_SOURCES):
            primary = "REAL_RECENT_HISTORY"
        elif any(source in totals for source in TEST_HISTORY_SOURCES):
            primary = TEST_HISTORY_LIVE_ANCHORED_SOURCE if totals.get(TEST_HISTORY_LIVE_ANCHORED_SOURCE) else "TEST_HISTORY"
        elif any(source in totals for source in LIVE_SOURCES):
            primary = "LIVE_PRICE_BUILDER"
        else:
            primary = "NO_CANDLE_SOURCE"
        return {"primary_source": primary, "totals": totals}

    def _label(self, mode: str) -> str:
        return {
            "REAL_MODE": "REAL",
            "TEST_MODE": "TEST MODE",
            "LIVE_ONLY_MODE": "LIVE ONLY",
            "NO_DATA_MODE": "NO DATA",
            "GAP_WARNING_MODE": "GAP WARNING",
            "BACKEND_OFFLINE_MODE": "BACKEND OFFLINE",
        }[mode]

    def _warnings(self, mode: str, enough_history: bool, active_gap: bool) -> list[str]:
        warnings: list[str] = []
        if mode == "TEST_MODE":
            warnings.append("TEST HISTORY is not real market history.")
        if mode == "LIVE_ONLY_MODE":
            warnings.append("Live price alone is not candle history.")
        if active_gap and mode == "GAP_WARNING_MODE":
            warnings.append("Fix data gap before real analysis.")
        if mode in {"REAL_MODE", "TEST_MODE"} and not enough_history:
            warnings.append("Required 1D, 4H, 1H, 15M, and 5M candle history is incomplete.")
        if mode == "BACKEND_OFFLINE_MODE":
            warnings.append("Backend offline. Do not show provider as live.")
        return warnings
