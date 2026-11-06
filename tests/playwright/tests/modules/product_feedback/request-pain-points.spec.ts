import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { createRequest, enablePainPoints, projectBase, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a triager sees which requests state no problem, creates the Pain Point a request addresses from the
 * request's own Links panel, and filters the list by whether a request has one. Where Pain Points are off, none of
 * it is offered.
 *
 * Builds its own disposable org (see `./helpers.ts`), so it depends on no seeded state.
 */
test.describe("Enhancement requests: Pain Points", () => {
  test("a Pain Point is created and linked from the request's Links panel, then filtered and counted in the list", async ({ page }) => {
    const { suffix, project, org, adminHeaders } = await setUpOrg(page, "FeedbackPainPoints");
    await enablePainPoints(page, org.id, adminHeaders);
    const withPain = await createRequest(page, projectBase(project.id), adminHeaders, { title: `Has problem ${suffix}` });
    await createRequest(page, projectBase(project.id), adminHeaders, { title: `No problem ${suffix}` });
    const list = `/projects/${project.id}/modules/product_feedback/requests`;

    await test.step("Create new in the Links panel makes the Pain Point and links it", async () => {
      await page.goto(`${list}/${withPain.id}`);
      await page.getByRole("button", { name: "Create a record and link it" }).click();
      await page.getByRole("button", { name: "New Pain Point" }).click();
      const dialog = page.getByRole("dialog", { name: /New Pain Point/ });
      await dialog.getByLabel("Type").selectOption({ index: 1 });
      await dialog.getByLabel("Pain Point title").fill(`Slow exports ${suffix}`);
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Pain Point created and linked.")).toBeVisible();
      await expect(page.getByRole("link", { name: new RegExp(`Slow exports ${suffix}`) })).toBeVisible();
      await expect(page.getByText("No Pain Point linked")).toHaveCount(0);
    });

    await test.step("the list counts them in an optional column, and the filter narrows to none or some", async () => {
      await page.goto(list);
      const table = page.getByRole("table", { name: "Enhancement requests" });
      await expect(table.getByText(`No problem ${suffix}`)).toBeVisible();
      await page.getByRole("button", { name: "Choose columns" }).click();
      await page.getByRole("dialog", { name: "Columns" }).getByRole("checkbox", { name: "Pain Points", exact: true }).check();
      await expect(table.getByRole("row", { name: new RegExp(`No problem ${suffix}`) }).getByText("None", { exact: true })).toBeVisible();
      await page.getByRole("combobox", { name: "Pain Points", exact: true }).selectOption("none");
      await expect(table.getByText(`No problem ${suffix}`)).toBeVisible();
      await expect(table.getByText(`Has problem ${suffix}`)).toHaveCount(0);
      await page.getByRole("combobox", { name: "Pain Points", exact: true }).selectOption("some");
      await expect(table.getByText(`Has problem ${suffix}`)).toBeVisible();
      await expect(table.getByText(`No problem ${suffix}`)).toHaveCount(0);
    });
  });

  test("where Pain Points are off the list offers no column or filter and the page no prompt", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "FeedbackNoPainPoints");
    const request = await createRequest(page, projectBase(project.id), adminHeaders, { title: `Stand-alone ${suffix}` });
    const list = `/projects/${project.id}/modules/product_feedback/requests`;

    await page.goto(list);
    await expect(page.getByRole("table", { name: "Enhancement requests" }).getByText(`Stand-alone ${suffix}`)).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Pain Points", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Choose columns" }).click();
    await expect(page.getByRole("dialog", { name: "Columns" }).getByRole("checkbox", { name: "Pain Points", exact: true })).toHaveCount(0);

    await page.goto(`${list}/${request.id}`);
    await expect(page.getByRole("region", { name: "Demand" })).toBeVisible();
    await expect(page.getByText("No Pain Point linked")).toHaveCount(0);
  });
});
