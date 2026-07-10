from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from .pro_analysis import ProAnalysisEngineV3


class InstitutionalAnalysisEngineV4(ProAnalysisEngineV3):
    def cache_snapshot(self) -> Dict[str, Any]:
        if not self.cache:
            return {"entries": 0, "keys": []}
        snap = self.cache.snapshot()
        return {key: value for key, value in snap.items() if str(key).startswith("pro:v4:")}

    def analyze(self, data_mode: Dict[str, Any], engine_mode: str = "balanced") -> Dict[str, Any]:
        result = super().analyze(data_mode, engine_mode)
        result.update({
            "version": "1.7.2",
            "engine_core_version": "V4",
            "engine_name": "Institutional Analysis Engine V4",
            "project_name": "SH Gold Analyzer V1.7.2",
        })
        if "score_engine" in result:
            result["smart_score_v2"] = result["score_engine"]
        if "workflow" in result:
            result["institutional_workflow"] = result["workflow"]
        explanation = self.analysis_explanation(result)
        result["analysis_explanation"] = explanation
        if result.get("signal"):
            result["signal"]["explanation"] = explanation.get("summary")
            result["signal"]["data_mode_warning"] = explanation.get("data_mode_warning")
        return result

    def analysis_explanation(self, result: Dict[str, Any]) -> Dict[str, Any]:
        mode = result.get("data_mode")
        direction = result.get("signal", {}).get("direction") or "WAIT"
        decision = result.get("final_decision") or result.get("market_state") or "Waiting for Data"
        bias = result.get("htf_bias", {}).get("bias") or result.get("bias") or "No Clear Bias"
        crt = result.get("crt_range", {})
        location = crt.get("current_price_location") or "Unknown"
        liquidity = result.get("liquidity_map", {})
        poi = result.get("poi_engine", {})
        confirmation = result.get("confirmation_engine", {})
        score = result.get("score_engine", {}).get("score", 0)
        warnings = result.get("data_mode_lock", {}).get("warnings", []) or result.get("signal", {}).get("warnings", [])
        if mode == "TEST_MODE":
            mode_warning = "TEST MODE: this is development analysis only, not a real market signal."
        elif mode == "LIVE_ONLY_MODE":
            mode_warning = "LIVE ONLY: full institutional setup is disabled until candle history exists."
        elif mode == "GAP_WARNING_MODE":
            mode_warning = "GAP WARNING: fix stale or misaligned history before real analysis."
        elif mode == "REAL_MODE":
            mode_warning = None
        else:
            mode_warning = "Waiting for complete XAUUSD data."

        if decision == "Test Mode Analysis":
            summary = f"XAUUSD test history is loaded. The engine sees {bias} HTF bias and price in {location}, but the output is test-only."
        elif decision == "Live Only":
            summary = "XAUUSD live price is available, but full 1D/4H/1H/15M/5M candle history is not ready."
        elif decision.startswith("Waiting"):
            summary = f"XAUUSD is {bias} on HTF. Price is in {location}, so the engine is {decision.lower()}."
        elif "Setup" in decision:
            summary = f"XAUUSD has a {decision.lower()} with score {score}. Direction is {direction} after POI and 5M confirmation checks."
        elif decision == "No Trade":
            summary = f"XAUUSD has no real setup. HTF bias is {bias}, liquidity sweep is {bool(liquidity.get('liquidity_sweep'))}, POI ready is {bool(poi.get('best_poi'))}, and 5M confirmation is {bool(confirmation.get('confirmation_ready'))}."
        else:
            summary = result.get("error") or "XAUUSD analysis is waiting for usable candle data."

        return {
            "direction": direction,
            "summary": summary,
            "reason": result.get("signal", {}).get("final_action") or decision,
            "waiting_condition": self._waiting_condition(decision, liquidity, poi, confirmation),
            "invalidation_condition": self._invalidation_condition(result),
            "next_trigger": self._next_trigger(decision),
            "confidence": result.get("score_engine", {}).get("score", result.get("signal", {}).get("score", 0)),
            "data_mode_warning": mode_warning,
            "warnings": warnings,
        }

    def _cached(self, name: str, dependency_tf: str, builder):
        dependency = self.store.latest_timestamp_for_sources(dependency_tf, self._active_sources) if self._active_sources else self.store.latest_any_timestamp(dependency_tf)
        key = f"pro:v4.1:{self._active_source_label}:{name}:{dependency_tf}"
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
        base = super()._data_integrity_stage(data_mode, counts)
        base["stage"] = "Data Integrity"
        base["engine_version"] = "V4"
        return base

    def _htf_bias(self, frames: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        base = super()._htf_bias(frames)
        current = self._first_number([frames["4H"]["close"].iloc[-1] if not frames["4H"].empty else None])
        high = base.get("key_swing_high")
        low = base.get("key_swing_low")
        location = "Unknown"
        if current is not None and high is not None and low is not None and high > low:
            mid = (high + low) / 2
            location = "Premium" if current > mid else "Discount"
        base.update({
            "stage": "HTF Bias Engine V2",
            "market_structure": {
                "d1": base.get("d1_structure", {}),
                "h4": base.get("h4_structure", {}),
            },
            "premium_discount": location,
            "current_price_location": location,
            "next_liquidity_target": high if base.get("bias") == "Bullish" else low if base.get("bias") == "Bearish" else None,
            "engine_version": "HTF Bias V2",
        })
        return base

    def _liquidity_map(self, frames: Dict[str, pd.DataFrame], current_price: Optional[float]) -> Dict[str, Any]:
        base = super()._liquidity_map(frames, current_price)
        pwh, pwl = self._previous_week_levels(frames.get("1D"))
        buy_levels = [level for level in [pwh, base.get("previous_day_high"), base.get("session_high")] if level is not None]
        sell_levels = [level for level in [pwl, base.get("previous_day_low"), base.get("session_low")] if level is not None]
        taken = [base.get("swept_liquidity")] if base.get("swept_liquidity") is not None else []
        untaken = [level for level in buy_levels + sell_levels if level not in taken]
        base.update({
            "stage": "Liquidity Engine V2",
            "previous_week_high": pwh,
            "previous_week_low": pwl,
            "buy_side_liquidity": list(dict.fromkeys(base.get("buy_side_liquidity", []) + buy_levels)),
            "sell_side_liquidity": list(dict.fromkeys(base.get("sell_side_liquidity", []) + sell_levels)),
            "liquidity_taken": taken,
            "liquidity_untaken": untaken,
            "target_liquidity": base.get("target_liquidity") or self._nearest(current_price, buy_levels, sell_levels),
            "engine_version": "Liquidity V2",
        })
        return base

    def _crt_range(self, frames: Dict[str, pd.DataFrame], current_price: Optional[float]) -> Dict[str, Any]:
        base = super()._crt_range(frames, current_price)
        high = float(base["crt_high"])
        low = float(base["crt_low"])
        width = max(high - low, 0.001)
        ratio = None if current_price is None else (float(current_price) - low) / width
        mid_range = ratio is not None and 0.40 <= ratio <= 0.60
        base.update({
            "stage": "Dealing Range / CRT Engine",
            "dealing_range_high": base["crt_high"],
            "dealing_range_low": base["crt_low"],
            "current_price_position": round(ratio * 100, 2) if ratio is not None else None,
            "manipulation_leg": "Possible sweep leg" if base.get("range_status") == "Expansion" else "Not confirmed",
            "displacement_leg": "Pending" if mid_range else "Possible",
            "ideal_poi_area": "Discount" if base.get("current_price_location") == "Premium" else "Premium",
            "mid_range_warning": bool(mid_range),
            "engine_version": "CRT / Dealing Range V2",
        })
        return base

    def _poi(self, frames: Dict[str, pd.DataFrame], htf: Dict[str, Any], crt: Dict[str, Any], current_price: Optional[float]) -> Dict[str, Any]:
        base = super()._poi(frames, htf, crt, current_price)
        best = base.get("best_poi") or {}
        base.update({
            "stage": "POI Engine V2",
            "best_buy_poi": base.get("buy_poi_zone"),
            "best_sell_poi": base.get("sell_poi_zone"),
            "poi_strength": base.get("confidence", 0),
            "rejection_zone": best,
            "premium_discount_alignment_reason": "POI aligns with the 1H dealing range." if base.get("premium_discount_alignment") else "Waiting for premium/discount alignment.",
            "engine_version": "POI V2",
        })
        return base

    def _confirmation(self, frames: Dict[str, pd.DataFrame], htf: Dict[str, Any], poi: Dict[str, Any], current_price: Optional[float]) -> Dict[str, Any]:
        base = super()._confirmation(frames, htf, poi, current_price)
        base.update({
            "stage": "Confirmation Engine V2",
            "failed_confirmation": not bool(base.get("confirmation_ready")),
            "retest_fvg_or_ob": bool(base.get("fvg_retest") or base.get("ob_retest")),
            "engine_version": "Confirmation V2",
        })
        return base

    def _score(self, locked_mode: str, data_mode: Dict[str, Any], htf: Dict[str, Any], crt: Dict[str, Any], liquidity: Dict[str, Any], poi: Dict[str, Any], confirmation: Dict[str, Any]) -> Dict[str, Any]:
        score = super()._score(locked_mode, data_mode, htf, crt, liquidity, poi, confirmation)
        if crt.get("mid_range_warning"):
            score["score"] = max(0, score["score"] - 10)
            score["penalty_reasons"].append("Mid-range price -10")
            score["score_result"] = self._score_result(score["score"])
        score["stage"] = "Smart Score V2"
        score["positive_model"] = {
            "HTF bias aligned": 20,
            "Correct premium/discount": 15,
            "Liquidity sweep": 20,
            "Valid 15M POI": 15,
            "OTE confluence": 10,
            "5M BOS/CHOCH confirmation": 20,
        }
        return score

    def _workflow(self, data_integrity: Dict[str, Any], htf: Dict[str, Any], liquidity: Dict[str, Any], crt: Dict[str, Any], poi: Dict[str, Any], confirmation: Dict[str, Any], score: Dict[str, Any], decision: str) -> list[Dict[str, Any]]:
        return [
            self._stage("Data Integrity", data_integrity["status"], data_integrity["confidence"], data_integrity["reason"], "All", []),
            self._stage("HTF Bias", "VALID" if htf["bias"] in {"Bullish", "Bearish"} else "WAITING", htf["confidence"], htf["reason"], "1D/4H", []),
            self._stage("Liquidity Map", "VALID" if liquidity.get("liquidity_sweep") else "WAITING", liquidity["confidence"], liquidity["reason"], "1H", []),
            self._stage("Dealing Range / CRT", "READY", crt["confidence"], f"Price is in {crt['current_price_location']}; mid-range warning: {crt.get('mid_range_warning')}.", "1H", []),
            self._stage("Premium / Discount", "VALID" if not crt.get("mid_range_warning") else "WAITING", crt["confidence"], f"Ideal POI area: {crt.get('ideal_poi_area')}.", "1H", []),
            self._stage("POI Detection", "VALID" if poi.get("best_poi") else "WAITING", poi["confidence"], poi["reason"], "15M", [poi["best_poi"]] if poi.get("best_poi") else []),
            self._stage("Confirmation", "VALID" if confirmation.get("confirmation_ready") else "WAITING", confirmation["confidence"], confirmation["reason"], "5M", []),
            self._stage("Setup Quality Score", "VALID" if score["score"] >= 75 else "WEAK", score["score"], score["score_result"], "All", []),
            self._stage("Final Decision", "VALID" if "Setup" in decision else "WAITING" if decision.startswith("Waiting") else "INFO", score["score"], decision, "All", []),
        ]

    def _blocked(self, decision: str, locked_mode: str, data_mode: Dict[str, Any], counts: Dict[str, int], reason: str, current_price: Optional[float] = None, missing: Optional[list[Dict[str, Any]]] = None) -> Dict[str, Any]:
        result = super()._blocked(decision, locked_mode, data_mode, counts, reason, current_price, missing)
        result.update({
            "version": "1.7.2",
            "engine_core_version": "V4",
            "engine_name": "Institutional Analysis Engine V4",
            "smart_score_v2": result.get("score_engine", {"score": 0, "score_result": "Waiting"}),
        })
        return result

    def _previous_week_levels(self, df: Optional[pd.DataFrame]) -> tuple[Optional[float], Optional[float]]:
        if df is None or df.empty or len(df) < 7:
            return None, None
        previous = df.tail(min(len(df), 10)).iloc[:-1]
        if previous.empty:
            return None, None
        return round(float(previous["high"].max()), 3), round(float(previous["low"].min()), 3)

    def _nearest(self, current_price: Optional[float], buy_levels: list[float], sell_levels: list[float]) -> Optional[float]:
        if current_price is None:
            return None
        candidates = [level for level in buy_levels + sell_levels if level is not None]
        if not candidates:
            return None
        return round(float(min(candidates, key=lambda level: abs(float(level) - float(current_price)))), 3)

    def _waiting_condition(self, decision: str, liquidity: Dict[str, Any], poi: Dict[str, Any], confirmation: Dict[str, Any]) -> str:
        if decision == "Waiting for Liquidity Sweep":
            return liquidity.get("reason") or "Wait for buy-side or sell-side liquidity sweep."
        if decision == "Waiting for Pullback to POI":
            return poi.get("reason") or "Wait for price to reach 15M FVG/OB/OTE."
        if decision == "Waiting for 5M Confirmation":
            return confirmation.get("reason") or "Wait for BOS/CHOCH and displacement/retest."
        if decision.startswith("Waiting"):
            return decision
        return "No waiting condition."

    def _invalidation_condition(self, result: Dict[str, Any]) -> str:
        invalidation = result.get("signal", {}).get("invalidation_level") or result.get("htf_bias", {}).get("invalidation_level")
        if invalidation is None:
            return "Invalidation is unavailable until a valid POI or HTF structure exists."
        return f"Setup is invalidated if price trades beyond {round(float(invalidation), 3)}."

    def _next_trigger(self, decision: str) -> str:
        if decision == "Waiting for Liquidity Sweep":
            return "A clean sweep of mapped liquidity."
        if decision == "Waiting for Pullback to POI":
            return "Pullback into the selected 15M POI."
        if decision == "Waiting for 5M Confirmation":
            return "5M BOS or CHOCH with displacement/retest."
        if "Setup" in decision:
            return "Monitor entry zone, invalidation, and target levels."
        return "Wait for complete data and aligned conditions."
