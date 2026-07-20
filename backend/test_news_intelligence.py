import unittest
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests

from engine.news_intelligence import EconomicNewsIntelligence


class EconomicNewsIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = EconomicNewsIntelligence(persist_cache=False, enable_official_fallback=False)
        self.now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)

    def event(self, title, currency="USD", impact="High", minutes=30, **values):
        return {
            "title": title,
            "country": currency,
            "impact": impact,
            "date": (self.now + timedelta(minutes=minutes)).isoformat(),
            **values,
        }

    def test_high_impact_us_cpi_locks_new_entries_without_creating_direction(self) -> None:
        result = self.engine.snapshot("XAUUSD", self.now, [
            self.event("Core CPI m/m", forecast="0.2%", previous="0.3%"),
        ])

        self.assertEqual(result["state"], "NEWS_LOCK")
        self.assertEqual(result["risk_level"], "HIGH")
        self.assertEqual(result["execution_gate"], "BLOCK_NEW_ENTRIES")
        self.assertEqual(result["primary_event"]["category"], "INFLATION")
        self.assertEqual(result["primary_event"]["countdown"], "in 30m")
        self.assertFalse(result["trade_direction_created"])
        self.assertEqual(result["directional_signal"], "TWO_SIDED_UNTIL_RELEASE_AND_PRICE_CONFIRMATION")

    def test_unrelated_low_impact_event_is_filtered_from_btc(self) -> None:
        result = self.engine.snapshot("BTCUSD", self.now, [
            self.event("Visitor Arrivals m/m", currency="NZD", impact="Low", minutes=60),
        ])

        self.assertEqual(result["state"], "NO_RELEVANT_EVENTS")
        self.assertEqual(result["events"], [])
        self.assertEqual(result["execution_gate"], "OPEN")

    def test_medium_us_event_near_release_creates_caution_not_lock(self) -> None:
        result = self.engine.snapshot("BTCUSD", self.now, [
            self.event("Retail Sales m/m", impact="Medium", minutes=20),
        ])

        self.assertEqual(result["state"], "NEWS_CAUTION")
        self.assertEqual(result["risk_level"], "ELEVATED")
        self.assertEqual(result["execution_gate"], "REDUCE_RISK")

    def test_high_event_remains_locked_during_post_release_volatility(self) -> None:
        result = self.engine.snapshot("XAUUSD", self.now, [
            self.event("FOMC Rate Statement", impact="High", minutes=-12, actual="5.25%", forecast="5.25%"),
        ])

        self.assertEqual(result["execution_gate"], "BLOCK_NEW_ENTRIES")
        self.assertEqual(result["primary_event"]["release_phase"], "POST_RELEASE_VOLATILITY")
        self.assertEqual(result["primary_event"]["release_status"], "RELEASED")
        self.assertEqual(result["primary_event"]["actual_status"], "AVAILABLE")
        self.assertEqual(result["primary_event"]["actual"], "5.25%")

    def test_high_event_three_hours_away_is_caution_only(self) -> None:
        result = self.engine.snapshot("XAUUSD", self.now, [
            self.event("Fed Chairman Testifies", impact="High", minutes=180),
        ])

        self.assertEqual(result["execution_gate"], "REDUCE_RISK")
        self.assertEqual(result["risk_level"], "ELEVATED")

    def test_news_lock_vetoes_actionable_plan_without_creating_new_prices(self) -> None:
        news = self.engine.snapshot("BTCUSD", self.now, [
            self.event("Core CPI y/y", impact="High", minutes=15),
        ])
        analysis = {
            "final_decision": "Valid Buy Setup",
            "signal": {"direction": "BUY", "execution_allowed": True, "trade_plan_valid": True},
            "trade_plan": {
                "status": "ACTIONABLE",
                "direction": "BUY",
                "entry_price": 62000.0,
                "stop_loss": 61500.0,
                "take_profit_levels": [63000.0],
                "missing_conditions": [],
            },
        }

        self.engine.apply_to_analysis(analysis, news)

        self.assertEqual(analysis["trade_plan"]["status"], "NEWS_LOCKED")
        self.assertEqual(analysis["trade_plan"]["technical_status"], "ACTIONABLE")
        self.assertEqual(analysis["trade_plan"]["entry_price"], 62000.0)
        self.assertFalse(analysis["signal"]["execution_allowed"])
        self.assertFalse(analysis["signal"]["trade_plan_valid"])

    def test_elevated_news_does_not_change_technical_plan_status(self) -> None:
        news = self.engine.snapshot("XAUUSD", self.now, [
            self.event("Retail Sales m/m", impact="Medium", minutes=20),
        ])
        analysis = {
            "signal": {"direction": "SELL", "execution_allowed": True},
            "trade_plan": {"status": "CANDIDATE", "direction": "SELL"},
        }

        self.engine.apply_to_analysis(analysis, news)

        self.assertEqual(analysis["trade_plan"]["status"], "CANDIDATE")
        self.assertTrue(analysis["signal"]["execution_allowed"])

    def test_provider_failure_uses_stale_cache_and_preserves_risk_gate(self) -> None:
        cached = self.event("Core CPI m/m", impact="High", minutes=20)
        self.engine._events = [cached]
        self.engine._fetched_at = self.now - timedelta(hours=1)

        with patch("engine.news_intelligence.requests.get", side_effect=requests.ConnectionError("offline")):
            result = self.engine.snapshot("XAUUSD", self.now)

        self.assertEqual(result["status"], "STALE_CACHE")
        self.assertEqual(result["feed"]["status"], "STALE_CACHE")
        self.assertEqual(result["execution_gate"], "BLOCK_NEW_ENTRIES")
        self.assertIn("offline", result["feed"]["error"])

    def test_provider_failure_without_cache_does_not_invent_news_lock(self) -> None:
        with patch("engine.news_intelligence.requests.get", side_effect=requests.ConnectionError("offline")):
            result = self.engine.snapshot("BTCUSD", self.now)

        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["state"], "CALENDAR_UNAVAILABLE")
        self.assertEqual(result["execution_gate"], "OPEN")
        self.assertFalse(result["trade_direction_created"])

    def test_weekly_calendar_preserves_full_source_week_and_marks_asset_relevance(self) -> None:
        events = [
            self.event("Core CPI m/m", currency="USD", impact="High", minutes=-24 * 60),
            self.event("Visitor Arrivals m/m", currency="NZD", impact="Low", minutes=60),
            self.event("Caixin Manufacturing PMI", currency="CNY", impact="Medium", minutes=2 * 24 * 60),
        ]

        result = self.engine.weekly_calendar("XAUUSD", self.now, events)

        self.assertEqual(result["scope"], "FULL_SOURCE_WEEK")
        self.assertEqual(result["stats"]["total"], 3)
        self.assertEqual(result["stats"]["relevant"], 2)
        self.assertEqual(result["stats"]["high_impact"], 1)
        self.assertEqual(result["events"][0]["title"], "Core CPI m/m")
        self.assertTrue(result["events"][0]["is_relevant"])
        self.assertEqual(result["events"][0]["release_status"], "RELEASED")
        self.assertEqual(result["events"][0]["actual_status"], "UPDATING")
        self.assertEqual(result["events"][1]["asset_relevance"], "UNRELATED")
        self.assertFalse(result["events"][1]["is_relevant"])

    def test_released_calendar_event_exposes_actual_and_release_counts(self) -> None:
        result = self.engine.weekly_calendar("XAUUSD", self.now, [
            self.event("Core CPI m/m", impact="High", minutes=-15, actual="0.4%", forecast="0.3%"),
            self.event("Retail Sales m/m", impact="Medium", minutes=60, forecast="0.2%"),
        ])

        self.assertEqual(result["stats"]["released"], 1)
        self.assertEqual(result["stats"]["actual_available"], 1)
        self.assertEqual(result["events"][0]["actual"], "0.4%")
        self.assertEqual(result["events"][0]["actual_status"], "AVAILABLE")

    def test_tradingview_actual_enrichment_matches_numbered_rate_events(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"result": [
            {"title": "Loan Prime Rate 1Y", "currency": "CNY", "date": (self.now - timedelta(minutes=20)).isoformat(), "actual": 3.0, "unit": "%"},
            {"title": "Loan Prime Rate 5Y", "currency": "CNY", "date": (self.now - timedelta(minutes=20)).isoformat(), "actual": 3.5, "unit": "%"},
        ]}
        events = [
            self.event("1-y Loan Prime Rate", currency="CNY", minutes=-20),
            self.event("5-y Loan Prime Rate", currency="CNY", minutes=-20),
        ]

        with patch("engine.news_intelligence.requests.get", return_value=response):
            enriched = self.engine._enrich_actual_values(events, self.now)

        self.assertEqual(enriched[0]["actual"], "3.0%")
        self.assertEqual(enriched[1]["actual"], "3.5%")
        self.assertEqual(enriched[1]["actual_source"], "TradingView Economic Calendar")

    def test_weekly_calendar_labels_active_high_impact_lock_window(self) -> None:
        result = self.engine.weekly_calendar("BTCUSD", self.now, [
            self.event("FOMC Rate Statement", currency="USD", impact="High", minutes=30),
        ])

        self.assertEqual(result["events"][0]["risk_window"], "LOCK")
        self.assertEqual(result["events"][0]["release_phase"], "PRE_RELEASE_WINDOW")

    def test_failed_provider_is_backed_off_instead_of_requested_for_every_snapshot(self) -> None:
        with patch("engine.news_intelligence.requests.get", side_effect=requests.ConnectionError("rate limited")) as request:
            self.engine.snapshot("XAUUSD", self.now)
            self.engine.weekly_calendar("XAUUSD", self.now + timedelta(seconds=10))

        self.assertEqual(request.call_count, 1)

    def test_successful_week_is_restored_from_disk_after_backend_restart(self) -> None:
        with TemporaryDirectory() as directory:
            cache_path = f"{directory}/calendar.json"
            writer = EconomicNewsIntelligence(cache_path=cache_path)
            writer._events = [self.event("Core CPI m/m", impact="High", minutes=30)]
            writer._fetched_at = self.now
            writer._persist_disk_cache()

            reader = EconomicNewsIntelligence(cache_path=cache_path)
            result = reader.weekly_calendar("XAUUSD", self.now)

        self.assertEqual(result["feed"]["status"], "CACHED")
        self.assertEqual(result["stats"]["total"], 1)

    def test_official_usd_schedule_is_used_when_primary_weekly_feed_is_rate_limited(self) -> None:
        primary = Mock()
        primary.raise_for_status.side_effect = requests.HTTPError("429 rate limited")
        fallback = Mock()
        fallback.raise_for_status.return_value = None
        fallback.json.return_value = {"data": [{
            "announcement_datetime_utc": (self.now + timedelta(minutes=30)).isoformat(),
            "name": "Federal Funds Rate",
            "event_importance": "high",
            "release_date_confirmed": True,
            "source": "Federal Reserve",
            "source_url": "https://www.federalreserve.gov/",
        }]}
        engine = EconomicNewsIntelligence(persist_cache=False, enable_official_fallback=True)

        with patch("engine.news_intelligence.requests.get", side_effect=[primary, fallback]):
            result = engine.weekly_calendar("XAUUSD", self.now)

        self.assertEqual(result["feed"]["status"], "OFFICIAL_FALLBACK")
        self.assertEqual(result["scope"], "ROLLING_7_DAY_OFFICIAL_FALLBACK")
        self.assertEqual(result["events"][0]["title"], "Federal Funds Rate")
        self.assertEqual(result["events"][0]["risk_window"], "LOCK")
        self.assertTrue(result["events"][0]["release_date_confirmed"])


if __name__ == "__main__":
    unittest.main()
