import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: keep a block that took effort (a house-style heading, a risk table) as a snippet, insert it into another
 * layout, share it from the organisation, and tidy the saved ones (rename, hide, restore, delete).
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Saved report snippets", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with an admin and a project; the page is left logged in as the admin. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-saved-snippets-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Saved Snippets ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Saved Snippets Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Saved snippets project ${suffix}`, summary: "" } })).json();
    return { org, headers, project, suffix };
  }

  /** Creates a layout from Project Admin's Report setup and lands in its designer. */
  async function newLayout(page: Page, projectId: string, name: string) {
    await page.goto(`/projects/${projectId}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
    const dialog = page.getByRole("dialog", { name: "New report layout" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();
  }

  /** Saves the heading-and-text blocks of a draft as an organisation snippet through the API. */
  async function orgSnippet(request: APIRequestContext, headers: Record<string, string>, orgId: string, name: string) {
    const tree = { schema_version: 1, family: "document", nodes: [{ type: "heading", text: "Shared heading", level: 1 }, { type: "text", text: "Shared body" }] };
    const resp = await request.post(`${API}/orgs/${orgId}/report-snippets`, {
      headers, data: { name, description: "Shared by the organisation.", category: "House style", tree, selection: { container: "nodes", start: 0, count: 2 } },
    });
    expect(resp.status()).toBe(201);
    return (await resp.json()) as { id: string };
  }

  const saveDialog = (page: Page) => page.getByRole("dialog", { name: "Save as snippet" });
  const picker = (page: Page) => page.getByRole("dialog", { name: "Insert snippet" });
  const snippetsTable = (page: Page) => page.getByRole("table", { name: "Saved snippets" });

  test("a block saved from the Blocks view is offered in another layout and inserted from there", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    const snippetName = `House heading ${suffix}`;
    await newLayout(page, project.id, `E2E saved source ${suffix}`);
    await page.getByRole("tab", { name: "Blocks" }).click();

    await test.step("Save as snippet needs a selected block", async () => {
      await page.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "Heading 1" }).click();
      await page.getByLabel("Block details").getByRole("textbox", { name: "Heading", exact: true }).fill("House style heading");
      await expect(page.getByRole("button", { name: "Save as snippet" })).toBeEnabled();
    });

    await test.step("the dialog saves it for the project", async () => {
      await page.getByRole("button", { name: "Save as snippet" }).click();
      const dialog = saveDialog(page);
      await expect(dialog.getByText("Saves 1 block.")).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Save snippet" })).toBeDisabled();
      await dialog.getByRole("textbox", { name: "Name" }).fill(snippetName);
      await dialog.getByRole("textbox", { name: "Description" }).fill("Our heading");
      await dialog.getByRole("combobox", { name: "Category" }).fill("House style");
      await dialog.getByRole("button", { name: "Save snippet" }).click();
      await expect(page.getByText(`Saved the snippet ${snippetName}.`)).toBeVisible();
      await expect(dialog).toBeHidden();
    });

    await test.step("another layout's Insert snippet lists it, says where it comes from and inserts it", async () => {
      await newLayout(page, project.id, `E2E saved target ${suffix}`);
      await page.getByRole("tab", { name: "Blocks" }).click();
      await page.getByRole("button", { name: "Insert snippet" }).click();
      const dialog = picker(page);
      const row = dialog.getByRole("button", { name: `Select ${snippetName}` });
      await expect(row).toContainText("Saved · This project");
      await row.click();
      await expect(dialog.getByRole("list", { name: `Blocks in ${snippetName}` })).toContainText("House style heading");
      await dialog.getByRole("button", { name: "Insert", exact: true }).click();
      await expect(page.getByRole("status", { name: "Snippet inserted" })).toContainText(`Inserted ${snippetName}`);
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@heading level=1 House style heading|@heading House style heading/);
    });

    await test.step("Report setup lists it with its source", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Report Setup");
      const row = snippetsTable(page).getByRole("row", { name: new RegExp(snippetName) });
      await expect(row).toContainText("This project");
      await expect(row).toContainText("House style");
    });
  });

  test("the Text view saves the blocks the caret is in, and says when there is none", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await newLayout(page, project.id, `E2E saved text ${suffix}`);
    const editor = page.getByRole("textbox", { name: "Layout text" });
    await editor.fill("@layout document\n\n@heading First block\n\n@heading Second block\n");
    await expect(page.getByText("The text is valid.")).toBeVisible();

    await test.step("a caret on the layout line is in no block", async () => {
      await editor.evaluate((el: HTMLTextAreaElement) => { el.focus(); el.setSelectionRange(2, 2); });
      await page.getByRole("button", { name: "Save as snippet" }).click();
      await expect(page.getByText("Put the caret in a block, or select blocks, to save them as a snippet.")).toBeVisible();
      await expect(saveDialog(page)).toHaveCount(0);
    });

    await test.step("a selection across both blocks saves both", async () => {
      await editor.evaluate((el: HTMLTextAreaElement) => { el.focus(); el.setSelectionRange(el.value.indexOf("First"), el.value.length - 2); });
      await page.getByRole("button", { name: "Save as snippet" }).click();
      const dialog = saveDialog(page);
      await expect(dialog.getByText("Saving 2 blocks (and everything inside them).")).toBeVisible();
      await expect(dialog.getByText("Saves 2 blocks.")).toBeVisible();
      await dialog.getByRole("textbox", { name: "Name" }).fill(`Two headings ${suffix}`);
      await dialog.getByRole("button", { name: "Save snippet" }).click();
      await expect(page.getByText(`Saved the snippet Two headings ${suffix}.`)).toBeVisible();
    });
  });

  test("an organisation snippet reaches the project, which can hide it and restore it, and a taken name is refused", async ({ page, request }) => {
    const { org, headers, project, suffix } = await setup(page, request);
    const name = `Org default ${suffix}`;
    await orgSnippet(request, headers, org.id, name);

    await test.step("the project's list shows it as the organisation's, read-only", async () => {
      await page.goto(`/projects/${project.id}/admin`);
      await selectProjectAdminGroup(page, "Report Setup");
      const row = snippetsTable(page).getByRole("row", { name: new RegExp(name) });
      await expect(row).toContainText("The organisation");
      await page.getByRole("button", { name: `Actions for ${name}` }).click();
      await expect(page.getByRole("menuitem", { name: "Edit details" })).toHaveCount(0);
      await expect(page.getByRole("menuitem", { name: "Delete" })).toHaveCount(0);
    });

    await test.step("hiding it asks first and removes it from Insert snippet in this project", async () => {
      await page.getByRole("menuitem", { name: "Hide in this project" }).click();
      const confirm = page.getByRole("dialog");
      await expect(confirm).toContainText("no longer offered when inserting a snippet in this project");
      await confirm.getByRole("button", { name: "Hide", exact: true }).click();
      await expect(page.getByText("Snippet hidden in this project.")).toBeVisible();
      await expect(snippetsTable(page).getByRole("row", { name: new RegExp(name) })).toContainText("Hidden here");
      const offered = await (await request.get(`${API}/projects/${project.id}/report-layouts/snippets`, { headers })).json();
      expect((offered as { name: string }[]).map((s) => s.name)).not.toContain(name);
    });

    await test.step("Add organisation defaults brings it back", async () => {
      await page.getByRole("button", { name: /Add organisation defaults/ }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toContainText(name);
      await dialog.getByRole("button", { name: /Add|Restore|Show/ }).last().click();
      await expect(page.getByText("Hidden snippets shown again.")).toBeVisible();
      await expect(snippetsTable(page).getByRole("row", { name: new RegExp(name) })).not.toContainText("Hidden here");
      const offered = await (await request.get(`${API}/projects/${project.id}/report-layouts/snippets`, { headers })).json();
      expect((offered as { name: string }[]).map((s) => s.name)).toContain(name);
    });

    await test.step("a copy of it is the project's own and a taken name is refused when saving", async () => {
      await page.getByRole("button", { name: `Actions for ${name}` }).click();
      await page.getByRole("menuitem", { name: "Make a copy" }).click();
      await expect(page.getByText(`Copied as ${name} (copy).`)).toBeVisible();
      const copy = snippetsTable(page).getByRole("row", { name: new RegExp(`${name} \\(copy\\)`) });
      await expect(copy).toContainText("This project");
      const taken = await request.post(`${API}/orgs/${org.id}/report-snippets`, {
        headers, data: { name: name.toUpperCase(), tree: { schema_version: 1, family: "document", nodes: [{ type: "page_break" }] }, selection: { start: 0 } },
      });
      expect(taken.status()).toBe(409);
    });
  });

  test("an own snippet is renamed in place and deleted only after its name is typed", async ({ page, request }) => {
    const { headers, project, suffix } = await setup(page, request);
    const name = `Own snippet ${suffix}`;
    const created = await request.post(`${API}/projects/${project.id}/report-snippets`, {
      headers, data: { name, tree: { schema_version: 1, family: "document", nodes: [{ type: "heading", text: "Mine" }] }, selection: { start: 0 } },
    });
    expect(created.status()).toBe(201);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");

    await test.step("Edit details renames it", async () => {
      await page.getByRole("button", { name: `Actions for ${name}` }).click();
      await page.getByRole("menuitem", { name: "Edit details" }).click();
      const dialog = page.getByRole("dialog", { name: `Edit ${name}` });
      await dialog.getByRole("textbox", { name: "Name" }).fill(`Renamed ${suffix}`);
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByText("Snippet details saved.")).toBeVisible();
      await expect(snippetsTable(page).getByRole("row", { name: new RegExp(`Renamed ${suffix}`) })).toBeVisible();
    });

    await test.step("Delete needs the name typed", async () => {
      await page.getByRole("button", { name: `Actions for Renamed ${suffix}` }).click();
      await page.getByRole("menuitem", { name: "Delete" }).click();
      const confirm = page.getByRole("dialog");
      await expect(confirm.getByRole("button", { name: "Delete", exact: true })).toBeDisabled();
      await confirm.getByRole("textbox").fill(`Renamed ${suffix}`);
      await confirm.getByRole("button", { name: "Delete", exact: true }).click();
      await expect(page.getByText("Snippet deleted.")).toBeVisible();
      await expect(snippetsTable(page).getByRole("row", { name: new RegExp(`Renamed ${suffix}`) })).toHaveCount(0);
    });
  });

  test("a person without the layout-management right sees no snippets and cannot save one", async ({ page, request }) => {
    const { org, headers, project, suffix } = await setup(page, request);
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const email = `e2e-saved-snippets-member-${suffix}@example.com`;
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email, display_name: "E2E Member", password: PASSWORD, role: "member" },
    });
    const member = await login(request, email, PASSWORD);

    expect((await request.get(`${API}/orgs/${org.id}/report-snippets`, { headers: member })).status()).toBe(403);
    expect((await request.get(`${API}/projects/${project.id}/report-snippets`, { headers: member })).status()).toBe(403);
    const refused = await request.post(`${API}/projects/${project.id}/report-snippets`, {
      headers: member, data: { name: "Nope", tree: { schema_version: 1, family: "document", nodes: [{ type: "page_break" }] }, selection: { start: 0 } },
    });
    expect(refused.status()).toBe(403);
    expect((await request.get(`${API}/orgs/${org.id}/report-snippets`, { headers })).status()).toBe(200);
  });
});
