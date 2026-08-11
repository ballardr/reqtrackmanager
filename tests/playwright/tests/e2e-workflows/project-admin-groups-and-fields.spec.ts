import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: per-project custom fields of all four types (C-C-01,
 * C-C-02), project group membership management (C-U-11), and per-project
 * terminology overrides (C-C-03).
 *
 * Uses Beta-2. The terminology change is reverted at the end of the test
 * since it's a shared, persistent project setting other specs' nav-label
 * assertions could otherwise be surprised by.
 */
test.describe("project admin: custom fields, groups, and terminology", () => {
  test("all four custom field types, group membership, and a terminology override", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.beta2).click();
    await page.getByRole("link", { name: "Project admin", exact: true }).click();

    await test.step("create a custom field of each type", async () => {
      await page.getByRole("button", { name: "Custom fields" }).click();

      const fieldNameInput = page.getByPlaceholder("Field name");

      await fieldNameInput.fill("Verification method");
      await expect(fieldNameInput).toHaveValue("Verification method");
      await page.getByRole("combobox").nth(1).selectOption("short_text");
      await page.getByRole("button", { name: "New field" }).click();
      await expect(page.getByText("Verification method")).toBeVisible();

      await fieldNameInput.fill("Detailed rationale");
      await expect(fieldNameInput).toHaveValue("Detailed rationale");
      await page.getByRole("combobox").nth(1).selectOption("long_text");
      await page.getByRole("button", { name: "New field" }).click();
      await expect(page.getByText("Detailed rationale")).toBeVisible();

      await fieldNameInput.fill("Safety critical");
      await expect(fieldNameInput).toHaveValue("Safety critical");
      await page.getByRole("combobox").nth(1).selectOption("checkbox");
      await page.getByRole("button", { name: "New field" }).click();
      await expect(page.getByText("Safety critical")).toBeVisible();

      await fieldNameInput.fill("Priority");
      await expect(fieldNameInput).toHaveValue("Priority");
      await page.getByRole("combobox").nth(1).selectOption("list");
      await page.getByPlaceholder("Options (comma separated)").fill("Low, Medium, High");
      await page.getByLabel("Required").check();
      await page.getByRole("button", { name: "New field" }).click();
      await expect(page.getByText("Priority")).toBeVisible();
      await expect(page.getByText("Required").first()).toBeVisible();
    });

    await test.step("a new custom field shows up on the requirement create form", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("button", { name: "New Requirement" }).click();
      await expect(page.getByText("Verification method")).toBeVisible();
      await expect(page.getByText("Priority")).toBeVisible();
      await page.keyboard.press("Escape").catch(() => {});
      await page.goto(page.url());
    });

    await test.step("delete a custom field", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("button", { name: "Custom fields" }).click();
      const row = page.locator(".row", { hasText: "Safety critical" });
      await row.getByRole("button").click();
      await expect(page.getByText("Safety critical")).toHaveCount(0);
    });

    await test.step("add and remove a project group member", async () => {
      await page.getByRole("button", { name: "Project groups" }).click();
      // Default project groups are created in a fixed order — Project
      // Managers, Project Administrators, Stakeholders, Members — so the
      // "Members" group's own add-member input is reliably the last one.
      await page.getByPlaceholder("Type a name or email to add…").last().fill(PERSONAS.memberAlphaBeta.name);
      await page.getByText(PERSONAS.memberAlphaBeta.email).click();
      await expect(page.getByText(PERSONAS.memberAlphaBeta.name)).toBeVisible();

      const removeButton = page.locator("li", { hasText: PERSONAS.memberAlphaBeta.email }).getByRole("button");
      await removeButton.click();
      await expect(page.getByText(PERSONAS.memberAlphaBeta.email)).toHaveCount(0);
    });

    await test.step("override and then revert a terminology term", async () => {
      await page.getByRole("button", { name: "Terminology" }).click();
      await page.getByPlaceholder("requirement").fill("Spec");
      await page.getByRole("button", { name: "Save settings" }).click();
      await page.reload();
      await page.getByRole("button", { name: "Terminology" }).click();
      await expect(page.getByPlaceholder("requirement")).toHaveValue("Spec");

      await page.getByRole("link", { name: "Specs", exact: true }).click();
      await expect(page.url()).toContain("/requirements");

      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("button", { name: "Terminology" }).click();
      await page.getByPlaceholder("requirement").fill("");
      await page.getByRole("button", { name: "Save settings" }).click();
    });
  });
});
