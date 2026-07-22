from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class ClosedCandleAlerts:
    """Deduplicated lifecycle alerts created only from trusted completed-candle analysis."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=20)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self.connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS closed_candle_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    event_time INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    side TEXT,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    entry REAL,
                    stop REAL,
                    target REAL,
                    source TEXT,
                    acknowledged INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    acknowledged_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_closed_alerts_market
                    ON closed_candle_alerts(symbol, acknowledged, id DESC);
                """
            )

    def record(self, analysis: Dict[str, Any], timeframe: str) -> Optional[Dict[str, Any]]:
        symbol = str(analysis.get("symbol") or analysis.get("market_symbol") or "XAUUSD").upper()
        normalized_timeframe = str(timeframe or "15M").upper()
        zones = analysis.get("key_zones") or {}
        reconciliation = analysis.get("feed_reconciliation") or {}
        decision_quality = analysis.get("decision_quality") or {}
        if reconciliation.get("trusted") is not True:
            return None
        auto_entry = analysis.get("diamond_auto_entry") or {}
        execution = analysis.get("execution_reality") or {}
        news = analysis.get("news_intelligence") or {}
        primary = zones.get("primary_zone") or {}
        confirmed = bool(
            zones.get("entry_event_status") == "CONFIRMED_ENTRY"
            and decision_quality.get("current_event") is True
            and str(primary.get("smt_execution_gate") or "NEUTRAL").upper() != "BLOCK_CONFLICT"
        )
        event = zones.get("latest_entry_event") or {}
        transition = "CONFIRMED"
        if confirmed:
            side = str(event.get("entry_side") or "WAIT").upper()
            if news.get("execution_gate") == "BLOCK_NEW_ENTRIES":
                kind, priority = "DIAMOND_NEWS_LOCKED", "HOLD"
                title = f"{side.title()} Diamond confirmed - News lock"
            elif auto_entry.get("status") == "AUTO_ARMED" and execution.get("research_trackable") is True:
                kind, priority = "TRACKABLE_DIAMOND_SETUP", "ACTION"
                title = f"Trackable {side.title()} Diamond"
            else:
                kind, priority = "DIAMOND_CONFIRMED_RESEARCH", "WATCH"
                title = f"{side.title()} Diamond confirmed"
        else:
            lead = zones.get("lead_diamond_zone") or {}
            invalidated = next((
                item for item in reversed(zones.get("zones") or [])
                if str(item.get("lifecycle") or "").upper() in {"INVALIDATED", "FLIPPED"}
                or str(item.get("entry_stage") or "").upper() == "INVALIDATED"
            ), None)
            lead_score = self._number(lead.get("diamond_score") or lead.get("diamond_confidence_score")) or 0
            if lead and lead_score >= 70 and news.get("execution_gate") == "BLOCK_NEW_ENTRIES":
                event = lead
                transition = "NEWS_LOCK"
                side = str(lead.get("entry_side") or ("BUY" if lead.get("direction") == "BULLISH" else "SELL")).upper()
                kind, priority = "DIAMOND_NEWS_LOCKED", "HOLD"
                title = f"{side.title()} Diamond paused by news"
            elif lead and lead_score >= 70 and (self._number(lead.get("distance_atr")) or 99) <= 1.25:
                event = lead
                transition = "APPROACH"
                side = str(lead.get("entry_side") or ("BUY" if lead.get("direction") == "BULLISH" else "SELL")).upper()
                kind, priority = "DIAMOND_ZONE_APPROACH", "WATCH"
                title = f"Price approaching {side.title()} Diamond"
            elif invalidated:
                event = invalidated
                transition = "INVALIDATED"
                side = str(invalidated.get("entry_side") or ("BUY" if invalidated.get("direction") == "BULLISH" else "SELL")).upper()
                kind, priority = "DIAMOND_INVALIDATED", "HOLD"
                title = f"{side.title()} Diamond invalidated"
            else:
                return None

        event_id = str(event.get("id") or event.get("zone_id") or "")
        event_time = self._integer(event.get("confirmation_time") or event.get("available_at") or event.get("time"))
        if not event_id or event_time is None:
            return None
        entry = self._number(event.get("execution_entry") or execution.get("entry"))
        if entry is None:
            entry = self._number(event.get("line") or event.get("marker_price"))
        stop = self._number(auto_entry.get("stop_loss") or execution.get("stop"))
        targets = auto_entry.get("take_profit_levels") or []
        target = self._number(targets[0]) if targets else self._number(execution.get("target"))
        quality = event.get("diamond_score") or event.get("quality_score") or "-"
        message = f"Completed-candle {side.lower()} Diamond {transition.lower()} on {normalized_timeframe}. Quality {quality}."
        payload = {
            "event": event,
            "auto_entry_status": auto_entry.get("status"),
            "execution_reality_status": execution.get("status"),
            "feed_reconciliation_status": reconciliation.get("status"),
            "news_gate": news.get("execution_gate"),
            "transition": transition,
            "completed_candle_only": True,
        }
        now = datetime.now(timezone.utc).isoformat()
        event_key = f"{symbol}:{normalized_timeframe}:{event_id}:{transition}"
        with self._lock, closing(self.connect()) as connection, connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO closed_candle_alerts (
                    event_key, symbol, timeframe, event_time, kind, priority, side,
                    title, message, entry, stop, target, source, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_key,
                    symbol,
                    normalized_timeframe,
                    event_time,
                    kind,
                    priority,
                    side,
                    title,
                    message,
                    entry,
                    stop,
                    target,
                    reconciliation.get("chart_source"),
                    json.dumps(payload, sort_keys=True),
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM closed_candle_alerts WHERE event_key = ?",
                (event_key,),
            ).fetchone()
        if not row:
            return None
        result = self._public(row)
        result["is_new"] = cursor.rowcount == 1
        return result

    def list(self, symbol: str, limit: int = 20, unacknowledged_only: bool = False) -> Dict[str, Any]:
        normalized_symbol = str(symbol or "XAUUSD").upper()
        where = "symbol = ? AND acknowledged = 0" if unacknowledged_only else "symbol = ?"
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM closed_candle_alerts WHERE {where} ORDER BY id DESC LIMIT ?",
                (normalized_symbol, max(1, min(int(limit), 100))),
            ).fetchall()
            stats = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN acknowledged = 0 THEN 1 ELSE 0 END) AS unread,
                       SUM(CASE WHEN priority = 'ACTION' THEN 1 ELSE 0 END) AS action_count
                FROM closed_candle_alerts WHERE symbol = ?
                """,
                (normalized_symbol,),
            ).fetchone()
        return {
            "status": "OK",
            "symbol": normalized_symbol,
            "alerts": [self._public(row) for row in rows],
            "stats": {
                "total": int((stats["total"] if stats else 0) or 0),
                "unread": int((stats["unread"] if stats else 0) or 0),
                "action_count": int((stats["action_count"] if stats else 0) or 0),
            },
            "delivery": "IN_APP_AND_OPT_IN_DEVICE",
            "broker_orders_enabled": False,
        }

    def acknowledge(self, alert_id: int) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, closing(self.connect()) as connection, connection:
            connection.execute(
                "UPDATE closed_candle_alerts SET acknowledged = 1, acknowledged_at = ? WHERE id = ?",
                (now, int(alert_id)),
            )
            row = connection.execute(
                "SELECT * FROM closed_candle_alerts WHERE id = ?",
                (int(alert_id),),
            ).fetchone()
        return self._public(row) if row else None

    @staticmethod
    def _public(row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        item["acknowledged"] = bool(item.get("acknowledged"))
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
