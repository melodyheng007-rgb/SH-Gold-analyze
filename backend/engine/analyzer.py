from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from .data_loader import build_timeframes, candles_to_records
from .indicators import atr
from .liquidity import crt_range, detect_liquidity
from .models import SignalPlan, Zone
from .smc import detect_fvg, detect_order_blocks, premium_discount_zone, select_best_zone
from .structure import detect_structure


class GoldAnalyzer:
    def __init__(self):
        self.pair = "XAUUSD"

    def analyze(
        self,
        df_m5: pd.DataFrame,
        timeframes: Dict[str, pd.DataFrame] | None = None,
        source: str = "live",
        include_chart: bool = True,
    ) -> Dict[str, Any]:
        tfs = timeframes or build_timeframes(df_m5)
        for tf, derived in build_timeframes(df_m5).items():
            if tf not in tfs or len(tfs[tf]) == 0:
                tfs[tf] = derived

        structures = {tf: detect_structure(data, tf) for tf, data in tfs.items()}
        liquidity = detect_liquidity(tfs["1H"], tfs["1D"])
        crt_low, crt_high = crt_range(tfs["1H"], 20)
        discount, premium, buy_ote, sell_ote = premium_discount_zone(crt_low, crt_high, "1H")
        fvg15 = detect_fvg(tfs["15M"], "15M")
        ob15 = detect_order_blocks(tfs["15M"], "15M")
        zones: List[Zone] = fvg15 + ob15 + [discount, premium, buy_ote, sell_ote]

        current = float(tfs["5M"]["close"].iloc[-1])
        bias = self._htf_bias(structures["1D"].trend, structures["4H"].trend)
        plan = self._build_plan(
            bias=bias,
            current=current,
            tfs=tfs,
            structures=structures,
            liquidity=liquidity,
            zones=zones,
            discount=discount,
            premium=premium,
            buy_ote=buy_ote,
            sell_ote=sell_ote,
            crt_low=crt_low,
            crt_high=crt_high,
        )

        result = {
            "symbol": self.pair,
            "pair": self.pair,
            "version": "1.7.2",
            "data_source": source,
            "current_price": round(current, 3),
            "bias": self._display_bias(bias),
            "market_state": plan.market_state,
            "timeframes": {tf: s.to_dict() for tf, s in structures.items()},
            "liquidity": liquidity.to_dict(),
            "crt_range": {
                "low": round(crt_low, 3),
                "high": round(crt_high, 3),
                "equilibrium": round((crt_low + crt_high) / 2, 3),
            },
            "zones": [z.to_dict() for z in zones[-24:]],
            "signal": plan.to_dict(),
        }
        if include_chart:
            result["chart"] = {
                "timeframe": "5M",
                "candles": candles_to_records(tfs["5M"], 800),
                "overlays": self._chart_overlays(liquidity, zones, plan, crt_low, crt_high),
            }
        return result

    def _htf_bias(self, d1_trend: str, h4_trend: str) -> str:
        if d1_trend == "bullish" and h4_trend == "bullish":
            return "buy"
        if d1_trend == "bearish" and h4_trend == "bearish":
            return "sell"
        if d1_trend == "neutral" and h4_trend == "neutral":
            return "range"
        return "neutral"

    def _display_bias(self, bias: str) -> str:
        return {
            "buy": "Bullish",
            "sell": "Bearish",
            "range": "Range",
            "neutral": "No Clear Bias",
        }.get(bias, "No Clear Bias")

    def _build_plan(
        self,
        bias: str,
        current: float,
        tfs: Dict[str, pd.DataFrame],
        structures: Dict[str, Any],
        liquidity,
        zones: List[Zone],
        discount: Zone,
        premium: Zone,
        buy_ote: Zone,
        sell_ote: Zone,
        crt_low: float,
        crt_high: float,
    ) -> SignalPlan:
        reasons: List[str] = []
        warnings: List[str] = []
        atr5 = float(atr(tfs["5M"]).iloc[-1])
        crt_mid = (crt_low + crt_high) / 2

        if bias in ["neutral", "range"]:
            warnings.append("1D and 4H do not provide a directional HTF edge.")
            state = "Range HTF structure" if bias == "range" else "No clear HTF bias"
            return self._empty_plan(current, "No Trade", state, warnings)

        direction = "bullish" if bias == "buy" else "bearish"
        expected_sweep = "sell_side_sweep" if bias == "buy" else "buy_side_sweep"
        expected_confirmation = direction
        poi_zone = select_best_zone([z for z in zones if z.type in ["FVG", "OrderBlock"]], direction, current)
        ote_zone = buy_ote if bias == "buy" else sell_ote
        pd_zone = discount if bias == "buy" else premium
        liquidity_target = self._liquidity_target(bias, liquidity)

        score = 0
        if structures["1D"].trend == direction and structures["4H"].trend == direction:
            score += 20
            reasons.append("1D and 4H align for HTF bias.")
        else:
            warnings.append("HTF bias is not fully aligned.")

        in_pd_zone = pd_zone.low <= current <= pd_zone.high
        if in_pd_zone:
            score += 15
            reasons.append("Price is in the correct premium/discount side of the CRT range.")
        else:
            warnings.append("Price is not in the preferred premium/discount area.")

        has_sweep = liquidity.recent_sweep == expected_sweep
        if has_sweep:
            score += 20
            reasons.append(f"Matching liquidity sweep detected: {liquidity.recent_sweep}.")
        else:
            warnings.append("Waiting for the matching liquidity sweep.")

        if poi_zone:
            score += 15
            reasons.append(f"15M point of interest found via {poi_zone.type}.")
        else:
            warnings.append("Waiting for a clean 15M FVG or Order Block.")

        in_ote = ote_zone.low <= current <= ote_zone.high
        if in_ote:
            score += 10
            reasons.append("OTE confluence is present.")
        else:
            warnings.append("OTE confluence is not active.")

        has_5m_confirmation = (
            structures["5M"].bos == expected_confirmation
            or structures["5M"].choch == expected_confirmation
        )
        if has_5m_confirmation:
            score += 20
            reasons.append("5M BOS/CHOCH confirms the setup.")
        else:
            warnings.append("Waiting for 5M BOS or CHOCH confirmation.")

        setup_zone = poi_zone or ote_zone
        entry_low, entry_high = round(setup_zone.low, 3), round(setup_zone.high, 3)
        if bias == "buy":
            invalidation = min(float(tfs["5M"].tail(48)["low"].min()), entry_low, crt_low) - atr5 * 0.3
            targets = [
                liquidity_target or crt_mid,
                crt_high,
                max(crt_high, current + (current - invalidation) * 2),
            ]
        else:
            invalidation = max(float(tfs["5M"].tail(48)["high"].max()), entry_high, crt_high) + atr5 * 0.3
            targets = [
                liquidity_target or crt_mid,
                crt_low,
                min(crt_low, current - (invalidation - current) * 2),
            ]

        status = self._status(score, has_sweep, poi_zone is not None, has_5m_confirmation, current, invalidation, bias)
        confirmation_status = "Confirmed" if has_5m_confirmation else "Waiting"
        final_action = self._final_action(status, bias)
        market_state = self._market_state(bias, has_sweep, poi_zone is not None, has_5m_confirmation)

        return SignalPlan(
            pair=self.pair,
            direction=bias.upper(),
            status=status,
            score=score,
            score_result=self._score_result(score),
            setup_type=setup_zone.type,
            market_state=market_state,
            liquidity_target=round(liquidity_target, 3) if liquidity_target else None,
            entry_zone=(entry_low, entry_high),
            invalidation_level=round(invalidation, 3),
            target_levels=[round(float(t), 3) for t in targets],
            final_action=final_action,
            confirmation_status=confirmation_status,
            reasons=reasons,
            warnings=warnings,
        )

    def _empty_plan(self, current: float, status: str, market_state: str, warnings: List[str]) -> SignalPlan:
        return SignalPlan(
            pair=self.pair,
            direction="WAIT",
            status=status,
            score=0,
            score_result=self._score_result(0),
            setup_type="None",
            market_state=market_state,
            liquidity_target=None,
            entry_zone=(round(current, 3), round(current, 3)),
            invalidation_level=round(current, 3),
            target_levels=[],
            final_action="Stand aside",
            confirmation_status="Not confirmed",
            reasons=[],
            warnings=warnings,
        )

    def _status(
        self,
        score: int,
        has_sweep: bool,
        has_poi: bool,
        has_5m_confirmation: bool,
        current: float,
        invalidation: float,
        bias: str,
    ) -> str:
        invalidated = current <= invalidation if bias == "buy" else current >= invalidation
        if invalidated:
            return "Invalidated"
        if not has_sweep:
            return "Waiting for Liquidity Sweep"
        if not has_poi:
            return "Waiting for POI"
        if not has_5m_confirmation:
            return "Waiting for 5M Confirmation"
        if score >= 85:
            return "High Quality Setup"
        if score >= 75:
            return "Valid Setup"
        if score >= 60:
            return "No Trade"
        return "No Trade"

    def _score_result(self, score: int) -> str:
        if score >= 85:
            return "Valid High Quality Setup"
        if score >= 75:
            return "Waiting Confirmation"
        if score >= 60:
            return "Weak Setup"
        return "No Trade"

    def _final_action(self, status: str, bias: str) -> str:
        if status in ["Valid Setup", "High Quality Setup"]:
            return f"Prepare {bias.upper()} execution at the setup zone."
        if status == "Invalidated":
            return "Invalidate the idea and wait for a new structure cycle."
        return "Wait. Do not force an entry."

    def _market_state(self, bias: str, has_sweep: bool, has_poi: bool, has_5m_confirmation: bool) -> str:
        if bias == "neutral":
            return "No directional HTF edge"
        if has_sweep and has_poi and has_5m_confirmation:
            return "Confirmed XAUUSD setup"
        if has_sweep and has_poi:
            return "POI formed, waiting for 5M confirmation"
        if has_sweep:
            return "Liquidity swept, waiting for POI"
        return "HTF bias set, waiting for liquidity sweep"

    def _liquidity_target(self, bias: str, liquidity) -> float | None:
        levels = liquidity.buy_side_levels if bias == "buy" else liquidity.sell_side_levels
        if not levels:
            return None
        return float(max(levels) if bias == "buy" else min(levels))

    def _chart_overlays(self, liquidity, zones: List[Zone], plan: SignalPlan, crt_low: float, crt_high: float) -> Dict[str, Any]:
        equilibrium = (crt_low + crt_high) / 2
        levels = [
            {"type": "previous_day_high", "price": liquidity.previous_day_high, "label": "PDH"},
            {"type": "previous_day_low", "price": liquidity.previous_day_low, "label": "PDL"},
            {"type": "crt_high", "price": crt_high, "label": "CRT High"},
            {"type": "crt_low", "price": crt_low, "label": "CRT Low"},
            {"type": "equilibrium", "price": equilibrium, "label": "EQ"},
            {"type": "invalidation", "price": plan.invalidation_level, "label": "Invalidation"},
        ]
        levels.extend({"type": "equal_high", "price": level, "label": "EQH"} for level in liquidity.buy_side_levels)
        levels.extend({"type": "equal_low", "price": level, "label": "EQL"} for level in liquidity.sell_side_levels)
        if liquidity.swept_level:
            levels.append({"type": "liquidity_sweep", "price": liquidity.swept_level, "label": "Sweep"})
        levels.extend(
            {"type": "target", "price": target, "label": f"Target {idx}"}
            for idx, target in enumerate(plan.target_levels, start=1)
        )

        chart_zones = [z.to_dict() for z in zones if z.type in ["FVG", "OrderBlock", "OTE", "Premium", "Discount"]][-18:]
        chart_zones.append({
            "type": "Entry",
            "direction": "bullish" if plan.direction == "BUY" else "bearish",
            "low": plan.entry_zone[0],
            "high": plan.entry_zone[1],
            "timeframe": "5M",
            "strength": plan.score,
            "reason": "Setup entry zone",
        })
        return {
            "levels": [level for level in levels if level["price"] is not None],
            "zones": chart_zones,
        }
