import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from engine.telegram_alerts import TelegramDiamondAlerts
from engine.xauusd_provider import ProviderSettings


class FakeSettings:
    def __init__(self):
        self.values = {
            "telegram_bot_token": "test-token",
            "telegram_chat_id": "-1001234567890",
            "telegram_alerts_enabled": True,
        }

    def get(self, name):
        return self.values.get(name, "")

    def update(self, values):
        self.values.update(values)
        return dict(self.values)


class TelegramDiamondAlertsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = FakeSettings()
        self.alerts = TelegramDiamondAlerts(
            Path(self.temp_dir.name) / "alerts.sqlite",
            self.settings,
        )
        self.alerts._send_message = lambda token, chat_id, text: {
            "ok": True,
            "result": {"message_id": 77},
        }

    def tearDown(self):
        self.alerts._queue.join()
        self.temp_dir.cleanup()

    def test_new_confirmed_diamond_is_delivered_once(self):
        captured = []
        self.alerts._send_message = lambda token, chat_id, text: captured.append(text) or {
            "ok": True,
            "result": {"message_id": 77},
        }
        alert = {
            "is_new": True,
            "event_key": "XAUUSD:5M:buy-1:CONFIRMED",
            "symbol": "XAUUSD",
            "timeframe": "5M",
            "kind": "DIAMOND_CONFIRMED_RESEARCH",
            "side": "BUY",
        }
        analysis = {
            "key_zones": {
                "trading_style": "SCALPING",
                "latest_entry_event": {
                    "line": 4110.25,
                    "diamond_grade": "A",
                    "diamond_score": 84,
                    "origin_model": "TREND_PULLBACK_RECLAIM",
                },
            },
            "market_regime": {"regime": "TRENDING_BULLISH"},
        }

        first = self.alerts.enqueue(alert, analysis)
        self.alerts._queue.join()
        second = self.alerts.enqueue(alert, analysis)
        status = self.alerts.status()

        self.assertTrue(first["queued"])
        self.assertFalse(second["queued"])
        self.assertEqual(second["reason"], "ALREADY_DELIVERED_OR_QUEUED")
        self.assertEqual(status["stats"]["delivered"], 1)
        self.assertEqual(status["stats"]["failed"], 0)
        self.assertIn("SH DIAMOND ENTRY ថ្មី", captured[0])
        self.assertIn("ទិញ (BUY)", captured[0])
        self.assertIn("តំបន់ Entry", captured[0])

    def test_polling_existing_alert_never_queues_again(self):
        result = self.alerts.enqueue({
            "is_new": False,
            "event_key": "BTCUSD:5M:sell-1:CONFIRMED",
            "kind": "TRACKABLE_DIAMOND_SETUP",
        }, {})

        self.assertFalse(result["queued"])
        self.assertEqual(result["reason"], "NOT_A_NEW_ALERT")

    def test_invalidation_is_not_delivered_to_telegram(self):
        captured = []
        self.alerts._send_message = lambda token, chat_id, text: captured.append(text) or {
            "ok": True,
            "result": {"message_id": 78},
        }
        alert = {
            "is_new": True,
            "event_key": "XAUUSD:5M:buy-1:INVALIDATED",
            "symbol": "XAUUSD",
            "timeframe": "5M",
            "kind": "DIAMOND_INVALIDATED",
            "side": "BUY",
        }

        result = self.alerts.enqueue(alert, {})

        self.assertFalse(result["queued"])
        self.assertEqual(result["reason"], "ALERT_KIND_NOT_DELIVERED")
        self.assertEqual(captured, [])
        self.assertEqual(self.alerts.status()["delivery_policy"], "NEW_CONFIRMED_ENTRY_ZONE_ONCE")

    def test_news_locked_zone_is_not_delivered_to_telegram(self):
        result = self.alerts.enqueue({
            "is_new": True,
            "event_key": "XAUUSD:5M:buy-2:NEWS_LOCK",
            "symbol": "XAUUSD",
            "timeframe": "5M",
            "kind": "DIAMOND_NEWS_LOCKED",
            "side": "BUY",
        }, {})

        self.assertFalse(result["queued"])
        self.assertEqual(result["reason"], "ALERT_KIND_NOT_DELIVERED")

    def test_configuration_never_returns_full_token_or_chat_id(self):
        status = self.alerts.configure(
            bot_token="replacement-token",
            chat_id="-1009876543210",
            enabled=True,
        )

        self.assertTrue(status["bot_token_saved"])
        self.assertEqual(status["chat_id"], "-100...210")
        self.assertNotIn("replacement-token", str(status))
        self.assertNotIn("-1009876543210", str(status))

    def test_saved_connection_is_restored_after_backend_restart(self):
        settings_path = Path(self.temp_dir.name) / "provider_settings.json"
        first_settings = ProviderSettings(str(settings_path))
        first = TelegramDiamondAlerts(
            Path(self.temp_dir.name) / "restart-alerts.sqlite",
            first_settings,
        )
        first.configure(
            bot_token="persistent-token",
            chat_id="-1002222333444",
            enabled=True,
            verified=True,
            bot_username="sh_alert_bot",
        )

        with patch.dict("os.environ", {
            "TELEGRAM_BOT_TOKEN": "stale-environment-token",
            "TELEGRAM_CHAT_ID": "@wrong_bot_destination",
        }):
            restored_settings = ProviderSettings(str(settings_path))
            restored = TelegramDiamondAlerts(
                Path(self.temp_dir.name) / "restart-alerts.sqlite",
                restored_settings,
            ).status()

        self.assertEqual(restored["status"], "READY")
        self.assertEqual(restored["connection_state"], "AUTO_CONNECTED")
        self.assertTrue(restored["auto_restore"])
        self.assertTrue(restored["verified"])
        self.assertEqual(restored["bot_username"], "sh_alert_bot")
        self.assertEqual(restored["chat_id"], "-100...444")
        self.assertNotIn("persistent-token", str(restored))

    def test_telegram_community_link_is_saved_replaced_and_removed(self):
        settings_path = Path(self.temp_dir.name) / "community-settings.json"
        community_settings = ProviderSettings(str(settings_path))

        saved = community_settings.save_telegram_community_url("https://t.me/sh_market_group")
        replaced = community_settings.save_telegram_community_url("https://telegram.me/+invite_code")
        removed = community_settings.save_telegram_community_url("")

        self.assertEqual(saved["url"], "https://t.me/sh_market_group")
        self.assertEqual(replaced["url"], "https://telegram.me/+invite_code")
        self.assertTrue(replaced["configured"])
        self.assertFalse(removed["configured"])
        self.assertIsNone(removed["url"])

    def test_telegram_community_link_rejects_non_telegram_hosts(self):
        settings_path = Path(self.temp_dir.name) / "invalid-community-settings.json"
        community_settings = ProviderSettings(str(settings_path))

        with self.assertRaises(ValueError):
            community_settings.save_telegram_community_url("https://example.com/not-telegram")


if __name__ == "__main__":
    unittest.main()
