import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, searchReportSetup, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a project administrator wants to keep a layout (and a pack that runs it) as a file, or move it to a
 * project of another organisation: export it from Report setup, import the file where it is wanted, see what will
 * happen (a taken name is renamed, never replaced) and apply it.
 *
 * Each test works in its own disposable organisations (created and deleted through the API) with uniquely named reports,
 * so it passes alone, in any order and repeated.
 */
test.describe("Export and import reports as a file", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with an administrator, one project, and the administrator's headers. */
  async function organisation(request: APIRequestContext, label: string, suffix: string) {
    const email = `e2e-report-file-${label}-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Report File ${label} ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email, display_name: `E2E ${label}`, password: PASSWORD, role: "org_admin" },
    });
    const headers = await login(request, email, PASSWORD);
    const project = (await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `${label} ${suffix}`, summary: "" } })).json()) as { id: string; name: string };
    return { email, headers, project };
  }

  async function addLayout(request: APIRequestContext, headers: Record<string, string>, projectId: string, name: string) {
    const base = `${API}/projects/${projectId}`;
    const parsed = await (await request.post(`${base}/report-layouts/text/parse`, { headers, data: { text: "@layout document\n" } })).json();
    const created = await request.post(`${base}/report-layouts`, { headers, data: { name, description: "", family: "document", tree: parsed.tree } });
    expect(created.ok(), await created.text()).toBeTruthy();
  }

  async function ownNames(request: APIRequestContext, headers: Record<string, string>, projectId: string, kind: "layouts" | "packs") {
    const rows = (await (await request.get(`${API}/projects/${projectId}/report-${kind}`, { headers })).json()) as { name: string; origin: string }[];
    return rows.filter((r) => r.origin === "project").map((r) => r.name).sort();
  }

  async function setup(request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const source = await organisation(request, "source", suffix);
    const names = { layout: `Handover ${suffix}`, taken: `Status ${suffix}`, pack: `Board pack ${suffix}` };
    await addLayout(request, source.headers, source.project.id, names.layout);
    await addLayout(request, source.headers, source.project.id, names.taken);
    const pack = await request.post(`${API}/projects/${source.project.id}/report-packs`, {
      headers: source.headers,
      data: { name: names.pack, description: "", definition: { schema_version: 1, entries: [{ kind: "layout", name: names.layout, format: "html" }] } },
    });
    expect(pack.ok(), await pack.text()).toBeTruthy();
    return { source, names, suffix };
  }

  test("a layout and a pack are exported as one file and imported into a project of another organisation", async ({ page, request }) => {
    const { source, names, suffix } = await setup(request);
    const target = await organisation(request, "target", suffix);
    await addLayout(request, target.headers, target.project.id, names.taken); // the target already uses this name
    const saved = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "report-file-")), "reports.zip");

    await test.step("export the ticked layouts and the pack", async () => {
      await loginAs(page, source.email, PASSWORD);
      await page.goto(`/projects/${source.project.id}/admin`);
      await selectProjectAdminGroup(page, "Reports");
      await page.getByRole("button", { name: "Export several as file…" }).click();
      await expect(page.getByRole("button", { name: "Export file…" })).toBeDisabled();
      const grid = await searchReportSetup(page, suffix);
      for (const name of [names.layout, names.taken, names.pack]) await grid.getByRole("checkbox", { name: `Select ${name}` }).check();
      await expect(page.getByText("3 selected")).toBeVisible();
      await page.getByRole("button", { name: "Export file…" }).click();
      const dialog = page.getByRole("dialog", { name: "Export 3 reports as a file" });
      const [download] = await Promise.all([page.waitForEvent("download"), dialog.getByRole("button", { name: "Export" }).click()]);
      expect(download.suggestedFilename()).toMatch(/\.zip$/);
      await download.saveAs(saved);
      expect(fs.statSync(saved).size).toBeGreaterThan(100);
    });

    await test.step("preview the import in the other organisation: a taken name is renamed and nothing is written", async () => {
      await loginAs(page, target.email, PASSWORD);
      await page.goto(`/projects/${target.project.id}/admin`);
      await selectProjectAdminGroup(page, "Reports");
      await page.getByRole("button", { name: "New", exact: true }).click();
      await page.getByRole("menuitem", { name: "Import from file…" }).click();
      const dialog = page.getByRole("dialog", { name: "Import reports from a file" });
      await dialog.getByLabel("Report file").setInputFiles(saved);
      await dialog.getByRole("button", { name: "Preview" }).click();
      await expect(dialog.getByText(`${names.taken} → ${names.taken} (copy)`)).toBeVisible();
      await expect(dialog.getByText(names.pack, { exact: true })).toBeVisible();
      expect(await ownNames(request, target.headers, target.project.id, "layouts")).toEqual([names.taken]);
    });

    await test.step("importing adds them as the project's own reports and leaves the existing one alone", async () => {
      const dialog = page.getByRole("dialog", { name: "Import reports from a file" });
      await dialog.getByRole("button", { name: "Import 3 items" }).click();
      await expect(dialog.getByRole("status")).toContainText("3 items imported.");
      expect(await ownNames(request, target.headers, target.project.id, "layouts")).toEqual([names.layout, names.taken, `${names.taken} (copy)`].sort());
      expect(await ownNames(request, target.headers, target.project.id, "packs")).toEqual([names.pack]);
      await expect(dialog.getByRole("button", { name: "Cancel" })).toHaveCount(0);
      await dialog.getByRole("button", { name: "OK", exact: true }).click();
      await expect(page.getByText("Discard unsaved changes?")).toHaveCount(0);
      await expect(dialog).toHaveCount(0);
      const grid = await searchReportSetup(page, suffix);
      await expect(grid.getByRole("button", { name: new RegExp(`^${names.layout}`) })).toBeVisible();
    });

    await test.step("the source is untouched", async () => {
      expect(await ownNames(request, source.headers, source.project.id, "layouts")).toEqual([names.layout, names.taken].sort());
    });
  });

  test("a single layout is exported from its row menu and a file that is not a report file is refused", async ({ page, request }) => {
    const { source, names, suffix } = await setup(request);
    await loginAs(page, source.email, PASSWORD);
    await page.goto(`/projects/${source.project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    const grid = await searchReportSetup(page, suffix);
    await grid.getByRole("button", { name: `Actions for ${names.layout}` }).click();
    await page.getByRole("menuitem", { name: "Export as file…" }).click();
    const dialog = page.getByRole("dialog", { name: "Export 1 report as a file" });
    const [download] = await Promise.all([page.waitForEvent("download"), dialog.getByRole("button", { name: "Export" }).click()]);
    expect(download.suggestedFilename()).toContain("Handover");

    const bogus = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "report-file-")), "not-a-report.zip");
    fs.writeFileSync(bogus, "this is not a zip");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "Import from file…" }).click();
    const importer = page.getByRole("dialog", { name: "Import reports from a file" });
    await importer.getByLabel("Report file").setInputFiles(bogus);
    await importer.getByRole("button", { name: "Preview" }).click();
    await expect(importer.getByText(/not a report file/i)).toBeVisible();
    expect(await ownNames(request, source.headers, source.project.id, "layouts")).toEqual([names.layout, names.taken].sort());
  });

  test("closing an import before it is applied asks to discard the chosen file", async ({ page, request }) => {
    const { source } = await setup(request);
    const chosen = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "report-file-")), "reports.zip");
    fs.writeFileSync(chosen, "any file the person has picked");
    await loginAs(page, source.email, PASSWORD);
    await page.goto(`/projects/${source.project.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "Import from file…" }).click();
    const dialog = page.getByRole("dialog", { name: "Import reports from a file" });
    await dialog.getByLabel("Report file").focus(); // a person reaches the field first; the guard measures from that moment
    await dialog.getByLabel("Report file").setInputFiles(chosen);
    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(page.getByText("Discard unsaved changes?")).toBeVisible();
    await page.getByRole("button", { name: "Keep editing" }).click();
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Close" }).click();
    await page.getByRole("button", { name: "Discard changes" }).click();
    await expect(dialog).toHaveCount(0);
  });
});
