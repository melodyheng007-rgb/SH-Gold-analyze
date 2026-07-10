from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

import pandas as pd

from .analyzer import GoldAnalyzer


def run_simple_backtest(
    df_m5: pd.DataFrame,
    step_bars: int = 96,
    hold_bars: int = 96,
    max_checks: int = 12,
) -> Dict[str, Any]:
    analyzer = GoldAnalyzer()
    trades: List[Dict[str, Any]] = []
    setup_records: List[Dict[str, Any]] = []
    if len(df_m5) < 800:
        return {
            "summary": _summary([], []) | {"message": "Need more M5 candles for backtest"},
            "trades": [],
        }

    start = max(700, int(len(df_m5) * 0.45))
    end = len(df_m5) - hold_bars - 1
    indexes = list(range(start, end, step_bars))
    if len(indexes) > max_checks:
        stride = max(1, len(indexes) // max_checks)
        indexes = indexes[::stride][:max_checks]

    for i in indexes:
        history = df_m5.iloc[max(0, i - 6000):i].copy()
        result = analyzer.analyze(history, include_chart=False)
        signal = result["signal"]
        setup_records.append({
            "time": str(history.index[-1]),
            "status": signal["status"],
            "setup_type": signal["setup_type"],
            "score": signal["score"],
            "failed_reasons": signal.get("warnings", []),
        })
        if signal["status"] not in ["Valid Setup", "High Quality Setup"]:
            continue
        if signal["direction"] not in ["BUY", "SELL"] or not signal["target_levels"]:
            continue

        entry_low = signal["entry_zone"]["low"]
        entry_high = signal["entry_zone"]["high"]
        entry = (entry_low + entry_high) / 2
        invalidation = signal["invalidation_level"]
        target = signal["target_levels"][0]
        future = df_m5.iloc[i:i + hold_bars]
        outcome = "open"
        exit_price = float(future["close"].iloc[-1])

        for _, row in future.iterrows():
            if signal["direction"] == "BUY":
                if row["low"] <= invalidation:
                    outcome = "loss"
                    exit_price = invalidation
                    break
                if row["high"] >= target:
                    outcome = "win"
                    exit_price = target
                    break
            else:
                if row["high"] >= invalidation:
                    outcome = "loss"
                    exit_price = invalidation
                    break
                if row["low"] <= target:
                    outcome = "win"
                    exit_price = target
                    break

        risk = abs(entry - invalidation)
        pnl_r = 0.0
        if risk > 0:
            pnl_r = (exit_price - entry) / risk if signal["direction"] == "BUY" else (entry - exit_price) / risk

        trades.append({
            "time": str(history.index[-1]),
            "direction": signal["direction"],
            "setup_type": signal["setup_type"],
            "status": signal["status"],
            "score": signal["score"],
            "entry": round(entry, 3),
            "invalidation": invalidation,
            "target": target,
            "outcome": outcome,
            "pnl_r": round(pnl_r, 2),
        })

    return {
        "summary": _summary(trades, setup_records),
        "trades": trades[-100:],
    }


def _summary(trades: List[Dict[str, Any]], setup_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    wins = sum(1 for t in trades if t["outcome"] == "win")
    losses = sum(1 for t in trades if t["outcome"] == "loss")
    total = len(trades)
    gross_r = round(sum(t["pnl_r"] for t in trades), 2)
    winrate = round((wins / total) * 100, 2) if total else 0.0
    gains = sum(t["pnl_r"] for t in trades if t["pnl_r"] > 0)
    losses_r = abs(sum(t["pnl_r"] for t in trades if t["pnl_r"] < 0))
    profit_factor: float | str = 0.0
    if losses_r > 0:
        profit_factor = round(gains / losses_r, 2)
    elif gains > 0:
        profit_factor = "INF"

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in trades:
        equity += trade["pnl_r"]
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)

    setup_stats: Dict[str, Dict[str, float]] = defaultdict(lambda: {"count": 0, "wins": 0, "gross_r": 0.0})
    for trade in trades:
        stats = setup_stats[trade["setup_type"]]
        stats["count"] += 1
        stats["wins"] += 1 if trade["outcome"] == "win" else 0
        stats["gross_r"] += trade["pnl_r"]
    best_setup_type = "None"
    if setup_stats:
        best_setup_type = sorted(
            setup_stats.items(),
            key=lambda item: (item[1]["gross_r"], item[1]["wins"] / item[1]["count"], item[1]["count"]),
            reverse=True,
        )[0][0]
    winrate_by_setup_type = {
        setup_type: round((stats["wins"] / stats["count"]) * 100, 2) if stats["count"] else 0.0
        for setup_type, stats in setup_stats.items()
    }
    failed_reasons: Dict[str, int] = defaultdict(int)
    for setup in setup_records:
        if setup["status"] in ["Valid Setup", "High Quality Setup"]:
            continue
        for reason in setup.get("failed_reasons", [])[:3]:
            failed_reasons[reason] += 1

    return {
        "total_setups": len(setup_records),
        "valid_setups": total,
        "no_trade_count": sum(1 for s in setup_records if s["status"] == "No Trade"),
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "winrate": winrate,
        "gross_r": gross_r,
        "profit_factor": profit_factor,
        "max_drawdown": round(abs(max_drawdown), 2),
        "average_rr": round(sum(abs(t["target"] - t["entry"]) / abs(t["entry"] - t["invalidation"]) for t in trades if abs(t["entry"] - t["invalidation"]) > 0) / total, 2) if total else 0.0,
        "best_setup_type": best_setup_type,
        "best_poi_type": best_setup_type,
        "winrate_by_setup_type": winrate_by_setup_type,
        "failed_setup_reasons": dict(sorted(failed_reasons.items(), key=lambda item: item[1], reverse=True)[:8]),
        "note": "CSV backtest/training only. Not used for live signal generation.",
    }
