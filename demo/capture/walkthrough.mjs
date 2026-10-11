// Real browser walkthrough of the live ProofOfPost dashboard, recorded with
// Playwright video. Every transaction is a genuine studio-dev write; nothing is
// mocked. The private key is typed into the site's masked (password) field and
// is never logged or written to any artifact.
//
// Deliverables produced by this script:
//   capture/video.webm    – full real-time recording of the session
//   capture/timeline.json – wall-clock offsets (s from context creation) of
//                           each walkthrough beat, used for subtitle timing
//   capture/shots/*.png   – stills at key beats (used for QC and notes)
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { chromium } from "playwright";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..", "..");
const SHOTS = path.join(HERE, "shots");
fs.mkdirSync(SHOTS, { recursive: true });

let pk = null;
for (const line of fs.readFileSync(path.join(ROOT, ".env"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^\s*GENLAYER_PRIVATE_KEY\s*=\s*(.+?)\s*$/);
  if (m) pk = m[1].trim();
}
if (!pk) throw new Error("missing GENLAYER_PRIVATE_KEY");
if (!pk.startsWith("0x")) pk = "0x" + pk;

const APP_URL = "https://richeroveis.github.io/proof-of-post/";
const ENTRY_ID = "2"; // new entry created by this run (ids are 0-based, 2 exist)
const APPEAL_ID = "1"; // existing NON_COMPLIANT entry, appeal_count 0

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const marks = [];
let t0 = null;
const mark = (name) => {
  marks.push({ name, t: (Date.now() - t0) / 1000 });
  console.error(`[mark ${marks[marks.length - 1].t.toFixed(1)}s] ${name}`);
};

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: path.join(HERE, "video"), size: { width: 1920, height: 1080 } },
});
t0 = Date.now();
const page = await context.newPage();

// smooth cursor moves to visible elements + human-ish typing
async function gotoEl(sel) {
  const el = page.locator(sel).first();
  await el.scrollIntoViewIfNeeded();
  await sleep(250);
  const box = await el.boundingBox();
  if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 24 });
  return el;
}
async function click(sel) {
  const el = await gotoEl(sel);
  await sleep(220);
  await el.click();
}
async function type(sel, text, delay = 22) {
  const el = await gotoEl(sel);
  await sleep(200);
  await el.click();
  await el.pressSequentially(text, { delay });
}
async function shot(name) {
  await page.screenshot({ path: path.join(SHOTS, name + ".png") });
}
async function waitFlash(re, what, timeoutMs = 13 * 60_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const txt = await page.locator(".notice.ok").last().textContent().catch(() => null);
    if (txt && re.test(txt)) return txt.trim();
    const err = await page.locator(".notice.error").last().textContent().catch(() => null);
    if (err && /Bond below|Empty|below signer balance|exceeds balance|insufficient/i.test(err)) {
      throw new Error(`${what} failed: ${err}`);
    }
    if (Date.now() > deadline) throw new Error(`${what}: timed out waiting for consensus`);
    await sleep(4000);
  }
}

try {
  // ---- 1. open the live app -------------------------------------------------
  await page.goto(APP_URL, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('.row:has(span:text-is("#1"))', { timeout: 90_000 });
  await sleep(2500);
  mark("app_loaded");
  await shot("01_app");

  // hero + network line + stats: slow read
  await page.mouse.move(960, 120, { steps: 20 });
  await sleep(1200);
  await gotoEl(".netline");
  await sleep(1600);
  await shot("02_netline");
  mark("show_netline");
  await gotoEl(".grid.stats");
  await sleep(1800);
  mark("show_stats");
  await shot("03_stats");

  // ---- 2. connect the studio-dev signer ------------------------------------
  await type('input[type="password"]', pk, 8); // masked field
  mark("typed_key");
  await click('button:has-text("Connect")');
  await page.waitForSelector("text=Signer connected", { timeout: 30_000 });
  await sleep(1500);
  mark("signer_connected");
  await shot("04_connected");

  // ---- 3. fill the submission form -----------------------------------------
  await type('input[placeholder^="Short title"]', "Launch note: on-chain content rules");
  await type(
    'textarea[placeholder^="The post to be judged"]',
    "ProofOfPost ships content-rule adjudication on @GenLayer. " +
      "Validators independently re-derive the verdict and the contract settles the bond on-chain. #ProofOfPost",
  );
  await type(
    'textarea[placeholder^="Must mention GenLayer"]',
    "Must mention GenLayer\nMust be under 50 words\nMust contain a hashtag",
  );
  mark("form_filled");
  await sleep(1200);
  await shot("05_form");
  mark("show_form");

  // ---- 4. submit (payable, 1 GEN bond) --------------------------------------
  await click('button:has-text("submit (payable)")');
  const submitTx = await waitFlash(/submit submitted/, "submit");
  console.error("submit tx line:", submitTx);
  mark("submit_sent");
  await sleep(2500);
  await shot("06_submit_pending");
  // real consensus wait — cursor idles over the pending banner
  const submitDone = await waitFlash(/submit finished with lifecycle/, "submit consensus");
  console.error("submit final:", submitDone);
  mark("submit_finalized");
  await sleep(1500);
  await shot("07_after_submit");

  // ---- 5. the new PENDING entry appears in the registry --------------------
  await gotoEl(`.row:has(span:text-is("#${ENTRY_ID}"))`);
  await sleep(1500);
  mark("new_entry_visible");
  await shot("08_entry_pending");

  // ---- 6. evaluate -> validator consensus verdict ----------------------------
  await click(`.row:has(span:text-is("#${ENTRY_ID}")) button:has-text("Evaluate")`);
  const evalTx = await waitFlash(/evaluate #2 submitted/, "evaluate");
  console.error("evaluate tx line:", evalTx);
  mark("evaluate_sent");
  const evalDone = await waitFlash(/evaluate #2 finished with lifecycle/, "evaluate consensus");
  console.error("evaluate final:", evalDone);
  mark("evaluate_finalized");
  await sleep(2000);

  // ---- 7. show the verdict detail -------------------------------------------
  await click(`.row:has(span:text-is("#${ENTRY_ID}")) button:has-text("View")`);
  await page.waitForSelector("h2:has-text('Entry #2')", { timeout: 30_000 });
  await sleep(1500);
  await gotoEl(".checks");
  await sleep(1500);
  mark("verdict_shown");
  await shot("09_verdict");

  // ---- 8. appeal the real NON_COMPLIANT entry -------------------------------
  await click('button:has-text("Close")');
  await gotoEl(`.row:has(span:text-is("#${APPEAL_ID}"))`);
  await sleep(1200);
  mark("appeal_row");
  await click(`.row:has(span:text-is("#${APPEAL_ID}")) button:has-text("Appeal")`);
  const appealTx = await waitFlash(/appeal #1 submitted/, "appeal");
  console.error("appeal tx line:", appealTx);
  mark("appeal_sent");
  const appealDone = await waitFlash(/appeal #1 finished with lifecycle/, "appeal consensus");
  console.error("appeal final:", appealDone);
  mark("appeal_finalized");
  await sleep(1500);
  await gotoEl(`.row:has(span:text-is("#${APPEAL_ID}"))`);
  await sleep(1200);
  mark("appeal_count_visible");
  await shot("10_after_appeal");

  // ---- 9. closing pan: stats then footer ------------------------------------
  await gotoEl(".grid.stats");
  await sleep(1500);
  await gotoEl(".foot");
  await sleep(2000);
  mark("closing_pan");
  await shot("11_final_stats");

  const rowIds = await page.locator(".row .muted").first().textContent();
  console.error("first row label:", rowIds);
} finally {
  fs.writeFileSync(path.join(HERE, "timeline.json"), JSON.stringify({ startedAt: t0, marks }, null, 2));
  const video = page.video();
  await context.close();
  await browser.close();
  if (video) await video.saveAs(path.join(HERE, "video.webm"));
  console.error("recording closed; timeline entries:", marks.length);
}
