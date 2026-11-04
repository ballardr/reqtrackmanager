import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, searchReportSetup, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a project administrator has set up reports in one project and wants the same in another project of the
 * organisation, without rebuilding them: tick them in Report setup, choose the project, see what will happen (a name that
 * is taken is renamed, never replaced), and copy.
 *
 * Each test works in its own disposable organisation (created and deleted through the API) with uniquely named reports,
 * so it passes alone, in any order and repeated.
 */
test.describe("Copy reports between projects", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with a source project holding two layouts and a pack, and an empty target project. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-report-copy-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Report Copy ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Copy Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = async (name: string) =>
      (await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name, summary: "" } })).json()) as { id: string; name: string };
    const source = await project(`Source ${suffix}`);
    const target = await project(`Target ${suffix}`);
    const names = { first: `Handover ${suffix}`, second: `Status ${suffix}`, pack: `Board pack ${suffix}` };
    const layout = async (projectId: string, name: string) => {
      const base = `${API}/projects/${projectId}`;
      const parsed = await (await request.post(`${base}/report-layouts/text/parse`, { headers, data: { text: "@layout document\n" } })).json();
      const created = await request.post(`${base}/report-layouts`, { headers, data: { name, description: "", family: "document", tree: parsed.tree } });
      expect(created.ok(), await created.text()).toBeTruthy();
    };
    await layout(source.id, names.first);
    await layout(source.id, names.second);
    await layout(target.id, names.second); // the target already uses this name
    const pack = await request.post(`${API}/projects/${source.id}/report-packs`, {
      headers, data: { name: names.pack, description: "", definition: { schema_version: 1, entries: [{ kind: "layout", name: names.first, format: "html" }] } },
    });
    expect(pack.ok(), await pack.text()).toBeTruthy();
    return { headers, source, target, names, suffix };
  }

  async function ownLayoutNames(request: APIRequestContext, headers: Record<string, string>, projectId: string) {
    const rows = (await (await request.get(`${API}/projects/${projectId}/report-layouts`, { headers })).json()) as { name: string; origin: string }[];
    return rows.filter((r) => r.origin === "project").map((r) => r.name);
  }

  test("ticked reports are previewed, copied under a new name where the name is taken, and listed in the target", async ({ page, request }) => {
    const { headers, source, target, names, suffix } = await setup(page, request);
    await page.goto(`/projects/${source.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");

    await test.step("copy mode shows tick boxes and nothing can be copied until something is ticked", async () => {
      await page.getByRole("button", { name: "Copy to another project…" }).click();
      await expect(page.getByRole("button", { name: "Copy…", exact: true })).toBeDisabled();
    });

    await test.step("tick two layouts and the pack", async () => {
      const grid = await searchReportSetup(page, suffix);
      for (const name of [names.first, names.second, names.pack]) await grid.getByRole("checkbox", { name: `Select ${name}` }).check();
      await expect(page.getByText("3 selected")).toBeVisible();
      await page.getByRole("button", { name: "Copy…", exact: true }).click();
    });

    const dialog = page.getByRole("dialog", { name: "Copy 3 items to another project" });
    await test.step("preview names the outcome of each item and renames the taken name", async () => {
      await dialog.getByRole("combobox", { name: /Copy into/ }).selectOption({ label: target.name });
      await dialog.getByRole("button", { name: "Preview" }).click();
      await expect(dialog.getByText(`${names.second} → ${names.second} (copy)`)).toBeVisible();
      await expect(dialog.getByText(names.first, { exact: true })).toBeVisible();
      expect(await ownLayoutNames(request, headers, target.id)).toEqual([names.second]); // a preview writes nothing
    });

    await test.step("copying adds the reports to the target and links to its report setup", async () => {
      await dialog.getByRole("button", { name: "Copy 3 items" }).click();
      await expect(dialog.getByRole("status")).toContainText(`3 items copied to ${target.name}.`);
      expect((await ownLayoutNames(request, headers, target.id)).sort()).toEqual([names.first, names.second, `${names.second} (copy)`].sort());
      await dialog.getByRole("link", { name: `Open ${target.name}'s report setup` }).click();
      await expect(page).toHaveURL(new RegExp(`/projects/${target.id}/admin/reportSetup`));
      const grid = await searchReportSetup(page, suffix);
      await expect(grid.getByRole("button", { name: new RegExp(`^${names.first}`) })).toBeVisible();
    });

    await test.step("the originals are untouched", async () => {
      expect((await ownLayoutNames(request, headers, source.id)).sort()).toEqual([names.first, names.second].sort());
    });
  });

  test("a single report is copied from its row menu, and skipping a taken name leaves the target's own alone", async ({ page, request }) => {
    const { headers, source, target, names, suffix } = await setup(page, request);
    await page.goto(`/projects/${source.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    const grid = await searchReportSetup(page, suffix);
    await grid.getByRole("button", { name: `Actions for ${names.second}` }).click();
    await page.getByRole("menuitem", { name: "Copy to another project…" }).click();

    const dialog = page.getByRole("dialog", { name: "Copy 1 item to another project" });
    await dialog.getByRole("combobox", { name: /Copy into/ }).selectOption({ label: target.name });
    await dialog.getByLabel(/If the project already has one/).selectOption({ label: "Skip it" });
    await dialog.getByRole("button", { name: "Preview" }).click();
    await expect(dialog.getByText("Skip: name already used")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Copy 0 items" })).toBeDisabled();
    expect(await ownLayoutNames(request, headers, target.id)).toEqual([names.second]);
  });

  test("a person who manages no other project is told there is nowhere to copy to", async ({ page, request }) => {
    const { headers, source, target, names, suffix } = await setup(page, request);
    // Archived projects are not offered, leaving no target at all.
    expect((await request.post(`${API}/projects/${target.id}/archive`, { headers })).ok()).toBeTruthy();
    await page.goto(`/projects/${source.id}/admin`);
    await selectProjectAdminGroup(page, "Reports");
    const grid = await searchReportSetup(page, suffix);
    await grid.getByRole("button", { name: `Actions for ${names.first}` }).click();
    await page.getByRole("menuitem", { name: "Copy to another project…" }).click();
    const dialog = page.getByRole("dialog", { name: "Copy 1 item to another project" });
    await expect(dialog.getByText(/no other project in this organisation where you can manage reports/)).toBeVisible();
    await expect(dialog.getByRole("combobox", { name: /Copy into/ })).toBeDisabled();
  });
});
