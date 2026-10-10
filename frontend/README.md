# ProofOfPost frontend

A Next.js (App Router) static dashboard for the **RuleRegistry** intelligent
contract on **GenLayer Studio Dev** (`studio-dev`, chainId `61997`).

- **Reads** call the contract's view methods (`get_stats`, `list_entries`,
  `get_entry`) over the GenLayer `gen_call` JSON-RPC using [`genlayer-js`](https://www.npmjs.com/package/genlayer-js).
- **Writes** (`submit`, `evaluate`, `appeal`) are signed **locally in the
  browser** from a `studio-dev`-only private key you paste into the form. The
  key is held in memory only — never persisted, never transmitted raw, and
  never included in the bundle. Do **not** use a mainnet key.
- **Current write caveat (documented, not hidden):** `studio-dev` requires a
  non-zero fee deposit on every transaction (see `docs/deployment.md`), and
  `genlayer-js@1.1.8` has no fee-distribution support, so browser writes are
  rejected on-chain (`FeeValueMustBeNonZero`) until the SDK ships fee
  support. All on-chain activity so far is proven through the fee-aware
  `genlayer` CLI; reads on this dashboard are fully live.
- Verdicts are produced by GenLayer validator consensus in the contract, not by
  this UI.

The `studio-dev` chain is not built into `genlayer-js`; it is derived from the
bundled `studionet` chain (same infrastructure and consensus contract
addresses) with only the id/name/RPC overridden, mirroring the official
GenLayer CLI — see [`lib/chain.ts`](lib/chain.ts).

## Run locally

```bash
cp .env.example .env.local   # NEXT_PUBLIC_CONTRACT_ADDRESS is prefilled
npm install
npm run dev
```

## Published instance

https://richeroveis.github.io/proof-of-post/ — built by the
`Deploy frontend to GitHub Pages` Actions workflow from the deployed contract
`0xF8341A84a27aAADE1A5C80ADC43C3AeE2F119df4` on studio-dev.

## Build (static export for GitHub Pages)

```bash
NEXT_PUBLIC_CONTRACT_ADDRESS=0x... NEXT_PUBLIC_BASE_PATH=/<repo> npm run build
# output is written to ./out and published by GitHub Pages
```

`next.config.mjs` uses `output: "export"`, so there is no server runtime; the
entire app talks to the RPC endpoint directly from the browser.
