# Deployment Record — ProofOfPost (RuleRegistry)

## Live deployment

| Field | Value |
|---|---|
| Network | GenLayer Studio Devnet (`studio-dev`, Studio Next preview) |
| Chain ID | 61997 |
| RPC | https://studio-dev.genlayer.com/api |
| Contract | `contracts/rule_registry.py` → class `RuleRegistry` |
| Address | `0xF8341A84a27aAADE1A5C80ADC43C3AeE2F119df4` |
| Deploy tx | `0xf463249d0bd5330848a5936974ab11302c909d8628a900517eb8a4146fc56c44` |
| Consensus | ACCEPTED (leader + validators executed with return) |
| Constructor args | `min_bond = 1000000000000000000` (1 GEN, atto-scale) |
| Owner / treasury | deployer `0x154a452b0755EE812014C1405B15D905BA06f9c7` (treasury retargetable via `set_treasury`) |

Post-deploy verification (real `gen_call` reads on studio-dev):

- `get_stats` → `total=0, verified=0, min_bond=1e18, slashed_total=0, owner/treasury=deployer` ✔
- `get_min_bond` → `1000000000000000000` ✔
- `genlayer schema` → ctor `(min_bond: int)`, 9 public methods, view/write/payable flags as designed ✔

## studio-dev operational findings (hard-won, October 2026)

These cost six deploy attempts and are recorded so the behavior is reproducible.

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
