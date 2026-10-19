import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a Pain Point manager who already knows how bad a problem is should not have to
 * create it and then reopen it to enter severity, frequency and confidence. The create form scores
 * it in the same trip, and the detail page's scoring panel shows what was entered.
 *
 * Disposable org, created through the API and removed afterwards, so the spec depends on no seeded
 * state and can be repeated against the same database. The org admin who creates it is a manager.
 */
test("a pain point created with severity, frequency and confidence is scored on its detail page", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "CreateScores");
  const enable = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers: adminHeaders, data: { enabled: true },
  });
  expect(enable.ok()).toBeTruthy();
  const title = `Exports time out ${suffix}`;

  await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
  await page.getByRole("button", { name: "New Pain Point" }).click();
  const dialog = page.getByRole("dialog", { name: "New Pain Point" });
  await dialog.getByLabel("Type", { exact: true }).selectOption({ label: "Operator" });
  await dialog.getByLabel("Pain Point title").fill(title);

  await test.step("the create form offers the scoring grid the detail page has", async () => {
    const scores = dialog.getByRole("group", { name: "All personas scores" });
    await scores.getByRole("combobox", { name: "Severity" }).selectOption({ label: "Blocker" });
    await scores.getByRole("combobox", { name: "Frequency" }).selectOption({ label: "Rare" });
    await scores.getByRole("combobox", { name: "Confidence" }).selectOption({ label: "High" });
  });

  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).not.toBeVisible();

  await test.step("the detail page shows the scores that were entered", async () => {
    await page.getByText(title).first().click();
    const scoring = page.getByRole("region", { name: "Scoring" });
    const row = scoring.getByRole("group", { name: "All personas scores" });
    await expect(row.getByRole("combobox", { name: "Severity" }).locator("option:checked")).toHaveText("Blocker");
    await expect(row.getByRole("combobox", { name: "Frequency" }).locator("option:checked")).toHaveText("Rare");
    await expect(row.getByRole("combobox", { name: "Confidence" }).locator("option:checked")).toHaveText("High");
  });
});
