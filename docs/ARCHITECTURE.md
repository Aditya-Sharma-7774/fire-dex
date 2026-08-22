# Fire DEX — Architecture

This document records *why* the system is shaped the way it is. Read it before adding a feature.

---

## 1. The central rule

> **Agents never fetch data, and agents never produce numbers.**

Everything else follows from this.

A naive "AI crypto analyst" hands a language model a question and prints whatever comes back. The output sounds authoritative and is unverifiable — the model can state a price that was never observed, cite a whale transfer that never happened, and nothing in the system notices.

Fire DEX splits the job in two:

| Deterministic code does | The language model does |
|---|---|
| Fetch prices, balances, transfers | Interpret what they mean |
| Calculate RSI, MACD, SMA, EMA, Bollinger | Explain whether momentum looks elevated |
| Compute portfolio weights and concentration | Describe the concentration risk |
| Compute the risk score from a published formula | Explain which factors drove it |
| Record timestamps, hashes, token counts | Nothing — never touches these |

The model's output is then **validated**: every interpretation must cite at least one `evidence_id`, and every number appearing in an observation must match a value in the evidence bundle. Output that fails validation is retried once with the violation fed back, then marked `failed`.

**A failed agent is reported as failed.** The orchestrator never fabricates a missing result.

---

## 2. Layers

```
┌────────────────────────────────────────────────────────┐
│  FRONTEND   React · TypeScript · Vite · Tailwind       │
│  Dashboard │ Fire AI │ History │ Audit                 │
└───────────────────────┬────────────────────────────────┘
                        │  typed REST  +  SSE (agent stream)
┌───────────────────────┴────────────────────────────────┐
│  api/         routers · request/response schemas       │
│───────────────────────────────────────────────────────-│
│  agents/      six specialists · orchestrator · reviewer│
│───────────────────────────────────────────────────────-│
│  evidence/    bundle builder · types · validator       │
│───────────────────────────────────────────────────────-│
│  audit/       auditor · canonicaliser · hasher         │
│───────────────────────────────────────────────────────-│
│  services/    indicators · portfolio · tokens          │
│───────────────────────────────────────────────────────-│
│  providers/   market/ · chain/ · llm/                  │
│               cache · rate limit · retry · error map   │
│───────────────────────────────────────────────────────-│
│  database/    SQLAlchemy 2.0 · Alembic                 │
└────────────────────────────────────────────────────────┘
```

**Dependencies point strictly downward.** No layer imports from a layer above it.

Two invariants:

1. **Only `providers/` performs external I/O.** Everything above consumes typed domain models. Replacing CoinGecko with Coinbase touches one file.
2. **Agents sit above `evidence/`, never above `providers/`.** They have no network access by construction — which is how rule §1 is enforced by the code rather than by a prompt.

---

## 3. The analysis pipeline

```
User query
    │
    ▼
Intent parser  ──────────────► Execution plan (which agents, which asset)
    │
    ▼
Evidence collectors (deterministic, parallel)
    │   → EvidenceBundle: typed, timestamped, source-attributed facts
    ▼
┌────────┬───────────┬────────┬─────────┬───────────┬──────┐
│ Market │ Technical │ Whale  │ OnChain │ Portfolio │ Risk │  (parallel, LLM)
└────────┴───────────┴────────┴─────────┴───────────┴──────┘
    │   → AgentResult[]  →  Output validator
    ▼
Orchestrator  — synthesise, detect conflicts, flag missing coverage
    ▼
Reviewer  ── REANALYZE (max 1 retry) ──┐
    │ APPROVED / REJECTED              │
    ▼                                  └──► back to planner
Fire Auditor  — metrics, canonicalise, SHA-256, chain to previous hash
    ▼
Stored result  →  history  →  verification
```

---

## 4. Core data contracts

Everything in the project is a Pydantic model. These two are the backbone.

### Evidence

```
Evidence
  evidence_id      "ev_001"
  kind             price | ohlcv | indicator | balance | transfer | ...
  source           provider · endpoint · fetched_at
  data_timestamp   when the fact was true (≠ when we fetched it)
  value            typed payload
```

`fetched_at` and `data_timestamp` are separate on purpose. A price fetched now may describe a candle that closed an hour ago; the freshness check needs both.

### Agent result

```
AgentResult
  agent · status · started_at · ended_at · duration_ms
  model · provider · mode (local|online)
  input_tokens · output_tokens
  observations     [{ text, evidence_ids[] }]
  interpretations  [{ text, evidence_ids[], confidence, alternatives[] }]
  warnings[] · errors[]
```

The observation/interpretation split is deliberate and is enforced in the prompt *and* checked by the validator:

> **Observation:** "RSI = 68."
> **Interpretation:** "Momentum is elevated relative to the 30-day mean."
>
> Never: "RSI is 68, so BUY."

---

## 5. Scoring — what is computed vs. what is judged

Neither the risk score nor the reviewer score is an LLM's opinion.

**Reviewer score** = weighted deterministic components, with a bounded LLM penalty:

| Computed by code | Judged by the model |
|---|---|
| Evidence coverage % | Unsupported claims |
| Citation validity % | Reasoning gaps |
| Data freshness | Overconfidence |
| Numeric consistency | Contradictions between agents |
| Agent agreement / conflict count | |

**Risk score** = a documented weighted formula over realised volatility, a liquidity proxy, concentration (HHI), stablecoin ratio and anomaly count. The model *explains* the number; it never *produces* it.

Both methodologies are written down in `docs/EVALUATION.md` so the numbers mean something under questioning.

---

## 6. Chain abstraction

A chain is a **config entry**, not a code path.

```
ChainAdapter (protocol)
    get_native_balance(address)      -> Balance
    get_token_balances(address)      -> list[TokenBalance]
    get_transactions(address, limit) -> list[Transaction]
    get_token_transfers(...)         -> list[TokenTransfer]
    validate_address(address)        -> bool

  EvmAdapter      parameterised by chain_id (1 / 56 / 11155111)
  SolanaAdapter   mints, lamports, SPL token accounts
  BitcoinAdapter  UTXO model, satoshis, read-only
```

Guards that are never optional:

- Addresses validated against **that chain's** format before any call — EIP-55 checksum for EVM, base58 + curve check for Solana, bech32/base58 for Bitcoin.
- Every request carries an explicit chain identifier. There is no ambient "current chain" global on the backend.
- The frontend refuses to build a transaction when `wallet.chainId !== selectedChain.chainId`.

Frontend mirror of this rule lives in `frontend/src/config/chains.ts`.

---

## 7. Why each significant dependency exists

| Choice | Reason it earns its place |
|---|---|
| **FastAPI** | Async, typed, generates the OpenAPI schema we turn into frontend types |
| **Pydantic v2** | The evidence and agent contracts *are* Pydantic models; validation is the feature |
| **LangGraph** | Specifically for the reviewer's `REANALYZE` loop — a conditional cycle. Plain function calls cannot express that cleanly |
| **structlog** | Fire Auditor consumes structured log records directly, no parsing |
| **Own indicator module** | No C toolchain on Windows, fully testable against known values, defensible in a viva — and the ideal first task for a beginner |
| **SQLite → PostgreSQL** | SQLite for the 10-day prototype (zero setup). SQLAlchemy makes the swap a one-line config change |
| **Vite** | Instant dev server; Next.js would add SSR we have no use for |
| **Tailwind v3** | v4 moved config into CSS; v3 has far more tutorial coverage, which matters while learning |
| **lightweight-charts** | Purpose-built candlestick rendering, far lighter than a general charting library |

---

## 8. Deliberately deferred

Recorded so these read as decisions, not oversights:

- **Mainnet swap execution** — quote and route display only. A student-built app routing real funds through a DEX has severe failure modes unrelated to the project's thesis. Execution is Sepolia-only.
- **Bitcoin transaction signing** — read-only for now. The UTXO signing path is isolated behind `BitcoinAdapter` so it can be added without touching anything else.
- **Sentiment / research agent** — highest hallucination and terms-of-service risk, lowest evidential value. Deferred until the spine is proven.
- **User authentication** — a wallet address is the identity. Adding auth later restructures nothing.
- **Fire Trade (paper trading, backtesting, Sharpe/drawdown)** — 8th semester. The audit archive built now becomes its training and evaluation set, which is exactly why the audit spine is built early rather than bolted on.
