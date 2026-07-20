from __future__ import annotations

import unittest

import pandas as pd

from engine.pro_analysis import ProAnalysisEngineV3


def candle_frame() -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=30, freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [102.0] * 30,
            "low": [98.0] * 30,
            "close": [100.0] * 30,
        },
        index=index,
    )


class BestAvailableTradePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ProAnalysisEngineV3(store=None)
        self.frames = {"15M": candle_frame()}

    def test_pending_sell_limit_has_valid_price_geometry(self) -> None:
        plan = self.engine._best_available_trade_plan(
            self.frames,
            "REAL_MODE",
            100.0,
            {"bias": "Bearish"},
            {"liquidity_sweep": None, "nearest_liquidity_above": 105.0},
            {"equilibrium": 102.0, "crt_high": 110.0, "crt_low": 90.0},
            {
                "best_poi": {"type": "FVG", "direction": "bearish", "low": 98.0, "high": 99.0},
                "fair_value_gaps": [
                    {"type": "FVG", "direction": "bearish", "low": 103.0, "high": 104.0},
                ],
                "order_blocks": [],
                "ote_zone": None,
                "premium_discount_alignment": False,
            },
            {"confirmation_ready": False},
            {"score": 35},
        )

        self.assertEqual(plan["status"], "CANDIDATE")
        self.assertEqual(plan["direction"], "SELL")
        self.assertEqual(plan["order_type"], "LIMIT")
        self.assertGreater(plan["stop_loss"], plan["entry_price"])
        self.assertTrue(all(target < plan["entry_price"] for target in plan["take_profit_levels"]))
        self.assertEqual(plan["risk_model"]["status"], "VALID")

    def test_missing_directional_poi_does_not_create_synthetic_prices(self) -> None:
        plan = self.engine._best_available_trade_plan(
            self.frames,
            "REAL_MODE",
            100.0,
            {"bias": "Bearish"},
            {"liquidity_sweep": None, "nearest_liquidity_above": 105.0},
            {"equilibrium": 102.0, "crt_high": 110.0, "crt_low": 90.0},
            {
                "best_poi": None,
                "fair_value_gaps": [],
                "order_blocks": [],
                "ote_zone": None,
                "premium_discount_alignment": False,
            },
            {"confirmation_ready": False},
            {"score": 20},
        )

        self.assertEqual(plan["status"], "NO_VALID_SETUP")
        self.assertEqual(plan["order_type"], "NONE")
        self.assertIsNone(plan["entry_price"])
        self.assertIsNone(plan["stop_loss"])
        self.assertEqual(plan["take_profit_levels"], [])
        self.assertIn("no synthetic entry", plan["action"].lower())

    def test_unclear_htf_bias_cannot_create_limit_candidate(self) -> None:
        plan = self.engine._best_available_trade_plan(
            self.frames,
            "REAL_MODE",
            100.0,
            {"bias": "No Clear Bias"},
            {"liquidity_sweep": None},
            {"equilibrium": 102.0, "crt_high": 110.0, "crt_low": 90.0},
            {
                "best_poi": {"type": "OrderBlock", "direction": "bullish", "low": 96.0, "high": 97.0},
                "fair_value_gaps": [],
                "order_blocks": [],
                "ote_zone": None,
                "premium_discount_alignment": True,
            },
            {"confirmation_ready": False},
            {"score": 30},
        )

        self.assertEqual(plan["status"], "NO_VALID_SETUP")
        self.assertEqual(plan["direction"], "WAIT")
        self.assertIsNone(plan["entry_price"])

    def test_confirmed_buy_plan_is_actionable(self) -> None:
        plan = self.engine._best_available_trade_plan(
            self.frames,
            "REAL_MODE",
            100.0,
            {"bias": "Bullish"},
            {"liquidity_sweep": "Sell-side sweep"},
            {"equilibrium": 102.0, "crt_high": 110.0, "crt_low": 90.0},
            {
                "best_poi": {"type": "OrderBlock", "direction": "bullish", "low": 98.0, "high": 99.0},
                "fair_value_gaps": [],
                "order_blocks": [],
                "ote_zone": None,
                "premium_discount_alignment": True,
            },
            {"confirmation_ready": True},
            {"score": 85},
        )

        self.assertEqual(plan["status"], "ACTIONABLE")
        self.assertEqual(plan["direction"], "BUY")
        self.assertEqual(plan["order_type"], "MARKET")
        self.assertLess(plan["stop_loss"], plan["entry_price"])
        self.assertTrue(all(target > plan["entry_price"] for target in plan["take_profit_levels"]))
        self.assertEqual(plan["risk_model"]["status"], "VALID")

    def test_engine_result_keeps_configured_asset_symbol(self) -> None:
        engine = ProAnalysisEngineV3(store=None, symbol="BTCUSD")
        result = engine._blocked(
            "Waiting for Data",
            "NO_DATA_MODE",
            {"data_mode_label": "NO DATA", "warnings": []},
            {},
            "BTC history is not ready.",
        )

        self.assertEqual(result["symbol"], "BTCUSD")
        self.assertEqual(engine.symbol, "BTCUSD")


if __name__ == "__main__":
    unittest.main()
