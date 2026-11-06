import { expect, test } from "@playwright/test";

import { installCleanupHook, selectProjectAdminGroup } from "../../e2e-workflows/helpers";
import { createRequest, orgBase, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a request that arrives before anyone knows its project waits in the organisation's inbox until a
 * triager moves it into one; a project administrator can restrict who may submit.
 *
 * Builds its own disposable org (see `./helpers.ts`), so it depends on no seeded state.
 */
test.describe("Enhancement requests: organisation inbox and submission setting", () => {
  test("triages an inbox request into a project, renumbering it there", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "FeedbackInbox");
    const title = `Inbox ask ${suffix}`;
    const request = await createRequest(page, orgBase(org.id), adminHeaders, { title });

    await test.step("the request opens at its organisation path and offers Move to a project", async () => {
      await page.goto(`/orgs/${org.id}/modules/product_feedback/requests/${request.id}`);
      await expect(page.getByRole("heading", { name: new RegExp(title) })).toBeVisible();
      await page.getByRole("button", { name: "Request actions" }).click();
      await page.getByRole("menuitem", { name: /Move to a project/ }).click();
    });

    await test.step("moving it lands on the project's copy with the project's code", async () => {
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByText(/cannot be undone/)).toBeVisible();
      await dialog.getByLabel("Project").selectOption({ label: project.name });
      await dialog.getByRole("button", { name: "Move" }).click();
      await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/product_feedback/requests/${request.id}$`));
      await expect(page.getByRole("heading", { name: new RegExp(title) })).toBeVisible();
    });
  });

  test("a project administrator can restrict submission to triagers", async ({ page }) => {
    const { project } = await setUpOrg(page, "FeedbackPolicy");

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Submission policy", "Product Feedback");
    const policy = page.getByLabel("Who can submit a request");
    await expect(policy).toHaveValue("members");
    await policy.selectOption("triagers");
    await expect(page.getByText("Submission setting saved.")).toBeVisible();

    await page.reload();
    await selectProjectAdminGroup(page, "Submission policy", "Product Feedback");
    await expect(page.getByLabel("Who can submit a request")).toHaveValue("triagers");
  });
});
