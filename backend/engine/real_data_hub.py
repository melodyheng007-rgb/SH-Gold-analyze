from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from .xauusd_provider import (
    MIN_ANALYSIS_CANDLES,
    REAL_CSV_HISTORY_SOURCE,
    SQLiteCandleStore,
    normalize_timeframe,
    validate_analysis_readiness,
)


class CSVImportProService:
    def __init__(self, store: SQLiteCandleStore):
        self.store = store

    def import_real_history(self, csv_path: str, filename: str = "", default_timeframe: str = "15M") -> Dict[str, Any]:
        path = Path(csv_path)
        df = pd.read_csv(path)
        df.columns = [col.strip().lower() for col in df.columns]
        if "time" in df.columns and "timestamp" not in df.columns:
            df = df.rename(columns={"time": "timestamp"})

        imported: Dict[str, int] = {}
        reports: Dict[str, Dict[str, Any]] = {}
        errors: Dict[str, str] = {}
        if "timeframe" in df.columns:
            for raw_tf, group in df.groupby("timeframe"):
                try:
                    tf = normalize_timeframe(str(raw_tf))
                    records, report = self._validate_group(group.drop(columns=["timeframe"]), filename or path.name)
                    imported[tf] = self.store.insert_candles(tf, records, REAL_CSV_HISTORY_SOURCE)
                    reports[tf] = report | {"imported": imported[tf]}
                except Exception as exc:
                    errors[str(raw_tf)] = str(exc)
        else:
            try:
                tf = self._timeframe_from_filename(filename or path.name) or normalize_timeframe(default_timeframe)
                records, report = self._validate_group(df, filename or path.name)
                imported[tf] = self.store.insert_candles(tf, records, REAL_CSV_HISTORY_SOURCE)
                reports[tf] = report | {"imported": imported[tf]}
            except Exception as exc:
                errors[default_timeframe] = str(exc)

        counts = self.store.counts()
        readiness = validate_analysis_readiness(counts)
        latest = self.store.latest_timestamps()
        skipped_bad_rows = sum(int(item.get("skipped_bad_rows", 0)) for item in reports.values())
        duplicate_rows = sum(int(item.get("duplicate_rows", 0)) for item in reports.values())
        return {
            "ok": not errors and bool(imported),
            "status": "REAL_CSV_HISTORY_IMPORTED" if imported else "IMPORT_FAILED",
            "source": REAL_CSV_HISTORY_SOURCE,
            "filename": filename or path.name,
            "imported": imported,
            "reports": reports,
            "errors": errors,
            "skipped_bad_rows": skipped_bad_rows,
            "duplicate_rows": duplicate_rows,
            "latest_candle_time": latest,
            "candle_counts": counts,
            "minimum_required": MIN_ANALYSIS_CANDLES,
            "readiness": readiness,
            "message": "Real XAUUSD history imported." if imported else "No valid XAUUSD candles were imported.",
        }

    def _validate_group(self, df: pd.DataFrame, name: str) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
        required = ["timestamp", "open", "high", "low", "close"]
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(f"{name} missing columns: {', '.join(missing)}")
        original_rows = len(df)
        work = df[required].copy()
        work["timestamp"] = pd.to_datetime(work["timestamp"], errors="coerce", utc=True)
        for col in ["open", "high", "low", "close"]:
            work[col] = pd.to_numeric(work[col], errors="coerce")
        invalid = (
            work["timestamp"].isna()
            | work[["open", "high", "low", "close"]].isna().any(axis=1)
            | (work[["open", "high", "low", "close"]] <= 0).any(axis=1)
            | (work["high"] < work[["open", "close", "low"]].max(axis=1))
            | (work["low"] > work[["open", "close", "high"]].min(axis=1))
        )
        bad_rows = int(invalid.sum())
        work = work[~invalid].sort_values("timestamp")
        duplicate_rows = int(work["timestamp"].duplicated(keep="last").sum())
        work = work.drop_duplicates(subset=["timestamp"], keep="last")
        records = [
            {
                "timestamp": row["timestamp"].isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "tick_count": 0,
            }
            for _, row in work.iterrows()
        ]
        if not records:
            raise ValueError(f"{name} has no valid OHLC rows after validation.")
        return records, {
            "source": REAL_CSV_HISTORY_SOURCE,
            "input_rows": original_rows,
            "valid_rows": len(records),
            "bad_rows": bad_rows,
            "duplicate_rows": duplicate_rows,
            "skipped_bad_rows": original_rows - len(records),
            "sorted_ascending": True,
            "first_candle_time": records[0]["timestamp"],
            "latest_candle_time": records[-1]["timestamp"],
        }

    def _timeframe_from_filename(self, filename: str) -> Optional[str]:
        name = filename.lower()
        mapping = {
            "xauusd_1m": "1M",
            "xauusd_m1": "1M",
            "xauusd_5m": "5M",
            "xauusd_m5": "5M",
            "xauusd_15m": "15M",
            "xauusd_m15": "15M",
            "xauusd_1h": "1H",
            "xauusd_h1": "1H",
            "xauusd_4h": "4H",
            "xauusd_h4": "4H",
            "xauusd_1d": "1D",
            "xauusd_d1": "1D",
        }
        for token, timeframe in mapping.items():
            if token in name:
                return timeframe
        return None
