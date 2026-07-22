from __future__ import annotations

import hashlib
import ipaddress
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


def _enabled(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AuthGuardError(Exception):
    code: str
    status_code: int
    message: str


class SupabaseAuthGuard:
    """Validate browser access tokens with Supabase Auth and briefly cache valid users."""

    PUBLIC_PATHS = {"/api/health", "/api/client-errors"}
    ADMIN_PATHS = {
        "/api/debug",
        "/api/routes",
        "/api/xauusd/debug-data",
        "/api/xauusd/provider-credentials",
        "/api/xauusd/provider-settings",
        "/api/xauusd/verify-oanda",
        "/api/xauusd/start-live-builder",
        "/api/xauusd/stop-live-builder",
        "/api/xauusd/seed-history",
        "/api/xauusd/reload-history",
        "/api/xauusd/generate-test-history",
        "/api/xauusd/generate-test-history-v2",
        "/api/xauusd/generate-live-anchored-test-history",
        "/api/xauusd/clear-test-history",
        "/api/xauusd/archive-stale-history",
        "/api/xauusd/set-data-mode",
        "/api/xauusd/fix-gap",
        "/api/xauusd/one-click-data-setup",
        "/api/xauusd/one-click-warmup",
        "/api/xauusd/smart-setup",
        "/api/xauusd/toggle-test-mode",
        "/api/xauusd/download-free-history",
        "/api/xauusd/sync-real-history",
        "/api/xauusd/set-engine-mode",
        "/api/xauusd/clear-cache",
        "/api/xauusd/clear-analysis-cache",
        "/api/xauusd/engine-logs",
        "/api/xauusd/clear-logs",
        "/api/xauusd/upload-csv",
        "/api/xauusd/rebuild-candles",
        "/api/xauusd/rebuild-candle-engine",
        "/api/xauusd/clear-invalid-candles",
        "/api/xauusd/import-recent-history",
        "/api/xauusd/import-real-recent-history",
        "/api/xauusd/import-real-history",
        "/api/xauusd/real-mode-wizard",
        "/api/xauusd/reset-database",
        "/api/market/diamond-validation/run",
        "/api/alerts/telegram-settings",
        "/api/alerts/telegram-test",
    }

    def __init__(self) -> None:
        required_setting = os.getenv("AUTH_REQUIRED")
        self.required = True if required_setting is None else _enabled(required_setting)
        self.supabase_url = str(os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
        self.publishable_key = str(
            os.getenv("SUPABASE_PUBLISHABLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or ""
        ).strip()
        self.configured = bool(self.supabase_url and self.publishable_key)
        self.local_owner_mode = _enabled(os.getenv("SH_LOCAL_OWNER_MODE"))
        self.admin_emails = {
            email.strip().lower()
            for email in str(os.getenv("ADMIN_EMAILS") or "").split(",")
            if email.strip()
        }
        self._session = requests.Session()
        self._cache: OrderedDict[str, tuple[float, Dict[str, Any]]] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._cache_seconds = max(5, min(120, int(os.getenv("AUTH_CACHE_SECONDS") or 45)))

    def protects(self, method: str, path: str) -> bool:
        return bool(
            self.required
            and str(method or "").upper() != "OPTIONS"
            and path not in self.PUBLIC_PATHS
        )

    def requires_admin(self, path: str) -> bool:
        return path in self.ADMIN_PATHS or path in {"/", "/docs", "/openapi.json", "/redoc"}

    def permits_local_owner(self, client_host: Optional[str]) -> bool:
        """Allow an authenticated local developer to manage feed credentials."""
        if not self.local_owner_mode or self.admin_emails:
            return False
        host = str(client_host or "").strip().strip("[]")
        if host.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def verify(self, authorization: Optional[str]) -> Dict[str, Any]:
        if not self.configured:
            raise AuthGuardError("AUTH_NOT_CONFIGURED", 503, "Authentication is not configured on the backend.")
        scheme, _, token = str(authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AuthGuardError("AUTH_REQUIRED", 401, "Sign in is required to use this API.")

        token = token.strip()
        cache_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and cached[0] > now:
                self._cache.move_to_end(cache_key)
                return dict(cached[1])
            if cached:
                self._cache.pop(cache_key, None)

        try:
            response = self._session.get(
                f"{self.supabase_url}/auth/v1/user",
                headers={
                    "apikey": self.publishable_key,
                    "Authorization": f"Bearer {token}",
                },
                timeout=6,
            )
        except requests.RequestException as exc:
            raise AuthGuardError("AUTH_PROVIDER_UNAVAILABLE", 503, "Authentication provider is temporarily unavailable.") from exc

        if response.status_code != 200:
            raise AuthGuardError("INVALID_SESSION", 401, "Your session is invalid or expired. Please sign in again.")
        try:
            user = response.json()
        except ValueError as exc:
            raise AuthGuardError("INVALID_AUTH_RESPONSE", 503, "Authentication provider returned an invalid response.") from exc
        if not user.get("id"):
            raise AuthGuardError("INVALID_SESSION", 401, "Your session is invalid or expired. Please sign in again.")

        email = str(user.get("email") or "").strip().lower()
        metadata_role = str((user.get("app_metadata") or {}).get("role") or "user").lower()
        app_role = "admin" if metadata_role == "admin" or email in self.admin_emails else "user"
        public_user = {
            "id": user.get("id"),
            "email": email,
            "role": user.get("role") or "authenticated",
            "aud": user.get("aud") or "authenticated",
            "app_role": app_role,
            "is_admin": app_role == "admin",
        }
        with self._cache_lock:
            self._cache[cache_key] = (now + self._cache_seconds, public_user)
            self._cache.move_to_end(cache_key)
            while len(self._cache) > 256:
                self._cache.popitem(last=False)
        return dict(public_user)

    def status(self) -> Dict[str, Any]:
        return {
            "required": self.required,
            "configured": self.configured,
            "provider": "SUPABASE" if self.configured else "NOT_CONFIGURED",
            "local_owner_mode": self.local_owner_mode,
            "admin_policy_configured": bool(self.admin_emails),
        }
