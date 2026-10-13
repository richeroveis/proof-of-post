// Health probe: deploy a trivial pinned-runner contract holding no funds.
// If the network cannot persist a deploy-class payload, this throws.
import { createClient, createAccount } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
const HERE = path.dirname(fileURLToPath(import.meta.url));
let pk = null;
for (const line of fs.readFileSync(path.join(HERE, "..", ".env"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^\s*GENLAYER_PRIVATE_KEY\s*=\s*(.+?)\s*$/);
  if (m) pk = m[1].trim();
}
if (!pk) throw new Error("no key");
if (!pk.startsWith("0x")) pk = "0x" + pk;
const code = '# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }\nfrom genlayer import *\n\nclass Probe(gl.Contract):\n    def ping(self) -> int:\n        return 1\n';
const acct = createAccount(pk);
const client = createClient({ chain: studioDevnet, account: acct });
const est = await client.estimateTransactionFees();
const hash = await client.deployContract({
  code, args: [], fees: { distribution: est.distribution, feeValue: est.feeValue },
});
if (!/^0x[0-9a-f]{64}$/.test(hash)) throw new Error("deploy probe rejected: " + hash);
// and it must become queryable (proves the big INSERT persisted)
for (let i = 0; i < 10; i++) {
  await new Promise((r) => setTimeout(r, 6000));
  try {
    const t = await client.getTransaction({ hash });
    const s = JSON.stringify(t).match(/"statusName":\s*"([A-Z_]+)"/)?.[1];
    if (s) { console.log("deploy probe", s); if (s === "FINALIZED" || s === "UNDETERMINED") process.exit(0); }
  } catch { /* keep polling */ }
}
throw new Error("deploy probe not queryable");
