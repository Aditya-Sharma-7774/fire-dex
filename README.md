# Fire DEX

A multi-chain crypto wallet with an analysis layer that shows its working. It reads balances and prices across several blockchains, calculates technical indicators in code, and asks a language model to explain the result. The model is only allowed to talk about numbers it was given, and every claim has to point at the evidence behind it.

7th semester Non-Syllabus Project, B.Tech CSE (Cyber Security), Poornima College of Engineering, Jaipur. It builds on our 6th semester multi-chain wallet.

## What it does

- Shows native balances and token holdings on Ethereum, Sepolia, BNB Smart Chain, Solana and Bitcoin. Ethereum, Sepolia and BNB connect through MetaMask. Solana and Bitcoin are watch-only: you paste an address.
- Pulls prices and candles, then calculates SMA, EMA, RSI, MACD, Bollinger Bands, ATR and divergence in plain Python.
- Turns the indicators into a buy/sell signal and a weighted risk score, both deterministic.
- Runs five agents (market, technical, risk, portfolio, on-chain) plus a reviewer that scores the others' output.
- Stores every analysis with a SHA-256 hash that is chained to the previous record, so an edited record can be detected.
- Backtests the signal against a simple baseline over past prices.

## The one rule

Agents never fetch data and never produce numbers.

Collectors gather facts into an evidence bundle, where every item has an id, a source and a timestamp. An agent gets that bundle and can only return observations and interpretations that cite evidence ids. A validator rejects any output containing a number it cannot trace back to a cited item.

## Stack

- Backend: Python 3.11, FastAPI, SQLAlchemy, Alembic, SQLite
- Frontend: React, TypeScript, Vite, Tailwind
- Language models: Groq, Gemini or Ollama, with automatic failover between whichever are configured

## Running it

You need Python 3.11+ and Node.js 20+.

On Windows, double-click `START.bat`. It sets up the virtual environment and packages the first time, starts both servers and opens the app. `STOP.bat` stops them. `DEV_BACKEND.bat` runs the backend with auto-reload.

To do it by hand:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env
uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

The API runs on http://127.0.0.1:8000 (docs at `/docs`) and the app on http://localhost:5173.

## API keys

Nothing needs a key to see balances, prices, charts or indicators. Analyses need at least one language model provider. Put the key in `backend/.env`:

- `GROQ_API_KEY` from console.groq.com
- `GEMINI_API_KEY` from aistudio.google.com
- or run Ollama locally (`ollama pull llama3.1:8b`), which needs no key but is slow on a laptop

`http://127.0.0.1:8000/api/v1/ai/status` shows which providers are available. Provider model names change often, so `backend/scripts/benchmark_models.py` runs a real analysis against a model to check that it works.

No MetaMask? Open `http://localhost:5173/?mockWallet=1` for a development-only fake wallet. It only fakes the wallet, and balances still come from the real backend.

## Tests

```bash
cd backend
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check app tests scripts

cd ..\frontend
npm test
npm run typecheck
```

The backend tests do not touch the network. Set `FIREDEX_LIVE_TESTS=1` to run the few that check token contracts against the real chains.

## Layout

```
backend/app/
  api/          routes and request validation
  agents/       the five agents, orchestrator, reviewer, suggestion
  evidence/     collectors, evidence types, output validator
  audit/        hashing, canonical form, verification
  indicators/   SMA, EMA, RSI, MACD, Bollinger, ATR, divergence
  signals/      buy/sell vote
  backtest/     signal replay against a baseline
  risk/         risk model
  blockchain/   EVM, Solana and Bitcoin adapters
  market/       prices and candles
  tokens/       verified token registry
  llm/          Groq, Gemini, Ollama and failover
  database/     models and migrations
frontend/src/   dashboard, Fire AI page, history
docs/           architecture, evaluation, security, roadmap
```

Only `blockchain/`, `market/` and `llm/` talk to the outside world, and the agents sit above `evidence/`, so they have no way to fetch anything themselves.

## Things worth knowing

- The app has no code path that accepts a private key or seed phrase, and the address field rejects anything shaped like one. Signing is left to the user's own wallet.
- Fire DEX reads mainnet and does not send transactions. Anything that writes is meant for Sepolia only.
- The same token can have different decimals on different chains (USDT is 6 on Ethereum and 18 on BNB Smart Chain), so every token address in the registry was checked against the chain itself and CoinGecko.
- The hash chain shows that a record has not been changed since it was written. It is tamper evidence, not immutability, because someone with write access to the database could rewrite a record and its hash.
- This is for study and research. It is not financial advice and it does not trade.

More detail in `docs/ARCHITECTURE.md`, `docs/EVALUATION.md` (how each score is worked out), `docs/SECURITY.md` and `docs/ROADMAP.md`.

## Team

Aditya Sharma, Akshat Sharma, Divyansh Kumar
