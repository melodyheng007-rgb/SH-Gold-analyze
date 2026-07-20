from __future__ import annotations

import base64
import ctypes
import ipaddress
import json
import os
import random
import socket
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import requests
import urllib3
from requests.certs import where as requests_ca_bundle
from urllib.parse import urlencode

from .data_loader import candles_to_records, load_ohlcv

SYMBOL = "XAUUSD"
PROVIDER_NAME = "Gold-API.com Free Live Price"
GOLD_API_COM_PROVIDER_NAME = "Gold-API.com Free Live Price"
GOLD_API_IO_PROVIDER_NAME = "GoldAPI.io"
PRELOADED_SOURCE = "PRELOADED_HISTORY"
LIVE_SOURCE = "GOLD_API_COM_LIVE_PRICE"
LIVE_BUILDER_SOURCE = "LIVE_BUILDER"
CSV_SOURCE = "CSV_IMPORT"
WARMUP_SOURCE = "PROVIDER_WARMUP"
TEST_HISTORY_SOURCE = "TEST_HISTORY"
TEST_HISTORY_LIVE_ANCHORED_SOURCE = "TEST_HISTORY_LIVE_ANCHORED"
RECENT_CSV_SOURCE = "RECENT_CSV_HISTORY"
USER_RECENT_CSV_SOURCE = "USER_RECENT_CSV"
REAL_CSV_HISTORY_SOURCE = "REAL_CSV_HISTORY"
ARCHIVED_STALE_SOURCE = "ARCHIVED_STALE_HISTORY"
TWELVE_DATA_HISTORY_SOURCE = "TWELVE_DATA_REAL_HISTORY"
OANDA_HISTORY_SOURCE = "OANDA_XAUUSD_REAL_HISTORY"
BINANCE_HISTORY_SOURCE = "BINANCE_BTCUSDT_REAL_HISTORY"
SOURCE_NAME = LIVE_SOURCE
LIVE_HISTORY_WARNING = "Live candle builder is running, but not enough candle history for full multi-timeframe analysis yet."
NO_LIVE_CANDLES_MESSAGE = "No live XAUUSD candle data available. Please check API key, provider limit, or connection."
HISTORY_GAP_WARNING = "Historical candle cache is loaded, but there is a gap before the current live candle."
NO_HISTORY_FILES_MESSAGE = "Preloaded history files are missing. Please add CSV files to backend/data/xauusd_history."
SUPPORTED_TIMEFRAMES = ["1M", "5M", "15M", "1H", "4H", "1D"]
ANALYSIS_TIMEFRAMES = ["5M", "15M", "1H", "4H", "1D"]
MIN_ANALYSIS_CANDLES = {"5M": 100, "15M": 100, "1H": 100, "4H": 50, "1D": 30}
REAL_RECENT_SOURCES = {
    RECENT_CSV_SOURCE,
    USER_RECENT_CSV_SOURCE,
    REAL_CSV_HISTORY_SOURCE,
    PRELOADED_SOURCE,
    WARMUP_SOURCE,
    TWELVE_DATA_HISTORY_SOURCE,
    OANDA_HISTORY_SOURCE,
    BINANCE_HISTORY_SOURCE,
}
TEST_HISTORY_SOURCES = {TEST_HISTORY_SOURCE, TEST_HISTORY_LIVE_ANCHORED_SOURCE}
HISTORY_SOURCES = REAL_RECENT_SOURCES | TEST_HISTORY_SOURCES
LIVE_SOURCES = {LIVE_SOURCE, LIVE_BUILDER_SOURCE}
AGGREGATION = {"5M": 5, "15M": 15, "1H": 60, "4H": 240, "1D": 1440}
TIMEFRAME_MINUTES = {"1M": 1, "5M": 5, "15M": 15, "1H": 60, "4H": 240, "1D": 1440}
HEALTHY_CANDLE_MINIMUMS = {"1M": 50, "5M": 50, "15M": 40, "1H": 30, "4H": 20, "1D": 10}
TABLES = {
    "1M": "candles_1m",
    "5M": "candles_5m",
    "15M": "candles_15m",
    "1H": "candles_1h",
    "4H": "candles_4h",
    "1D": "candles_1d",
}

DPAPI_PREFIX = "dpapi:"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_ulong),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _windows_protect_secret(value: str) -> Optional[str]:
    if os.name != "nt" or not value:
        return None
    raw = value.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    protected = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "SH Market Analyzer OANDA credential",
        None,
        None,
        None,
        0x01,
        ctypes.byref(protected),
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(protected.pbData, protected.cbData)
        return DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(protected.pbData)


def _windows_unprotect_secret(value: str) -> Optional[str]:
    if os.name != "nt" or not value.startswith(DPAPI_PREFIX):
        return None
    raw = base64.b64decode(value[len(DPAPI_PREFIX):])
    buffer = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    unprotected = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        0x01,
        ctypes.byref(unprotected),
    ):
        raise ctypes.WinError()
    try:
        decrypted = ctypes.string_at(unprotected.pbData, unprotected.cbData)
        return decrypted.decode("utf-8")
    finally:
        kernel32.LocalFree(unprotected.pbData)


class ProviderSettings:
    def __init__(self, settings_path: str):
        self.settings_path = Path(settings_path)
        self._lock = threading.RLock()
        self._migrate_oanda_token()

    def get(self, name: str) -> str:
        env_name = {
            "goldapi_key": "GOLDAPI_KEY",
            "goldapi_io_key": "GOLDAPI_IO_KEY",
            "oanda_api_token": "OANDA_API_TOKEN",
        }.get(name, name.upper())
        value = os.getenv(env_name)
        if value:
            return value.strip()
        data = self._load()
        if name == "oanda_api_token":
            protected = str(data.get("oanda_api_token_protected") or "").strip()
            if protected:
                try:
                    return str(_windows_unprotect_secret(protected) or "").strip()
                except Exception:
                    return ""
        return str(data.get(name, "")).strip()

    def update(self, values: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self._load_unlocked()
            for key in ["goldapi_key", "goldapi_io_key", "twelve_data_api_key", "oanda_api_token"]:
                value = str(values.get(key, "")).strip()
                if value:
                    if key == "oanda_api_token":
                        self._store_oanda_token(data, value)
                    else:
                        data[key] = value
            if "oanda_environment" in values:
                environment = str(values.get("oanda_environment") or "practice").strip().lower()
                data["oanda_environment"] = environment if environment in {"practice", "live"} else "practice"
            if "test_mode_enabled" in values:
                data["test_mode_enabled"] = bool(values.get("test_mode_enabled"))
            if "data_mode" in values:
                data["data_mode"] = str(values.get("data_mode", "")).strip().upper()
            if "show_stale_history" in values:
                data["show_stale_history"] = bool(values.get("show_stale_history"))
            self._write_unlocked(data)
        return self.masked_status()

    def save_verified_oanda(self, token: str, environment: str, verified_at: Optional[str] = None) -> Dict[str, Any]:
        access_token = str(token or "").strip()
        if not access_token:
            raise ValueError("A verified OANDA token is required before it can be saved.")
        selected_environment = str(environment or "practice").strip().lower()
        if selected_environment not in {"practice", "live"}:
            selected_environment = "practice"
        with self._lock:
            data = self._load_unlocked()
            data.update({
                "oanda_environment": selected_environment,
                "oanda_verified_at": verified_at or datetime.now(timezone.utc).isoformat(),
            })
            self._store_oanda_token(data, access_token)
            self._write_unlocked(data)
        return self.masked_status()

    def mark_oanda_verified(self, verified_at: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            data = self._load_unlocked()
            if not self.get("oanda_api_token"):
                return self.masked_status()
            data["oanda_verified_at"] = verified_at or datetime.now(timezone.utc).isoformat()
            self._write_unlocked(data)
        return self.masked_status()

    def masked_status(self) -> Dict[str, Any]:
        token_saved = bool(self.get("oanda_api_token"))
        verified_at = self.get("oanda_verified_at") or None
        return {
            "gold_api_com_key_required": False,
            "goldapi_io_key": bool(self.get("goldapi_io_key") or self.get("goldapi_key")),
            "twelve_data_api_key": bool(self.get("twelve_data_api_key")),
            "oanda_api_token": token_saved,
            "oanda_environment": self.get("oanda_environment") or "practice",
            "oanda_credential_state": "VERIFIED" if token_saved and verified_at else "SAVED" if token_saved else "NOT_CONFIGURED",
            "oanda_verified_at": verified_at,
            "test_mode_enabled": self.test_mode_enabled(),
            "data_mode": self.data_mode(),
            "show_stale_history": self.show_stale_history(),
        }

    def set_test_mode(self, enabled: bool) -> Dict[str, bool]:
        with self._lock:
            data = self._load_unlocked()
            data["test_mode_enabled"] = bool(enabled)
            self._write_unlocked(data)
        return self.masked_status()

    def test_mode_enabled(self) -> bool:
        return bool(self._load().get("test_mode_enabled", False))

    def set_data_mode(self, mode: str) -> Dict[str, Any]:
        with self._lock:
            data = self._load_unlocked()
            data["data_mode"] = mode.strip().upper()
            self._write_unlocked(data)
        return self.masked_status()

    def data_mode(self) -> str:
        return str(self._load().get("data_mode", "AUTO")).upper()

    def set_show_stale_history(self, enabled: bool) -> Dict[str, Any]:
        with self._lock:
            data = self._load_unlocked()
            data["show_stale_history"] = bool(enabled)
            self._write_unlocked(data)
        return self.masked_status()

    def show_stale_history(self) -> bool:
        return bool(self._load().get("show_stale_history", False))

    def _load(self) -> Dict[str, Any]:
        with self._lock:
            return self._load_unlocked()

    def _load_unlocked(self) -> Dict[str, Any]:
        if not self.settings_path.exists():
            return {}
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_unlocked(self, data: Dict[str, Any]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.settings_path.with_name(
            f".{self.settings_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(temporary, self.settings_path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    def _store_oanda_token(self, data: Dict[str, Any], token: str) -> None:
        protected = _windows_protect_secret(token)
        if protected:
            data["oanda_api_token_protected"] = protected
            data.pop("oanda_api_token", None)
        else:
            data["oanda_api_token"] = token

    def _migrate_oanda_token(self) -> None:
        if os.name != "nt":
            return
        with self._lock:
            data = self._load_unlocked()
            token = str(data.get("oanda_api_token") or "").strip()
            if data.get("oanda_api_token_protected"):
                if token:
                    data.pop("oanda_api_token", None)
                    self._write_unlocked(data)
                return
            if not token:
                return
            self._store_oanda_token(data, token)
            self._write_unlocked(data)


@dataclass
class GoldAPIStatus:
    status: str
    provider_name: str = PROVIDER_NAME
    message: str = ""
    last_updated: Optional[str] = None
    latest_price: Optional[float] = None
    is_running: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "provider_name": self.provider_name,
            "message": self.message,
            "last_updated": self.last_updated,
            "latest_price": self.latest_price,
            "is_running": self.is_running,
        }


class SQLiteCandleStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def database_info(self) -> Dict[str, Any]:
        errors: list[str] = []
        try:
            with self.connect() as conn:
                table_names = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()]
                candle_tables_created = all(table in table_names for table in TABLES.values())
                latest_tick = conn.execute("SELECT timestamp FROM live_ticks ORDER BY timestamp DESC LIMIT 1").fetchone()
        except Exception as exc:
            table_names = []
            candle_tables_created = False
            latest_tick = None
            errors.append(str(exc))
        return {
            "database_path": str(self.db_path),
            "database_exists": self.db_path.exists(),
            "table_names": table_names,
            "candle_tables_created": candle_tables_created,
            "candle_counts": self.counts() if self.db_path.exists() else {},
            "latest_tick_time": latest_tick["timestamp"] if latest_tick else None,
            "latest_candle_time": self.latest_any_timestamp("15M") if self.db_path.exists() else None,
            "errors": errors,
        }

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS live_ticks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL UNIQUE,
                    price REAL NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_live_ticks_timestamp ON live_ticks(timestamp)")
            for table in TABLES.values():
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL UNIQUE,
                        open REAL NOT NULL,
                        high REAL NOT NULL,
                        low REAL NOT NULL,
                        close REAL NOT NULL,
                        source TEXT NOT NULL,
                        is_complete INTEGER NOT NULL DEFAULT 1,
                        is_partial INTEGER NOT NULL DEFAULT 0,
                        tick_count INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT
                    )
                """)
                self._ensure_candle_columns(conn, table)
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_timestamp ON {table}(timestamp)")
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_source ON {table}(source)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS provider_status (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    provider_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    latest_price REAL,
                    last_updated TEXT,
                    is_running INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analysis_cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    dependency_timestamp TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS engine_status (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    mode TEXT NOT NULL,
                    current_analysis_status TEXT,
                    last_analysis_time TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS engine_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL
                )
            """)

    def _ensure_candle_columns(self, conn: sqlite3.Connection, table: str) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        additions = {
            "is_complete": "INTEGER NOT NULL DEFAULT 1",
            "is_partial": "INTEGER NOT NULL DEFAULT 0",
            "tick_count": "INTEGER NOT NULL DEFAULT 0",
            "confidence": "TEXT NOT NULL DEFAULT 'HIGH'",
            "updated_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def save_tick(self, timestamp: str, price: float) -> None:
        if not _valid_price(price):
            return
        now = _utc_now()
        tick_time = pd.Timestamp(timestamp)
        if tick_time.tzinfo is None:
            tick_time = tick_time.tz_localize("UTC")
        else:
            tick_time = tick_time.tz_convert("UTC")
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO live_ticks (timestamp, price, source, created_at) VALUES (?, ?, ?, ?)",
                (tick_time.isoformat(), float(price), SOURCE_NAME, now),
            )

    def save_ticks(self, ticks: list[tuple[str, float]]) -> None:
        if not ticks:
            return
        now = _utc_now()
        rows = []
        for timestamp, price in ticks:
            if not _valid_price(price):
                continue
            tick_time = pd.Timestamp(timestamp)
            if tick_time.tzinfo is None:
                tick_time = tick_time.tz_localize("UTC")
            else:
                tick_time = tick_time.tz_convert("UTC")
            rows.append((tick_time.isoformat(), float(price), SOURCE_NAME, now))
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO live_ticks (timestamp, price, source, created_at) VALUES (?, ?, ?, ?)",
                rows,
            )

    def upsert_candle(
        self,
        timeframe: str,
        timestamp: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        source: str = LIVE_SOURCE,
        is_complete: bool = True,
        is_partial: bool = False,
        tick_count: int = 0,
        confidence: Optional[str] = None,
    ) -> None:
        table = TABLES[timeframe]
        now = _utc_now()
        candle_confidence = confidence or _confidence_from_count(tick_count, TIMEFRAME_MINUTES.get(timeframe, 1))
        with self.connect() as conn:
            existing = conn.execute(f"SELECT source FROM {table} WHERE timestamp = ?", (timestamp,)).fetchone()
            if existing and source in LIVE_SOURCES and existing[0] in HISTORY_SOURCES:
                return
            conn.execute(
                f"""
                INSERT INTO {table} (timestamp, open, high, low, close, source, is_complete, is_partial, tick_count, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(timestamp) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    source=excluded.source,
                    is_complete=excluded.is_complete,
                    is_partial=excluded.is_partial,
                    tick_count=excluded.tick_count,
                    confidence=excluded.confidence,
                    updated_at=excluded.updated_at
                """,
                (timestamp, open_, high, low, close, source, 1 if is_complete else 0, 1 if is_partial else 0, tick_count, candle_confidence, now, now),
            )

    def insert_candles(self, timeframe: str, candles: list[Dict[str, Any]], source: str = PRELOADED_SOURCE) -> int:
        if not candles:
            return 0
        table = TABLES[normalize_timeframe(timeframe)]
        now = _utc_now()
        rows = [
            (
                candle["timestamp"],
                float(candle["open"]),
                float(candle["high"]),
                float(candle["low"]),
                float(candle["close"]),
                source,
                1,
                0,
                int(candle.get("tick_count", 0)),
                candle.get("confidence", "HIGH"),
                now,
                now,
            )
            for candle in candles
        ]
        with self.connect() as conn:
            before = conn.total_changes
            conn.executemany(
                f"""
                INSERT INTO {table}
                    (timestamp, open, high, low, close, source, is_complete, is_partial, tick_count, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(timestamp) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    source=excluded.source,
                    is_complete=excluded.is_complete,
                    is_partial=excluded.is_partial,
                    tick_count=excluded.tick_count,
                    confidence=excluded.confidence,
                    updated_at=excluded.updated_at
                """,
                rows,
            )
            return conn.total_changes - before

    def get_candles_df(self, timeframe: str, limit: int = 600, sources: Optional[set[str]] = None) -> pd.DataFrame:
        tf = normalize_timeframe(timeframe)
        table = TABLES[tf]
        with self.connect() as conn:
            if sources:
                placeholders = ", ".join("?" for _ in sources)
                rows = conn.execute(
                    f"""
                    SELECT timestamp, open, high, low, close, source, is_complete, is_partial, tick_count, confidence
                    FROM {table}
                    WHERE source IN ({placeholders})
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (*tuple(sources), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT timestamp, open, high, low, close, source, is_complete, is_partial, tick_count, confidence FROM {table} ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        rows = list(reversed(rows))
        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "source", "is_complete", "is_partial", "tick_count", "confidence"])
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df["volume"] = 0
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col])
        for col in ["is_complete", "is_partial", "tick_count"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        return df.set_index("time")

    def get_ticks_df(self, limit: int = 100000) -> pd.DataFrame:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT timestamp, price FROM live_ticks ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["price"])
        rows = list(reversed(rows))
        df = pd.DataFrame(rows, columns=["time", "price"])
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df["price"] = pd.to_numeric(df["price"])
        return df.set_index("time")

    def get_candles_payload(self, timeframe: str, limit: int = 600) -> Dict[str, Any]:
        tf = normalize_timeframe(timeframe)
        df = self.get_candles_df(tf, limit)
        candles = candles_to_records(df, limit)
        if not candles:
            return {
                "symbol": SYMBOL,
                "timeframe": tf,
                "source": "NO_HISTORY",
                "status": "NO_CANDLES",
                "error": "No candle data found. Start Live Builder or Seed History.",
                "candles": [],
                "count": 0,
                "last_updated": None,
            }
        return {
            "symbol": SYMBOL,
            "timeframe": tf,
            "source": self.source_summary(tf),
            "candles": candles,
            "count": len(candles),
            "last_updated": self.latest_any_timestamp(tf),
            "status": "READY",
        }

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        with self.connect() as conn:
            for tf, table in TABLES.items():
                out[tf] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return out

    def latest_timestamps(self) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {}
        with self.connect() as conn:
            for tf, table in TABLES.items():
                row = conn.execute(f"SELECT timestamp FROM {table} ORDER BY timestamp DESC LIMIT 1").fetchone()
                out[tf] = row["timestamp"] if row else None
        return out

    def latest_historical_timestamp(self, timeframe: str = "15M") -> Optional[str]:
        tf = normalize_timeframe(timeframe)
        placeholders = ", ".join("?" for _ in HISTORY_SOURCES)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT timestamp FROM {TABLES[tf]} WHERE source IN ({placeholders}) ORDER BY timestamp DESC LIMIT 1",
                tuple(HISTORY_SOURCES),
            ).fetchone()
        return row["timestamp"] if row else None

    def latest_any_timestamp(self, timeframe: str = "15M", completed_only: bool = False) -> Optional[str]:
        tf = normalize_timeframe(timeframe)
        with self.connect() as conn:
            complete_filter = " WHERE is_complete = 1" if completed_only else ""
            row = conn.execute(
                f"SELECT timestamp FROM {TABLES[tf]}{complete_filter} ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        return row["timestamp"] if row else None

    def has_source(self, timeframe: str, source: str) -> bool:
        tf = normalize_timeframe(timeframe)
        with self.connect() as conn:
            row = conn.execute(f"SELECT 1 FROM {TABLES[tf]} WHERE source = ? LIMIT 1", (source,)).fetchone()
        return bool(row)

    def latest_candle_for_sources(
        self,
        timeframe: str,
        sources: set[str],
        completed_only: bool = False,
    ) -> Optional[Dict[str, Any]]:
        tf = normalize_timeframe(timeframe)
        if not sources:
            return None
        placeholders = ", ".join("?" for _ in sources)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT timestamp, close, source, is_complete, is_partial
                FROM {TABLES[tf]}
                WHERE source IN ({placeholders})
                  {"AND is_complete = 1" if completed_only else ""}
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                tuple(sources),
            ).fetchone()
        return dict(row) if row else None

    def latest_timestamp_for_sources(
        self,
        timeframe: str,
        sources: set[str],
        completed_only: bool = False,
    ) -> Optional[str]:
        latest = self.latest_candle_for_sources(timeframe, sources, completed_only=completed_only)
        return latest.get("timestamp") if latest else None

    def source_counts(self) -> Dict[str, Dict[str, int]]:
        out: Dict[str, Dict[str, int]] = {}
        with self.connect() as conn:
            for tf, table in TABLES.items():
                rows = conn.execute(
                    f"SELECT source, COUNT(*) AS count FROM {table} WHERE is_complete = 1 GROUP BY source"
                ).fetchall()
                out[tf] = {row["source"]: int(row["count"]) for row in rows}
        return out

    def delete_source(self, source: str) -> Dict[str, int]:
        removed: Dict[str, int] = {}
        with self.connect() as conn:
            for tf, table in TABLES.items():
                before = conn.total_changes
                conn.execute(f"DELETE FROM {table} WHERE source = ?", (source,))
                removed[tf] = conn.total_changes - before
        return removed

    def archive_sources(self, sources: set[str]) -> Dict[str, int]:
        archived: Dict[str, int] = {}
        if not sources:
            return {tf: 0 for tf in SUPPORTED_TIMEFRAMES}
        placeholders = ", ".join("?" for _ in sources)
        with self.connect() as conn:
            for tf, table in TABLES.items():
                before = conn.total_changes
                conn.execute(f"UPDATE {table} SET source = ?, updated_at = ? WHERE source IN ({placeholders})", (ARCHIVED_STALE_SOURCE, _utc_now(), *tuple(sources)))
                archived[tf] = conn.total_changes - before
        return archived

    def source_summary(self, timeframe: str) -> str:
        tf = normalize_timeframe(timeframe)
        with self.connect() as conn:
            rows = conn.execute(f"SELECT source, COUNT(*) AS count FROM {TABLES[tf]} GROUP BY source").fetchall()
        if not rows:
            return "NO_HISTORY"
        sources = {row["source"] for row in rows}
        live_sources = {LIVE_SOURCE, LIVE_BUILDER_SOURCE}
        if OANDA_HISTORY_SOURCE in sources:
            return OANDA_HISTORY_SOURCE
        if BINANCE_HISTORY_SOURCE in sources:
            return BINANCE_HISTORY_SOURCE
        if REAL_CSV_HISTORY_SOURCE in sources:
            return "REAL_CSV_HISTORY"
        if TWELVE_DATA_HISTORY_SOURCE in sources:
            return "TWELVE_DATA_REAL_HISTORY"
        if USER_RECENT_CSV_SOURCE in sources:
            return "USER_RECENT_CSV"
        if RECENT_CSV_SOURCE in sources:
            return "RECENT_CSV_HISTORY"
        if TEST_HISTORY_LIVE_ANCHORED_SOURCE in sources:
            return "TEST_HISTORY_LIVE_ANCHORED"
        if PRELOADED_SOURCE in sources and sources.intersection(live_sources):
            return "PRELOADED_HISTORY_AND_LIVE_BUILDER"
        if PRELOADED_SOURCE in sources:
            return "PRELOADED_HISTORY"
        if TEST_HISTORY_SOURCE in sources:
            return "TEST_HISTORY"
        if ARCHIVED_STALE_SOURCE in sources:
            return "ARCHIVED_STALE_HISTORY"
        if sources.intersection(live_sources):
            return "LIVE_BUILDER"
        return ", ".join(sorted(sources))

    def save_status(self, status: GoldAPIStatus) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_status (id, provider_name, status, message, latest_price, last_updated, is_running, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    provider_name=excluded.provider_name,
                    status=excluded.status,
                    message=excluded.message,
                    latest_price=excluded.latest_price,
                    last_updated=excluded.last_updated,
                    is_running=excluded.is_running,
                    updated_at=excluded.updated_at
                """,
                (
                    status.provider_name,
                    status.status,
                    status.message,
                    status.latest_price,
                    status.last_updated,
                    1 if status.is_running else 0,
                    _utc_now(),
                ),
            )

    def load_status(self) -> GoldAPIStatus:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT provider_name, status, message, latest_price, last_updated, is_running FROM provider_status WHERE id = 1"
            ).fetchone()
        if not row:
            return GoldAPIStatus("NO_DATA", message="No live price received.", is_running=False)
        return GoldAPIStatus(row[1], row[0], row[2] or "", row[4], row[3], bool(row[5]))


class GoldAPIComProvider:
    provider_name = GOLD_API_COM_PROVIDER_NAME

    def __init__(self):
        self.status = GoldAPIStatus("STARTING", provider_name=self.provider_name, message="Starting Gold-API.com free live price provider.")
        self.last_valid_price: Optional[float] = None
        self.last_provider_error: Optional[str] = None

    def fetch_latest_price(self) -> tuple[float, str]:
        try:
            response = requests.get("https://api.gold-api.com/price/XAU", timeout=10)
        except requests.RequestException as exc:
            self.last_provider_error = str(exc)
            self.status = GoldAPIStatus("CONNECTION_FAILED", self.provider_name, f"Gold-API.com connection failed: {exc}")
            raise RuntimeError(self.status.message) from exc
        if response.status_code == 429:
            self.last_provider_error = "Gold-API.com rate limit reached."
            self.status = GoldAPIStatus("RATE_LIMIT", self.provider_name, self.last_provider_error)
            raise RuntimeError(self.status.message)
        if response.status_code >= 400:
            self.last_provider_error = f"Provider API {response.status_code}: Gold-API.com endpoint returned HTTP {response.status_code}."
            self.status = GoldAPIStatus("CONNECTION_FAILED", self.provider_name, self.last_provider_error)
            raise RuntimeError(self.status.message)
        payload = response.json()
        price = payload.get("price")
        if price is None or not _valid_price(price):
            self.last_provider_error = "Gold-API.com returned no usable XAU price."
            self.status = GoldAPIStatus("NO_PRICE", self.provider_name, self.last_provider_error)
            raise RuntimeError(self.status.message)
        price = float(price)
        if self.last_valid_price and _is_abnormal_spike(self.last_valid_price, price):
            self.last_provider_error = f"Abnormal XAU price spike ignored: {self.last_valid_price} -> {price}."
            self.status = GoldAPIStatus("NO_PRICE", self.provider_name, self.last_provider_error, latest_price=self.last_valid_price)
            raise RuntimeError(self.status.message)
        tick_time = payload.get("updatedAt") or _utc_now()
        self.last_valid_price = price
        self.last_provider_error = None
        self.status = GoldAPIStatus("LIVE", self.provider_name, "Live XAU/USD price received from Gold-API.com.", tick_time, price)
        return price, tick_time


class GoldAPIioProvider:
    provider_name = GOLD_API_IO_PROVIDER_NAME

    def __init__(self, settings: ProviderSettings):
        self.settings = settings
        self.status = GoldAPIStatus("NO_PRICE", self.provider_name, message="No live price received.")
        self.last_valid_price: Optional[float] = None
        self.last_provider_error: Optional[str] = None

    def fetch_latest_price(self) -> tuple[float, str]:
        api_key = self.settings.get("goldapi_io_key") or self.settings.get("goldapi_key")
        if not api_key:
            self.status = GoldAPIStatus("NO_PRICE", self.provider_name, message="GoldAPI.io key is missing.")
            raise RuntimeError(self.status.message)
        headers = {"x-access-token": api_key, "Content-Type": "application/json"}
        try:
            response = requests.get("https://www.goldapi.io/api/XAU/USD", headers=headers, timeout=10)
        except requests.RequestException as exc:
            self.last_provider_error = str(exc)
            self.status = GoldAPIStatus("CONNECTION_FAILED", self.provider_name, f"GoldAPI.io connection failed: {exc}")
            raise RuntimeError(self.status.message) from exc
        if response.status_code == 429:
            self.last_provider_error = "Gold-API rate limit reached."
            self.status = GoldAPIStatus("RATE_LIMIT", self.provider_name, self.last_provider_error)
            raise RuntimeError(self.status.message)
        if response.status_code >= 400:
            self.last_provider_error = f"GoldAPI.io returned HTTP {response.status_code}."
            self.status = GoldAPIStatus("CONNECTION_FAILED", self.provider_name, self.last_provider_error)
            raise RuntimeError(self.status.message)
        payload = response.json()
        price = payload.get("price") or payload.get("ask") or payload.get("bid")
        if price is None or not _valid_price(price):
            self.last_provider_error = "GoldAPI.io returned missing or invalid XAU price."
            self.status = GoldAPIStatus("NO_PRICE", self.provider_name, self.last_provider_error)
            raise RuntimeError(self.status.message)
        price = float(price)
        if self.last_valid_price and _is_abnormal_spike(self.last_valid_price, price):
            self.last_provider_error = f"Abnormal XAU price spike ignored: {self.last_valid_price} -> {price}."
            self.status = GoldAPIStatus("NO_PRICE", self.provider_name, self.last_provider_error, latest_price=self.last_valid_price)
            raise RuntimeError(self.status.message)
        timestamp = payload.get("timestamp")
        if timestamp:
            try:
                tick_time = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat()
            except Exception:
                tick_time = _utc_now()
        else:
            tick_time = _utc_now()
        self.last_valid_price = price
        self.last_provider_error = None
        self.status = GoldAPIStatus("LIVE", self.provider_name, "Live XAU/USD price received from GoldAPI.io.", tick_time, price)
        return price, tick_time


class TwelveDataHistoryService:
    provider_name = "Twelve Data XAU/USD OHLC"
    interval_map = {
        "1M": "1min",
        "5M": "5min",
        "15M": "15min",
        "1H": "1h",
        "4H": "4h",
        "1D": "1day",
    }
    output_sizes = {
        "1M": 1000,
        "5M": 1000,
        "15M": 1000,
        "1H": 600,
        "4H": 400,
        "1D": 250,
    }

    def __init__(
        self,
        settings: ProviderSettings,
        store: SQLiteCandleStore,
        market_symbol: str = "XAU/USD",
        provider_name: Optional[str] = None,
        source: str = TWELVE_DATA_HISTORY_SOURCE,
    ):
        self.settings = settings
        self.store = store
        self.market_symbol = market_symbol
        self.provider_name = provider_name or f"Twelve Data {market_symbol} OHLC"
        self.source = source

    def sync_recent_history(self, timeframes: Optional[list[str]] = None) -> Dict[str, Any]:
        api_key = self.settings.get("twelve_data_api_key")
        if not api_key:
            return {
                "ok": False,
                "status": "TWELVE_DATA_KEY_MISSING",
                "provider": self.provider_name,
                "message": "Twelve Data API key is missing.",
                "imported": {},
                "errors": {},
            }
        imported: Dict[str, int] = {}
        errors: Dict[str, str] = {}
        latest: Dict[str, Optional[str]] = {}
        for raw_tf in (timeframes or SUPPORTED_TIMEFRAMES):
            tf = normalize_timeframe(raw_tf)
            try:
                candles = self._fetch_timeframe(tf, api_key)
                imported[tf] = self.store.insert_candles(tf, candles, self.source)
                latest[tf] = candles[-1]["timestamp"] if candles else None
            except Exception as exc:
                errors[tf] = str(exc)
        return {
            "ok": not errors and bool(imported),
            "status": "TWELVE_DATA_HISTORY_SYNCED" if imported else "TWELVE_DATA_NO_HISTORY",
            "provider": self.provider_name,
            "source": self.source,
            "imported": imported,
            "latest": latest,
            "errors": errors,
            "candle_counts": self.store.counts(),
        }

    def _fetch_timeframe(
        self,
        timeframe: str,
        api_key: str,
        include_incomplete: bool = False,
        outputsize: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        interval = self.interval_map[timeframe]
        requested_size = outputsize or self.output_sizes[timeframe]
        response = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": self.market_symbol,
                "interval": interval,
                "outputsize": requested_size,
                "timezone": "UTC",
                "apikey": api_key,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") == "error":
            raise RuntimeError(payload.get("message") or payload.get("code") or "Twelve Data returned an error.")
        values = payload.get("values") or []
        if not values:
            raise RuntimeError("Twelve Data returned no candle values.")
        rows = []
        now = pd.Timestamp.now(tz="UTC")
        duration = pd.Timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
        for item in values:
            timestamp = pd.to_datetime(item.get("datetime"), errors="coerce", utc=True)
            if pd.isna(timestamp):
                continue
            try:
                open_ = float(item.get("open"))
                high = float(item.get("high"))
                low = float(item.get("low"))
                close = float(item.get("close"))
            except (TypeError, ValueError):
                continue
            if open_ <= 0 or high <= 0 or low <= 0 or close <= 0:
                continue
            if high < max(open_, close, low) or low > min(open_, close, high):
                continue
            is_complete = timestamp + duration <= now
            if not is_complete and not include_incomplete:
                continue
            rows.append({
                "timestamp": timestamp.isoformat(),
                "open": round(open_, 3),
                "high": round(high, 3),
                "low": round(low, 3),
                "close": round(close, 3),
                "is_complete": is_complete,
                "is_partial": not is_complete,
            })
        rows.sort(key=lambda candle: candle["timestamp"])
        deduped: Dict[str, Dict[str, Any]] = {candle["timestamp"]: candle for candle in rows}
        return list(deduped.values())

    def sync_live_candle(self, timeframe: str) -> Dict[str, Any]:
        tf = normalize_timeframe(timeframe)
        api_key = self.settings.get("twelve_data_api_key")
        if not api_key:
            return {
                "ok": False,
                "status": "TWELVE_DATA_KEY_MISSING",
                "provider": self.provider_name,
                "source": self.source,
                "message": "Twelve Data API key is missing.",
            }
        try:
            candles = self._fetch_timeframe(tf, api_key, include_incomplete=True, outputsize=3)
            return _persist_chart_candles(self.store, tf, candles, self.source, self.provider_name)
        except Exception as exc:
            return {
                "ok": False,
                "status": "LIVE_CANDLE_SYNC_FAILED",
                "provider": self.provider_name,
                "source": self.source,
                "message": str(exc),
            }


class OandaHistoryService:
    provider_name = "OANDA XAU_USD Mid OHLC"
    instrument = "XAU_USD"
    source = OANDA_HISTORY_SOURCE
    granularity_map = {
        "1M": "M1",
        "5M": "M5",
        "15M": "M15",
        "1H": "H1",
        "4H": "H4",
        "1D": "D",
    }
    output_sizes = TwelveDataHistoryService.output_sizes

    def __init__(self, settings: ProviderSettings, store: SQLiteCandleStore):
        self.settings = settings
        self.store = store
        self._dns_cache: Dict[str, tuple[float, list[str]]] = {}
        self._dns_lock = threading.Lock()
        self._transport_state = threading.local()

    @staticmethod
    def _endpoint_host(environment: str) -> str:
        return "api-fxtrade.oanda.com" if environment == "live" else "api-fxpractice.oanda.com"

    @classmethod
    def _endpoint_resolution_error(cls, environment: str) -> Optional[Dict[str, Any]]:
        host = cls._endpoint_host(environment)
        try:
            addresses = sorted({
                str(item[4][0])
                for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                if item[4]
            })
        except socket.gaierror:
            return {
                "status": "DNS_FAILED",
                "host": host,
                "resolved_addresses": [],
                "message": f"DNS could not resolve {host}. Check the device or router DNS, then retry.",
            }

        blocked = []
        for address in addresses:
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError:
                continue
            if (
                parsed.is_loopback
                or parsed.is_unspecified
                or parsed.is_private
                or parsed.is_link_local
                or parsed.is_multicast
                or parsed.is_reserved
            ):
                blocked.append(address)
        if not blocked:
            return None
        return {
            "status": "DNS_BLOCKED",
            "host": host,
            "resolved_addresses": addresses,
            "message": (
                f"{host} resolves to a local address ({', '.join(blocked)}), so the backend cannot reach OANDA. "
                "Change Windows or router DNS to 1.1.1.1 or 8.8.8.8, flush DNS, then verify again."
            ),
        }

    def _public_dns_addresses(self, host: str) -> list[str]:
        now = time.monotonic()
        with self._dns_lock:
            cached = self._dns_cache.get(host)
            if cached and cached[0] > now:
                return list(cached[1])

        errors = []
        providers = [
            ("https://cloudflare-dns.com/dns-query", {"name": host, "type": "A"}, {"accept": "application/dns-json"}),
            ("https://dns.google/resolve", {"name": host, "type": "A"}, {}),
        ]
        for url, params, headers in providers:
            try:
                response = requests.get(url, params=params, headers=headers, timeout=8)
                response.raise_for_status()
                payload = response.json()
                addresses = []
                for answer in payload.get("Answer") or []:
                    if int(answer.get("type") or 0) != 1:
                        continue
                    address = str(answer.get("data") or "").strip()
                    try:
                        parsed = ipaddress.ip_address(address)
                    except ValueError:
                        continue
                    if not any((parsed.is_private, parsed.is_loopback, parsed.is_link_local, parsed.is_reserved, parsed.is_multicast)):
                        addresses.append(address)
                if addresses:
                    unique_addresses = list(dict.fromkeys(addresses))
                    with self._dns_lock:
                        self._dns_cache[host] = (now + 300, unique_addresses)
                    return unique_addresses
            except Exception as exc:
                errors.append(type(exc).__name__)
        raise ConnectionError(f"Secure DNS lookup failed for {host}: {', '.join(errors) or 'no public address'}")

    def _request_via_public_dns(
        self,
        host: str,
        path: str,
        params: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        query = urlencode(params)
        request_path = f"{path}?{query}" if query else path
        last_error: Optional[Exception] = None
        for address in self._public_dns_addresses(host):
            pool = urllib3.HTTPSConnectionPool(
                address,
                port=443,
                server_hostname=host,
                assert_hostname=host,
                cert_reqs="CERT_REQUIRED",
                ca_certs=requests_ca_bundle(),
                timeout=urllib3.Timeout(connect=8, read=20),
            )
            try:
                raw = pool.request(
                    "GET",
                    request_path,
                    headers={**headers, "Host": host},
                    retries=False,
                )
                response = requests.Response()
                response.status_code = raw.status
                response._content = raw.data
                response.url = f"https://{host}{request_path}"
                response.headers.update(dict(raw.headers))
                response.raise_for_status()
                self._transport_state.dns_recovery = True
                with self._dns_lock:
                    cached = self._dns_cache.get(host)
                    remaining = [item for item in (cached[1] if cached else []) if item != address]
                    self._dns_cache[host] = (time.monotonic() + 300, [address, *remaining])
                return response.json()
            except requests.HTTPError:
                raise
            except Exception as exc:
                last_error = exc
            finally:
                pool.close()
        raise ConnectionError(f"Could not connect to {host} through secure DNS recovery") from last_error

    def _request_candle_payload(
        self,
        host: str,
        params: Dict[str, Any],
        token: str,
    ) -> Dict[str, Any]:
        path = f"/v3/instruments/{self.instrument}/candles"
        headers = {"Authorization": f"Bearer {token}"}
        resolution_error = self._endpoint_resolution_error(
            "live" if host == self._endpoint_host("live") else "practice"
        )
        if resolution_error:
            return self._request_via_public_dns(host, path, params, headers)
        response = requests.get(
            f"https://{host}{path}",
            params=params,
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def sync_recent_history(self, timeframes: Optional[list[str]] = None) -> Dict[str, Any]:
        self._transport_state.dns_recovery = False
        token = self.settings.get("oanda_api_token")
        environment = (self.settings.get("oanda_environment") or "practice").lower()
        if not token:
            return {
                "ok": False,
                "status": "OANDA_TOKEN_MISSING",
                "provider": self.provider_name,
                "source": self.source,
                "message": "OANDA API token is missing. Add it in Data settings to match OANDA:XAUUSD.",
                "imported": {},
                "errors": {},
            }
        imported: Dict[str, int] = {}
        errors: Dict[str, str] = {}
        latest: Dict[str, Optional[str]] = {}
        for raw_tf in (timeframes or SUPPORTED_TIMEFRAMES):
            tf = normalize_timeframe(raw_tf)
            try:
                candles = self._fetch_timeframe(tf, token, environment)
                imported[tf] = self.store.insert_candles(tf, candles, self.source)
                latest[tf] = candles[-1]["timestamp"] if candles else None
            except Exception as exc:
                errors[tf] = str(exc)
        error_text = " ".join(errors.values()).lower()
        if "401" in error_text or "unauthorized" in error_text:
            message = "OANDA rejected the access token for the selected environment."
        elif "403" in error_text or "forbidden" in error_text:
            message = "OANDA denied candle access for the selected environment."
        elif errors:
            message = "OANDA candle history could not be synchronized."
        else:
            message = "OANDA candle history synchronized."
        return {
            "ok": not errors and bool(imported),
            "status": "OANDA_HISTORY_SYNCED" if imported else "OANDA_NO_HISTORY",
            "provider": self.provider_name,
            "source": self.source,
            "instrument": self.instrument,
            "environment": environment,
            "imported": imported,
            "latest": latest,
            "errors": errors,
            "message": message,
            "candle_counts": self.store.counts(),
            "dns_recovery": bool(getattr(self._transport_state, "dns_recovery", False)),
        }

    def _fetch_timeframe(
        self,
        timeframe: str,
        token: str,
        environment: str,
        include_incomplete: bool = False,
        count: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        host = self._endpoint_host(environment)
        payload = self._request_candle_payload(
            host,
            {
                "granularity": self.granularity_map[timeframe],
                "count": count or self.output_sizes[timeframe],
                "price": "M",
                "smooth": "false",
            },
            token,
        )
        if payload.get("errorMessage"):
            raise RuntimeError(payload["errorMessage"])
        rows = []
        for item in payload.get("candles") or []:
            mid = item.get("mid") or {}
            is_complete = bool(item.get("complete"))
            if (not is_complete and not include_incomplete) or not mid:
                continue
            timestamp = pd.to_datetime(item.get("time"), errors="coerce", utc=True)
            if pd.isna(timestamp):
                continue
            candle = _normalized_history_candle(timestamp, mid.get("o"), mid.get("h"), mid.get("l"), mid.get("c"))
            if candle:
                candle["is_complete"] = is_complete
                candle["is_partial"] = not is_complete
                rows.append(candle)
        rows.sort(key=lambda candle: candle["timestamp"])
        return list({candle["timestamp"]: candle for candle in rows}.values())

    def sync_live_candle(self, timeframe: str) -> Dict[str, Any]:
        self._transport_state.dns_recovery = False
        tf = normalize_timeframe(timeframe)
        token = self.settings.get("oanda_api_token")
        environment = (self.settings.get("oanda_environment") or "practice").lower()
        if not token:
            return {
                "ok": False,
                "status": "OANDA_TOKEN_MISSING",
                "provider": self.provider_name,
                "source": self.source,
                "message": "OANDA API token is missing.",
            }
        try:
            candles = self._fetch_timeframe(tf, token, environment, include_incomplete=True, count=3)
            result = _persist_chart_candles(self.store, tf, candles, self.source, self.provider_name)
            result["environment"] = environment
            result["dns_recovery"] = bool(getattr(self._transport_state, "dns_recovery", False))
            return result
        except Exception as exc:
            return {
                "ok": False,
                "status": "LIVE_CANDLE_SYNC_FAILED",
                "provider": self.provider_name,
                "source": self.source,
                "message": str(exc),
            }

    def verify_connection(self, token: Optional[str] = None, environment: Optional[str] = None) -> Dict[str, Any]:
        self._transport_state.dns_recovery = False
        access_token = (token or self.settings.get("oanda_api_token") or "").strip()
        selected_environment = (environment or self.settings.get("oanda_environment") or "practice").lower()
        if selected_environment not in {"practice", "live"}:
            selected_environment = "practice"
        if not access_token:
            return {
                "ok": False,
                "status": "TOKEN_MISSING",
                "provider": self.provider_name,
                "environment": selected_environment,
                "message": "Enter an OANDA personal access token.",
            }
        started = time.perf_counter()
        try:
            candles = self._fetch_timeframe(
                "5M",
                access_token,
                selected_environment,
                include_incomplete=True,
                count=3,
            )
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            return {
                "ok": False,
                "status": "TOKEN_REJECTED" if status_code in {401, 403} else "PROVIDER_ERROR",
                "provider": self.provider_name,
                "environment": selected_environment,
                "http_status": status_code,
                "message": "OANDA rejected the token or environment." if status_code in {401, 403} else "OANDA is unavailable for verification.",
            }
        except Exception:
            return {
                "ok": False,
                "status": "CONNECTION_FAILED",
                "provider": self.provider_name,
                "environment": selected_environment,
                "message": "Could not connect to the OANDA candle endpoint.",
            }
        latest = candles[-1] if candles else None
        return {
            "ok": bool(candles),
            "status": "VERIFIED" if candles else "NO_CANDLES",
            "provider": self.provider_name,
            "source": self.source,
            "instrument": self.instrument,
            "environment": selected_environment,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "candle_count": len(candles),
            "latest_candle_time": latest.get("timestamp") if latest else None,
            "latest_close": latest.get("close") if latest else None,
            "dns_recovery": bool(getattr(self._transport_state, "dns_recovery", False)),
            "message": "OANDA XAU_USD candle access verified." if candles else "OANDA returned no XAU_USD candles.",
        }


class BinanceHistoryService:
    provider_name = "Binance BTCUSDT Spot OHLC"
    market_symbol = "BTCUSDT"
    source = BINANCE_HISTORY_SOURCE
    interval_map = {
        "1M": "1m",
        "5M": "5m",
        "15M": "15m",
        "1H": "1h",
        "4H": "4h",
        "1D": "1d",
    }
    output_sizes = TwelveDataHistoryService.output_sizes

    def __init__(self, store: SQLiteCandleStore):
        self.store = store

    def sync_recent_history(self, timeframes: Optional[list[str]] = None) -> Dict[str, Any]:
        imported: Dict[str, int] = {}
        errors: Dict[str, str] = {}
        latest: Dict[str, Optional[str]] = {}
        for raw_tf in (timeframes or SUPPORTED_TIMEFRAMES):
            tf = normalize_timeframe(raw_tf)
            try:
                candles = self._fetch_timeframe(tf)
                imported[tf] = self.store.insert_candles(tf, candles, self.source)
                latest[tf] = candles[-1]["timestamp"] if candles else None
            except Exception as exc:
                errors[tf] = str(exc)
        return {
            "ok": not errors and bool(imported),
            "status": "BINANCE_HISTORY_SYNCED" if imported else "BINANCE_NO_HISTORY",
            "provider": self.provider_name,
            "source": self.source,
            "symbol": self.market_symbol,
            "imported": imported,
            "latest": latest,
            "errors": errors,
            "candle_counts": self.store.counts(),
        }

    def _fetch_timeframe(
        self,
        timeframe: str,
        include_incomplete: bool = False,
        limit: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        response = requests.get(
            "https://data-api.binance.vision/api/v3/klines",
            params={
                "symbol": self.market_symbol,
                "interval": self.interval_map[timeframe],
                "limit": limit or self.output_sizes[timeframe],
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            raise RuntimeError(payload.get("msg") or "Binance returned an invalid candle response.")
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        rows = []
        for item in payload:
            if len(item) < 7:
                continue
            is_complete = int(item[6]) <= now_ms
            if not is_complete and not include_incomplete:
                continue
            timestamp = pd.to_datetime(int(item[0]), unit="ms", errors="coerce", utc=True)
            if pd.isna(timestamp):
                continue
            candle = _normalized_history_candle(timestamp, item[1], item[2], item[3], item[4])
            if candle:
                candle["is_complete"] = is_complete
                candle["is_partial"] = not is_complete
                rows.append(candle)
        rows.sort(key=lambda candle: candle["timestamp"])
        return list({candle["timestamp"]: candle for candle in rows}.values())

    def sync_live_candle(self, timeframe: str) -> Dict[str, Any]:
        tf = normalize_timeframe(timeframe)
        try:
            candles = self._fetch_timeframe(tf, include_incomplete=True, limit=3)
            return _persist_chart_candles(self.store, tf, candles, self.source, self.provider_name)
        except Exception as exc:
            return {
                "ok": False,
                "status": "LIVE_CANDLE_SYNC_FAILED",
                "provider": self.provider_name,
                "source": self.source,
                "message": str(exc),
            }


def _normalized_history_candle(timestamp: Any, open_: Any, high: Any, low: Any, close: Any) -> Optional[Dict[str, Any]]:
    try:
        open_value = float(open_)
        high_value = float(high)
        low_value = float(low)
        close_value = float(close)
    except (TypeError, ValueError):
        return None
    if min(open_value, high_value, low_value, close_value) <= 0:
        return None
    if high_value < max(open_value, close_value, low_value) or low_value > min(open_value, close_value, high_value):
        return None
    return {
        "timestamp": pd.Timestamp(timestamp).isoformat(),
        "open": round(open_value, 3),
        "high": round(high_value, 3),
        "low": round(low_value, 3),
        "close": round(close_value, 3),
    }


def _persist_chart_candles(
    store: SQLiteCandleStore,
    timeframe: str,
    candles: list[Dict[str, Any]],
    source: str,
    provider: str,
) -> Dict[str, Any]:
    completed = [candle for candle in candles if candle.get("is_complete", True)]
    partial = [candle for candle in candles if not candle.get("is_complete", True)]
    imported = store.insert_candles(timeframe, completed, source)
    for candle in partial:
        store.upsert_candle(
            timeframe,
            candle["timestamp"],
            float(candle["open"]),
            float(candle["high"]),
            float(candle["low"]),
            float(candle["close"]),
            source=source,
            is_complete=False,
            is_partial=True,
            confidence="LIVE",
        )
    latest = candles[-1] if candles else None
    return {
        "ok": bool(candles),
        "status": "LIVE_CANDLE_SYNCED" if candles else "NO_LIVE_CANDLE",
        "provider": provider,
        "source": source,
        "timeframe": timeframe,
        "completed_imported": imported,
        "forming_candle": bool(latest and latest.get("is_partial")),
        "last_candle": latest,
        "synced_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }


class LocalCandleBuilder:
    def __init__(self, store: SQLiteCandleStore):
        self.store = store
        self.rejected_outliers = 0
        self.last_valid_price: Optional[float] = None

    def add_tick(self, price: float, timestamp: str) -> None:
        if not self._accept_tick(price):
            return
        self.store.save_tick(timestamp, price)
        self._update_partial_candles(price, timestamp)
        self._build_completed_1m_from_ticks()
        self.aggregate_all()

    def _accept_tick(self, price: float) -> bool:
        if not _valid_price(price):
            return False
        if self.last_valid_price and _is_abnormal_spike(self.last_valid_price, float(price)):
            self.rejected_outliers += 1
            return False
        self.last_valid_price = float(price)
        return True

    def _update_partial_candles(self, price: float, timestamp: str) -> None:
        tick_time = pd.Timestamp(timestamp)
        if tick_time.tzinfo is None:
            tick_time = tick_time.tz_localize("UTC")
        else:
            tick_time = tick_time.tz_convert("UTC")
        candle_time = _floor_time(tick_time, "1M")
        ticks = self.store.get_ticks_df(limit=2000)
        window = ticks[(ticks.index >= candle_time) & (ticks.index < candle_time + pd.Timedelta(minutes=1))]
        if window.empty:
            open_ = high = low = close = float(price)
            tick_count = 1
        else:
            open_ = float(window["price"].iloc[0])
            high = float(window["price"].max())
            low = float(window["price"].min())
            close = float(window["price"].iloc[-1])
            tick_count = int(len(window))
        self.store.upsert_candle(
            "1M",
            candle_time.isoformat(),
            open_,
            high,
            low,
            close,
            source=LIVE_SOURCE,
            is_complete=False,
            is_partial=True,
            tick_count=tick_count,
            confidence=_confidence_from_tick_count(tick_count),
        )

    def _build_completed_1m_from_ticks(self) -> None:
        ticks = self.store.get_ticks_df()
        if len(ticks) == 0:
            return
        current_minute = pd.Timestamp.now(tz="UTC").floor("min")
        completed = ticks[ticks.index.floor("min") < current_minute]
        if len(completed) == 0:
            return
        grouped = completed["price"].resample("1min", label="left", closed="left").agg(["first", "max", "min", "last", "count"]).dropna()
        for timestamp, row in grouped.iterrows():
            tick_count = int(row["count"])
            self.store.upsert_candle(
                "1M",
                timestamp.isoformat(),
                float(row["first"]),
                float(row["max"]),
                float(row["min"]),
                float(row["last"]),
                source=LIVE_SOURCE,
                is_complete=True,
                is_partial=False,
                tick_count=tick_count,
                confidence=_confidence_from_tick_count(tick_count),
            )

    def aggregate_all(self) -> None:
        df_1m = self.store.get_candles_df("1M", limit=100000)
        if len(df_1m) == 0:
            return
        if "source" in df_1m.columns:
            df_1m = df_1m[df_1m["source"].isin([LIVE_SOURCE, LIVE_BUILDER_SOURCE])]
        if len(df_1m) == 0:
            return
        for timeframe, minutes in AGGREGATION.items():
            self._aggregate_timeframe(df_1m, timeframe, minutes)

    def _aggregate_timeframe(self, df_1m: pd.DataFrame, timeframe: str, minutes: int) -> None:
        if len(df_1m) == 0:
            return
        rule = _pandas_rule(timeframe)
        grouped = df_1m.resample(rule, label="left", closed="left").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "tick_count": "sum",
            "is_partial": "max",
        }).dropna()
        now = pd.Timestamp.now(tz="UTC")
        for timestamp, row in grouped.iterrows():
            window = df_1m[(df_1m.index >= timestamp) & (df_1m.index < timestamp + pd.Timedelta(minutes=minutes))]
            if window.empty:
                continue
            child_count = int(len(window))
            complete = child_count >= minutes and not bool(row.get("is_partial", 0)) and timestamp + pd.Timedelta(minutes=minutes) <= now
            self.store.upsert_candle(
                timeframe,
                timestamp.isoformat(),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                source=LIVE_SOURCE,
                is_complete=complete,
                is_partial=not complete,
                tick_count=int(row.get("tick_count", child_count)),
                confidence=_confidence_from_child_count(child_count, minutes),
            )

    def rebuild_from_ticks(self) -> Dict[str, Any]:
        self._build_completed_1m_from_ticks()
        self.aggregate_all()
        return {"ok": True, "status": "CANDLE_ENGINE_REBUILT", "candle_counts": self.store.counts(), "outlier_rejected_count": self.rejected_outliers}


class CandleHistorySeeder:
    def __init__(self, store: SQLiteCandleStore, history_dir: str):
        self.store = store
        self.history_dir = Path(history_dir)

    def seed_if_needed(self) -> Dict[str, Any]:
        return self._seed(only_when_missing_source=True)

    def seed_all(self) -> Dict[str, Any]:
        return self._seed(only_when_missing_source=False)

    def reload_safely(self) -> Dict[str, Any]:
        return self.seed_all() | {"message": "Historical candles reloaded safely with duplicate timestamps ignored."}

    def _seed(self, only_when_missing_source: bool) -> Dict[str, Any]:
        imported: Dict[str, int] = {}
        skipped: Dict[str, str] = {}
        errors: Dict[str, str] = {}
        self.history_dir.mkdir(parents=True, exist_ok=True)
        for timeframe in SUPPORTED_TIMEFRAMES:
            csv_path = self.history_dir / f"xauusd_{timeframe.lower()}.csv"
            if only_when_missing_source and self.store.has_source(timeframe, PRELOADED_SOURCE):
                skipped[timeframe] = "PRELOADED_HISTORY already exists."
                continue
            if not csv_path.exists():
                errors[timeframe] = f"Missing history file: {csv_path}"
                continue
            try:
                candles = self._load_history_csv(csv_path)
                imported[timeframe] = self.store.insert_candles(timeframe, candles, PRELOADED_SOURCE)
            except Exception as exc:
                errors[timeframe] = str(exc)
        status = "READY"
        if len(errors) == len(SUPPORTED_TIMEFRAMES):
            status = "NO_HISTORY_FILES"
        return {
            "ok": not errors,
            "status": status,
            "message": NO_HISTORY_FILES_MESSAGE if status == "NO_HISTORY_FILES" else "Preloaded XAUUSD history seed completed.",
            "source": PRELOADED_SOURCE,
            "history_dir": str(self.history_dir),
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
            "candle_counts": self.store.counts(),
        }

    def history_files_found(self) -> Dict[str, bool]:
        self.history_dir.mkdir(parents=True, exist_ok=True)
        return {timeframe: (self.history_dir / f"xauusd_{timeframe.lower()}.csv").exists() for timeframe in SUPPORTED_TIMEFRAMES}

    def _load_history_csv(self, csv_path: Path) -> list[Dict[str, Any]]:
        df = pd.read_csv(csv_path)
        df.columns = [col.strip().lower() for col in df.columns]
        if "timestamp" not in df.columns and "time" in df.columns:
            df = df.rename(columns={"time": "timestamp"})
        required = ["timestamp", "open", "high", "low", "close"]
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(f"{csv_path.name} missing columns: {', '.join(missing)}")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        valid = (
            (df[["open", "high", "low", "close"]] > 0).all(axis=1)
            & (df["high"] >= df[["open", "close", "low"]].max(axis=1))
            & (df["low"] <= df[["open", "close", "high"]].min(axis=1))
        )
        df = df[valid].drop_duplicates(subset=["timestamp"])
        return [
            {
                "timestamp": row["timestamp"].isoformat(),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
            }
            for _, row in df.iterrows()
        ]


class CandleGapDetector:
    def __init__(self, store: SQLiteCandleStore):
        self.store = store

    def readiness(self) -> Dict[str, Any]:
        counts = self.store.counts()
        provider_status = self.store.load_status().to_dict()
        latest_historical = self.store.latest_historical_timestamp("15M")
        latest_any = self.store.latest_any_timestamp("15M")
        latest_live = provider_status.get("last_updated")
        chart_ready = any(counts.values())
        history_status, gap_warning, details = self._history_status(latest_any, latest_live, counts, latest_historical)
        readiness = validate_analysis_readiness(counts)
        full_analysis_ready = readiness["ready"] and history_status == "READY" and provider_status.get("status") == "LIVE"
        analysis_ready = full_analysis_ready
        if not chart_ready:
            analysis_state = "Waiting for Data"
        elif provider_status.get("status") != "LIVE":
            analysis_state = "Waiting for Live Price"
        elif history_status in ["HISTORY_TOO_OLD", "NOT_ENOUGH_RECENT_DATA", "READY_WITH_GAP_WARNING"]:
            analysis_state = "Waiting for Recent Candle History"
        elif readiness["ready"]:
            analysis_state = "Full Analysis Ready"
        else:
            analysis_state = "Partial Analysis Only"
        return {
            "chart_ready": chart_ready,
            "analysis_ready": analysis_ready,
            "full_analysis_ready": full_analysis_ready,
            "partial_analysis_only": chart_ready and not full_analysis_ready,
            "analysis_state": analysis_state,
            "history_status": history_status,
            "latest_historical_candle_time": latest_historical,
            "latest_candle_time": latest_any,
            "latest_live_update_time": latest_live,
            "latest_live_price": provider_status.get("latest_price"),
            "live_status": provider_status.get("status"),
            "data_source": "Preloaded History + Gold-API.com Free Live Price Builder",
            "candle_counts": counts,
            "minimum_required": MIN_ANALYSIS_CANDLES,
            "missing_history": readiness["missing"],
            "gap_warning": gap_warning,
            "warnings": details,
        }

    def _history_status(
        self,
        latest_any: Optional[str],
        latest_live: Optional[str],
        counts: Dict[str, int],
        latest_historical: Optional[str],
    ) -> tuple[str, Optional[str], list[str]]:
        if not latest_any:
            return "NO_HISTORY", None, ["No local candle history found. Please seed history first."]
        warnings: list[str] = []
        duplicates = self._duplicate_warnings()
        warnings.extend(duplicates)
        latest_ts = pd.Timestamp(latest_any)
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.tz_localize("UTC")
        else:
            latest_ts = latest_ts.tz_convert("UTC")
        now = pd.Timestamp.now(tz="UTC")
        age_minutes = (now - latest_ts).total_seconds() / 60
        if age_minutes > 1440:
            warnings.append(HISTORY_GAP_WARNING)
            return "HISTORY_TOO_OLD", HISTORY_GAP_WARNING, warnings
        if age_minutes > 90:
            warnings.append(HISTORY_GAP_WARNING)
            return "READY_WITH_GAP_WARNING", HISTORY_GAP_WARNING, warnings
        readiness = validate_analysis_readiness(counts)
        if not readiness["ready"]:
            warnings.extend(item["message"] for item in readiness["missing"])
            return "NOT_ENOUGH_RECENT_DATA", None, warnings
        if latest_live:
            live_ts = pd.Timestamp(latest_live)
            if live_ts.tzinfo is None:
                live_ts = live_ts.tz_localize("UTC")
            else:
                live_ts = live_ts.tz_convert("UTC")
            if latest_historical:
                historical_ts = pd.Timestamp(latest_historical)
                if historical_ts.tzinfo is None:
                    historical_ts = historical_ts.tz_localize("UTC")
                else:
                    historical_ts = historical_ts.tz_convert("UTC")
                if (live_ts - historical_ts).total_seconds() > 3600:
                    warnings.append(HISTORY_GAP_WARNING)
                    return "READY_WITH_GAP_WARNING", HISTORY_GAP_WARNING, warnings
            if abs((live_ts - latest_ts).total_seconds()) > 3600:
                warnings.append(HISTORY_GAP_WARNING)
                return "READY_WITH_GAP_WARNING", HISTORY_GAP_WARNING, warnings
        return "READY", None, warnings

    def _duplicate_warnings(self) -> list[str]:
        warnings: list[str] = []
        with self.store.connect() as conn:
            for timeframe, table in TABLES.items():
                rows = conn.execute(
                    f"SELECT timestamp, COUNT(*) AS count FROM {table} GROUP BY timestamp HAVING COUNT(*) > 1 LIMIT 1"
                ).fetchall()
                if rows:
                    warnings.append(f"Duplicate candles detected on {timeframe}.")
        return warnings


class LiveCandleBuilderService:
    def __init__(self, settings: ProviderSettings, store: SQLiteCandleStore, poll_seconds: int = 5, retry_seconds: int = 10):
        self.settings = settings
        self.store = store
        self.price_provider = GoldAPIComProvider()
        self.optional_goldapi_io = GoldAPIioProvider(settings)
        self.candle_builder = LocalCandleBuilder(store)
        self.poll_seconds = max(3, min(5, poll_seconds))
        self.retry_seconds = max(5, retry_seconds)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> Dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop_event.clear()
            self.store.save_status(GoldAPIStatus("STARTING", PROVIDER_NAME, "Gold-API.com live builder starting.", is_running=True))
            try:
                self._fetch_and_store_tick()
            except Exception:
                pass
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            status = self.store.load_status()
            status.is_running = True
            status.message = status.message or "Live candle builder started."
            self.store.save_status(status)
            return self.status()

    def stop(self) -> Dict[str, Any]:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        status = self.store.load_status()
        status.status = "STOPPED"
        status.is_running = False
        status.message = "Live candle builder stopped."
        self.store.save_status(status)
        return self.status()

    def status(self) -> Dict[str, Any]:
        status = self.store.load_status()
        if self._thread and self._thread.is_alive():
            status.is_running = True
        counts = self.store.counts()
        readiness = validate_analysis_readiness(counts)
        return {
            "symbol": SYMBOL,
            "provider_name": PROVIDER_NAME,
            "provider_display_name": GOLD_API_COM_PROVIDER_NAME,
            "optional_provider_name": GOLD_API_IO_PROVIDER_NAME,
            "api_key_required": False,
            "status": status.status,
            "message": status.message,
            "latest_price": status.latest_price,
            "last_updated": status.last_updated,
            "is_running": status.is_running,
            "candle_counts": counts,
            "analysis_ready": readiness["ready"],
            "partial_analysis_available": counts.get("5M", 0) > 0,
            "missing_history": readiness["missing"],
            "warning": None if readiness["ready"] else LIVE_HISTORY_WARNING,
            "last_error": self.price_provider.last_provider_error or self.optional_goldapi_io.last_provider_error,
        }

    def live_price(self) -> Dict[str, Any]:
        status = self.store.load_status()
        return {
            "symbol": SYMBOL,
            "provider_name": PROVIDER_NAME,
            "api_key_required": False,
            "status": status.status,
            "latest_price": status.latest_price,
            "last_updated": status.last_updated,
            "message": status.message,
        }

    def _run(self) -> None:
        while not self._stop_event.is_set():
            wait_seconds = self.poll_seconds
            try:
                self._fetch_and_store_tick()
            except Exception:
                status = self.price_provider.status
                status.is_running = True
                if status.status not in ["RATE_LIMIT", "CONNECTION_FAILED", "NO_PRICE"]:
                    status.status = "RETRYING"
                status.message = f"{status.message} Retrying in {self.retry_seconds} seconds."
                self.store.save_status(status)
                wait_seconds = self.retry_seconds
            self._stop_event.wait(wait_seconds)

    def _fetch_and_store_tick(self) -> None:
        price, tick_time = self.price_provider.fetch_latest_price()
        self.candle_builder.add_tick(price, tick_time)
        status = self.price_provider.status
        status.is_running = True
        self.store.save_status(status)


class TestHistoryGenerator:
    def __init__(self, store: SQLiteCandleStore):
        self.store = store

    def generate(self, base_price: Optional[float] = None, source: str = TEST_HISTORY_SOURCE) -> Dict[str, Any]:
        provider_status = self.store.load_status().to_dict()
        price = float(base_price or provider_status.get("latest_price") or 2400.0)
        imported: Dict[str, int] = {}
        now = pd.Timestamp.now(tz="UTC")
        for timeframe in SUPPORTED_TIMEFRAMES:
            candles = self._candles_for_timeframe(timeframe, now, price)
            imported[timeframe] = self.store.insert_candles(timeframe, candles, source)
        return {
            "ok": True,
            "status": "TEST_HISTORY_GENERATED" if source == TEST_HISTORY_SOURCE else "LIVE_ANCHORED_TEST_HISTORY_GENERATED",
            "source": source,
            "badge": "TEST DATA",
            "message": "Generated live-anchored TEST DATA candles for chart recovery only. This is not real market history.",
            "imported": imported,
            "candle_counts": self.store.counts(),
            "analysis_enabled": False,
        }

    def generate_live_anchored(self) -> Dict[str, Any]:
        provider_status = self.store.load_status().to_dict()
        price = provider_status.get("latest_price")
        if price is None:
            raise RuntimeError("Cannot generate live-anchored test history without a latest live XAUUSD price.")
        return self.generate(float(price), TEST_HISTORY_LIVE_ANCHORED_SOURCE)

    def clear(self) -> Dict[str, Any]:
        removed_standard = self.store.delete_source(TEST_HISTORY_SOURCE)
        removed_live_anchored = self.store.delete_source(TEST_HISTORY_LIVE_ANCHORED_SOURCE)
        removed = {tf: removed_standard.get(tf, 0) + removed_live_anchored.get(tf, 0) for tf in SUPPORTED_TIMEFRAMES}
        return {
            "ok": True,
            "status": "TEST_HISTORY_CLEARED",
            "source": ",".join(sorted(TEST_HISTORY_SOURCES)),
            "removed": removed,
            "removed_total": sum(removed.values()),
            "candle_counts": self.store.counts(),
            "message": "TEST_HISTORY candles cleared.",
        }

    def _candles_for_timeframe(self, timeframe: str, now: pd.Timestamp, base_price: float) -> list[Dict[str, Any]]:
        counts = {"1M": 1500, "5M": 1000, "15M": 800, "1H": 500, "4H": 300, "1D": 200}
        minutes = TIMEFRAME_MINUTES[timeframe]
        count = counts[timeframe]
        end = _floor_time(now, timeframe)
        candles: list[Dict[str, Any]] = []
        volatility = {"1M": 0.35, "5M": 0.75, "15M": 1.35, "1H": 2.4, "4H": 4.8, "1D": 8.5}[timeframe]
        previous_close = base_price - ((count % 23) - 11) * volatility * 0.05
        for position, idx in enumerate(range(count, 0, -1)):
            timestamp = end - pd.Timedelta(minutes=idx * minutes)
            progress = position / max(count - 1, 1)
            wave = ((position % 29) - 14) * volatility * 0.035
            cycle = ((position % 11) - 5) * volatility * 0.025
            mean_reversion = (base_price - previous_close) * 0.08
            close = previous_close + wave + cycle + mean_reversion
            if position == count - 1:
                close = base_price
            close = max(1, close)
            open_ = previous_close
            spread = max(volatility * (0.45 + (position % 5) * 0.07), base_price * 0.00008)
            high = max(open_, close) + spread
            low = min(open_, close) - spread
            candles.append({
                "timestamp": timestamp.isoformat(),
                "open": round(open_, 3),
                "high": round(high, 3),
                "low": round(low, 3),
                "close": round(close, 3),
                "tick_count": 0,
            })
            previous_close = close
        return candles


class RealisticTestHistoryGeneratorV2(TestHistoryGenerator):
    COUNTS = {"1M": 3000, "5M": 1500, "15M": 1000, "1H": 600, "4H": 300, "1D": 180}
    VOLATILITY = {"1M": 0.28, "5M": 0.72, "15M": 1.35, "1H": 2.55, "4H": 5.4, "1D": 11.5}

    def generate(self, base_price: Optional[float] = None, source: str = TEST_HISTORY_LIVE_ANCHORED_SOURCE) -> Dict[str, Any]:
        provider_status = self.store.load_status().to_dict()
        price = float(base_price or provider_status.get("latest_price") or 2400.0)
        self.clear()
        imported: Dict[str, int] = {}
        now = pd.Timestamp.now(tz="UTC")
        seed = int(now.timestamp())
        for timeframe in SUPPORTED_TIMEFRAMES:
            candles = self._candles_for_timeframe_v2(timeframe, now, price, seed)
            imported[timeframe] = self.store.insert_candles(timeframe, candles, source)
        return {
            "ok": True,
            "status": "REALISTIC_TEST_HISTORY_GENERATED_V2",
            "source": source,
            "badge": "TEST DATA",
            "generator": "RealisticTestHistoryGeneratorV2",
            "message": "Generated realistic TEST DATA candles for development only. This is not real market history.",
            "imported": imported,
            "required_counts": self.COUNTS,
            "candle_counts": self.store.counts(),
            "test_data_rule": "TEST DATA must never be labeled real or used as a real signal.",
        }

    def generate_live_anchored(self) -> Dict[str, Any]:
        provider_status = self.store.load_status().to_dict()
        price = provider_status.get("latest_price") or 2400.0
        return self.generate(float(price), TEST_HISTORY_LIVE_ANCHORED_SOURCE)

    def _candles_for_timeframe_v2(self, timeframe: str, now: pd.Timestamp, base_price: float, seed: int) -> list[Dict[str, Any]]:
        tf = normalize_timeframe(timeframe)
        count = self.COUNTS[tf]
        minutes = TIMEFRAME_MINUTES[tf]
        end = _floor_time(now, tf)
        volatility = self.VOLATILITY[tf]
        rng = random.Random(seed + sum(ord(ch) for ch in tf) * 97)
        regimes = self._regimes(count, rng)
        start_offset = rng.uniform(-0.018, 0.018) * base_price
        previous_close = max(1.0, base_price + start_offset)
        raw: list[Dict[str, Any]] = []
        for position in range(count):
            timestamp = end - pd.Timedelta(minutes=(count - position - 1) * minutes)
            regime = regimes[position]
            progress = position / max(count - 1, 1)
            mean_reversion = (base_price - previous_close) * rng.uniform(0.003, 0.016)
            regime_drift = regime["drift"] * volatility
            shock = rng.gauss(0, volatility * regime["volatility"])
            pullback = 0.0
            if position % rng.randint(17, 43) == 0:
                pullback = -regime_drift * rng.uniform(1.4, 3.1)
            close = max(1.0, previous_close + regime_drift + shock + pullback + mean_reversion)
            open_ = previous_close
            wick_base = max(abs(close - open_) * rng.uniform(0.25, 0.85), volatility * rng.uniform(0.35, 1.15))
            high = max(open_, close) + wick_base * rng.uniform(0.45, 1.65)
            low = min(open_, close) - wick_base * rng.uniform(0.45, 1.65)
            if rng.random() < 0.018:
                if rng.random() >= 0.5:
                    high += volatility * rng.uniform(2.4, 5.7)
                else:
                    low -= volatility * rng.uniform(2.4, 5.7)
            raw.append({
                "timestamp": timestamp,
                "open": open_,
                "high": max(high, open_, close),
                "low": max(0.01, min(low, open_, close)),
                "close": close,
            })
            previous_close = close

        end_gap = raw[-1]["close"] - base_price
        candles: list[Dict[str, Any]] = []
        for position, candle in enumerate(raw):
            adjustment = end_gap * (position / max(count - 1, 1))
            open_ = max(1.0, candle["open"] - adjustment)
            close = max(1.0, candle["close"] - adjustment)
            high = max(candle["high"] - adjustment, open_, close)
            low = max(0.01, min(candle["low"] - adjustment, open_, close))
            if position == count - 1:
                close = base_price
                high = max(high, open_, close)
                low = min(low, open_, close)
            candles.append({
                "timestamp": candle["timestamp"].isoformat(),
                "open": round(open_, 3),
                "high": round(high, 3),
                "low": round(low, 3),
                "close": round(close, 3),
                "tick_count": 0,
            })
        return candles

    def _regimes(self, count: int, rng: random.Random) -> list[Dict[str, float]]:
        regimes: list[Dict[str, float]] = []
        templates = [
            {"name": "bullish", "drift": 0.055, "volatility": 0.75},
            {"name": "bearish", "drift": -0.055, "volatility": 0.78},
            {"name": "ranging", "drift": 0.0, "volatility": 0.52},
            {"name": "expansion", "drift": 0.035, "volatility": 1.22},
            {"name": "sell_expansion", "drift": -0.035, "volatility": 1.24},
        ]
        while len(regimes) < count:
            template = dict(rng.choice(templates))
            segment = rng.randint(35, 180)
            if template["name"] == "ranging":
                template["drift"] = rng.uniform(-0.014, 0.014)
            for _ in range(segment):
                regimes.append({
                    "drift": template["drift"] * rng.uniform(0.55, 1.35),
                    "volatility": template["volatility"] * rng.uniform(0.72, 1.48),
                })
                if len(regimes) >= count:
                    break
        return regimes[:count]


class DataGapDiagnosisService:
    def __init__(self, store: SQLiteCandleStore):
        self.store = store

    def diagnose(self, timeframe: str = "15M") -> Dict[str, Any]:
        tf = normalize_timeframe(timeframe)
        provider_status = self.store.load_status().to_dict()
        live_price = provider_status.get("latest_price")
        active_history = self.store.latest_candle_for_sources(tf, REAL_RECENT_SOURCES | TEST_HISTORY_SOURCES)
        archived_history = self.store.latest_candle_for_sources(tf, {ARCHIVED_STALE_SOURCE})
        latest = active_history or archived_history
        if not latest:
            return {
                "symbol": SYMBOL,
                "timeframe": tf,
                "status": "NO_HISTORY",
                "live_price": live_price,
                "latest_history_close": None,
                "price_gap_percent": None,
                "latest_history_time": None,
                "latest_history_source": None,
                "recommended_action": "FIX_GAP_NOW",
                "message": "No local candle history found.",
            }
        latest_close = float(latest["close"])
        latest_time = latest["timestamp"]
        latest_source = latest["source"]
        price_gap = None
        price_gap_status = False
        if live_price is not None and latest_close > 0:
            price_gap = abs(float(live_price) - latest_close) / latest_close * 100
            price_gap_status = price_gap > 2
        stale_status = self._is_stale(latest_time, tf)
        if price_gap_status and stale_status:
            status = "CRITICAL_GAP"
        elif price_gap_status:
            status = "PRICE_GAP"
        elif stale_status:
            status = "STALE_HISTORY"
        else:
            status = "READY"
        return {
            "symbol": SYMBOL,
            "timeframe": tf,
            "status": status,
            "live_price": round(float(live_price), 3) if live_price is not None else None,
            "latest_history_close": round(latest_close, 3),
            "price_gap_percent": round(price_gap, 3) if price_gap is not None else None,
            "latest_history_time": latest_time,
            "latest_history_source": latest_source,
            "archived_history_time": archived_history.get("timestamp") if archived_history else None,
            "archived_history_close": round(float(archived_history["close"]), 3) if archived_history else None,
            "recommended_action": "FIX_GAP_NOW" if status != "READY" else "NONE",
            "message": self._message(status),
        }

    def _is_stale(self, timestamp: str, timeframe: str) -> bool:
        try:
            ts = pd.Timestamp(timestamp)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
        except Exception:
            return True
        max_age_hours = 72 if timeframe == "1D" else 24
        return (pd.Timestamp.now(tz="UTC") - ts).total_seconds() > max_age_hours * 3600

    def _message(self, status: str) -> str:
        return {
            "NO_HISTORY": "No historical candles are available.",
            "PRICE_GAP": "Historical price is not aligned with the latest live XAUUSD price.",
            "STALE_HISTORY": "Historical candles are stale for the selected timeframe.",
            "CRITICAL_GAP": "Historical candles are stale and far from the latest live XAUUSD price.",
            "READY": "Recent history is aligned with the latest live XAUUSD price.",
        }.get(status, status)


class RecentHistoryResolver:
    def __init__(self, store: SQLiteCandleStore):
        self.store = store

    def resolve(self, integrity: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        counts = self.store.counts()
        source_counts = self.store.source_counts()
        provider_status = self.store.load_status().to_dict()
        readiness = validate_analysis_readiness(counts)
        warnings = list((integrity or {}).get("warnings", []) or [])
        has_any_candles = any(counts.values())
        has_live_price = provider_status.get("latest_price") is not None
        has_live_source = self._has_any_source(LIVE_SOURCES)
        has_test = self._has_any_source(TEST_HISTORY_SOURCES)
        has_real_recent = self._has_any_source(REAL_RECENT_SOURCES)
        gap_detected = bool((integrity or {}).get("gap_detected"))

        if has_test:
            mode = "TEST_HISTORY_MODE"
            data_mode = "TEST"
            label = "TEST"
            description = "Generated test history + live price"
            chart_ready = True
            analysis_ready = False
            full_analysis_ready = False
            analysis_state = "Chart Ready - Test Mode"
        elif gap_detected:
            mode = "GAP_WARNING"
            data_mode = "GAP_WARNING"
            label = "GAP WARNING"
            description = "History does not match current price"
            chart_ready = has_any_candles or has_live_price
            analysis_ready = False
            full_analysis_ready = False
            analysis_state = "Waiting for Recent History"
        elif has_real_recent:
            mode = "REAL_RECENT_HISTORY"
            data_mode = "REAL"
            label = "REAL"
            description = "Recent real history + live price"
            chart_ready = has_any_candles
            full_analysis_ready = bool(readiness["ready"] and provider_status.get("status") == "LIVE")
            analysis_ready = full_analysis_ready
            analysis_state = "Full Analysis Ready" if full_analysis_ready else "Partial Analysis Ready"
        elif has_live_price or has_live_source:
            mode = "LIVE_ONLY_MODE"
            data_mode = "LIVE_ONLY"
            label = "LIVE ONLY"
            description = "Only live price, not enough candles"
            chart_ready = has_any_candles or has_live_price
            analysis_ready = False
            full_analysis_ready = False
            analysis_state = "Live Only - Waiting for Candle Build"
        else:
            mode = "NO_DATA"
            data_mode = "NO_DATA"
            label = "NO DATA"
            description = "No live price or candle history"
            chart_ready = False
            analysis_ready = False
            full_analysis_ready = False
            analysis_state = "Waiting for Data"

        actions = self._actions_for(mode, provider_status)
        return {
            "mode": mode,
            "data_mode": data_mode,
            "data_mode_label": label,
            "description": description,
            "chart_ready": chart_ready,
            "analysis_ready": analysis_ready,
            "full_analysis_ready": full_analysis_ready,
            "analysis_state": analysis_state,
            "action_required": bool(actions) and not full_analysis_ready,
            "action_choices": actions,
            "provider_status": provider_status,
            "candle_counts": counts,
            "source_counts": source_counts,
            "missing_history": readiness["missing"],
            "gap_detected": gap_detected,
            "warnings": list(dict.fromkeys(warnings)),
        }

    def _has_any_source(self, sources: set[str]) -> bool:
        for timeframe in SUPPORTED_TIMEFRAMES:
            for source in sources:
                if self.store.has_source(timeframe, source):
                    return True
        return False

    def _actions_for(self, mode: str, provider_status: Dict[str, Any]) -> list[Dict[str, str]]:
        if mode in {"NO_DATA", "LIVE_ONLY_MODE", "GAP_WARNING"}:
            actions = [
                {"id": "import_recent_history", "label": "Import Real Recent History", "description": "Upload real XAUUSD CSV candles."},
                {"id": "generate_test_history", "label": "Generate Test History", "description": "Create TEST DATA candles for development."},
                {"id": "debug_data", "label": "Debug Data", "description": "Inspect database, routes, and provider state."},
            ]
            if not provider_status.get("is_running"):
                actions.insert(2, {"id": "start_live_builder", "label": "Start Live Builder", "description": "Start Gold-API live price updates."})
            return actions
        if mode == "TEST_HISTORY_MODE":
            return [
                {"id": "clear_test_history", "label": "Clear Test History", "description": "Remove generated TEST_HISTORY candles."},
                {"id": "import_recent_history", "label": "Import Real Recent History", "description": "Replace test mode with real CSV history."},
            ]
        return []


class RecentHistorySyncService:
    def __init__(self, store: SQLiteCandleStore, recent_history_dir: str):
        self.store = store
        self.recent_history_dir = Path(recent_history_dir)

    def recent_files_found(self) -> Dict[str, bool]:
        self.recent_history_dir.mkdir(parents=True, exist_ok=True)
        return {
            timeframe: (self.recent_history_dir / f"xauusd_{timeframe.lower()}.csv").exists()
            for timeframe in SUPPORTED_TIMEFRAMES
        }

    def import_local_recent_history(self) -> Dict[str, Any]:
        imported: Dict[str, int] = {}
        errors: Dict[str, str] = {}
        last_imported: Dict[str, Optional[str]] = {}
        self.recent_history_dir.mkdir(parents=True, exist_ok=True)
        for timeframe in SUPPORTED_TIMEFRAMES:
            csv_path = self.recent_history_dir / f"xauusd_{timeframe.lower()}.csv"
            if not csv_path.exists():
                continue
            try:
                candles = self._load_recent_csv(csv_path)
                imported[timeframe] = self.store.insert_candles(timeframe, candles, RECENT_CSV_SOURCE)
                last_imported[timeframe] = candles[-1]["timestamp"] if candles else None
            except Exception as exc:
                errors[timeframe] = str(exc)
        return {
            "ok": not errors,
            "status": "RECENT_HISTORY_IMPORTED" if imported else "NO_RECENT_HISTORY_FILES",
            "source": RECENT_CSV_SOURCE,
            "history_dir": str(self.recent_history_dir),
            "history_files_found": self.recent_files_found(),
            "imported": imported,
            "last_imported_candle_time": last_imported,
            "errors": errors,
            "candle_counts": self.store.counts(),
        }

    def one_click_setup(self, live_builder: Any, history_seeder: Any, data_integrity_engine: Any, resolver: Optional[RecentHistoryResolver] = None) -> Dict[str, Any]:
        return self.one_click_warmup(live_builder, history_seeder, data_integrity_engine, resolver)

    def one_click_warmup(self, live_builder: Any, history_seeder: Any, data_integrity_engine: Any, resolver: Optional[RecentHistoryResolver] = None) -> Dict[str, Any]:
        warnings: list[str] = []
        steps: list[Dict[str, Any]] = []
        db_info = self.store.database_info()
        steps.append({"step": "backend_health", "status": "OK"})
        steps.append({"step": "sqlite_database", "status": "READY" if db_info.get("database_exists") and db_info.get("candle_tables_created") else "ERROR"})
        provider_before = self.store.load_status().to_dict()
        steps.append({"step": "live_price_provider", "status": provider_before.get("status") or "NO_DATA"})
        recent_files = self.recent_files_found()
        steps.append({"step": "recent_history_files", "status": "FOUND" if any(recent_files.values()) else "MISSING", "files": recent_files})
        recent_import = self.import_local_recent_history()
        history_imported = bool(recent_import.get("imported"))
        steps.append({"step": "import_recent_history", "status": recent_import.get("status"), "imported": recent_import.get("imported", {})})
        if not history_imported:
            seeded = history_seeder.seed_if_needed()
            if seeded.get("status") == "NO_HISTORY_FILES":
                warnings.append("No recent history files found in backend/data/xauusd_recent_history.")
            else:
                history_imported = bool(seeded.get("imported")) or bool(seeded.get("skipped"))
            steps.append({"step": "seed_preloaded_history", "status": seeded.get("status"), "imported": seeded.get("imported", {}), "skipped": seeded.get("skipped", {})})
        live_status = live_builder.start()
        steps.append({"step": "start_live_builder", "status": live_status.get("status"), "running": live_status.get("is_running")})
        live_builder.candle_builder.aggregate_all()
        steps.append({"step": "rebuild_aggregates", "status": "DONE"})
        integrity = data_integrity_engine.data_integrity("15M", 300)
        readiness = validate_analysis_readiness(self.store.counts())
        mode = resolver.resolve(integrity) if resolver else {}
        if integrity.get("gap_detected"):
            warnings.append(integrity.get("gap_warning") or HISTORY_GAP_WARNING)
        if self._has_only_live_builder_history():
            warnings.append("Gold-API live price alone cannot create full historical candle structure.")
        warnings.extend(mode.get("warnings", []))
        full_ready = bool(mode.get("full_analysis_ready")) if mode else bool(readiness.get("ready") and not integrity.get("gap_detected") and live_status.get("status") == "LIVE")
        return {
            "ok": True,
            "status": "WARMUP_READY" if full_ready else "ACTION_REQUIRED" if mode.get("action_required") else "ONE_CLICK_WARMUP_COMPLETE",
            "database_connected": bool(db_info.get("database_exists") and db_info.get("candle_tables_created")),
            "history_imported": history_imported,
            "recent_history_import": recent_import,
            "live_builder_started": bool(live_status.get("is_running")),
            "provider_status": live_status.get("status"),
            "gap_detected": bool(integrity.get("gap_detected")),
            "full_analysis_ready": full_ready,
            "data_mode": mode,
            "data_integrity": integrity,
            "candle_counts": self.store.counts(),
            "workflow_steps": steps,
            "next_actions": mode.get("action_choices", []),
            "warnings": list(dict.fromkeys(warnings)),
        }

    def _has_only_live_builder_history(self) -> bool:
        counts = self.store.counts()
        if not any(counts.values()):
            return False
        for timeframe in ["5M", "15M", "1H", "4H", "1D"]:
            if any(self.store.has_source(timeframe, source) for source in REAL_RECENT_SOURCES | {TEST_HISTORY_SOURCE}):
                return False
        return True

    def _load_recent_csv(self, csv_path: Path) -> list[Dict[str, Any]]:
        df = pd.read_csv(csv_path)
        df.columns = [col.strip().lower() for col in df.columns]
        if "timestamp" not in df.columns and "time" in df.columns:
            df = df.rename(columns={"time": "timestamp"})
        required = ["timestamp", "open", "high", "low", "close"]
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(f"{csv_path.name} missing columns: {', '.join(missing)}")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        valid = (
            (df[["open", "high", "low", "close"]] > 0).all(axis=1)
            & (df["high"] >= df[["open", "close", "low"]].max(axis=1))
            & (df["low"] <= df[["open", "close", "high"]].min(axis=1))
        )
        df = df[valid].drop_duplicates(subset=["timestamp"])
        return [
            {
                "timestamp": row["timestamp"].isoformat(),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
            }
            for _, row in df.iterrows()
        ]


class CSVBacktestProvider:
    def __init__(self, sample_csv: str, upload_csv: str):
        self.sample_csv = Path(sample_csv)
        self.upload_csv = Path(upload_csv)

    def save_upload(self, file_path: str) -> Dict[str, Any]:
        df_m5 = load_ohlcv(file_path)
        self.upload_csv.parent.mkdir(parents=True, exist_ok=True)
        df_m5.reset_index().to_csv(self.upload_csv, index=False)
        return self.backtest_frame(prefer_upload=True) | {"message": "Uploaded XAUUSD CSV saved for backtest/training only."}

    def backtest_frame(self, prefer_upload: bool = True) -> Dict[str, Any]:
        if prefer_upload and self.upload_csv.exists():
            df_m5 = load_ohlcv(str(self.upload_csv))
            source = "csv_upload"
        else:
            df_m5 = load_ohlcv(str(self.sample_csv))
            source = "csv_demo"
        return {"source": source, "df_m5": df_m5}


def validate_analysis_readiness(counts: Dict[str, int]) -> Dict[str, Any]:
    missing = []
    for timeframe, required in MIN_ANALYSIS_CANDLES.items():
        available = counts.get(timeframe, 0)
        if available < required:
            missing.append({
                "timeframe": timeframe,
                "required": required,
                "available": available,
                "message": f"Not enough {timeframe} candles. Required: {required}, Available: {available}.",
            })
    return {"ready": not missing, "missing": missing}


def normalize_timeframe(timeframe: str) -> str:
    tf = timeframe.upper().strip()
    aliases = {"M1": "1M", "M5": "5M", "M15": "15M", "H1": "1H", "H4": "4H", "D1": "1D"}
    tf = aliases.get(tf, tf)
    if tf not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {timeframe}. Use one of {', '.join(SUPPORTED_TIMEFRAMES)}")
    return tf


def _pandas_rule(timeframe: str) -> str:
    return {"5M": "5min", "15M": "15min", "1H": "1h", "4H": "4h", "1D": "1D"}[timeframe]


def _floor_time(timestamp: pd.Timestamp, timeframe: str) -> pd.Timestamp:
    if timeframe == "1M":
        return timestamp.floor("min")
    if timeframe == "5M":
        return timestamp.floor("5min")
    if timeframe == "15M":
        return timestamp.floor("15min")
    if timeframe == "1H":
        return timestamp.floor("h")
    if timeframe == "4H":
        hour = (timestamp.hour // 4) * 4
        return timestamp.replace(hour=hour, minute=0, second=0, microsecond=0, nanosecond=0)
    if timeframe == "1D":
        return timestamp.floor("D")
    return timestamp


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_price(price: Any) -> bool:
    try:
        value = float(price)
    except Exception:
        return False
    return value > 0


def _is_abnormal_spike(previous: float, current: float) -> bool:
    if previous <= 0:
        return False
    return abs(current - previous) / previous > 0.015


def _confidence_from_tick_count(tick_count: int) -> str:
    if tick_count >= 10:
        return "HIGH"
    if tick_count >= 4:
        return "MEDIUM"
    return "LOW"


def _confidence_from_child_count(child_count: int, expected_count: int) -> str:
    if expected_count <= 1:
        return _confidence_from_tick_count(child_count)
    ratio = child_count / expected_count
    if ratio >= 1:
        return "HIGH"
    if ratio >= 0.5:
        return "MEDIUM"
    return "LOW"


def _confidence_from_count(count: int, expected_count: int) -> str:
    if expected_count <= 1:
        return _confidence_from_tick_count(count)
    return _confidence_from_child_count(count, expected_count)


class CandleEngineQualityValidator:
    def __init__(self, store: SQLiteCandleStore):
        self.store = store

    def validate(self, timeframe: Optional[str] = None, limit: int = 1000) -> Dict[str, Any]:
        timeframes = [normalize_timeframe(timeframe)] if timeframe else SUPPORTED_TIMEFRAMES
        results = {tf: self._validate_timeframe(tf, limit) for tf in timeframes}
        invalid_total = sum(item["invalid_count"] for item in results.values())
        warning_total = sum(len(item["warnings"]) for item in results.values())
        return {
            "ok": invalid_total == 0,
            "status": "VALID" if invalid_total == 0 and warning_total == 0 else "WARNINGS" if invalid_total == 0 else "INVALID",
            "timeframes": results,
        }

    def _validate_timeframe(self, timeframe: str, limit: int) -> Dict[str, Any]:
        df = self.store.get_candles_df(timeframe, limit)
        warnings: list[str] = []
        invalid_count = 0
        flags: Dict[str, int] = {"VALID": 0, "LOW_TICK_CONFIDENCE": 0, "PARTIAL": 0, "GAP": 0, "OUTLIER": 0, "INVALID": 0}
        if df.empty:
            return {"status": "NO_CANDLES", "checked": 0, "invalid_count": 0, "flags": flags, "warnings": ["No candles available."]}
        duplicate_count = int(df.index.duplicated().sum())
        if duplicate_count:
            invalid_count += duplicate_count
            flags["INVALID"] += duplicate_count
            warnings.append(f"{duplicate_count} duplicate timestamps.")
        invalid_ohlc = (
            (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
            | (df["high"] < df[["open", "close", "low"]].max(axis=1))
            | (df["low"] > df[["open", "close", "high"]].min(axis=1))
        )
        invalid_ohlc_count = int(invalid_ohlc.sum())
        if invalid_ohlc_count:
            invalid_count += invalid_ohlc_count
            flags["INVALID"] += invalid_ohlc_count
            warnings.append(f"{invalid_ohlc_count} invalid OHLC candles.")
        if not df.index.is_monotonic_increasing:
            flags["GAP"] += 1
            warnings.append("Backward timestamps detected.")
        low_confidence = int((df.get("confidence", "") == "LOW").sum()) if "confidence" in df else 0
        partial = int((df.get("is_partial", 0).astype(bool)).sum()) if "is_partial" in df else 0
        flags["LOW_TICK_CONFIDENCE"] += low_confidence
        flags["PARTIAL"] += partial
        if len(df) >= 20:
            candle_range = (df["high"] - df["low"]).abs()
            median_range = float(candle_range[candle_range > 0].median() or 0)
            if median_range > 0:
                outliers = int((candle_range > median_range * 12).sum())
                flags["OUTLIER"] += outliers
                if outliers:
                    warnings.append(f"{outliers} outlier candles flagged.")
        flags["VALID"] = max(0, int(len(df)) - invalid_count)
        return {
            "status": "VALID" if invalid_count == 0 else "INVALID",
            "checked": int(len(df)),
            "invalid_count": invalid_count,
            "flags": flags,
            "warnings": warnings,
        }


class CandleHealthService:
    def __init__(self, store: SQLiteCandleStore, builder: Optional[LocalCandleBuilder] = None):
        self.store = store
        self.builder = builder

    def health(self, timeframe: str = "15M", limit: int = 1000) -> Dict[str, Any]:
        tf = normalize_timeframe(timeframe)
        sources, source_label = self._preferred_sources(tf)
        df = self.store.get_candles_df(tf, limit, sources=sources)
        completed = df[df["is_complete"].astype(bool)] if not df.empty and "is_complete" in df else df
        partial = df[df["is_partial"].astype(bool)] if not df.empty and "is_partial" in df else df.iloc[0:0]
        completed_count = int(len(completed))
        partial_count = int(len(partial))
        minimum = HEALTHY_CANDLE_MINIMUMS[tf]
        confidence_counts: Dict[str, int] = {}
        if not df.empty and "confidence" in df:
            confidence_counts = {str(key): int(value) for key, value in df["confidence"].fillna("UNKNOWN").value_counts().to_dict().items()}
        latest_completed_time = None
        if completed_count:
            latest_completed_time = pd.Timestamp(completed.index[-1]).isoformat()
        warnings: list[str] = []
        if completed_count == 0:
            health_status = "NO_COMPLETED_CANDLES"
            warnings.append(f"No completed {tf} candles yet. Keep live builder running or import recent history.")
        elif completed_count < minimum:
            health_status = "WARMING_UP"
            warnings.append(f"Not enough completed {tf} candles yet. Building chart history...")
        else:
            health_status = "HEALTHY"
        if confidence_counts.get("LOW", 0):
            warnings.append("LOW_TICK_CONFIDENCE candles are present.")
        return {
            "timeframe": tf,
            "source": source_label,
            "completed_count": completed_count,
            "partial_count": partial_count,
            "latest_completed_time": latest_completed_time,
            "health_status": health_status,
            "healthy_minimum": minimum,
            "confidence_summary": confidence_counts,
            "latest_partial_candle": candles_to_records(partial.tail(1), 1)[0] if partial_count else None,
            "warnings": warnings,
            "outlier_rejected_count": self.builder.rejected_outliers if self.builder else 0,
        }

    def _preferred_sources(self, timeframe: str) -> tuple[Optional[set[str]], str]:
        priority = [
            (OANDA_HISTORY_SOURCE, {OANDA_HISTORY_SOURCE}),
            (BINANCE_HISTORY_SOURCE, {BINANCE_HISTORY_SOURCE}),
            (TWELVE_DATA_HISTORY_SOURCE, {TWELVE_DATA_HISTORY_SOURCE}),
            (REAL_CSV_HISTORY_SOURCE, {REAL_CSV_HISTORY_SOURCE}),
            (USER_RECENT_CSV_SOURCE, {USER_RECENT_CSV_SOURCE}),
            (RECENT_CSV_SOURCE, {RECENT_CSV_SOURCE}),
            (LIVE_SOURCE, {LIVE_SOURCE, LIVE_BUILDER_SOURCE}),
        ]
        for label, sources in priority:
            if any(self.store.has_source(timeframe, source) for source in sources):
                return sources, label
        return None, "AUTO"
