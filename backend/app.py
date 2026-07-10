from __future__ import annotations

import os
from tempfile import NamedTemporaryFile
from typing import Any, Dict, Optional

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from engine.backtester import run_simple_backtest
from engine.data_integrity import DataIntegrityEngine
from engine.data_mode_lock import DataModeLockService
from engine.engine_core import EngineCore
from engine.institutional_analysis import InstitutionalAnalysisEngineV4
from engine.pro_analysis import ProAnalysisEngineV3
from engine.real_data_hub import CSVImportProService
from engine.xauusd_provider import (
    ARCHIVED_STALE_SOURCE,
    CandleGapDetector,
    CandleEngineQualityValidator,
    CandleHealthService,
    CandleHistorySeeder,
    CSVBacktestProvider,
    CSV_SOURCE,
    DataGapDiagnosisService,
    GOLD_API_COM_PROVIDER_NAME,
    GOLD_API_IO_PROVIDER_NAME,
    LIVE_BUILDER_SOURCE,
    LIVE_SOURCE,
    LiveCandleBuilderService,
    MIN_ANALYSIS_CANDLES,
    ProviderSettings,
    REAL_CSV_HISTORY_SOURCE,
    RecentHistoryResolver,
    RecentHistorySyncService,
    RealisticTestHistoryGeneratorV2,
    RECENT_CSV_SOURCE,
    REAL_RECENT_SOURCES,
    SQLiteCandleStore,
    SUPPORTED_TIMEFRAMES,
    TEST_HISTORY_LIVE_ANCHORED_SOURCE,
    TEST_HISTORY_SOURCES,
    TEST_HISTORY_SOURCE,
    TestHistoryGenerator,
    TwelveDataHistoryService,
    TWELVE_DATA_HISTORY_SOURCE,
    USER_RECENT_CSV_SOURCE,
    WARMUP_SOURCE,
    PRELOADED_SOURCE,
    validate_analysis_readiness,
    normalize_timeframe,
)

APP_VERSION = "1.8.3"
APP_VERSION_LABEL = "V1.8.3"
APP_DESCRIPTION = "Candle History Alignment Lock"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SAMPLE_CSV = os.path.join(DATA_DIR, "sample_xauusd_m5.csv")
HISTORY_DIR = os.path.join(DATA_DIR, "xauusd_history")
RECENT_HISTORY_DIR = os.path.join(DATA_DIR, "xauusd_recent_history")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
UPLOAD_CSV = os.path.join(UPLOAD_DIR, "xauusd_latest_upload.csv")
SETTINGS_FILE = os.path.join(DATA_DIR, "provider_settings.json")
SQLITE_DB = os.path.join(DATA_DIR, "sh_gold_analyzer.sqlite")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RECENT_HISTORY_DIR, exist_ok=True)

app = FastAPI(title="SH Gold Analyzer API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings = ProviderSettings(SETTINGS_FILE)
candle_store = SQLiteCandleStore(SQLITE_DB)
history_seeder = CandleHistorySeeder(candle_store, HISTORY_DIR)
gap_detector = CandleGapDetector(candle_store)
live_builder = LiveCandleBuilderService(settings, candle_store)
candle_health_service = CandleHealthService(candle_store, live_builder.candle_builder)
candle_quality_validator = CandleEngineQualityValidator(candle_store)
csv_provider = CSVBacktestProvider(SAMPLE_CSV, UPLOAD_CSV)
engine_core = EngineCore(candle_store)
data_integrity_engine = DataIntegrityEngine(candle_store)
test_history_generator = TestHistoryGenerator(candle_store)
test_history_generator_v2 = RealisticTestHistoryGeneratorV2(candle_store)
csv_import_pro = CSVImportProService(candle_store)
recent_history_sync = RecentHistorySyncService(candle_store, RECENT_HISTORY_DIR)
recent_history_resolver = RecentHistoryResolver(candle_store)
gap_diagnosis_service = DataGapDiagnosisService(candle_store)
data_mode_lock = DataModeLockService(candle_store, settings)
twelve_data_history = TwelveDataHistoryService(settings, candle_store)
pro_analysis_engine = ProAnalysisEngineV3(candle_store, engine_core.cache)
institutional_engine_v4 = InstitutionalAnalysisEngineV4(candle_store, engine_core.cache)
startup_seed_result = history_seeder.seed_if_needed()
startup_live_status = live_builder.start()


class ProviderSettingsPayload(BaseModel):
    goldapi_key: Optional[str] = None
    goldapi_io_key: Optional[str] = None
    twelve_data_api_key: Optional[str] = None


class EngineModePayload(BaseModel):
    mode: str


class TestModePayload(BaseModel):
    enabled: bool


class FixGapPayload(BaseModel):
    mode: str


class DataModePayload(BaseModel):
    mode: str
    show_stale_history: Optional[bool] = None


class ResetDatabasePayload(BaseModel):
    confirm: bool = False


@app.get("/")
def root():
    return {
        "name": f"SH Gold Analyzer {APP_VERSION_LABEL} - {APP_DESCRIPTION}",
        "description": APP_DESCRIPTION,
        "symbol": "XAUUSD",
        "version": APP_VERSION,
        "status": "online",
        "timeframes": SUPPORTED_TIMEFRAMES,
        "database_path": SQLITE_DB,
        "providers": {
            "primary": GOLD_API_COM_PROVIDER_NAME,
            "primary_api_key_required": False,
            "optional": GOLD_API_IO_PROVIDER_NAME,
            "optional_api_key_required": True,
        },
        "live_data_rule": "Data mode is locked by source truth table. TradingView Lightweight Charts is display only.",
        "data_mode_lock": _locked_data_mode(),
        "data_readiness": gap_detector.readiness(),
        "startup_seed_result": startup_seed_result,
        "startup_live_status": startup_live_status,
        "endpoints": [
            "GET /api/health",
            "GET /api/debug",
            "GET /api/routes",
            "GET /api/xauusd/live-price",
            "GET /api/xauusd/candles?timeframe=15M&limit=300",
            "GET /api/xauusd/chart-data?timeframe=15M&limit=300",
            "GET /api/xauusd/candle-health?timeframe=15M",
            "GET /api/xauusd/history-alignment?timeframe=15M",
            "GET /api/xauusd/data-integrity",
            "GET /api/xauusd/overlays?timeframe=15M",
            "GET /api/xauusd/overlay-status?timeframe=15M",
            "GET /api/xauusd/indicator-panels?timeframe=15M",
            "GET /api/xauusd/chart-indicators?timeframe=15M&limit=300",
            "GET /api/xauusd/data-readiness",
            "GET /api/xauusd/data-mode",
            "GET /api/xauusd/data-hub",
            "GET /api/xauusd/backend-status",
            "GET /api/xauusd/analysis-state",
            "GET /api/xauusd/pro-analysis",
            "GET /api/xauusd/pro-analysis-v4",
            "GET /api/xauusd/analysis-explanation",
            "GET /api/xauusd/pro-analysis-cache",
            "GET /api/xauusd/data-state",
            "GET /api/xauusd/gap-diagnosis",
            "GET /api/xauusd/readiness",
            "GET /api/xauusd/debug-data",
            "GET /api/xauusd/indicator-panels-v2?timeframe=15M",
            "GET /api/xauusd/indicator-panels-v3?timeframe=15M",
            "GET /api/xauusd/overlays-v2?timeframe=15M",
            "GET /api/xauusd/export-current-candles",
            "POST /api/xauusd/seed-history",
            "POST /api/xauusd/reload-history",
            "POST /api/xauusd/download-free-history",
            "GET /api/xauusd/provider-status",
            "POST /api/xauusd/start-live-builder",
            "POST /api/xauusd/stop-live-builder",
            "POST /api/xauusd/analyze-live",
            "POST /api/xauusd/upload-csv",
            "GET /api/xauusd/engine-status",
            "POST /api/xauusd/set-engine-mode",
            "POST /api/xauusd/analyze-fast",
            "POST /api/xauusd/analyze-balanced",
            "POST /api/xauusd/analyze-deep",
            "POST /api/xauusd/analyze-pro",
            "GET /api/xauusd/analysis-cache",
            "POST /api/xauusd/clear-cache",
            "POST /api/xauusd/clear-analysis-cache",
            "GET /api/xauusd/engine-logs",
            "POST /api/xauusd/clear-logs",
            "POST /api/xauusd/backtest-csv",
            "POST /api/xauusd/rebuild-candles",
            "POST /api/xauusd/rebuild-candle-engine",
            "POST /api/xauusd/validate-candles",
            "POST /api/xauusd/clear-invalid-candles",
            "POST /api/xauusd/import-recent-history",
            "POST /api/xauusd/import-real-recent-history",
            "POST /api/xauusd/generate-test-history",
            "POST /api/xauusd/generate-test-history-v2",
            "POST /api/xauusd/generate-live-anchored-test-history",
            "POST /api/xauusd/clear-test-history",
            "POST /api/xauusd/archive-stale-history",
            "POST /api/xauusd/fix-gap",
            "POST /api/xauusd/set-data-mode",
            "POST /api/xauusd/one-click-data-setup",
            "POST /api/xauusd/one-click-warmup",
            "POST /api/xauusd/smart-setup",
            "POST /api/xauusd/real-mode-wizard",
            "POST /api/xauusd/import-real-history",
            "POST /api/xauusd/analyze-v4",
            "POST /api/xauusd/reset-database",
            "POST /api/xauusd/toggle-test-mode",
        ],
    }


@app.on_event("startup")
def startup_log():
    print(f"SH Gold Analyzer {APP_VERSION_LABEL} startup")
    print(f"SQLite database path: {SQLITE_DB}")
    print(f"History folder path: {HISTORY_DIR}")
    print(f"Recent history folder path: {RECENT_HISTORY_DIR}")
    print("Registered routes:")
    for route in app.routes:
        methods = ",".join(sorted(getattr(route, "methods", []) or []))
        path = getattr(route, "path", "")
        if path:
            print(f"  {methods} {path}")


@app.get("/api/health")
def api_health():
    info = candle_store.database_info()
    provider_status = live_builder.status()
    locked = _locked_data_mode()
    return {
        "status": "OK",
        "app": "SH Gold Analyzer",
        "version": APP_VERSION_LABEL,
        "database_connected": bool(info.get("database_exists") and info.get("candle_tables_created")),
        "provider_status": provider_status.get("status"),
        "backend_status": "ONLINE",
        "data_mode": locked.get("locked_mode"),
        "data_mode_label": locked.get("data_mode_label"),
        "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
    }


@app.get("/api/routes")
def api_routes():
    routes = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api"):
            continue
        methods = sorted(method for method in (getattr(route, "methods", set()) or set()) if method not in {"HEAD", "OPTIONS"})
        if not methods:
            continue
        routes.append({"path": path, "methods": methods, "name": getattr(route, "name", "")})
    return {"app": "SH Gold Analyzer", "version": APP_VERSION_LABEL, "routes": routes, "count": len(routes)}


@app.get("/api/debug")
def api_debug():
    return {
        "health": api_health(),
        "data_hub": xauusd_data_hub(),
        "data_mode": xauusd_data_mode(),
        "chart_data": xauusd_chart_data("15M", 10),
    }


def _locked_data_mode() -> dict:
    integrity = data_integrity_engine.data_integrity("15M", 300)
    diagnosis = gap_diagnosis_service.diagnose("15M")
    return data_mode_lock.locked_mode(integrity=integrity, diagnosis=diagnosis, backend_online=True)


@app.get("/api/xauusd/backend-status")
def xauusd_backend_status():
    health = api_health()
    locked = _locked_data_mode()
    return {
        "backend_status": "ONLINE",
        "health": health,
        "provider_status": live_builder.status(),
        "data_mode_lock": locked,
        "actions_enabled": {
            "refresh": locked.get("can_refresh"),
            "smart_setup": locked.get("can_smart_setup"),
            "analyze": locked.get("can_analyze"),
        },
    }


@app.get("/api/xauusd/analysis-state")
def xauusd_analysis_state():
    locked = _locked_data_mode()
    return {
        "symbol": "XAUUSD",
        "version": APP_VERSION_LABEL,
        "analysis_state": locked.get("analysis_state"),
        "data_mode": locked.get("locked_mode"),
        "data_mode_label": locked.get("data_mode_label"),
        "analysis_ready": locked.get("analysis_ready"),
        "full_analysis_ready": locked.get("full_analysis_ready"),
        "real_signal_allowed": locked.get("real_signal_allowed"),
        "can_analyze": locked.get("can_analyze"),
        "lock_reason": locked.get("lock_reason"),
    }


@app.get("/api/xauusd/live-price")
def xauusd_live_price():
    return live_builder.live_price()


@app.get("/api/xauusd/candles")
def xauusd_candles(timeframe: str = Query("15M"), limit: int = Query(300, ge=1, le=5000)):
    try:
        return candle_store.get_candles_payload(normalize_timeframe(timeframe), limit)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/chart-indicators")
def xauusd_chart_indicators(timeframe: str = Query("15M"), limit: int = Query(300, ge=30, le=1000)):
    try:
        tf = normalize_timeframe(timeframe)
        overlays = data_integrity_engine.overlays(tf, limit)
        indicators = data_integrity_engine.indicator_panels(tf, limit)
        return {
            "symbol": "XAUUSD",
            "timeframe": tf,
            "status": overlays["status"],
            "chart_overlays": overlays["chart_overlays"],
            "indicator_panels": indicators["indicator_panels"],
            "analysis_summary": _analysis_summary_from_overlays(overlays, indicators),
            "data_integrity": overlays["data_integrity"],
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/data-integrity")
def xauusd_data_integrity(timeframe: str = Query("15M"), limit: int = Query(300, ge=30, le=5000)):
    try:
        return data_integrity_engine.data_integrity(normalize_timeframe(timeframe), limit)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/chart-data")
def xauusd_chart_data(timeframe: str = Query("15M"), limit: int = Query(500, ge=1, le=5000), include_stale: bool = Query(False)):
    try:
        tf = normalize_timeframe(timeframe)
        payload = data_integrity_engine.chart_data(tf, limit)
        candle_health = candle_health_service.health(tf, min(max(limit, 100), 2000))
        alignment = payload.get("alignment") or data_integrity_engine.history_alignment(tf, min(max(limit, 100), 2000))
        if alignment.get("alignment_status") == "TEST_MODE":
            candle_health["health_status"] = "TEST_MODE"
            candle_health["warnings"] = list(dict.fromkeys((candle_health.get("warnings") or []) + [alignment.get("warning_message") or "TEST MODE: generated candle history is not real market history."]))
        elif not alignment.get("healthy") and alignment.get("alignment_status") not in {"LIVE_ONLY"}:
            candle_health["health_status"] = alignment.get("alignment_status") or "INVALID"
            candle_health["warnings"] = list(dict.fromkeys((candle_health.get("warnings") or []) + [alignment.get("warning_message") or "History candles are not aligned with current live price."]))
        candle_health["alignment"] = alignment
        candle_health["analysis_allowed"] = alignment.get("analysis_allowed")
        payload.pop("frames", None)
        if not include_stale:
            payload.setdefault("segments", {})["stale"] = []
            if payload.get("archived_stale_history_hidden"):
                payload["gap_marker"] = None
        overlay_payload = data_integrity_engine.overlays(tf, min(limit, 1000))
        payload["valid_overlays"] = {
            key: item for key, item in overlay_payload.get("overlays", {}).items()
            if item.get("ready") and item.get("price") is not None
        }
        payload["overlay_status"] = overlay_payload.get("overlay_status", {})
        payload["overlays"] = overlay_payload.get("overlays", {})
        payload["data_readiness"] = xauusd_data_readiness()
        payload["data_state"] = xauusd_data_state()
        payload["data_mode_lock"] = _locked_data_mode()
        payload["gap_diagnosis"] = xauusd_gap_diagnosis(tf)
        payload["source_labels"] = payload.get("data_integrity", {}).get("source_labels")
        payload["candle_health"] = candle_health
        payload["completed_count"] = candle_health.get("completed_count")
        payload["partial_count"] = candle_health.get("partial_count")
        payload["health_status"] = candle_health.get("health_status")
        payload["latest_price"] = alignment.get("latest_live_price") or payload.get("data_integrity", {}).get("latest_live_price")
        payload["latest_live_price"] = alignment.get("latest_live_price")
        payload["latest_history_close"] = alignment.get("latest_history_close")
        payload["alignment_status"] = alignment.get("alignment_status")
        payload["analysis_allowed"] = alignment.get("analysis_allowed")
        payload["warning_message"] = alignment.get("warning_message") if not alignment.get("healthy") else None
        payload["latest_partial_candle"] = candle_health.get("latest_partial_candle")
        payload["warnings"] = list(dict.fromkeys((payload.get("data_integrity", {}).get("warnings") or []) + (candle_health.get("warnings") or [])))
        return payload
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/candle-health")
def xauusd_candle_health(timeframe: str = Query("15M"), limit: int = Query(1000, ge=1, le=5000)):
    try:
        tf = normalize_timeframe(timeframe)
        health = candle_health_service.health(tf, limit)
        alignment = data_integrity_engine.history_alignment(tf, limit)
        if alignment.get("alignment_status") == "TEST_MODE":
            health["health_status"] = "TEST_MODE"
            health["warnings"] = list(dict.fromkeys((health.get("warnings") or []) + [alignment.get("warning_message") or "TEST MODE: generated candle history is not real market history."]))
        elif not alignment.get("healthy") and alignment.get("alignment_status") not in {"LIVE_ONLY"}:
            health["health_status"] = alignment.get("alignment_status") or "INVALID"
            health["warnings"] = list(dict.fromkeys((health.get("warnings") or []) + [alignment.get("warning_message") or "History candles are not aligned with current live price."]))
        health["alignment"] = alignment
        health["analysis_allowed"] = alignment.get("analysis_allowed")
        return health
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/history-alignment")
def xauusd_history_alignment(timeframe: str = Query("15M"), limit: int = Query(1000, ge=1, le=5000)):
    try:
        return data_integrity_engine.history_alignment(normalize_timeframe(timeframe), limit)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/xauusd/rebuild-candle-engine")
def xauusd_rebuild_candle_engine():
    try:
        result = live_builder.candle_builder.rebuild_from_ticks()
        return result | {
            "candle_health": {tf: candle_health_service.health(tf, 1000) for tf in SUPPORTED_TIMEFRAMES},
            "data_readiness": xauusd_data_readiness(),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/xauusd/validate-candles")
def xauusd_validate_candles(timeframe: Optional[str] = Query(None), limit: int = Query(1000, ge=1, le=5000)):
    try:
        return candle_quality_validator.validate(timeframe, limit)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/overlays")
def xauusd_overlays(timeframe: str = Query("15M"), limit: int = Query(300, ge=30, le=1000)):
    try:
        return data_integrity_engine.overlays(normalize_timeframe(timeframe), limit)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/overlays-v2")
def xauusd_overlays_v2(timeframe: str = Query("15M"), limit: int = Query(300, ge=30, le=1000)):
    try:
        tf = normalize_timeframe(timeframe)
        base = data_integrity_engine.overlays(tf, limit)
        analysis = institutional_engine_v4.analyze(_locked_data_mode(), "fast")
        levels = dict(base.get("overlays", {}))
        levels.update(_institutional_overlay_levels(analysis))
        base["version"] = "V2"
        base["overlays"] = levels
        base["chart_overlays"] = {
            key: item["price"] for key, item in levels.items()
            if item.get("ready") and item.get("price") is not None
        }
        base["overlay_status"] = _overlay_status(levels)
        base["analysis_decision"] = analysis.get("final_decision")
        return base
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/overlay-status")
def xauusd_overlay_status(timeframe: str = Query("15M"), limit: int = Query(300, ge=30, le=1000)):
    try:
        overlays = data_integrity_engine.overlays(normalize_timeframe(timeframe), limit)
        return {
            "symbol": "XAUUSD",
            "timeframe": overlays["timeframe"],
            "status": overlays["status"],
            "overlay_status": overlays.get("overlay_status", {}),
            "overlays": overlays.get("overlays", {}),
            "data_integrity": overlays.get("data_integrity", {}),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/indicator-panels")
def xauusd_indicator_panels(timeframe: str = Query("15M"), limit: int = Query(300, ge=30, le=1000)):
    try:
        return data_integrity_engine.indicator_panels(normalize_timeframe(timeframe), limit)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/indicator-panels-v2")
def xauusd_indicator_panels_v2(timeframe: str = Query("15M"), limit: int = Query(300, ge=30, le=1000)):
    try:
        locked = _locked_data_mode()
        panels = data_integrity_engine.indicator_panels(normalize_timeframe(timeframe), limit)
        base = panels.get("indicator_panels", {})
        quality = []
        for idx, item in enumerate((base.get("boys_selling") or [])[-80:]):
            bullish = max(0, float(item.get("value", 0)))
            bearish = abs(min(0, float((base.get("bearishness") or [{}])[-80:][idx].get("value", 0) if idx < len((base.get("bearishness") or [])[-80:]) else 0)))
            quality.append({
                "time": item.get("time"),
                "value": round(max(0, min(100, bullish * 0.35 + bearish * 0.25)), 3),
                "color": "yellow" if locked.get("locked_mode") == "TEST_MODE" else "green",
            })
        panels["version"] = "V2"
        panels["data_mode_lock"] = locked
        panels["badge"] = "TEST DATA" if locked.get("locked_mode") == "TEST_MODE" else "REAL DATA" if locked.get("locked_mode") == "REAL_MODE" else locked.get("data_mode_label")
        panels["indicator_panels"] = {
            "market_pressure": base.get("boys_selling", []),
            "balance": base.get("bearishness", []),
            "setup_quality": quality,
            "market_pressure_score": base.get("market_pressure_score", {"bullish": 0, "bearish": 0, "neutral": 100}),
            "boys_selling": base.get("boys_selling", []),
            "bearishness": base.get("bearishness", []),
        }
        if locked.get("locked_mode") == "LIVE_ONLY_MODE":
            panels["status"] = "WAITING_FOR_HISTORY"
            panels["message"] = "Live Only / Not enough candle history"
        elif locked.get("locked_mode") == "GAP_WARNING_MODE":
            panels["status"] = "FIX_GAP_REQUIRED"
            panels["message"] = "Fix gap required"
        return panels
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/indicator-panels-v3")
def xauusd_indicator_panels_v3(timeframe: str = Query("15M"), limit: int = Query(300, ge=30, le=1000)):
    try:
        panels = xauusd_indicator_panels_v2(timeframe, limit)
        if isinstance(panels, JSONResponse):
            return panels
        base = panels.get("indicator_panels", {})
        locked = panels.get("data_mode_lock") or _locked_data_mode()
        panels["version"] = "V3"
        panels["indicator_panels"] = {
            "market_pressure": base.get("market_pressure") or base.get("boys_selling", []),
            "liquidity_pressure": base.get("balance") or base.get("bearishness", []),
            "setup_quality": base.get("setup_quality", []),
            "market_pressure_score": base.get("market_pressure_score", {"bullish": 0, "bearish": 0, "neutral": 100}),
        }
        if locked.get("locked_mode") == "TEST_MODE":
            panels["badge"] = "TEST DATA"
        elif locked.get("locked_mode") == "LIVE_ONLY_MODE":
            panels["message"] = "Waiting for candle history"
            panels["badge"] = "LIVE ONLY"
        elif locked.get("locked_mode") == "REAL_MODE":
            panels["badge"] = "REAL DATA"
        return panels
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/data-readiness")
def xauusd_data_readiness():
    readiness = gap_detector.readiness()
    integrity = data_integrity_engine.data_integrity("15M", 300)
    mode = recent_history_resolver.resolve(integrity)
    selected_mode = settings.data_mode()
    diagnosis = gap_diagnosis_service.diagnose("15M")
    test_data_present = any(any(candle_store.has_source(timeframe, source) for source in TEST_HISTORY_SOURCES) for timeframe in ["5M", "15M", "1H", "4H", "1D"])
    if test_data_present:
        readiness["history_status"] = "TEST_DATA_MODE"
        readiness["data_status"] = "TEST_DATA_MODE"
        readiness["analysis_state"] = "Test Mode Analysis" if settings.test_mode_enabled() else "Chart Ready - Test Mode"
        readiness["test_mode_enabled"] = settings.test_mode_enabled()
        readiness["test_data_warning"] = "Test history is for development only."
        if not settings.test_mode_enabled():
            readiness["analysis_ready"] = False
            readiness["full_analysis_ready"] = False
            readiness["partial_analysis_only"] = True
        else:
            readiness["analysis_ready"] = True
            readiness["full_analysis_ready"] = True
            readiness["partial_analysis_only"] = False
    if integrity.get("gap_detected") and not test_data_present:
        readiness["analysis_ready"] = False
        readiness["full_analysis_ready"] = False
        readiness["partial_analysis_only"] = True
        readiness["analysis_state"] = "Waiting for Recent History"
        readiness["history_status"] = "READY_WITH_GAP_WARNING"
        readiness["gap_warning"] = integrity.get("gap_warning")
        readiness["data_status"] = "READY_WITH_GAP_WARNING"
    elif not readiness.get("data_status"):
        if not readiness.get("chart_ready"):
            readiness["data_status"] = "NO_HISTORY"
        elif integrity.get("data_status") == "RECENT_HISTORY_READY":
            readiness["data_status"] = "RECENT_HISTORY_READY"
        elif readiness.get("full_analysis_ready"):
            readiness["data_status"] = "FULL_ANALYSIS_READY"
        else:
            readiness["data_status"] = integrity.get("data_status") or readiness.get("history_status")
    readiness["data_mode"] = mode.get("data_mode")
    readiness["data_mode_label"] = mode.get("data_mode_label")
    readiness["data_mode_description"] = mode.get("description")
    readiness["action_required"] = mode.get("action_required")
    readiness["action_choices"] = mode.get("action_choices")
    readiness["analysis_state"] = mode.get("analysis_state") or readiness.get("analysis_state")
    if mode.get("data_mode") == "TEST" and settings.test_mode_enabled():
        readiness["analysis_state"] = "Test Mode Analysis"
    if selected_mode == "LIVE_ONLY":
        mode["data_mode"] = "LIVE_ONLY"
        mode["data_mode_label"] = "LIVE ONLY"
        mode["description"] = "Only live price, not enough candles"
        mode["analysis_state"] = "Live Only"
        mode["full_analysis_ready"] = False
        mode["analysis_ready"] = False
    if mode.get("data_mode") == "LIVE_ONLY":
        readiness["history_status"] = "LIVE_ONLY"
        readiness["data_status"] = "LIVE_ONLY"
        readiness["analysis_ready"] = False
        readiness["full_analysis_ready"] = False
        readiness["analysis_state"] = "Live Only"
    if mode.get("data_mode") == "NO_DATA":
        readiness["history_status"] = "NO_HISTORY"
        readiness["data_status"] = "NO_DATA"
    readiness["gap_diagnosis"] = diagnosis
    readiness["selected_data_mode"] = selected_mode
    readiness["data_integrity"] = integrity
    locked = data_mode_lock.locked_mode(integrity=integrity, diagnosis=diagnosis, backend_online=True)
    readiness["locked_mode"] = locked["locked_mode"]
    readiness["data_mode"] = locked["locked_mode"]
    readiness["data_mode_label"] = locked["data_mode_label"]
    readiness["data_mode_description"] = locked["description"]
    readiness["analysis_state"] = locked["analysis_state"]
    readiness["analysis_ready"] = locked["analysis_ready"]
    readiness["full_analysis_ready"] = locked["full_analysis_ready"]
    readiness["real_signal_allowed"] = locked["real_signal_allowed"]
    readiness["chart_ready"] = locked["chart_ready"]
    readiness["can_analyze"] = locked["can_analyze"]
    readiness["can_refresh"] = locked["can_refresh"]
    readiness["can_smart_setup"] = locked["can_smart_setup"]
    readiness["candle_source"] = locked["candle_source"]
    readiness["data_mode_lock"] = locked
    return readiness


@app.get("/api/xauusd/data-mode")
def xauusd_data_mode():
    return _locked_data_mode()


@app.get("/api/xauusd/data-hub")
def xauusd_data_hub():
    return _data_hub_snapshot()


@app.get("/api/xauusd/gap-diagnosis")
def xauusd_gap_diagnosis(timeframe: str = Query("15M")):
    try:
        return gap_diagnosis_service.diagnose(normalize_timeframe(timeframe))
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/data-state")
def xauusd_data_state():
    locked = _locked_data_mode()
    return {
        "symbol": "XAUUSD",
        "data_state": locked["locked_mode"],
        "analysis_state": locked["analysis_state"],
        "data_mode": locked["locked_mode"],
        "data_mode_label": locked["data_mode_label"],
        "chart_ready": locked.get("chart_ready"),
        "analysis_ready": locked.get("analysis_ready"),
        "full_analysis_ready": locked.get("full_analysis_ready"),
        "real_signal_allowed": locked.get("real_signal_allowed"),
        "gap_diagnosis": locked.get("gap_diagnosis"),
        "warnings": locked.get("warnings", []),
        "action_choices": [],
        "data_mode_lock": locked,
    }


@app.get("/api/xauusd/readiness")
def xauusd_readiness():
    readiness = xauusd_data_readiness()
    return {
        "symbol": "XAUUSD",
        "chart_ready": readiness.get("chart_ready"),
        "analysis_ready": readiness.get("analysis_ready"),
        "full_analysis_ready": readiness.get("full_analysis_ready"),
        "data_mode": readiness.get("data_mode"),
        "data_mode_label": readiness.get("data_mode_label"),
        "analysis_state": readiness.get("analysis_state"),
        "warnings": readiness.get("warnings", []),
        "action_required": readiness.get("action_required"),
        "action_choices": readiness.get("action_choices", []),
        "candle_counts": readiness.get("candle_counts", {}),
        "missing_history": readiness.get("missing_history", []),
    }


@app.get("/api/xauusd/debug-data")
def xauusd_debug_data():
    info = candle_store.database_info()
    provider_status = live_builder.status()
    history_files = history_seeder.history_files_found()
    errors = list(info.get("errors", []))
    if not any(history_files.values()):
        errors.append("Preloaded history files are missing. Please add CSV files to backend/data/xauusd_history.")
    if not info["database_exists"]:
        errors.append(f"SQLite database not found at {info['database_path']}.")
    return {
        "backend_connected": True,
        "app_version": APP_VERSION_LABEL,
        "database_path": info["database_path"],
        "database_exists": info["database_exists"],
        "table_names": info["table_names"],
        "candle_counts": info["candle_counts"],
        "provider_status": provider_status,
        "provider_name": provider_status.get("provider_name"),
        "last_error": provider_status.get("last_error"),
        "latest_price": provider_status.get("latest_price"),
        "latest_tick_time": info["latest_tick_time"],
        "latest_candle_time": info["latest_candle_time"],
        "history_folder_exists": os.path.isdir(HISTORY_DIR),
        "recent_history_folder_exists": os.path.isdir(RECENT_HISTORY_DIR),
        "history_files_found": history_files,
        "recent_history_files_found": recent_history_sync.recent_files_found(),
        "data_mode": recent_history_resolver.resolve(data_integrity_engine.data_integrity("15M", 300)),
        "setup_checklist": _setup_checklist(info, provider_status, history_files),
        "available_routes": api_routes()["routes"],
        "errors": errors,
    }


@app.get("/api/xauusd/provider-status")
def xauusd_provider_status():
    return live_builder.status() | {"settings": settings.masked_status(), "minimum_required": MIN_ANALYSIS_CANDLES, "data_readiness": xauusd_data_readiness()}


@app.post("/api/xauusd/provider-settings")
def xauusd_provider_settings(payload: ProviderSettingsPayload):
    masked = settings.update(payload.model_dump(exclude_none=True))
    return {"ok": True, "settings": masked, "message": "GoldAPI key saved in backend local settings."}


@app.post("/api/xauusd/start-live-builder")
def xauusd_start_live_builder():
    result = live_builder.start()
    if result.get("last_error") and result.get("status") in ["CONNECTION_FAILED", "RATE_LIMIT", "NO_PRICE", "RETRYING"]:
        result["error"] = result["last_error"]
    return result


@app.post("/api/xauusd/stop-live-builder")
def xauusd_stop_live_builder():
    return live_builder.stop()


@app.post("/api/xauusd/seed-history")
def xauusd_seed_history():
    result = history_seeder.seed_if_needed()
    history_files = history_seeder.history_files_found()
    if not any(history_files.values()):
        result["status"] = "NO_HISTORY_FILES"
        result["message"] = "No history files found in backend/data/xauusd_history."
    elif result.get("status") == "READY":
        result["status"] = "SEEDED"
    return result | {"data_readiness": gap_detector.readiness()}


@app.post("/api/xauusd/reload-history")
def xauusd_reload_history():
    return history_seeder.reload_safely() | {"data_readiness": gap_detector.readiness()}


@app.post("/api/xauusd/generate-test-history")
def xauusd_generate_test_history():
    return test_history_generator_v2.generate_live_anchored() | {
        "warning": "Test history is for development only.",
        "test_mode_enabled": settings.test_mode_enabled(),
        "data_readiness": xauusd_data_readiness(),
        "data_state": xauusd_data_state(),
        "data_hub": _data_hub_snapshot(),
    }


@app.post("/api/xauusd/generate-test-history-v2")
def xauusd_generate_test_history_v2():
    try:
        result = test_history_generator_v2.generate_live_anchored()
        settings.set_data_mode("TEST")
        settings.set_test_mode(True)
        return result | {
            "warning": "TEST DATA is for development only. It is never real market history.",
            "data_readiness": xauusd_data_readiness(),
            "data_mode": xauusd_data_mode(),
            "data_state": xauusd_data_state(),
            "data_hub": _data_hub_snapshot(),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/xauusd/generate-live-anchored-test-history")
def xauusd_generate_live_anchored_test_history():
    try:
        result = test_history_generator_v2.generate_live_anchored()
        settings.set_data_mode("TEST")
        settings.set_test_mode(True)
        return result | {
            "warning": "Test history is for development only. It is not real market history.",
            "data_readiness": xauusd_data_readiness(),
            "data_state": xauusd_data_state(),
            "gap_diagnosis": xauusd_gap_diagnosis("15M"),
            "data_hub": _data_hub_snapshot(),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/xauusd/clear-test-history")
def xauusd_clear_test_history():
    result = test_history_generator.clear()
    return result | {"data_readiness": xauusd_data_readiness(), "data_mode": xauusd_data_mode()}


@app.post("/api/xauusd/archive-stale-history")
def xauusd_archive_stale_history():
    diagnosis = gap_diagnosis_service.diagnose("15M")
    if diagnosis.get("status") == "READY":
        return {"ok": True, "status": "NO_ARCHIVE_NEEDED", "gap_diagnosis": diagnosis, "archived": {}}
    archived = candle_store.archive_sources({"PRELOADED_HISTORY", "PROVIDER_WARMUP"})
    return {
        "ok": True,
        "status": "STALE_HISTORY_ARCHIVED",
        "source": ARCHIVED_STALE_SOURCE,
        "archived": archived,
        "archived_total": sum(archived.values()),
        "gap_diagnosis": gap_diagnosis_service.diagnose("15M"),
        "data_state": xauusd_data_state(),
    }


@app.post("/api/xauusd/set-data-mode")
def xauusd_set_data_mode(payload: DataModePayload):
    mode = payload.mode.strip().upper()
    mode_map = {
        "REAL_MODE": "REAL",
        "TEST_MODE": "TEST",
        "LIVE_ONLY_MODE": "LIVE_ONLY",
        "GAP_WARNING_MODE": "GAP_WARNING",
        "NO_DATA_MODE": "AUTO",
        "BACKEND_OFFLINE_MODE": "AUTO",
    }
    selected = mode_map.get(mode, mode)
    if selected not in {"AUTO", "REAL", "TEST", "LIVE_ONLY", "GAP_WARNING"}:
        return JSONResponse(status_code=400, content={"error": "mode must be AUTO, REAL_MODE, TEST_MODE, LIVE_ONLY_MODE, or GAP_WARNING_MODE"})
    settings.set_data_mode(selected)
    if payload.show_stale_history is not None:
        settings.set_show_stale_history(payload.show_stale_history)
    return {
        "ok": True,
        "settings": settings.masked_status(),
        "data_mode": xauusd_data_mode(),
        "data_state": xauusd_data_state(),
    }


@app.post("/api/xauusd/fix-gap")
def xauusd_fix_gap(payload: FixGapPayload):
    mode = payload.mode.strip().upper()
    if mode == "TEST_HISTORY":
        return xauusd_generate_live_anchored_test_history()
    if mode == "LIVE_ONLY":
        settings.set_data_mode("LIVE_ONLY")
        live_status = live_builder.start()
        live_builder.candle_builder.aggregate_all()
        return {
            "ok": True,
            "status": "LIVE_ONLY_MODE_ENABLED",
            "provider_status": live_status,
            "data_mode": xauusd_data_mode(),
            "data_state": xauusd_data_state(),
        }
    if mode == "IMPORT_REAL_HISTORY":
        return {
            "ok": True,
            "status": "IMPORT_REQUIRED",
            "message": "Upload real recent XAUUSD CSV with /api/xauusd/import-real-recent-history.",
            "data_mode": xauusd_data_mode(),
            "gap_diagnosis": xauusd_gap_diagnosis("15M"),
        }
    return JSONResponse(status_code=400, content={"error": "mode must be TEST_HISTORY, IMPORT_REAL_HISTORY, or LIVE_ONLY"})


@app.post("/api/xauusd/one-click-data-setup")
def xauusd_one_click_data_setup():
    return xauusd_one_click_warmup()


@app.post("/api/xauusd/one-click-warmup")
def xauusd_one_click_warmup():
    try:
        real_sync = twelve_data_history.sync_recent_history()
        if real_sync.get("ok"):
            settings.set_data_mode("REAL")
            settings.set_test_mode(False)
        result = recent_history_sync.one_click_warmup(live_builder, history_seeder, data_integrity_engine, recent_history_resolver)
        result["real_history_sync"] = real_sync
        result["data_readiness"] = xauusd_data_readiness()
        result["readiness"] = xauusd_readiness()
        result["overlay_status"] = data_integrity_engine.overlays("15M", 300).get("overlay_status", {})
        return result
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/xauusd/smart-setup")
def xauusd_smart_setup():
    try:
        health = api_health()
        real_sync = twelve_data_history.sync_recent_history()
        if real_sync.get("ok"):
            settings.set_data_mode("REAL")
            settings.set_test_mode(False)
        live_status = live_builder.start()
        live_builder.candle_builder.aggregate_all()
        diagnosis = gap_diagnosis_service.diagnose("15M")
        mode = xauusd_data_mode()
        response = {
            "ok": True,
            "status": "SMART_SETUP_READY" if diagnosis.get("status") == "READY" else "FIX_GAP_REQUIRED",
            "health": health,
            "real_history_sync": real_sync,
            "provider_status": live_status,
            "gap_diagnosis": diagnosis,
            "data_mode": mode,
            "data_state": xauusd_data_state(),
            "fix_gap_required": diagnosis.get("recommended_action") == "FIX_GAP_NOW",
            "fix_gap_options": [
                {"mode": "TEST_HISTORY", "label": "Generate Live-Anchored Test History"},
                {"mode": "IMPORT_REAL_HISTORY", "label": "Import Real Recent History"},
                {"mode": "LIVE_ONLY", "label": "Live-Only Mode"},
            ],
            "overlay_status": data_integrity_engine.overlays("15M", 300).get("overlay_status", {}),
        }
        return response
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/xauusd/toggle-test-mode")
def xauusd_toggle_test_mode(payload: TestModePayload):
    status = settings.set_test_mode(payload.enabled)
    return {
        "ok": True,
        "test_mode_enabled": status["test_mode_enabled"],
        "warning": "Test history is for development only." if status["test_mode_enabled"] else None,
        "data_readiness": xauusd_data_readiness(),
    }


@app.post("/api/xauusd/download-free-history")
def xauusd_download_free_history():
    return {
        "ok": False,
        "status": "NO_FREE_HISTORY_PROVIDER",
        "message": "Gold-API.com has no free OHLC history endpoint. Use /api/xauusd/sync-real-history when a Twelve Data key is configured, or upload real XAUUSD CSV.",
        "history_dir": HISTORY_DIR,
        "data_readiness": gap_detector.readiness(),
    }


@app.post("/api/xauusd/sync-real-history")
def xauusd_sync_real_history(timeframe: Optional[str] = Query(None)):
    try:
        timeframes = [normalize_timeframe(timeframe)] if timeframe else None
        result = twelve_data_history.sync_recent_history(timeframes)
        if result.get("ok"):
            settings.set_data_mode("REAL")
            settings.set_test_mode(False)
            live_builder.candle_builder.aggregate_all()
        return result | {
            "data_integrity": data_integrity_engine.data_integrity(normalize_timeframe(timeframe or "15M"), 500),
            "data_readiness": xauusd_data_readiness(),
            "data_mode": xauusd_data_mode(),
            "data_state": xauusd_data_state(),
            "gap_diagnosis": xauusd_gap_diagnosis(normalize_timeframe(timeframe or "15M")),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/xauusd/analyze-live")
def xauusd_analyze_live():
    return _analysis_response(engine_core.get_mode())


@app.get("/api/xauusd/pro-analysis")
def xauusd_pro_analysis(mode: str = Query("balanced")):
    try:
        return pro_analysis_engine.analyze(_locked_data_mode(), mode)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/pro-analysis-v4")
def xauusd_pro_analysis_v4(mode: str = Query("balanced")):
    try:
        return institutional_engine_v4.analyze(_locked_data_mode(), mode)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/analysis-explanation")
def xauusd_analysis_explanation(mode: str = Query("balanced")):
    try:
        analysis = institutional_engine_v4.analyze(_locked_data_mode(), mode)
        return {
            "symbol": "XAUUSD",
            "version": APP_VERSION_LABEL,
            "analysis_explanation": analysis.get("analysis_explanation"),
            "final_decision": analysis.get("final_decision"),
            "score": analysis.get("signal", {}).get("score"),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/xauusd/analyze-pro")
def xauusd_analyze_pro():
    try:
        return _analysis_response(engine_core.get_mode())
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/xauusd/analyze-v4")
def xauusd_analyze_v4():
    try:
        return _analysis_response(engine_core.get_mode())
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/engine-status")
def xauusd_engine_status():
    return engine_core.status() | {
        "engine_core_version": "V4",
        "analysis_engine": "Institutional Analysis Engine V4",
        "provider_builder_status": live_builder.status(),
        "data_readiness": xauusd_data_readiness(),
        "data_mode_lock": _locked_data_mode(),
    }


@app.post("/api/xauusd/set-engine-mode")
def xauusd_set_engine_mode(payload: EngineModePayload):
    try:
        return engine_core.set_mode(payload.mode)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/xauusd/analyze-fast")
def xauusd_analyze_fast():
    return _analysis_response("fast")


@app.post("/api/xauusd/analyze-balanced")
def xauusd_analyze_balanced():
    return _analysis_response("balanced")


@app.post("/api/xauusd/analyze-deep")
def xauusd_analyze_deep():
    return _analysis_response("deep")


@app.get("/api/xauusd/analysis-cache")
def xauusd_analysis_cache():
    return engine_core.cache.snapshot()


@app.get("/api/xauusd/pro-analysis-cache")
def xauusd_pro_analysis_cache():
    return {"v3": pro_analysis_engine.cache_snapshot(), "v4": institutional_engine_v4.cache_snapshot()}


@app.post("/api/xauusd/clear-cache")
def xauusd_clear_cache():
    return engine_core.clear_cache()


@app.post("/api/xauusd/clear-analysis-cache")
def xauusd_clear_analysis_cache():
    return engine_core.clear_cache()


@app.get("/api/xauusd/engine-logs")
def xauusd_engine_logs():
    return {"logs": engine_core.logs.latest()}


@app.post("/api/xauusd/clear-logs")
def xauusd_clear_logs():
    engine_core.logs.clear()
    return {"ok": True, "logs": []}


@app.post("/api/xauusd/upload-csv")
async def xauusd_upload_csv(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return JSONResponse(status_code=400, content={"error": "Only CSV files are supported"})
    tmp_path = ""
    try:
        with NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        csv_provider.save_upload(tmp_path)
        data = csv_provider.backtest_frame(prefer_upload=True)
        result = run_simple_backtest(data["df_m5"])
        result["symbol"] = "XAUUSD"
        result["data_source"] = data["source"]
        result["data_message"] = "CSV is for backtest/training only. It is never used for live analysis."
        return result
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@app.post("/api/xauusd/backtest-csv")
def xauusd_backtest_csv():
    data = csv_provider.backtest_frame(prefer_upload=True)
    result = run_simple_backtest(data["df_m5"])
    result["symbol"] = "XAUUSD"
    result["data_source"] = data["source"]
    result["data_message"] = "CSV is for backtest/training only. It is never used for live analysis."
    return result


@app.post("/api/xauusd/rebuild-candles")
def xauusd_rebuild_candles():
    try:
        live_builder.candle_builder.aggregate_all()
        return {"ok": True, "message": "Aggregated candles rebuilt safely from valid live 1M candles.", "candle_counts": candle_store.counts()}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/xauusd/clear-invalid-candles")
def xauusd_clear_invalid_candles():
    try:
        return data_integrity_engine.clear_invalid_candles()
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/xauusd/import-recent-history")
async def xauusd_import_recent_history(file: UploadFile = File(...), timeframe: str = Query("15M")):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return JSONResponse(status_code=400, content={"error": "Only CSV files are supported"})
    tmp_path = ""
    try:
        with NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        tf = _timeframe_from_filename(file.filename) or normalize_timeframe(timeframe)
        return data_integrity_engine.import_real_recent_history(tmp_path, tf, USER_RECENT_CSV_SOURCE) | {
            "data_readiness": xauusd_data_readiness(),
            "data_mode": xauusd_data_mode(),
            "data_state": xauusd_data_state(),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@app.post("/api/xauusd/import-real-recent-history")
async def xauusd_import_real_recent_history(file: UploadFile = File(...), timeframe: str = Query("15M")):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return JSONResponse(status_code=400, content={"error": "Only CSV files are supported"})
    tmp_path = ""
    try:
        with NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        tf = _timeframe_from_filename(file.filename) or normalize_timeframe(timeframe)
        result = data_integrity_engine.import_real_recent_history(tmp_path, tf, USER_RECENT_CSV_SOURCE)
        live_builder.candle_builder.aggregate_all()
        settings.set_data_mode("REAL")
        return result | {
            "badge": "REAL CSV",
            "data_readiness": xauusd_data_readiness(),
            "data_mode": xauusd_data_mode(),
            "data_state": xauusd_data_state(),
            "gap_diagnosis": xauusd_gap_diagnosis("15M"),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@app.post("/api/xauusd/import-real-history")
async def xauusd_import_real_history(file: UploadFile = File(...), timeframe: str = Query("15M")):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return JSONResponse(status_code=400, content={"error": "Only CSV files are supported"})
    tmp_path = ""
    try:
        with NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        tf = _timeframe_from_filename(file.filename) or normalize_timeframe(timeframe)
        result = csv_import_pro.import_real_history(tmp_path, file.filename, tf)
        live_builder.candle_builder.aggregate_all()
        if result.get("ok") and not result.get("readiness", {}).get("missing"):
            settings.set_data_mode("REAL")
        return result | {
            "badge": "REAL CSV HISTORY",
            "data_readiness": xauusd_data_readiness(),
            "data_mode": xauusd_data_mode(),
            "data_state": xauusd_data_state(),
            "gap_diagnosis": xauusd_gap_diagnosis("15M"),
            "data_hub": _data_hub_snapshot(),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@app.post("/api/xauusd/real-mode-wizard")
def xauusd_real_mode_wizard():
    try:
        steps = []
        info = candle_store.database_info()
        provider = live_builder.status()
        source_counts = candle_store.source_counts()
        counts = candle_store.counts()
        latest = candle_store.latest_timestamps()
        diagnosis = gap_diagnosis_service.diagnose("15M")
        integrity = data_integrity_engine.data_integrity("15M", 300)
        readiness = validate_analysis_readiness(counts)
        has_real_csv = _has_source_anywhere(REAL_CSV_HISTORY_SOURCE)
        has_test = any(_has_source_anywhere(source) for source in TEST_HISTORY_SOURCES)
        steps.append({"step": 1, "name": "Check backend connection", "status": "OK"})
        steps.append({"step": 2, "name": "Check SQLite database", "status": "READY" if info.get("database_exists") and info.get("candle_tables_created") else "ERROR"})
        steps.append({"step": 3, "name": "Check live provider", "status": provider.get("status"), "latest_price": provider.get("latest_price")})
        steps.append({"step": 4, "name": "Import real recent XAUUSD history", "status": "FOUND" if has_real_csv else "REQUIRED", "source": REAL_CSV_HISTORY_SOURCE})
        steps.append({"step": 5, "name": "Validate candle data", "status": "READY" if not readiness.get("missing") else "MISSING", "missing": readiness.get("missing")})
        steps.append({"step": 6, "name": "Check gap with live price", "status": diagnosis.get("status"), "diagnosis": diagnosis})
        live_builder.candle_builder.aggregate_all()
        steps.append({"step": 7, "name": "Rebuild 5M / 15M / 1H / 4H / 1D candles", "status": "DONE", "candle_counts": candle_store.counts()})
        steps.append({"step": 8, "name": "Run data integrity check", "status": integrity.get("status"), "gap_detected": integrity.get("gap_detected")})
        can_enable_real = bool(has_real_csv and not has_test and not readiness.get("missing") and diagnosis.get("status") == "READY" and provider.get("latest_price") is not None)
        if can_enable_real:
            settings.set_data_mode("REAL")
            enable_status = "REAL_MODE_ENABLED"
            message = "REAL_MODE enabled from REAL_CSV_HISTORY and live provider status."
        elif not has_real_csv:
            enable_status = "REAL_HISTORY_REQUIRED"
            message = "Real history is required for REAL_MODE. You can use TEST_MODE for development only."
        elif has_test:
            enable_status = "CLEAR_TEST_HISTORY_REQUIRED"
            message = "Clear generated TEST HISTORY before enabling REAL_MODE."
        else:
            enable_status = "ACTION_REQUIRED"
            message = "REAL_MODE is not ready. Check provider, gap, or missing timeframe candles."
        steps.append({"step": 9, "name": "Enable REAL_MODE if ready", "status": enable_status, "enabled": can_enable_real})
        return {
            "ok": True,
            "status": enable_status,
            "message": message,
            "workflow_steps": steps,
            "source_counts": source_counts,
            "candle_counts": counts,
            "latest_candle_time": latest,
            "provider_status": provider,
            "readiness": readiness,
            "data_hub": _data_hub_snapshot(),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/xauusd/export-current-candles")
def xauusd_export_current_candles(limit: int = Query(5000, ge=1, le=20000)):
    payload: Dict[str, Any] = {}
    for timeframe in SUPPORTED_TIMEFRAMES:
        payload[timeframe] = candle_store.get_candles_payload(timeframe, limit).get("candles", [])
    return {
        "ok": True,
        "symbol": "XAUUSD",
        "version": APP_VERSION_LABEL,
        "source_counts": candle_store.source_counts(),
        "candle_counts": candle_store.counts(),
        "candles": payload,
    }


@app.post("/api/xauusd/reset-database")
def xauusd_reset_database(payload: ResetDatabasePayload):
    if not payload.confirm:
        return JSONResponse(status_code=400, content={"error": "Set confirm=true to reset local candle database sources."})
    sources = {
        TEST_HISTORY_SOURCE,
        TEST_HISTORY_LIVE_ANCHORED_SOURCE,
        REAL_CSV_HISTORY_SOURCE,
        USER_RECENT_CSV_SOURCE,
        RECENT_CSV_SOURCE,
        PRELOADED_SOURCE,
        WARMUP_SOURCE,
        CSV_SOURCE,
        LIVE_BUILDER_SOURCE,
        LIVE_SOURCE,
        ARCHIVED_STALE_SOURCE,
    }
    removed = {source: candle_store.delete_source(source) for source in sources}
    engine_core.clear_cache()
    settings.set_data_mode("AUTO")
    settings.set_test_mode(False)
    return {
        "ok": True,
        "status": "DATABASE_CANDLE_SOURCES_RESET",
        "removed": removed,
        "candle_counts": candle_store.counts(),
        "data_hub": _data_hub_snapshot(),
    }


def _analysis_response(mode: str):
    locked = _locked_data_mode()
    result = institutional_engine_v4.analyze(locked, mode)
    result["provider_status"] = live_builder.status()
    result["data_readiness"] = xauusd_data_readiness()
    result["data_state"] = xauusd_data_state()
    result["data_hub"] = _data_hub_snapshot()
    return result


def _data_hub_snapshot() -> Dict[str, Any]:
    locked = _locked_data_mode()
    provider = live_builder.status()
    info = candle_store.database_info()
    counts = candle_store.counts()
    source_counts = candle_store.source_counts()
    latest = candle_store.latest_timestamps()
    diagnosis = gap_diagnosis_service.diagnose("15M")
    readiness = validate_analysis_readiness(counts)
    last_error = provider.get("last_error") or (provider.get("message") if provider.get("status") in {"ERROR", "CONNECTION_FAILED", "RATE_LIMIT", "NO_PRICE"} else None)
    return {
        "symbol": "XAUUSD",
        "version": APP_VERSION_LABEL,
        "title": "Real Data Hub",
        "current_data_mode": locked.get("locked_mode"),
        "data_mode_label": locked.get("data_mode_label"),
        "backend_status": locked.get("backend_status"),
        "provider_status": provider.get("status"),
        "provider_name": provider.get("provider_display_name") or provider.get("provider_name"),
        "candle_source": locked.get("candle_source"),
        "source_counts": source_counts,
        "latest_live_price": provider.get("latest_price"),
        "latest_price": provider.get("latest_price"),
        "latest_candle_time": latest,
        "latest_primary_candle_time": latest.get("15M") or info.get("latest_candle_time"),
        "candle_counts_by_timeframe": counts,
        "history_freshness": "FRESH" if diagnosis.get("status") == "READY" else "STALE_OR_MISSING",
        "gap_status": diagnosis.get("status"),
        "gap_diagnosis": diagnosis,
        "analysis_readiness": {
            "ready": locked.get("analysis_ready"),
            "full_analysis_ready": locked.get("full_analysis_ready"),
            "real_signal_allowed": locked.get("real_signal_allowed"),
            "missing": readiness.get("missing"),
            "state": locked.get("analysis_state"),
        },
        "last_error": last_error,
        "database": {
            "path": info.get("database_path"),
            "exists": info.get("database_exists"),
            "tables_ready": info.get("candle_tables_created"),
        },
        "actions": [
            "Import Real History",
            "Generate Test History",
            "Clear Test History",
            "Live Only Mode",
            "Fix Gap",
            "Smart Setup",
            "Debug Data",
            "Export Current Candles",
            "Reset Database",
        ],
        "honesty_rules": [
            "Generated test history is never real.",
            "REAL_MODE requires REAL_CSV_HISTORY and live provider status.",
            "LIVE_ONLY_MODE cannot produce full analysis.",
        ],
    }


def _has_source_anywhere(source: str) -> bool:
    return any(candle_store.has_source(timeframe, source) for timeframe in SUPPORTED_TIMEFRAMES)


def _overlay_status(levels: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    groups: Dict[str, Dict[str, int]] = {}
    for item in levels.values():
        group = item.get("group", "Debug")
        groups.setdefault(group, {"ready": 0, "waiting": 0})
        if item.get("ready"):
            groups[group]["ready"] += 1
        else:
            groups[group]["waiting"] += 1
    return {
        "ready_count": sum(1 for item in levels.values() if item.get("ready")),
        "waiting_count": sum(1 for item in levels.values() if not item.get("ready")),
        "groups": groups,
    }


def _overlay_level(label: str, price: Any, color: str, group: str, style: str = "solid", visible: bool = False) -> Dict[str, Any]:
    valid = price is not None and pd.notna(price)
    return {
        "label": label,
        "price": round(float(price), 3) if valid else None,
        "color": color,
        "style": style,
        "group": group,
        "ready": bool(valid),
        "visible": bool(visible and valid),
        "default_visible": bool(visible),
        "reason": "Ready" if valid else "Waiting for Data",
    }


def _institutional_overlay_levels(analysis: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    liquidity = analysis.get("liquidity_map", {})
    crt = analysis.get("crt_range", {})
    poi = analysis.get("poi_engine", {})
    signal = analysis.get("signal", {})
    best = poi.get("best_poi") or {}
    entry = signal.get("entry_zone") or {}
    targets = signal.get("target_levels") or poi.get("target_levels") or []
    return {
        "previous_week_high": _overlay_level("Previous Week High", liquidity.get("previous_week_high"), "#60a5fa", "Liquidity"),
        "previous_week_low": _overlay_level("Previous Week Low", liquidity.get("previous_week_low"), "#60a5fa", "Liquidity"),
        "crt_high": _overlay_level("CRT High", crt.get("crt_high"), "#a78bfa", "Liquidity"),
        "crt_low": _overlay_level("CRT Low", crt.get("crt_low"), "#a78bfa", "Liquidity"),
        "equilibrium": _overlay_level("Equilibrium", crt.get("equilibrium"), "#facc15", "Liquidity", "dashed", True),
        "premium_zone_high": _overlay_level("Premium Zone High", (crt.get("premium_zone") or {}).get("high"), "#f59e0b", "Liquidity"),
        "premium_zone_low": _overlay_level("Premium Zone Low", (crt.get("premium_zone") or {}).get("low"), "#f59e0b", "Liquidity"),
        "discount_zone_high": _overlay_level("Discount Zone High", (crt.get("discount_zone") or {}).get("high"), "#22c55e", "Liquidity"),
        "discount_zone_low": _overlay_level("Discount Zone Low", (crt.get("discount_zone") or {}).get("low"), "#22c55e", "Liquidity"),
        "buy_poi_low": _overlay_level("Buy POI Low", ((poi.get("best_buy_poi") or best) or {}).get("low"), "#22c55e", "Setup"),
        "buy_poi_high": _overlay_level("Buy POI High", ((poi.get("best_buy_poi") or best) or {}).get("high"), "#22c55e", "Setup"),
        "sell_poi_low": _overlay_level("Sell POI Low", ((poi.get("best_sell_poi") or best) or {}).get("low"), "#ff8a65", "Setup"),
        "sell_poi_high": _overlay_level("Sell POI High", ((poi.get("best_sell_poi") or best) or {}).get("high"), "#ff8a65", "Setup"),
        "entry_zone_low": _overlay_level("Entry Zone Low", entry.get("low"), "#7CFC00", "Setup", "solid", True),
        "entry_zone_high": _overlay_level("Entry Zone High", entry.get("high"), "#7CFC00", "Setup", "solid", True),
        "invalidation": _overlay_level("Invalidation", signal.get("invalidation_level"), "#ff5630", "Setup", "dashed", True),
        "target_1": _overlay_level("Target 1", targets[0] if len(targets) > 0 else None, "#7CFC00", "Setup", "dashed", True),
        "target_2": _overlay_level("Target 2", targets[1] if len(targets) > 1 else None, "#7CFC00", "Setup", "dashed", True),
        "target_3": _overlay_level("Target 3", targets[2] if len(targets) > 2 else None, "#7CFC00", "Setup", "dashed", True),
    }


def _analysis_summary_from_overlays(overlays: dict, indicators: dict) -> dict:
    chart_overlays = overlays.get("chart_overlays", {})
    pressure = indicators.get("indicator_panels", {}).get("market_pressure_score", {})
    current = chart_overlays.get("price_line")
    ma_30 = chart_overlays.get("ma_30")
    if current is None or ma_30 is None:
        bias = "Range"
    elif current > ma_30 and pressure.get("bullish", 0) >= pressure.get("bearish", 0):
        bias = "Bullish"
    elif current < ma_30 and pressure.get("bearish", 0) > pressure.get("bullish", 0):
        bias = "Bearish"
    else:
        bias = "Range"
    return {
        "bias": bias,
        "current_price": current,
        "key_level": chart_overlays.get("pivot_line"),
        "pressure": pressure,
    }


def _setup_checklist(info: dict, provider_status: dict, history_files: dict) -> dict:
    counts = info.get("candle_counts", {})
    candles_available = any(counts.values())
    return {
        "backend_connected": True,
        "sqlite_database_found": bool(info.get("database_exists")),
        "candle_tables_created": bool(info.get("candle_tables_created")),
        "history_seeded": bool(candles_available),
        "live_builder_running": bool(provider_status.get("is_running")),
        "latest_price_received": provider_status.get("latest_price") is not None,
        "chart_candles_available": candles_available,
        "analysis_ready": bool(gap_detector.readiness().get("full_analysis_ready")),
        "history_files_available": all(history_files.values()),
    }


def _timeframe_from_filename(filename: str) -> Optional[str]:
    if not filename:
        return None
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
