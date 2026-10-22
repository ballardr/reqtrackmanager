import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, createRisk, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: the Risks register opens on the risks still being managed, so a rejected or
 * closed one does not bury them; a link that names a status, or says `open=0`, shows it anyway.
 * The same rule (`hooks/useOpenOnly.ts`) backs the Decisions, Open Questions and Pain Points lists.
 *
 * Builds its own disposable org (see `./helpers.ts`), so it depends on no seeded state.
 */
test.describe("Risks register: open only by default", () => {
  test("opens on open risks, and a status or open=0 link shows the rest", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "RiskOpenOnly");
    const openTitle = `Still being managed ${suffix}`;
    const rejectedTitle = `Ruled out ${suffix}`;
    const open = await createRisk(page, project.id, adminHeaders, { title: openTitle });
    const rejected = await createRisk(page, project.id, adminHeaders, { title: rejectedTitle });
    const moved = await page.request.post(
      `${API_BASE_URL}/api/v1/projects/${project.id}/modules/risk_management/risks/${rejected.id}/transition`,
      { headers: adminHeaders, data: { status: "rejected", comment: "Not applicable to this programme." } },
    );
    expect(moved.ok(), await moved.text()).toBeTruthy();
    const register = `/projects/${project.id}/modules/risk_management/risks`;

    await test.step("the register opens on open risks only, with the filter shown ticked", async () => {
      await page.goto(register);
      await expect(page.getByRole("checkbox", { name: "Open only" })).toBeChecked();
      await expect(page.getByRole("link", { name: open.unique_code })).toBeVisible();
      await expect(page.getByRole("link", { name: rejected.unique_code })).toHaveCount(0);
    });

    await test.step("unticking the filter shows the rejected risk", async () => {
      await page.getByRole("checkbox", { name: "Open only" }).uncheck();
      await expect(page.getByRole("link", { name: rejected.unique_code })).toBeVisible();
      await expect(page.getByRole("link", { name: open.unique_code })).toBeVisible();
    });

    await test.step("a link that names a status starts with the filter off", async () => {
      await page.goto(`${register}?status=rejected`);
      await expect(page.getByRole("checkbox", { name: "Open only" })).not.toBeChecked();
      await expect(page.getByRole("link", { name: rejected.unique_code })).toBeVisible();
      await expect(page.getByRole("link", { name: open.unique_code })).toHaveCount(0);
    });

    await test.step("open=0 shows everything", async () => {
      await page.goto(`${register}?open=0`);
      await expect(page.getByRole("checkbox", { name: "Open only" })).not.toBeChecked();
      await expect(page.getByRole("link", { name: rejected.unique_code })).toBeVisible();
      await expect(page.getByRole("link", { name: open.unique_code })).toBeVisible();
    });

    await test.step("when only the default hides everything, the empty state says so", async () => {
      const alsoMoved = await page.request.post(
        `${API_BASE_URL}/api/v1/projects/${project.id}/modules/risk_management/risks/${open.id}/transition`,
        { headers: adminHeaders, data: { status: "rejected", comment: "Also ruled out." } },
      );
      expect(alsoMoved.ok(), await alsoMoved.text()).toBeTruthy();
      await page.goto(register);
      await expect(page.getByText(/^No open Risks\. Untick Open only/)).toBeVisible();
    });
  });
});
