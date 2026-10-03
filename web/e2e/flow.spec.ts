import { expect, test, type Page } from "@playwright/test";

/**
 * Full standard-of-care flow against the real API:
 * create -> live research progress -> HITL review (permissions, conflicts, selection) -> report -> delete.
 * Works with the API in replay mode (no credentials) or live mode.
 */
const RESEARCH_TIMEOUT = Number(process.env.E2E_RESEARCH_TIMEOUT_MS ?? 5 * 60_000);
const REPORT_TIMEOUT = Number(process.env.E2E_REPORT_TIMEOUT_MS ?? 3 * 60_000);
const CONDITION = process.env.E2E_CONDITION ?? "type 2 diabetes";

async function actAs(page: Page, userId: string) {
  await page.getByLabel(/Acting user/).selectOption(userId);
}

test("research, review with conflicts, and generate the report", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  page.on("dialog", (d) => void d.accept());

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Briefings", level: 1 })).toBeVisible();
  await actAs(page, "admin");

  // --- Create ---------------------------------------------------------------
  await page.getByRole("link", { name: "New briefing" }).first().click();
  await expect(page.getByRole("heading", { name: "New briefing" })).toBeVisible();
  const chips = page.getByRole("list", { name: "Recorded conditions" }).getByRole("button");
  await page.waitForTimeout(1000); // health + replay manifests load
  const wanted = chips.filter({ hasText: new RegExp(`^${CONDITION}$`, "i") });
  if ((await wanted.count()) > 0) {
    await wanted.first().click();
  } else if ((await chips.count()) > 0 && !process.env.E2E_CONDITION) {
    await chips.first().click();
  } else {
    await page.getByRole("combobox", { name: "Condition" }).fill(CONDITION);
  }
  await expect(page.getByRole("combobox", { name: "Condition" })).not.toHaveValue("");
  await page.getByLabel("Region").selectOption("US");
  await page.getByRole("button", { name: /Start research/ }).click();

  await page.waitForURL(/\/briefings\/brf_[0-9a-f]{12}$/);
  const briefingId = page.url().split("/").pop() ?? "";
  await expect(page.getByRole("heading", { name: "Agent steps" })).toBeVisible();

  // --- Research progress (SSE) -----------------------------------------------
  await expect(page.getByText(/Awaiting review/).first()).toBeVisible({ timeout: RESEARCH_TIMEOUT });
  await expect(page.getByRole("heading", { name: /Treatment options \(\d+ of \d+ selected\)/ })).toBeVisible();

  const checkboxes = page.locator('input[type="checkbox"][id^="select-opt-"]');
  expect(await checkboxes.count()).toBeGreaterThan(0);

  // --- Permissions: an analyst cannot review an admin's briefing -------------
  await actAs(page, "analyst");
  await expect(page.getByText("Read-only")).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate report" })).toBeDisabled();
  await actAs(page, "admin");
  await expect(page.getByText("Read-only")).toBeHidden();

  // --- Selection rules ----------------------------------------------------------
  await page.getByRole("button", { name: "Select none" }).click();
  await expect(page.getByText("Select at least one treatment option.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate report" })).toBeDisabled();
  await page.getByRole("button", { name: "Reset to AI suggestions" }).click();
  if ((await checkboxes.and(page.locator(":checked")).count()) === 0) await checkboxes.first().check();

  // The human overrides the AI: drop one suggested option (when more than one is suggested).
  const checked = checkboxes.and(page.locator(":checked"));
  let droppedName: string | null = null;
  if ((await checked.count()) > 1) {
    const optionId = ((await checked.last().getAttribute("id")) ?? "").replace(/^select-/, "");
    const box = page.locator(`[id="select-${optionId}"]`); // stable locator; `checked` re-resolves
    droppedName = ((await page.locator(`[id="${optionId}-name"]`).textContent()) ?? "").trim();
    await box.uncheck();
    await expect(box).not.toBeChecked();
  }

  // --- Conflicts (HITL) ---------------------------------------------------------
  const confirm = page.getByRole("button", { name: "Confirm decision" });
  const conflictCards = page.locator('section[aria-labelledby="conflicts-heading"] article');
  const conflictCount = await conflictCards.count();
  if (conflictCount > 0) {
    await expect(page.getByRole("button", { name: "Generate report" })).toBeDisabled();
    await expect(page.getByText(/Confirm a decision for \d+ conflict/)).toBeVisible();
    // Every conflict shows at least two positions, an AI assessment and a rule-based suggestion.
    await expect(page.getByText("Source B").first()).toBeVisible();
    await expect(page.getByText(/AI assessment/).first()).toBeVisible();
    await expect(page.getByText(/^Rule: /).first()).toBeVisible();
    // Nothing is pre-chosen for the human: no radio checked, confirm disabled until a choice is made.
    expect(await page.locator('section[aria-labelledby="conflicts-heading"] input[type="radio"]:checked').count()).toBe(0);
    await expect(conflictCards.first().getByText("Choose a resolution.")).toBeVisible();
    await expect(conflictCards.first().getByRole("button", { name: "Confirm decision" })).toBeDisabled();

    // Conflict 1: custom resolution requires a note.
    const firstCard = conflictCards.nth(0);
    await firstCard.getByLabel("Custom resolution (note required)").check();
    await expect(firstCard.getByRole("button", { name: "Confirm decision" })).toBeDisabled();
    await firstCard.getByRole("textbox").fill("E2E: keep both statements with dose context.");
    await expect(firstCard.getByRole("button", { name: "Confirm decision" })).toBeEnabled();
    await firstCard.getByRole("button", { name: "Confirm decision" }).click();

    // Conflict 2: override the suggestion (pick a radio that is not the suggested one); a note is required.
    if (conflictCount > 1) {
      const secondCard = conflictCards.nth(1);
      const labels = secondCard.locator("fieldset label");
      const n = await labels.count();
      let target = -1;
      for (let i = 0; i < n; i += 1) {
        const text = (await labels.nth(i).textContent()) ?? "";
        if (!text.includes("Suggested") && !text.startsWith("Custom")) {
          target = i;
          break;
        }
      }
      await labels.nth(target).locator('input[type="radio"]').check();
      await expect(secondCard.getByText("Add a note: you are overriding the suggestion.")).toBeVisible();
      await expect(secondCard.getByRole("button", { name: "Confirm decision" })).toBeDisabled();
      await secondCard.getByRole("textbox").fill("E2E: overriding the rule for local context.");
      await secondCard.getByRole("button", { name: "Confirm decision" }).click();
    }

    // Remaining conflicts: take the suggestion explicitly, then confirm.
    for (let i = 2; i < conflictCount; i += 1) {
      const card = conflictCards.nth(i);
      await card.getByRole("button", { name: "Use the suggestion" }).click();
      await card.getByRole("button", { name: "Confirm decision" }).click();
    }
    await expect(confirm).toHaveCount(0);
    await expect(page.getByText(`${conflictCount} of ${conflictCount} decided`)).toBeVisible();

    // Review drafts survive a reload (sessionStorage).
    const checkedBefore = await checkboxes.and(page.locator(":checked")).count();
    await page.reload();
    await expect(page.getByText(`${conflictCount} of ${conflictCount} decided`)).toBeVisible();
    await expect(checkboxes.and(page.locator(":checked"))).toHaveCount(checkedBefore);
  }

  // --- Generate -------------------------------------------------------------------
  const generate = page.getByRole("button", { name: "Generate report" });
  await expect(generate).toBeEnabled();
  await generate.click();
  await expect(page.getByRole("heading", { name: "Executive summary" })).toBeVisible({ timeout: REPORT_TIMEOUT });

  // --- Report template --------------------------------------------------------------
  await expect(page.getByRole("heading", { name: "Key takeaways" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Scope & method" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Report sections" })).toBeVisible();
  await expect(page.getByRole("note").filter({ hasText: "Not medical advice" })).toBeVisible();
  await expect(page.getByRole("term").filter({ hasText: /^(Research conducted \(evidence snapshot\)|Evidence snapshot recorded)$/ })).toBeVisible();
  await expect(page.getByRole("term").filter({ hasText: "Research run" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  // Exactly one "research conducted" event in the timeline list.
  await expect(
    page.getByRole("list", { name: "Timeline events" }).getByText(/^(Research conducted|Evidence snapshot recorded)/),
  ).toHaveCount(1);
  await expect(page.getByRole("heading", { name: /Treatment options \(\d+ selected\)/ })).toBeVisible();
  const optionsTable = page.locator('section[aria-labelledby="options"] table');
  await expect(optionsTable.getByRole("columnheader", { name: "Recommendation" })).toBeVisible();
  if (droppedName) {
    await expect(optionsTable).toBeVisible();
    const names = await optionsTable
      .locator('th[scope="row"]')
      .evaluateAll((ths) => ths.map((th) => (th.childNodes[0]?.textContent ?? "").trim()));
    expect(names.length).toBeGreaterThan(0);
    expect(names).not.toContain(droppedName);
    // ...and it is listed as considered but excluded.
    await expect(page.locator('section[aria-labelledby="excluded"]').getByText(droppedName, { exact: true })).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: /Conflict resolution log/ })).toBeVisible();
  if (conflictCount > 0) {
    const log = page.locator('section[aria-labelledby="conflicts"]');
    await expect(log.getByText("E2E: keep both statements with dose context.")).toBeVisible();
    await expect(log.getByText(/Decided by/).first()).toBeVisible();
    // The custom decision and the override on the second conflict are both recorded against the suggestion.
    expect(await log.getByText(/\(suggested: /).count()).toBeGreaterThanOrEqual(Math.min(conflictCount, 2));
  }
  if (droppedName && (await page.getByText("(Replay)", { exact: true }).count()) > 0) {
    // Replay narratives were recorded for the AI-suggested path; the report must say the review differed.
    await expect(page.getByText(/^Replay note: /)).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: /^Sources \(\d+\)$/ })).toBeVisible();
  await expect(page.locator("#source-1")).toContainText("Retrieved (researched)");
  await expect(page.locator("#source-1")).toContainText("Published");
  await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
  await page.getByText(/^Show all \d+ entries/).click();
  await expect(page.getByRole("cell", { name: "Review submitted", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Report generated", exact: true })).toBeVisible();

  // --- Dashboard shows it as completed, then clean up ------------------------------------
  await page.goto("/");
  const row = page.getByRole("row").filter({ hasText: briefingId });
  await expect(row.getByText("Completed")).toBeVisible();
  await row.getByRole("button", { name: /Delete briefing/ }).click();
  await expect(page.getByRole("row").filter({ hasText: briefingId })).toHaveCount(0);

  expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
});
