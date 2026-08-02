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

    await page.getByRole("button", { name: "New project" }).click();
    await page.getByPlaceholder("Name").fill(projectName);
    await page.getByPlaceholder("Summary").fill("Created by Playwright (mockup engagement spec)");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);
  });

  await test.step("add a component and category via the Categories admin tab", async () => {
    await page.getByText("Project Admin").click();
    await page.getByRole("button", { name: "Categories" }).click();
    await page.getByPlaceholder("Name").first().fill("Web");
    await page.getByPlaceholder("Prefix").first().fill("WEB");
    await page.getByRole("button", { name: "New component" }).click();
    await page.getByPlaceholder("Name").nth(1).fill("Functional");
    await page.getByPlaceholder("Prefix").nth(1).fill("FN");
    await page.getByRole("button", { name: "New category" }).click();
    await expect(page.getByText("Functional").first()).toBeVisible();
  });

  await test.step("create a requirement and open its card from the card-based list", async () => {
    await page.getByText("Requirements").click();
    await page.getByRole("button", { name: "New requirement" }).click();
    await page.getByPlaceholder("Name", { exact: true }).fill("Users can export their data");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText("WEB-FN-001")).toBeVisible();

    await page.getByText("Users can export their data").click();
    await expect(page.getByRole("heading", { name: /WEB-FN-001/ })).toBeVisible();
  });

  await test.step("subscribe to the requirement", async () => {
    await page.getByRole("button", { name: "Subscribe" }).click();
    await expect(page.getByRole("button", { name: "Subscribed" })).toBeVisible();
  });

  await test.step("post a comment and react to it", async () => {
    await page.getByPlaceholder("Add comment").fill("This looks ready for review.");
    await page.getByRole("button", { name: "Add comment", exact: true }).click();
    await expect(page.getByText("Server Administrator", { exact: true })).toBeVisible();
    await expect(page.getByText("This looks ready for review.")).toBeVisible();

    await page.getByRole("button", { name: "Like this comment" }).click();
    await expect(page.getByText("1", { exact: true })).toBeVisible();
  });

  await test.step("raise a change request, subscribe, and comment on it", async () => {
    await page.getByText("Change Requests").click();
    await page.getByRole("button", { name: "New change request" }).click();
    // The requirement select defaults asynchronously once project data
    // loads — wait so Create doesn't submit with an empty requirement_id.
    await expect(page.getByRole("combobox").first()).toContainText("Users can export their data");
    await page.getByPlaceholder("Proposed name").fill("Export as CSV or JSON");
    await page.getByPlaceholder("Proposed reasoning").fill("Stakeholders want a choice of format");
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
    await expect(page.getByText("Change requests", { exact: true })).toBeVisible();
    await expect(page.getByText("Stage progress")).toBeVisible();
    await expect(page.getByText("Project activity")).toBeVisible();
  });
});
