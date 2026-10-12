// Independent resubmission verification: re-checks every transaction recorded
// in e2e/evidence.json directly against the studio-dev RPC (genlayer_getTransaction),
// so no live claim rests on the driver's own log. Read-only: no account signs
// anything; contract views are fetched without a signer where possible.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createClient } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const CONTRACT = "0x30A9A1D88E8885319a9f5F259D5C416Bd55d149E";
const client = createClient({ chain: studioDevnet });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ev = JSON.parse(fs.readFileSync(path.join(ROOT, "e2e/evidence.json"), "utf8"));
const steps = [];
const seen = new Set();
for (const s of ev.steps ?? []) {
  const h = s.tx_hash ?? s.hash;
  if (!h || seen.has(h)) continue;
  seen.add(h);
  steps.push({ label: s.step ?? s.label ?? "?", hash: h });
}

// expectations: label -> substring that MUST appear (ok) or MUST NOT (forbid)
const EXPECT = {
  B_withdraw_premature: { must: "Collateral reserved for appeal window" },
  F3_oversized_rules: { must: "Too many rules" },
  C_late_evaluate: { must: "Entry not pending" },
  F7_appeal: { forbid: ["window expired", "liability finalized"] },
};

const decodeHints = (raw) => {
  const found = { err: null, verdicts: [] };
  // 1) classified errors may appear directly in the JSON payload
  const plain = raw.match(/\[(EXPECTED|EXTERNAL|TRANSIENT|LLM_ERROR)\][^"\\]*/);
  if (plain) found.err = plain[0].slice(0, 120);
  // 2) otherwise decode base64 result segments
  const b64s = raw.match(/"[A-Za-z0-9+/=]{20,}"/g) ?? [];
  for (const seg of b64s) {
    if (found.err) break;
    const m = seg.slice(1, -1);
    let dec;
    try { dec = Buffer.from(m, "base64").toString("utf8"); } catch { continue; }
    if (!/^[\x20-\x7e]*$/.test(dec)) continue;
    const err = dec.match(/\[(EXPECTED|EXTERNAL|TRANSIENT|LLM_ERROR)\][^"\\]*/);
    if (err) found.err = err[0].slice(0, 120);
  }
  // verdict strings may be visible in the readable/plain payload or decoded results
  for (const v of ["NON_COMPLIANT", "COMPLIANT", "INCONCLUSIVE", "CANCELLED"]) {
    if (raw.includes(v)) found.verdicts.push(v);
  }
  return found;
};

let failures = 0;
const rows = [];
for (const { label, hash } of steps) {
  let ok = false, status = "?", hint = { err: null, verdicts: [] };
  for (let i = 0; i < 4 && !ok; i++) {
    try {
      const tx = await client.getTransaction({ hash });
      const raw = JSON.stringify(tx, (_k, v) => (typeof v === "bigint" ? v.toString() : v));
      status = raw.match(/"statusName":\s*"([A-Z_]+)"/)?.[1] ?? "PENDING";
      if (status === "FINALIZED" || status === "UNDETERMINED") {
        hint = decodeHints(raw);
        ok = true;
      }
    } catch { await sleep(1500); }
  }
  let verdict = "OK";
  if (!ok) { verdict = "NOT-QUERIED"; failures++; }
  else if (status !== "FINALIZED") { verdict = `BAD:${status}`; failures++; }
  const exp = EXPECT[label];
  if (exp?.must && !(hint.err ?? "").includes(exp.must)) { verdict = `MISSING-ERROR:${hint.err ?? "none"}`; failures++; }
  if (exp?.forbid && exp.forbid.some((f) => (hint.err ?? "").includes(f))) { verdict = `FORBIDDEN:${hint.err}`; failures++; }
  if (label === "F7_appeal" && ok && status === "FINALIZED" && !hint.err) verdict = "OK (appeal executed, no expiry refusal)";
  rows.push({ label, hash: hash.slice(0, 18) + "…", status, err: hint.err, verdict });
}

console.log("\n=== Independent evidence re-check (studio-dev RPC) ===");
for (const r of rows) {
  console.log(
    `${r.verdict === "OK" ? "✓" : "✗"} ${r.label.padEnd(22)} ${r.status.padEnd(9)} ` +
    `${(r.err ?? "").slice(0, 60).padEnd(61)} ${r.verdict === "OK" ? "" : r.verdict}`
  );
}

// ledger snapshot: pull get_stats through the RPC too (view call, no signer)
try {
  const stats = await client.readContract({ address: CONTRACT, functionName: "get_stats", args: [] });
  const normStats = (v) => v instanceof Map ? Object.fromEntries([...v].map(([k, x]) => [k, normStats(x)])) : Array.isArray(v) ? v.map(normStats) : typeof v === "bigint" ? v.toString() : v;
  console.log("\nlive get_stats:", JSON.stringify(normStats(stats), null, 1));
} catch (e) {
  console.log("\nget_stats via RPC failed:", e?.message?.slice(0, 120));
}

console.log(`\nRESULT: ${failures === 0 ? "ALL EVIDENCE INDEPENDENTLY VERIFIED" : failures + " PROBLEM(S)"} (${rows.length} txs checked)`);
process.exit(failures === 0 ? 0 : 1);
