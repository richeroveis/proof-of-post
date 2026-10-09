/** @type {import('next').NextConfig} */
const base = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  // Static export for GitHub Pages. All chain data is fetched at runtime in
  // the browser via the GenLayer JSON-RPC endpoint; there is no server runtime.
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
  basePath: base,
  assetPrefix: base ? base + "/" : undefined,
  env: {
    NEXT_PUBLIC_CONTRACT_ADDRESS: process.env.NEXT_PUBLIC_CONTRACT_ADDRESS || "",
    NEXT_PUBLIC_GENLAYER_RPC: process.env.NEXT_PUBLIC_GENLAYER_RPC || "https://studio-dev.genlayer.com/api",
    NEXT_PUBLIC_GENLAYER_CHAIN_ID: process.env.NEXT_PUBLIC_GENLAYER_CHAIN_ID || "61997",
    NEXT_PUBLIC_BASE_PATH: base,
  },
};

export default nextConfig;
