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
      const downloadPromise = page.waitForEvent("download");
      await page.getByRole("button", { name: "Export organisation bundle" }).click();
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
      await page.getByRole("button", { name: "New organisation" }).click();
      await page.getByPlaceholder(/Organisation name/).fill(newOrgName);
      const fileInput = page.locator('input[type="file"][accept*="zip"]');
      await fileInput.setInputFiles(exportedPath);
      await page.getByRole("button", { name: "Create" }).click();

      await expect(page.getByText(newOrgName)).toBeVisible({ timeout: 15000 });
      await page.getByText(newOrgName).locator("..").getByRole("link", { name: "Edit" }).click();
      await expect(page).toHaveURL(/\/orgs\/[0-9a-f-]+\/admin$/);
      await expect(page.getByRole("heading", { name: newOrgName })).toBeVisible();

      await page.getByRole("link", { name: "Projects", exact: true }).click();
      await expect(page.getByText("E2E Bundle Source Project")).toBeVisible();
    });

    fs.rmSync(exportedPath!, { force: true });
  });
});
