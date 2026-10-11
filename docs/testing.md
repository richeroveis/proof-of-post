# Testing Report — ProofOfPost (RuleRegistry)

Three-layer validation, per the campaign's security/testability criteria.

## 1. Static validation — `genvm-lint`

```
genvm-lint check contracts/rule_registry.py
```

Result: **PASS**. `validate: ok=true`. Contract `RuleRegistry`, 9 methods
(4 view, 5 write), constructor params 1 (`min_bond`; the treasury defaults to
the deployer — see `docs/deployment.md` finding 3). The runner pin
`py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` is accepted,
preceded by the `# v0.2.16` version-preamble line that the Studio Devnet
executor requires. A non-blocking note reports a newer runner is available; it
cannot be loaded by the current public toolchain (`docs/deployment.md`
finding 4), so we keep the pinned runner and re-evaluate before submission.

## 2. Behavioral tests — direct mode

```
python -m pytest tests/direct/        # 44 tests, ~2s, no server
```

Result: **44 passed**. Runs the real contract code in-process and exercises the
leader **and** the comparative validator (`direct_vm.run_validator`). Coverage:

- Deploy / initial accounting (`get_stats`), lifecycle `tick`.
- Bond gate, empty-content, no-rules, oversized-title/rules reverts (limits are
  rejected, never truncated - boundary tests at exactly-max and max+1).
- Entry creation as `PENDING`; missing-entry view returns `{}`.
- `evaluate`: COMPLIANT (refund + verify), NON_COMPLIANT (slash + **reserve**),
  INCONCLUSIVE (no slash/verify), malformed-LLM → `[LLM_ERROR]` revert,
  double-evaluate revert, unauthorized caller revert.
- Appeal: flip NON_COMPLIANT→COMPLIANT (un-reserve + un-slash + verify),
  submitter-only, requires-NON_COMPLIANT, appeal-count cap (2), and refusal
  once the liability is actually finalized (`Appeal liability finalized`).
- Tick-window hardening (security audit F7): four cheap submit+cancel writes
  from an unrelated account burn the entire nominal `APPEAL_WINDOW_TICKS`
  window - reproduced as an appeal denial against the old counter-gated
  appeal, and now pinned as `test_spam_cannot_deny_legitimate_appeal` (appeal
  still succeeds while the bond is reserved) plus
  `test_appeal_refused_after_withdraw_sweeps_reservation` (appeal refused only
  after the sweep made the liability irreversible). Second-pass adversarial
  gaps now pinned too: `test_post_deadline_upheld_appeals_exhaust_and_release_once`
  (upheld appeals after the deadline release exactly once, then a real paying
  `deal()`-funded withdrawal succeeds), `test_post_deadline_appeal_inconclusive_refunds_without_verify`
  (INCONCLUSIVE flip: release + un-slash + refund, no verified credit), and
  `test_mixed_window_sweep_finalizes_only_elapsed_reservations` (two different
  deadlines: the paying sweep finalizes only the elapsed entry; the younger
  reservation stays reserved and appealable; treasury got only the eligible share).
- Reservation invariants (the `_assert_ledger` helper checks I1-I4 after every
  transition): premature `withdraw_slashed` inside the appeal window reverts
  with the explicit reserved-collateral error; two upheld appeals finalize the
  liability; window expiry sweeps to available inside the withdraw write (only
  *after* the minimum window - the sweep timing gate is unchanged); multiple
  slashed entries reserve additively; zero/over-cap withdraws revert.
- PENDING recovery: `cancel_pending` refunds and sets terminal CANCELLED;
  unauthorized cancel, cancel-after-verdict, double cancel and **late evaluate
  after cancel** all revert deterministically.
- Treasury withdrawal: owner-only, insufficient-balance guard.
- Resubmission-audit additions: `withdraw_slashed` validates the raw signed int
  for `<= 0` before the unsigned `u256` cast, pinned by
  `test_withdraw_negative_amount_rejected_cleanly`; accounting scales with the
  ACTUAL posted bond (not `min_bond`) via
  `test_bond_above_minimum_is_slashed_reserved_and_withdrawn_exactly`; and
  `test_withdraw_sweep_finalizes_all_elapsed_reservations` pins that a paying
  sweep finalizes every elapsed reservation while the ledger invariants hold.
- List pagination.
- Validator: agrees on independent re-derivation, disagrees on a mismatched
  leader status, and disagrees on leader LLM error (forces rotation).

### What direct mode cannot see

Direct mode does not model native GEN transfers: `emit_transfer` is a no-op, so
these tests assert the contract's internal ledger (`verified_count`,
`slashed_total`, `reserved_slashed`, `withdrawn_slashed`, `bonded_pending`) and
never a recipient's balance. Direct mode also does not roll back mid-write state
on a revert (on-chain finalization does) - the window-expiry test documents that
harness difference explicitly. That boundary cost us a real bug once — the first
deployed version paid bonds out with an internal IC→IC message, which an EOA can
never receive, and **all 22 direct tests then passing** proved nothing about
delivery. Payout delivery is therefore covered by the live settlement regression
in `docs/onchain-activity.md`, and the refund/claim tests here are explicitly
documented as accounting-only.

### Windows harness workaround

`gltest`'s direct harness injects the message by `os.dup2`-ing a temp file onto
stdin (fd 0) and then immediately `os.unlink`-ing it — which raises
`PermissionError`/`WinError 32` on Windows because fd 0 still holds the file.
`tools/win_stdin_patch.py` rebinds only the cleanup timing (defer the unlink to
`atexit`); the message is built and injected identically and no installed
package file is modified. `tests/direct/conftest.py` applies it for the test
process.

## 3. Consensus tests — integration (real GenLayer network)

```
$env:RUN_INTEGRATION='1'
gltest tests/integration/ -v -s --network studio-dev
```

`tests/integration/test_rule_registry_integration.py` (deploy args `[MIN_BOND]`)
is written for full
leader + validator consensus and asserts only genuinely deterministic
transitions (deploy, bond-gated submit, resolved-entry double-evaluate revert,
appeal authorization) — a real LLM verdict is non-reproducible and is therefore
not pinned to an exact status. The suite is skipped by default
(`RUN_INTEGRATION` guard): the shipped `gltest` has no studio-dev network
profile and no fee-deposit flow, while studio-dev charges a non-zero fee on
every transaction (`docs/deployment.md` finding 1). Consensus is instead proven
on the real network by the accepted production deploys (leader + all validators
executed with return) and by the bounded Phase 9 on-chain activity, driven
fee-aware through `genlayer-js@2.0.0-rc.1` (`estimateTransactionFees` →
`writeContract({ value, fees })`) and recorded with transaction hashes and
balance deltas in `docs/onchain-activity.md`.

### Why not GLSim locally

GLSim 0.29.2 (the shipped simulator) is **incompatible with the pinned GenVM
runner on Windows**. Two harness fixes were required just to reach the contract,
and the failure then moved to deeper simulator bugs, all of which are simulator
artifacts and not defects in the contract (a trivial one-field `gl.Contract`
reproduced them identically):

1. The same fd-0 stdin `WinError 32` (fixed by the patch above, applied to the
   GLSim server process via `tools/glsim_win.py`).
2. On the class-cache path GLSim reuses a cached root class and calls
   `_storage_build` on it, reverting with
   `class is not marked for usage within storage ... @allow_storage`. The write
   contract standard does **not** decorate the root `gl.Contract` (the SDK's
   `__init_subclass__` marks it once); forcing this via `tools/glsim_engine_patch.py`
   advanced to the next bug rather than resolving the incompatibility.
3. Bypassing the class cache advanced the failure to view calls raising
   `No VM context active` and the returned contract schema omitting its methods.

Because these are environment bugs, the correct place to prove consensus is the
real network, so integration runs there in Phase 7. No contract source was bent
to satisfy the simulator.
