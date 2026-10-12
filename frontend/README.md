# ProofOfPost frontend

A Next.js (App Router) static dashboard for the **RuleRegistry** intelligent
contract on **GenLayer Studio Dev** (`studio-dev`, chainId `61997`).

- **Reads** call the contract's view methods (`get_stats`, `list_entries`,
  `get_entry`) over the GenLayer `gen_call` JSON-RPC using [`genlayer-js`](https://www.npmjs.com/package/genlayer-js).
- **Writes** (`submit`, `evaluate`, `appeal`) are signed **locally in the
  browser** from a `studio-dev`-only private key you paste into the form. The
  key is held in memory only - never persisted, never transmitted raw, and
  never included in the bundle. Do **not** use a mainnet key.
- **Fees:** `studio-dev` is not gasless - every transaction needs a non-zero fee
  deposit (`docs/deployment.md`). Before each write the page asks the node for a
  fee quote (`estimateTransactionFees`) and attaches the returned
  `distribution`/`feeValue` to the transaction, the same flow the official CLI
  uses; the quoted fee and the signer's GEN balance are shown in the UI so the
  cost is visible up front. The deposit is charged down to actual usage and the
  remainder is refunded.
- **Consensus latency:** a write is not a result. After broadcasting, the page
  polls the transaction lifecycle until the protocol reaches `FINALIZED` (or the
  window ends) and only then re-reads the contract, because the validator
  verdict - not the tx hash - decides whether a bond was refunded or slashed.
- Verdicts are produced by GenLayer validator consensus in the contract, not by
  this UI.

The `studio-dev` chain (`studioDevnet`, chainId 61997) is taken from the SDK's
own built-in chain list in `genlayer-js@2.x` rather than being hand-derived, so
its infrastructure and consensus contract addresses are exactly what the SDK and
official CLI configure - see [`lib/chain.ts`](lib/chain.ts).

## Run locally

```bash
cp .env.example .env.local   # NEXT_PUBLIC_CONTRACT_ADDRESS is prefilled
npm install
npm run dev
```

## Published instance

https://richeroveis.github.io/proof-of-post/ - built by the
`Deploy frontend to GitHub Pages` Actions workflow from the deployed contract
`0x30A9A1D88E8885319a9f5F259D5C416Bd55d149E` on studio-dev (the current F7 +
withdraw-hardened instance; supersedes `0x405e…b594` and `0x61eE…304b`).

## Build (static export for GitHub Pages)

```bash
NEXT_PUBLIC_CONTRACT_ADDRESS=0x... NEXT_PUBLIC_BASE_PATH=/<repo> npm run build
# output is written to ./out and published by GitHub Pages
```

`next.config.mjs` uses `output: "export"`, so there is no server runtime; the
entire app talks to the RPC endpoint directly from the browser.
