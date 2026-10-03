// Capture the walkthrough screenshots against a running stack in API mode (replay is fine).
//
//   BASE_URL=http://localhost:3000 SCREENSHOT_DIR=./screenshots node scripts/screenshots-api.mjs
//
// Picks the newest awaiting_review briefing for the review shots and the newest completed one for
// the report shots (override with AWAITING_ID / REPORT_ID). Starts one new briefing for the
// research-progress shot and deletes it afterwards.
import { mkdirSync } from "node:fs";
import path from "node:path";
import { chromium } from "@playwright/test";

const BASE_URL = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/+$/, "");
const OUT = path.resolve(process.env.SCREENSHOT_DIR ?? "screenshots");
const CONDITION = process.env.SCREENSHOT_CONDITION ?? "Type 2 diabetes";
mkdirSync(OUT, { recursive: true });

async function newest(status) {
  const res = await fetch(`${BASE_URL}/api/briefings?status=${status}`);
  const list = await res.json();
  return list.find((b) => /diabetes/i.test(b.condition_label))?.id ?? list[0]?.id;
}
const awaitingId = process.env.AWAITING_ID ?? (await newest("awaiting_review"));
const reportId = process.env.REPORT_ID ?? (await newest("completed"));
if (!awaitingId || !reportId) throw new Error("Need one awaiting_review and one completed briefing");

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const errors = [];
async function open(viewport, deviceScaleFactor = 1) {
  const context = await browser.newContext({ viewport, deviceScaleFactor });
  const page = await context.newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("response", (r) => r.status() >= 400 && errors.push(`HTTP ${r.status()} ${r.url()}`));
  return page;
}
const saved = (file) => console.log("saved", file);
async function shot(page, name, opts = {}) {
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true, ...opts });
  saved(file);
}
async function box(locator) {
  await locator.scrollIntoViewIfNeeded();
  const b = await locator.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height };
  });
  return b;
}

const page = await open({ width: 1440, height: 900 });

// 01 Dashboard
await page.goto(`${BASE_URL}/`);
await page.getByRole("table").waitFor();
await page.getByText("Evidence snapshot").first().waitFor();
await page.waitForTimeout(800);
await shot(page, "01-dashboard");

// 02 New briefing
await page.goto(`${BASE_URL}/briefings/new`);
await page.getByRole("list", { name: "Recorded conditions" }).getByRole("button", { name: CONDITION }).click();
await page.waitForTimeout(300);
await shot(page, "02-new-briefing");

// 03 Research progress (live SSE, mid-run)
await page.getByRole("button", { name: /Start research/ }).click();
await page.waitForURL(/\/briefings\/brf_/);
const progressId = page.url().split("/").pop();
await page.getByText("Agent steps").waitFor();
// Wait until the agent is mid-way (extraction running, sources counted) so the shot shows live progress.
await page.getByText("running…").or(page.getByText("running...")).first().waitFor({ timeout: 15_000 }).catch(() => {});
await page
  .waitForFunction(() => /Extract treatments[\s\S]*running/.test(document.body.innerText), null, { timeout: 15_000 })
  .catch(() => {});
await page.waitForTimeout(700);
await shot(page, "03-research-progress");

// 04 / 05 Review of the awaiting briefing
await page.goto(`${BASE_URL}/briefings/${awaitingId}`);
await page.getByRole("heading", { name: /Treatment options \(\d+ of \d+ selected\)/ }).waitFor();
await page.waitForTimeout(500);
// The sticky "Generate report" bar would otherwise be painted mid-way through clipped full-page shots.
const unstick = (p) => p.addStyleTag({ content: ".sticky { position: static !important; }" });
await unstick(page);
const options = page.locator('section[aria-labelledby="options-heading"]');
await shot(page, "04-review-options", { clip: await box(options) });

const zoom = await open({ width: 1440, height: 900 }, 2);
await zoom.goto(`${BASE_URL}/briefings/${awaitingId}`);
const conflicts = zoom.locator('section[aria-labelledby="conflicts-heading"]');
await conflicts.waitFor();
await unstick(zoom);
await zoom.waitForTimeout(500);
await shot(zoom, "05-review-conflicts", { clip: await box(conflicts) });

// 06 / 07 Report
await page.goto(`${BASE_URL}/briefings/${reportId}`);
await page.getByRole("heading", { name: "Timeline" }).waitFor();
await unstick(page);
await page.waitForTimeout(500);
const timeline = await box(page.locator('section[aria-labelledby="timeline"]'));
await shot(page, "06-report-top", { clip: { x: 0, y: 0, width: 1440, height: timeline.y + timeline.height + 24 } });
const optionsTop = await box(page.locator('section[aria-labelledby="options"]'));
const audit = await box(page.locator('section[aria-labelledby="audit"]'));
await shot(page, "07-report-sources", {
  clip: { x: 0, y: optionsTop.y - 16, width: 1440, height: audit.y - optionsTop.y + 8 },
});

// 08 Mobile report
const mobile = await open({ width: 390, height: 844 }, 2);
await mobile.goto(`${BASE_URL}/briefings/${reportId}`);
await mobile.getByRole("heading", { name: "Timeline" }).waitFor();
await unstick(mobile);
await mobile.waitForTimeout(500);
await shot(mobile, "08-mobile-report");

// Clean up the briefing started for the progress shot.
if (progressId) await fetch(`${BASE_URL}/api/briefings/${progressId}`, { method: "DELETE" });

await browser.close();
if (errors.length) {
  console.error("Console errors:\n" + errors.join("\n"));
  process.exitCode = 1;
}
