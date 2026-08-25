import { expect, test } from "@playwright/test";

/**
 * Coverage for the mockup-driven engagement features added on top of the
 * Ossa (v1) golden path: comment reactions, per-entity subscriptions, the
 * tabbed Project Admin page, and the Project Overview dashboard charts.
 */

const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "ChangeMe123!";

test("mockup engagement: reactions, subscriptions, admin tabs, dashboard charts", async ({ page }) => {
  const projectName = `Mockup Engagement ${Date.now()}`;

  await test.step("login and create a project", async () => {
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

    // "New project" opens a Modal (style guide "Pattern: modal dialog for
    // entity create/rename") — scoped to it rather than a bare ".card", and
    // its Name/Summary fields are real <label>s now, not placeholder-only
    // (2026-08 UX audit roadmap item 521).
    await page.getByRole("button", { name: "New project" }).click();
    const newProjectDialog = page.getByRole("dialog", { name: "New project" });
    // The org picker only renders at all when the caller belongs to more
    // than one organisation (see ProjectListPage.tsx) — the bootstrap admin
    // used here belongs to exactly one ("Default Organization"), so it's
    // implicit rather than offered as a choice. Select explicitly only if
    // a picker is actually present, so this still works if the admin ever
    // gains a second org membership in some other stack/seed configuration.
    const orgPicker = newProjectDialog.locator("select:has(option:text-is('Default Organization'))");
    if (await orgPicker.count() > 0) {
      await orgPicker.selectOption({ label: "Default Organization" });
    }
    await newProjectDialog.getByLabel("Name", { exact: true }).fill(projectName);
    await newProjectDialog.getByLabel("Summary").fill("Created by Playwright (mockup engagement spec)");
    await newProjectDialog.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
  });

  await test.step("add a component and category via the Structure admin tab", async () => {
    await page.getByText("Project Admin").click();
    // Categories now lives inside the merged "Structure" tab (2026-08 UX
    // audit roadmap: Project Admin's 8 tabs -> 5), alongside a "Project
    // stages" section that also has its own "Name"-placeholder "add stage"
    // field (which would otherwise be `.first()` and silently win) — scope
    // to "Components & categories" specifically.
    await page.getByRole("tab", { name: "Structure" }).click();
    const componentsSection = page.locator(".card", { has: page.getByRole("button", { name: "Components & categories section" }) });
    await componentsSection.getByPlaceholder("Name").first().fill("Web");
    await componentsSection.getByPlaceholder("Prefix").first().fill("WEB");
    await componentsSection.getByRole("button", { name: "New component" }).click();
    // Wait for "Web" (and its own, now-rendered nested "add category" form)
    // before filling it — otherwise the fill can race ahead of the reload
    // and land on the wrong (not-yet-replaced) form.
    await expect(page.locator('input[value="Web"]').first()).toBeVisible();
    // ProjectAdminPage's reload() after a mutation fires 9 requests: 7
    // concurrently, then two more awaited *sequentially* afterwards (org
    // users, report templates) — unrelated to the categories tab, but
    // still part of the same component's state, so each one still
    // triggers a re-render ~150-300ms after "Web" itself first becomes
    // visible (confirmed via a MutationObserver against the real running
    // app), enough to reset whatever's mid-typed into the newly-created
    // component's own "add category" form. Wait for the network to go
    // idle to ride past that settling window before touching the form.
    await page.waitForLoadState("networkidle");
    // The component/category rename UI (each name/prefix rendered as an
    // always-editable input) also means a page-wide getByPlaceholder("Name")
    // is ambiguous once both "Web"'s own "add category" form and the
    // standalone "add component" form exist — scope explicitly to "Web"'s
    // own container (input -> row -> row -> the component's own stack
    // div, three levels up) so this can't cross-hit the wrong form.
    // `:not([placeholder])`: the "add component" row's own Name field
    // shares this same value transiently (not yet cleared) right after
    // creating "Web" — see golden-path.spec.ts's identical guard for the
    // full reasoning (Structure now shares one tab panel with Stages,
    // 2026-08 UX audit roadmap: 8 tabs -> 5).
    const webRow = page.locator('input[value="Web"]:not([placeholder])').locator("xpath=../../..");
    await webRow.getByPlaceholder("Name").fill("Functional");
    await webRow.getByPlaceholder("Prefix").fill("FN");
    await webRow.getByRole("button", { name: "New category" }).click();
    await expect(page.locator('input[value="Functional"]').first()).toBeVisible();
  });

  await test.step("create a requirement and open its card from the card-based list", async () => {
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill("Users can export their data");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText("WEB-FN-001")).toBeVisible();

    await page.getByText("Users can export their data").click();
    await expect(page.getByRole("heading", { name: /WEB-FN-001/ })).toBeVisible();
  });

  await test.step("approve the requirement so a change request can target it later", async () => {
    // A modify change request can only target an already-locked requirement
    // (2026-08 UX audit roadmap, "No requirement approval action; change
    // requests can target draft requirements") — this spec never baselines
    // a stage (unlike golden-path.spec.ts), so approve it directly instead.
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.getByText("Locked (approved)")).toBeVisible();
  });

  await test.step("subscribe to the requirement", async () => {
    await page.getByRole("button", { name: "Subscribe" }).click();
    await expect(page.getByRole("button", { name: "Subscribed" })).toBeVisible();
  });

  await test.step("post a comment and react to it", async () => {
    await page.getByPlaceholder("Add comment").fill("This looks ready for review.");
    await page.getByRole("button", { name: "Add comment", exact: true }).click();
    // Scoped to the posted comment's own card: a page-wide exact "Server
    // Administrator" text match is now ambiguous against both the nav
    // rail's own "Server Administrator" link and the requirement's Change
    // log table, which gained a "Changed by" column showing the same name
    // for the requirement's own creation entry. `.card` is nested (the
    // Discussion section's own card wraps each individual comment's card),
    // so `.last()` picks the innermost, most specific match.
    const postedComment = page.locator(".card", { hasText: "This looks ready for review." }).last();
    await expect(postedComment.getByText("Server Administrator", { exact: true })).toBeVisible();
    await expect(postedComment).toBeVisible();

    const likeButton = page.getByRole("button", { name: "Like this comment" });
    await likeButton.click();
    // Scoped to the like button itself (its reaction count renders inside
    // it) rather than a page-wide "1" text match, which now also matches
    // the notification bell's own unread-count bubble.
    await expect(likeButton).toContainText("1");
  });

  await test.step("raise a change request, subscribe, and comment on it", async () => {
    await page.getByText("Change Requests").click();
    await page.getByRole("button", { name: "New change request" }).click();
    // The create form is a `Modal` portalled to the end of `document.body`
    // — scope to it rather than an unscoped `getByRole("combobox").first()`,
    // which would otherwise resolve to the filter sidebar's own Status
    // select (it precedes the dialog in DOM order once the form is a
    // portal instead of an inline block).
    const dialog = page.getByRole("dialog", { name: "New change request" });
    // The requirement select defaults asynchronously once project data
    // loads — wait so Create doesn't submit with an empty requirement_id.
    await expect(dialog.getByRole("combobox").first()).toContainText("Users can export their data");
    // Modify-requirement CRs are field-toggle driven: a field's proposed
    // value is only editable (and only becomes part of `changed_fields`)
    // once its "Fields to change" checkbox is ticked. Each checkbox and its
    // (once checked) inline editor live in the same field-row container
    // (checkbox -> label -> field-row div), so scope the fill to that row
    // rather than a page-wide input query.
    const nameCheckbox = page.getByRole("checkbox", { name: "Name", exact: true });
    await nameCheckbox.check();
    await nameCheckbox.locator("xpath=../..").locator("input.input").fill("Export as CSV or JSON");
    const reasoningCheckbox = page.getByRole("checkbox", { name: "Reasoning", exact: true });
    await reasoningCheckbox.check();
    await reasoningCheckbox.locator("xpath=../..").locator("textarea.input").fill("Stakeholders want a choice of format");
    await page.getByPlaceholder("Reason for change").fill("Clarifying the export format options");
    await page.getByRole("button", { name: "Create", exact: true }).click();

    await page.getByText("Export as CSV or JSON").click();
    await page.getByRole("button", { name: "Subscribe" }).click();
    await expect(page.getByRole("button", { name: "Subscribed" })).toBeVisible();

    await page.getByPlaceholder("Add comment").fill("Let's default to CSV.");
    await page.getByRole("button", { name: "Add comment", exact: true }).click();
    await expect(page.getByText("Let's default to CSV.")).toBeVisible();
  });

  await test.step("the Project Overview dashboard shows status/CR charts and activity", async () => {
    await page.getByText("Overview").click();
    await expect(page.getByText("Requirements by status")).toBeVisible();
    // Scoped to main: the nav rail's own "Change requests" link (always
    // present alongside this dashboard once a project is selected) exact-
    // matches the same text as this chart's legend label.
    await expect(page.getByRole("main").getByText("Change requests", { exact: true })).toBeVisible();
    await expect(page.getByText("Stage progress")).toBeVisible();
    await expect(page.getByText("Project activity")).toBeVisible();
  });
});
