from __future__ import annotations

import hashlib
from typing import Any


DELIVERY_PROTOCOL = "LIVE_ANALYSIS_V2"


def build_analysis_revision(
    state_key: str,
    closed_candle_time: int,
    input_signature: tuple[Any, ...],
    app_version: str,
) -> str:
    """Build a stable revision shared by every client and backend worker."""
    payload = "|".join(
        (
            DELIVERY_PROTOCOL,
            str(app_version or ""),
            str(state_key or ""),
            str(int(closed_candle_time)),
            repr(input_signature),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def should_deliver_analysis(
    analysis: Any,
    current_revision: str | None,
    known_revision: str | None,
) -> bool:
    if not isinstance(analysis, dict) or not analysis:
        return False
    revision = str(current_revision or "").strip()
    known = str(known_revision or "").strip()
    return not revision or revision != known
