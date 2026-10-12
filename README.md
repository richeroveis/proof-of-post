# ProofOfPost - on-chain content-rule adjudication on GenLayer

**ProofOfPost** is a stake-backed content-compliance registry built as a GenLayer
**Intelligent Contract**. A submitter posts literal text (URLs are judged as
text - remote content is never fetched) together with an explicit
natural-language rule set and a bond; a GenLayer validator ensemble
**independently re-derives** whether the content satisfies the rules; the contract
settles a normalized, appealable verdict that drives a real bonded payout
(COMPLIANT → registered + bond kept, NON_COMPLIANT → bond slashed but **reserved
against the appeal window**, INCONCLUSIVE → held/refundable; a stuck PENDING
entry is recoverable by the submitter via `cancel_pending`). Slashed collateral
becomes treasury-withdrawable only after its appeal liability is finalized
(the minimum window elapsed and a withdrawal swept it, or the appeal budget
was exhausted), so a winning appeal is always refundable.

This repository also ships **two standalone, independently-reviewable Intelligent
Contracts** (`standalone/`) that are *not* part of the main project and stand on
their own as reusable GenLayer primitives.

| | |
|---|---|
| Live demo | https://richeroveis.github.io/proof-of-post |
| Repository | https://github.com/richeroveis/proof-of-post |
| Network | GenLayer Studio Devnet (`studio-dev`, chainId **61997**, RPC `https://studio-dev.genlayer.com/api`) |
| Main contract `RuleRegistry` (F7 + withdraw-hardened, 2026-10-11) | `0x30A9A1D88E8885319a9f5F259D5C416Bd55d149E` |
| Deploy provenance | source = commit `cbbb459`, sha256 `db714bb9…b5993` of `contracts/rule_registry.py` (byte-identical at current `main`), deploy tx `0xfcdf651213c1414b…aaf660b6` (FINALIZED), tag `deploy-0x30A9` |
| Standalone `EvidenceOracle` | `0xc315465D70D377CDB078aB0117C011d46A288E1F` |
| Standalone `ScoreRegistry` | `0x2579a22a567a6A9D424Fa6225c201aD359bd8d66` |

The remediation of the reviewer findings (F1 slashed-collateral reservation,
F2 PENDING recovery, F3 strict rule-size limits, F5 treasury-only routing, F6
bounded appeal semantics, F7 reservation-gated appeal hardened against third-party
tick-window spam, plus a `withdraw_slashed` malformed-input guard) is documented
in [`docs/remediation-plan.md`](docs/remediation-plan.md) with the exact
regression tests, and every security path above is exercised against the live
contract in [`docs/onchain-activity.md`](docs/onchain-activity.md).

## Contract lifecycle (state machine)

| Status | Funds state | Permitted transitions (caller) |
|---|---|---|
| `PENDING` | bond escrowed in the contract (in `bonded_pending`) | `evaluate` (submitter or owner) -> settled verdict; `cancel_pending` (submitter or owner) -> `CANCELLED` + refund |
| `COMPLIANT` | bond refunded, entry verified | terminal |
| `INCONCLUSIVE` | bond refunded, not verified | terminal |
| `CANCELLED` | bond refunded | terminal |
| `NON_COMPLIANT` | bond slashed and **reserved** (`reserved_slashed`; `appeal_deadline = settle tick + 4`) | `appeal` (submitter only) while reserved and `appeal_count < 2`: a reversing verdict releases the reservation, un-slashes and refunds; an upheld verdict keeps it reserved; the second upheld appeal exhausts the budget and finalizes the liability. `withdraw_slashed` (owner only) first sweeps reservations whose `appeal_deadline` has elapsed, then pays the treasury only the unreserved portion; swept entries are no longer appealable |

Ledger invariants held after every transition (asserted in tests):
`slashed_total >= withdrawn_slashed + reserved_slashed`,
`reserved_slashed == sum of bonds of entries with appeal_deadline > 0`,
`bonded_pending == sum of PENDING bonds`, and `withdraw_slashed` is capped by
both the availability figure and the contract's native balance. Every guard
reverts with a classified `[EXPECTED]` error, and a reverted write rolls back
atomically on-chain.

---

## Why GenLayer (and not a plain contract or an AI API)

Whether free-form content satisfies natural-language rules is a **subjective,
AI-mediated judgment with a financial consequence**. A deterministic smart
contract cannot make it; a single centralized LLM answer is opaque, censorable,
and contestable when it slashes a bond. GenLayer is used precisely because
**multiple validators independently reproduce the decision and must agree on the
settled verdict**, which is then reproducible and appealable on-chain. Every
contract here uses **Optimistic Democracy consensus** with an explicit
**Equivalence Principle** and a **comparative custom validator** (never
`strict_eq` on LLM output, never leader-only format checking).

## Architecture boundary

- **Frontend owns:** UI, wallet connect, submission form, non-authoritative
  preview, registry browsing. It talks to the **real deployed contract** only -
  no mock data or simulated transactions.
- **Contract owns:** bond custody, the minimum state transition needing consensus
  (the verdict), evidence inputs, the validator comparison rule, the settlement
  effect, and the appeal path.
- **External sources own:** raw content, always treated as **untrusted** and
  prompt-injection-hardened.

Money is handled as atto-scale `u256` (never `float`); payouts to EOAs use an
**external EVM message** (an internal `get_contract_at().emit_transfer` is
silently never delivered to an EOA). See `docs/deployment.md` finding 6.

**Time model.** The pinned GenVM runner (v0.2.16) exposes no timestamp or
block-height API, so appeal windows and PENDING recovery are expressed on the
contract's own lifecycle clock: `tick` counts finalized writes, a NON_COMPLIANT
bond stays reserved for at least `APPEAL_WINDOW_TICKS` (4) further settled
writes before a withdrawal may sweep it, and expired reservations are swept
inside the withdrawal write itself. The **right to appeal** is gated on the
reservation, not the counter: anyone could burn ticks with cheap self-canceling
writes, so an entry stays appealable while its bond is still reserved and only
loses that right when the liability is truly finalized (appeal cap exhausted,
or a sweep inside a completed, paying withdrawal). A stuck
PENDING bond is recovered with `cancel_pending()` - safe without a timer because
`evaluate` and `cancel` serialize through atomic finalization (the loser reverts
with `[EXPECTED] Entry not pending`). See `docs/remediation-plan.md`.

**Limits are enforced by rejection, never truncation**: ≤ 30 rules × 300 chars,
title ≤ 200, content ≤ 8000 - the rules the validators judge are exactly the
rules the submitter stored. `withdraw_slashed(amount)` pays only to the
configured treasury. An appeal re-runs the same assessment on the same stored
evidence; no new evidence can be attached.

## Repository layout

```
contracts/rule_registry.py        # main RuleRegistry intelligent contract
frontend/                         # Next.js static dashboard (genlayer-js 2.x)
standalone/
  evidence-oracle/                # standalone contract 1 (README + tests)
  score-registry/                 # standalone contract 2 (README + tests)
tests/                            # direct + guarded integration tests (main project)
docs/                             # research, decision, deployment, activity, submission
```

## The two standalone contracts

They are **independent of ProofOfPost** (no shared code, distinct domains,
distinct validation strategies), each fully documented with use case, why
GenLayer, justified equivalence principle, security controls, example calls with
expected outcomes, tests, and a deployment procedure.

- **[EvidenceOracle](standalone/evidence-oracle/README.md)** - bonded, appealable
  attestations about public web pages. Comparative validator agrees on the verdict
  exactly and on any extracted scalar within a 1% integer tolerance; SSRF-hardened
  fetcher; classified errors for consensus on failure paths. **30 direct tests.**
- **[ScoreRegistry](standalone/score-registry/README.md)** - consensus rubric
  scoring with a reproducible pass/fail gate. **Hybrid** equivalence: deterministic
  LLM-generated checks evaluated in a restricted interpreter under **strict
  equality**, the subjective score within a **tolerance band**, and the pass/fail
  gate by **exact** agreement. **24 direct tests.**

## Lint & test

Every contract pins a concrete GenVM runner and carries the required version
preamble (the fleet rejects `test`/`latest`/unversioned runners and headers
without the `# v0.2.16` line).

```bash
# static analysis + SDK semantics (all PASS: 10 methods each standalone)
genvm-lint check contracts/rule_registry.py
genvm-lint check standalone/evidence-oracle/contract.py
genvm-lint check standalone/score-registry/contract.py

# fast direct mode tests (mocked web/LLM, no network) - 41 + 54 pass
pytest tests/direct -q
pytest standalone/evidence-oracle/tests/direct standalone/score-registry/tests/direct -q

# integration tests hit a real network and self-skip unless explicitly enabled
RUN_INTEGRATION=1 gltest standalone/evidence-oracle/tests/integration -v -s
```

## Frontend

See [`frontend/README.md`](frontend/README.md). Reads use `gen_call` view calls;
writes are signed locally in the browser with a **studio-dev-only** key (never a
mainnet key), attach an estimated non-zero fee, and poll the tx lifecycle to
`FINALIZED` before re-reading - because the validator verdict, not the tx hash,
decides whether a bond is refunded or slashed.

## Documentation

- [`docs/remediation-plan.md`](docs/remediation-plan.md) - reviewer findings → fixes → regression tests
- [`docs/research.md`](docs/research.md) - campaign/network/tooling research
- [`docs/project-decision.md`](docs/project-decision.md) - approved scope & consensus design
- [`docs/deployment.md`](docs/deployment.md) - studio-dev operational findings (fees, runner header, EOA payouts)
- [`docs/onchain-activity.md`](docs/onchain-activity.md) - bounded real-transaction regression record
- [`docs/testing.md`](docs/testing.md) - test strategy
- [`docs/submission.md`](docs/submission.md) - submission-ready descriptions

## Security

- `.env` is gitignored; `.env.example` holds placeholders only.
- No private key or GitHub token ever enters source, frontend bundles, or logs.
- All chain operations are restricted to the authorized **studio-dev** dev network;
  no mainnet, no force-push.

## Known limitations

- `studio-dev` is temporary and resets; deployments are ephemeral and must be
  re-deployed/re-configured (see `docs/deployment.md`).
- The nominal appeal window (`APPEAL_WINDOW_TICKS`) is measured in lifecycle
  writes, not wall-clock time (the pinned runner exposes no timestamp/block API)
  and now bounds only when a treasury withdrawal MAY sweep the reservation; the
  right to appeal continues past that tick until the liability is actually
  finalized - a completed paying withdrawal or the two-appeal budget being
  exhausted. This is a deliberate protocol-semantic change (see
  `docs/remediation-plan.md`, F7): it is now deployed and **live-verified on
  `0x30A9A1D8…d149E`** (the tick-window-spam appeal survives on-chain), but it
  still **needs reviewer sign-off** as a semantics decision; a quiet registry
  therefore keeps collateral reserved longer in real time, which is the
  conservative direction for submitters.
- Whether a verdict is *reversible* on appeal is up to the validator ensemble:
  the reversal/refund path is proven deterministic in direct tests and live
  `e2e/` runs, but an individual LLM flip cannot be forced on command.
- Consensus on `evaluate`/`resolve`/`grade`-type writes depends on the shared
  validator set being available and converging; constructors and views are
  deterministic and were verified live on studio-dev.
- Campaign point ranges were not independently verifiable from the JS-rendered
  portal and require an in-browser human check at submission time.
