// Capture UI screenshots against a running web server (mock mode recommended).
//
//   NEXT_PUBLIC_API_MODE=mock npx next dev --port 3001 &
//   BASE_URL=http://localhost:3001 SCREENSHOT_DIR=./screenshots node scripts/screenshots.mjs
//
// CHROMIUM_PATH points at a preinstalled Chromium when Playwright's own browser is not installed.
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { chromium } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3001";
const OUT = path.resolve(process.env.SCREENSHOT_DIR ?? "screenshots");
const PREFIX = process.env.SCREENSHOT_PREFIX ?? "mock";
mkdirSync(OUT, { recursive: true });
const seedId = (name) => JSON.parse(readFileSync(new URL(`../src/mocks/${name}.json`, import.meta.url), "utf8")).id;
const AWAITING_ID = seedId("briefing-awaiting-review");
const COMPLETED_ID = seedId("briefing-completed");
const unstick = () => page.addStyleTag({ content: ".sticky { position: static !important; }" });

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await context.newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));
page.on("response", (r) => r.status() >= 400 && errors.push(`HTTP ${r.status()} ${r.url()}`));

const shot = async (name, opts = {}) => {
  const file = path.join(OUT, `${PREFIX}-${name}.png`);
  await page.screenshot({ path: file, fullPage: true, ...opts });
  console.log("saved", file);
};

// 1. Dashboard
await page.goto(`${BASE_URL}/`);
await page.getByRole("table").waitFor();
await page.getByText("Evidence snapshot").first().waitFor();
await page.waitForTimeout(500);
await shot("dashboard");

// 2. Review step of the seeded awaiting-review briefing
await page.goto(`${BASE_URL}/briefings/${AWAITING_ID}`);
await page.getByRole("heading", { name: /Conflicting sources/ }).waitFor();
await shot("review-viewport", { fullPage: false });
await unstick();
await shot("review");

// 3. Report of the seeded completed briefing
await page.goto(`${BASE_URL}/briefings/${COMPLETED_ID}`);
await page.getByRole("heading", { name: "Timeline" }).waitFor();
await unstick();
await shot("report");
await page.getByRole("heading", { name: "Timeline" }).scrollIntoViewIfNeeded();
const marker = page.getByRole("list", { name: "Guidelines markers" }).getByRole("button").last();
await marker.focus(); // focus-within keeps the tooltip open while the element screenshot scrolls
await page.waitForTimeout(300);
await page.locator("#timeline").locator("..").screenshot({ path: path.join(OUT, `${PREFIX}-timeline-tooltip.png`) });
console.log("saved", path.join(OUT, `${PREFIX}-timeline-tooltip.png`));

// 4. Full flow: new briefing -> research progress -> review -> report
await page.goto(`${BASE_URL}/briefings/new`);
await page.getByRole("button", { name: "Type 2 diabetes" }).click();
await shot("new-briefing", { fullPage: false });
await page.getByRole("button", { name: /Start research/ }).click();
await page.waitForURL(/\/briefings\/brf_/);
await page.getByText("Agent steps").waitFor();
await page.waitForTimeout(1800);
await shot("research-progress", { fullPage: false });
await page.getByRole("heading", { name: /Conflicting sources/ }).waitFor({ timeout: 30_000 });
const useSuggestion = page.getByRole("button", { name: "Use the suggestion" });
while ((await useSuggestion.count()) > 0) {
  await useSuggestion.first().click();
  await page.getByRole("button", { name: "Confirm decision" }).first().click();
}
await page.getByRole("button", { name: "Generate report" }).click();
await page.getByRole("heading", { name: "Executive summary" }).waitFor({ timeout: 30_000 });
await unstick();
await shot("flow-report");

// 5. Mobile report (vertical timeline)
await page.setViewportSize({ width: 390, height: 844 });
await page.goto(`${BASE_URL}/briefings/${COMPLETED_ID}`);
await page.getByRole("heading", { name: "Timeline" }).waitFor();
await unstick();
await shot("report-mobile");

await browser.close();
if (errors.length) {
  console.error("Console errors:\n" + errors.join("\n"));
  process.exitCode = 1;
}
