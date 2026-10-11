// Read-only: recover a deployed contract address from its deploy tx and verify
// live views. Takes a deploy tx hash as argv[2]. No new transaction, no cost.
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
if (pk && !pk.startsWith("0x")) pk = "0x" + pk;

const account = createAccount(pk);
const client = createClient({ chain: studioDevnet, account });
const norm = (v) =>
  v instanceof Map ? Object.fromEntries([...v].map(([k, x]) => [k, norm(x)]))
  : Array.isArray(v) ? v.map(norm)
  : typeof v === "bigint" ? v.toString()
  : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, norm(x)]))
  : v;

const hash = process.argv[2];
const tx = await client.getTransaction({ hash });
const address = tx.contract_address || tx.to_address;
process.stdout.write("deploy tx " + hash + "\n");
process.stdout.write("contract  " + address + "\n");
const stats = norm(await client.readContract({ address, functionName: "get_stats", args: [] }));
process.stdout.write("get_stats " + JSON.stringify(stats) + "\n");
const list = norm(await client.readContract({ address, functionName: "list_entries", args: [0n, 5n] }));
process.stdout.write("list_entries " + JSON.stringify(list) + "\n");
