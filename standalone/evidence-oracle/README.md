# EvidenceOracle

A standalone GenLayer **Intelligent Contract** that turns *"I claim this public
web page says X"* into a **bonded, appealable, independently-verified on-chain
attestation** that other contracts and frontends can consume as a fact.

- **Source:** `standalone/evidence-oracle/contract.py` (class `EvidenceOracle`)
- **Tests:** `standalone/evidence-oracle/tests/direct/` (30 tests) and
  `standalone/evidence-oracle/tests/integration/` (guarded)
- **Live deployment (studio-dev):** `0xc315465D70D377CDB078aB0117C011d46A288E1F`
- **Deploy tx:** `0x5d99874cc6448fbac42c89ba4b4beb1d1be533e9a2e029e4248b4736367eb9c6` (FINALIZED)

> This contract is **independent of the main ProofOfPost / RuleRegistry project**.
> It shares no code with it and stands on its own as a reusable oracle primitive.

---

## 1. Use case

A prediction market, a dispute-resolution dApp, a compliance workflow, or a
bounty platform often needs a single question answered definitively from
evidence that lives **off-chain**: *"Did page X report value Y?"*, *"Does this
public receipt show the order shipped?"*, *"Does the source article say the
event happened on the claimed date?"*

`EvidenceOracle` lets anyone **stake a claim about a public `https` page**, have
a validator set **independently re-fetch that page and re-derive the verdict**,
and settle the result on-chain with a bond that is refunded when the claim is
right and slashed when it is contradicted. The settled verdict is a first-class,
appealable, reproducible on-chain fact.

## 2. Independent value beyond a main project

It is a **general-purpose evidence oracle**, not a feature of any one app. Any
GenLayer contract or frontend that needs "was this statement about a public
source verified, and with what verdict?" can read `get_claim` / `is_supported`.
It is reusable and educational on its own: it demonstrates the bounded
propose → resolve → challenge money-and-consensus lifecycle with a comparative
validator.

## 3. Why GenLayer (and not a plain smart contract or an AI API)

The judgment is **subjective natural-language inference over content that lives
off-chain**:

- A deterministic EVM smart contract **cannot read a web page** and cannot
  decide whether prose supports a statement.
- A single centralized AI/LLM answer is **not trustworthy and not disputable** -
  one model's opinion, with no recourse when it is wrong.
- A traditional oracle (e.g. price feeds) only works for values that have a
  canonical numeric source; free-form textual entailment has none.

GenLayer is the right tool because **every validator independently fetches the
same URL and re-derives the decision**, and the settled result is reproducible
and **appealable**. Consensus over an untrusting read of untrusted content is
exactly the niche a centralized API cannot fill.

## 4. State model

```
PENDING --resolve()--> SUPPORTED | CONTRADICTED | UNVERIFIABLE
   ^                          |
   |                          v
   (challenge re-runs consensus; a flipped verdict
    updates the recorded status, up to MAX_CHALLENGES=2 rounds)
```

Per-claim data (`Claim` dataclass): `claim_id, proposer, url, statement, bond,
status, verdict_quote, observed_value, reason, challenge_count`. Contract-level
counters: `supported_total / contradicted_total / unverifiable_total /
slashed_total / withdrawn_slashed / min_bond / next_id`. IDs are **0-based**.

## 5. Equivalence Principle - comparative, custom validator (justified)

Every `resolve`/`challenge` runs one non-deterministic operation, `_verify`:

- **Leader:** `gl.nondet.web.get(url)` → truncate to 12 000 chars →
  `gl.nondet.exec_prompt(..., response_format="json")` → normalized
  `{verdict, value, quote, reason}`.
- **Validator:** performs **the same fetch and the same derivation
  independently**, then agrees **only on the decision**:
  - `verdict` must match **exactly** (`SUPPORTED` / `CONTRADICTED` / `UNVERIFIABLE`);
  - any extracted scalar `value` must agree within a **1% relative tolerance**
    using integer math (`_as_scaled` scales to 1e6; no floats cross validators).
  - Wording (`quote`, `reason`) is deliberately **not** compared.

Why not the alternatives:
- `strict_eq` is impossible - pages change between fetches and LLMs paraphrase,
  so full-text equality would never converge.
- Non-comparative validation would let the **leader decide alone**, defeating the
  purpose of an oracle. Requiring independent re-derivation of the *verdict* is
  what makes the settled result trustworthy.

### Error classification (consensus on failure paths)

The fetcher classifies outcomes so validators can compare them deterministically:

| Prefix | Meaning | Agreement rule |
|---|---|---|
| `[EXPECTED]` | business/validation error | exact match |
| `[EXTERNAL]` | source 4xx / empty page | exact match |
| `[TRANSIENT]` | source 5xx / no body | agree if both transient |
| `[LLM_ERROR]` | bad model output shape | always disagree → force rotation |

`_handle_leader_error` re-runs the leader function on the validator side and
applies this table, so a missing page and a flaky page are handled distinctly.

## 6. Input validation & security controls

- **URL validation** (`_clean_url`): non-empty, ≤500 chars, no whitespace,
  must start with `https://`.
- **SSRF / local-target guard**: hosts beginning with `localhost`, `127.`,
  `0.0.0.0`, `10.`, `192.168.`, `172.16.`, `169.254.` (link-local), `[fd`/`[::1`
  (IPv6 loopback/ULA), `host.docker.internal`, or any URL carrying `@`
  credentials are **rejected**. The fetch runs on validator infrastructure, so a
  submitted URL must never reach an internal service.
- **Prompt-injection hardening**: the adjudicator prompt explicitly instructs the
  model to treat page text as **untrusted data** and ignore instructions inside
  it; page text is delimited and capped.
- **Bounds**: statement ≤1000, quote ≤400, reason ≤600, value ≤80 chars; page
  truncated to 12 000 chars; verdict forced into an allowed enum.
- **Bond gate**: `propose` and `challenge` require `msg.value ≥ min_bond`.
- **Access control**: only the proposer or owner may `resolve`; the proposer can
  never `challenge` its own claim; `withdraw_slashed` / `set_min_bond` are
  owner-only.
- **Bounded escalation**: `MAX_CHALLENGES = 2` prevents endless re-litigation.
- **Money safety**: payouts to EOAs use an **external** EVM message
  (`_GENReceiver(to).emit_transfer(value=...)`); internal `get_contract_at`
  transfers are silently never delivered to an EOA. Each challenge round's stake
  is settled on its own and a `CONTRADICTED` bond is only released if it is
  actually held, so no stake or bond is ever double-paid.

## 7. Public interface

Writes: `propose(url, statement) payable -> claim_id`, `resolve(claim_id) -> status`,
`challenge(claim_id) payable -> status`, `withdraw_slashed(to, amount)`,
`set_min_bond(amount)`.
Views: `get_claim(claim_id)`, `list_claims(offset, limit)`, `get_stats()`,
`is_supported(claim_id) -> bool`, `get_min_bond() -> str`.
Constructor: `__init__(min_bond: int)`.

## 8. Example calls & expected outcomes

```python
# 1. Post a claim about a public page, attaching a 1 GEN bond
claim_id = oracle.propose(
    url="https://example.com/order-12345",
    statement="The page shows order 12345 as shipped",
    value=1_000_000_000_000_000_000,   # 1 GEN, must be >= min_bond
)   # -> claim_id = 0, status stored as PENDING

# 2. Settle it: validators fetch the page and independently decide
status = oracle.resolve(claim_id)      # -> "SUPPORTED" | "CONTRADICTED" | "UNVERIFIABLE"
# SUPPORTED / UNVERIFIABLE -> proposer bond refunded
# CONTRADICTED             -> bond slashed into the owner pool

# 3. A third party disputes the settled verdict, posting their own stake
new_status = oracle.challenge(claim_id, value=1_000_000_000_000_000_000)
# verdict flipped  -> challenger's stake returned (+ proposer bond if it was held)
# verdict upheld   -> challenger's stake slashed

# 4. Consumers read the settled fact
oracle.get_claim(0)
# {"claim_id":"0","proposer":"0x…","url":"https://example.com/order-12345",
#  "statement":"…","bond":"1000000000000000000","status":"SUPPORTED",
#  "quote":"Your order #12345 has shipped","value":"","reason":"…",
#  "challenge_count":"0"}
oracle.is_supported(0)   # -> True  (the downstream gate a consumer checks)
oracle.get_stats()
# {"total":"1","supported":"1","contradicted":"0","unverifiable":"0",
#  "min_bond":"1000000000000000000","slashed_total":"0","withdrawn_slashed":"0",
#  "contract_balance":"…","owner":"0x…"}
```

Rejected inputs raise classified `[EXPECTED]` errors, e.g. `propose("http://…")`
→ `"[EXPECTED] Url must be https"`, `propose` with a `169.254.` host
→ `"[EXPECTED] Url host is not allowed"`, `resolve` on a settled claim
→ `"[EXPECTED] Claim already settled"`.

## 9. Tests

- **Direct (fast, mocked, no network):** `tests/direct/test_evidence_oracle.py` -
  30 tests covering URL/statement/bond validation incl. every SSRF prefix, all
  three verdicts and their accounting, `[EXTERNAL]` 404 and `[TRANSIENT]` 503
  paths, invalid-verdict `LLM_ERROR`, unauthorized/duplicate `resolve`, the full
  challenge matrix (upheld slash, flip release, no-double-pay, proposer-can't-
  challenge, limit), owner-only withdraw, pagination, and `run_validator`
  consensus (agree / verdict mismatch / value-within-1%-tolerance / llm-error).
  Run: `pytest standalone/evidence-oracle/tests/direct -q`
- **Integration (live network, guarded):** `tests/integration/` self-skips unless
  `RUN_INTEGRATION=1`; run against a real environment with
  `RUN_INTEGRATION=1 gltest standalone/evidence-oracle/tests/integration -v -s`.

## 10. Deployment procedure

Network: **GenLayer Studio Devnet** (`studio-dev`, Studio Next preview),
chainId **61997**, RPC `https://studio-dev.genlayer.com/api`. It is **not**
gasless - each tx needs a non-zero fee deposit (≈0.1 GEN quoted, ~0.00008 GEN
actually consumed, remainder refunded on finalize).

The contract pins a specific runner and carries the required version preamble;
the first two lines are load-bearing (the fleet rejects `test`/`latest`/unversioned
runners and a header without the `# v0.2.16` line):

```python
# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
```

Lint before deploying: `genvm-lint check standalone/evidence-oracle/contract.py`
(→ PASS, 10 methods: 5 view / 5 write, ctor_params 1).

**SDK deploy (recommended - fee-aware, never exposes the key):** see
`frontend/deploy_standalone.mjs`. It reads `GENLAYER_PRIVATE_KEY` from `.env`,
estimates fees, deploys with `args=[min_bond]`, polls until FINALIZED, and
**recovers the deployed address from the deploy tx's `to_address` /
`contract_address`** (genlayer-js `2.0.0-rc.1` does not populate
`receipt.contractAddress`).

**CLI alternative** (keystore must be unlocked):

```bash
genlayer network set studionet   # studio-dev RPC if not built-in to your CLI build
genlayer deploy --contract standalone/evidence-oracle/contract.py --args 1000000000000000000
genlayer call <address> get_stats
```

Constructor arg `min_bond` is in atto-GEN (`1000000000000000000` = 1 GEN).

## 11. Why this is useful to other builders

EvidenceOracle is a compact, self-contained template for the
**"bonded oracle over untrusted web evidence"** pattern: a comparative validator
that agrees on the *decision* (not the wording), an integer-tolerance scalar
match, an SSRF-hardened fetcher, classified errors so consensus holds on failure
paths, and an external-message payout that actually reaches an EOA. Any project
needing an appealable "is this claim about a public source true?" primitive can
adopt it directly or lift these specific techniques.

## 12. Known limitations

- Consensus depends on validator LLM/fetch availability on the chosen network;
  the constructor and views are deterministic, but `resolve`/`challenge` require
  the shared validator set to converge.
- The oracle attests to what a page **says at fetch time**; mutable pages may
  change afterward (bounded challenges mitigate, not eliminate, this).
- `value` tolerance applies only when the statement's number appears on the
  page; absent numbers fall back to verdict-only agreement.
