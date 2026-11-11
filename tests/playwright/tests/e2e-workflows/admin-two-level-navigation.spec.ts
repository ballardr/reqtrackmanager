import { expect, test } from "@playwright/test";

import { installCleanupHook, selectProjectAdminGroup } from "./helpers";
import { setUpOrg } from "../modules/product_feedback/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an administrator finds a module's settings under one expandable menu entry in the project and
 * organisation admin menus, and an address from before the entries were grouped still opens the right page.
 *
 * Builds its own disposable org (see `../modules/product_feedback/helpers.ts`), so it depends on no seeded state.
 * Product Feedback is the module used because it contributes several sections at both tiers.
 */
test.describe("admin menus: two-level navigation", () => {
  test("a module's sections sit under one expandable entry that opens with the active page", async ({ page }) => {
    const { project } = await setUpOrg(page, "AdminTwoLevelProject");
    await page.goto(`/projects/${project.id}/admin`);

    const header = page.getByRole("button", { name: "Product Feedback", exact: true });
    await test.step("the group starts closed and lists no sub-pages", async () => {
      await expect(header).toHaveAttribute("aria-expanded", "false");
      await expect(page.getByRole("link", { name: "Request Scoring", exact: true })).toHaveCount(0);
    });

    await test.step("opening the group does not leave the page, and a sub-page has a two-level address", async () => {
      await header.click();
      await expect(header).toHaveAttribute("aria-expanded", "true");
      await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/admin/?$`));
      await page.getByRole("link", { name: "Request Scoring", exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/admin/product-feedback/product-feedback-scoring$`));
      await expect(page.getByRole("link", { name: "Request Scoring", exact: true })).toHaveAttribute("aria-current", "page");
    });

    await test.step("a reload keeps the group open on the same sub-page", async () => {
      await page.reload();
      await expect(header).toHaveAttribute("aria-expanded", "true");
      await expect(page.getByRole("link", { name: "Request Scoring", exact: true })).toHaveAttribute("aria-current", "page");
    });

    await test.step("the group can be closed and the keyboard moves between rows", async () => {
      await header.focus();
      await page.keyboard.press("Enter");
      await expect(header).toHaveAttribute("aria-expanded", "false");
      await page.keyboard.press("Enter");
      await expect(header).toHaveAttribute("aria-expanded", "true");
      await page.keyboard.press("ArrowDown");
      await expect(page.getByRole("link", { name: "Submission policy", exact: true })).toBeFocused();
    });

    await test.step("the helper reaches a sub-page of a closed group", async () => {
      await page.goto(`/projects/${project.id}/admin/overview`);
      await selectProjectAdminGroup(page, "Request Channels", "Product Feedback");
      await expect(page).toHaveURL(/\/admin\/product-feedback\/product-feedback-request-channels$/);
    });
  });

  test("an address from before the entries were grouped opens the grouped page", async ({ page }) => {
    const { org, project } = await setUpOrg(page, "AdminTwoLevelRedirect");

    await test.step("a project: the earlier one-level address", async () => {
      await page.goto(`/projects/${project.id}/admin/product-feedback-request-channels`);
      await expect(page).toHaveURL(/\/admin\/product-feedback\/product-feedback-request-channels$/);
      await expect(page.getByRole("link", { name: "Request Channels", exact: true })).toHaveAttribute("aria-current", "page");
    });

    await test.step("a project: the group address opens its first page", async () => {
      await page.goto(`/projects/${project.id}/admin/product-feedback`);
      await expect(page).toHaveURL(/\/admin\/product-feedback\/product-feedback-settings$/);
    });

    await test.step("a project: an unknown page under the group opens its first page", async () => {
      await page.goto(`/projects/${project.id}/admin/product-feedback/not-a-page`);
      await expect(page).toHaveURL(/\/admin\/product-feedback\/product-feedback-settings$/);
    });

    await test.step("an organisation: the earlier address and the group address", async () => {
      await page.goto(`/orgs/${org.id}/admin/product-feedback-scoring`);
      await expect(page).toHaveURL(/\/admin\/product-feedback\/product-feedback-scoring$/);
      await page.goto(`/orgs/${org.id}/admin/product-feedback`);
      await expect(page).toHaveURL(/\/admin\/product-feedback\/product-feedback-scoring$/);
      await expect(page.getByRole("button", { name: "Product Feedback", exact: true })).toHaveAttribute("aria-expanded", "true");
    });
  });
});
