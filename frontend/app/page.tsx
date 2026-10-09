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
  writeSubmit,
  writeEvaluate,
  writeAppeal,
  type Stats,
  type EntrySummary,
  type EntryDetail,
} from "@/lib/contract";
import { STUDIO_DEV_CHAIN_ID } from "@/lib/chain";

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
    } catch (err: any) {
      setSigner(null);
      setError("Invalid private key. " + String(err?.message || err));
    }
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
    setBusy(true);
    setError(null);
    setFlash(null);
    try {
      const bondWei = parseEther(bondGen);
      const res = await writeSubmit(signer as any, title, content, rulesBlob, bondWei);
      setFlash(`submit sent → ${typeof res === "string" ? res : JSON.stringify(res)}`);
      setTitle(""); setContent(""); setRulesBlob("");
      await refresh();
    } catch (err: any) {
      setError(String(err?.shortMessage || err?.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function onEvaluate(id: number) {
    if (!signer) { setError("Connect a signer first."); return; }
    setBusy(true); setError(null); setFlash(null);
    try {
      const res = await writeEvaluate(signer as any, id);
      setFlash(`evaluate #${id} sent → ${typeof res === "string" ? res : JSON.stringify(res)}`);
      await refresh();
    } catch (err: any) {
      setError(String(err?.shortMessage || err?.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function onAppeal(id: number) {
    if (!signer) { setError("Connect a signer first."); return; }
    setBusy(true); setError(null); setFlash(null);
    try {
      const res = await writeAppeal(signer as any, id);
      setFlash(`appeal #${id} sent → ${typeof res === "string" ? res : JSON.stringify(res)}`);
      await refresh();
    } catch (err: any) {
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
          A stake-backed content-compliance registry. Submitters post content with an explicit
          rule set and a GEN bond; GenLayer validators independently judge compliance and the
          contract settles the verdict on-chain — refunding the bond on COMPLIANT / INCONCLUSIVE
          and slashing it on NON_COMPLIANT.
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
          <div className="card"><div className="label">Contract balance (GEN)</div><div className="value">{stats ? formatEther(BigInt(stats.contract_balance)) : "—"}</div></div>
          <div className="card"><div className="label">Owner</div><div className="value" style={{ fontSize: 14 }}>{shortAddr(stats?.owner)}</div></div>
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

          <label>Title</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Short title (max 200)" />

          <label>Content</label>
          <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="The post to be judged (max 8000 chars)" />

          <label>Rules (one per line, natural language)</label>
          <textarea value={rulesBlob} onChange={(e) => setRulesBlob(e.target.value)} placeholder={"Must mention GenLayer\nMust be under 50 words\nMust contain a hashtag"} />

          <label>Bond (GEN, ≥ min bond)</label>
          <input value={bondGen} onChange={(e) => setBondGen(e.target.value)} />

          <div className="actions">
            <button onClick={onSubmit} disabled={!signer || busy || notDeployed || !content.trim() || !rulesBlob.trim()}>
              {busy ? "Submitting…" : "submit (payable)"}
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
                  <button onClick={() => onEvaluate(Number(e.entry_id))} disabled={busy}>Evaluate</button>
                )}
                {signer && e.status === "NON_COMPLIANT" && (
                  <button onClick={() => onAppeal(Number(e.entry_id))} disabled={busy}>Appeal</button>
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
            <div className="small">Submitter {shortAddr(detail.submitter)} · Bond {formatEther(BigInt(detail.bond))} GEN · Appeals {detail.appeal_count}</div>
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
          an intelligent contract; it does not decide outcomes.
        </p>
      </footer>
    </div>
  );
}
