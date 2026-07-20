from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


ACTIVE_STATUSES = {"WAITING_ENTRY", "OPEN"}
TERMINAL_STATUSES = {"WON", "LOST", "EXPIRED", "AMBIGUOUS", "CANCELLED"}
TIMEFRAME_SECONDS = {"1M": 60, "5M": 300, "15M": 900, "1H": 3600, "4H": 14400, "1D": 86400}
EXPIRY_BARS = {"1M": 45, "5M": 36, "15M": 24, "1H": 16, "4H": 10, "1D": 5}


class SetupTracker:
    """Persist and conservatively verify setup outcomes against closed candles."""

    def __init__(self, db_path: str | Path, retention_per_symbol: int = 500):
        self.db_path = str(db_path)
        self.retention_per_symbol = max(50, int(retention_per_symbol))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tracked_setups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    journal_run_id INTEGER,
                    fingerprint TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    evaluation_start_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    analysis_status TEXT NOT NULL,
                    lifecycle_status TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    target_1 REAL NOT NULL,
                    risk_reward REAL,
                    score REAL,
                    analysis_source TEXT,
                    trust_status TEXT NOT NULL,
                    entry_hit_at TEXT,
                    closed_at TEXT,
                    close_price REAL,
                    outcome_r REAL,
                    max_favorable_r REAL NOT NULL DEFAULT 0,
                    max_adverse_r REAL NOT NULL DEFAULT 0,
                    last_candle_at TEXT,
                    note TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracked_setups_symbol_id ON tracked_setups(symbol, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracked_setups_active ON tracked_setups(symbol, lifecycle_status)"
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(tracked_setups)").fetchall()}
            migrations = {
                "setup_model": "TEXT NOT NULL DEFAULT 'LEGACY_CANDIDATE'",
                "entry_model": "TEXT",
                "quality_tier": "TEXT",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE tracked_setups ADD COLUMN {name} {definition}")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracked_setups_model ON tracked_setups(symbol, setup_model, id DESC)"
            )

    def register(
        self,
        analysis: Dict[str, Any],
        timeframe: str,
        journal_run_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        plan = analysis.get("trade_plan") or {}
        signal = analysis.get("signal") or {}
        trust = analysis.get("trust_gate") or {}
        status = str(plan.get("status") or "").upper()
        direction = str(plan.get("direction") or "").upper()
        tf = str(timeframe or "15M").upper()
        targets = plan.get("take_profit_levels") or []
        entry = self._number(plan.get("entry_price"))
        stop = self._number(plan.get("stop_loss"))
        target = self._number(targets[0]) if targets else None

        if not trust.get("trusted") or status not in {"CANDIDATE", "ACTIONABLE"}:
            return None
        if direction not in {"BUY", "SELL"} or tf not in TIMEFRAME_SECONDS:
            return None
        if not self._valid_geometry(direction, entry, stop, target):
            return None

        symbol = str(analysis.get("symbol") or analysis.get("market_symbol") or "UNKNOWN").upper()
        order_type = str(plan.get("order_type") or "LIMIT").upper()
        diamond = analysis.get("diamond_auto_entry") or {}
        diamond_armed = bool(
            diamond.get("status") == "AUTO_ARMED"
            and plan.get("auto_entry_armed") is True
            and str(plan.get("position_type") or "").upper() == "CONFIRMED_ENTRY"
        )
        setup_model = "DIAMOND_V6_AUTO" if diamond_armed else "INSTITUTIONAL_CANDIDATE"
        entry_model = str(
            diamond.get("entry_model")
            or plan.get("position_type")
            or order_type
        ).upper()
        quality_tier = str(
            diamond.get("precision_grade")
            or plan.get("quality_grade")
            or signal.get("quality_grade")
            or "-"
        ).upper()
        fingerprint = self._fingerprint(symbol, tf, direction, order_type, entry, stop, target, setup_model)
        existing = self._active_by_fingerprint(fingerprint)
        if existing:
            return {**existing, "created": False, "deduplicated": True}

        now = datetime.now(timezone.utc)
        interval = TIMEFRAME_SECONDS[tf]
        next_boundary = datetime.fromtimestamp(((int(now.timestamp()) // interval) + 1) * interval, tz=timezone.utc)
        expires_at = next_boundary + timedelta(seconds=interval * EXPIRY_BARS[tf])
        is_market = status == "ACTIONABLE" and order_type == "MARKET" and signal.get("execution_allowed")
        lifecycle = "OPEN" if is_market else "WAITING_ENTRY"
        entry_hit_at = now.isoformat() if is_market else None
        risk = abs(float(entry) - float(stop))
        reward = abs(float(target) - float(entry))
        risk_reward = reward / risk if risk else None

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tracked_setups (
                    journal_run_id, fingerprint, symbol, timeframe, created_at,
                    evaluation_start_at, expires_at, updated_at, direction, order_type,
                    analysis_status, lifecycle_status, entry_price, stop_loss, target_1,
                    risk_reward, score, analysis_source, trust_status, entry_hit_at, note
                    , setup_model, entry_model, quality_tier
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    journal_run_id, fingerprint, symbol, tf, now.isoformat(), next_boundary.isoformat(),
                    expires_at.isoformat(), now.isoformat(), direction, order_type, status, lifecycle,
                    entry, stop, target, risk_reward, self._number(signal.get("score")),
                    analysis.get("analysis_data_source"), str(trust.get("status") or "TRUSTED"),
                    entry_hit_at, "Market setup opened at analysis time." if is_market else "Waiting for entry on a future closed candle.",
                    setup_model, entry_model, quality_tier,
                ),
            )
            setup_id = int(cursor.lastrowid)
            connection.execute(
                """
                DELETE FROM tracked_setups
                WHERE symbol = ? AND id NOT IN (
                    SELECT id FROM tracked_setups WHERE symbol = ? ORDER BY id DESC LIMIT ?
                )
                """,
                (symbol, symbol, self.retention_per_symbol),
            )
        created = self.get(setup_id)
        return {**created, "created": True, "deduplicated": False} if created else None

    def evaluate(self, setup_id: int, candles: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        setup = self.get(setup_id)
        if not setup or setup["lifecycle_status"] in TERMINAL_STATUSES:
            return setup

        status = setup["lifecycle_status"]
        direction = setup["direction"]
        entry = float(setup["entry_price"])
        stop = float(setup["stop_loss"])
        target = float(setup["target_1"])
        risk = abs(entry - stop)
        evaluation_start = self._datetime(setup["evaluation_start_at"])
        expires_at = self._datetime(setup["expires_at"])
        entry_hit_at = setup.get("entry_hit_at")
        closed_at = setup.get("closed_at")
        close_price = setup.get("close_price")
        outcome_r = setup.get("outcome_r")
        max_favorable = float(setup.get("max_favorable_r") or 0)
        max_adverse = float(setup.get("max_adverse_r") or 0)
        last_candle_at = setup.get("last_candle_at")
        note = setup.get("note")

        normalized = []
        for candle in candles:
            timestamp = self._datetime(candle.get("time") or candle.get("timestamp"))
            if timestamp is None or evaluation_start is None or timestamp < evaluation_start:
                continue
            try:
                normalized.append((timestamp, float(candle["open"]), float(candle["high"]), float(candle["low"]), float(candle["close"])))
            except (KeyError, TypeError, ValueError):
                continue
        normalized.sort(key=lambda item: item[0])

        for timestamp, _open, high, low, close in normalized:
            if last_candle_at and timestamp <= self._datetime(last_candle_at):
                continue
            last_candle_at = timestamp.isoformat()
            entry_touched = low <= entry <= high
            stop_touched = low <= stop if direction == "BUY" else high >= stop
            target_touched = high >= target if direction == "BUY" else low <= target

            if status == "WAITING_ENTRY":
                if not entry_touched:
                    if expires_at is not None and timestamp >= expires_at:
                        status = "EXPIRED"
                        closed_at = timestamp.isoformat()
                        note = "Entry was not reached before the setup expired."
                        break
                    continue
                entry_hit_at = timestamp.isoformat()
                if stop_touched or target_touched:
                    status = "AMBIGUOUS"
                    closed_at = timestamp.isoformat()
                    close_price = close
                    note = "Entry and an exit level were touched in the same candle; intrabar order is unknown."
                    break
                status = "OPEN"
                note = "Entry confirmed by a completed provider candle."

            if status == "OPEN":
                favorable = high - entry if direction == "BUY" else entry - low
                adverse = entry - low if direction == "BUY" else high - entry
                if risk:
                    max_favorable = max(max_favorable, favorable / risk)
                    max_adverse = max(max_adverse, adverse / risk)
                if stop_touched and target_touched:
                    status = "AMBIGUOUS"
                    closed_at = timestamp.isoformat()
                    close_price = close
                    note = "Stop and target were touched in the same candle; outcome is not assumed."
                    break
                if stop_touched:
                    status = "LOST"
                    closed_at = timestamp.isoformat()
                    close_price = stop
                    outcome_r = -1.0
                    note = "Stop loss confirmed by a completed provider candle."
                    break
                if target_touched:
                    status = "WON"
                    closed_at = timestamp.isoformat()
                    close_price = target
                    outcome_r = round(abs(target - entry) / risk, 4) if risk else None
                    note = "Target 1 confirmed by a completed provider candle."
                    break

        self._update(
            setup_id,
            lifecycle_status=status,
            entry_hit_at=entry_hit_at,
            closed_at=closed_at,
            close_price=close_price,
            outcome_r=outcome_r,
            max_favorable_r=round(max_favorable, 4),
            max_adverse_r=round(max_adverse, 4),
            last_candle_at=last_candle_at,
            note=note,
        )
        return self.get(setup_id)

    def cancel(self, setup_id: int) -> Optional[Dict[str, Any]]:
        setup = self.get(setup_id)
        if not setup or setup["lifecycle_status"] not in ACTIVE_STATUSES:
            return setup
        self._update(
            setup_id,
            lifecycle_status="CANCELLED",
            closed_at=datetime.now(timezone.utc).isoformat(),
            note="Setup cancelled by the user.",
        )
        return self.get(setup_id)

    def active(self, symbol: Optional[str] = None, setup_model: Optional[str] = None) -> list[Dict[str, Any]]:
        params: list[Any] = list(ACTIVE_STATUSES)
        where = "lifecycle_status IN (?, ?)"
        if symbol:
            where += " AND symbol = ?"
            params.append(symbol.upper())
        if setup_model:
            where += " AND setup_model = ?"
            params.append(setup_model.upper())
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM tracked_setups WHERE {where} ORDER BY id DESC",
                tuple(params),
            ).fetchall()
        return [self._row(row) for row in rows]

    def list(
        self,
        symbol: Optional[str] = None,
        limit: int = 20,
        setup_model: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        where = []
        params: list[Any] = []
        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())
        if setup_model:
            where.append("setup_model = ?")
            params.append(setup_model.upper())
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM tracked_setups{clause} ORDER BY id DESC LIMIT ?",
                (*params, safe_limit),
            ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, setup_id: int) -> Optional[Dict[str, Any]]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tracked_setups WHERE id = ?", (int(setup_id),)).fetchone()
        return self._row(row) if row else None

    def stats(self, symbol: Optional[str] = None, setup_model: Optional[str] = None) -> Dict[str, Any]:
        filters = []
        params: list[Any] = []
        if symbol:
            filters.append("symbol = ?")
            params.append(symbol.upper())
        if setup_model:
            filters.append("setup_model = ?")
            params.append(setup_model.upper())
        where = f" WHERE {' AND '.join(filters)}" if filters else ""
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN lifecycle_status IN ('WAITING_ENTRY', 'OPEN') THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN lifecycle_status = 'WON' THEN 1 ELSE 0 END) AS won,
                       SUM(CASE WHEN lifecycle_status = 'LOST' THEN 1 ELSE 0 END) AS lost,
                       SUM(CASE WHEN lifecycle_status = 'EXPIRED' THEN 1 ELSE 0 END) AS expired,
                       SUM(CASE WHEN lifecycle_status = 'AMBIGUOUS' THEN 1 ELSE 0 END) AS ambiguous,
                       AVG(CASE WHEN outcome_r IS NOT NULL THEN outcome_r END) AS average_r,
                       SUM(CASE WHEN outcome_r IS NOT NULL THEN outcome_r ELSE 0 END) AS net_r
                FROM tracked_setups{where}
                """,
                tuple(params),
            ).fetchone()
        won = int(row["won"] or 0)
        lost = int(row["lost"] or 0)
        resolved = won + lost
        return {
            "total": int(row["total"] or 0),
            "active": int(row["active"] or 0),
            "won": won,
            "lost": lost,
            "expired": int(row["expired"] or 0),
            "ambiguous": int(row["ambiguous"] or 0),
            "verified_win_rate": round(won / resolved * 100, 1) if resolved else None,
            "average_r": round(float(row["average_r"]), 2) if row["average_r"] is not None else None,
            "net_r": round(float(row["net_r"] or 0), 2),
            "method": "CLOSED_CANDLE_VERIFICATION",
            "setup_model": setup_model.upper() if setup_model else "ALL",
        }

    def _active_by_fingerprint(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tracked_setups WHERE fingerprint = ? AND lifecycle_status IN ('WAITING_ENTRY', 'OPEN') ORDER BY id DESC LIMIT 1",
                (fingerprint,),
            ).fetchone()
        return self._row(row) if row else None

    def _update(self, setup_id: int, **values: Any) -> None:
        allowed = {
            "lifecycle_status", "entry_hit_at", "closed_at", "close_price", "outcome_r",
            "max_favorable_r", "max_adverse_r", "last_candle_at", "note",
        }
        fields = {key: value for key, value in values.items() if key in allowed}
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE tracked_setups SET {assignments} WHERE id = ?",
                (*fields.values(), int(setup_id)),
            )

    @staticmethod
    def _row(row: sqlite3.Row) -> Dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    @staticmethod
    def _valid_geometry(direction: str, entry: Optional[float], stop: Optional[float], target: Optional[float]) -> bool:
        if entry is None or stop is None or target is None or min(entry, stop, target) <= 0:
            return False
        return stop < entry < target if direction == "BUY" else target < entry < stop

    @staticmethod
    def _fingerprint(
        symbol: str,
        timeframe: str,
        direction: str,
        order_type: str,
        entry: float,
        stop: float,
        target: float,
        setup_model: str = "INSTITUTIONAL_CANDIDATE",
    ) -> str:
        payload = [setup_model, symbol, timeframe, direction, order_type, round(entry, 5), round(stop, 5), round(target, 5)]
        return hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
