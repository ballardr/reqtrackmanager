import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { loginAs, logout, PASSWORD, PERSONAS } from "./helpers";

/**
 * Job to be done: merging an exported organisation bundle into an
 * *existing* organisation — the "Import into this organisation" action on
 * the org admin page (`services.org_export.merge_org_bundle`,
 * `POST /orgs/{id}/import/preview` + `.../import/merge`) — as opposed to
 * `org-bundle-export-import.spec.ts`, which always creates a brand-new
 * organisation. Drives a project-name collision through the actual
 * conflict-resolution UI and confirms the target organisation's own
 * branding is untouched by the merge.
 *
 * Disposable orgs built from scratch via the API, same reasoning as
 * `org-bundle-export-import.spec.ts`: importing/merging genuinely grants
 * real roles and creates real projects, which would pollute the shared
 * Alpha/Beta/Gamma personas other specs in this suite depend on staying
 * in a known state.
 */
test.describe("organisation bundle merge-import", () => {
  test("merge a bundle into an existing organisation, resolving a project-name conflict", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);
    const serverAdminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${serverAdminToken}` };

    const suffix = Date.now();
    const sourceOrgName = `E2E Merge Source Org (${suffix})`;
    const targetOrgName = `E2E Merge Target Org (${suffix})`;
    const sourceAdminEmail = `e2e-merge-source-admin-${suffix}@example.com`;
    const targetAdminEmail = `e2e-merge-target-admin-${suffix}@example.com`;
    const sharedProjectName = `E2E Merge Shared Project (${suffix})`;

    const sourceOrg = await (
      await page.request.post("http://localhost:8000/api/v1/orgs", { headers: authHeaders, data: { name: sourceOrgName } })
    ).json();
    await page.request.post(`http://localhost:8000/api/v1/orgs/${sourceOrg.id}/join-as-admin`, { headers: authHeaders });
    await page.request.post(`http://localhost:8000/api/v1/orgs/${sourceOrg.id}/users`, {
      headers: authHeaders,
      data: { email: sourceAdminEmail, display_name: "E2E Merge Source Admin", password: PASSWORD, role: "org_admin" },
    });
    await page.request.delete(`http://localhost:8000/api/v1/orgs/${sourceOrg.id}/membership`, { headers: authHeaders });

    const sourceAdminToken = (
      await (
        await page.request.post("http://localhost:8000/api/v1/auth/login", { data: { email: sourceAdminEmail, password: PASSWORD } })
      ).json()
    ).access_token;
    await page.request.post("http://localhost:8000/api/v1/projects", {
      headers: { Authorization: `Bearer ${sourceAdminToken}` },
      data: { organization_id: sourceOrg.id, name: sharedProjectName, summary: "" },
    });

    const targetOrg = await (
      await page.request.post("http://localhost:8000/api/v1/orgs", { headers: authHeaders, data: { name: targetOrgName } })
    ).json();
    await page.request.post(`http://localhost:8000/api/v1/orgs/${targetOrg.id}/join-as-admin`, { headers: authHeaders });
    await page.request.post(`http://localhost:8000/api/v1/orgs/${targetOrg.id}/users`, {
      headers: authHeaders,
      data: { email: targetAdminEmail, display_name: "E2E Merge Target Admin", password: PASSWORD, role: "org_admin" },
    });
    await page.request.delete(`http://localhost:8000/api/v1/orgs/${targetOrg.id}/membership`, { headers: authHeaders });

    const targetAdminToken = (
      await (
        await page.request.post("http://localhost:8000/api/v1/auth/login", { data: { email: targetAdminEmail, password: PASSWORD } })
      ).json()
    ).access_token;
    // Deliberately the same name as the source org's project, and a
    // deliberately different accent colour — the collision the conflict
    // panel resolves, and the org-profile field that must survive
    // untouched by the merge.
    await page.request.post("http://localhost:8000/api/v1/projects", {
      headers: { Authorization: `Bearer ${targetAdminToken}` },
      data: { organization_id: targetOrg.id, name: sharedProjectName, summary: "" },
    });
    await page.request.put(`http://localhost:8000/api/v1/orgs/${targetOrg.id}/branding`, {
      headers: { Authorization: `Bearer ${targetAdminToken}` },
      data: { accent_color_hex: "#123456", header_title: "Target Org Header" },
    });

    await logout(page);
    await loginAs(page, sourceAdminEmail, PASSWORD);

    let exportedPath: string;
    await test.step("export the source organisation's bundle", async () => {
      await page.goto("/orgs");
      await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
      // Style guide "Pattern: action menu" — rename + export now live
      // behind the Overview group's kebab trigger, not a standalone button.
      await page.getByRole("button", { name: "Organisation actions" }).click();
      const downloadPromise = page.waitForEvent("download");
      await page.getByRole("menuitem", { name: "Export organisation bundle" }).click();
      const download = await downloadPromise;
      exportedPath = (await download.path())!;
    });

    await logout(page);
    await loginAs(page, targetAdminEmail, PASSWORD);

    await test.step("upload the bundle and resolve the project-name conflict as a copy", async () => {
      await page.goto("/orgs");
      await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);
      await page.getByRole("button", { name: `Import into this organisation` }).click();
      const fileInput = page.locator('input[type="file"][accept*="zip"]');
      await fileInput.setInputFiles(exportedPath!);
      await page.getByRole("button", { name: "Preview import" }).click();

      await expect(page.getByText("1 conflict(s) to resolve before importing")).toBeVisible({ timeout: 10000 });
      await expect(page.getByText(sharedProjectName)).toBeVisible();
      await page.getByRole("radio", { name: "Import as a new copy" }).check();
      await page.getByRole("button", { name: "Import", exact: true }).click();

      await expect(page.getByText("Import complete")).toBeVisible({ timeout: 15000 });
      await expect(page.getByText("1 project(s) imported")).toBeVisible();
      await expect(page.getByText("0 project(s) skipped")).toBeVisible();
    });

    await test.step("the target organisation now has both projects, and its own branding is untouched", async () => {
      const targetProjects: { name: string }[] = await (
        await page.request.get(`http://localhost:8000/api/v1/projects?organization_id=${targetOrg.id}`, {
          headers: { Authorization: `Bearer ${targetAdminToken}` },
        })
      ).json();
      const names = targetProjects.map((p) => p.name);
      expect(names).toContain(sharedProjectName);
      expect(names).toContain(`${sharedProjectName} (imported)`);

      const targetOrgAfter = await (
        await page.request.get(`http://localhost:8000/api/v1/orgs/${targetOrg.id}`, {
          headers: { Authorization: `Bearer ${targetAdminToken}` },
        })
      ).json();
      expect(targetOrgAfter.accent_color_hex).toBe("#123456");
      expect(targetOrgAfter.header_title).toBe("Target Org Header");
    });

    fs.rmSync(exportedPath!, { force: true });
  });
});
