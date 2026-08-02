import { expect, test } from "@playwright/test";

/**
 * End-to-end coverage for the Pelion (v2) feature set, on top of the Ossa
 * (v1) golden path already covered by golden-path.spec.ts: a project
 * custom field definition and its value on a requirement, a file
 * attachment upload, an in-app notification (password change), favouriting
 * a project, and creating a new project from a template.
 *
 * The password-change step restores the original admin password before the
 * test ends, since golden-path.spec.ts's login step depends on the fixed
 * ADMIN_PASSWORD below staying valid across runs.
 */

const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "ChangeMe123!";
const TEMP_PASSWORD = "TempForE2E123!";
const apiBaseUrl = "http://localhost:8000";

test("Pelion v2 walkthrough: custom fields, attachments, notifications, favourites, templates", async ({ page }) => {
  const templateProjectName = `Pelion Template ${Date.now()}`;
  const clonedProjectName = `Pelion From Template ${Date.now()}`;

  await test.step("login", async () => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(ADMIN_EMAIL);
    await page.getByLabel("Password").fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    // Post-login landing depends on the admin's landing_preference (U-U-03:
    // "auto" goes straight to the sole accessible project instead of the
    // overview list once there's exactly one) — navigate explicitly rather
    // than asserting a specific destination, since that's not what this
    // spec is testing.
    await page.waitForURL(/\/projects(\/|$)/);
    await page.goto("/projects");
  });

  await test.step("create the project that will become a template", async () => {
    await page.getByRole("button", { name: "New project" }).click();
    await page.getByPlaceholder("Name").fill(templateProjectName);
    await page.getByPlaceholder("Summary").fill("Created by Playwright (Pelion v2 spec)");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: templateProjectName })).toBeVisible();
  });

  await test.step("add component, category, and a custom field, then mark as template", async () => {
    await page.getByText("Project Admin").click();

    await page.getByRole("button", { name: "Categories" }).click();
    await page.getByPlaceholder("Name").first().fill("Software");
    await page.getByPlaceholder("Prefix").first().fill("SW");
    await page.getByRole("button", { name: "New component" }).click();
    await expect(page.getByText("Software").first()).toBeVisible();

    await page.getByPlaceholder("Name").nth(1).fill("Performance");
    await page.getByPlaceholder("Prefix").nth(1).fill("PERF");
    await page.getByRole("button", { name: "New category" }).click();
    await expect(page.getByText("Performance").first()).toBeVisible();

    await page.getByRole("button", { name: "Custom fields" }).click();
    await page.getByPlaceholder("Field name").fill("Priority");
    await page.getByRole("button", { name: "New field" }).click();
    await expect(page.getByText("Priority").first()).toBeVisible();

    await page.getByRole("button", { name: "Project settings" }).click();
    await page.getByRole("checkbox", { name: "Usable as a project template" }).check();
    await page.getByRole("button", { name: "Save settings" }).click();
  });

  await test.step("create a requirement with a custom field value", async () => {
    await page.getByText("Requirements").click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill("Ship the widget");
    await page.getByLabel("Priority").fill("High");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText("SW-PERF-001")).toBeVisible();

    await page.getByText("Ship the widget").click();
    await expect(page.getByLabel("Priority")).toHaveValue("High");
  });

  await test.step("upload a file attachment to the requirement", async () => {
    await page.locator('input[type="file"]').setInputFiles({
      name: "notes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Playwright attachment test"),
    });
    await expect(page.getByText("notes.txt")).toBeVisible();
  });

  await test.step("change password triggers an in-app notification, then revert it", async () => {
    // Changing the password bumps User.token_version, which deliberately
    // invalidates the session's own current token (a stolen token must not
    // keep working after the legitimate user "locks out" that session by
    // changing credentials) — the frontend responds by logging the user out
    // and redirecting to /login. Wrapped in try/finally: golden-path.spec.ts's
    // login step depends on ADMIN_PASSWORD staying valid across runs, so the
    // revert (and re-login as ADMIN_PASSWORD) must happen even if the
    // notification assertion below fails.
    await page.getByTitle("Preferences").click();
    await page.getByPlaceholder("Current password").fill(ADMIN_PASSWORD);
    await page.getByPlaceholder("New password").fill(TEMP_PASSWORD);
    const changeResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/api/v1/auth/change-password") && resp.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Change password", exact: true }).click();
    const changeResponse = await changeResponsePromise;
    expect(changeResponse.ok()).toBe(true);
    await page.waitForURL(/\/login$/);

    try {
      // Log back in with the new password to pick up a fresh session and
      // confirm the change-password notification was created.
      await page.getByLabel("Email").fill(ADMIN_EMAIL);
      await page.getByLabel("Password").fill(TEMP_PASSWORD);
      await page.getByRole("button", { name: "Sign in" }).click();
      await page.waitForURL(/\/projects(\/|$)/);
      await page.getByTitle("Notifications").click();
      await expect(page.getByText("Your password was changed").first()).toBeVisible();
      await page.getByTitle("Notifications").click();
    } finally {
      // Revert through the UI, same as the forward change above. This also
      // invalidates the TEMP_PASSWORD session, so log back in as
      // ADMIN_PASSWORD afterwards to leave the shared admin account usable
      // for the rest of this spec and every other spec that logs in with it.
      await page.getByTitle("Preferences").click();
      await page.getByPlaceholder("Current password").fill(TEMP_PASSWORD);
      await page.getByPlaceholder("New password").fill(ADMIN_PASSWORD);
      const revertResponsePromise = page.waitForResponse(
        (resp) => resp.url().includes("/api/v1/auth/change-password") && resp.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Change password", exact: true }).click();
      const revertResponse = await revertResponsePromise;
      expect(revertResponse.ok()).toBe(true);
      await page.waitForURL(/\/login$/);

      await page.getByLabel("Email").fill(ADMIN_EMAIL);
      await page.getByLabel("Password").fill(ADMIN_PASSWORD);
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

    // A role-scoped locator, not getByText: after the password-change step's
    // re-login, the admin may already land on the /projects overview (whose
    // <h1> also reads "Projects"), which would make a plain text match
    // ambiguous between that heading and this nav link.
    await page.getByRole("link", { name: "Projects", exact: true }).click();
    await expect(page).toHaveURL(/\/projects$/);

    const card = page.locator("main .card", { hasText: templateProjectName });
    await card.getByRole("button", { name: "Favourite" }).click();
    await expect(card.getByRole("button", { name: "Remove from favourites" })).toBeVisible();
    await expect(page.locator("main .card").first()).toContainText(templateProjectName);
  });

  await test.step("create a new project from the template and verify configuration was copied", async () => {
    await page.getByRole("button", { name: "New project" }).click();
    await page.getByPlaceholder("Name").fill(clonedProjectName);
    await page.getByPlaceholder("Summary").fill("Cloned by Playwright (Pelion v2 spec)");
    await page.getByLabel("Create from template").selectOption({ label: templateProjectName });
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: clonedProjectName })).toBeVisible();

    await page.getByText("Project Admin").click();
    await page.getByRole("button", { name: "Categories" }).click();
    await expect(page.getByText("Software").first()).toBeVisible();
    await page.getByRole("button", { name: "Custom fields" }).click();
    await expect(page.getByText("Priority").first()).toBeVisible();
  });
});
