import { createClient, createAccount } from "genlayer-js";
import { studioDev } from "./chain";

// The signer type produced by the SDK's own createAccount (avoids a mismatch
// between genlayer-js's bundled viem version and the app's top-level viem).
type Signer = ReturnType<typeof createAccount>;

// ---------------------------------------------------------------------------
// RuleRegistry typed bindings
//
// All reads go through the GenLayer `gen_call` RPC; all writes go through a
// locally-signed GenLayer raw transaction (eth_sendRawTransaction). The
// contract returns Python dicts/lists; the SDK decodes maps into JS `Map`s, so we normalize everything into plain JSON before rendering.
//
// studio-dev is NOT gasless: every transaction must carry a non-zero fee
// deposit. Writes therefore ask the node for a fee quote
// (`estimateTransactionFees`) and attach the returned distribution/feeValue to
// `writeContract`, exactly like the official CLI does. The required fee is
// surfaced in the UI so a user can fund the signer account before writing.
// ---------------------------------------------------------------------------

export const CONTRACT_ADDRESS = (process.env.NEXT_PUBLIC_CONTRACT_ADDRESS || "").trim();
export const GENLAYER_RPC = process.env.NEXT_PUBLIC_GENLAYER_RPC || "https://studio-dev.genlayer.com/api";

export type EntrySummary = {
  entry_id: string;
  submitter: string;
  title: string;
  status: string;
  bond: string;
  appeal_count: string;
};

export type RuleCheck = { rule: string; status: string };

export type EntryDetail = {
  entry_id: string;
  submitter: string;
  title: string;
  content: string;
  rules: string[];
  bond: string;
  status: string;
  checks: RuleCheck[];
  verdict_reason: string;
  appeal_count: string;
};

export type Stats = {
  total: string;
  verified: string;
  min_bond: string;
  slashed_total: string;
  withdrawn_slashed: string;
  contract_balance: string;
  owner: string;
  treasury: string;
};

// Recursively convert Maps/arrays of Maps into plain JS objects.
export function normalize(value: any): any {
  if (value instanceof Map) {
    const obj: Record<string, any> = {};
    for (const [k, v] of value.entries()) obj[String(k)] = normalize(v);
    return obj;
  }
  if (Array.isArray(value)) return value.map(normalize);
  return value;
}

// A read client only needs a sender identity for `gen_call`; we use an
// ephemeral in-memory account (random key, never persisted, no value).
export function makeReadClient() {
  return createClient({ chain: studioDev as any, account: createAccount() });
}

// A write client signs GenLayer raw transactions locally. The caller supplies
// the signer account; the private key never leaves the browser.
export function makeWriteClient(account: Signer) {
  return createClient({ chain: studioDev as any, account: account as any });
}

export async function readStats(): Promise<Stats> {
  const client = makeReadClient();
  const res = await client.readContract({
    address: CONTRACT_ADDRESS as any,
    functionName: "get_stats",
    args: [],
  });
  return normalize(res) as Stats;
}

export async function readEntries(offset: number, limit: number): Promise<EntrySummary[]> {
  const client = makeReadClient();
  const res = await client.readContract({
    address: CONTRACT_ADDRESS as any,
    functionName: "list_entries",
    args: [BigInt(offset), BigInt(limit)],
  });
  return normalize(res) as EntrySummary[];
}

export async function readEntry(entryId: number): Promise<EntryDetail | null> {
  const client = makeReadClient();
  const res = await client.readContract({
    address: CONTRACT_ADDRESS as any,
    functionName: "get_entry",
    args: [BigInt(entryId)],
  });
  const obj = normalize(res);
  if (!obj || Object.keys(obj).length === 0) return null;
  return obj as EntryDetail;
}

export type GenClient = ReturnType<typeof makeReadClient>;

// The SDK's own transaction-hash type (a branded viem `Hash`), used only at the
// RPC boundary so hashes coming from `writeContract`/URLs stay plain strings.
type TxHash = Parameters<GenClient["getTransaction"]>[0]["hash"];

export async function readBalance(address: string): Promise<bigint> {
  const client = makeReadClient();
  return client.getBalance({ address: address as any });
}

export async function estimateFees(client: GenClient): Promise<bigint> {
  const est = await client.estimateTransactionFees();
  return est.feeValue;
}

// Poll a submitted transaction until the protocol reports a terminal lifecycle
// state. `getTransaction` returns the full consensus view, so we read the
// lifecycle name from its serialized form rather than inventing a shape.
export async function waitForDecided(
  client: GenClient,
  hash: string,
  timeoutMs = 8 * 60_000,
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    await new Promise((r) => setTimeout(r, 10_000));
    let raw = "";
    try {
      const tx = await client.getTransaction({ hash: hash as TxHash });
      raw = JSON.stringify(tx, (_k, v) => (typeof v === "bigint" ? v.toString() : v));
    } catch {
      // Transaction not yet queryable: keep polling inside the deadline.
    }
    const status = raw.match(/"statusName":\s*"([A-Z_]+)"/)?.[1] ?? "PENDING";
    if (status === "FINALIZED" || status === "UNDETERMINED") return status;
    if (Date.now() > deadline) return status;
  }
}

// --- writes (require a signer account from the caller) ---

export async function writeSubmit(
  account: Signer,
  title: string,
  content: string,
  rulesBlob: string,
  bondWei: bigint,
): Promise<any> {
  const client = makeWriteClient(account);
  const est = await client.estimateTransactionFees();
  return client.writeContract({
    address: CONTRACT_ADDRESS as any,
    functionName: "submit",
    args: [title, content, rulesBlob],
    value: bondWei,
    fees: { distribution: est.distribution, feeValue: est.feeValue },
  });
}

export async function writeEvaluate(account: Signer, entryId: number): Promise<any> {
  const client = makeWriteClient(account);
  const est = await client.estimateTransactionFees();
  return client.writeContract({
    address: CONTRACT_ADDRESS as any,
    functionName: "evaluate",
    args: [BigInt(entryId)],
    value: BigInt(0),
    fees: { distribution: est.distribution, feeValue: est.feeValue },
  });
}

export async function writeAppeal(account: Signer, entryId: number): Promise<any> {
  const client = makeWriteClient(account);
  const est = await client.estimateTransactionFees();
  return client.writeContract({
    address: CONTRACT_ADDRESS as any,
    functionName: "appeal",
    args: [BigInt(entryId)],
    value: BigInt(0),
    fees: { distribution: est.distribution, feeValue: est.feeValue },
  });
}
