# 🔥 Fire DEX

**Agentic AI-Powered Multi-Chain Smart Wallet & Decentralized Asset Intelligence Platform**

A multi-chain crypto wallet with an **auditable multi-agent intelligence layer**. It combines market, technical, portfolio and on-chain evidence into explainable decision support — where every result is recorded, hashed, and independently verifiable.

> 7th-semester Non-Syllabus Project · B.Tech CSE (Cyber Security) · Poornima College of Engineering
> Continues the 6th-semester *Multi-Chain Supported Wallet*. Extends into *Fire Trade* (paper trading) in the 8th semester.

---

## What makes this different

It is not "a wallet with a chatbot", and it is not a price predictor. The core idea is one architectural rule:

> **Agents never fetch data, and agents never produce numbers.**
>
> Deterministic collectors gather facts into a typed, timestamped, source-attributed **Evidence Bundle**. Agents receive that bundle and may only emit `observations` and `interpretations` that cite `evidence_id`s. A validator rejects any agent output containing a number that cannot be traced back to an evidence record.

Every indicator (RSI, MACD, Bollinger…) is calculated in tested Python. The language model *interprets* those values — it never invents them. That is what makes the results auditable rather than merely plausible.

**Read mainnet · write testnet.** All chains are read for balances, prices and transfers. The only chain where this app constructs and submits transactions is Sepolia.

---

## Status

| | |
|---|---|
| **Current milestone** | ✅ M2 — MetaMask + live Ethereum/Sepolia balances |
| **Next milestone** | M3 — Token registry + live prices |
| **Prototype target** | 10-day vertical slice: Ethereum + Sepolia, 3 agents, full audit spine |
| **Full project** | November |

---

## Quick start

**Prerequisites:** Python 3.11+ · Node.js 20+

### The easy way

Double-click **`START.bat`**.

It checks Python and Node, sets everything up the first time (virtual environment, packages, `.env` files), starts both servers in their own windows, and opens the app in your browser. No commands to type.

To stop everything, double-click **`STOP.bat`**.

While editing backend code, use **`DEV_BACKEND.bat`** instead of the backend window — it enables auto-reload.

### Documentation

| File | What it's for |
|---|---|
| [docs/PHASES.md](docs/PHASES.md) | **Start here.** The project explained in plain language, phase by phase, with what to say to professors |
| [docs/VIVA.md](docs/VIVA.md) | Technical question bank for the viva — Python, agents, blockchain, security |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Why the system is shaped the way it is |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Milestone plan and scope decisions |

### The manual way

<details>
<summary>If you prefer running the servers yourself</summary>

#### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env
uvicorn app.main:app --reload
```

→ API on <http://127.0.0.1:8000> · interactive docs on <http://127.0.0.1:8000/docs>

#### Frontend

```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

→ UI on <http://localhost:5173>

</details>

### Tests

```bash
cd backend
.venv\Scripts\python -m pytest
```

### Developing without MetaMask

If you do not have MetaMask installed, add `?mockWallet=1` to the URL:

<http://localhost:5173/?mockWallet=1>

This installs a **development-only fake wallet** so wallet UI can be built and tested. It fakes only the *wallet* — addresses, approval, network switching. Balances still come from the real backend reading a real node, so a mocked address shows its genuine on-chain balance. A permanent orange banner appears while it is active, and the whole module is stripped from production builds.

Console helpers while it is active:

```js
__mockWallet.switchAccount()            // fires accountsChanged
__mockWallet.switchToUnsupportedChain() // fires chainChanged to Polygon (137)
__mockWallet.revokeAccess()             // simulates the user disconnecting
```

Add `&mockReject=1` to test the user-rejection path.

### API keys

**None are required.** RPC access defaults to verified public keyless endpoints. To use your own (recommended for heavier use), set `ETHEREUM_RPC_URL` and `SEPOLIA_RPC_URL` in `backend/.env`.

---

## Architecture

```
FRONTEND  React + TypeScript + Vite + Tailwind
   Dashboard │ Fire AI │ History │ Audit
          │ typed REST + SSE
BACKEND   FastAPI
   api/         routers and schemas
   agents/      market · technical · whale · onchain · portfolio · risk
                orchestrator (LangGraph) · reviewer
   evidence/    bundle builder · evidence types · output validator
   audit/       Fire Auditor · canonicaliser · SHA-256 · verifier
   services/    indicators · portfolio · tokens
   providers/   market/ chain/ llm/     ← only layer touching the outside
   database/    SQLAlchemy + Alembic
```

Two rules hold it together:

1. **Only `providers/` performs external I/O.** Swapping a market data provider touches one file.
2. **Agents sit above `evidence/`, never above `providers/`.** They physically cannot fetch, so they cannot smuggle in unsourced data.

Full detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Milestone plan in [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Supported networks

| Network | Family | Chain ID | Wallet | Status |
|---|---|---|---|---|
| Ethereum | EVM | 1 | MetaMask | ✅ Live |
| Sepolia Testnet | EVM | 11155111 | MetaMask | ✅ Live |
| BNB Smart Chain | EVM | 56 | MetaMask | November |
| Solana | Solana | — | Phantom | November |
| Bitcoin | UTXO | — | read-only | November |

---

## Security model

This is a wallet application, so the security posture is an architectural invariant, not a feature:

- **The app has no code path that accepts a private key or seed phrase.** There is no input field, no parameter, no storage column. All signing happens inside the user's wallet extension.
- **No secrets in the frontend.** Every keyed third-party API is proxied through the backend. `VITE_*` variables are compiled into the public bundle and are treated as public.
- **AI-influenced transaction parameters are untrusted input** and are validated against an allow-list (known contract, value bounds, chain match) before the wallet ever sees them.
- **`.env` is gitignored from the first commit.** `.env.example` documents every required variable.

See [docs/SECURITY.md](docs/SECURITY.md) *(added in the security milestone)*.

---

## On result hashing — an honest note

Every completed analysis gets a result ID (`FIRE-2026-000042`), a canonical serialisation, and a SHA-256 hash, chained to the previous record's hash.

This proves a record **has not been altered since it was written**. It is *tamper-evidence*, not immutability — anyone with database write access could rewrite a record and its hash, though the hash chain makes a silent single-record edit detectable. The word "immutable" is only earned if we later anchor a chain root on-chain, which is a documented future option and not a current claim.

---

## Disclaimer

Fire DEX provides AI-assisted analytical information for **educational and research purposes**. It does not provide guaranteed financial returns or personalized financial advice. No component performs autonomous trading with real funds.

---

## Team

| | Registration ID | Role |
|---|---|---|
| Aditya Sharma | PCE23CY001 | Scrum Master / Team Leader |
| Akshat Sharma | PCE23CY002 | — |
| Divyansh Kumar | PCE23CY020 | — |
