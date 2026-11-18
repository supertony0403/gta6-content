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
  const [video, caption, when] = args; // optional when: "DD HH:MM" (day of month, local time)
  for (const old of ctx.pages().filter(isPrepared)) await old.close({ runBeforeUnload: false }); // drop stale drafts
  page = await ctx.newPage(); // own tab: never hijack a tab the user is using
  await page.goto("https://www.tiktok.com/tiktokstudio/upload#" + MARK, { waitUntil: "domcontentloaded" });
  await page.locator('input[type="file"]').first().setInputFiles(video, { timeout: 30000 });
  const editor = page.locator('[contenteditable="true"]').first();
  await editor.waitFor({ timeout: 120000 });
  const setCaption = async () => {
    await editor.click();
    await page.keyboard.press("ControlOrMeta+A");
    await page.keyboard.press("Backspace");
    await page.keyboard.insertText(caption); // insertText avoids hashtag autocomplete eating input
    await page.waitForTimeout(800);
    await page.keyboard.press("Escape");
  };
  await setCaption();
  await page.getByRole("button", { name: "Optionale Cookies ablehnen" }).click({ timeout: 2000 }).catch(() => {});
  // synthetic voice → TikTok's "AI-generated content" label must be on
  await page.getByText("Mehr anzeigen").first().click({ timeout: 5000 }).catch(() => {});
  const aiSwitch = page.locator('xpath=//*[normalize-space(text())="KI-generierter Inhalt"]/ancestor::*[.//input[@role="switch"]][1]//input[@role="switch"]').first();
  const wantAi = process.env.AI_LABEL !== "0"; // AI_LABEL=0 for clips without synthetic voice
  if ((await aiSwitch.isChecked()) !== wantAi) await aiSwitch.click({ force: true });
  await page.waitForTimeout(1500);
  // TikTok may show a confirmation dialog for the AI label
  if (wantAi) await page.getByRole("button", { name: /^(Aktivieren|Einschalten|Bestätigen|OK|Turn on)$/ }).click({ timeout: 2500 }).catch(() => {});
  console.log("AI_LABEL", await aiSwitch.isChecked());
  const vis = await page.getByRole("combobox").filter({ hasText: /^(Alle|Everyone|Follower|Freunde|Nur ich)/ }).first().innerText().catch(() => "?");
  console.log("VISIBILITY", vis.trim());
  if (when) {
    const [, day, hh, mm] = when.match(/^(\d{1,2}) (\d\d):(\d\d)$/) || [];
    if (!day) { console.log("ABORT: bad schedule", when); process.exit(1); }
    await page.locator('input[type="radio"][value="schedule"]').check({ force: true });
    await page.waitForTimeout(1200);
    // date: open the field showing "<n>. <Monat>. <Jahr>" and pick the day in the calendar
    const dateField = page.getByText(/^\d{1,2}\. \S+ \d{4}$/).first();
    if (!(await dateField.innerText()).startsWith(String(Number(day)) + ".")) {
      await dateField.click();
      await page.waitForTimeout(800);
      await page.locator(".Picker__panel, [class*=Calendar]").getByText(String(Number(day)), { exact: true }).first().click();
      await page.waitForTimeout(800);
    }
    await page.getByText(/^\d\d:\d\d$/).first().click();
    await page.waitForTimeout(800);
    const cols = page.locator(".TimePicker__column");
    await cols.nth(0).getByText(hh, { exact: true }).click();
    await cols.nth(1).getByText(mm, { exact: true }).click();
    await page.keyboard.press("Escape");
    await page.waitForTimeout(800);
    const shown = [await dateField.innerText(), await page.getByText(/^\d\d:\d\d$/).first().innerText()];
    console.log("SCHEDULED_FOR", shown.join(" "));
    if (!shown[0].startsWith(String(Number(day)) + ".") || shown[1] !== `${hh}:${mm}`) { console.log("ABORT: schedule not applied"); process.exit(1); }
  }
  // schedule pickers can reset the editor → set and verify the caption last
  if ((await editor.innerText()).trim() !== caption.trim()) await setCaption();
  if ((await editor.innerText()).trim() !== caption.trim()) { console.log("ABORT: caption not set"); process.exit(1); }
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
  await page.getByRole("button", { name: /^(Posten|Post|Veröffentlichen|Planen|Schedule)$/ }).click();
  // "publish before the content check finishes?" confirmation
  await page.getByRole("button", { name: /^(Jetzt veröffentlichen|Post now)$/ }).click({ timeout: 6000 }).catch(() => {});
  // success = TikTok leaves the upload page (goes to the post list)
  const ok = await page.waitForURL((u) => !u.pathname.startsWith("/tiktokstudio/upload"), { timeout: 60000 }).then(() => true).catch(() => false);
  console.log(ok ? "POSTED" : "POST_UNCONFIRMED", page.url());
  if (ok) await page.close();
} else {
  console.log("usage: status|prepare|shot|post");
}
process.exit(0); // detach without closing the user's Chrome
