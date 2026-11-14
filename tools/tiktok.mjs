// Drives the user's visible Chrome (started with --remote-debugging-port=9333)
// to prepare a TikTok Studio upload. Never clicks "Post" unless called with `post`.
// Usage: node tools/tiktok.mjs status | prepare <video> <caption> | shot <png> | post <caption>
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW_CORE || "playwright-core");

const [cmd, ...args] = process.argv.slice(2);
const browser = await chromium.connectOverCDP("http://127.0.0.1:9333");
const ctx = browser.contexts()[0];
const isTikTok = (p) => { try { return new URL(p.url()).hostname.endsWith("tiktok.com"); } catch { return false; } };
const MARK = "claude-prep";
const isPrepared = (p) => { try { const u = new URL(p.url()); return u.hostname.endsWith("tiktok.com") && u.pathname.startsWith("/tiktokstudio/upload") && u.hash === "#" + MARK; } catch { return false; } };
let page = ctx.pages().find(isTikTok);

if (cmd === "status") {
  // read-only: never navigate, so a login in progress is not interrupted
  const cookies = await ctx.cookies("https://www.tiktok.com");
  const loggedIn = cookies.some((c) => c.name === "sessionid" && c.value);
  console.log(loggedIn ? "LOGGED_IN" : "NOT_LOGGED_IN", page ? page.url() : "(kein TikTok-Tab)");
} else if (cmd === "prepare") {
  const [video, caption] = args;
  page = await ctx.newPage(); // own tab: never hijack a tab the user is using
  await page.goto("https://www.tiktok.com/tiktokstudio/upload#" + MARK, { waitUntil: "domcontentloaded" });
  await page.locator('input[type="file"]').first().setInputFiles(video, { timeout: 30000 });
  const editor = page.locator('[contenteditable="true"]').first();
  await editor.waitFor({ timeout: 120000 });
  await editor.click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.press("Backspace");
  await page.keyboard.insertText(caption); // insertText avoids hashtag autocomplete eating input
  await page.waitForTimeout(800);
  await page.keyboard.press("Escape");
  console.log("PREPARED");
} else if (cmd === "shot") {
  page = ctx.pages().find(isPrepared) || page;
  if (!page) { console.log("NO_TIKTOK_TAB"); process.exit(1); }
  await page.screenshot({ path: args[0], fullPage: true });
  console.log("SHOT", args[0]);
} else if (cmd === "post") {
  const [expected] = args;
  const prepared = ctx.pages().filter(isPrepared);
  if (prepared.length !== 1) { console.log("ABORT: need exactly one prepared tab, found", prepared.length); process.exit(1); }
  page = prepared[0];
  const actual = (await page.locator('[contenteditable="true"]').first().innerText()).trim();
  if (!expected || actual !== expected.trim()) { console.log("ABORT: caption mismatch:", JSON.stringify(actual)); process.exit(1); }
  await page.getByRole("button", { name: /^(Posten|Post|Veröffentlichen)$/ }).click();
  await page.waitForTimeout(8000);
  console.log("CLICKED_POST", page.url());
} else {
  console.log("usage: status|prepare|shot|post");
}
process.exit(0); // detach without closing the user's Chrome
