import crypto from "node:crypto";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, saveNewVersion, selectProjectAdminGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";
/** A 1 x 1 pixel PNG. */
const PIXEL = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

/**
 * Job to be done: put a ready-made piece (a cover page, a logo, an approvals block) into a report layout from the Blocks
 * and the Text views, and be told what was added.
 *
 * Each test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report snippets", () => {
  installCleanupHook();

  async function login(request: APIRequestContext, email: string, password: string) {
    const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
    return { Authorization: `Bearer ${(await resp.json()).access_token}` };
  }

  /** A disposable organisation with an admin and a project; the page is left logged in as the admin. */
  async function setup(page: Page, request: APIRequestContext) {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-snippets-${suffix}@example.com`;
    const serverHeaders = await login(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Snippets ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Snippets Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const headers = await login(request, adminEmail, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Snippets project ${suffix}`, summary: "" } })).json();
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

  const picker = (page: Page) => page.getByRole("dialog", { name: "Insert snippet" });

  test("the Blocks view inserts a cover page at the start, previews it and keeps it when saved", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    const name = `E2E snippet blocks ${suffix}`;
    await newLayout(page, project.id, name);
    await page.getByRole("tab", { name: "Blocks" }).click();

    await test.step("a heading to put the cover in front of", async () => {
      await page.getByRole("button", { name: "Add block" }).click();
      await page.getByRole("menuitem", { name: "Heading 1" }).click();
      await page.getByLabel("Block details").getByRole("textbox", { name: "Heading", exact: true }).fill("Body starts here");
    });

    await test.step("the dialog offers the snippets by category and names where the cover will go", async () => {
      await page.getByRole("button", { name: "Insert snippet" }).click();
      const dialog = picker(page);
      await expect(dialog.getByRole("button", { name: "Select Cover page" })).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Select Approvals" })).toBeVisible();
      await dialog.getByRole("button", { name: "Select Cover page" }).click();
      await expect(dialog.getByRole("list", { name: "Blocks in Cover page" })).toContainText("Section");
      await expect(dialog.getByRole("group", { name: "Output formats" })).toContainText("PDF");
      await dialog.getByRole("combobox", { name: "Where to insert the snippet" }).selectOption({ label: "Inserting at the start of the layout" });
      await dialog.getByRole("button", { name: "Insert", exact: true }).click();
      await expect(dialog).toBeHidden();
    });

    await test.step("the author is told what was added", async () => {
      const notice = page.getByRole("status", { name: "Snippet inserted" });
      await expect(notice).toContainText("Inserted Cover page");
      await expect(notice).toContainText('Added page style "Cover"');
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("the preview shows the cover's title lines", async () => {
      await page.getByRole("button", { name: "Preview", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Report preview" });
      await dialog.getByRole("button", { name: "Run preview" }).click();
      const frame = dialog.frameLocator('iframe[title="Report preview"]');
      await expect(frame.getByText(project.name).first()).toBeVisible();
      await expect(frame.getByText("Body starts here")).toBeVisible();
      await dialog.getByRole("button", { name: "Close" }).click();
    });

    await test.step("saved, the layout reads back with the cover section first", async () => {
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
      await page.reload();
      await page.getByRole("tab", { name: "Text" }).click();
      const text = await page.getByRole("textbox", { name: "Layout text" }).inputValue();
      expect(text.indexOf("Cover")).toBeGreaterThan(-1);
      expect(text.indexOf("Cover")).toBeLessThan(text.indexOf("Body starts here"));
    });
  });

  test("the Blocks view takes a logo from the image library and a missing picture blocks the insertion", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await newLayout(page, project.id, `E2E snippet logo ${suffix}`);
    await page.getByRole("tab", { name: "Blocks" }).click();
    await page.getByRole("button", { name: "Insert snippet" }).click();
    const dialog = picker(page);
    await dialog.getByRole("button", { name: "Select Logo, top right of the first page" }).click();
    await expect(dialog.getByRole("button", { name: "Insert", exact: true })).toBeDisabled();
    await dialog.getByRole("button", { name: "Choose image…" }).click();
    const fileName = `logo-${suffix}.png`;
    const library = page.getByRole("dialog", { name: "Image library" });
    await library.locator('input[type="file"]').setInputFiles({ name: fileName, mimeType: "image/png", buffer: PIXEL });
    await expect(library.getByRole("button", { name: `Select ${fileName}` })).toHaveAttribute("aria-pressed", "true");
    await library.getByRole("button", { name: "Use image" }).click();
    // The layout is empty, so its start and its end are the same place and only one is offered.
    await expect(dialog.getByRole("combobox", { name: "Where to insert the snippet" })).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Insert", exact: true })).toBeEnabled();
    await dialog.getByRole("button", { name: "Insert", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("status", { name: "Snippet inserted" })).toContainText("Inserted Logo, top right of the first page");
    // The picture is on an Image block, in front of the text, placed from the page.
    await expect(page.getByLabel("Block details").getByText(fileName)).toBeVisible();
    await expect(page.getByLabel("Block details").getByRole("combobox", { name: "Placement" })).toHaveValue("front");
  });

  test("the Text view writes a snippet into the text, reports it, and undoes it while the text stands", async ({ page, request }) => {
    const { project, suffix } = await setup(page, request);
    await newLayout(page, project.id, `E2E snippet text ${suffix}`);
    const editor = page.getByRole("textbox", { name: "Layout text" });
    await editor.fill("@layout document\n\n@heading Existing heading\n");
    await expect(page.getByText("The text is valid.")).toBeVisible();

    await test.step("insert at the end", async () => {
      await page.getByRole("button", { name: "Insert snippet" }).click();
      const dialog = picker(page);
      await dialog.getByRole("button", { name: "Select Approvals" }).click();
      await expect(dialog.getByRole("combobox", { name: "Where to insert the snippet" })).toHaveValue("0");
      await dialog.getByRole("button", { name: "Insert", exact: true }).click();
      await expect(dialog).toBeHidden();
      await expect(editor).toHaveValue(/@heading Existing heading[\s\S]*Approvals/);
      await expect(page.getByRole("status", { name: "Snippet inserted" })).toContainText("Inserted Approvals");
    });

    await test.step("Undo puts the text back as it was", async () => {
      await page.getByRole("button", { name: "Undo insertion" }).click();
      await expect(editor).toHaveValue("@layout document\n\n@heading Existing heading\n");
      await expect(page.getByRole("status", { name: "Snippet inserted" })).toHaveCount(0);
    });

    await test.step("insert at the start, then edit: Undo is no longer offered, and the layout saves", async () => {
      await page.getByRole("button", { name: "Insert snippet" }).click();
      const dialog = picker(page);
      await dialog.getByRole("button", { name: "Select Document control" }).click();
      await dialog.getByRole("combobox", { name: "Where to insert the snippet" }).selectOption({ label: "Inserting at the start of the layout" });
      await dialog.getByRole("button", { name: "Insert", exact: true }).click();
      await expect(editor).toHaveValue(/@layout document[\s\S]*Document control[\s\S]*Existing heading/);
      await editor.press("End");
      await editor.pressSequentially(" ");
      await expect(page.getByRole("button", { name: "Undo insertion" })).toHaveCount(0);
      await expect(page.getByText("The text is valid.")).toBeVisible();
      await saveNewVersion(page);
      await expect(page.getByText("Saved as version 2.")).toBeVisible();
    });
  });

  test("text with problems is not an insertion target, and a picture from a project's library is refused for an organisation layout", async ({ page, request }) => {
    const { org, headers, project, suffix } = await setup(page, request);
    await newLayout(page, project.id, `E2E snippet refusals ${suffix}`);
    await page.getByRole("textbox", { name: "Layout text" }).fill("@layout document\n\n@nonsense here\n");
    await page.getByRole("button", { name: "Insert snippet" }).click();
    await expect(page.getByText(/Fix the problems in the text before inserting a snippet/)).toBeVisible();
    await expect(picker(page)).toHaveCount(0);

    // The organisation's library has no project pictures, so the refusal is made through the API the dialog calls.
    const image = (await (await request.post(`${API}/projects/${project.id}/report-images`, {
      headers, multipart: { file: { name: `project-${suffix}.png`, mimeType: "image/png", buffer: PIXEL } },
    })).json()) as { id: string };
    const applied = await (await request.post(`${API}/orgs/${org.id}/report-layouts/snippets/logo-top-right/apply`, {
      headers, data: { tree: { schema_version: 1, family: "document", nodes: [] }, parameters: { image: image.id }, target: { container: "nodes", index: 0 } },
    })).json();
    expect(applied.ok).toBe(false);
    expect(JSON.stringify(applied.errors)).toContain("image");
  });
});
