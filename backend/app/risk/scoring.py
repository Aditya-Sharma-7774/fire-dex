"""The risk model.

THE SCORE IS COMPUTED HERE, NOT BY A LANGUAGE MODEL.

If an examiner asks "how did you arrive at 68 out of 100?", the answer must
be a formula that can be shown and recomputed. A number produced by a model
cannot be defended, and a confident-sounding risk score with no methodology
behind it is exactly the kind of thing this project exists to avoid.

The Risk Agent's job is to EXPLAIN the factors below. It does not choose the
number.

METHODOLOGY
-----------
Each factor is normalised to 0-100, where higher means more risk, then
combined as a weighted average of whichever factors could be computed. The
weights are declared here and documented in docs/EVALUATION.md.

Factors that cannot be computed are dropped and the remaining weights are
renormalised, so a missing input lowers CONFIDENCE in the score rather than
silently contributing a zero.
"""

from dataclasses import dataclass, field

from app.indicators.service import IndicatorSnapshot
from app.market.types import Price


@dataclass
class RiskFactor:
    """One contributing factor."""

    name: str
    #: The raw measured value, recorded as evidence.
    value: float
    unit: str | None
    #: Normalised 0-100 contribution, higher meaning more risk.
    normalised: float
    weight: float
    explanation: str


@dataclass
class RiskScore:
    score: float
    factors: list[RiskFactor] = field(default_factory=list)
    #: Fraction of total weight we were able to compute.
    coverage: float = 1.0
    note: str = ""


# Declared weights. They sum to 1.0 when every factor is available.
WEIGHTS = {
    "volatility": 0.35,
    "liquidity": 0.25,
    "momentum_extremity": 0.20,
    "drawdown_from_high": 0.20,
}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def compute_risk_score(
    *,
    snapshot: IndicatorSnapshot | None,
    price: Price | None,
) -> RiskScore | None:
    """Compute the risk score from available measurements.

    Returns None when nothing at all could be computed -- which is reported
    as "risk could not be assessed", never as a risk of zero.
    """
    factors: list[RiskFactor] = []

    # --- volatility -------------------------------------------------
    # Annualised realised volatility. 0% maps to 0, 150%+ maps to 100;
    # crypto routinely runs 50-100%, so this range keeps typical assets
    # spread across the middle of the scale rather than pinned at the top.
    if snapshot and snapshot.realised_volatility is not None:
        vol_pct = snapshot.realised_volatility * 100
        factors.append(
            RiskFactor(
                name="volatility",
                value=round(vol_pct, 2),
                unit="% annualised",
                normalised=_clamp(vol_pct / 1.5),
                weight=WEIGHTS["volatility"],
                explanation="Annualised realised volatility from log returns",
            )
        )

    # --- liquidity --------------------------------------------------
    # Volume relative to market cap. A thinly traded asset is harder to exit,
    # so LOW turnover means HIGH risk -- note the inversion.
    if price and price.volume_24h and price.market_cap and price.market_cap > 0:
        turnover = price.volume_24h / price.market_cap
        factors.append(
            RiskFactor(
                name="liquidity",
                value=round(turnover * 100, 4),
                unit="% of market cap traded in 24h",
                # 10% turnover or more is treated as fully liquid.
                normalised=_clamp(100 - (turnover / 0.10) * 100),
                weight=WEIGHTS["liquidity"],
                explanation="24h volume as a share of market cap; lower is riskier",
            )
        )

    # --- momentum extremity -----------------------------------------
    # Distance of RSI from its midpoint. Both extremes are treated as
    # elevated risk: strongly overbought and strongly oversold conditions
    # are each associated with sharper moves than a neutral reading.
    if snapshot and snapshot.rsi_14 is not None:
        distance = abs(snapshot.rsi_14 - 50)
        factors.append(
            RiskFactor(
                name="momentum_extremity",
                value=round(snapshot.rsi_14, 2),
                unit="RSI",
                normalised=_clamp((distance / 50) * 100),
                weight=WEIGHTS["momentum_extremity"],
                explanation="Distance of RSI from the neutral midpoint of 50",
            )
        )

    # --- drawdown from window high ----------------------------------
    if snapshot and snapshot.resistance and snapshot.resistance > 0:
        drawdown = (snapshot.resistance - snapshot.last_close) / snapshot.resistance
        factors.append(
            RiskFactor(
                name="drawdown_from_high",
                value=round(drawdown * 100, 2),
                unit="% below window high",
                # A 50% drawdown maps to the top of the scale.
                normalised=_clamp((drawdown / 0.5) * 100),
                weight=WEIGHTS["drawdown_from_high"],
                explanation="How far price sits below the highest high in the window",
            )
        )

    if not factors:
        return None

    # Renormalise across the factors we actually have, so a missing input
    # does not drag the score toward zero.
    total_weight = sum(f.weight for f in factors)
    score = sum(f.normalised * f.weight for f in factors) / total_weight
    coverage = total_weight / sum(WEIGHTS.values())

    note = ""
    if coverage < 1.0:
        missing = sorted(set(WEIGHTS) - {f.name for f in factors})
        note = f"Computed from {len(factors)} of {len(WEIGHTS)} factors; missing: {', '.join(missing)}"

    return RiskScore(
        score=round(score, 1),
        factors=factors,
        coverage=round(coverage, 3),
        note=note,
    )
