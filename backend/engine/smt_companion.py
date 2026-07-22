from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict

from engine.xauusd_provider import BinanceHistoryService, OandaHistoryService, normalize_timeframe


class SMTCompanionFeedService:
    """Fetch companion candles in the background and keep them out of primary stores."""

    CACHE_SECONDS = {"5M": 45, "15M": 90, "1H": 180, "4H": 300, "1D": 900}

    def __init__(self, settings: Any, xau_store: Any, btc_store: Any):
        self.settings = settings
        self.xag = OandaHistoryService(settings, xau_store)
        self.xag.instrument = "XAG_USD"
        self.xag.provider_name = "OANDA XAG_USD Mid OHLC"
        self.eth = BinanceHistoryService(btc_store)
        self.eth.market_symbol = "ETHUSDT"
        self.eth.provider_name = "Binance ETHUSDT Spot OHLC"
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._running: set[str] = set()
        self._lock = threading.RLock()

    def snapshot(self, symbol: str, timeframe: str, limit: int = 220) -> Dict[str, Any]:
        market = str(symbol or "UNKNOWN").upper()
        tf = normalize_timeframe(timeframe)
        key = f"{market}:{tf}"
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            max_age = int(self.CACHE_SECONDS.get(tf, 120))
            if cached and now - float(cached.get("cached_at") or 0) <= max_age:
                return self._public(cached, cache_hit=True)
            if key not in self._running:
                self._running.add(key)
                threading.Thread(
                    target=self._refresh,
                    args=(key, market, tf, limit),
                    name=f"smt-companion-{market.lower()}-{tf.lower()}",
                    daemon=True,
                ).start()
            if cached:
                stale = dict(cached)
                stale["refreshing"] = True
                return self._public(stale, cache_hit=True)
        companion = "XAGUSD" if market == "XAUUSD" else "ETHUSD" if market == "BTCUSD" else None
        provider_symbol = "OANDA:XAGUSD" if market == "XAUUSD" else "BINANCE:ETHUSDT" if market == "BTCUSD" else None
        return {
            "status": "FETCHING" if companion else "UNAVAILABLE",
            "companion_symbol": companion,
            "provider_symbol": provider_symbol,
            "candles": [],
            "reason": "Loading synchronized companion candles." if companion else "No SMT companion is configured.",
            "cache_hit": False,
            "refreshing": bool(companion),
        }

    def refresh_now(self, symbol: str, timeframe: str, limit: int = 220) -> Dict[str, Any]:
        market = str(symbol or "UNKNOWN").upper()
        tf = normalize_timeframe(timeframe)
        key = f"{market}:{tf}"
        with self._lock:
            self._running.add(key)
        self._refresh(key, market, tf, limit)
        with self._lock:
            cached = self._cache.get(key)
        return self._public(cached or {}, cache_hit=False)

    def _refresh(self, key: str, market: str, timeframe: str, limit: int) -> None:
        started = time.perf_counter()
        try:
            if market == "XAUUSD":
                token = str(self.settings.get("oanda_api_token") or "").strip()
                environment = str(self.settings.get("oanda_environment") or "practice").lower()
                if not token:
                    result = {
                        "status": "UNAVAILABLE",
                        "source_status": "OANDA_TOKEN_MISSING",
                        "companion_symbol": "XAGUSD",
                        "provider_symbol": "OANDA:XAGUSD",
                        "candles": [],
                        "reason": "XAG companion verification requires the saved OANDA connection.",
                    }
                else:
                    candles = self.xag._fetch_timeframe(timeframe, token, environment, count=limit)
                    result = {
                        "status": "READY" if candles else "UNAVAILABLE",
                        "source_status": "OANDA_XAGUSD_MATCHED" if candles else "OANDA_XAGUSD_EMPTY",
                        "companion_symbol": "XAGUSD",
                        "provider_symbol": "OANDA:XAGUSD",
                        "candles": candles,
                        "reason": "Timestamp-matched XAGUSD candles are ready." if candles else "OANDA returned no XAGUSD companion candles.",
                    }
            elif market == "BTCUSD":
                candles = self.eth._fetch_timeframe(timeframe, limit=limit)
                result = {
                    "status": "READY" if candles else "UNAVAILABLE",
                    "source_status": "BINANCE_ETHUSDT_MATCHED" if candles else "BINANCE_ETHUSDT_EMPTY",
                    "companion_symbol": "ETHUSD",
                    "provider_symbol": "BINANCE:ETHUSDT",
                    "candles": candles,
                    "reason": "Timestamp-matched ETHUSDT candles are ready." if candles else "Binance returned no ETHUSDT companion candles.",
                }
            else:
                result = {
                    "status": "UNAVAILABLE",
                    "source_status": "UNSUPPORTED_SYMBOL",
                    "companion_symbol": None,
                    "provider_symbol": None,
                    "candles": [],
                    "reason": "No SMT companion is configured for this market.",
                }
        except Exception:
            result = {
                "status": "UNAVAILABLE",
                "source_status": "COMPANION_CONNECTION_FAILED",
                "companion_symbol": "XAGUSD" if market == "XAUUSD" else "ETHUSD" if market == "BTCUSD" else None,
                "provider_symbol": "OANDA:XAGUSD" if market == "XAUUSD" else "BINANCE:ETHUSDT" if market == "BTCUSD" else None,
                "candles": [],
                "reason": "The companion market could not be verified. SMT remains neutral.",
            }
        result.update({
            "cached_at": time.monotonic(),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "refreshing": False,
        })
        with self._lock:
            self._cache[key] = result
            self._running.discard(key)

    @staticmethod
    def _public(value: Dict[str, Any], cache_hit: bool) -> Dict[str, Any]:
        if not value:
            return {"status": "UNAVAILABLE", "candles": [], "cache_hit": cache_hit}
        result = dict(value)
        result.pop("cached_at", None)
        result["cache_hit"] = cache_hit
        return result
