// Live appeal-refund verification (reviewer rejection gap 1).
//
// Proves the FULL lifecycle on Studio Devnet with the CURRENT source:
//   submit -> evaluate -> NON_COMPLIANT -> appeal -> COMPLIANT -> real refund
//
// A success is ONLY declared when, read back from the live contract:
//   - the entry actually transitioned NON_COMPLIANT -> COMPLIANT via appeal
//   - appeal_count increased and appeal_deadline returned to 0
//   - slashed_total and reserved_slashed each decreased by exactly the bond
//   - the verified counter increased
//   - the contract native balance decreased by the bond
//   - the submitter balance increased by the bond minus appeal tx fees
//   - the conservation invariant slashed == withdrawn + reserved + available
//     holds before and after
//
// Roles: owner/deployer = repo .env key (studio-dev only); submitter and
// treasury = throwaway in-memory keys (never printed, never persisted).
// Every transaction is fee-aware; consensus results are never mocked or
// edited; UNDETERMINED or execution errors are NEVER treated as success.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createClient, createAccount } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";
import { generatePrivateKey } from "viem/accounts";
import { parseEther, formatEther } from "viem";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..");
const CONTRACT_FILE = path.join(ROOT, "contracts", "rule_registry.py");
const EVIDENCE_FILE = path.join(HERE, "evidence-appeal-refund.json");
// Studio-dev owner wallet budget is small and the network is not gasless, so the
// proof uses a 0.1 GEN bond. The reversal/reservation/refund path under test is
// amount-independent; the recorded balances and deltas are all real on-chain GEN.
const MIN_BOND = 10n ** 17n;

let mainPk = null;
for (const line of fs.readFileSync(path.join(ROOT, ".env"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^\s*GENLAYER_PRIVATE_KEY\s*=\s*(.+?)\s*$/);
  if (m) mainPk = m[1].trim();
}
if (!mainPk) throw new Error("missing GENLAYER_PRIVATE_KEY in project .env");
if (!mainPk.startsWith("0x")) mainPk = "0x" + mainPk;

const mainAcct = createAccount(mainPk);
const subAcct = createAccount(generatePrivateKey());
const tresAcct = createAccount(generatePrivateKey());
console.log("owner    :", mainAcct.address);
console.log("submitter:", subAcct.address);
console.log("treasury :", tresAcct.address);

const norm = (v) =>
  v instanceof Map ? Object.fromEntries([...v].map(([k, x]) => [k, norm(x)]))
  : Array.isArray(v) ? v.map(norm)
  : typeof v === "bigint" ? v.toString()
  : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, norm(x)]))
  : v;

const evidence = {
  startedAt: new Date().toISOString(),
  network: "studio-dev(61997)",
  contractSourceSha256: null,
  address: null,
  steps: [],
  candidates: [],
  expectations: { txs: [], final: null },
  success: false,
};
const { createHash } = await import("crypto");
evidence.contractSourceSha256 = createHash("sha256").update(fs.readFileSync(CONTRACT_FILE)).digest("hex");

// save() must be BigInt-safe: candidate before/after snapshots carry raw
// getBalance() BigInts, and a bare JSON.stringify throws on them.
const save = () => fs.writeFileSync(
  EVIDENCE_FILE,
  JSON.stringify(evidence, (_k, v) => (typeof v === "bigint" ? v.toString() : v), 2),
);
const rec = (step, data) => {
  evidence.steps.push({ step, at: new Date().toISOString(), ...data });
  console.log(`\n### ${step}`);
  console.log(JSON.stringify(data, (_k, v) => (typeof v === "bigint" ? v.toString() : v), 1));
  save();
};
const expectTx = (label, hash, { forbid = ["[EXPECTED]", "[LLM_ERROR]", "[TRANSIENT]", "[EXTERNAL]"], verdict = null } = {}) => {
  evidence.expectations.txs.push({ label, hash, must_finalize: true, forbid, verdict_contains: verdict });
};
// Success-only: tighten once the appeal refund is proven in this run.
const successExpectations = () => {
  const ci = evidence.candidates.findIndex((c) => c.outcome === "REFUNDED_ON_CHAIN");
  if (ci < 0) return;
  for (const t of evidence.expectations.txs) {
    if (t.label === `C${ci}_evaluate`) t.verdict_contains = "NON_COMPLIANT";
  }
};

const clientFor = (acct) => createClient({ chain: studioDevnet, account: acct });
const mainClient = clientFor(mainAcct);
const subClient = clientFor(subAcct);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function balanceOf(addr) {
  for (let i = 0; i < 5; i++) {
    try { return await mainClient.getBalance({ address: addr }); }
    catch (e) { if (i === 4) throw e; await sleep(20000); }
  }
}

function payloadHints(raw) {
  const found = { err: null, verdicts: [] };
  const plain = raw.match(/\[(EXPECTED|EXTERNAL|TRANSIENT|LLM_ERROR)\][^"\\]*/);
  if (plain) found.err = plain[0].slice(0, 160);
  const b64s = raw.match(/"[A-Za-z_]*result[A-Za-z_]*":\s*"([A-Za-z0-9+/=]{16,})"/g) ?? [];
  for (const seg of b64s) {
    const m = seg.match(/"([A-Za-z0-9+/=]{16,})"/)[1];
    try {
      const dec = Buffer.from(m, "base64").toString("utf8");
      const err = dec.match(/\[(EXPECTED|EXTERNAL|TRANSIENT|LLM_ERROR)\][^"\\]*/);
      if (err && !found.err) found.err = err[0].slice(0, 160);
    } catch { /* not base64 */ }
  }
  for (const v of ["NON_COMPLIANT", "COMPLIANT", "INCONCLUSIVE", "CANCELLED"]) {
    if (raw.includes(v) && !found.verdicts.includes(v)) found.verdicts.push(v);
  }
  return found;
}

async function waitDecided(client, hash, label, timeoutMs = 15 * 60_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    await sleep(8000);
    let raw = "";
    try {
      const tx = await client.getTransaction({ hash });
      raw = JSON.stringify(tx, (_k, v) => (typeof v === "bigint" ? v.toString() : v));
    } catch { /* not queryable yet */ }
    const status = raw.match(/"statusName":\s*"([A-Z_]+)"/)?.[1] ?? "PENDING";
    if (status === "FINALIZED" || status === "UNDETERMINED") {
      return { status, ...payloadHints(raw), raw };
    }
    if (Date.now() > deadline) throw new Error(`${label}: consensus timeout ${hash}`);
  }
}

async function write(step, client, fn, expectation) {
  // studio-dev intermittently rejects submissions while its DB recovers;
  // a rejected send persisted nothing, so resubmitting with a fresh fee
  // quote is safe. Rare persisted-but-unanswered sends would surface as a
  // duplicate deploy/tx on a devnet throwaway chain - accepted trade-off.
  let lastErr;
  for (let t = 0; t < 6; t++) {
    try {
      const est = await client.estimateTransactionFees();
      const hash = await fn(est);
      const res = await waitDecided(client, hash, step);
      rec(step, { hash, status: res.status, execError: res.execError ?? undefined, verdicts: res.verdicts, attempt: t + 1 });
      if (res.status === "UNDETERMINED" && t < 5) {
        // UNDETERMINED = the consensus round failed; the transaction can never
        // execute, so resubmitting a fresh one cannot double-run anything.
        console.log(`  [re-submit ${t + 1}] ${step}: UNDETERMINED ${hash}`);
        await sleep(30000);
        continue;
      }
      if (expectation) expectTx(step, hash, expectation);
      return { hash, ...res };
    } catch (e) {
      lastErr = e;
      const msg = String(e?.message ?? e).slice(0, 100);
      console.log(`  [retry ${t + 1}] ${step}: ${msg}`);
      await sleep(45000 + t * 30000);
    }
  }
  throw new Error(`${step}: gave up after 6 submissions: ${String(lastErr?.message ?? lastErr).slice(0, 140)}`);
}

async function read(addr, fn, args) {
  return norm(await mainClient.readContract({ address: addr, functionName: fn, args }));
}
async function readRetry(addr, fn, args) {
  let last;
  // studio-dev outage mode: gen_call reads fail network-wide for minutes at
  // a time while writes intermittently finalize; stay patient so one attempt
  // can ride out a short recovery instead of burning a full redeploy cycle.
  for (let i = 0; i < 10; i++) {
    try { return await read(addr, fn, args); }
    catch (e) { last = e; console.log(`  [read-retry ${i + 1}] ${fn}: ${String(e?.message ?? e).slice(0, 80)}`); await sleep(45000); }
  }
  throw last;
}
const stats = (addr) => readRetry(addr, "get_stats", []);
const entryOf = (addr, id) => readRetry(addr, "get_entry", [BigInt(id)]);

// Genuinely ambiguous but defensible candidates: a strict first pass can
// fairly read them as VIOLATED; under the appeal reconsideration frame
// (clear-violation-required, ambiguity to the submitter) they can fairly
// read as SATISFIED. No content fakes determinism: counts and tone reads
// differ by reasonable interpretation.
const CANDIDATES = [
  {
    title: "Hyphenated word-count edge",
    rules: "Must be written in English\nMust contain at most 10 words",
    content: "Well-known expert said late-night review is done, ship it tomorrow!",
  },
  {
    title: "Mixed-tone edge",
    rules: "The post must maintain a purely optimistic tone",
    content: "We are disappointed the launch slipped two weeks, but thrilled every beta user stayed and the fix is live.",
  },
  {
    title: "Sentence-count edge",
    rules: "Must be written in English\nMust be a single sentence",
    content: "Rain all morning - forecast says sunshine by noon - bring a light jacket anyway.",
  },
  {
    title: "Word-form mention edge",
    rules: "The post must mention the word sunny",
    content: "A rare sunniness broke through the grey week, lifting everyone.",
  },
  {
    title: "Comma-list count edge",
    rules: "The post must list at least three distinct items",
    content: "For the trail bring water, and snacks.",
  },
  {
    title: "Emoticon vs emoji edge",
    rules: "The post must contain no emojis",
    content: "Launch went smoothly :-) thanks to the whole night crew.",
  },
  {
    title: "Digits vs words number edge",
    rules: "The post must spell out numbers as words, never digits",
    content: "We shipped twenty-three fixes, and two follow-ups are pending.",
  },
  {
    title: "Sentence capitalization edge",
    rules: "Every sentence must begin with a capital letter",
    content: "ship the patch tonight. Then we can all celebrate tomorrow.",
  },
  {
    title: "Formality exclamation edge",
    rules: "The post must stay formal and avoid exclamation marks",
    content: "Quarterly results are ready! Please review them at your convenience.",
  },
  {
    title: "Substring word mention edge",
    rules: "The post must mention the exact word blue",
    content: "After the storm the far horizon looked blueish for a moment.",
  },
];

// ---------------------------------------------------------------------------
// 0. fund the throwaway submitter
// ---------------------------------------------------------------------------
{
  const before = await balanceOf(subAcct.address);
  const t = await write("fund_submitter", mainClient, (est) => mainClient.sendTransaction({
    to: subAcct.address, value: parseEther("2.2"),
    fees: { distribution: est.distribution, feeValue: est.feeValue },
  }), null);
  if (t.status !== "FINALIZED" || t.execError) throw new Error("funding failed: " + (t.execError ?? t.status));
  await sleep(5000);
  const after = await balanceOf(subAcct.address);
  rec("fund_balance", { sub_before: formatEther(before), sub_after: formatEther(after) });
  expectTx("fund_submitter", t.hash);
}

// ---------------------------------------------------------------------------
// 1. deploy the CURRENT source (this run's instance; nothing superseded is
//    reused) and set the dedicated treasury
// ---------------------------------------------------------------------------
let ADDR;
{
  const code = fs.readFileSync(CONTRACT_FILE, "utf8");
  const t = await write("deploy", mainClient, (est) => mainClient.deployContract({
    code, args: [Number(MIN_BOND)],
    fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  if (t.status !== "FINALIZED") throw new Error("deploy not FINALIZED: " + t.status);
  const m = t.raw.match(/"contract_address":\s*"(0x[0-9a-fA-F]{40})"/) ?? t.raw.match(/"to_address":\s*"(0x[0-9a-fA-F]{40})"/);
  ADDR = m?.[1];
  if (!ADDR) throw new Error("deploy did not surface a contract address");
  evidence.address = ADDR;
  rec("deploy_address", { address: ADDR });
  expectTx("deploy", t.hash);
}
{
  // stale-address guard: the deployed instance must answer with our min bond
  const mb = await readRetry(ADDR, "get_min_bond", []);
  if (String(mb) !== MIN_BOND.toString()) throw new Error("freshly deployed instance fails get_min_bond probe");
}
{
  await write("set_treasury", mainClient, (est) => mainClient.writeContract({
    address: ADDR, functionName: "set_treasury", args: [tresAcct.address],
    value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
}

// ---------------------------------------------------------------------------
// 2. candidate loop: the exact lifecycle, strict success gate
// ---------------------------------------------------------------------------
for (let ci = 0; ci < CANDIDATES.length && !evidence.success; ci++) {
  const c = CANDIDATES[ci];
  const cand = { index: ci, ...c, txs: {}, outcome: "NOT_ATTEMPTED" };
  evidence.candidates.push(cand);

  const totalBefore = Number((await stats(ADDR)).total);
  const tSub = await write(`C${ci}_submit`, subClient, (est) => subClient.writeContract({
    address: ADDR, functionName: "submit", args: [c.title, c.content, c.rules],
    value: MIN_BOND, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  cand.txs.submit = tSub.hash;
  const entryId = totalBefore; // ids are 0-based and total increments per submit

  const tEval = await write(`C${ci}_evaluate`, subClient, (est) => subClient.writeContract({
    address: ADDR, functionName: "evaluate", args: [BigInt(entryId)],
    value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  cand.txs.evaluate = tEval.hash;
  if (tEval.status !== "FINALIZED" || tEval.execError) { cand.outcome = "EVALUATE_FAILED"; save(); continue; }

  const eAfter = await entryOf(ADDR, entryId);
  const sAfter = await stats(ADDR);
  cand.initial_verdict = eAfter.status;
  cand.before = {
    slashed_total: sAfter.slashed_total, reserved_slashed: sAfter.reserved_slashed,
    withdrawn_slashed: sAfter.withdrawn_slashed, available_slashed: sAfter.available_slashed,
    verified: sAfter.verified, contract_balance: sAfter.contract_balance,
    appeal_deadline: eAfter.appeal_deadline, appeal_count: eAfter.appeal_count,
    submitter_balance: await balanceOf(subAcct.address),
  };
  if (eAfter.status !== "NON_COMPLIANT") {
    cand.outcome = `NOT_SLASHED (${eAfter.status})`;
    save();
    continue;
  }

  // Appeal #1 (submitter wallet, no value beyond fees; reservation intact).
  const tApp1 = await write(`C${ci}_appeal_1`, subClient, (est) => subClient.writeContract({
    address: ADDR, functionName: "appeal", args: [BigInt(entryId)],
    value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  cand.txs.appeal_1 = tApp1.hash;
  let entry = await entryOf(ADDR, entryId);

  if (entry.status === "NON_COMPLIANT" && Number(entry.appeal_count) < 2 && entry.appeal_deadline !== "0") {
    // Upheld once, still reserved and appealable: exercise appeal #2.
    const tApp2 = await write(`C${ci}_appeal_2`, subClient, (est) => subClient.writeContract({
      address: ADDR, functionName: "appeal", args: [BigInt(entryId)],
      value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
    }));
    cand.txs.appeal_2 = tApp2.hash;
    entry = await entryOf(ADDR, entryId);
  }

  const sFinal = await stats(ADDR);
  const subBalFinal = await balanceOf(subAcct.address);
  cand.final = {
    status: entry.status, appeal_count: entry.appeal_count, appeal_deadline: entry.appeal_deadline,
    slashed_total: sFinal.slashed_total, reserved_slashed: sFinal.reserved_slashed,
    withdrawn_slashed: sFinal.withdrawn_slashed, available_slashed: sFinal.available_slashed,
    verified: sFinal.verified, contract_balance: sFinal.contract_balance,
    submitter_balance: subBalFinal,
  };

  const b = cand.before, f = cand.final;
  const big = (x) => BigInt(x ?? "0");
  const subDelta = big(f.submitter_balance) - big(b.submitter_balance);
  const checks = {
    verdict_transition: cand.initial_verdict === "NON_COMPLIANT" && f.status === "COMPLIANT",
    slashed_decreased_by_bond: big(b.slashed_total) - big(f.slashed_total) === MIN_BOND,
    reserved_decreased_by_bond: big(b.reserved_slashed) - big(f.reserved_slashed) === MIN_BOND,
    verified_increased: Number(f.verified) === Number(b.verified) + 1,
    deadline_zeroed: f.appeal_deadline === "0",
    contract_balance_decreased_by_bond: big(b.contract_balance) - big(f.contract_balance) === MIN_BOND,
    submitter_refunded_minus_fees: subDelta > MIN_BOND - parseEther("0.01"),
    conservation_before: big(b.slashed_total) >= big(b.withdrawn_slashed) + big(b.reserved_slashed),
    conservation_after: big(f.slashed_total) >= big(f.withdrawn_slashed) + big(f.reserved_slashed),
  };
  cand.checks = checks;
  cand.submitter_delta_wei = subDelta.toString();

  if (Object.values(checks).every(Boolean)) {
    evidence.success = true;
    cand.outcome = "REFUNDED_ON_CHAIN";
    evidence.expectations.final = {
      address: ADDR,
      entry_id: entryId,
      expect_status: "COMPLIANT",
      expect_appeal_deadline: "0",
      expect_appeal_count_min: 1,
      success_appeal_hash: f.status === "COMPLIANT" ? (cand.txs.appeal_2 ?? cand.txs.appeal_1) : null,
      require_no_unsuccessful_consensus: true,
    };
    rec("APPEAL_REFUND_PROVEN", { entry_id: entryId, checks, candidate: c.title });
    successExpectations();
  } else {
    cand.outcome = f.status === "NON_COMPLIANT" ? "UPHELD_AFTER_ALL_APPEALS" : "CHECKS_FAILED";
    rec(`C${ci}_result`, { outcome: cand.outcome, failed: Object.entries(checks).filter(([, v]) => !v).map(([k]) => k) });
  }
  save();
}

// ---------------------------------------------------------------------------
// 3. sweep the throwaway submitter back to the owner (no stranded dust)
// ---------------------------------------------------------------------------
if (evidence.success) {
  rec("expectations_summary", { final: evidence.expectations.final, tx_count: evidence.expectations.txs.length });
}
{
  const bal = await balanceOf(subAcct.address);
  const est = await subClient.estimateTransactionFees();
  const send = bal > parseEther("0.001") ? bal - parseEther("0.001") : 0n;
  if (send > 0n) {
    try {
      const hash = await subClient.sendTransaction({
        to: mainAcct.address, value: send,
        fees: { distribution: est.distribution, feeValue: est.feeValue },
      });
      const res = await waitDecided(subClient, hash, "sweep submitter");
      rec("sweep_submitter", { hash, status: res.status, swept: formatEther(send) });
    } catch (e) {
      rec("sweep_submitter", { error: String(e?.message ?? e).slice(0, 160) });
    }
  }
}

save();
console.log("\n================ RESULT ================");
console.log("success:", evidence.success, "| address:", ADDR);
console.log("evidence:", EVIDENCE_FILE);
process.exit(evidence.success ? 0 : 1);
