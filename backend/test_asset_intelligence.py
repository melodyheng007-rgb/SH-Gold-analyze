import unittest

import pandas as pd

from engine.asset_intelligence import AssetIntelligenceEngine
from engine.institutional_analysis import InstitutionalAnalysisEngineV4


def trend_frame(step: float, final_jump: float = 0.0) -> pd.DataFrame:
    rows = []
    base = 100.0
    for index in range(120):
        previous = base + max(0, index - 1) * step
        close = base + index * step
        if index == 119:
            close += final_jump
        padding = max(0.15, abs(close - previous) * 0.20)
        rows.append({
            "open": previous,
            "high": max(previous, close) + padding,
            "low": min(previous, close) - padding,
            "close": close,
            "is_complete": 1,
        })
    return pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=120, freq="5min", tz="UTC"))


class AssetIntelligenceEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = AssetIntelligenceEngine()

    def test_xau_profile_opens_only_when_all_weighted_context_agrees(self) -> None:
        frames = {timeframe: trend_frame(0.25) for timeframe in self.engine.TIMEFRAMES}

        result = self.engine.evaluate("XAUUSD", frames, "BUY")

        self.assertEqual(result["profile"], "XAU_PRECISION")
        self.assertEqual(result["consensus"], "BULLISH")
        self.assertEqual(result["execution_gate"], "OPEN")
        self.assertTrue(result["allows_execution"])
        self.assertEqual(result["required_htf"], ["1D", "4H"])

    def test_btc_profile_uses_4h_1h_and_continuous_market_context(self) -> None:
        frames = {timeframe: trend_frame(-0.30) for timeframe in self.engine.TIMEFRAMES}

        result = self.engine.evaluate("BTCUSD", frames, "SELL")

        self.assertEqual(result["profile"], "BTC_24_7_MOMENTUM")
        self.assertEqual(result["consensus"], "BEARISH")
        self.assertEqual(result["execution_gate"], "OPEN")
        self.assertEqual(result["required_htf"], ["4H", "1H"])
        self.assertEqual(result["session_context"]["market"], "GLOBAL_24_7")

    def test_opposite_mtf_consensus_blocks_the_intended_direction(self) -> None:
        frames = {timeframe: trend_frame(-0.25) for timeframe in self.engine.TIMEFRAMES}

        result = self.engine.evaluate("XAUUSD", frames, "BUY")

        self.assertEqual(result["execution_gate"], "BLOCK_MTF_CONFLICT")
        self.assertFalse(result["allows_execution"])

    def test_pro_gate_demotes_actionable_setup_when_asset_context_is_closed(self) -> None:
        analysis = {
            "execution_allowed": True,
            "trade_plan_valid": True,
            "final_decision": "Actionable Buy Market Setup",
            "market_state": "Actionable Buy Market Setup",
            "signal": {"status": "Actionable Buy Market Setup", "execution_allowed": True, "trade_plan_valid": True},
            "trade_plan": {
                "status": "ACTIONABLE",
                "actionable": True,
                "direction": "BUY",
                "order_type": "MARKET",
                "missing_conditions": [],
            },
        }
        intelligence = {
            "version": self.engine.VERSION,
            "profile": "XAU_PRECISION",
            "quality_score": 44,
            "consensus": "BEARISH",
            "agreement_percent": 72.0,
            "execution_gate": "BLOCK_MTF_CONFLICT",
            "reason": "MTF direction conflicts with BUY.",
            "next_trigger": "Wait for MTF direction alignment.",
        }
        pro = InstitutionalAnalysisEngineV4(store=None, symbol="XAUUSD")

        pro._apply_asset_intelligence_gate(analysis, intelligence)

        self.assertEqual(analysis["trade_plan"]["status"], "CANDIDATE")
        self.assertFalse(analysis["execution_allowed"])
        self.assertFalse(analysis["signal"]["trade_plan_valid"])
        self.assertIn("Pro Analyze", analysis["trade_plan"]["missing_conditions"][0])

    def test_open_asset_context_does_not_promote_a_candidate(self) -> None:
        analysis = {
            "execution_allowed": False,
            "trade_plan_valid": False,
            "signal": {"execution_allowed": False, "trade_plan_valid": False},
            "trade_plan": {"status": "CANDIDATE", "actionable": False, "direction": "SELL"},
        }
        intelligence = {
            "version": self.engine.VERSION,
            "profile": "BTC_24_7_MOMENTUM",
            "quality_score": 90,
            "consensus": "BEARISH",
            "agreement_percent": 85.0,
            "execution_gate": "OPEN",
        }
        pro = InstitutionalAnalysisEngineV4(store=None, symbol="BTCUSD")

        pro._apply_asset_intelligence_gate(analysis, intelligence)

        self.assertEqual(analysis["trade_plan"]["status"], "CANDIDATE")
        self.assertFalse(analysis["execution_allowed"])

    def test_abnormal_execution_timeframe_range_locks_new_entries(self) -> None:
        frames = {timeframe: trend_frame(0.12) for timeframe in self.engine.TIMEFRAMES}
        frames["5M"] = trend_frame(0.12, final_jump=12.0)

        result = self.engine.evaluate("BTCUSD", frames, "BUY")

        self.assertEqual(result["timeframes"]["5M"]["regime"], "VOLATILITY_SHOCK")
        self.assertEqual(result["execution_gate"], "BLOCK_VOLATILITY")
        self.assertFalse(result["allows_execution"])


if __name__ == "__main__":
    unittest.main()
