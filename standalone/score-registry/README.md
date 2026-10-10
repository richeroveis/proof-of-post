# ScoreRegistry

A standalone GenLayer **Intelligent Contract** that turns *"this work is good
enough"* into a **settled 0–100 score with a public, reproducible pass/fail
gate**, backed by validator consensus and an appealable bond.

- **Source:** `standalone/score-registry/contract.py` (class `ScoreRegistry`)
- **Tests:** `standalone/score-registry/tests/direct/` (24 tests) and
  `standalone/score-registry/tests/integration/` (guarded)
- **Live deployment (studio-dev):** `0x2579a22a567a6A9D424Fa6225c201aD359bd8d66`
- **Deploy tx:** `0x6f695e46ed3a8bbc86a67e0222e434d9407b1174f696ae72f80d5feef5ebae71` (FINALIZED)

> Independent of the main ProofOfPost / RuleRegistry project: no shared code, and
> a different domain (rubric scoring) with a different, hybrid equivalence
> strategy.

---

## 1. Use case

Grants, bounties, content moderation, assignment review, marketplace listings,
and contribution rewards all need the same thing: score a piece of free-form
work against a rubric and publish a **defensible pass/fail decision** that a
downstream payout or access rule can trust — without a single trusted scorer
deciding arbitrarily.

`ScoreRegistry` lets a submitter post work + rubric + a pass threshold with a
bond; validators then produce a 0–100 score and a settled `PASSED`/`FAILED`
gate; a failed verdict can be appealed (bounded, staked re-grade).

## 2. Independent value beyond a main project

It is a **reusable scoring/review oracle**, not a feature of one app. Any
contract or frontend that needs "did this submission clear its rubric gate, and
with what score?" reads `get_item` / `passes_gate` / `get_score`. It is
educational on its own because it demonstrates the hardest consensus problem —
mixing deterministic and subjective evidence — with a **hybrid** equivalence
rule rather than one blunt strategy.

## 3. Why GenLayer (and not a plain smart contract or an AI API)

Scoring text against a natural-language rubric is **subjective and
non-deterministic**, yet the outcome gates real value:

- A deterministic contract cannot judge text quality.
- A single LLM's score is untrustworthy, unreproducible, and — crucially —
  **hallucinable**: asked to count characters or check keyword presence, models
  get it wrong and disagree with themselves.
- No party should be able to pick the number that releases a payout.

GenLayer is appropriate because **multiple validators independently reproduce the
whole procedure** and must agree on the settlement gate, so the published verdict
is a consensus outcome, not one model's opinion.

## 4. Hybrid scoring (the core idea)

`_assess` runs three steps, and each kind of result is held to a different
consensus bar:

1. **LLM → code:** the model translates every *objectively checkable* rubric line
   into a Python boolean expression over `text` (skips subjective lines).
2. **Deterministic evaluation:** those expressions are run in a **restricted
   interpreter** with a tiny builtins whitelist (`len/any/all/str/int/abs/sum`)
   and only `text` in scope — so neither leader nor validator can hallucinate
   the outcome, and nothing can import or reach the host. Broken/unsafe
   expressions are **dropped, not guessed**.
3. **LLM → score:** the model proposes a 0–100 score **with the deterministic
   results supplied as ground truth it may not contradict**; status is
   `PASSED` iff `score ≥ threshold`.

## 5. Equivalence Principle — comparative, with two agreements (justified)

The validator independently repeats steps 1–3, then must agree with the leader on:

| Evidence | Agreement rule | Why |
|---|---|---|
| Deterministic sub-check map (`index → SATISFIED/VIOLATED`) | **STRICT EQUALITY** (JSON `sort_keys=True` byte-compare) | Same rule must yield the same status map; any divergence is a real defect |
| Numeric score (0–100) | **TOLERANCE BAND** `SCORE_TOLERANCE = 10` | Raw `strict_eq` on an LLM score never converges; unbounded tolerance lets the leader pick any number |
| Pass/fail gate (score ≥ threshold) | **EXACT match** | The gate *is* the settlement a consumer relies on |

This split is the whole point: strict equality is enforced where the evidence is
deterministic, and only the genuinely subjective part gets a tolerance — while
the decision that matters (pass/fail) is pinned to exact agreement.
`strict_eq` on the full LLM output would never reach consensus; pure
non-comparative validation would let the leader decide alone.

Errors are classified `[EXPECTED]` / `[EXTERNAL]` / `[TRANSIENT]` / `[LLM_ERROR]`
and compared with the same canonical `_handle_leader_error` table as the
companion EvidenceOracle, so consensus holds on failure paths too.

## 6. State model

```
PENDING --grade()--> PASSED | FAILED | INCONCLUSIVE
                        ^      |
                        |      v
             appeal() bounded re-grade of FAILED (up to MAX_APPEALS=2)
               flip -> release held bond + refund this round's stake
               upheld -> this round's stake slashed
```

Per-item (`Item` dataclass): `item_id, submitter, title, payload, rubric,
threshold, bond, status, score, checks_json, reason, appeal_count`. Counters:
`passing_total / failing_total / inconclusive_total / slashed_total /
withdrawn_slashed / min_bond / next_id`. IDs are **0-based**.

## 7. Input validation & security controls

- **Payload** non-empty, ≤6000 chars; **rubric** non-empty, ≤3000, capped at
  `MAX_CHECKS = 20` lines (each ≤300); **title** ≤200; **threshold** must be 0–100.
- **Bond gate**: `submit` and `appeal` require `msg.value ≥ min_bond`.
- **Access control**: only the submitter or owner may `grade`; only the submitter
  may `appeal`; only `FAILED` items may be appealed; `withdraw_slashed` /
  `set_min_bond` are owner-only.
- **Sandboxed eval**: LLM-generated expressions run against a whitelist; the
  work text is framed as **untrusted data** in every prompt and instructed to be
  ignored if it contains instructions.
- **Defensive number parsing**: `_clamp_score` coerces `"82"`, `82.0`, `82/100`,
  `82%` and clamps to 0–100 using integer logic.
- **Money safety**: EOA payouts go through an **external** EVM message
  (`_GENReceiver(to).emit_transfer(value=...)`); per-appeal stakes are settled
  individually and a held bond is released only once, so `slashed_total` is never
  overstated and nothing is double-paid.

## 8. Public interface

Writes: `submit(title, payload, rubric, threshold) payable -> item_id`,
`grade(item_id) -> status`, `appeal(item_id) payable -> status`,
`withdraw_slashed(to, amount)`, `set_min_bond(amount)`.
Views: `get_item(item_id)`, `list_items(offset, limit)`, `get_stats()`,
`passes_gate(item_id) -> bool`, `get_score(item_id) -> str`.
Constructor: `__init__(min_bond: int)`.
(`min_bond` is exposed through `get_stats`; there is no `get_min_bond` view on
this contract.)

## 9. Example calls & expected outcomes

```python
item_id = sr.submit(
    title="Launch blog post",
    payload="Our GenLayer launch post ... (article text)",
    rubric="Must mention GenLayer\nMust be at least 100 characters\nShould have an inviting tone",
    threshold=70,
    value=1_000_000_000_000_000_000,   # 1 GEN bond >= min_bond
)   # -> item_id = 0, status PENDING

status = sr.grade(item_id)   # -> "PASSED" | "FAILED" | "INCONCLUSIVE"
# PASSED / INCONCLUSIVE -> bond refunded;  FAILED -> bond slashed

# If FAILED, the submitter may stake a bounded re-grade:
new_status = sr.appeal(item_id, value=1_000_000_000_000_000_000)
# flipped to PASSED -> held bond released + stake refunded
# still FAILED      -> this round's stake slashed

sr.get_item(0)
# {"item_id":"0","submitter":"0x…","title":"Launch blog post",
#  "rubric":"Must mention GenLayer\n…","threshold":"70",
#  "bond":"1000000000000000000","status":"PASSED","score":"84",
#  "checks":[{"rule":"Must mention GenLayer","status":"SATISFIED"},
#            {"rule":"Must be at least 100 characters","status":"SATISFIED"}],
#  "reason":"…","appeal_count":"0"}
sr.passes_gate(0)   # -> True  (the downstream settlement a consumer checks)
sr.get_stats()
# {"total":"1","passing":"1","failing":"0","inconclusive":"0",
#  "min_bond":"1000000000000000000","slashed_total":"0","withdrawn_slashed":"0",
#  "contract_balance":"…","owner":"0x…"}
```

Rejected inputs raise `[EXPECTED]` errors, e.g. empty payload
→ `"[EXPECTED] Empty payload"`, `threshold=120`
→ `"[EXPECTED] Threshold must be 0-100"`, appealing a `PASSED` item
→ `"[EXPECTED] Only FAILED items can be appealed"`.

## 10. Tests

- **Direct (fast, mocked):** `tests/direct/test_score_registry.py` — 24 tests
  covering payload/rubric/threshold/bond validation, `grade` PASSED (checks
  generated & all `SATISFIED`) and FAILED slash, a broken `__import__` expression
  being dropped, unauthorized/duplicate grade, the full appeal matrix (flip
  release, upheld slash with `slashed_total` exactness, only-submitter,
  requires-failed, below-stake, limit), owner-only withdraw, pagination, and
  `run_validator` consensus (agree / gate mismatch / llm-error).
  Run: `pytest standalone/score-registry/tests/direct -q`
- **Integration (live network, guarded):** `tests/integration/` self-skips unless
  `RUN_INTEGRATION=1`; run with
  `RUN_INTEGRATION=1 gltest standalone/score-registry/tests/integration -v -s`.

## 11. Deployment procedure

Network: **GenLayer Studio Devnet** (`studio-dev`), chainId **61997**, RPC
`https://studio-dev.genlayer.com/api` (not gasless; see the fee notes in the
EvidenceOracle README). The runner pin and the `# v0.2.16` version-preamble line
are both required for the fleet to load the contract:

```python
# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
```

Lint: `genvm-lint check standalone/score-registry/contract.py` (→ PASS, 10
methods: 5 view / 5 write, ctor_params 1).

Deploy via the fee-aware SDK driver `frontend/deploy_standalone.mjs` (reads the
key from `.env`, estimates fees, deploys with `args=[min_bond]`, waits FINALIZED,
and recovers the address from the deploy tx's `to_address` / `contract_address`).
CLI alternative:

```bash
genlayer deploy --contract standalone/score-registry/contract.py --args 1000000000000000000
genlayer call <address> get_stats
```

Constructor arg `min_bond` is in atto-GEN (`1000000000000000000` = 1 GEN).
Verify live reads with the read-only helper:
`node frontend/verify_live.mjs <deploy-tx-hash>` (recovers the address and reads
`get_stats` + `list_items` without spending GEN).

## 12. Why this is useful to other builders

ScoreRegistry is a template for the hardest consensus case: **subjective output
that must gate value**. It shows how to (a) convert the checkable part of a
natural-language rubric into deterministically-evaluated code so no model can
hallucinate it, (b) feed those deterministic results back as ground truth, and
(c) use a **hybrid** equivalence rule — strict equality on deterministic evidence,
a tolerance band on the score, exact agreement on the settlement gate. Builders
implementing on-chain review, grading, or quality-gated payouts can adopt it
directly or reuse the hybrid-validation technique.

## 13. Known limitations

- The score is subjective; the tolerance band accepts reasonable disagreement
  but pins the pass/fail gate.
- Rubric lines that cannot be expressed programmatically are left to the model's
  judgment (by design) and are not part of the strict-equality map.
- As with any LLM consensus, `grade`/`appeal` require the validator set to be
  available and to converge; the constructor and views are deterministic.
