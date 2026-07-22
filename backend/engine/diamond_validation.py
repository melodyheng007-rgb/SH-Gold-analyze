from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .key_zone import DiamondZoneEngine


ENGINE_VERSION = "DIAMOND_V8.5_WALK_FORWARD_SMT_GUARD"
STRATEGY_NAME = "SH_DIAMOND_ZONE_V8_5_ADAPTIVE_SMT"
REPLAY_OUTCOME_MODEL = "TOUCH_INVALIDATION_1_5_ATR_V1"
MIN_HISTORY_BARS = 220
DEFAULT_HORIZON = {"5M": 48, "15M": 48, "1H": 32, "4H": 20, "1D": 10}


class DiamondValidationLab:
    """Closed-candle walk-forward evidence for the production Diamond engine."""

    def __init__(self, db_path: str | Path, engine: Optional[DiamondZoneEngine] = None):
        self.db_path = str(db_path)
        self.engine = engine or DiamondZoneEngine()
        self._lock = threading.RLock()
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
                CREATE TABLE IF NOT EXISTS diamond_validation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_key TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    source TEXT NOT NULL,
                    first_candle_time INTEGER NOT NULL,
                    last_candle_time INTEGER NOT NULL,
                    candle_count INTEGER NOT NULL,
                    horizon_bars INTEGER NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_diamond_validation_latest ON diamond_validation_runs(symbol, timeframe, id DESC)"
            )

    def latest(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        normalized_symbol = str(symbol or "XAUUSD").upper()
        normalized_timeframe = str(timeframe or "15M").upper()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, result_json, created_at
                FROM diamond_validation_runs
                WHERE symbol = ? AND timeframe = ? AND engine_version = ?
                ORDER BY id DESC LIMIT 1
                """,
                (normalized_symbol, normalized_timeframe, ENGINE_VERSION),
            ).fetchone()
        if not row:
            return {
                "status": "NOT_RUN",
                "symbol": normalized_symbol,
                "timeframe": normalized_timeframe,
                "strategy": STRATEGY_NAME,
                "engine_version": ENGINE_VERSION,
                "methodology": self.methodology(),
            }
        result = json.loads(row["result_json"])
        result["run_id"] = row["id"]
        result["cached"] = True
        return result

    def run(
        self,
        symbol: str,
        timeframe: str,
        candles: Iterable[Dict[str, Any]],
        source: str,
        horizon_bars: Optional[int] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        normalized_symbol = str(symbol or "XAUUSD").upper()
        normalized_timeframe = str(timeframe or "15M").upper()
        rows = self._candles(candles)
        horizon = max(8, min(int(horizon_bars or DEFAULT_HORIZON.get(normalized_timeframe, 48)), 240))
        if len(rows) < MIN_HISTORY_BARS + horizon + 1:
            return {
                "status": "INSUFFICIENT_DATA",
                "symbol": normalized_symbol,
                "timeframe": normalized_timeframe,
                "strategy": STRATEGY_NAME,
                "engine_version": ENGINE_VERSION,
                "source": source,
                "candle_count": len(rows),
                "required_candles": MIN_HISTORY_BARS + horizon + 1,
                "methodology": self.methodology(),
            }

        run_key = self._run_key(normalized_symbol, normalized_timeframe, source, rows, horizon)
        if not force:
            cached = self._by_key(run_key)
            if cached:
                cached["cached"] = True
                return cached

        with self._lock:
            if not force:
                cached = self._by_key(run_key)
                if cached:
                    cached["cached"] = True
                    return cached
            result = self._walk_forward(normalized_symbol, normalized_timeframe, rows, source, horizon)
            created_at = datetime.now(timezone.utc).isoformat()
            result["generated_at"] = created_at
            result["data_fingerprint"] = run_key[:16]
            result["cached"] = False
            with self.connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO diamond_validation_runs (
                        run_key, symbol, timeframe, strategy, engine_version, source,
                        first_candle_time, last_candle_time, candle_count, horizon_bars,
                        result_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_key) DO UPDATE SET
                        result_json = excluded.result_json,
                        created_at = excluded.created_at
                    """,
                    (
                        run_key, normalized_symbol, normalized_timeframe, STRATEGY_NAME,
                        ENGINE_VERSION, source, rows[0]["time"], rows[-1]["time"],
                        len(rows), horizon, json.dumps(result, separators=(",", ":"), sort_keys=True),
                        created_at,
                    ),
                )
                result["run_id"] = cursor.lastrowid or connection.execute(
                    "SELECT id FROM diamond_validation_runs WHERE run_key = ?", (run_key,)
                ).fetchone()["id"]
            return result

    def _walk_forward(
        self,
        symbol: str,
        timeframe: str,
        rows: list[Dict[str, Any]],
        source: str,
        horizon: int,
    ) -> Dict[str, Any]:
        qualified_origins: set[str] = set()
        context_origins: set[str] = set()
        seen_events: set[str] = set()
        seen_replay_zones: set[str] = set()
        trades: list[Dict[str, Any]] = []
        replay_zones: list[Dict[str, Any]] = []
        trace_states: Dict[str, Dict[str, Any]] = {}
        scan_count = 0
        last_mature_index = len(rows) - horizon - 1

        for end_index in range(MIN_HISTORY_BARS - 1, last_mature_index + 1):
            scan_count += 1
            history = rows[max(0, end_index - MIN_HISTORY_BARS + 1):end_index + 1]
            snapshot = self.engine.calculate(
                history,
                timeframe,
                source=source,
                symbol=symbol,
            )
            for trace in (snapshot.get("gate_funnel") or {}).get("zone_traces") or []:
                self._update_trace_state(trace_states, trace, end_index)
            for zone in snapshot.get("zones") or []:
                zone_id = str(zone.get("id") or "")
                if not zone_id:
                    continue
                context_origins.add(zone_id)
                if zone.get("entry_eligible_origin"):
                    qualified_origins.add(zone_id)
                if (
                    zone_id not in seen_replay_zones
                    and zone.get("strategy_confirmed_origin") is True
                    and zone.get("display_as_diamond") is True
                ):
                    seen_replay_zones.add(zone_id)
                    future = rows[end_index + 1:end_index + horizon + 1]
                    replay_zones.append(self._evaluate_replay_zone(
                        symbol,
                        timeframe,
                        zone,
                        int(rows[end_index]["time"]),
                        future,
                    ))

            current_time = int(rows[end_index]["time"])
            for event in snapshot.get("entry_events") or []:
                event_id = str(event.get("id") or "")
                event_time = self._timestamp(event.get("available_at") or event.get("time"))
                if not event_id or event_id in seen_events or event_time != current_time:
                    continue
                seen_events.add(event_id)
                future = rows[end_index + 1:end_index + horizon + 1]
                trades.append(self._evaluate_event(symbol, timeframe, event, future))

        summary = self._summary(trades)
        replay_summary = self._replay_summary(replay_zones)
        confidence = self._sample_confidence(summary["resolved"])
        failure_diagnostics = self._failure_diagnostics(trace_states, summary["confirmed_events"])
        return {
            "status": "READY" if trades else "NO_CONFIRMED_EVENTS",
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy": STRATEGY_NAME,
            "engine_version": ENGINE_VERSION,
            "source": source,
            "data_trust": "MATCHED_PROVIDER_CLOSED_CANDLES_ONLY",
            "data_range": {
                "from": self._iso(rows[0]["time"]),
                "to": self._iso(rows[-1]["time"]),
                "candles": len(rows),
                "matured_through": self._iso(rows[last_mature_index]["time"]),
            },
            "scan_count": scan_count,
            "context_origins": len(context_origins),
            "qualified_origins": len(qualified_origins),
            "summary": summary,
            "replay_summary": replay_summary,
            "replay_outcome_model": REPLAY_OUTCOME_MODEL,
            "sample_confidence": confidence,
            "failure_diagnostics": failure_diagnostics,
            "result_integrity": {
                "version": "DIAMOND_RESULT_INTEGRITY_V5_SIGNAL_TIERS",
                "production_results": summary["confirmed_events"],
                "qualified_watch": len(qualified_origins),
                "market_context": len(context_origins),
                "context_excluded_from_win_loss": True,
                "qualified_excluded_from_win_loss": True,
                "result_rule": "Only closed-candle confirmed entry events are evaluated as Buy/Sell results.",
            },
            "segments": self._segments(trades),
            "trades": trades[-120:],
            "replay_zones": replay_zones[-200:],
            "horizon_bars": horizon,
            "methodology": self.methodology(),
            "risk_note": "Historical evidence is not a guarantee of future performance.",
        }

    @staticmethod
    def _evaluate_replay_zone(
        symbol: str,
        timeframe: str,
        zone: Dict[str, Any],
        detected_time: int,
        future: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        side = str(zone.get("entry_side") or zone.get("direction") or "").upper()
        buy = side in {"BUY", "BULLISH"}
        side = "BUY" if buy else "SELL"
        line = float(zone.get("line") or 0)
        atr = max(float(zone.get("atr_14") or 0), 1e-9)
        low = float(zone.get("low") or line)
        high = float(zone.get("high") or line)
        invalidation = low - atr * 0.10 if buy else high + atr * 0.10
        reaction_atr = 1.5
        reaction_level = line + atr * reaction_atr if buy else line - atr * reaction_atr
        outcome = "WATCHING"
        resolved_time = None
        maximum_favorable_atr = 0.0
        maximum_adverse_atr = 0.0

        for candle in future:
            favorable = float(candle["high"]) - line if buy else line - float(candle["low"])
            adverse = line - float(candle["low"]) if buy else float(candle["high"]) - line
            maximum_favorable_atr = max(maximum_favorable_atr, favorable / atr)
            maximum_adverse_atr = max(maximum_adverse_atr, adverse / atr)
            respected = float(candle["high"]) >= reaction_level if buy else float(candle["low"]) <= reaction_level
            failed = float(candle["low"]) <= invalidation if buy else float(candle["high"]) >= invalidation
            if respected and failed:
                outcome = "AMBIGUOUS"
                resolved_time = int(candle["time"])
                break
            if failed:
                outcome = "FAILED"
                resolved_time = int(candle["time"])
                break
            if respected:
                outcome = "RESPECTED"
                resolved_time = int(candle["time"])
                break

        score = int(zone.get("diamond_score") or zone.get("diamond_confidence_score") or 0)
        return {
            "zone_key": f"replay:{symbol}:{timeframe}:{zone.get('id')}",
            "zone_id": zone.get("id"),
            "symbol": symbol,
            "timeframe": timeframe,
            "origin_time": int(zone.get("time") or detected_time),
            "detected_time": int(detected_time),
            "detected_at": DiamondValidationLab._iso(detected_time),
            "resolved_time": resolved_time,
            "resolved_at": DiamondValidationLab._iso(resolved_time) if resolved_time else None,
            "entry_side": side,
            "direction": "BULLISH" if buy else "BEARISH",
            "line": round(line, 5),
            "zone_low": round(low, 5),
            "zone_high": round(high, 5),
            "origin_model": zone.get("origin_model"),
            "diamond_score": score,
            "diamond_grade": zone.get("diamond_grade"),
            "signal_tier": "QUALIFIED",
            "classification": "QUALIFIED",
            "strategy_confirmed_origin": True,
            "display_as_diamond": True,
            "score_creates_diamond": False,
            "outcome": outcome,
            "verification_status": outcome,
            "reaction_atr": reaction_atr,
            "maximum_favorable_atr": round(maximum_favorable_atr, 3),
            "maximum_adverse_atr": round(maximum_adverse_atr, 3),
            "closed_candle_only": True,
            "engine_replay": True,
        }

    @staticmethod
    def _replay_summary(replay_zones: list[Dict[str, Any]]) -> Dict[str, Any]:
        respected = sum(1 for zone in replay_zones if zone.get("outcome") == "RESPECTED")
        failed = sum(1 for zone in replay_zones if zone.get("outcome") == "FAILED")
        ambiguous = sum(1 for zone in replay_zones if zone.get("outcome") == "AMBIGUOUS")
        watching = sum(1 for zone in replay_zones if zone.get("outcome") == "WATCHING")
        resolved = respected + failed
        return {
            "strategy_confirmed_setups": len(replay_zones),
            "respected": respected,
            "failed": failed,
            "ambiguous": ambiguous,
            "watching": watching,
            "resolved": resolved,
            "respect_rate": round(respected / resolved * 100, 1) if resolved else None,
            "buy_zones": sum(1 for zone in replay_zones if zone.get("entry_side") == "BUY"),
            "sell_zones": sum(1 for zone in replay_zones if zone.get("entry_side") == "SELL"),
        }

    @staticmethod
    def _evaluate_event(
        symbol: str,
        timeframe: str,
        event: Dict[str, Any],
        future: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        side = str(event.get("entry_side") or "").upper()
        entry = float(event["execution_entry"])
        atr = float(event["atr_14"])
        stop_reference = float(event["stop_reference"])
        stop = stop_reference - atr * 0.10 if side == "BUY" else stop_reference + atr * 0.10
        risk = abs(entry - stop)
        reward_r = 1.8 if symbol == "XAUUSD" else 1.6
        target = entry + risk * reward_r if side == "BUY" else entry - risk * reward_r
        outcome = "EXPIRED"
        outcome_r = 0.0
        resolved_time = None
        mfe_r = 0.0
        mae_r = 0.0

        for candle in future:
            stop_hit = candle["low"] <= stop if side == "BUY" else candle["high"] >= stop
            target_hit = candle["high"] >= target if side == "BUY" else candle["low"] <= target
            favorable = candle["high"] - entry if side == "BUY" else entry - candle["low"]
            adverse = entry - candle["low"] if side == "BUY" else candle["high"] - entry
            mfe_r = max(mfe_r, favorable / risk if risk else 0.0)
            mae_r = max(mae_r, adverse / risk if risk else 0.0)
            if stop_hit and target_hit:
                outcome = "AMBIGUOUS"
                resolved_time = candle["time"]
                break
            if stop_hit:
                outcome = "LOST"
                outcome_r = -1.0
                resolved_time = candle["time"]
                break
            if target_hit:
                outcome = "WON"
                outcome_r = reward_r
                resolved_time = candle["time"]
                break

        if outcome == "EXPIRED" and future and risk:
            final_close = future[-1]["close"]
            mark_r = (final_close - entry) / risk if side == "BUY" else (entry - final_close) / risk
            outcome_r = round(max(-1.0, min(reward_r, mark_r)), 3)

        event_time = int(event.get("time") or event.get("available_at"))
        return {
            "event_id": event.get("id"),
            "zone_id": event.get("zone_id"),
            "time": event_time,
            "confirmed_at": DiamondValidationLab._iso(event_time),
            "resolved_at": DiamondValidationLab._iso(resolved_time) if resolved_time else None,
            "symbol": symbol,
            "timeframe": timeframe,
            "session": DiamondValidationLab._session(event_time),
            "side": side,
            "entry": round(entry, 5),
            "stop": round(stop, 5),
            "target": round(target, 5),
            "risk": round(risk, 5),
            "planned_reward_r": reward_r,
            "quality_score": event.get("quality_score"),
            "precision_grade": event.get("precision_grade"),
            "origin_model": event.get("origin_model"),
            "entry_pathway": event.get("entry_pathway"),
            "confirmation_model": event.get("confirmation_model"),
            "outcome": outcome,
            "outcome_r": round(outcome_r, 3),
            "mfe_r": round(mfe_r, 3),
            "mae_r": round(mae_r, 3),
        }

    @staticmethod
    def _summary(trades: list[Dict[str, Any]]) -> Dict[str, Any]:
        wins = [trade for trade in trades if trade["outcome"] == "WON"]
        losses = [trade for trade in trades if trade["outcome"] == "LOST"]
        ambiguous = sum(1 for trade in trades if trade["outcome"] == "AMBIGUOUS")
        expired = sum(1 for trade in trades if trade["outcome"] == "EXPIRED")
        resolved = wins + losses
        pnl = [float(trade["outcome_r"]) for trade in resolved]
        gross_gain = sum(value for value in pnl if value > 0)
        gross_loss = abs(sum(value for value in pnl if value < 0))
        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for value in pnl:
            equity += value
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
        resolved_count = len(resolved)
        return {
            "confirmed_events": len(trades),
            "resolved": resolved_count,
            "wins": len(wins),
            "losses": len(losses),
            "ambiguous": ambiguous,
            "expired": expired,
            "win_rate": round(len(wins) / resolved_count * 100, 1) if resolved_count else None,
            "expectancy_r": round(sum(pnl) / resolved_count, 3) if resolved_count else None,
            "net_r": round(sum(pnl), 3),
            "profit_factor": round(gross_gain / gross_loss, 3) if gross_loss else ("INF" if gross_gain else None),
            "max_drawdown_r": round(max_drawdown, 3),
            "average_mfe_r": round(sum(float(trade["mfe_r"]) for trade in trades) / len(trades), 3) if trades else None,
            "average_mae_r": round(sum(float(trade["mae_r"]) for trade in trades) / len(trades), 3) if trades else None,
        }

    @classmethod
    def _segments(cls, trades: list[Dict[str, Any]]) -> Dict[str, list[Dict[str, Any]]]:
        return {
            "direction": cls._group(trades, "side"),
            "session": cls._group(trades, "session"),
            "entry_pathway": cls._group(trades, "entry_pathway"),
        }

    @classmethod
    def _update_trace_state(
        cls,
        states: Dict[str, Dict[str, Any]],
        trace: Dict[str, Any],
        scan_index: int,
    ) -> None:
        zone_id = str(trace.get("zone_id") or "")
        if not zone_id or trace.get("blocker") == "ORIGIN_NOT_ENTRY_ELIGIBLE":
            return
        candidate = dict(trace)
        candidate["scan_index"] = int(scan_index)
        candidate["stage_rank"] = cls._trace_stage_rank(candidate)
        current = states.get(zone_id)
        candidate_terminal = bool(candidate.get("confirmed")) or str(candidate.get("blocker") or "").startswith("ZONE_INVALIDATED")
        current_terminal = bool(current and (current.get("confirmed") or str(current.get("blocker") or "").startswith("ZONE_INVALIDATED")))
        if current_terminal:
            return
        if candidate_terminal or current is None or (
            candidate["stage_rank"], candidate["scan_index"]
        ) >= (
            int(current.get("stage_rank") or 0), int(current.get("scan_index") or 0)
        ):
            states[zone_id] = candidate

    @classmethod
    def _failure_diagnostics(
        cls,
        states: Dict[str, Dict[str, Any]],
        confirmed_events: int,
    ) -> Dict[str, Any]:
        blockers = Counter()
        stages = Counter()
        for trace in states.values():
            stage = cls._trace_stage(trace)
            stages[stage] += 1
            if not trace.get("confirmed"):
                blockers[str(trace.get("blocker") or "WAITING_SEQUENCE")] += 1
        return {
            "qualified_origins_traced": len(states),
            "confirmed_entries": int(confirmed_events),
            "conversion_percent": round(int(confirmed_events) / len(states) * 100, 1) if states else 0.0,
            "final_blockers": [
                {
                    "id": identifier,
                    "label": DiamondZoneEngine._blocker_label(identifier),
                    "count": int(count),
                }
                for identifier, count in blockers.most_common()
            ],
            "deepest_stages": [
                {"stage": stage, "count": int(count)}
                for stage, count in stages.most_common()
            ],
            "interpretation": (
                "No confirmed executable entry exists yet; context and qualified Buy/Sell Diamond Zones remain visible."
                if not confirmed_events
                else "Only confirmed entries contribute to resolved performance metrics."
            ),
        }

    @staticmethod
    def _trace_stage_rank(trace: Dict[str, Any]) -> int:
        return sum(bool(trace.get(key)) for key in ("controlled_retest", "rejection", "follow_through", "risk_quality"))

    @classmethod
    def _trace_stage(cls, trace: Dict[str, Any]) -> str:
        if trace.get("confirmed"):
            return "CONFIRMED_ENTRY"
        blocker = str(trace.get("blocker") or "")
        if blocker.startswith("ZONE_INVALIDATED"):
            return "INVALIDATED"
        if trace.get("risk_quality"):
            return "RISK_QUALITY"
        if trace.get("follow_through"):
            return "FOLLOW_THROUGH"
        if trace.get("rejection"):
            return "REJECTION"
        if trace.get("controlled_retest"):
            return "CONTROLLED_RETEST"
        return "WAITING_RETEST"

    @classmethod
    def _group(cls, trades: list[Dict[str, Any]], key: str) -> list[Dict[str, Any]]:
        values: Dict[str, list[Dict[str, Any]]] = {}
        for trade in trades:
            values.setdefault(str(trade.get(key) or "UNKNOWN"), []).append(trade)
        return [
            {key: value, **cls._summary(group)}
            for value, group in sorted(values.items())
        ]

    def _by_key(self, run_key: str) -> Optional[Dict[str, Any]]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, result_json FROM diamond_validation_runs WHERE run_key = ?",
                (run_key,),
            ).fetchone()
        if not row:
            return None
        result = json.loads(row["result_json"])
        result["run_id"] = row["id"]
        return result

    @staticmethod
    def _sample_confidence(resolved: int) -> Dict[str, Any]:
        if resolved >= 100:
            status = "EVIDENCE_READY"
        elif resolved >= 50:
            status = "DEVELOPING_SAMPLE"
        elif resolved >= 20:
            status = "EARLY_SAMPLE"
        else:
            status = "INSUFFICIENT_SAMPLE"
        return {
            "status": status,
            "resolved": resolved,
            "minimum_evidence_sample": 100,
            "progress_percent": min(100, resolved),
        }

    @staticmethod
    def methodology() -> Dict[str, Any]:
        return {
            "mode": "EXPANDING_CLOSED_CANDLE_WALK_FORWARD",
            "signal_timing": "An event is accepted only when its confirmation_time equals the current historical candle.",
            "zone_replay": "A historical Diamond is plotted only after the current engine confirms its strategy setup on completed candles; score grades the setup but cannot create it.",
            "zone_outcome": "RESPECTED requires a 1.5-ATR favorable reaction before price touches the structural invalidation boundary; a same-candle touch of both sides is AMBIGUOUS.",
            "outcome_timing": "Only later completed candles can resolve stop or fixed-R target.",
            "same_candle_policy": "Stop and target touched on the same candle is AMBIGUOUS and excluded from win rate.",
            "look_ahead": False,
            "provider_rule": "Matched-provider candles only.",
            "result_rule": "Context and qualified watch markers are excluded; only confirmed entries are scored.",
        }

    def _run_key(
        self,
        symbol: str,
        timeframe: str,
        source: str,
        rows: list[Dict[str, Any]],
        horizon: int,
    ) -> str:
        payload = {
            "engine": ENGINE_VERSION,
            "symbol": symbol,
            "timeframe": timeframe,
            "source": source,
            "first": rows[0]["time"],
            "last": rows[-1]["time"],
            "count": len(rows),
            "last_close": rows[-1]["close"],
            "horizon": horizon,
            "replay_outcome_model": REPLAY_OUTCOME_MODEL,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _candles(candles: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
        normalized: Dict[int, Dict[str, Any]] = {}
        for item in candles or []:
            if item.get("is_complete") is False or item.get("is_partial") is True:
                continue
            timestamp = DiamondValidationLab._timestamp(item.get("time") or item.get("timestamp"))
            try:
                row = {
                    "time": timestamp,
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                }
            except (KeyError, TypeError, ValueError):
                continue
            if timestamp is None or min(row["open"], row["high"], row["low"], row["close"]) <= 0:
                continue
            if row["high"] < max(row["open"], row["low"], row["close"]) or row["low"] > min(row["open"], row["high"], row["close"]):
                continue
            normalized[timestamp] = row
        return [normalized[key] for key in sorted(normalized)]

    @staticmethod
    def _timestamp(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _iso(timestamp: Optional[int]) -> Optional[str]:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat() if timestamp is not None else None

    @staticmethod
    def _session(timestamp: int) -> str:
        hour = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).hour
        if 0 <= hour < 7:
            return "ASIA"
        if 7 <= hour < 13:
            return "LONDON"
        if 13 <= hour < 21:
            return "NEW_YORK"
        return "ROLLOVER"
