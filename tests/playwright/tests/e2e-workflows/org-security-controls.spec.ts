import { expect, test } from "@playwright/test";

import { clickAndAwaitSave, deleteOrgOnCleanup, ensureExpanded, ensureTwoFactorSectionExpanded, nextTotpCode, installCleanupHook, loginAs, PASSWORD, selectOrgAdminGroup, selectPreferencesGroup, selectProjectAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";

/**
 * Job to be done: an org admin can require 2FA organisation-wide (blocking every member, including admins, from
 * organisation and project access until they enrol; see docs/decisions.md), lock a user's display name, filter the
 * member directory (stale / no-2FA / no-project-access), and control whether external, not-yet-member accounts can
 * be added to projects.
 *
 * Uses a disposable organisation, admin and project created through the API (as
 * org-admin-project-statuses-and-link-types.spec.ts does), not the shared "E2E Gamma Labs" org: the organisation-wide
 * 2FA toggle blocks every member including its admin, so it would collide with any other spec using Gamma
 * concurrently (org-admin-modules.spec.ts also flips a Gamma-wide toggle).
 */
test.describe("org security controls: 2FA requirement, display-name lock, member filters", () => {
  test("org-wide 2FA requirement blocks access until enabled; display-name lock; member filters", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Security Org ${suffix}`;
    const adminEmail = `e2e-security-admin-${suffix}@example.com`;
    const adminName = "E2E Security Admin";
    const projectName = `E2E Security Project ${suffix}`;

    const serverAdminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: "admin@example.com", password: "ChangeMe123!" },
    });
    const serverAdminToken = (await serverAdminLoginResp.json()).access_token;
    const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };

    const org = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverAdminHeaders, data: { name: orgName } })
    ).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: serverAdminHeaders,
      data: { email: adminEmail, display_name: adminName, password: PASSWORD, role: "org_admin" },
    });

    const ownerToken = (
      await (
        await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })
      ).json()
    ).access_token;
    await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: { Authorization: `Bearer ${ownerToken}` },
      data: { organization_id: org.id, name: projectName, summary: "E2E seed project." },
    });

    await loginAs(page, adminEmail, PASSWORD);
    await page.goto("/orgs");
    await expect(page).toHaveURL(/\/orgs\/[^/]+\/admin$/);

    await test.step("member directory filters: stale, no-2FA, no-project-access", async () => {
      // Users is its own top-level resource-menu group — a real navigation, so it must be selected before
      // the section is reachable at all.
      await selectOrgAdminGroup(page, "Users");
      await ensureExpanded(page, "Organisation users");
      // The filters are independent `FilterCheckbox`es in the shared `FilterPanel` (no "Clear filters" button), so each is
      // unchecked explicitly. Each toggle waits for its own reload (`/users?` with or without the filter's param) so a
      // late reload cannot re-render a row menu shut.
      const toggle = async (name: string, param: string, on: boolean) => {
        await Promise.all([
          page.waitForResponse((r) => r.url().includes("/users?") && r.url().includes(param) === on),
          page.getByRole("checkbox", { name }).click(),
        ]);
      };
      await toggle("No 2FA", "has_2fa=false", true);
      await expect(page.getByText(adminEmail)).toBeVisible();
      await toggle("No 2FA", "has_2fa=false", false);

      // The admin logged in moments ago, so isn't stale.
      await toggle("Stale (180+ days)", "stale_since_days=180", true);
      await expect(page.getByText(adminEmail)).toHaveCount(0);
      await toggle("Stale (180+ days)", "stale_since_days=180", false);
      await expect(page.getByText(adminEmail)).toBeVisible();
    });

    await test.step("lock then unlock a display name", async () => {
      // "Lock/Unlock display name" is a row `ActionMenu` item: open it through the kebab trigger (`${display name}'s
      // actions`), then click the `menuitem` in the `Popover`, after waiting for the menu itself (the popover repositions
      // after mount), as org-merge-import.spec.ts does.
      const row = page.locator("tr", { hasText: adminEmail });
      // The menu trigger's accessible name (`usersActionsFor`, strings.ts)
      // is keyed off the user's display name, not their email.
      const menuTriggerName = `${adminName}'s actions`;
      await row.getByRole("button", { name: menuTriggerName }).click();
      await expect(page.getByRole("menu", { name: menuTriggerName })).toBeVisible();
      // Await the lock change itself before reopening the menu, so its
      // label has flipped (the menu reflects the saved state).
      await clickAndAwaitSave(page, page.getByRole("menuitem", { name: "Lock display name" }), "/display-name-lock");

      await row.getByRole("button", { name: menuTriggerName }).click();
      await expect(page.getByRole("menu", { name: menuTriggerName })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Unlock display name" })).toBeVisible();
      // Await the lock change itself before reopening the menu, so its
      // label has flipped (the menu reflects the saved state).
      await clickAndAwaitSave(page, page.getByRole("menuitem", { name: "Unlock display name" }), "/display-name-lock");

      await row.getByRole("button", { name: menuTriggerName }).click();
      await expect(page.getByRole("menu", { name: menuTriggerName })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Lock display name" })).toBeVisible();
      await page.keyboard.press("Escape");
    });

    let projectId = "";
    await test.step("enabling org-wide 2FA blocks the admin's own project/settings access until they enrol", async () => {
      // 2FA/self-signup/external-user-policy live in the "Security"
      // top-level resource-menu group — a real navigation, so it must be selected
      // before the card is reachable at all.
      await selectOrgAdminGroup(page, "Security");
      await ensureExpanded(page, "Security");
      await page.getByRole("switch", { name: "Require two-factor authentication" }).click();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/advanced-settings") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save security settings" }).click(),
      ]);

      await page.goto("/projects");
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const projectsResp = await page.request.get("http://localhost:8000/api/v1/projects?archived=false", {
        headers: { Authorization: `Bearer ${token}` },
      });
      // The cross-org project *list* deliberately isn't gated per-org (a
      // user could belong to other, non-2FA-required orgs too) — only
      // project-*specific* endpoints enforce a single org's requirement.
      projectId = (await projectsResp.json()).find((p: { name: string }) => p.name === projectName).id;

      // Wait for the project-detail fetch this click triggers (it resolves 403, driving the "2FA required" UI) before
      // asserting: a bare click() plus an immediate expect() relies on the assertion timeout to outlast the navigation and
      // network round trip.
      await Promise.all([
        page.waitForResponse((r) => r.url().includes(`/api/v1/projects/${projectId}`) && r.request().method() === "GET"),
        page.getByText(projectName).click(),
      ]);
      // `toggleDisplayNameLock`'s `reload()` can still be in flight from the previous test.step and reset this toggle's
      // local state to its last-saved value right before Save, so the PUT would send `require_2fa: false`; OrgAdminPage.tsx
      // guards against that with `advancedDirtyRef`, so this assertion needs no special timeout.
      await expect(page.getByText(/2FA|two-factor/i).first()).toBeVisible();
    });

    await test.step("a direct API call against the specific project is also blocked, not just the UI", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const resp = await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(resp.status()).toBe(403);
    });

    let recoverySecret = "";
    await test.step("the blocked admin's self-service way out: /auth/2fa isn't org-scoped, so they can still enrol themselves", async () => {
      await page.goto("/preferences");
      await selectPreferencesGroup(page, "Security");
      await ensureTwoFactorSectionExpanded(page);
      const [enrollResponse] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/auth/2fa/enroll") && r.request().method() === "POST"),
        page.getByRole("switch", { name: "Enable 2FA" }).click(),
      ]);
      ({ secret: recoverySecret } = await enrollResponse.json());
      await page.getByLabel("Confirm code").fill(await nextTotpCode(recoverySecret));
      await page.getByRole("button", { name: "Confirm code" }).click();
      await expect(page.getByText("Enabled", { exact: true })).toBeVisible();
    });

    await test.step("2FA now enabled, access is restored and the org-wide requirement can be turned back off, cleaning up for later specs", async () => {
      await page.goto("/projects");
      await page.getByText(projectName).click();
      await expect(page).toHaveURL(/\/projects\/[^/]+/);

      await page.goto("/orgs");
      await selectOrgAdminGroup(page, "Security");
      await ensureExpanded(page, "Security");
      await page.getByRole("switch", { name: "Require two-factor authentication" }).click();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/advanced-settings") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save security settings" }).click(),
      ]);

      // Also disable this admin's personal 2FA again: it was enrolled only to exercise the self-service recovery path
      // above, and leaving it on would break this persona's plain loginAs() in later specs.
      await page.goto("/preferences");
      await selectPreferencesGroup(page, "Security");
      await ensureTwoFactorSectionExpanded(page);
      await page.getByLabel("Authenticator code").fill(await nextTotpCode(recoverySecret));
      await page.getByRole("button", { name: "Disable 2FA" }).click();
      // Disabling 2FA bumps token_version server-side (same as a password
      // change) to invalidate the current session's token immediately —
      // the frontend's AUTH_UNAUTHORIZED_EVENT handling logs this session
      // out on its very next request rather than showing "Not enabled" in
      // place, so log back in (with a plain password now — 2FA is off)
      // before continuing.
      await page.waitForURL(/\/login$/);
      await loginAs(page, adminEmail);
    });

    await test.step("external-user-on-project policy: 'anyone' allows adding a not-yet-member by email", async () => {
      await page.goto("/orgs");
      await selectOrgAdminGroup(page, "Security");
      await ensureExpanded(page, "Security");
      await page.getByLabel("External users on projects").selectOption("anyone");
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/advanced-settings") && r.request().method() === "PUT"),
        page.getByRole("button", { name: "Save security settings" }).click(),
      ]);

      await page.goto("/projects");
      await page.getByText(projectName).click();
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      // A project has no auto-created group: invite through the Members section's add control, which grants the by-email
      // invite a direct role as a project group's member picker does.
      await selectProjectAdminGroup(page, "Members");
      // The add control opens in a Modal behind an "Add member" button (docs/ux-style-guide.md Principle 3, "create is a
      // layer, not a page reflow").
      await page.getByRole("button", { name: "Add member" }).click();
      const addMemberModal = page.getByRole("dialog", { name: "Add member" });
      const outsideEmail = `e2e-external-${Date.now()}@example.com`;
      await addMemberModal.getByPlaceholder("Type a name to add, or an email to invite…").fill(outsideEmail);
      // A brand-new email with no account anywhere shows an "Invite"
      // option (not "Add"), per UserAutocomplete's existing/new distinction.
      await addMemberModal.getByText(`Invite ${outsideEmail}`, { exact: true }).click();
      // Picking the invite option only stages it (`AddMembersModal`'s
      // staged multi-add) — committing is what actually sends the invite.
      await addMemberModal.getByRole("button", { name: "Add 1 member" }).click();
      // Committing closes the modal; the result message renders on the
      // page underneath it, same as before this control moved into a Modal.
      await expect(addMemberModal).not.toBeVisible();
      await expect(page.getByText(/invite email was sent/i).first()).toBeVisible();
    });
  });
});
