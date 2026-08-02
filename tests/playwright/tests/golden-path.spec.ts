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
    await page.getByPlaceholder("Name").fill(projectName);
    await page.getByPlaceholder("Summary").fill("Created by Playwright");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
  });

  await test.step("add component and category", async () => {
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
  });

  await test.step("add requirement", async () => {
    await page.getByText("Requirements").click();
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

    await page.getByText("Requirements").click();
    await expect(page.getByText("Locked (approved)")).toBeVisible();
  });

  let requirementCode = "";
  await test.step("raise and approve a change request", async () => {
    await page.getByText("Change Requests").click();
    await page.getByRole("button", { name: "New change request" }).click();
    await page.getByPlaceholder("Proposed name").fill("Boot in under 3 seconds");
    await page.getByPlaceholder("Proposed reasoning").fill("Tighter UX target");
    await page.getByPlaceholder("Reason for change").fill("Field feedback showed 5s felt slow");
    await page.getByRole("button", { name: "Create", exact: true }).click();

    await page.getByText("Boot in under 3 seconds").click();
    await page.getByRole("button", { name: "Submit" }).click();
    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText("approved")).toBeVisible();

    await page.getByText("Requirements").click();
    await expect(page.getByText("Boot in under 3 seconds")).toBeVisible();
    requirementCode = "SW-PERF-001";
  });

  await test.step("generate a PDF report", async () => {
    await page.getByText("Reports").click();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download PDF" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toContain("requirements.pdf");
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
