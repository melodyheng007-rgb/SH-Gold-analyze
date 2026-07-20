from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd


SENSITIVE_KEY_PARTS = ("token", "api_key", "authorization", "secret", "password")


class AnalysisJournal:
    def __init__(self, db_path: str | Path, retention_per_symbol: int = 1000):
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
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    selected_timeframe TEXT NOT NULL,
                    current_price REAL,
                    analysis_source TEXT,
                    provider_status TEXT,
                    trust_status TEXT,
                    decision TEXT,
                    bias TEXT,
                    score REAL,
                    setup_status TEXT,
                    direction TEXT,
                    execution_allowed INTEGER NOT NULL DEFAULT 0,
                    entry_price REAL,
                    stop_loss REAL,
                    target_1 REAL,
                    fingerprint TEXT NOT NULL,
                    change_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_analysis_runs_symbol_created ON analysis_runs(symbol, id DESC)"
            )

    def record(self, analysis: Dict[str, Any], selected_timeframe: str = "15M") -> Dict[str, Any]:
        summary = self._summary(analysis, selected_timeframe)
        previous = self.latest(summary["symbol"])
        change = self._change(previous, summary)
        fingerprint = self._fingerprint(summary)
        payload = self._redact(self._payload(analysis))
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analysis_runs (
                    symbol, created_at, selected_timeframe, current_price, analysis_source,
                    provider_status, trust_status, decision, bias, score, setup_status,
                    direction, execution_allowed, entry_price, stop_loss, target_1,
                    fingerprint, change_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary["symbol"], summary["created_at"], summary["selected_timeframe"],
                    summary["current_price"], summary["analysis_source"], summary["provider_status"],
                    summary["trust_status"], summary["decision"], summary["bias"], summary["score"],
                    summary["setup_status"], summary["direction"], 1 if summary["execution_allowed"] else 0,
                    summary["entry_price"], summary["stop_loss"], summary["target_1"], fingerprint,
                    json.dumps(change, default=str), json.dumps(payload, default=str),
                ),
            )
            run_id = int(cursor.lastrowid)
            connection.execute(
                """
                DELETE FROM analysis_runs
                WHERE symbol = ? AND id NOT IN (
                    SELECT id FROM analysis_runs WHERE symbol = ? ORDER BY id DESC LIMIT ?
                )
                """,
                (summary["symbol"], summary["symbol"], self.retention_per_symbol),
            )
        return {"id": run_id, **summary, "fingerprint": fingerprint, "change": change}

    def latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        rows = self.list(symbol, 1)
        return rows[0] if rows else None

    def list(self, symbol: Optional[str] = None, limit: int = 20) -> list[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self.connect() as connection:
            if symbol:
                rows = connection.execute(
                    "SELECT * FROM analysis_runs WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                    (symbol.upper(), safe_limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM analysis_runs ORDER BY id DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
        return [self._public_row(row, include_payload=False) for row in rows]

    def get(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM analysis_runs WHERE id = ?", (int(run_id),)).fetchone()
        return self._public_row(row, include_payload=True) if row else None

    def stats(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        where = " WHERE symbol = ?" if symbol else ""
        params = (symbol.upper(),) if symbol else ()
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total,
                       SUM(execution_allowed) AS actionable,
                       SUM(CASE WHEN trust_status = 'TRUSTED' THEN 1 ELSE 0 END) AS trusted,
                       MAX(created_at) AS latest_at
                FROM analysis_runs{where}
                """,
                params,
            ).fetchone()
        total = int(row["total"] or 0)
        trusted = int(row["trusted"] or 0)
        return {
            "total": total,
            "actionable": int(row["actionable"] or 0),
            "trusted": trusted,
            "trusted_percent": round(trusted / total * 100, 1) if total else 0,
            "latest_at": row["latest_at"],
        }

    def _summary(self, analysis: Dict[str, Any], selected_timeframe: str) -> Dict[str, Any]:
        signal = analysis.get("signal") or {}
        plan = analysis.get("trade_plan") or {}
        trust = analysis.get("trust_gate") or {}
        alignment = analysis.get("provider_alignment") or {}
        targets = plan.get("take_profit_levels") or []
        score = signal.get("score")
        if score is None:
            score = (analysis.get("score_engine") or {}).get("score")
        return {
            "symbol": str(analysis.get("symbol") or analysis.get("market_symbol") or "UNKNOWN").upper(),
            "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "selected_timeframe": str(selected_timeframe or "15M").upper(),
            "current_price": self._number(analysis.get("current_price")),
            "analysis_source": analysis.get("analysis_data_source"),
            "provider_status": alignment.get("status"),
            "trust_status": trust.get("status"),
            "decision": analysis.get("final_decision"),
            "bias": analysis.get("bias") or (analysis.get("htf_bias") or {}).get("bias"),
            "score": self._number(score),
            "setup_status": plan.get("status") or signal.get("status"),
            "direction": plan.get("direction") or signal.get("direction") or "WAIT",
            "execution_allowed": bool(signal.get("execution_allowed") and trust.get("trusted")),
            "entry_price": self._number(plan.get("entry_price")),
            "stop_loss": self._number(plan.get("stop_loss")),
            "target_1": self._number(targets[0]) if targets else None,
        }

    def _change(self, previous: Optional[Dict[str, Any]], current: Dict[str, Any]) -> Dict[str, Any]:
        if not previous:
            return {
                "type": "INITIAL_SCAN",
                "significant": True,
                "decision_changed": False,
                "bias_changed": False,
                "setup_changed": False,
                "trust_changed": False,
                "score_delta": None,
                "price_delta": None,
            }
        decision_changed = previous.get("decision") != current.get("decision")
        bias_changed = previous.get("bias") != current.get("bias")
        setup_changed = previous.get("setup_status") != current.get("setup_status") or previous.get("direction") != current.get("direction")
        trust_changed = previous.get("trust_status") != current.get("trust_status")
        score_delta = self._delta(current.get("score"), previous.get("score"))
        price_delta = self._delta(current.get("current_price"), previous.get("current_price"))
        if trust_changed:
            change_type = "TRUST_CHANGE"
        elif setup_changed:
            change_type = "SETUP_CHANGE"
        elif bias_changed:
            change_type = "BIAS_CHANGE"
        elif decision_changed:
            change_type = "DECISION_CHANGE"
        elif score_delta is not None and abs(score_delta) >= 10:
            change_type = "SCORE_MOVE"
        else:
            change_type = "NO_CHANGE"
        return {
            "type": change_type,
            "significant": change_type != "NO_CHANGE",
            "decision_changed": decision_changed,
            "bias_changed": bias_changed,
            "setup_changed": setup_changed,
            "trust_changed": trust_changed,
            "score_delta": round(score_delta, 3) if score_delta is not None else None,
            "price_delta": round(price_delta, 3) if price_delta is not None else None,
        }

    def _payload(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "symbol": analysis.get("symbol") or analysis.get("market_symbol"),
            "current_price": analysis.get("current_price"),
            "final_decision": analysis.get("final_decision"),
            "bias": analysis.get("bias"),
            "analysis_data_source": analysis.get("analysis_data_source"),
            "provider_alignment": analysis.get("provider_alignment"),
            "trust_gate": analysis.get("trust_gate"),
            "signal": analysis.get("signal"),
            "trade_plan": analysis.get("trade_plan"),
            "session_framework": analysis.get("session_framework"),
            "news_intelligence": analysis.get("news_intelligence"),
            "analysis_explanation": analysis.get("analysis_explanation"),
            "score_engine": analysis.get("score_engine"),
        }

    def _public_row(self, row: sqlite3.Row, include_payload: bool) -> Dict[str, Any]:
        result = {
            "id": int(row["id"]),
            "symbol": row["symbol"],
            "created_at": row["created_at"],
            "selected_timeframe": row["selected_timeframe"],
            "current_price": row["current_price"],
            "analysis_source": row["analysis_source"],
            "provider_status": row["provider_status"],
            "trust_status": row["trust_status"],
            "decision": row["decision"],
            "bias": row["bias"],
            "score": row["score"],
            "setup_status": row["setup_status"],
            "direction": row["direction"],
            "execution_allowed": bool(row["execution_allowed"]),
            "entry_price": row["entry_price"],
            "stop_loss": row["stop_loss"],
            "target_1": row["target_1"],
            "fingerprint": row["fingerprint"],
            "change": json.loads(row["change_json"] or "{}"),
        }
        if include_payload:
            result["payload"] = json.loads(row["payload_json"] or "{}")
        return result

    def _fingerprint(self, summary: Dict[str, Any]) -> str:
        stable = {
            key: summary.get(key)
            for key in ["symbol", "analysis_source", "trust_status", "decision", "bias", "setup_status", "direction", "execution_allowed"]
        }
        return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS) else self._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if pd.notna(number) else None

    @staticmethod
    def _delta(current: Any, previous: Any) -> Optional[float]:
        if current is None or previous is None:
            return None
        return float(current) - float(previous)
