# Remediation Plan - Reviewer "zoefunds" findings (2026-10)

Each finding is mapped to its root cause in the current accounting model, the
fix, and the regression test that pins it. Baseline model (pre-fix):

```
submit      : bond -> contract, status PENDING
evaluate    : COMPLIANT/INCONCLUSIVE -> refund; NON_COMPLIANT -> slashed_total += bond
appeal      : re-assess; overturn -> slashed_total -= bond + refund (bounded by MAX_APPEALS=2)
withdraw    : owner may pull up to slashed_total - withdrawn_slashed, to ANY address
```

## Runtime constraint that shapes the design (verified, not assumed)

The pinned GenVM runner (`py-genlayer:1jb45aa8…`, std lib v0.2.16 - the only
runner the fleet executes and the public toolchain can load, deployment.md
finding 4) exposes **no timestamp or block-height API**: `gl.message` carries
only `contract_address/sender_address/origin_address/value/chain_id`, and the
WASI surface is limited to `get_balance`/`get_self_balance`/`gl_call`
(verified against the cached std lib in `~/.cache/gltest-direct`). A wall-clock
timeout is therefore impossible on this runtime.

**Chosen time model:** the contract's own lifecycle clock - a monotonic `tick`
u256 incremented by every finalized write. Windows are measured in finalized
state transitions of this contract, which is the only deterministic "time" the
runtime provides. Rationale and consequences are documented in
`docs/deployment.md` (finding 8) and the contract header.

## Findings

| # | Reviewer finding | Root cause | Fix | Regression tests |
|---|---|---|---|---|
| F1 | Slashed collateral can be treasury-withdrawn **while the verdict is still appealable**; a later winning appeal would refund money that already left (or double-spend the same slashed balance) | `slashed_total` conflated "reserved against appeal liability" with "finalized"; `withdraw_slashed` cap ignored appealability; appeal reversal had no reservation to release | New fields `reserved_slashed` + per-entry `appeal_deadline` (= settle tick + `APPEAL_WINDOW_TICKS`). Slash -> reserved. Winning appeal -> un-reserve + un-slash + refund. Liability ends on: reversal, `appeal_count` reaching `MAX_APPEALS` while upheld, or window expiry swept **inside the withdraw write itself**. Withdraw cap = `slashed_total - withdrawn_slashed - reserved_slashed`, checked after the sweep. Premature withdraw -> `[EXPECTED] Slashed collateral reserved for appeal window` | attack-exact test + winning/losing appeal, expiry, multi-entry, repeated-withdraw tests |
| F2 | A submission whose assessment never completes is **PENDING forever**, locking the bond | no cancellation path; no clock to expire | `cancel_pending(entry_id)`: submitter-or-owner, only while `PENDING`; refunds the bond, sets terminal `CANCELLED`. Late `evaluate`/`appeal` hit the existing status gates and revert deterministically - a concurrently in-flight evaluate finalizes either before (cancel reverts) or after (evaluate reverts), so no double refund is possible | early-cancel-after-terminal, recovery, repeated cancel, late-evaluate-after-cancel tests |
| F3 | Rule sets are **silently truncated** (`rules[:MAX_RULES]`, `text[:MAX_RULE_LEN]`, `title[:MAX_TITLE_LEN]`), so validators can judge different rules than the submitter intended | truncation in `_parse_rules` and `submit` | Reject with `[EXPECTED]` errors: too many rules, over-long rule, over-long title; drop the truncations; the stored rules are exactly the evaluated rules; frontend enforces the same bounds client-side | boundary tests at exactly-max, max+1, empty, whitespace-only, duplicate/contradictory rules |
| F4 | README/decision docs promise content "**or a URL**" but nothing is ever fetched - only the literal text is judged | wording implied URL fetching | Restrict the product to literal text (the safe, fully-testable option): docstring, README, project-decision, submission, frontend copy all state URLs are judged **as text, not fetched**. No fetching added (would change the consensus surface without reviewer necessity) | docs only; prompt already treats content as untrusted data |
| F5 | `withdraw_slashed(to, amount)` lets the **owner route funds to any address**; the configured `treasury` is dead state | `to` parameter + unused `self.treasury` | Signature becomes `withdraw_slashed(amount)`; payout destination is **always `self.treasury`** (retargetable only via `set_treasury`); owner-only authorization unchanged; accounting updates before the external transfer | unauthorized-caller, treasury-destination, zero/over-cap/repeated withdrawal tests |
| F6 | Appeal semantics unclear - re-runs the *same* assessment, accepts **no new evidence** | undocumented | Contract header + README + UI note state: appeal = bounded re-adjudication of identical inputs (max 2; available while the collateral is reserved); no evidence submission | invalid-target, non-submitter, limit, finalized-liability refusal tests |
| F7 | *(follow-up security audit)* The tick-based appeal window could be **burned by third-party write spam**: four permitted, self-canceling state transitions (submit+cancel cycles, refundable bonds) expire an open window and silently deny a legitimate appeal while the bond was still reserved | `appeal()` gated the right on `tick < appeal_deadline`, but `tick` counts *any* finalized write - a shared, attacker-advanceable counter; no wall-clock/block API exists in the pinned runner to do otherwise | Reservation-gated appeal: the right now ends only when the liability is **truly irreversible** - appeal-count exhaustion, or a sweep that ran inside a completed, paying withdrawal (`withdraw_slashed` is the sole executor and is owner-gated). While `appeal_deadline > 0` the bond is reserved and a reversal fundable, so appeal stays available. The tick window keeps its (unchanged) role as the *minimum* reservation period protecting against an eager treasury. Residual: a colluding owner + spammer can still finalize a reservation before the submitter appeals - a privileged, visible economic act, not free third-party griefing; inherent to a clockless runtime | `test_spam_cannot_deny_legitimate_appeal` (reproduced as denial pre-fix, then flipped) + `test_appeal_refused_after_withdraw_sweeps_reservation` (double-pay safety) |
| G1 | *(resubmission rejection 2026-10-13)* No successful on-chain verdict-reversing appeal with an actual refund had ever been demonstrated | an appeal re-ran the byte-identical "strict compliance adjudicator" prompt, so consensus simply re-derived its first decision; a reversal was theoretically possible but had never been reached on any live candidate | Smallest principled change: `appeal()` now re-adjudicates the SAME stored content and rules under an explicit **appeal reconsideration frame** in the prompt - violations require a clear breach, genuine ambiguity resolves in favor of the submitter (penalty-under-doubt tie-break). No new evidence, same consensus path, same guards; the frame is deterministic prompt text every validator builds identically. Candidates for the live proof are genuinely ambiguous (hyphenated word counts, mixed tone, sentence segmentation, word-form mentions) - reversals must be earned by the ensemble, never forced | Live driver `e2e/appeal_refund_e2e.mjs` exercises the full lifecycle with before/after on-chain state, balance deltas and an independently verifiable evidence file (`e2e/evidence-appeal-refund.json`, checked by `frontend/verify_evidence.mjs`). **Status 2026-10-16: G1 CLOSED.** After a studio-dev storage outage blocked earlier attempts, `gen_call` recovered and the driver deployed the committed source (sha256 `92e94de8…`) at `0xC0d33d779d12Ae43f0Fe890fc13906631B7a377b` and earned a real reversal: entry 1 ("Mixed-tone edge") settled NON_COMPLIANT (`0x9166f438…405a232`) and the submitter's appeal reversed it to COMPLIANT (`0x5476309b…ae727b29`), releasing the reservation, un-slashing and refunding the 0.1 GEN bond (submitter +99872399999999177 wei net of fee), with `slashed_total`/`reserved_slashed` back to 0 and `verified` 1 to 2. `node frontend/verify_evidence.mjs e2e/evidence-appeal-refund.json` returns exit 0 with the live readback `status=COMPLIANT appeals=1 deadline=0 slashed=0 reserved=0 withdrawn=0 verified=2`. Full table and before/after ledger in `docs/onchain-activity.md`. The flip was earned on a genuinely ambiguous candidate, not forced (no backdoor, no owner override). |
| G2 | *(resubmission rejection 2026-10-13)* The suite did not directly test a second withdrawal after a successful withdrawal | coverage gap: over-cap reverts were tested against un-withdrawn collateral, never against a state where a first withdrawal had actually paid out | Dedicated regression performs the legitimate exhaustion flow, funds the native balance so the first withdrawal genuinely pays, then re-attempts the exact same withdrawal and pins the revert plus the unchanged monetary ledger. Widened to cover every second-withdrawal shape: partial-then-remaining-then-over-cap, the native-balance ceiling, and no re-sweep or double count of an entry the first withdrawal already finalized | `test_second_withdrawal_after_successful_withdrawal_reverts_without_double_payout` + `test_second_withdrawal_of_remaining_available_succeeds_and_third_reverts` + `test_withdraw_is_capped_by_native_balance_then_by_availability` + `test_second_withdrawal_does_not_ressweep_or_double_count_a_finalized_entry` |

## Financial invariants (asserted after every relevant transition in tests)

```
I1  slashed_total  >=  withdrawn_slashed + reserved_slashed
I2  reserved_slashed == sum of bond over entries with appeal_deadline > 0
I3  bonded_pending == sum of bond over PENDING entries
I4  available_for_withdraw == slashed_total - withdrawn_slashed - reserved_slashed
I5  each entry's bond leaves the contract exactly once:
    refund (COMPLIANT/INCONCLUSIVE/cancel/appeal-overturn) XOR slash (NON_COMPLIANT)
I6  contract_balance >= bonded_pending + reserved_slashed + available_for_withdraw
    (on-chain only; direct mode does not model native transfers - see testing.md)
```

## Files touched

- `contracts/rule_registry.py` - F1, F2, F3, F5 (+ views: `tick`, `bonded_pending`,
  `reserved_slashed`, `available_slashed`, per-entry `appeal_deadline`)
- `tests/direct/test_rule_registry.py` - update changed signatures, add ~18 regression tests
- `tests/integration/test_rule_registry_integration.py` - 0-based entry ids fix, CANCELLED path
- `frontend/lib/contract.ts`, `frontend/app/page.tsx`, `frontend/app/globals.css` - new stats fields, Cancel write, client-side rule bounds, appeal-window copy, literal-text labels
- `.github/workflows/deploy-pages.yml` - contract address after verified redeploy
- `README.md`, `docs/{project-decision,deployment,onchain-activity,submission,testing}.md` - semantics, findings, live evidence

## Verification results (2026-10-11)

- **Static:** `genvm-lint check contracts/rule_registry.py` → PASS (10 methods,
  4 view / 6 write; pinned runner unchanged).
- **Direct tests:** `pytest tests/direct -q` → **36 passed** (was 22; no
  existing assertion weakened - the two withdrawal tests were reworked only for
  the new signature/finalization flow). Standalone suites untouched: 54 passed.
- **Frontend:** `npm run build` (static export) passes with the new types,
  Cancel write, client-side rule bounds, and literal-text copy.
- **Studio Devnet E2E** on `0x405e957542856E5f6830EDD40757480BDA8ab594`: 17
  real fee-aware transactions, all FINALIZED - premature withdrawal rejected
  with the explicit reservation error, two upheld appeals finalized the
  liability, 1 GEN withdrawn to the CONFIGURED treasury, cancel refunded live,
  late evaluate and oversized-rule submit rejected with `[EXPECTED]` errors,
  conservation invariants verified. Full table: `docs/onchain-activity.md`.
- **Not achieved live:** a verdict-reversing appeal (two honest attempts, the
  ensemble did not flip either); covered deterministically by the direct
  attack/regression tests as documented.

### F7 follow-up audit (tick-window hardening, same day)

- Reproduced the third-party spam denial deterministically against the
  committed pre-fix contract (`test_repro_third_party_write_spam_denies_legitimate_appeal`,
  1 passed pre-fix), implemented the reservation-gated appeal, and re-ran:
  `pytest tests/direct -q` → **38 passed**, full suite **92 passed**,
  `genvm-lint` PASS. All F1-F6 tests kept intact; the withdrawal-side gates
  were not touched.
- **Second-pass adversarial review** found no accounting defect (invariants
  `deadline > 0 ⟺ bond reserved` and `withdrawn ≤ slashed − reserved` hold on
  every mutation path enumerated) but flagged three unpinned post-mitigation
  paths and two UI copy issues. Now closed locally:
  `test_post_deadline_upheld_appeals_exhaust_and_release_once`,
  `test_post_deadline_appeal_inconclusive_refunds_without_verify`,
  `test_mixed_window_sweep_finalizes_only_elapsed_reservations` (uses
  `direct_vm.deal` for genuinely paying withdrawals - no balance-guard trick),
  plus corrected the frontend banner copy and gated the row-level Appeal
  button on `appeal_deadline > 0`. Suite: **41 passed** (main), **95 passed**
  overall.
- **PROTOCOL-SEMANTIC CHANGE - requires reviewer sign-off, not just bug-fix
  acceptance.** The reviewer's original ask implied a time-bounded appeal
  window. The clockless runtime cannot offer one that survives write spam, so
  appealability is now **state-bounded**: the nominal tick window only sets
  when a treasury withdrawal may first sweep a reservation; the appeal right
  itself continues past that tick until the liability is actually finalized
  (completed paying withdrawal, or the two-appeal budget). Trade-off accepted:
  third-party denial is eliminated; owner-side denial remains possible as a
  single privileged, economically-committing, fully visible on-chain act -
  inherent to any clockless design, not removable without giving the owner an
  even cheaper finalization path.
- **Resubmission audit (2026-10-11, this pass):** a fresh full review of the
  remediated contract confirmed the F1-F7 accounting is sound (all I1-I6
  invariants hold on every mutation path traced). Two additions from that audit:
  (1) a `withdraw_slashed` hardening - the raw signed int is validated for
  `<= 0` BEFORE the unsigned `u256` cast, so a negative amount reverts with a
  clean `[EXPECTED]` error instead of an opaque cast failure; (2) three new
  adversarial direct tests - `test_withdraw_negative_amount_rejected_cleanly`,
  `test_bond_above_minimum_is_slashed_reserved_and_withdrawn_exactly`,
  `test_withdraw_sweep_finalizes_all_elapsed_reservations`. Direct suite now
  **44 passed** (main), **98 passed / 12 skipped** overall (the 12 are guarded
  live-integration tests, never counted as passing); `genvm-lint` PASS; frontend
  production build PASS; `git diff --check` clean.
- **Deployed and live-verified (previously local-only):** the reservation-gated
  F7 code + the withdraw guard were redeployed to a NEW studio-dev instance
  `0x30A9A1D88E8885319a9f5F259D5C416Bd55d149E` (deploy tx
  `0xfcdf651213c1414bad107cf869477976938e0910227867034b1dfc5aaaf660b6`, FINALIZED,
  5-validator MAJORITY_AGREE). The e2e now proves F7 **on-chain**: burning the
  nominal window with self-canceling submit+cancel cycles advanced the tick past
  `appeal_deadline` yet left the bond reserved, and the submitter's subsequent
  appeal still FINALIZED and incremented `appeal_count` (the pre-F7 counter-gate
  reverted this exact call). Premature-withdrawal rejection, treasury-only routing
  (treasury 0 → 1 GEN via external message), cancel recovery, oversized-rule
  rejection and I1/I4/I6 conservation were all observed live - full table in
  `docs/onchain-activity.md`. `0x405e…b594` is retained as the historical
  pre-F7 deployment; `0x61eE…304b` as pre-remediation.
- **Reviewer sign-off still required (not claimed accepted):** the F7
  appeal-semantics change (appeal gated on the reservation, not the lifecycle
  tick) is now deployed and verified, but it remains a protocol-semantic decision
  for the reviewer to explicitly accept. What was NOT shown live: a
  verdict-reversing appeal with on-chain refund - the shared ensemble did not
  flip any of the three appealable entries in this run and consensus cannot be
  forced without fabrication; that path is proven deterministic in direct tests.

## Resubmission gap-closure pass (2026-10-13, this session)

Reviewer finding: the committed studio-dev results still did not show a
verdict-reversing appeal with a successful on-chain refund (G1), and the suite
still did not directly cover a second withdrawal after a successful one (G2).

- **G2 closed and widened.** Three additional direct tests were added alongside
  the existing dedicated one, covering the partial-then-remaining-then-over-cap
  sequence, the native-balance ceiling as a separate guard, and the no-re-sweep /
  no-double-count behavior for an entry a prior withdrawal already finalized, each
  asserting the full I1-I4 ledger invariants after every step and that the
  treasury-receipt ledger equals exactly the sum of the payouts. None exposed a
  contract defect, so no source change was required; the accounting held.
- **Verification this pass.** `genvm-lint check` PASS on all three contracts
  (RuleRegistry 10 methods, 4 view / 6 write; both standalone 10 methods, 5 / 5).
  `pytest tests/direct` **48 passed** (was 45); standalone direct suites
  **54 passed**; combined direct total **102 passed**, 0 failed. `git diff --check`
  clean. The guarded live-integration tests remain skipped by default and are
  never counted as passing.
- **G1 CLOSED (2026-10-16).** Studio-dev `gen_call` recovered (5/5 probe reads OK).
  The driver was scaled to a 0.1 GEN bond (studio-dev is not gasless and the owner
  development wallet holds a small balance; the reversal path under test is
  amount-independent) and its `save()` BigInt-serialization crash was fixed. A
  fresh deploy of the committed source (`92e94de8…`) at
  `0xC0d33d779d12Ae43f0Fe890fc13906631B7a377b` earned a genuine on-chain
  reversal: entry 1 ("Mixed-tone edge") NON_COMPLIANT
  (`0x9166f438…405a232`) then reversed to COMPLIANT on appeal
  (`0x5476309b…ae727b29`), reservation released, bond un-slashed and refunded
  (submitter +0.09987 GEN after the fee), `verified` 1 to 2. Independently
  verified via `frontend/verify_evidence.mjs` (exit 0). Evidence:
  `e2e/evidence-appeal-refund.json`. The earlier outage log is retained in
  `docs/onchain-activity.md` as history. No result was fabricated.
