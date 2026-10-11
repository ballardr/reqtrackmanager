import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: docs/plans/platform-enhancements-2026-10-plan.md Phase 6 — every
 * artefact detail page shows the shared Links panel with an add control, and the
 * panel makes any two artefacts linkable from either end: a Pain Point is addressed
 * by a Decision that implements a Requirement, and the chain reads correctly from
 * all three pages.
 *
 * Builds one disposable org with a record of every type that has its own detail page
 * (Compliance records have no pages of their own; their panels are covered in
 * Storybook and `requirement-traceability-links.spec.ts`).
 */
const links = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "Links", exact: true });

async function setUpRecords(page: import("@playwright/test").Page) {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "Links");
  for (const key of ["context_strategy", "decisions"]) {
    const resp = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/${key}`, { headers: adminHeaders, data: { enabled: true } });
    expect(resp.ok()).toBeTruthy();
  }
  const api = `${API_BASE_URL}/api/v1/projects/${project.id}`;
  const post = async (path: string, data: object) => {
    const resp = await page.request.post(`${api}${path}`, { headers: adminHeaders, data });
    expect(resp.ok(), `${path}: ${await resp.text()}`).toBeTruthy();
    return resp.json();
  };
  const get = async (path: string) => (await page.request.get(`${api}${path}`, { headers: adminHeaders })).json();

  const component = await post("/components", { name: "Software", prefix: "SW" });
  const category = await post("/categories", { name: "Performance", prefix: "PERF", component_id: component.id });
  const requirement = await post("/requirements", { name: `Report in 30 seconds ${suffix}`, component_id: component.id, category_id: category.id });
  const actionTypes = await get("/action-types");
  const action = await post("/actions", { title: `Review report ${suffix}`, action_type_id: actionTypes[0].id });
  const painPointTypes = await get("/modules/context_strategy/pain-point-types");
  const painPoint = await post("/modules/context_strategy/pain-points", {
    title: `Reports arrive late ${suffix}`, description: "d", priority: "high", date_identified: "2026-09-01", pain_point_type_id: painPointTypes[0].id,
  });
  const strategy = await post("/modules/context_strategy/strategies", { title: `Lead the market ${suffix}`, objective: "o" });
  const futureState = await post("/modules/context_strategy/future-states", { title: `Self-service ${suffix}` });
  const guidingPrinciple = await post("/modules/context_strategy/guiding-principles", { name: `Simple first ${suffix}`, principle_statement: "s" });
  const openQuestion = await post("/modules/context_strategy/open-questions", { question: `Which database ${suffix}?` });
  const decisionTypes = await get("/modules/decisions/decision-types");
  const decision = await post("/modules/decisions", { title: `Use Postgres ${suffix}`, decision_statement: "We will.", decision_type_id: decisionTypes[0].id });
  const persona = await post("/modules/stakeholders/personas", { name: `Field Technician ${suffix}` });
  const stakeholder = await post("/modules/stakeholders/stakeholders", { name: `Pat Regulator ${suffix}` });
  const need = await post("/modules/stakeholders/needs", { name: `Offline access ${suffix}` });

  const base = `/projects/${project.id}`;
  return {
    suffix, painPoint, decision, requirement,
    pages: {
      Requirement: `${base}/requirements/${requirement.id}`,
      Action: `${base}/actions/${action.id}`,
      "Pain point": `${base}/modules/context_strategy/pain-points/${painPoint.id}`,
      Strategy: `${base}/modules/context_strategy/strategies/${strategy.id}`,
      "Future state": `${base}/modules/context_strategy/future-states/${futureState.id}`,
      "Guiding principle": `${base}/modules/context_strategy/guiding-principles/${guidingPrinciple.id}`,
      "Open question": `${base}/modules/context_strategy/open-questions/${openQuestion.id}`,
      Decision: `${base}/modules/decisions/${decision.id}`,
      Persona: `${base}/modules/stakeholders/personas/${persona.id}`,
      Stakeholder: `${base}/modules/stakeholders/stakeholders/${stakeholder.id}`,
      "Stakeholder need": `${base}/modules/stakeholders/needs/${need.id}`,
    } as Record<string, string>,
  };
}

/** Links the open page's record to `record` (of type `type`) with `relationship` through the panel. */
async function addLink(page: import("@playwright/test").Page, relationship: string, record: { type: string; label: string }) {
  await links(page).getByRole("button", { name: "Add link" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a link" });
  await dialog.getByLabel("Link to").selectOption({ label: record.type });
  const recordSelect = dialog.getByLabel("Record");
  await expect(recordSelect.locator("option", { hasText: record.label })).toHaveCount(1);
  await recordSelect.selectOption({ label: record.label });
  await dialog.getByLabel("Relationship").selectOption({ label: relationship });
  await dialog.getByRole("button", { name: "Add link" }).click();
  await expect(dialog).not.toBeVisible();
}

test.describe("Links panel on every artefact detail page", () => {
  test("every artefact type's detail page shows the Links panel with an add control", async ({ page }) => {
    const { pages } = await setUpRecords(page);
    for (const [type, path] of Object.entries(pages)) {
      await test.step(`${type} page`, async () => {
        await page.goto(path);
        await expect(links(page)).toBeVisible();
        await expect(links(page).getByRole("button", { name: "Add link" })).toBeVisible();
        await expect(links(page).getByText("No links yet.")).toBeVisible();
      });
    }
  });

  test("a Pain Point is addressed by a Decision that implements a Requirement, readable from all three pages", async ({ page }) => {
    const { suffix, painPoint, decision, requirement, pages } = await setUpRecords(page);
    const painPointTitle = `Reports arrive late ${suffix}`;
    const decisionLabel = `${decision.unique_code} Use Postgres ${suffix}`;
    const requirementLabel = `${requirement.unique_code} Report in 30 seconds ${suffix}`;

    await page.goto(pages.Decision);
    await addLink(page, "Addresses", { type: "Pain point", label: painPointTitle });
    await addLink(page, "Implements", { type: "Requirement", label: requirementLabel });
    await expect(links(page).getByRole("link", { name: painPointTitle })).toBeVisible();
    await expect(links(page).getByRole("link", { name: new RegExp(`Report in 30 seconds ${suffix}`) })).toBeVisible();

    await test.step("the Pain Point's page reads the link from its own side", async () => {
      await page.goto(pages["Pain point"]);
      const row = links(page).locator(".artefact-links__row", { hasText: "Is addressed by" });
      await expect(row.getByRole("link", { name: new RegExp(decisionLabel) })).toBeVisible();
      await row.getByRole("link", { name: new RegExp(decisionLabel) }).click();
      await expect(page).toHaveURL(new RegExp(`/modules/decisions/${decision.id}$`));
      expect(painPoint.id).toBeTruthy();
    });

    await test.step("the Requirement's page shows the Decision, and the link can be removed from there", async () => {
      await page.goto(pages.Requirement);
      const row = links(page).locator(".artefact-links__row", { hasText: "Is implemented by" });
      await expect(row.getByRole("link", { name: new RegExp(decisionLabel) })).toBeVisible();
      await row.getByRole("button", { name: /^Remove link/ }).click();
      await page.getByRole("dialog", { name: "Remove this link?" }).getByRole("button", { name: "Remove link" }).click();
      await expect(links(page).getByText("No links yet.")).toBeVisible();
    });
  });
});
