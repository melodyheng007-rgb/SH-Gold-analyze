from __future__ import annotations

from typing import List, Tuple
from .models import StructureResult, LiquidityResult, Zone


def quality_from_score(score: int) -> str:
    if score >= 85:
        return "A+"
    if score >= 75:
        return "A"
    if score >= 65:
        return "B"
    if score >= 55:
        return "C"
    return "NO TRADE"


def score_signal(
    direction: str,
    d1: StructureResult,
    h4: StructureResult,
    h1: StructureResult,
    m15_zone: Zone | None,
    m5: StructureResult,
    liquidity: LiquidityResult,
    in_ote: bool,
    in_crt_extreme: bool,
) -> Tuple[int, List[str], List[str]]:
    score = 0
    reasons: List[str] = []
    warnings: List[str] = []
    expected_trend = "bullish" if direction == "buy" else "bearish"
    expected_sweep = "sell_side_sweep" if direction == "buy" else "buy_side_sweep"

    if d1.trend == expected_trend:
        score += 20
        reasons.append(f"1D bias aligns with {direction.upper()}")
    else:
        warnings.append("1D bias does not confirm the trade direction")

    if h4.trend == expected_trend:
        score += 20
        reasons.append(f"4H structure aligns with {direction.upper()}")
    else:
        warnings.append("4H structure does not confirm the trade direction")

    h1_context = liquidity.recent_sweep == expected_sweep or in_crt_extreme
    if liquidity.recent_sweep == expected_sweep:
        score += 20
        reasons.append(f"Liquidity sweep detected: {liquidity.recent_sweep}")
    elif in_crt_extreme:
        score += 15
        reasons.append("Price is reacting from the 1H CRT extreme")
    else:
        warnings.append("No matching 1H liquidity sweep or CRT extreme")

    if m15_zone:
        score += 20
        reasons.append(f"15M {m15_zone.type} zone found")
    else:
        warnings.append("No clean 15M OB/FVG zone")

    if m5.choch == expected_trend or m5.bos == expected_trend:
        score += 20
        reasons.append("5M confirmation found")
    else:
        warnings.append("Wait for 5M CHOCH/BOS confirmation")

    if in_ote:
        score += 5
        reasons.append("Price is inside OTE / premium-discount confluence")

    if h1.trend not in [expected_trend, "neutral"]:
        warnings.append("1H structure is fighting the setup")

    return min(score, 100), reasons, warnings
