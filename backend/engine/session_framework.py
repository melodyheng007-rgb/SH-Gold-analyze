from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional


class SessionFramework:
    """Transparent session levels inspired by public opening-price concepts."""

    def calculate(
        self,
        daily_candles: Iterable[Dict[str, Any]],
        intraday_candles: Iterable[Dict[str, Any]],
        timeframe_context: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        daily = self._candles(daily_candles)
        intraday = self._candles(intraday_candles)
        context = timeframe_context or {}
        if not intraday:
            return self._empty("NO_INTRADAY_DATA", source)

        latest_time = intraday[-1]["time"]
        session_date = latest_time.date()
        session_rows = [row for row in intraday if row["time"].date() == session_date]
        if not session_rows:
            return self._empty("NO_CURRENT_SESSION", source)

        previous_daily = [row for row in daily if row["time"].date() < session_date]
        if not previous_daily:
            return self._empty("NO_PREVIOUS_SESSION", source)

        previous = previous_daily[-1]
        current_open = session_rows[0]["open"]
        current_price = session_rows[-1]["close"]
        mlp = (previous["open"] + previous["close"]) / 2
        pivot = (previous["high"] + previous["low"] + previous["close"]) / 3
        atr = self._average_true_range(previous_daily, 14)
        if atr is None or atr <= 0:
            return self._empty("NO_DAILY_RANGE", source)

        if current_price > current_open and current_price > mlp:
            position = "ABOVE_OP_AND_MLP"
            position_score = 60
        elif current_price < current_open and current_price < mlp:
            position = "BELOW_OP_AND_MLP"
            position_score = -60
        elif current_price >= current_open:
            position = "ABOVE_OP_MIXED_MLP"
            position_score = 20
        else:
            position = "BELOW_OP_MIXED_MLP"
            position_score = -20

        context_score = self._number(context.get("score")) or 0
        confluence_score = round(max(-100, min(100, position_score * 0.65 + context_score * 0.35)))
        stance = "BULLISH" if confluence_score >= 25 else "BEARISH" if confluence_score <= -25 else "BALANCED"
        half_range = atr * 0.5
        levels = {
            "op": current_open,
            "mlp": mlp,
            "pivot": pivot,
            "k_plus_1": current_open + half_range,
            "k_plus_2": current_open + atr,
            "k_plus_3": current_open + atr * 1.5,
            "k_minus_1": current_open - half_range,
            "k_minus_2": current_open - atr,
            "k_minus_3": current_open - atr * 1.5,
            "dr_plus_1": current_open + half_range,
            "dr_plus_2": current_open + atr,
            "dr_minus_1": current_open - half_range,
            "dr_minus_2": current_open - atr,
        }
        k_trend = self._k_trend(intraday, current_open, mlp, levels)
        return {
            "status": "READY",
            "scope": "CONTEXT_CONFIRMATION_ONLY",
            "source": source,
            "session_date": session_date.isoformat(),
            "current_price": round(current_price, 5),
            "previous_session": {
                "time": previous["time"].isoformat(),
                "open": round(previous["open"], 5),
                "high": round(previous["high"], 5),
                "low": round(previous["low"], 5),
                "close": round(previous["close"], 5),
            },
            "levels": {key: round(value, 5) for key, value in levels.items()},
            "daily_atr_14": round(atr, 5),
            "position": position,
            "stance": stance,
            "position_score": position_score,
            "timeframe_score": round(context_score),
            "confluence_score": confluence_score,
            "buy_context": bool(stance == "BULLISH" and current_price < levels["dr_plus_2"]),
            "sell_context": bool(stance == "BEARISH" and current_price > levels["dr_minus_2"]),
            "range_extension": bool(current_price >= levels["dr_plus_2"] or current_price <= levels["dr_minus_2"]),
            "k_trend": k_trend,
            "k_range": {
                "status": "READY",
                "name": "SH_K_RANGE",
                "step_atr": 0.5,
                "next_target": k_trend.get("next_target"),
                "next_target_label": k_trend.get("next_target_label"),
                "scope": "VOLATILITY_TARGET_AND_TREND_CONTEXT_ONLY",
            },
            "formulas": {
                "op": "First completed 5M candle open of the current UTC session",
                "mlp": "(previous session open + previous session close) / 2",
                "pivot": "(previous session high + low + close) / 3",
                "daily_range": "14-session average true range; SH K1 = 0.5 ATR, K2 = 1.0 ATR, K3 = 1.5 ATR from OP",
                "k_trend": "EMA13/EMA34 alignment + ATR-normalized 5-bar slope + 10-bar price efficiency + OP/MLP position, completed candles only",
            },
            "proprietary_formula_claimed": False,
        }

    def _average_true_range(self, candles: list[Dict[str, Any]], period: int) -> Optional[float]:
        selected = candles[-(period + 1):]
        if len(selected) < 2:
            return None
        ranges = []
        for previous, current in zip(selected, selected[1:]):
            ranges.append(max(
                current["high"] - current["low"],
                abs(current["high"] - previous["close"]),
                abs(current["low"] - previous["close"]),
            ))
        return sum(ranges) / len(ranges) if ranges else None

    def _k_trend(
        self,
        candles: list[Dict[str, Any]],
        session_open: float,
        mlp: float,
        levels: Dict[str, float],
    ) -> Dict[str, Any]:
        selected = candles[-120:]
        if len(selected) < 35:
            return {
                "status": "WARMING_UP",
                "engine": "SH_K_RANGE_TREND_V1",
                "regime": "WAITING",
                "score": 0,
                "strength": 0,
                "confirmation": "WAITING",
                "next_target": None,
                "next_target_label": None,
                "completed_candles_used": len(selected),
                "trade_direction_created": False,
            }

        closes = [row["close"] for row in selected]
        fast = self._ema(closes, 13)
        slow = self._ema(closes, 34)
        intraday_atr = self._average_true_range(selected, 14)
        if intraday_atr is None or intraday_atr <= 0:
            return {
                "status": "NO_INTRADAY_RANGE",
                "engine": "SH_K_RANGE_TREND_V1",
                "regime": "WAITING",
                "score": 0,
                "strength": 0,
                "confirmation": "WAITING",
                "next_target": None,
                "next_target_label": None,
                "completed_candles_used": len(selected),
                "trade_direction_created": False,
            }

        current = selected[-1]
        current_price = current["close"]
        position_vote = 30 if current_price > session_open and current_price > mlp else -30 if current_price < session_open and current_price < mlp else 10 if current_price >= session_open else -10
        ema_vote = 30 if fast[-1] > slow[-1] else -30 if fast[-1] < slow[-1] else 0
        slope_ratio = (fast[-1] - fast[-6]) / intraday_atr
        slope_vote = max(-20, min(20, slope_ratio * 20))
        net_change = closes[-1] - closes[-11]
        path = sum(abs(right - left) for left, right in zip(closes[-11:-1], closes[-10:]))
        efficiency = abs(net_change) / path if path > 0 else 0
        efficiency_vote = (20 if net_change > 0 else -20 if net_change < 0 else 0) * min(1.0, efficiency / 0.45)
        score = round(max(-100, min(100, position_vote + ema_vote + slope_vote + efficiency_vote)))
        if score >= 45 and fast[-1] > slow[-1] and current_price > session_open:
            regime = "BULLISH"
        elif score <= -45 and fast[-1] < slow[-1] and current_price < session_open:
            regime = "BEARISH"
        else:
            regime = "RANGE"
        candle_direction = "BULLISH" if current["close"] > current["open"] else "BEARISH" if current["close"] < current["open"] else "NEUTRAL"
        confirmed = bool(
            (regime == "BULLISH" and candle_direction == "BULLISH" and current_price > fast[-1])
            or (regime == "BEARISH" and candle_direction == "BEARISH" and current_price < fast[-1])
        )
        next_label, next_target = self._next_k_target(current_price, regime, levels)
        return {
            "status": "READY",
            "engine": "SH_K_RANGE_TREND_V1",
            "regime": regime,
            "score": score,
            "strength": abs(score),
            "confirmation": "CONFIRMED" if confirmed else "WAIT_CLOSED_CANDLE",
            "current_candle_direction": candle_direction,
            "ema_13": round(fast[-1], 5),
            "ema_34": round(slow[-1], 5),
            "slope_atr": round(slope_ratio, 3),
            "price_efficiency_10": round(efficiency, 3),
            "next_target": round(next_target, 5) if next_target is not None else None,
            "next_target_label": next_label,
            "completed_candles_used": len(selected),
            "uses_completed_candles_only": True,
            "scope": "TREND_CONFIRMATION_AND_TARGET_CONTEXT_ONLY",
            "trade_direction_created": False,
        }

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float]:
        alpha = 2 / (period + 1)
        result = [values[0]]
        for value in values[1:]:
            result.append(value * alpha + result[-1] * (1 - alpha))
        return result

    @staticmethod
    def _next_k_target(price: float, regime: str, levels: Dict[str, float]) -> tuple[Optional[str], Optional[float]]:
        if regime == "BULLISH":
            candidates = [(f"K+{index}", levels[f"k_plus_{index}"]) for index in range(1, 4)]
            return next(((label, level) for label, level in candidates if level > price), (None, None))
        if regime == "BEARISH":
            candidates = [(f"K-{index}", levels[f"k_minus_{index}"]) for index in range(1, 4)]
            return next(((label, level) for label, level in candidates if level < price), (None, None))
        return None, None

    def _candles(self, candles: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
        normalized = []
        for item in candles or []:
            if item.get("is_complete") is False or item.get("is_partial") is True:
                continue
            timestamp = self._datetime(item.get("time") or item.get("timestamp"))
            values = [self._number(item.get(key)) for key in ("open", "high", "low", "close")]
            if timestamp is None or any(value is None for value in values):
                continue
            open_value, high, low, close = values
            if min(open_value, high, low, close) <= 0 or high < max(open_value, low, close) or low > min(open_value, high, close):
                continue
            normalized.append({"time": timestamp, "open": open_value, "high": high, "low": low, "close": close})
        return sorted(normalized, key=lambda row: row["time"])

    @staticmethod
    def _empty(status: str, source: Optional[str]) -> Dict[str, Any]:
        return {
            "status": status,
            "scope": "CONTEXT_CONFIRMATION_ONLY",
            "source": source,
            "levels": {},
            "stance": "WAITING",
            "confluence_score": 0,
            "buy_context": False,
            "sell_context": False,
            "range_extension": False,
            "k_trend": {
                "status": "WAITING",
                "engine": "SH_K_RANGE_TREND_V1",
                "regime": "WAITING",
                "score": 0,
                "confirmation": "WAITING",
                "trade_direction_created": False,
            },
            "proprietary_formula_claimed": False,
        }

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
