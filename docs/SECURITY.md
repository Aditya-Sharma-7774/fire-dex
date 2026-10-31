# Fire DEX — Security Model

How Fire DEX defends against each class of attack that applies to it, what
a security review found and fixed, and what remains a known limit.

Every defence listed under "Implemented" has an automated test that performs
the attack and asserts it fails — mostly in `backend/tests/test_security.py`.

---

## 1. What is being protected

| Asset | Why it matters | Where it lives |
|---|---|---|
| **The user's private keys** | Loss means loss of funds | **Never in Fire DEX.** They stay inside MetaMask |
| Integrity of recorded analyses | The project's claims rest on the record being trustworthy | SQLite, SHA-256 hash-chained |
| The Groq API key | Billing and quota | `backend/.env`, never committed |
| Correctness of displayed figures | A wrong balance or price is a financial error | Computed by tested code, validated before display |
| Availability | A stalled server makes the wallet unusable | The backend process |

The strongest control is the first row. **Fire DEX has no code path that
accepts, stores or transmits a private key or seed phrase** — no input field,
no API parameter, no database column. Signing happens inside the wallet
extension; the application only ever receives a public address. An attack
that steals keys from Fire DEX has nothing to steal.

## 2. Trust boundaries

```
  Browser (untrusted input)          External data (untrusted content)
         │                                   │
         ▼                                   ▼
  ┌─────────────────────┐          ┌──────────────────────┐
  │ API boundary        │          │ Provider boundary    │
  │ params.py           │          │ jsonrpc.py, market/  │
  │ host + CORS checks  │          │ timeouts, size caps  │
  └──────────┬──────────┘          └──────────┬───────────┘
             ▼                                ▼
        Deterministic code: indicators, risk, signal, audit
                             │
                             ▼
              Language model (untrusted OUTPUT)
                             │
                             ▼
              Output validator — rejects untraceable claims
```

Three things are treated as untrusted: what the browser sends, what
external providers return, and what the language model writes. Each has its
own boundary.

---

## 3. Threats and defences

### 3.1 Secret exposure

**Attack.** A user pastes a private key into the wrong field. The input is
correctly rejected — and then quoted back in the error message, shown on
screen and written to the log.

**Defence.**
- **The Solana and Bitcoin address field checks in the browser first.** It is
  exactly where people paste secrets by mistake, so every input is tested the
  moment it arrives. A private key, keypair file, extended private key or
  12-to-24-word recovery phrase is wiped from the field at once and never
  sent, stored or shown. Verified in a real browser: the field emptied, and
  the network log showed no request containing the key.
- The server repeats every check, because a request need not come from the
  page. Address validators reject the *shapes* of secrets loudly: a
  64-character hex string (an EVM private key), a 64-byte base58 value (a
  Solana keypair), a JSON array of numbers (a `solana-keygen` keypair file),
  an extended private key (`xprv`…), and a Bitcoin **WIF private key**.
- WIF needs special care. It is valid base58check with its own correct
  checksum, so a validator that only checked the checksum would accept a
  private key as an address. It is refused by its version byte, `0x80`.
- Secret shapes are checked before any length limit. An extended private key
  is 111 characters, and a length check that ran first answered it with a
  bland "not an address" instead of the warning it needs — found by a test
  and fixed.
- Rejection messages quote only a preview of the input (`0xd8dA...6045`).
- **Every error response and every log line** passes through one redaction
  step that removes secret-shaped strings: EVM keys, Solana secret keys,
  Groq keys, bearer tokens, and the path of any URL (where providers such as
  Alchemy embed API keys). It sits in the one handler all errors pass
  through and in the shared logging pipeline, so no call site can forget it.
- The server's own access log is filtered the same way, because it records
  request paths before any project code runs.

**Residual.** A raw 32-byte ed25519 seed has exactly the shape of a Solana
public key and cannot be distinguished by any format check. Wallets export
the 64-byte form, which is caught.

### 3.2 Prompt injection

**Direct injection.** The asset symbol is placed into every agent's prompt
as the analysis subject. A symbol of `ETH` followed by a newline and
instructions would have been read by all five agents.

**Defence.** The symbol is restricted to 1–12 letters and digits at the API
boundary. Injection is not detected after the fact; the input that would
carry it cannot be expressed. The user's free-text question is never sent to
any model at all.

**Indirect injection** — hostile text arriving through provider data.
Evidence labels are generated by code, and provider data enters as numbers,
so there is no free-text channel from providers into prompts today.

**Containment if injection succeeded anyway.** The architecture limits what
an injected instruction could achieve:

| An injected instruction tries to… | Outcome |
|---|---|
| State a false price or balance | **Rejected** — the validator finds no cited evidence with that value |
| Fetch data or call a URL | **Impossible** — agents have no network access by construction |
| Change the buy/sell signal | **Impossible** — the signal is computed by code, not the model |
| Inflate the review score | **Bounded** — the base score is computed; the model can only subtract |
| Write misleading wording with a valid citation | **Not prevented** — see residual risks |

### 3.3 Fabricated figures (model hallucination)

Treated as an attack on integrity because the effect is identical. Agents
must cite an evidence id for every claim, and the validator rejects any
number not traceable to a cited value, label or unit within 2%. Rejected
output gets one repair attempt, then the agent is marked failed. Citation
validity has been 100% across every recorded analysis.

### 3.4 DNS rebinding

**Attack.** A hostile web page makes its own domain resolve to `127.0.0.1`.
The browser then treats requests to the local API as same-origin, so CORS
never applies.

**Defence.** The server only answers requests whose `Host` header is
`127.0.0.1` or `localhost`. The browser still sends the attacker's domain in
that header, so rebound requests are refused before reaching any route.

### 3.5 Cross-site request forgery

JSON endpoints require `Content-Type: application/json`, which forces a CORS
preflight that hostile origins fail. CORS allows only the frontend's own
origins, and only `GET` and `POST`. Every `GET` is read-only.

### 3.6 Denial of service

| Vector | Defence |
|---|---|
| Huge request fields | Length limits at the boundary on every field |
| Base58 decoding cost | Solana input is length-checked before decoding, which is quadratic |
| Backtest replay is CPU-bound | Runs on a worker thread, one at a time, so it cannot stall the server |
| Burning the Groq quota | Bounded agent count and retries; local-only binding |
| A slow or dead provider | 12-second timeouts; cached and stale-flagged values |

The backtest was the real finding: a `GET`, so any web page could trigger it
with an `<img>` tag, running on the event loop where it blocked every other
request.

A second, quieter one: every chain request built a new HTTP client, and
creating one takes 0.23 seconds of blocking work to load the certificate
bundle. Requests meant to run concurrently were therefore serialised, and the
event loop stalled on each. One client is now reused per event loop, with the
certificate bundle loaded once. A request costs 0.0002 seconds instead, and
certificate verification is unchanged — a self-signed certificate is still
rejected.

### 3.7 Malicious or faulty data provider

A provider can lie, and some do by accident.

- **Wrong network.** EVM nodes — Ethereum, Sepolia and BNB Smart Chain —
  must report the expected chain ID. Solana nodes must report mainnet's
  genesis hash, and Bitcoin services must report Bitcoin's genesis block. A
  devnet or testnet endpoint is refused and named, so test tokens are never
  shown as real holdings.
- **A provider that goes down.** Bitcoin is read from two independent
  services running the same API, tried in order, so either can fail.
- **Impossible data.** A real public Solana provider reported a block height
  above its own slot on every request we made. Impossible values are withheld
  rather than displayed.
- **Someone else's data.** Token accounts are checked to belong to the
  requested owner, so a dishonest node cannot add another wallet's holdings.
- **Unknown versus zero.** A failed read is reported as unknown, never as a
  zero balance.

### 3.8 Tampering with stored records

Each analysis is canonicalised and chained to its predecessor by SHA-256.
Editing any stored record is detected by the integrity check.

This is **tamper-evidence, not immutability**. Someone with write access to
the database could alter a record and recompute every later hash. A test
asserts this limit. Anchoring the chain root on a public blockchain would
close it, and is documented as future work.

### 3.9 Injection into the database, page or server

| Attack | Status |
|---|---|
| SQL injection | Not possible — every query goes through the SQLAlchemy ORM; there is no raw SQL |
| Cross-site scripting | Model output is rendered as React text, which escapes it. No raw HTML, no markdown renderer |
| Server-side request forgery | No user input ever becomes a URL; every endpoint comes from configuration |
| Reverse tabnabbing | Every external link carries `rel="noreferrer noopener"` |
| Clickjacking | `X-Frame-Options: DENY` |
| MIME sniffing | `X-Content-Type-Options: nosniff` |

### 3.10 Transaction risk

Fire DEX reads mainnet and would construct a transaction only on the Sepolia
testnet. It never signs anything itself. This removes front-running,
sandwich attacks and loss of funds from scope entirely.

### 3.11 Information disclosure

- Error responses carry a message and a redacted detail, never a stack trace.
- The interactive API documentation is disabled when `APP_MODE=production`.
- Responses carry `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.

### 3.12 Supply chain

`requirements.txt` sets minimum versions; `requirements.lock.txt` records the
exact versions that were tested. The frontend is pinned by `package-lock.json`.
Both are scanned for known vulnerabilities — see section 4.

---

### 3.13 Adding a network to the user's wallet

When MetaMask does not know BNB Smart Chain, Fire DEX asks it to add the
network (EIP-3085). That request hands MetaMask an RPC endpoint, and the
user's **own transactions** will travel through it from then on — a dishonest
RPC can misreport what a transaction does or front-run it. So the endpoint
given is BNB Chain's official one, never a third party's, and a test fails if
anything else is supplied. MetaMask shows the user the network details and
asks them to approve before anything changes.

### 3.14 Watch-only chains

Solana and Bitcoin are read from a pasted public address. Fire DEX holds no
key for them and has no code path that could move funds, so the worst outcome
of a wrong address is a wrong *display*, never a loss. Bitcoin addresses carry
a checksum, so a typo is caught. Solana addresses have none — a property of
Solana itself — so a mistyped one that still decodes is read as written.

## 4. Findings from this review

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Medium | A rejected private key was echoed in the error message and the log | Preview-only messages; central redaction of responses and logs |
| 2 | Medium | Free-text symbol placed into every agent prompt — prompt injection | Symbol restricted to `[A-Za-z0-9]{1,12}` at the boundary |
| 3 | Medium | No length limits on request fields | Limits on every field; strict types for `interval` and `prefer` |
| 4 | Medium | Backtest blocked the event loop, and could be triggered cross-site | Worker thread, one-at-a-time gate |
| 5 | Medium | Localhost API exposed to DNS rebinding | Host-header allow-list |
| 6 | Low | Upstream error bodies relayed verbatim, could carry a key-bearing URL | Central redaction |
| 7 | Low | Server access log recorded full request paths | Redacting log filter |
| 8 | Low | No hardening headers | `nosniff`, `DENY`, `no-referrer`, `no-store` |
| 9 | Low | API docs exposed regardless of mode | Disabled in production |
| 10 | Low | CORS allowed every method and header | Restricted to what the frontend uses |
| 11 | Info | The Groq and Gemini keys were shared in a chat session during development | **Rotate both** — see section 6 |
| 12 | Medium | A pasted extended private key got a generic message, because the length check ran first | Secret shapes checked before any length limit |
| 13 | Low | Every chain request built a new HTTP client, blocking the event loop for 0.23 s | One client per event loop, certificate bundle loaded once |

Severities assume the documented deployment: one user, bound to `127.0.0.1`.
Several would be High on a server reachable from the internet.

### 4.1 Dependency vulnerability scan

| Scope | Tool | Result |
|---|---|---|
| Backend, every installed package | `pip-audit` | **No known vulnerabilities** |
| Frontend, shipped code | `npm audit --omit=dev` | **0 vulnerabilities** |
| Frontend, development tooling | `npm audit` | 13 findings, all in tools that never ship |

The code users run is clean. The 13 findings are in the build and test
toolchain on the developer's own machine. One non-breaking fix was applied;
every remaining fix needs a major-version upgrade, so each was assessed for
whether it is actually exploitable here.

| Advisory | Exploitable in this setup? |
|---|---|
| Vite `server.fs.deny` bypass on Windows paths (high) | **Only by something that can reach the dev server over the network.** It is the one that matters: on Windows it could read files the server should refuse, including `backend/.env`. The dev server binds to localhost by default, and Vite 5.4.21 already blocks DNS rebinding and cross-origin reads |
| Vite NTLM hash disclosure via UNC paths (moderate) | Same condition as above |
| Tinypool prototype pollution to RCE (critical) | No — requires attacker-controlled options passed to the test runner, meaning the attacker already controls the test code |
| esbuild development-server CORS (moderate) | No — affects esbuild's own `--serve` mode, which Vite does not use |
| Tailwind's file-matching libraries (high, ReDoS) | No — they match the project's own source globs, never untrusted input |

**Never start the frontend dev server with `--host`.** That is the condition
that would make the Vite advisories exploitable. The complete fix is Vite
6.4.3 or later, which also requires upgrading the test runner. Because that
upgrade changes the build toolchain, it is recommended after the submission
rather than days before a demonstration.

---

## 5. Known residual risks

Stated deliberately. Each is a decision or a limit, not an oversight.

1. **No authentication.** Fire DEX is a single-user application bound to
   `127.0.0.1`. Exposing it on a network would require authentication first.
2. **Misleading wording with a valid citation** would pass the validator,
   which checks that claims are traceable, not that their phrasing is fair.
   The deterministic signal and the computed review score are the defence
   against being misled by it.
3. **Public RPC trust.** Data from a public node is trusted once it passes the
   network-identity and sanity checks. A single malicious node that reported
   self-consistent false balances would not be detected.
4. **The Groq key is stored in plain text** in `backend/.env`, protected only
   by file permissions. An operating-system credential store would be stronger.
5. **Console logs are visible on screen.** Redaction protects them, but avoid
   projecting the backend console during a demonstration.
6. **No content security policy** is set on the frontend, because Vite's
   development server relies on inline scripts. A production build should
   add one.

## 6. Operating it safely

- **Rotate the Groq and Gemini API keys now.** Both were pasted into a chat
  session during development. Generate new ones at console.groq.com and
  aistudio.google.com, and replace the old values in `backend/.env`.
- Never start the backend with `--host 0.0.0.0`. The launchers bind to
  `127.0.0.1` deliberately.
- Never paste a private key, seed phrase or keypair file anywhere in Fire DEX.
  Nothing in it needs one.
- Use the Sepolia testnet for anything that involves a transaction.
