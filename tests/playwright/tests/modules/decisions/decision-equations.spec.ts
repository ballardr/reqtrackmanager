import { expect, test, type Page } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "../../e2e-workflows/helpers";
import { chooseMarkdownView, markdownField } from "../../markdownViews";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const API = "http://localhost:8000/api/v1";

/** Creates a disposable organisation with an administrator, switches Decision Management on and returns a project in it. */
async function setUpDecisionProject(page: Page, label: string) {
  const suffix = Date.now();
  const adminEmail = `e2e-dmq-${label}-admin-${suffix}@example.com`;
  const serverToken = (
    await (await page.request.post(`${API}/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (await page.request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Equation ${label} Org ${suffix}` } })).json();
  deleteOrgOnCleanup({ id: org.id });
  await page.request.post(`${API}/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: adminEmail, display_name: `E2E ${label} Admin`, password: PASSWORD, role: "org_admin" },
  });
  await loginAs(page, adminEmail, PASSWORD);
  const adminToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const adminHeaders = { Authorization: `Bearer ${adminToken}` };
  expect((await page.request.put(`${API}/orgs/${org.id}/modules/decisions`, { headers: adminHeaders, data: { enabled: true } })).ok()).toBeTruthy();
  const project = await (
    await page.request.post(`${API}/projects`, { headers: adminHeaders, data: { organization_id: org.id, name: `E2E Equation ${label} ${suffix}`, summary: "" } })
  ).json();
  return { project, adminHeaders };
}

/**
 * Job to be done: a Decision's text holds equations. The Inline equation and Equation block buttons open a panel that
 * draws the TeX as it is typed; the Visual view draws each equation and changes it in the same panel; the detail page
 * shows the equation; the stored text is exactly the delimited TeX.
 *
 * Uses a disposable organisation with an administrator and Decision Management switched on, set up through the API.
 */
test.describe("Decision Management: equations", () => {
  test("an equation is written with the toolbar, drawn on the page, and changed in the Visual view", async ({ page }) => {
    const { project, adminHeaders } = await setUpDecisionProject(page, "equations");
    await page.goto(`/projects/${project.id}/modules/decisions`);
    await page.getByRole("button", { name: "New decision" }).click();
    const dialog = page.getByRole("dialog", { name: "New decision" });
    await dialog.getByLabel("Decision title").fill("Size the actuator");

    await test.step("the Inline equation button opens a panel that draws the TeX as it is typed", async () => {
      // The run remembers the Write view (playwright.config.ts), so the field is source text with a toolbar.
      const statement = dialog.getByRole("textbox", { name: "Decision statement" });
      await statement.fill("The force is ");
      await statement.press("End");
      await dialog.getByRole("button", { name: "Inline equation" }).click();
      const panel = page.getByRole("dialog", { name: "Inline equation" });
      await expect(panel.getByRole("textbox", { name: "TeX" })).toBeFocused();
      await panel.getByRole("textbox", { name: "TeX" }).fill("F = m a_1");
      await expect(panel.getByTestId("math-preview").locator(".katex")).toBeVisible({ timeout: 30_000 });
      await panel.getByRole("button", { name: "Insert" }).click();
      await expect(statement).toHaveValue("The force is \\(F = m a_1\\)");
    });

    await test.step("a formula the reports cannot draw is refused with a reason", async () => {
      await dialog.getByRole("button", { name: "Equation block" }).click();
      const panel = page.getByRole("dialog", { name: "Equation block" });
      await panel.getByRole("textbox", { name: "TeX" }).fill("a$$b");
      await expect(panel.getByRole("alert")).toContainText("cannot contain $$");
      await expect(panel.getByRole("button", { name: "Insert" })).toBeDisabled();
      await panel.getByRole("button", { name: "Cancel" }).click();
    });

    await dialog.getByRole("button", { name: "Save" }).click();
    await page.getByRole("button", { name: /^(\w+-)?DEC-001$/ }).click();
    await page.getByRole("dialog", { name: "DEC-001" }).getByRole("link", { name: "View full details" }).click();

    await test.step("the detail page draws the equation", async () => {
      await expect(page.locator(".math-text").first()).toBeVisible({ timeout: 30_000 });
    });

    await test.step("in the Visual view the equation is drawn and changed in the same panel", async () => {
      await page.getByRole("button", { name: "Edit", exact: true }).click();
      const edit = page.getByRole("dialog", { name: /^Edit/ });
      await chooseMarkdownView(markdownField(edit, 0), "Visual");
      const statement = edit.getByRole("textbox", { name: "Decision statement" });
      await expect(statement.locator(".math-text")).toBeVisible({ timeout: 30_000 });
      await statement.getByRole("button", { name: /Change equation/ }).click();
      const panel = page.getByRole("dialog", { name: "Inline equation" });
      await expect(panel.getByRole("textbox", { name: "TeX" })).toHaveValue("F = m a_1");
      await panel.getByRole("textbox", { name: "TeX" }).fill("F = m a_2");
      await panel.getByRole("button", { name: "Apply" }).click();
      await edit.getByRole("button", { name: "Save" }).click();
      await expect(edit).not.toBeVisible();
    });

    await test.step("the stored text is the delimited TeX, unescaped", async () => {
      const list = await (await page.request.get(`${API}/projects/${project.id}/modules/decisions`, { headers: adminHeaders })).json();
      expect(list[0].decision_statement).toBe("The force is \\(F = m a_2\\)");
    });
  });
});
