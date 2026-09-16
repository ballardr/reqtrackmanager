import { expect, test } from "@playwright/test";

import { loginAs, PASSWORD, selectOrgAdminGroup } from "./helpers";

const apiBaseUrl = "http://localhost:8000";

/**
 * Job to be done: docs/decisions.md's "AI approval via MCP" entry. An AI
 * assistant acting through the MCP server may only approve/decide/complete
 * something once an org admin AND that project's own manager/administrator
 * have each explicitly enabled it — and enabling either one requires an
 * explicit acknowledgment that an AI-made approval isn't necessarily a
 * deliberate, in-the-moment human decision. This spec covers the UI half
 * of that (the two toggles + the acknowledgment dialog blocking Confirm
 * until checked, and persistence); the actual MCP-channel gate/audit-marker
 * behaviour is covered by backend/tests/test_ai_approvals_via_mcp.py and
 * mcp-server/tests/test_server.py, which can call the real MCP tools —
 * outside what a browser-driven Playwright test can exercise.
 *
 * Uses a brand-new, disposable organisation + admin + project created via
 * the API (mirroring org-security-controls.spec.ts) rather than shared
 * seed data, since this org-wide toggle could otherwise collide with
 * another spec's concurrent use of a shared org.
 */
test.describe("AI approval via MCP: org + project opt-in toggles and acknowledgment", () => {
  test("enabling either toggle requires acknowledging the trade-off first, and both persist", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E AI Approval Org ${suffix}`;
    const adminEmail = `e2e-ai-approval-admin-${suffix}@example.com`;
    const adminName = "E2E AI Approval Admin";
    const projectName = `E2E AI Approval Project ${suffix}`;

    const serverAdminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: "admin@example.com", password: "ChangeMe123!" },
    });
    const serverAdminToken = (await serverAdminLoginResp.json()).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };

    const org = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverAdminHeaders, data: { name: orgName } })
    ).json();
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: adminName, password: PASSWORD, role: "org_admin" },
    });

    const ownerToken = (
      await (
        await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })
      ).json()
    ).access_token;
    const project = await (
      await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
        headers: { Authorization: `Bearer ${ownerToken}` },
        data: { organization_id: org.id, name: projectName, summary: "E2E seed project." },
      })
    ).json();

    await loginAs(page, adminEmail, PASSWORD);

    await test.step("org level: toggle blocked by dialog until acknowledged, then persists", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Security");

      const toggle = page.getByRole("switch", { name: "Allow AI approval via MCP" });
      await expect(toggle).not.toBeChecked();
      await toggle.click();

      const dialog = page.getByRole("dialog", { name: "Allow AI approval for this organisation?" });
      await expect(dialog).toBeVisible();
      const confirmButton = dialog.getByRole("button", { name: "Allow AI approval" });
      await expect(confirmButton).toBeDisabled();
      await dialog.getByRole("checkbox").click();
      await expect(confirmButton).toBeEnabled();
      await confirmButton.click();
      await expect(toggle).toBeChecked();

      await page.getByRole("button", { name: "Save security settings" }).click();
      await page.reload();
      await selectOrgAdminGroup(page, "Security");
      await expect(page.getByRole("switch", { name: "Allow AI approval via MCP" })).toBeChecked();
    });

    await test.step("project level: same acknowledgment gate, independent of the org toggle, and persists", async () => {
      await page.goto(`/projects/${project.id}/admin`);

      const toggle = page.getByRole("switch", { name: "Allow AI approval via MCP for this project" });
      await expect(toggle).not.toBeChecked();
      await toggle.click();

      const dialog = page.getByRole("dialog", { name: "Allow AI approval for this project?" });
      await expect(dialog).toBeVisible();
      const confirmButton = dialog.getByRole("button", { name: "Allow AI approval" });
      await expect(confirmButton).toBeDisabled();
      await dialog.getByRole("checkbox").click();
      await expect(confirmButton).toBeEnabled();
      await confirmButton.click();
      await expect(toggle).toBeChecked();

      await page.getByRole("button", { name: "Save settings" }).click();
      await page.reload();
      await expect(page.getByRole("switch", { name: "Allow AI approval via MCP for this project" })).toBeChecked();
    });
  });
});
