import unittest
from datetime import datetime, timezone

from engine.execution_reality import ExecutionRealityEngine, FeedReconciliationEngine


class FeedReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.engine = FeedReconciliationEngine()

    def chart(self, timestamp, source="OANDA_XAUUSD_REAL_HISTORY"):
        return {
            "candles": [{
                "time": timestamp,
                "open": 4100.0,
                "high": 4102.0,
                "low": 4099.0,
                "close": 4101.0,
                "is_complete": True,
            }],
            "data_integrity": {
                "chart_source": source,
                "mixed_chart_sources": False,
                "gap_detected": False,
                "invalid_candles_removed": 0,
                "duplicate_candles_removed": 0,
            },
        }

    def test_matches_same_provider_closed_candle(self):
        now = datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc)
        timestamp = int(now.timestamp()) - 900
        result = self.engine.evaluate(
            "XAUUSD",
            "15M",
            self.chart(timestamp),
            "OANDA_XAUUSD_REAL_HISTORY",
            {"last_candle": {"time": timestamp, "close": 4101.0}},
            now=now,
        )
        self.assertEqual(result["status"], "MATCHED_RECONCILED")
        self.assertTrue(result["trusted"])
        self.assertEqual(result["close_drift"], 0.0)

    def test_source_mismatch_is_never_trusted(self):
        now = int(datetime.now(timezone.utc).timestamp())
        result = self.engine.evaluate(
            "XAUUSD",
            "15M",
            self.chart(now - 900, "FALLBACK"),
            "OANDA_XAUUSD_REAL_HISTORY",
        )
        self.assertEqual(result["status"], "SOURCE_MISMATCH")
        self.assertFalse(result["trusted"])
        self.assertTrue(result["blockers"])

    def test_xau_weekend_closure_is_not_reported_as_stale_data(self):
        saturday = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
        friday_close = int(datetime(2026, 7, 17, 20, 45, tzinfo=timezone.utc).timestamp())
        result = self.engine.evaluate(
            "XAUUSD",
            "15M",
            self.chart(friday_close),
            "OANDA_XAUUSD_REAL_HISTORY",
            now=saturday,
        )
        self.assertEqual(result["status"], "MATCHED_MARKET_CLOSED")
        self.assertEqual(result["market_session"]["status"], "CLOSED")
        self.assertTrue(result["trusted"])
        self.assertTrue(next(check for check in result["checks"] if check["id"] == "freshness")["pass"])

    def test_btc_remains_freshness_sensitive_during_xau_weekend(self):
        saturday = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
        old_candle = int(datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc).timestamp())
        result = self.engine.evaluate(
            "BTCUSD",
            "15M",
            self.chart(old_candle, "BINANCE_BTCUSDT_REAL_HISTORY"),
            "BINANCE_BTCUSDT_REAL_HISTORY",
            now=saturday,
        )
        self.assertEqual(result["status"], "STALE")
        self.assertEqual(result["market_session"]["status"], "OPEN")
        self.assertFalse(result["trusted"])


class ExecutionRealityTests(unittest.TestCase):
    def test_midpoint_setup_can_be_tracked_but_not_called_broker_executable(self):
        analysis = {
            "symbol": "XAUUSD",
            "trade_plan": {
                "status": "ACTIONABLE",
                "entry_price": 4100.0,
                "stop_loss": 4090.0,
                "take_profit_levels": [4118.0],
            },
            "key_zones": {"primary_zone": {"atr_14": 8.0}},
            "news_intelligence": {"execution_gate": "ALLOW"},
        }
        result = ExecutionRealityEngine().evaluate(analysis, {"trusted": True, "blockers": []})
        self.assertEqual(result["status"], "TRACKABLE_NOT_BROKER_READY")
        self.assertTrue(result["research_trackable"])
        self.assertFalse(result["broker_executable"])
        self.assertEqual(result["pricing_mode"], "MIDPOINT_RESEARCH")
        self.assertIsNone(result["spread"])


if __name__ == "__main__":
    unittest.main()
