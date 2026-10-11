// Studio Devnet end-to-end verification for the remediated RuleRegistry.
//
// Roles use DISTINCT wallets: owner/deployer = repo .env key (studio-dev only),
// submitter + treasury = throwaway keys generated in-memory here (never
// printed, never persisted). Small controlled GEN amounts only.
//
// Evidence: every tx hash + lifecycle + on-chain state assertions are appended
// to e2e/evidence.json and streamed to stdout.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createClient, createAccount } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { parseEther, formatEther } from "viem";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..");
const CONTRACT_FILE = path.join(ROOT, "contracts", "rule_registry.py");
const RPC = "https://studio-dev.genlayer.com/api";
const MIN_BOND = 10n ** 18n;

let mainPk = null;
for (const line of fs.readFileSync(path.join(ROOT, ".env"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^\s*GENLAYER_PRIVATE_KEY\s*=\s*(.+?)\s*$/);
  if (m) mainPk = m[1].trim();
}
if (!mainPk) throw new Error("missing GENLAYER_PRIVATE_KEY");
if (!mainPk.startsWith("0x")) mainPk = "0x" + mainPk;

const mainAcct = createAccount(mainPk);
const subAcct = createAccount(generatePrivateKey());   // dedicated submitter
const tresAcct = createAccount(generatePrivateKey());  // dedicated treasury
console.log("owner   :", mainAcct.address);
console.log("submitter:", subAcct.address);
console.log("treasury :", tresAcct.address);

const norm = (v) =>
  v instanceof Map ? Object.fromEntries([...v].map(([k, x]) => [k, norm(x)]))
  : Array.isArray(v) ? v.map(norm)
  : typeof v === "bigint" ? v.toString()
  : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, norm(x)]))
  : v;

const evidence = { startedAt: new Date().toISOString(), network: "studio-dev(61997)", steps: [] };
const rec = (step, data) => {
  evidence.steps.push({ step, at: new Date().toISOString(), ...data });
  console.log(`\n### ${step}`);
  console.log(JSON.stringify(data, null, 1));
  fs.writeFileSync(path.join(HERE, "evidence.json"), JSON.stringify(evidence, null, 2));
};

const clientFor = (acct) => createClient({ chain: studioDevnet, account: acct });
const mainClient = clientFor(mainAcct);
const subClient = clientFor(subAcct);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function balanceOf(addr) {
  return formatEther(await mainClient.getBalance({ address: addr }));
}

async function waitDecided(client, hash, label, timeoutMs = 12 * 60_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    await sleep(8000);
    let raw = "";
    let tx = null;
    try {
      tx = await client.getTransaction({ hash });
      raw = JSON.stringify(tx, (_k, v) => (typeof v === "bigint" ? v.toString() : v));
    } catch { /* not queryable yet */ }
    const status = raw.match(/"statusName":\s*"([A-Z_]+)"/)?.[1] ?? "PENDING";
    if (status === "FINALIZED" || status === "UNDETERMINED") {
      // Surface the execution outcome: look for a classified error message in
      // the consensus payload (results may be base64).
      let execError = null;
      const b64 = raw.match(/"[A-Za-z_]*result[A-Za-z_]*":\s*"([A-Za-z0-9+/=]{16,})"/g) ?? [];
      for (const seg of b64) {
        const m = seg.match(/"([A-Za-z0-9+/=]{16,})"/)[1];
        try {
          const dec = Buffer.from(m, "base64").toString("utf8");
          const err = dec.match(/\[(EXPECTED|EXTERNAL|TRANSIENT|LLM_ERROR)\][^"\\]*/);
          if (err) { execError = err[0].slice(0, 200); break; }
        } catch { /* not base64 */ }
      }
      const ret = raw.match(/"return_value":\s*"?([^",}]+)"?/)?.[1];
      return { status, execError, ret, raw };
    }
    if (Date.now() > deadline) throw new Error(`${label}: consensus timeout ${hash}`);
  }
}

async function write(step, client, fn) {
  const est = await client.estimateTransactionFees();
  const hash = await fn(est);
  const res = await waitDecided(client, hash, step);
  rec(step, { hash, ...res, execError: res.execError ?? undefined, raw: undefined });
  return { hash, ...res };
}

async function read(addr, fn, args) {
  return norm(await mainClient.readContract({ address: addr, functionName: fn, args }));
}

// ---------------------------------------------------------------------------
// 0. fund the throwaway submitter (owner -> submitter value transfer)
// ---------------------------------------------------------------------------
{
  const before = await balanceOf(subAcct.address);
  const est = await mainClient.estimateTransactionFees();
  let hash;
  try {
    hash = await mainClient.sendTransaction({
      to: subAcct.address, value: parseEther("3.2"),
      fees: { distribution: est.distribution, feeValue: est.feeValue },
    });
  } catch (e) {
    console.log("sendTransaction with fees failed, trying transfer():", String(e?.message ?? e));
    const r = await mainClient.transfer({ to: subAcct.address, value: parseEther("3.2") });
    hash = r.transactionHash ?? r.hash;
  }
  const res = await waitDecided(mainClient, hash, "fund submitter");
  await sleep(5000);
  rec("fund_submitter", { hash, ...res, sub_before: before, sub_after: await balanceOf(subAcct.address), raw: undefined });
}

// ---------------------------------------------------------------------------
// 1. deploy the remediated contract
// ---------------------------------------------------------------------------
let ADDR;
{
  const code = fs.readFileSync(CONTRACT_FILE, "utf8");
  const est = await mainClient.estimateTransactionFees();
  const hash = await mainClient.deployContract({
    code, args: [Number(MIN_BOND)],
    fees: { distribution: est.distribution, feeValue: est.feeValue },
  });
  const res = await waitDecided(mainClient, hash, "deploy");
  const m = res.raw.match(/"contract_address":\s*"(0x[0-9a-fA-F]{40})"/) ?? res.raw.match(/"to_address":\s*"(0x[0-9a-fA-F]{40})"/);
  ADDR = m?.[1];
  if (!ADDR) throw new Error("deploy did not surface a contract address: " + res.raw.slice(0, 400));
  rec("deploy", { hash, ...res, address: ADDR, raw: undefined });
}

const stats = async () => read(ADDR, "get_stats", []);

// ---------------------------------------------------------------------------
// 2. set_treasury to the dedicated treasury wallet (owner authorization)
// ---------------------------------------------------------------------------
await write("set_treasury", mainClient, (est) => mainClient.writeContract({
  address: ADDR, functionName: "set_treasury", args: [tresAcct.address],
  value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
}));
rec("treasury_configured", { treasury: tresAcct.address, stats: await stats() });

// ---------------------------------------------------------------------------
// 3. Case R - ambiguous word-count submission:
//    submit -> evaluate -> (if NON_COMPLIANT) premature withdraw MUST be
//    rejected while appealable -> appeal -> if overturned, refund observed.
// ---------------------------------------------------------------------------
const R_RULES = "Must be at most 10 words\nMust mention Jupiter";
const R_CONTENT = "Mission to Jupiter: four new moons join the known family";
let rId = null;
{
  const t = await write("R_submit", subClient, (est) => subClient.writeContract({
    address: ADDR, functionName: "submit", args: ["Jupiter count note", R_CONTENT, R_RULES],
    value: MIN_BOND, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  rId = (await stats()).total === "0" ? 0 : Number((await stats()).total) - 1;
  rec("R_submit", { ...t, entry_id: rId });
}
{
  await write("R_evaluate", subClient, (est) => subClient.writeContract({
    address: ADDR, functionName: "evaluate", args: [BigInt(rId)],
    value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  const entry = await read(ADDR, "get_entry", [BigInt(rId)]);
  const s = await stats();
  rec("R_evaluate", { status: entry.status, reserved: s.reserved_slashed, slashed_total: s.slashed_total, deadline: entry.appeal_deadline, tick: s.tick });

  if (entry.status === "NON_COMPLIANT") {
    // ATTACK PATH: treasury withdrawal while still appealable must FAIL.
    const before = await stats();
    await write("R_withdraw_premature", mainClient, (est) => mainClient.writeContract({
      address: ADDR, functionName: "withdraw_slashed", args: [Number(MIN_BOND)],
      value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
    }));
    const after = await stats();
    rec("R_withdraw_premature_check", {
      rejected: after.withdrawn_slashed === before.withdrawn_slashed && after.reserved_slashed === before.reserved_slashed,
      reserved_before: before.reserved_slashed, reserved_after: after.reserved_slashed,
      withdrawn_after: after.withdrawn_slashed, execError: after.reserved_slashed !== "0" ? "reserved (state unchanged)" : undefined,
    });

    // Appeal: LLM-dependent reversal. Record whatever consensus decides.
    const subBefore = await balanceOf(subAcct.address);
    await write("R_appeal", subClient, (est) => subClient.writeContract({
      address: ADDR, functionName: "appeal", args: [BigInt(rId)],
      value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
    }));
    const entry2 = await read(ADDR, "get_entry", [BigInt(rId)]);
    await sleep(6000);
    const s2 = await stats();
    rec("R_appeal_result", {
      status: entry2.status, appeals: entry2.appeal_count,
      slashed_total: s2.slashed_total, reserved: s2.reserved_slashed,
      submitter_before: subBefore, submitter_after: await balanceOf(subAcct.address),
      overturned: entry2.status !== "NON_COMPLIANT",
    });
  }
}

// ---------------------------------------------------------------------------
// 4. Case B - clear violation: losing appeals exhaust liability, then the
//    finalized collateral is withdrawable to the CONFIGURED TREASURY.
// ---------------------------------------------------------------------------
const B_RULES = "Must be written in English\nMust not contain any URL";
const B_CONTENT = "Este texto esta en espanol y enlaza https://example.com para mas informacion.";
let bId = null;
{
  await write("B_submit", subClient, (est) => subClient.writeContract({
    address: ADDR, functionName: "submit", args: ["Spanish with URL", B_CONTENT, B_RULES],
    value: MIN_BOND, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  bId = Number((await stats()).total) - 1;
  await write("B_evaluate", subClient, (est) => subClient.writeContract({
    address: ADDR, functionName: "evaluate", args: [BigInt(bId)],
    value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  const entry = await read(ADDR, "get_entry", [BigInt(bId)]);
  const s = await stats();
  rec("B_evaluate", { entry_id: bId, status: entry.status, slashed_total: s.slashed_total, reserved: s.reserved_slashed, available: s.available_slashed });

  if (entry.status === "NON_COMPLIANT") {
    // reserve check while appealable (may already be proven in R)
    const before = await stats();
    await write("B_withdraw_premature", mainClient, (est) => mainClient.writeContract({
      address: ADDR, functionName: "withdraw_slashed", args: [Number(MIN_BOND)],
      value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
    }));
    const mid = await stats();
    rec("B_withdraw_premature_check", { rejected: mid.withdrawn_slashed === before.withdrawn_slashed, reserved: mid.reserved_slashed });

    for (const tag of ["B_appeal_1", "B_appeal_2"]) {
      await write(tag, subClient, (est) => subClient.writeContract({
        address: ADDR, functionName: "appeal", args: [BigInt(bId)],
        value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
      }));
      const e = await read(ADDR, "get_entry", [BigInt(bId)]);
      const st = await stats();
      rec(tag, { status: e.status, appeals: e.appeal_count, reserved: st.reserved_slashed, available: st.available_slashed });
      if (e.status !== "NON_COMPLIANT") break; // overturned -> liability gone
    }

    // Withdraw whatever is FINALIZED now, to the configured treasury.
    const st0 = await stats();
    const avail = BigInt(st0.available_slashed);
    if (avail > 0n) {
      const tresBefore = await balanceOf(tresAcct.address);
      await write("B_withdraw_finalized", mainClient, (est) => mainClient.writeContract({
        address: ADDR, functionName: "withdraw_slashed", args: [Number(avail)],
        value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
      }));
      await sleep(6000);
      const st1 = await stats();
      rec("B_withdraw_finalized", {
        amount: formatEther(avail), withdrawn_counter: st1.withdrawn_slashed,
        treasury_before: tresBefore, treasury_after: await balanceOf(tresAcct.address),
        contract_balance: st1.contract_balance, reserved: st1.reserved_slashed,
      });
    } else {
      rec("B_withdraw_finalized", { skipped: "nothing finalized (appeal may have overturned)" });
    }
  }
}

// ---------------------------------------------------------------------------
// 5. Case C - PENDING recovery: submit -> cancel -> late evaluate rejected.
// ---------------------------------------------------------------------------
{
  await write("C_submit", subClient, (est) => subClient.writeContract({
    address: ADDR, functionName: "submit", args: ["Will cancel", "Some pending content.", B_RULES],
    value: MIN_BOND, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  const cId = Number((await stats()).total) - 1;
  const before = await balanceOf(subAcct.address);
  await write("C_cancel", subClient, (est) => subClient.writeContract({
    address: ADDR, functionName: "cancel_pending", args: [BigInt(cId)],
    value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  const entry = await read(ADDR, "get_entry", [BigInt(cId)]);
  await sleep(6000);
  rec("C_cancel", { entry_id: cId, status: entry.status, bonded_pending: (await stats()).bonded_pending, submitter_before: before, submitter_after: await balanceOf(subAcct.address) });

  await write("C_late_evaluate", subClient, (est) => subClient.writeContract({
    address: ADDR, functionName: "evaluate", args: [BigInt(cId)],
    value: 0n, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  const entry2 = await read(ADDR, "get_entry", [BigInt(cId)]);
  rec("C_late_evaluate_check", { still_cancelled: entry2.status === "CANCELLED", status: entry2.status });
}

// ---------------------------------------------------------------------------
// 6. oversized rules rejected live (F3) - zero state change expected
// ---------------------------------------------------------------------------
{
  const before = await stats();
  const blob31 = Array.from({ length: 31 }, (_, i) => `Rule number ${i}`).join("\n");
  await write("F3_oversized_rules", subClient, (est) => subClient.writeContract({
    address: ADDR, functionName: "submit", args: ["too many", "content", blob31],
    value: MIN_BOND, fees: { distribution: est.distribution, feeValue: est.feeValue },
  }));
  const after = await stats();
  rec("F3_oversized_rules_check", { rejected: after.total === before.total, total: after.total });
}

// ---------------------------------------------------------------------------
// 7. final accounting + conservation
// ---------------------------------------------------------------------------
{
  const s = await stats();
  const slash = BigInt(s.slashed_total), wd = BigInt(s.withdrawn_slashed), resv = BigInt(s.reserved_slashed);
  const bal = BigInt(s.contract_balance), pend = BigInt(s.bonded_pending);
  const entries = await read(ADDR, "list_entries", [0n, 100n]);
  rec("final", {
    address: ADDR, stats: s, entries: entries.map(e => ({ id: e.entry_id, status: e.status, appeals: e.appeal_count, deadline: e.appeal_deadline })),
    invariants: {
      I1_slashed_ge_withdrawn_plus_reserved: slash >= wd + resv,
      I4_available_consistent: BigInt(s.available_slashed) === slash - wd - resv,
      I6_balance_covers_locks: bal >= pend + resv + (slash - wd - resv > 0n ? slash - wd - resv : 0n),
    },
    balances: { owner: await balanceOf(mainAcct.address), submitter: await balanceOf(subAcct.address), treasury: await balanceOf(tresAcct.address), contract: s.contract_balance },
  });
}
console.log("\nDONE. contract:", ADDR);
