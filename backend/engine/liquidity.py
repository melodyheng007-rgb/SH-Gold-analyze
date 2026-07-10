from __future__ import annotations

from typing import List, Optional, Tuple
import pandas as pd
from .indicators import swing_points, atr
from .models import LiquidityResult


def _cluster_equal_levels(values: List[float], tolerance: float) -> List[float]:
    if not values:
        return []
    values = sorted(values)
    clusters: List[List[float]] = [[values[0]]]
    for v in values[1:]:
        if abs(v - clusters[-1][-1]) <= tolerance:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    levels = [round(sum(c) / len(c), 3) for c in clusters if len(c) >= 2]
    return levels[-5:]


def detect_liquidity(df: pd.DataFrame, daily: Optional[pd.DataFrame] = None) -> LiquidityResult:
    if len(df) < 30:
        return LiquidityResult([], [], None, None, None, None)
    recent = df.tail(200)
    tolerance = max(float(atr(recent).iloc[-1]) * 0.18, 0.15)
    highs, lows = swing_points(recent, 3, 3)
    buy_side = _cluster_equal_levels([float(v) for v in highs["high"].tail(30)], tolerance)
    sell_side = _cluster_equal_levels([float(v) for v in lows["low"].tail(30)], tolerance)

    prev_day_high = None
    prev_day_low = None
    if daily is not None and len(daily) >= 2:
        prev_day_high = float(daily["high"].iloc[-2])
        prev_day_low = float(daily["low"].iloc[-2])
        buy_side.append(round(prev_day_high, 3))
        sell_side.append(round(prev_day_low, 3))

    last = recent.iloc[-1]
    recent_sweep = None
    swept_level = None
    all_buy = sorted(set(buy_side))
    all_sell = sorted(set(sell_side))

    for level in reversed(all_buy):
        if last["high"] > level and last["close"] < level:
            recent_sweep = "buy_side_sweep"
            swept_level = float(level)
            break
    if recent_sweep is None:
        for level in all_sell:
            if last["low"] < level and last["close"] > level:
                recent_sweep = "sell_side_sweep"
                swept_level = float(level)
                break

    return LiquidityResult(
        buy_side_levels=sorted(set([round(x, 3) for x in all_buy]))[-6:],
        sell_side_levels=sorted(set([round(x, 3) for x in all_sell]))[:6],
        recent_sweep=recent_sweep,
        swept_level=swept_level,
        previous_day_high=prev_day_high,
        previous_day_low=prev_day_low,
    )


def crt_range(df_1h: pd.DataFrame, lookback: int = 20) -> Tuple[float, float]:
    recent = df_1h.tail(lookback)
    return float(recent["low"].min()), float(recent["high"].max())
