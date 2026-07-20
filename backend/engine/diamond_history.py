from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


CLASSIFICATION_RANK = {"CONTEXT": 0, "QUALIFIED": 1, "CONFIRMED": 2, "AUTO_ENTRY": 3}
ACTIVE_VERIFICATIONS = {"MONITORING", "OPEN"}
TIMEFRAME_SECONDS = {"5M": 300, "15M": 900, "1H": 3600, "4H": 14400, "1D": 86400}
EXPIRY_BARS = {"5M": 36, "15M": 24, "1H": 16, "4H": 10, "1D": 5}


class DiamondHistory:
    """Persistent, closed-candle audit trail for Diamond zones and entry events."""

    def __init__(self, db_path: str | Path, retention_per_symbol: Optional[int] = None):
        self.db_path = str(db_path)
        self.retention_per_symbol = max(100, int(retention_per_symbol)) if retention_per_symbol is not None else None
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
                CREATE TABLE IF NOT EXISTS diamond_zone_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zone_key TEXT NOT NULL UNIQUE,
                    zone_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    origin_time INTEGER NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source TEXT,
                    strategy TEXT,
                    profile TEXT,
                    engine_version TEXT,
                    configuration_fingerprint TEXT,
                    feed_matched INTEGER NOT NULL DEFAULT 0,
                    trust_status TEXT,
                    direction TEXT NOT NULL,
                    entry_side TEXT NOT NULL,
                    line REAL NOT NULL,
                    zone_low REAL NOT NULL,
                    zone_high REAL NOT NULL,
                    origin_model TEXT,
                    origin_quality REAL,
                    quality_grade TEXT,
                    entry_eligible INTEGER NOT NULL DEFAULT 0,
                    classification TEXT NOT NULL,
                    lifecycle TEXT,
                    execution_quality TEXT,
                    rejection_status TEXT,
                    zone_strength REAL,
                    diamond_score REAL,
                    diamond_grade TEXT,
                    grade_model TEXT,
                    peak_diamond_score REAL,
                    peak_diamond_grade TEXT,
                    ever_visible INTEGER NOT NULL DEFAULT 0,
                    event_id TEXT,
                    event_time INTEGER,
                    entry_price REAL,
                    stop_price REAL,
                    target_price REAL,
                    event_quality REAL,
                    precision_grade TEXT,
                    tracked_setup_id INTEGER,
                    verification_status TEXT NOT NULL,
                    verified_at TEXT,
                    outcome_r REAL,
                    last_candle_at INTEGER,
                    note TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_diamond_history_symbol_id ON diamond_zone_history(symbol, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_diamond_history_active ON diamond_zone_history(symbol, verification_status)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS diamond_evidence_ledger (
                    zone_key TEXT PRIMARY KEY,
                    captured_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    trading_style TEXT,
                    market_session TEXT,
                    regime TEXT,
                    regime_gate TEXT,
                    decision_quality_score REAL,
                    decision_quality_status TEXT,
                    evidence_json TEXT NOT NULL,
                    lifecycle_json TEXT NOT NULL,
                    forward_returns_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_diamond_evidence_profile ON diamond_evidence_ledger(trading_style, market_session, regime)"
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(diamond_zone_history)").fetchall()}
            additions = {
                "strategy": "TEXT",
                "profile": "TEXT",
                "engine_version": "TEXT",
                "configuration_fingerprint": "TEXT",
                "diamond_score": "REAL",
                "diamond_grade": "TEXT",
                "grade_model": "TEXT",
                "peak_diamond_score": "REAL",
                "peak_diamond_grade": "TEXT",
                "ever_visible": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE diamond_zone_history ADD COLUMN {name} {definition}")
            connection.execute(
                """
                UPDATE diamond_zone_history
                SET diamond_score = COALESCE(diamond_score, event_quality, zone_strength, origin_quality, 0),
                    diamond_grade = COALESCE(
                        diamond_grade,
                        precision_grade,
                        CASE
                            WHEN COALESCE(event_quality, zone_strength, origin_quality, 0) >= 90 THEN 'A+'
                            WHEN COALESCE(event_quality, zone_strength, origin_quality, 0) >= 80 THEN 'A'
                            WHEN COALESCE(event_quality, zone_strength, origin_quality, 0) >= 70 THEN 'B'
                            WHEN COALESCE(event_quality, zone_strength, origin_quality, 0) >= 60 THEN 'C'
                            WHEN symbol = 'XAUUSD' AND COALESCE(event_quality, zone_strength, origin_quality, 0) >= 45 THEN 'D'
                            WHEN COALESCE(event_quality, zone_strength, origin_quality, 0) >= 50 THEN 'D'
                            ELSE 'UNRATED'
                        END
                    ),
                    grade_model = COALESCE(grade_model, 'DIAMOND_GRADE_V2_BACKFILLED')
                WHERE diamond_score IS NULL OR diamond_grade IS NULL OR grade_model IS NULL
                """
            )
            self._backfill_visibility_metadata(connection)
            connection.execute(
                """
                UPDATE diamond_zone_history
                SET diamond_score = CASE
                        WHEN verification_status IN ('INVALIDATED_NO_ENTRY', 'CANCELLED')
                          AND classification NOT IN ('CONFIRMED', 'AUTO_ENTRY')
                        THEN MIN(COALESCE(diamond_score, 49), 49)
                        ELSE diamond_score
                    END,
                    diamond_grade = 'UNRATED',
                    grade_model = 'DIAMOND_GRADE_V2_REJECTED'
                WHERE diamond_grade = 'F'
                   OR diamond_score < CASE WHEN symbol = 'XAUUSD' THEN 45 ELSE 50 END
                   OR (
                        verification_status IN ('INVALIDATED_NO_ENTRY', 'CANCELLED')
                        AND classification NOT IN ('CONFIRMED', 'AUTO_ENTRY')
                   )
                """
            )

    def _backfill_visibility_metadata(self, connection: sqlite3.Connection) -> None:
        """Preserve the strongest score a saved zone had before later lifecycle updates."""
        rows = connection.execute(
            """
            SELECT h.zone_key, h.symbol, h.classification, h.diamond_score, h.diamond_grade,
                   h.peak_diamond_score, h.peak_diamond_grade, h.ever_visible,
                   e.evidence_json
            FROM diamond_zone_history h
            LEFT JOIN diamond_evidence_ledger e ON e.zone_key = h.zone_key
            """
        ).fetchall()
        for row in rows:
            evidence = self._json_object(row["evidence_json"])
            captured = evidence.get("diamond") or {}
            score_candidates = [
                self._number(row["peak_diamond_score"]),
                self._number(row["diamond_score"]),
                self._number(captured.get("diamond_score")),
            ]
            scores = [score for score in score_candidates if score is not None]
            peak_score = max(scores) if scores else 0.0
            visibility_floor = self._visibility_floor(row["symbol"])
            peak_grade = self._grade(peak_score, visibility_floor)
            ever_visible = bool(
                row["ever_visible"]
                or peak_score >= visibility_floor
                or CLASSIFICATION_RANK.get(str(row["classification"] or "CONTEXT").upper(), 0) >= CLASSIFICATION_RANK["QUALIFIED"]
            )
            connection.execute(
                """
                UPDATE diamond_zone_history
                SET peak_diamond_score = ?, peak_diamond_grade = ?, ever_visible = ?
                WHERE zone_key = ?
                """,
                (peak_score, peak_grade or "UNRATED", 1 if ever_visible else 0, row["zone_key"]),
            )

    def record(
        self,
        analysis: Dict[str, Any],
        timeframe: str,
        tracked_setup: Optional[Dict[str, Any]] = None,
    ) -> int:
        zones_result = analysis.get("key_zones") or {}
        zones = zones_result.get("zones") or []
        if zones_result.get("status") != "READY" or not zones:
            return 0

        symbol = str(analysis.get("symbol") or analysis.get("market_symbol") or zones_result.get("symbol") or "UNKNOWN").upper()
        tf = str(timeframe or zones_result.get("timeframe") or "15M").upper()
        source = zones_result.get("source") or analysis.get("analysis_data_source")
        strategy = zones_result.get("strategy") or "SH_DIAMOND_ZONE_V6_PRECISION"
        profile = zones_result.get("profile") or zones_result.get("profile_label")
        engine_version = zones_result.get("engine_version") or analysis.get("diamond_engine_version") or "DIAMOND_V6.1"
        configuration_fingerprint = self._fingerprint({
            "strategy": strategy,
            "profile": profile,
            "formulas": zones_result.get("formulas") or {},
        })
        trust_status = (analysis.get("trust_gate") or {}).get("status")
        feed_matched = bool(zones_result.get("feed_matched"))
        events = {event.get("zone_id"): event for event in zones_result.get("entry_events") or []}
        now = datetime.now(timezone.utc).isoformat()
        recorded = 0

        with self.connect() as connection:
            for zone in zones:
                zone_id = str(zone.get("id") or "")
                origin_time = self._integer(zone.get("time"))
                line = self._number(zone.get("line"))
                low = self._number(zone.get("low"))
                high = self._number(zone.get("high"))
                if not zone_id or origin_time is None or None in {line, low, high}:
                    continue

                event = events.get(zone_id) or {}
                event_id = str(event.get("id") or "") or None
                diamond_score = self._number(
                    event.get("diamond_score")
                    or event.get("quality_score")
                    or zone.get("diamond_score")
                    or zone.get("diamond_confidence_score")
                    or zone.get("zone_strength_score")
                    or zone.get("origin_quality_score")
                )
                diamond_grade = str(
                    event.get("diamond_grade")
                    or event.get("precision_grade")
                    or zone.get("diamond_grade")
                    or self._grade(diamond_score)
                    or "UNRATED"
                )
                grade_model = str(zone.get("grade_model") or event.get("grade_model") or "DIAMOND_GRADE_V2_FALLBACK")
                diamond_tracked = bool(
                    tracked_setup
                    and tracked_setup.get("setup_model") == "DIAMOND_V6_AUTO"
                    and event_id
                    and (analysis.get("diamond_auto_entry") or {}).get("entry_event_id") == event_id
                )
                qualified_watch = bool(
                    zone.get("entry_eligible_origin")
                    and str(zone.get("display_role") or "QUALIFIED_WATCH") != "INVALIDATED_CONTEXT"
                    and str(zone.get("execution_quality") or "") != "INVALID"
                    and diamond_grade in {"A+", "A", "B", "C"}
                    and float(diamond_score or 0) >= 60
                )
                classification = (
                    "AUTO_ENTRY" if diamond_tracked
                    else "CONFIRMED" if event_id
                    else "QUALIFIED" if qualified_watch
                    else "CONTEXT"
                )
                zone_key = f"{symbol}:{tf}:{zone_id}"
                existing = connection.execute(
                    "SELECT classification, verification_status FROM diamond_zone_history WHERE zone_key = ?",
                    (zone_key,),
                ).fetchone()
                promoted = existing is None or CLASSIFICATION_RANK.get(classification, 0) > CLASSIFICATION_RANK.get(existing["classification"], 0)
                if existing and CLASSIFICATION_RANK.get(existing["classification"], 0) > CLASSIFICATION_RANK[classification]:
                    classification = existing["classification"]

                entry = self._number(event.get("execution_entry"))
                atr = self._number(event.get("atr_14") or zone.get("atr_14"))
                stop_reference = self._number(event.get("stop_reference"))
                stop = None
                target = None
                if event_id and entry is not None and atr and atr > 0 and stop_reference is not None:
                    stop = stop_reference - atr * 0.10 if zone.get("entry_side") == "BUY" else stop_reference + atr * 0.10
                    risk = abs(entry - stop)
                    minimum_rr = 1.8 if symbol == "XAUUSD" else 1.6
                    target = entry + risk * minimum_rr if zone.get("entry_side") == "BUY" else entry - risk * minimum_rr

                verification = (
                    "OPEN" if classification in {"CONFIRMED", "AUTO_ENTRY"}
                    else "MONITORING" if classification == "QUALIFIED"
                    else "NOT_AN_ENTRY"
                )
                if existing and existing["verification_status"] not in ACTIVE_VERIFICATIONS:
                    verification = existing["verification_status"]
                note = self._note(classification, verification)
                connection.execute(
                    """
                    INSERT INTO diamond_zone_history (
                        zone_key, zone_id, symbol, timeframe, origin_time, first_seen_at, updated_at,
                        source, strategy, profile, engine_version, configuration_fingerprint,
                        feed_matched, trust_status, direction, entry_side, line, zone_low,
                        zone_high, origin_model, origin_quality, quality_grade, entry_eligible,
                        classification, lifecycle, execution_quality, rejection_status, zone_strength,
                        diamond_score, diamond_grade, grade_model,
                        event_id, event_time, entry_price, stop_price, target_price, event_quality,
                        precision_grade, tracked_setup_id, verification_status, note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(zone_key) DO UPDATE SET
                        updated_at = excluded.updated_at,
                        source = excluded.source,
                        strategy = COALESCE(diamond_zone_history.strategy, excluded.strategy),
                        profile = COALESCE(diamond_zone_history.profile, excluded.profile),
                        engine_version = COALESCE(diamond_zone_history.engine_version, excluded.engine_version),
                        configuration_fingerprint = COALESCE(diamond_zone_history.configuration_fingerprint, excluded.configuration_fingerprint),
                        feed_matched = excluded.feed_matched,
                        trust_status = excluded.trust_status,
                        origin_quality = excluded.origin_quality,
                        quality_grade = excluded.quality_grade,
                        entry_eligible = MAX(diamond_zone_history.entry_eligible, excluded.entry_eligible),
                        classification = excluded.classification,
                        lifecycle = excluded.lifecycle,
                        execution_quality = excluded.execution_quality,
                        rejection_status = excluded.rejection_status,
                        zone_strength = excluded.zone_strength,
                        diamond_score = excluded.diamond_score,
                        diamond_grade = excluded.diamond_grade,
                        grade_model = excluded.grade_model,
                        event_id = COALESCE(excluded.event_id, diamond_zone_history.event_id),
                        event_time = COALESCE(excluded.event_time, diamond_zone_history.event_time),
                        entry_price = COALESCE(excluded.entry_price, diamond_zone_history.entry_price),
                        stop_price = COALESCE(excluded.stop_price, diamond_zone_history.stop_price),
                        target_price = COALESCE(excluded.target_price, diamond_zone_history.target_price),
                        event_quality = COALESCE(excluded.event_quality, diamond_zone_history.event_quality),
                        precision_grade = COALESCE(excluded.precision_grade, diamond_zone_history.precision_grade),
                        tracked_setup_id = COALESCE(excluded.tracked_setup_id, diamond_zone_history.tracked_setup_id),
                        verification_status = CASE
                            WHEN diamond_zone_history.verification_status IN ('MONITORING', 'OPEN') THEN excluded.verification_status
                            ELSE diamond_zone_history.verification_status
                        END,
                        note = excluded.note
                    """,
                    (
                        zone_key, zone_id, symbol, tf, origin_time, now, now, source, strategy, profile,
                        engine_version, configuration_fingerprint, 1 if feed_matched else 0,
                        trust_status, zone.get("direction"), zone.get("entry_side"), line, low, high,
                        zone.get("origin_model"), self._number(zone.get("origin_quality_score")),
                        zone.get("origin_quality_grade") or zone.get("quality_grade"),
                        1 if zone.get("entry_eligible_origin") else 0, classification, zone.get("lifecycle"),
                        zone.get("execution_quality"), zone.get("rejection_status"),
                        self._number(zone.get("zone_strength_score")), diamond_score, diamond_grade, grade_model,
                        event_id, self._integer(event.get("time")),
                        entry, stop, target, self._number(event.get("quality_score")),
                        event.get("precision_grade"), tracked_setup.get("id") if diamond_tracked else None,
                        verification, note,
                    ),
                )
                current_score = float(diamond_score or 0)
                current_grade = diamond_grade if diamond_grade in {"A+", "A", "B", "C", "D"} else self._grade(current_score)
                visible_now = bool(
                    zone.get("display_as_diamond") is True
                    or CLASSIFICATION_RANK.get(classification, 0) >= CLASSIFICATION_RANK["QUALIFIED"]
                )
                connection.execute(
                    """
                    UPDATE diamond_zone_history
                    SET peak_diamond_grade = CASE
                            WHEN ? >= COALESCE(peak_diamond_score, -1) THEN ?
                            ELSE peak_diamond_grade
                        END,
                        peak_diamond_score = MAX(COALESCE(peak_diamond_score, 0), ?),
                        ever_visible = MAX(COALESCE(ever_visible, 0), ?)
                    WHERE zone_key = ?
                    """,
                    (current_score, current_grade or "UNRATED", current_score, 1 if visible_now else 0, zone_key),
                )
                self._record_evidence(
                    connection,
                    zone_key,
                    analysis,
                    zones_result,
                    zone,
                    event,
                    classification,
                    verification,
                    now,
                    promoted,
                )
                recorded += 1

            if self.retention_per_symbol is not None:
                connection.execute(
                    """
                    DELETE FROM diamond_zone_history
                    WHERE symbol = ? AND id NOT IN (
                        SELECT id FROM diamond_zone_history WHERE symbol = ? ORDER BY id DESC LIMIT ?
                    )
                    """,
                    (symbol, symbol, self.retention_per_symbol),
                )
        return recorded

    def _record_evidence(
        self,
        connection: sqlite3.Connection,
        zone_key: str,
        analysis: Dict[str, Any],
        zones_result: Dict[str, Any],
        zone: Dict[str, Any],
        event: Dict[str, Any],
        classification: str,
        verification: str,
        captured_at: str,
        promoted: bool,
    ) -> None:
        existing = connection.execute(
            "SELECT * FROM diamond_evidence_ledger WHERE zone_key = ?",
            (zone_key,),
        ).fetchone()
        existing_events = self._json_list(existing["lifecycle_json"] if existing else None)
        events = self._classification_events(existing_events, classification, zone, event, captured_at)
        snapshot = self._evidence_snapshot(analysis, zones_result, zone, event, classification, verification, captured_at)
        replace_snapshot = existing is None or promoted
        evidence_json = json.dumps(snapshot, separators=(",", ":"), sort_keys=True)
        if existing and not replace_snapshot:
            evidence_json = existing["evidence_json"]
        stored_snapshot = self._json_object(evidence_json)
        style = str(stored_snapshot.get("trade_profile", {}).get("style") or "UNKNOWN").upper()
        session = str(stored_snapshot.get("market", {}).get("session") or "UNKNOWN").upper()
        regime = str(stored_snapshot.get("regime", {}).get("name") or "UNKNOWN").upper()
        regime_gate = str(stored_snapshot.get("regime", {}).get("gate") or "OBSERVE").upper()
        decision_score = self._number(stored_snapshot.get("decision", {}).get("score"))
        decision_status = str(stored_snapshot.get("decision", {}).get("status") or "UNKNOWN").upper()
        connection.execute(
            """
            INSERT INTO diamond_evidence_ledger (
                zone_key, captured_at, updated_at, trading_style, market_session,
                regime, regime_gate, decision_quality_score, decision_quality_status,
                evidence_json, lifecycle_json, forward_returns_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(zone_key) DO UPDATE SET
                captured_at = excluded.captured_at,
                updated_at = excluded.updated_at,
                trading_style = excluded.trading_style,
                market_session = excluded.market_session,
                regime = excluded.regime,
                regime_gate = excluded.regime_gate,
                decision_quality_score = excluded.decision_quality_score,
                decision_quality_status = excluded.decision_quality_status,
                evidence_json = excluded.evidence_json,
                lifecycle_json = excluded.lifecycle_json
            """,
            (
                zone_key,
                captured_at if replace_snapshot or existing is None else existing["captured_at"],
                captured_at,
                style,
                session,
                regime,
                regime_gate,
                decision_score,
                decision_status,
                evidence_json,
                json.dumps(events, separators=(",", ":"), sort_keys=True),
                existing["forward_returns_json"] if existing else "{}",
            ),
        )

    def _evidence_snapshot(
        self,
        analysis: Dict[str, Any],
        zones_result: Dict[str, Any],
        zone: Dict[str, Any],
        event: Dict[str, Any],
        classification: str,
        verification: str,
        captured_at: str,
    ) -> Dict[str, Any]:
        reconciliation = analysis.get("feed_reconciliation") or {}
        decision = analysis.get("decision_quality") or {}
        regime = analysis.get("market_regime") or {}
        news = analysis.get("news_intelligence") or {}
        session = analysis.get("session_framework") or {}
        k_trend = session.get("k_trend") or {}
        mtf = zones_result.get("mtf_confluence") or {}
        event_time = self._integer(event.get("confirmation_time") or event.get("available_at") or event.get("time"))
        origin_time = self._integer(zone.get("time"))
        anchor_time = event_time or origin_time
        primary_news = news.get("primary_event") or {}
        return {
            "schema": "DIAMOND_EVIDENCE_V1",
            "captured_at": captured_at,
            "data": {
                "source": zones_result.get("source") or analysis.get("analysis_data_source"),
                "feed_matched": zones_result.get("feed_matched") is True,
                "trust_status": (analysis.get("trust_gate") or {}).get("status"),
                "reconciliation": reconciliation.get("status"),
                "latest_closed_time": reconciliation.get("latest_closed_time"),
            },
            "trade_profile": {
                "style": str(analysis.get("trading_style") or zones_result.get("trading_style") or self._style_for_timeframe(zones_result.get("timeframe"))).upper(),
                "timeframe": str(zones_result.get("timeframe") or "15M").upper(),
                "execution_timeframe": zones_result.get("execution_timeframe"),
                "confirmation_timeframe": zones_result.get("confirmation_timeframe"),
            },
            "market": {
                "session": self._session(anchor_time),
                "stance": session.get("stance"),
                "position": session.get("position"),
                "confluence_score": session.get("confluence_score"),
                "k_trend_regime": k_trend.get("regime"),
                "k_trend_score": k_trend.get("score"),
            },
            "regime": {
                "name": regime.get("regime"),
                "gate": regime.get("execution_gate"),
                "strength": regime.get("strength"),
                "range_location": (regime.get("metrics") or {}).get("range_location"),
                "volatility_ratio": (regime.get("metrics") or {}).get("volatility_ratio"),
            },
            "decision": {
                "status": decision.get("status"),
                "score": decision.get("score"),
                "grade": decision.get("grade"),
                "ceiling": decision.get("score_ceiling"),
                "current_event": decision.get("current_event") is True,
                "blockers": [item.get("id") for item in (decision.get("top_blockers") or [])[:5]],
            },
            "news": {
                "risk_level": news.get("risk_level"),
                "gate": news.get("execution_gate"),
                "event": primary_news.get("title"),
                "event_time": primary_news.get("timestamp") or primary_news.get("date"),
            },
            "diamond": {
                "classification": classification,
                "signal_tier": event.get("signal_tier") or zone.get("signal_tier") or (
                    "CONFIRMED" if classification in {"CONFIRMED", "AUTO_ENTRY"}
                    else "QUALIFIED" if classification == "QUALIFIED"
                    else "EARLY"
                ),
                "closed_candle_proof": event.get("closed_candle_proof") or zone.get("closed_candle_proof") or {},
                "verification": verification,
                "origin_model": zone.get("origin_model"),
                "origin_quality": zone.get("origin_quality_score"),
                "quality_grade": zone.get("origin_quality_grade") or zone.get("quality_grade"),
                "diamond_score": event.get("diamond_score") or event.get("quality_score") or zone.get("diamond_score") or zone.get("diamond_confidence_score"),
                "diamond_grade": event.get("diamond_grade") or event.get("precision_grade") or zone.get("diamond_grade"),
                "grade_model": zone.get("grade_model") or event.get("grade_model"),
                "score_components": zone.get("score_components") or {},
                "score_penalties": zone.get("score_penalties") or {},
                "lifecycle": zone.get("lifecycle"),
                "execution_quality": zone.get("execution_quality"),
                "rejection": zone.get("rejection_status"),
                "zone_strength": zone.get("zone_strength_score"),
                "mtf_state": mtf.get("state") or mtf.get("status"),
                "mtf_score": mtf.get("score"),
            },
            "limitations": "Snapshot records evidence available when this lifecycle stage was first observed; it does not guarantee a future outcome.",
        }

    def _classification_events(
        self,
        existing: list[Dict[str, Any]],
        classification: str,
        zone: Dict[str, Any],
        event: Dict[str, Any],
        captured_at: str,
    ) -> list[Dict[str, Any]]:
        events = list(existing)
        origin_at = self._iso(self._integer(zone.get("time"))) if self._integer(zone.get("time")) is not None else captured_at
        event_time = self._integer(event.get("confirmation_time") or event.get("available_at") or event.get("time"))
        event_at = self._iso(event_time) if event_time is not None else captured_at
        self._append_event(events, "DETECTED", origin_at, "Diamond context first observed from a completed candle.")
        if CLASSIFICATION_RANK.get(classification, 0) >= CLASSIFICATION_RANK["QUALIFIED"]:
            self._append_event(events, "QUALIFIED", origin_at, "Origin passed the Diamond context quality gate.")
        if CLASSIFICATION_RANK.get(classification, 0) >= CLASSIFICATION_RANK["CONFIRMED"]:
            self._append_event(events, "CONFIRMED", event_at, "Retest and closed-candle confirmation were recorded.")
        if classification == "AUTO_ENTRY":
            self._append_event(events, "AUTO_ENTRY_ARMED", event_at, "Verified Diamond plan entered the research tracker.")
        return sorted(events, key=lambda item: (str(item.get("at") or ""), str(item.get("stage") or "")))

    def reconcile(self, symbol: str, frames: Dict[str, Iterable[Dict[str, Any]]]) -> int:
        normalized = str(symbol or "").upper()
        updates = 0
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT h.*, e.lifecycle_json, e.forward_returns_json
                FROM diamond_zone_history h
                LEFT JOIN diamond_evidence_ledger e ON e.zone_key = h.zone_key
                WHERE h.symbol = ?
                ORDER BY h.id
                """,
                (normalized,),
            ).fetchall()
            for row in rows:
                existing_forward = self._json_object(row["forward_returns_json"])
                horizon_20 = (existing_forward.get("horizons") or {}).get("20") or {}
                if row["verification_status"] not in ACTIVE_VERIFICATIONS and horizon_20.get("available") is True:
                    continue
                candles = self._candles(frames.get(row["timeframe"]) or [], int(row["origin_time"]))
                if not candles:
                    continue
                status = row["verification_status"]
                verified_at = row["verified_at"]
                outcome_r = row["outcome_r"]
                last_candle_at = int(candles[-1]["time"])

                if row["classification"] in {"CONFIRMED", "AUTO_ENTRY"} and row["event_time"]:
                    event_rows = [item for item in candles if item["time"] > int(row["event_time"])]
                    direction = row["entry_side"]
                    stop = self._number(row["stop_price"])
                    target = self._number(row["target_price"])
                    if stop is not None and target is not None:
                        for candle in event_rows:
                            stop_hit = candle["low"] <= stop if direction == "BUY" else candle["high"] >= stop
                            target_hit = candle["high"] >= target if direction == "BUY" else candle["low"] <= target
                            if stop_hit and target_hit:
                                status, outcome_r = "AMBIGUOUS", None
                            elif stop_hit:
                                status, outcome_r = "LOST", -1.0
                            elif target_hit:
                                status = "WON"
                                outcome_r = 1.8 if normalized == "XAUUSD" else 1.6
                            else:
                                continue
                            verified_at = self._iso(candle["time"])
                            break
                    if status == "OPEN" and len(event_rows) >= EXPIRY_BARS.get(row["timeframe"], 24):
                        status = "EXPIRED"
                        verified_at = self._iso(event_rows[-1]["time"])
                else:
                    consecutive = 0
                    for candle in candles:
                        broken = candle["close"] < row["zone_low"] if row["entry_side"] == "BUY" else candle["close"] > row["zone_high"]
                        consecutive = consecutive + 1 if broken else 0
                        if consecutive >= 2:
                            status = "INVALIDATED_NO_ENTRY"
                            verified_at = self._iso(candle["time"])
                            break
                    if status == "MONITORING" and len(candles) >= EXPIRY_BARS.get(row["timeframe"], 24):
                        status = "EXPIRED_NO_ENTRY"
                        verified_at = self._iso(candles[-1]["time"])

                forward_returns = self._forward_returns(row, candles)
                self._update_reconciliation_evidence(
                    connection,
                    row,
                    status,
                    verified_at,
                    forward_returns,
                )

                if status != row["verification_status"] or last_candle_at != row["last_candle_at"]:
                    connection.execute(
                        """
                        UPDATE diamond_zone_history
                        SET verification_status = ?, verified_at = ?, outcome_r = ?, last_candle_at = ?,
                            updated_at = ?, note = ?,
                            diamond_score = CASE
                                WHEN ? IN ('INVALIDATED_NO_ENTRY', 'CANCELLED') AND classification NOT IN ('CONFIRMED', 'AUTO_ENTRY')
                                THEN MIN(COALESCE(diamond_score, 49), 49)
                                ELSE diamond_score
                            END,
                            diamond_grade = CASE
                                WHEN ? IN ('INVALIDATED_NO_ENTRY', 'CANCELLED') AND classification NOT IN ('CONFIRMED', 'AUTO_ENTRY')
                                THEN 'UNRATED'
                                ELSE diamond_grade
                            END,
                            grade_model = CASE
                                WHEN ? IN ('INVALIDATED_NO_ENTRY', 'CANCELLED') AND classification NOT IN ('CONFIRMED', 'AUTO_ENTRY')
                                THEN 'DIAMOND_GRADE_V2_REJECTED'
                                ELSE grade_model
                            END
                        WHERE id = ?
                        """,
                        (
                            status, verified_at, outcome_r, last_candle_at,
                            datetime.now(timezone.utc).isoformat(), self._note(row["classification"], status),
                            status, status, status, row["id"],
                        ),
                    )
                    updates += 1
        return updates

    def _update_reconciliation_evidence(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        status: str,
        verified_at: Optional[str],
        forward_returns: Dict[str, Any],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        events = self._json_list(row["lifecycle_json"] if "lifecycle_json" in row.keys() else None)
        if not events:
            origin_at = self._iso(int(row["origin_time"]))
            self._append_event(events, "DETECTED", origin_at, "Historical Diamond context was restored into the V3 ledger.")
            if CLASSIFICATION_RANK.get(row["classification"], 0) >= CLASSIFICATION_RANK["QUALIFIED"]:
                self._append_event(events, "QUALIFIED", origin_at, "Historical qualified origin was restored into the V3 ledger.")
            if CLASSIFICATION_RANK.get(row["classification"], 0) >= CLASSIFICATION_RANK["CONFIRMED"]:
                confirmed_at = self._iso(int(row["event_time"])) if row["event_time"] else origin_at
                self._append_event(events, "CONFIRMED", confirmed_at, "Historical confirmed entry was restored into the V3 ledger.")
        if status != row["verification_status"]:
            self._append_event(events, status, verified_at or now, self._note(row["classification"], status))

        style = self._style_for_timeframe(row["timeframe"])
        anchor_time = int(row["event_time"] or row["origin_time"])
        legacy_snapshot = {
            "schema": "DIAMOND_EVIDENCE_V1",
            "captured_at": row["first_seen_at"],
            "data": {
                "source": row["source"],
                "feed_matched": bool(row["feed_matched"]),
                "trust_status": row["trust_status"],
            },
            "trade_profile": {"style": style, "timeframe": row["timeframe"]},
            "market": {"session": self._session(anchor_time)},
            "regime": {"name": "UNKNOWN", "gate": "OBSERVE"},
            "decision": {"status": "LEGACY_EVIDENCE", "score": None},
            "diamond": {
                "classification": row["classification"],
                "verification": status,
                "origin_quality": row["origin_quality"],
                "quality_grade": row["quality_grade"],
            },
            "limitations": "Legacy evidence predates V3 decision and regime snapshots.",
        }
        connection.execute(
            """
            INSERT INTO diamond_evidence_ledger (
                zone_key, captured_at, updated_at, trading_style, market_session,
                regime, regime_gate, decision_quality_score, decision_quality_status,
                evidence_json, lifecycle_json, forward_returns_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(zone_key) DO UPDATE SET
                updated_at = excluded.updated_at,
                lifecycle_json = excluded.lifecycle_json,
                forward_returns_json = excluded.forward_returns_json
            """,
            (
                row["zone_key"],
                row["first_seen_at"],
                now,
                style,
                self._session(anchor_time),
                "UNKNOWN",
                "OBSERVE",
                None,
                "LEGACY_EVIDENCE",
                json.dumps(legacy_snapshot, separators=(",", ":"), sort_keys=True),
                json.dumps(events, separators=(",", ":"), sort_keys=True),
                json.dumps(forward_returns, separators=(",", ":"), sort_keys=True),
            ),
        )

    def _forward_returns(self, row: sqlite3.Row, candles: list[Dict[str, float]]) -> Dict[str, Any]:
        anchor_time = int(row["event_time"] or row["origin_time"])
        future = [candle for candle in candles if int(candle["time"]) > anchor_time]
        direction = str(row["entry_side"] or "BUY").upper()
        anchor_price = self._number(row["entry_price"] if row["event_time"] else row["line"])
        stop = self._number(row["stop_price"])
        risk = abs(anchor_price - stop) if anchor_price is not None and stop is not None else None
        horizons: Dict[str, Any] = {}
        for bars in (5, 10, 20):
            if len(future) < bars or anchor_price is None or anchor_price <= 0:
                horizons[str(bars)] = {"available": False}
                continue
            candle = future[bars - 1]
            move = candle["close"] - anchor_price if direction == "BUY" else anchor_price - candle["close"]
            horizons[str(bars)] = {
                "available": True,
                "time": int(candle["time"]),
                "at": self._iso(int(candle["time"])),
                "close": round(float(candle["close"]), 5),
                "directional_pct": round(move / anchor_price * 100.0, 3),
                "mark_r": round(move / risk, 3) if risk else None,
            }
        return {
            "basis": "EVENT_ENTRY" if row["event_time"] else "ZONE_LINE_CONTEXT",
            "anchor_time": anchor_time,
            "anchor_price": anchor_price,
            "direction": direction,
            "horizons": horizons,
            "uses_completed_candles_only": True,
        }

    def list(self, symbol: Optional[str] = None, limit: int = 30) -> list[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        where = " WHERE h.symbol = ?" if symbol else ""
        params = (symbol.upper(), safe_limit) if symbol else (safe_limit,)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT h.*,
                       t.lifecycle_status AS tracked_status,
                       t.outcome_r AS tracked_outcome_r,
                       t.entry_hit_at AS tracked_entry_hit_at,
                       t.closed_at AS tracked_closed_at,
                       t.note AS tracked_note,
                       e.captured_at AS evidence_captured_at,
                       e.trading_style AS evidence_trading_style,
                       e.market_session AS evidence_market_session,
                       e.regime AS evidence_regime,
                       e.regime_gate AS evidence_regime_gate,
                       e.decision_quality_score AS evidence_decision_score,
                       e.decision_quality_status AS evidence_decision_status,
                       e.evidence_json,
                       e.lifecycle_json,
                       e.forward_returns_json
                FROM diamond_zone_history h
                LEFT JOIN tracked_setups t ON t.id = h.tracked_setup_id
                LEFT JOIN diamond_evidence_ledger e ON e.zone_key = h.zone_key
                {where}
                ORDER BY h.origin_time DESC, h.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._public_row(row) for row in rows]

    def stats(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        where = " WHERE h.symbol = ?" if symbol else ""
        params = (symbol.upper(),) if symbol else ()
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total,
                       SUM(CASE
                           WHEN h.classification = 'CONTEXT'
                             OR (h.classification = 'QUALIFIED' AND COALESCE(t.lifecycle_status, h.verification_status) IN ('INVALIDATED_NO_ENTRY', 'EXPIRED_NO_ENTRY', 'CANCELLED'))
                           THEN 1 ELSE 0 END) AS context,
                       SUM(CASE
                           WHEN h.classification = 'QUALIFIED' AND COALESCE(t.lifecycle_status, h.verification_status) IN ('MONITORING', 'WAITING_ENTRY')
                           THEN 1 ELSE 0 END) AS qualified,
                       SUM(CASE WHEN h.classification IN ('CONFIRMED', 'AUTO_ENTRY') THEN 1 ELSE 0 END) AS confirmed,
                       SUM(CASE WHEN h.classification = 'AUTO_ENTRY' THEN 1 ELSE 0 END) AS auto_entries,
                       SUM(CASE WHEN COALESCE(t.lifecycle_status, h.verification_status) = 'WON' THEN 1 ELSE 0 END) AS won,
                       SUM(CASE WHEN COALESCE(t.lifecycle_status, h.verification_status) = 'LOST' THEN 1 ELSE 0 END) AS lost,
                       SUM(CASE WHEN COALESCE(t.lifecycle_status, h.verification_status) = 'AMBIGUOUS' THEN 1 ELSE 0 END) AS ambiguous,
                       SUM(CASE WHEN COALESCE(t.lifecycle_status, h.verification_status) IN ('MONITORING', 'WAITING_ENTRY') THEN 1 ELSE 0 END) AS monitoring,
                       SUM(CASE WHEN COALESCE(t.lifecycle_status, h.verification_status) = 'OPEN' THEN 1 ELSE 0 END) AS open,
                       SUM(CASE WHEN COALESCE(t.lifecycle_status, h.verification_status) IN ('WON', 'LOST') THEN 1 ELSE 0 END) AS resolved,
                       SUM(CASE WHEN COALESCE(t.lifecycle_status, h.verification_status) IN ('EXPIRED', 'EXPIRED_NO_ENTRY') THEN 1 ELSE 0 END) AS expired,
                       SUM(CASE WHEN COALESCE(t.lifecycle_status, h.verification_status) IN ('INVALIDATED_NO_ENTRY', 'CANCELLED') THEN 1 ELSE 0 END) AS invalidated,
                       SUM(CASE WHEN h.feed_matched = 1 THEN 1 ELSE 0 END) AS matched,
                       AVG(CASE WHEN h.diamond_score >= CASE WHEN h.symbol = 'XAUUSD' THEN 45 ELSE 50 END AND h.diamond_grade IN ('A+', 'A', 'B', 'C', 'D') THEN h.diamond_score END) AS average_diamond_score,
                       AVG(h.diamond_score) AS audit_average_score,
                       SUM(CASE WHEN h.diamond_grade = 'A+' THEN 1 ELSE 0 END) AS grade_a_plus,
                       SUM(CASE WHEN h.diamond_grade = 'A' THEN 1 ELSE 0 END) AS grade_a,
                       SUM(CASE WHEN h.diamond_grade = 'B' THEN 1 ELSE 0 END) AS grade_b,
                       SUM(CASE WHEN h.diamond_grade = 'C' THEN 1 ELSE 0 END) AS grade_c,
                       SUM(CASE WHEN h.diamond_grade = 'D' THEN 1 ELSE 0 END) AS grade_d,
                       SUM(CASE WHEN h.diamond_grade NOT IN ('A+', 'A', 'B', 'C', 'D') OR h.diamond_score < CASE WHEN h.symbol = 'XAUUSD' THEN 45 ELSE 50 END THEN 1 ELSE 0 END) AS rejected_score,
                       MAX(h.updated_at) AS latest_at
                FROM diamond_zone_history h
                LEFT JOIN tracked_setups t ON t.id = h.tracked_setup_id
                {where}
                """,
                params,
            ).fetchone()
        won = int(row["won"] or 0)
        lost = int(row["lost"] or 0)
        resolved = won + lost
        return {
            "total": int(row["total"] or 0),
            "context": int(row["context"] or 0),
            "qualified": int(row["qualified"] or 0),
            "confirmed": int(row["confirmed"] or 0),
            "auto_entries": int(row["auto_entries"] or 0),
            "won": won,
            "lost": lost,
            "ambiguous": int(row["ambiguous"] or 0),
            "average_diamond_score": round(float(row["average_diamond_score"] or 0), 1),
            "audit_average_score": round(float(row["audit_average_score"] or 0), 1),
            "grade_distribution": {
                "A+": int(row["grade_a_plus"] or 0),
                "A": int(row["grade_a"] or 0),
                "B": int(row["grade_b"] or 0),
                "C": int(row["grade_c"] or 0),
                "D": int(row["grade_d"] or 0),
            },
            "rejected_observations": int(row["rejected_score"] or 0),
            "lifecycle": {
                "detected": int(row["total"] or 0),
                "qualified": int(row["qualified"] or 0) + int(row["confirmed"] or 0),
                "confirmed": int(row["confirmed"] or 0),
                "monitoring": int(row["monitoring"] or 0),
                "open": int(row["open"] or 0),
                "resolved": int(row["resolved"] or 0),
                "expired": int(row["expired"] or 0),
                "invalidated": int(row["invalidated"] or 0),
            },
            "matched": int(row["matched"] or 0),
            "verified_accuracy": round(won / resolved * 100, 1) if resolved else None,
            "latest_at": row["latest_at"],
            "verification_method": "CLOSED_CANDLE_FIXED_R_AUDIT",
        }

    def calibration(self, symbol: str) -> Dict[str, Any]:
        normalized = str(symbol or "XAUUSD").upper()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT h.timeframe, h.entry_side, h.event_time, h.origin_time, h.diamond_grade,
                       COALESCE(t.lifecycle_status, h.verification_status) AS outcome,
                       COALESCE(t.outcome_r, h.outcome_r) AS outcome_r,
                       COALESCE(e.trading_style, '') AS trading_style,
                       COALESCE(e.market_session, '') AS market_session,
                       COALESCE(e.regime, '') AS regime
                FROM diamond_zone_history h
                LEFT JOIN tracked_setups t ON t.id = h.tracked_setup_id
                LEFT JOIN diamond_evidence_ledger e ON e.zone_key = h.zone_key
                WHERE h.symbol = ? AND h.classification IN ('CONFIRMED', 'AUTO_ENTRY')
                ORDER BY COALESCE(h.event_time, h.origin_time), h.id
                """,
                (normalized,),
            ).fetchall()
        records = []
        for row in rows:
            timeframe = str(row["timeframe"] or "15M").upper()
            anchor_time = int(row["event_time"] or row["origin_time"])
            records.append({
                "timeframe": timeframe,
                "side": str(row["entry_side"] or "UNKNOWN").upper(),
                "grade": str(row["diamond_grade"] or "-").upper(),
                "style": str(row["trading_style"] or self._style_for_timeframe(timeframe)).upper(),
                "session": str(row["market_session"] or self._session(anchor_time)).upper(),
                "regime": str(row["regime"] or "UNKNOWN").upper(),
                "outcome": str(row["outcome"] or "MONITORING").upper(),
                "outcome_r": self._number(row["outcome_r"]),
            })
        profiles = []
        for style, timeframes in (("SCALPING", ["5M", "15M"]), ("SWING", ["1H", "4H"]), ("POSITION", ["1D"])):
            group = [record for record in records if record["style"] == style or record["timeframe"] in timeframes]
            if group or style != "POSITION":
                profiles.append({"style": style, "timeframes": timeframes, **self._calibration_summary(group)})
        overall = self._calibration_summary(records)
        return {
            "status": overall["sample_status"],
            "version": "DIAMOND_CALIBRATION_V1",
            "symbol": normalized,
            "overall": overall,
            "profiles": profiles,
            "segments": {
                "timeframe": self._calibration_groups(records, "timeframe"),
                "session": self._calibration_groups(records, "session"),
                "side": self._calibration_groups(records, "side"),
                "grade": self._calibration_groups(records, "grade"),
                "regime": self._calibration_groups(records, "regime"),
            },
            "minimum_evidence_sample": 100,
            "uses_confirmed_entries_only": True,
            "uses_completed_candles_only": True,
            "expired_and_ambiguous_excluded_from_win_rate": True,
            "risk_note": "Historical calibration describes recorded evidence and does not guarantee future performance.",
        }

    @classmethod
    def _calibration_groups(cls, records: list[Dict[str, Any]], key: str) -> list[Dict[str, Any]]:
        values: Dict[str, list[Dict[str, Any]]] = {}
        for record in records:
            values.setdefault(str(record.get(key) or "UNKNOWN"), []).append(record)
        return [{key: name, **cls._calibration_summary(group)} for name, group in sorted(values.items())]

    @staticmethod
    def _calibration_summary(records: list[Dict[str, Any]]) -> Dict[str, Any]:
        resolved = [record for record in records if record["outcome"] in {"WON", "LOST"}]
        pnl = [float(record["outcome_r"]) for record in resolved if record.get("outcome_r") is not None]
        wins = sum(1 for record in resolved if record["outcome"] == "WON")
        losses = sum(1 for record in resolved if record["outcome"] == "LOST")
        gross_gain = sum(value for value in pnl if value > 0)
        gross_loss = abs(sum(value for value in pnl if value < 0))
        equity = 0.0
        peak = 0.0
        drawdown = 0.0
        for value in pnl:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        resolved_count = wins + losses
        sample_status = (
            "EVIDENCE_READY" if resolved_count >= 100
            else "DEVELOPING_SAMPLE" if resolved_count >= 50
            else "EARLY_SAMPLE" if resolved_count >= 20
            else "INSUFFICIENT_SAMPLE"
        )
        return {
            "confirmed": len(records),
            "resolved": resolved_count,
            "wins": wins,
            "losses": losses,
            "active": sum(1 for record in records if record["outcome"] in {"OPEN", "WAITING_ENTRY", "MONITORING"}),
            "expired": sum(1 for record in records if str(record["outcome"]).startswith("EXPIRED")),
            "ambiguous": sum(1 for record in records if record["outcome"] == "AMBIGUOUS"),
            "win_rate": round(wins / resolved_count * 100.0, 1) if resolved_count else None,
            "expectancy_r": round(sum(pnl) / len(pnl), 3) if pnl else None,
            "net_r": round(sum(pnl), 3),
            "profit_factor": round(gross_gain / gross_loss, 3) if gross_loss else ("INF" if gross_gain else None),
            "max_drawdown_r": round(drawdown, 3),
            "sample_status": sample_status,
            "progress_percent": min(100, resolved_count),
        }

    def _public_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        private = {
            "tracked_status", "tracked_outcome_r", "tracked_entry_hit_at", "tracked_closed_at", "tracked_note",
            "evidence_json", "lifecycle_json", "forward_returns_json",
        }
        result = {key: row[key] for key in row.keys() if key not in private}
        result["feed_matched"] = bool(result["feed_matched"])
        result["entry_eligible"] = bool(result["entry_eligible"])
        result["ever_visible"] = bool(result.get("ever_visible"))
        evidence = self._json_object(row["evidence_json"] if "evidence_json" in row.keys() else None)
        lifecycle = self._json_list(row["lifecycle_json"] if "lifecycle_json" in row.keys() else None)
        forward_returns = self._json_object(row["forward_returns_json"] if "forward_returns_json" in row.keys() else None)
        if row["tracked_status"]:
            result["verification_status"] = row["tracked_status"]
            result["outcome_r"] = row["tracked_outcome_r"]
            result["verification_source"] = "AUTO_ENTRY_TRACKER"
            tracked_at = row["tracked_closed_at"] or row["tracked_entry_hit_at"] or result.get("evidence_captured_at") or result["updated_at"]
            self._append_event(lifecycle, row["tracked_status"], tracked_at, row["tracked_note"] or "Research tracker lifecycle updated.")
        else:
            result["verification_source"] = "DIAMOND_CLOSED_CANDLE_AUDIT"
        result["evidence_snapshot"] = evidence
        result["lifecycle_events"] = sorted(lifecycle, key=lambda item: (str(item.get("at") or ""), str(item.get("stage") or "")))
        result["forward_returns"] = forward_returns
        result["lifecycle_stage"] = self._public_lifecycle_stage(result["classification"], result["verification_status"])
        score = self._number(result.get("diamond_score"))
        if score is None:
            score = self._number(result.get("event_quality") or result.get("zone_strength") or result.get("origin_quality")) or 0.0
        result["diamond_score"] = round(score)
        visibility_floor = self._visibility_floor(result.get("symbol"))
        stored_grade = str(result.get("diamond_grade") or "").upper()
        result["diamond_grade"] = stored_grade if stored_grade in {"A+", "A", "B", "C", "D"} and score >= visibility_floor else self._grade(score, visibility_floor)
        captured_diamond = evidence.get("diamond") or {}
        peak_candidates = [
            self._number(result.get("peak_diamond_score")),
            score,
            self._number(captured_diamond.get("diamond_score")),
        ]
        peak_scores = [item for item in peak_candidates if item is not None]
        peak_score = max(peak_scores) if peak_scores else 0.0
        result["peak_diamond_score"] = round(peak_score)
        result["peak_diamond_grade"] = self._grade(peak_score, visibility_floor)
        result["ever_visible"] = bool(
            result["ever_visible"]
            or peak_score >= visibility_floor
            or CLASSIFICATION_RANK.get(str(result.get("classification") or "CONTEXT").upper(), 0) >= CLASSIFICATION_RANK["QUALIFIED"]
        )
        verification = str(result.get("verification_status") or "").upper()
        if verification in {"INVALIDATED_NO_ENTRY", "CANCELLED"}:
            result["display_classification"] = "INVALIDATED_CONTEXT"
            result["diamond_grade"] = None
            result["grade_status"] = "REJECTED_CONTEXT"
        elif verification == "EXPIRED_NO_ENTRY":
            result["display_classification"] = "EXPIRED_CONTEXT"
            result["grade_status"] = "EXPIRED_CONTEXT"
        else:
            result["display_classification"] = result["classification"]
            result["grade_status"] = (
                "CONFIRMED_EVIDENCE" if result["classification"] in {"CONFIRMED", "AUTO_ENTRY"}
                else "QUALIFIED_WATCH" if result["classification"] == "QUALIFIED"
                else "CONTEXT_ONLY"
            )
        result["origin_at"] = self._iso(int(result["origin_time"]))
        result["event_at"] = self._iso(int(result["event_time"])) if result.get("event_time") else None
        result["signal_tier"] = (
            "CONFIRMED" if result["classification"] in {"CONFIRMED", "AUTO_ENTRY"}
            else "QUALIFIED" if result["classification"] == "QUALIFIED"
            else "EARLY"
        )
        proof_time = int(result.get("event_time") or result["origin_time"])
        timeframe_seconds = {"5M": 300, "15M": 900, "1H": 3600, "4H": 14400, "1D": 86400}.get(str(result.get("timeframe") or "").upper(), 0)
        result["closed_candle_proof"] = {
            "status": "VERIFIED",
            "source_bar_time": proof_time,
            "locked_after": proof_time + timeframe_seconds if timeframe_seconds else proof_time,
            "completed_candle_only": True,
            "non_repainting": True,
            "policy": "CLOSED_CANDLE_LOCKED",
        }
        return result

    @staticmethod
    def _candles(candles: Iterable[Dict[str, Any]], origin_time: int) -> list[Dict[str, float]]:
        normalized = []
        for item in candles:
            timestamp = DiamondHistory._integer(item.get("time") or item.get("timestamp"))
            try:
                row = {
                    "time": timestamp,
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                }
            except (KeyError, TypeError, ValueError):
                continue
            if timestamp is not None and timestamp > origin_time and item.get("is_complete") is not False and item.get("is_partial") is not True:
                normalized.append(row)
        return sorted(normalized, key=lambda item: item["time"])

    @staticmethod
    def _note(classification: str, verification: str) -> str:
        if verification == "NOT_AN_ENTRY":
            return "Context marker only; excluded from Diamond entry accuracy."
        if verification == "EXPIRED_NO_ENTRY":
            return "Qualified origin expired without a confirmed entry; excluded from win/loss."
        if verification == "INVALIDATED_NO_ENTRY":
            return "Zone invalidated before entry confirmation; excluded from win/loss."
        if verification == "WON":
            return "Fixed-R target verified on a later completed provider candle."
        if verification == "LOST":
            return "Stop level verified on a later completed provider candle."
        if verification == "AMBIGUOUS":
            return "Stop and target touched in one candle; intrabar order is unknown."
        if verification == "EXPIRED":
            return "Confirmed entry did not reach stop or target inside the audit window."
        return "Waiting for later completed provider candles."

    @staticmethod
    def _fingerprint(configuration: Dict[str, Any]) -> str:
        payload = json.dumps(configuration, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _append_event(events: list[Dict[str, Any]], stage: str, at: str, note: str) -> None:
        normalized_stage = str(stage or "UNKNOWN").upper()
        normalized_at = str(at or "")
        if any(item.get("stage") == normalized_stage and str(item.get("at") or "") == normalized_at for item in events):
            return
        events.append({"stage": normalized_stage, "at": normalized_at, "note": note})

    @staticmethod
    def _json_object(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _json_list(value: Any) -> list[Dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if not value:
            return []
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []

    @staticmethod
    def _style_for_timeframe(timeframe: Any) -> str:
        normalized = str(timeframe or "15M").upper()
        if normalized in {"5M", "15M"}:
            return "SCALPING"
        if normalized in {"1H", "4H"}:
            return "SWING"
        return "POSITION"

    @staticmethod
    def _session(timestamp: Optional[int]) -> str:
        if timestamp is None:
            return "UNKNOWN"
        hour = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).hour
        if 0 <= hour < 7:
            return "ASIA"
        if 7 <= hour < 13:
            return "LONDON"
        if 13 <= hour < 21:
            return "NEW_YORK"
        return "ROLLOVER"

    @staticmethod
    def _public_lifecycle_stage(classification: str, verification: str) -> str:
        normalized = str(verification or "").upper()
        if normalized == "WAITING_ENTRY":
            return "WAITING_ENTRY"
        if normalized == "OPEN":
            return "ACTIVE"
        if normalized in {"WON", "LOST", "AMBIGUOUS", "EXPIRED", "CANCELLED"}:
            return normalized
        if normalized in {"INVALIDATED_NO_ENTRY", "EXPIRED_NO_ENTRY"}:
            return normalized
        return "QUALIFIED" if CLASSIFICATION_RANK.get(classification, 0) >= CLASSIFICATION_RANK["QUALIFIED"] else "CONTEXT"

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _grade(score: Optional[float], minimum_d_score: int = 50) -> Optional[str]:
        value = float(score or 0)
        if value >= 90:
            return "A+"
        if value >= 80:
            return "A"
        if value >= 70:
            return "B"
        if value >= 60:
            return "C"
        if value >= minimum_d_score:
            return "D"
        return None

    @staticmethod
    def _visibility_floor(symbol: Any) -> int:
        return 45 if str(symbol or "").upper() == "XAUUSD" else 50

    @staticmethod
    def _integer(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            pass
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())

    @staticmethod
    def _iso(timestamp: int) -> str:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
