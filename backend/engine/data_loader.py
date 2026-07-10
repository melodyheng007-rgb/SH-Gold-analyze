from __future__ import annotations

import os
from typing import Any, Dict
import pandas as pd

REQUIRED_COLUMNS = ["time", "open", "high", "low", "close"]
TIMEFRAME_ORDER = ["1D", "4H", "1H", "15M", "5M"]


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"OHLCV data missing required column: {col}")
    if "volume" not in df.columns:
        df["volume"] = 0
    df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=False)
    df = df.dropna(subset=["time"]).sort_values("time")
    numeric_cols = ["open", "high", "low", "close", "volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df.drop_duplicates(subset=["time"]).set_index("time")


def load_ohlcv(csv_path: str) -> pd.DataFrame:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV data file not found: {csv_path}")
    df = pd.read_csv(csv_path)
    return normalize_ohlcv(df)


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })
    return out.dropna(subset=["open", "high", "low", "close"])


def build_timeframes(df_m5: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    return {
        "5M": df_m5.copy(),
        "15M": resample_ohlcv(df_m5, "15min"),
        "1H": resample_ohlcv(df_m5, "1h"),
        "4H": resample_ohlcv(df_m5, "4h"),
        "1D": resample_ohlcv(df_m5, "1D"),
    }


def candles_to_records(df: pd.DataFrame, limit: int = 500) -> list[Dict[str, Any]]:
    records: list[Dict[str, Any]] = []
    for time, row in df.tail(limit).iterrows():
        timestamp = pd.Timestamp(time)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        record = {
            "time": int(timestamp.timestamp()),
            "open": round(float(row["open"]), 3),
            "high": round(float(row["high"]), 3),
            "low": round(float(row["low"]), 3),
            "close": round(float(row["close"]), 3),
            "volume": float(row.get("volume", 0)),
        }
        for optional in ["source", "is_complete", "is_partial", "tick_count", "confidence"]:
            if optional in row:
                value = row.get(optional)
                if optional in ["is_complete", "is_partial"]:
                    value = bool(value)
                elif optional == "tick_count":
                    value = int(value)
                record[optional] = value
        records.append(record)
    return records
