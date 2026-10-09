# GenLayer Builder Campaign — Phase 1 Research

Verification date: 2026-10-09. All technical claims below were checked against
official GenLayer documentation, the installed GenLayer skills, or the local
toolchain. Sources and dates are listed at the bottom. Anything not yet
independently verified is flagged explicitly.

---

## 1. Environment / Phase 0 findings (verified locally)

| Item | Status |
|------|--------|
| Workspace | `c:\Users\oveis\Project\Richer_Project_1` — initially contained only `.env` |
| Git repo | **Not present** (no `.git`, no remote) — must be initialised in Phase 6 |
| `.env` variables | `GENLAYER_PRIVATE_KEY` present (66 chars, looks like `0x…` key); `GITHUB_TOKEN` present (40 chars). Values never printed. |
| Python | 3.13.13 |
| Node.js / npm | v24.21.0 / 11.19.0 |
| uv | 0.11.24 |
| pip | 26.1 |
| Git | 2.53.0 |
| GenLayer CLI (`genlayer`) | **Not installed** — needs `npm install -g genlayer` (target version ≥ the CLI that ships the `studio-dev` alias) |
| GenLayer Python SDK (`genlayer`) | **Not installed** — `pip show genlayer` empty |
| `genvm-linter` / `genlayer-test` | **Not installed** |

Unblocking actions (safe, executable later in the phases): install the CLI,
SDK, linter, and test plugin; import the account from `GENLAYER_PRIVATE_KEY`
without echoing it. None required for the Phase 2 decision.

---

## 2. Required technical stack (verified from skills + docs)

- **Contracts:** Python "intelligent contracts" executed in GenVM.
- **Runner pinning (CRITICAL):** every contract's first line must pin a concrete
  runner hash, e.g.
  `# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }`.
  `py-genlayer:test`, `:latest`, and unversioned aliases are **rejected on all
  networks**. Multi-file packages use `py-genlayer-multi`; embeddings use
  `py-lib-genlayer-embeddings` inside a `Seq` block.
- **SDK surface:** `gl.Contract`, `@gl.public.view` / `@gl.public.write`,
  storage types `Address`, `u256`/`i256`, `TreeMap[K,V]`, `DynArray[T]`,
  `@allow_storage @dataclass`. Non-deterministic ops:
  `gl.nondet.web.get/post`, `gl.nondet.exec_prompt(..., response_format="json")`,
  `gl.get_webpage`.
- **Equivalence principles:** `gl.eq_principle.strict_eq` (deterministic only),
  `prompt_comparative`, `prompt_non_comparative`, and the production-preferred
  custom validator via `gl.vm.run_nondet_unsafe(leader_fn, validator_fn)`.
- **Errors:** classified with prefixes `[EXPECTED]`, `[EXTERNAL]`, `[TRANSIENT]`,
  `[LLM_ERROR]`; raise `gl.vm.UserError` / `gl.vm.UserError`, never bare `Exception`.
- **Testing:** three layers — `genvm-lint check` (AST safety + SDK semantics),
  direct-mode pytest tests (`genlayer-test` plugin, ~30ms, mocked web/LLM), and
  integration tests (`gltest`, full consensus, real web/LLM).
- **Client / frontend:** Next.js 15 boilerplate (`genlayer-project-boilerplate`),
  wallet connection, JS SDK for reads/writes/tx lifecycle.

---

## 3. Development network — Studio Next / dev (verified, important)

Official `Network Configuration` doc (last_updated 2026-09-03):

- The stable built-in aliases are `localnet`, `studionet`, `testnet-asimov`,
  `testnet-bradbury`.
- The **v0.123 / Consensus v0.6 release candidate** adds the alias **`studio-dev`**,
  backed by the JS SDK `studioDevnet` chain definition:
  - RPC: `https://studio-dev.genlayer.com/api`
  - Chain ID: **61997**
- `studio-next.genlayer.com` is treated as a **web alias** for the same preview;
  keep the canonical SDK/RPC target on `studio-dev`.
- **Warning:** if `studio-dev` is not listed by `genlayer network list`, the
  installed CLI/SDK is older than the RC — upgrade to the matching RC. Do **not**
  substitute `studionet` (chain ID 61999, different consensus deployment).
- Studio-dev is **temporary and resets**; do not depend on its state for durable
  deployments. Redeploy + update frontend config must be documented.

**Conclusion for Phase 7:** the campaign's "Studio Next / dev" maps to the
`studio-dev` alias (chain ID 61997), **conditional on an RC-capable CLI/SDK**.
This must be confirmed with `genlayer network list` / `genlayer network info`
after install, before any deployment. Whether `studio-dev` is gasless like
`studionet` is **not yet verified** — needs a check after CLI install.

---

## 4. What makes a project genuinely GenLayer-native (from `write-contract` skill)

GenLayer is an **adjudication/consensus layer for subjective, external, or
AI-mediated judgments** that multiple validators must verify independently. It is
NOT a generic AI backend.

Use GenLayer when the contract must settle on a decision that:
- evaluates evidence and affects escrow, payouts, reputation, or access;
- is a prediction/oracle outcome needing independently validated truth;
- is a compliance/moderation/scoring decision not reducible to a deterministic call;
- is an autonomous agent action needing transparent, appealable settlement.

Do NOT use GenLayer when the frontend already computes the answer (rubber-stamp),
the contract only stores user data, or a deterministic contract/REST/DB job suffices.

Boundary discipline required per contract:
- **Frontend/backend owns:** UI, auth, indexing, non-authoritative previews, caching.
- **Contract owns:** the minimum state transition needing consensus, evidence inputs,
  the validator comparison rule, the settlement effect, appeal/rotation path.
- **External sources own:** raw facts — untrusted unless validators can re-fetch,
  normalise, and compare them.

Anti-patterns to avoid: `strict_eq` on LLM output; schema-only / leader-only
validators (format check ≠ truth); storing `dict`/`list`; `float` for money
(use atto-scale `u256`); inserting dataclass fields mid-layout; non-comparative
validation for classification/scoring decisions.

---

## 5. Campaign requirements (partially verified — treat ranges as possible, not guaranteed)

- The **GenLayer Portal** contribution system lets anyone submit work built on
  GenLayer: shipping a **Project**, submitting a standalone **Intelligent
  Contract**, or improving network operations (validators/stewards). Builders earn
  **Builder Points** per accepted contribution.
- Point ranges supplied by the user's interface: **Projects 20–4,000**;
  **standalone Contracts 0–500**. These are **unverified against a stable public
  source** (the portal front-end is JS-rendered and returned no scrapable rules on
  2026-10-09). Treat as possible ranges only; **re-verify current rules before
  submission (Phase 11).**
- A recent official event (DoraHacks "Testnet Bradbury" hackathon, submission
  window ~Mar–Apr 2026) required each project's Intelligent Contract to use
  **Optimistic Democracy consensus** and an **Equivalence Principle**. This aligns
  with the docs' guidance and is a reasonable proxy for review expectations, but
  it is an event-specific page, not necessarily the standing campaign rubric.

**Action:** before final submission, confirm the live campaign rules on
`portal.genlayer.foundation` (and the Project Explorer / contract submission
pages) with a human-assisted check if the JS UI cannot be scraped.

---

## 6. Competitor / ecosystem research (to deepen in Phase 2)

- Public boilerplate: `genlayerlabs/genlayer-project-boilerplate` (Next.js 15 +
  Python contracts + tests). Reference contracts & ideas at
  `docs.genlayer.com/developers/intelligent-contracts/ideas`.
- Community repo `Siriron/genlayer-intelligent-contracts` shows Studio deploy flow.
- Common builder trap noted in skills: many projects "start by treating GenLayer
  as a generic AI backend" then must be pushed toward a real on-chain consensus
  role. Differentiation should come from a genuine adjudication need.

Phase 2 candidates will each explicitly state why a plain smart contract AND a
centralised AI service are both insufficient, to prove GenLayer-necessity.

---

## 7. Implementation risks (cross-cutting)

1. **CLI/SDK RC availability** — `studio-dev` needs the matching release candidate;
   older installs won't list the alias. Mitigation: verify after install; fall back
   to documented stable flow only with explicit approval.
2. **Studio-dev resets** — deployments are ephemeral; demo must be redeployable and
   contract address must be re-injectable into the frontend config.
3. **Consensus flakiness** — LLM/web non-determinism; mitigated by custom validators,
   stable-field extraction, derived status, error classification, tolerances.
4. **Rate limits** (hosted Studio) — 60 req/min, 1000/hr, 10000/day; ≤32 in-flight
   txs/sender. Batch regression must be throttled/paced (Phase 9).
5. **Prompt injection / untrusted web content** — treat external content adversarially.
6. **Scraping campaign rules** — portal is JS-rendered; final rules need human/browser
   verification before irreversible submission actions (Phase 11 gate).

---

## 8. Sources & verification dates

- Local toolchain probe — 2026-10-09 (versions, `.env` keys, missing GenLayer tools).
- Installed skills (`write-contract`, `genlayer-cli`, `direct-tests`,
  `integration-tests`, `genvm-lint`, `genlayernode`) — read 2026-10-09.
- https://docs.genlayer.com/developers/intelligent-contracts/deploying/network-configuration
  (last_updated 2026-09-03) — Studio-dev alias, RPC, chain ID 61997, RC requirement.
- https://docs.genlayer.com/developers/intelligent-contracts/ideas — contract ideas/boilerplate.
- https://skills.genlayer.com/ — skills marketplace (install method).
- https://portal.genlayer.foundation/how-it-works — contribution/points system (JS page,
  content not fully retrievable 2026-10-09 → flagged for re-verify).
- https://dorahacks.io/hackathon/genlayer-bradbury/detail — event requirements (Optimistic
  Democracy + Equivalence Principle), event-scoped, not confirmed standing rubric.
