import os
import unittest
from unittest.mock import Mock, patch

from engine.auth_guard import AuthGuardError, SupabaseAuthGuard


class SupabaseAuthGuardTests(unittest.TestCase):
    def make_guard(self, **overrides):
        values = {
            "AUTH_REQUIRED": "true",
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
            "AUTH_CACHE_SECONDS": "45",
            "ADMIN_EMAILS": "",
            **overrides,
        }
        with patch.dict(os.environ, values, clear=False):
            return SupabaseAuthGuard()

    def test_auth_is_optional_for_local_development(self):
        guard = self.make_guard(AUTH_REQUIRED="false")
        self.assertFalse(guard.protects("GET", "/api/market/chart-live"))

    def test_auth_is_required_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            guard = SupabaseAuthGuard()
        self.assertTrue(guard.required)
        self.assertTrue(guard.protects("GET", "/api/market/chart-live"))

    def test_health_and_preflight_remain_public(self):
        guard = self.make_guard()
        self.assertFalse(guard.protects("GET", "/api/health"))
        self.assertFalse(guard.protects("OPTIONS", "/api/market/chart-live"))
        self.assertTrue(guard.protects("GET", "/api/market/chart-live"))
        self.assertTrue(guard.protects("GET", "/docs"))

    def test_sensitive_tools_require_admin_role(self):
        guard = self.make_guard()
        self.assertTrue(guard.requires_admin("/api/xauusd/provider-settings"))
        self.assertTrue(guard.requires_admin("/api/xauusd/reset-database"))
        self.assertFalse(guard.requires_admin("/api/market/chart-live"))

    def test_local_owner_mode_only_allows_loopback_clients(self):
        guard = self.make_guard(SH_LOCAL_OWNER_MODE="true")
        self.assertTrue(guard.permits_local_owner("127.0.0.1"))
        self.assertTrue(guard.permits_local_owner("::1"))
        self.assertTrue(guard.permits_local_owner("localhost"))
        self.assertFalse(guard.permits_local_owner("192.168.1.20"))

    def test_local_owner_mode_is_disabled_by_default(self):
        guard = self.make_guard(SH_LOCAL_OWNER_MODE="false")
        self.assertFalse(guard.permits_local_owner("127.0.0.1"))

    def test_missing_bearer_token_is_rejected(self):
        guard = self.make_guard()
        with self.assertRaises(AuthGuardError) as captured:
            guard.verify("")
        self.assertEqual(captured.exception.status_code, 401)
        self.assertEqual(captured.exception.code, "AUTH_REQUIRED")

    def test_valid_user_is_cached_without_storing_plain_token(self):
        guard = self.make_guard()
        response = Mock(status_code=200)
        response.json.return_value = {
            "id": "user-123",
            "email": "user@example.com",
            "role": "authenticated",
            "aud": "authenticated",
            "app_metadata": {"role": "admin"},
        }
        guard._session.get = Mock(return_value=response)

        first = guard.verify("Bearer access-token")
        second = guard.verify("Bearer access-token")

        self.assertEqual(first["id"], "user-123")
        self.assertEqual(first["app_role"], "admin")
        self.assertEqual(second, first)
        guard._session.get.assert_called_once()
        self.assertNotIn("access-token", guard._cache)

    def test_configured_owner_email_receives_admin_role(self):
        guard = self.make_guard(ADMIN_EMAILS=" owner@example.com,second@example.com ")
        response = Mock(status_code=200)
        response.json.return_value = {
            "id": "owner-123",
            "email": "Owner@Example.com",
            "role": "authenticated",
            "aud": "authenticated",
            "app_metadata": {},
        }
        guard._session.get = Mock(return_value=response)

        user = guard.verify("Bearer owner-token")

        self.assertEqual(user["email"], "owner@example.com")
        self.assertEqual(user["app_role"], "admin")
        self.assertTrue(user["is_admin"])

    def test_regular_email_cannot_self_promote_with_user_metadata(self):
        guard = self.make_guard(ADMIN_EMAILS="owner@example.com")
        response = Mock(status_code=200)
        response.json.return_value = {
            "id": "user-123",
            "email": "user@example.com",
            "role": "authenticated",
            "aud": "authenticated",
            "app_metadata": {},
            "user_metadata": {"role": "admin"},
        }
        guard._session.get = Mock(return_value=response)

        user = guard.verify("Bearer user-token")

        self.assertEqual(user["app_role"], "user")
        self.assertFalse(user["is_admin"])

    def test_owner_email_policy_disables_local_admin_bypass(self):
        guard = self.make_guard(
            ADMIN_EMAILS="owner@example.com",
            SH_LOCAL_OWNER_MODE="true",
        )

        self.assertFalse(guard.permits_local_owner("127.0.0.1"))


if __name__ == "__main__":
    unittest.main()
