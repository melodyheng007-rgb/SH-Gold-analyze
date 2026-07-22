from __future__ import annotations

from math import sqrt
from typing import Any, Dict, Iterable, Optional


class SMTModelEngine:
    """Confirm a setup with synchronized, positively-correlated companion candles."""

    VERSION = "SH_SMT_V1_MATCHED_COMPANION"
    MIN_MATCHED_CANDLES = 42
    DIVERGENCE_CONFIDENCE_FLOOR = 66
    COMPANIONS = {
        "XAUUSD": {"symbol": "XAGUSD", "provider_symbol": "OANDA:XAGUSD"},
        "BTCUSD": {"symbol": "ETHUSD", "provider_symbol": "BINANCE:ETHUSDT"},
    }

    def evaluate(
        self,
        symbol: str,
        timeframe: str,
        primary_candles: Iterable[Dict[str, Any]],
        companion_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_symbol = str(symbol or "UNKNOWN").upper()
        companion = dict(companion_snapshot or {})
        metadata = self.COMPANIONS.get(normalized_symbol)
        base = {
            "engine": self.VERSION,
            "symbol": normalized_symbol,
            "timeframe": str(timeframe or "-").upper(),
            "companion_symbol": companion.get("companion_symbol") or (metadata or {}).get("symbol"),
            "companion_provider_symbol": companion.get("provider_symbol") or (metadata or {}).get("provider_symbol"),
            "creates_diamond_zone": False,
            "uses_completed_candles_only": True,
            "scope": "CONFIRMATION_AND_CONFLICT_VETO_ONLY",
        }
        if metadata is None:
            return base | self._unavailable("UNSUPPORTED_SYMBOL", "No verified SMT companion is configured for this market.")
        if str(companion.get("status") or "").upper() != "READY":
            reason = companion.get("reason") or companion.get("message") or "The verified companion feed is not ready."
            return base | self._unavailable(str(companion.get("status") or "UNAVAILABLE"), str(reason))

        primary = self._candles(primary_candles)
        secondary = self._candles(companion.get("candles") or [])
        primary_by_time = {row["time"]: row for row in primary}
        secondary_by_time = {row["time"]: row for row in secondary}
        matched_times = sorted(set(primary_by_time).intersection(secondary_by_time))
        coverage_denominator = max(1, min(len(primary), len(secondary)))
        coverage = len(matched_times) / coverage_denominator
        if len(matched_times) < self.MIN_MATCHED_CANDLES or coverage < 0.72:
            return base | {
                **self._unavailable(
                    "INSUFFICIENT_MATCHED_CANDLES",
                    "SMT is waiting for enough timestamp-matched completed candles.",
                ),
                "matched_candles": len(matched_times),
                "coverage": round(coverage, 3),
            }

        matched_times = matched_times[-180:]
        left = [primary_by_time[value] for value in matched_times]
        right = [secondary_by_time[value] for value in matched_times]
        window = 10 if len(left) >= 70 else 8
        correlation = self._correlation(self._returns(left[:-window]), self._returns(right[:-window]))
        latest_matched_time = matched_times[-1]
        if correlation < 0.18:
            return base | {
                "status": "READY",
                "state": "CORRELATION_WEAK",
                "direction": "WAIT",
                "confidence": 0,
                "execution_gate": "NEUTRAL",
                "reason": "The companion feed is synchronized, but current correlation is too weak for an SMT decision.",
                "matched_candles": len(matched_times),
                "coverage": round(coverage, 3),
                "correlation": round(correlation, 3),
                "latest_matched_time": latest_matched_time,
                "evidence": [],
            }

        prior_left, recent_left = left[-window * 2:-window], left[-window:]
        prior_right, recent_right = right[-window * 2:-window], right[-window:]
        left_atr = self._atr(left[-40:])
        right_atr = self._atr(right[-40:])
        left_high_break = self._break_strength(prior_left, recent_left, "high", left_atr)
        right_high_break = self._break_strength(prior_right, recent_right, "high", right_atr)
        left_low_break = self._break_strength(prior_left, recent_left, "low", left_atr)
        right_low_break = self._break_strength(prior_right, recent_right, "low", right_atr)

        bearish_gap = self._divergence_gap(left_high_break, right_high_break)
        bullish_gap = self._divergence_gap(left_low_break, right_low_break)
        evidence = [
            {
                "id": "HIGH_CONFIRMATION",
                "primary_break_atr": round(left_high_break, 3),
                "companion_break_atr": round(right_high_break, 3),
            },
            {
                "id": "LOW_CONFIRMATION",
                "primary_break_atr": round(left_low_break, 3),
                "companion_break_atr": round(right_low_break, 3),
            },
        ]
        divergence_floor = 0.16
        if bearish_gap >= divergence_floor and bearish_gap > bullish_gap * 1.15:
            state, direction, gap = "BEARISH_DIVERGENCE", "SELL", bearish_gap
            reason = "One correlated market made a meaningful higher high while the other failed to confirm it."
        elif bullish_gap >= divergence_floor and bullish_gap > bearish_gap * 1.15:
            state, direction, gap = "BULLISH_DIVERGENCE", "BUY", bullish_gap
            reason = "One correlated market made a meaningful lower low while the other failed to confirm it."
        else:
            state, direction, gap = "TREND_CONFIRMED", "WAIT", max(bearish_gap, bullish_gap)
            reason = "The synchronized companion market confirms the current structural expansion; no SMT divergence is active."

        confidence = 0
        gate = "NEUTRAL"
        if direction in {"BUY", "SELL"}:
            confidence = int(max(50, min(92, 54 + gap * 52 + max(0.0, correlation) * 12)))
            gate = "DIVERGENCE_READY" if confidence >= self.DIVERGENCE_CONFIDENCE_FLOOR else "NEUTRAL"
        return base | {
            "status": "READY",
            "state": state,
            "direction": direction,
            "confidence": confidence,
            "execution_gate": gate,
            "reason": reason,
            "matched_candles": len(matched_times),
            "coverage": round(coverage, 3),
            "correlation": round(correlation, 3),
            "latest_matched_time": latest_matched_time,
            "evidence": evidence,
            "source_status": companion.get("source_status") or "MATCHED_COMPANION",
        }

    def apply_to_key_zones(self, key_zones: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
        key_zones["smt_model"] = model
        direction = str(model.get("direction") or "WAIT").upper()
        confidence = int(model.get("confidence") or 0)
        active = (
            model.get("status") == "READY"
            and model.get("execution_gate") == "DIVERGENCE_READY"
            and direction in {"BUY", "SELL"}
            and confidence >= self.DIVERGENCE_CONFIDENCE_FLOOR
        )

        def annotate(zone: Dict[str, Any]) -> None:
            side = str(zone.get("entry_side") or "WAIT").upper()
            if not active or side not in {"BUY", "SELL"}:
                alignment, gate = "NEUTRAL", "NEUTRAL"
            elif side == direction:
                alignment, gate = "ALIGNED", "CONFIRM"
            else:
                alignment, gate = "CONFLICT", "BLOCK_CONFLICT"
            zone["smt_alignment"] = alignment
            zone["smt_execution_gate"] = gate
            zone["smt_companion"] = model.get("companion_symbol")
            zone["smt_confidence"] = confidence

        seen: set[int] = set()
        for name in ("zones", "visible_zones", "live_zones"):
            for zone in key_zones.get(name) or []:
                if id(zone) in seen:
                    continue
                annotate(zone)
                seen.add(id(zone))
        primary = key_zones.get("primary_zone") or {}
        if primary and id(primary) not in seen:
            annotate(primary)
        key_zones["smt_state"] = model.get("state")
        key_zones["smt_direction"] = direction
        key_zones["smt_execution_gate"] = primary.get("smt_execution_gate") if primary else "NEUTRAL"
        return key_zones

    @staticmethod
    def _unavailable(status: str, reason: str) -> Dict[str, Any]:
        return {
            "status": status if status in {"FETCHING", "INSUFFICIENT_MATCHED_CANDLES"} else "UNAVAILABLE",
            "source_status": status,
            "state": "WAITING_COMPANION",
            "direction": "WAIT",
            "confidence": 0,
            "execution_gate": "NEUTRAL",
            "reason": reason,
            "matched_candles": 0,
            "coverage": 0.0,
            "correlation": None,
            "latest_matched_time": None,
            "evidence": [],
        }

    @classmethod
    def _candles(cls, values: Iterable[Dict[str, Any]]) -> list[Dict[str, float | int]]:
        rows: list[Dict[str, float | int]] = []
        for value in values or []:
            if value.get("is_complete") is False or value.get("is_partial") is True:
                continue
            timestamp = value.get("time") or value.get("timestamp")
            try:
                if isinstance(timestamp, str):
                    from pandas import Timestamp

                    time_value = int(Timestamp(timestamp).timestamp())
                else:
                    time_value = int(float(timestamp))
                    if time_value > 10_000_000_000:
                        time_value //= 1000
                row = {
                    "time": time_value,
                    "open": float(value["open"]),
                    "high": float(value["high"]),
                    "low": float(value["low"]),
                    "close": float(value["close"]),
                }
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]:
                rows.append(row)
        rows.sort(key=lambda item: int(item["time"]))
        return list({int(item["time"]): item for item in rows}.values())

    @staticmethod
    def _returns(rows: list[Dict[str, float | int]]) -> list[float]:
        closes = [float(row["close"]) for row in rows]
        return [(right - left) / max(abs(left), 1e-12) for left, right in zip(closes, closes[1:])]

    @staticmethod
    def _correlation(left: list[float], right: list[float]) -> float:
        size = min(len(left), len(right))
        if size < 10:
            return 0.0
        x, y = left[-size:], right[-size:]
        x_mean, y_mean = sum(x) / size, sum(y) / size
        numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
        x_var = sum((a - x_mean) ** 2 for a in x)
        y_var = sum((b - y_mean) ** 2 for b in y)
        denominator = sqrt(x_var * y_var)
        return numerator / denominator if denominator else 0.0

    @staticmethod
    def _atr(rows: list[Dict[str, float | int]]) -> float:
        if not rows:
            return 1e-9
        ranges: list[float] = []
        previous = float(rows[0]["close"])
        for row in rows:
            high, low = float(row["high"]), float(row["low"])
            ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
            previous = float(row["close"])
        return max(sum(ranges[-14:]) / min(14, len(ranges)), 1e-9)

    @staticmethod
    def _break_strength(
        prior: list[Dict[str, float | int]],
        recent: list[Dict[str, float | int]],
        edge: str,
        atr: float,
    ) -> float:
        if edge == "high":
            move = max(float(row["high"]) for row in recent) - max(float(row["high"]) for row in prior)
        else:
            move = min(float(row["low"]) for row in prior) - min(float(row["low"]) for row in recent)
        return move / max(atr, 1e-9)

    @staticmethod
    def _divergence_gap(left: float, right: float) -> float:
        left_strength = max(left, 0.0)
        right_strength = max(right, 0.0)
        if max(left_strength, right_strength) <= 0.15:
            return 0.0
        gap = abs(left_strength - right_strength)
        return gap if gap >= 0.16 else 0.0
