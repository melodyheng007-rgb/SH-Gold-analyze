from datetime import datetime, timezone
import unittest

from engine.smr_model import SMRModelEngine


def candles(count: int, seconds: int, start: int | None = None) -> list[dict]:
    anchor = start or int(datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc).timestamp())
    rows = []
    for index in range(count):
        close = 100.0 + index * 0.08
        rows.append({
            "time": anchor + index * seconds,
            "open": close - 0.03,
            "high": close + 0.12,
            "low": close - 0.12,
            "close": close,
            "is_complete": True,
        })
    return rows


class SMRModelEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SMRModelEngine()

    def test_scalp_and_swing_profiles_use_distinct_timeframes(self) -> None:
        scalp = self.engine.evaluate(
            "XAUUSD",
            "SCALPING",
            {"1H": candles(45, 3600), "15M": candles(45, 900), "5M": candles(45, 300)},
        )
        swing = self.engine.evaluate(
            "BTCUSD",
            "SWING",
            {"1D": candles(45, 86400), "4H": candles(45, 14400), "1H": candles(45, 3600)},
        )

        self.assertEqual(scalp["profile"]["execution_timeframe"], "5M")
        self.assertEqual(scalp["profile"]["context_timeframe"], "15M")
        self.assertEqual(swing["profile"]["execution_timeframe"], "1H")
        self.assertEqual(swing["profile"]["structure_timeframe"], "1D")
        self.assertTrue(scalp["uses_completed_candles_only"])
        self.assertFalse(scalp["repaints"])

    def test_partial_execution_candle_does_not_complete_warmup(self) -> None:
        execution = candles(39, 300)
        partial = dict(candles(1, 300, execution[-1]["time"] + 300)[0])
        partial.update(is_complete=False, is_partial=True, high=500.0, low=1.0)
        execution.append(partial)

        result = self.engine.evaluate(
            "XAUUSD",
            "SCALPING",
            {"1H": candles(40, 3600), "15M": candles(40, 900), "5M": execution},
        )

        self.assertEqual(result["status"], "WARMING_UP")
        self.assertEqual(result["completed_candles"]["execution"], 39)

    def test_xau_rollover_blocks_scalp_but_not_normal_session(self) -> None:
        rollover = int(datetime(2026, 7, 22, 21, 30, tzinfo=timezone.utc).timestamp())
        london = int(datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc).timestamp())

        blocked = self.engine._session_window("XAUUSD", "SCALPING", rollover)
        active = self.engine._session_window("XAUUSD", "SCALPING", london)

        self.assertEqual(blocked["quality"], "AVOID")
        self.assertFalse(blocked["execution_allowed"])
        self.assertEqual(active["quality"], "PRIME")
        self.assertTrue(active["execution_allowed"])

    def test_confirmed_alignment_boosts_zone_without_creating_direction(self) -> None:
        zones = {
            "primary_zone": {"entry_side": "BUY", "diamond_score": 70, "diamond_grade": "B"},
            "zones": [{"entry_side": "BUY", "diamond_score": 70, "diamond_grade": "B"}],
            "visible_zones": [{"entry_side": "BUY", "diamond_score": 70, "diamond_grade": "B"}],
        }
        model = {
            "status": "READY",
            "direction": "BUY",
            "pattern_state": "CONFIRMED",
            "trading_style": "SCALPING",
            "execution_gate": "OPEN",
            "session": {"execution_allowed": True},
        }

        result = self.engine.apply_to_key_zones(zones, model)

        self.assertEqual(result["primary_zone"]["diamond_score"], 76)
        self.assertEqual(result["zones"][0]["diamond_score"], 76)
        self.assertEqual(result["smr_gate"], "CONFIRMED")
        self.assertEqual(model["diamond_alignment"], "ALIGNED")

    def test_confirmed_opposite_direction_blocks_primary_zone(self) -> None:
        zones = {
            "primary_zone": {"entry_side": "BUY", "diamond_score": 72, "diamond_grade": "B"},
            "zones": [{"entry_side": "BUY", "diamond_score": 72, "diamond_grade": "B"}],
        }
        model = {
            "status": "READY",
            "direction": "SELL",
            "pattern_state": "CONFIRMED",
            "trading_style": "SCALPING",
            "execution_gate": "OPEN",
            "session": {"execution_allowed": True},
        }

        result = self.engine.apply_to_key_zones(zones, model)

        self.assertEqual(result["primary_zone"]["diamond_score"], 64)
        self.assertEqual(result["smr_gate"], "BLOCK_CONFLICT")
        self.assertEqual(model["execution_gate"], "BLOCK_CONFLICT")


if __name__ == "__main__":
    unittest.main()
