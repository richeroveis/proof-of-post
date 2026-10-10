# Deployment Record — ProofOfPost (RuleRegistry)

## Live deployment

| Field | Value |
|---|---|
| Network | GenLayer Studio Devnet (`studio-dev`, Studio Next preview) |
| Chain ID | 61997 |
| RPC | https://studio-dev.genlayer.com/api |
| Contract | `contracts/rule_registry.py` → class `RuleRegistry` |
| Address | `0x61eE31810F804E53b4Eb4A3c876F0504A1fC304b` |
| Deploy tx | `0xba738586f4f50a12e9aa831d9bee2464c3a4f0a466f5516972a8f86d39233cd2` |
| Consensus | ACCEPTED (leader + validators executed with return) |
| Constructor args | `min_bond = 1000000000000000000` (1 GEN, atto-scale) |
| Owner / treasury | deployer `0x154a452b0755EE812014C1405B15D905BA06f9c7` (treasury retargetable via `set_treasury`) |

Superseded instances on the same network, kept for traceability:

| Address | Why superseded |
|---|---|
| `0xF8341A84a27aAADE1A5C80ADC43C3AeE2F119df4` (tx `0xf463249d…`) | first successful deploy; contained the internal-message payout bug of finding 6, so its 2 GEN of bonds are stranded in it |
| `0xcb8Be18DC66763cB0CCFEa06F8272538f89Ce94C` (tx `0x95b0beb7…`) | interim build that passed `on="finalized"` to the EVM-layer `emit_transfer`, whose kwargs accept only `value` |

Post-deploy verification (real `gen_call` reads on studio-dev):

- `get_stats` → `total=0, verified=0, min_bond=1e18, slashed_total=0, owner/treasury=deployer` ✔
- `get_min_bond` → `1000000000000000000` ✔
- `genlayer schema` → ctor `(min_bond: int)`, 9 public methods, view/write/payable flags as designed ✔

Full write/settlement regression on the live instance is recorded in
[onchain-activity.md](./onchain-activity.md).

## studio-dev operational findings (hard-won, October 2026)

These cost eight deploy attempts and several consensus rounds and are recorded
so the behavior is reproducible.

1. **studio-dev is not gasless.** Unlike `studionet`, every transaction on
   Studio Devnet requires a **non-zero fee deposit** (`FeeValueMustBeNonZero`),
   and no FeeManager contract is configured, so the CLI cannot auto-derive the
   fee. Working flow: run `genlayer estimate-fees --json`, pass its
   `distribution` as `--fees '<json>'` and its `feeValue` as `--fee-value`
   (currently `100000000000010352` ≈ 0.1 GEN per tx; refunds occur on
   finalize). The deployer holds 170 GEN on this chain.

2. **The runner header must carry a version-preamble line.** On this fleet, a
   contract whose file begins directly with `# { "Depends": "py-genlayer:…" }`
   executes as `invalid_contract runner malformed` — unanimously (leader and
   all validators), regardless of pin, line endings (CRLF and LF fail
   identically), or header form (single-line and multi-line `Seq` both fail).
   Prefixing the pin with `# v0.2.16` on its own line (the format the hosted
   Studio tooling emits) fixes it. Cross-checked byte-for-byte against a
   third-party deploy that succeeded on studio-dev with the **same** runner
   pin (`tx 0xc2c001d9ea63be803b084be36d3ec2387856a2c1087dfd1370c3c6e3fdc21de0`):
   the only header difference was the version line.

3. **`genlayer deploy --args` type coercion makes `str` address params
   unpassable.** A `0x`+40-hex literal is encoded as `Address` calldata and an
   empty string collapses to `0` (see the tx readable: `[1000000000000000000,0,]`).
   A constructor declared `treasury: str` therefore cannot receive a reliable
   string argument from the CLI. The constructor was simplified to
   `__init__(min_bond: int)` with treasury defaulting to the deployer;
   `set_treasury(str)` retargets it afterwards as an owner write. (The same
   coercion applies to write args, so `set_treasury`/`withdraw_slashed` string
   address arguments are exercised explicitly in the Phase 9 activity run.)
   Direct tests and the integration suite were updated to match.

4. **The "newer runner" (`py-genlayer:1zr6nqk…`, genvm-lint note I200) cannot
   be adopted with the current public toolchain.** `genvm-linter` 0.11.0 and
   `genlayer-py` 0.16.3 fail to load its v0.3-style std lib
   (`No module named 'genlayer.py'`), so lint/validation/direct tests all break
   against it. The pinned `1jb45aa8…` runner is the version the local toolchain
   verifies and (with the version line) the fleet executes.

5. **Receipt/debugging quirks.** `genlayer receipt <hash>` can hang waiting for
   finalization even with `--wait-until decided`; the SDK
   (`client.getTransaction`) returns the full consensus payload instead, and
   leader/validator `result` fields are base64 strings there. The debug-trace
   RPC (`gen_dbg_traceTransaction`) is not exposed on studio-dev.

6. **Paying an EOA requires an *external* message, not `get_contract_at`.**
   The first live version refunded bonds and claimed slashed bonds with
   `gl.get_contract_at(to).emit_transfer(value=…, on="finalized")`, which is an
   **internal IC→IC** message. When the recipient is an externally owned
   account there is no contract to receive it, so the transfer is silently never
   delivered: on studio-dev `evaluate`/`withdraw_slashed` finalized, `verified`,
   `slashed_total` and `withdrawn_slashed` all updated correctly, yet the
   contract's native balance stayed at 2 GEN and the recipient's balance only
   decreased by fees. The docs require an EVM-layer (external) message for
   value to an EOA, so `_send` now uses an empty
   `@gl.evm.contract_interface` receiver:

   ```python
   _GENReceiver(to).emit_transfer(value=amount)
   ```

   External messages always execute on finalization and their kwargs accept only
   `value`, so passing `on=` there is a runtime error. Direct mode does not model
   native transfers at all (22/22 tests passed either way), so this class of bug
   is only visible against a real network — it is why Phase 9 settles money, not
   just verdicts. After the fix the same sequence moves GEN exactly (see
   [onchain-activity.md](./onchain-activity.md)).

7. **Fee deposits are mostly refunded.** The quoted per-transaction fee is
   ≈0.1 GEN, but measured balance deltas per settled transaction are
   ≈0.00008 GEN, i.e. the deposit is charged down to actual usage and the
   remainder returns to the sender. Budget for the quote, expect the remainder
   back.

## Failed deploy attempts (no state, fees burned)

`0xc7bbe151…` (addr treasury), `0x9b91aa74…` (str treasury),
`0x1dc0f6e2…` (LF, no preamble), `0x9d568a18…` (Seq header) — all
ACCEPTED + leader `FINISHED_WITH_ERROR` with `invalid_contract runner
malformed`; kept as evidence for finding 2. A failed deploy creates no
contract, as expected.

## Reproduce

`setup_deploy.ps1` (gitignored helper) performs estimate-fees → deploy with
explicit fees, single int arg, keystore password via stdin. The deployer
keystore is imported from `GENLAYER_PRIVATE_KEY` in `.env` by
`setup_genlayer.ps1`; neither secret is ever printed.
