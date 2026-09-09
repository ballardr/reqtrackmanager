import { expect, test } from "@playwright/test";

import { loginAs, ORG_NAMES, PERSONAS } from "../../e2e-workflows/helpers";
import { createStandardWithVersion } from "./helpers";

/**
 * Job to be done: docs/compliance-module-plan.md Phase 29 — three fixes to
 * `StandardNavSection.tsx`'s expandable "Versions" nav-rail group.
 *
 * `orgAdminAlphaBeta` is used for the same reason
 * `compliance-standards-management.spec.ts` uses it: `require_module_role
 * ("compliance", "standards_manager")` composes with `OrgRole.ORG_ADMIN` by
 * design, so no dedicated `standards_manager` persona/grant is needed here.
 */
test.describe("Compliance Module: Standard workspace version nav (Phase 29)", () => {
  test("landing directly on a version's URL auto-expands the nav with only that version's row active", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-29-${suffix}`;
    const standardName = `E2E Version Nav Standard ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await page.getByRole("button", { name: "v1.0" }).click();
    await expect(page).toHaveURL(/\/standards\/[0-9a-f-]+\/versions\/[0-9a-f-]+$/);
    const versionUrl = page.url();

    // A fresh, full navigation to the exact same URL — not an in-app click —
    // simulating a bookmark, a shared link, or a page refresh.
    await page.goto(versionUrl);

    const versionsToggle = page.getByRole("button", { name: "Collapse versions" });
    await expect(versionsToggle).toBeVisible();
    await expect(page.getByRole("link", { name: /v1\.0/ })).toHaveClass(/active/);
    await expect(page.getByRole("link", { name: "Versions", exact: true })).not.toHaveClass(/active/);
  });

  test("a manual click on the toggle collapses the group even while its own route forces it open", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-29b-${suffix}`;
    const standardName = `E2E Version Nav Collapse Standard ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await page.getByRole("button", { name: "v1.0" }).click();
    await page.goto(page.url());

    await expect(page.getByRole("button", { name: "Collapse versions" })).toBeVisible();
    await page.getByRole("button", { name: "Collapse versions" }).click();
    await expect(page.getByRole("link", { name: /v1\.0/ })).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Expand versions" })).toBeVisible();
  });

  test("switches versions from the version workspace via the entity quick-switch chevron", async ({ page }) => {
    const suffix = Date.now();
    const reference = `E2E-29c-${suffix}`;
    const standardName = `E2E Version Quick Switch Standard ${suffix}`;

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await createStandardWithVersion(page, { orgName: ORG_NAMES.alpha, reference, name: standardName, versionLabel: "v1.0" });

    await page.getByRole("link", { name: "Versions", exact: true }).click();
    await page.getByRole("button", { name: "New version" }).click();
    const dialog = page.getByRole("dialog", { name: "New version" });
    await dialog.getByLabel("Version label").fill("v1.1");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Version created.")).toBeVisible();

    await page.getByRole("button", { name: "v1.0" }).click();
    await expect(page).toHaveURL(/\/versions\/[0-9a-f-]+$/);

    await page.getByRole("button", { name: "Switch version" }).click();
    const switcherDialog = page.getByRole("dialog", { name: "Switch version" });
    await expect(switcherDialog).toBeVisible();
    await expect(switcherDialog.getByRole("link", { name: "v1.0" })).not.toBeVisible();

    await switcherDialog.getByRole("link", { name: "v1.1" }).click();
    await expect(page.getByRole("heading", { name: new RegExp(`${reference} — v1\\.1`) })).toBeVisible();
    await expect(switcherDialog).not.toBeVisible();
  });
});
