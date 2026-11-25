import { expect, test, type Page } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "../../e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000/api/v1";

/** A 1x1 PNG, the smallest picture a report can print. */
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

/** Creates a disposable organisation with an administrator, switches Decision Management on and returns a Decision. */
async function setUpDecision(page: Page, label: string) {
  const suffix = Date.now();
  const adminEmail = `e2e-dpic-${label}-admin-${suffix}@example.com`;
  const serverToken = (
    await (await page.request.post(`${API}/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (await page.request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Picture ${label} Org ${suffix}` } })).json();
  deleteOrgOnCleanup({ id: org.id });
  await page.request.post(`${API}/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: adminEmail, display_name: `E2E ${label} Admin`, password: PASSWORD, role: "org_admin" },
  });
  await loginAs(page, adminEmail, PASSWORD);
  const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const adminHeaders = { Authorization: `Bearer ${adminToken}` };
  expect((await page.request.put(`${API}/orgs/${org.id}/modules/decisions`, { headers: adminHeaders, data: { enabled: true, default_project_enabled: true } })).ok()).toBeTruthy();
  const project = await (
    await page.request.post(`${API}/projects`, { headers: adminHeaders, data: { organization_id: org.id, name: `E2E Picture ${label} ${suffix}`, summary: "" } })
  ).json();
  const base = `${API}/projects/${project.id}/modules/decisions`;
  const types = await (await page.request.get(`${base}/decision-types`, { headers: adminHeaders })).json();
  const decision = await (
    await page.request.post(base, {
      headers: adminHeaders, data: { title: `Size the actuator ${suffix}`, decision_statement: "We will size it.", decision_type_id: types[0].id },
    })
  ).json();
  return { project, decision, base, adminHeaders };
}

/**
 * Job to be done: a Decision's text holds a picture beside the words. The picture is an attachment of the Decision,
 * chosen from its attachments or uploaded while inserting, drawn on the page, printed by a report (or replaced by its
 * alternative text when the file is confidential) and shown as its alternative text when the file is no longer
 * attached.
 *
 * Uses a disposable organisation with an administrator and Decision Management switched on, set up through the API.
 */
test.describe("Decision Management: pictures in text", () => {
  test("a picture is uploaded while inserting, drawn on the page, printed in a report and falls back to its words", async ({ page }) => {
    const { project, decision, base, adminHeaders } = await setUpDecision(page, "flow");
    await page.goto(`/projects/${project.id}/modules/decisions/${decision.id}`);

    await test.step("the Picture button uploads the file as an attachment and chooses it", async () => {
      await page.getByRole("button", { name: "Edit", exact: true }).click();
      const edit = page.getByRole("dialog", { name: /^Edit/ });
      const statement = edit.getByRole("textbox", { name: "Decision statement" });
      await statement.press("End");
      await edit.getByRole("button", { name: "Picture" }).click();
      const panel = page.getByRole("dialog", { name: "Insert a picture" });
      await expect(panel.getByText("No pictures are attached to this record yet.")).toBeVisible();
      await panel.locator('input[type="file"]').setInputFiles({ name: "plot.png", mimeType: "image/png", buffer: PNG });
      await panel.getByRole("textbox", { name: "Alternative text" }).fill("A red square");
      await panel.getByRole("textbox", { name: "Caption" }).fill("Figure 1");
      await panel.getByRole("button", { name: "Insert" }).click();
      await expect(statement).toHaveValue(/!\[A red square\]\(attachment:[0-9a-f-]{36} "Figure 1"\)/);
      await edit.getByRole("button", { name: "Save" }).click();
      await expect(edit).not.toBeVisible();
    });

    const stored = await (await page.request.get(`${base}/${decision.id}`, { headers: adminHeaders })).json();
    const fileId = /attachment:([0-9a-f-]{36})/.exec(stored.decision_statement)?.[1] ?? "";
    expect(fileId).not.toBe("");

    await test.step("the picture is also in the Attachments card, and the page draws it with its caption", async () => {
      await expect(page.getByRole("link", { name: "plot.png" })).toBeVisible();
      const figure = page.locator("figure.markdown-figure");
      await expect(figure.getByRole("img", { name: "A red square" })).toBeVisible();
      await expect(figure).toContainText("Figure 1");
      await expect(figure.locator("img")).toHaveAttribute("src", new RegExp(`/api/v1/files/${fileId}\\?token=`));
    });

    const layout = await page.request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers: adminHeaders, data: {
        name: "Decision statements", description: "E2E layout", family: "document",
        tree: { schema_version: 1, family: "document", nodes: [
          { type: "each", source: { record_type: "decision" }, children: [{ type: "text", text: "{{record.decision_statement}}" }] },
        ] },
      },
    });
    expect(layout.ok(), await layout.text()).toBeTruthy();
    const run = `${API}/projects/${project.id}/custom-reports/${(await layout.json()).id}/run`;

    await test.step("a report prints the picture with its caption", async () => {
      const html = await (await page.request.get(`${run}?format=html`, { headers: adminHeaders })).text();
      expect(html).toContain("<img");
      expect(html).toContain("Figure 1");
      expect(html).not.toContain("attachment:");
    });

    await test.step("a confidential picture is never printed: the report shows its alternative text", async () => {
      const marked = await page.request.patch(`${API}/files/${fileId}/confidential`, { headers: adminHeaders, data: { confidential: true } });
      expect(marked.ok(), await marked.text()).toBeTruthy();
      const html = await (await page.request.get(`${run}?format=html`, { headers: adminHeaders })).text();
      expect(html).not.toContain("<img");
      expect(html).toContain("A red square");
    });

    await test.step("once the file is no longer an attachment the page shows the alternative text", async () => {
      const removed = await page.request.delete(`${base}/${decision.id}/files/${fileId}`, { headers: adminHeaders });
      expect(removed.status()).toBe(204);
      await page.reload();
      const missing = page.locator("figure.markdown-figure .markdown-picture--missing");
      await expect(missing).toHaveText("A red square");
    });
  });

  test("a picture is refused when the file is not an attachment of the record, and a create form has no Picture button", async ({ page }) => {
    const { project, decision, base, adminHeaders } = await setUpDecision(page, "refuse");

    await test.step("the API refuses a picture of a file the record does not have", async () => {
      const refused = await page.request.put(`${base}/${decision.id}`, {
        headers: adminHeaders, data: { ...decision, rationale: "![x](attachment:3f2c9a52-6c1e-4f6e-9b7a-0a1b2c3d4e5f)" },
      });
      expect(refused.status()).toBe(422);
      expect(await refused.text()).toContain("not an attachment of this record");
    });

    await test.step("a form that creates the record has no Picture button, because there is nothing to attach to yet", async () => {
      await page.goto(`/projects/${project.id}/modules/decisions`);
      await page.getByRole("button", { name: "New decision" }).click();
      const dialog = page.getByRole("dialog", { name: "New decision" });
      await dialog.getByRole("textbox", { name: "Decision statement" }).click();
      await expect(dialog.getByRole("button", { name: "Bold" })).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Picture" })).toHaveCount(0);
    });
  });
});
