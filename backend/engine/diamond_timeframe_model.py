from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, Iterable, Optional


class DiamondTimeframeFusionEngine:
    """Coordinate existing Diamond evidence around the 5M and 1H execution lanes."""

    VERSION = "DIAMOND_DUAL_CORE_V3_8_7_SETUP_AUTHORITY"
    PROFILES = {
        "SCALPING": {
            "label": "5M Scalp Core",
            "execution_timeframe": "5M",
            "context_timeframe": "15M",
            "anchor_timeframe": "1H",
            "minimum_score": 64,
            "strong_score": 80,
            "cadence": "5-8 setup-confirmed zones per 100 completed candles",
        },
        "SWING": {
            "label": "1H Intraday / Swing Core",
            "execution_timeframe": "1H",
            "context_timeframe": "4H",
            "anchor_timeframe": "1D",
            "minimum_score": 68,
            "strong_score": 82,
            "cadence": "3-5 setup-confirmed zones per 100 completed candles",
        },
    }
    MINIMUM_CANDLES = {"execution": 30, "context": 35, "anchor": 45}
    CONCEPT_WEIGHTS = {
        "anchor_structure": 12,
        "context_structure": 14,
        "execution_structure": 16,
        "execution_momentum": 11,
        "zone_location": 10,
        "origin_evidence": 10,
        "mtf_agreement": 9,
        "smr_sequence": 7,
        "smt_divergence": 7,
        "session_timing": 4,
    }

    def evaluate(
        self,
        symbol: str,
        trading_style: str,
        frames: Dict[str, Iterable[Dict[str, Any]]],
        key_zones: Optional[Dict[str, Any]] = None,
        analysis: Optional[Dict[str, Any]] = None,
        session_context: Optional[Dict[str, Any]] = None,
        smr_model: Optional[Dict[str, Any]] = None,
        smt_model: Optional[Dict[str, Any]] = None,
        market_regime: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_symbol = str(symbol or "UNKNOWN").upper()
        style = "SWING" if str(trading_style or "SCALPING").upper() == "SWING" else "SCALPING"
        profile = dict(self.PROFILES[style])
        zones = key_zones or {}
        context = analysis or {}
        session = session_context or {}
        smr = smr_model or zones.get("smr_model") or context.get("smr_model") or {}
        smt = smt_model or zones.get("smt_model") or context.get("smt_model") or {}
        regime = market_regime or context.get("market_regime") or {}

        rows = {
            "execution": self._candles(frames.get(profile["execution_timeframe"]) or []),
            "context": self._candles(frames.get(profile["context_timeframe"]) or []),
            "anchor": self._candles(frames.get(profile["anchor_timeframe"]) or []),
        }
        completed = {
            profile["execution_timeframe"]: len(rows["execution"]),
            profile["context_timeframe"]: len(rows["context"]),
            profile["anchor_timeframe"]: len(rows["anchor"]),
        }
        missing = [role for role, minimum in self.MINIMUM_CANDLES.items() if len(rows[role]) < minimum]
        if missing:
            return self._empty(normalized_symbol, style, profile, completed, missing)

        metrics = {role: self._frame_metrics(values) for role, values in rows.items()}
        primary = zones.get("primary_zone") or {}
        zone_direction = str(primary.get("entry_side") or "WAIT").upper()
        if zone_direction not in {"BUY", "SELL"}:
            zone_direction = "WAIT"
        mtf = zones.get("mtf_confluence") or {}
        mtf_direction = {
            "BULLISH": "BUY",
            "BEARISH": "SELL",
        }.get(str(mtf.get("direction") or "MIXED").upper(), "WAIT")
        smr_direction = str(smr.get("direction") or "WAIT").upper()
        smr_state = str(smr.get("pattern_state") or "SCANNING").upper()
        smr_gate = str(smr.get("execution_gate") or "WATCH").upper()

        concepts = [
            self._direction_concept(
                "anchor_structure",
                f"{profile['anchor_timeframe']} structure anchor",
                metrics["anchor"]["trend"],
                zone_direction,
            ),
            self._direction_concept(
                "context_structure",
                f"{profile['context_timeframe']} directional context",
                metrics["context"]["trend"],
                zone_direction,
            ),
            self._direction_concept(
                "execution_structure",
                f"{profile['execution_timeframe']} execution structure",
                metrics["execution"]["trend"],
                zone_direction,
            ),
            self._direction_concept(
                "execution_momentum",
                f"{profile['execution_timeframe']} MACD / RSI momentum",
                metrics["execution"]["momentum_direction"],
                zone_direction,
                detail=(
                    f"RSI {metrics['execution']['rsi_14']:.1f}; "
                    f"MACD histogram {metrics['execution']['macd_histogram']:.5f}."
                ),
            ),
            self._location_concept(primary, rows["execution"], zone_direction),
            self._origin_concept(primary, zone_direction),
            self._direction_concept(
                "mtf_agreement",
                "Diamond MTF agreement",
                mtf_direction,
                zone_direction,
                detail=f"MTF state is {str(mtf.get('state') or 'waiting').replace('_', ' ').lower()}.",
            ),
            self._smr_concept(smr_direction, smr_state, smr_gate, zone_direction),
            self._smt_concept(smt, zone_direction),
            self._session_concept(smr, session),
        ]

        score = min(95, sum(int(item["points"]) for item in concepts))
        votes = [metrics[role]["trend"] for role in ("anchor", "context", "execution")]
        consensus_direction = self._consensus(votes)
        conflict_ids = {item["id"] for item in concepts if item["state"] == "CONFLICT"}
        structural_conflict = {"anchor_structure", "context_structure"}.issubset(conflict_ids)
        mtf_conflict = "mtf_agreement" in conflict_ids and str(mtf.get("status") or "WAITING") == "READY"
        smr_conflict = smr_gate == "BLOCK_CONFLICT" or (
            smr_state == "CONFIRMED"
            and smr_direction in {"BUY", "SELL"}
            and zone_direction in {"BUY", "SELL"}
            and smr_direction != zone_direction
        )
        smt_conflict = (
            str(smt.get("execution_gate") or "NEUTRAL").upper() == "DIVERGENCE_READY"
            and int(smt.get("confidence") or 0) >= 66
            and str(smt.get("direction") or "WAIT").upper() in {"BUY", "SELL"}
            and zone_direction in {"BUY", "SELL"}
            and str(smt.get("direction") or "WAIT").upper() != zone_direction
        )
        execution_conflict = "execution_structure" in conflict_ids and "execution_momentum" in conflict_ids
        regime_direction = str(regime.get("regime_direction") or "WAIT").upper()
        regime_name = str(regime.get("regime") or "UNKNOWN").upper()
        regime_strength = int(regime.get("strength") or 0)
        strong_regime_conflict = bool(
            regime_direction in {"BUY", "SELL"}
            and zone_direction in {"BUY", "SELL"}
            and regime_direction != zone_direction
            and regime_strength >= 62
        )
        regime_volatility_lock = regime_name == "VOLATILITY_SHOCK"
        hard_conflicts = [
            name
            for name, active in (
                ("ANCHOR_CONTEXT_CONFLICT", structural_conflict),
                ("MTF_CONFLICT", mtf_conflict),
                ("SMR_CONFLICT", smr_conflict),
                ("SMT_CONFLICT", smt_conflict),
                ("EXECUTION_CONFLICT", execution_conflict),
                ("STRONG_REGIME_CONFLICT", strong_regime_conflict),
            )
            if active
        ]

        feed_matched = zones.get("feed_matched") is True and smr.get("feed_matched", True) is not False
        news = context.get("news_intelligence") or {}
        news_locked = news.get("execution_gate") == "BLOCK_NEW_ENTRIES"
        smr_session = smr.get("session") or {}
        session_allowed = smr_session.get("execution_allowed") is not False
        volatility_shock = bool(metrics["execution"]["volatility_shock"] or regime_volatility_lock)

        if not feed_matched:
            state, gate = "DATA_WAIT", "WAIT_DATA"
            next_trigger = "Wait until every Dual-Core timeframe uses the matched provider feed."
        elif zone_direction == "WAIT":
            state, gate = "SCANNING_ZONE", "WAIT_ZONE"
            next_trigger = f"Wait for a completed-candle {profile['execution_timeframe']} Diamond origin."
        elif news_locked:
            state, gate = "NEWS_LOCK", "NEWS_LOCK"
            next_trigger = news.get("summary") or "Wait for the high-impact news lock to clear."
        elif not session_allowed:
            state, gate = "SESSION_WAIT", "WAIT_SESSION"
            next_trigger = smr_session.get("reason") or "Wait for the next valid execution window."
        elif volatility_shock:
            state, gate = "VOLATILITY_WAIT", "WAIT_VOLATILITY"
            next_trigger = "Wait for execution-frame volatility to normalize and form a controlled retest."
        elif hard_conflicts:
            state, gate = "CORE_CONFLICT", "BLOCK_CONFLICT"
            next_trigger = f"Resolve {hard_conflicts[0].replace('_', ' ').lower()} before accepting this Diamond."
        elif score >= int(profile["minimum_score"]):
            state, gate = "CORE_ALIGNED", "CONFIRMED"
            next_trigger = "Dual-Core context is aligned; the closed-candle Diamond trigger remains the entry authority."
        elif score >= 58:
            state, gate = "CORE_BUILDING", "WATCH"
            next_trigger = self._next_concept(concepts)
        else:
            state, gate = "CORE_WEAK", "WATCH"
            next_trigger = self._next_concept(concepts)

        confidence_label = self._confidence_label(
            gate,
            zone_direction,
            consensus_direction,
            regime_direction,
            concepts,
        )
        lifecycle = self._public_lifecycle(zones, gate)

        return {
            "status": "READY",
            "engine": self.VERSION,
            "symbol": normalized_symbol,
            "trading_style": style,
            "profile": profile,
            "focus_timeframe": profile["execution_timeframe"],
            "state": state,
            "execution_gate": gate,
            "zone_direction": zone_direction,
            "consensus_direction": consensus_direction,
            "score": score,
            "grade": self._grade(score),
            "confidence_label": confidence_label,
            "lifecycle": lifecycle,
            "market_regime": {
                "regime": regime_name,
                "direction": regime_direction,
                "strength": regime_strength,
                "strength_band": regime.get("strength_band") or "UNKNOWN",
                "pullback_state": regime.get("pullback_state") or "WAITING",
            },
            "agreement": {
                "aligned": sum(item["state"] == "ALIGNED" for item in concepts),
                "neutral": sum(item["state"] == "NEUTRAL" for item in concepts),
                "conflicts": sum(item["state"] == "CONFLICT" for item in concepts),
                "total": len(concepts),
            },
            "concepts": concepts,
            "hard_conflicts": hard_conflicts,
            "smt_state": smt.get("state"),
            "smt_direction": smt.get("direction"),
            "smt_confidence": smt.get("confidence"),
            "frame_metrics": {
                profile["execution_timeframe"]: metrics["execution"],
                profile["context_timeframe"]: metrics["context"],
                profile["anchor_timeframe"]: metrics["anchor"],
            },
            "completed_candles": completed,
            "next_trigger": next_trigger,
            "uses_completed_candles_only": True,
            "repaints": False,
            "creates_diamond_zone": False,
            "scope": "DIAMOND_VALIDATION_BOOST_AND_VETO_ONLY",
        }

    def apply_to_key_zones(self, key_zones: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
        key_zones["diamond_timeframe_model"] = model
        if model.get("status") != "READY":
            return key_zones

        gate = str(model.get("execution_gate") or "WATCH").upper()
        score = int(model.get("score") or 0)
        profile = model.get("profile") or {}
        consensus = str(model.get("consensus_direction") or "WAIT").upper()
        zone_direction = str(model.get("zone_direction") or "WAIT").upper()
        if gate == "CONFIRMED":
            base_adjustment = 6 if score >= int(profile.get("strong_score") or 85) else 4
        elif gate == "WATCH" and score >= 58:
            base_adjustment = 1
        elif gate == "BLOCK_CONFLICT":
            base_adjustment = -10
        elif gate == "WAIT_VOLATILITY":
            base_adjustment = -6
        elif gate == "WAIT_SESSION" and model.get("trading_style") == "SCALPING":
            base_adjustment = -4
        else:
            base_adjustment = 0

        def annotate(zone: Dict[str, Any]) -> None:
            side = str(zone.get("entry_side") or "WAIT").upper()
            alignment = (
                "ALIGNED" if consensus in {"BUY", "SELL"} and side == consensus
                else "CONFLICT" if consensus in {"BUY", "SELL"} and side in {"BUY", "SELL"}
                else "PRIMARY" if side == zone_direction and side in {"BUY", "SELL"}
                else "WAIT"
            )
            adjustment = base_adjustment
            if base_adjustment > 0 and alignment not in {"ALIGNED", "PRIMARY"}:
                adjustment = 0
            if alignment == "CONFLICT" and gate == "BLOCK_CONFLICT":
                adjustment = min(adjustment, -10)
            original = self._number(zone.get("pre_dual_core_score"))
            if original is None:
                original = self._number(zone.get("diamond_score") or zone.get("diamond_confidence_score"))
                if original is not None:
                    zone["pre_dual_core_score"] = int(round(original))
            if original is not None and adjustment:
                adjusted = int(max(0, min(100, round(original + adjustment))))
                zone["diamond_score"] = adjusted
                zone["diamond_confidence_score"] = adjusted
                zone["diamond_grade"] = self._grade(adjusted)
            zone["dual_core_alignment"] = alignment
            zone["dual_core_adjustment"] = adjustment
            zone["dual_core_state"] = model.get("state")

        seen: set[int] = set()
        for collection_name in ("zones", "visible_zones", "live_zones"):
            for zone in key_zones.get(collection_name) or []:
                if id(zone) not in seen:
                    annotate(zone)
                    seen.add(id(zone))
        primary = key_zones.get("primary_zone") or {}
        if primary and id(primary) not in seen:
            annotate(primary)
        if primary:
            key_zones["diamond_score"] = primary.get("diamond_score")
            key_zones["diamond_grade"] = primary.get("diamond_grade")
        key_zones["dual_core_state"] = model.get("state")
        key_zones["dual_core_gate"] = gate
        key_zones["dual_core_score"] = score
        key_zones["confidence_label"] = model.get("confidence_label")
        key_zones["public_lifecycle"] = model.get("lifecycle")
        key_zones["regime_validation"] = model.get("market_regime")
        return key_zones

    @staticmethod
    def _confidence_label(
        gate: str,
        zone_direction: str,
        consensus_direction: str,
        regime_direction: str,
        concepts: list[Dict[str, Any]],
    ) -> str:
        if gate == "BLOCK_CONFLICT" or (
            regime_direction in {"BUY", "SELL"}
            and zone_direction in {"BUY", "SELL"}
            and regime_direction != zone_direction
        ):
            return "Counter-Trend Risk"
        aligned_ids = {item["id"] for item in concepts if item.get("state") == "ALIGNED"}
        if gate == "CONFIRMED" and zone_direction == consensus_direction:
            return "Trend Aligned"
        if {"origin_evidence", "smr_sequence"} & aligned_ids:
            return "Liquidity Confirmed"
        return "Wait for Rejection"

    @staticmethod
    def _public_lifecycle(zones: Dict[str, Any], gate: str) -> str:
        primary = zones.get("primary_zone") or {}
        latest = zones.get("latest_entry_event") or {}
        if latest and gate == "CONFIRMED":
            return "READY"
        lifecycle = str(primary.get("lifecycle") or "").upper()
        if lifecycle in {"TESTED", "WEAKENED"}:
            return "TESTED"
        if lifecycle == "FLIPPED":
            return "FAILED"
        if primary:
            return "READY" if gate == "CONFIRMED" else "WATCHING"
        return "WATCHING"

    def _frame_metrics(self, rows: list[Dict[str, Any]]) -> Dict[str, Any]:
        closes = [row["close"] for row in rows]
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)
        true_ranges = self._true_ranges(rows)
        atr14 = sum(true_ranges[-14:]) / 14.0
        baseline_samples = [
            sum(true_ranges[index - 13:index + 1]) / 14.0
            for index in range(13, len(true_ranges) - 1)
        ]
        baseline_atr = median(baseline_samples[-60:]) if baseline_samples else atr14
        safe_atr = max(atr14, abs(closes[-1]) * 1e-8, 1e-9)
        slope_atr = (ema20[-1] - ema20[-6]) / (safe_atr * 5.0)
        sample = closes[-24:]
        path = sum(abs(right - left) for left, right in zip(sample, sample[1:]))
        efficiency = abs(sample[-1] - sample[0]) / path if path else 0.0
        if ema20[-1] > ema50[-1] and slope_atr > 0.01:
            trend = "BUY"
        elif ema20[-1] < ema50[-1] and slope_atr < -0.01:
            trend = "SELL"
        else:
            trend = "WAIT"

        ema12 = self._ema(closes, 12)
        ema26 = self._ema(closes, 26)
        macd = [fast - slow for fast, slow in zip(ema12, ema26)]
        signal = self._ema(macd, 9)
        histogram = macd[-1] - signal[-1]
        rsi = self._rsi(closes, 14)
        momentum_floor = safe_atr * 0.005
        if histogram > momentum_floor and rsi >= 52:
            momentum_direction = "BUY"
        elif histogram < -momentum_floor and rsi <= 48:
            momentum_direction = "SELL"
        else:
            momentum_direction = "WAIT"

        range_rows = rows[-48:]
        range_low = min(row["low"] for row in range_rows)
        range_high = max(row["high"] for row in range_rows)
        width = max(range_high - range_low, 1e-9)
        range_position = max(0.0, min(1.0, (closes[-1] - range_low) / width))
        volatility_ratio = atr14 / max(baseline_atr, 1e-9)
        latest_range_atr = (rows[-1]["high"] - rows[-1]["low"]) / max(baseline_atr, 1e-9)
        return {
            "trend": trend,
            "momentum_direction": momentum_direction,
            "ema_20": round(ema20[-1], 5),
            "ema_50": round(ema50[-1], 5),
            "ema_slope_atr": round(slope_atr, 4),
            "efficiency": round(efficiency, 4),
            "atr_14": round(atr14, 5),
            "rsi_14": round(rsi, 2),
            "macd_histogram": round(histogram, 5),
            "range_position": round(range_position, 3),
            "volatility_ratio": round(volatility_ratio, 3),
            "latest_range_atr": round(latest_range_atr, 3),
            "volatility_shock": volatility_ratio >= 2.25 or latest_range_atr >= 3.0,
            "latest_completed_time": rows[-1]["time"],
        }

    def _direction_concept(
        self,
        identifier: str,
        label: str,
        actual: str,
        expected: str,
        detail: Optional[str] = None,
    ) -> Dict[str, Any]:
        state = self._direction_state(actual, expected)
        return self._concept(identifier, label, state, detail or f"Observed {actual}; Diamond requires {expected}.")

    def _location_concept(
        self,
        primary: Dict[str, Any],
        execution_rows: list[Dict[str, Any]],
        direction: str,
    ) -> Dict[str, Any]:
        line = self._number(primary.get("line"))
        if line is None or direction not in {"BUY", "SELL"}:
            return self._concept("zone_location", "Execution-frame zone location", "NEUTRAL", "Waiting for a primary Diamond line.")
        sample = execution_rows[-48:]
        low = min(row["low"] for row in sample)
        high = max(row["high"] for row in sample)
        position = max(0.0, min(1.0, (line - low) / max(high - low, 1e-9)))
        if (direction == "BUY" and position <= 0.58) or (direction == "SELL" and position >= 0.42):
            state = "ALIGNED"
        elif (direction == "BUY" and position >= 0.82) or (direction == "SELL" and position <= 0.18):
            state = "CONFLICT"
        else:
            state = "NEUTRAL"
        return self._concept(
            "zone_location",
            "Execution-frame zone location",
            state,
            f"Diamond line is at {position * 100:.0f}% of the recent execution range.",
        )

    def _origin_concept(self, primary: Dict[str, Any], direction: str) -> Dict[str, Any]:
        if direction not in {"BUY", "SELL"}:
            state = "NEUTRAL"
        elif primary.get("active_structure") and primary.get("entry_eligible_origin"):
            state = "ALIGNED"
        elif any(primary.get(key) for key in ("liquidity_sweep", "structure_break", "compression_break", "trend_pullback_reclaim")):
            state = "ALIGNED"
        elif primary:
            state = "NEUTRAL"
        else:
            state = "NEUTRAL"
        return self._concept(
            "origin_evidence",
            "Diamond origin evidence",
            state,
            str(primary.get("origin_model") or "Waiting for a structural origin").replace("_", " ").title(),
        )

    def _smr_concept(self, direction: str, state: str, gate: str, expected: str) -> Dict[str, Any]:
        if gate == "BLOCK_CONFLICT":
            concept_state = "CONFLICT"
        elif state == "CONFIRMED":
            concept_state = self._direction_state(direction, expected)
        else:
            concept_state = "NEUTRAL"
        return self._concept(
            "smr_sequence",
            "SMR liquidity-to-retest sequence",
            concept_state,
            f"SMR {state.replace('_', ' ').lower()} / {direction.lower()}.",
        )

    def _smt_concept(self, smt: Dict[str, Any], expected: str) -> Dict[str, Any]:
        status = str(smt.get("status") or "UNAVAILABLE").upper()
        direction = str(smt.get("direction") or "WAIT").upper()
        confidence = int(smt.get("confidence") or 0)
        if status != "READY" or confidence < 66 or direction not in {"BUY", "SELL"}:
            state = "NEUTRAL"
        else:
            state = self._direction_state(direction, expected)
        companion = smt.get("companion_symbol") or "companion"
        return self._concept(
            "smt_divergence",
            "SMT companion confirmation",
            state,
            f"{companion} / {str(smt.get('state') or status).replace('_', ' ').lower()} / confidence {confidence}%.",
        )

    def _session_concept(self, smr: Dict[str, Any], session: Dict[str, Any]) -> Dict[str, Any]:
        timing = smr.get("session") or {}
        quality = str(timing.get("quality") or "ACTIVE").upper()
        if timing.get("execution_allowed") is False or quality == "AVOID":
            state = "CONFLICT"
        elif quality in {"PRIME", "ACTIVE"}:
            state = "ALIGNED"
        else:
            state = "NEUTRAL"
        name = timing.get("name") or session.get("position") or "WAITING"
        return self._concept(
            "session_timing",
            "Execution timing window",
            state,
            f"{str(name).replace('_', ' ').title()} is {quality.lower()} quality.",
        )

    def _concept(self, identifier: str, label: str, state: str, detail: str) -> Dict[str, Any]:
        weight = int(self.CONCEPT_WEIGHTS[identifier])
        points = weight if state == "ALIGNED" else int(weight * 0.5 + 0.5) if state == "NEUTRAL" else 0
        return {
            "id": identifier,
            "label": label,
            "state": state,
            "weight": weight,
            "points": points,
            "detail": detail,
        }

    @staticmethod
    def _direction_state(actual: str, expected: str) -> str:
        if expected not in {"BUY", "SELL"} or actual not in {"BUY", "SELL"}:
            return "NEUTRAL"
        return "ALIGNED" if actual == expected else "CONFLICT"

    @staticmethod
    def _consensus(votes: list[str]) -> str:
        buy = sum(value == "BUY" for value in votes)
        sell = sum(value == "SELL" for value in votes)
        return "BUY" if buy >= 2 else "SELL" if sell >= 2 else "WAIT"

    @staticmethod
    def _next_concept(concepts: list[Dict[str, Any]]) -> str:
        blocker = next((item for item in concepts if item["state"] == "CONFLICT"), None)
        if blocker:
            return f"Wait for {blocker['label'].lower()} to align."
        pending = next((item for item in concepts if item["state"] == "NEUTRAL"), None)
        return f"Wait for {pending['label'].lower()} confirmation." if pending else "Continue monitoring closed-candle alignment."

    @staticmethod
    def _true_ranges(rows: list[Dict[str, Any]]) -> list[float]:
        result = [rows[0]["high"] - rows[0]["low"]]
        for current, previous in zip(rows[1:], rows[:-1]):
            result.append(max(
                current["high"] - current["low"],
                abs(current["high"] - previous["close"]),
                abs(current["low"] - previous["close"]),
            ))
        return result

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float]:
        alpha = 2.0 / (period + 1.0)
        result = [values[0]]
        for value in values[1:]:
            result.append(value * alpha + result[-1] * (1.0 - alpha))
        return result

    @staticmethod
    def _rsi(values: list[float], period: int) -> float:
        changes = [right - left for left, right in zip(values, values[1:])]
        sample = changes[-period:]
        gains = sum(max(change, 0.0) for change in sample) / max(len(sample), 1)
        losses = sum(max(-change, 0.0) for change in sample) / max(len(sample), 1)
        if losses <= 1e-12:
            return 100.0 if gains > 0 else 50.0
        relative_strength = gains / losses
        return 100.0 - (100.0 / (1.0 + relative_strength))

    def _candles(self, values: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
        unique: Dict[int, Dict[str, Any]] = {}
        for item in values or []:
            if item.get("is_complete") is False or item.get("is_partial") is True:
                continue
            timestamp = self._integer(item.get("time") or item.get("timestamp"))
            numbers = [self._number(item.get(key)) for key in ("open", "high", "low", "close")]
            if timestamp is None or any(value is None for value in numbers):
                continue
            open_value, high, low, close = numbers
            if (
                min(open_value, high, low, close) <= 0
                or high < low
                or high < max(open_value, close)
                or low > min(open_value, close)
            ):
                continue
            unique[timestamp] = {
                "time": timestamp,
                "open": open_value,
                "high": high,
                "low": low,
                "close": close,
            }
        return [unique[key] for key in sorted(unique)]

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer(value: Any) -> Optional[int]:
        if value is None or isinstance(value, bool):
            return None
        try:
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000.0
            return int(numeric)
        except (TypeError, ValueError):
            pass
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _grade(score: int) -> str:
        if score >= 90:
            return "A+"
        if score >= 80:
            return "A"
        if score >= 70:
            return "B"
        if score >= 60:
            return "C"
        return "D"

    def _empty(
        self,
        symbol: str,
        style: str,
        profile: Dict[str, Any],
        completed: Dict[str, int],
        missing: list[str],
    ) -> Dict[str, Any]:
        return {
            "status": "WARMING_UP",
            "engine": self.VERSION,
            "symbol": symbol,
            "trading_style": style,
            "profile": profile,
            "focus_timeframe": profile["execution_timeframe"],
            "state": "DATA_WAIT",
            "execution_gate": "WAIT_DATA",
            "zone_direction": "WAIT",
            "consensus_direction": "WAIT",
            "score": 0,
            "grade": "D",
            "confidence_label": "Wait for Rejection",
            "lifecycle": "WATCHING",
            "market_regime": {
                "regime": "UNKNOWN",
                "direction": "WAIT",
                "strength": 0,
                "strength_band": "UNKNOWN",
                "pullback_state": "WAITING",
            },
            "agreement": {"aligned": 0, "neutral": 0, "conflicts": 0, "total": len(self.CONCEPT_WEIGHTS)},
            "concepts": [],
            "hard_conflicts": [],
            "frame_metrics": {},
            "completed_candles": completed,
            "missing_roles": missing,
            "next_trigger": f"Load complete {', '.join(missing)} timeframe history for the {profile['label']}.",
            "uses_completed_candles_only": True,
            "repaints": False,
            "creates_diamond_zone": False,
            "scope": "DIAMOND_VALIDATION_BOOST_AND_VETO_ONLY",
        }
