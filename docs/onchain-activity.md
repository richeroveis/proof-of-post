# On-chain regression activity - studio-dev

Real transactions against deployed RuleRegistry instances, chosen to cover
every write path and the money that moves with it. Nothing here is mocked;
every hash below is queryable on `studio-dev` (chain ID 61997) at
https://studio-dev.genlayer.com/api.

## Appeal-refund live proof 2026-10-13 - IN PROGRESS, blocked by studio-dev outage

Remediation for the resubmission rejection G1: a dedicated live scenario
(`e2e/appeal_refund_e2e.mjs`) that deploys the CURRENT source (appeal
reconsideration frame, sha256 `d10623df…`) fresh on each attempt and runs the
exact lifecycle `submit -> evaluate -> NON_COMPLIANT -> appeal -> COMPLIANT ->
refund` against genuinely ambiguous candidates, recording before/after on-chain
state, native-balance deltas and a machine-checkable evidence file
(`e2e/evidence-appeal-refund.json`) that `frontend/verify_evidence.mjs`
re-verifies through the RPC independently of the driver log.

Status as of this writing: **no completed run yet, so G1 live proof is NOT
demonstrated and resubmission must not proceed on it.** From ~06:30 UTC the
studio-dev backend refuses most operations with storage-layer errors
(`psycopg2.errors.DiskFull` on transaction INSERTs, "Can't reconnect until
invalid transaction is rolled back", "database system is in recovery mode",
`-32603` on both writes and `gen_call` reads). Attempt logs: `e2e/attempt_1.log`
through `e2e/attempt_15.log` plus `e2e/retry_driver*.log`. One attempt reached a
FINALIZED deploy of the frame source
(`0x6520063Ba2D28eE6123D2a93E73b90c2FBf59058`, tx
`0xdd75bd75b40deaa3bf11cc3cf16876f041bdab016e7dff97d23419b2ec300231`) before a
degraded-DB read killed the run; that instance executed zero lifecycle steps
and is recorded here only for traceability, not as evidence. Rerun with
`cd e2e && ./retry_driver.sh`; the acceptance evidence is a run with
`success: true` whose verifier exits 0.

### Verdict-reversing appeal with refund: NOT achieved (reviewer G1)

Target flow, exactly what the reviewer asked to see: `submit -> evaluate ->
NON_COMPLIANT (bond slashed + reserved) -> appeal -> COMPLIANT (verdict
reversed) -> reservation released, bond un-slashed, submitter native balance
up by the bond`, every step read back from the live contract with tx hashes and
before/after ledger numbers (`slashed_total`, `reserved_slashed`,
`withdrawn_slashed`, `bonded_pending`) and a submitter balance delta.

**This pass (2026-10-13) the flow could not be executed or verified, so NO such
refund exists to report.** The blocker is the studio-dev storage outage, which
was still in effect when this pass ran. A read-only `gen_call` health monitor
polled `get_stats` on the current instance 24 times over ~20 minutes; every
single poll failed with `Can't reconnect until invalid transaction is rolled
back`, while stateless RPC (`eth_chainId` and `estimateTransactionFees`) kept
responding. Full timestamps (UTC): polls 1-24 at 17:50:50, 17:51:41, 17:52:32,
17:53:23, 17:54:14, 17:55:05, 17:55:56, 17:56:53, 17:57:44, 17:58:34, 17:59:25,
18:00:16, 18:01:07, 18:01:58, 18:02:50, 18:03:41, 18:04:31, 18:05:22, 18:06:16,
18:07:09, 18:08:02, 18:08:53, 18:09:44, 18:10:34; final result `gen_call still
DOWN after full window`. This is on top of the 15 driver attempts earlier the
same day.

Because the proof requires reading the flipped verdict and the balance delta
back from the chain, deploying and firing an appeal whose result cannot be read
would spend fees and produce no verifiable evidence, so no lifecycle transactions
were submitted this pass. The candidate set in `e2e/appeal_refund_e2e.mjs` was
widened from 4 to 10 genuinely ambiguous posts (hyphenated/soft word counts,
mixed tone, sentence segmentation, substring word-form mentions, emoticon-vs-
emoji, digits-vs-words, sentence capitalization, formality/exclamation) so that a
single recovered run gets many honest chances to earn a flip from the ensemble.

**Honest status:** G1 remains OPEN. The reversal/refund accounting is proven
only in direct tests (`test_appeal_flips_non_compliant_to_compliant`,
`test_attack_withdraw_while_appealable_fails_then_win_refunds`); it has never
been shown live. Resubmission must not claim it until `cd e2e &&
./retry_driver.sh` yields a `success: true` evidence file that
`node frontend/verify_evidence.mjs e2e/evidence-appeal-refund.json` re-verifies
with exit 0.

## F7 + withdraw-hardening regression 2026-10-11 - `0x30A9A1D88E8885319a9f5F259D5C416Bd55d149E` (CURRENT)

Full scripted run: `e2e/studio_devnet_e2e.mjs` (structured evidence in
`e2e/evidence.json`, raw `raw` fields stripped). Distinct wallets: owner/deployer
= repo studio-dev key; submitter + treasury = throwaway in-memory keys (never
persisted). Every hash is FINALIZED and queryable on studio-dev (chain 61997).

Independent re-check: `node frontend/verify_evidence.mjs` re-queries every
recorded hash directly against the RPC (no reliance on the driver's own log),
asserts the rejection payloads (`Collateral reserved for appeal window`,
`Too many rules`, `Entry not pending`), asserts the F7 appeal shows no
expiry-refusal payload, and snapshots live `get_stats`. Re-run 2026-10-12:
22/22 txs FINALIZED, all expectations met, exit 0; live ledger matches the
conservation invariant below.

| # | Call | Tx | Outcome |
|---|---|---|---|
| 0 | fund submitter (EO→EO 3.2 GEN) | `0x44f0c8669e13a8741fdaf6a41cca4bc66265bb6afad6eea652514ee8990d825b` | submitter → 3.2 GEN |
| 1 | deploy (fee-aware) | `0xfcdf651213c1414bad107cf869477976938e0910227867034b1dfc5aaaf660b6` | contract `0x30A9…149E`, 5-validator MAJORITY_AGREE |
| 2 | `set_treasury` | `0x100d98bb5083efcce228649c745503600ca02aaa88c947e5d433d962c76ea8e7` | treasury `0x754238CA…1Cda` configured |
| 3 | R `evaluate` (≤10-word Jupiter post) | `0xd8cb28e2e6256d425d9e3ee3e9f222dc184c421ed1ed123fb936fdd8663f99bb` | **COMPLIANT**, refunded, `verified=1` |
| 4 | B `evaluate` (Spanish + URL) | `0xe13fd5bb1b28a5b6f856d2f887b34fe5c08a1ad4ceae64d608e2b5b33832bace` | **NON_COMPLIANT**, `slashed=1 reserved=1 available=0` |
| 5 | **premature** `withdraw_slashed(1)` | `0x98ddb8f1edccf68994c34fa073e280f17cb7ee1817fdc3de59d62eb58d367687` | **REJECTED** - `[EXPECTED] Collateral reserved for appeal window`; ledger unchanged (F1 live) |
| 6 | B `appeal` #1 | `0x9579e160f9f4e8e472b71e1372ee726bcc893e4fd432f10de0756e32f2291b74` | upheld; still reserved |
| 7 | B `appeal` #2 | `0xfcd2635125d5d1120b0e5f2934c78dcd30ade31e6f4ff339340fb6d18b4ec781` | upheld; cap → exhausted: `reserved=0 available=1` |
| 8 | `withdraw_slashed(1)` | `0x69faad85301486db1ea213e81f24623d7ce6787fe60836a2e6fce43c63d4c7ce` | **treasury 0 → 1 GEN** via external message (F5 live); `withdrawn=1` |
| 9 | C `cancel_pending` | `0xf862edf88930b5a5e186160464c632598f128025f01056decda41a920ad34209` | **CANCELLED**; submitter 1.199 → 2.199 GEN (F2 live) |
| 10 | C late `evaluate` | (rejected) | stays CANCELLED - `Entry not pending`; no double settle |
| 11 | 31-rule `submit` | (rejected) | **REJECTED** - `Too many rules`; `total` unchanged (F3 live) |
| 12 | F7 `evaluate` (Spanish + URL) | `0xdd15d77d7f9e843fd07d48bed06d0dafe6965bb63585f19c3c62b89dd1e5254c` | **NON_COMPLIANT**, reserved, `appeal_deadline=16` |
| 13 | F7 window burn (submit+cancel ×2) | see `evidence.json` | tick 12 → 16 (past deadline); **`reserved` still 1 - tick advance did NOT finalize** |
| 14 | **F7 `appeal` after window burn** | see `evidence.json` | **FINALIZED, `appeal_count=1`** - appeal SURVIVED the burned tick window; **not** refused by `liability finalized` (F7 live - the pre-F7 counter-gate reverted here) |

Final ledger: `total=6 verified=1 slashed=2 withdrawn=1 reserved=1 available=0
bonded_pending=0 contract_balance=1` - the residual 1 GEN is exactly the F7
entry's still-reserved, still-appealable bond. Invariants **I1/I4/I6 all true**.

**What was NOT demonstrated live:** a verdict-*reversing* appeal with an on-chain
refund. R was COMPLIANT up front, B stayed NON_COMPLIANT through both appeals,
and the F7 appeal was upheld - the shared validator ensemble did not flip any of
them, and consensus cannot be forced without fabricating results. The
reversal/un-reserve/refund transition is proven deterministically in direct tests
(`test_appeal_flips_non_compliant_to_compliant`,
`test_attack_withdraw_while_appealable_fails_then_win_refunds`); the live refund
*mechanism* was itself demonstrated twice (steps 3 COMPLIANT refund, 9 cancel
refund). Residual devnet state (the F7 entry's reserved 1 GEN and the throwaway
keys) dies with the ephemeral studio-dev reset.

## Remediation regression 2026-10-11 (earlier, pre-F7) - `0x405e957542856E5f6830EDD40757480BDA8ab594`

Full scripted run: `e2e/studio_devnet_e2e.mjs` (raw evidence in
`e2e/evidence.json`, `e2e/e2e.log`), plus two focused reversal attempts
(`e2e/appeal_flip_attempt*.mjs`, `e2e/evidence-flip*.json`). Roles used
DISTINCT wallets throughout: owner/deployer = the repo studio-dev key,
submitter and treasury = throwaway keys generated in memory (never persisted;
leftover devnet dust swept back to the owner where the key was still live).

| # | Call | Tx | Outcome (all FINALIZED) |
|---|---|---|---|
| 0 | fund submitter (EO→EO 3.2 GEN) | `0xc2373a761f3a47af14fcc96ba9247efec4119e0705eb83ebf52bec8677cffa16` | submitter 0 → 3.2 GEN |
| 1 | deploy (fee-aware `deployContract`) | `0x53acb35cd493bfee82c1928c3744c728f688d2cecf850503564cf68188549c40` | contract `0x405e…b594` |
| 2 | `set_treasury(throwaway)` | `0xa74fc35369f059a10c82f9d979c09d8bb31abb02e05b8f4f36d41f30ec1fccb4` | treasury configured |
| 3 | R `submit` (1 GEN, 10-word post) | `0x348d0e278c41445d951c4927df66ffe694243b981135291f5c2c485d81153a30` | entry 0 PENDING |
| 4 | R `evaluate` | `0xaf4fbb5765b66ac2a8cff5eb7fea654f8a30995dc7ab3f8c724541e9e97a67ee` | **COMPLIANT**, bond refunded, `verified=1` |
| 5 | B `submit` (Spanish + URL vs English/no-URL) | `0x89a4edd4944cb0943185307acbd39e5ef0531d9f814dd259e562959cd54edb9b` | entry 1 PENDING |
| 6 | B `evaluate` | `0xe6459c728abae77e0101a04c94f1470c46b6ac94e353c1da95d69fd6208c2502` | **NON_COMPLIANT**; `slashed_total=1`, `reserved=1`, `available=0` |
| 7 | **premature** `withdraw_slashed(1)` | `0x1f76692e8eae3f86e75e21c5db681865a895e88baea0a2e428f8184b646edeae` | **REJECTED** - consensus surfaced `[EXPECTED] Collateral reserved for appeal window`; ledger unchanged |
| 8 | B `appeal` #1 | `0xb1f25a1fa1b54cc27672c895c951e465dafc6db69da72fca608f2f325dee2cea` | upheld; still reserved (`appeals=1`) |
| 9 | B `appeal` #2 | `0xcf945a3d48c5f6712f3aaabb21c8e34add8302a44294b50af71dd4043582854b` | upheld; count cap → liability exhausted: `reserved=0`, `available=1` |
| 10 | `withdraw_slashed(1)` | `0xf8bf5a7bceda188cc4979d74a2f55a5e8e91888baab8fc03c4b3801bc58db4cd` | **treasury wallet 0 → 1 GEN** (external message), `withdrawn=1`, contract balance 0 |
| 11 | C `submit` | `0xf7a7031f940f80dced83b940279593d6d1cb8d8ff57d039aeb775d34f26740c4` | entry 2 PENDING |
| 12 | C `cancel_pending` | `0xa7793daeed7619e8703a1414e8fc2e271c4942ab79538bb5187f0fd825950dbe` | **CANCELLED**; submitter 1.199 → 2.199 GEN (bond recovered) |
| 13 | C late `evaluate` | `0x27d93aae9015ea60ff246f2b6d33d7c332e2b33ae5eaede6aa6bd59ccda9d1f5` | **REJECTED** - `[EXPECTED] Entry not pending`; status stays CANCELLED |
| 14 | 31-rule `submit` | `0x51fe4c987231487ca3264d61895699f6c3d2055f6fc893cac1fed42deac4b6b5` | **REJECTED** - `[EXPECTED] Too many rules`; `total` unchanged (no truncation) |
| 15 | F `evaluate` (sentence-count edge case) | `0xba123d592d99f4bb01efc8a7f5890e6f96d47ab16867ee8a57f186876a28343d` | entry 4 **NON_COMPLIANT**, reserved, deadline tick 18 |
| 16 | F `appeal` | `0xccd0d2bab72ceeedf5227b3d369173bcf66f5925e4775b4effcaf70f88412a09` | upheld (`appeals=1`, still reserved) |

Final ledger after step 14: `total=3 verified=1 slashed=1 withdrawn=1 reserved=0
available=0 bonded_pending=0 contract_balance=0` - all conservation invariants
(I1/I4/I6) true; balances: owner 164.8, submitter 2.199, treasury 1.0 GEN.

**What was NOT demonstrated live:** a verdict-*reversing* appeal with refund.
Two attempts (ambiguous word count → judged COMPLIANT up front; sentence-count
case → NON_COMPLIANT and the appeal ensemble reached the same conclusion) both
failed to flip, and consensus cannot be forced without fabricating results. The
reversal/un-reserve/refund transition is therefore covered by deterministic
direct tests (`test_appeal_flips_non_compliant_to_compliant`,
`test_attack_withdraw_while_appealable_fails_then_win_refunds`), and the live
refund *mechanism* itself was demonstrated twice (steps 4 and 12).

**Residual devnet state:** entry 4's 1 GEN remains reserved in the ephemeral
studio-dev instance (its appeal window expires after 2 more settled writes);
the throwaway submitter/treasury keys were not persisted, so that GEN - like
everything on this chain - dies with the network reset. No mainnet value exists
anywhere in this run.

## Phase 9 record (pre-remediation instance)

Tooling: `genlayer-js` 2.0.0-rc.1 with the built-in `studioDevnet` chain. Every
write is fee-aware - `client.estimateTransactionFees()` supplies the
`distribution` + `feeValue` that `writeContract` attaches, the same flow the
official CLI uses. The CLI itself cannot be used for these writes: `genlayer
write` has no `--value` flag, so the payable `submit` is unreachable from it.

## Current instance `0x61eE31810F804E53b4Eb4A3c876F0504A1fC304b` (superseded 2026-10-11)

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
comparative re-derivation, and the settled verdicts match the rule text -
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
| `evaluate(1)` while only entry 0 existed | `0x40faacad2da87e64d52d811d06088e1152a5592211c34c33bea5a681cf8be7cf` | FINALIZED with `[EXPECTED] No such entry` - all validators returned the same classified error |
| `evaluate(2)` | `0x4111943a36f63c8be140f29e31354fcd466884958c55e4382132ac6445db7aba` | same deterministic rejection path |
| `set_treasury(deployer)` | `0xd9c17a6ee478090175f3c98d454d5c6c0ce251b548d5b6b329454afd0ec37881` | FINALIZED, SUCCESS - a `str` address argument passes cleanly through the SDK, unlike via `genlayer deploy --args` |
| `evaluate(0)` | - | COMPLIANT, verdict recorded (`verified=1`), refund lost (see above) |
| `evaluate(1)` / `withdraw_slashed` | - | NON_COMPLIANT + slash recorded, GEN never left the contract |

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
`appeal_count` to 1 - the bounded re-adjudication path works end to end.

## Cost

Roughly 1.6 GEN of fee deposits were submitted across deploys and activity in
this phase; the network charged ≈0.00008 GEN per settled transaction and
refunded the rest of each deposit (finding 7 in deployment.md). The 2 GEN bonded
on the superseded first instance remain locked there by the payout bug it
shipped with; it is kept as evidence rather than rewritten.
