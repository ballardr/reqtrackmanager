import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, searchReportSetup, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: arrange every report a project offers (layouts, tables, packs and the reports modules provide) from one
 * folder list in Report setup: see what each row is at a glance, make, rename and delete folders, and move a report into
 * one, without a separate screen for packs or for module reports.
 *
 * Each test works in its own disposable organisation (created and deleted through the API) with uniquely named reports,
 * so it passes alone, in any order and repeated.
 */
test.describe("Report setup list", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation and project with Decision Management on, a document layout, a table layout and a pack. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-setup-list-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Setup List ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Setup Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const enabled = await request.put(`${API}/orgs/${org.id}/modules/decisions`, { headers, data: { enabled: true } });
    expect(enabled.ok(), await enabled.text()).toBeTruthy();
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Setup ${suffix}`, summary: "" } })).json();
    const base = `${API}/projects/${project.id}`;
    const names = { doc: `Doc ${suffix}`, table: `Rows ${suffix}`, pack: `Pack ${suffix}` };
    for (const [family, name] of [["document", names.doc], ["table", names.table]] as const) {
      const parsed = await (await request.post(`${base}/report-layouts/text/parse`, { headers, data: { text: `@layout ${family}\n` } })).json();
      const created = await request.post(`${base}/report-layouts`, { headers, data: { name, description: "", family, tree: parsed.tree } });
      expect(created.ok(), await created.text()).toBeTruthy();
    }
    const pack = await request.post(`${base}/report-packs`, {
      headers, data: { name: names.pack, description: "", definition: { schema_version: 1, entries: [{ kind: "layout", name: names.doc, format: "html" }] } },
    });
    expect(pack.ok(), await pack.text()).toBeTruthy();
    return { headers, project, base, names, packId: (await pack.json()).id as string, suffix };
  }

  async function openSetup(page: Page, projectId: string) {
    await page.goto(`/projects/${projectId}/admin`);
    await selectProjectAdminGroup(page, "Reports");
  }

  test("layouts, tables, packs and module reports are rows of one list, each with its type icon", async ({ page, request }) => {
    const { project, names, suffix } = await setup(page, request);
    await openSetup(page, project.id);

    await test.step("the three custom reports show their type, and there is no Kind column", async () => {
      const grid = await searchReportSetup(page, suffix);
      await expect(grid.getByRole("row", { name: new RegExp(names.doc) }).getByRole("img", { name: "Report" })).toBeVisible();
      await expect(grid.getByRole("row", { name: new RegExp(names.table) }).getByRole("img", { name: "Sheet" })).toBeVisible();
      await expect(grid.getByRole("row", { name: new RegExp(names.pack) }).getByRole("img", { name: "Pack" })).toBeVisible();
      await expect(grid.getByRole("columnheader", { name: "Kind" })).toHaveCount(0);
    });

    await test.step("a module report is in the same list; the removed sections are gone", async () => {
      const grid = await searchReportSetup(page, "Decision register");
      await expect(grid.getByRole("button", { name: /^Decision register/ })).toBeVisible();
      await expect(page.getByRole("button", { name: /Report folders section/ })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /Report packs section/ })).toHaveCount(0);
    });

    await test.step("the type filter narrows to packs", async () => {
      await page.getByRole("textbox", { name: "Search reports" }).fill(suffix);
      await page.getByLabel("Type").first().selectOption("Packs");
      const grid = page.getByRole("treegrid", { name: "Reports, packs and tables" });
      await expect(grid.getByRole("button", { name: new RegExp(`^${names.pack}`) })).toBeVisible();
      await expect(grid.getByRole("button", { name: new RegExp(`^${names.doc}`) })).toHaveCount(0);
    });
  });

  test("a folder is made, renamed and deleted from the list, and a pack moved into it follows", async ({ page, request }) => {
    const { headers, project, base, names, packId } = await setup(page, request);
    const folderOf = async () => {
      const packs = await (await request.get(`${base}/report-packs`, { headers })).json();
      return packs.find((p: { id: string }) => p.id === packId).folder as string;
    };
    await openSetup(page, project.id);
    const grid = page.getByRole("treegrid", { name: "Reports, packs and tables" });

    await test.step("New → New folder adds an empty folder", async () => {
      await page.getByRole("button", { name: "New", exact: true }).click();
      await page.getByRole("menuitem", { name: "New folder" }).click();
      await page.getByRole("dialog", { name: "New folder" }).getByRole("textbox").fill("Audit");
      await page.getByRole("dialog", { name: "New folder" }).getByRole("button", { name: "Add" }).click();
      await expect(page.getByText("Folder Audit added.")).toBeVisible();
      await grid.getByRole("button", { name: "Expand Audit" }).click();
      await expect(grid.getByText("Empty folder")).toBeVisible();
    });

    await test.step("the folder's own menu renames it", async () => {
      await grid.getByRole("button", { name: "Actions for the folder Audit" }).click();
      await page.getByRole("menuitem", { name: "Rename" }).click();
      const dialog = page.getByRole("dialog", { name: "Rename" });
      await dialog.getByRole("textbox").fill("Audits");
      await dialog.getByRole("button", { name: "Save name" }).click();
      await expect(page.getByText(/Renamed to Audits/)).toBeVisible();
      await expect(grid.getByRole("button", { name: "Expand Audits" })).toBeVisible();
    });

    await test.step("moving the pack edits the pack's own folder", async () => {
      const found = await searchReportSetup(page, names.pack);
      await found.getByRole("button", { name: `Actions for ${names.pack}` }).click();
      await page.getByRole("menuitem", { name: "Move to folder…" }).click();
      const dialog = page.getByRole("dialog", { name: `Move ${names.pack}` });
      await dialog.getByRole("radio", { name: "Audits" }).click();
      await dialog.getByRole("button", { name: "Move" }).click();
      await expect(page.getByText("Report moved.")).toBeVisible();
      expect(await folderOf()).toBe("Audits");
    });

    await test.step("deleting the folder asks first and moves the pack up, deleting no report", async () => {
      await page.getByRole("textbox", { name: "Search reports" }).fill("");
      await grid.getByRole("button", { name: "Actions for the folder Audits" }).click();
      await page.getByRole("menuitem", { name: "Delete" }).click();
      const confirm = page.getByRole("dialog", { name: "Delete the folder Audits?" });
      await expect(confirm.getByText(/No report is deleted/)).toBeVisible();
      await confirm.getByRole("button", { name: "Delete", exact: true }).click();
      await expect(page.getByText(/Folder Audits deleted/)).toBeVisible();
      expect(await folderOf()).toBe("");
      await searchReportSetup(page, names.pack);
      await expect(grid.getByRole("button", { name: new RegExp(`^${names.pack}`) })).toBeVisible();
    });
  });

  test("the column chooser keeps Version, Type and Folder off until chosen and remembers the choice", async ({ page, request }) => {
    const { project, names, suffix } = await setup(page, request);
    await openSetup(page, project.id);
    const grid = page.getByRole("treegrid", { name: "Reports, packs and tables" });

    await test.step("by default only the in-list, shared-from and last-changed columns show", async () => {
      await searchReportSetup(page, suffix);
      await expect(grid.getByRole("columnheader", { name: "Last changed" })).toBeVisible();
      for (const name of ["Version", "Type", "Folder"]) await expect(grid.getByRole("columnheader", { name })).toHaveCount(0);
    });

    await test.step("ticking Type and Folder shows them, and Name cannot be hidden", async () => {
      await page.getByRole("button", { name: "Choose columns" }).click();
      const chooser = page.getByRole("dialog", { name: "Columns" });
      await expect(chooser.getByRole("checkbox", { name: "Name" })).toBeDisabled();
      await chooser.getByRole("checkbox", { name: "Type" }).check();
      await chooser.getByRole("checkbox", { name: "Folder" }).check();
      await expect(grid.getByRole("columnheader", { name: /Type/ })).toBeVisible();
      await expect(grid.getByRole("row", { name: new RegExp(names.table) })).toContainText("Sheet");
      await page.keyboard.press("Escape");
    });

    await test.step("the choice survives a reload, and the reset brings the defaults back", async () => {
      await page.reload();
      await selectProjectAdminGroup(page, "Reports");
      await expect(grid.getByRole("columnheader", { name: /Type/ })).toBeVisible();
      await page.getByRole("button", { name: "Choose columns" }).click();
      await page.getByRole("dialog", { name: "Columns" }).getByRole("button", { name: "Show the default columns" }).click();
      await expect(grid.getByRole("columnheader", { name: "Type" })).toHaveCount(0);
      await page.keyboard.press("Escape");
    });
  });

  for (const width of [360, 768, 1280]) {
    test(`at ${width}px nothing in the list is out of reach and the page does not scroll sideways`, async ({ page, request }) => {
      const { project, names, suffix } = await setup(page, request);
      await page.setViewportSize({ width, height: 900 });
      await openSetup(page, project.id);
      const grid = await searchReportSetup(page, suffix);
      const row = grid.getByRole("row", { name: new RegExp(names.pack) });
      await expect(row).toBeVisible();

      await test.step("the page itself has no sideways scroll", async () => {
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(overflow).toBeLessThanOrEqual(0);
      });

      await test.step("the row's actions can be reached and opened", async () => {
        const actions = row.getByRole("button", { name: `Actions for ${names.pack}` });
        await actions.scrollIntoViewIfNeeded();
        await expect(actions).toBeInViewport();
        await actions.click();
        await expect(page.getByRole("menuitem", { name: "Move to folder…" })).toBeVisible();
        await page.keyboard.press("Escape");
      });
    });
  }
});
