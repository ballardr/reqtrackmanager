import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "../../e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a Decision is written in Markdown and can be a full document. The text fields and the Document
 * offer Write and Preview; the detail page shows the formatting, a table and a Mermaid diagram; an approved
 * Decision locks the Document with the rest of its content; and the global search finds text in the Document.
 *
 * Uses a disposable organisation with an administrator and Decision Management switched on, set up through the API.
 */
test.describe("Decision Management: Markdown and the long-form Document", () => {
  test("a Decision with a document shows its formatting, table and diagram, and the document locks on approval", async ({ page }) => {
    const suffix = Date.now();
    const adminEmail = `e2e-dmd-admin-${suffix}@example.com`;
    const serverToken = (
      await (await page.request.post(`${API}/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
    ).access_token;
    const serverHeaders = { Authorization: `Bearer ${serverToken}` };
    const org = await (await page.request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Decision Markdown Org ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Markdown Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, adminEmail, PASSWORD);
    const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const adminHeaders = { Authorization: `Bearer ${adminToken}` };
    expect((await page.request.put(`${API}/orgs/${org.id}/modules/decisions`, { headers: adminHeaders, data: { enabled: true } })).ok()).toBeTruthy();
    const project = await (
      await page.request.post(`${API}/projects`, { headers: adminHeaders, data: { organization_id: org.id, name: `E2E Decision Markdown ${suffix}`, summary: "" } })
    ).json();

    const document = [
      "## Failover plan", "", "The standby board takes over within **200 ms** (quokka-marker).", "",
      "| Option | Cost |", "| --- | --- |", "| Dual | Moderate |", "",
      "```mermaid", "flowchart LR", "  A[Active] --> B[Standby]", "```",
    ].join("\n");

    await test.step("create the Decision: the fields offer Write and Preview", async () => {
      await page.goto(`/projects/${project.id}/modules/decisions`);
      await page.getByRole("button", { name: "New decision" }).click();
      const dialog = page.getByRole("dialog", { name: "New decision" });
      await dialog.getByLabel("Decision title").fill("Adopt a standby controller");
      await dialog.getByLabel("Decision statement").fill("We **adopt** a standby controller.");
      await dialog.getByRole("textbox", { name: "Document" }).fill(document);
      await dialog.getByRole("tab", { name: "Preview" }).last().click();
      await expect(dialog.getByRole("heading", { name: "Failover plan" })).toBeVisible();
      await expect(dialog.getByRole("cell", { name: "Moderate" })).toBeVisible();
      await expect(dialog.getByRole("img", { name: "Diagram: flowchart" })).toBeVisible({ timeout: 30_000 });
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByRole("button", { name: "DEC-001" })).toBeVisible();
    });

    await test.step("the quick view formats the statement and the detail page shows the Document", async () => {
      await page.getByRole("button", { name: "DEC-001" }).click();
      const quickView = page.getByRole("dialog", { name: "DEC-001" });
      await expect(quickView.locator("strong", { hasText: "adopt" })).toBeVisible();
      await expect(quickView).not.toContainText("**");
      await quickView.getByRole("link", { name: "View full details" }).click();
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
      await page.getByRole("button", { name: "Propose" }).click();
      await page.getByRole("button", { name: "Submit for review" }).click();
      await page.getByRole("button", { name: "Approve" }).click();
      const confirm = page.getByRole("dialog", { name: "Approve this Decision?" });
      await confirm.getByRole("button", { name: "Approve" }).click();
      await expect(page.getByText("Approved", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);
      await expect(page.getByRole("region", { name: "Document" })).toBeVisible();
    });
  });
});
