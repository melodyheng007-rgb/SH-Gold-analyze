from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine.analysis_journal import AnalysisJournal


def analysis_result(decision: str = "No Valid Setup", score: float = 20, trust: str = "TRUSTED"):
    return {
        "symbol": "BTCUSD",
        "current_price": 64000,
        "analysis_data_source": "BINANCE_BTCUSDT_REAL_HISTORY",
        "provider_alignment": {"status": "MATCHED"},
        "trust_gate": {"status": trust, "trusted": trust == "TRUSTED", "api_token": "must-not-leak"},
        "final_decision": decision,
        "bias": "Bullish",
        "signal": {"score": score, "direction": "WAIT", "execution_allowed": False},
        "trade_plan": {"status": "NO_VALID_SETUP", "direction": "WAIT", "take_profit_levels": []},
    }


class AnalysisJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.journal = AnalysisJournal(Path(self.temp_dir.name) / "journal.sqlite")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_records_initial_scan_and_redacts_secrets(self):
        entry = self.journal.record(analysis_result(), "5M")
        stored = self.journal.get(entry["id"])

        self.assertEqual(entry["change"]["type"], "INITIAL_SCAN")
        self.assertEqual(stored["selected_timeframe"], "5M")
        self.assertNotIn("must-not-leak", str(stored))
        self.assertIn("[REDACTED]", str(stored))

    def test_detects_setup_and_score_changes(self):
        self.journal.record(analysis_result(), "5M")
        changed = analysis_result("Actionable Buy", 82)
        changed["signal"].update({"direction": "BUY", "execution_allowed": True})
        changed["trade_plan"].update({
            "status": "ACTIONABLE",
            "direction": "BUY",
            "entry_price": 64010,
            "stop_loss": 63800,
            "take_profit_levels": [64400],
        })

        entry = self.journal.record(changed, "5M")

        self.assertEqual(entry["change"]["type"], "SETUP_CHANGE")
        self.assertTrue(entry["change"]["significant"])
        self.assertEqual(entry["change"]["score_delta"], 62)
        self.assertEqual(self.journal.stats("BTCUSD")["total"], 2)


if __name__ == "__main__":
    unittest.main()
