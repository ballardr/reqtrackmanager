import { expect, test } from "@playwright/test";

import { addStructureCategory, addStructureComponent, structureRow, selectProjectAdminGroup } from "./e2e-workflows/helpers";
import { chooseListAction, chooseExport } from "./listActions";

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
    // The post-login landing depends on the admin's landing_preference (U-U-03: "auto" goes straight to the
    // sole accessible project), so the spec navigates explicitly rather than asserting a destination.
    await page.waitForURL(/\/projects(\/|$)/);
    await page.goto("/projects");
  });

  await test.step("create project", async () => {
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
    await newProjectDialog.getByLabel("Summary").fill("Created by Playwright");
    await newProjectDialog.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
  });

  await test.step("add component and category", async () => {
    await page.getByText("Project Admin").click();
    // Categories sits in the merged "Structure" tab beside a "Project stages" section with its own
    // "Name"-placeholder field, so the query is scoped to "Components & categories".
    await selectProjectAdminGroup(page, "Structure");
    await addStructureComponent(page, "Software", "SW");
    await addStructureCategory(page, "Software", "Performance", "PERF");
    await expect(structureRow(page, "Performance")).toBeVisible();
  });

  await test.step("add requirement", async () => {
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill("Boot in under 5 seconds");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    // The confirmation and the list row both carry the code, so the row is found by its title.
    await expect(page.getByRole("link", { name: "Boot in under 5 seconds" })).toBeVisible();
  });

  await test.step("approve stage locks the requirement", async () => {
    await page.getByText("Project Admin").click();
    // Project stages live under the "Workflows and phases" group, with workflows, component phases and the schedule.
    await selectProjectAdminGroup(page, "Workflows and phases");
    // Moves between the workflow's phases are free; entering the locked "Approved" phase writes the baseline.
    const phase = page.getByRole("combobox", { name: "Phase of Scoping" });
    await phase.selectOption({ label: "Review" });
    await expect(phase.locator("option:checked")).toHaveText("Review");
    await phase.selectOption({ label: "Approved" });
    await expect(phase.locator("option:checked")).toHaveText("Approved");

    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    await expect(page.getByText("Locked (approved)")).toBeVisible();
  });

  let requirementCode = "";
  await test.step("raise and approve a change request", async () => {
    await page.getByText("Change Requests").click();
    await page.getByRole("button", { name: "New change request" }).click();
    // The create form is a `Modal` portalled to the end of `document.body`, so it is scoped by dialog rather
    // than `getByRole("combobox").first()`, which would resolve to the filter sidebar's Status select.
    const dialog = page.getByRole("dialog", { name: "New change request" });
    // The requirement select defaults asynchronously once project data
    // loads — wait so Create doesn't submit with an empty requirement_id
    // (same race already worked around in mockup-engagement.spec.ts).
    await expect(dialog.getByRole("combobox").first()).toContainText("Boot in under 5 seconds");
    // Modify-requirement change requests are field-toggle driven: a field's proposed value is editable (and
    // part of `changed_fields`) only once its "Fields to change" checkbox is ticked. The checkbox and its
    // inline editor share a field-row container, so the fill is scoped to that row.
    const nameCheckbox = page.getByRole("checkbox", { name: "Name", exact: true });
    await nameCheckbox.check();
    await nameCheckbox.locator("xpath=../..").locator("input.input").fill("Boot in under 3 seconds");
    const reasoningCheckbox = page.getByRole("checkbox", { name: "Reasoning", exact: true });
    await reasoningCheckbox.check();
    await reasoningCheckbox.locator("xpath=../..").locator("textarea.input").fill("Tighter UX target");
    await page.getByLabel("Reason for change").fill("Field feedback showed 5s felt slow");
    await page.getByRole("button", { name: "Create", exact: true }).click();

    await page.getByText("Boot in under 3 seconds").click();
    await page.getByRole("button", { name: "Submit", exact: true }).click();
    // Exact match: a project manager also sees the advisory "Vote to
    // approve" button, which a loose "Approve" query would ambiguously
    // match alongside the real decision button.
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();

    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    // Role-scoped, not a page-wide getByText: React Router 7 wraps navigation updates in `startTransition`,
    // so the change request detail's "Name: Boot in under 3 seconds" summary can stay painted for one frame
    // beside the requirements list, a transient strict-mode double-match. The requirement card's link is unambiguous.
    await expect(page.getByRole("link", { name: "Boot in under 3 seconds" })).toBeVisible();
    requirementCode = "SW-PERF-001";
  });

  await test.step("generate a PDF report", async () => {
    await page.getByRole("link", { name: "Overview", exact: true }).click();
    await page.getByRole("button", { name: "Reports", exact: true }).click();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Generate PDF" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toContain("requirements.pdf");
  });

  await test.step("generate a Word report", async () => {
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "More formats" }).click();
    await page.getByRole("dialog", { name: "Export" }).getByRole("menuitem", { name: "Download Word report" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toContain("requirements.docx");
  });

  await test.step("generate a CSV report", async () => {
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "More formats" }).click();
    await page.getByRole("dialog", { name: "Export" }).getByRole("menuitem", { name: "Download CSV report" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toContain("requirements.csv");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Reports" })).toHaveCount(0);
  });

  await test.step("download the CSV import template", async () => {
    await page.getByRole("link", { name: "Requirements", exact: true }).click();
    const downloadPromise = page.waitForEvent("download");
    await chooseListAction(page, "Download import template");
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("requirements-import-template.csv");
  });

  await test.step("export requirements as a full-fidelity CSV", async () => {
    const downloadPromise = page.waitForEvent("download");
    await chooseExport(page, "CSV");
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("requirements-export.csv");
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
