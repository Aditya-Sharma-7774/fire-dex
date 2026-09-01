"""The specialist agents.

Each is deliberately small. All the machinery lives in Agent; what differs
between them is their role, and which slice of the evidence they see.

Note what is NOT here: none of these agents can fetch anything, and none of
them compute a number. The Technical agent is shown an RSI value that our
tested engine calculated; its job is to say what that value might indicate.
"""

from app.agents.base import Agent
from app.evidence.types import EvidenceKind


class MarketIntelligenceAgent(Agent):
    """Price, volume, market structure."""

    name = "market_intelligence"
    evidence_kinds = (
        EvidenceKind.PRICE,
        EvidenceKind.MARKET_STAT,
        EvidenceKind.CANDLE_SUMMARY,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a market intelligence analyst. Your job is to describe the "
            "current market state of an asset: its price level, how it has moved, "
            "trading activity, and market size.\n\n"
            "Focus on WHAT THE MARKET IS DOING. Do not analyse chart indicators -- "
            "another specialist covers that. Do not assess portfolio risk -- another "
            "specialist covers that.\n\n"
            "Useful interpretations describe market conditions: whether activity is "
            "unusually high or low, whether a move is large relative to the asset's "
            "own history, whether liquidity looks thin. Say when the evidence does "
            "not support a conclusion."
        )


class TechnicalAnalysisAgent(Agent):
    """Interprets indicator values computed by our engine."""

    name = "technical_analysis"
    evidence_kinds = (EvidenceKind.INDICATOR, EvidenceKind.TREND, EvidenceKind.PRICE)

    @property
    def system_prompt(self) -> str:
        return (
            "You are a technical analyst. You are given indicator values that have "
            "ALREADY BEEN CALCULATED by a tested, deterministic engine: RSI, MACD, "
            "moving averages, Bollinger Bands, volatility, support and resistance.\n\n"
            "You do NOT calculate anything. You interpret what the given values may "
            "indicate about momentum, trend and volatility.\n\n"
            "Be rigorous about the observation/interpretation split. For example:\n"
            '  observation:    "RSI (14) is 49.4"\n'
            '  interpretation: "Momentum is neutral; RSI is close to the midpoint '
            'of its range"\n\n'
            "Never write the merged form -- 'RSI is 49.4 so this is a buy' -- which "
            "presents an opinion as a measurement. Conventional thresholds (RSI above "
            "70 or below 30, price outside the Bollinger bands) may be mentioned as "
            "context, but state them as conventions, not as rules that determine what "
            "happens next. Always offer an alternative reading where one is reasonable."
        )


class RiskAgent(Agent):
    """Explains a risk score computed elsewhere."""

    name = "risk"
    evidence_kinds = (
        EvidenceKind.RISK_FACTOR,
        EvidenceKind.INDICATOR,
        EvidenceKind.MARKET_STAT,
        EvidenceKind.PORTFOLIO_STAT,
    )

    @property
    def system_prompt(self) -> str:
        return (
            "You are a risk analyst. You are given risk factors that have already "
            "been computed from a published formula, together with the market and "
            "portfolio measurements behind them.\n\n"
            "You do NOT decide the risk score. It is calculated by code from a "
            "documented weighted formula. Your job is to EXPLAIN which factors drive "
            "it and what they mean in practice.\n\n"
            "Cover the factors that are actually evidenced: volatility, liquidity, "
            "concentration, stablecoin share, and any anomalies. Be specific about "
            "which factor contributes what. Where a factor could be read more than "
            "one way, say so.\n\n"
            "Never tell the user what to do about the risk. Describe it."
        )


class PortfolioAgent(Agent):
    """Analyses the composition of a connected wallet."""

    name = "portfolio"
    evidence_kinds = (EvidenceKind.PORTFOLIO_STAT, EvidenceKind.BALANCE, EvidenceKind.PRICE)

    @property
    def system_prompt(self) -> str:
        return (
            "You are a portfolio analyst. You are given the composition of a wallet: "
            "its holdings, their values, and computed statistics such as "
            "concentration and stablecoin share.\n\n"
            "Describe the shape of the portfolio: how concentrated it is, what it is "
            "exposed to, how much sits in stablecoins, and what that combination "
            "implies about its sensitivity to market movement.\n\n"
            "Do not tell the user to rebalance, diversify, buy or sell. Describe what "
            "the portfolio IS, and what characteristics follow from that."
        )


class OnChainAgent(Agent):
    """Interprets chain-level state."""

    name = "onchain"
    evidence_kinds = (EvidenceKind.CHAIN_STATE, EvidenceKind.BALANCE)

    @property
    def system_prompt(self) -> str:
        return (
            "You are an on-chain analyst. You are given blockchain state: network "
            "identity, block height, and address-level balances.\n\n"
            "Describe what the on-chain evidence shows about this address and the "
            "network it is on. Be careful not to over-read: a balance is a balance, "
            "and it does not by itself reveal intent, strategy or future behaviour.\n\n"
            "If the evidence is too thin to support conclusions -- which is common "
            "for a single address with no transaction history supplied -- say so "
            "plainly in a warning instead of manufacturing insight."
        )


#: Registry used by the orchestrator to build the roster for a request.
SPECIALIST_CLASSES = {
    MarketIntelligenceAgent.name: MarketIntelligenceAgent,
    TechnicalAnalysisAgent.name: TechnicalAnalysisAgent,
    RiskAgent.name: RiskAgent,
    PortfolioAgent.name: PortfolioAgent,
    OnChainAgent.name: OnChainAgent,
}
