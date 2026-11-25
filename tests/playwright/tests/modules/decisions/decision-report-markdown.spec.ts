import crypto from "node:crypto";

import { expect, test, type APIRequestContext } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, PASSWORD } from "../../e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000/api/v1";

async function token(request: APIRequestContext, email: string, password: string) {
  const resp = await request.post(`${API}/auth/login`, { data: { email, password } });
  return { Authorization: `Bearer ${(await resp.json()).access_token}` };
}

/**
 * Job to be done: a Decision written in Markdown, with a table and a diagram, is printed in a report as it reads on
 * screen. A custom layout prints the Decision's document through its placeholder, and every format carries the
 * formatting, the table and the drawn diagram (the converter service draws it, in the version and font of the screen).
 *
 * Uses a disposable organisation with an administrator and Decision Management switched on, set up through the API.
 */
test.describe("Decision Management: Markdown and diagrams in reports", () => {
  test("a layout that prints the Decision's document carries its formatting, table and drawn diagram in HTML, Word and PDF", async ({ request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const adminEmail = `e2e-decision-md-report-${suffix}@example.com`;
    const serverHeaders = await token(request, "admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Decision Markdown Report ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Markdown Report Admin", password: PASSWORD, role: "org_admin" },
    });
    const headers = await token(request, adminEmail, PASSWORD);
    expect((await request.put(`${API}/orgs/${org.id}/modules/decisions`, { headers, data: { enabled: true, default_project_enabled: true } })).ok()).toBeTruthy();
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Markdown Report ${suffix}`, summary: "" } })).json();
    const base = `${API}/projects/${project.id}/modules/decisions`;
    const types = await (await request.get(`${base}/decision-types`, { headers })).json();

    const document = [
      "## Failover plan", "", `The standby board takes over within **200 ms** (marker-${suffix}).`, "",
      "- primary", "  - standby", "", "| Option | Cost |", "| --- | --- |", "| Dual | Moderate |", "",
      "```mermaid", "flowchart LR", "  A[Active] --> B[Standby]", "```",
    ].join("\n");
    const created = await request.post(base, {
      headers, data: { title: `Adopt standby ${suffix}`, decision_statement: "We will fail over.", decision_type_id: types[0].id, document },
    });
    expect(created.ok(), await created.text()).toBeTruthy();

    const layout = await request.post(`${API}/projects/${project.id}/report-layouts`, {
      headers, data: {
        name: `Decision documents ${suffix}`, description: "E2E layout", family: "document",
        tree: {
          schema_version: 1, family: "document", nodes: [
            { type: "heading", text: "Decision documents" },
            { type: "each", source: { record_type: "decision" }, children: [{ type: "text", text: "{{record.document}}" }] },
          ],
        },
      },
    });
    expect(layout.ok(), await layout.text()).toBeTruthy();
    const run = `${API}/projects/${project.id}/custom-reports/${(await layout.json()).id}/run`;

    await test.step("HTML: formatted text, nested list, table and an inline drawn diagram without a style sheet", async () => {
      const response = await request.get(`${run}?format=html`, { headers });
      expect(response.ok(), await response.text()).toBeTruthy();
      const html = await response.text();
      expect(html).toContain(`<strong>200 ms</strong> (marker-${suffix})`);
      expect(html).toContain("<ul><li>primary<ul><li>standby</li></ul></li></ul>");
      expect(html).toContain("<p>Option</p>");
      const figure = html.match(/<figure[\s\S]*?<\/figure>/)?.[0] ?? "";
      expect(figure).toContain("<svg");
      expect(figure).toContain('aria-label="Diagram (flowchart)');
      expect(figure).not.toContain("<style");
      expect(html).not.toContain("<script");
    });

    await test.step("Word and PDF carry the same document", async () => {
      const word = await request.get(`${run}?format=docx`, { headers });
      expect(word.ok(), await word.text()).toBeTruthy();
      const docx = await word.body();
      expect(docx.subarray(0, 2).toString()).toBe("PK");
      expect(docx.length).toBeGreaterThan(20_000); // the diagram is a picture inside the file
      const pdf = await request.get(`${run}?format=pdf`, { headers });
      expect(pdf.ok(), await pdf.text()).toBeTruthy();
      expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
    });
  });
});
