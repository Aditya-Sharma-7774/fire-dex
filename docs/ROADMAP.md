# Fire DEX — Roadmap

Two horizons: a **10-day prototype** for the interim presentation, and the **full project** by November.

---

## Horizon 1 — 10-day prototype

**Goal:** one narrow slice, complete end to end. Ethereum + Sepolia only, three agents, full audit spine.

This proves the actual thesis — auditable multi-agent intelligence — rather than showing a half-finished wallet. A wallet that connects but explains nothing is a weaker demo than a single asset analysed with full traceability.

| Day | Milestone | Deliverable |
|---|---|---|
| 1 | **M1 Foundation** ✅ DONE | Repo, FastAPI `/health`, React fire-theme shell, live backend status |
| 2 | M2 Wallet ✅ DONE | MetaMask connect, account/chain detection, ETH + Sepolia native balances |
| 3 | M3 Tokens & prices ✅ DONE | Token registry (~10 ETH assets), market data provider, live prices |
| 4 | M4 Charts & indicators ✅ DONE | Candlestick chart, timeframes, **tested indicator engine** |
| 5 | M5 Audit spine ✅ DONE | Evidence bundle, validator, canonicaliser, SHA-256, hash chain |
| 6 | M6 First agent ✅ DONE | LLM provider abstraction, Market Agent, end-to-end through audit |
| 7 | M7 More agents ✅ DONE | Technical Agent, Risk Agent, Orchestrator |
| 8 | M8 Review & history ✅ DONE | Reviewer Agent, Fire Auditor metrics, history + drill-down |
| 9 | M9 Fire AI page ✅ DONE | Live agent visualisation over SSE, verification UI |
| 10 | M10 Demo | Buffer, demo script, README screenshots |

### Why the audit spine lands on day 5, not at the end

The original specification placed hashing and auditing at milestones 20–21. Auditing cannot be retrofitted: if agents ship before the evidence contract exists, every agent gets rewritten to conform to it. Building the spine before the first agent means every later agent is a copy-and-adapt.

### Prototype scope boundary

**In:** Ethereum + Sepolia · MetaMask · ~10 tokens · live prices · candlestick chart · indicator engine · evidence bundle · Market/Technical/Risk agents · orchestrator · reviewer · Fire Auditor · hashing · history · agent visualisation

**Out (November):** Solana · Bitcoin · BNB · swap · Whale agent · On-Chain agent · Portfolio agent · Sentiment agent · model comparison · Postgres

---

## Horizon 2 — full project (November)

| Phase | Content |
|---|---|
| **P2** Chains | BNB Smart Chain · Solana + Phantom · Bitcoin read-only adapter · full token registry |
| **P3** Data | Provider fallbacks · caching · portfolio aggregation across chains |
| **P5** Intelligence | On-Chain Agent · Whale Agent · Portfolio Agent · Ollama local mode · model comparison |
| **P6** Surface | Swap quote + route UI · Sepolia transaction execution · audit viewer |
| **P7** Harden | Security pass · rate limiting · observability · test suite · full docs · Postgres migration |

---

## If time gets short

Cut in this order. Decided in advance so it is a plan, not a panic:

1. Sentiment / research agent
2. Bitcoin adapter
3. Whale agent
4. BNB Smart Chain *(Ethereum + Sepolia + Solana already demonstrate multi-chain)*
5. Swap interface

**Never cut:** the evidence contract, the validator, the hash chain, or the history drill-down. Those are the project.

---

## 8th semester — Fire Trade

Not built now. The architecture leaves the seams in place:

- Paper wallet with virtual capital
- Simulated orders against recorded market snapshots
- Historical backtesting
- Agent-generated signals
- Performance evaluation: drawdown, Sharpe ratio, win rate, directional accuracy
- Model and agent comparison

Every analysis stored by Fire Auditor is timestamped and hashed, so 8th semester can score past predictions against what actually happened — using an archive that already exists rather than one that has to be manufactured. This is the reason accuracy is **not** claimed in the 7th semester: there is no ground truth yet, and the specification is explicit that unmeasured accuracy must never be asserted.

### Measured in the 7th semester

Execution time · token usage · evidence coverage · reviewer score · citation validity · consistency · confidence calibration · data freshness · agent agreement

### Not claimed in the 7th semester

Prediction accuracy · profitability · market direction · "95% accurate"
