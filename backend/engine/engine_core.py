from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from .analyzer import GoldAnalyzer
from .xauusd_provider import MIN_ANALYSIS_CANDLES, SQLiteCandleStore, SOURCE_NAME, validate_analysis_readiness

BUFFER_LIMITS = {"1M": 1500, "5M": 1000, "15M": 800, "1H": 500, "4H": 300, "1D": 200}
VALID_MODES = {"fast", "balanced", "deep"}


@dataclass
class WorkflowStage:
    name: str
    status: str
    confidence: int
    reason: str
    timeframe: str
    detected_zones: List[Dict[str, Any]]
    invalidation_condition: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "confidence": self.confidence,
            "reason": self.reason,
            "timeframe": self.timeframe,
            "detected_zones": self.detected_zones,
            "invalidation_condition": self.invalidation_condition,
        }


class EngineLogger:
    def __init__(self, store: SQLiteCandleStore):
        self.store = store

    def log(self, category: str, message: str, level: str = "INFO") -> None:
        with self.store.connect() as conn:
            conn.execute(
                "INSERT INTO engine_logs (timestamp, category, level, message) VALUES (?, ?, ?, ?)",
                (pd.Timestamp.now(tz="UTC").isoformat(), category, level, message),
            )
            conn.execute("DELETE FROM engine_logs WHERE id NOT IN (SELECT id FROM engine_logs ORDER BY id DESC LIMIT 500)")

    def latest(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT timestamp, category, level, message FROM engine_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear(self) -> None:
        with self.store.connect() as conn:
            conn.execute("DELETE FROM engine_logs")


class CandleBuffer:
    def __init__(self, store: SQLiteCandleStore):
        self.store = store
        self.frames: Dict[str, pd.DataFrame] = {}
        self.refresh()

    def refresh(self, timeframes: Optional[List[str]] = None) -> None:
        for tf in timeframes or list(BUFFER_LIMITS):
            self.frames[tf] = self.store.get_candles_df(tf, BUFFER_LIMITS[tf])

    def get(self, timeframe: str, limit: Optional[int] = None) -> pd.DataFrame:
        if timeframe not in self.frames:
            self.refresh([timeframe])
        df = self.frames.get(timeframe, pd.DataFrame())
        return df.tail(limit).copy() if limit else df.copy()

    def counts(self) -> Dict[str, int]:
        return {tf: len(df) for tf, df in self.frames.items()}


class CandleQualityValidator:
    def validate(self, frames: Dict[str, pd.DataFrame], provider_status: Dict[str, Any]) -> Dict[str, Any]:
        warnings: List[str] = []
        errors: List[str] = []
        counts = {tf: len(df) for tf, df in frames.items()}
        readiness = validate_analysis_readiness(counts)
        for item in readiness["missing"]:
            warnings.append(item["message"])
        for tf, df in frames.items():
            if len(df) == 0:
                continue
            if df.index.has_duplicates:
                errors.append(f"Duplicate timestamps detected on {tf}.")
            invalid_ohlc = (
                (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
                | (df["high"] < df[["open", "close", "low"]].max(axis=1))
                | (df["low"] > df[["open", "close", "high"]].min(axis=1))
            )
            if invalid_ohlc.any():
                errors.append(f"Invalid OHLC values detected on {tf}.")
            if len(df) >= 2:
                pct = df["close"].pct_change().abs().dropna()
                if (pct > 0.05).any():
                    warnings.append(f"Large abnormal candle gap detected on {tf}.")
        if provider_status.get("status") in ["DELAYED", "CONNECTION_FAILED", "RATE_LIMIT", "ERROR", "INVALID_PRICE", "NO_PRICE", "RETRYING", "STARTING"]:
            warnings.append(f"Provider status is {provider_status.get('status')}.")
        status = "ERROR" if errors else "WEAK" if warnings else "READY"
        return {
            "status": status,
            "warnings": warnings,
            "errors": errors,
            "counts": counts,
            "ready": status != "ERROR" and readiness["ready"],
            "missing_history": readiness["missing"],
        }


class AnalysisCache:
    def __init__(self, store: SQLiteCandleStore):
        self.store = store

    def get(self, key: str, dependency_timestamp: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self.store.connect() as conn:
            row = conn.execute("SELECT value, dependency_timestamp FROM analysis_cache WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        if dependency_timestamp is not None and row["dependency_timestamp"] != dependency_timestamp:
            return None
        return json.loads(row["value"])

    def set(self, key: str, value: Dict[str, Any], dependency_timestamp: Optional[str] = None) -> None:
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO analysis_cache (key, value, dependency_timestamp, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    dependency_timestamp=excluded.dependency_timestamp,
                    updated_at=excluded.updated_at
                """,
                (key, json.dumps(value, default=str), dependency_timestamp, pd.Timestamp.now(tz="UTC").isoformat()),
            )

    def snapshot(self) -> Dict[str, Any]:
        with self.store.connect() as conn:
            rows = conn.execute("SELECT key, value, dependency_timestamp, updated_at FROM analysis_cache ORDER BY key").fetchall()
        return {
            row["key"]: {
                "value": json.loads(row["value"]),
                "dependency_timestamp": row["dependency_timestamp"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def clear(self) -> None:
        with self.store.connect() as conn:
            conn.execute("DELETE FROM analysis_cache")

    def status(self) -> Dict[str, Any]:
        snap = self.snapshot()
        return {"entries": len(snap), "keys": list(snap)}


class EngineCore:
    def __init__(self, store: SQLiteCandleStore):
        self.store = store
        self.buffer = CandleBuffer(store)
        self.cache = AnalysisCache(store)
        self.quality = CandleQualityValidator()
        self.logs = EngineLogger(store)

    def get_mode(self) -> str:
        with self.store.connect() as conn:
            row = conn.execute("SELECT mode FROM engine_status WHERE id = 1").fetchone()
        return row["mode"] if row else "balanced"

    def set_mode(self, mode: str) -> Dict[str, Any]:
        mode = mode.lower().strip()
        if mode not in VALID_MODES:
            raise ValueError("mode must be fast, balanced, or deep")
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO engine_status (id, mode, current_analysis_status, last_analysis_time, updated_at)
                VALUES (1, ?, 'IDLE', NULL, ?)
                ON CONFLICT(id) DO UPDATE SET mode=excluded.mode, updated_at=excluded.updated_at
                """,
                (mode, pd.Timestamp.now(tz="UTC").isoformat()),
            )
        self.logs.log("Engine", f"Engine mode set to {mode}.")
        return self.status()

    def status(self) -> Dict[str, Any]:
        self.buffer.refresh()
        provider_status = self.store.load_status().to_dict()
        quality = self.quality.validate({tf: self.buffer.get(tf) for tf in ["5M", "15M", "1H", "4H", "1D"]}, provider_status)
        with self.store.connect() as conn:
            row = conn.execute("SELECT current_analysis_status, last_analysis_time FROM engine_status WHERE id = 1").fetchone()
        return {
            "engine_core_version": "V3",
            "engine_mode": self.get_mode(),
            "provider_status": provider_status,
            "last_price": provider_status.get("latest_price"),
            "last_updated": provider_status.get("last_updated"),
            "candle_counts": self.store.counts(),
            "cache_status": self.cache.status(),
            "data_quality_status": quality,
            "current_analysis_status": row["current_analysis_status"] if row else "IDLE",
            "last_analysis_time": row["last_analysis_time"] if row else None,
            "logs": self.logs.latest(),
        }

    def analyze(self, mode: str = "balanced") -> Dict[str, Any]:
        mode = mode.lower().strip()
        if mode not in VALID_MODES:
            raise ValueError("mode must be fast, balanced, or deep")
        self.buffer.refresh()
        provider_status = self.store.load_status().to_dict()
        frames = self._frames_for_mode(mode)
        quality = self.quality.validate(frames, provider_status)
        if not quality["ready"]:
            self.logs.log("Analysis", "Analysis blocked by candle quality/history.", "WARN")
            return {
                "version": "1.7.2",
                "engine_core_version": "V3",
                "mode": mode,
                "analysis_ready": False,
                "partial_analysis_available": quality["status"] != "ERROR",
                "error": "Full analysis disabled because candle quality or history is not ready.",
                "data_quality_status": quality,
                "workflow": self._blocked_workflow(quality),
            }
        cache_key = f"analysis:{mode}"
        dependency = self._dependency_for_mode(mode)
        if mode == "fast":
            cached = self.cache.get(cache_key, dependency)
            if cached:
                cached["cache_hit"] = True
                self.logs.log("Cache", "Fast analysis served from cache.")
                return cached
        analyzer = GoldAnalyzer()
        raw = analyzer.analyze(frames["5M"], frames, source=SOURCE_NAME, include_chart=True)
        result = self._power_result(raw, mode, quality)
        self.cache.set(cache_key, result, dependency)
        self._update_engine_status(result["final_decision"])
        self.logs.log("Analysis", f"{mode.title()} analysis completed: {result['final_decision']}.")
        return result

    def clear_cache(self) -> Dict[str, Any]:
        self.cache.clear()
        self.logs.log("Cache", "Analysis cache cleared.")
        return self.cache.status()

    def _frames_for_mode(self, mode: str) -> Dict[str, pd.DataFrame]:
        limits = {
            "fast": {"5M": 160, "15M": 140, "1H": 140, "4H": 80, "1D": 45},
            "balanced": {"5M": 600, "15M": 400, "1H": 300, "4H": 160, "1D": 80},
            "deep": {"5M": 1000, "15M": 800, "1H": 500, "4H": 300, "1D": 200},
        }[mode]
        return {tf: self.buffer.get(tf, limits[tf]) for tf in ["5M", "15M", "1H", "4H", "1D"]}

    def _dependency_for_mode(self, mode: str) -> Optional[str]:
        latest = self.store.latest_timestamps()
        if mode == "fast":
            return latest.get("5M")
        return "|".join(str(latest.get(tf)) for tf in ["5M", "15M", "1H", "4H", "1D"])

    def _power_result(self, raw: Dict[str, Any], mode: str, quality: Dict[str, Any]) -> Dict[str, Any]:
        signal = raw.get("signal", {})
        workflow = self._workflow(raw, quality)
        score, positives, penalties = self._score(raw, quality)
        final_decision = self._decision(raw, score)
        signal["score"] = score
        signal["score_result"] = self._score_result(score)
        signal["status"] = final_decision
        signal["final_action"] = "Wait. Do not force an entry." if final_decision.startswith("Wait") or final_decision == "No Trade" else final_decision
        raw.update({
            "version": "1.7.2",
            "engine_core_version": "V3",
            "mode": mode,
            "engine_mode": mode,
            "analysis_ready": True,
            "data_quality_status": quality,
            "workflow": workflow,
            "positive_score_reasons": positives,
            "penalty_score_reasons": penalties,
            "final_decision": final_decision,
            "signal": signal,
            "cache_hit": False,
        })
        return raw

    def _workflow(self, raw: Dict[str, Any], quality: Dict[str, Any]) -> List[Dict[str, Any]]:
        signal = raw.get("signal", {})
        zones = raw.get("zones", [])
        liquidity = raw.get("liquidity", {})
        stages = [
            WorkflowStage("Data Integrity", "READY" if quality["ready"] else "WEAK", 100 if quality["ready"] else 45, "Candle quality, freshness, history, and source safety checked.", "All", [], "Disable full analysis if quality is poor."),
            WorkflowStage("HTF Bias Analysis", "VALID" if raw.get("bias") in ["Bullish", "Bearish"] else "WEAK", 80 if raw.get("bias") in ["Bullish", "Bearish"] else 35, f"Bias is {raw.get('bias')}.", "1D/4H", [], "No trade if bias is unclear."),
            WorkflowStage("Liquidity Map", "VALID" if liquidity.get("recent_sweep") else "WAITING", 75 if liquidity.get("recent_sweep") else 40, liquidity.get("recent_sweep") or "Waiting for liquidity sweep.", "1H", [], "Setup waits without sweep."),
            WorkflowStage("CRT Range", "READY", 70, "CRT high, low, and equilibrium calculated.", "1H", [], "Range invalid if price breaks and holds outside."),
            WorkflowStage("POI Detection", "VALID" if signal.get("setup_type") not in [None, "None"] else "WAITING", 70 if signal.get("setup_type") not in [None, "None"] else 35, f"POI type: {signal.get('setup_type', 'None')}.", "15M", zones[-8:], "POI invalid after mitigation/failure."),
            WorkflowStage("Confirmation Check", "VALID" if signal.get("confirmation_status") == "Confirmed" else "WAITING", 80 if signal.get("confirmation_status") == "Confirmed" else 35, signal.get("confirmation_status", "Waiting"), "5M", [], "Wait for BOS/CHOCH confirmation."),
            WorkflowStage("Signal Score", "VALID" if signal.get("score", 0) >= 75 else "WEAK", signal.get("score", 0), signal.get("score_result", "No Trade"), "All", [], "Score penalized by missing conditions."),
            WorkflowStage("Final Decision", "VALID" if signal.get("status") in ["Valid Setup", "High Quality Setup"] else "WAITING", signal.get("score", 0), signal.get("status", "No Trade"), "All", [], "Never force a setup."),
        ]
        return [stage.to_dict() for stage in stages]

    def _score(self, raw: Dict[str, Any], quality: Dict[str, Any]) -> tuple[int, List[str], List[str]]:
        signal = raw.get("signal", {})
        warnings = signal.get("warnings", [])
        score = 0
        positives: List[str] = []
        penalties: List[str] = []
        if raw.get("bias") in ["Bullish", "Bearish"]:
            score += 20
            positives.append("HTF bias alignment +20")
        else:
            score -= 25
            penalties.append("HTF bias conflict -25")
        if not any("premium/discount" in w for w in warnings):
            score += 15
            positives.append("Correct premium/discount zone +15")
        else:
            score -= 15
            penalties.append("Wrong premium/discount zone -15")
        if raw.get("liquidity", {}).get("recent_sweep"):
            score += 20
            positives.append("Liquidity sweep detected +20")
        else:
            score -= 20
            penalties.append("No liquidity sweep -20")
        if signal.get("setup_type") not in [None, "None"]:
            score += 15
            positives.append("15M FVG or OB present +15")
        else:
            score -= 15
            penalties.append("No POI zone -15")
        if not any("OTE confluence is not active" in w for w in warnings):
            score += 10
            positives.append("OTE confluence +10")
        if signal.get("confirmation_status") == "Confirmed":
            score += 20
            positives.append("5M BOS/CHOCH confirmation +20")
        else:
            score -= 20
            penalties.append("No 5M confirmation -20")
        if quality["missing_history"]:
            score -= 40
            penalties.append("Not enough history -40")
        if quality["status"] == "WEAK":
            score -= 10
            penalties.append("High volatility/noise or quality warning -10")
        return max(0, min(100, score)), positives, penalties

    def _decision(self, raw: Dict[str, Any], score: int) -> str:
        signal = raw.get("signal", {})
        direction = "Buy" if raw.get("bias") == "Bullish" else "Sell" if raw.get("bias") == "Bearish" else ""
        if raw.get("bias") not in ["Bullish", "Bearish"]:
            return "No Trade"
        if not raw.get("liquidity", {}).get("recent_sweep"):
            return "Wait for Liquidity Sweep"
        if signal.get("setup_type") in [None, "None"]:
            return "Wait for Pullback to POI"
        if signal.get("confirmation_status") != "Confirmed":
            return "Wait for 5M Confirmation"
        if score >= 85:
            return f"High Quality {direction} Setup"
        if score >= 75:
            return f"Valid {direction} Setup"
        return "No Trade"

    def _score_result(self, score: int) -> str:
        if score >= 85:
            return "Valid High Quality Setup"
        if score >= 75:
            return "Waiting Confirmation"
        if score >= 60:
            return "Weak Setup"
        return "No Trade"

    def _blocked_workflow(self, quality: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            WorkflowStage("Data Integrity", "ERROR" if quality["status"] == "ERROR" else "WEAK", 0, "; ".join(quality["errors"] or quality["warnings"] or ["Not enough candle history."]), "All", [], "Full analysis disabled.").to_dict()
        ]

    def _update_engine_status(self, status: str) -> None:
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO engine_status (id, mode, current_analysis_status, last_analysis_time, updated_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    current_analysis_status=excluded.current_analysis_status,
                    last_analysis_time=excluded.last_analysis_time,
                    updated_at=excluded.updated_at
                """,
                (self.get_mode(), status, pd.Timestamp.now(tz="UTC").isoformat(), pd.Timestamp.now(tz="UTC").isoformat()),
            )
