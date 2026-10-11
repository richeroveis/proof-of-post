"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createAccount } from "genlayer-js";
import { parseEther, formatEther } from "viem";
import {
  CONTRACT_ADDRESS,
  GENLAYER_RPC,
  readStats,
  readEntries,
  readEntry,
  readBalance,
  makeWriteClient,
  estimateFees,
  waitForDecided,
  writeSubmit,
  writeEvaluate,
  writeAppeal,
  writeCancel,
  type Stats,
  type EntrySummary,
  type EntryDetail,
} from "@/lib/contract";
import { STUDIO_DEV_CHAIN_ID } from "@/lib/chain";

// Client-side mirrors of the contract's hard limits (contracts/rule_registry.py).
// The contract REJECTS oversized input - it never truncates - so the form must
// surface the same constraints before paying a fee for a doomed transaction.
const MAX_TITLE_LEN = 200;
const MAX_CONTENT_LEN = 8000;
const MAX_RULES = 30;
const MAX_RULE_LEN = 300;

function validateSubmission(title: string, content: string, rulesBlob: string): string | null {
  if (title.length > MAX_TITLE_LEN) return `Title exceeds ${MAX_TITLE_LEN} characters (contract rejects, never truncates).`;
  const clean = content.trim();
  if (clean.length === 0) return "Content is empty.";
  if (clean.length > MAX_CONTENT_LEN) return `Content exceeds ${MAX_CONTENT_LEN} characters.`;
  const rules = rulesBlob.split("\n").map((r) => r.trim()).filter((r) => r.length > 0);
  if (rules.length === 0) return "No rules provided.";
  if (rules.length > MAX_RULES) return `Too many rules: ${rules.length} > ${MAX_RULES} (contract rejects, never truncates).`;
  const tooLong = rules.findIndex((r) => r.length > MAX_RULE_LEN);
  if (tooLong >= 0) return `Rule ${tooLong + 1} exceeds ${MAX_RULE_LEN} characters.`;
  return null;
}

function shortAddr(a?: string) {
  if (!a) return "—";
  return a.length > 14 ? `${a.slice(0, 8)}…${a.slice(-6)}` : a;
}

function Badge({ status }: { status: string }) {
  return <span className={`badge ${status}`}>{status}</span>;
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [entries, setEntries] = useState<EntrySummary[]>([]);
  const [detail, setDetail] = useState<EntryDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  // signer (in-memory only — never persisted, never sent anywhere raw)
  const [pkInput, setPkInput] = useState("");
  const [signer, setSigner] = useState<ReturnType<typeof createAccount> | null>(null);

  // submit form
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [rulesBlob, setRulesBlob] = useState("");
  const [bondGen, setBondGen] = useState("1");
  const [busy, setBusy] = useState(false);
  // studio-dev is not gasless: every write needs a non-zero fee deposit, and
  // consensus takes a round or two, so the UI shows both while acting.
  const [feeGen, setFeeGen] = useState<string | null>(null);
  const [signerBalance, setSignerBalance] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!CONTRACT_ADDRESS) return;
    setLoading(true);
    setError(null);
    try {
      const [s, e] = await Promise.all([readStats(), readEntries(0, 50)]);
      setStats(s);
      setEntries(e);
    } catch (err: any) {
      setError(String(err?.shortMessage || err?.message || err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const minBond = useMemo(() => (stats ? formatEther(BigInt(stats.min_bond)) : "0"), [stats]);

  async function connectSigner() {
    try {
      const acc = createAccount(pkInput.trim() as `0x${string}`);
      setSigner(acc);
      setFlash(`Signer connected: ${acc.address}`);
      setError(null);
      // Read the account's GEN balance and the network's current fee quote so
      // the user knows upfront whether this key can afford a write.
      try {
        const [bal, fee] = await Promise.all([
          readBalance(acc.address),
          estimateFees(makeWriteClient(acc as any)),
        ]);
        setSignerBalance(formatEther(bal));
        setFeeGen(formatEther(fee));
      } catch {
        setSignerBalance(null);
        setFeeGen(null);
      }
    } catch (err: any) {
      setSigner(null);
      setSignerBalance(null);
      setFeeGen(null);
      setError("Invalid private key. " + String(err?.message || err));
    }
  }

  // Run a write, then wait for the protocol to reach a terminal lifecycle state
  // before re-reading contract state — a tx hash alone says nothing about the
  // validator verdict.
  async function runWrite(label: string, fn: () => Promise<any>) {
    if (!signer) throw new Error("Connect a signer first.");
    const hash = String(await fn());
    setFlash(`${label} submitted → ${hash} · waiting for validator consensus…`);
    setPending(label);
    const status = await waitForDecided(makeWriteClient(signer as any), hash);
    setPending(null);
    setFlash(`${label} finished with lifecycle ${status} · ${hash}`);
    await refresh();
    return status;
  }

  async function onView(id: number) {
    setError(null);
    try {
      const d = await readEntry(id);
      setDetail(d);
    } catch (err: any) {
      setError(String(err?.shortMessage || err?.message || err));
    }
  }

  async function onSubmit() {
    if (!signer) { setError("Connect a signer first."); return; }
    const invalid = validateSubmission(title, content, rulesBlob);
    if (invalid) { setError(invalid); return; }
    setBusy(true);
    setError(null);
    setFlash(null);
    try {
      const bondWei = parseEther(bondGen);
      await runWrite("submit", () => writeSubmit(signer as any, title, content, rulesBlob, bondWei));
      setTitle(""); setContent(""); setRulesBlob("");
    } catch (err: any) {
      setPending(null);
      setError(String(err?.shortMessage || err?.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function onEvaluate(id: number) {
    if (!signer) { setError("Connect a signer first."); return; }
    setBusy(true); setError(null); setFlash(null);
    try {
      await runWrite(`evaluate #${id}`, () => writeEvaluate(signer as any, id));
    } catch (err: any) {
      setPending(null);
      setError(String(err?.shortMessage || err?.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function onAppeal(id: number) {
    if (!signer) { setError("Connect a signer first."); return; }
    setBusy(true); setError(null); setFlash(null);
    try {
      await runWrite(`appeal #${id}`, () => writeAppeal(signer as any, id));
    } catch (err: any) {
      setPending(null);
      setError(String(err?.shortMessage || err?.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function onCancel(id: number) {
    if (!signer) { setError("Connect a signer first."); return; }
    setBusy(true); setError(null); setFlash(null);
    try {
      await runWrite(`cancel #${id}`, () => writeCancel(signer as any, id));
    } catch (err: any) {
      setPending(null);
      setError(String(err?.shortMessage || err?.message || err));
    } finally {
      setBusy(false);
    }
  }

  const notDeployed = !CONTRACT_ADDRESS;

  return (
    <div className="wrap">
      <header className="hero">
        <h1>ProofOfPost · RuleRegistry</h1>
        <p>
          A stake-backed content-compliance registry. Submitters post LITERAL TEXT (URLs are judged
          as text — remote content is never fetched) with an explicit rule set and a GEN bond;
          GenLayer validators independently judge compliance and the contract settles the verdict
          on-chain — refunding the bond on COMPLIANT / INCONCLUSIVE and slashing it on
          NON_COMPLIANT. Slashed bonds stay RESERVED and the verdict stays APPEALABLE while the
          reservation holds; the liability is finalized only when the two-appeal budget runs out
          or when a treasury withdrawal sweeps it after the minimum reservation window — counted
          in lifecycle writes, not wall-clock time (the pinned runner has no timestamp API).
        </p>
        <div className="netline">
          <span>Network: <code>studio-dev</code> chainId <code>{STUDIO_DEV_CHAIN_ID}</code></span>
          <span>RPC: <code>{GENLAYER_RPC}</code></span>
          <span>Contract: <code>{notDeployed ? "not deployed yet" : CONTRACT_ADDRESS}</code></span>
        </div>
      </header>

      {notDeployed && (
        <div className="notice info">
          The contract address is not configured (<code>NEXT_PUBLIC_CONTRACT_ADDRESS</code> is empty).
          This dashboard will show live on-chain state once the RuleRegistry is deployed to studio-dev
          and the address is injected at build time.
        </div>
      )}

      {error && <div className="notice error">{error}</div>}
      {flash && <div className="notice ok">{flash}</div>}

      <section>
        <div className="grid stats">
          <div className="card"><div className="label">Total entries</div><div className="value">{stats?.total ?? "—"}</div></div>
          <div className="card"><div className="label">Verified</div><div className="value">{stats?.verified ?? "—"}</div></div>
          <div className="card"><div className="label">Min bond (GEN)</div><div className="value">{stats ? minBond : "—"}</div></div>
          <div className="card"><div className="label">Slashed (GEN)</div><div className="value">{stats ? formatEther(BigInt(stats.slashed_total)) : "—"}</div></div>
          <div className="card"><div className="label">Reserved (appealable)</div><div className="value">{stats ? formatEther(BigInt(stats.reserved_slashed)) : "—"}</div></div>
          <div className="card"><div className="label">Treasury-available</div><div className="value">{stats ? formatEther(BigInt(stats.available_slashed)) : "—"}</div></div>
          <div className="card"><div className="label">Contract balance (GEN)</div><div className="value">{stats ? formatEther(BigInt(stats.contract_balance)) : "—"}</div></div>
          <div className="card"><div className="label">Owner</div><div className="value" style={{ fontSize: 14 }}>{shortAddr(stats?.owner)}</div></div>
          <div className="card"><div className="label">Treasury</div><div className="value" style={{ fontSize: 14 }}>{shortAddr(stats?.treasury)}</div></div>
          <div className="card"><div className="label">Lifecycle tick</div><div className="value">{stats?.tick ?? "—"}</div></div>
        </div>
        <div className="actions" style={{ marginTop: 12 }}>
          <button onClick={refresh} disabled={loading || notDeployed}>{loading ? "Refreshing…" : "Refresh"}</button>
        </div>
      </section>

      <section>
        <h2>Submit content for adjudication</h2>
        {!signer && (
          <div className="notice info">
            Writes are signed locally in your browser. Paste a <strong>studio-dev-only</strong> private key
            to enable the write forms. Never use a mainnet key. The key is held in memory only and is never
            stored or transmitted raw.
          </div>
        )}
        <div className="notice">
          <strong>Costs:</strong> studio-dev is not gasless — each write carries a network fee deposit
          {feeGen ? <> (currently <code>{feeGen} GEN</code>, quoted by the node per transaction)</> : <> quoted by the node per transaction</>},
          paid by the signer on top of the bond. {signerBalance !== null && (
            <>Signer balance: <code>{signerBalance} GEN</code>.</>
          )}
          {pending && <> <strong>{pending}</strong> is in validator consensus — a verdict usually lands within a couple of minutes.</>}
        </div>
        <div className="form">
          <label>Signer private key (in-memory)</label>
          <div className="rowbtns">
            <input type="password" placeholder="0x…" value={pkInput} onChange={(e) => setPkInput(e.target.value)} />
            {signer ? (
              <button onClick={() => { setSigner(null); setPkInput(""); }}>Disconnect {shortAddr(signer.address)}</button>
            ) : (
              <button onClick={connectSigner} disabled={!pkInput.trim()}>Connect</button>
            )}
          </div>

          <label>Title (max {MAX_TITLE_LEN} chars — rejected, never truncated)</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Short title (max 200)" />

          <label>Content — literal text only (URLs are judged as text; nothing is fetched)</label>
          <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="The post to be judged (max 8000 chars)" />

          <label>Rules (one per line, natural language; max {MAX_RULES} × {MAX_RULE_LEN} chars)</label>
          <textarea value={rulesBlob} onChange={(e) => setRulesBlob(e.target.value)} placeholder={"Must mention GenLayer\nMust be under 50 words\nMust contain a hashtag"} />

          <label>Bond (GEN, ≥ min bond)</label>
          <input value={bondGen} onChange={(e) => setBondGen(e.target.value)} />

          <div className="actions">
            <button onClick={onSubmit} disabled={!signer || busy || !!pending || notDeployed || !content.trim() || !rulesBlob.trim()}>
              {busy ? "Working…" : "submit (payable)"}
            </button>
            <span className="small">Creates a PENDING entry and locks the bond.</span>
          </div>
        </div>
      </section>

      <section>
        <h2>Entries</h2>
        {entries.length === 0 && <div className="notice info">No entries yet.</div>}
        <div className="rows">
          {entries.map((e) => (
            <div className="row" key={e.entry_id}>
              <span className="muted">#{e.entry_id}</span>
              <span>{e.title || <span className="muted">(untitled)</span>}<br />
                <span className="muted">{shortAddr(e.submitter)} · {formatEther(BigInt(e.bond))} GEN</span></span>
              <span><Badge status={e.status} /></span>
              <span className="muted">appeals: {e.appeal_count}</span>
              <span className="rowbtns">
                <button onClick={() => onView(Number(e.entry_id))}>View</button>
                {signer && e.status === "PENDING" && (
                  <button onClick={() => onEvaluate(Number(e.entry_id))} disabled={busy || !!pending}>Evaluate</button>
                )}
                {signer && e.status === "PENDING" && (
                  <button onClick={() => onCancel(Number(e.entry_id))} disabled={busy || !!pending}>Cancel (refund)</button>
                )}
                {signer && e.status === "NON_COMPLIANT" && BigInt(e.appeal_deadline) > 0n && (
                  <button onClick={() => onAppeal(Number(e.entry_id))} disabled={busy || !!pending}>Appeal</button>
                )}
              </span>
            </div>
          ))}
        </div>
      </section>

      {detail && (
        <section>
          <h2>Entry #{detail.entry_id} <Badge status={detail.status} /></h2>
          <div className="detail">
            <div className="small">Submitter {shortAddr(detail.submitter)} · Bond {formatEther(BigInt(detail.bond))} GEN · Appeals {detail.appeal_count}/2</div>
            {detail.status === "NON_COMPLIANT" && BigInt(detail.appeal_deadline) > 0n && (
              <div className="small">Appeal liability: reserved (treasury sweep possible only after write #{detail.appeal_deadline}, current write #{detail.tick}) — the verdict stays appealable while the bond remains reserved.</div>
            )}
            <h3 style={{ marginBottom: 4 }}>{detail.title}</h3>
            <div className="content-box">{detail.content}</div>
            <div className="label small">Rules & verdicts</div>
            <ul className="checks">
              {detail.checks.map((c, i) => (
                <li key={i}><Badge status={c.status} /><span>{c.rule}</span></li>
              ))}
            </ul>
            {detail.verdict_reason && <><div className="label small">Reason</div><pre>{detail.verdict_reason}</pre></>}
            <div className="actions" style={{ marginTop: 12 }}>
              <button onClick={() => setDetail(null)}>Close</button>
            </div>
          </div>
        </section>
      )}

      <footer className="foot">
        <p>
          Verdicts are produced by GenLayer validator consensus (<code>run_nondet</code> with an
          independent comparative re-derivation), not by this UI. This frontend is read/write access to
          an intelligent contract; it does not decide outcomes. An appeal re-runs the SAME assessment
          on the SAME stored content and rules — no new evidence can be attached.
        </p>
      </footer>
    </div>
  );
}
