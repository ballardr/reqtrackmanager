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
      await page.getByRole("tab", { name: "Custom fields" }).click();

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
      // Anchored regex, not a plain substring match: `csv-import-wizard.
      // spec.ts` creates its own `E2E Priority <timestamp>` field on this
      // same project (Beta-2), and plain getByText("Priority") substring-
      // matches that one too when both specs land in the same batch run.
      await expect(page.getByText(/^Priority\b/)).toBeVisible();
      await expect(page.getByText("Required").first()).toBeVisible();
    });

    await test.step("a new custom field shows up on the requirement create form", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("button", { name: "New Requirement" }).click();
      await page.getByRole("button", { name: "Add one" }).click();
      await expect(page.getByText("Verification method")).toBeVisible();
      // Anchored regex, not a plain substring match: `csv-import-wizard.
      // spec.ts` creates its own `E2E Priority <timestamp>` field on this
      // same project (Beta-2), and plain getByText("Priority") substring-
      // matches that one too when both specs land in the same batch run.
      await expect(page.getByText(/^Priority\b/)).toBeVisible();
      await page.keyboard.press("Escape").catch(() => {});
      await page.goto(page.url());
    });

    await test.step("delete a custom field", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("tab", { name: "Custom fields" }).click();
      const row = page.locator(".row", { hasText: "Safety critical" });
      await row.getByRole("button").click();
      await expect(page.getByText("Safety critical")).toHaveCount(0);
    });

    await test.step("add and remove a project group member", async () => {
      await page.getByRole("tab", { name: "Project groups" }).click();
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

    await test.step("nest an org group into a project group directly from Project Admin", async () => {
      // The backend has always supported org_group_id here (add_project_group_member);
      // this closes the UX gap where no frontend surface sent it — only
      // OrgAdminPage's own "expanded project" panel could, previously.
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const projectId = page.url().match(/projects\/([0-9a-f-]+)\/admin/)![1];
      const project = await (
        await page.request.get(`http://localhost:8000/api/v1/projects/${projectId}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
      ).json();
      const groupName = `E2E Nest Into Project ${Date.now()}`;
      await page.request.post(`http://localhost:8000/api/v1/orgs/${project.organization_id}/groups`, {
        headers: { Authorization: `Bearer ${token}` }, data: { name: groupName },
      });
      // ProjectAdminPage fetches org groups once on mount — the group just
      // created via a direct API call isn't in that state until reloaded.
      await page.reload();

      await page.getByRole("tab", { name: "Project groups" }).click();
      // Default project groups are created in a fixed order — Project
      // Managers, Project Administrators, Stakeholders, Members — so the
      // "Members" group's own org-group picker is reliably the last one
      // (same assumption the add-member step above already makes).
      const membersGroupSelect = page.getByRole("combobox").last();
      await membersGroupSelect.selectOption({ label: groupName });
      await membersGroupSelect.locator("xpath=../button").click();
      await expect(page.getByText(`${groupName} (`)).toBeVisible();

      const orgGroupRow = page.locator("li", { hasText: groupName });
      await orgGroupRow.getByRole("button").click();
      await expect(page.getByText(`${groupName} (`)).toHaveCount(0);
    });

    await test.step("override and then revert a terminology term", async () => {
      await page.getByRole("tab", { name: "Terminology" }).click();
      await page.getByPlaceholder("requirement").fill("Spec");
      await page.getByRole("button", { name: "Save settings" }).click();
      await page.reload();
      await page.getByRole("tab", { name: "Terminology" }).click();
      await expect(page.getByPlaceholder("requirement")).toHaveValue("Spec");

      await page.getByRole("link", { name: "Specs", exact: true }).click();
      await expect(page.url()).toContain("/requirements");

      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByRole("tab", { name: "Terminology" }).click();
      await page.getByPlaceholder("requirement").fill("");
      await page.getByRole("button", { name: "Save settings" }).click();
    });
  });
});
