// Minimal liveness probe: send 1 wei owner->owner on studio-dev. If the network
// cannot persist transactions (DiskFull/recovery), this throws immediately.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createClient, createAccount } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";
const HERE = path.dirname(fileURLToPath(import.meta.url));
let pk = null;
for (const line of fs.readFileSync(path.join(HERE, "..", ".env"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^\s*GENLAYER_PRIVATE_KEY\s*=\s*(.+?)\s*$/);
  if (m) pk = m[1].trim();
}
if (!pk) throw new Error("no key");
if (!pk.startsWith("0x")) pk = "0x" + pk;
const acct = createAccount(pk);
const client = createClient({ chain: studioDevnet, account: acct });
const est = await client.estimateTransactionFees();
const hash = await client.sendTransaction({
  to: acct.address, value: 1n,
  fees: { distribution: est.distribution, feeValue: est.feeValue },
});
if (!/^0x[0-9a-f]{64}$/.test(hash)) throw new Error("bad hash " + hash);
console.log("write accepted:", hash);
