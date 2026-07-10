from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import pandas as pd

from .indicators import atr, displacement
from .liquidity import crt_range, detect_liquidity
from .smc import detect_fvg, detect_order_blocks, premium_discount_zone, select_best_zone
from .structure import detect_structure
from .xauusd_provider import (
    MIN_ANALYSIS_CANDLES,
    REAL_CSV_HISTORY_SOURCE,
    REAL_RECENT_SOURCES,
    RECENT_CSV_SOURCE,
    SQLiteCandleStore,
    TEST_HISTORY_SOURCES,
    TWELVE_DATA_HISTORY_SOURCE,
    USER_RECENT_CSV_SOURCE,
    WARMUP_SOURCE,
    PRELOADED_SOURCE,
)


class ProAnalysisEngineV3:
    REQUIRED_TIMEFRAMES = ["1D", "4H", "1H", "15M", "5M"]

    def __init__(self, store: SQLiteCandleStore, cache: Any = None):
        self.store = store
        self.cache = cache
        self._active_source_label = "AUTO"
        self._active_sources: set[str] | None = None

    def analyze(self, data_mode: Dict[str, Any], engine_mode: str = "balanced") -> Dict[str, Any]:
        locked_mode = data_mode.get("locked_mode") or data_mode.get("data_mode") or "NO_DATA_MODE"
        frames = self._frames(engine_mode, data_mode)
        counts = {tf: len(df) for tf, df in frames.items()}
        missing = self._missing(counts)
        current_price = self._current_price(frames, data_mode)

        if locked_mode == "BACKEND_OFFLINE_MODE":
            return self._blocked("Backend Offline", locked_mode, data_mode, counts, "Backend is offline. Analysis disabled.")
        if locked_mode == "NO_DATA_MODE":
            return self._blocked("Waiting for Data", locked_mode, data_mode, counts, "No XAUUSD candle history or live price is available.")
        if locked_mode == "LIVE_ONLY_MODE":
            return self._blocked("Live Only", locked_mode, data_mode, counts, "Live price alone cannot produce a professional MTF setup.", current_price)
        if locked_mode == "GAP_WARNING_MODE":
            return self._blocked("Waiting for Data", locked_mode, data_mode, counts, "Fix stale or price-misaligned candle history before analysis.", current_price)
        if missing:
            return self._blocked("Waiting for Data", locked_mode, data_mode, counts, "Required 1D, 4H, 1H, 15M, and 5M candle history is incomplete.", current_price, missing)

        data_integrity = self._cached("data_integrity", "5M", lambda: self._data_integrity_stage(data_mode, counts))
        htf = self._cached("htf_bias", "4H", lambda: self._htf_bias(frames))
        liquidity = self._cached("liquidity_map", "1H", lambda: self._liquidity_map(frames, current_price))
        crt = self._cached("crt_range", "1H", lambda: self._crt_range(frames, current_price))
        poi = self._cached("poi", "15M", lambda: self._poi(frames, htf, crt, current_price))
        confirmation = self._cached("confirmation", "5M", lambda: self._confirmation(frames, htf, poi, current_price))
        score = self._score(locked_mode, data_mode, htf, crt, liquidity, poi, confirmation)
        decision = self._decision(locked_mode, htf, liquidity, poi, confirmation, score)

        direction = "BUY" if htf["bias"] == "Bullish" else "SELL" if htf["bias"] == "Bearish" else "WAIT"
        best_poi = poi.get("best_poi") or {}
        signal = {
            "status": decision,
            "score": score["score"],
            "score_result": score["score_result"],
            "direction": direction,
            "setup_type": best_poi.get("type") or "None",
            "entry_zone": confirmation.get("entry_zone") or best_poi or None,
            "invalidation_level": confirmation.get("invalidation_level") or poi.get("invalidation_level"),
            "target_levels": poi.get("target_levels", []),
            "confirmation_status": "Confirmed" if confirmation.get("confirmation_ready") else "Waiting",
            "final_action": self._final_action(decision, locked_mode),
            "reasons": score["positive_reasons"],
            "warnings": score["penalty_reasons"] + data_mode.get("warnings", []),
        }
        risk_model = self._risk_model(signal, current_price)
        signal["risk_model"] = risk_model
        signal["trade_plan_valid"] = risk_model["status"] == "VALID"
        signal["execution_allowed"] = locked_mode == "REAL_MODE" and "Setup" in decision and risk_model["status"] == "VALID"
        if risk_model["status"] != "VALID" and "Setup" in decision:
            decision = "No Trade"
            signal["status"] = decision
            signal["final_action"] = "Wait. Risk model did not validate the setup."
            signal["warnings"] = signal.get("warnings", []) + risk_model["warnings"]
            signal["execution_allowed"] = False
        workflow = self._workflow(data_integrity, htf, liquidity, crt, poi, confirmation, score, decision)
        if locked_mode == "TEST_MODE":
            signal["test_data_warning"] = "TEST MODE analysis is for validation only. It is not a real market signal."

        return {
            "symbol": "XAUUSD",
            "version": "1.7.2",
            "engine_core_version": "V3",
            "engine_name": "Pro Analysis Engine V3",
            "engine_mode": engine_mode,
            "data_mode": locked_mode,
            "data_mode_label": data_mode.get("data_mode_label"),
            "analysis_ready": True,
            "real_signal_allowed": locked_mode == "REAL_MODE",
            "test_mode_analysis": locked_mode == "TEST_MODE",
            "analysis_data_source": self._active_source_label,
            "analysis_source_filter": sorted(self._active_sources or []),
            "analysis_candle_counts": counts,
            "trade_plan_valid": signal["trade_plan_valid"],
            "execution_allowed": signal["execution_allowed"],
            "current_price": current_price,
            "bias": htf["bias"],
            "market_state": decision,
            "final_decision": decision,
            "data_integrity_check": data_integrity,
            "htf_bias": htf,
            "liquidity_map": liquidity,
            "crt_range": crt,
            "poi_engine": poi,
            "confirmation_engine": confirmation,
            "score_engine": score,
            "risk_model": risk_model,
            "signal": signal,
            "workflow": workflow,
            "cache_status": self.cache.status() if self.cache else {},
            "data_mode_lock": data_mode,
        }

    def cache_snapshot(self) -> Dict[str, Any]:
        if not self.cache:
            return {"entries": 0, "keys": []}
        snap = self.cache.snapshot()
        return {key: value for key, value in snap.items() if str(key).startswith("pro:v3:")}

    def _frames(self, mode: str, data_mode: Optional[Dict[str, Any]] = None) -> Dict[str, pd.DataFrame]:
        limits = {
            "fast": {"5M": 180, "15M": 160, "1H": 140, "4H": 80, "1D": 45},
            "balanced": {"5M": 700, "15M": 500, "1H": 320, "4H": 180, "1D": 90},
            "deep": {"5M": 1200, "15M": 900, "1H": 600, "4H": 320, "1D": 220},
        }.get(mode, {"5M": 700, "15M": 500, "1H": 320, "4H": 180, "1D": 90})
        sources, label = self._analysis_sources(data_mode or {})
        self._active_sources = sources
        self._active_source_label = label
        return {tf: self.store.get_candles_df(tf, limits[tf], sources=sources) for tf in self.REQUIRED_TIMEFRAMES}

    def _analysis_sources(self, data_mode: Dict[str, Any]) -> tuple[set[str] | None, str]:
        locked_mode = data_mode.get("locked_mode") or data_mode.get("data_mode")
        source_counts = data_mode.get("source_counts") or {}
        if locked_mode == "TEST_MODE":
            return set(TEST_HISTORY_SOURCES), "TEST_HISTORY_ONLY"
        if locked_mode == "REAL_MODE":
            priority = [
                (TWELVE_DATA_HISTORY_SOURCE, {TWELVE_DATA_HISTORY_SOURCE}),
                (REAL_CSV_HISTORY_SOURCE, {REAL_CSV_HISTORY_SOURCE}),
                (USER_RECENT_CSV_SOURCE, {USER_RECENT_CSV_SOURCE}),
                (RECENT_CSV_SOURCE, {RECENT_CSV_SOURCE}),
                (WARMUP_SOURCE, {WARMUP_SOURCE}),
                (PRELOADED_SOURCE, {PRELOADED_SOURCE}),
            ]
            for label, sources in priority:
                if self._source_has_required_counts(source_counts, sources):
                    return sources, label
            return set(REAL_RECENT_SOURCES), "REAL_RECENT_MIXED"
        return None, "AUTO_ALL_SOURCES"

    def _source_has_required_counts(self, source_counts: Dict[str, Dict[str, int]], sources: set[str]) -> bool:
        for tf in self.REQUIRED_TIMEFRAMES:
            count = sum(int(source_counts.get(tf, {}).get(source, 0)) for source in sources)
            if count < MIN_ANALYSIS_CANDLES[tf]:
                return False
        return True

    def _missing(self, counts: Dict[str, int]) -> list[Dict[str, Any]]:
        return [
            {"timeframe": tf, "required": MIN_ANALYSIS_CANDLES[tf], "available": counts.get(tf, 0)}
            for tf in self.REQUIRED_TIMEFRAMES
            if counts.get(tf, 0) < MIN_ANALYSIS_CANDLES[tf]
        ]

    def _current_price(self, frames: Dict[str, pd.DataFrame], data_mode: Dict[str, Any]) -> Optional[float]:
        if self._active_source_label not in {"AUTO_ALL_SOURCES", "LIVE_PRICE_BUILDER"} and not frames["5M"].empty:
            return round(float(frames["5M"]["close"].iloc[-1]), 3)
        live_price = data_mode.get("data_integrity", {}).get("latest_live_price")
        if live_price is not None:
            return round(float(live_price), 3)
        if not frames["5M"].empty:
            return round(float(frames["5M"]["close"].iloc[-1]), 3)
        provider_price = data_mode.get("gap_diagnosis", {}).get("live_price")
        return round(float(provider_price), 3) if provider_price is not None else None

    def _cached(self, name: str, dependency_tf: str, builder: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        dependency = self.store.latest_timestamp_for_sources(dependency_tf, self._active_sources) if self._active_sources else self.store.latest_any_timestamp(dependency_tf)
        key = f"pro:v3.1:{self._active_source_label}:{name}:{dependency_tf}"
        if self.cache:
            cached = self.cache.get(key, dependency)
            if cached:
                cached["cache_hit"] = True
                return cached
        value = builder()
        value["cache_hit"] = False
        if self.cache:
            self.cache.set(key, value, dependency)
        return value

    def _data_integrity_stage(self, data_mode: Dict[str, Any], counts: Dict[str, int]) -> Dict[str, Any]:
        return {
            "stage": "Data Integrity Check",
            "status": "READY" if data_mode.get("locked_mode") in {"REAL_MODE", "TEST_MODE"} else "WAITING",
            "confidence": 100 if data_mode.get("locked_mode") in {"REAL_MODE", "TEST_MODE"} else 35,
            "locked_mode": data_mode.get("locked_mode"),
            "candle_source": data_mode.get("candle_source"),
            "analysis_data_source": self._active_source_label,
            "counts": counts,
            "reason": data_mode.get("lock_reason"),
        }

    def _htf_bias(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        d1 = detect_structure(frames["1D"], "1D")
        h4 = detect_structure(frames["4H"], "4H")
        if d1.trend == "bullish" and h4.trend == "bullish":
            bias, confidence = "Bullish", 85
        elif d1.trend == "bearish" and h4.trend == "bearish":
            bias, confidence = "Bearish", 85
        elif d1.trend == "neutral" and h4.trend == "neutral":
            bias, confidence = "Range", 50
        else:
            bias, confidence = "No Clear Bias", 35
        key_high = self._first_number([h4.last_swing_high, d1.last_swing_high])
        key_low = self._first_number([h4.last_swing_low, d1.last_swing_low])
        invalidation = key_low if bias == "Bullish" else key_high if bias == "Bearish" else None
        return {
            "stage": "HTF Bias Engine",
            "bias": bias,
            "confidence": confidence,
            "d1_structure": d1.to_dict(),
            "h4_structure": h4.to_dict(),
            "key_swing_high": key_high,
            "key_swing_low": key_low,
            "invalidation_level": round(float(invalidation), 3) if invalidation is not None else None,
            "reason": f"1D is {d1.trend}; 4H is {h4.trend}.",
        }

    def _liquidity_map(self, frames: Dict[str, pd.DataFrame], current_price: Optional[float]) -> Dict[str, Any]:
        result = detect_liquidity(frames["1H"], frames["1D"])
        buy_levels = result.buy_side_levels
        sell_levels = result.sell_side_levels
        above = [level for level in buy_levels if current_price is not None and level > current_price]
        below = [level for level in sell_levels if current_price is not None and level < current_price]
        session = frames["1H"].tail(24)
        session_high = float(session["high"].max()) if not session.empty else None
        session_low = float(session["low"].min()) if not session.empty else None
        target = min(above) if above else max(below) if below else None
        return {
            "stage": "Liquidity Map Engine",
            "previous_day_high": result.previous_day_high,
            "previous_day_low": result.previous_day_low,
            "equal_highs": buy_levels,
            "equal_lows": sell_levels,
            "buy_side_liquidity": buy_levels,
            "sell_side_liquidity": sell_levels,
            "liquidity_sweep": result.recent_sweep,
            "swept_liquidity": result.swept_level,
            "unswept_liquidity": [level for level in buy_levels + sell_levels if level != result.swept_level],
            "nearest_liquidity_above": min(above) if above else None,
            "nearest_liquidity_below": max(below) if below else None,
            "target_liquidity": target,
            "session_high": session_high,
            "session_low": session_low,
            "confidence": 80 if result.recent_sweep else 45,
            "reason": result.recent_sweep or "Waiting for a clean liquidity sweep.",
        }

    def _crt_range(self, frames: Dict[str, pd.DataFrame], current_price: Optional[float]) -> Dict[str, Any]:
        low, high = crt_range(frames["1H"], 20)
        equilibrium = (low + high) / 2
        width = max(high - low, 0.001)
        location = "Discount" if current_price is not None and current_price < equilibrium else "Premium" if current_price is not None else "Unknown"
        last_ranges = (frames["1H"].tail(20)["high"] - frames["1H"].tail(20)["low"]).abs()
        compression = float(last_ranges.tail(5).mean()) < float(last_ranges.mean()) * 0.75 if len(last_ranges) >= 6 else False
        return {
            "stage": "CRT Range Engine",
            "crt_high": round(high, 3),
            "crt_low": round(low, 3),
            "equilibrium": round(equilibrium, 3),
            "premium_zone": {"low": round(equilibrium, 3), "high": round(high, 3)},
            "discount_zone": {"low": round(low, 3), "high": round(equilibrium, 3)},
            "current_price_location": location,
            "premium_discount_status": location,
            "range_status": "Compression" if compression else "Expansion" if width > 0 else "Range",
            "suggested_waiting_area": "Discount" if location == "Premium" else "Premium",
            "confidence": 70,
        }

    def _poi(self, frames: Dict[str, pd.DataFrame], htf: Dict[str, Any], crt: Dict[str, Any], current_price: Optional[float]) -> Dict[str, Any]:
        direction = "bullish" if htf["bias"] == "Bullish" else "bearish" if htf["bias"] == "Bearish" else "neutral"
        fvg = detect_fvg(frames["15M"], "15M", 10)
        ob = detect_order_blocks(frames["15M"], "15M", 10)
        discount, premium, buy_ote, sell_ote = premium_discount_zone(crt["crt_low"], crt["crt_high"], "1H")
        zones = fvg + ob
        best = select_best_zone(zones, direction, current_price or float(frames["15M"]["close"].iloc[-1])) if direction != "neutral" else None
        ote = buy_ote if direction == "bullish" else sell_ote if direction == "bearish" else None
        best_payload = best.to_dict() if best else None
        if not best_payload and ote:
            best_payload = ote.to_dict()
        invalidation = None
        if best_payload:
            invalidation = best_payload["low"] if direction == "bullish" else best_payload["high"]
        target_levels = self._targets(direction, current_price, crt, invalidation)
        pd_aligned = (
            direction == "bullish" and crt["current_price_location"] == "Discount"
        ) or (
            direction == "bearish" and crt["current_price_location"] == "Premium"
        )
        return {
            "stage": "POI Engine",
            "fair_value_gaps": [zone.to_dict() for zone in fvg],
            "order_blocks": [zone.to_dict() for zone in ob],
            "breaker_blocks": [],
            "mitigation_blocks": [],
            "ote_zone": ote.to_dict() if ote else None,
            "buy_poi_zone": self._zone_payload(best, "bullish"),
            "sell_poi_zone": self._zone_payload(best, "bearish"),
            "best_poi": best_payload,
            "premium_discount_alignment": pd_aligned,
            "invalidation_level": round(float(invalidation), 3) if invalidation is not None else None,
            "target_levels": target_levels,
            "confidence": 75 if best_payload else 35,
            "reason": "15M FVG/Order Block or OTE zone found." if best_payload else "Waiting for 15M FVG/Order Block.",
        }

    def _confirmation(self, frames: Dict[str, pd.DataFrame], htf: Dict[str, Any], poi: Dict[str, Any], current_price: Optional[float]) -> Dict[str, Any]:
        structure = detect_structure(frames["5M"], "5M")
        expected = "bullish" if htf["bias"] == "Bullish" else "bearish" if htf["bias"] == "Bearish" else None
        disp = displacement(frames["5M"], 14, 1.2)
        last_displacement = bool(disp.iloc[-1]) if len(disp) else False
        liquidity = detect_liquidity(frames["5M"], None)
        best = poi.get("best_poi") or {}
        in_poi = bool(best and current_price is not None and best.get("low") <= current_price <= best.get("high"))
        candle = frames["5M"].iloc[-1]
        body = abs(float(candle["close"] - candle["open"]))
        wick = float(candle["high"] - candle["low"])
        rejection = wick > 0 and body / wick < 0.45
        bos_choch = expected and (structure.bos == expected or structure.choch == expected)
        ready = bool(bos_choch and (last_displacement or in_poi or rejection))
        confirmation_type = (
            "BOS/CHOCH + Displacement" if bos_choch and last_displacement else
            "BOS/CHOCH + POI Retest" if bos_choch and in_poi else
            "BOS/CHOCH + Rejection" if bos_choch and rejection else
            "Waiting"
        )
        entry_zone = {"low": best.get("low"), "high": best.get("high")} if best else None
        return {
            "stage": "Confirmation Engine",
            "confirmation_ready": ready,
            "confirmation_type": confirmation_type,
            "confirmation_candle_time": str(frames["5M"].index[-1]) if not frames["5M"].empty else None,
            "bos": structure.bos,
            "choch": structure.choch,
            "displacement_candle": last_displacement,
            "liquidity_sweep": liquidity.recent_sweep,
            "fvg_retest": in_poi and best.get("type") == "FVG",
            "ob_retest": in_poi and best.get("type") == "OrderBlock",
            "rejection_candle": rejection,
            "entry_zone": entry_zone,
            "invalidation_level": poi.get("invalidation_level"),
            "confidence": 85 if ready else 40,
            "reason": confirmation_type,
        }

    def _score(self, locked_mode: str, data_mode: Dict[str, Any], htf: Dict[str, Any], crt: Dict[str, Any], liquidity: Dict[str, Any], poi: Dict[str, Any], confirmation: Dict[str, Any]) -> Dict[str, Any]:
        score = 0
        positives: list[str] = []
        penalties: list[str] = []
        if htf["bias"] in {"Bullish", "Bearish"}:
            score += 20
            positives.append("HTF bias aligned +20")
        else:
            score -= 25
            penalties.append("HTF conflict -25")
        correct_pd = (
            htf["bias"] == "Bullish" and crt["premium_discount_status"] == "Discount"
        ) or (
            htf["bias"] == "Bearish" and crt["premium_discount_status"] == "Premium"
        )
        if correct_pd:
            score += 15
            positives.append("Correct premium/discount +15")
        if liquidity.get("liquidity_sweep"):
            score += 20
            positives.append("Liquidity sweep +20")
        else:
            score -= 20
            penalties.append("No liquidity sweep -20")
        if poi.get("best_poi") and poi.get("best_poi", {}).get("type") in {"FVG", "OrderBlock", "OTE"}:
            score += 15
            positives.append("Valid 15M POI +15")
        else:
            score -= 15
            penalties.append("No POI -15")
        if poi.get("ote_zone") and poi.get("premium_discount_alignment"):
            score += 10
            positives.append("OTE confluence +10")
        if confirmation.get("bos") or confirmation.get("choch"):
            score += 20
            positives.append("5M BOS/CHOCH confirmation +20")
        else:
            score -= 20
            penalties.append("No confirmation -20")
        if locked_mode == "TEST_MODE":
            penalties.append("TEST MODE: not a real signal")
        if locked_mode == "LIVE_ONLY_MODE":
            penalties.append("LIVE ONLY: candle history missing")
        if locked_mode == "GAP_WARNING_MODE" or data_mode.get("data_integrity", {}).get("gap_detected"):
            score -= 40
            penalties.append("Stale/gapped data -40")
        if self._active_source_label in {"AUTO_ALL_SOURCES", "REAL_RECENT_MIXED"}:
            score -= 10
            penalties.append("Mixed candle source -10")
        final_score = max(0, min(100, score))
        return {
            "stage": "Score Engine",
            "score": final_score,
            "score_result": self._score_result(final_score),
            "positive_reasons": positives,
            "penalty_reasons": penalties,
        }

    def _decision(self, locked_mode: str, htf: Dict[str, Any], liquidity: Dict[str, Any], poi: Dict[str, Any], confirmation: Dict[str, Any], score: Dict[str, Any]) -> str:
        if locked_mode == "TEST_MODE":
            return "Test Mode Analysis"
        if locked_mode == "LIVE_ONLY_MODE":
            return "Live Only"
        if locked_mode == "BACKEND_OFFLINE_MODE":
            return "Backend Offline"
        if locked_mode in {"NO_DATA_MODE", "GAP_WARNING_MODE"}:
            return "Waiting for Data"
        if htf["bias"] not in {"Bullish", "Bearish"}:
            return "No Trade"
        if not liquidity.get("liquidity_sweep"):
            return "Waiting for Liquidity Sweep"
        if not poi.get("best_poi"):
            return "Waiting for Pullback to POI"
        if not confirmation.get("confirmation_ready"):
            return "Waiting for 5M Confirmation"
        side = "Buy" if htf["bias"] == "Bullish" else "Sell"
        if score["score"] >= 85:
            return f"High Quality {side} Setup"
        if score["score"] >= 75:
            return f"Valid {side} Setup"
        return "No Trade"

    def _workflow(self, data_integrity: Dict[str, Any], htf: Dict[str, Any], liquidity: Dict[str, Any], crt: Dict[str, Any], poi: Dict[str, Any], confirmation: Dict[str, Any], score: Dict[str, Any], decision: str) -> list[Dict[str, Any]]:
        return [
            self._stage("Data Integrity Check", data_integrity["status"], data_integrity["confidence"], data_integrity["reason"], "All", []),
            self._stage("HTF Bias Engine", "VALID" if htf["bias"] in {"Bullish", "Bearish"} else "WAITING", htf["confidence"], htf["reason"], "1D/4H", []),
            self._stage("Liquidity Map Engine", "VALID" if liquidity.get("liquidity_sweep") else "WAITING", liquidity["confidence"], liquidity["reason"], "1H", []),
            self._stage("CRT Range Engine", "READY", crt["confidence"], f"Price is in {crt['current_price_location']}; range is {crt['range_status']}.", "1H", []),
            self._stage("POI Engine", "VALID" if poi.get("best_poi") else "WAITING", poi["confidence"], poi["reason"], "15M", [poi["best_poi"]] if poi.get("best_poi") else []),
            self._stage("Confirmation Engine", "VALID" if confirmation.get("confirmation_ready") else "WAITING", confirmation["confidence"], confirmation["reason"], "5M", []),
            self._stage("Score Engine", "VALID" if score["score"] >= 75 else "WEAK", score["score"], score["score_result"], "All", []),
            self._stage("Final Decision Engine", "VALID" if "Setup" in decision else "WAITING" if decision.startswith("Waiting") else "INFO", score["score"], decision, "All", []),
        ]

    def _blocked(self, decision: str, locked_mode: str, data_mode: Dict[str, Any], counts: Dict[str, int], reason: str, current_price: Optional[float] = None, missing: Optional[list[Dict[str, Any]]] = None) -> Dict[str, Any]:
        workflow = [
            self._stage("Data Integrity Check", "WAITING", 0, reason, "All", []),
            self._stage("Final Decision Engine", "WAITING", 0, decision, "All", []),
        ]
        return {
            "symbol": "XAUUSD",
            "version": "1.7.2",
            "engine_core_version": "V3",
            "engine_name": "Pro Analysis Engine V3",
            "data_mode": locked_mode,
            "data_mode_label": data_mode.get("data_mode_label"),
            "analysis_ready": False,
            "real_signal_allowed": False,
            "current_price": current_price,
            "bias": "No Clear Bias",
            "market_state": decision,
            "final_decision": decision,
            "error": reason,
            "missing_history": missing or [],
            "candle_counts": counts,
            "signal": {
                "status": decision,
                "score": 0,
                "score_result": "Waiting",
                "final_action": reason,
                "direction": "WAIT",
                "warnings": data_mode.get("warnings", []),
            },
            "workflow": workflow,
            "data_mode_lock": data_mode,
        }

    def _stage(self, name: str, status: str, confidence: int, reason: str, timeframe: str, detected_zones: list[Any]) -> Dict[str, Any]:
        return {
            "name": name,
            "status": status,
            "confidence": int(confidence),
            "reason": reason,
            "timeframe": timeframe,
            "detected_zones": [zone for zone in detected_zones if zone],
            "invalidation_condition": "Wait for the next valid XAUUSD data state.",
        }

    def _score_result(self, score: int) -> str:
        if score >= 85:
            return "High Quality Setup"
        if score >= 75:
            return "Waiting Confirmation"
        if score >= 60:
            return "Weak Setup"
        return "No Trade"

    def _final_action(self, decision: str, locked_mode: str) -> str:
        if locked_mode == "TEST_MODE":
            return "Review the test workflow only. Do not treat this as a real signal."
        if decision.startswith("High Quality") or decision.startswith("Valid"):
            return decision
        return "Wait. Do not force an entry."

    def _targets(self, direction: str, current_price: Optional[float], crt: Dict[str, Any], invalidation: Optional[float]) -> list[float]:
        if current_price is None:
            return []
        if direction == "bullish":
            risk = max(current_price - float(invalidation or crt["crt_low"]), 0.5)
            return [round(crt["equilibrium"], 3), round(crt["crt_high"], 3), round(current_price + risk * 2, 3)]
        if direction == "bearish":
            risk = max(float(invalidation or crt["crt_high"]) - current_price, 0.5)
            return [round(crt["equilibrium"], 3), round(crt["crt_low"], 3), round(current_price - risk * 2, 3)]
        return []

    def _risk_model(self, signal: Dict[str, Any], current_price: Optional[float]) -> Dict[str, Any]:
        warnings: list[str] = []
        entry = signal.get("entry_zone") or {}
        low = entry.get("low")
        high = entry.get("high")
        invalidation = signal.get("invalidation_level")
        targets = signal.get("target_levels") or []
        direction = signal.get("direction")
        if current_price is None or low is None or high is None or invalidation is None or not targets or direction not in {"BUY", "SELL"}:
            return {"status": "WAITING", "rr": None, "entry": None, "risk": None, "reward": None, "warnings": ["Risk model waiting for entry, invalidation, and target."]}
        entry_price = (float(low) + float(high)) / 2
        target = float(targets[0])
        risk = abs(entry_price - float(invalidation))
        reward = abs(target - entry_price)
        if risk <= 0:
            warnings.append("Invalid risk distance.")
        if direction == "BUY" and not (float(invalidation) < entry_price < target):
            warnings.append("BUY plan must have stop below entry and target above entry.")
        if direction == "SELL" and not (float(invalidation) > entry_price > target):
            warnings.append("SELL plan must have stop above entry and target below entry.")
        rr = reward / risk if risk > 0 else 0
        if rr < 1.2:
            warnings.append("Risk/reward below 1.2R.")
        return {
            "status": "VALID" if not warnings else "WAITING",
            "rr": round(rr, 2) if risk > 0 else None,
            "entry": round(entry_price, 3),
            "risk": round(risk, 3),
            "reward": round(reward, 3),
            "warnings": warnings,
        }

    def _zone_payload(self, zone: Any, direction: str) -> Optional[Dict[str, Any]]:
        if zone and zone.direction == direction:
            return zone.to_dict()
        return None

    def _first_number(self, values: list[Any]) -> Optional[float]:
        for value in values:
            if value is not None and pd.notna(value):
                return round(float(value), 3)
        return None
