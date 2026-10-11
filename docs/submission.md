# Submission Preparation — GenLayer Builder Campaign (Phase 11)

Prepared: 2026-10-10, revised 2026-10-11 after the reviewer remediation
(zoefunds): the live contract was replaced by a financially safer instance;
see `docs/remediation-plan.md` and `docs/onchain-activity.md`. Everything here
is **verified against the local repo, the live studio-dev chain, and the
official docs**. Fields that could **not** be independently confirmed are
flagged. **No campaign points, addresses, tx hashes, or test results below are
fabricated** — each is a real artifact of this build.

## Rules re-verification status (important)

- The GenLayer Portal (`https://portal.genlayer.foundation/how-it-works`) is the
  live hub: "Deploy Intelligent Contracts, ship projects, and earn Builder
  Points for every accepted contribution." Confirmed via web search 2026-10-10.
- The **exact point ranges** (Projects 20–4,000; standalone Contracts 0–500) come
  from the interface the campaign brief supplied and remain **not scrapable**
  (the portal is a JS-rendered SPA; `/submit`, `/projects` routes 404 to the
  client). They must be confirmed **in-browser by a human at submission time**.
- The DoraHacks "Testnet Bradbury" event page (re-surfaced 2026-10-10) still
  states each contract must use **Optimistic Democracy consensus** and an
  **Equivalence Principle** — both satisfied by every contract here. This is an
  event-scoped proxy, not necessarily the standing rubric.
- **Submission is an irreversible action and is NOT performed here.** This
  document is submission-ready content for a human to review and submit; the
  actual portal submission requires explicit human approval.

---

## A. Project — ProofOfPost (RuleRegistry)

**Title:** ProofOfPost — on-chain content-rule adjudication with GenLayer

**Description:** A public registry where posts of literal text are submitted
against a natural-language rule set and a validator ensemble independently
re-derives whether each post satisfies the rules, settling a reproducible,
appealable verdict that gates a bonded payout — slashed collateral stays
reserved against the appeal window until the liability is finalized (swept in a
completed withdrawal after the minimum window, or appeal budget exhausted).

**Problem & target users:** Creators, communities, and bounty platforms need
content to be checked against subjective written rules (format, required
elements, prohibited claims) by a decision that is neither a rubber-stamp nor a
single trusted referee's opinion. GenLayer provides multi-validator,
independently-reproduced adjudication with escrow and appeal.

**GenLayer's role:** the verdict is subjective natural-language inference that
cannot be reduced to a deterministic call; every validator re-derives it and must
agree on the settled decision, with error classification and a comparative
validator for consensus on failure paths.

**Repository:** https://github.com/richeroveis/proof-of-post
**Live demo:** https://richeroveis.github.io/proof-of-post (GitHub Pages,
browser-verified reads against the deployed contract)
**Deployed contract (studio-dev, chainId 61997):**
`0x405e957542856E5f6830EDD40757480BDA8ab594` (remediated instance; supersedes
`0x61eE31810F804E53b4Eb4A3c876F0504A1fC304b`)
**Network:** GenLayer Studio Devnet — RPC `https://studio-dev.genlayer.com/api` (non-gasless; fee ~0.00008 GEN per settled tx after refund)

**Setup & test instructions:** see repo `README` / `docs/testing.md` —
`genvm-lint check contracts/rule_registry.py`; `pytest tests/direct -q`
(41 direct tests); guarded integration suite via `gltest`; full live
regression `node e2e/studio_devnet_e2e.mjs`.
**Architecture docs:** `docs/research.md`, `docs/project-decision.md`,
`docs/deployment.md`, `docs/onchain-activity.md`,
`docs/remediation-plan.md`.
**Evidence of real functionality:** live reads verified in-browser on the Pages
demo; the 2026-10-11 remediation regression settled real verdicts, rejected a
premature treasury withdrawal on-chain, refunded a cancelled bond, and moved
1 GEN of finalized slashed collateral to the configured treasury (hashes in
`docs/onchain-activity.md`).

---

## B. Standalone Intelligent Contract — EvidenceOracle

**Title:** EvidenceOracle — bonded, appealable attestations about public web pages

**Purpose:** turn "this public page says X" into a validator-verified,
bond-backed on-chain fact that other contracts/frontends can consume.

**Problem it solves:** off-chain evidence must gate on-chain value (markets,
disputes, compliance), but deterministic contracts can't read pages and a single
LLM answer isn't trustable or disputable.

**Why GenLayer consensus is useful:** every validator independently re-fetches
the URL and re-derives the verdict; the settled result is reproducible and
appealable.

**Validation strategy:** comparative custom validator (`gl.vm.run_nondet`) —
agree on verdict **exactly** and on any extracted scalar within a **1% integer
tolerance**; wording is not compared. Classified `[EXPECTED]/[EXTERNAL]/
[TRANSIENT]/[LLM_ERROR]` errors.

**Source location:** `standalone/evidence-oracle/` in
https://github.com/richeroveis/proof-of-post (independently reviewable; no shared
code with the main project).
**Deployed (studio-dev):** `0xc315465D70D377CDB078aB0117C011d46A288E1F`
(deploy tx `0x5d99874cc6448fbac42c89ba4b4beb1d1be533e9a2e029e4248b4736367eb9c6`, FINALIZED).
**Tests:** 30 direct tests (mocked web/LLM, `pytest standalone/evidence-oracle/tests/direct`); guarded integration suite.
**Examples & deploy:** `standalone/evidence-oracle/README.md`.
**Known limitations:** attests to page content at fetch time; mutable pages can
change (bounded challenges mitigate); value-tolerance applies only when the cited
number appears on the page.

---

## C. Standalone Intelligent Contract — ScoreRegistry

**Title:** ScoreRegistry — consensus rubric scoring with a reproducible pass/fail gate

**Purpose:** score free-form work against a natural-language rubric and publish a
defensible 0–100 score + `PASSED`/`FAILED` gate that gates bonded value.

**Problem it solves:** grants/bounties/moderation need subjective work scored
without one trusted scorer picking the number that releases value; raw LLM
scoring is unreproducible and hallucinable even on checkable criteria.

**Why GenLayer consensus is useful:** validators independently reproduce the
whole generate→evaluate→score procedure and must agree on the settlement gate.

**Validation strategy (hybrid):** comparative custom validator with **two**
agreements — deterministic sub-checks by **strict equality**, the subjective
score within a **tolerance band** (`SCORE_TOLERANCE=10`), and the pass/fail gate
by **exact** match. LLM-generated rubric checks run in a restricted interpreter
so their outcome cannot be hallucinated.

**Source location:** `standalone/score-registry/` in
https://github.com/richeroveis/proof-of-post (independently reviewable; distinct
domain and equivalence strategy from the main project).
**Deployed (studio-dev):** `0x2579a22a567a6A9D424Fa6225c201aD359bd8d66`
(deploy tx `0x6f695e46ed3a8bbc86a67e0222e434d9407b1174f696ae72f80d5feef5ebae71`, FINALIZED).
**Tests:** 24 direct tests (`pytest standalone/score-registry/tests/direct`);
guarded integration suite.
**Examples & deploy:** `standalone/score-registry/README.md`.
**Known limitations:** score is subjective (tolerance band accepts reasonable
disagreement but pins the gate); non-programmatic rubric lines are left to model
judgment by design.

---

## Verification summary (all real)

| Item | Value | Status |
|---|---|---|
| Repo | github.com/richeroveis/proof-of-post | pushed (`main`) |
| Project demo | richeroveis.github.io/proof-of-post | live, browser-verified |
| RuleRegistry (remediated) | 0x405e957542856E5f6830EDD40757480BDA8ab594 | live on studio-dev, full E2E regression |
| RuleRegistry (superseded) | 0x61eE31810F804E53b4Eb4A3c876F0504A1fC304b | pre-remediation instance |
| EvidenceOracle | 0xc315465D70D377CDB078aB0117C011d46A288E1F | FINALIZED, get_stats/get_min_bond read OK |
| ScoreRegistry | 0x2579a22a567a6A9D424Fa6225c201aD359bd8d66 | FINALIZED, get_stats/list_items read OK |
| Direct tests | 41 (main) + 54 (standalone) | all pass |
| Lint | both standalone + main | genvm-lint check PASS |

## Outstanding before submission

1. Human in-browser confirmation of the live Builder point ranges / field schema
   (portal is a JS SPA — not scrapable from the agent).
2. Human approval to perform the **irreversible** portal submission (not done here).
3. **Reviewer sign-off on the F7 appeal-semantics change**: appealability is no
   longer time-boxed by the lifecycle tick — it continues past the nominal
   sweep-eligibility window until the liability is finalized by a completed
   paying treasury withdrawal or the two-appeal budget (verified locally only;
   the deployed `0x405e…b594` still runs the counter-gated appeal until
   redeployed). See `docs/remediation-plan.md` F7.
