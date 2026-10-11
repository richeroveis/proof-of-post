// Dry probe: load the live app, check key selectors exist. No writes, no key.
import { chromium } from "playwright";
const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
await page.goto("https://richeroveis.github.io/proof-of-post/", { waitUntil: "domcontentloaded" });
await page.waitForSelector("text=Total entries", { timeout: 45_000 });
const checks = {
  passwordInput: await page.locator('input[type="password"]').count(),
  titleInput: await page.locator('input[placeholder^="Short title"]').count(),
  contentArea: await page.locator('textarea[placeholder^="The post to be judged"]').count(),
  rulesArea: await page.locator('textarea[placeholder^="Must mention GenLayer"]').count(),
  bondInput: await page.locator('xpath=//label[contains(text(),"Bond")]/following-sibling::input[1]').count(),
  connectBtn: await page.locator('button:has-text("Connect")').count(),
  submitBtn: await page.locator('button:has-text("submit (payable)")').count(),
  statsTotal: await page.locator(".grid.stats .card .value").first().textContent(),
  row0: await page.locator('.row:has(span:text-is("#0"))').count(),
  row1appeal: await page.locator('.row:has(span:text-is("#1")) button:has-text("Appeal")').count(),
  netline: (await page.locator(".netline").textContent())?.trim(),
};
console.log(JSON.stringify(checks, null, 2));
await page.screenshot({ path: new URL("./shots/probe.png", import.meta.url).pathname });
await browser.close();
