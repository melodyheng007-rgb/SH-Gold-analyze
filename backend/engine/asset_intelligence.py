from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

import pandas as pd


class AssetIntelligenceEngine:
    """Asset-specific MTF context gate built only from completed provider candles."""

    VERSION = "PRO_ANALYZE_V5_ASSET_INTELLIGENCE"
    TIMEFRAMES = ("1D", "4H", "1H", "15M", "5M")
    MINIMUM_CANDLES = 55
    PROFILES: Dict[str, Dict[str, Any]] = {
        "XAUUSD": {
            "name": "XAU_PRECISION",
            "weights": {"1D": 24, "4H": 28, "1H": 24, "15M": 16, "5M": 8},
            "required_htf": ("1D", "4H"),
            "trigger_timeframes": ("15M", "5M"),
            "minimum_agreement": 62.0,
            "volatility_lock_ratio": 2.20,
            "shock_range_atr": 2.80,
            "context": "Session-aware gold structure, liquidity, and controlled volatility.",
        },
        "BTCUSD": {
            "name": "BTC_24_7_MOMENTUM",
            "weights": {"1D": 18, "4H": 30, "1H": 27, "15M": 17, "5M": 8},
            "required_htf": ("4H", "1H"),
            "trigger_timeframes": ("15M", "5M"),
            "minimum_agreement": 58.0,
            "volatility_lock_ratio": 2.65,
            "shock_range_atr": 3.40,
            "context": "Continuous 24/7 structure, momentum persistence, and volatility expansion.",
        },
    }

    def evaluate(
        self,
        symbol: str,
        frames: Mapping[str, pd.DataFrame],
        intended_direction: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized = str(symbol or "XAUUSD").upper()
        profile = self.PROFILES.get(normalized, self.PROFILES["XAUUSD"])
        direction = str(intended_direction or "WAIT").upper()
        if direction not in {"BUY", "SELL"}:
            direction = "WAIT"

        snapshots = {
            timeframe: self._timeframe_snapshot(timeframe, frames.get(timeframe), profile)
            for timeframe in self.TIMEFRAMES
        }
        ready = [timeframe for timeframe, snapshot in snapshots.items() if snapshot["status"] == "READY"]
        weights = profile["weights"]
        ready_weight = sum(float(weights[timeframe]) for timeframe in ready)
        signed_vote = sum(
            float(weights[timeframe]) * self._direction_vote(snapshots[timeframe]["direction"])
            for timeframe in ready
        )
        agreement = abs(signed_vote) / ready_weight * 100.0 if ready_weight else 0.0
        consensus = (
            "BULLISH" if signed_vote > 0 and agreement >= 25.0
            else "BEARISH" if signed_vote < 0 and agreement >= 25.0
            else "MIXED"
        )

        expected = "BULLISH" if direction == "BUY" else "BEARISH" if direction == "SELL" else "WAIT"
        opposite = "BEARISH" if expected == "BULLISH" else "BULLISH" if expected == "BEARISH" else "WAIT"
        required_htf = list(profile["required_htf"])
        trigger_timeframes = list(profile["trigger_timeframes"])
        htf_aligned = expected != "WAIT" and all(
            snapshots[timeframe]["status"] == "READY"
            and snapshots[timeframe]["direction"] == expected
            for timeframe in required_htf
        )
        trigger_aligned = expected != "WAIT" and any(
            snapshots[timeframe]["direction"] == expected
            for timeframe in trigger_timeframes
        )
        trigger_conflict = expected != "WAIT" and any(
            snapshots[timeframe]["direction"] == opposite
            for timeframe in trigger_timeframes
        )
        shock_timeframes = [
            timeframe for timeframe in trigger_timeframes
            if snapshots[timeframe].get("regime") == "VOLATILITY_SHOCK"
        ]

        quality_score = round(min(100.0, max(0.0,
            agreement * 0.70
            + (15.0 if htf_aligned else 0.0)
            + (10.0 if trigger_aligned and not trigger_conflict else 0.0)
            + (5.0 if not shock_timeframes else 0.0)
        )))
        gate, reason, next_trigger = self._execution_gate(
            profile,
            ready,
            direction,
            consensus,
            agreement,
            htf_aligned,
            trigger_aligned,
            trigger_conflict,
            shock_timeframes,
        )
        session = self._session_context(normalized, snapshots.get("5M", {}))
        risk_flags = []
        if shock_timeframes:
            risk_flags.append(f"Volatility shock on {', '.join(shock_timeframes)}")
        if expected != "WAIT" and consensus not in {expected, "MIXED"}:
            risk_flags.append(f"MTF consensus conflicts with {direction}")
        if expected != "WAIT" and not htf_aligned:
            risk_flags.append(f"Required {'/'.join(required_htf)} direction is not aligned")
        if trigger_conflict:
            risk_flags.append(f"{'/'.join(trigger_timeframes)} trigger conflict")

        return {
            "status": "READY" if len(ready) == len(self.TIMEFRAMES) else "PARTIAL" if ready else "INSUFFICIENT_DATA",
            "version": self.VERSION,
            "symbol": normalized,
            "profile": profile["name"],
            "profile_context": profile["context"],
            "intended_direction": direction,
            "consensus": consensus,
            "agreement_percent": round(agreement, 1),
            "quality_score": quality_score,
            "execution_gate": gate,
            "allows_execution": gate == "OPEN",
            "reason": reason,
            "next_trigger": next_trigger,
            "required_htf": required_htf,
            "trigger_timeframes": trigger_timeframes,
            "htf_aligned": htf_aligned,
            "trigger_aligned": trigger_aligned,
            "trigger_conflict": trigger_conflict,
            "risk_flags": risk_flags,
            "session_context": session,
            "timeframes": snapshots,
            "ready_timeframes": ready,
            "minimum_agreement": profile["minimum_agreement"],
            "uses_completed_candles_only": True,
            "decision_role": "CONSERVATIVE_GATE_ONLY",
        }

    def waiting(self, symbol: str, reason: str = "Complete MTF candle history is required.") -> Dict[str, Any]:
        normalized = str(symbol or "XAUUSD").upper()
        profile = self.PROFILES.get(normalized, self.PROFILES["XAUUSD"])
        return {
            "status": "INSUFFICIENT_DATA",
            "version": self.VERSION,
            "symbol": normalized,
            "profile": profile["name"],
            "consensus": "WAIT",
            "agreement_percent": 0.0,
            "quality_score": 0,
            "execution_gate": "OBSERVE",
            "allows_execution": False,
            "reason": reason,
            "next_trigger": "Wait for completed 1D, 4H, 1H, 15M, and 5M provider candles.",
            "timeframes": {},
            "uses_completed_candles_only": True,
            "decision_role": "CONSERVATIVE_GATE_ONLY",
        }

    def _timeframe_snapshot(
        self,
        timeframe: str,
        frame: Optional[pd.DataFrame],
        profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        if frame is None or frame.empty:
            return self._waiting_timeframe(timeframe, 0)
        data = frame.copy()
        if "is_complete" in data.columns:
            data = data[pd.to_numeric(data["is_complete"], errors="coerce").fillna(0) == 1]
        for column in ("open", "high", "low", "close"):
            data[column] = pd.to_numeric(data[column], errors="coerce")
        data = data.dropna(subset=["open", "high", "low", "close"])
        data = data[
            (data[["open", "high", "low", "close"]] > 0).all(axis=1)
            & (data["high"] >= data[["open", "close", "low"]].max(axis=1))
            & (data["low"] <= data[["open", "close", "high"]].min(axis=1))
        ].tail(240)
        if len(data) < self.MINIMUM_CANDLES:
            return self._waiting_timeframe(timeframe, len(data))

        close = data["close"]
        high = data["high"]
        low = data["low"]
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        macd_histogram = macd - macd.ewm(span=9, adjust=False).mean()

        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        rsi = (100 - 100 / (1 + gain / loss.mask(loss == 0))).astype(float)
        rsi = rsi.mask((loss == 0) & (gain > 0), 100.0)
        rsi = rsi.mask((gain == 0) & (loss > 0), 0.0).fillna(50.0)

        previous_close = close.shift(1)
        true_range = pd.concat([
            (high - low).abs(),
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ], axis=1).max(axis=1)
        atr14 = true_range.rolling(14, min_periods=14).mean()
        latest_atr = float(atr14.iloc[-1])
        baseline_atr = float(atr14.iloc[-61:-1].median()) if len(atr14.dropna()) > 20 else latest_atr
        safe_atr = max(latest_atr, float(close.iloc[-1]) * 1e-8, 1e-9)
        safe_baseline = max(baseline_atr, float(close.iloc[-1]) * 1e-8, 1e-9)
        volatility_ratio = latest_atr / safe_baseline
        latest_range_atr = float(high.iloc[-1] - low.iloc[-1]) / safe_baseline

        score = 0
        if close.iloc[-1] > ema20.iloc[-1] > ema50.iloc[-1]:
            score += 2
        elif close.iloc[-1] < ema20.iloc[-1] < ema50.iloc[-1]:
            score -= 2
        score += 1 if ema20.iloc[-1] > ema20.iloc[-6] else -1 if ema20.iloc[-1] < ema20.iloc[-6] else 0
        score += 1 if macd_histogram.iloc[-1] > 0 else -1 if macd_histogram.iloc[-1] < 0 else 0
        score += 1 if rsi.iloc[-1] >= 52 else -1 if rsi.iloc[-1] <= 48 else 0
        direction = "BULLISH" if score >= 3 else "BEARISH" if score <= -3 else "NEUTRAL"

        efficiency_close = close.tail(24)
        path = efficiency_close.diff().abs().sum()
        efficiency = abs(float(efficiency_close.iloc[-1] - efficiency_close.iloc[0])) / float(path) if path else 0.0
        range_frame = data.tail(48)
        range_low = float(range_frame["low"].min())
        range_high = float(range_frame["high"].max())
        range_width = max(range_high - range_low, 1e-9)
        range_position = max(0.0, min(1.0, (float(close.iloc[-1]) - range_low) / range_width))

        if volatility_ratio >= profile["volatility_lock_ratio"] or latest_range_atr >= profile["shock_range_atr"]:
            regime = "VOLATILITY_SHOCK"
        elif volatility_ratio <= 0.72:
            regime = "COMPRESSION"
        elif direction != "NEUTRAL" and efficiency >= 0.30:
            regime = "TRENDING"
        elif efficiency <= 0.22:
            regime = "RANGE"
        else:
            regime = "TRANSITION"

        return {
            "status": "READY",
            "timeframe": timeframe,
            "count": len(data),
            "direction": direction,
            "direction_score": score,
            "confidence": round(abs(score) / 5.0 * 100.0),
            "regime": regime,
            "close": self._rounded(close.iloc[-1]),
            "ema_20": self._rounded(ema20.iloc[-1]),
            "ema_50": self._rounded(ema50.iloc[-1]),
            "rsi_14": self._rounded(rsi.iloc[-1], 2),
            "macd_histogram": self._rounded(macd_histogram.iloc[-1], 6),
            "atr_14": self._rounded(latest_atr),
            "atr_percent": self._rounded(latest_atr / float(close.iloc[-1]) * 100.0, 4),
            "volatility_ratio": self._rounded(volatility_ratio, 3),
            "latest_range_atr": self._rounded(latest_range_atr, 3),
            "efficiency_ratio": self._rounded(efficiency, 3),
            "range_position": self._rounded(range_position, 3),
            "latest_complete_time": self._timestamp(data.index[-1]),
        }

    def _execution_gate(
        self,
        profile: Dict[str, Any],
        ready: list[str],
        direction: str,
        consensus: str,
        agreement: float,
        htf_aligned: bool,
        trigger_aligned: bool,
        trigger_conflict: bool,
        shock_timeframes: list[str],
    ) -> tuple[str, str, str]:
        if len(ready) != len(self.TIMEFRAMES):
            return (
                "OBSERVE",
                "All five completed-candle timeframes are required for the asset profile.",
                "Wait for complete 1D, 4H, 1H, 15M, and 5M provider history.",
            )
        if shock_timeframes:
            return (
                "BLOCK_VOLATILITY",
                f"Abnormal volatility is active on {', '.join(shock_timeframes)}.",
                "Wait for ATR and candle range to normalize before a new confirmation.",
            )
        if direction == "WAIT":
            return (
                "OBSERVE",
                "MTF context is ready, but no Diamond setup direction is currently intended.",
                "Wait for a qualified directional Diamond origin.",
            )
        expected = "BULLISH" if direction == "BUY" else "BEARISH"
        if consensus not in {expected, "MIXED"}:
            return (
                "BLOCK_MTF_CONFLICT",
                f"{profile['name']} consensus is {consensus}, which conflicts with {direction}.",
                "Wait for weighted MTF direction to realign with the intended setup.",
            )
        if not htf_aligned:
            return (
                "WAIT_HTF_ALIGNMENT",
                f"Required {'/'.join(profile['required_htf'])} structure is not aligned with {direction}.",
                f"Wait for {'/'.join(profile['required_htf'])} direction agreement.",
            )
        if trigger_conflict or not trigger_aligned:
            return (
                "WAIT_TRIGGER_ALIGNMENT",
                f"{'/'.join(profile['trigger_timeframes'])} momentum has not produced a clean {direction} trigger.",
                f"Wait for {'/'.join(profile['trigger_timeframes'])} pullback and closed-candle confirmation.",
            )
        if agreement < float(profile["minimum_agreement"]):
            return (
                "WAIT_MTF_CONFLUENCE",
                f"Weighted MTF agreement is {agreement:.1f}%, below the {profile['minimum_agreement']:.0f}% profile minimum.",
                "Wait for more timeframes to align without chasing price.",
            )
        return (
            "OPEN",
            f"{profile['name']} MTF direction, volatility, and trigger context agree with {direction}.",
            "Continue through Diamond origin, location, news, and risk gates.",
        )

    @staticmethod
    def _waiting_timeframe(timeframe: str, count: int) -> Dict[str, Any]:
        return {
            "status": "WAITING",
            "timeframe": timeframe,
            "count": count,
            "direction": "WAIT",
            "confidence": 0,
            "regime": "UNKNOWN",
        }

    @staticmethod
    def _direction_vote(direction: str) -> int:
        return 1 if direction == "BULLISH" else -1 if direction == "BEARISH" else 0

    @staticmethod
    def _timestamp(value: Any) -> str:
        try:
            timestamp = pd.Timestamp(value)
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize("UTC")
            else:
                timestamp = timestamp.tz_convert("UTC")
            return timestamp.isoformat()
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _session_context(symbol: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        latest = snapshot.get("latest_complete_time")
        try:
            timestamp = pd.Timestamp(latest)
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize("UTC")
            else:
                timestamp = timestamp.tz_convert("UTC")
        except (TypeError, ValueError):
            timestamp = pd.Timestamp.now(tz="UTC")
        if symbol == "BTCUSD":
            return {
                "market": "GLOBAL_24_7",
                "session": "WEEKEND" if timestamp.dayofweek >= 5 else "WEEKDAY",
                "session_weight": "CONTINUOUS",
                "utc_hour": timestamp.hour,
            }
        if 0 <= timestamp.hour < 7:
            session = "ASIA"
        elif timestamp.hour < 12:
            session = "LONDON"
        elif timestamp.hour < 17:
            session = "NEW_YORK"
        else:
            session = "AFTER_HOURS"
        return {
            "market": "SESSION_BASED",
            "session": session,
            "session_weight": "PRIMARY" if session in {"LONDON", "NEW_YORK"} else "SECONDARY",
            "utc_hour": timestamp.hour,
        }

    @staticmethod
    def _rounded(value: Any, digits: int = 5) -> float:
        return round(float(value), digits)
