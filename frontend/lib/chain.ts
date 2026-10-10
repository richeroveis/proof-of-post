import { studioDevnet } from "genlayer-js/chains";

// studio-dev ("GenLayer Studio Devnet", chainId 61997) is now a BUILT-IN chain of
// genlayer-js 2.x, so we use the SDK's own definition instead of hand-deriving one
// from `studionet` (which is what we had to do with genlayer-js 1.1.8). Using the
// built-in keeps the infrastructure / consensus contract addresses and fee-policy
// metadata exactly as the SDK and official CLI configure them, instead of trusting
// values copied from a sibling chain.
export const studioDev = studioDevnet;

export const STUDIO_DEV_RPC = studioDevnet.rpcUrls.default.http[0];
export const STUDIO_DEV_CHAIN_ID = studioDevnet.id;
