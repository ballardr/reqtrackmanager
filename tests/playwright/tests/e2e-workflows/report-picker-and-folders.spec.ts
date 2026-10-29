import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";
import { chooseReport, listReports, openReportPicker, reportPickerButton } from "./reportPicker";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: find a report quickly in a long list and arrange the list for a team: the Reports picker files
 * reports in nested folders with search, a type filter and favourites; an organisation moves or hides the module
 * reports and shared layouts upstream of its projects and a project overrides that; the layouts list searches and
 * filters; the designer's widget list is a collapsed tree.
 *
 * Each test works in its own disposable organisation (created and deleted through the API) with uniquely named
 * reports, so it passes alone, in any order and repeated.
 */
test.describe("Report picker, folders and placements", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with Decision Management on and two projects; the page is left logged in as its admin. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-picker-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Picker ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Picker Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const enabled = await request.put(`${API}/orgs/${org.id}/modules/decisions`, { headers, data: { enabled: true } });
    expect(enabled.ok(), await enabled.text()).toBeTruthy();
    const projects: { id: string; name: string }[] = [];
    for (const label of ["Alpha", "Beta"]) {
      const created = await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `${label} ${suffix}`, summary: "" } });
      expect(created.ok(), await created.text()).toBeTruthy();
      projects.push(await created.json());
    }
    return { org, headers, projects, suffix };
  }

  /** Creates a layout of a family at a scope, with a folder, through the API (the server writes the empty tree). */
  async function createLayout(
    request: APIRequestContext, headers: Record<string, string>, base: string, name: string, family: "document" | "table", folder = "",
  ) {
    const parsed = await (await request.post(`${base}/report-layouts/text/parse`, { headers, data: { text: `@layout ${family}\n` } })).json();
    const created = await request.post(`${base}/report-layouts`, { headers, data: { name, description: "", folder, family, tree: parsed.tree } });
    expect(created.ok(), await created.text()).toBeTruthy();
    return created.json();
  }

  test("the picker files reports in nested folders, searches, filters by kind and keeps favourites", async ({ page, request }) => {
    const { org, headers, projects, suffix } = await setup(page, request);
    const orgBase = `${API}/orgs/${org.id}`;
    const doc = `Handover doc ${suffix}`;
    const sheet = `Handover rows ${suffix}`;
    const pack = `Handover pack ${suffix}`;
    await createLayout(request, headers, orgBase, doc, "document", "Handover/Quarterly");
    await createLayout(request, headers, orgBase, sheet, "table", "Handover/Quarterly");
    const made = await request.post(`${orgBase}/report-packs`, {
      headers, data: { name: pack, description: "", folder: "Handover", definition: { schema_version: 1, entries: [] } },
    });
    expect(made.ok(), await made.text()).toBeTruthy();
    await page.goto(`/projects/${projects[0].id}?reports=choose`);

    await test.step("the button names the current report and its folder", async () => {
      await expect(reportPickerButton(page)).toHaveAttribute("aria-label", "Report: Requirements report");
      await expect(reportPickerButton(page)).toContainText("Platform");
    });

    await test.step("folders nest and every one starts collapsed the first time", async () => {
      const dialog = await openReportPicker(page);
      await expect(dialog.getByRole("button", { name: "Expand Platform" })).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Expand Handover" })).toBeVisible();
      await dialog.getByRole("button", { name: "Expand Handover" }).click();
      await expect(dialog.getByRole("button", { name: new RegExp(`^${pack}`) })).toBeVisible();
      await dialog.getByRole("button", { name: "Expand Quarterly" }).click();
      await expect(dialog.getByRole("button", { name: new RegExp(`^${doc}`) })).toBeVisible();
      await page.keyboard.press("Escape");
    });

    await test.step("the folders left open are open again after closing the dialog and after a reload", async () => {
      for (const reload of [false, true]) {
        if (reload) await page.reload();
        const dialog = await openReportPicker(page);
        await expect(dialog.getByRole("button", { name: "Collapse Handover" })).toBeVisible();
        await expect(dialog.getByRole("button", { name: "Collapse Quarterly" })).toBeVisible();
        await expect(dialog.getByRole("button", { name: "Expand Platform" })).toBeVisible();
        await page.keyboard.press("Escape");
      }
    });

    await test.step("search opens the matching folders and the type filter narrows to sheets or packs", async () => {
      const dialog = await openReportPicker(page);
      await dialog.getByRole("textbox", { name: "Search reports" }).fill(suffix);
      await expect(dialog.getByRole("button", { name: new RegExp(`^${doc}`) })).toBeVisible();
      await dialog.getByLabel("Show").selectOption("Sheets");
      await expect(dialog.getByRole("button", { name: new RegExp(`^${sheet}`) })).toBeVisible();
      await expect(dialog.getByRole("button", { name: new RegExp(`^${doc}`) })).toHaveCount(0);
      await dialog.getByLabel("Show").selectOption("Packs");
      await expect(dialog.getByRole("button", { name: new RegExp(`^${pack}`) })).toBeVisible();
      await expect(dialog.getByRole("button", { name: new RegExp(`^${sheet}`) })).toHaveCount(0);
      await page.keyboard.press("Escape");
    });

    await test.step("a favourite is listed first and survives a reload", async () => {
      const dialog = await openReportPicker(page);
      await dialog.getByRole("textbox", { name: "Search reports" }).fill(doc);
      await dialog.getByRole("button", { name: `Add ${doc} to favourites` }).click();
      await page.keyboard.press("Escape");
      await page.reload();
      const reopened = await openReportPicker(page);
      await reopened.getByRole("button", { name: "Expand Favourites" }).click();
      await expect(reopened.getByRole("button", { name: "Collapse Favourites" })).toBeVisible();
      await expect(reopened.getByRole("button", { name: new RegExp(`^${doc}`) }).first()).toBeVisible();
      await page.keyboard.press("Escape");
    });

    await test.step("choosing a report closes the dialog and puts it in the link", async () => {
      await chooseReport(page, doc);
      await expect(page).toHaveURL(/report=custom-handover-doc/);
      expect(await listReports(page)).toContain(sheet);
    });
  });

  test("an organisation moves and hides upstream reports and a project overrides that", async ({ page, request }) => {
    const { org, projects } = await setup(page, request);
    const [alpha, beta] = projects;

    await test.step("the organisation moves one module report to a nested folder and hides another", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Templates & reports");
      await ensureExpanded(page, "Report folders");
      const table = page.getByRole("table", { name: "Reports and where they are filed" });
      await table.getByRole("button", { name: "Actions for Decision register" }).click();
      await page.getByRole("menuitem", { name: "Move to folder…" }).click();
      const dialog = page.getByRole("dialog", { name: "Move Decision register" });
      await dialog.getByRole("radio", { name: "Top level" }).click();
      await dialog.getByRole("button", { name: "New folder", exact: true }).click();
      await dialog.getByRole("textbox", { name: "Name of the new folder" }).fill("Governance");
      await dialog.getByRole("button", { name: "Add", exact: true }).click();
      await dialog.getByRole("button", { name: "New folder inside" }).click();
      await dialog.getByRole("textbox", { name: "Name of the new folder inside Governance" }).fill("Decisions");
      await dialog.getByRole("button", { name: "Add", exact: true }).click();
      await expect(dialog.getByRole("radio", { name: "Decisions" })).toBeChecked();
      await dialog.getByRole("button", { name: "Move" }).click();
      await expect(page.getByText("Report moved.")).toBeVisible();
      await expect(table.getByText("Governance/Decisions")).toBeVisible();
      await expect(table.getByText("Default: Decision Management")).toBeVisible();

      await table.getByRole("button", { name: "Actions for Approval ageing" }).click();
      await page.getByRole("menuitem", { name: "Hide from the list" }).click();
      await expect(page.getByText(/anyone with access can still run it/)).toBeVisible();
      await page.getByRole("dialog").getByRole("button", { name: "Hide from the list" }).click();
      await expect(page.getByText("Report hidden from the list.")).toBeVisible();
    });

    await test.step("every project follows it: the report is in the new folder and the hidden one is gone", async () => {
      await page.goto(`/projects/${alpha.id}?reports=choose`);
      const dialog = await openReportPicker(page);
      await dialog.getByRole("button", { name: "Expand Governance" }).click();
      await dialog.getByRole("button", { name: "Expand Decisions" }).click();
      await expect(dialog.getByRole("button", { name: /^Decision register/ })).toBeVisible();
      await page.keyboard.press("Escape");
      expect(await listReports(page)).not.toContain("Approval ageing");
    });

    await test.step("a project shows what the organisation hid, and names who hid it", async () => {
      await page.goto(`/projects/${alpha.id}/admin`);
      await selectProjectAdminGroup(page, "Report Setup");
      await ensureExpanded(page, "Report folders");
      const table = page.getByRole("table", { name: "Reports and where they are filed" });
      await expect(table.getByText("Hidden (the organisation)")).toBeVisible();
      await expect(table.getByText(/Default: Decision Management · the organisation/)).toBeVisible();
      await table.getByRole("button", { name: "Actions for Approval ageing" }).click();
      await page.getByRole("menuitem", { name: "Show in the list" }).click();
      await expect(page.getByText("Report shown in the list.")).toBeVisible();
      await page.goto(`/projects/${alpha.id}?reports=choose`);
      expect(await listReports(page)).toContain("Approval ageing");
    });

    await test.step("another project still follows the organisation", async () => {
      await page.goto(`/projects/${beta.id}?reports=choose`);
      expect(await listReports(page)).not.toContain("Approval ageing");
    });

    await test.step("a project can go back to following the organisation", async () => {
      await page.goto(`/projects/${alpha.id}/admin`);
      await selectProjectAdminGroup(page, "Report Setup");
      await ensureExpanded(page, "Report folders");
      const table = page.getByRole("table", { name: "Reports and where they are filed" });
      await table.getByRole("button", { name: "Actions for Approval ageing" }).click();
      await page.getByRole("menuitem", { name: "Follow the default again" }).click();
      await expect(page.getByText("Back to following the default.")).toBeVisible();
      await page.goto(`/projects/${alpha.id}?reports=choose`);
      expect(await listReports(page)).not.toContain("Approval ageing");
    });
  });

  test("a folder is chosen, added, renamed and deleted from the layout form without losing a report", async ({ page, request }) => {
    const { headers, projects, suffix } = await setup(page, request);
    const [alpha] = projects;
    const base = `${API}/projects/${alpha.id}`;
    const name = `Foldered layout ${suffix}`;
    const layout = await createLayout(request, headers, base, name, "document", "Handover/Quarterly");
    const folderOf = async () => {
      const rows = await (await request.get(`${base}/report-layouts`, { headers })).json();
      return rows.find((row: { id: string }) => row.id === layout.id).folder as string;
    };

    const openForm = async () => {
      await page.goto(`/projects/${alpha.id}/admin`);
      await selectProjectAdminGroup(page, "Report Setup");
      await page.getByRole("table", { name: "Report layouts" }).getByRole("button", { name: `Actions for ${name}` }).click();
      await page.getByRole("menuitem", { name: "Edit details" }).click();
      return page.getByRole("dialog", { name: "Layout details" });
    };

    await test.step("the form shows the layout's folder chosen in a tree and offers no free text", async () => {
      const dialog = await openForm();
      await expect(dialog.getByRole("radio", { name: "Quarterly" })).toBeChecked();
      await expect(dialog.getByRole("combobox", { name: "Folder" })).toHaveCount(0);
    });

    await test.step("a new folder is added inside the chosen one and the layout is saved into it", async () => {
      const dialog = page.getByRole("dialog", { name: "Layout details" });
      await dialog.getByRole("button", { name: "New folder inside" }).click();
      await dialog.getByRole("textbox", { name: "Name of the new folder inside Handover/Quarterly" }).fill("Archive");
      await dialog.getByRole("button", { name: "Add", exact: true }).click();
      await expect(page.getByText("Folder Handover/Quarterly/Archive added.")).toBeVisible();
      await expect(dialog.getByRole("radio", { name: "Archive" })).toBeChecked();
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Layout details saved.")).toBeVisible();
      expect(await folderOf()).toBe("Handover/Quarterly/Archive");
    });

    await test.step("renaming a folder moves the layout with it", async () => {
      const dialog = await openForm();
      await dialog.getByRole("radio", { name: "Handover" }).click();
      await dialog.getByRole("button", { name: "Rename", exact: true }).click();
      await dialog.getByRole("textbox", { name: "New name for Handover" }).fill("Delivery");
      await dialog.getByRole("button", { name: "Save name" }).click();
      await expect(page.getByText(/Renamed to Delivery\. 1 filed item followed\./)).toBeVisible();
      await expect(dialog.getByRole("radio", { name: "Delivery" })).toBeChecked();
      expect(await folderOf()).toBe("Delivery/Quarterly/Archive");
    });

    await test.step("deleting a folder asks first, then moves the layout up a level and deletes no report", async () => {
      const dialog = page.getByRole("dialog", { name: "Layout details" });
      await dialog.getByRole("radio", { name: "Quarterly" }).click();
      await dialog.getByRole("button", { name: "Delete", exact: true }).click();
      const confirm = page.getByRole("dialog", { name: "Delete the folder Delivery/Quarterly?" });
      await expect(confirm.getByText(/No report is deleted/)).toBeVisible();
      await confirm.getByRole("button", { name: "Delete", exact: true }).click();
      await expect(page.getByText(/Folder Delivery\/Quarterly deleted\. 1 filed item moved up\./)).toBeVisible();
      await expect(dialog.getByRole("radio", { name: "Delivery" })).toBeChecked();
      await dialog.getByRole("button", { name: "Cancel" }).click();
      expect(await folderOf()).toBe("Delivery/Archive");
    });
  });

  test("the layouts list searches and filters, and the designer's widget list is a collapsed tree", async ({ page, request }) => {
    const { headers, projects, suffix } = await setup(page, request);
    const [alpha] = projects;
    const base = `${API}/projects/${alpha.id}`;
    const filed = `Filed layout ${suffix}`;
    const rows = `Rows sheet ${suffix}`;
    const plain = `Plain layout ${suffix}`;
    const created = await createLayout(request, headers, base, filed, "document", "Handover/Quarterly");
    await createLayout(request, headers, base, rows, "table", "Handover");
    await createLayout(request, headers, base, plain, "document");

    await test.step("search matches the name or the folder and the filters narrow further", async () => {
      await page.goto(`/projects/${alpha.id}/admin`);
      await selectProjectAdminGroup(page, "Report Setup");
      const table = page.getByRole("table", { name: "Report layouts" });
      await expect(table.getByRole("link", { name: filed })).toBeVisible();
      await expect(table.getByText("Handover/Quarterly")).toBeVisible();
      const search = page.getByRole("textbox", { name: "Search this list" }).first();
      await search.fill("quarterly");
      await expect(table.getByRole("link", { name: filed })).toBeVisible();
      await expect(table.getByRole("link", { name: plain })).toHaveCount(0);
      await search.fill("");
      await page.getByLabel("Kind").first().selectOption("Table");
      await expect(table.getByRole("link", { name: rows })).toBeVisible();
      await expect(table.getByRole("link", { name: filed })).toHaveCount(0);
      await page.getByLabel("Kind").first().selectOption("Any");
      await page.getByLabel("Folder").first().selectOption("Handover");
      await expect(table.getByRole("link", { name: filed })).toBeVisible(); // a folder filter keeps what is inside it
      await expect(table.getByRole("link", { name: rows })).toBeVisible();
      await expect(table.getByRole("link", { name: plain })).toHaveCount(0);
      await search.fill("zzzz-nothing");
      await expect(page.getByText("Nothing matches these filters.")).toBeVisible();
    });

    await test.step("the widget list starts collapsed and says each module once", async () => {
      await page.goto(`/projects/${alpha.id}/report-layouts/${created.id}`);
      await page.getByRole("tab", { name: "Widgets" }).click();
      await expect(page.getByRole("button", { name: "Expand Decision Management" })).toHaveAttribute("aria-expanded", "false");
      await expect(page.getByRole("button", { name: "Decision register" })).toHaveCount(0);
      await page.getByRole("button", { name: "Expand Decision Management" }).click();
      await expect(page.getByRole("button", { name: "Expand Decision register" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Expand Approval ageing" })).toBeVisible();
      await expect(page.getByText(/Decision Management ·/)).toHaveCount(0);
      await page.getByRole("button", { name: "Expand Decision register" }).click();
      await expect(page.getByRole("button", { name: "Decision register" })).toBeVisible();
    });
  });
});
