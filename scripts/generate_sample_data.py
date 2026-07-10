from __future__ import annotations

import os
import numpy as np
import pandas as pd


def generate(path: str, seed: int = 77):
    rng = np.random.default_rng(seed)
    periods = 24 * 12 * 35  # 35 days of M5 candles
    times = pd.date_range("2026-05-20", periods=periods, freq="5min")
    price = 2320.0
    rows = []
    for i, t in enumerate(times):
        session_push = 0.0
        if 7 <= t.hour <= 10:  # London activity
            session_push = 0.035
        if 13 <= t.hour <= 16:  # NY activity
            session_push = -0.02
        trend = 0.006 if i < periods * 0.45 else -0.004 if i < periods * 0.75 else 0.003
        shock = rng.normal(0, 0.55)
        open_price = price
        close = price + trend + session_push + shock
        high = max(open_price, close) + abs(rng.normal(0.4, 0.2))
        low = min(open_price, close) - abs(rng.normal(0.4, 0.2))
        volume = int(rng.integers(100, 900))
        rows.append([t, round(open_price, 3), round(high, 3), round(low, 3), round(close, 3), volume])
        price = close
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Wrote {len(df)} candles to {path}")


if __name__ == "__main__":
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    generate(os.path.join(base, "backend", "data", "sample_xauusd_m5.csv"))
