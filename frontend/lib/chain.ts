import { studionet } from "genlayer-js/chains";

// studio-dev ("GenLayer Studio Next / dev", chainId 61997) is NOT a built-in
// chain in genlayer-js. We derive it from `studionet` exactly the way the
// official GenLayer CLI does: same infrastructure and consensus contract
// addresses (inherited via the spread), overriding only the id, name, RPC host,
// and clearing the block explorer (the stable explorer does not index this
// preview deployment). This avoids hand-inventing any contract address.
const STUDIO_DEV_RPC = "https://studio-dev.genlayer.com/api";

export const studioDev = {
  ...studionet,
  id: 61997,
  name: "GenLayer Studio Devnet",
  rpcUrls: {
    default: { http: [STUDIO_DEV_RPC] },
    public: { http: [STUDIO_DEV_RPC] },
  },
  blockExplorers: undefined,
} as const;

export const STUDIO_DEV_CHAIN_ID = 61997;
