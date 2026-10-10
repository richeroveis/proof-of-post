// Phase 10 bounded studio-dev verification for the two standalone contracts.
//
// Deploys each contract (constructor only -> deterministic, no LLM/web, so it
// converges reliably and cheaply), waits for FINALIZED, reads the deployed
// address back from the receipt, and verifies read-only views against the live
// GenVM state. Non-deterministic verdict settlement (resolve/grade) is covered
// by the direct-mode suite and is deliberately NOT executed here to avoid
// spending GEN on shared-validator consensus that may not converge.
//
// Lives under frontend/ so it resolves the same genlayer-js 2.0.0-rc.1 that the
// dashboard uses. Never prints the private key.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createClient, createAccount } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");

let pk = null;
for (const line of fs.readFileSync(path.join(ROOT, ".env"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^\s*GENLAYER_PRIVATE_KEY\s*=\s*(.+?)\s*$/);
  if (m) pk = m[1].trim();
}
if (!pk) throw new Error("GENLAYER_PRIVATE_KEY missing in .env");
if (!pk.startsWith("0x")) pk = "0x" + pk;

const MIN_BOND = 10n ** 18n; // 1 GEN

const normalize = (v) =>
  v instanceof Map ? Object.fromEntries([...v].map(([k, x]) => [k, normalize(x)]))
  : Array.isArray(v) ? v.map(normalize)
  : typeof v === "bigint" ? v.toString()
  : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, normalize(x)]))
  : v;

const account = createAccount(pk);
const client = createClient({ chain: studioDevnet, account });

async function waitDecided(hash, maxMin = 10) {
  const deadline = Date.now() + maxMin * 60_000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 10_000));
    let raw;
    try {
      raw = JSON.stringify(await client.getTransaction({ hash }), (_k, v) => (typeof v === "bigint" ? v.toString() : v));
    } catch (e) {
      process.stdout.write("  poll err " + (e?.shortMessage || e?.message || e) + "\n");
      continue;
    }
    const status = (raw.match(/"statusName":"([A-Z_]+)"/) || [])[1] || "?";
    process.stdout.write(`  ${String(hash).slice(0, 10)}... ${status}\n`);
    if (status === "FINALIZED" || status === "UNDETERMINED") return status;
  }
  return "TIMEOUT";
}

async function verifyAt(name, address) {
  const stats = normalize(await client.readContract({ address, functionName: "get_stats", args: [] }));
  const minBond = normalize(await client.readContract({ address, functionName: "get_min_bond", args: [] }));
  process.stdout.write("  contract " + address + "\n");
  process.stdout.write("  get_stats " + JSON.stringify(stats) + "\n");
  process.stdout.write("  get_min_bond " + JSON.stringify(minBond) + "\n");
  return { name, address, status: "FINALIZED", stats, minBond };
}

// genlayer-js 2.0.0-rc.1 does not populate a camelCase `contractAddress` for a
// deploy: the deployed IC lives at the deploy transaction's `to_address` (also
// echoed as the snake_case `contract_address` on getTransaction).
function deployedAddress(receipt, tx) {
  return receipt?.to_address || tx?.contract_address || receipt?.contract_address || tx?.to_address;
}

async function deployAndVerify(name, file) {
  process.stdout.write(`\n==== ${name} (${file})\n`);
  const code = fs.readFileSync(path.join(ROOT, file), "utf8");
  const est = await client.estimateTransactionFees();
  const hash = await client.deployContract({
    code,
    args: [MIN_BOND],
    fees: { distribution: est.distribution, feeValue: est.feeValue },
  });
  process.stdout.write("  deploy tx " + hash + "\n");
  const status = await waitDecided(hash);
  if (status !== "FINALIZED") {
    process.stdout.write(`  RESULT ${name}: deploy ${status} (not finalized)\n`);
    return { name, status: "DEPLOY_" + status };
  }
  const receipt = await client.waitForTransactionReceipt({ hash, waitUntil: "finalized" });
  const tx = await client.getTransaction({ hash });
  const address = deployedAddress(receipt, tx);
  return verifyAt(name, address);
}

const results = [];
// EvidenceOracle was already deployed + FINALIZED this run; verify its live reads
// instead of paying for a redundant redeploy.
const EXISTING_ORACLE = "0xc315465D70D377CDB078aB0117C011d46A288E1F";
try {
  process.stdout.write(`\n==== EvidenceOracle (verifying existing ${EXISTING_ORACLE})\n`);
  results.push(await verifyAt("EvidenceOracle", EXISTING_ORACLE));
} catch (e) {
  process.stdout.write("  verify err " + (e?.shortMessage || e?.message || e) + "\n");
  results.push({ name: "EvidenceOracle", status: "VERIFY_ERROR" });
}
results.push(await deployAndVerify("ScoreRegistry", "standalone/score-registry/contract.py"));

fs.writeFileSync(path.join(__dirname, "deploy_standalone_results.json"), JSON.stringify(results, null, 2));
process.stdout.write("\nDONE\n");
