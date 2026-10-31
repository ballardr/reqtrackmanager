import crypto from "node:crypto";
import fs from "node:fs";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { chooseReport } from "./reportPicker";
import {
  deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, openSetupReport, PASSWORD, saveNewVersion, selectOrgAdminGroup, selectProjectAdminGroup,
} from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: have every downloaded or stored report named the way the team files them, for example
 * "ACME-Quarterly review-2026-10-29.pdf", from a template with placeholders that is checked as it is typed, set once
 * on a pack or for the whole organisation.
 *
 * Each test works in its own disposable organisation (created and deleted through the API) with uniquely named
 * layouts, packs and records, so it passes alone, in any order and repeated.
 */
test.describe("Report file names", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation and project with a document layout; the page is left logged in as the admin. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-file-names-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E File Names ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Names Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Names project ${suffix}`, summary: "" } })).json();
    const base = `${API}/projects/${project.id}`;
    const text = '@layout document\n@heading Overview of {{project_name}}\n';
    const parsed = await (await request.post(`${base}/report-layouts/text/parse`, { headers, data: { text } })).json();
    const layoutName = `E2E Named ${suffix}`;
    const created = await request.post(`${base}/report-layouts`, {
      headers, data: { name: layoutName, description: "E2E", family: "document", tree: parsed.tree },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    return { org, headers, project, base, layoutName, suffix };
  }

  test("a pack's zip and its report take the names typed in the pack editor", async ({ page, request }) => {
    const { headers, project, base, layoutName, suffix } = await setup(page, request);
    const packName = `E2E Named pack ${suffix}`;
    const made = await request.post(`${base}/report-packs`, {
      headers, data: {
        name: packName, description: "E2E",
        definition: { schema_version: 1, entries: [{ kind: "layout", name: layoutName, format: "html" }] },
      },
    });
    expect(made.ok(), await made.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await openSetupReport(page, packName);

    await test.step("the live example follows what is typed and names a mistake", async () => {
      const zipName = page.getByRole("textbox", { name: "Zip file name" });
      await zipName.fill("{{report_title}}-{{generated_on}}");
      await expect(page.getByText(/^Example: Quarterly review-2026-10-29\.zip$/)).toBeVisible();
      await zipName.fill("{{record.code}}");
      await expect(page.getByRole("alert").filter({ hasText: "no current record" })).toBeVisible();
    });

    await test.step("a placeholder is inserted from the list and the names are saved as a new version", async () => {
      const zipName = page.getByRole("textbox", { name: "Zip file name" });
      await zipName.fill("pack-");
      await page.getByRole("combobox", { name: "Insert placeholder" }).first().selectOption("{{project_name}}");
      await expect(zipName).toHaveValue("pack-{{project_name}}");
      const entry = page.getByRole("region", { name: "Report 1" });
      await entry.getByRole("textbox", { name: "File name" }).fill("{{report_title}}-v{{layout_version}}");
      await saveNewVersion(page, "Name the files");
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
    });

    await test.step("the zip is downloaded under the pack's name and holds the report under the entry's", async () => {
      await page.goto(`/projects/${project.id}?reports=choose`);
      await chooseReport(page, packName);
      const pending = page.waitForEvent("download");
      await page.getByRole("button", { name: "Download zip" }).click();
      const download = await pending;
      expect(download.suggestedFilename()).toBe(`pack-${project.name}.zip`);
      const names = fs.readFileSync((await download.path())!).toString("latin1");
      expect(names).toContain(`01-${layoutName}-v1.html`);
    });
  });

  test("the organisation default names a built-in report that sets no name of its own", async ({ page, request }) => {
    const { org, headers, project } = await setup(page, request);
    const requirementsReport = () =>
      request.post(`${API}/projects/${project.id}/reports`, { headers, data: { format: "csv" } });
    expect((await requirementsReport()).headers()["content-disposition"]).toContain(`${project.name}-requirements.csv`);

    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Templates & reports");
    await ensureExpanded(page, "Configuration");

    await test.step("an invalid default is explained and a valid one is saved", async () => {
      const field = page.getByRole("textbox", { name: "Default report file name" });
      await field.fill("{{layout_version}}");
      await expect(page.getByRole("alert").filter({ hasText: "Unknown placeholder" })).toBeVisible();
      await field.fill("{{project_name}}-{{report_title}}");
      await expect(page.getByText(/^Example: Apollo-Quarterly review\.pdf$/)).toBeVisible();
      await page.getByRole("button", { name: "Save configuration" }).click();
      await expect(page.getByText("Settings saved.")).toBeVisible();
    });

    await test.step("the setting is kept and the report downloads under it", async () => {
      await page.reload();
      await selectOrgAdminGroup(page, "Templates & reports");
      await ensureExpanded(page, "Configuration");
      await expect(page.getByRole("textbox", { name: "Default report file name" })).toHaveValue("{{project_name}}-{{report_title}}");
      const disposition = (await requirementsReport()).headers()["content-disposition"];
      expect(disposition).toContain(`${project.name}-Requirements report.csv`);
    });
  });
});
