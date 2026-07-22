from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Optional


class MarketRegimeEngine:
    """Classify closed-candle conditions and veto unsafe setup contexts."""

    VERSION = "MARKET_REGIME_V3_ADAPTIVE_PULLBACK"
    MINIMUM_CANDLES = 60
    THRESHOLDS = {
        "trend_efficiency": 0.32,
        "range_efficiency": 0.25,
        "trend_ema_spread_atr": 0.25,
        "range_ema_spread_atr": 0.35,
        "trend_ema_slope_atr": 0.02,
        "volatility_ratio": 2.0,
        "shock_range_atr": 2.8,
        "range_edge": 0.25,
        "max_directional_extension_atr": 4.75,
        "extreme_range_position": 0.92,
    }

    def evaluate(
        self,
        symbol: str,
        timeframe: str,
        candles: Iterable[Dict[str, Any]],
        intended_direction: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows = self._completed_candles(candles)
        direction = str(intended_direction or "WAIT").upper()
        if direction not in {"BUY", "SELL"}:
            direction = "WAIT"

        if len(rows) < self.MINIMUM_CANDLES:
            return {
                "status": "INSUFFICIENT_DATA",
                "version": self.VERSION,
                "symbol": str(symbol or "XAUUSD").upper(),
                "timeframe": str(timeframe or "15M").upper(),
                "regime": "UNKNOWN",
                "regime_direction": "WAIT",
                "intended_direction": direction,
                "execution_gate": "OBSERVE",
                "allows_new_entry": False,
                "strength": 0,
                "reason": f"At least {self.MINIMUM_CANDLES} completed candles are required.",
                "next_trigger": "Wait for enough completed candles to classify the market regime.",
                "metrics": {},
                "location_guard": {
                    "status": "INSUFFICIENT_DATA",
                    "allows_entry": False,
                    "reason": "Location cannot be evaluated until enough completed candles are available.",
                },
                "thresholds": dict(self.THRESHOLDS),
                "completed_candles": len(rows),
                "uses_completed_candles_only": True,
                "changes_signal_logic": False,
            }

        closes = [row["close"] for row in rows]
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)
        true_ranges = self._true_ranges(rows)
        atr14 = sum(true_ranges[-14:]) / 14.0
        prior_atr_samples = [
            sum(true_ranges[index - 13:index + 1]) / 14.0
            for index in range(13, len(true_ranges) - 1)
        ]
        baseline_atr = median(prior_atr_samples[-60:]) if prior_atr_samples else atr14
        safe_atr = max(atr14, abs(closes[-1]) * 1e-8, 1e-9)
        safe_baseline_atr = max(baseline_atr, abs(closes[-1]) * 1e-8, 1e-9)

        efficiency_window = closes[-25:]
        path = sum(abs(right - left) for left, right in zip(efficiency_window, efficiency_window[1:]))
        efficiency = abs(efficiency_window[-1] - efficiency_window[0]) / path if path else 0.0
        ema_spread_atr = (ema20[-1] - ema50[-1]) / safe_atr
        ema_slope_atr = (ema20[-1] - ema20[-11]) / (safe_atr * 10.0)
        ema_distance_atr = (closes[-1] - ema20[-1]) / safe_atr
        volatility_ratio = atr14 / safe_baseline_atr
        latest_range_atr = (rows[-1]["high"] - rows[-1]["low"]) / safe_baseline_atr

        range_rows = rows[-48:]
        range_low = min(row["low"] for row in range_rows)
        range_high = max(row["high"] for row in range_rows)
        range_width = range_high - range_low
        range_position = (closes[-1] - range_low) / range_width if range_width > 0 else 0.5
        range_position = max(0.0, min(1.0, range_position))

        regime, regime_direction = self._classify(
            efficiency,
            ema_spread_atr,
            ema_slope_atr,
            volatility_ratio,
            latest_range_atr,
        )
        strength = self._strength(regime, efficiency, ema_spread_atr, ema_slope_atr, volatility_ratio, latest_range_atr)
        strength_band = self._strength_band(strength)
        pullback_state = self._pullback_state(
            regime,
            regime_direction,
            ema_distance_atr,
            range_position,
        )
        location_guard = self._location_guard(direction, ema_distance_atr, range_position)
        gate, reason, next_trigger = self._execution_gate(
            regime,
            regime_direction,
            direction,
            range_position,
            location_guard,
        )

        return {
            "status": "READY",
            "version": self.VERSION,
            "symbol": str(symbol or "XAUUSD").upper(),
            "timeframe": str(timeframe or "15M").upper(),
            "regime": regime,
            "regime_direction": regime_direction,
            "intended_direction": direction,
            "execution_gate": gate,
            "allows_new_entry": gate in {"OPEN", "OPEN_RANGE_EDGE"},
            "strength": strength,
            "strength_band": strength_band,
            "pullback_state": pullback_state,
            "reason": reason,
            "next_trigger": next_trigger,
            "metrics": {
                "ema_20": self._rounded(ema20[-1]),
                "ema_50": self._rounded(ema50[-1]),
                "atr_14": self._rounded(atr14),
                "efficiency_ratio": self._rounded(efficiency, 4),
                "ema_spread_atr": self._rounded(ema_spread_atr, 4),
                "ema_slope_atr": self._rounded(ema_slope_atr, 4),
                "ema_distance_atr": self._rounded(ema_distance_atr, 3),
                "directional_extension_atr": location_guard["directional_extension_atr"],
                "volatility_ratio": self._rounded(volatility_ratio, 3),
                "latest_range_atr": self._rounded(latest_range_atr, 3),
                "range_position": self._rounded(range_position, 3),
                "range_location": self._range_location(range_position),
            },
            "location_guard": location_guard,
            "thresholds": dict(self.THRESHOLDS),
            "completed_candles": len(rows),
            "latest_completed_time": rows[-1]["time"],
            "uses_completed_candles_only": True,
            "changes_signal_logic": True,
        }

    @staticmethod
    def _strength_band(strength: int) -> str:
        if strength >= 80:
            return "STRONG"
        if strength >= 62:
            return "ESTABLISHED"
        if strength >= 44:
            return "DEVELOPING"
        return "WEAK"

    @staticmethod
    def _pullback_state(
        regime: str,
        regime_direction: str,
        ema_distance_atr: float,
        range_position: float,
    ) -> str:
        if regime == "VOLATILITY_SHOCK":
            return "UNSTABLE"
        if regime_direction == "BUY":
            if ema_distance_atr > 1.8 or range_position >= 0.88:
                return "EXTENDED"
            if ema_distance_atr <= 0.45:
                return "PULLBACK_READY"
            return "TREND_CONTINUATION"
        if regime_direction == "SELL":
            if ema_distance_atr < -1.8 or range_position <= 0.12:
                return "EXTENDED"
            if ema_distance_atr >= -0.45:
                return "PULLBACK_READY"
            return "TREND_CONTINUATION"
        if regime == "RANGE":
            if range_position <= 0.25:
                return "LOWER_EDGE"
            if range_position >= 0.75:
                return "UPPER_EDGE"
            return "MID_RANGE"
        return "TRANSITION"

    def _classify(
        self,
        efficiency: float,
        ema_spread_atr: float,
        ema_slope_atr: float,
        volatility_ratio: float,
        latest_range_atr: float,
    ) -> tuple[str, str]:
        threshold = self.THRESHOLDS
        if volatility_ratio >= threshold["volatility_ratio"] or latest_range_atr >= threshold["shock_range_atr"]:
            return "VOLATILITY_SHOCK", "WAIT"
        if (
            efficiency >= threshold["trend_efficiency"]
            and ema_spread_atr >= threshold["trend_ema_spread_atr"]
            and ema_slope_atr >= threshold["trend_ema_slope_atr"]
        ):
            return "TRENDING_BULLISH", "BUY"
        if (
            efficiency >= threshold["trend_efficiency"]
            and ema_spread_atr <= -threshold["trend_ema_spread_atr"]
            and ema_slope_atr <= -threshold["trend_ema_slope_atr"]
        ):
            return "TRENDING_BEARISH", "SELL"
        if efficiency <= threshold["range_efficiency"] and abs(ema_spread_atr) <= threshold["range_ema_spread_atr"]:
            return "RANGE", "WAIT"
        return "TRANSITION", "WAIT"

    def _execution_gate(
        self,
        regime: str,
        regime_direction: str,
        intended_direction: str,
        range_position: float,
        location_guard: Dict[str, Any],
    ) -> tuple[str, str, str]:
        if regime == "VOLATILITY_SHOCK":
            return (
                "BLOCK_VOLATILITY",
                "Closed-candle range or ATR expansion is outside the normal volatility baseline.",
                "Wait for volatility to normalize and a controlled closed-candle retest to form.",
            )
        if intended_direction == "WAIT":
            return (
                "OBSERVE",
                "The market regime is classified, but there is no current intended setup direction.",
                "Continue scanning for a qualified Diamond origin before evaluating direction agreement.",
            )
        if regime_direction in {"BUY", "SELL"} and regime_direction != intended_direction:
            return (
                "BLOCK_DIRECTION_CONFLICT",
                f"The intended {intended_direction} setup conflicts with the {regime.replace('_', ' ').lower()} regime.",
                "Wait for trend structure to transition or for a new setup aligned with the regime.",
            )
        if location_guard.get("status") == "WAIT_OVEREXTENDED":
            return (
                "WAIT_OVEREXTENDED",
                str(location_guard.get("reason")),
                str(location_guard.get("next_trigger")),
            )
        if regime_direction == intended_direction:
            return (
                "OPEN",
                f"The intended {intended_direction} direction agrees with the completed-candle trend regime.",
                "Require the remaining Diamond, data, news, and risk gates before tracking the setup.",
            )
        if regime == "RANGE":
            edge = self.THRESHOLDS["range_edge"]
            at_directional_edge = (
                intended_direction == "BUY" and range_position <= edge
            ) or (
                intended_direction == "SELL" and range_position >= 1.0 - edge
            )
            if at_directional_edge:
                return (
                    "OPEN_RANGE_EDGE",
                    f"The intended {intended_direction} setup is located at the matching outer range edge.",
                    "Require rejection and closed follow-through before treating the range edge as actionable.",
                )
            return (
                "WAIT_RANGE_EDGE",
                "The intended setup is inside the middle of a completed-candle range.",
                f"Wait for price to reach the {'lower' if intended_direction == 'BUY' else 'upper'} 25% range edge.",
            )
        return (
            "WAIT_TRANSITION",
            "Trend and range measurements are not yet aligned into a stable regime.",
            "Wait for EMA direction, efficiency, and volatility to stabilize on closed candles.",
        )

    def _location_guard(
        self,
        intended_direction: str,
        ema_distance_atr: float,
        range_position: float,
    ) -> Dict[str, Any]:
        threshold = self.THRESHOLDS["max_directional_extension_atr"]
        extreme = self.THRESHOLDS["extreme_range_position"]
        if intended_direction not in {"BUY", "SELL"}:
            return {
                "status": "OBSERVE",
                "allows_entry": False,
                "side": "WAIT",
                "directional_extension_atr": 0.0,
                "maximum_extension_atr": threshold,
                "range_position": self._rounded(range_position, 3),
                "reason": "A direction is required before the anti-chase location guard can evaluate price.",
                "next_trigger": "Wait for a qualified directional Diamond origin.",
            }

        directional_extension = ema_distance_atr if intended_direction == "BUY" else -ema_distance_atr
        at_extreme = range_position >= extreme if intended_direction == "BUY" else range_position <= 1.0 - extreme
        overextended = directional_extension > threshold and at_extreme
        side = "BUY_HIGH" if intended_direction == "BUY" and overextended else "SELL_LOW" if overextended else "VALID_LOCATION"
        if overextended:
            edge = "upper" if intended_direction == "BUY" else "lower"
            return {
                "status": "WAIT_OVEREXTENDED",
                "allows_entry": False,
                "side": side,
                "directional_extension_atr": self._rounded(directional_extension, 3),
                "maximum_extension_atr": threshold,
                "range_position": self._rounded(range_position, 3),
                "reason": (
                    f"The {intended_direction} setup is {directional_extension:.2f} ATR from EMA20 "
                    f"at the {edge} range extreme, so chasing is blocked."
                ),
                "next_trigger": "Wait for price to mean-revert, form a controlled retest, and close a new Diamond confirmation.",
            }
        return {
            "status": "PASS",
            "allows_entry": True,
            "side": side,
            "directional_extension_atr": self._rounded(max(0.0, directional_extension), 3),
            "maximum_extension_atr": threshold,
            "range_position": self._rounded(range_position, 3),
            "reason": "Price is not directionally overextended at the completed-candle range extreme.",
            "next_trigger": "Continue through the Diamond confirmation and risk gates.",
        }

    def _strength(
        self,
        regime: str,
        efficiency: float,
        ema_spread_atr: float,
        ema_slope_atr: float,
        volatility_ratio: float,
        latest_range_atr: float,
    ) -> int:
        if regime == "VOLATILITY_SHOCK":
            shock = max(
                volatility_ratio / self.THRESHOLDS["volatility_ratio"],
                latest_range_atr / self.THRESHOLDS["shock_range_atr"],
            )
            return round(min(100.0, shock * 70.0))
        if regime == "RANGE":
            compression = max(0.0, 1.0 - efficiency)
            flatness = max(0.0, 1.0 - abs(ema_spread_atr) / max(self.THRESHOLDS["range_ema_spread_atr"], 1e-9))
            return round(min(100.0, compression * 60.0 + flatness * 40.0))
        trend_score = (
            min(1.0, efficiency) * 45.0
            + min(1.0, abs(ema_spread_atr) / 1.5) * 35.0
            + min(1.0, abs(ema_slope_atr) / 0.12) * 20.0
        )
        if regime == "TRANSITION":
            trend_score *= 0.65
        return round(min(100.0, trend_score))

    @staticmethod
    def _completed_candles(candles: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        unique: Dict[str, Dict[str, Any]] = {}
        for candle in candles or []:
            if not isinstance(candle, dict):
                continue
            if candle.get("is_complete") is False or candle.get("complete") is False or candle.get("is_partial") is True:
                continue
            try:
                opened = float(candle.get("open"))
                high = float(candle.get("high"))
                low = float(candle.get("low"))
                close = float(candle.get("close"))
            except (TypeError, ValueError):
                continue
            if min(opened, high, low, close) <= 0 or high < max(opened, close) or low > min(opened, close):
                continue
            timestamp = candle.get("time") or candle.get("timestamp") or candle.get("datetime")
            if timestamp is None:
                continue
            unique[str(timestamp)] = {
                "time": timestamp,
                "open": opened,
                "high": high,
                "low": low,
                "close": close,
            }
        return sorted(unique.values(), key=lambda row: MarketRegimeEngine._time_value(row["time"]))

    @staticmethod
    def _time_value(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value))
        except (TypeError, ValueError):
            pass
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    @staticmethod
    def _ema(values: List[float], period: int) -> List[float]:
        alpha = 2.0 / (period + 1.0)
        result = [values[0]]
        for value in values[1:]:
            result.append(alpha * value + (1.0 - alpha) * result[-1])
        return result

    @staticmethod
    def _true_ranges(rows: List[Dict[str, Any]]) -> List[float]:
        ranges: List[float] = []
        previous_close = rows[0]["close"]
        for row in rows:
            ranges.append(max(
                row["high"] - row["low"],
                abs(row["high"] - previous_close),
                abs(row["low"] - previous_close),
            ))
            previous_close = row["close"]
        return ranges

    @staticmethod
    def _range_location(position: float) -> str:
        if position <= 0.25:
            return "LOWER_EDGE"
        if position >= 0.75:
            return "UPPER_EDGE"
        return "MID_RANGE"

    @staticmethod
    def _rounded(value: float, digits: int = 5) -> float:
        return round(float(value), digits)
