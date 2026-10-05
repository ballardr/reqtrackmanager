import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "../../e2e-workflows/helpers";

const API_BASE_URL = "http://localhost:8000";

/**
 * Creates a disposable org with Context & Strategy and Stakeholders &
 * Personas enabled, an org admin, a project, two Active personas (weights 3
 * and 1) and two Pain Points — all via the API, `Date.now()`-suffixed, so
 * the spec never depends on or mutates shared seed data (CLAUDE.md's
 * test-independence rule). The org is deleted afterwards by
 * `deleteOrgOnCleanup`.
 */
async function setup(page: Page, request: APIRequestContext) {
  const suffix = Date.now();
  const adminEmail = `e2e-pp-persona-scoring-${suffix}@example.com`;
  const login = await request.post(`${API_BASE_URL}/api/v1/auth/login`, {
    data: { email: "admin@example.com", password: "ChangeMe123!" },
  });
  const serverHeaders = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const org = await (await request.post(`${API_BASE_URL}/api/v1/orgs`, {
    headers: serverHeaders, data: { name: `E2E Persona Scoring ${suffix}` },
  })).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Persona Scoring Admin", password: PASSWORD, role: "org_admin" },
  });
  await loginAs(page, adminEmail, PASSWORD);
  const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
  const headers = { Authorization: `Bearer ${token}` };
  for (const module of ["context_strategy", "stakeholders"]) {
    const enable = await request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/${module}`, {
      headers, data: { enabled: true, default_project_enabled: true },
    });
    expect(enable.ok(), `${module}: ${await enable.text()}`).toBeTruthy();
  }
  const project = await (await request.post(`${API_BASE_URL}/api/v1/projects`, {
    headers, data: { organization_id: org.id, name: `Persona Scoring Project ${suffix}`, summary: "" },
  })).json();

  const personaNames = { heavy: `E2E Heavy Persona ${suffix}`, light: `E2E Light Persona ${suffix}` };
  for (const [name, weight] of [[personaNames.heavy, 3], [personaNames.light, 1]] as const) {
    const persona = await (await request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas`, {
      headers, data: { name, description: name, weight },
    })).json();
    const activate = await request.post(
      `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas/${persona.id}/activate`, { headers },
    );
    expect(activate.ok()).toBeTruthy();
  }

  const types = await (await request.get(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/context_strategy/pain-point-types`, { headers })).json();
  const titles = { across: `Across personas ${suffix}`, everyone: `For everyone ${suffix}` };
  const painPoints: Record<string, { id: string }> = {};
  for (const [key, title] of Object.entries(titles)) {
    const created = await request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/context_strategy/pain-points`, {
      headers, data: { pain_point_type_id: types[0].id, title },
    });
    expect(created.ok()).toBeTruthy();
    painPoints[key] = await created.json();
  }
  return { project, personaNames, titles, painPoints };
}

/** The scoring controls for one persona (or "All personas") on the detail page. */
function scoreGroup(page: Page, name: string) {
  return page.getByRole("group", { name: `${name} scores` });
}

async function choose(page: Page, group: string, axis: string, level: string) {
  await scoreGroup(page, group).getByRole("combobox", { name: axis }).selectOption({ label: level });
}

/**
 * Job to be done: docs/plans/module-01-context-and-strategy-plan.md Phase 11
 * — scoring a Pain Point per persona (Severity, Frequency, Confidence), the
 * roll-up and Blocker flag shown on its detail page, the list's Score column
 * re-ranking when a different model is chosen, and the intentional-limitation
 * flag. Rating maths: S×F is 4×4 for the heavy persona and 5×1 for the light
 * one on a 5×4 scale, so the weighted average is (3×16 + 1×5) / 4.
 */
test.describe("Context & Strategy: per-persona Pain Point scoring", () => {
  installCleanupHook();

  test("scores per persona, shows the roll-up and Blocker, and re-ranks the list by model", async ({ page, request }) => {
    const { project, personaNames, titles, painPoints } = await setup(page, request);
    const base = `/projects/${project.id}/modules/context_strategy/pain-points`;

    await test.step("score one Pain Point separately for each persona", async () => {
      await page.goto(`${base}/${painPoints.across.id}`);
      await expect(page.getByText("Not scored yet.")).toBeVisible();
      await page.getByRole("combobox", { name: "Scoring mode", exact: true }).selectOption({ label: "Each persona separately" });

      await choose(page, personaNames.heavy, "Severity", "Major");
      await choose(page, personaNames.heavy, "Frequency", "Constant");
      await choose(page, personaNames.heavy, "Confidence", "Low");
      await choose(page, personaNames.light, "Severity", "Blocker");
      await choose(page, personaNames.light, "Frequency", "Rare");
      await choose(page, personaNames.light, "Confidence", "Low");
      await page.getByRole("button", { name: "Save scores" }).click();
      await expect(page.getByText("Scores saved.")).toBeVisible();

      // Default model is S×F×C; the Blocker persona is named even though it carries little weight.
      const rollup = page.getByRole("group", { name: "Rolled-up score" });
      await expect(rollup.getByText("Blocker")).toHaveAttribute("title", `Unusable for: ${personaNames.light}`);
      await expect(rollup.getByText("2 scores counted.")).toBeVisible();
    });

    await test.step("the roll-up changes with the chosen model and persona roll-up", async () => {
      await page.getByRole("combobox", { name: "Scoring model" }).selectOption({ label: "Severity × Frequency" });
      const rollup = page.getByRole("group", { name: "Rolled-up score" });
      // (3 × 16 + 1 × 5) / 4 = 13.25 of 20.
      await expect(rollup.getByText(/Critical · 13\.3/)).toBeVisible();
      await page.getByRole("combobox", { name: "Combine personas by" }).selectOption({ label: "Worst case" });
      await expect(rollup.getByText(/Critical · 16/)).toBeVisible();
      await expect(rollup.getByText("Blocker")).toBeVisible(); // survives every roll-up
    });

    await test.step("score the second Pain Point for all personas", async () => {
      await page.goto(`${base}/${painPoints.everyone.id}`);
      await choose(page, "All personas", "Severity", "Moderate");
      await choose(page, "All personas", "Frequency", "Rare");
      await choose(page, "All personas", "Confidence", "High");
      await page.getByRole("button", { name: "Save scores" }).click();
      await expect(page.getByText("Scores saved.")).toBeVisible();
    });

    await test.step("the list ranks by score and re-ranks when the model changes", async () => {
      await page.goto(base);
      const order = async () => (await page.getByRole("table", { name: "Pain Points" }).locator("tbody").getByRole("button").allTextContents())
        .map((text) => text.replace("Intentional", "").trim());

      await page.getByRole("combobox", { name: "Scoring model" }).selectOption({ label: "Severity × Frequency" });
      const scoreHeader = page.getByRole("button", { name: /^Score/ });
      await scoreHeader.click(); // ascending
      await scoreHeader.click(); // descending
      await expect.poll(order).toEqual([titles.across, titles.everyone]);
      await expect(page.getByText("Blocker")).toBeVisible();

      // S×C: 2.125 of 5 for "across" against 3 of 5 for "everyone" flips the order.
      await page.getByRole("combobox", { name: "Scoring model" }).selectOption({ label: "Severity × Confidence" });
      await expect.poll(order).toEqual([titles.everyone, titles.across]);
    });
  });

  test("flags an intentional limitation and can hide it from the list", async ({ page, request }) => {
    const { project, titles, painPoints } = await setup(page, request);
    const base = `/projects/${project.id}/modules/context_strategy/pain-points`;

    await page.goto(`${base}/${painPoints.everyone.id}`);
    await page.getByRole("button", { name: "Edit" }).click();
    await page.getByRole("switch", { name: "Intentional limitation" }).click();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("Pain Point updated.")).toBeVisible();
    await expect(page.getByText("Intentional", { exact: true })).toBeVisible();

    await page.goto(base);
    await expect(page.getByText(titles.everyone)).toBeVisible();
    await expect(page.getByText("Intentional", { exact: true })).toBeVisible();
    await page.getByRole("checkbox", { name: "Hide intentional limitations" }).check();
    await expect(page.getByText(titles.everyone)).toBeHidden();
    await expect(page.getByText(titles.across)).toBeVisible();
  });
});
