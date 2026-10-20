import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable org after the test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a Strategy the organisation owns (created and read at organisation level, never shown by a
 * project) is found by the global search, in the all-projects scope and in a project's own, and opens at its
 * organisation page, not through a project. The project search can leave organisation records out.
 *
 * Builds its own organisation (see `../stakeholders/helpers.ts`) with Context & Strategy on and a run-unique word.
 */
test.describe("global search: organisation-owned Context & Strategy records", () => {
  test("an organisation Strategy is found in the all-projects scope and opens at its organisation page", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "SearchOrgRec", false, "Context & Strategy");
    const word = `orgstrategy${suffix.toString(36)}`;
    const created = await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy/strategies`, {
      headers: adminHeaders, data: { title: `Shared ${word} roadmap`, objective: "Grow the portfolio" },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const strategy = await created.json();

    await page.goto(`/search?q=${word}`);
    const hit = page.getByRole("link", { name: new RegExp(`Shared.*${word}.*roadmap`) });
    await expect(hit).toBeVisible();
    await expect(page.getByText("Organisation record")).toBeVisible();

    await hit.click();
    await expect(page).toHaveURL(new RegExp(`/orgs/${org.id}/modules/context_strategy/strategies/${strategy.id}$`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(`Shared ${word} roadmap`);

    // A search of one project covers its organisation's records too, until the filter is switched off.
    await page.goto(`/search?q=${word}&scope=project&project=${project.id}`);
    await expect(hit).toBeVisible();
    // The box is controlled by the URL, which updates a beat after the click, so assert the result rather than `uncheck()`.
    const include = page.getByRole("checkbox", { name: "Include organisation records" });
    await expect(include).toBeChecked();
    await include.click();
    await expect(include).not.toBeChecked();
    await expect(page.getByText("Nothing found")).toBeVisible();
    await expect(page).toHaveURL(/orgrecords=0/);
  });
});
