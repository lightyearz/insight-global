import { defineConfig, devices } from "@playwright/test";

/**
 * E2E against a running stack (web + API). Start both first, e.g. API in replay mode on :8080 and
 * `npm run dev` on :3000, then `npm run e2e`. Env:
 *   E2E_BASE_URL   web URL (default http://localhost:3000)
 *   E2E_CONDITION  condition to research when no replay chips are shown (default "type 2 diabetes")
 *   CHROMIUM_PATH  optional path to a preinstalled Chromium
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 8 * 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
