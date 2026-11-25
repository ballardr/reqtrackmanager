import { expect, test, type Page } from "@playwright/test";

import { deleteOrgOnCleanup, expectCurrentStep, installCleanupHook, loginAs, PASSWORD, promoteTo } from "../../e2e-workflows/helpers";
import { chooseMarkdownView, markdownField, offeredMarkdownViews, shownMarkdownView } from "../../markdownViews";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000/api/v1";

/** Creates a disposable organisation with an administrator, switches Decision Management on and returns a project in it. */
async function setUpDecisionProject(page: Page, label: string) {
  const suffix = Date.now();
  const adminEmail = `e2e-dmd-${label}-admin-${suffix}@example.com`;
  const serverToken = (
    await (await page.request.post(`${API}/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (await page.request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Decision ${label} Org ${suffix}` } })).json();
  deleteOrgOnCleanup({ id: org.id });
  await page.request.post(`${API}/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: adminEmail, display_name: `E2E ${label} Admin`, password: PASSWORD, role: "org_admin" },
  });
  await loginAs(page, adminEmail, PASSWORD);
  const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const adminHeaders = { Authorization: `Bearer ${adminToken}` };
  expect((await page.request.put(`${API}/orgs/${org.id}/modules/decisions`, { headers: adminHeaders, data: { enabled: true } })).ok()).toBeTruthy();
  const project = await (
    await page.request.post(`${API}/projects`, { headers: adminHeaders, data: { organization_id: org.id, name: `E2E Decision ${label} ${suffix}`, summary: "" } })
  ).json();

  return { project, adminHeaders };
}

/**
 * Job to be done: a Decision is written in Markdown and can be a full document. The text fields and the Document
 * offer Write and Preview; the detail page shows the formatting, a table and a Mermaid diagram; an approved
 * Decision locks the Document with the rest of its content; and the global search finds text in the Document.
 *
 * Uses a disposable organisation with an administrator and Decision Management switched on, set up through the API.
 */
test.describe("Decision Management: Markdown and the long-form Document", () => {
  test("a Decision with a document shows its formatting, table and diagram, and the document locks on approval", async ({ page }) => {
    const { project, adminHeaders } = await setUpDecisionProject(page, "markdown");

    const document = [
      "## Failover plan", "", "The standby board takes over within **200 ms** (quokka-marker).", "",
      "| Option | Cost |", "| --- | --- |", "| Dual | Moderate |", "",
      "```mermaid", "flowchart LR", "  A[Active] --> B[Standby]", "```",
    ].join("\n");

    await test.step("create the Decision: the fields offer Visual, Write and Preview", async () => {
      // The run starts remembering Write (playwright.config.ts); this step tests the default, so the choice is cleared.
      await page.evaluate(() => localStorage.removeItem("reqtrack.markdownEditorView"));
      await page.goto(`/projects/${project.id}/modules/decisions`);
      await page.getByRole("button", { name: "New decision" }).click();
      const dialog = page.getByRole("dialog", { name: "New decision" });
      // The fields open in the Visual view; the source is typed in Write, chosen for each field (a choice changes that field only).
      const fieldNamed = (name: string) => dialog.locator(".markdown-editor").filter({ has: page.getByRole("textbox", { name }) });
      await expect(shownMarkdownView(markdownField(dialog, 0), "Visual")).toHaveCount(1);
      await expect(offeredMarkdownViews(markdownField(dialog, 0))).toHaveCount(3);
      await chooseMarkdownView(fieldNamed("Decision statement"), "Write");
      // Another field on the form is unchanged by that choice.
      await expect(shownMarkdownView(fieldNamed("Context"), "Visual")).toHaveCount(1);
      await chooseMarkdownView(fieldNamed("Document"), "Write");
      await dialog.getByLabel("Decision title").fill("Adopt a standby controller");
      await dialog.getByLabel("Decision statement").fill("We **adopt** a standby controller.");
      await dialog.getByRole("textbox", { name: "Document" }).fill(document);
      await chooseMarkdownView(fieldNamed("Document"), "Preview");
      await expect(dialog.getByRole("heading", { name: "Failover plan" })).toBeVisible();
      await expect(dialog.getByRole("cell", { name: "Moderate" })).toBeVisible();
      await expect(dialog.getByRole("img", { name: "Diagram: flowchart" })).toBeVisible({ timeout: 30_000 });
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByRole("link", { name: /^(\w+-)?DEC-001$/ })).toBeVisible();
    });

    await test.step("the detail page formats the statement and shows the Document", async () => {
      await page.getByRole("link", { name: /^(\w+-)?DEC-001$/ }).click();
      await expect(page.locator("strong", { hasText: "adopt" })).toBeVisible();
      await expect(page.locator(".record-header")).not.toContainText("**");
      const card = page.getByRole("region", { name: "Document" });
      await expect(card.getByRole("heading", { name: "Failover plan" })).toBeVisible();
      await expect(card.getByRole("cell", { name: "Moderate" })).toBeVisible();
      await expect(card.getByRole("img", { name: "Diagram: flowchart" })).toBeVisible({ timeout: 30_000 });
    });

    await test.step("the search finds text in the Document", async () => {
      const found = await page.request.post(`${API}/search`, {
        headers: adminHeaders,
        data: { q: "quokka-marker", scope: "project", project_id: project.id, fields: ["id", "title", "document"] },
      });
      const hits = (await found.json()).hits;
      expect(hits).toHaveLength(1);
      expect(hits[0].snippet.text).not.toContain("**");
    });

    await test.step("an approved Decision locks the Document", async () => {
      await promoteTo(page, "Proposed");
      await expectCurrentStep(page, "Proposed");
      await promoteTo(page, "Under review");
      await expectCurrentStep(page, "Under review");
      await promoteTo(page, "Approved");
      const confirm = page.getByRole("dialog", { name: "Approve this Decision?" });
      await confirm.getByRole("button", { name: "Approve" }).click();
      await expectCurrentStep(page, "Approved");
      await expect(page.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);
      await expect(page.getByRole("region", { name: "Document" })).toBeVisible();
    });
  });

  test("a field shows its formatting buttons only while it is being worked in", async ({ page }) => {
    const { project } = await setUpDecisionProject(page, "toolbar");
    await page.evaluate(() => localStorage.removeItem("reqtrack.markdownEditorView"));
    await page.goto(`/projects/${project.id}/modules/decisions`);
    await page.getByRole("button", { name: "New decision" }).click();
    const dialog = page.getByRole("dialog", { name: "New decision" });
    const bold = dialog.getByRole("button", { name: "Bold", exact: true });
    const statement = dialog.getByRole("textbox", { name: "Decision statement" });

    await test.step("no formatting buttons are drawn before a field is used", async () => {
      await expect(shownMarkdownView(markdownField(dialog, 0), "Visual")).toHaveCount(1);
      await expect(statement).toBeVisible();
      await expect(dialog.getByRole("toolbar")).toHaveCount(0);
      await expect(bold).toHaveCount(0);
    });

    await test.step("clicking a field shows its buttons, which take the room of their own row only, and a button applies to the text", async () => {
      const before = (await statement.boundingBox())?.y;
      await statement.click();
      await page.keyboard.type("adopt");
      await expect(bold).toHaveCount(1);
      // The toolbar is a row of its own that exists only while the field is in use, so the field sits below it.
      expect((await statement.boundingBox())?.y).toBeGreaterThan(before ?? 0);
      await page.keyboard.press("ControlOrMeta+A");
      await bold.click();
      await expect(statement.locator("strong", { hasText: "adopt" })).toBeVisible();
      // Pressing the button did not end the editing: the buttons are still there.
      await expect(bold).toHaveCount(1);
    });

    await test.step("moving to another field moves the buttons with it, and leaving the dialog's fields hides them", async () => {
      await dialog.getByRole("textbox", { name: "Context" }).click();
      await expect(bold).toHaveCount(1);
      await dialog.getByLabel("Decision title").click();
      await expect(bold).toHaveCount(0);
    });

    await test.step("the keyboard shows the buttons when the field takes focus and Shift+Tab reaches them", async () => {
      await statement.focus();
      await expect(bold).toHaveCount(1);
      await page.keyboard.press("Shift+Tab");
      await expect(dialog.getByRole("button", { name: "Undo", exact: true })).toBeFocused();
      await expect(bold).toHaveCount(1);
    });
  });

  test("a Decision is written in the Visual view, and pasted Markdown is converted on request", async ({ page }) => {
    const { project } = await setUpDecisionProject(page, "visual");
    await page.evaluate(() => localStorage.removeItem("reqtrack.markdownEditorView"));
    await page.goto(`/projects/${project.id}/modules/decisions`);
    await page.getByRole("button", { name: "New decision" }).click();
    const dialog = page.getByRole("dialog", { name: "New decision" });
    await dialog.getByLabel("Decision title").fill("Adopt a standby controller");
    await expect(shownMarkdownView(markdownField(dialog, 0), "Visual")).toHaveCount(1);

    await test.step("typing Markdown shortcuts formats the text and a diagram is drawn", async () => {
      const statement = dialog.getByRole("textbox", { name: "Decision statement" });
      await statement.click();
      await page.keyboard.type("We **adopt** a standby controller.");
      await expect(statement.locator("strong", { hasText: "adopt" })).toBeVisible();
      const document = dialog.getByRole("textbox", { name: "Document" });
      await document.click();
      // Only the field being worked in shows its formatting buttons.
      await expect(dialog.getByRole("button", { name: "Diagram" })).toHaveCount(1);
      await dialog.getByRole("button", { name: "Diagram" }).click();
      await expect(dialog.getByRole("img", { name: "Diagram: flowchart" })).toBeVisible({ timeout: 30_000 });
    });

    await test.step("pasted Markdown is offered for conversion", async () => {
      const context = dialog.getByRole("textbox", { name: "Context" });
      await context.click();
      await context.evaluate((element) => {
        const data = new DataTransfer();
        data.setData("text/plain", "## Background\n\n- first point\n- second point");
        element.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
      });
      await expect(dialog.getByText("The pasted text looks like Markdown.")).toBeVisible();
      await dialog.getByRole("button", { name: "Convert to formatting" }).click();
      await expect(context.getByRole("heading", { name: "Background" })).toBeVisible();
      await expect(context.getByRole("listitem")).toHaveCount(2);
    });

    await test.step("the saved Decision shows the formatting", async () => {
      await dialog.getByRole("button", { name: "Save" }).click();
      await page.getByRole("link", { name: /^(\w+-)?DEC-001$/ }).click();
      await expect(page.locator("strong", { hasText: "adopt" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Background" })).toBeVisible();
      await expect(page.getByRole("listitem").filter({ hasText: "first point" })).toBeVisible();
    });
  });
});
