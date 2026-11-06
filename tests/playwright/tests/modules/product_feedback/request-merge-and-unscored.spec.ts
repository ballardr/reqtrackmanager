import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { createRequest, projectBase, requestLevels, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a triager finds the requests that still lack a score, and merges a duplicate into the request it
 * repeats (and can undo it), so demand adds up instead of being counted twice.
 *
 * Builds its own disposable org (see `./helpers.ts`), so it depends on no seeded state.
 */
test.describe("Enhancement requests: unscored filter and merge", () => {
  test("filters to unscored requests, merges a duplicate and undoes the merge", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "FeedbackMerge");
    const { level } = await requestLevels(page, project.id, adminHeaders);
    const scored = await createRequest(page, projectBase(project.id), adminHeaders, {
      title: `Scored ask ${suffix}`,
      // Every manual axis, so it is scored whichever model the list treats as primary.
      levels: {
        reach: level("reach", "Many"), impact: level("impact", "High"), confidence: level("confidence", "High"),
        ease: level("ease", "Easy"), effort: level("effort", "Medium"),
      },
    });
    const unscored = await createRequest(page, projectBase(project.id), adminHeaders, { title: `Unscored ask ${suffix}` });
    const repeat = await createRequest(page, projectBase(project.id), adminHeaders, { title: `Same ask again ${suffix}` });
    const list = `/projects/${project.id}/modules/product_feedback/requests`;

    await test.step("the Unscored filter counts and narrows to requests missing a level", async () => {
      await page.goto(list);
      await expect(page.getByRole("link", { name: scored.unique_code })).toBeVisible();
      const scoring = page.getByRole("combobox", { name: "Scoring", exact: true });
      await expect(scoring).toContainText("Unscored (2)");
      await scoring.selectOption("unscored");
      await expect(page.getByRole("link", { name: unscored.unique_code })).toBeVisible();
      await expect(page.getByRole("link", { name: scored.unique_code })).toHaveCount(0);
      await expect(page).toHaveURL(/scored=unscored/);
    });

    await test.step("merging a duplicate marks it and names the request it repeats", async () => {
      await page.goto(`${list}/${repeat.id}`);
      await page.getByRole("button", { name: "Request actions" }).click();
      await page.getByRole("menuitem", { name: /Merge into another request/ }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Merge into").selectOption({ label: `${scored.unique_code} ${scored.title}` });
      await dialog.getByLabel("Note").fill("Same ask, different words");
      await dialog.getByRole("button", { name: "Merge" }).click();
      await expect(page.getByText("Request merged.")).toBeVisible();
      await expect(page.locator("span.badge", { hasText: /^Duplicate$/ })).toBeVisible();
      await expect(page.getByRole("link", { name: new RegExp(`${scored.unique_code} `) })).toBeVisible();
      await expect(page.getByRole("button", { name: "Undo merge" })).toBeVisible();
    });

    await test.step("the note says why, in the version history and in the merge history", async () => {
      await expect(page.getByRole("cell", { name: `Merged into ${scored.unique_code} as a duplicate. Same ask, different words` })).toBeVisible();
      await page.getByText(/^Merge history/).click();
      await expect(page.getByRole("table", { name: "Merge history" }).getByText("Same ask, different words")).toBeVisible();
    });

    await test.step("undoing the merge returns the request to its previous status", async () => {
      await page.getByRole("button", { name: "Undo merge" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Undo merge" }).click();
      await expect(page.getByText("Merge undone.")).toBeVisible();
      await expect(page.locator("span.badge", { hasText: /^New$/ })).toBeVisible();
    });
  });
});
