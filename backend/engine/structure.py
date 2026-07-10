from __future__ import annotations

from typing import Optional
import pandas as pd
from .indicators import swing_points, last_n_values
from .models import StructureResult


def detect_structure(df: pd.DataFrame, timeframe: str, swing_left: int = 3, swing_right: int = 3) -> StructureResult:
    if len(df) < 20:
        return StructureResult(timeframe, "neutral", None, None, None, None, None, None, "Not enough candles")

    highs, lows = swing_points(df, swing_left, swing_right)
    sh = last_n_values(highs, "high", 2)
    sl = last_n_values(lows, "low", 2)
    last_high = sh[-1] if len(sh) >= 1 else None
    prev_high = sh[-2] if len(sh) >= 2 else None
    last_low = sl[-1] if len(sl) >= 1 else None
    prev_low = sl[-2] if len(sl) >= 2 else None

    trend = "neutral"
    if len(sh) >= 2 and len(sl) >= 2:
        if last_high > prev_high and last_low > prev_low:
            trend = "bullish"
        elif last_high < prev_high and last_low < prev_low:
            trend = "bearish"

    recent_close = float(df["close"].iloc[-1])
    bos: Optional[str] = None
    choch: Optional[str] = None

    if prev_high is not None and recent_close > prev_high:
        bos = "bullish"
        if trend == "bearish":
            choch = "bullish"
    if prev_low is not None and recent_close < prev_low:
        bos = "bearish"
        if trend == "bullish":
            choch = "bearish"

    parts = []
    if last_high and prev_high:
        parts.append("HH" if last_high > prev_high else "LH")
    if last_low and prev_low:
        parts.append("HL" if last_low > prev_low else "LL")
    description = f"{timeframe} trend={trend}; " + ", ".join(parts)
    if bos:
        description += f"; BOS={bos}"
    if choch:
        description += f"; CHOCH={choch}"

    return StructureResult(
        timeframe=timeframe,
        trend=trend,
        last_swing_high=last_high,
        last_swing_low=last_low,
        previous_swing_high=prev_high,
        previous_swing_low=prev_low,
        bos=bos,
        choch=choch,
        description=description,
    )
