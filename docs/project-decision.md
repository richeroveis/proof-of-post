# Approved Project Decision

**Selected candidate:** ProofOfPost (Candidate 2 from `docs/candidates.md`)
**Approved by:** user (explicit selection at the Phase 2 approval gate, 2026-10-09)
**Approval note:** the user selected ProofOfPost over the assistant's recommended
MeritBounty. The user's choice is authoritative; ProofOfPost is a valid,
GenLayer-native concept.

## One-line definition

ProofOfPost is a **stake-backed content-compliance registry**: a submitter posts
literal text (URLs are judged as text; remote content is never fetched) together
with an explicit natural-language rule set and a bond; GenLayer validators
independently assess whether the content satisfies the rules; the contract
settles a normalized verdict (COMPLIANT → entry registered + bond kept,
NON_COMPLIANT → bond slashed and RESERVED against the appeal window before any
treasury withdrawal, INCONCLUSIVE → bond held/refundable), with an appeal path
that forces validator re-evaluation (same evidence, bounded count and window)
and a `cancel_pending` recovery path for submissions that never settle.

> 2026-10-11 revision (reviewer remediation): the original wording said
> "content (or a URL)" - no fetching has ever been implemented, so the product
> is now explicitly literal-text; and slashed bonds were withdrawable while
> still appealable, which the reservation model in `docs/remediation-plan.md`
> fixes.

## Why GenLayer is genuinely required

- A plain deterministic smart contract cannot interpret whether free-form content
  satisfies natural-language compliance rules.
- A single centralized AI check is opaque, censorable, and easily contested when
  it has a financial consequence (bond slashing) - the decision must be
  reproducible across independent validators and appealable.
- The compliance verdict directly drives an on-chain settlement (register / slash /
  refund), which is exactly the "AI-mediated judgment tied to a state transition"
  pattern the GenLayer `write-contract` skill prescribes.

## Approved scope

### In scope (v1)
- One substantive intelligent contract: `RuleRegistry`.
- Comparative, custom-validator consensus over rule compliance.
- Deterministic, isolated money logic (bond in/out as atto-scale `u256`).
- Next.js static frontend: wallet connect, submit content+rules+bond, view verdict,
  view registry, appeal; real deployed-contract interaction only (no mock data).
- Direct-mode tests + integration tests + linting.
- Deploy to the campaign's Studio-dev / "Studio Next" environment (chain id 61997),
  verified before and after deploy.
- GitHub repo (public), CI where feasible, docs.
- Two additional standalone intelligent contracts (Phase 10).

### Out of scope / deferred (unless approval requested)
- Any backend server (only added if a hard technical limitation forces it).
- Mainnet or non-dev networks (never - all chain ops stay on the authorized dev net).
- Irreversible campaign submissions without an explicit human approval gate (Phase 11).

## Consensus design boundary (per write-contract skill)

- **Frontend owns:** UI, wallet, submission form, non-authoritative preview, registry browsing.
- **Contract owns:** bond custody, the minimum state transition needing consensus
  (the compliance verdict), evidence inputs (content text/URL + rule list), the
  validator comparison rule, the settlement effect (register/slash/refund), appeal path.
- **External sources own:** raw content; treated as untrusted (prompt-injection hardened).

## Equivalence principle decision

- **Not** `strict_eq` (verdict comes from LLM/web judgment → non-deterministic).
- Use a **comparative custom validator** (`gl.vm.run_nondet_unsafe`): the validator
  independently re-runs the assessment and the contract compares the **normalized
  decision field** (`COMPLIANT`/`NON_COMPLIANT`/`INCONCLUSIVE`) plus derived per-rule
  statuses, with an explicit gate rule (e.g., any hard-violation → NON_COMPLIANT).
- Deterministic, machine-checkable rules are generated as code and evaluated in-sandbox
  (`spawn_sandbox` + `eval`) as ground truth (the skill's agentic pattern) to reduce
  hallucination; subjective rules fall back to LLM judgment with `response_format="json"`.
- Errors classified with `[EXPECTED]/[EXTERNAL]/[TRANSIENT]/[LLM_ERROR]`; validators never
  agree on LLM-malformed output (force rotation).

## Risks carried into Phase 3+

1. Interpretive rule ambiguity → mitigated by requiring explicit rule lists, INCONCLUSIVE
   state, and appeals.
2. Prompt injection in submitted content → mitigated by isolating content as data,
   structured prompts, and code-grounded checks.
3. studio-dev resets → mitigated by re-deployable scripts and frontend config injection.
