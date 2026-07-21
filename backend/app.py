from __future__ import annotations

import asyncio
import os
import threading
from tempfile import NamedTemporaryFile
from typing import Any, Dict, Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=False)

from engine.backtester import run_simple_backtest
from engine.analysis_journal import AnalysisJournal
from engine.auth_guard import AuthGuardError, SupabaseAuthGuard
from engine.setup_tracker import SetupTracker
from engine.diamond_history import DiamondHistory
from engine.diamond_validation import DiamondValidationLab, ENGINE_VERSION as DIAMOND_VALIDATION_ENGINE_VERSION
from engine.session_framework import SessionFramework
from engine.key_zone import DiamondZoneEngine
from engine.diamond_auto_entry import DiamondAutoEntryEngine
from engine.news_intelligence import EconomicNewsIntelligence
from engine.strategy_governance import CHALLENGER_VERSION, StrategyGovernance
from engine.execution_reality import ExecutionRealityEngine, FeedReconciliationEngine
from engine.decision_quality import DecisionQualityEngine
from engine.market_regime import MarketRegimeEngine
from engine.signal_alerts import ClosedCandleAlerts
from engine.xau_confluence import XAUPrecisionConfluenceEngine
from engine.data_integrity import DataIntegrityEngine
from engine.data_mode_lock import DataModeLockService
from engine.engine_core import EngineCore
from engine.institutional_analysis import InstitutionalAnalysisEngineV4
from engine.pro_analysis import ProAnalysisEngineV3
from engine.real_data_hub import CSVImportProService
from engine.xauusd_provider import (
    ARCHIVED_STALE_SOURCE,
    BINANCE_HISTORY_SOURCE,
    BinanceHistoryService,
    CandleGapDetector,
    CandleEngineQualityValidator,
    CandleHealthService,
    CandleHistorySeeder,
    CSVBacktestProvider,
    CSV_SOURCE,
    DataGapDiagnosisService,
    GoldAPIStatus,
    GOLD_API_COM_PROVIDER_NAME,
    GOLD_API_IO_PROVIDER_NAME,
    LIVE_BUILDER_SOURCE,
    LIVE_SOURCE,
    LiveCandleBuilderService,
    MIN_ANALYSIS_CANDLES,
    OANDA_HISTORY_SOURCE,
    OandaHistoryService,
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

APP_VERSION = "3.8.0"
APP_VERSION_LABEL = "V3.8"
APP_DESCRIPTION = "Diamond Discovery Trading OS"
MARKET_VISUAL_SYMBOLS = {
    "XAUUSD": "OANDA:XAUUSD",
    "BTCUSD": "BINANCE:BTCUSDT",
}
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_DIR = os.path.abspath(os.getenv("SH_DATA_DIR") or BUNDLED_DATA_DIR)
SAMPLE_CSV = os.path.join(BUNDLED_DATA_DIR, "sample_xauusd_m5.csv")
HISTORY_DIR = os.path.join(BUNDLED_DATA_DIR, "xauusd_history")
RECENT_HISTORY_DIR = os.path.join(DATA_DIR, "xauusd_recent_history")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
UPLOAD_CSV = os.path.join(UPLOAD_DIR, "xauusd_latest_upload.csv")
SETTINGS_FILE = os.path.join(DATA_DIR, "provider_settings.json")
SQLITE_DB = os.path.join(DATA_DIR, "sh_gold_analyzer.sqlite")
BTC_SQLITE_DB = os.path.join(DATA_DIR, "sh_btc_analyzer.sqlite")
ANALYSIS_JOURNAL_DB = os.path.join(DATA_DIR, "analysis_journal.sqlite")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RECENT_HISTORY_DIR, exist_ok=True)

app = FastAPI(title="SH Market Analyzer API", version=APP_VERSION)
cors_origins = [item.strip() for item in str(os.getenv("CORS_ORIGINS") or "").split(",") if item.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
auth_guard = SupabaseAuthGuard()


@app.middleware("http")
async def require_authenticated_api(request: Request, call_next):
    if not auth_guard.protects(request.method, request.url.path):
        return await call_next(request)
    try:
        request.state.auth_user = await asyncio.to_thread(
            auth_guard.verify,
            request.headers.get("Authorization"),
        )
    except AuthGuardError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "code": exc.code},
        )
    if auth_guard.requires_admin(request.url.path) and request.state.auth_user.get("app_role") != "admin":
        return JSONResponse(
            status_code=403,
            content={"error": "Administrator access is required.", "code": "ADMIN_REQUIRED"},
        )
    return await call_next(request)

settings = ProviderSettings(SETTINGS_FILE)
analysis_journal = AnalysisJournal(ANALYSIS_JOURNAL_DB)
setup_tracker = SetupTracker(ANALYSIS_JOURNAL_DB)
diamond_history = DiamondHistory(ANALYSIS_JOURNAL_DB)
session_framework_engine = SessionFramework()
diamond_zone_engine = DiamondZoneEngine()
diamond_challenger_engine = DiamondZoneEngine(
    strategy_name="SH_DIAMOND_ZONE_V6_2_SHADOW",
    engine_version=CHALLENGER_VERSION,
    profile_adjustments={
        "min_entry_quality": -2.0,
        "min_retest_close_strength": -0.02,
        "min_follow_body_ratio": -0.02,
        "min_follow_close_strength": -0.02,
        "min_follow_progress_atr": -0.02,
        "max_entry_displacement_atr": 0.05,
    },
    profile_suffix="SHADOW",
)
diamond_validation_lab = DiamondValidationLab(ANALYSIS_JOURNAL_DB, diamond_zone_engine)
strategy_governance = StrategyGovernance(ANALYSIS_JOURNAL_DB)
diamond_auto_entry_engine = DiamondAutoEntryEngine()
feed_reconciliation_engine = FeedReconciliationEngine()
execution_reality_engine = ExecutionRealityEngine()
decision_quality_engine = DecisionQualityEngine()
market_regime_engine = MarketRegimeEngine()
closed_candle_alerts = ClosedCandleAlerts(ANALYSIS_JOURNAL_DB)
news_intelligence_engine = EconomicNewsIntelligence()
xau_precision_engine = XAUPrecisionConfluenceEngine()
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
oanda_history = OandaHistoryService(settings, candle_store)
pro_analysis_engine = ProAnalysisEngineV3(candle_store, engine_core.cache)
institutional_engine_v4 = InstitutionalAnalysisEngineV4(candle_store, engine_core.cache)
btc_candle_store = SQLiteCandleStore(BTC_SQLITE_DB)
btc_data_integrity_engine = DataIntegrityEngine(btc_candle_store)
btc_engine_core = EngineCore(btc_candle_store)
btc_data_mode_lock = DataModeLockService(btc_candle_store, settings, symbol="BTCUSD")
btc_twelve_data_history = TwelveDataHistoryService(
    settings,
    btc_candle_store,
    market_symbol="BTC/USD",
    provider_name="Twelve Data BTC/USD OHLC",
)
binance_history = BinanceHistoryService(btc_candle_store)
btc_institutional_engine_v4 = InstitutionalAnalysisEngineV4(
    btc_candle_store,
    btc_engine_core.cache,
    symbol="BTCUSD",
)
auto_analysis_lock = threading.Lock()
auto_analysis_state: Dict[str, Dict[str, Any]] = {}
oanda_history_sync_lock = threading.Lock()
oanda_restore_state: Dict[str, Any] = {
    "status": "PENDING" if settings.get("oanda_api_token") else "NOT_CONFIGURED",
    "running": False,
    "last_restored_at": None,
    "dns_recovery": False,
    "message": "Saved OANDA credentials will be restored at startup." if settings.get("oanda_api_token") else "OANDA credentials are not configured.",
}
startup_seed_result = history_seeder.seed_if_needed()
startup_live_status = live_builder.start()


class ProviderSettingsPayload(BaseModel):
    goldapi_key: Optional[str] = None
    goldapi_io_key: Optional[str] = None
    twelve_data_api_key: Optional[str] = None
    oanda_api_token: Optional[str] = None
    oanda_environment: Optional[str] = None


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


class DiamondValidationPayload(BaseModel):
    symbol: str = "XAUUSD"
    timeframe: str = "15M"
    lookback_bars: int = 1000
    horizon_bars: Optional[int] = None
    refresh_market: bool = True
    force: bool = False


@app.get("/")
def root():
    return {
        "name": f"SH Market Analyzer {APP_VERSION_LABEL} - {APP_DESCRIPTION}",
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
    print(f"SH Market Analyzer {APP_VERSION_LABEL} startup")
    print(f"SQLite database path: {SQLITE_DB}")
    print(f"History folder path: {HISTORY_DIR}")
    print(f"Recent history folder path: {RECENT_HISTORY_DIR}")
    print("Registered routes:")
    for route in app.routes:
        methods = ",".join(sorted(getattr(route, "methods", []) or []))
        path = getattr(route, "path", "")
        if path:
            print(f"  {methods} {path}")
    if settings.get("oanda_api_token"):
        threading.Thread(
            target=_restore_saved_oanda_feed,
            name="oanda-feed-restore",
            daemon=True,
        ).start()


@app.get("/api/health")
def api_health():
    info = candle_store.database_info()
    btc_info = btc_candle_store.database_info()
    provider_status = live_builder.status()
    locked = _locked_data_mode()
    oanda_configured = bool(settings.get("oanda_api_token"))
    return {
        "status": "OK",
        "app": "SH Market Analyzer",
        "version": APP_VERSION_LABEL,
        "diamond_zone_engine": diamond_zone_engine.engine_version,
        "diamond_validation_engine": DIAMOND_VALIDATION_ENGINE_VERSION,
        "diamond_challenger_engine": CHALLENGER_VERSION,
        "decision_quality_engine": decision_quality_engine.VERSION,
        "market_regime_engine": market_regime_engine.VERSION,
        "pro_analyze_engine": institutional_engine_v4.VERSION,
        "diamond_result_integrity": "DIAMOND_RESULT_INTEGRITY_V5_SIGNAL_TIERS",
        "diamond_evidence_ledger": "DIAMOND_EVIDENCE_V1",
        "database_connected": bool(info.get("database_exists") and info.get("candle_tables_created")),
        "btc_database_connected": bool(btc_info.get("database_exists") and btc_info.get("candle_tables_created")),
        "supported_assets": list(MARKET_VISUAL_SYMBOLS),
        "provider_status": provider_status.get("status"),
        "backend_status": "ONLINE",
        "authentication": auth_guard.status(),
        "market_feed": {
            "oanda_configured": oanda_configured,
            "oanda_environment": settings.get("oanda_environment") or "practice",
            "restore_status": oanda_restore_state.get("status"),
            "restore_running": bool(oanda_restore_state.get("running")),
            "restore_message": oanda_restore_state.get("message"),
            "source_by_timeframe": {
                timeframe: candle_store.source_summary(timeframe)
                for timeframe in ["5M", "15M", "1H", "4H", "1D"]
            },
        },
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
    return {"app": "SH Market Analyzer", "version": APP_VERSION_LABEL, "routes": routes, "count": len(routes)}


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


def _normalize_market_symbol(symbol: str) -> str:
    normalized = str(symbol or "XAUUSD").upper().replace("/", "").replace("-", "")
    aliases = {"GOLD": "XAUUSD", "XAU": "XAUUSD", "BTC": "BTCUSD", "BTCUSDT": "BTCUSD"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in MARKET_VISUAL_SYMBOLS:
        raise ValueError("symbol must be XAUUSD or BTCUSD")
    return normalized


def _normalize_trading_style(value: str) -> str:
    return "SWING" if str(value or "").strip().upper() == "SWING" else "SCALPING"


def _locked_market_data_mode(symbol: str) -> dict:
    normalized = _normalize_market_symbol(symbol)
    if normalized == "XAUUSD":
        return _locked_data_mode()
    return btc_data_mode_lock.locked_mode(integrity={}, diagnosis={}, backend_online=True)


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
            "indicator_snapshot": base.get("indicator_snapshot") or {
                "status": "WAITING",
                "source": "CLOSED_PROVIDER_CANDLES",
            },
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
            "indicator_snapshot": base.get("indicator_snapshot") or {
                "status": "WAITING",
                "source": "CLOSED_PROVIDER_CANDLES",
            },
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
    return live_builder.status() | {
        "settings": settings.masked_status(),
        "oanda_restore": dict(oanda_restore_state),
        "minimum_required": MIN_ANALYSIS_CANDLES,
        "data_readiness": xauusd_data_readiness(),
    }


@app.get("/api/xauusd/provider-credentials")
async def xauusd_provider_credentials():
    """Return masked credential state without waiting on candle database checks."""
    return {
        "status": "OK",
        "settings": settings.masked_status(),
        "oanda_restore": dict(oanda_restore_state),
    }


@app.post("/api/xauusd/provider-settings")
def xauusd_provider_settings(payload: ProviderSettingsPayload):
    masked = settings.update(payload.model_dump(exclude_none=True))
    return {"ok": True, "settings": masked, "message": "Provider settings saved in backend local settings."}


@app.post("/api/xauusd/verify-oanda")
def xauusd_verify_oanda(payload: ProviderSettingsPayload):
    result = oanda_history.verify_connection(payload.oanda_api_token, payload.oanda_environment)
    if not result.get("ok"):
        return JSONResponse(status_code=400, content=result)
    access_token = payload.oanda_api_token or settings.get("oanda_api_token")
    selected_environment = result.get("environment") or payload.oanda_environment or "practice"
    masked = settings.save_verified_oanda(access_token, selected_environment)
    sync = _sync_live_visual_analysis_history()
    matched_sync = sync.get("ok") and sync.get("source") == OANDA_HISTORY_SOURCE
    oanda_restore_state.update({
        "status": "READY" if matched_sync else "SYNC_WARNING",
        "running": False,
        "last_restored_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "dns_recovery": bool(result.get("dns_recovery") or sync.get("dns_recovery")),
        "message": "Saved OANDA credentials restored and matched history synchronized." if matched_sync else "OANDA was verified and saved, but matched history is still synchronizing.",
    })
    return result | {
        "saved": True,
        "settings": masked,
        "history_sync": {
            "ok": matched_sync,
            "status": sync.get("status"),
            "source": sync.get("source"),
            "imported": sync.get("imported") or {},
            "dns_recovery": bool(sync.get("dns_recovery")),
        },
        "message": (
            "OANDA XAU_USD verified, saved, and matched history synchronized."
            if matched_sync
            else "OANDA XAU_USD verified and saved. Matched history synchronization needs another retry."
        ),
    }


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
        return _market_analysis_payload(analysis)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/analysis-explanation")
def market_analysis_explanation(symbol: str = Query("XAUUSD"), mode: str = Query("balanced")):
    try:
        return _market_analysis_payload(_market_analysis(symbol, mode))
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/overview")
def market_overview(mode: str = Query("balanced")):
    try:
        analyses = {
            "XAUUSD": institutional_engine_v4.analyze(_locked_data_mode(), mode),
            "BTCUSD": btc_institutional_engine_v4.analyze(_locked_market_data_mode("BTCUSD"), mode),
        }
        stores = {"XAUUSD": candle_store, "BTCUSD": btc_candle_store}
        assets = []
        for symbol, analysis in analyses.items():
            signal = analysis.get("signal") or {}
            plan = analysis.get("trade_plan") or {}
            explanation = analysis.get("analysis_explanation") or {}
            assets.append({
                "symbol": symbol,
                "visual_symbol": MARKET_VISUAL_SYMBOLS[symbol],
                "price": analysis.get("current_price"),
                "bias": analysis.get("bias") or "No Clear Bias",
                "decision": analysis.get("final_decision") or "Waiting for Data",
                "score": signal.get("score", 0),
                "data_mode": analysis.get("data_mode"),
                "analysis_source": analysis.get("analysis_data_source"),
                "provider_alignment": _provider_alignment(symbol, analysis.get("analysis_data_source")),
                "plan_status": plan.get("status") or "NO_DATA",
                "direction": plan.get("direction") or signal.get("direction") or "WAIT",
                "order_type": plan.get("order_type") or "NONE",
                "execution_allowed": bool(signal.get("execution_allowed")),
                "evidence": plan.get("zone_source"),
                "next_trigger": explanation.get("next_trigger") or plan.get("trigger"),
                "asset_profile": (analysis.get("asset_intelligence") or {}).get("profile"),
                "asset_consensus": (analysis.get("asset_intelligence") or {}).get("consensus"),
                "asset_quality_score": (analysis.get("asset_intelligence") or {}).get("quality_score"),
                "asset_execution_gate": (analysis.get("asset_intelligence") or {}).get("execution_gate"),
                "latest_5m_candle": stores[symbol].latest_any_timestamp("5M"),
            })
        return {
            "status": "OK",
            "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "assets": assets,
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/signal-view")
def market_signal_view(
    symbol: str = Query("XAUUSD"),
    timeframe: str = Query("15M"),
    trade_style: str = Query("SCALPING"),
    refresh_market: bool = Query(True),
    limit: int = Query(500, ge=30, le=1000),
):
    try:
        normalized = _normalize_market_symbol(symbol)
        tf = normalize_timeframe(timeframe)
        style = _normalize_trading_style(trade_style)
        sync = _sync_market_chart_history(normalized, tf) if refresh_market else {
            "ok": True,
            "status": "CACHED_ANALYSIS",
            "source": OANDA_HISTORY_SOURCE if normalized == "XAUUSD" else BINANCE_HISTORY_SOURCE,
            "provider": oanda_history.provider_name if normalized == "XAUUSD" else binance_history.provider_name,
            "message": "Analyzing the cached matched feed while live candle sync continues in the background.",
        }
        integrity_engine = data_integrity_engine if normalized == "XAUUSD" else btc_data_integrity_engine
        locked = _locked_market_data_mode(normalized)
        chart = integrity_engine.chart_data(tf, limit)
        chart.pop("frames", None)
        chart["symbol"] = normalized
        overlays = integrity_engine.overlays(tf, min(limit, 1000))
        overlays["symbol"] = normalized
        panels = _verifiable_indicator_panels(integrity_engine, normalized, tf, min(limit, 1000), locked)
        analysis = _market_analysis(normalized, engine_core.get_mode())
        chart_source = chart.get("data_integrity", {}).get("chart_source") or sync.get("source")
        session = _market_session_framework(normalized, tf)
        analysis["session_framework"] = session
        key_zones = _market_key_zones(normalized, tf, chart, analysis, session, style)
        challenger_snapshot = key_zones.pop("challenger_snapshot", {})
        strategy_governance.record(
            normalized,
            tf,
            chart.get("candles") or [],
            chart_source,
            key_zones.get("feed_matched") is True,
            key_zones,
            challenger_snapshot,
        )
        champion_validation = diamond_validation_lab.latest(normalized, tf)
        analysis["strategy_governance"] = strategy_governance.snapshot(
            normalized,
            tf,
            champion_validation,
        )
        expected_source = OANDA_HISTORY_SOURCE if normalized == "XAUUSD" else BINANCE_HISTORY_SOURCE
        analysis["feed_reconciliation"] = feed_reconciliation_engine.evaluate(
            normalized,
            tf,
            chart,
            expected_source,
            sync,
        )
        news_intelligence = news_intelligence_engine.snapshot(normalized)
        provider_alignment = _provider_alignment(normalized, chart_source, sync)
        analysis["provider_alignment"] = provider_alignment
        analysis["trust_gate"] = _market_trust_gate(normalized, provider_alignment)
        analysis["key_zones"] = key_zones
        analysis["news_intelligence"] = news_intelligence
        xau_confluence = xau_precision_engine.evaluate(analysis, key_zones, session, news_intelligence)
        analysis["xau_confluence"] = xau_confluence
        analysis["market_regime"] = market_regime_engine.evaluate(
            normalized,
            tf,
            chart.get("candles") or [],
            (analysis.get("trade_plan") or {}).get("direction")
            or (analysis.get("signal") or {}).get("direction"),
        )
        execution_reality = execution_reality_engine.evaluate(analysis, analysis["feed_reconciliation"])
        execution_reality_engine.apply_to_analysis(analysis, execution_reality)
        decision_quality = decision_quality_engine.evaluate(analysis, champion_validation)
        decision_quality_engine.apply_to_analysis(analysis, decision_quality)
        analysis["closed_candle_alert"] = closed_candle_alerts.record(analysis, tf)
        diamond_history.record(analysis, tf)
        return {
            "status": "OK",
            "symbol": normalized,
            "visual_symbol": MARKET_VISUAL_SYMBOLS[normalized],
            "timeframe": tf,
            "trading_style": style,
            "chart_data": chart,
            "overlays": overlays,
            "panels": panels,
            "analysis": _market_analysis_payload(analysis),
            "session_framework": session,
            "key_zones": key_zones,
            "news_intelligence": news_intelligence,
            "xau_confluence": xau_confluence,
            "market_regime": analysis["market_regime"],
            "provider_alignment": provider_alignment,
            "history_provenance": {
                "source": chart_source,
                "mixed_sources": bool(chart.get("data_integrity", {}).get("mixed_chart_sources")),
                "backfill": sync.get("backfill"),
                "history_refresh": sync.get("history_refresh"),
                "audit": _chart_candle_audit(normalized, tf, chart),
            },
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/chart-snapshot")
def market_chart_snapshot(
    symbol: str = Query("XAUUSD"),
    timeframe: str = Query("15M"),
    limit: int = Query(500, ge=30, le=1000),
):
    """Return cached chart data immediately while the full analysis refresh runs."""
    try:
        normalized = _normalize_market_symbol(symbol)
        tf = normalize_timeframe(timeframe)
        integrity_engine = data_integrity_engine if normalized == "XAUUSD" else btc_data_integrity_engine
        chart = integrity_engine.chart_data(tf, limit)
        chart.pop("frames", None)
        chart["symbol"] = normalized
        source = chart.get("data_integrity", {}).get("chart_source")
        alignment = _provider_alignment(normalized, source)
        return {
            "status": "CACHED_SNAPSHOT",
            "symbol": normalized,
            "visual_symbol": MARKET_VISUAL_SYMBOLS[normalized],
            "timeframe": tf,
            "chart_data": chart,
            "overlays": {"status": "REFRESHING", "symbol": normalized, "overlays": {}, "overlay_status": {}},
            "panels": {"status": "REFRESHING", "symbol": normalized, "indicator_panels": {}},
            "provider_alignment": alignment,
            "history_provenance": {
                "source": source,
                "mixed_sources": bool(chart.get("data_integrity", {}).get("mixed_chart_sources")),
                "audit": _chart_candle_audit(normalized, tf, chart),
                "snapshot_only": True,
            },
            "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/chart-live")
def market_chart_live(
    symbol: str = Query("XAUUSD"),
    timeframe: str = Query("15M"),
    trade_style: str = Query("SCALPING"),
    limit: int = Query(500, ge=30, le=1000),
):
    """Update only the forming chart candle; analysis continues to use closed candles."""
    try:
        normalized = _normalize_market_symbol(symbol)
        tf = normalize_timeframe(timeframe)
        style = _normalize_trading_style(trade_style)
        sync = _sync_market_chart_candle(normalized, tf)
        integrity_engine = data_integrity_engine if normalized == "XAUUSD" else btc_data_integrity_engine
        chart = integrity_engine.chart_data(tf, limit)
        chart.pop("frames", None)
        chart["symbol"] = normalized
        auto_scan = _auto_analyze_market_if_due(normalized, tf, chart, style)
        if auto_scan.get("ran"):
            chart = integrity_engine.chart_data(tf, limit)
            chart.pop("frames", None)
            chart["symbol"] = normalized
        panels = _verifiable_indicator_panels(
            integrity_engine,
            normalized,
            tf,
            min(limit, 1000),
            _locked_market_data_mode(normalized),
        )
        source = chart.get("data_integrity", {}).get("chart_source") or sync.get("source")
        alignment = _provider_alignment(normalized, source, sync)
        analysis = auto_scan.get("analysis") or {}
        session = analysis.get("session_framework") or _market_session_framework(normalized, tf)
        key_zones = analysis.get("key_zones") or _market_key_zones(normalized, tf, chart, analysis or None, session, style)
        news_intelligence = analysis.get("news_intelligence") or news_intelligence_engine.snapshot(normalized)
        _refresh_tracked_setups(normalized)
        tracker_snapshot = {
            "status": "OK",
            "symbol": normalized,
            "model": "DIAMOND_V6_AUTO",
            "setups": setup_tracker.list(normalized, 20, "DIAMOND_V6_AUTO"),
            "stats": setup_tracker.stats(normalized, "DIAMOND_V6_AUTO"),
            "overall_stats": setup_tracker.stats(normalized),
        }
        if auto_scan.get("ran"):
            _reconcile_diamond_history(normalized)
        diamond_snapshot = {
            "status": "OK",
            "symbol": normalized,
            "strategy": "SH_DIAMOND_ZONE_V6_SIMPLE_DISCOVERY",
            "entries": diamond_history.list(normalized, 200),
            "stats": diamond_history.stats(normalized),
        }
        auto_status = {key: value for key, value in auto_scan.items() if key != "analysis"}
        return {
            "status": "OK" if sync.get("ok") else "DEGRADED",
            "symbol": normalized,
            "visual_symbol": MARKET_VISUAL_SYMBOLS[normalized],
            "timeframe": tf,
            "trading_style": style,
            "chart_data": chart,
            "panels": panels,
            "session_framework": session,
            "key_zones": key_zones,
            "news_intelligence": news_intelligence,
            "analysis": analysis or None,
            "auto_analysis": auto_status,
            "setup_tracker": tracker_snapshot,
            "diamond_history": diamond_snapshot,
            "live_sync": sync | {
                "poll_after_ms": 5000 if normalized == "BTCUSD" else 10000 if alignment["matched"] else 30000,
                "analysis_uses_completed_candles_only": True,
                "manual_analysis_required": False,
            },
            "provider_alignment": alignment,
            "history_provenance": {
                "source": chart.get("data_integrity", {}).get("chart_source") or source,
                "mixed_sources": bool(chart.get("data_integrity", {}).get("mixed_chart_sources")),
                "backfill": sync.get("backfill"),
                "audit": _chart_candle_audit(normalized, tf, chart),
            },
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/mtf-snapshot")
def market_mtf_snapshot(symbol: str = Query("XAUUSD")):
    try:
        normalized = _normalize_market_symbol(symbol)
        integrity_engine = data_integrity_engine if normalized == "XAUUSD" else btc_data_integrity_engine
        rows = [integrity_engine.timeframe_snapshot(tf) for tf in ["1D", "4H", "1H", "15M", "5M"]]
        weights = {"1D": 30, "4H": 25, "1H": 20, "15M": 15, "5M": 10}
        ready = [row for row in rows if row.get("status") == "READY"]
        weighted_score = (
            sum(float(row.get("score", 0)) * weights[row["timeframe"]] for row in ready)
            / sum(weights[row["timeframe"]] for row in ready)
            if ready
            else 0
        )
        expected_source = OANDA_HISTORY_SOURCE if normalized == "XAUUSD" else BINANCE_HISTORY_SOURCE
        sources_matched = bool(ready) and all(row.get("source") == expected_source for row in ready)
        bias = "BULLISH" if weighted_score >= 25 else "BEARISH" if weighted_score <= -25 else "MIXED"
        return {
            "status": "READY" if len(ready) == 5 else "PARTIAL",
            "symbol": normalized,
            "bias": bias,
            "confluence_score": round(weighted_score),
            "ready_timeframes": len(ready),
            "timeframes": rows,
            "expected_source": expected_source,
            "sources_matched": sources_matched,
            "scope": "MARKET_CONTEXT_ONLY",
            "actionable": False,
            "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/session-framework")
def market_session_framework(symbol: str = Query("XAUUSD"), timeframe: str = Query("15M")):
    try:
        return _market_session_framework(_normalize_market_symbol(symbol), normalize_timeframe(timeframe))
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
        return _analyze_market_v4("XAUUSD")
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/market/analyze-v4")
def market_analyze_v4(
    symbol: str = Query("XAUUSD"),
    timeframe: str = Query("15M"),
    trade_style: str = Query("SCALPING"),
):
    try:
        return _analyze_market_v4(symbol, normalize_timeframe(timeframe), _normalize_trading_style(trade_style))
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/news-intelligence")
def market_news_intelligence(symbol: str = Query("XAUUSD")):
    try:
        return news_intelligence_engine.snapshot(_normalize_market_symbol(symbol))
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/news-calendar")
def market_news_calendar(
    symbol: str = Query("XAUUSD"),
    refresh: bool = Query(False),
):
    try:
        return news_intelligence_engine.weekly_calendar(
            _normalize_market_symbol(symbol),
            force_refresh=refresh,
        )
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/analysis-history")
def market_analysis_history(
    symbol: Optional[str] = Query(None),
    limit: int = Query(12, ge=1, le=200),
):
    try:
        normalized = _normalize_market_symbol(symbol) if symbol else None
        return {
            "status": "OK",
            "symbol": normalized,
            "entries": analysis_journal.list(normalized, limit),
            "stats": analysis_journal.stats(normalized),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/diamond-history")
def market_diamond_history(
    symbol: str = Query("XAUUSD"),
    limit: int = Query(30, ge=1, le=200),
):
    try:
        normalized = _normalize_market_symbol(symbol)
        reconciled = _reconcile_diamond_history(normalized)
        return {
            "status": "OK",
            "symbol": normalized,
            "strategy": "SH_DIAMOND_ZONE_V6_SIMPLE_DISCOVERY",
            "ledger_version": "DIAMOND_EVIDENCE_V1",
            "entries": diamond_history.list(normalized, limit),
            "stats": diamond_history.stats(normalized),
            "calibration": diamond_history.calibration(normalized),
            "reconciled": reconciled,
            "verification_rule": (
                "Context and unconfirmed zones are excluded from win/loss. Confirmed entries use later "
                "completed matched-provider candles with a fixed 1.8R XAU or 1.6R BTC audit target."
            ),
            "lifecycle_rule": (
                "Detected and qualified context remains separate from confirmed entries. Waiting, active, resolved, "
                "expired, ambiguous, and invalidated stages are preserved as an append-only evidence timeline."
            ),
            "forward_return_rule": (
                "Directional 5, 10, and 20-bar returns mature only after the required later provider candles close."
            ),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/diamond-validation")
def market_diamond_validation(
    symbol: str = Query("XAUUSD"),
    timeframe: str = Query("15M"),
):
    try:
        normalized = _normalize_market_symbol(symbol)
        tf = normalize_timeframe(timeframe)
        return diamond_validation_lab.latest(normalized, tf)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/strategy-governance")
def market_strategy_governance(
    symbol: str = Query("XAUUSD"),
    timeframe: str = Query("15M"),
):
    try:
        normalized = _normalize_market_symbol(symbol)
        tf = normalize_timeframe(timeframe)
        champion_validation = diamond_validation_lab.latest(normalized, tf)
        return strategy_governance.snapshot(normalized, tf, champion_validation)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/alerts")
def market_closed_candle_alerts(
    symbol: str = Query("XAUUSD"),
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
):
    try:
        normalized = _normalize_market_symbol(symbol)
        return closed_candle_alerts.list(normalized, limit, unread_only)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/market/alerts/{alert_id}/acknowledge")
def acknowledge_market_alert(alert_id: int):
    try:
        alert = closed_candle_alerts.acknowledge(alert_id)
        if not alert:
            return JSONResponse(status_code=404, content={"error": "Alert not found."})
        return {"status": "ACKNOWLEDGED", "alert": alert}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/market/diamond-validation/run")
def run_market_diamond_validation(payload: DiamondValidationPayload):
    try:
        normalized = _normalize_market_symbol(payload.symbol)
        tf = normalize_timeframe(payload.timeframe)
        lookback = max(400, min(int(payload.lookback_bars), 5000))
        sync = _sync_market_chart_history(normalized, tf) if payload.refresh_market else {
            "ok": True,
            "status": "CACHED_PROVIDER_HISTORY",
        }
        store = candle_store if normalized == "XAUUSD" else btc_candle_store
        expected_source = OANDA_HISTORY_SOURCE if normalized == "XAUUSD" else BINANCE_HISTORY_SOURCE
        frame = store.get_candles_df(tf, lookback, {expected_source})
        candles = []
        for timestamp, row in frame.iterrows():
            candles.append({
                "time": int(timestamp.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "is_complete": bool(row.get("is_complete", True)),
                "is_partial": bool(row.get("is_partial", False)),
            })
        result = diamond_validation_lab.run(
            normalized,
            tf,
            candles,
            expected_source,
            payload.horizon_bars,
            payload.force,
        )
        result["provider_sync"] = {
            "ok": bool(sync.get("ok")),
            "status": sync.get("status"),
            "source": sync.get("source") or expected_source,
        }
        return result
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/market/analysis-history/{run_id}")
def market_analysis_history_detail(run_id: int):
    entry = analysis_journal.get(run_id)
    if not entry:
        return JSONResponse(status_code=404, content={"error": "Analysis journal entry not found."})
    return {"status": "OK", "entry": entry}


@app.get("/api/market/setups")
def market_setups(
    symbol: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=200),
):
    try:
        normalized = _normalize_market_symbol(symbol) if symbol else None
        if normalized:
            _refresh_tracked_setups(normalized)
        return {
            "status": "OK",
            "symbol": normalized,
            "model": "DIAMOND_V6_AUTO",
            "setups": setup_tracker.list(normalized, limit, "DIAMOND_V6_AUTO"),
            "stats": setup_tracker.stats(normalized, "DIAMOND_V6_AUTO"),
            "overall_stats": setup_tracker.stats(normalized),
            "verification_rule": "Completed source-matched candles after setup creation only.",
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/market/setups/refresh")
def market_setups_refresh(symbol: str = Query("XAUUSD")):
    try:
        normalized = _normalize_market_symbol(symbol)
        refreshed = _refresh_tracked_setups(normalized)
        return {
            "status": "OK",
            "symbol": normalized,
            "refreshed": refreshed,
            "model": "DIAMOND_V6_AUTO",
            "setups": setup_tracker.list(normalized, 20, "DIAMOND_V6_AUTO"),
            "stats": setup_tracker.stats(normalized, "DIAMOND_V6_AUTO"),
            "overall_stats": setup_tracker.stats(normalized),
        }
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.post("/api/market/setups/{setup_id}/cancel")
def market_setup_cancel(setup_id: int):
    setup = setup_tracker.cancel(setup_id)
    if not setup:
        return JSONResponse(status_code=404, content={"error": "Tracked setup not found."})
    return {"status": "OK", "setup": setup}


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


def _restore_saved_oanda_feed() -> None:
    if not settings.get("oanda_api_token"):
        oanda_restore_state.update({
            "status": "NOT_CONFIGURED",
            "running": False,
            "message": "OANDA credentials are not configured.",
        })
        return
    oanda_restore_state.update({
        "status": "RESTORING",
        "running": True,
        "message": "Restoring saved OANDA credentials and matched candle history.",
    })
    try:
        sync = _sync_live_visual_analysis_history()
        matched = sync.get("ok") and sync.get("source") == OANDA_HISTORY_SOURCE
        if matched:
            settings.mark_oanda_verified()
        oanda_restore_state.update({
            "status": "READY" if matched else "SYNC_WARNING",
            "running": False,
            "last_restored_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "dns_recovery": bool(sync.get("dns_recovery")),
            "message": (
                "Saved OANDA credentials restored and matched history synchronized."
                if matched
                else sync.get("primary_message") or sync.get("message") or "Saved credentials loaded, but OANDA history is not ready."
            ),
        })
    except Exception as exc:
        oanda_restore_state.update({
            "status": "RESTORE_FAILED",
            "running": False,
            "last_restored_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "message": f"Saved OANDA credentials loaded, but feed restore failed: {type(exc).__name__}.",
        })


def _sync_live_visual_analysis_history() -> Dict[str, Any]:
    with oanda_history_sync_lock:
        return _sync_live_visual_analysis_history_unlocked()


def _sync_live_visual_analysis_history_unlocked() -> Dict[str, Any]:
    """Refresh real OHLC data used by the TradingView-live visual workflow."""
    timeframes = ["5M", "15M", "1H", "4H", "1D"]
    primary = oanda_history.sync_recent_history(timeframes)
    if primary.get("ok"):
        sync = primary
    else:
        fallback = twelve_data_history.sync_recent_history(timeframes)
        sync = fallback | {
            "primary_provider": oanda_history.provider_name,
            "primary_status": primary.get("status"),
            "primary_message": primary.get("message"),
        }
    if sync.get("ok"):
        active_source = sync.get("source") or TWELVE_DATA_HISTORY_SOURCE
        if active_source == OANDA_HISTORY_SOURCE:
            archived = candle_store.archive_sources({PRELOADED_SOURCE, WARMUP_SOURCE})
            sync["stale_history_archived"] = archived
            sync["stale_history_archived_total"] = sum(archived.values())
        latest = candle_store.latest_candle_for_sources("5M", {active_source}) or {}
        candle_store.save_status(GoldAPIStatus(
            status="LIVE",
            provider_name=sync.get("provider") or twelve_data_history.provider_name,
            message=f"Latest XAU market history synced from {sync.get('provider') or 'the backend provider'}.",
            last_updated=latest.get("timestamp"),
            latest_price=latest.get("close"),
            is_running=True,
        ))
        settings.set_data_mode("REAL")
        settings.set_test_mode(False)
        live_builder.candle_builder.aggregate_all()
        engine_core.cache.clear()
        sync["analysis_cache_refreshed"] = True
    return sync


def _sync_btc_visual_analysis_history() -> Dict[str, Any]:
    timeframes = ["5M", "15M", "1H", "4H", "1D"]
    primary = binance_history.sync_recent_history(timeframes)
    if primary.get("ok"):
        sync = primary
    else:
        fallback = btc_twelve_data_history.sync_recent_history(timeframes)
        sync = fallback | {
            "primary_provider": binance_history.provider_name,
            "primary_status": primary.get("status"),
            "primary_message": primary.get("message"),
        }
    if sync.get("ok"):
        active_source = sync.get("source") or TWELVE_DATA_HISTORY_SOURCE
        if active_source == BINANCE_HISTORY_SOURCE:
            archived = btc_candle_store.archive_sources({PRELOADED_SOURCE, WARMUP_SOURCE})
            sync["stale_history_archived"] = archived
            sync["stale_history_archived_total"] = sum(archived.values())
        latest = btc_candle_store.latest_candle_for_sources("5M", {active_source}) or {}
        btc_candle_store.save_status(GoldAPIStatus(
            status="LIVE",
            provider_name=sync.get("provider") or btc_twelve_data_history.provider_name,
            message=f"Latest BTC market history synced from {sync.get('provider') or 'the backend provider'}.",
            last_updated=latest.get("timestamp"),
            latest_price=latest.get("close"),
            is_running=True,
        ))
        settings.set_data_mode("REAL")
        settings.set_test_mode(False)
        btc_engine_core.cache.clear()
        sync["analysis_cache_refreshed"] = True
    return sync


def _sync_market_chart_candle(symbol: str, timeframe: str) -> Dict[str, Any]:
    normalized = _normalize_market_symbol(symbol)
    if normalized == "BTCUSD":
        store = btc_candle_store
        primary = binance_history.sync_live_candle(timeframe)
        if primary.get("ok") and _source_has_candle_gap(store, timeframe, BINANCE_HISTORY_SOURCE):
            backfill = binance_history.sync_recent_history([timeframe])
            primary = binance_history.sync_live_candle(timeframe)
            primary["backfill"] = {
                "status": backfill.get("status"),
                "imported": (backfill.get("imported") or {}).get(timeframe, 0),
                "gap_repaired": not _source_has_candle_gap(store, timeframe, BINANCE_HISTORY_SOURCE),
            }
        sync = primary if primary.get("ok") else btc_twelve_data_history.sync_live_candle(timeframe) | {
            "primary_provider": binance_history.provider_name,
            "primary_status": primary.get("status"),
            "primary_message": primary.get("message"),
        }
    else:
        store = candle_store
        primary = oanda_history.sync_live_candle(timeframe)
        sync = primary if primary.get("ok") else twelve_data_history.sync_live_candle(timeframe) | {
            "primary_provider": oanda_history.provider_name,
            "primary_status": primary.get("status"),
            "primary_message": primary.get("message"),
        }
    latest = sync.get("last_candle") or {}
    if sync.get("ok") and latest:
        store.save_status(GoldAPIStatus(
            status="LIVE",
            provider_name=sync.get("provider") or "Market OHLC provider",
            message="Live chart candle synchronized.",
            last_updated=latest.get("timestamp"),
            latest_price=latest.get("close"),
            is_running=True,
        ))
    return sync


def _sync_market_chart_history(symbol: str, timeframe: str) -> Dict[str, Any]:
    normalized = _normalize_market_symbol(symbol)
    if normalized == "BTCUSD":
        primary = binance_history.sync_recent_history([timeframe])
        history = primary if primary.get("ok") else btc_twelve_data_history.sync_recent_history([timeframe]) | {
            "primary_provider": binance_history.provider_name,
            "primary_status": primary.get("status"),
            "primary_message": primary.get("message"),
        }
    else:
        primary = oanda_history.sync_recent_history([timeframe])
        history = primary if primary.get("ok") else twelve_data_history.sync_recent_history([timeframe]) | {
            "primary_provider": oanda_history.provider_name,
            "primary_status": primary.get("status"),
            "primary_message": primary.get("message"),
        }
    live = _sync_market_chart_candle(normalized, timeframe)
    live["history_refresh"] = {
        "status": history.get("status"),
        "provider": history.get("provider"),
        "source": history.get("source"),
        "imported": (history.get("imported") or {}).get(timeframe, 0),
        "errors": history.get("errors") or {},
    }
    return live


def _source_has_candle_gap(
    store: SQLiteCandleStore,
    timeframe: str,
    source: str,
    limit: int = 500,
) -> bool:
    frame = store.get_candles_df(timeframe, limit, {source})
    if len(frame) < 3:
        return True
    timeframe_minutes = {"1M": 1, "5M": 5, "15M": 15, "1H": 60, "4H": 240, "1D": 1440}[timeframe]
    gaps = frame.sort_index().index.to_series().diff().dt.total_seconds().div(60)
    return bool((gaps > timeframe_minutes * 1.5).any())


def _verifiable_indicator_panels(
    integrity_engine: DataIntegrityEngine,
    symbol: str,
    timeframe: str,
    limit: int,
    locked: Dict[str, Any],
) -> Dict[str, Any]:
    panels = integrity_engine.indicator_panels(timeframe, limit)
    panels["symbol"] = symbol
    base = panels.get("indicator_panels") or {}
    panels["indicator_panels"] = {
        "market_pressure": base.get("boys_selling") or [],
        "liquidity_pressure": base.get("bearishness") or [],
        "setup_quality": [],
        "indicator_snapshot": base.get("indicator_snapshot") or {
            "status": "WAITING",
            "source": "CLOSED_PROVIDER_CANDLES",
        },
        "market_pressure_score": base.get(
            "market_pressure_score",
            {"bullish": 0, "bearish": 0, "neutral": 100},
        ),
        "indicator_meta": {
            "market_pressure": {
                "name": "MACD Histogram",
                "parameters": "EMA 12, EMA 26, signal 9",
                "input": "Provider candle close",
            },
            "liquidity_pressure": {
                "name": "RSI 14",
                "parameters": "Wilder 14, centered at 50",
                "input": "Provider candle close",
            },
        },
    }
    panels["data_mode_lock"] = locked
    return panels


def _chart_candle_audit(symbol: str, timeframe: str, chart: Dict[str, Any]) -> Dict[str, Any]:
    candles = chart.get("candles") or []
    times = [int(item.get("time")) for item in candles if item.get("time") is not None]
    duplicates = len(times) - len(set(times))
    invalid = 0
    for item in candles:
        try:
            open_value = float(item.get("open"))
            high_value = float(item.get("high"))
            low_value = float(item.get("low"))
            close_value = float(item.get("close"))
        except (TypeError, ValueError):
            invalid += 1
            continue
        if min(open_value, high_value, low_value, close_value) <= 0 or high_value < max(open_value, close_value, low_value) or low_value > min(open_value, close_value, high_value):
            invalid += 1
    interval_seconds = {"1M": 60, "5M": 300, "15M": 900, "1H": 3600, "4H": 14400, "1D": 86400}[timeframe]
    sorted_times = sorted(set(times))
    gaps = [current - previous for previous, current in zip(sorted_times, sorted_times[1:]) if current - previous > interval_seconds * 1.5]
    sources = sorted({str(item.get("source")) for item in candles if item.get("source")})
    strict_continuity = symbol == "BTCUSD"
    continuity_ok = not gaps if strict_continuity else True
    verified = bool(candles) and invalid == 0 and duplicates == 0 and len(sources) == 1 and continuity_ok
    return {
        "status": "OHLC_CLEAN" if verified else "REVIEW",
        "candle_count": len(candles),
        "source_count": len(sources),
        "sources": sources,
        "invalid_ohlc": invalid,
        "duplicate_timestamps": duplicates,
        "gap_count": len(gaps),
        "max_gap_seconds": max(gaps) if gaps else 0,
        "continuity_rule": "24/7_STRICT" if strict_continuity else "MARKET_SESSIONS_ALLOWED",
        "latest_candle_time": max(times) if times else None,
    }


def _market_analysis(symbol: str, mode: str = "balanced") -> Dict[str, Any]:
    normalized = _normalize_market_symbol(symbol)
    if normalized == "XAUUSD":
        return _analysis_response(mode)
    locked = _locked_market_data_mode(normalized)
    result = btc_institutional_engine_v4.analyze(locked, mode)
    result["provider_status"] = btc_candle_store.load_status().to_dict()
    result["data_readiness"] = locked
    result["data_state"] = {
        "symbol": normalized,
        "data_state": locked.get("locked_mode"),
        "analysis_state": locked.get("analysis_state"),
    }
    return result


def _market_analysis_payload(analysis: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "symbol": analysis.get("symbol"),
        "trading_style": analysis.get("trading_style") or (analysis.get("key_zones") or {}).get("trading_style"),
        "version": APP_VERSION_LABEL,
        "analysis_explanation": analysis.get("analysis_explanation"),
        "final_decision": analysis.get("final_decision"),
        "gate_decision": analysis.get("gate_decision"),
        "score": analysis.get("signal", {}).get("score"),
        "bias": analysis.get("bias"),
        "current_price": analysis.get("current_price"),
        "analysis_ready": analysis.get("analysis_ready"),
        "data_mode": analysis.get("data_mode"),
        "analysis_data_source": analysis.get("analysis_data_source"),
        "provider_alignment": analysis.get("provider_alignment") or _provider_alignment(
            analysis.get("symbol") or "XAUUSD",
            analysis.get("analysis_data_source"),
        ),
        "data_integrity_check": analysis.get("data_integrity_check"),
        "htf_bias": analysis.get("htf_bias"),
        "liquidity_map": analysis.get("liquidity_map"),
        "poi_engine": analysis.get("poi_engine"),
        "confirmation_engine": analysis.get("confirmation_engine"),
        "score_engine": analysis.get("score_engine"),
        "signal": analysis.get("signal"),
        "trade_plan": analysis.get("trade_plan"),
        "trust_gate": analysis.get("trust_gate"),
        "session_framework": analysis.get("session_framework"),
        "key_zones": analysis.get("key_zones"),
        "news_intelligence": analysis.get("news_intelligence"),
        "xau_confluence": analysis.get("xau_confluence"),
        "diamond_auto_entry": analysis.get("diamond_auto_entry"),
        "strategy_governance": analysis.get("strategy_governance"),
        "feed_reconciliation": analysis.get("feed_reconciliation"),
        "execution_reality": analysis.get("execution_reality"),
        "decision_quality": analysis.get("decision_quality"),
        "market_regime": analysis.get("market_regime"),
        "asset_intelligence": analysis.get("asset_intelligence"),
        "closed_candle_alert": analysis.get("closed_candle_alert"),
        "automation": analysis.get("automation"),
        "workflow": analysis.get("workflow"),
    }


def _analyze_market_v4(
    symbol: str,
    selected_timeframe: str = "15M",
    trading_style: str = "SCALPING",
) -> Dict[str, Any]:
    normalized = _normalize_market_symbol(symbol)
    sync = _sync_live_visual_analysis_history() if normalized == "XAUUSD" else _sync_btc_visual_analysis_history()
    return _build_market_analysis_v4(normalized, selected_timeframe, sync, "MANUAL_API", trading_style=trading_style)


def _build_market_analysis_v4(
    symbol: str,
    selected_timeframe: str,
    sync: Dict[str, Any],
    trigger: str,
    closed_candle_time: Optional[int] = None,
    trading_style: str = "SCALPING",
) -> Dict[str, Any]:
    normalized = _normalize_market_symbol(symbol)
    style = _normalize_trading_style(trading_style)
    result = _market_analysis(normalized, engine_core.get_mode())
    result["visual_source"] = "TradingView Live"
    result["visual_symbol"] = MARKET_VISUAL_SYMBOLS[normalized]
    result["market_symbol"] = normalized
    result["trading_style"] = style
    result["provider_alignment"] = _provider_alignment(normalized, result.get("analysis_data_source"), sync)
    result["trust_gate"] = _market_trust_gate(normalized, result["provider_alignment"])
    _apply_analysis_trust_gate(result)
    result["session_framework"] = _market_session_framework(normalized, selected_timeframe)
    result["key_zones"] = _market_key_zones(
        normalized,
        selected_timeframe,
        analysis=result,
        session=result["session_framework"],
        trading_style=style,
    )
    governance_chart = (
        data_integrity_engine if normalized == "XAUUSD" else btc_data_integrity_engine
    ).chart_data(selected_timeframe, 500)
    challenger_snapshot = result["key_zones"].pop("challenger_snapshot", {})
    strategy_governance.record(
        normalized,
        normalize_timeframe(selected_timeframe),
        governance_chart.get("candles") or [],
        governance_chart.get("data_integrity", {}).get("chart_source"),
        result["key_zones"].get("feed_matched") is True,
        result["key_zones"],
        challenger_snapshot,
    )
    champion_validation = diamond_validation_lab.latest(normalized, normalize_timeframe(selected_timeframe))
    result["strategy_governance"] = strategy_governance.snapshot(
        normalized,
        normalize_timeframe(selected_timeframe),
        champion_validation,
    )
    expected_source = OANDA_HISTORY_SOURCE if normalized == "XAUUSD" else BINANCE_HISTORY_SOURCE
    result["feed_reconciliation"] = feed_reconciliation_engine.evaluate(
        normalized,
        normalize_timeframe(selected_timeframe),
        governance_chart,
        expected_source,
        sync,
    )
    result["news_intelligence"] = news_intelligence_engine.snapshot(normalized)
    result["market_regime"] = market_regime_engine.evaluate(
        normalized,
        normalize_timeframe(selected_timeframe),
        governance_chart.get("candles") or [],
        (result.get("trade_plan") or {}).get("direction")
        or (result.get("signal") or {}).get("direction"),
    )
    diamond_auto_entry_engine.apply(
        result,
        result["key_zones"],
        result["session_framework"],
        result["news_intelligence"],
    )
    _apply_session_confluence_gate(result)
    _apply_diamond_zone_context(result)
    news_intelligence_engine.apply_to_analysis(result, result["news_intelligence"])
    result["xau_confluence"] = xau_precision_engine.evaluate(
        result,
        result["key_zones"],
        result["session_framework"],
        result["news_intelligence"],
    )
    xau_precision_engine.apply_to_analysis(result, result["xau_confluence"])
    execution_reality = execution_reality_engine.evaluate(result, result["feed_reconciliation"])
    execution_reality_engine.apply_to_analysis(result, execution_reality)
    decision_quality = decision_quality_engine.evaluate(result, champion_validation)
    decision_quality_engine.apply_to_analysis(result, decision_quality)
    result["closed_candle_alert"] = closed_candle_alerts.record(result, normalize_timeframe(selected_timeframe))
    result["analysis_data_rule"] = (
        f"TradingView is the visual chart. Analysis uses freshly synced real {normalized} OHLC history "
        "from the backend market-data provider before running the setup engine."
    )
    result["live_ohlc_sync"] = sync
    result["automation"] = {
        "mode": "AUTO_CLOSED_CANDLE",
        "trigger": trigger,
        "closed_candle_time": closed_candle_time,
        "uses_completed_candles_only": True,
        "manual_analysis_required": False,
        "trading_style": style,
        "execution_timeframe": result["key_zones"].get("execution_timeframe"),
        "confirmation_timeframe": result["key_zones"].get("confirmation_timeframe"),
    }
    journal_entry = analysis_journal.record(result, selected_timeframe)
    result["journal_entry"] = journal_entry
    result["analysis_change"] = journal_entry.get("change")
    result["tracked_setup"] = setup_tracker.register(result, selected_timeframe, journal_entry.get("id"))
    diamond_history.record(result, selected_timeframe, result.get("tracked_setup"))
    return result


def _latest_completed_candle_time(chart: Dict[str, Any]) -> Optional[int]:
    times = []
    for candle in chart.get("candles") or []:
        if candle.get("is_complete") is False or candle.get("is_partial") is True:
            continue
        try:
            times.append(int(candle.get("time")))
        except (TypeError, ValueError):
            continue
    return max(times) if times else None


def _auto_analysis_signature(symbol: str, chart: Dict[str, Any]) -> tuple:
    normalized = _normalize_market_symbol(symbol)
    store = candle_store if normalized == "XAUUSD" else btc_candle_store
    expected_source = OANDA_HISTORY_SOURCE if normalized == "XAUUSD" else BINANCE_HISTORY_SOURCE
    source_counts = store.source_counts()
    required_history = tuple(
        (
            timeframe,
            int(source_counts.get(timeframe, {}).get(expected_source, 0)),
            store.latest_timestamp_for_sources(timeframe, {expected_source}, completed_only=True),
        )
        for timeframe in ["5M", "15M", "1H", "4H", "1D"]
    )
    return (
        chart.get("data_integrity", {}).get("chart_source"),
        expected_source,
        required_history,
    )


def _auto_analyze_market_if_due(
    symbol: str,
    timeframe: str,
    chart: Dict[str, Any],
    trading_style: str = "SCALPING",
) -> Dict[str, Any]:
    normalized = _normalize_market_symbol(symbol)
    tf = normalize_timeframe(timeframe)
    style = _normalize_trading_style(trading_style)
    state_key = f"{normalized}:{tf}:{style}"
    closed_candle_time = _latest_completed_candle_time(chart)
    input_signature = _auto_analysis_signature(normalized, chart)
    if closed_candle_time is None:
        return {
            "status": "WAITING_FOR_CLOSED_CANDLE",
            "mode": "AUTO_CLOSED_CANDLE",
            "ran": False,
            "analysis": None,
            "last_analyzed_candle_time": None,
        }

    with auto_analysis_lock:
        previous = auto_analysis_state.get(state_key) or {}
        if previous.get("in_progress"):
            return {
                "status": "SCANNING",
                "mode": "AUTO_CLOSED_CANDLE",
                "ran": False,
                "analysis": previous.get("analysis"),
                "last_analyzed_candle_time": previous.get("closed_candle_time"),
            }
        if (
            previous.get("closed_candle_time") == closed_candle_time
            and previous.get("input_signature") == input_signature
            and previous.get("analysis")
        ):
            return {
                "status": "CURRENT",
                "mode": "AUTO_CLOSED_CANDLE",
                "ran": False,
                "analysis": previous["analysis"],
                "last_analyzed_candle_time": closed_candle_time,
            }
        auto_analysis_state[state_key] = {**previous, "in_progress": True}

    try:
        sync = _sync_live_visual_analysis_history() if normalized == "XAUUSD" else _sync_btc_visual_analysis_history()
        result = _build_market_analysis_v4(
            normalized,
            tf,
            sync,
            "AUTO_CLOSED_CANDLE",
            closed_candle_time,
            style,
        )
        payload = _market_analysis_payload(result)
        with auto_analysis_lock:
            auto_analysis_state[state_key] = {
                "in_progress": False,
                "closed_candle_time": closed_candle_time,
                "input_signature": input_signature,
                "analysis": payload,
                "journal_entry": result.get("journal_entry"),
                "tracked_setup": result.get("tracked_setup"),
            }
        return {
            "status": "ANALYZED",
            "mode": "AUTO_CLOSED_CANDLE",
            "ran": True,
            "analysis": payload,
            "last_analyzed_candle_time": closed_candle_time,
            "journal_entry": result.get("journal_entry"),
            "tracked_setup": result.get("tracked_setup"),
        }
    except Exception as exc:
        with auto_analysis_lock:
            previous = auto_analysis_state.get(state_key) or {}
            auto_analysis_state[state_key] = {**previous, "in_progress": False, "error": str(exc)}
        return {
            "status": "AUTO_ANALYSIS_FAILED",
            "mode": "AUTO_CLOSED_CANDLE",
            "ran": False,
            "analysis": previous.get("analysis"),
            "last_analyzed_candle_time": previous.get("closed_candle_time"),
            "error": str(exc),
        }


def _market_session_framework(symbol: str, timeframe: str = "15M") -> Dict[str, Any]:
    normalized = _normalize_market_symbol(symbol)
    integrity_engine = data_integrity_engine if normalized == "XAUUSD" else btc_data_integrity_engine
    daily_chart = integrity_engine.chart_data("1D", 100)
    intraday_chart = integrity_engine.chart_data("5M", 1000)
    context = integrity_engine.timeframe_snapshot(normalize_timeframe(timeframe))
    source = (
        intraday_chart.get("data_integrity", {}).get("chart_source")
        or daily_chart.get("data_integrity", {}).get("chart_source")
    )
    result = session_framework_engine.calculate(
        daily_chart.get("candles") or [],
        intraday_chart.get("candles") or [],
        context,
        source,
    )
    result["symbol"] = normalized
    result["timeframe"] = normalize_timeframe(timeframe)
    result["generated_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    return result


def _market_key_zones(
    symbol: str,
    timeframe: str = "15M",
    chart: Optional[Dict[str, Any]] = None,
    analysis: Optional[Dict[str, Any]] = None,
    session: Optional[Dict[str, Any]] = None,
    trading_style: str = "SCALPING",
) -> Dict[str, Any]:
    normalized = _normalize_market_symbol(symbol)
    tf = normalize_timeframe(timeframe)
    style = _normalize_trading_style(trading_style)
    style_profile = diamond_zone_engine.trading_style_profile(style)
    required_timeframes = list(style_profile["weights"])
    integrity_engine = data_integrity_engine if normalized == "XAUUSD" else btc_data_integrity_engine
    expected_source = OANDA_HISTORY_SOURCE if normalized == "XAUUSD" else BINANCE_HISTORY_SOURCE
    generated_at = pd.Timestamp.now(tz="UTC").isoformat()

    def calculate_timeframe(zone_timeframe: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        chart_payload = payload or integrity_engine.chart_data(zone_timeframe, 260)
        source = chart_payload.get("data_integrity", {}).get("chart_source")
        zone_result = diamond_zone_engine.calculate(
            chart_payload.get("candles") or [],
            zone_timeframe,
            source,
            session or {},
            analysis or {},
            normalized,
        )
        zone_result["expected_source"] = expected_source
        zone_result["feed_matched"] = source == expected_source
        zone_result["execution_trusted"] = bool(
            zone_result["feed_matched"] and zone_result.get("status") == "READY"
        )
        zone_result["trading_style"] = style
        zone_result["profile_label"] = style_profile["label"]
        zone_result["execution_timeframe"] = style_profile["execution_timeframe"]
        zone_result["confirmation_timeframe"] = style_profile["confirmation_timeframe"]
        zone_result["required_timeframes"] = required_timeframes
        zone_result["timeframe_role"] = (
            "EXECUTION" if zone_timeframe == style_profile["execution_timeframe"]
            else "CONFIRMATION" if zone_timeframe == style_profile["confirmation_timeframe"]
            else "OUTSIDE_PROFILE"
        )
        zone_result["style_timeframe_eligible"] = zone_timeframe in required_timeframes
        if not zone_result["feed_matched"]:
            zone_result["scope"] = "RESEARCH_ONLY"
        zone_result["symbol"] = normalized
        zone_result["generated_at"] = generated_at
        return zone_result

    selected_chart = chart or integrity_engine.chart_data(tf, 500)
    result = calculate_timeframe(tf, selected_chart)
    challenger = diamond_challenger_engine.calculate(
        selected_chart.get("candles") or [],
        tf,
        selected_chart.get("data_integrity", {}).get("chart_source"),
        session or {},
        analysis or {},
        normalized,
    )
    challenger["expected_source"] = expected_source
    challenger["feed_matched"] = challenger.get("source") == expected_source
    challenger["execution_trusted"] = False
    challenger["scope"] = "SHADOW_RESEARCH_ONLY"
    result["challenger_snapshot"] = challenger
    result["strategy_comparison"] = {
        "champion": {
            "version": result.get("engine_version") or "DIAMOND_V6.1",
            "role": "LIVE_CHAMPION",
            "current_gate": (result.get("gate_funnel") or {}).get("current_gate"),
            "confirmed_entries": len(result.get("entry_events") or []),
        },
        "challenger": {
            "version": challenger.get("engine_version") or CHALLENGER_VERSION,
            "role": "SHADOW_ONLY",
            "current_gate": (challenger.get("gate_funnel") or {}).get("current_gate"),
            "confirmed_entries": len(challenger.get("entry_events") or []),
        },
        "challenger_can_place_trades": False,
    }
    timeframe_results: Dict[str, Dict[str, Any]] = {}
    for zone_timeframe in required_timeframes:
        timeframe_results[zone_timeframe] = (
            result if zone_timeframe == tf else calculate_timeframe(zone_timeframe)
        )
    mtf_confluence = diamond_zone_engine.combine_timeframes(timeframe_results, style)
    result["mtf_confluence"] = mtf_confluence
    result["mtf_state"] = mtf_confluence.get("state")
    result["mtf_risk_filter"] = mtf_confluence.get("risk_filter")
    return result


def _apply_diamond_zone_context(result: Dict[str, Any]) -> None:
    key_zones = result.get("key_zones") or {}
    signal = result.setdefault("signal", {})
    plan = result.get("trade_plan") or {}
    primary = key_zones.get("primary_zone") or {}
    entry_event = key_zones.get("latest_entry_event") or {}
    mtf = key_zones.get("mtf_confluence") or {}
    signal["diamond_zone_status"] = key_zones.get("status")
    signal["diamond_zone_bias"] = key_zones.get("directional_bias")
    signal["diamond_zone_line"] = primary.get("line")
    signal["diamond_zone_role"] = primary.get("role")
    signal["diamond_zone_lifecycle"] = primary.get("lifecycle")
    signal["diamond_zone_quality"] = key_zones.get("quality_grade")
    signal["diamond_zone_confirmation"] = key_zones.get("confirmation_state")
    signal["diamond_zone_rejection"] = key_zones.get("rejection_status")
    signal["diamond_zone_rejection_score"] = key_zones.get("rejection_score")
    signal["diamond_zone_strength"] = key_zones.get("zone_strength_score")
    signal["diamond_zone_execution_quality"] = key_zones.get("execution_quality")
    signal["diamond_zone_invalidation"] = key_zones.get("invalidation_level")
    signal["diamond_mtf_state"] = mtf.get("state")
    signal["diamond_mtf_score"] = mtf.get("score")
    signal["diamond_zone_trusted"] = key_zones.get("execution_trusted") is True
    signal["diamond_entry_status"] = key_zones.get("entry_event_status")
    signal["diamond_entry_side"] = entry_event.get("entry_side")
    signal["diamond_entry_price"] = entry_event.get("execution_entry")
    signal["diamond_entry_quality"] = entry_event.get("quality_score")
    signal["diamond_entry_confirmed_at"] = entry_event.get("confirmation_time")
    signal["diamond_trading_style"] = key_zones.get("trading_style")
    signal["diamond_execution_timeframe"] = key_zones.get("execution_timeframe")
    signal["diamond_confirmation_timeframe"] = key_zones.get("confirmation_timeframe")
    if key_zones.get("status") != "READY":
        signal["diamond_zone_aligned"] = None
        return
    if not key_zones.get("execution_trusted"):
        signal["diamond_zone_aligned"] = None
        if plan:
            plan["diamond_zone_context"] = "RESEARCH_ONLY"
            plan["diamond_zone_line"] = primary.get("line")
            plan["diamond_zone_quality"] = key_zones.get("quality_grade")
            plan["diamond_zone_execution_quality"] = key_zones.get("execution_quality")
            plan["diamond_mtf_state"] = mtf.get("state")
        result.setdefault("analysis_explanation", {})["diamond_zone"] = "Diamond Zone is research-only until the visual and analysis feeds match."
        return

    direction = str(plan.get("direction") or signal.get("direction") or "WAIT").upper()
    zone_bias = str(key_zones.get("directional_bias") or "WAIT").upper()
    selected_aligned = bool(
        (direction == "BUY" and zone_bias == "BUY_CONTEXT")
        or (direction == "SELL" and zone_bias == "SELL_CONTEXT")
    )
    selected_opposed = bool(
        (direction == "BUY" and zone_bias == "SELL_CONTEXT")
        or (direction == "SELL" and zone_bias == "BUY_CONTEXT")
    )
    mtf_direction = str(mtf.get("direction") or "MIXED").upper()
    mtf_aligned = bool(
        (direction == "BUY" and mtf_direction == "BULLISH")
        or (direction == "SELL" and mtf_direction == "BEARISH")
    )
    mtf_opposed = bool(
        (direction == "BUY" and mtf_direction == "BEARISH")
        or (direction == "SELL" and mtf_direction == "BULLISH")
    )
    quality = str(key_zones.get("quality_grade") or "C").upper()
    confirmation = str(key_zones.get("confirmation_state") or "WAITING").upper()
    strong_selected_conflict = selected_opposed and quality in {"A+", "A"} and confirmation.startswith("CONFIRMED_")
    strong_mtf_conflict = mtf_opposed and float(mtf.get("confidence") or 0) >= 50
    blocked_by_conflict = strong_selected_conflict or strong_mtf_conflict
    aligned = (selected_aligned or mtf_aligned) and not blocked_by_conflict
    signal["diamond_zone_aligned"] = aligned if direction in {"BUY", "SELL"} else None
    signal["diamond_zone_gate"] = "BLOCKED" if blocked_by_conflict else "ALIGNED" if aligned else "WAIT"
    if plan:
        plan["diamond_zone_context"] = "CONFLICT" if blocked_by_conflict else "ALIGNED" if aligned else "WAIT"
        plan["diamond_zone_line"] = primary.get("line")
        plan["diamond_zone_quality"] = key_zones.get("quality_grade")
        plan["diamond_zone_lifecycle"] = primary.get("lifecycle")
        plan["diamond_zone_confirmation"] = key_zones.get("confirmation_state")
        plan["diamond_zone_rejection"] = key_zones.get("rejection_status")
        plan["diamond_zone_strength"] = key_zones.get("zone_strength_score")
        plan["diamond_zone_execution_quality"] = key_zones.get("execution_quality")
        plan["diamond_zone_invalidation"] = key_zones.get("invalidation_level")
        plan["diamond_mtf_state"] = mtf.get("state")
        plan["diamond_mtf_score"] = mtf.get("score")
    explanation = result.setdefault("analysis_explanation", {})
    explanation["diamond_zone"] = key_zones.get("next_trigger")
    if direction not in {"BUY", "SELL"} or not blocked_by_conflict:
        return

    reasons = []
    if strong_mtf_conflict:
        required_timeframes = mtf.get("required_timeframes") or key_zones.get("required_timeframes") or []
        profile_name = mtf.get("profile_label") or key_zones.get("profile_label") or "Diamond Zone"
        timeframe_pair = "/".join(str(item) for item in required_timeframes)
        profile_context = f"{profile_name} ({timeframe_pair})" if timeframe_pair else profile_name
        reasons.append(
            f"Diamond Zone {profile_context} confluence is {mtf_direction.lower()} ({mtf.get('score', 0)}), opposite the {direction.lower()} plan."
        )
    if strong_selected_conflict:
        reasons.append(
            f"Selected timeframe has a confirmed Grade {quality} {zone_bias.replace('_', ' ').lower()}."
        )
    reason = " ".join(reasons)
    missing = plan.setdefault("missing_conditions", [])
    if reason and reason not in missing:
        missing.append(reason)
    signal["execution_allowed"] = False
    if str(plan.get("status") or "").upper() == "ACTIONABLE":
        plan["status"] = "CANDIDATE"
        plan["label"] = f"Candidate {direction.title()} Setup - Diamond Zone Confirmation Required"
        result["final_decision"] = plan["label"]
    explanation["diamond_zone_risk"] = reason
    explanation["next_trigger"] = reason


def _apply_session_confluence_gate(result: Dict[str, Any]) -> None:
    framework = result.get("session_framework") or {}
    k_trend = framework.get("k_trend") or {}
    signal = result.setdefault("signal", {})
    signal["session_stance"] = framework.get("stance")
    signal["session_confluence_score"] = framework.get("confluence_score")
    signal["session_position"] = framework.get("position")
    signal["k_trend_regime"] = k_trend.get("regime")
    signal["k_trend_score"] = k_trend.get("score")
    signal["k_trend_confirmation"] = k_trend.get("confirmation")
    signal["k_trend_next_target"] = k_trend.get("next_target")
    if framework.get("status") != "READY":
        signal["session_context_aligned"] = None
        return

    plan = result.get("trade_plan") or {}
    if plan:
        plan["k_trend_regime"] = k_trend.get("regime")
        plan["k_trend_score"] = k_trend.get("score")
        plan["k_trend_confirmation"] = k_trend.get("confirmation")
        plan["k_trend_next_target"] = k_trend.get("next_target")
        plan["k_trend_next_target_label"] = k_trend.get("next_target_label")
    direction = str(plan.get("direction") or signal.get("direction") or "WAIT").upper()
    aligned = bool(
        (direction == "BUY" and framework.get("buy_context"))
        or (direction == "SELL" and framework.get("sell_context"))
    )
    signal["session_context_aligned"] = aligned if direction in {"BUY", "SELL"} else None
    if direction not in {"BUY", "SELL"} or not (result.get("trust_gate") or {}).get("trusted"):
        return

    reasons = []
    if not aligned:
        reasons.append(f"Session position is {str(framework.get('position') or 'mixed').replace('_', ' ').lower()}.")
    if framework.get("range_extension"):
        reasons.append("Price has reached the outer transparent daily-range band; wait for a pullback or new confirmation.")
    if not reasons:
        return

    missing = plan.setdefault("missing_conditions", [])
    for reason in reasons:
        if reason not in missing:
            missing.append(reason)
    plan["session_context"] = "WAIT"
    signal["execution_allowed"] = False
    if str(plan.get("status") or "").upper() == "ACTIONABLE":
        plan["status"] = "CANDIDATE"
        plan["label"] = f"Candidate {direction.title()} Setup - Session Confirmation Required"
        result["final_decision"] = plan["label"]
    explanation = result.setdefault("analysis_explanation", {})
    explanation["session_context"] = " ".join(reasons)
    explanation["next_trigger"] = reasons[0]


def _refresh_tracked_setups(symbol: str) -> int:
    normalized = _normalize_market_symbol(symbol)
    store = candle_store if normalized == "XAUUSD" else btc_candle_store
    refreshed = 0
    for setup in setup_tracker.active(normalized):
        source = setup.get("analysis_source")
        sources = {source} if source else None
        frame = store.get_candles_df(setup["timeframe"], 1000, sources)
        if frame.empty:
            continue
        if "is_complete" in frame.columns:
            frame = frame[frame["is_complete"] == 1]
        candles = [
            {
                "time": timestamp.isoformat(),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
            }
            for timestamp, row in frame.iterrows()
        ]
        setup_tracker.evaluate(setup["id"], candles)
        refreshed += 1
    return refreshed


def _reconcile_diamond_history(symbol: str) -> int:
    normalized = _normalize_market_symbol(symbol)
    store = candle_store if normalized == "XAUUSD" else btc_candle_store
    expected_source = OANDA_HISTORY_SOURCE if normalized == "XAUUSD" else BINANCE_HISTORY_SOURCE
    frames: Dict[str, list[Dict[str, Any]]] = {}
    for timeframe in ["5M", "15M", "1H", "4H", "1D"]:
        frame = store.get_candles_df(timeframe, 3000, {expected_source})
        if frame.empty:
            frames[timeframe] = []
            continue
        if "is_complete" in frame.columns:
            frame = frame[frame["is_complete"] == 1]
        frames[timeframe] = [
            {
                "time": int(timestamp.timestamp()),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "is_complete": True,
            }
            for timestamp, row in frame.iterrows()
        ]
    return diamond_history.reconcile(normalized, frames)


def _market_trust_gate(symbol: str, provider_alignment: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_market_symbol(symbol)
    integrity_engine = data_integrity_engine if normalized == "XAUUSD" else btc_data_integrity_engine
    expected_source = provider_alignment.get("expected_analysis_source")
    timeframe_audits: Dict[str, Any] = {}
    for timeframe in ["5M", "15M", "1H", "4H", "1D"]:
        chart = integrity_engine.chart_data(timeframe, 500)
        audit = _chart_candle_audit(normalized, timeframe, chart)
        active_source = chart.get("data_integrity", {}).get("chart_source")
        audit["active_source"] = active_source
        audit["expected_source"] = expected_source
        audit["source_matched"] = active_source == expected_source
        timeframe_audits[timeframe] = audit
    clean_timeframes = all(item.get("status") == "OHLC_CLEAN" for item in timeframe_audits.values())
    source_matched = all(item.get("source_matched") for item in timeframe_audits.values())
    provider_matched = bool(provider_alignment.get("matched"))
    trusted = provider_matched and source_matched and clean_timeframes
    if trusted:
        status = "TRUSTED"
        reason = "Matched provider and all required timeframe candle audits passed."
    elif not provider_matched or not source_matched:
        status = "RESEARCH_ONLY"
        reason = "Analysis feed does not match the TradingView market source. Actionable prices are blocked."
    else:
        status = "BLOCKED"
        reason = "One or more required timeframe candle audits need review. Actionable prices are blocked."
    return {
        "status": status,
        "trusted": trusted,
        "execution_allowed": trusted,
        "provider_matched": provider_matched,
        "all_sources_matched": source_matched,
        "all_timeframes_clean": clean_timeframes,
        "expected_source": expected_source,
        "reason": reason,
        "timeframes": timeframe_audits,
    }


def _apply_analysis_trust_gate(result: Dict[str, Any]) -> None:
    trust = result.get("trust_gate") or {}
    signal = result.setdefault("signal", {})
    signal["trust_status"] = trust.get("status")
    if trust.get("trusted"):
        signal["execution_allowed"] = bool(signal.get("execution_allowed"))
        return
    reason = trust.get("reason") or "Market data trust verification is required."
    result["analysis_scope"] = "RESEARCH_ONLY"
    result["real_signal_allowed"] = False
    result["gate_decision"] = trust.get("status") or "BLOCKED"
    result["final_decision"] = "Research Only - Feed Verification Required"
    signal.update({
        "direction": "WAIT",
        "status": "RESEARCH_ONLY",
        "execution_allowed": False,
        "trade_plan_valid": False,
        "final_action": reason,
    })
    result["trade_plan"] = {
        "status": "BLOCKED_BY_DATA_TRUST",
        "label": "Research Only",
        "direction": "WAIT",
        "order_type": "NONE",
        "entry_price": None,
        "stop_loss": None,
        "take_profit_levels": [],
        "risk_reward": None,
        "action": reason,
        "trigger": "Connect the matched provider and pass all candle audits.",
        "missing_conditions": [reason],
        "evidence_only": True,
    }
    explanation = result.setdefault("analysis_explanation", {})
    explanation.update({
        "direction": "WAIT",
        "summary": reason,
        "reason": "DATA_TRUST_GATE",
        "next_trigger": "Matched provider plus clean 5M/15M/1H/4H/1D audits.",
        "data_mode_warning": reason,
    })
    workflow = result.get("workflow")
    if isinstance(workflow, list):
        workflow.append({
            "name": "Data Trust Gate",
            "timeframe": "All",
            "status": trust.get("status"),
            "confidence": 100 if trust.get("trusted") else 0,
            "reason": reason,
        })


def _provider_alignment(symbol: str, source: Optional[str], sync: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized = _normalize_market_symbol(symbol)
    expected = {
        "XAUUSD": {
            "visual_symbol": "OANDA:XAUUSD",
            "analysis_source": OANDA_HISTORY_SOURCE,
            "provider": oanda_history.provider_name,
        },
        "BTCUSD": {
            "visual_symbol": "BINANCE:BTCUSDT",
            "analysis_source": BINANCE_HISTORY_SOURCE,
            "provider": binance_history.provider_name,
        },
    }[normalized]
    matched = source == expected["analysis_source"]
    return {
        "status": "MATCHED" if matched else "FALLBACK",
        "matched": matched,
        "visual_symbol": expected["visual_symbol"],
        "expected_analysis_source": expected["analysis_source"],
        "active_analysis_source": source or "NO_DATA",
        "provider": expected["provider"],
        "fallback_provider": (sync or {}).get("provider") if not matched else None,
        "reason": (
            "TradingView and the analysis engine use the same market feed and symbol."
            if matched
            else (sync or {}).get("primary_message") or "Matched provider history is not ready; real fallback history is active."
        ),
    }


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
