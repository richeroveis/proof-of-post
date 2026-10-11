// Focused follow-up: attempt a LIVE verdict-reversing appeal on the deployed
// remediated instance. Content is deliberately ambiguous on word counting
// ("well-known" counts as 1 or 2 words depending on the adjudicator), which is
// the only realistic way to get a NON_COMPLIANT -> COMPLIANT flip from
// independent LLM re-derivation. Whatever consensus decides is recorded as-is.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createClient, createAccount } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";
import { generatePrivateKey } from "viem/accounts";
import { parseEther, formatEther } from "viem";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..");
const ADDR = "0x405e957542856E5f6830EDD40757480BDA8ab594";
const MIN_BOND = 10n ** 18n;

let mainPk = null;
for (const line of fs.readFileSync(path.join(ROOT, ".env"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^\s*GENLAYER_PRIVATE_KEY\s*=\s*(.+?)\s*$/);
  if (m) mainPk = m[1].trim();
}
if (!mainPk.startsWith("0x")) mainPk = "0x" + mainPk;

const mainAcct = createAccount(mainPk);
const subAcct = createAccount(generatePrivateKey());
const mainClient = createClient({ chain: studioDevnet, account: mainAcct });
const subClient = createClient({ chain: studioDevnet, account: subAcct });
console.log("new submitter:", subAcct.address);

const norm = (v) => v instanceof Map ? Object.fromEntries([...v].map(([k, x]) => [k, norm(x)]))
  : Array.isArray(v) ? v.map(norm) : typeof v === "bigint" ? v.toString()
  : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, norm(x)])) : v;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const steps = [];
const rec = (step, data) => { steps.push({ step, ...data }); console.log(`### ${step}`, JSON.stringify(data, null, 1)); };

async function waitDecided(client, hash, label, timeoutMs = 12 * 60_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    await sleep(8000);
    let raw = "";
    try { raw = JSON.stringify(await client.getTransaction({ hash }), (_k, v) => typeof v === "bigint" ? v.toString() : v); } catch {}
    const status = raw.match(/"statusName":\s*"([A-Z_]+)"/)?.[1] ?? "PENDING";
    if (status === "FINALIZED" || status === "UNDETERMINED") {
      let execError = null;
      for (const seg of raw.match(/"[A-Za-z_]*result[A-Za-z_]*":\s*"([A-Za-z0-9+/=]{16,})"/g) ?? []) {
        try {
          const dec = Buffer.from(seg.match(/"([A-Za-z0-9+/=]{16,})"/)[1], "base64").toString("utf8");
          const err = dec.match(/\[(EXPECTED|EXTERNAL|TRANSIENT|LLM_ERROR)\][^"\\]*/);
          if (err) { execError = err[0].slice(0, 200); break; }
        } catch {}
      }
      return { status, execError };
    }
    if (Date.now() > deadline) throw new Error(`${label}: timeout`);
  }
}
async function write(label, client, fn) {
  const est = await client.estimateTransactionFees();
  const hash = await fn(est);
  const res = await waitDecided(client, hash, label);
  rec(label, { hash, ...res });
  return res;
}
const read = async (fn, args) => norm(await mainClient.readContract({ address: ADDR, functionName: fn, args }));

// fund the fresh submitter
{
  const est = await mainClient.estimateTransactionFees();
  const hash = await mainClient.sendTransaction({
    to: subAcct.address, value: parseEther("1.5"),
    fees: { distribution: est.distribution, feeValue: est.feeValue },
  });
  rec("fund", { hash, ...(await waitDecided(mainClient, hash, "fund")) });
}

const RULES = "Must be at most 10 words\nMust mention Jupiter";
const CONTENT = "The well-known observatory team documented four new moons around Jupiter today";

await write("F_submit", subClient, (est) => subClient.writeContract({
  address: ADDR, functionName: "submit", args: ["Word-count edge case", CONTENT, RULES],
  value: MIN_BOND, fees: { distribution: est.distribution, feeValue: est.feeValue },
}));
const stats0 = await read("get_stats", []);
const fId = Number(stats0.total) - 1;

await write("F_evaluate", subClient, (est) => subClient.writeContract({
  address: ADDR, functionName: "evaluate", args: [BigInt(fId)],
  value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
}));
let entry = await read("get_entry", [BigInt(fId)]);
let s = await read("get_stats", []);
rec("F_after_evaluate", { entry_id: fId, status: entry.status, reserved: s.reserved_slashed, deadline: entry.appeal_deadline, tick: s.tick });

if (entry.status === "NON_COMPLIANT") {
  const before = formatEther(await subClient.getBalance({ address: subAcct.address }));
  await write("F_appeal", subClient, (est) => subClient.writeContract({
    address: ADDR, functionName: "appeal", args: [BigInt(fId)],
    value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  await sleep(6000);
  entry = await read("get_entry", [BigInt(fId)]);
  s = await read("get_stats", []);
  rec("F_appeal_result", {
    status: entry.status, appeals: entry.appeal_count,
    slashed_total: s.slashed_total, reserved: s.reserved_slashed, verified: s.verified,
    submitter_before: before, submitter_after: formatEther(await subClient.getBalance({ address: subAcct.address })),
    overturned: entry.status !== "NON_COMPLIANT",
  });
} else {
  rec("F_appeal_result", { skipped: `evaluate returned ${entry.status}; no reversal needed/possible` });
}

// sweep the throwaway's remaining devnet GEN back to the main account
{
  const bal = await subClient.getBalance({ address: subAcct.address });
  const est = await mainClient.estimateTransactionFees();
  const keep = est.feeValue * 2n;
  if (bal > keep) {
    const sweepHash = await subClient.sendTransaction({
      to: mainAcct.address, value: bal - keep,
      fees: { distribution: est.distribution, feeValue: est.feeValue },
    });
    rec("sweep_back", { hash: sweepHash, amount: formatEther(bal - keep), ...(await waitDecided(subClient, sweepHash, "sweep")) });
  }
  rec("final_submitter_balance", formatEther(await subClient.getBalance({ address: subAcct.address })));
}

fs.writeFileSync(path.join(HERE, "evidence-flip.json"), JSON.stringify({ address: ADDR, steps }, null, 2));
console.log("DONE flip attempt");
