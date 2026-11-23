import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, logout, PASSWORD, PERSONAS } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: exporting an entire organisation (settings, members, report templates, every project's structure
 * and history) as a bundle and importing it to create a new organisation: the UI path for backup, offboarding and
 * migration (`services.org_export`).
 *
 * Reuses none of the shared Alpha/Beta/Gamma personas: an import grants the matched existing administrator a real
 * role in the new organisation, which would turn e.g. orgAdminGamma from single-org into multi-org for every spec
 * that navigates via `/orgs` relying on the single-org redirect. Everything is built through the API with a
 * disposable admin account.
 */
test.describe("organisation bundle export/import", () => {
  test("export an organisation from its admin page, then import it as a new organisation", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);
    const serverAdminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${serverAdminToken}` };

    const suffix = Date.now();
    const sourceOrgName = `E2E Bundle Source Org (${suffix})`;
    const bundleAdminEmail = `e2e-bundle-admin-${suffix}@example.com`;

    const sourceOrg = await (
      await page.request.post("http://localhost:8000/api/v1/orgs", { headers: authHeaders, data: { name: sourceOrgName } })
    ).json();
    deleteOrgOnCleanup({ id: sourceOrg.id });
    // Server admins hold no org membership by default (I-M-05) — self-
    // elevate just long enough to bootstrap the org's real admin, the same
    // pattern backend/scripts/seed_e2e_dataset.py itself uses for its
    // zero-org server-admin persona.
    await page.request.post(`http://localhost:8000/api/v1/orgs/${sourceOrg.id}/join-as-admin`, { headers: authHeaders });
    await page.request.post(`http://localhost:8000/api/v1/orgs/${sourceOrg.id}/users`, {
      headers: authHeaders,
      data: { email: bundleAdminEmail, display_name: "E2E Bundle Admin", password: PASSWORD, role: "org_admin" },
    });
    // Leave *before* any project exists in this org, so the server admin
    // never holds a project role here at all (there's nothing to reassign
    // and no lingering grant to worry about) — the org's real admin
    // creates the project themselves below, once they're the only member.
    await page.request.delete(`http://localhost:8000/api/v1/orgs/${sourceOrg.id}/membership`, { headers: authHeaders });

    const bundleAdminToken = (
      await (
        await page.request.post("http://localhost:8000/api/v1/auth/login", { data: { email: bundleAdminEmail, password: PASSWORD } })
      ).json()
    ).access_token;
    await page.request.post("http://localhost:8000/api/v1/projects", {
      headers: { Authorization: `Bearer ${bundleAdminToken}` },
      data: { organization_id: sourceOrg.id, name: "E2E Bundle Source Project", summary: "" },
    });

    await logout(page);
    await loginAs(page, bundleAdminEmail, PASSWORD);

    let exportedPath: string;
    await test.step("export the organisation bundle from its admin page", async () => {
      await page.goto("/orgs");
      await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
      // Style guide "Pattern: action menu" — rename + export now live
      // behind the Overview group's kebab trigger, not a standalone button.
      await page.getByRole("button", { name: "Organisation actions" }).click();
      // See the identical fix (and its full explanation) in
      // org-merge-import.spec.ts: clicking the menuitem before the
      // `Popover`-based menu finishes positioning can silently miss it.
      await expect(page.getByRole("menu", { name: "Organisation actions" })).toBeVisible();
      const downloadPromise = page.waitForEvent("download");
      await page.getByRole("menuitem", { name: "Export organisation bundle" }).click();
      const download = await downloadPromise;
      expect(download.suggestedFilename()).toMatch(/-export\.zip$/);
      exportedPath = (await download.path())!;
    });

    await logout(page);
    await loginAs(page, PERSONAS.serverAdmin.email);

    await test.step("import the bundle as a new organisation", async () => {
      const newOrgName = `E2E Imported Org (${suffix})`;
      deleteOrgOnCleanup({ nameContains: newOrgName });
      await page.getByRole("link", { name: "Organisations", exact: true }).click();
      await expect(page).toHaveURL(/\/server\/organisations$/);
      // Import is the second door beside "New organisation": the split button's chevron offers it and it
      // opens its own dialog, scoped here rather than the whole page.
      await page.getByRole("button", { name: "More options" }).click();
      await page.getByRole("menuitem", { name: "Import organisation" }).click();
      const dialog = page.getByRole("dialog", { name: "Import organisation" });
      await dialog.getByLabel(/Organisation name/).fill(newOrgName);
      const fileInput = dialog.locator('input[type="file"][accept*="zip"]');
      await fileInput.setInputFiles(exportedPath);
      await dialog.getByRole("button", { name: "Import", exact: true }).click();

      await expect(page.getByText(newOrgName)).toBeVisible({ timeout: 15000 });
      // Style guide "Pattern: action menu" — the row's Edit/Disable-Enable/
      // Delete buttons now live behind one `ActionMenu` kebab trigger
      // (ServerOrganisationsPage.tsx), not a standalone link.
      await page.getByRole("button", { name: `${newOrgName} actions` }).click();
      await expect(page.getByRole("menu", { name: `${newOrgName} actions` })).toBeVisible();
      await page.getByRole("menuitem", { name: "Administration" }).click();
      await expect(page).toHaveURL(/\/orgs\/[0-9a-f-]+\/admin$/);
      await expect(page.getByRole("heading", { name: newOrgName })).toBeVisible();
      const newOrgId = page.url().match(/orgs\/([0-9a-f-]+)\/admin/)![1];

      // The importing server admin has no role in the new organisation (no bypass), so the project would show in their
      // "Projects" tab only if the "guaranteed project manager" fallback wrongly attributed it to them; the check runs as
      // the bundle admin (granted org_admin by the import, matched by email).
      const bundleAdminToken2 = (
        await (
          await page.request.post("http://localhost:8000/api/v1/auth/login", { data: { email: bundleAdminEmail, password: PASSWORD } })
        ).json()
      ).access_token;
      const importedProjects: { name: string }[] = await (
        await page.request.get(`http://localhost:8000/api/v1/projects?organization_id=${newOrgId}`, {
          headers: { Authorization: `Bearer ${bundleAdminToken2}` },
        })
      ).json();
      expect(importedProjects.map((p) => p.name)).toContain("E2E Bundle Source Project");
    });

    fs.rmSync(exportedPath!, { force: true });
  });
});
