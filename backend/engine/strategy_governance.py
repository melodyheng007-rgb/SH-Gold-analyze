from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


CHAMPION_VERSION = "DIAMOND_V8_5_SETUP_SMT_GUARDED"
CHALLENGER_VERSION = "DIAMOND_V7.1_SHADOW"
MIN_PROMOTION_SAMPLE = 100


class StrategyGovernance:
    """Persist shadow observations and forbid unevidenced strategy promotion."""

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
                CREATE TABLE IF NOT EXISTS strategy_shadow_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    candle_time INTEGER NOT NULL,
                    challenger_version TEXT NOT NULL,
                    source TEXT,
                    feed_matched INTEGER NOT NULL DEFAULT 0,
                    champion_gate TEXT,
                    challenger_gate TEXT,
                    champion_entries INTEGER NOT NULL DEFAULT 0,
                    challenger_entries INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, timeframe, candle_time, challenger_version)
                );

                CREATE TABLE IF NOT EXISTS strategy_shadow_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    event_time INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    entry REAL NOT NULL,
                    stop REAL NOT NULL,
                    target REAL NOT NULL,
                    planned_reward_r REAL NOT NULL,
                    source TEXT,
                    outcome TEXT NOT NULL DEFAULT 'MONITORING',
                    outcome_r REAL,
                    resolved_time INTEGER,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(event_id, strategy_version)
                );

                CREATE INDEX IF NOT EXISTS idx_shadow_observations_market
                    ON strategy_shadow_observations(symbol, timeframe, id DESC);
                CREATE INDEX IF NOT EXISTS idx_shadow_trades_market
                    ON strategy_shadow_trades(symbol, timeframe, outcome, event_time);
                """
            )

    def record(
        self,
        symbol: str,
        timeframe: str,
        candles: Iterable[Dict[str, Any]],
        source: Optional[str],
        feed_matched: bool,
        champion: Dict[str, Any],
        challenger: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_symbol = str(symbol or "XAUUSD").upper()
        normalized_timeframe = str(timeframe or "15M").upper()
        rows = self._candles(candles)
        if not rows:
            return self.snapshot(normalized_symbol, normalized_timeframe)
        latest_time = int(rows[-1]["time"])
        champion_funnel = champion.get("gate_funnel") or {}
        challenger_funnel = challenger.get("gate_funnel") or {}
        payload = {
            "champion": self._strategy_snapshot(champion, CHAMPION_VERSION),
            "challenger": self._strategy_snapshot(challenger, CHALLENGER_VERSION),
        }
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, closing(self.connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO strategy_shadow_observations (
                    symbol, timeframe, candle_time, challenger_version, source, feed_matched,
                    champion_gate, challenger_gate, champion_entries, challenger_entries,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe, candle_time, challenger_version) DO UPDATE SET
                    source = excluded.source,
                    feed_matched = excluded.feed_matched,
                    champion_gate = excluded.champion_gate,
                    challenger_gate = excluded.challenger_gate,
                    champion_entries = excluded.champion_entries,
                    challenger_entries = excluded.challenger_entries,
                    payload_json = excluded.payload_json
                """,
                (
                    normalized_symbol,
                    normalized_timeframe,
                    latest_time,
                    CHALLENGER_VERSION,
                    source,
                    int(bool(feed_matched)),
                    champion_funnel.get("current_gate"),
                    challenger_funnel.get("current_gate"),
                    len(champion.get("entry_events") or []),
                    len(challenger.get("entry_events") or []),
                    json.dumps(payload, sort_keys=True),
                    now,
                ),
            )
            self._resolve_monitoring(connection, normalized_symbol, normalized_timeframe, rows, now)
            if feed_matched:
                event = challenger.get("latest_entry_event") or {}
                event_time = self._timestamp(event.get("available_at") or event.get("time"))
                if event_time == latest_time:
                    self._insert_shadow_trade(
                        connection,
                        normalized_symbol,
                        normalized_timeframe,
                        source,
                        event,
                        now,
                    )
        return self.snapshot(normalized_symbol, normalized_timeframe)

    def snapshot(
        self,
        symbol: str,
        timeframe: str,
        champion_validation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_symbol = str(symbol or "XAUUSD").upper()
        normalized_timeframe = str(timeframe or "15M").upper()
        with closing(self.connect()) as connection:
            observation = connection.execute(
                """
                SELECT COUNT(*) AS observations, MAX(candle_time) AS latest_candle_time,
                       SUM(feed_matched) AS matched_observations,
                       SUM(champion_entries) AS champion_entries,
                       SUM(challenger_entries) AS challenger_entries
                FROM strategy_shadow_observations
                WHERE symbol = ? AND timeframe = ? AND challenger_version = ?
                """,
                (normalized_symbol, normalized_timeframe, CHALLENGER_VERSION),
            ).fetchone()
            latest = connection.execute(
                """
                SELECT payload_json, source, feed_matched, created_at
                FROM strategy_shadow_observations
                WHERE symbol = ? AND timeframe = ? AND challenger_version = ?
                ORDER BY id DESC LIMIT 1
                """,
                (normalized_symbol, normalized_timeframe, CHALLENGER_VERSION),
            ).fetchone()
            trades = connection.execute(
                """
                SELECT * FROM strategy_shadow_trades
                WHERE symbol = ? AND timeframe = ? AND strategy_version = ?
                ORDER BY event_time ASC
                """,
                (normalized_symbol, normalized_timeframe, CHALLENGER_VERSION),
            ).fetchall()
        shadow_summary = self._summary([dict(row) for row in trades])
        promotion = self._promotion_gate(shadow_summary, champion_validation or {})
        latest_payload = json.loads(latest["payload_json"]) if latest else {}
        return {
            "status": "READY" if observation and observation["observations"] else "WAITING_FIRST_OBSERVATION",
            "symbol": normalized_symbol,
            "timeframe": normalized_timeframe,
            "champion": {
                "version": CHAMPION_VERSION,
                "role": "LIVE_CHAMPION",
                "automatic_promotion": False,
                "validation": (champion_validation or {}).get("summary") or {},
                "current": latest_payload.get("champion") or {},
            },
            "challenger": {
                "version": CHALLENGER_VERSION,
                "role": "SHADOW_ONLY",
                "observations": int((observation["observations"] if observation else 0) or 0),
                "matched_observations": int((observation["matched_observations"] if observation else 0) or 0),
                "entry_observations": int((observation["challenger_entries"] if observation else 0) or 0),
                "summary": shadow_summary,
                "current": latest_payload.get("challenger") or {},
            },
            "promotion_gate": promotion,
            "latest_candle_time": observation["latest_candle_time"] if observation else None,
            "source": latest["source"] if latest else None,
            "feed_matched": bool(latest["feed_matched"]) if latest else False,
            "updated_at": latest["created_at"] if latest else None,
            "policy": {
                "minimum_resolved_sample": MIN_PROMOTION_SAMPLE,
                "minimum_expectancy_r": 0.10,
                "minimum_profit_factor": 1.20,
                "maximum_drawdown_r": 12.0,
                "manual_review_required": True,
                "challenger_can_place_trades": False,
            },
        }

    @staticmethod
    def _strategy_snapshot(result: Dict[str, Any], version: str) -> Dict[str, Any]:
        funnel = result.get("gate_funnel") or {}
        frequency = result.get("signal_frequency") or {}
        return {
            "version": version,
            "strategy": result.get("strategy"),
            "profile": result.get("profile"),
            "status": result.get("status"),
            "current_gate": funnel.get("current_gate"),
            "next_gate": funnel.get("next_gate"),
            "context_zones": frequency.get("context_zones", 0),
            "qualified_origins": frequency.get("qualified_origins", 0),
            "confirmed_entries": frequency.get("confirmed_entries", 0),
            "top_blockers": (funnel.get("top_blockers") or [])[:3],
        }

    @staticmethod
    def _insert_shadow_trade(
        connection: sqlite3.Connection,
        symbol: str,
        timeframe: str,
        source: Optional[str],
        event: Dict[str, Any],
        now: str,
    ) -> None:
        side = str(event.get("entry_side") or "").upper()
        entry = StrategyGovernance._number(event.get("execution_entry"))
        atr = StrategyGovernance._number(event.get("atr_14"))
        stop_reference = StrategyGovernance._number(event.get("stop_reference"))
        event_time = StrategyGovernance._timestamp(event.get("available_at") or event.get("time"))
        event_id = str(event.get("id") or "")
        if side not in {"BUY", "SELL"} or None in {entry, atr, stop_reference, event_time} or not event_id or atr <= 0:
            return
        stop = stop_reference - atr * 0.10 if side == "BUY" else stop_reference + atr * 0.10
        risk = abs(entry - stop)
        if risk <= 0:
            return
        reward_r = 1.8 if symbol == "XAUUSD" else 1.6
        target = entry + risk * reward_r if side == "BUY" else entry - risk * reward_r
        connection.execute(
            """
            INSERT OR IGNORE INTO strategy_shadow_trades (
                event_id, strategy_version, symbol, timeframe, event_time, side,
                entry, stop, target, planned_reward_r, source, outcome, outcome_r,
                payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'MONITORING', NULL, ?, ?, ?)
            """,
            (
                event_id,
                CHALLENGER_VERSION,
                symbol,
                timeframe,
                event_time,
                side,
                entry,
                stop,
                target,
                reward_r,
                source,
                json.dumps(event, sort_keys=True),
                now,
                now,
            ),
        )

    @staticmethod
    def _resolve_monitoring(
        connection: sqlite3.Connection,
        symbol: str,
        timeframe: str,
        candles: list[Dict[str, Any]],
        now: str,
    ) -> None:
        trades = connection.execute(
            """
            SELECT * FROM strategy_shadow_trades
            WHERE symbol = ? AND timeframe = ? AND strategy_version = ? AND outcome = 'MONITORING'
            """,
            (symbol, timeframe, CHALLENGER_VERSION),
        ).fetchall()
        for trade in trades:
            later = [candle for candle in candles if int(candle["time"]) > int(trade["event_time"])]
            outcome = None
            outcome_r = None
            resolved_time = None
            for candle in later:
                stop_hit = candle["low"] <= trade["stop"] if trade["side"] == "BUY" else candle["high"] >= trade["stop"]
                target_hit = candle["high"] >= trade["target"] if trade["side"] == "BUY" else candle["low"] <= trade["target"]
                if stop_hit and target_hit:
                    outcome, outcome_r = "AMBIGUOUS", None
                elif stop_hit:
                    outcome, outcome_r = "LOST", -1.0
                elif target_hit:
                    outcome, outcome_r = "WON", float(trade["planned_reward_r"])
                if outcome:
                    resolved_time = int(candle["time"])
                    break
            if outcome:
                connection.execute(
                    """
                    UPDATE strategy_shadow_trades
                    SET outcome = ?, outcome_r = ?, resolved_time = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (outcome, outcome_r, resolved_time, now, trade["id"]),
                )

    @staticmethod
    def _summary(trades: list[Dict[str, Any]]) -> Dict[str, Any]:
        resolved = [trade for trade in trades if trade.get("outcome") in {"WON", "LOST"}]
        wins = [trade for trade in resolved if trade.get("outcome") == "WON"]
        losses = [trade for trade in resolved if trade.get("outcome") == "LOST"]
        pnl = [float(trade.get("outcome_r") or 0) for trade in resolved]
        gross_gain = sum(value for value in pnl if value > 0)
        gross_loss = abs(sum(value for value in pnl if value < 0))
        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for value in pnl:
            equity += value
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
        return {
            "events": len(trades),
            "monitoring": sum(1 for trade in trades if trade.get("outcome") == "MONITORING"),
            "resolved": len(resolved),
            "wins": len(wins),
            "losses": len(losses),
            "ambiguous": sum(1 for trade in trades if trade.get("outcome") == "AMBIGUOUS"),
            "win_rate": round(len(wins) / len(resolved) * 100, 1) if resolved else None,
            "expectancy_r": round(sum(pnl) / len(resolved), 3) if resolved else None,
            "profit_factor": round(gross_gain / gross_loss, 3) if gross_loss else ("INF" if gross_gain else None),
            "net_r": round(sum(pnl), 3),
            "max_drawdown_r": round(max_drawdown, 3),
        }

    @staticmethod
    def _promotion_gate(summary: Dict[str, Any], champion_validation: Dict[str, Any]) -> Dict[str, Any]:
        resolved = int(summary.get("resolved") or 0)
        expectancy = summary.get("expectancy_r")
        profit_factor = summary.get("profit_factor")
        drawdown = float(summary.get("max_drawdown_r") or 0)
        blockers = []
        if resolved < MIN_PROMOTION_SAMPLE:
            blockers.append(f"Need {MIN_PROMOTION_SAMPLE - resolved} more resolved shadow events.")
        if expectancy is None or float(expectancy) < 0.10:
            blockers.append("Shadow expectancy must be at least 0.10R.")
        if profit_factor == "INF":
            numeric_profit_factor = float("inf")
        else:
            numeric_profit_factor = float(profit_factor) if profit_factor is not None else 0.0
        if numeric_profit_factor < 1.20:
            blockers.append("Shadow profit factor must be at least 1.20.")
        if drawdown > 12.0:
            blockers.append("Shadow maximum drawdown must not exceed 12R.")
        champion_resolved = int(((champion_validation.get("summary") or {}).get("resolved")) or 0)
        if champion_resolved < MIN_PROMOTION_SAMPLE:
            blockers.append("Champion comparison sample is not evidence-ready.")
        return {
            "status": "ELIGIBLE_FOR_MANUAL_REVIEW" if not blockers else "BLOCKED",
            "blockers": blockers,
            "automatic_promotion": False,
            "manual_review_required": True,
            "progress_percent": min(100, resolved),
        }

    @staticmethod
    def _candles(candles: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
        normalized: Dict[int, Dict[str, Any]] = {}
        for candle in candles or []:
            if candle.get("is_complete") is False or candle.get("is_partial") is True:
                continue
            timestamp = StrategyGovernance._timestamp(candle.get("time") or candle.get("timestamp"))
            values = [StrategyGovernance._number(candle.get(key)) for key in ("open", "high", "low", "close")]
            if timestamp is None or any(value is None for value in values):
                continue
            open_value, high, low, close = values
            if min(open_value, high, low, close) <= 0 or high < max(open_value, close, low) or low > min(open_value, close, high):
                continue
            normalized[timestamp] = {"time": timestamp, "open": open_value, "high": high, "low": low, "close": close}
        return [normalized[key] for key in sorted(normalized)]

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _timestamp(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
