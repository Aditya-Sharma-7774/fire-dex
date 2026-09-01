# Fire DEX — Evaluation Methodology

Every number this system reports about itself is defined here. If a figure appears on screen, its formula is in this document.

This exists because a score with no published methodology cannot be defended. "Risk: 68/100" is meaningless unless someone can ask *how* and get a real answer.

---

## What we measure — and what we deliberately do not

### Measured in the 7th semester

| Metric | Meaning |
|---|---|
| Execution time | Wall-clock duration of the full pipeline, and per agent |
| Token usage | Input and output tokens, per agent and per analysis |
| Evidence coverage | Fraction of collected evidence that agents actually cited |
| Citation validity | Fraction of agent claims whose citations all resolved |
| Reviewer score | Composite quality score, defined below |
| Agent agreement | Overlap between agents' cited evidence |
| Data freshness | Whether any evidence came from expired cache |
| Confidence | Model-stated confidence, calibrated against coverage |
| Completion rate | Agents that finished vs. agents attempted |

### NOT claimed in the 7th semester

**Prediction accuracy. Profitability. Market direction.**

Accuracy requires ground truth — comparing a prediction against what actually happened. We have no ground truth yet, so any accuracy figure would be invented. Establishing it properly is the 8th-semester *Fire Trade* extension, which will score the hashed, timestamped archive this system is building against real subsequent outcomes.

> If asked "how accurate is your AI?", the correct answer is that we do not claim a figure, and why. That answer scores better than any number we could manufacture.

---

## 1. Risk score

**Implemented in:** `backend/app/risk/scoring.py`

The score is computed by code from measured inputs. The Risk Agent **explains** it; it does not produce it.

Each factor is normalised to 0–100 (higher = more risk), then combined as a weighted average.

| Factor | Weight | Raw measurement | Normalisation |
|---|---|---|---|
| Volatility | 0.35 | Annualised realised volatility from log returns over 14 periods | `vol% / 1.5`, capped at 100. 150% annualised maps to the top |
| Liquidity | 0.25 | 24h volume ÷ market cap | `100 − (turnover / 0.10) × 100`. **Inverted** — low turnover is high risk. 10% turnover counts as fully liquid |
| Momentum extremity | 0.20 | RSI(14) | `|RSI − 50| / 50 × 100`. Both extremes count as elevated risk |
| Drawdown from high | 0.20 | `(window high − last close) / window high` | `drawdown / 0.5 × 100`. A 50% drawdown maps to the top |

**Missing factors are dropped and the remaining weights renormalised.** A factor we could not compute lowers *coverage* rather than silently contributing zero — otherwise a missing input would drag the score down and look like low risk.

`coverage` is reported alongside the score: `computed weight / total weight`.

### Worked example

Volatility 7.6% annualised, turnover 3.8%, RSI 43.35, drawdown 4.65%:

```
volatility        7.63 / 1.5                  =  5.09
liquidity         100 − (0.038 / 0.10 × 100)  = 61.86
momentum          |43.35 − 50| / 50 × 100     = 13.30
drawdown          4.65 / 0.5                  =  9.30

score = (5.09×0.35 + 61.86×0.25 + 13.30×0.20 + 9.30×0.20) / 1.0
      = 21.7
```

---

## 2. Reviewer score

**Implemented in:** `backend/app/agents/reviewer.py`

Deliberately **hybrid**. Letting a language model grade its own output is circular reasoning — we would be using the same class of system whose reliability we are trying to establish as the judge of that reliability.

### Deterministic component (the base score)

| Component | Weight | Definition |
|---|---|---|
| Evidence coverage | 30 | `|cited ∩ available| / |available|` |
| Citation validity | 35 | `1 − (invalid citations / total claims)` |
| Completion rate | 25 | `completed agents / attempted agents` |
| Agent agreement | 10 | Mean Jaccard overlap of cited evidence between agent pairs. Fixed at 0.5 with fewer than two completed agents, since there is nothing to compare |

**Staleness cap:** if any evidence came from expired cache, the score is capped at 75. An analysis of old numbers cannot be excellent however well argued.

### Model component (bounded)

The reviewer model may recommend a penalty of **0–25 points** for genuine problems it identifies: unsupported claims, reasoning gaps, overconfidence, contradictions between agents.

```
final = max(0, deterministic_score − model_penalty)
```

The model cannot invent a high score for weak work, and cannot veto a well-evidenced analysis.

### Verdict thresholds

| Score | Verdict |
|---|---|
| < 40 | `REJECTED` |
| 40–55 | `REANALYZE` — orchestrator re-runs once, bounded |
| ≥ 55 | `APPROVED` |

The re-analysis limit is **1**, so a persistent disagreement between reviewer and agents cannot loop forever.

### Confidence calibration

```
confidence = min(model_stated_confidence, 0.5 + evidence_coverage / 2)
```

High confidence on thin coverage is not passed through unchanged.

---

## 3. Evidence coverage

```
coverage = |evidence cited by completed agents ∩ evidence available|
           ─────────────────────────────────────────────────────────
                        |evidence available|
```

Low coverage means the analysis ignored information it had. This is a real quality signal, not a technicality.

Typical observed values: **44–59%**. Not every fact is relevant to every question, so 100% is neither expected nor desirable.

---

## 4. Citation validity

```
validity = 1 − (claims with unresolvable citations / total claims)
```

Enforced by `validate_agent_output` in `backend/app/agents/contract.py`. Four checks:

1. Every cited `evidence_id` exists in the bundle
2. Every interpretation cites at least one id
3. Every observation cites at least one id
4. Every number in an observation matches a cited evidence **value**, **label** or **unit**, within a 2% relative tolerance for rounding

Check 4 is what actually catches hallucinated figures. The tolerance allows legitimate rounding ("2462" for 2462.7) but not a materially wrong number ("2800" for 2462.7) — there is a test asserting exactly that boundary.

**On checks against labels and units:** indicator names carry their period (`SMA (20)`, `RSI (14)`) and units carry windows (`% of market cap traded in 24h`). An agent quoting those accurately is doing what we asked. Two live runs failed on this before it was fixed; both are now regression tests.

---

## 5. Indicator correctness

**Implemented in:** `backend/app/indicators/engine.py` · **Tested in:** `tests/test_indicators.py`

Indicators are hand-implemented rather than imported, because the AI is not permitted to compute numbers and therefore every value must come from code we can prove correct.

Verification approach: **assert against hand calculations documented in the test**, not against another library. Checking one implementation against another only proves they agree, not that either is right.

RSI uses **Wilder's smoothing**:

```
avg_gain_t = (avg_gain_{t−1} × (period − 1) + gain_t) / period
```

A plain rolling mean gives visibly different values. The test pins the implementation to Wilder's definition with the arithmetic shown.

> During development the engine returned 70.4641 where the test expected 70.53. Working the formula by hand confirmed the **engine** was right and the expected constant was wrong. The test now asserts the hand-verified value.

---

## 6. Result integrity

**Implemented in:** `backend/app/audit/hashing.py`

```
canonical = json(payload, sorted keys, no whitespace, floats normalised,
                 volatile metadata excluded)
hash      = SHA-256(prev_hash + ":" + canonical)
```

**What this proves:** the record has not been altered since it was written — *tamper-evidence*.

**What it does not prove:** immutability. Anyone with database write access could rewrite both record and hash. There is a test asserting exactly this, so the limit is documented rather than glossed over.

**What the chain adds:** each record commits to its predecessor's hash, so editing an old record invalidates every hash after it. An attacker must rewrite the entire subsequent chain, not one row.

**What would earn the word "immutable":** anchoring a chain root on-chain. Documented as a future option; not currently claimed.

---

## 7. Local vs online model comparison

Identical analysis of ETH — same evidence bundle, same prompts, same validator.

| | Model | Duration | Agents completed | Coverage | Reviewer score |
|---|---|---|---|---|---|
| Online | `openai/gpt-oss-120b` | **8s** | 4/4 | 59% | 78.5 |
| Local | `llama3.1:8b` | 462s | 4/4 | 44% | 59.9 |

### Findings

1. **The local model is ~58× slower** on this hardware. Not a defect — an 8B model on a laptop versus a large model on dedicated hardware.

2. **Concurrency behaves completely differently.** Ollama loads one copy of the model and serves largely serially. Firing four agents at it simultaneously made all four time out at 120s, though a single warm request answers in 1.6s. Providers now advertise `max_concurrency` (local 1, online 5).

3. **Structured-output reliability differs.** Both produced valid JSON under `format: json` / `response_format: json_object`, but the local model needed the repair retry more often.

4. **Quality difference is real but not dramatic.** The larger model cited more evidence (59% vs 44%), producing a higher reviewer score. Both stayed within the validation rules.

We report this as an observed finding on one machine with one prompt set. It is not a general benchmark, and we do not present it as one.

---

## Reproducibility

We claim **evidential reproducibility**, not bit-identical output.

- Temperature is 0 for every analytical call
- Model, provider, mode and all parameters are stored with every result
- The full evidence bundle is stored, so a run can be re-attempted against identical inputs

Temperature 0 makes sampling greedy but **not** deterministic: floating-point non-determinism on GPUs, batching, and provider-side model updates all cause variation. Claiming bit-identical reproducibility would be false.
