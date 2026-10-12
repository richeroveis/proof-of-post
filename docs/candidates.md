# Phase 2 - Five Candidate Projects (GenLayer Builder)

Each candidate is evaluated against the campaign's core test: **why is a plain
smart contract insufficient, AND why is a centralised AI service insufficient,
so that GenLayer validator consensus is genuinely required?**

Rubric weights (fixed, applied identically):
- GenLayer-native necessity 25%
- Real user value 20%
- Technical feasibility & reliability 15%
- Originality & differentiation 15%
- Security & testability 10%
- Product completeness & demo quality 10%
- Potential for legitimate continued use 5%

Scores are out of 10 per criterion; weighted total out of 10.

---

## Candidate 1 - **EvenHand** (evidence-adjudicated dispute escrow)

1. **Pitch:** Two parties lock a micro-escrow for a peer task ("I'll design your
   logo / translate this doc"); if they disagree on completion, validators read
   the submitted evidence and settle the payout.
2. **Users/problem:** Freelancers + small buyers who can't afford arbitration;
   today either trust, chargebacks, or platform fees.
3. **Journey:** create agreement (terms + milestone) → fund escrow → submit
   delivery evidence (URL/artifact hash) → counterparty accepts or disputes →
   on dispute, contract runs nondeterministic evaluation of evidence vs terms →
   weighted payout → appeal window → finalized.
4. **Plain contract insufficient:** completion is subjective; a deterministic
   contract cannot judge "did the work meet the terms."
5. **Central AI insufficient:** a single off-chain AI decision is un-auditable,
   censorable, and both sides must trust one operator; outcome moves money.
6. **GenLayer decides:** did delivery satisfy the agreed terms → release/split/refund.
7. **Evidence:** delivery artifact (URL/web content), the agreed terms text, optional
   third-party confirmations.
8. **Equivalence/consensus:** custom validator (`run_nondet_unsafe`) - validator
   independently re-fetches the same evidence and re-derives the decision; comparative
   agreement on the normalized decision field (`released`/`refunded`/`split_pct`) with
   tolerances. Optimistic Democracy with appeal rotation.
9. **On-chain:** escrow balances (atto `u256`), agreement state machine, evidence
   hashes/URLs, decision, appeal records.
10. **Architecture:** `AgreementFactory` + per-agreement `Agreement` contract
    (state: OPEN→FUNDED→DELIVERED→DISPUTED→RESOLVED→FINALIZED/APPEALED).
11. **FE/BE:** Next.js static frontend + JS SDK; wallet connect; no backend needed
    (reads via SDK, evidence fetched by validators on-chain).
12. **Security/abuse:** evidence is untrusted (prompt-injection hardening),
    escrow sizing limits, double-submit guards, appeal bond to deter spam.
13. **Alternatives/diff:** Kleros (heavy, token-court), fiverr (custodial). Diff:
    lightweight, gasless-network, Python-native, appealable adjudication.
14. **Plan:** factory+agreement contract → direct tests (state machine, escrow math)
    → integration tests (real evidence eval) → Next.js UI → deploy studio-dev → GH Pages.
15. **Testability:** excellent - deterministic escrow math testable in direct mode;
    adjudication via integration tests on stable fixtures.
16. **Repeatable activity:** every real dispute + regression scenario is a genuine tx.
17. **Review criteria:** strong necessity (money-moving judgment), full product, appeals.
18. **Risks/complexity:** evidence-quality edge cases; MEDIUM complexity. Well-trodden
    category → necessity obvious but originality lower.

---

## Candidate 2 - **ProofOfPost** (rule-compliant content registry)

1. **Pitch:** Creators stake to register content against a natural-language rule set
   (e.g. disclosure/compliance rules); validators check compliance and slash or reward.
2. **Users/problem:** regulated-content platforms (sponsored posts, financial
   disclosures) that need provable, neutral compliance checks, not platform caprice.
3. **Journey:** submit content + rules + bond → validators evaluate → pass (registry
   entry + bond kept) or fail (slash) → appeal → final.
4. **Plain contract insufficient:** compliance is interpretive.
5. **Central AI insufficient:** single operator can bias/censor; result has financial
   (slashing) effect and should be appealable/auditable.
6. **GenLayer decides:** satisfies/violates the stated rules.
7. **Evidence:** the content text/URL + rule list.
8. **Equivalence:** comparative custom validator; deterministic rule checks generated
   as code and evaluated in-sandbox (`spawn_sandbox` + `eval`), subjective ones by LLM,
   then validator re-derives same verdict.
9. **On-chain:** registry entries, bonds (`u256`), verdicts, appeal history.
10. **Architecture:** single `RuleRegistry` contract + content records.
11. **FE/BE:** Next.js static; no backend.
12. **Security:** prompt-injection, ambiguous rules, sybil via bond.
13. **Diff:** novel framing vs generic "AI moderation."
14. **Plan:** contract → direct/integration → UI → deploy.
15. **Testability:** GOOD - the agentic code-gen eval pattern is deterministic-ish;
    clear fixtures.
16. **Repeatable:** each registration/check is a tx.
17. **Review:** solid necessity + settlement; moderate originality.
18. **Risks:** rule ambiguity disputes; LOW-MEDIUM complexity.

---

## Candidate 3 - **OriginLedger** (AI-content provenance adjudication)

1. **Pitch:** Publish a claim about a work's origin ("human-made"/"AI-assisted with X")
   backed by evidence; validators assess authenticity into a public, appealable attestation.
2. **Users/problem:** trust collapse around AI-generated content; buyers/audiences need
   a neutral, verifiable provenance signal that isn't a platform badge.
3. **Journey:** submit artifact + provenance claim + evidence (metadata, drafts, source)
   → validators assess → attestation stored (authentic / synthetic / inconclusive + confidence)
   → appeal.
4. **Plain contract insufficient:** authenticity is inherently non-deterministic judgment.
5. **Central AI insufficient:** one company's detector is biased, opaque, and monetarily
   influential to creators; needs multi-model consensus + appeal.
6. **GenLayer decides:** normalized authenticity status + confidence bucket.
7. **Evidence:** artifact text/image URL, metadata, claimant-provided process proof.
8. **Equivalence:** **comparative** - validator independently re-runs assessment, compares
   decision field (status) and score bucket with tolerance; never leader-only format checks.
9. **On-chain:** attestation registry, status enum-as-str, confidence (scaled u256), appeals.
10. **Architecture:** `ProvenanceRegistry` (+ optional `Attestor` reputation view).
11. **FE/BE:** Next.js static explorer + submit + wallet; no backend.
12. **Security:** adversarial evidence, detector unreliability, defamation/label risk →
    status includes `inconclusive`, appeal path, disclaimers.
13. **Diff:** high - provenance-by-consensus is fresh; C2PA exists (deterministic signing)
    but doesn't judge AI-ness; our value is the adjudication + appeal, clearly separated.
14. **Plan:** registry contract → direct (state, schema) → integration (real assessment on
    fixed fixtures) → UI explorer → deploy.
15. **Testability:** MEDIUM - authenticity is the flakiest judgment; mitigated by fixed
    fixtures + `inconclusive` tolerance band; consensus may rotate more.
16. **Repeatable:** every attestation + appeal is a real tx; strong demo resonance.
17. **Review:** top-tier necessity & timeliness; slightly higher consensus risk.
18. **Risks:** detector reliability, subjective edge cases; MEDIUM-HIGH complexity.
    Highest originality + narrative impact; feasibility is the trade-off.

---

## Candidate 4 - **TrueResolution** (appealable prediction-market oracle)

1. **Pitch:** Binary/scalar markets resolve on real-world outcomes where validators
   fetch & normalize evidence, with an appeal window instead of a single oracle call.
2. **Users/problem:** prediction markets suffer oracle manipulation / UMA-style disputes.
3. **Journey:** create market (question, resolution evidence spec) → stakes → resolve
   window → validators decide outcome → payout → appeal.
4. **Plain contract insufficient:** outcome requires interpreting external reality.
5. **Central AI insufficient:** single oracle is a censorship/manipulation point for real money.
6. **GenLayer decides:** the market outcome (normalized enum/scalar).
7. **Evidence:** specified public sources (URLs) re-fetched by validators.
8. **Equivalence:** comparative; strict stable-field extraction where sources are
   deterministic, custom validator/tolerance where not; derived status for variable data.
9. **On-chain:** markets, pools (`u256` atto), outcomes, payouts, appeals.
10. **Architecture:** `MarketFactory` + `Market` + `USDC-like` token mock for pool math.
11. **FE/BE:** Next.js static; no backend.
12. **Security:** source manipulation, ambiguous questions, timing attacks.
13. **Diff:** category is crowded (UMA, Gnosis预测); appealable multi-model is the angle.
14. **Plan:** contracts → tests → UI → deploy.
15. **Testability:** GOOD - outcomes from fixed evidence testable in integration.
16. **Repeatable:** real markets + regression resolutions.
17. **Review:** necessity clear; originality lower due to many prior oracles.
18. **Risks:** market plumbing volume; MEDIUM complexity, lots of boilerplate money math.

---

## Candidate 5 - **MeritBounty** (rubric-scored open-bounty settlement)

1. **Pitch:** Anyone posts a bounty with a natural-language rubric and escrow;
   contributors submit work; validators score entries against the rubric and the
   contract allocates the escrow by normalized score, with appeals.
2. **Users/problem:** open bounties/grants need fair, neutral judging without a trusted
   central judge or a corruptible token vote.
3. **Journey:** fund bounty + rubric → submit entries → judging window opens → validators
   score each entry vs rubric → contract computes payout split from normalized scores →
   distribute → appeal wrong scoring.
4. **Plain contract insufficient:** "quality vs rubric" is subjective scoring.
5. **Central AI insufficient:** one judge can be bribed/biased; outcomes move escrow and
   must be reproducible + appealable.
6. **GenLayer decides:** normalized score per entry → drives settlement.
7. **Evidence:** entry artifact (URL/text) + rubric text.
8. **Equivalence:** **comparative** custom validator re-scores independently and compares
   the score bucket with tolerance; gate check (eligible/zero) must match; error classification
   for transient source failures.
9. **On-chain:** bounty state machine, escrow, entries, per-entry scores (scaled u256),
   payout allocation, appeals.
10. **Architecture:** `BountyFactory` + `Bounty` (OPEN→SUBMITTING→JUDGING→RESOLVED→APPEAL).
11. **FE/BE:** Next.js static (post, submit, view scores/payouts, appeal); no backend.
12. **Security:** rubric gaming, prompt-injection in submitted work, sybil submissions
    (submission fee / bond), collusive appeals (appeal bond).
13. **Diff:** high - most escrow projects do binary dispute; **rubric→multi-entry payout
    allocation by consensus score** is fresher and shows off comparative validation well.
14. **Plan:** contracts (deterministic payout math isolated from nondeterministic scoring)
    → direct tests (allocation math, state, access, bonds) → integration tests (real scoring
    on fixed fixtures) → Next.js UI → deploy studio-dev → GH Pages → 2 standalone contracts.
15. **Testability:** EXCELLENT - payout math is deterministic/unit-testable; scoring isolated
    behind one nondeterministic op with clear fixtures.
16. **Repeatable:** real bounties + bounded regression scenarios; genuine ecosystem utility.
17. **Review:** hits every criterion - necessity, settlement effect, appeals, completeness,
    demonstrable multi-party flows.
18. **Risks:** rubric ambiguity (mitigated by requiring explicit rubric + gate checks);
    MEDIUM complexity, but cleanly separable (deterministic vs nondeterministic).

---

## Weighted comparison

Weights: Nec .25 · Val .20 · Feas .15 · Orig .15 · Sec .10 · Demo .10 · Use .05

| # | Candidate | Nec | Val | Feas | Orig | Sec | Demo | Use | **Weighted** |
|---|-----------|----|----|----|----|----|----|----|----|
| 1 | EvenHand | 9 | 8 | 8 | 6 | 8 | 8 | 8 | **7.85** |
| 2 | ProofOfPost | 8 | 7 | 8 | 7 | 8 | 7 | 8 | **7.60** |
| 3 | OriginLedger | 9 | 8 | 6 | 9 | 7 | 9 | 8 | **8.00** |
| 4 | TrueResolution | 9 | 8 | 7 | 5 | 7 | 8 | 8 | **7.65** |
| 5 | **MeritBounty** | 9 | 9 | 9 | 8 | 9 | 9 | 9 | **8.85** |

### Recommendation

**MeritBounty** scores highest without manipulating the rubric. Why it wins:

- **Cleanest GenLayer necessity + settlement coupling:** the consensus output (a score)
  directly drives a deterministic payout allocation - the exact pattern the `write-contract`
  skill says to prefer (nondeterministic judgment tied to a real state transition/escrow).
- **Best feasibility/reliability balance:** the risky part (scoring) is isolated behind a
  single comparative nondeterministic op with fixed fixtures; the money math is
  deterministic and fully unit-testable in direct mode. This de-risks consensus vs the
  authenticity judgment in OriginLedger.
- **High originality:** rubric-scored multi-entry escrow allocation by consensus is fresher
  than the well-covered binary-dispute (EvenHand) and oracle-market (TrueResolution) spaces.
- **Strong, honest repeatable activity:** every bounty, submission, judging, and appeal is a
  genuine transaction; regression scenarios map to real product flows, not spam.
- **Demonstrable completeness:** multi-party journeys (poster / contributor / appellant) show
  well to reviewers and exercise the full tx lifecycle (pending/accepted/finalized/appeal).

**OriginLedger** is the runner-up - higher raw narrative impact and originality, but the
authenticity judgment is the least reliable for validator consensus, which risks demo
flakiness. If you prefer narrative boldness over reliability, pick it.

Runner-up ordering: MeritBounty (5) > OriginLedger (3) > EvenHand (1) > TrueResolution (4)
> ProofOfPost (2).
