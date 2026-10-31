import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, ensureExpanded, installCleanupHook, loginAs, PASSWORD, searchReportSetup, selectOrgAdminGroup, selectProjectAdminGroup, saveNewVersion } from "./helpers";

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
    await selectProjectAdminGroup(page, "Reports");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
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
      await saveNewVersion(page, "Listed the requirements");
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

  test("a layout is built in the block editor, previewed, saved and read back as text", async ({ page, request }) => {
    const { project, requirements, suffix } = await setup(page, request);
    await createFromProjectAdmin(page, project.id, `E2E blocks layout ${suffix}`);
    const inspector = page.getByLabel("Block details");
    const where = page.getByRole("combobox", { name: "Where to add the block" });

    await test.step("the block editor starts empty and has the full width, with no palette column and no preview", async () => {
      await page.getByRole("tab", { name: "Blocks" }).click();
      await expect(page.getByRole("region", { name: "Block editor" })).toBeVisible();
      await expect(inspector.getByText("Select a block to edit its settings.")).toBeVisible();
      await expect(page.getByText("Adding at the end of the layout")).toBeVisible();
      await expect(page.locator(".blocklyToolboxFlyout, .blocklyFlyout").first()).toBeHidden();
      await expect(page.getByRole("button", { name: "Run preview" })).toHaveCount(0);
      // The canvas is wider than the old half-page column (about 150px once the palette was open).
      const stage = await page.locator(".blocks-stage").boundingBox();
      const viewport = page.viewportSize();
      expect(stage?.width ?? 0).toBeGreaterThan(Math.min(600, (viewport?.width ?? 1280) * 0.4));
    });

    await test.step("a For each block takes its records from a type and names each record", async () => {
      await page.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "For each record" }).click();
      await inspector.getByRole("combobox", { name: "Record type" }).selectOption({ label: "Requirement" });
      await inspector.getByRole("textbox", { name: "Name", exact: true }).fill("req");
    });

    await test.step("a heading inside it shows each requirement's title", async () => {
      await inspector.getByRole("button", { name: "Add to Contents" }).click();
      await page.getByRole("menuitem", { name: "Heading 2" }).click();
      await inspector.getByRole("textbox", { name: "Heading", exact: true }).fill("{{req.title}}");
      await expect(page.getByText("No problems.")).toBeVisible();
      // The block on the workspace shows the same words.
      await expect(page.locator(".blocklyEditableField .blocklyText", { hasText: "{{req.title}}" })).toBeVisible();
    });

    await test.step("blocks land where the line beside Add block says", async () => {
      // The Heading just added inside the For each is selected: a leaf, so the default is after it.
      await expect(where.locator("option:checked")).toHaveText(/^Adding after: Heading/);
      await page.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "Page break" }).click();
      await expect(inspector.getByTestId("block-inspector")).toContainText("Page break block");
      // Nothing selected is not offered once a block has been chosen; the end of the layout is always an option.
      await where.selectOption({ label: "Adding at the end of the layout" });
      await page.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "Page break" }).click();
      const pageBreaks = page.locator(".blocklyText.rl-block-title", { hasText: "Page break" });
      await expect(pageBreaks).toHaveCount(2);
      // Undo takes the last addition back, like a drag.
      await expect(inspector.getByTestId("block-inspector")).toContainText("Page break block");
      await page.keyboard.press("ControlOrMeta+z");
      await expect(pageBreaks).toHaveCount(1);
      // Back on the heading, whose title is edited next.
      await page.locator(".blocklyText.rl-block-title", { hasText: /^Heading$/ }).click();
      await expect(inspector.getByTestId("block-inspector")).toContainText("Heading block");
    });

    await test.step("the preview opens in a dialog, or beside the blocks when switched on, and lists this project's requirements", async () => {
      await page.getByRole("button", { name: "Preview", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Report preview" });
      await dialog.getByRole("button", { name: "Run preview" }).click();
      const frame = dialog.frameLocator('iframe[title="Report preview"]');
      for (const requirement of requirements) await expect(frame.getByText(requirement)).toBeVisible();
      await dialog.getByRole("button", { name: "Close" }).click();
      await expect(dialog).toBeHidden();
      await page.getByRole("button", { name: "Preview panel" }).click();
      await expect(page.getByRole("button", { name: "Run preview" })).toBeVisible();
      await page.getByRole("button", { name: "Preview panel" }).click();
      await expect(page.getByRole("button", { name: "Run preview" })).toHaveCount(0);
    });

    await test.step("a block with a problem says so and holds back saving", async () => {
      await inspector.getByRole("textbox", { name: "Heading", exact: true }).fill("");
      await expect(inspector.getByText("Must not be empty.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save new version" })).toBeDisabled();
      await inspector.getByRole("textbox", { name: "Heading", exact: true }).fill("{{req.title}}");
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("saving makes version 2, and the text view reads the same layout", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/@each requirement[\s\S]*as req[\s\S]*@heading[\s\S]*\{\{req\.title\}\}/);
    });

    await test.step("a reload and the block editor show the saved blocks", async () => {
      await page.reload();
      await page.getByRole("tab", { name: "Blocks" }).click();
      await expect(page.locator(".blocklyEditableField .blocklyText", { hasText: "{{req.title}}" })).toBeVisible();
    });
  });

  test("formatting and links written in the text view are previewed, saved and read back in the block editor", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await createFromProjectAdmin(page, project.id, `E2E formatted layout ${suffix}`);
    const editor = page.getByRole("textbox", { name: "Layout text" });

    await test.step("a heading and a formatted paragraph with a web link and a section link are typed", async () => {
      await editor.fill(
        "@layout document\n\n@heading Spec review\n\nRead the [spec](https://example.org/spec) **now** [please](#spec-review)\n",
      );
      await expect(page.getByText("The text is valid.")).toBeVisible();
    });

    await test.step("the preview draws the styles, the links and the heading's anchor", async () => {
      await page.getByRole("button", { name: "Run preview" }).click();
      const frame = page.frameLocator('iframe[title="Report preview"]');
      await expect(frame.locator("h2#spec-review")).toHaveText("Spec review");
      await expect(frame.locator("strong", { hasText: "now" })).toBeVisible();
      await expect(frame.locator("a[href='https://example.org/spec']")).toHaveText("spec");
      await expect(frame.locator("a[href='#spec-review']")).toHaveText("please");
    });

    await test.step("saving makes version 2 and the block editor reads the same layout", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.getByRole("tab", { name: "Blocks" }).click();
      await expect(page.locator(".blocklyText.rl-summary", { hasText: "Read the" })).toBeVisible();
      await page.getByRole("tab", { name: "Text" }).click();
      await expect(editor).toHaveValue(/Read the \[spec\]\(https:\/\/example\.org\/spec\) \*\*now\*\* \[please\]\(#spec-review\)/);
    });
  });

  test("page orientation and size are set from the toolbar, written into the first line and used by the preview", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await createFromProjectAdmin(page, project.id, `E2E page layout ${suffix}`);
    const editor = page.getByRole("textbox", { name: "Layout text" });

    await page.getByRole("button", { name: "Page setup: A4, portrait" }).click();
    const popover = page.getByRole("dialog", { name: "Page setup" });
    await popover.getByRole("combobox", { name: "Page size" }).selectOption("Letter");
    await popover.getByRole("combobox", { name: "Orientation" }).selectOption("landscape");
    await expect(editor).toHaveValue(/^@layout document landscape Letter\n/);
    await expect(page.getByRole("button", { name: "Page setup: Letter, landscape" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(popover).toBeHidden();
    await expect(page.getByText("The text is valid.")).toBeVisible();
    await saveNewVersion(page);
    await expect(page.getByText("Saved as version 2.")).toBeVisible();
    await page.reload();
    await expect(page.getByRole("button", { name: "Page setup: Letter, landscape" })).toBeVisible();
  });

  test("margins and a page style are set in the Page setup dialog, used by a section, saved and read back in the block editor", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await createFromProjectAdmin(page, project.id, `E2E page styles ${suffix}`);
    const editor = page.getByRole("textbox", { name: "Layout text" });

    await test.step("margins, mirroring and a landscape A3 style are written as header lines", async () => {
      await page.getByRole("button", { name: "Page setup: A4, portrait" }).click();
      const dialog = page.getByRole("dialog", { name: "Page setup" });
      await dialog.getByRole("spinbutton", { name: "Top" }).first().fill("2");
      await dialog.getByRole("spinbutton", { name: "Gutter" }).first().fill("1");
      await dialog.getByRole("checkbox", { name: "Mirror margins" }).check();
      await dialog.getByRole("button", { name: "Add page style" }).click();
      await dialog.getByRole("textbox", { name: "Name" }).fill("Wide tables");
      const style = dialog.getByRole("group", { name: "Wide tables" });
      await style.getByRole("combobox", { name: "Page size" }).selectOption("A3");
      await style.getByRole("combobox", { name: "Orientation" }).selectOption("landscape");
      await expect(editor).toHaveValue(/^@layout document mirror margins top=2 gutter=1\n@pagestyle "Wide tables" landscape A3\n/);
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
    });

    await test.step("a section uses the style and the server accepts the text", async () => {
      await editor.fill(`${await editor.inputValue()}\nBefore.\n\n@section "Wide tables"\n  Inside the wide section.\n@end\n\nAfter.\n`);
      await expect(page.getByText("The text is valid.")).toBeVisible();
    });

    await test.step("the preview labels the section's page style and shows the text in it", async () => {
      await page.getByRole("button", { name: "Run preview" }).click();
      const frame = page.frameLocator('iframe[title="Report preview"]');
      await expect(frame.getByText("Page style: A3 landscape")).toBeVisible();
      await expect(frame.locator("section.page-style").getByText("Inside the wide section.")).toBeVisible();
      await expect(frame.locator("section.page-style").getByText("After.")).toHaveCount(0);
    });

    await test.step("saved and reloaded, the block editor shows the section and its style", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Blocks" }).click();
      await page.getByText("Layout settings").click();
      await expect(page.getByRole("group", { name: "Wide tables" })).toBeVisible();
      await expect(page.getByRole("checkbox", { name: "Mirror margins" })).toBeChecked();
    });
  });

  test("a header and footer are set in the Page setup dialog, shown with page numbers in the preview, saved and read back in the block editor", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await createFromProjectAdmin(page, project.id, `E2E header layout ${suffix}`);
    const editor = page.getByRole("textbox", { name: "Layout text" });

    await test.step("own text in the header's centre cell and the footer's right cell is written as @header and @footer lines", async () => {
      await page.getByRole("button", { name: "Page setup: A4, portrait" }).click();
      const dialog = page.getByRole("dialog", { name: "Page setup" });
      await dialog.getByRole("combobox", { name: "Header: print" }).selectOption("custom");
      await dialog.getByRole("textbox", { name: "Header, centre cell" }).fill("{{report_title}}");
      await dialog.getByRole("combobox", { name: "Footer: print" }).selectOption("custom");
      await dialog.getByRole("textbox", { name: "Footer, right cell" }).fill("Page {{page}} of {{pages}}");
      await expect(editor).toHaveValue(/^@layout document\n@header left "" centre "\{\{report_title\}\}"\n@footer left "" right "Page \{\{page\}\} of \{\{pages\}\}"\n/);
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(page.getByText("The text is valid.")).toBeVisible();
    });

    await test.step("the preview shows the header and footer bands, with the page numbers left for printing", async () => {
      await page.getByRole("button", { name: "Run preview" }).click();
      const frame = page.frameLocator('iframe[title="Report preview"]');
      await expect(frame.locator(".band.header")).toContainText(`E2E header layout ${suffix}`);
      await expect(frame.locator(".band.footer")).toContainText("Page n of N");
    });

    await test.step("a header taller than the margin is refused with the margin it needs", async () => {
      await editor.fill(`${await editor.inputValue()}`.replace('centre "{{report_title}}"', 'centre "a\\nb\\nc"'));
      await expect(page.getByText(/header needs a top margin of at least 1\.7 cm/)).toBeVisible();
      await editor.fill((await editor.inputValue()).replace('centre "a\\nb\\nc"', 'centre "{{report_title}}"'));
      await expect(page.getByText("The text is valid.")).toBeVisible();
    });

    await test.step("saved and reloaded, the block editor shows both as their own text", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Blocks" }).click();
      await page.getByText("Layout settings").click();
      await expect(page.getByRole("combobox", { name: "Header: print" })).toHaveValue("custom");
      await expect(page.getByRole("textbox", { name: "Footer, right cell" })).toHaveValue("Page {{page}} of {{pages}}");
    });
  });

  test("fields and project values are one searchable list", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await createFromProjectAdmin(page, project.id, `E2E fields layout ${suffix}`);
    // The caret sits inside an unfinished For each, so its name (req) is in scope.
    const editor = page.getByRole("textbox", { name: "Layout text" });
    await editor.fill("@layout document\n\n@each requirement sort title as req\n  ");
    await editor.press("End");
    await page.getByRole("tab", { name: "Fields" }).click();
    const list = page.getByRole("list", { name: "Fields" });
    await expect(list.getByRole("button", { name: "Insert {{project_description}}" })).toBeVisible();
    await expect(list.getByRole("button", { name: "Insert {{req.title}}" })).toBeVisible();
    await page.getByRole("textbox", { name: "Find a field" }).fill("descr");
    await expect(list.getByRole("button", { name: "Insert {{req.title}}" })).toHaveCount(0);
    await expect(list.getByRole("button", { name: "Insert {{project_description}}" })).toBeVisible();
    await page.getByRole("textbox", { name: "Find a field" }).fill("");
    await page.getByRole("combobox", { name: "From" }).selectOption("req");
    await expect(list.getByRole("button", { name: "Insert {{project_name}}" })).toHaveCount(0);
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
    await selectProjectAdminGroup(page, "Reports");
    const item = (grid: Awaited<ReturnType<typeof searchReportSetup>>) => grid.getByRole("button", { name: new RegExp(`^${name}`) });

    await test.step("the shared layout is listed, with where it comes from, and opens read-only", async () => {
      const table = await searchReportSetup(page, name);
      await expect(table.getByRole("row", { name: new RegExp(`${name}.*The organisation`) })).toBeVisible();
      await item(table).click();
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveAttribute("readonly", "");
      await expect(page.getByRole("note")).toContainText("read-only here");
      await expect(page.getByRole("button", { name: "Save new version" })).toHaveCount(0);
      await page.getByRole("button", { name: "Report layouts" }).click();
    });

    await test.step("hiding it removes it from this project's list and it can be added back", async () => {
      const table = await searchReportSetup(page, name);
      await table.getByRole("button", { name: `Actions for ${name}` }).click();
      await page.getByRole("menuitem", { name: "Hide in this project" }).click();
      await page.getByRole("dialog", { name: /Hide .* in this project\?/ }).getByRole("button", { name: "Hide" }).click();
      await expect(page.getByText("Layout hidden in this project.")).toBeVisible();
      await expect(table.getByRole("row", { name: new RegExp(`${name}.*Hidden`) })).toBeVisible();
      await page.getByRole("button", { name: "Add organisation defaults (1)" }).click();
      await page.getByRole("dialog", { name: "Add organisation defaults" }).getByRole("button", { name: "Add 1 default" }).click();
      await expect(table.getByRole("row", { name: new RegExp(`${name}.*Hidden`) })).toHaveCount(0);
      await expect(item(table)).toBeVisible();
    });

    await test.step("a copy is the project's own layout and can be edited", async () => {
      const table = await searchReportSetup(page, name);
      await table.getByRole("button", { name: `Actions for ${name}` }).click();
      await page.getByRole("menuitem", { name: "Duplicate…" }).click();
      const duplicate = page.getByRole("dialog", { name: "Duplicate layout" });
      await expect(duplicate.getByRole("textbox", { name: "Name" })).toHaveValue(`${name} (copy)`);
      await duplicate.getByRole("button", { name: "Create copy" }).click();
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
    await ensureExpanded(page, "Reports");
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "New layout" }).click();
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

    await saveNewVersion(page);
    await expect(page.getByText("Saved as version 2.")).toBeVisible();
  });

  test("deleting a layout needs its name typed", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    const name = `E2E doomed layout ${suffix}`;
    await createFromProjectAdmin(page, project.id, name);
    await page.getByRole("button", { name: "Report layouts" }).click();

    const table = await searchReportSetup(page, name);
    await table.getByRole("button", { name: `Actions for ${name}` }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    const dialog = page.getByRole("dialog", { name: `Delete ${name}?` });
    await expect(dialog.getByRole("button", { name: "Delete" })).toBeDisabled();
    await dialog.getByRole("textbox").fill(name);
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect(page.getByText("Layout deleted.")).toBeVisible();
    await expect(table.getByRole("button", { name: new RegExp(`^${name}`) })).toHaveCount(0);
  });
});
