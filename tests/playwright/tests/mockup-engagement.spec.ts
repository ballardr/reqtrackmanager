import { expect, test } from "@playwright/test";

import { addStructureCategory, addStructureComponent, structureRow, approveRequirementFromDetail, chooseRecordAction, selectProjectAdminGroup, recordCodeText, expectRecordLocked } from "./e2e-workflows/helpers";

/**
 * Mockup-driven engagement features on top of the golden path: comment reactions, per-entity
 * subscriptions, the resource-menu Project Admin page and the Project Overview dashboard charts.
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
    // The post-login landing depends on the admin's landing_preference (U-U-03: "auto" goes straight to the
    // sole accessible project), so the spec navigates explicitly rather than asserting a destination.
    await page.waitForURL(/\/projects(\/|$)/);
    await page.goto("/projects");

    // "New project" opens a Modal (style guide "Pattern: modal dialog for entity create/rename"); the fields
    // are scoped to it and found by their `<label>`s.
    await page.getByRole("button", { name: "New project" }).click();
    const newProjectDialog = page.getByRole("dialog", { name: "New project" });
    // The org picker renders only when the caller belongs to more than one organisation; the bootstrap admin
    // belongs to one, so it is selected only when a picker is present.
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
    // Categories sits in the merged "Structure" tab beside a "Project stages" section with its own
    // "Name"-placeholder field that `.first()` would pick, so the query is scoped to "Components & categories".
    await selectProjectAdminGroup(page, "Structure");
    await addStructureComponent(page, "Web", "WEB");
    await addStructureCategory(page, "Web", "Functional", "FN");
    await expect(structureRow(page, "Functional")).toBeVisible();
  });

  await test.step("create a requirement and open its card from the card-based list", async () => {
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill("Users can export their data");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText(/^(\w+-)?WEB-FN-001$/)).toBeVisible();

    await page.getByText("Users can export their data").click();
    await expect(page.locator(".record-header").getByText(recordCodeText("WEB-FN-001"))).toBeVisible();
  });

  await test.step("approve the requirement so a change request can target it later", async () => {
    // A modify change request can only target an already-locked requirement
    // — this spec never baselines
    // a stage (unlike golden-path.spec.ts), so approve it directly instead.
    await approveRequirementFromDetail(page);
    await expectRecordLocked(page);
  });

  await test.step("subscribe to the requirement", async () => {
    await chooseRecordAction(page, "Requirement", "Subscribe");
    await expect(page.getByText("Subscribed", { exact: true })).toBeVisible();
  });

  await test.step("post a comment and react to it", async () => {
    await page.getByPlaceholder("Add comment").fill("This looks ready for review.");
    await page.getByRole("button", { name: "Add comment", exact: true }).click();
    // Scoped to the posted comment's own row: an exact "Server Administrator" text match is ambiguous against
    // the nav rail link and the requirement's Change log "Changed by" column.
    const postedComment = page.locator(".comment-row", { hasText: "This looks ready for review." });
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
    // The create form is a `Modal` portalled to the end of `document.body`, so it is scoped by dialog rather
    // than `getByRole("combobox").first()`, which would resolve to the filter sidebar's Status select.
    const dialog = page.getByRole("dialog", { name: "New change request" });
    // The requirement select defaults asynchronously once project data
    // loads — wait so Create doesn't submit with an empty requirement_id.
    await expect(dialog.getByRole("combobox").first()).toContainText("Users can export their data");
    // Modify-requirement change requests are field-toggle driven: a field's proposed value is editable (and
    // part of `changed_fields`) only once its "Fields to change" checkbox is ticked. The checkbox and its
    // inline editor share a field-row container, so the fill is scoped to that row.
    const nameCheckbox = page.getByRole("checkbox", { name: "Name", exact: true });
    await nameCheckbox.check();
    await nameCheckbox.locator("xpath=../..").locator("input.input").fill("Export as CSV or JSON");
    const reasoningCheckbox = page.getByRole("checkbox", { name: "Reasoning", exact: true });
    await reasoningCheckbox.check();
    await reasoningCheckbox.locator("xpath=../..").locator("textarea.input").fill("Stakeholders want a choice of format");
    await page.getByLabel("Reason for change").fill("Clarifying the export format options");
    await page.getByRole("button", { name: "Create", exact: true }).click();

    await page.getByText("Export as CSV or JSON").click();
    await chooseRecordAction(page, "Change request", "Subscribe");
    await expect(page.getByText("Subscribed", { exact: true })).toBeVisible();

    await page.getByPlaceholder("Add comment").fill("Let's default to CSV.");
    await page.getByRole("button", { name: "Add comment", exact: true }).click();
    await expect(page.getByText("Let's default to CSV.")).toBeVisible();
  });

  await test.step("the Project Overview dashboard shows status/CR charts and activity", async () => {
    // Not a bare `getByText("Overview")`: it matches by case-insensitive substring, so the nav rail's
    // "Organisation overview" link also resolves. Scope to the project-level link's exact accessible name.
    await page.getByRole("link", { name: "Overview", exact: true }).click();
    await expect(page.getByText("Requirements by status")).toBeVisible();
    // Scoped to main and to the chart's title: the nav rail's own "Change requests"
    // link and the total-records chart's "Change requests" legend button exact-match
    // the same text.
    await expect(page.getByRole("main").locator("div.text-muted").filter({ hasText: /^Change requests$/ })).toBeVisible();
    await expect(page.getByText("Stage progress")).toBeVisible();
    await expect(page.getByText("Project activity")).toBeVisible();
  });
});
