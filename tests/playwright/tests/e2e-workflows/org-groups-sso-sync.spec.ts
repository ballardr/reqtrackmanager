import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, openOrgGroupPanel, selectOrgAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an org group's SSO-sync sub-section (docs/decisions.md) is gated on SSO being configured for the
 * organisation, and the explicit enable/disable toggle within it works in both directions. The first scenario pins
 * that the entire sub-section (toggle, name input, role select, save action) is absent without SSO configured,
 * not only the role select.
 *
 * Runs against a dedicated, freshly created organisation and admin, because it mutates the SSO configuration via
 * `PUT /orgs/{id}/sso-config`, which would leak SSO state into specs sharing a persona (e.g. the Gamma org in
 * `org-group-nesting.spec.ts`). `sso.spec.ts` covers the real Keycloak flow; this spec exercises only the Org
 * Admin UI's gating and toggle logic, so a fake (never-dialled) issuer URL suffices: `oidc_issuer_url` and
 * `oidc_client_id` only need to be truthy for the frontend gate.
 */
const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "ChangeMe123!";
const apiBaseUrl = "http://localhost:8000";

test.describe("org groups: SSO-sync sub-section gating and toggle", () => {
  test("hidden entirely without SSO configured, then togglable on/off once it is", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E SSO Sync Org ${suffix}`;
    const orgAdminEmail = `e2e-sso-sync-admin-${suffix}@example.com`;
    const groupName = `Sync Test Group ${suffix}`;

    const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    });
    const adminToken = (await adminLoginResp.json()).access_token;
    const authHeaders = { Authorization: `Bearer ${adminToken}` };

    const org = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: authHeaders, data: { name: orgName } })
    ).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: authHeaders,
      data: { email: orgAdminEmail, display_name: "SSO Sync Test Admin", password: "OrgAdmin123!", role: "org_admin" },
    });

    await page.goto("/login");
    await page.getByLabel("Email").fill(orgAdminEmail);
    await page.getByLabel("Password").fill("OrgAdmin123!");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    // `require_org_role(ORG_ADMIN)` (`services/rbac.py`) deliberately does
    // NOT let a server admin bypass it (I-M-05: server admin access is
    // tenancy-wide, not content-wide) — the platform admin's own token from
    // above can create the org and its first user, but every org-scoped
    // admin action after this point (including the SSO config PUT below)
    // needs the new org admin's own token instead.
    const orgAdminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const orgAdminAuthHeaders = { Authorization: `Bearer ${orgAdminToken}` };

    await page.goto(`/orgs/${org.id}/admin`);
    await expect(page.getByRole("heading", { name: orgName })).toBeVisible();
    await selectOrgAdminGroup(page, "Groups");

    await test.step("create the test group", async () => {
      await page.getByRole("button", { name: "New group" }).click();
      const dialog = page.getByRole("dialog", { name: "New group" });
      await dialog.getByPlaceholder("e.g. Engineering").fill(groupName);
      await dialog.getByRole("button", { name: "Create" }).click();
      await expect(dialog).not.toBeVisible();
      await expect(page.getByRole("button", { name: groupName })).toBeVisible();
    });

    await test.step("without SSO configured, the whole sync sub-section is absent — only the hint renders", async () => {
      const panel = await openOrgGroupPanel(page, groupName);
      await expect(panel.getByRole("checkbox", { name: "Sync membership and role from an SSO/IdP group" })).toHaveCount(0);
      await expect(panel.getByPlaceholder("e.g. eng-team")).toHaveCount(0);
      await expect(panel.getByLabel("Grants role on sync")).toHaveCount(0);
      await expect(panel.getByRole("button", { name: "Save sync settings" })).toHaveCount(0);
      await expect(panel.getByText(/Set up SSO\/OIDC/)).toBeVisible();
      await panel.getByRole("button", { name: "Close" }).click();
    });

    await test.step("configure SSO for the org (setup, not what's being tested)", async () => {
      const ssoResp = await page.request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/sso-config`, {
        headers: orgAdminAuthHeaders,
        data: {
          slug: `e2e-sso-sync-${suffix}`, sso_enabled: true, sso_only: false,
          oidc_issuer_url: "https://idp.example.com/never-dialled", oidc_client_id: "never-dialled-client",
        },
      });
      expect(ssoResp.ok()).toBe(true);
      await page.reload();
      await selectOrgAdminGroup(page, "Groups");
    });

    await test.step("the toggle starts unchecked (group isn't synced yet) and reveals the fields once checked", async () => {
      const panel = await openOrgGroupPanel(page, groupName);
      const toggle = panel.getByRole("checkbox", { name: "Sync membership and role from an SSO/IdP group" });
      await expect(toggle).toBeVisible();
      await expect(toggle).not.toBeChecked();
      await expect(panel.getByPlaceholder("e.g. eng-team")).toHaveCount(0);

      await toggle.check();
      await panel.getByPlaceholder("e.g. eng-team").fill("eng-team-sync");
      await panel.getByLabel("Grants role on sync").selectOption("member");
      await panel.getByRole("button", { name: "Save sync settings" }).click();
      // Principle 7: every mutation ends with feedback.
      await expect(page.getByText("Sync settings updated")).toBeVisible();
      // Close before the next step reopens it: `SidePanel`'s backdrop (`role="presentation"`) covers the underlying
      // `DirectoryTable` row while open and would intercept the next click on that row.
      await panel.getByRole("button", { name: "Close" }).click();
    });

    await test.step("re-opening the panel shows the toggle checked by default and the saved values populated", async () => {
      const panel = await openOrgGroupPanel(page, groupName);
      await expect(panel.getByRole("checkbox", { name: "Sync membership and role from an SSO/IdP group" })).toBeChecked();
      await expect(panel.getByPlaceholder("e.g. eng-team")).toHaveValue("eng-team-sync");
      await expect(panel.getByLabel("Grants role on sync")).toHaveValue("member");

      const groupsAfterSave = await (
        await page.request.get(`${apiBaseUrl}/api/v1/orgs/${org.id}/groups`, { headers: orgAdminAuthHeaders })
      ).json();
      const savedGroup = groupsAfterSave.find((g: { name: string }) => g.name === groupName);
      expect(savedGroup.idp_synced_group_name).toBe("eng-team-sync");
      expect(savedGroup.granted_org_role).toBe("member");

      await test.step("unchecking clears both fields immediately, no separate Save click needed", async () => {
        await panel.getByRole("checkbox", { name: "Sync membership and role from an SSO/IdP group" }).uncheck();
        await expect(panel.getByPlaceholder("e.g. eng-team")).toHaveCount(0);

        await expect(async () => {
          const groupsAfterClear = await (
            await page.request.get(`${apiBaseUrl}/api/v1/orgs/${org.id}/groups`, { headers: orgAdminAuthHeaders })
          ).json();
          const clearedGroup = groupsAfterClear.find((g: { name: string }) => g.name === groupName);
          expect(clearedGroup.idp_synced_group_name).toBeNull();
          expect(clearedGroup.granted_org_role).toBeNull();
        }).toPass();
      });
    });
  });
});
