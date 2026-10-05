import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: docs/plans/module-02-stakeholders-and-personas-plan.md
 * Phase 3's exit criteria — Playwright e2e coverage for the §10.5 relationship
 * panel on Stakeholder and Persona pages (`frontend/src/modules/stakeholders/
 * RelationshipsPanel.tsx`) against a real backend: add relationships to a Pain
 * Point, a Requirement and a Decision (other modules' records, reached through
 * the generic summary-provider hook), follow a link to the target's own page,
 * remove one behind a tier-1 confirm, and see a Persona offered only the kinds
 * that apply to it.
 *
 * Each test builds its own disposable org (see `./helpers.ts`).
 */

test.describe("Stakeholders & Personas: relationships", () => {
  test("a Stakeholder relates to a Pain Point, a Requirement and a Decision", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "Rel");
    const projectApi = `${API_BASE_URL}/api/v1/projects/${project.id}`;
    const stakeholderName = `Pat Regulator ${suffix}`;
    const painPointTitle = `Reports arrive late ${suffix}`;
    const decisionTitle = `Use Postgres ${suffix}`;
    const requirementName = `Report within 30 seconds ${suffix}`;

    for (const key of ["context_strategy", "decisions"]) {
      const resp = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/${key}`, { headers: adminHeaders, data: { enabled: true } });
      expect(resp.ok()).toBeTruthy();
    }
    const stakeholder = await (
      await page.request.post(`${projectApi}/modules/stakeholders/stakeholders`, { headers: adminHeaders, data: { name: stakeholderName } })
    ).json();
    const painPointTypes = await (await page.request.get(`${projectApi}/modules/context_strategy/pain-point-types`, { headers: adminHeaders })).json();
    const painPoint = await (
      await page.request.post(`${projectApi}/modules/context_strategy/pain-points`, {
        headers: adminHeaders,
        data: { title: painPointTitle, description: "d", priority: "high", date_identified: "2026-09-01", pain_point_type_id: painPointTypes[0].id },
      })
    ).json();
    const decisionTypes = await (await page.request.get(`${projectApi}/modules/decisions/decision-types`, { headers: adminHeaders })).json();
    const decision = await (
      await page.request.post(`${projectApi}/modules/decisions`, {
        headers: adminHeaders, data: { title: decisionTitle, decision_statement: "We will.", decision_type_id: decisionTypes[0].id },
      })
    ).json();
    const component = await (await page.request.post(`${projectApi}/components`, { headers: adminHeaders, data: { name: "Software", prefix: "SW" } })).json();
    const category = await (
      await page.request.post(`${projectApi}/categories`, { headers: adminHeaders, data: { name: "Performance", prefix: "PERF", component_id: component.id } })
    ).json();
    const requirement = await (
      await page.request.post(`${projectApi}/requirements`, {
        headers: adminHeaders, data: { name: requirementName, component_id: component.id, category_id: category.id },
      })
    ).json();

    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders/${stakeholder.id}`);
    const panel = page.getByTestId("relationships-panel");
    await expect(panel.getByText("No relationships to this project's records yet.")).toBeVisible();

    // --- A kind with one target type goes straight to the target picker.
    await panel.getByLabel("Relationship").selectOption({ label: "Experiences" });
    await panel.getByLabel("Pain Point").selectOption({ label: painPointTitle });
    await panel.getByRole("button", { name: "Add relationship" }).click();
    await expect(page.getByText("Relationship added.")).toBeVisible();
    await expect(panel.getByRole("link", { name: painPointTitle })).toBeVisible();

    // --- A kind with two target types asks for the type first.
    await panel.getByLabel("Relationship").selectOption({ label: "Approves" });
    await panel.getByLabel("Target type").selectOption({ label: "Requirement" });
    await panel.getByLabel("Requirement").selectOption({ label: `${requirement.unique_code} ${requirementName}` });
    await panel.getByRole("button", { name: "Add relationship" }).click();
    await expect(panel.getByRole("link", { name: new RegExp(requirementName) })).toBeVisible();

    await panel.getByLabel("Relationship").selectOption({ label: "Consulted on" });
    await panel.getByLabel("Decision").selectOption({ label: `${decision.unique_code} ${decisionTitle}` });
    await panel.getByRole("button", { name: "Add relationship" }).click();
    await expect(panel.getByRole("link", { name: new RegExp(decisionTitle) })).toBeVisible();

    // --- The reserved Design / System Element kind is a note, not an option.
    await expect(panel.getByText(/Uses Design \/ System Element: available once the module that provides it is installed\./)).toBeVisible();

    // --- A link goes to the target's own page (another module's route, resolved generically).
    await panel.getByRole("link", { name: painPointTitle }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/pain-points/${painPoint.id}$`));
    await page.goBack();

    // --- Removal is behind a tier-1 confirm, with a toast.
    await page.getByTestId("relationships-panel").getByRole("button", { name: `Remove Experiences ${painPointTitle}` }).click();
    await page.getByRole("dialog", { name: "Remove this relationship?" }).getByRole("button", { name: "Remove" }).click();
    await expect(page.getByText("Relationship removed.")).toBeVisible();
    await expect(page.getByTestId("relationships-panel").getByRole("link", { name: painPointTitle })).toHaveCount(0);
  });

  test("a Persona is only offered the relationship kinds that apply to it", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "RelPersona");
    const persona = await (
      await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas`, {
        headers: adminHeaders, data: { name: `Field Technician ${suffix}` },
      })
    ).json();

    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
    const kind = page.getByTestId("relationships-panel").getByLabel("Relationship");
    await expect(kind).toBeVisible();
    const options = await kind.locator("option").allTextContents();
    expect(options).toEqual(expect.arrayContaining(["Experiences", "Provides", "Is affected by"]));
    for (const stakeholderOnly of ["Consulted on", "Approves", "Reviews"]) expect(options).not.toContain(stakeholderOnly);
  });
});
