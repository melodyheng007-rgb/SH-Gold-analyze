from __future__ import annotations

import copy
import unittest

from engine.diamond_timeframe_model import DiamondTimeframeFusionEngine


def trend_candles(count: int, step: float, seconds: int, start: float = 100.0) -> list[dict]:
    rows = []
    price = start
    for index in range(count):
        open_price = price
        close = open_price + step + ((index % 5) - 2) * abs(step) * 0.04
        spread = max(abs(step) * 0.55, 0.08)
        rows.append({
            "time": 1_720_000_000 + index * seconds,
            "open": round(open_price, 5),
            "high": round(max(open_price, close) + spread, 5),
            "low": round(min(open_price, close) - spread, 5),
            "close": round(close, 5),
            "is_complete": True,
        })
        price = close
    return rows


def aligned_zone(frames: dict[str, list[dict]], style: str = "SCALPING") -> dict:
    execution = "5M" if style == "SCALPING" else "1H"
    rows = frames[execution]
    line = rows[-30]["close"]
    return {
        "status": "READY",
        "feed_matched": True,
        "primary_zone": {
            "id": "dual-core-zone",
            "entry_side": "BUY",
            "line": line,
            "active_structure": True,
            "entry_eligible_origin": True,
            "origin_model": "STRUCTURE_DISPLACEMENT",
            "diamond_score": 76,
            "diamond_grade": "B",
            "display_as_diamond": True,
        },
        "mtf_confluence": {
            "status": "READY",
            "state": "ALIGNED_BULLISH",
            "direction": "BULLISH",
        },
    }


def confirmed_smr() -> dict:
    return {
        "status": "READY",
        "pattern_state": "CONFIRMED",
        "direction": "BUY",
        "execution_gate": "CONFIRMED",
        "feed_matched": True,
        "session": {
            "name": "LONDON",
            "quality": "PRIME",
            "execution_allowed": True,
        },
    }


class DiamondTimeframeFusionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DiamondTimeframeFusionEngine()

    def test_profiles_focus_on_5m_and_1h_execution(self) -> None:
        scalp = self.engine.PROFILES["SCALPING"]
        swing = self.engine.PROFILES["SWING"]

        self.assertEqual(
            (scalp["execution_timeframe"], scalp["context_timeframe"], scalp["anchor_timeframe"]),
            ("5M", "15M", "1H"),
        )
        self.assertEqual(
            (swing["execution_timeframe"], swing["context_timeframe"], swing["anchor_timeframe"]),
            ("1H", "4H", "1D"),
        )

    def test_aligned_scalp_core_confirms_existing_diamond(self) -> None:
        frames = {
            "5M": trend_candles(100, 0.22, 300),
            "15M": trend_candles(100, 0.45, 900),
            "1H": trend_candles(100, 0.9, 3600),
        }
        model = self.engine.evaluate(
            "XAUUSD",
            "SCALPING",
            frames,
            aligned_zone(frames),
            {"news_intelligence": {"execution_gate": "OPEN"}},
            {"position": "LONDON"},
            confirmed_smr(),
        )

        self.assertEqual(model["status"], "READY")
        self.assertEqual(model["focus_timeframe"], "5M")
        self.assertEqual(model["execution_gate"], "CONFIRMED")
        self.assertGreaterEqual(model["score"], 72)
        self.assertFalse(model["creates_diamond_zone"])
        self.assertFalse(model["repaints"])

    def test_anchor_and_context_conflict_block_existing_buy_diamond(self) -> None:
        frames = {
            "5M": trend_candles(100, -0.22, 300, 160.0),
            "15M": trend_candles(100, -0.35, 900, 180.0),
            "1H": trend_candles(100, -0.55, 3600, 210.0),
        }
        zones = aligned_zone(frames)
        model = self.engine.evaluate(
            "BTCUSD",
            "SCALPING",
            frames,
            zones,
            {"news_intelligence": {"execution_gate": "OPEN"}},
            {},
            confirmed_smr(),
        )

        self.assertEqual(model["execution_gate"], "BLOCK_CONFLICT")
        self.assertIn("ANCHOR_CONTEXT_CONFLICT", model["hard_conflicts"])

    def test_partial_or_short_history_stays_in_warmup(self) -> None:
        frames = {
            "5M": trend_candles(40, 0.2, 300),
            "15M": trend_candles(40, 0.4, 900),
            "1H": trend_candles(40, 0.8, 3600),
        }
        frames["5M"][-1]["is_partial"] = True

        model = self.engine.evaluate("XAUUSD", "SCALPING", frames)

        self.assertEqual(model["status"], "WARMING_UP")
        self.assertEqual(model["execution_gate"], "WAIT_DATA")

    def test_verified_smt_conflict_vetoes_an_otherwise_aligned_core(self) -> None:
        frames = {
            "5M": trend_candles(100, 0.22, 300),
            "15M": trend_candles(100, 0.45, 900),
            "1H": trend_candles(100, 0.9, 3600),
        }
        model = self.engine.evaluate(
            "XAUUSD",
            "SCALPING",
            frames,
            aligned_zone(frames),
            {"news_intelligence": {"execution_gate": "OPEN"}},
            {"position": "LONDON"},
            confirmed_smr(),
            {
                "status": "READY",
                "state": "BEARISH_DIVERGENCE",
                "direction": "SELL",
                "confidence": 80,
                "execution_gate": "DIVERGENCE_READY",
                "companion_symbol": "XAGUSD",
            },
        )

        self.assertEqual(model["execution_gate"], "BLOCK_CONFLICT")
        self.assertIn("SMT_CONFLICT", model["hard_conflicts"])

    def test_iso_timestamps_are_accepted(self) -> None:
        rows = [{
            "time": "2026-07-22T05:00:00Z",
            "open": 100,
            "high": 102,
            "low": 99,
            "close": 101,
            "is_complete": True,
        }]

        normalized = self.engine._candles(rows)

        self.assertEqual(len(normalized), 1)
        self.assertIsInstance(normalized[0]["time"], int)

    def test_fusion_adjusts_but_never_publishes_or_creates_a_zone(self) -> None:
        model = {
            "status": "READY",
            "execution_gate": "CONFIRMED",
            "score": 90,
            "profile": {"strong_score": 84},
            "consensus_direction": "BUY",
            "zone_direction": "BUY",
            "state": "CORE_ALIGNED",
        }
        zone = {
            "entry_side": "BUY",
            "diamond_score": 70,
            "diamond_confidence_score": 70,
            "diamond_grade": "B",
            "display_as_diamond": False,
        }
        zones = {"primary_zone": copy.deepcopy(zone), "zones": [copy.deepcopy(zone)]}

        self.engine.apply_to_key_zones(zones, model)

        self.assertEqual(zones["primary_zone"]["diamond_score"], 76)
        self.assertFalse(zones["primary_zone"]["display_as_diamond"])
        self.assertEqual(len(zones["zones"]), 1)

        self.engine.apply_to_key_zones(zones, model)
        self.assertEqual(zones["primary_zone"]["diamond_score"], 76)

        empty = {"primary_zone": None, "zones": []}
        self.engine.apply_to_key_zones(empty, model)
        self.assertEqual(empty["zones"], [])
        self.assertIsNone(empty["primary_zone"])

    def test_strong_market_regime_vetoes_counter_trend_diamond(self) -> None:
        frames = {
            "5M": trend_candles(100, 0.22, 300),
            "15M": trend_candles(100, 0.45, 900),
            "1H": trend_candles(100, 0.9, 3600),
        }
        zones = aligned_zone(frames)
        zones["primary_zone"]["entry_side"] = "SELL"
        model = self.engine.evaluate(
            "XAUUSD",
            "SCALPING",
            frames,
            zones,
            {"news_intelligence": {"execution_gate": "OPEN"}},
            {"position": "LONDON"},
            confirmed_smr(),
            {},
            {
                "regime": "TRENDING_BULLISH",
                "regime_direction": "BUY",
                "strength": 84,
                "strength_band": "STRONG",
                "pullback_state": "PULLBACK_READY",
            },
        )

        self.assertEqual(model["execution_gate"], "BLOCK_CONFLICT")
        self.assertIn("STRONG_REGIME_CONFLICT", model["hard_conflicts"])
        self.assertEqual(model["confidence_label"], "Counter-Trend Risk")
        self.assertEqual(model["lifecycle"], "WATCHING")

    def test_public_lifecycle_is_ready_only_after_confirmed_entry(self) -> None:
        zones = {
            "primary_zone": {"lifecycle": "FRESH"},
            "latest_entry_event": {"id": "entry-1"},
        }

        self.assertEqual(self.engine._public_lifecycle(zones, "CONFIRMED"), "READY")
        self.assertEqual(self.engine._public_lifecycle(zones, "WATCH"), "WATCHING")


if __name__ == "__main__":
    unittest.main()
