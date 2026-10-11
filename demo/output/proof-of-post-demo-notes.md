# ProofOfPost Demo Video — Production Notes

> **HISTORICAL RECORDING.** This video was captured against the pre-remediation
> contract instance `0x61eE31810F804E53b4Eb4A3c876F0504A1fC304b` (devnet chain
> timestamps shown in the video read 2026-08-08) and its UI. That instance was
> superseded by the remediated deployment
> `0x405e957542856E5f6830EDD40757480BDA8ab594` (appeal-window collateral
> reservation, `cancel_pending`, strict rule limits, treasury-routed withdrawals -
> see `docs/remediation-plan.md`). Everything shown here is still a truthful
> recording of what happened on the old instance, but the contract behaviors and
> statistics displayed no longer match the live one.

Recorded and rendered: 2026-10-11 (Asia/Tehran). All footage is a real,
un-staged session of the live application; nothing in the video is mocked.

## Deliverables

| File | Description |
|---|---|
| `proof-of-post-demo.mp4` | 69.08 s, 1920x1080, 25 fps, H.264 (yuv420p) + AAC, subtitles burned in |
| `proof-of-post-subtitles.srt` | 16 cues, matched to the final cut |
| `proof-of-post-demo-notes.md` | this file |

Raw evidence (kept alongside): `../capture/video/*.webm` (full 339.8 s real-time
recording), `../capture/shots/*.png` (per-step stills),
`../capture/timeline.json` (wall-clock markers), `../capture/walkthrough.log`.

## Environment used

- Network: **GenLayer Studio Devnet** (`studio-dev`, chainId **61997**),
  RPC `https://studio-dev.genlayer.com/api`
- Contract: `RuleRegistry` at `0x61eE31810F804E53b4Eb4A3c876F0504A1fC304b`
- Live app: `https://richeroveis.github.io/proof-of-post` (HTTP 200; live chain
  reads confirmed before recording — get_stats / list_entries returned real data)
- Signer: the repo's `.env` studio-dev-only key, connected through the site's
  masked password field. The key is dots-only in the recording (QC-verified on
  extracted frames); no secret, personal data, or seed phrase appears anywhere.

## Features actually demonstrated (real transactions)

1. Opening the live dashboard; hero, network line, and live stats
   (Total 2 / Verified 1 / Min bond 1 GEN / Slashed 1 GEN / Balance 0).
2. Signer connect — in-browser local signing (no extension wallet; the app's
   documented model), fee quote and signer balance surfaced by the UI.
3. Filling the form: title, content, three natural-language rules, 1 GEN bond.
4. `submit` (payable) → tx
   `0x56a2b77e5b13a5774bf4f0cca26a944592189ccd617a3817736782531fd9ff35` →
   lifecycle **FINALIZED** (real wait ≈ 70 s), entry **#2** created **PENDING**.
5. `evaluate(#2)` → tx
   `0x0b341d87c6e2fc101a73f08b0b799fbb5137ca901c355796752f96a340582ea0` →
   **FINALIZED** (real wait ≈ 100 s). Post-consensus chain read: entry #2
   **COMPLIANT**, all three rules SATISFIED, `verified` 1→2, contract balance
   back to 0 — the 1 GEN bond was refunded via the external-message payout.
6. `appeal(#1)` on the pre-existing NON_COMPLIANT entry → tx
   `0x9435353f860468528e3198dbad50916276aacd8e4b030e7d12015775bd09d778` →
   **FINALIZED** (real wait ≈ 100 s). Post-consensus chain read: entry #1
   remains **NON_COMPLIANT**, `appeal_count` 0→**1**, `slashed_total` unchanged
   (1 GEN stays slashed). The bounded re-adjudication path works end to end.
7. Registry browsing / entry detail view (Rules & verdicts + reason).

## Editing honesty

- The three consensus waits (70–100 s each of real, unmodified recording) were
  time-compressed to 4–5 s in the final cut; the subtitles state the exact
  speed-up factor for each. No frames were faked or skipped within actions.
- Background music is a self-generated ambient bed (no third-party assets).
- Opening/closing cards contain only the real project links and contract address.

## Skipped / not demonstrated

- **INCONCLUSIVE** settlement path — not exercised (would require content whose
  rules are unverifiable; not attempted to avoid extra bonded transactions).
- `withdraw_slashed` / `set_treasury` (owner ops) — documented in
  `docs/onchain-activity.md` with real hashes, but not in this video.
- **Protocol-level** appeal (`appealTransaction`) — per the docs, studio-dev
  exposes no open appeal window for a non-validator EOA; the video shows the
  contract-level `appeal()` write instead, which is what the UI implements.
- The standalone EvidenceOracle / ScoreRegistry contracts — out of scope here.

## Discrepancies noticed (live app vs docs / repo)

- None material. The live app matched the documented journey exactly: fields,
  bond minimum (1 GEN), lifecycle polling to FINALIZED, verdict badges, appeal
  button gated to NON_COMPLIANT rows for the submitter.
- Minor repo staleness (does not affect the deployed site):
  `frontend/verify_live.mjs` calls `list_items`, which is the ScoreRegistry
  method name; the deployed RuleRegistry exposes `list_entries`.
- The UI's fee quote displayed as `0.100000000000010352 GEN` (a raw deposit
  amount, formatted with float-ish noise); docs describe the real charged fee
  as ≈0.00008 GEN per settled tx with the deposit refunded — consistent with
  the signer balance moving only ~0.0005 GEN across all three writes.

## Validation performed after render

- `ffprobe`: 1920x1080, h264 yuv420p, 25 fps, AAC audio, duration 69.08 s.
- Frames extracted at intro, signer connect (masking check), consensus wait,
  verdict detail, and end card — subtitles legible, positioned bottom-center
  with dark box, not covering the demonstrated UI.
- Post-recording read-only chain verification of all three outcomes above
  (`get_stats`, `get_entry(1)`, `get_entry(2)`).
