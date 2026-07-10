from __future__ import annotations

from typing import List, Tuple
import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def displacement(df: pd.DataFrame, period: int = 14, multiplier: float = 1.2) -> pd.Series:
    body = (df["close"] - df["open"]).abs()
    return body > atr(df, period) * multiplier


def swing_points(df: pd.DataFrame, left: int = 3, right: int = 3) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if len(df) < left + right + 1:
        return df.iloc[0:0], df.iloc[0:0]
    highs = []
    lows = []
    rows = list(df.itertuples())
    for i in range(left, len(df) - right):
        window = df.iloc[i-left:i+right+1]
        row = rows[i]
        if row.high == window["high"].max() and window["high"].idxmax() == df.index[i]:
            highs.append(i)
        if row.low == window["low"].min() and window["low"].idxmin() == df.index[i]:
            lows.append(i)
    return df.iloc[highs].copy(), df.iloc[lows].copy()


def last_n_values(frame: pd.DataFrame, col: str, n: int = 2) -> List[float]:
    if frame is None or len(frame) == 0:
        return []
    return [float(x) for x in frame[col].dropna().tail(n).values]
