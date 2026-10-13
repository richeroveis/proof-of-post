// Independent evidence verification against the studio-dev RPC.
//
// Usage:
//   node verify_evidence.mjs                    -> e2e/evidence.json (legacy mode)
//   node verify_evidence.mjs <evidence.json>    -> any evidence file; if it
//                                                   carries an "expectations"
//                                                   section, those are enforced
// Read-only: no wallet operations, nothing is signed, no secrets are printed.
// Every claim in the evidence file is re-checked by querying the chain itself,
// so no assertion rests on the driver script's own log.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createClient } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const fileArg = process.argv[2];
const EV_PATH = fileArg
  ? (path.isAbsolute(fileArg) ? fileArg : path.join(ROOT, fileArg))
  : path.join(ROOT, "e2e/evidence.json");
const client = createClient({ chain: studioDevnet });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ev = JSON.parse(fs.readFileSync(EV_PATH, "utf8"));

// Legacy expectations for e2e/evidence.json (label-keyed)
const LEGACY_EXPECT = {
  B_withdraw_premature: { must: "Collateral reserved for appeal window" },
  F3_oversized_rules: { must: "Too many rules" },
  C_late_evaluate: { must: "Entry not pending" },
  F7_appeal: { forbid: ["window expired", "liability finalized"] },
};

function payloadHints(raw) {
  const found = { err: null, verdicts: [], hasAny: false };
  const plain = raw.match(/\[(EXPECTED|EXTERNAL|TRANSIENT|LLM_ERROR)\][^"\\]*/);
  if (plain) { found.err = plain[0].slice(0, 140); found.hasAny = true; }
  const b64s = raw.match(/"[A-Za-z0-9+/=]{20,}"/g) ?? [];
  for (const seg of b64s) {
    const m = seg.slice(1, -1);
    let dec;
    try { dec = Buffer.from(m, "base64").toString("utf8"); } catch { continue; }
    if (!/^[\x20-\x7e]*$/.test(dec)) continue;
    const err = dec.match(/\[(EXPECTED|EXTERNAL|TRANSIENT|LLM_ERROR)\][^"\\]*/);
    if (err && !found.err) { found.err = err[0].slice(0, 140); found.hasAny = true; }
    for (const v of ["NON_COMPLIANT", "COMPLIANT", "INCONCLUSIVE", "CANCELLED"]) {
      if (dec.includes(v) && !found.verdicts.includes(v)) found.verdicts.push(v);
    }
  }
  for (const v of ["NON_COMPLIANT", "COMPLIANT", "INCONCLUSIVE", "CANCELLED"]) {
    if (raw.includes(v) && !found.verdicts.includes(v)) found.verdicts.push(v);
  }
  return found;
}

async function queryTx(hash) {
  for (let i = 0; i < 5; i++) {
    try {
      const tx = await client.getTransaction({ hash });
      const raw = JSON.stringify(tx, (_k, v) => (typeof v === "bigint" ? v.toString() : v));
      const status = raw.match(/"statusName":\s*"([A-Z_]+)"/)?.[1] ?? "PENDING";
      if (status === "FINALIZED" || status === "UNDETERMINED") return { status, raw, hints: payloadHints(raw) };
    } catch { /* retry */ }
    await sleep(1500);
  }
  return { status: "NOT-QUERYABLE", raw: "", hints: { err: null, verdicts: [], hasAny: false } };
}

let failures = 0;
const fail = (msg) => { failures++; console.log("  FAIL " + msg); };

const norm = (v) =>
  v instanceof Map ? Object.fromEntries([...v].map(([k, x]) => [k, norm(x)]))
  : Array.isArray(v) ? v.map(norm)
  : typeof v === "bigint" ? v.toString()
  : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, norm(x)]))
  : v;

if (ev.expectations?.txs) {
  // ---------- generic mode: evidence carries its own expectations ----------
  console.log(`=== Independent verification: ${path.basename(EV_PATH)} ===`);
  console.log(`contract: ${ev.address ?? "?"} | network: ${ev.network} | source sha256: ${(ev.contractSourceSha256 ?? "").slice(0, 16)}...`);
  for (const t of ev.expectations.txs) {
    const { status, hints } = await queryTx(t.hash);
    let ok = status === "FINALIZED";                 // UNDETERMINED is NOT success
    if (!ok) fail(`${t.label}: status ${status}`);
    for (const f of t.forbid ?? []) {
      if ((hints.err ?? "").includes(f)) fail(`${t.label}: forbidden payload "${f}" (${hints.err})`);
    }
    if (t.verdict_contains && !hints.verdicts.includes(t.verdict_contains)) {
      fail(`${t.label}: verdict "${t.verdict_contains}" not found (saw: ${hints.verdicts.join("/") || "none"})`);
    }
    console.log(`  ${ok ? "ok" : "XX"} ${t.label.padEnd(16)} ${status.padEnd(9)} ${(hints.err ?? "").slice(0, 60)}`);
  }
  const fin = ev.expectations.final;
  if (ev.success && fin) {
    const entry = norm(await client.readContract({ address: fin.address, functionName: "get_entry", args: [BigInt(fin.entry_id)] }));
    if (entry.status !== fin.expect_status) fail(`final readback: status ${entry.status} != ${fin.expect_status}`);
    if (entry.appeal_deadline !== fin.expect_appeal_deadline) fail(`final readback: deadline ${entry.appeal_deadline} != ${fin.expect_appeal_deadline}`);
    if (Number(entry.appeal_count) < Number(fin.expect_appeal_count_min)) fail(`final readback: appeal_count ${entry.appeal_count} < ${fin.expect_appeal_count_min}`);
    const s = norm(await client.readContract({ address: fin.address, functionName: "get_stats", args: [] }));
    const big = (x) => BigInt(x ?? "0");
    if (big(s.slashed_total) < big(s.withdrawn_slashed) + big(s.reserved_slashed)) fail("conservation invariant violated on live readback");
    console.log(`  final readback: status=${entry.status} appeals=${entry.appeal_count} deadline=${entry.appeal_deadline} | slashed=${s.slashed_total} reserved=${s.reserved_slashed} withdrawn=${s.withdrawn_slashed} verified=${s.verified}`);
  } else if (ev.success !== true) {
    console.log("  note: evidence.success=false -> no final-state expectations to verify");
  }
} else {
  // ---------- legacy mode: e2e/evidence.json with driver-recorded steps ------
  console.log(`=== Independent evidence re-check (studio-dev RPC): ${path.basename(EV_PATH)} ===`);
  const seen = new Set();
  const rows = [];
  for (const s of ev.steps ?? []) {
    const hash = s.tx_hash ?? s.hash;
    if (!hash || seen.has(hash)) continue;
    seen.add(hash);
    const label = s.step ?? s.label ?? "?";
    const { status, hints } = await queryTx(hash);
    let verdict = "OK";
    if (status !== "FINALIZED") { verdict = `BAD:${status}`; failures++; }
    const exp = LEGACY_EXPECT[label];
    if (exp?.must && !(hints.err ?? "").includes(exp.must)) { verdict = `MISSING-ERROR:${hints.err ?? "none"}`; failures++; }
    if (exp?.forbid && exp.forbid.some((f) => (hints.err ?? "").includes(f))) { verdict = `FORBIDDEN:${hints.err}`; failures++; }
    rows.push(`${verdict === "OK" ? "✓" : "✗"} ${label.padEnd(22)} ${status.padEnd(9)} ${(hints.err ?? "").slice(0, 60)}${verdict === "OK" ? "" : "  " + verdict}`);
  }
  rows.forEach((r) => console.log(r));
  try {
    const stats = norm(await client.readContract({ address: "0x30A9A1D88E8885319a9f5F259D5C416Bd55d149E", functionName: "get_stats", args: [] }));
    console.log("\nlive get_stats:", JSON.stringify(stats));
  } catch (e) { console.log("\nget_stats failed:", String(e?.message).slice(0, 100)); }
}

console.log(`\nRESULT: ${failures === 0 ? "ALL EXPECTATIONS INDEPENDENTLY VERIFIED" : failures + " PROBLEM(S)"} for ${path.basename(EV_PATH)}`);
process.exit(failures === 0 ? 0 : 1);
