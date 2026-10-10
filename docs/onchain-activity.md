# On-chain regression activity — studio-dev

Phase 9 record: real transactions against the deployed RuleRegistry, chosen to
cover every write path and the money that moves with it. Nothing here is mocked;
every hash below is queryable on `studio-dev` (chain ID 61997) at
https://studio-dev.genlayer.com/api.

Tooling: `genlayer-js` 2.0.0-rc.1 with the built-in `studioDevnet` chain. Every
write is fee-aware — `client.estimateTransactionFees()` supplies the
`distribution` + `feeValue` that `writeContract` attaches, the same flow the
official CLI uses. The CLI itself cannot be used for these writes: `genlayer
write` has no `--value` flag, so the payable `submit` is unreachable from it.

## Current instance `0x61eE31810F804E53b4Eb4A3c876F0504A1fC304b`

| # | Call | Tx | Consensus outcome |
|---|---|---|---|
| 1 | `submit` (payable, 1 GEN bond, English post, 3 rules) | `0xf7c61a2b34e90cecc2c9bf50f25bc29b50dc21e0c54d12151cbd6987e50ee977` | FINALIZED, entry 0 created PENDING |
| 2 | `submit` (payable, 1 GEN bond, Spanish post containing a URL) | `0x7882ba1b3ef7f6cf498e76de3cbb3f1499d614c374f525d20ae28207056b36ca` | FINALIZED, entry 1 created PENDING |
| 3 | `evaluate(0)` | `0x754fa448f5da94acbdf2c9501a8473353d16a66465803ab9fb877c491f130ee9` | FINALIZED, leader/validators returned **COMPLIANT**, bond refunded |
| 4 | `evaluate(1)` | `0x63fe7ec2c3a803e59665ce91875dfd6ddf07b02c070c732a55b4ccb6f64952dd` | FINALIZED, **NON_COMPLIANT**, bond slashed |
| 5 | `withdraw_slashed(treasury, 1e18)` | `0x0c203a26c35381ed0b36b238f5a5f5cd31ddb3240e1ed4fbb24f3c06c30a423d` | FINALIZED, treasury received the slashed GEN |

Settlement ledger observed through `get_stats` plus the signer's GEN balance:

| Step | contract GEN | signer GEN | total | verified | slashed | withdrawn |
|---|---|---|---|---|---|---|
| initial | 0 | 167.998634 | 0 | 0 | 0 | 0 |
| after 2 submits | 2 | 165.998476 | 2 | 0 | 0 | 0 |
| after evaluate(0) | 1 | 166.998349 | 2 | 1 | 0 | 0 |
| after evaluate(1) | 1 | 166.998268 | 2 | 1 | 1 | 0 |
| after withdraw_slashed | 0 | 167.998142 | 2 | 1 | 1 | 1 |

Verdicts came from validator consensus, not from the client: each `evaluate`
ran the LLM compliance prompt inside `run_nondet` with an independent
comparative re-derivation, and the settled verdicts match the rule text —
entry 0 satisfied all three rules, entry 1 violated "must be written in
English" and "must not contain any URL".

## What this activity found (fixed in the same phase)

Steps 3 and 5 were run twice. On the **previous** instance
(`0xF8341A84…`, deploy tx `0xf463249d…`) the identical sequence finalized and
updated `verified` / `slashed_total` / `withdrawn_slashed` exactly as above, but
the contract's native balance never moved: 2 GEN stayed locked in it. The
payout used `gl.get_contract_at(to).emit_transfer(...)`, an internal IC→IC
message that is silently undeliverable to an EOA. All 22 direct tests passed
with that bug, because direct mode does not model native transfers. Switching
`_send` to an external EVM message (finding 6 in
[deployment.md](./deployment.md)) is what makes the rows above move money.

## First instance `0xF8341A84a27aAADE1A5C80ADC43C3AeE2F119df4`

| Call | Tx | Outcome |
|---|---|---|
| `submit` (payable) | `0xf964f9e6c7fdec4f968ae17b059d979fe5a64faeabad94a4f58c052af9260db5` | FINALIZED, entry 0 created, 1 GEN bonded |
| `submit` (payable) | `0x769c595161d049ac59cb031380ef860588e54dc03cd6d6539fe3bc0d0aaf6d45` | FINALIZED, entry 1 created, 1 GEN bonded |
| `evaluate(1)` while only entry 0 existed | `0x40faacad2da87e64d52d811d06088e1152a5592211c34c33bea5a681cf8be7cf` | FINALIZED with `[EXPECTED] No such entry` — all validators returned the same classified error |
| `evaluate(2)` | `0x4111943a36f63c8be140f29e31354fcd466884958c55e4382132ac6445db7aba` | same deterministic rejection path |
| `set_treasury(deployer)` | `0xd9c17a6ee478090175f3c98d454d5c6c0ce251b548d5b6b329454afd0ec37881` | FINALIZED, SUCCESS — a `str` address argument passes cleanly through the SDK, unlike via `genlayer deploy --args` |
| `evaluate(0)` | — | COMPLIANT, verdict recorded (`verified=1`), refund lost (see above) |
| `evaluate(1)` / `withdraw_slashed` | — | NON_COMPLIANT + slash recorded, GEN never left the contract |

Entry ids are 0-based (`next_id` starts at `0`), which is why the first pass's
`evaluate(1)` / `evaluate(2)` calls hit the not-found guard. That turned into
useful coverage: it proves the `[EXPECTED]` error classification reaches
consensus agreement instead of rotating validators.

## Protocol-level appeal: not available on studio-dev

`client.canAppeal({txId})` returns `false` for finalized transactions here, and
`getAppealCharge` answers `Transaction … has no active decision to appeal`.
Studio Devnet simulates the consensus pipeline and exposes no open appeal
window for a non-validator EOA, so the *protocol* rotation path
(`genlayer appeal` / `appealTransaction`) cannot be exercised on this network.
The regression therefore covers the contract's own appeal write instead: on the
first instance `appeal(1)` (`0x4927af9bd38cb68733fd0a80a9a4c7f1040044f6c281fa9fb0a0c0bd94bfb703`)
finalized, re-ran consensus, kept `NON_COMPLIANT`, and incremented
`appeal_count` to 1 — the bounded re-adjudication path works end to end.

## Cost

Roughly 1.6 GEN of fee deposits were submitted across deploys and activity in
this phase; the network charged ≈0.00008 GEN per settled transaction and
refunded the rest of each deposit (finding 7 in deployment.md). The 2 GEN bonded
on the superseded first instance remain locked there by the payout bug it
shipped with; it is kept as evidence rather than rewritten.
