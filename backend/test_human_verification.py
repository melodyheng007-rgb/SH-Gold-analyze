import unittest
from unittest.mock import Mock, patch

from engine.human_verification import HumanVerificationService, RequestAbuseGuard


class HumanVerificationTests(unittest.TestCase):
    def test_unconfigured_service_is_optional_for_local_development(self):
        with patch.dict("os.environ", {}, clear=True):
            service = HumanVerificationService()

        result = service.verify("", "127.0.0.1", "account_access")

        self.assertTrue(result["success"])
        self.assertFalse(result["configured"])

    def test_configured_service_validates_action_and_hostname(self):
        with patch.dict("os.environ", {
            "TURNSTILE_SECRET_KEY": "secret",
            "TURNSTILE_ALLOWED_HOSTNAMES": "app.example.com",
        }, clear=True):
            service = HumanVerificationService()
        response = Mock()
        response.json.return_value = {
            "success": True,
            "hostname": "app.example.com",
            "action": "account_access",
        }
        service._session.post = Mock(return_value=response)

        result = service.verify("one-time-token", "203.0.113.10", "account_access")

        self.assertTrue(result["success"])
        service._session.post.assert_called_once()

    def test_wrong_hostname_is_rejected(self):
        with patch.dict("os.environ", {
            "TURNSTILE_SECRET_KEY": "secret",
            "TURNSTILE_ALLOWED_HOSTNAMES": "app.example.com",
        }, clear=True):
            service = HumanVerificationService()
        response = Mock()
        response.json.return_value = {
            "success": True,
            "hostname": "lookalike.example",
            "action": "account_access",
        }
        service._session.post = Mock(return_value=response)

        result = service.verify("one-time-token", None, "account_access")

        self.assertFalse(result["success"])
        self.assertFalse(result["hostname_allowed"])

    def test_turnstile_endpoint_has_a_small_burst_limit(self):
        with patch.dict("os.environ", {"TURNSTILE_RATE_LIMIT_PER_MINUTE": "3"}, clear=True):
            guard = RequestAbuseGuard()

        for _ in range(3):
            self.assertTrue(guard.check("client", "/api/security/turnstile/verify")["allowed"])
        self.assertFalse(guard.check("client", "/api/security/turnstile/verify")["allowed"])


if __name__ == "__main__":
    unittest.main()
