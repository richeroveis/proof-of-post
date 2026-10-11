# Remediation Plan — Reviewer "zoefunds" findings (2026-10)

Each finding is mapped to its root cause in the current accounting model, the
fix, and the regression test that pins it. Baseline model (pre-fix):

```
submit      : bond -> contract, status PENDING
evaluate    : COMPLIANT/INCONCLUSIVE -> refund; NON_COMPLIANT -> slashed_total += bond
appeal      : re-assess; overturn -> slashed_total -= bond + refund (bounded by MAX_APPEALS=2)
withdraw    : owner may pull up to slashed_total - withdrawn_slashed, to ANY address
```

## Runtime constraint that shapes the design (verified, not assumed)

The pinned GenVM runner (`py-genlayer:1jb45aa8…`, std lib v0.2.16 — the only
runner the fleet executes and the public toolchain can load, deployment.md
finding 4) exposes **no timestamp or block-height API**: `gl.message` carries
only `contract_address/sender_address/origin_address/value/chain_id`, and the
WASI surface is limited to `get_balance`/`get_self_balance`/`gl_call`
(verified against the cached std lib in `~/.cache/gltest-direct`). A wall-clock
timeout is therefore impossible on this runtime.

**Chosen time model:** the contract's own lifecycle clock — a monotonic `tick`
u256 incremented by every finalized write. Windows are measured in finalized
state transitions of this contract, which is the only deterministic "time" the
runtime provides. Rationale and consequences are documented in
`docs/deployment.md` (finding 8) and the contract header.

## Findings

| # | Reviewer finding | Root cause | Fix | Regression tests |
|---|---|---|---|---|
| F1 | Slashed collateral can be treasury-withdrawn **while the verdict is still appealable**; a later winning appeal would refund money that already left (or double-spend the same slashed balance) | `slashed_total` conflated "reserved against appeal liability" with "finalized"; `withdraw_slashed` cap ignored appealability; appeal reversal had no reservation to release | New fields `reserved_slashed` + per-entry `appeal_deadline` (= settle tick + `APPEAL_WINDOW_TICKS`). Slash -> reserved. Winning appeal -> un-reserve + un-slash + refund. Liability ends on: reversal, `appeal_count` reaching `MAX_APPEALS` while upheld, or window expiry swept **inside the withdraw write itself**. Withdraw cap = `slashed_total - withdrawn_slashed - reserved_slashed`, checked after the sweep. Premature withdraw -> `[EXPECTED] Slashed collateral reserved for appeal window` | attack-exact test + winning/losing appeal, expiry, multi-entry, repeated-withdraw tests |
| F2 | A submission whose assessment never completes is **PENDING forever**, locking the bond | no cancellation path; no clock to expire | `cancel_pending(entry_id)`: submitter-or-owner, only while `PENDING`; refunds the bond, sets terminal `CANCELLED`. Late `evaluate`/`appeal` hit the existing status gates and revert deterministically — a concurrently in-flight evaluate finalizes either before (cancel reverts) or after (evaluate reverts), so no double refund is possible | early-cancel-after-terminal, recovery, repeated cancel, late-evaluate-after-cancel tests |
| F3 | Rule sets are **silently truncated** (`rules[:MAX_RULES]`, `text[:MAX_RULE_LEN]`, `title[:MAX_TITLE_LEN]`), so validators can judge different rules than the submitter intended | truncation in `_parse_rules` and `submit` | Reject with `[EXPECTED]` errors: too many rules, over-long rule, over-long title; drop the truncations; the stored rules are exactly the evaluated rules; frontend enforces the same bounds client-side | boundary tests at exactly-max, max+1, empty, whitespace-only, duplicate/contradictory rules |
| F4 | README/decision docs promise content "**or a URL**" but nothing is ever fetched — only the literal text is judged | wording implied URL fetching | Restrict the product to literal text (the safe, fully-testable option): docstring, README, project-decision, submission, frontend copy all state URLs are judged **as text, not fetched**. No fetching added (would change the consensus surface without reviewer necessity) | docs only; prompt already treats content as untrusted data |
| F5 | `withdraw_slashed(to, amount)` lets the **owner route funds to any address**; the configured `treasury` is dead state | `to` parameter + unused `self.treasury` | Signature becomes `withdraw_slashed(amount)`; payout destination is **always `self.treasury`** (retargetable only via `set_treasury`); owner-only authorization unchanged; accounting updates before the external transfer | unauthorized-caller, treasury-destination, zero/over-cap/repeated withdrawal tests |
| F6 | Appeal semantics unclear — re-runs the *same* assessment, accepts **no new evidence** | undocumented | Contract header + README + UI note state: appeal = bounded re-adjudication of identical inputs (max 2; available while the collateral is reserved); no evidence submission | invalid-target, non-submitter, limit, finalized-liability refusal tests |
| F7 | *(follow-up security audit)* The tick-based appeal window could be **burned by third-party write spam**: four permitted, self-canceling state transitions (submit+cancel cycles, refundable bonds) expire an open window and silently deny a legitimate appeal while the bond was still reserved | `appeal()` gated the right on `tick < appeal_deadline`, but `tick` counts *any* finalized write — a shared, attacker-advanceable counter; no wall-clock/block API exists in the pinned runner to do otherwise | Reservation-gated appeal: the right now ends only when the liability is **truly irreversible** — appeal-count exhaustion, or a sweep that ran inside a completed, paying withdrawal (`withdraw_slashed` is the sole executor and is owner-gated). While `appeal_deadline > 0` the bond is reserved and a reversal fundable, so appeal stays available. The tick window keeps its (unchanged) role as the *minimum* reservation period protecting against an eager treasury. Residual: a colluding owner + spammer can still finalize a reservation before the submitter appeals — a privileged, visible economic act, not free third-party griefing; inherent to a clockless runtime | `test_spam_cannot_deny_legitimate_appeal` (reproduced as denial pre-fix, then flipped) + `test_appeal_refused_after_withdraw_sweeps_reservation` (double-pay safety) |

## Financial invariants (asserted after every relevant transition in tests)

```
I1  slashed_total  >=  withdrawn_slashed + reserved_slashed
I2  reserved_slashed == sum of bond over entries with appeal_deadline > 0
I3  bonded_pending == sum of bond over PENDING entries
I4  available_for_withdraw == slashed_total - withdrawn_slashed - reserved_slashed
I5  each entry's bond leaves the contract exactly once:
    refund (COMPLIANT/INCONCLUSIVE/cancel/appeal-overturn) XOR slash (NON_COMPLIANT)
I6  contract_balance >= bonded_pending + reserved_slashed + available_for_withdraw
    (on-chain only; direct mode does not model native transfers — see testing.md)
```

## Files touched

- `contracts/rule_registry.py` — F1, F2, F3, F5 (+ views: `tick`, `bonded_pending`,
  `reserved_slashed`, `available_slashed`, per-entry `appeal_deadline`)
- `tests/direct/test_rule_registry.py` — update changed signatures, add ~18 regression tests
- `tests/integration/test_rule_registry_integration.py` — 0-based entry ids fix, CANCELLED path
- `frontend/lib/contract.ts`, `frontend/app/page.tsx`, `frontend/app/globals.css` — new stats fields, Cancel write, client-side rule bounds, appeal-window copy, literal-text labels
- `.github/workflows/deploy-pages.yml` — contract address after verified redeploy
- `README.md`, `docs/{project-decision,deployment,onchain-activity,submission,testing}.md` — semantics, findings, live evidence

## Verification results (2026-10-11)

- **Static:** `genvm-lint check contracts/rule_registry.py` → PASS (10 methods,
  4 view / 6 write; pinned runner unchanged).
- **Direct tests:** `pytest tests/direct -q` → **36 passed** (was 22; no
  existing assertion weakened — the two withdrawal tests were reworked only for
  the new signature/finalization flow). Standalone suites untouched: 54 passed.
- **Frontend:** `npm run build` (static export) passes with the new types,
  Cancel write, client-side rule bounds, and literal-text copy.
- **Studio Devnet E2E** on `0x405e957542856E5f6830EDD40757480BDA8ab594`: 17
  real fee-aware transactions, all FINALIZED — premature withdrawal rejected
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
  `genvm-lint` PASS. All F1–F6 tests kept intact; the withdrawal-side gates
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
- **PROTOCOL-SEMANTIC CHANGE — requires reviewer sign-off, not just bug-fix
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
- **Local-only:** the fix is NOT yet on Studio Devnet — the live
  `0x405e…b594` instance runs the counter-gated appeal until the next
  deployment (no deployment performed during this audit; storage layout is
  unchanged so a redeploy carries no migration risk, but the old instance's
  behavior remains as documented above).
