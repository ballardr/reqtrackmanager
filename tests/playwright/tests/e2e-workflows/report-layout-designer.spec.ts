import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: design a report layout as text, see its problems and a preview of it on the real records, save
 * it as versions, and share organisation layouts with projects that can hide them.
 *
 * Each test works in its own disposable organisation (created and deleted through the API) with uniquely named
 * layouts and records, so it passes alone, in any order and repeated.
 */
test.describe("Report layout designer", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with an admin and a project holding two requirements; the page is left logged in as the admin. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-layout-designer-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Layout Designer ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Layout Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Designer project ${suffix}`, summary: "" } })).json();
    const component = await (await request.post(`${API}/projects/${project.id}/components`, { headers, data: { name: "Hardware", prefix: "HW" } })).json();
    const category = await (await request.post(`${API}/projects/${project.id}/categories`, {
      headers, data: { name: "Functional", prefix: "FN", component_id: component.id },
    })).json();
    const requirements = [`Brake pads ${suffix}`, `Handbrake ${suffix}`];
    for (const name of requirements) {
      const created = await request.post(`${API}/projects/${project.id}/requirements`, {
        headers, data: { name, component_id: component.id, category_id: category.id },
      });
      expect(created.ok(), await created.text()).toBeTruthy();
    }
    return { org, headers, project, requirements, suffix };
  }

  /** Creates a layout from Project Admin's Report setup and lands in its designer. */
  async function createFromProjectAdmin(page: Page, projectId: string, name: string) {
    await page.goto(`/projects/${projectId}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");
    await page.getByRole("button", { name: "New layout" }).click();
    const dialog = page.getByRole("dialog", { name: "New report layout" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();
  }

  test("a layout is written as text, previewed on the real records and saved as versions", async ({ page, request }) => {
    const { project, requirements, suffix } = await setup(page, request);
    const name = `E2E designed layout ${suffix}`;
    await createFromProjectAdmin(page, project.id, name);
    const editor = page.getByRole("textbox", { name: "Layout text" });

    await test.step("a new layout starts empty and valid", async () => {
      await expect(page.getByText("Version 1")).toBeVisible();
      await expect(page.getByText("The text is valid.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save new version" })).toBeDisabled();
    });

    await test.step("a block shortcut writes the starting text and the checker accepts the result", async () => {
      await page.getByRole("button", { name: "Insert block: For each record" }).click();
      await expect(editor).toHaveValue(/@each requirement sort title as req/);
      await expect(page.getByText("Unsaved changes")).toBeVisible();
    });

    await test.step("the preview shows this project's requirements and nothing is stored", async () => {
      await page.getByRole("button", { name: "Run preview" }).click();
      const frame = page.frameLocator('iframe[title="Report preview"]');
      for (const requirement of requirements) await expect(frame.getByText(requirement)).toBeVisible();
      await expect(page.getByRole("status").filter({ hasText: "records read" })).toBeVisible();
    });

    await test.step("saving makes version 2 and the note is kept in the history", async () => {
      await page.getByRole("textbox", { name: "Note on this change" }).fill("Listed the requirements");
      await page.getByRole("button", { name: "Save new version" }).click();
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await expect(page.getByText("Unsaved changes")).toHaveCount(0);
      await page.getByRole("tab", { name: "History" }).click();
      const history = page.getByRole("table", { name: "Versions" });
      await expect(history.getByRole("row", { name: /Version 2 \(current\).*Listed the requirements/ })).toBeVisible();
      await expect(history.getByRole("row", { name: /Version 1/ })).toBeVisible();
      await expect(page.getByLabel("Changes between the two versions")).toContainText("+ @each requirement sort title as req");
    });

    await test.step("a reload shows the saved text", async () => {
      await page.reload();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@each requirement sort title as req/);
    });
  });

  test("a layout is built in the block outline, previewed, saved and read back as text", async ({ page, request }) => {
    const { project, requirements, suffix } = await setup(page, request);
    await createFromProjectAdmin(page, project.id, `E2E outline layout ${suffix}`);

    await test.step("the outline starts empty", async () => {
      await page.getByRole("tab", { name: "Outline" }).click();
      await expect(page.getByRole("region", { name: "Layout outline" })).toBeVisible();
      await expect(page.getByText("This layout has no blocks yet. Add one to start.")).toBeVisible();
    });

    await test.step("a For each block takes its records from a type and names each record", async () => {
      await page.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "For each record" }).click();
      const each = page.getByRole("listitem", { name: "For each record block 1" });
      await each.getByRole("combobox", { name: "Record type" }).selectOption({ label: "Requirement" });
      await each.getByRole("textbox", { name: "Name" }).fill("req");
    });

    await test.step("a heading inside it shows each requirement's title", async () => {
      await page.getByRole("button", { name: "Add to Contents: For each record 1" }).click();
      await page.getByRole("menuitem", { name: "Heading" }).click();
      const heading = page.getByRole("listitem", { name: "Heading block 1" });
      await heading.getByRole("textbox", { name: "Heading" }).fill("{{req.title}}");
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("the preview lists this project's requirements", async () => {
      await page.getByRole("button", { name: "Run preview" }).click();
      const frame = page.frameLocator('iframe[title="Report preview"]');
      for (const requirement of requirements) await expect(frame.getByText(requirement)).toBeVisible();
    });

    await test.step("a block with a problem says so and holds back saving", async () => {
      const heading = page.getByRole("listitem", { name: "Heading block 1" });
      await heading.getByRole("textbox", { name: "Heading" }).fill("");
      await expect(heading.getByText("Must not be empty.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save new version" })).toBeDisabled();
      await heading.getByRole("textbox", { name: "Heading" }).fill("{{req.title}}");
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("saving makes version 2, and the text view reads the same layout", async () => {
      await page.getByRole("button", { name: "Save new version" }).click();
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@each requirement[\s\S]*as req[\s\S]*@heading[\s\S]*\{\{req\.title\}\}/);
    });

    await test.step("a reload and the outline show the saved blocks", async () => {
      await page.reload();
      await page.getByRole("tab", { name: "Outline" }).click();
      await expect(page.getByRole("listitem", { name: "For each record block 1" })).toBeVisible();
      await expect(page.getByRole("textbox", { name: "Heading" })).toHaveValue("{{req.title}}");
    });
  });

  test("a layout is written in the document view with formatting and links, previewed, saved and read back in the other views", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await createFromProjectAdmin(page, project.id, `E2E document layout ${suffix}`);
    await page.getByRole("tab", { name: "Document" }).click();
    const region = page.getByRole("region", { name: "Layout document" });

    await test.step("a heading and a text block are added and typed in place", async () => {
      await region.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "Heading" }).click();
      await region.locator(".rich-heading").click({ clickCount: 3 });
      await page.keyboard.type("Spec review");
      await region.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "Text", exact: true }).click();
      await region.locator(".rich-prose p").click({ clickCount: 3 });
      await page.keyboard.type("Read the spec **now** please");
      await expect(region.locator(".rich-prose strong")).toHaveText("now");
    });

    await test.step("selected words become a web link and a link to the heading through the dialog", async () => {
      await region.locator(".rich-prose p").click();
      await page.keyboard.press("Home");
      for (let i = 0; i < 9; i += 1) await page.keyboard.press("ArrowRight");
      for (let i = 0; i < 4; i += 1) await page.keyboard.press("Shift+ArrowRight");
      await region.getByRole("button", { name: "Link", exact: true }).click();
      let dialog = page.getByRole("dialog", { name: "Link" });
      await dialog.getByRole("textbox", { name: /Web address/ }).fill("javascript:alert(1)");
      await expect(dialog.getByRole("alert")).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Apply" })).toBeDisabled();
      await dialog.getByRole("textbox", { name: /Web address/ }).fill("https://example.org/spec");
      await dialog.getByRole("button", { name: "Apply" }).click();
      await expect(region.locator(".rich-prose a[href='https://example.org/spec']")).toHaveText("spec");

      await region.locator(".rich-prose p").click();
      await page.keyboard.press("End");
      for (let i = 0; i < 6; i += 1) await page.keyboard.press("Shift+ArrowLeft");
      await region.getByRole("button", { name: "Link", exact: true }).click();
      dialog = page.getByRole("dialog", { name: "Link" });
      await dialog.getByRole("combobox", { name: /Link to/ }).selectOption("section");
      await dialog.getByRole("combobox", { name: /^Section/ }).selectOption({ label: "Spec review" });
      await dialog.getByRole("button", { name: "Apply" }).click();
      await expect(region.locator(".rich-prose a[href='#spec-review']")).toHaveText("please");
    });

    await test.step("the preview draws the styles, the links and the heading's anchor", async () => {
      await page.getByRole("button", { name: "Run preview" }).click();
      const frame = page.frameLocator('iframe[title="Report preview"]');
      await expect(frame.locator("h3#spec-review")).toHaveText("Spec review");
      await expect(frame.locator("strong", { hasText: "now" })).toBeVisible();
      await expect(frame.locator("a[href='https://example.org/spec']")).toHaveText("spec");
      await expect(frame.locator("a[href='#spec-review']")).toHaveText("please");
    });

    await test.step("saving makes version 2 and the other views read the same layout", async () => {
      await page.getByRole("button", { name: "Save new version" }).click();
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.getByRole("tab", { name: "Text" }).click();
      const text = page.getByRole("textbox", { name: "Layout text" });
      await expect(text).toHaveValue(/@heading[\s\S]*Spec review/);
      await expect(text).toHaveValue(/Read the \[spec\]\(https:\/\/example\.org\/spec\) \*\*now\*\* \[please\]\(#spec-review\)/);
      await page.getByRole("tab", { name: "Outline" }).click();
      await expect(page.getByRole("listitem", { name: "Text block 2" })).toBeVisible();
    });

    await test.step("a reload and the document view show the saved links", async () => {
      await page.reload();
      await page.getByRole("tab", { name: "Document" }).click();
      await expect(page.getByRole("region", { name: "Layout document" }).locator("a[href='https://example.org/spec']")).toHaveText("spec");
    });
  });

  test("an equation is inserted, drawn in the preview, and a command that is not allowed is refused", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await createFromProjectAdmin(page, project.id, `E2E equation layout ${suffix}`);
    const editor = page.getByRole("textbox", { name: "Layout text" });
    const frame = page.frameLocator('iframe[title="Report preview"]');

    await test.step("the Equation shortcut writes an equation block the checker accepts", async () => {
      await page.getByRole("button", { name: "Insert block: Equation" }).click();
      await expect(editor).toHaveValue(/@equation \\frac\{a\}\{b\} = c/);
      await expect(page.getByText("The text is valid.")).toBeVisible();
    });

    await test.step("the preview draws the block and an equation written inside a text line", async () => {
      await editor.fill(
        "@layout document\n\n@equation \\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}\n\nThe load \\(F = m a\\) is the force.\n",
      );
      await expect(page.getByText("The text is valid.")).toBeVisible();
      await page.getByRole("button", { name: "Run preview" }).click();
      await expect(frame.locator("figure.equation svg")).toBeVisible();
      await expect(frame.locator("span.math svg")).toBeVisible();
      await expect(frame.getByText("The load")).toBeVisible();
    });

    await test.step("a command outside the allowed list is a problem on its line and blocks saving", async () => {
      await editor.fill("@layout document\n\n@equation \\href{http://example.com}{x}\n");
      await expect(page.getByRole("button", { name: /^Line 3: .*\\href is not supported/ })).toBeVisible();
      await expect(page.getByRole("button", { name: "Save new version" })).toBeDisabled();
    });
  });

  test("a mistake is listed by line, blocks saving and previewing, and a click goes to it", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await createFromProjectAdmin(page, project.id, `E2E broken layout ${suffix}`);
    const editor = page.getByRole("textbox", { name: "Layout text" });

    await editor.fill("@layout document\n\n@heading Fine\n\n@bogus nothing\n");

    const problem = page.getByRole("button", { name: /^Line 5, column 1:/ });
    await expect(problem).toBeVisible();
    await expect(page.getByText("1 problem to fix")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save new version" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Run preview" })).toBeDisabled();
    await problem.click();
    await expect(editor).toBeFocused();

    await editor.fill("@layout document\n\n@heading Fine\n");
    await expect(page.getByText("The text is valid.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save new version" })).toBeEnabled();
  });

  test("leaving with unsaved changes asks first", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await createFromProjectAdmin(page, project.id, `E2E unsaved layout ${suffix}`);
    await page.getByRole("textbox", { name: "Layout text" }).fill("@layout document\n\n@heading Draft\n");

    await page.getByRole("button", { name: "Report layouts" }).click();
    const dialog = page.getByRole("dialog", { name: "Leave without saving?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/Draft/);

    await page.getByRole("button", { name: "Report layouts" }).click();
    await page.getByRole("dialog", { name: "Leave without saving?" }).getByRole("button", { name: "Leave" }).click();
    await expect(page).toHaveURL(/\/admin\/reportSetup$/);
  });

  test("a project hides an organisation layout, brings it back and copies it to change it", async ({ page, request }) => {
    const { org, headers, project, suffix } = await setup(page, request);
    const name = `E2E organisation layout ${suffix}`;
    const created = await request.post(`${API}/orgs/${org.id}/report-layouts`, {
      headers, data: {
        name, description: "Shared", family: "document",
        tree: { schema_version: 1, family: "document", orientation: "portrait", nodes: [{ type: "heading", text: "Shared heading" }] },
      },
    });
    expect(created.ok(), await created.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Report Setup");
    const table = page.getByRole("table", { name: "Report layouts" });

    await test.step("the shared layout is listed, with where it comes from, and opens read-only", async () => {
      await expect(table.getByRole("row", { name: new RegExp(`${name}.*The organisation`) })).toBeVisible();
      await table.getByRole("link", { name: new RegExp(name) }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveAttribute("readonly", "");
      await expect(page.getByRole("note")).toContainText("read-only here");
      await expect(page.getByRole("button", { name: "Save new version" })).toHaveCount(0);
      await page.getByRole("button", { name: "Report layouts" }).click();
    });

    await test.step("hiding it removes it from this project's list and it can be added back", async () => {
      await page.getByRole("button", { name: `Actions for ${name}` }).click();
      await page.getByRole("menuitem", { name: "Hide in this project" }).click();
      await page.getByRole("dialog", { name: /Hide .* in this project\?/ }).getByRole("button", { name: "Hide" }).click();
      await expect(page.getByText("Layout hidden in this project.")).toBeVisible();
      await expect(page.getByRole("link", { name: new RegExp(name) })).toHaveCount(0);
      await page.getByRole("button", { name: "Add organisation defaults (1)" }).click();
      await page.getByRole("dialog", { name: "Add organisation defaults" }).getByRole("button", { name: "Add 1 default" }).click();
      await expect(page.getByRole("link", { name: new RegExp(name) })).toBeVisible();
    });

    await test.step("a copy is the project's own layout and can be edited", async () => {
      await page.getByRole("button", { name: `Actions for ${name}` }).click();
      await page.getByRole("menuitem", { name: "Make a copy" }).click();
      await expect(page.getByRole("heading", { name: `${name} (copy)` })).toBeVisible();
      await expect(page.getByRole("textbox", { name: "Layout text" })).not.toHaveAttribute("readonly", "");
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/Shared heading/);
    });
  });

  test("an organisation layout is designed from Org Admin and previewed across the organisation's projects", async ({ page, request }) => {
    const { org, requirements, suffix } = await setup(page, request);
    const name = `E2E org designed ${suffix}`;

    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Templates & reports");
    await ensureExpanded(page, "Report layouts");
    await page.getByRole("button", { name: "New layout" }).click();
    const dialog = page.getByRole("dialog", { name: "New report layout" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("combobox", { name: "Kind of report" }).selectOption("table");
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();

    await test.step("text declaring the other kind is refused before anything runs", async () => {
      await page.getByRole("textbox", { name: "Layout text" }).fill("@layout document\n");
      await expect(page.getByRole("button", { name: /^Line 1: This is a table layout/ })).toBeVisible();
      await expect(page.getByRole("button", { name: "Run preview" })).toBeDisabled();
    });

    await page.getByRole("textbox", { name: "Layout text" }).fill(
      '@layout table\n\n@sheet "Requirements" requirement sort title\n  @column code\n  @column title\n@end\n',
    );
    await expect(page.getByText("The text is valid.")).toBeVisible();
    await page.getByRole("button", { name: "Run preview" }).click();
    const sheet = page.getByRole("region", { name: "Requirements" });
    for (const requirement of requirements) await expect(sheet.getByRole("cell", { name: requirement })).toBeVisible();
    await expect(sheet.getByRole("columnheader", { name: "Project" })).toBeVisible();

    await page.getByRole("button", { name: "Save new version" }).click();
    await expect(page.getByText("Saved as version 2.")).toBeVisible();
  });

  test("deleting a layout needs its name typed", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    const name = `E2E doomed layout ${suffix}`;
    await createFromProjectAdmin(page, project.id, name);
    await page.getByRole("button", { name: "Report layouts" }).click();

    await page.getByRole("button", { name: `Actions for ${name}` }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    const dialog = page.getByRole("dialog", { name: `Delete ${name}?` });
    await expect(dialog.getByRole("button", { name: "Delete" })).toBeDisabled();
    await dialog.getByRole("textbox").fill(name);
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect(page.getByText("Layout deleted.")).toBeVisible();
    await expect(page.getByRole("link", { name: new RegExp(name) })).toHaveCount(0);
  });
});
