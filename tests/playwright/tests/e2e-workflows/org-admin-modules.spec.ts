import { expect, test } from "@playwright/test";

import { loginAs, PASSWORD, selectOrgAdminGroup, setOrgModuleAvailability } from "./helpers";

const apiBaseUrl = "http://localhost:8000";

/**
 * Job to be done: module system Phase 1 (docs/compliance-module-plan.md) —
 * Org Admin's "Modules" resource-menu group (`GET /orgs/{id}/modules`).
 *
 * Updated for Compliance Module Phase 12 (see docs/compliance-module-plan.md's
 * Phase 12 notes): this spec's own docstring originally flagged itself as
 * scoped to "no real module yet" and explicitly said to revisit once Phase 5
 * shipped a real first-party module. Phase 5 shipped Compliance
 * (`default_enabled=True`, `implemented=True`) well before this session, but
 * nothing had actually run this spec against a live, freshly-rebuilt
 * backend container since — `backend/app/modules/registry.py`'s
 * `INSTALLED_MODULES` list only reflects what's actually running, and the
 * container this repo's Playwright suite runs against had gone stale
 * (pre-Phase-5) until this session rebuilt it while verifying Phase 12's own
 * new e2e spec. This is that overdue revisit, not a Phase-12-specific
 * feature test.
 *
 * Uses a brand-new, disposable organisation + admin created via the API
 * (mirroring org-admin-project-statuses-and-link-types.spec.ts), not the
 * shared "E2E Gamma Labs" org/PERSONAS.orgAdminGamma this spec previously
 * ran against — this spec's own toggle-off-then-back-on already restores
 * Gamma's enablement state for *order* independence, but under real
 * concurrency (Phase 1, docs/platform-review-2026-09-plan.md) another spec
 * reading/writing Gamma (e.g. org-security-controls.spec.ts) could still
 * observe the module disabled mid-window. A disposable org removes that
 * collision entirely.
 */
test.describe("org admin: Modules section", () => {
  test("shows the Compliance module on by default, with one availability control and no column headers", async ({ page }) => {
    const suffix = Date.now();
    const adminEmail = `e2e-modules-admin-${suffix}@example.com`;

    const serverAdminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: "admin@example.com", password: "ChangeMe123!" },
    });
    const serverAdminToken = (await serverAdminLoginResp.json()).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };

    const org = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
        headers: serverAdminHeaders,
        data: { name: `E2E Modules Org ${suffix}` },
      })
    ).json();
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: "E2E Modules Admin", password: PASSWORD, role: "org_admin" },
    });

    await loginAs(page, adminEmail, PASSWORD);
    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");

    // The list replaced the old table: no column headers at all.
    await expect(page.locator(".module-settings-list")).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Default for new projects" })).toHaveCount(0);

    const select = page.getByRole("combobox", { name: "Compliance availability", exact: true });
    await expect(select).toHaveValue("default_on");
    await expect(select).toBeEnabled();

    // Change then restore — leaves this disposable org as found, per the
    // repo's test-idempotency rule.
    await setOrgModuleAvailability(page, "Compliance", "opt_in");
    await expect(page.getByText("Compliance: Available, off for new projects")).toBeVisible();
    await setOrgModuleAvailability(page, "Compliance", "default_on");
  });

  test("sub-components start collapsed behind a summary and expand to their own controls", async ({ page }) => {
    const suffix = Date.now();
    const adminEmail = `e2e-modules-sub-admin-${suffix}@example.com`;
    const serverAdminToken = (
      await (
        await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
          data: { email: "admin@example.com", password: "ChangeMe123!" },
        })
      ).json()
    ).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };
    const org = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
        headers: serverAdminHeaders,
        data: { name: `E2E Modules Sub Org ${suffix}` },
      })
    ).json();
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: "E2E Modules Sub Admin", password: PASSWORD, role: "org_admin" },
    });

    await loginAs(page, adminEmail, PASSWORD);
    await page.goto("/orgs");
    await selectOrgAdminGroup(page, "Modules");
    await setOrgModuleAvailability(page, "Context & Strategy", "default_on");

    const row = page.locator(".module-settings-row", { has: page.getByText("Context & Strategy", { exact: true }) });
    const disclosure = row.getByRole("button", { name: "5 components · all on" });
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByRole("combobox", { name: "Pain Points (Context & Strategy) availability" })).toHaveCount(0);

    await setOrgModuleAvailability(page, "Pain Points", "off", "Context & Strategy");
    await expect(row.getByRole("button", { name: "5 components · 1 off" })).toBeVisible();
  });
});
