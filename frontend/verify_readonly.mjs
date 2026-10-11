// Read-only live verification of the deployed RuleRegistry on studio-dev.
// Prints the signer ADDRESS and balances only — never the private key.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createClient, createAccount } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";
import { formatEther } from "viem";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
let pk = null;
for (const line of fs.readFileSync(path.join(ROOT, ".env"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^\s*GENLAYER_PRIVATE_KEY\s*=\s*(.+?)\s*$/);
  if (m) pk = m[1].trim();
}
if (!pk) throw new Error("no GENLAYER_PRIVATE_KEY in .env");
if (!pk.startsWith("0x")) pk = "0x" + pk;

const CONTRACT = "0x30A9A1D88E8885319a9f5F259D5C416Bd55d149E";
const account = createAccount(pk);
const client = createClient({ chain: studioDevnet, account });
const norm = (v) =>
  v instanceof Map ? Object.fromEntries([...v].map(([k, x]) => [k, norm(x)]))
  : Array.isArray(v) ? v.map(norm)
  : typeof v === "bigint" ? v.toString()
  : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, norm(x)]))
  : v;

console.log("signer address:", account.address);
const bal = await client.getBalance({ address: account.address });
console.log("signer balance:", formatEther(bal), "GEN");

const minBond = norm(await client.readContract({ address: CONTRACT, functionName: "get_min_bond", args: [] }));
console.log("get_min_bond:", minBond, "->", formatEther(BigInt(minBond)), "GEN");

const stats = norm(await client.readContract({ address: CONTRACT, functionName: "get_stats", args: [] }));
console.log("get_stats:", JSON.stringify(stats));

const entries = norm(await client.readContract({ address: CONTRACT, functionName: "list_entries", args: [0n, 20n] }));
console.log("list_entries:", JSON.stringify(entries, null, 1));

try {
  const est = await client.estimateTransactionFees();
  console.log("fee quote:", formatEther(est.feeValue), "GEN", "distribution:", JSON.stringify(est.distribution));
} catch (e) {
  console.log("fee estimate failed:", String(e?.message || e));
}
