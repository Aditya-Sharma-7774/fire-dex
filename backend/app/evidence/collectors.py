"""Evidence collectors: the only code that gathers facts for an analysis.

Everything here is deterministic. Collectors call providers, compute derived
statistics, and record each fact with its source and timestamps. No language
model is involved at any point.

When a collector fails it records the failure on the bundle instead of
raising. A partial bundle with an honest note about what is missing is far
more useful than no analysis at all -- and the orchestrator reports the
reduced coverage rather than hiding it.
"""

import asyncio

from app.blockchain.adapters.evm import EvmAdapter
from app.core.logging import get_logger
from app.evidence.types import EvidenceBuilder, EvidenceBundle, EvidenceKind
from app.indicators.service import build_snapshot, classify_trend
from app.market.candles import CandleProvider
from app.market.service import MarketDataService
from app.risk.scoring import compute_risk_score
from app.tokens.registry import get_token, list_tokens

log = get_logger(__name__)


async def collect_asset_evidence(
    symbol: str,
    *,
    market: MarketDataService,
    candles: CandleProvider,
    interval: str = "1h",
) -> EvidenceBundle:
    """Gather everything known about one asset."""
    symbol = symbol.upper()
    builder = EvidenceBuilder(subject=symbol)

    token = get_token("ethereum", symbol)
    coingecko_id = token.coingecko_id if token else None

    price_task = (
        market.get_prices([coingecko_id]) if coingecko_id else asyncio.sleep(0, result={})
    )
    candle_task = _safe_candles(candles, symbol, interval)

    prices, candle_list = await asyncio.gather(price_task, candle_task)

    # --- price and market statistics ---
    price = prices.get(coingecko_id or "")
    if price is not None:
        builder.add(
            EvidenceKind.PRICE,
            f"{symbol} price",
            round(price.usd, 8),
            unit="USD",
            provider=price.source,
            method="simple/price",
            data_timestamp=price.data_timestamp,
            fetched_at=price.fetched_at,
            is_stale=price.is_stale,
        )
        builder.add(
            EvidenceKind.MARKET_STAT,
            "24h price change",
            round(price.change_24h, 4) if price.change_24h is not None else None,
            unit="%",
            provider=price.source,
            method="simple/price",
            fetched_at=price.fetched_at,
            is_stale=price.is_stale,
        )
        builder.add(
            EvidenceKind.MARKET_STAT,
            "Market capitalisation",
            round(price.market_cap, 2) if price.market_cap is not None else None,
            unit="USD",
            provider=price.source,
            method="simple/price",
            fetched_at=price.fetched_at,
        )
        builder.add(
            EvidenceKind.MARKET_STAT,
            "24h trading volume",
            round(price.volume_24h, 2) if price.volume_24h is not None else None,
            unit="USD",
            provider=price.source,
            method="simple/price",
            fetched_at=price.fetched_at,
        )
    else:
        builder.record_failure(f"No price available for {symbol}")

    # --- indicators ---
    snapshot = None
    if candle_list:
        snapshot = build_snapshot(symbol, interval, candle_list)
        provider_name = "binance"
        method = f"klines/{interval}"

        if snapshot.proxy_for:
            builder.add(
                EvidenceKind.CANDLE_SUMMARY,
                "Candle source note",
                f"Candles are from {snapshot.proxy_for}, used as a proxy for {symbol}",
                provider=provider_name,
                method=method,
            )

        for label, value, unit in [
            ("Last close", round(snapshot.last_close, 8), "USD"),
            ("SMA (20)", _round(snapshot.sma_20), "USD"),
            ("SMA (50)", _round(snapshot.sma_50), "USD"),
            ("SMA (200)", _round(snapshot.sma_200), "USD"),
            ("EMA (12)", _round(snapshot.ema_12), "USD"),
            ("EMA (26)", _round(snapshot.ema_26), "USD"),
            ("RSI (14)", _round(snapshot.rsi_14, 2), None),
            ("MACD line", _round(snapshot.macd_line, 6), None),
            ("MACD signal", _round(snapshot.macd_signal, 6), None),
            ("MACD histogram", _round(snapshot.macd_histogram, 6), None),
            ("Bollinger upper", _round(snapshot.bollinger_upper), "USD"),
            ("Bollinger lower", _round(snapshot.bollinger_lower), "USD"),
            ("Position within Bollinger bands", _round(snapshot.bollinger_position, 4), None),
            ("Support (window low)", _round(snapshot.support), "USD"),
            ("Resistance (window high)", _round(snapshot.resistance), "USD"),
            ("Volume vs average", _round(snapshot.volume_ratio, 4), "x"),
        ]:
            builder.add(
                EvidenceKind.INDICATOR,
                label,
                value,
                unit=unit,
                provider="fire-dex-indicator-engine",
                method=f"{method} + deterministic computation",
                data_timestamp=snapshot.last_candle_time,
            )

        builder.add(
            EvidenceKind.CANDLE_SUMMARY,
            f"Price change over {snapshot.candle_count} {interval} candles",
            _round(snapshot.price_change_pct, 4),
            unit="%",
            provider=provider_name,
            method=method,
            data_timestamp=snapshot.last_candle_time,
        )

        trend = classify_trend(snapshot)
        if trend:
            builder.add(
                EvidenceKind.TREND,
                "Trend classification (moving-average alignment)",
                trend,
                provider="fire-dex-indicator-engine",
                method="classify_trend (documented rules)",
                data_timestamp=snapshot.last_candle_time,
            )
    else:
        builder.record_failure(f"No candle data available for {symbol}")

    # --- risk factors, computed from a published formula ---
    risk = compute_risk_score(snapshot=snapshot, price=price)
    if risk is not None:
        builder.add(
            EvidenceKind.RISK_FACTOR,
            "Risk score (0 low - 100 high)",
            risk.score,
            provider="fire-dex-risk-model",
            method="compute_risk_score (documented weighted formula)",
        )
        for factor in risk.factors:
            builder.add(
                EvidenceKind.RISK_FACTOR,
                f"Risk factor: {factor.name}",
                factor.value,
                unit=factor.unit,
                provider="fire-dex-risk-model",
                method=f"weight {factor.weight}",
            )

    return builder.build()


async def collect_portfolio_evidence(
    chain: str,
    address: str,
    *,
    adapter: EvmAdapter,
    market: MarketDataService,
) -> EvidenceBundle:
    """Gather everything known about a connected wallet."""
    from app.services.portfolio import build_portfolio

    builder = EvidenceBuilder(subject=f"portfolio:{address[:10]}", chain=chain, address=address)

    try:
        snapshot = await build_portfolio(chain, address, adapter, market)
    except Exception as exc:  # noqa: BLE001 - report, do not crash the analysis
        builder.record_failure(f"Portfolio could not be read: {exc}")
        return builder.build()

    builder.add(
        EvidenceKind.PORTFOLIO_STAT,
        "Total portfolio value",
        snapshot.total_value_usd,
        unit="USD",
        provider="fire-dex",
        method="portfolio aggregation",
        fetched_at=snapshot.fetched_at,
    )
    builder.add(
        EvidenceKind.PORTFOLIO_STAT,
        "Number of priced holdings",
        snapshot.priced_count,
        provider="fire-dex",
        method="portfolio aggregation",
    )

    total = snapshot.total_value_usd or 0.0
    stablecoin_value = 0.0
    largest_value = 0.0
    largest_symbol = None
    weights: list[float] = []

    for balance in snapshot.balances:
        if balance.value_usd is None:
            continue
        builder.add(
            EvidenceKind.BALANCE,
            f"{balance.symbol} holding",
            balance.formatted,
            unit=balance.symbol,
            provider="fire-dex",
            method="chain read",
            fetched_at=snapshot.fetched_at,
        )
        builder.add(
            EvidenceKind.BALANCE,
            f"{balance.symbol} value",
            balance.value_usd,
            unit="USD",
            provider="fire-dex",
            method="balance x price",
            fetched_at=snapshot.fetched_at,
        )
        if total > 0:
            weights.append(balance.value_usd / total)
        token = get_token(chain, balance.symbol)
        if token and token.is_stablecoin:
            stablecoin_value += balance.value_usd
        if balance.value_usd > largest_value:
            largest_value = balance.value_usd
            largest_symbol = balance.symbol

    if total > 0:
        # Herfindahl-Hirschman Index: sum of squared weights. 1.0 means
        # everything is in one asset; lower means more spread.
        hhi = sum(w * w for w in weights)
        builder.add(
            EvidenceKind.PORTFOLIO_STAT,
            "Concentration index (HHI, 0 spread - 1 single asset)",
            round(hhi, 4),
            provider="fire-dex-risk-model",
            method="sum of squared portfolio weights",
        )
        builder.add(
            EvidenceKind.PORTFOLIO_STAT,
            "Largest holding share",
            round((largest_value / total) * 100, 2),
            unit="%",
            provider="fire-dex",
            method="largest value / total",
        )
        if largest_symbol:
            builder.add(
                EvidenceKind.PORTFOLIO_STAT,
                "Largest holding",
                largest_symbol,
                provider="fire-dex",
                method="portfolio aggregation",
            )
        builder.add(
            EvidenceKind.PORTFOLIO_STAT,
            "Stablecoin allocation",
            round((stablecoin_value / total) * 100, 2),
            unit="%",
            provider="fire-dex",
            method="stablecoin value / total",
        )

    if snapshot.unpriced_count:
        builder.record_failure(
            f"{snapshot.unpriced_count} holding(s) could not be priced and are excluded"
        )

    return builder.build()


async def collect_chain_evidence(chain: str, adapter: EvmAdapter) -> EvidenceBundle:
    """Network-level state."""
    builder = EvidenceBuilder(subject=f"chain:{chain}", chain=chain)

    try:
        status = await adapter.get_status()
    except Exception as exc:  # noqa: BLE001
        builder.record_failure(f"Chain status unavailable: {exc}")
        return builder.build()

    builder.add(
        EvidenceKind.CHAIN_STATE,
        "Network",
        adapter.config.name,
        provider="fire-dex",
        method="chain registry",
    )
    builder.add(
        EvidenceKind.CHAIN_STATE,
        "Chain ID",
        status.chain_id,
        provider=f"{chain}-rpc",
        method="eth_chainId",
    )
    builder.add(
        EvidenceKind.CHAIN_STATE,
        "Current block height",
        status.block_number,
        provider=f"{chain}-rpc",
        method="eth_blockNumber",
    )
    builder.add(
        EvidenceKind.CHAIN_STATE,
        "Is a test network",
        adapter.config.is_testnet,
        provider="fire-dex",
        method="chain registry",
    )
    return builder.build()


def merge_bundles(subject: str, *bundles: EvidenceBundle) -> EvidenceBundle:
    """Combine bundles into one, renumbering ids so they stay unique.

    Ids are only unique within a bundle, so merging must renumber. Doing it
    anywhere else would silently produce duplicate ids and break citation
    checking in a way that is hard to spot.
    """
    merged = EvidenceBuilder(subject=subject)
    for bundle in bundles:
        merged._bundle.chain = merged._bundle.chain or bundle.chain
        merged._bundle.address = merged._bundle.address or bundle.address
        for item in bundle.items:
            merged.add(
                item.kind,
                item.label,
                item.value,
                unit=item.unit,
                provider=item.source.provider,
                method=item.source.method,
                data_timestamp=item.data_timestamp,
                fetched_at=item.source.fetched_at,
                is_stale=item.source.is_stale,
            )
        for failure in bundle.failures:
            merged.record_failure(failure)
    return merged.build()


async def _safe_candles(provider: CandleProvider, symbol: str, interval: str) -> list:
    """Fetch candles, returning an empty list rather than raising."""
    try:
        return await provider.get_candles(symbol, interval, 300)
    except Exception as exc:  # noqa: BLE001
        log.warning("candles_unavailable", symbol=symbol, error=str(exc))
        return []


def _round(value: float | None, digits: int = 8) -> float | None:
    return None if value is None else round(value, digits)
