import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: someone submits an enhancement request from the project's list, scores it as they go, and a
 * triager walks it through review, declines it with a reason and reopens it.
 *
 * Builds its own disposable org (see `./helpers.ts`), so it depends on no seeded state.
 */
test.describe("Enhancement requests: submit, score and decide", () => {
  test("submits a scored request, flags the missing Pain Point, declines with a reason and reopens", async ({ page }) => {
    const { suffix, project } = await setUpOrg(page, "FeedbackLife");
    const title = `Export the list to Excel ${suffix}`;
    const list = `/projects/${project.id}/modules/product_feedback/requests`;

    await test.step("the project's nav rail links to an empty list", async () => {
      await page.goto(`/projects/${project.id}`);
      await page.getByRole("link", { name: "Enhancement requests", exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`${list}(\\?.*)?$`));
      await expect(page.getByText("No enhancement requests in this project yet.")).toBeVisible();
    });

    await test.step("a new request is submitted with scoring levels from the form", async () => {
      await page.getByRole("button", { name: "New request" }).click();
      const dialog = page.getByRole("dialog", { name: /New enhancement request/ });
      await dialog.getByLabel("Request title").fill(title);
      await dialog.getByLabel("Impact").selectOption({ label: "High" });
      await dialog.getByLabel("Confidence").selectOption({ label: "High" });
      await dialog.getByLabel("Ease").selectOption({ label: "Easy" });
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Request submitted.")).toBeVisible();
    });

    await test.step("the list shows its code, status, score and the missing-Pain-Point warning", async () => {
      const row = page.getByRole("row", { name: new RegExp(title) });
      await expect(row.getByRole("link", { name: "ENH-001" })).toBeVisible();
      await expect(row.getByText("New", { exact: true })).toBeVisible();
      await expect(row.getByText("No Pain Point")).toBeVisible();
      await expect(row.getByText(/· \d+/).first()).toBeVisible();
    });

    await test.step("the detail page carries the same warning, and starting review moves the status", async () => {
      await page.getByRole("link", { name: "ENH-001" }).click();
      await expect(page.getByRole("heading", { name: new RegExp(title) })).toBeVisible();
      await expect(page.getByText("No Pain Point linked")).toBeVisible();
      await page.getByRole("button", { name: "Start review" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Start review" }).click();
      await expect(page.locator("span.badge", { hasText: /^Under review$/ })).toBeVisible();
    });

    await test.step("declining needs a reason, which is then shown", async () => {
      await page.getByRole("button", { name: "Decline", exact: true }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByRole("button", { name: "Decline", exact: true })).toBeDisabled();
      await dialog.getByLabel(/Decline reason/).fill("Out of scope for this product.");
      await dialog.getByRole("button", { name: "Decline", exact: true }).click();
      await expect(page.locator("span.badge", { hasText: /^Declined$/ })).toBeVisible();
      await expect(page.getByRole("region", { name: "Details" }).getByText("Out of scope for this product.")).toBeVisible();
    });

    await test.step("a declined request can be reopened to New", async () => {
      await page.getByRole("button", { name: "Reopen" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Reopen" }).click();
      await expect(page.locator("span.badge", { hasText: /^New$/ })).toBeVisible();
    });
  });
});
