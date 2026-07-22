from __future__ import annotations

import html
import queue
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests


class TelegramDiamondAlerts:
    """Deliver each new confirmed Diamond entry zone once without blocking analysis."""

    ALLOWED_KINDS = {
        "TRACKABLE_DIAMOND_SETUP",
        "DIAMOND_CONFIRMED_RESEARCH",
    }

    def __init__(self, db_path: str | Path, settings: Any):
        self.db_path = str(db_path)
        self.settings = settings
        self._queue: queue.Queue[tuple[Dict[str, Any], Dict[str, Any]]] = queue.Queue(maxsize=100)
        self._session = requests.Session()
        self._lock = threading.RLock()
        self._initialize()
        self._worker = threading.Thread(
            target=self._run,
            name="telegram-diamond-alerts",
            daemon=True,
        )
        self._worker.start()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=20)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self.connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS telegram_diamond_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    telegram_message_id TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_telegram_delivery_status
                    ON telegram_diamond_deliveries(status, id DESC);
                """
            )

    def status(self) -> Dict[str, Any]:
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'DELIVERED' THEN 1 ELSE 0 END) AS delivered,
                       SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed,
                       MAX(delivered_at) AS last_delivered_at
                FROM telegram_diamond_deliveries
                """
            ).fetchone()
        token_saved = bool(self.settings.get("telegram_bot_token"))
        chat_id = str(self.settings.get("telegram_chat_id") or "").strip()
        enabled = self._enabled(self.settings.get("telegram_alerts_enabled"))
        ready = enabled and token_saved and bool(chat_id)
        return {
            "status": "READY" if ready else "DISABLED" if not enabled else "NEEDS_CONFIGURATION",
            "connection_state": "AUTO_CONNECTED" if ready else "PAUSED" if token_saved and chat_id else "SETUP_REQUIRED",
            "auto_restore": bool(token_saved and chat_id),
            "enabled": enabled,
            "bot_token_saved": token_saved,
            "chat_id_saved": bool(chat_id),
            "chat_id": self._masked_chat_id(chat_id),
            "verified": self._enabled(self.settings.get("telegram_connection_verified")),
            "verified_at": self.settings.get("telegram_verified_at") or None,
            "bot_username": self.settings.get("telegram_bot_username") or None,
            "delivery_policy": "NEW_CONFIRMED_ENTRY_ZONE_ONCE",
            "queue_depth": self._queue.qsize(),
            "stats": {
                "total": int((row["total"] if row else 0) or 0),
                "delivered": int((row["delivered"] if row else 0) or 0),
                "failed": int((row["failed"] if row else 0) or 0),
                "last_delivered_at": row["last_delivered_at"] if row else None,
            },
        }

    def configure(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        verified: Optional[bool] = None,
        bot_username: Optional[str] = None,
    ) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        credentials_replaced = bool(str(bot_token or "").strip() or str(chat_id or "").strip())
        if str(bot_token or "").strip():
            values["telegram_bot_token"] = str(bot_token).strip()
        if str(chat_id or "").strip():
            values["telegram_chat_id"] = str(chat_id).strip()
        if enabled is not None:
            values["telegram_alerts_enabled"] = bool(enabled)
        if verified is not None:
            values["telegram_connection_verified"] = bool(verified)
        elif credentials_replaced:
            values["telegram_connection_verified"] = False
        if verified:
            values["telegram_verified_at"] = datetime.now(timezone.utc).isoformat()
        if str(bot_username or "").strip():
            values["telegram_bot_username"] = str(bot_username).strip().lstrip("@")
        self.settings.update(values)
        return self.status()

    def send_test(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        token = str(bot_token or self.settings.get("telegram_bot_token") or "").strip()
        target = str(chat_id or self.settings.get("telegram_chat_id") or "").strip()
        if not token or not target:
            return {
                "ok": False,
                "status": "NEEDS_CONFIGURATION",
                "message": "Add the Telegram bot token and group chat ID first.",
            }
        identity = self._request(token, "getMe", {})
        if not identity.get("ok"):
            return identity
        result = self._send_message(
            token,
            target,
            (
                "<b>SH Market Analyzer</b>\n"
                "Telegram បានភ្ជាប់ជោគជ័យ។\n"
                "Bot នឹងផ្ញើតែ Diamond Entry Zone ថ្មីដែល Engine បានបញ្ជាក់។"
            ),
        )
        if result.get("ok"):
            bot = (identity.get("result") or {}).get("username")
            result.update({
                "status": "VERIFIED",
                "message": f"Telegram group alert connected{f' to @{bot}' if bot else ''}.",
                "bot_username": bot,
            })
        return result

    def enqueue(self, alert: Optional[Dict[str, Any]], analysis: Dict[str, Any]) -> Dict[str, Any]:
        if not alert or alert.get("is_new") is not True:
            return {"queued": False, "reason": "NOT_A_NEW_ALERT"}
        if str(alert.get("kind") or "") not in self.ALLOWED_KINDS:
            return {"queued": False, "reason": "ALERT_KIND_NOT_DELIVERED"}
        if not self._enabled(self.settings.get("telegram_alerts_enabled")):
            return {"queued": False, "reason": "TELEGRAM_DISABLED"}
        if not self.settings.get("telegram_bot_token") or not self.settings.get("telegram_chat_id"):
            return {"queued": False, "reason": "TELEGRAM_NOT_CONFIGURED"}

        event_key = str(alert.get("event_key") or "").strip()
        if not event_key:
            return {"queued": False, "reason": "MISSING_EVENT_KEY"}
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, closing(self.connect()) as connection, connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO telegram_diamond_deliveries (
                    event_key, symbol, timeframe, kind, status, created_at
                ) VALUES (?, ?, ?, ?, 'QUEUED', ?)
                """,
                (
                    event_key,
                    str(alert.get("symbol") or "UNKNOWN"),
                    str(alert.get("timeframe") or "-"),
                    str(alert.get("kind") or "DIAMOND_CONFIRMED_RESEARCH"),
                    now,
                ),
            )
            inserted = cursor.rowcount == 1
        if not inserted:
            return {"queued": False, "reason": "ALREADY_DELIVERED_OR_QUEUED"}
        try:
            self._queue.put_nowait((dict(alert), self._delivery_context(analysis)))
        except queue.Full:
            self._mark(event_key, "FAILED", 0, "Alert queue is full.")
            return {"queued": False, "reason": "QUEUE_FULL"}
        return {"queued": True, "event_key": event_key}

    def _run(self) -> None:
        while True:
            alert, context = self._queue.get()
            try:
                self._deliver(alert, context)
            finally:
                self._queue.task_done()

    def _deliver(self, alert: Dict[str, Any], context: Dict[str, Any]) -> None:
        event_key = str(alert.get("event_key") or "")
        token = str(self.settings.get("telegram_bot_token") or "").strip()
        chat_id = str(self.settings.get("telegram_chat_id") or "").strip()
        if not token or not chat_id or not self._enabled(self.settings.get("telegram_alerts_enabled")):
            self._mark(event_key, "FAILED", 0, "Telegram alerts are disabled or incomplete.")
            return

        message = self._message(alert, context)
        last_error = "Telegram delivery failed."
        for attempt in range(1, 4):
            result = self._send_message(token, chat_id, message)
            if result.get("ok"):
                message_id = str((result.get("result") or {}).get("message_id") or "")
                self._mark(event_key, "DELIVERED", attempt, None, message_id)
                return
            last_error = str(result.get("message") or last_error)
            if attempt < 3:
                time.sleep(attempt)
        self._mark(event_key, "FAILED", 3, last_error)

    def _send_message(self, token: str, chat_id: str, text: str) -> Dict[str, Any]:
        return self._request(token, "sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })

    def _request(self, token: str, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = self._session.post(
                f"https://api.telegram.org/bot{token}/{method}",
                json=payload,
                timeout=8,
            )
        except requests.RequestException:
            return {
                "ok": False,
                "status": "CONNECTION_FAILED",
                "message": "Could not reach Telegram. Check the network and try again.",
            }
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.ok and data.get("ok") is True:
            return data
        description = str(data.get("description") or "Telegram rejected the request.")
        return {
            "ok": False,
            "status": "TELEGRAM_REJECTED",
            "message": description,
        }

    def _mark(
        self,
        event_key: str,
        status: str,
        attempts: int,
        error: Optional[str],
        message_id: Optional[str] = None,
    ) -> None:
        delivered_at = datetime.now(timezone.utc).isoformat() if status == "DELIVERED" else None
        with self._lock, closing(self.connect()) as connection, connection:
            connection.execute(
                """
                UPDATE telegram_diamond_deliveries
                SET status = ?, attempts = ?, telegram_message_id = ?, last_error = ?, delivered_at = ?
                WHERE event_key = ?
                """,
                (status, attempts, message_id, error, delivered_at, event_key),
            )

    @staticmethod
    def _delivery_context(analysis: Dict[str, Any]) -> Dict[str, Any]:
        zones = analysis.get("key_zones") or {}
        event = zones.get("latest_entry_event") or zones.get("lead_diamond_zone") or zones.get("primary_zone") or {}
        regime = analysis.get("market_regime") or {}
        return {
            "style": zones.get("trading_style"),
            "zone": event.get("line") or event.get("execution_entry") or event.get("marker_price"),
            "grade": event.get("diamond_grade") or event.get("precision_grade") or zones.get("diamond_grade"),
            "score": event.get("diamond_score") or event.get("quality_score") or zones.get("diamond_score"),
            "model": event.get("origin_model") or event.get("entry_pathway") or (zones.get("precision_gate") or {}).get("origin_model"),
            "regime": regime.get("regime"),
            "regime_direction": regime.get("regime_direction"),
            "confidence_label": zones.get("confidence_label"),
        }

    @staticmethod
    def _message(alert: Dict[str, Any], context: Dict[str, Any]) -> str:
        raw_side = str(alert.get("side") or "WAIT").upper()
        side = html.escape({"BUY": "ទិញ (BUY)", "SELL": "លក់ (SELL)"}.get(raw_side, raw_side))
        symbol = html.escape(str(alert.get("symbol") or "UNKNOWN").upper())
        timeframe = html.escape(str(alert.get("timeframe") or "-").upper())
        raw_style = str(context.get("style") or "-").upper()
        style = html.escape({"SCALPING": "Scalp", "SCALP": "Scalp", "SWING": "Swing"}.get(raw_style, raw_style.title()))
        grade = html.escape(str(context.get("grade") or "-"))
        score = html.escape(str(context.get("score") or "-"))
        zone = context.get("zone")
        zone_text = f"{float(zone):.5f}" if isinstance(zone, (int, float)) else "-"
        model = html.escape(str(context.get("model") or "STRUCTURAL SETUP").replace("_", " ").title())
        raw_regime = str(context.get("regime") or "WAITING").upper()
        regime = html.escape({
            "TRENDING_BULLISH": "ទីផ្សារកំពុងឡើង",
            "TRENDING_BEARISH": "ទីផ្សារកំពុងចុះ",
            "RANGE": "ទីផ្សារក្នុងចន្លោះ",
            "RANGING": "ទីផ្សារក្នុងចន្លោះ",
            "WAITING": "កំពុងរង់ចាំទិន្នន័យ",
        }.get(raw_regime, raw_regime.replace("_", " ").title()))
        confidence = html.escape(str(context.get("confidence_label") or "Setup Confirmed"))
        return (
            "<b>SH DIAMOND ENTRY ថ្មី</b>\n"
            f"<b>{symbol} | {timeframe} | {style}</b>\n\n"
            f"ទិសដៅ៖ <b>{side}</b>\n"
            f"កម្រិត៖ <b>{grade}</b> ({score}%)\n"
            f"តំបន់ Entry៖ <b>{zone_text}</b>\n"
            f"ស្ថានភាព៖ {confidence}\n"
            f"Strategy៖ {model}\n"
            f"ស្ថានភាពទីផ្សារ៖ {regime}\n\n"
            "<b>Engine បានបញ្ជាក់ Entry Zone ថ្មី។</b>\n"
            "សូមពិនិត្យតម្លៃបច្ចុប្បន្ន និងព័ត៌មានទីផ្សារមុនពេលសម្រេចចិត្ត។"
        )

    @staticmethod
    def _enabled(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _masked_chat_id(value: str) -> Optional[str]:
        chat_id = str(value or "").strip()
        if not chat_id:
            return None
        if len(chat_id) <= 6:
            return "*" * len(chat_id)
        return f"{chat_id[:4]}...{chat_id[-3:]}"
