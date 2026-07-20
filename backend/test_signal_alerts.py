import tempfile
import unittest
from pathlib import Path

from engine.signal_alerts import ClosedCandleAlerts


def analysis(event_id="event-1"):
    return {
        "symbol": "XAUUSD",
        "key_zones": {
            "entry_event_status": "CONFIRMED_ENTRY",
            "latest_entry_event": {
                "id": event_id,
                "confirmation_time": 1_700_000_000,
                "entry_side": "BUY",
                "execution_entry": 4100.0,
                "quality_score": 91,
            },
        },
        "feed_reconciliation": {
            "trusted": True,
            "status": "MATCHED_RECONCILED",
            "chart_source": "OANDA_XAUUSD_REAL_HISTORY",
        },
        "diamond_auto_entry": {
            "status": "AUTO_ARMED",
            "stop_loss": 4090.0,
            "take_profit_levels": [4118.0],
        },
        "execution_reality": {
            "status": "TRACKABLE_NOT_BROKER_READY",
            "research_trackable": True,
        },
        "decision_quality": {
            "status": "TRACKABLE_SETUP",
            "current_event": True,
        },
        "news_intelligence": {"execution_gate": "ALLOW"},
    }


class ClosedCandleAlertsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.alerts = ClosedCandleAlerts(Path(self.temp.name) / "alerts.sqlite")

    def tearDown(self):
        self.temp.cleanup()

    def test_deduplicates_and_acknowledges_confirmed_alert(self):
        first = self.alerts.record(analysis(), "15M")
        second = self.alerts.record(analysis(), "15M")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["priority"], "ACTION")
        listed = self.alerts.list("XAUUSD")
        self.assertEqual(listed["stats"]["total"], 1)
        self.assertEqual(listed["stats"]["unread"], 1)
        acknowledged = self.alerts.acknowledge(first["id"])
        self.assertTrue(acknowledged["acknowledged"])
        self.assertEqual(self.alerts.list("XAUUSD")["stats"]["unread"], 0)

    def test_unmatched_or_unconfirmed_event_does_not_alert(self):
        unmatched = analysis("unmatched")
        unmatched["feed_reconciliation"]["trusted"] = False
        self.assertIsNone(self.alerts.record(unmatched, "15M"))
        waiting = analysis("waiting")
        waiting["key_zones"]["entry_event_status"] = "WAITING_CONFIRMATION"
        self.assertIsNone(self.alerts.record(waiting, "15M"))
        historical = analysis("historical")
        historical["decision_quality"]["current_event"] = False
        self.assertIsNone(self.alerts.record(historical, "15M"))
        self.assertEqual(self.alerts.list("XAUUSD")["stats"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
