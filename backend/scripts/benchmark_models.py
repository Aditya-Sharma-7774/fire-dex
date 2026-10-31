"""Run one real analysis against several models and compare them.

    .venv\\Scripts\\python.exe scripts\\benchmark_models.py
    .venv\\Scripts\\python.exe scripts\\benchmark_models.py --models gemini:gemini-3.5-flash qwen2.5:3b-instruct-q4_K_M

A model is an Ollama name unless prefixed with `gemini:` or `groq:`. The
prefix is needed because Ollama names themselves contain colons.

What keeps this a fair comparison rather than a demo:

  * ONE evidence bundle is collected and reused for every model, so market
    movement between runs cannot change the inputs. Only the model varies.

  * Each model is driven through a bare provider, never the failover chain.
    A model that fails must be recorded as failing -- a silent switch to
    another provider would report a result that model never produced.

  * Citation breadth is reported beside the scores. Evidence coverage and
    agent agreement both rise when every claim cites everything, and the
    validator does not object to an irrelevant citation. A model that wins on
    coverage while citing ten items per claim has not reasoned better; it has
    found a weakness in the metric. Reading the two together tells them apart.

Nothing is written to the database. This measures; it does not record.
"""

import argparse
import asyncio
import pathlib
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.agents.contract import AgentStatus  # noqa: E402
from app.agents.orchestrator import run_analysis  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.evidence.collectors import collect_asset_evidence  # noqa: E402
from app.indicators.service import build_snapshot  # noqa: E402
from app.llm.provider import GeminiProvider, GroqProvider, LlmProvider, OllamaProvider  # noqa: E402
from app.market.candles import get_candle_provider  # noqa: E402
from app.market.service import get_market_service  # noqa: E402

DEFAULT_MODELS = [
    "llama3.1:8b",
    "qwen2.5:7b-instruct-q4_K_M",
    "qwen2.5:3b-instruct-q4_K_M",
]

#: A claim citing at least this many evidence items is counted as broad.
BROAD_CITATION = 5


def build_provider(spec: str, settings: Settings) -> LlmProvider:
    if spec.startswith("gemini:"):
        return GeminiProvider(settings.gemini_api_key, spec.removeprefix("gemini:"))
    if spec.startswith("groq:"):
        return GroqProvider(settings.groq_api_key, spec.removeprefix("groq:"))
    return OllamaProvider(settings.ollama_base_url, spec)


async def warm(provider: LlmProvider) -> float:
    """Load a local model into memory, excluded from the measured run.

    A cold load reads gigabytes from disk, which would otherwise be charged
    to whichever model happened to run first.
    """
    start = time.perf_counter()
    try:
        await provider.complete("Reply with {}", "ping", json_mode=True)
    except Exception as exc:  # noqa: BLE001
        print(f"    warm-up failed: {type(exc).__name__}: {str(exc)[:90]}")
    return time.perf_counter() - start


def citation_breadth(results) -> tuple[float, int, float]:
    """(mean citations per claim, most on one claim, share of broad claims)."""
    counts = [
        len(claim.evidence_ids)
        for result in results
        if result.status is AgentStatus.COMPLETED
        for claim in [*result.observations, *result.interpretations]
    ]
    if not counts:
        return 0.0, 0, 0.0
    broad = sum(1 for count in counts if count >= BROAD_CITATION) / len(counts)
    return statistics.mean(counts), max(counts), broad


async def benchmark(symbol: str, interval: str, specs: list[str]) -> None:
    settings = get_settings()
    market = get_market_service()

    print(f"Collecting evidence for {symbol} ({interval})...")
    bundle = await collect_asset_evidence(
        symbol, market=market, candles=get_candle_provider(), interval=interval
    )
    candles = await get_candle_provider().get_candles(symbol, interval, 300)
    snapshot = build_snapshot(symbol, interval, candles) if candles else None
    print(f"  {len(bundle.items)} evidence records, {len(bundle.failures)} collector failures\n")

    rows = []
    for spec in specs:
        print(f"--- {spec} ---", flush=True)
        provider = build_provider(spec, settings)

        if not await provider.is_available():
            print("    provider not available (no key, or Ollama not running); skipping\n")
            continue

        if provider.mode == "local":
            print(f"    warm-up (model load, excluded): {await warm(provider):.1f}s")

        started = time.perf_counter()
        try:
            outcome = await run_analysis(bundle, provider, snapshot=snapshot)
        except Exception as exc:  # noqa: BLE001
            print(f"    FAILED after {time.perf_counter() - started:.1f}s: "
                  f"{type(exc).__name__}: {str(exc)[:110]}\n")
            rows.append({"model": spec, "error": str(exc)[:40]})
            continue

        # Printed first: a run can take many minutes, and an earlier version
        # of this script lost a completed run to a typo in the code below.
        elapsed = time.perf_counter() - started
        print(f"    duration        {elapsed:.1f}s", flush=True)

        completed = sum(1 for r in outcome.results if r.status is AgentStatus.COMPLETED)
        valid = sum(1 for v in outcome.validations.values() if v.valid)
        tokens = sum((r.input_tokens or 0) + (r.output_tokens or 0) for r in outcome.results)
        mean_cites, max_cites, broad = citation_breadth(outcome.results)
        reviewer = outcome.reviewer

        print(f"    agents          {completed}/{len(outcome.results)} completed")
        print(f"    validation      {valid}/{len(outcome.validations)} passed")
        print(f"    coverage        {reviewer.evidence_coverage:.1%}")
        print(f"    reviewer score  {reviewer.score:.1f} ({reviewer.verdict.value})")
        print(f"    citations/claim {mean_cites:.1f} mean, {max_cites} max, "
              f"{broad:.0%} cite {BROAD_CITATION}+ items")
        print(f"    tokens          {tokens:,}", flush=True)
        for result in outcome.results:
            if result.status is not AgentStatus.COMPLETED:
                print(f"    ! {result.agent} {result.status.value}: {'; '.join(result.errors)[:200]}")
        print()

        rows.append({
            "model": spec, "seconds": elapsed, "agents": f"{completed}/{len(outcome.results)}",
            "coverage": reviewer.evidence_coverage, "score": reviewer.score,
            "cites": mean_cites, "broad": broad, "tokens": tokens,
        })

    print("=" * 100)
    print(f"{'model':<34} {'seconds':>8} {'agents':>7} {'coverage':>9} {'score':>6} "
          f"{'cites/claim':>12} {'broad':>6} {'tokens':>8}")
    print("-" * 100)
    for row in rows:
        if "error" in row:
            print(f"{row['model']:<34} {'FAILED':>8}   {row['error']}")
            continue
        print(f"{row['model']:<34} {row['seconds']:>8.1f} {row['agents']:>7} "
              f"{row['coverage']:>8.1%} {row['score']:>6.1f} {row['cites']:>12.1f} "
              f"{row['broad']:>6.0%} {row['tokens']:>8,}")
    print("=" * 100)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", default="ETH")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    args = parser.parse_args()
    asyncio.run(benchmark(args.symbol, args.interval, args.models))


if __name__ == "__main__":
    main()
