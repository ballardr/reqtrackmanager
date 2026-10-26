import crypto from "node:crypto";

import { expect, test } from "@playwright/test";

import { approveRequirementFromDetail, deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: write an equation in a requirement's description, reasoning or clarification and read it typeset
 * once the requirement is locked, while anything that is not an allowed equation stays as typed.
 *
 * The test works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Equations in requirement text", () => {
  installCleanupHook();

  test("a locked requirement shows its equations typeset and everything else as typed", async ({ page, request }) => {
    const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const email = `e2e-req-math-${suffix}@example.com`;
    const login = async (e: string, p: string) => ({
      Authorization: `Bearer ${(await (await request.post(`${API}/auth/login`, { data: { email: e, password: p } })).json()).access_token}`,
    });
    const serverHeaders = await login("admin@example.com", "ChangeMe123!");
    const org = await (await request.post(`${API}/orgs`, { headers: serverHeaders, data: { name: `E2E Req Math ${suffix}` } })).json();
    deleteOrgOnCleanup({ id: org.id });
    await request.post(`${API}/orgs/${org.id}/users`, {
      headers: serverHeaders, data: { email, display_name: "E2E Math Admin", password: PASSWORD, role: "org_admin" },
    });
    await loginAs(page, email, PASSWORD);
    const headers = await login(email, PASSWORD);
    const project = await (await request.post(`${API}/projects`, { headers, data: { organization_id: org.id, name: `Math project ${suffix}`, summary: "" } })).json();
    const component = await (await request.post(`${API}/projects/${project.id}/components`, { headers, data: { name: "Structure", prefix: "ST" } })).json();
    const category = await (await request.post(`${API}/projects/${project.id}/categories`, {
      headers, data: { name: "Strength", prefix: "STR", component_id: component.id },
    })).json();
    const created = await request.post(`${API}/projects/${project.id}/requirements`, {
      headers, data: {
        name: `Bracket ${suffix}`, component_id: component.id, category_id: category.id,
        reasoning: "The stress \\(\\sigma = F/A\\) must stay below yield.",
        description: "Margin: $$ \\sigma_{max} \\leq \\frac{\\sigma_y}{n} $$ Costs $5 and \\(\\href{http://example.com}{x}\\).",
      },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const requirement = await created.json();

    await page.goto(`/projects/${project.id}/requirements/${requirement.id}`);
    await approveRequirementFromDetail(page);
    await expect(page.getByText("Locked (approved)")).toBeVisible();

    await test.step("allowed equations are typeset, inline and as a block", async () => {
      await expect(page.locator(".math-text .katex")).toHaveCount(2);
      await expect(page.locator(".math-text--display .katex-display")).toBeVisible();
      await expect(page.getByText("The stress")).toBeVisible();
    });

    await test.step("a refused command and a stray dollar sign stay as written", async () => {
      await expect(page.getByText("Costs $5 and \\(\\href{http://example.com}{x}\\).")).toBeVisible();
      await expect(page.locator("a[href='http://example.com']")).toHaveCount(0);
    });
  });
});
