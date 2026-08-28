import { expect, test } from "@playwright/test";

import { selectProjectAdminGroup } from "./e2e-workflows/helpers";

/**
 * End-to-end golden path against the running tests/container/docker-compose.yml stack:
 * login -> create project -> add component/category -> add requirement ->
 * approve stage (baseline + lock) -> raise & approve a change request ->
 * generate a PDF report -> toggle dark/light theme.
 */

const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "ChangeMe123!";

test("full requirements lifecycle through the UI", async ({ page }) => {
  const projectName = `E2E Project ${Date.now()}`;

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

  await test.step("create project", async () => {
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
    await newProjectDialog.getByLabel("Summary").fill("Created by Playwright");
    await newProjectDialog.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
  });

  await test.step("add component and category", async () => {
    await page.getByText("Project Admin").click();
    // Categories now lives inside the merged "Structure" tab (2026-08 UX
    // audit roadmap: Project Admin's 8 tabs -> 5), alongside a "Project
    // stages" section that also has its own "Name"-placeholder "add stage"
    // field — scope to "Components & categories" specifically rather than
    // relying on page-wide Name/Prefix queries.
    await selectProjectAdminGroup(page, "Structure");
    const componentsSection = page.locator(".card", { has: page.getByRole("button", { name: "Components & categories section" }) });
    // Component/category tree (C-G-07): with no components yet, the only
    // Name/Prefix inputs in this section are the "add component" form's own.
    await componentsSection.getByPlaceholder("Name").fill("Software");
    await componentsSection.getByPlaceholder("Prefix").fill("SW");
    await componentsSection.getByRole("button", { name: "New component" }).click();
    await expect(page.locator('input[value="Software"]').first()).toBeVisible();
    // ProjectAdminPage's reload() after a mutation fires 9 requests: 7
    // concurrently, then two more awaited *sequentially* afterwards
    // (org users, report templates) — unrelated to the categories tab,
    // but still part of the same component's state, so each one still
    // triggers a re-render. That second wave lands ~150-300ms after the
    // component itself first becomes visible (confirmed via a
    // MutationObserver against the real running app) and is enough to
    // reset whatever's mid-typed into the newly-created component's own
    // "add category" form. Waiting for the network to go idle rides past
    // that whole settling window before touching the form at all.
    await page.waitForLoadState("networkidle");

    // The component/category rename UI (each name/prefix rendered as an
    // always-editable input, not static text) means a page-wide
    // getByPlaceholder("Name").first() is also ambiguous on its own: the
    // "Software" component's own nested "add category" form and the
    // standalone "add component" form at the bottom both have
    // Name/Prefix-placeholder inputs. Scope explicitly to the "Software"
    // component's own container (input -> row -> row -> the component's
    // own stack div, three levels up) so this can't cross-hit a sibling
    // form.
    // `:not([placeholder])`: the "add component" row's own Name field
    // shares this same value transiently (not yet cleared) right after
    // creating "Software", which — since Structure now shares one tab
    // panel with Stages (2026-08 UX audit roadmap: 8 tabs -> 5) — would
    // otherwise let the xpath ancestor climb below escape all the way up
    // to that shared panel and pick up Stages' own "Name" field too, a
    // real (if narrow-window) strict-mode violation. Only a genuine
    // rename input for an existing row is ever placeholder-less (matches
    // project-admin-structural.spec.ts's own established convention).
    const softwareRow = page.locator('input[value="Software"]:not([placeholder])').locator("xpath=../../..");
    await softwareRow.getByPlaceholder("Name").fill("Performance");
    await softwareRow.getByPlaceholder("Prefix").fill("PERF");
    await softwareRow.getByRole("button", { name: "New category" }).click();
    await expect(page.locator('input[value="Performance"]').first()).toBeVisible();
  });

  await test.step("add requirement", async () => {
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill("Boot in under 5 seconds");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText("SW-PERF-001")).toBeVisible();
  });

  await test.step("approve stage locks the requirement", async () => {
    await page.getByText("Project Admin").click();
    // Project stages now lives inside the merged "Structure" tab.
    await selectProjectAdminGroup(page, "Structure");
    // A stage must enter review before it can be approved (C-R-05's
    // review-deadline/response workflow lives in that state) — approving
    // straight from scoping is no longer a valid transition.
    await page.getByRole("button", { name: "Start review" }).click();
    await page.getByRole("button", { name: "Approve stage" }).click();
    await expect(page.getByRole("button", { name: "Approve stage" })).toHaveCount(0);

    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await expect(page.getByText("Locked (approved)")).toBeVisible();
  });

  let requirementCode = "";
  await test.step("raise and approve a change request", async () => {
    await page.getByText("Change Requests").click();
    await page.getByRole("button", { name: "New change request" }).click();
    // The create form is a `Modal` portalled to the end of `document.body`
    // — scope to it rather than an unscoped `getByRole("combobox").first()`,
    // which would otherwise resolve to the filter sidebar's own Status
    // select (it precedes the dialog in DOM order once the form is a
    // portal instead of an inline block).
    const dialog = page.getByRole("dialog", { name: "New change request" });
    // The requirement select defaults asynchronously once project data
    // loads — wait so Create doesn't submit with an empty requirement_id
    // (same race already worked around in mockup-engagement.spec.ts).
    await expect(dialog.getByRole("combobox").first()).toContainText("Boot in under 5 seconds");
    // Modify-requirement CRs are field-toggle driven: a field's proposed
    // value is only editable (and only becomes part of `changed_fields`)
    // once its "Fields to change" checkbox is ticked. Each checkbox and its
    // (once checked) inline editor live in the same field-row container
    // (checkbox -> label -> field-row div), so scope the fill to that row
    // rather than a page-wide input query.
    const nameCheckbox = page.getByRole("checkbox", { name: "Name", exact: true });
    await nameCheckbox.check();
    await nameCheckbox.locator("xpath=../..").locator("input.input").fill("Boot in under 3 seconds");
    const reasoningCheckbox = page.getByRole("checkbox", { name: "Reasoning", exact: true });
    await reasoningCheckbox.check();
    await reasoningCheckbox.locator("xpath=../..").locator("textarea.input").fill("Tighter UX target");
    await page.getByPlaceholder("Reason for change").fill("Field feedback showed 5s felt slow");
    await page.getByRole("button", { name: "Create", exact: true }).click();

    await page.getByText("Boot in under 3 seconds").click();
    await page.getByRole("button", { name: "Submit" }).click();
    // Exact match: a project manager also sees the advisory "Vote to
    // approve" button, which a loose "Approve" query would ambiguously
    // match alongside the real decision button.
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();

    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await expect(page.getByText("Boot in under 3 seconds")).toBeVisible();
    requirementCode = "SW-PERF-001";
  });

  await test.step("generate a PDF report", async () => {
    await page.getByText("Reports").click();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Generate PDF" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toContain("requirements.pdf");
  });

  await test.step("generate a CSV report", async () => {
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Generate CSV" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toContain("requirements.csv");
  });

  await test.step("download the CSV import template", async () => {
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    await page.getByRole("dialog", { name: "Export" }).getByRole("button", { name: "Download template" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("requirements-import-template.csv");
  });

  await test.step("export requirements as a full-fidelity CSV", async () => {
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    await page.getByRole("dialog", { name: "Export" }).getByRole("button", { name: "Export CSV" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/-requirements-export\.csv$/);
  });

  await test.step("toggle theme", async () => {
    await page.getByTitle("Preferences").click();
    await page.getByLabel("Theme").selectOption("dark");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.getByLabel("Theme").selectOption("light");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  });

  expect(requirementCode).toBe("SW-PERF-001");
});
