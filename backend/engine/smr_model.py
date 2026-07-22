from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional


class SMRModelEngine:
    """Completed-candle liquidity raid, structure shift, and FVG retest model."""

    VERSION = "SH_SMR_V1_SESSION_AWARE"
    PROFILES = {
        "SCALPING": {
            "label": "Scalp 1H / 15M / 5M",
            "structure_timeframe": "1H",
            "context_timeframe": "15M",
            "execution_timeframe": "5M",
            "sweep_lookback": 10,
        },
        "SWING": {
            "label": "Swing 1D / 4H / 1H",
            "structure_timeframe": "1D",
            "context_timeframe": "4H",
            "execution_timeframe": "1H",
            "sweep_lookback": 8,
        },
    }

    def evaluate(
        self,
        symbol: str,
        trading_style: str,
        frames: Dict[str, Iterable[Dict[str, Any]]],
        session_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_symbol = str(symbol or "UNKNOWN").upper()
        style = "SWING" if str(trading_style or "SCALPING").upper() == "SWING" else "SCALPING"
        profile = dict(self.PROFILES[style])
        structure = self._candles(frames.get(profile["structure_timeframe"]) or [])
        context = self._candles(frames.get(profile["context_timeframe"]) or [])
        execution = self._candles(frames.get(profile["execution_timeframe"]) or [])
        minimums = {"structure": 35, "context": 35, "execution": 40}
        if len(structure) < minimums["structure"] or len(context) < minimums["context"] or len(execution) < minimums["execution"]:
            return self._empty(
                "WARMING_UP",
                normalized_symbol,
                style,
                profile,
                execution[-1]["time"] if execution else None,
                {
                    "structure": len(structure),
                    "context": len(context),
                    "execution": len(execution),
                },
            )

        latest_time = execution[-1]["time"]
        session = self._session_window(normalized_symbol, style, latest_time)
        structure_trend = self._trend(structure)
        context_trend = self._trend(context)
        poi = self._recent_fvg(context, context_trend)
        sweep = self._liquidity_raid(execution, int(profile["sweep_lookback"]))
        direction = str((sweep or {}).get("direction") or "WAIT")
        shift = self._structure_shift(execution, sweep, int(profile["sweep_lookback"])) if sweep else None
        fvg = self._post_raid_fvg(execution, sweep, shift) if sweep and shift else None
        retest = self._fvg_retest(execution, fvg, direction) if fvg else None

        expected_trend = "BULLISH" if direction == "BUY" else "BEARISH" if direction == "SELL" else "MIXED"
        poi_direction = str((poi or {}).get("direction") or "WAIT")
        htf_aligned = bool(
            direction in {"BUY", "SELL"}
            and (structure_trend == expected_trend or context_trend == expected_trend or poi_direction == direction)
        )
        stance = str((session_context or {}).get("stance") or "BALANCED").upper()
        session_stance_aligned = bool(
            (direction == "BUY" and stance == "BULLISH")
            or (direction == "SELL" and stance == "BEARISH")
        )

        score = 0
        score += 12 if direction in {"BUY", "SELL"} and structure_trend == expected_trend else 4 if direction in {"BUY", "SELL"} and context_trend == expected_trend else 0
        score += 13 if direction in {"BUY", "SELL"} and poi_direction == direction else 5 if poi else 0
        score += 25 if sweep else 0
        score += 22 if shift else 0
        score += 13 if fvg else 0
        score += 10 if retest else 0
        score += {"PRIME": 10, "ACTIVE": 7, "SELECTIVE": 4, "AVOID": 0}.get(session["quality"], 0)
        score += 5 if session_stance_aligned else 0
        # Reserve a small uncertainty margin; market evidence should never be
        # presented as absolute certainty even when every model component aligns.
        score = int(max(0, min(95, score)))

        if not sweep:
            pattern_state = "SCANNING_LIQUIDITY"
            next_trigger = "Wait for a completed-candle buy-side or sell-side liquidity raid."
        elif not shift:
            pattern_state = "WAIT_STRUCTURE_SHIFT"
            next_trigger = f"Wait for a {direction.lower()} market-structure shift with displacement."
        elif not fvg:
            pattern_state = "WAIT_FVG_FORMATION"
            next_trigger = "Wait for a directional FVG after the structure shift."
        elif not retest:
            pattern_state = "WAIT_FVG_RETEST"
            next_trigger = "Wait for price to retest the SMR FVG on a completed candle."
        elif not htf_aligned:
            pattern_state = "HTF_CONFLICT"
            next_trigger = "The lower-timeframe reversal is not aligned with HTF structure or POI."
        else:
            pattern_state = "CONFIRMED"
            next_trigger = "SMR sequence confirmed; Diamond and risk gates still control entry."

        if session["execution_allowed"] is False:
            execution_gate = "WAIT_SESSION"
            next_trigger = session["reason"]
        elif pattern_state == "HTF_CONFLICT":
            execution_gate = "BLOCK_CONFLICT"
        elif pattern_state == "CONFIRMED" and score >= 70:
            execution_gate = "OPEN"
        else:
            execution_gate = "WATCH"

        return {
            "status": "READY",
            "engine": self.VERSION,
            "symbol": normalized_symbol,
            "trading_style": style,
            "profile": profile,
            "pattern_state": pattern_state,
            "direction": direction,
            "score": score,
            "grade": self._grade(score),
            "execution_gate": execution_gate,
            "next_trigger": next_trigger,
            "session": session,
            "evidence": {
                "structure_trend": structure_trend,
                "context_trend": context_trend,
                "htf_aligned": htf_aligned,
                "session_stance_aligned": session_stance_aligned,
                "htf_poi": poi,
                "liquidity_raid": sweep,
                "structure_shift": shift,
                "fvg": fvg,
                "fvg_retest": retest,
            },
            "completed_candles": {
                profile["structure_timeframe"]: len(structure),
                profile["context_timeframe"]: len(context),
                profile["execution_timeframe"]: len(execution),
            },
            "uses_completed_candles_only": True,
            "repaints": False,
            "creates_trade_direction": False,
            "scope": "DIAMOND_CONFIRMATION_AND_TIMING_ONLY",
        }

    def apply_to_key_zones(self, key_zones: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
        key_zones["smr_model"] = model
        if model.get("status") != "READY":
            return key_zones

        model_direction = str(model.get("direction") or "WAIT").upper()
        pattern_state = str(model.get("pattern_state") or "SCANNING_LIQUIDITY").upper()
        session_allowed = (model.get("session") or {}).get("execution_allowed") is not False
        def annotate(zone: Dict[str, Any]) -> None:
            zone_side = str(zone.get("entry_side") or "WAIT").upper()
            aligned = model_direction in {"BUY", "SELL"} and zone_side == model_direction
            conflict = model_direction in {"BUY", "SELL"} and zone_side in {"BUY", "SELL"} and zone_side != model_direction
            adjustment = 0
            if aligned and pattern_state == "CONFIRMED":
                adjustment = 6
            elif aligned and pattern_state in {"WAIT_FVG_RETEST", "WAIT_FVG_FORMATION"}:
                adjustment = 3
            elif conflict and pattern_state in {"CONFIRMED", "HTF_CONFLICT"}:
                adjustment = -8
            if not session_allowed and str(model.get("trading_style")) == "SCALPING":
                adjustment = min(adjustment, -4)
            original = self._number(zone.get("diamond_score") or zone.get("diamond_confidence_score"))
            if original is not None and adjustment:
                adjusted = int(max(0, min(100, round(original + adjustment))))
                zone["diamond_score"] = adjusted
                zone["diamond_confidence_score"] = adjusted
                zone["diamond_grade"] = self._grade(adjusted)
            zone["smr_alignment"] = "ALIGNED" if aligned else "CONFLICT" if conflict else "WAIT"
            zone["smr_score_adjustment"] = adjustment
            zone["smr_pattern_state"] = pattern_state

        # Public zone collections are separate dictionaries. Annotate each one so
        # the chart, detail panel, and history ledger all receive the same result.
        seen: set[int] = set()
        for collection_name in ("zones", "visible_zones", "live_zones"):
            for zone in key_zones.get(collection_name) or []:
                if id(zone) not in seen:
                    annotate(zone)
                    seen.add(id(zone))

        primary = key_zones.get("primary_zone") or {}
        if primary:
            annotate(primary)
        primary_side = str(primary.get("entry_side") or "WAIT").upper()
        primary_alignment = (
            "ALIGNED" if model_direction in {"BUY", "SELL"} and primary_side == model_direction
            else "CONFLICT" if model_direction in {"BUY", "SELL"} and primary_side in {"BUY", "SELL"}
            else "WAIT"
        )
        if not session_allowed:
            diamond_gate = "WAIT_SESSION"
        elif primary_alignment == "CONFLICT" and pattern_state in {"CONFIRMED", "HTF_CONFLICT"}:
            diamond_gate = "BLOCK_CONFLICT"
        elif primary_alignment == "ALIGNED" and pattern_state == "CONFIRMED":
            diamond_gate = "CONFIRMED"
        else:
            diamond_gate = "WATCH"
        model["diamond_alignment"] = primary_alignment
        model["diamond_gate"] = diamond_gate
        if diamond_gate in {"WAIT_SESSION", "BLOCK_CONFLICT"}:
            model["execution_gate"] = diamond_gate

        if primary:
            key_zones["diamond_score"] = primary.get("diamond_score")
            key_zones["diamond_grade"] = primary.get("diamond_grade")
        key_zones["smr_alignment"] = primary_alignment
        key_zones["smr_gate"] = diamond_gate
        return key_zones

    @staticmethod
    def _session_window(symbol: str, style: str, timestamp: int) -> Dict[str, Any]:
        moment = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        hour = moment.hour
        weekday = moment.weekday()
        if style == "SWING":
            closed = symbol == "XAUUSD" and (
                weekday == 5
                or (weekday == 4 and hour >= 21)
                or (weekday == 6 and hour < 22)
            )
            return {
                "name": "MARKET_CLOSED" if closed else "SWING_WINDOW",
                "quality": "AVOID" if closed else "ACTIVE",
                "execution_allowed": not closed,
                "utc_hour": hour,
                "reason": "XAU swing confirmation waits for the weekday market." if closed else "Swing confirmation is controlled by 1D, 4H, and 1H completed candles.",
            }

        xau_closed = symbol == "XAUUSD" and (
            weekday == 5
            or (weekday == 4 and hour >= 21)
            or (weekday == 6 and hour < 22)
        )
        if xau_closed:
            name, quality = "MARKET_CLOSED", "AVOID"
        elif symbol == "XAUUSD" and 7 <= hour < 12:
            name, quality = "LONDON", "PRIME"
        elif symbol == "XAUUSD" and 12 <= hour < 17:
            name, quality = "NEW_YORK", "PRIME"
        elif symbol == "XAUUSD" and 21 <= hour < 23:
            name, quality = "ROLLOVER", "AVOID"
        elif symbol == "XAUUSD" and (hour < 7):
            name, quality = "ASIA", "SELECTIVE"
        elif symbol == "XAUUSD":
            name, quality = "LATE_NEW_YORK", "ACTIVE"
        elif 8 <= hour < 13:
            name, quality = "LONDON", "PRIME"
        elif 13 <= hour < 21:
            name, quality = "NEW_YORK", "PRIME"
        elif hour < 8:
            name, quality = "ASIA", "ACTIVE"
        else:
            name, quality = "LATE_SESSION", "SELECTIVE"
        allowed = quality != "AVOID"
        return {
            "name": name,
            "quality": quality,
            "execution_allowed": allowed,
            "utc_hour": hour,
            "reason": (
                f"{name.replace('_', ' ').title()} is a {quality.lower()} {symbol} scalp window."
                if allowed else f"Wait until the {symbol} rollover or market-closed window ends."
            ),
        }

    def _liquidity_raid(self, rows: list[Dict[str, Any]], lookback: int) -> Optional[Dict[str, Any]]:
        latest = None
        start = max(lookback, len(rows) - 48)
        for index in range(start, len(rows)):
            prior = rows[index - lookback:index]
            candle = rows[index]
            atr = self._atr(rows, index)
            if atr is None:
                continue
            prior_low = min(item["low"] for item in prior)
            prior_high = max(item["high"] for item in prior)
            tolerance = atr * 0.02
            if candle["low"] < prior_low - tolerance and candle["close"] > prior_low:
                latest = {"direction": "BUY", "time": candle["time"], "index": index, "level": round(prior_low, 5), "extreme": round(candle["low"], 5), "atr": round(atr, 5)}
            elif candle["high"] > prior_high + tolerance and candle["close"] < prior_high:
                latest = {"direction": "SELL", "time": candle["time"], "index": index, "level": round(prior_high, 5), "extreme": round(candle["high"], 5), "atr": round(atr, 5)}
        return latest

    def _structure_shift(self, rows: list[Dict[str, Any]], sweep: Dict[str, Any], lookback: int) -> Optional[Dict[str, Any]]:
        index = int(sweep["index"])
        before = rows[max(0, index - lookback):index]
        if not before:
            return None
        direction = sweep["direction"]
        level = max(item["high"] for item in before) if direction == "BUY" else min(item["low"] for item in before)
        for cursor in range(index + 1, len(rows)):
            candle = rows[cursor]
            crossed = candle["close"] > level if direction == "BUY" else candle["close"] < level
            if not crossed:
                continue
            atr = self._atr(rows, cursor)
            body_atr = abs(candle["close"] - candle["open"]) / atr if atr else 0
            if body_atr < 0.35:
                continue
            return {"direction": direction, "time": candle["time"], "index": cursor, "level": round(level, 5), "body_atr": round(body_atr, 3)}
        return None

    @staticmethod
    def _post_raid_fvg(rows: list[Dict[str, Any]], sweep: Dict[str, Any], shift: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        direction = sweep["direction"]
        start = max(2, int(sweep["index"]) + 1)
        end = min(len(rows), int(shift["index"]) + 4)
        selected = None
        for index in range(start, end):
            left, current = rows[index - 2], rows[index]
            if direction == "BUY" and current["low"] > left["high"]:
                selected = {"direction": direction, "time": current["time"], "index": index, "low": round(left["high"], 5), "high": round(current["low"], 5)}
            elif direction == "SELL" and current["high"] < left["low"]:
                selected = {"direction": direction, "time": current["time"], "index": index, "low": round(current["high"], 5), "high": round(left["low"], 5)}
        return selected

    @staticmethod
    def _fvg_retest(rows: list[Dict[str, Any]], fvg: Dict[str, Any], direction: str) -> Optional[Dict[str, Any]]:
        for candle in rows[int(fvg["index"]) + 1:]:
            touched = candle["low"] <= fvg["high"] and candle["high"] >= fvg["low"]
            held = candle["close"] >= fvg["low"] if direction == "BUY" else candle["close"] <= fvg["high"]
            if touched and held:
                return {"time": candle["time"], "close": round(candle["close"], 5), "held": True}
        return None

    def _recent_fvg(self, rows: list[Dict[str, Any]], trend: str) -> Optional[Dict[str, Any]]:
        selected = None
        for index in range(max(2, len(rows) - 80), len(rows)):
            left, current = rows[index - 2], rows[index]
            if current["low"] > left["high"] and trend != "BEARISH":
                selected = {"direction": "BUY", "time": current["time"], "low": round(left["high"], 5), "high": round(current["low"], 5), "timeframe_role": "HTF_POI"}
            elif current["high"] < left["low"] and trend != "BULLISH":
                selected = {"direction": "SELL", "time": current["time"], "low": round(current["high"], 5), "high": round(left["low"], 5), "timeframe_role": "HTF_POI"}
        return selected

    def _trend(self, rows: list[Dict[str, Any]]) -> str:
        closes = [row["close"] for row in rows[-80:]]
        fast = self._ema(closes, 20)
        slow = self._ema(closes, 50)
        if fast[-1] > slow[-1] and closes[-1] > fast[-1]:
            return "BULLISH"
        if fast[-1] < slow[-1] and closes[-1] < fast[-1]:
            return "BEARISH"
        return "MIXED"

    def _atr(self, rows: list[Dict[str, Any]], index: int, period: int = 14) -> Optional[float]:
        start = max(1, index - period + 1)
        ranges = []
        for cursor in range(start, index + 1):
            current, previous = rows[cursor], rows[cursor - 1]
            ranges.append(max(current["high"] - current["low"], abs(current["high"] - previous["close"]), abs(current["low"] - previous["close"])))
        return sum(ranges) / len(ranges) if ranges else None

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float]:
        alpha = 2 / (period + 1)
        result = [values[0]]
        for value in values[1:]:
            result.append(value * alpha + result[-1] * (1 - alpha))
        return result

    def _candles(self, values: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
        rows: Dict[int, Dict[str, Any]] = {}
        for item in values or []:
            if item.get("is_complete") is False or item.get("is_partial") is True:
                continue
            timestamp = self._timestamp(item.get("time") or item.get("timestamp"))
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
            rows[timestamp] = {"time": timestamp, "open": open_value, "high": high, "low": low, "close": close}
        return [rows[key] for key in sorted(rows)]

    @staticmethod
    def _timestamp(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
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
        status: str,
        symbol: str,
        style: str,
        profile: Dict[str, Any],
        latest_time: Optional[int],
        completed: Dict[str, int],
    ) -> Dict[str, Any]:
        session = self._session_window(symbol, style, latest_time) if latest_time is not None else {
            "name": "WAITING",
            "quality": "AVOID",
            "execution_allowed": False,
            "utc_hour": None,
            "reason": "Waiting for completed execution candles.",
        }
        return {
            "status": status,
            "engine": self.VERSION,
            "symbol": symbol,
            "trading_style": style,
            "profile": profile,
            "pattern_state": "WARMING_UP",
            "direction": "WAIT",
            "score": 0,
            "grade": "D",
            "execution_gate": "WATCH",
            "next_trigger": "SMR requires complete structure, context, and execution candle history.",
            "session": session,
            "evidence": {},
            "completed_candles": completed,
            "uses_completed_candles_only": True,
            "repaints": False,
            "creates_trade_direction": False,
            "scope": "DIAMOND_CONFIRMATION_AND_TIMING_ONLY",
        }
