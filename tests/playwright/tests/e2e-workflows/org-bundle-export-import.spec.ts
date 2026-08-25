import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { loginAs, logout, PASSWORD, PERSONAS } from "./helpers";

/**
 * Job to be done: exporting an entire organisation (settings, members,
 * report templates, every project's full structure/history) as a self-
 * describing bundle, and importing it to stand up a brand-new organisation
 * — the actual UI path for org backup/offboarding/migration
 * (`services.org_export`), not just the underlying API.
 *
 * Deliberately does NOT reuse any of the shared Alpha/Beta/Gamma personas:
 * importing an org bundle genuinely grants the matched existing admin a
 * real role in the freshly-created org (that's the feature working
 * correctly, not a test artifact) — reusing e.g. orgAdminGamma here would
 * permanently turn that persona from single-org into multi-org for every
 * other spec in this suite that assumes it stays single-org (several
 * specs navigate via `/orgs` relying on its single-org auto-redirect).
 * Everything below is built from scratch via the API and torn down to a
 * disposable admin account instead.
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
      await page.getByRole("link", { name: "Organisations", exact: true }).click();
      await expect(page).toHaveURL(/\/server\/organisations$/);
      // "New organisation" opens a Modal (style guide "Pattern: modal
      // dialog for entity create/rename") — scoped to it rather than the
      // whole page.
      await page.getByRole("button", { name: "New organisation" }).click();
      const dialog = page.getByRole("dialog", { name: "New organisation" });
      await dialog.getByLabel(/Organisation name/).fill(newOrgName);
      const fileInput = dialog.locator('input[type="file"][accept*="zip"]');
      await fileInput.setInputFiles(exportedPath);
      await dialog.getByRole("button", { name: "Create" }).click();

      await expect(page.getByText(newOrgName)).toBeVisible({ timeout: 15000 });
      await page.getByText(newOrgName).locator("..").getByRole("link", { name: "Edit" }).click();
      await expect(page).toHaveURL(/\/orgs\/[0-9a-f-]+\/admin$/);
      await expect(page.getByRole("heading", { name: newOrgName })).toBeVisible();
      const newOrgId = page.url().match(/orgs\/([0-9a-f-]+)\/admin/)![1];

      // The server admin who ran the import has no role in the new org
      // themselves (I-M-05: no bypass) — this project only shows up in
      // *their* "Projects" tab if the "guaranteed project manager" fallback
      // wrongly attributed to them instead of the org's real admin. Verify
      // as the bundle admin (who was granted a real org_admin role by the
      // import, matched by email) instead, confirming the fallback landed
      // on the right person.
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
