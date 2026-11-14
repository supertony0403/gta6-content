// Drives the user's visible Chrome (started with --remote-debugging-port=9333)
// to prepare a TikTok Studio upload. Never clicks "Post" unless called with `post`.
// Usage: node tools/tiktok.mjs status|prepare <video> <caption>|shot <png>|post
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW_CORE || "playwright-core");

const [cmd, ...args] = process.argv.slice(2);
const browser = await chromium.connectOverCDP("http://127.0.0.1:9333");
const ctx = browser.contexts()[0];
const isTikTok = (p) => { try { return new URL(p.url()).hostname.endsWith("tiktok.com"); } catch { return false; } };
let page = ctx.pages().find(isTikTok) || (await ctx.newPage());

if (cmd === "status") {
  // read-only: never navigate, so a login in progress is not interrupted
  const cookies = await ctx.cookies("https://www.tiktok.com");
  const loggedIn = cookies.some((c) => c.name === "sessionid" && c.value);
  console.log(loggedIn ? "LOGGED_IN" : "NOT_LOGGED_IN", page.url());
} else if (cmd === "prepare") {
  const [video, caption] = args;
  await page.goto("https://www.tiktok.com/tiktokstudio/upload", { waitUntil: "domcontentloaded" });
  await page.locator('input[type="file"]').first().setInputFiles(video, { timeout: 30000 });
  const editor = page.locator('[contenteditable="true"]').first();
  await editor.waitFor({ timeout: 120000 });
  await editor.click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.press("Backspace");
  // type hashtags slowly enough for TikTok's autocomplete, then close any suggestion popup
  for (const word of caption.split(" ")) {
    await page.keyboard.type(word + " ", { delay: 30 });
    if (word.startsWith("#")) { await page.waitForTimeout(600); await page.keyboard.press("Escape"); }
  }
  console.log("PREPARED");
} else if (cmd === "shot") {
  await page.screenshot({ path: args[0], fullPage: true });
  console.log("SHOT", args[0]);
} else if (cmd === "post") {
  await page.getByRole("button", { name: /^(Posten|Post)$/ }).click();
  await page.waitForTimeout(8000);
  console.log("CLICKED_POST", page.url());
} else {
  console.log("usage: status|prepare|shot|post");
}
process.exit(0); // detach without closing the user's Chrome
