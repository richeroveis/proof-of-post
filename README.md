# ProofOfPost — on-chain content-rule adjudication on GenLayer

**ProofOfPost** is a stake-backed content-compliance registry built as a GenLayer
**Intelligent Contract**. A submitter posts content (or a URL) together with an
explicit natural-language rule set and a bond; a GenLayer validator ensemble
**independently re-derives** whether the content satisfies the rules; the contract
settles a normalized, appealable verdict that drives a real bonded payout
(COMPLIANT → registered + bond kept, NON_COMPLIANT → slashed, INCONCLUSIVE →
held/refundable).

This repository also ships **two standalone, independently-reviewable Intelligent
Contracts** (`standalone/`) that are *not* part of the main project and stand on
their own as reusable GenLayer primitives.

| | |
|---|---|
| Live demo | https://richeroveis.github.io/proof-of-post |
| Repository | https://github.com/richeroveis/proof-of-post |
| Network | GenLayer Studio Devnet (`studio-dev`, chainId **61997**, RPC `https://studio-dev.genlayer.com/api`) |
| Main contract `RuleRegistry` | `0x61eE31810F804E53b4Eb4A3c876F0504A1fC304b` |
| Standalone `EvidenceOracle` | `0xc315465D70D377CDB078aB0117C011d46A288E1F` |
| Standalone `ScoreRegistry` | `0x2579a22a567a6A9D424Fa6225c201aD359bd8d66` |

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
  preview, registry browsing. It talks to the **real deployed contract** only —
  no mock data or simulated transactions.
- **Contract owns:** bond custody, the minimum state transition needing consensus
  (the verdict), evidence inputs, the validator comparison rule, the settlement
  effect, and the appeal path.
- **External sources own:** raw content, always treated as **untrusted** and
  prompt-injection-hardened.

Money is handled as atto-scale `u256` (never `float`); payouts to EOAs use an
**external EVM message** (an internal `get_contract_at().emit_transfer` is
silently never delivered to an EOA). See `docs/deployment.md` finding 6.

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

- **[EvidenceOracle](standalone/evidence-oracle/README.md)** — bonded, appealable
  attestations about public web pages. Comparative validator agrees on the verdict
  exactly and on any extracted scalar within a 1% integer tolerance; SSRF-hardened
  fetcher; classified errors for consensus on failure paths. **30 direct tests.**
- **[ScoreRegistry](standalone/score-registry/README.md)** — consensus rubric
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

# fast direct-mode tests (mocked web/LLM, no network) — 22 + 54 pass
pytest tests/direct -q
pytest standalone/evidence-oracle/tests/direct standalone/score-registry/tests/direct -q

# integration tests hit a real network and self-skip unless explicitly enabled
RUN_INTEGRATION=1 gltest standalone/evidence-oracle/tests/integration -v -s
```

## Frontend

See [`frontend/README.md`](frontend/README.md). Reads use `gen_call` view calls;
writes are signed locally in the browser with a **studio-dev-only** key (never a
mainnet key), attach an estimated non-zero fee, and poll the tx lifecycle to
`FINALIZED` before re-reading — because the validator verdict, not the tx hash,
decides whether a bond is refunded or slashed.

## Documentation

- [`docs/research.md`](docs/research.md) — campaign/network/tooling research
- [`docs/project-decision.md`](docs/project-decision.md) — approved scope & consensus design
- [`docs/deployment.md`](docs/deployment.md) — studio-dev operational findings (fees, runner header, EOA payouts)
- [`docs/onchain-activity.md`](docs/onchain-activity.md) — bounded real-transaction regression record
- [`docs/testing.md`](docs/testing.md) — test strategy
- [`docs/submission.md`](docs/submission.md) — submission-ready descriptions

## Security

- `.env` is gitignored; `.env.example` holds placeholders only.
- No private key or GitHub token ever enters source, frontend bundles, or logs.
- All chain operations are restricted to the authorized **studio-dev** dev network;
  no mainnet, no force-push.

## Known limitations

- `studio-dev` is temporary and resets; deployments are ephemeral and must be
  re-deployed/re-configured (see `docs/deployment.md`).
- Consensus on `evaluate`/`resolve`/`grade`-type writes depends on the shared
  validator set being available and converging; constructors and views are
  deterministic and were verified live on studio-dev.
- Campaign point ranges were not independently verifiable from the JS-rendered
  portal and require an in-browser human check at submission time.
