from __future__ import annotations

from typing import List, Tuple
import pandas as pd
from .indicators import atr, displacement
from .models import Zone


def detect_fvg(df: pd.DataFrame, timeframe: str, max_zones: int = 8) -> List[Zone]:
    zones: List[Zone] = []
    if len(df) < 5:
        return zones
    recent = df.tail(250)
    for i in range(2, len(recent)):
        c0 = recent.iloc[i-2]
        c2 = recent.iloc[i]
        candle_time = recent.index[i]
        if c2["low"] > c0["high"]:
            zones.append(Zone("FVG", "bullish", float(c0["high"]), float(c2["low"]), timeframe, 60, f"Bullish imbalance at {candle_time}"))
        if c2["high"] < c0["low"]:
            zones.append(Zone("FVG", "bearish", float(c2["high"]), float(c0["low"]), timeframe, 60, f"Bearish imbalance at {candle_time}"))
    return zones[-max_zones:]


def detect_order_blocks(df: pd.DataFrame, timeframe: str, max_zones: int = 8) -> List[Zone]:
    zones: List[Zone] = []
    if len(df) < 30:
        return zones
    recent = df.tail(250).copy()
    disp = displacement(recent, 14, 1.15)
    for i in range(3, len(recent)):
        if not bool(disp.iloc[i]):
            continue
        candle = recent.iloc[i]
        direction = "bullish" if candle["close"] > candle["open"] else "bearish"
        lookback = recent.iloc[max(0, i-5):i]
        if direction == "bullish":
            opposite = lookback[lookback["close"] < lookback["open"]]
            if len(opposite):
                ob = opposite.iloc[-1]
                zones.append(Zone("OrderBlock", "bullish", float(min(ob["open"], ob["close"], ob["low"])), float(max(ob["open"], ob["close"], ob["high"])), timeframe, 70, "Last bearish candle before bullish displacement"))
        else:
            opposite = lookback[lookback["close"] > lookback["open"]]
            if len(opposite):
                ob = opposite.iloc[-1]
                zones.append(Zone("OrderBlock", "bearish", float(min(ob["open"], ob["close"], ob["low"])), float(max(ob["open"], ob["close"], ob["high"])), timeframe, 70, "Last bullish candle before bearish displacement"))
    return zones[-max_zones:]


def premium_discount_zone(range_low: float, range_high: float, timeframe: str = "1H") -> Tuple[Zone, Zone, Zone, Zone]:
    mid = (range_low + range_high) / 2
    rng = range_high - range_low
    discount = Zone("Discount", "bullish", range_low, mid, timeframe, 55, "Below equilibrium")
    premium = Zone("Premium", "bearish", mid, range_high, timeframe, 55, "Above equilibrium")
    buy_ote_low = range_high - rng * 0.79
    buy_ote_high = range_high - rng * 0.62
    sell_ote_low = range_low + rng * 0.62
    sell_ote_high = range_low + rng * 0.79
    buy_ote = Zone("OTE", "bullish", buy_ote_low, buy_ote_high, timeframe, 65, "62%-79% retracement discount zone")
    sell_ote = Zone("OTE", "bearish", sell_ote_low, sell_ote_high, timeframe, 65, "62%-79% retracement premium zone")
    return discount, premium, buy_ote, sell_ote


def select_best_zone(zones: List[Zone], direction: str, current_price: float) -> Zone | None:
    candidates = [z for z in zones if z.direction == direction]
    if not candidates:
        return None
    # Prefer zones near current price and stronger score.
    def rank(z: Zone):
        center = (z.low + z.high) / 2
        distance = abs(center - current_price)
        return (distance, -z.strength)
    return sorted(candidates, key=rank)[0]
