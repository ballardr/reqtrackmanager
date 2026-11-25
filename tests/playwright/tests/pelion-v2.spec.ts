import { expect, test } from "@playwright/test";

import { addStructureCategory, addStructureComponent, structureRow, deleteOrgOnCleanup, installCleanupHook, selectPreferencesGroup, selectProjectAdminGroup } from "./e2e-workflows/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * End-to-end coverage for the Pelion (v2) feature set, on top of the Ossa (v1) golden path covered by
 * golden-path.spec.ts: a project custom field definition and its value on a requirement, a file attachment
 * upload, an in-app notification (password change), favouriting a project, and creating a new project from a
 * template.
 *
 * The password-change step runs against a disposable org-admin persona this spec creates, not the bootstrap
 * admin@example.com: a try/finally revert cannot protect a shared account's password against a browser crash
 * or worker kill. `admin@example.com` is used here only, read-only, to bootstrap the throwaway org and persona
 * through direct API calls, never to log in through the UI form.
 */

const SERVER_ADMIN_EMAIL = "admin@example.com";
const SERVER_ADMIN_PASSWORD = "ChangeMe123!";
const TEMP_PASSWORD = "TempForE2E123!";
const apiBaseUrl = "http://localhost:8000";

test("Pelion v2 walkthrough: custom fields, attachments, notifications, favourites, templates", async ({ page }) => {
  const templateProjectName = `Pelion Template ${Date.now()}`;
  const clonedProjectName = `Pelion From Template ${Date.now()}`;
  const suffix = Date.now();
  const orgAdminEmail = `pelion-v2-admin-${suffix}@example.com`;
  let orgAdminPassword = "PelionV2Admin123!";

  await test.step("provision a disposable org + org-admin persona for this run", async () => {
    const serverAdminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: SERVER_ADMIN_EMAIL, password: SERVER_ADMIN_PASSWORD },
    });
    const serverAdminToken = (await serverAdminLoginResp.json()).access_token;
    const authHeaders = { Authorization: `Bearer ${serverAdminToken}` };

    const org = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
        headers: authHeaders, data: { name: `Pelion V2 Org ${suffix}` },
      })
    ).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: authHeaders,
      data: {
        email: orgAdminEmail, display_name: "Pelion V2 Admin", password: orgAdminPassword, role: "org_admin",
      },
    });
  });

  await test.step("login", async () => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(orgAdminEmail);
    await page.getByLabel("Password").fill(orgAdminPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    // The post-login landing depends on the admin's landing_preference (U-U-03: "auto" goes straight to the
    // sole accessible project), so the spec navigates explicitly rather than asserting a destination.
    await page.waitForURL(/\/projects(\/|$)/);
    await page.goto("/projects");
    // ProjectListPage's org list (behind the org picker) loads after mount, separately from the "Name"/"Summary"
    // inputs, so clicking "New project" too soon can see zero orgs; settle network activity first.
    await page.waitForLoadState("networkidle");
  });

  await test.step("create the project that will become a template", async () => {
    // "New project" opens a Modal (style guide "Pattern: modal dialog for entity create/rename"); the fields
    // are scoped to it and found by their `<label>`s.
    await page.getByRole("button", { name: "New project" }).click();
    const newProjectDialog = page.getByRole("dialog", { name: "New project" });
    await newProjectDialog.getByLabel("Name", { exact: true }).waitFor();
    // The org picker renders only for a caller in more than one organisation, so it is selected only when present.
    // `newOrgId` defaults to whichever org sorts first, so an untouched picker could create the template project
    // under the wrong org and break the "create from template" step, which offers only the selected org's templates.
    const orgPicker = newProjectDialog.locator("select:has(option:text-is('Default Organization'))");
    if (await orgPicker.count() > 0) {
      await orgPicker.selectOption({ label: "Default Organization" });
    }
    await newProjectDialog.getByLabel("Name", { exact: true }).fill(templateProjectName);
    await newProjectDialog.getByLabel("Summary").fill("Created by Playwright (Pelion v2 spec)");
    await newProjectDialog.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: templateProjectName })).toBeVisible();
  });

  await test.step("add component, category, and a custom field, then mark as template", async () => {
    await page.getByText("Project Admin").click();

    // Categories sits in the merged "Structure" tab beside a "Project stages" section with its own
    // "Name"-placeholder field, so the query is scoped to "Components & categories".
    await selectProjectAdminGroup(page, "Structure");
    await addStructureComponent(page, "Software", "SW");
    await addStructureCategory(page, "Software", "Performance", "PERF");
    await expect(structureRow(page, "Performance")).toBeVisible();

    // Custom fields sit in the merged "Fields & actions" group.
    await selectProjectAdminGroup(page, "Fields & actions");
    await page.getByRole("button", { name: "New field" }).click();
    const fieldDialog = page.getByRole("dialog", { name: "New field" });
    await fieldDialog.getByLabel("Field name", { exact: true }).fill("Priority");
    await fieldDialog.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByText("Priority").first()).toBeVisible();

    await selectProjectAdminGroup(page, "Project settings");
    await page.getByRole("checkbox", { name: "Usable as a project template" }).check();
    await page.getByRole("button", { name: "Save settings" }).click();
  });

  await test.step("create a requirement with a custom field value", async () => {
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill("Ship the widget");
    await page.getByLabel("Priority").fill("High");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText(/^(\S+-)?SW-PERF-001$/)).toBeVisible();

    await page.getByText("Ship the widget").click();
    await expect(page.getByLabel("Priority")).toHaveValue("High");
  });

  await test.step("upload a file attachment to the requirement", async () => {
    // Scoped to the requirement's "Attachments" card: the comment thread's compose box (CommentThread.tsx) has
    // its own always-present file input for staging a comment attachment, so a page-wide input[type="file"] is ambiguous.
    const attachmentsCard = page.locator(".card", { has: page.getByRole("heading", { name: "Attachments" }) });
    await attachmentsCard.locator('input[type="file"]').setInputFiles({
      name: "notes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Playwright attachment test"),
    });
    await expect(page.getByText("notes.txt")).toBeVisible();
  });

  await test.step("change password triggers an in-app notification, then revert it", async () => {
    // Changing the password bumps User.token_version, invalidating the current token, so the frontend logs out and
    // redirects to /login. The try/finally starts before the forward change: once `changeResponse.ok()` is true
    // the mutation is committed, so a failure anywhere after it (including `waitForURL`) must still revert.
    try {
      await page.getByTitle("Preferences").click();
      await selectPreferencesGroup(page, "Security");
      await page.getByLabel("Current password").fill(orgAdminPassword);
      await page.getByLabel("New password").fill(TEMP_PASSWORD);
      const changeResponsePromise = page.waitForResponse(
        (resp) => resp.url().includes("/api/v1/auth/change-password") && resp.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Change password", exact: true }).click();
      const changeResponse = await changeResponsePromise;
      expect(changeResponse.ok()).toBe(true);
      await page.waitForURL(/\/login$/);

      // Log back in with the new password to pick up a fresh session and
      // confirm the change-password notification was created.
      await page.getByLabel("Email").fill(orgAdminEmail);
      await page.getByLabel("Password").fill(TEMP_PASSWORD);
      await page.getByRole("button", { name: "Sign in" }).click();
      await page.waitForURL(/\/projects(\/|$)/);
      await page.getByTitle("Notifications").click();
      await expect(page.getByText("Your password was changed").first()).toBeVisible();
      await page.getByTitle("Notifications").click();
    } finally {
      // Revert through the UI, as the forward change did. This invalidates the TEMP_PASSWORD session, so log back
      // in with the original password afterwards to leave this persona usable for the rest of this spec.
      await page.getByTitle("Preferences").click();
      await selectPreferencesGroup(page, "Security");
      await page.getByLabel("Current password").fill(TEMP_PASSWORD);
      await page.getByLabel("New password").fill(orgAdminPassword);
      const revertResponsePromise = page.waitForResponse(
        (resp) => resp.url().includes("/api/v1/auth/change-password") && resp.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Change password", exact: true }).click();
      const revertResponse = await revertResponsePromise;
      expect(revertResponse.ok()).toBe(true);
      await page.waitForURL(/\/login$/);

      await page.getByLabel("Email").fill(orgAdminEmail);
      await page.getByLabel("Password").fill(orgAdminPassword);
      await page.getByRole("button", { name: "Sign in" }).click();
      await page.waitForURL(/\/projects(\/|$)/);
    }
  });

  await test.step("favourite the project and confirm it sorts first", async () => {
    // Clear any favourites left over from earlier runs of this same spec
    // first, so the "sorts first" assertion below is deterministic
    // regardless of how many times this spec has run against this stack.
    const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
    const authHeaders = { Authorization: `Bearer ${token}` };
    const existingProjects = await (
      await page.request.get(`${apiBaseUrl}/api/v1/projects?archived=false`, { headers: authHeaders })
    ).json();
    for (const project of existingProjects) {
      if (project.is_favorite) {
        await page.request.delete(`${apiBaseUrl}/api/v1/projects/${project.id}/favorite`, { headers: authHeaders });
      }
    }

    // A role-scoped locator, not getByText: after the password-change step's re-login the admin may land on the
    // /projects overview, whose <h1> also reads "Projects", making a plain text match ambiguous with this nav link.
    await page.getByRole("link", { name: "Projects", exact: true }).click();
    await expect(page).toHaveURL(/\/projects$/);
    // Same reasoning as the login step's wait above — settle this fresh
    // ProjectListPage mount's org fetch before the org-picker-dependent
    // "create a new project from the template" step below.
    await page.waitForLoadState("networkidle");

    // The project is a template, which the list leaves out until "Show templates" is ticked.
    await page.getByRole("checkbox", { name: "Show templates" }).check();
    const card = page.locator("main .card", { hasText: templateProjectName });
    await card.getByRole("button", { name: "Favourite" }).click();
    await expect(card.getByRole("button", { name: "Remove from favourites" })).toBeVisible();
    await expect(page.locator("main .card").first()).toContainText(templateProjectName);
  });

  await test.step("create a new project from the template and verify configuration was copied", async () => {
    // "New project" opens a Modal — scoped to it, and its Name/Summary
    // fields are real <label>s now, not placeholder-only.
    await page.getByRole("button", { name: "New project" }).click();
    const newProjectDialog = page.getByRole("dialog", { name: "New project" });
    await newProjectDialog.getByLabel("Name", { exact: true }).waitFor();
    // The template dropdown lists only templates of the selected org, so the same org the template project was
    // created under must be selected (see the org picker in the "create the project that will become a template"
    // step above).
    const orgPicker = newProjectDialog.locator("select:has(option:text-is('Default Organization'))");
    if (await orgPicker.count() > 0) {
      await orgPicker.selectOption({ label: "Default Organization" });
    }
    await newProjectDialog.getByLabel("Name", { exact: true }).fill(clonedProjectName);
    await newProjectDialog.getByLabel("Summary").fill("Cloned by Playwright (Pelion v2 spec)");
    await expect(newProjectDialog.getByLabel("Create from template")).toContainText(templateProjectName);
    await newProjectDialog.getByLabel("Create from template").selectOption({ label: templateProjectName });
    await newProjectDialog.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: clonedProjectName })).toBeVisible();

    await page.getByText("Project Admin").click();
    await selectProjectAdminGroup(page, "Structure");
    await expect(structureRow(page, "Software")).toBeVisible();
    await selectProjectAdminGroup(page, "Fields & actions");
    await expect(page.getByText("Priority").first()).toBeVisible();
  });
});
