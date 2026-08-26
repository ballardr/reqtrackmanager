import { expect, test } from "@playwright/test";

/**
 * End-to-end coverage for the Pelion (v2) feature set, on top of the Ossa
 * (v1) golden path already covered by golden-path.spec.ts: a project
 * custom field definition and its value on a requirement, a file
 * attachment upload, an in-app notification (password change), favouriting
 * a project, and creating a new project from a template.
 *
 * The password-change step runs against a disposable org-admin persona this
 * spec creates for itself, not the real bootstrap admin@example.com — a
 * change this test's own diff had to make (see docs/decisions.md), since an
 * earlier version changed that shared account's actual password mid-test.
 * Its try/finally revert had a real gap (the redirect-to-/login wait
 * between the forward change and the try block wasn't covered — a flake
 * there left the change committed with no revert ever attempted), and even
 * a gap-free try/finally would still leave the same account's password
 * hostage to a browser crash or worker kill. `admin@example.com` is only
 * ever used here, read-only, to bootstrap this spec's own throwaway
 * org/persona via direct API calls — never to log in through the UI form,
 * so this spec can never itself change that account's real password.
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
    // Post-login landing depends on the admin's landing_preference (U-U-03:
    // "auto" goes straight to the sole accessible project instead of the
    // overview list once there's exactly one) — navigate explicitly rather
    // than asserting a specific destination, since that's not what this
    // spec is testing.
    await page.waitForURL(/\/projects(\/|$)/);
    await page.goto("/projects");
    // ProjectListPage's own org list (which the "New project" form's org
    // picker depends on — see the next step) loads asynchronously after
    // mount, separately from the "Name"/"Summary" inputs that render
    // unconditionally and immediately once the form opens. Waiting for the
    // Name input alone doesn't wait for that org fetch, so clicking "New
    // project" too soon after this navigation can see zero orgs loaded yet
    // (the picker correctly absent at that instant) even though a picker
    // will exist moments later — settle network activity first.
    await page.waitForLoadState("networkidle");
  });

  await test.step("create the project that will become a template", async () => {
    // "New project" opens a Modal (style guide "Pattern: modal dialog for
    // entity create/rename") — scoped to it rather than the old bare-".card"
    // xpath-ancestor climb, and its Name/Summary fields are real <label>s
    // now, not placeholder-only (2026-08 UX audit roadmap item 521).
    await page.getByRole("button", { name: "New project" }).click();
    const newProjectDialog = page.getByRole("dialog", { name: "New project" });
    await newProjectDialog.getByLabel("Name", { exact: true }).waitFor();
    // The org picker only renders at all when the caller belongs to more
    // than one organisation (see ProjectListPage.tsx) — select explicitly
    // only if a picker is actually present, so this still works whether the
    // bootstrap admin belongs to exactly one org or several (e.g. seeded
    // orgs the admin API-created directly, which grants the creator
    // membership). Explicit selection matters as soon as a picker exists:
    // ProjectListPage defaults `newOrgId` to whichever org happens to sort
    // first, not specifically "Default Organization", so leaving the
    // picker untouched when it's present could create this template
    // project under the wrong org and silently break the "create from
    // template" step below (which only offers templates belonging to
    // whichever org it explicitly selects).
    const orgPicker = newProjectDialog.locator("select:has(option:text-is('Default Organization'))");
    if (await orgPicker.count() > 0) {
      await orgPicker.selectOption({ label: "Default Organization" });
    }
    await newProjectDialog.getByLabel("Name", { exact: true }).fill(templateProjectName);
    await newProjectDialog.getByLabel("Summary").fill("Created by Playwright (Pelion v2 spec)");
    await newProjectDialog.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: templateProjectName })).toBeVisible();
  });

  await test.step("add component, category, and a custom field, then mark as template", async () => {
    await page.getByText("Project Admin").click();

    // Categories now lives inside the merged "Structure" tab (2026-08 UX
    // audit roadmap: Project Admin's 8 tabs -> 5), alongside a "Project
    // stages" section that also has its own "Name"-placeholder "add stage"
    // field — scope to "Components & categories" specifically.
    await page.getByRole("tab", { name: "Structure" }).click();
    const componentsSection = page.locator(".card", { has: page.getByRole("button", { name: "Components & categories section" }) });
    await componentsSection.getByPlaceholder("Name").first().fill("Software");
    await componentsSection.getByPlaceholder("Prefix").first().fill("SW");
    await componentsSection.getByRole("button", { name: "New component" }).click();
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
    // `:not([placeholder])`: see golden-path.spec.ts's identical guard —
    // the "add component" row's own Name field transiently shares this
    // value right after creating "Software", which would otherwise let
    // the xpath ancestor climb escape up to the shared "Structure" tab
    // panel (Stages + Components & categories, 2026-08 UX audit roadmap:
    // 8 tabs -> 5) and pick up Stages' own "Name" field too.
    const softwareRow = page.locator('input[value="Software"]:not([placeholder])').locator("xpath=../../..");
    await softwareRow.getByPlaceholder("Name").fill("Performance");
    await softwareRow.getByPlaceholder("Prefix").fill("PERF");
    // The comment above describes *two* waves in this same reload()
    // cascade — 7 requests concurrently, then 2 more awaited sequentially
    // afterwards — and the first `waitForLoadState("networkidle")` above
    // can resolve during the brief gap between those waves, not only after
    // both. A real run caught this exact gap: "Prefix" (filled last)
    // survived, but "Name" (filled first) had been silently reset back to
    // empty by the second wave's re-render, leaving "New category"
    // permanently disabled. Wait for the network to settle a second time,
    // and only re-fill whichever field actually got wiped, rather than
    // assuming which one (if either) was hit.
    await page.waitForLoadState("networkidle");
    if ((await softwareRow.getByPlaceholder("Name").inputValue()) !== "Performance") {
      await softwareRow.getByPlaceholder("Name").fill("Performance");
    }
    if ((await softwareRow.getByPlaceholder("Prefix").inputValue()) !== "PERF") {
      await softwareRow.getByPlaceholder("Prefix").fill("PERF");
    }
    await softwareRow.getByRole("button", { name: "New category" }).click();
    await expect(page.locator('input[value="Performance"]').first()).toBeVisible();

    // Custom fields now lives inside the merged "Fields & actions" tab.
    await page.getByRole("tab", { name: "Fields & actions" }).click();
    await page.getByPlaceholder("Field name").fill("Priority");
    await page.getByRole("button", { name: "New field" }).click();
    await expect(page.getByText("Priority").first()).toBeVisible();

    await page.getByRole("tab", { name: "Project settings" }).click();
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
    // and redirecting to /login. This account is this spec's own disposable
    // persona (not the real bootstrap admin@example.com — see this file's
    // header comment for why), so a stuck temp password here only strands a
    // throwaway login, not the one this repo's developers use daily.
    // Wrapped in try/finally regardless, starting *before* the forward
    // change itself (not just around the re-login+notification-check that
    // follows it): once `changeResponse.ok()` is true the mutation has
    // already committed server-side, so a failure anywhere after that —
    // including the very next `waitForURL` — must still trigger the revert.
    // An earlier version of this test drew the try boundary after that
    // waitForURL, missing exactly that window.
    try {
      await page.getByTitle("Preferences").click();
      await page.getByRole("tab", { name: "Security", exact: true }).click();
      await page.getByPlaceholder("Current password").fill(orgAdminPassword);
      await page.getByPlaceholder("New password").fill(TEMP_PASSWORD);
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
      // Revert through the UI, same as the forward change above. This also
      // invalidates the TEMP_PASSWORD session, so log back in with the
      // original password afterwards to leave this persona usable for the
      // rest of this spec.
      await page.getByTitle("Preferences").click();
      await page.getByRole("tab", { name: "Security", exact: true }).click();
      await page.getByPlaceholder("Current password").fill(TEMP_PASSWORD);
      await page.getByPlaceholder("New password").fill(orgAdminPassword);
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

    // A role-scoped locator, not getByText: after the password-change step's
    // re-login, the admin may already land on the /projects overview (whose
    // <h1> also reads "Projects"), which would make a plain text match
    // ambiguous between that heading and this nav link.
    await page.getByRole("link", { name: "Projects", exact: true }).click();
    await expect(page).toHaveURL(/\/projects$/);
    // Same reasoning as the login step's wait above — settle this fresh
    // ProjectListPage mount's org fetch before the org-picker-dependent
    // "create a new project from the template" step below.
    await page.waitForLoadState("networkidle");

    const card = page.locator("main .card", { hasText: templateProjectName });
    await card.getByRole("button", { name: "Favourite" }).click();
    await expect(card.getByRole("button", { name: "Remove from favourites" })).toBeVisible();
    await expect(page.locator("main .card").first()).toContainText(templateProjectName);
  });

  await test.step("create a new project from the template and verify configuration was copied", async () => {
    // "New project" opens a Modal — scoped to it, and its Name/Summary
    // fields are real <label>s now, not placeholder-only (2026-08 UX audit
    // roadmap item 521).
    await page.getByRole("button", { name: "New project" }).click();
    const newProjectDialog = page.getByRole("dialog", { name: "New project" });
    await newProjectDialog.getByLabel("Name", { exact: true }).waitFor();
    // The template dropdown only lists templates belonging to the
    // currently-selected org — must explicitly select the same org the
    // template project above was created under (see the identical picker
    // in the "create the project that will become a template" step above
    // for the full reasoning on why this can't be left implicit).
    const orgPicker = newProjectDialog.locator("select:has(option:text-is('Default Organization'))");
    if (await orgPicker.count() > 0) {
      await orgPicker.selectOption({ label: "Default Organization" });
    }
    await newProjectDialog.getByLabel("Name", { exact: true }).fill(clonedProjectName);
    await newProjectDialog.getByLabel("Summary").fill("Cloned by Playwright (Pelion v2 spec)");
    await expect(newProjectDialog.getByLabel("Create from template")).toContainText(templateProjectName);
    await newProjectDialog.getByLabel("Create from template").selectOption({ label: templateProjectName });
    await newProjectDialog.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: clonedProjectName })).toBeVisible();

    await page.getByText("Project Admin").click();
    await page.getByRole("tab", { name: "Structure" }).click();
    await expect(page.locator('input[value="Software"]').first()).toBeVisible();
    await page.getByRole("tab", { name: "Fields & actions" }).click();
    await expect(page.getByText("Priority").first()).toBeVisible();
  });
});
