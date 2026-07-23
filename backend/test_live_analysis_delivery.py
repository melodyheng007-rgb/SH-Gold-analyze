import unittest

from engine.live_analysis_delivery import build_analysis_revision, should_deliver_analysis


class LiveAnalysisDeliveryTests(unittest.TestCase):
    def test_revision_is_stable_for_the_same_completed_analysis(self):
        signature = ("OANDA_XAUUSD_REAL_HISTORY", (("5M", 500, 123456),))
        first = build_analysis_revision("XAUUSD:5M:SCALPING", 123456, signature, "3.8.7")
        second = build_analysis_revision("XAUUSD:5M:SCALPING", 123456, signature, "3.8.7")
        self.assertEqual(first, second)

    def test_revision_changes_for_a_new_closed_candle(self):
        signature = ("OANDA_XAUUSD_REAL_HISTORY", (("5M", 500, 123456),))
        first = build_analysis_revision("XAUUSD:5M:SCALPING", 123456, signature, "3.8.7")
        second = build_analysis_revision("XAUUSD:5M:SCALPING", 123756, signature, "3.8.7")
        self.assertNotEqual(first, second)

    def test_each_client_receives_an_unseen_revision(self):
        analysis = {"symbol": "XAUUSD", "diamond_auto_entry": {"status": "AUTO_ARMED"}}
        self.assertTrue(should_deliver_analysis(analysis, "revision-2", "revision-1"))
        self.assertFalse(should_deliver_analysis(analysis, "revision-2", "revision-2"))
        self.assertTrue(should_deliver_analysis(analysis, "revision-2", None))


if __name__ == "__main__":
    unittest.main()
