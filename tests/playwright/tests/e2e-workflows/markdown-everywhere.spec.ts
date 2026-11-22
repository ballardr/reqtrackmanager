import { expect, test, type Page } from "@playwright/test";

import { chooseMarkdownView, markdownField, offeredMarkdownViews } from "../markdownViews";
import { createDisposableProject, installCleanupHook, loginAs, PERSONAS } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: every long free-text field is written in Markdown, so a requirement's description holds
 * formatting and equations side by side, a comment can be formatted, and a list or report shows the words with no
 * marks. The text stored is always the source, so nothing is rewritten.
 *
 * Works in its own disposable project with its own requirement.
 */
test.describe("Markdown for every long-text field", () => {
  installCleanupHook();

  const DESCRIPTION = "The **range** shall satisfy \\( x_1 + y_2 \\) at all times:\n\n- first item\n- second item";

  async function projectWithRequirement(page: Page, label: string) {
    const project = await createDisposableProject(page.request, PERSONAS.orgAdminAlphaBeta.email, label);
    const name = `E2E Markdown ${Date.now()}`;
    const resp = await page.request.post(`${API}/projects/${project.projectId}/requirements`, {
      headers: project.headers,
      data: {
        name, reasoning: "Because **safety** matters.", description: DESCRIPTION,
        component_id: project.components[0].id, category_id: project.categories[0].id,
      },
    });
    expect(resp.ok(), await resp.text()).toBeTruthy();
    const requirement = await resp.json();
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    return { ...project, requirementName: name, requirementId: requirement.id as string };
  }

  test("a requirement shows formatting and equations together, and its comment is formatted", async ({ page }) => {
    const project = await projectWithRequirement(page, "E2E Markdown Requirement");
    await page.goto(`/projects/${project.projectId}/requirements/${project.requirementId}`);

    await test.step("the description is edited as source, previewed with formatting and its equation drawn, the source untouched", async () => {
      // Reasoning, clarification and description hold equations: they offer Visual (which draws each equation), Write and Preview.
      await expect(offeredMarkdownViews(markdownField(page, 0))).toHaveCount(3);
      await expect(page.getByRole("textbox", { name: "Description" })).toHaveValue(DESCRIPTION);
      await chooseMarkdownView(markdownField(page, 2), "Preview");
      const preview = page.locator(".markdown-preview");
      await expect(preview.locator("strong", { hasText: "range" })).toBeVisible();
      await expect(preview.locator("li")).toHaveCount(2);
      await expect(preview.locator(".math-text").first()).toBeVisible({ timeout: 30_000 });
      const stored = await (
        await page.request.get(`${API}/projects/${project.projectId}/requirements/${project.requirementId}`, { headers: project.headers })
      ).json();
      expect(stored.description).toBe(DESCRIPTION);
    });

    await test.step("a comment is written in Write and Preview and shown formatted", async () => {
      await page.getByPlaceholder("Add comment").fill("Please **recheck** the margin:\n\n- upper\n- lower");
      await page.getByRole("button", { name: "Add comment", exact: true }).click();
      const row = page.locator(".comment-row", { hasText: "recheck" });
      await expect(row.locator("strong", { hasText: "recheck" })).toBeVisible();
      await expect(row.locator("li")).toHaveCount(2);
    });
  });

  test("the record list report shows the words of a Markdown cell and the CSV keeps its source", async ({ page }) => {
    const project = await projectWithRequirement(page, "E2E Markdown Report");
    await page.goto(`/projects/${project.projectId}?reports=choose&report=record-list`);

    await test.step("the on-screen table shows plain words in the Description cell", async () => {
      const row = page.getByRole("row", { name: new RegExp(project.requirementName) });
      await expect(row).toBeVisible();
      await expect(row).toContainText("The range shall satisfy");
      await expect(row).not.toContainText("**");
    });

    await test.step("the CSV carries the Markdown source, as the import file does", async () => {
      const csv = await (
        await page.request.get(
          `${API}/projects/${project.projectId}/reports/record-list?record_type=requirement&format=csv`, { headers: project.headers },
        )
      ).text();
      expect(csv).toContain("The **range** shall satisfy");
    });
  });
});
