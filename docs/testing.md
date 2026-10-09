# Testing Report — ProofOfPost (RuleRegistry)

Three-layer validation, per the campaign's security/testability criteria.

## 1. Static validation — `genvm-lint`

```
genvm-lint check contracts/rule_registry.py
```

Result: **PASS**. `validate: ok=true`. Contract `RuleRegistry`, 9 methods
(4 view, 5 write), constructor params 2. The runner pin
`py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` is accepted.
A non-blocking note reports a newer runner is available; we keep the pinned
runner for reproducibility and re-evaluate it before submission.

## 2. Behavioral tests — direct mode

```
python -m pytest tests/direct/        # 22 tests, ~2s, no server
```

Result: **22 passed**. Runs the real contract code in-process and exercises the
leader **and** the comparative validator (`direct_vm.run_validator`). Coverage:

- Deploy / initial accounting (`get_stats`).
- Bond gate, empty-content and no-rules reverts.
- Entry creation as `PENDING`; missing-entry view returns `{}`.
- `evaluate`: COMPLIANT (refund + verify), NON_COMPLIANT (slash), INCONCLUSIVE
  (no slash/verify), malformed-LLM → `[LLM_ERROR]` revert, double-evaluate revert,
  unauthorized caller revert.
- Appeal: flip NON_COMPLIANT→COMPLIANT (un-slash + verify), submitter-only,
  requires-NON_COMPLIANT, appeal-count cap (2).
- Treasury withdrawal: owner-only, insufficient-balance guard.
- List pagination.
- Validator: agrees on independent re-derivation, disagrees on a mismatched
  leader status, and disagrees on leader LLM error (forces rotation).

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

`tests/integration/test_rule_registry_integration.py` runs under full leader +
validator consensus and asserts only genuinely deterministic transitions (deploy,
bond-gated submit, resolved-entry double-evaluate revert, appeal authorization) —
a real LLM verdict is non-reproducible and is therefore not pinned to an exact
status. The suite is skipped by default (`RUN_INTEGRATION` guard) and is executed
as part of the Phase 7 deployment against the Studio dev network, the same
authoritative GenVM the project ships on.

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
