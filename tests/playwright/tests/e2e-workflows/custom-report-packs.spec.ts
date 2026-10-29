import crypto from "node:crypto";
import fs from "node:fs";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { chooseReport } from "./reportPicker";
import { deleteOrgOnCleanup, installCleanupHook, loginAs, openSetupReport, PASSWORD, selectProjectAdminGroup, saveNewVersion } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: hand an external team several reports at once, for the categories they care about, as one zip,
 * and see what the zip will contain before downloading it.
 *
 * Each test works in its own disposable organisation (created and deleted through the API) with uniquely named
 * layouts, packs and records, so it passes alone, in any order and repeated.
 */
test.describe("Custom report packs", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation and project with a requirement in each of three categories; the page is left logged in as the admin. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-report-packs-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Report Packs ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Packs Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Packs project ${suffix}`, summary: "" } })).json();
    const component = await (await request.post(`${API}/projects/${project.id}/components`, { headers, data: { name: "Hardware", prefix: "HW" } })).json();
    for (const category of ["Security", "Usability", "Billing"]) {
      const created = await (await request.post(`${API}/projects/${project.id}/categories`, {
        headers, data: { name: category, prefix: category.slice(0, 3).toUpperCase(), component_id: component.id },
      })).json();
      const resp = await request.post(`${API}/projects/${project.id}/requirements`, {
        headers, data: { name: `${category} requirement ${suffix}`, component_id: component.id, category_id: created.id },
      });
      expect(resp.ok(), await resp.text()).toBeTruthy();
    }
    return { org, headers, project, suffix };
  }

  /** A document layout of the requirements in the chosen categories (all of them when `filtered` is false). */
  const layoutText = (filtered: boolean) =>
    filtered
      ? '@layout document\n@var categories enum list label "Categories" from requirement.category\n\n@heading Chosen\n\n@table requirement where category in $categories\n  @column title "Name"\n@end\n'
      : '@layout document\n\n@heading Everything\n\n@table requirement\n  @column title "Name"\n@end\n';

  async function createLayout(request: APIRequestContext, headers: Record<string, string>, base: string, name: string, body: string) {
    const parsed = await (await request.post(`${base}/report-layouts/text/parse`, { headers, data: { text: body } })).json();
    expect(parsed.ok, JSON.stringify(parsed)).toBeTruthy();
    const resp = await request.post(`${base}/report-layouts`, { headers, data: { name, description: "E2E", family: "document", tree: parsed.tree } });
    expect(resp.ok(), await resp.text()).toBeTruthy();
    return resp.json();
  }

  const categoriesVariable = { name: "categories", type: "enum", multiple: true, label: "Categories", source: { record_type: "requirement", field: "category" } };

  async function createPack(request: APIRequestContext, headers: Record<string, string>, base: string, name: string, entries: unknown[]) {
    const resp = await request.post(`${base}/report-packs`, {
      headers, data: { name, description: "E2E pack", definition: { schema_version: 1, variables: [categoriesVariable], entries } },
    });
    expect(resp.ok(), await resp.text()).toBeTruthy();
    return resp.json();
  }

  async function choosePack(page: Page, name: string) {
    await chooseReport(page, name);
  }

  async function choose(page: Page, ...categories: string[]) {
    await page.getByRole("button", { name: /Categories/ }).first().click();
    for (const category of categories) await page.getByRole("checkbox", { name: category }).click();
    await page.keyboard.press("Escape");
  }

  test("a pack shows what each report includes for the chosen categories and downloads as one zip", async ({ page, request }) => {
    const { headers, project, suffix } = await setup(page, request);
    const base = `${API}/projects/${project.id}`;
    const chosen = `E2E Chosen ${suffix}`;
    const everything = `E2E Everything ${suffix}`;
    await createLayout(request, headers, base, chosen, layoutText(true));
    await createLayout(request, headers, base, everything, layoutText(false));
    const packName = `E2E Handover ${suffix}`;
    await createPack(request, headers, base, packName, [
      { kind: "layout", name: chosen, format: "docx", filename: "chosen" },
      { kind: "layout", name: everything, format: "html" },
      { kind: "layout", name: `No such layout ${suffix}`, format: "pdf" },
    ]);

    await page.goto(`/projects/${project.id}?reports=choose`);
    await choosePack(page, packName);

    await test.step("the pack waits for the categories it needs", async () => {
      await expect(page.getByText("Choose a value for Categories to run this report.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Download zip" })).toBeDisabled();
    });

    await test.step("the counts follow the choice and the missing report is listed with its reason", async () => {
      await choose(page, "Security");
      const table = page.getByRole("table", { name: "What the zip will contain" });
      await expect(table.getByRole("row", { name: new RegExp(`${chosen}.*Included.*1`) })).toBeVisible();
      await expect(table.getByRole("row", { name: new RegExp(`${everything}.*Included.*3`) })).toBeVisible();
      await expect(table.getByRole("row", { name: /No such layout.*Not available/ })).toBeVisible();
      await expect(page.getByText(/1 report is not available/)).toBeVisible();
      await choose(page, "Billing");
      await expect(table.getByRole("row", { name: new RegExp(`${chosen}.*Included.*2`) })).toBeVisible();
    });

    await test.step("the download is one zip holding the manifest and the numbered files", async () => {
      const pending = page.waitForEvent("download");
      await page.getByRole("button", { name: "Download zip" }).click();
      const download = await pending;
      expect(download.suggestedFilename()).toMatch(/\.zip$/);
      const names = fs.readFileSync((await download.path())!).toString("latin1");
      expect(names).toContain("manifest.json");
      expect(names).toContain("01-chosen.docx");
      expect(names).toContain(`02-${everything}.html`);
      expect(names).not.toContain("03-");
    });
  });

  test("a saved set fills the form, and a project overrides an organisation pack's set for itself", async ({ page, request }) => {
    const { org, headers, project, suffix } = await setup(page, request);
    const orgBase = `${API}/orgs/${org.id}`;
    const chosen = `E2E Org chosen ${suffix}`;
    await createLayout(request, headers, orgBase, chosen, layoutText(true));
    const packName = `E2E Org pack ${suffix}`;
    const pack = await createPack(request, headers, orgBase, packName, [{ kind: "layout", name: chosen, format: "html" }]);
    const set = await (await request.post(`${orgBase}/report-packs/${pack.id}/sets`, {
      headers, data: { name: "Team Alpha", values: { categories: ["Security"] } },
    })).json();

    await test.step("the project's Report setup lists the shared pack and its set", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Report Setup");
      await openSetupReport(page, packName);
      await expect(page.getByRole("heading", { name: packName })).toBeVisible();
      await expect(page.getByText(/is read-only here/)).toBeVisible();
      await page.getByRole("tab", { name: "Saved sets" }).click();
      await expect(page.getByRole("region", { name: "Team Alpha" })).toBeVisible();
    });

    await test.step("the project overrides the categories and the shared value stays visible beside its own", async () => {
      await page.getByRole("button", { name: "Actions for Team Alpha" }).click();
      await page.getByRole("menuitem", { name: "Override for this project" }).click();
      const dialog = page.getByRole("dialog", { name: /Override Team Alpha/ });
      await dialog.getByRole("button", { name: /Categories/ }).click();
      await page.getByRole("checkbox", { name: "Security" }).click(); // off
      await page.getByRole("checkbox", { name: "Billing" }).click(); // on
      await page.keyboard.press("Escape");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Override saved.")).toBeVisible();
      const card = page.getByRole("region", { name: "Team Alpha" });
      await expect(card.getByText("Overridden here")).toBeVisible();
      await expect(card.getByRole("columnheader", { name: "Shared value" })).toBeVisible();
    });

    await test.step("running from the set uses the project's values; the organisation's set is unchanged", async () => {
      await page.goto(`/projects/${project.id}?reports=choose`);
      await choosePack(page, packName);
      await page.getByLabel("Saved choices").selectOption("Team Alpha");
      const table = page.getByRole("table", { name: "What the zip will contain" });
      await expect(table.getByRole("row", { name: new RegExp(`${chosen}.*Included.*1`) })).toBeVisible();
      const shared = await (await request.get(`${orgBase}/report-packs/${pack.id}/sets`, { headers })).json();
      expect(shared.find((s: { id: string }) => s.id === set.id).base).toEqual({ categories: ["Security"] });
    });

    await test.step("resetting the override brings the shared values back", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Report Setup");
      await openSetupReport(page, packName);
      await page.getByRole("tab", { name: "Saved sets" }).click();
      await page.getByRole("button", { name: "Actions for Team Alpha" }).click();
      await page.getByRole("menuitem", { name: "Reset to the shared values" }).click();
      await expect(page.getByText("Override removed.")).toBeVisible();
      await expect(page.getByText("Overridden here")).toHaveCount(0);
    });
  });

  test("an administrator builds a pack in Report setup: reports, a variable, a saved set", async ({ page, request }) => {
    const { headers, project, suffix } = await setup(page, request);
    const layout = `E2E Built ${suffix}`;
    await createLayout(request, headers, `${API}/projects/${project.id}`, layout, layoutText(true));
    const packName = `E2E Built pack ${suffix}`;

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");

    await test.step("a new pack opens its editor", async () => {
      await page.getByRole("button", { name: "New", exact: true }).click();
      await page.getByRole("menuitem", { name: "New pack" }).click();
      await page.getByRole("dialog", { name: "New report pack" }).getByRole("textbox", { name: /^Name/ }).fill(packName);
      await page.getByRole("dialog", { name: "New report pack" }).getByRole("button", { name: "Create" }).click();
      await expect(page.getByRole("heading", { name: packName })).toBeVisible();
      await expect(page.getByText("No reports in this pack yet.")).toBeVisible();
    });

    await test.step("adding a layout and a variable and saving makes version 2", async () => {
      await page.getByRole("button", { name: "Add a layout" }).click();
      const entry = page.getByRole("region", { name: "Report 1" });
      await entry.getByRole("combobox", { name: /^Layout/ }).selectOption(layout);
      await entry.getByRole("combobox", { name: /^Format/ }).selectOption("html");
      await page.getByRole("tab", { name: "Variables" }).click();
      await page.getByRole("button", { name: "Add a variable" }).click();
      const variable = page.getByRole("region", { name: "Variable 1" });
      await variable.getByRole("textbox", { name: /^Name/ }).fill("categories");
      await variable.getByRole("textbox", { name: "Label" }).fill("Categories");
      await variable.getByRole("combobox", { name: /^Type/ }).selectOption("enum");
      await variable.getByRole("switch", { name: "Takes several values" }).click();
      await variable.getByRole("combobox", { name: /^Take options from/ }).selectOption("requirement");
      await variable.getByRole("combobox", { name: "Field" }).selectOption("category");
      await saveNewVersion(page, "First reports");
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await expect(page.getByText("Unsaved changes")).toHaveCount(0);
    });

    await test.step("a saved set is created from the variable's own options", async () => {
      await page.getByRole("tab", { name: "Saved sets" }).click();
      await page.getByRole("button", { name: "New saved set" }).click();
      const dialog = page.getByRole("dialog", { name: "New saved set" });
      await dialog.getByRole("textbox", { name: /^Name/ }).fill("Security team");
      await dialog.getByRole("button", { name: /Categories/ }).click();
      await page.getByRole("checkbox", { name: "Security" }).click();
      await page.keyboard.press("Escape");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Saved set saved.")).toBeVisible();
      await expect(page.getByRole("region", { name: "Security team" })).toBeVisible();
    });

    await test.step("the Reports page offers the pack with the saved choice", async () => {
      await page.goto(`/projects/${project.id}?reports=choose`);
      await choosePack(page, packName);
      await page.getByLabel("Saved choices").selectOption("Security team");
      await expect(page.getByRole("table", { name: "What the zip will contain" }).getByRole("row", { name: new RegExp(`${layout}.*Included.*1`) })).toBeVisible();
    });
  });
});
