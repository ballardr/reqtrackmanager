import { expect, test } from "@playwright/test";

import { loginAs, logout, ORG_NAMES, PERSONAS } from "./helpers";

/**
 * Job to be done: a project can be marked "Org-wide visibility" so every
 * member of its organisation gets automatic read access with no explicit
 * user/group assignment — as opposed to the default "Only specified" mode,
 * where access requires one. Covers both places the toggle lives (the "New
 * project" creation form, and Project Admin's settings tab) and confirms
 * the grant is read-only (never implies management rights) and reversible.
 *
 * Uses a disposable project created within this spec (not a shared seeded
 * one) specifically so it can't interfere with project-access-scope.spec.ts,
 * which asserts StakeholderAlphaOnly does *not* see Alpha-2 by default.
 *
 * Persona: StakeholderAlphaOnly is a stakeholder on Alpha-1 only (still a
 * member of the Alpha organisation, C-U-02) — holds no explicit role at all
 * on the new project this spec creates, so any access they get to it can
 * only come from org-wide visibility.
 */
test.describe("project visibility: org-wide vs only specified", () => {
  test("org-wide visibility grants read access with no explicit role, and is reversible", async ({ page }) => {
    const projectName = `Org Wide Visibility ${Date.now()}`;

    await test.step("org admin creates a new Alpha project with Org-wide visibility set at creation", async () => {
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.goto("/projects");
      await page.getByRole("button", { name: "New project" }).click();
      await expect(page.getByRole("combobox").first()).toContainText(ORG_NAMES.alpha);
      await page.getByRole("combobox").first().selectOption({ label: ORG_NAMES.alpha });
      await page.getByPlaceholder("Name").fill(projectName);
      await page.getByLabel("Visibility").selectOption("org_wide");
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
    });

    await test.step("Project Admin's settings tab reflects Org-wide visibility", async () => {
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await expect(page.getByLabel("Visibility")).toHaveValue("org_wide");
    });

    await test.step("a plain Alpha org member with no explicit role sees and can open the project", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.goto("/projects");
      await expect(page.getByText(projectName)).toBeVisible();
      await page.getByText(projectName).click();
      await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
    });

    await test.step("org admin switches it back to Only specified", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.goto("/projects");
      await page.getByText(projectName).click();
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      await page.getByLabel("Visibility").selectOption("only_specified");
      await page.getByRole("button", { name: "Save settings" }).click();
      await expect(page.getByLabel("Visibility")).toHaveValue("only_specified");
    });

    await test.step("the same org member no longer sees the project", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.goto("/projects");
      await expect(page.getByText(projectName)).toHaveCount(0);
    });
  });
});
