from __future__ import annotations

import tempfile
import unittest
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from engine.xauusd_provider import (
    BINANCE_HISTORY_SOURCE,
    OANDA_HISTORY_SOURCE,
    BinanceHistoryService,
    GoldAPIStatus,
    OandaHistoryService,
    ProviderSettings,
    SQLiteCandleStore,
)
from engine.data_integrity import CandleHistoryAlignmentEngine, DataIntegrityEngine
from engine.pro_analysis import ProAnalysisEngineV3


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class ProviderAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.temp_dir.name)
        self.settings = ProviderSettings(root / "settings.json")
        self.store = SQLiteCandleStore(root / "candles.sqlite")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_binance_maps_completed_btcusdt_klines(self) -> None:
        payload = [[1767225600000, "100", "110", "95", "105", "12", 1767225899999]]
        service = BinanceHistoryService(self.store)
        with patch("engine.xauusd_provider.requests.get", return_value=FakeResponse(payload)):
            result = service.sync_recent_history(["5M"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], BINANCE_HISTORY_SOURCE)
        candle = self.store.latest_candle_for_sources("5M", {BINANCE_HISTORY_SOURCE})
        self.assertEqual(candle["close"], 105.0)

    def test_binance_live_sync_keeps_the_forming_candle_partial(self) -> None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        current_open = now_ms - (now_ms % 300_000)
        payload = [
            [current_open - 300_000, "100", "110", "95", "105", "12", current_open - 1],
            [current_open, "105", "112", "104", "111", "8", current_open + 299_999],
        ]
        service = BinanceHistoryService(self.store)
        with patch("engine.xauusd_provider.requests.get", return_value=FakeResponse(payload)):
            result = service.sync_live_candle("5M")

        frame = self.store.get_candles_df("5M", 10, {BINANCE_HISTORY_SOURCE})
        self.assertTrue(result["ok"])
        self.assertTrue(result["forming_candle"])
        self.assertEqual(int(frame.iloc[-1]["is_complete"]), 0)
        self.assertEqual(int(frame.iloc[-1]["is_partial"]), 1)
        self.assertEqual(float(frame.iloc[-1]["close"]), 111.0)

    def test_analysis_frames_exclude_forming_candles(self) -> None:
        completed_time = "2026-01-01T00:00:00+00:00"
        partial_time = "2026-01-01T00:05:00+00:00"
        self.store.upsert_candle(
            "5M", completed_time, 100, 105, 99, 104,
            source=BINANCE_HISTORY_SOURCE, is_complete=True, is_partial=False,
        )
        self.store.upsert_candle(
            "5M", partial_time, 104, 110, 103, 109,
            source=BINANCE_HISTORY_SOURCE, is_complete=False, is_partial=True,
        )

        frames = ProAnalysisEngineV3(self.store)._frames("fast", {})

        self.assertEqual(len(frames["5M"]), 1)
        self.assertEqual(float(frames["5M"].iloc[-1]["close"]), 104.0)

    def test_oanda_uses_only_completed_mid_candles(self) -> None:
        self.settings.update({"oanda_api_token": "test-token", "oanda_environment": "practice"})
        payload = {
            "candles": [
                {"complete": True, "time": "2026-01-01T00:00:00Z", "mid": {"o": "100", "h": "110", "l": "95", "c": "105"}},
                {"complete": False, "time": "2026-01-01T00:05:00Z", "mid": {"o": "105", "h": "111", "l": "104", "c": "110"}},
            ]
        }
        service = OandaHistoryService(self.settings, self.store)
        with patch.object(service, "_endpoint_resolution_error", return_value=None), \
                patch("engine.xauusd_provider.requests.get", return_value=FakeResponse(payload)):
            result = service.sync_recent_history(["5M"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], OANDA_HISTORY_SOURCE)
        self.assertEqual(self.store.source_counts()["5M"][OANDA_HISTORY_SOURCE], 1)

    def test_oanda_missing_token_reports_honest_fallback_reason(self) -> None:
        service = OandaHistoryService(self.settings, self.store)
        result = service.sync_recent_history(["5M"])

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "OANDA_TOKEN_MISSING")

    def test_oanda_verification_checks_xau_candles_without_echoing_token(self) -> None:
        payload = {
            "candles": [
                {"complete": False, "time": "2026-01-01T00:05:00Z", "mid": {"o": "100", "h": "111", "l": "99", "c": "110"}},
            ]
        }
        service = OandaHistoryService(self.settings, self.store)
        with patch.object(service, "_endpoint_resolution_error", return_value=None), \
                patch("engine.xauusd_provider.requests.get", return_value=FakeResponse(payload)):
            result = service.verify_connection("private-test-token", "practice")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["instrument"], "XAU_USD")
        self.assertNotIn("private-test-token", str(result))

    def test_oanda_verification_recovers_from_loopback_dns_without_echoing_token(self) -> None:
        service = OandaHistoryService(self.settings, self.store)
        loopback = [(2, 1, 6, "", ("127.0.0.1", 443))]
        payload = {
            "candles": [
                {"complete": False, "time": "2026-01-01T00:05:00Z", "mid": {"o": "100", "h": "111", "l": "99", "c": "110"}},
            ]
        }

        def recover(*_args, **_kwargs):
            service._transport_state.dns_recovery = True
            return payload

        with patch("engine.xauusd_provider.socket.getaddrinfo", return_value=loopback), \
                patch.object(service, "_request_via_public_dns", side_effect=recover) as recovery, \
                patch("engine.xauusd_provider.requests.get") as request:
            result = service.verify_connection("private-test-token", "practice")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["dns_recovery"])
        self.assertNotIn("private-test-token", str(result))
        recovery.assert_called_once()
        request.assert_not_called()

    def test_verified_oanda_token_persists_without_being_exposed(self) -> None:
        with patch.dict(os.environ, {"OANDA_API_TOKEN": ""}):
            saved = self.settings.save_verified_oanda("private-persistent-token", "live", "2026-01-01T00:00:00+00:00")
            reloaded = ProviderSettings(self.settings.settings_path)

            self.assertTrue(saved["oanda_api_token"])
            self.assertEqual(saved["oanda_credential_state"], "VERIFIED")
            self.assertEqual(saved["oanda_environment"], "live")
            self.assertEqual(reloaded.get("oanda_api_token"), "private-persistent-token")
            self.assertNotIn("private-persistent-token", str(reloaded.masked_status()))
            raw_settings = self.settings.settings_path.read_text(encoding="utf-8")
            if os.name == "nt":
                self.assertNotIn("private-persistent-token", raw_settings)
                self.assertIn("oanda_api_token_protected", raw_settings)

    def test_same_provider_active_candle_move_is_not_a_data_gap(self) -> None:
        timestamp = datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
        self.store.insert_candles("15M", [{
            "timestamp": timestamp,
            "open": 4100.0,
            "high": 4110.0,
            "low": 4098.0,
            "close": 4100.0,
        }], OANDA_HISTORY_SOURCE)
        self.store.save_status(GoldAPIStatus(
            status="LIVE",
            provider_name="OANDA XAU_USD Mid OHLC",
            latest_price=4110.0,
            last_updated=timestamp,
            is_running=True,
        ))

        alignment = CandleHistoryAlignmentEngine(self.store).check("15M")

        self.assertEqual(alignment["alignment_status"], "ALIGNED")
        self.assertTrue(alignment["analysis_allowed"])

    def test_chart_locks_to_one_provider_and_builds_standard_indicators(self) -> None:
        base = pd.Timestamp("2026-01-01T00:00:00Z")
        fallback = []
        matched = []
        for index in range(60):
            fallback_price = 90 + index * 0.1
            fallback.append({
                "timestamp": (base + pd.Timedelta(minutes=index * 5)).isoformat(),
                "open": fallback_price,
                "high": fallback_price + 1,
                "low": fallback_price - 1,
                "close": fallback_price + 0.25,
            })
            matched_price = 100 + index * 0.2
            matched.append({
                "timestamp": (base + pd.Timedelta(days=1, minutes=index * 5)).isoformat(),
                "open": matched_price,
                "high": matched_price + 1,
                "low": matched_price - 1,
                "close": matched_price + 0.4,
            })
        self.store.insert_candles("5M", fallback, OANDA_HISTORY_SOURCE)
        self.store.insert_candles("5M", matched, BINANCE_HISTORY_SOURCE)
        self.store.save_status(GoldAPIStatus(
            status="LIVE",
            provider_name="Binance BTCUSDT Spot OHLC",
            latest_price=matched[-1]["close"],
            last_updated=matched[-1]["timestamp"],
            is_running=True,
        ))

        engine = DataIntegrityEngine(self.store)
        chart = engine.chart_data("5M", 100)
        panels = engine.indicator_panels("5M", 100)
        snapshot = engine.timeframe_snapshot("5M", 100)

        self.assertEqual({item["source"] for item in chart["candles"]}, {BINANCE_HISTORY_SOURCE})
        self.assertFalse(chart["data_integrity"]["mixed_chart_sources"])
        self.assertEqual(chart["data_integrity"]["chart_source"], BINANCE_HISTORY_SOURCE)
        self.assertGreater(len(panels["indicator_panels"]["boys_selling"]), 0)
        self.assertGreater(len(panels["indicator_panels"]["bearishness"]), 0)
        indicator_snapshot = panels["indicator_panels"]["indicator_snapshot"]
        self.assertEqual(indicator_snapshot["status"], "READY")
        self.assertEqual(indicator_snapshot["source"], "CLOSED_PROVIDER_CANDLES")
        self.assertEqual(indicator_snapshot["macd"]["bias"], "BULLISH")
        self.assertGreater(indicator_snapshot["rsi"]["value"], 50)
        self.assertEqual(indicator_snapshot["confluence"], "ALIGNED_BULLISH")
        self.assertEqual(snapshot["status"], "READY")
        self.assertEqual(snapshot["source"], BINANCE_HISTORY_SOURCE)
        self.assertIn(snapshot["trend"], {"BULLISH", "BEARISH", "RANGE"})

    def test_valid_high_volatility_provider_candle_is_flagged_but_retained(self) -> None:
        candles = [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "open": 100,
                "high": 112,
                "low": 96,
                "close": 110,
            },
            {
                "timestamp": "2026-01-01T00:05:00+00:00",
                "open": 110,
                "high": 111,
                "low": 108,
                "close": 109,
            },
        ]
        self.store.insert_candles("5M", candles, BINANCE_HISTORY_SOURCE)
        self.store.save_status(GoldAPIStatus(
            status="LIVE",
            provider_name="Binance BTCUSDT Spot OHLC",
            latest_price=109,
            last_updated=candles[-1]["timestamp"],
            is_running=True,
        ))

        chart = DataIntegrityEngine(self.store).chart_data("5M", 30)

        self.assertEqual(len(chart["candles"]), 2)
        self.assertGreaterEqual(chart["data_integrity"]["abnormal_candles_flagged"], 1)

    def test_daily_oanda_history_is_not_rejected_for_intraday_price_distance(self) -> None:
        now = pd.Timestamp.now(tz="UTC")
        latest_oanda = now.floor("D") - pd.Timedelta(hours=3)
        latest_fallback = now.floor("D")
        oanda = []
        fallback = []
        for index in range(60):
            age = 59 - index
            oanda.append({
                "timestamp": (latest_oanda - pd.Timedelta(days=age)).isoformat(),
                "open": 3000.0,
                "high": 3010.0,
                "low": 2990.0,
                "close": 3005.0,
            })
            fallback.append({
                "timestamp": (latest_fallback - pd.Timedelta(days=age)).isoformat(),
                "open": 4090.0,
                "high": 4110.0,
                "low": 4080.0,
                "close": 4099.0,
            })
        self.store.insert_candles("1D", oanda, OANDA_HISTORY_SOURCE)
        self.store.insert_candles("1D", fallback, BINANCE_HISTORY_SOURCE)
        self.store.save_status(GoldAPIStatus(
            status="LIVE",
            provider_name="OANDA XAU_USD Mid OHLC",
            latest_price=4100.0,
            last_updated=now.isoformat(),
            is_running=True,
        ))

        frame = DataIntegrityEngine(self.store).preferred_real_history("1D", 200)

        self.assertEqual(set(frame["source"]), {OANDA_HISTORY_SOURCE})
        self.assertEqual(len(frame), 60)


if __name__ == "__main__":
    unittest.main()
