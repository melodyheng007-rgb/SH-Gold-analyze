from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

import requests


def _enabled(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class HumanVerificationService:
    """Verify one-time Cloudflare Turnstile tokens for non-Supabase auth flows."""

    VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

    def __init__(self) -> None:
        self.secret_key = str(os.getenv("TURNSTILE_SECRET_KEY") or "").strip()
        self.allowed_hostnames = {
            value.strip().lower()
            for value in str(os.getenv("TURNSTILE_ALLOWED_HOSTNAMES") or "").split(",")
            if value.strip()
        }
        self._session = requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.secret_key)

    def status(self) -> Dict[str, Any]:
        return {
            "configured": self.configured,
            "provider": "CLOUDFLARE_TURNSTILE" if self.configured else "NOT_CONFIGURED",
            "hostname_policy": "RESTRICTED" if self.allowed_hostnames else "TURNSTILE_WIDGET_POLICY",
        }

    def verify(self, token: str, remote_ip: Optional[str], expected_action: str) -> Dict[str, Any]:
        if not self.configured:
            return {"success": True, "configured": False, "reason": "TURNSTILE_NOT_CONFIGURED"}
        response_token = str(token or "").strip()
        if not response_token:
            return {"success": False, "configured": True, "reason": "CHALLENGE_REQUIRED"}
        payload = {
            "secret": self.secret_key,
            "response": response_token,
        }
        if remote_ip:
            payload["remoteip"] = remote_ip
        try:
            response = self._session.post(self.VERIFY_URL, data=payload, timeout=8)
            result = response.json()
        except (requests.RequestException, ValueError):
            return {"success": False, "configured": True, "reason": "VERIFICATION_UNAVAILABLE"}

        hostname = str(result.get("hostname") or "").lower()
        action = str(result.get("action") or "")
        hostname_allowed = not self.allowed_hostnames or hostname in self.allowed_hostnames
        action_allowed = not action or action == expected_action
        success = bool(result.get("success") and hostname_allowed and action_allowed)
        return {
            "success": success,
            "configured": True,
            "reason": "VERIFIED" if success else "CHALLENGE_REJECTED",
            "hostname_allowed": hostname_allowed,
            "action_allowed": action_allowed,
            "error_codes": list(result.get("error-codes") or []),
        }


class RequestAbuseGuard:
    """Small in-process burst guard; edge WAF remains the primary DDoS control."""

    def __init__(self) -> None:
        self.general_limit = max(0, int(os.getenv("API_RATE_LIMIT_PER_MINUTE") or 0))
        self.turnstile_limit = max(3, int(os.getenv("TURNSTILE_RATE_LIMIT_PER_MINUTE") or 10))
        self._windows: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, client_key: str, path: str) -> Dict[str, Any]:
        limit = self.turnstile_limit if path == "/api/security/turnstile/verify" else self.general_limit
        if limit <= 0:
            return {"allowed": True, "limit": 0, "retry_after": 0}
        now = time.monotonic()
        key = f"{client_key}:{path if path == '/api/security/turnstile/verify' else 'api'}"
        with self._lock:
            window = self._windows[key]
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= limit:
                retry_after = max(1, round(60 - (now - window[0])))
                return {"allowed": False, "limit": limit, "retry_after": retry_after}
            window.append(now)
            if len(self._windows) > 2048:
                stale = [name for name, values in self._windows.items() if not values or now - values[-1] >= 120]
                for name in stale[:512]:
                    self._windows.pop(name, None)
        return {"allowed": True, "limit": limit, "retry_after": 0}

    @staticmethod
    def client_key(headers: Any, fallback: Optional[str]) -> str:
        cloudflare_ip = str(headers.get("CF-Connecting-IP") or "").strip()
        if cloudflare_ip:
            return cloudflare_ip[:64]
        forwarded = str(headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        return (forwarded or str(fallback or "unknown"))[:64]

