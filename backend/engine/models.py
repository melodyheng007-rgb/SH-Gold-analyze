from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Zone:
    type: str
    direction: str
    low: float
    high: float
    timeframe: str
    strength: int = 50
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StructureResult:
    timeframe: str
    trend: str
    last_swing_high: Optional[float]
    last_swing_low: Optional[float]
    previous_swing_high: Optional[float]
    previous_swing_low: Optional[float]
    bos: Optional[str]
    choch: Optional[str]
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LiquidityResult:
    buy_side_levels: List[float]
    sell_side_levels: List[float]
    recent_sweep: Optional[str]
    swept_level: Optional[float]
    previous_day_high: Optional[float]
    previous_day_low: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SignalPlan:
    pair: str
    direction: str
    status: str
    score: int
    score_result: str
    setup_type: str
    market_state: str
    liquidity_target: Optional[float]
    entry_zone: Tuple[float, float]
    invalidation_level: float
    target_levels: List[float]
    final_action: str
    confirmation_status: str
    reasons: List[str]
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["entry_zone"] = {"low": self.entry_zone[0], "high": self.entry_zone[1]}
        return data
