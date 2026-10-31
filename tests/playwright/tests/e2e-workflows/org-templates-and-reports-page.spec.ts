import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: open an organisation's Templates & reports page on the list of reports, with the other sections
 * out of the way, and set the output settings (file names, background report retention) with one Save.
 *
 * Each test works in its own disposable organisation and admin (created and deleted through the API), so the sections
 * start in their default state and the test passes alone, in any order and repeated.
 */
test.describe("Organisation Templates & reports page", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with an admin; the page is left logged in as that admin. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-tr-page-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Templates page ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Templates Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    return { org };
  }

  test("the page opens on the Reports list with every other section closed, and Configuration saves both settings at once", async ({ page, request }) => {
    const { org } = await setup(page, request);

    await test.step("only Reports is open", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Templates & reports");
      await expect(page.getByRole("button", { name: "Reports section" })).toHaveAttribute("aria-expanded", "true");
      for (const title of ["Report snippets", "Configuration"]) {
        await expect(page.getByRole("button", { name: `${title} section` })).toHaveAttribute("aria-expanded", "false");
      }
      await expect(page.getByRole("treegrid", { name: "Reports, packs and tables" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Report templates section" })).toHaveCount(0);
    });

    await test.step("one Save keeps the file name and the background retention", async () => {
      await ensureExpanded(page, "Configuration");
      await page.getByRole("textbox", { name: "Default report file name" }).fill("{{project_name}}-{{report_title}}");
      await page.getByLabel("Keep background report files for (days)").fill("4");
      await page.getByRole("textbox", { name: "Default footer text" }).fill("Confidential — E2E");
      await page.getByRole("checkbox", { name: "Include cover page" }).check();
      await page.getByRole("checkbox", { name: /^Chapter per/ }).uncheck();
      await expect(page.getByRole("button", { name: "Save configuration" })).toHaveCount(1);
      await page.getByRole("button", { name: "Save configuration" }).click();
      await expect(page.getByText("Settings saved.")).toBeVisible();

      await page.reload();
      await selectOrgAdminGroup(page, "Templates & reports");
      await ensureExpanded(page, "Configuration");
      await expect(page.getByRole("textbox", { name: "Default report file name" })).toHaveValue("{{project_name}}-{{report_title}}");
      await expect(page.getByLabel("Keep background report files for (days)")).toHaveValue("4");
      await expect(page.getByRole("textbox", { name: "Default footer text" })).toHaveValue("Confidential — E2E");
      await expect(page.getByRole("checkbox", { name: "Include cover page" })).toBeChecked();
      await expect(page.getByRole("checkbox", { name: /^Chapter per/ })).not.toBeChecked();
    });
  });

  test("Branding gives reports their own accent colour and decides whether they carry the logo", async ({ page, request }) => {
    const { org } = await setup(page, request);
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Branding & defaults");

    await test.step("reports follow the UI accent until they are given their own", async () => {
      const own = page.getByRole("checkbox", { name: "Give reports their own accent colour" });
      await expect(own).not.toBeChecked();
      await expect(page.getByLabel("Report accent colour")).toHaveCount(0);
      await own.check();
      await expect(page.getByLabel("Report accent colour")).toBeVisible();
      await page.getByRole("checkbox", { name: /^Include .* logo$/ }).uncheck();
      await page.getByRole("button", { name: "Save branding" }).click();
      await expect(page.getByText("Branding saved")).toBeVisible();
    });

    await test.step("the choices are kept", async () => {
      await page.reload();
      await selectOrgAdminGroup(page, "Branding & defaults");
      await expect(page.getByRole("checkbox", { name: "Give reports their own accent colour" })).toBeChecked();
      await expect(page.getByRole("checkbox", { name: /^Include .* logo$/ })).not.toBeChecked();
    });
  });
});
