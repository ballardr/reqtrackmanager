import { expect, test } from "@playwright/test";

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
    await page.getByRole("button", { name: "New project" }).click();
    // The org dropdown's default selection is whichever org sorts first
    // alphabetically, not necessarily the admin's own org (this stack may
    // also have E2E-workflow seed orgs present) — select explicitly, after
    // waiting for the actual option (not just any combobox on the page —
    // the role/stage filter comboboxes already have static options and can
    // satisfy a weaker "not empty" check before the org picker mounts).
    await expect(page.getByRole("combobox").first()).toContainText("Default Organization");
    await page.getByRole("combobox").first().selectOption({ label: "Default Organization" });
    await page.getByPlaceholder("Name").fill(projectName);
    await page.getByPlaceholder("Summary").fill("Created by Playwright");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
  });

  await test.step("add component and category", async () => {
    await page.getByText("Project Admin").click();
    await page.getByRole("button", { name: "Categories" }).click();
    // Component/category tree (C-G-07): with no components yet, the only
    // Name/Prefix inputs on the page are the "add component" form's own.
    await page.getByPlaceholder("Name").fill("Software");
    await page.getByPlaceholder("Prefix").fill("SW");
    await page.getByRole("button", { name: "New component" }).click();
    await expect(page.getByText("Software").first()).toBeVisible();

    // Once "Software" exists, its own nested "add category" form is the
    // first Name/Prefix pair on the page (it renders above the "add
    // component" form at the bottom of the list).
    await page.getByPlaceholder("Name").first().fill("Performance");
    await page.getByPlaceholder("Prefix").first().fill("PERF");
    await page.getByRole("button", { name: "New category" }).click();
    await expect(page.getByText("Performance").first()).toBeVisible();
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
    await page.getByRole("button", { name: "Project stages" }).click();
    await page.getByRole("button", { name: "Approve stage" }).click();
    await expect(page.getByRole("button", { name: "Approve stage" })).toHaveCount(0);

    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await expect(page.getByText("Locked (approved)")).toBeVisible();
  });

  let requirementCode = "";
  await test.step("raise and approve a change request", async () => {
    await page.getByText("Change Requests").click();
    await page.getByRole("button", { name: "New change request" }).click();
    // The requirement select defaults asynchronously once project data
    // loads — wait so Create doesn't submit with an empty requirement_id
    // (same race already worked around in mockup-engagement.spec.ts).
    await expect(page.getByRole("combobox").first()).toContainText("Boot in under 5 seconds");
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
    await page.getByRole("button", { name: "Download template" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("requirements-import-template.csv");
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
