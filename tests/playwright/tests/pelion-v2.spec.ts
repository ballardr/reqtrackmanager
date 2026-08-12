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
    // The org picker only renders at all when the caller belongs to more
    // than one organisation (see ProjectListPage.tsx) — the bootstrap admin
    // used here belongs to exactly one ("Default Organization"), so it's
    // implicit rather than offered as a choice. Select explicitly only if
    // a picker is actually present, so this still works if the admin ever
    // gains a second org membership in some other stack/seed configuration.
    const orgPicker = page.locator("select:has(option:text-is('Default Organization'))");
    if (await orgPicker.count() > 0) {
      await orgPicker.selectOption({ label: "Default Organization" });
    }
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
    await expect(page.locator('input[value="Software"]').first()).toBeVisible();
    // ProjectAdminPage's reload() after a mutation fires 9 requests: 7
    // concurrently, then two more awaited *sequentially* afterwards (org
    // users, report templates) — unrelated to the categories tab, but
    // still part of the same component's state, so each one still
    // triggers a re-render ~150-300ms after "Software" itself first
    // becomes visible (confirmed via a MutationObserver against the real
    // running app), enough to reset whatever's mid-typed into the
    // newly-created component's own "add category" form. Wait for the
    // network to go idle to ride past that settling window before
    // touching the form.
    await page.waitForLoadState("networkidle");

    // The component/category rename UI (each name/prefix rendered as an
    // always-editable input) also means a page-wide getByPlaceholder("Name")
    // is ambiguous once both "Software"'s own "add category" form and the
    // standalone "add component" form exist — scope explicitly to
    // "Software"'s own container (input -> row -> row -> the component's
    // own stack div, three levels up) so this can't cross-hit the wrong
    // form.
    const softwareRow = page.locator('input[value="Software"]').locator("xpath=../../..");
    await softwareRow.getByPlaceholder("Name").fill("Performance");
    await softwareRow.getByPlaceholder("Prefix").fill("PERF");
    await softwareRow.getByRole("button", { name: "New category" }).click();
    await expect(page.locator('input[value="Performance"]').first()).toBeVisible();

    await page.getByRole("button", { name: "Custom fields" }).click();
    await page.getByPlaceholder("Field name").fill("Priority");
    await page.getByRole("button", { name: "New field" }).click();
    await expect(page.getByText("Priority").first()).toBeVisible();

    await page.getByRole("button", { name: "Project settings" }).click();
    await page.getByRole("checkbox", { name: "Usable as a project template" }).check();
    await page.getByRole("button", { name: "Save settings" }).click();
  });

  await test.step("create a requirement with a custom field value", async () => {
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill("Ship the widget");
    await page.getByLabel("Priority").fill("High");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText("SW-PERF-001")).toBeVisible();

    await page.getByText("Ship the widget").click();
    await expect(page.getByLabel("Priority")).toHaveValue("High");
  });

  await test.step("upload a file attachment to the requirement", async () => {
    // Scoped to the requirement's own "Attachments" card: the comment
    // thread's compose box (CommentThread.tsx) now also renders its own
    // always-present file input for staging a comment attachment, so a
    // page-wide input[type="file"] is ambiguous between the two.
    const attachmentsCard = page.locator(".card", { has: page.getByRole("heading", { name: "Attachments" }) });
    await attachmentsCard.locator('input[type="file"]').setInputFiles({
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
    await page.getByRole("button", { name: "Security", exact: true }).click();
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
      await page.getByRole("button", { name: "Security", exact: true }).click();
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
    // The template dropdown only lists templates belonging to the
    // currently-selected org. The org picker itself only renders when the
    // caller belongs to more than one organisation (see ProjectListPage.tsx)
    // — the bootstrap admin used here belongs to exactly one ("Default
    // Organization"), which is auto-selected as soon as it's the only
    // option, so the template project created above is still on offer
    // without needing to select it explicitly. Select explicitly only if a
    // picker is actually present, so this still works if the admin ever
    // gains a second org membership in some other stack/seed configuration.
    const orgPicker = page.locator("select:has(option:text-is('Default Organization'))");
    if (await orgPicker.count() > 0) {
      await orgPicker.selectOption({ label: "Default Organization" });
    }
    await page.getByPlaceholder("Name").fill(clonedProjectName);
    await page.getByPlaceholder("Summary").fill("Cloned by Playwright (Pelion v2 spec)");
    await expect(page.getByLabel("Create from template")).toContainText(templateProjectName);
    await page.getByLabel("Create from template").selectOption({ label: templateProjectName });
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: clonedProjectName })).toBeVisible();

    await page.getByText("Project Admin").click();
    await page.getByRole("button", { name: "Categories" }).click();
    await expect(page.locator('input[value="Software"]').first()).toBeVisible();
    await page.getByRole("button", { name: "Custom fields" }).click();
    await expect(page.getByText("Priority").first()).toBeVisible();
  });
});
