import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done:
 * As delivered through the shared Links panel
 * (`frontend/src/components/ArtefactLinksPanel.tsx`) against a real backend: a Stakeholder or Persona links
 * to a Pain Point, a Requirement and a Decision (other modules' records,
 * reached through the generic summary-provider hook), follows a link to the
 * target's own page, removes one behind a tier-1 confirm, and a Persona is
 * offered only the relationship kinds that apply to it.
 *
 * Each test builds its own disposable org (see `./helpers.ts`).
 */

/** Opens the panel's "Add link" dialog and links to `record` with `relationship`. */
async function addLink(
  page: import("@playwright/test").Page,
  relationship: string,
  record: { type: string; label: string },
) {
  await page.getByRole("region", { name: "Links", exact: true }).getByRole("button", { name: "Add link" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a link" });
  await dialog.getByLabel("Link to").selectOption({ label: record.type });
  const recordSelect = dialog.getByLabel("Record");
  await expect(recordSelect.locator("option", { hasText: record.label })).toHaveCount(1);
  await recordSelect.selectOption({ label: record.label });
  await dialog.getByLabel("Relationship").selectOption({ label: relationship });
  await dialog.getByRole("button", { name: "Add link" }).click();
  await expect(page.getByText("Link added.").last()).toBeVisible();
  await expect(dialog).not.toBeVisible();
}

test.describe("Stakeholders & Personas: links", () => {
  test("a Stakeholder links to a Pain Point, a Requirement and a Decision", async ({ page }) => {
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
    const panel = page.getByRole("region", { name: "Links", exact: true });
    await expect(panel.getByText("No links yet.")).toBeVisible();

    await addLink(page, "Experiences", { type: "Pain point", label: painPointTitle });
    await expect(panel.getByRole("link", { name: painPointTitle })).toBeVisible();

    await addLink(page, "Approves", { type: "Requirement", label: `${requirement.unique_code} ${requirementName}` });
    await expect(panel.getByRole("link", { name: new RegExp(requirementName) })).toBeVisible();

    await addLink(page, "Consulted on", { type: "Decision", label: `${decision.unique_code} ${decisionTitle}` });
    await expect(panel.getByRole("link", { name: new RegExp(decisionTitle) })).toBeVisible();

    // --- A link goes to the target's own page (another module's route, resolved generically).
    await panel.getByRole("link", { name: painPointTitle }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/context_strategy/pain-points/${painPoint.id}$`));
    await page.goBack();

    // --- Removal is behind a tier-1 confirm, with a toast.
    await page.getByRole("region", { name: "Links", exact: true }).getByRole("button", { name: `Remove link: Experiences ${painPointTitle}` }).click();
    await page.getByRole("dialog", { name: "Remove this link?" }).getByRole("button", { name: "Remove link" }).click();
    await expect(page.getByText("Link removed.")).toBeVisible();
    await expect(page.getByRole("region", { name: "Links", exact: true }).getByRole("link", { name: painPointTitle })).toHaveCount(0);
  });

  test("a Persona is only offered the relationship kinds that apply to it", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "RelPersona");
    const persona = await (
      await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas`, {
        headers: adminHeaders, data: { name: `Field Technician ${suffix}` },
      })
    ).json();

    const projectApi = `${API_BASE_URL}/api/v1/projects/${project.id}`;
    const component = await (await page.request.post(`${projectApi}/components`, { headers: adminHeaders, data: { name: "Software", prefix: "SW" } })).json();
    const category = await (
      await page.request.post(`${projectApi}/categories`, { headers: adminHeaders, data: { name: "Performance", prefix: "PERF", component_id: component.id } })
    ).json();
    const requirementName = `Technician safety ${suffix}`;
    await page.request.post(`${projectApi}/requirements`, {
      headers: adminHeaders, data: { name: requirementName, component_id: component.id, category_id: category.id },
    });

    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
    await page.getByRole("region", { name: "Links", exact: true }).getByRole("button", { name: "Add link" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a link" });
    await dialog.getByLabel("Link to").selectOption({ label: "Requirement" });
    // The relationships offered are those usable between a Persona and the chosen record.
    const recordSelect = dialog.getByLabel("Record");
    await expect(recordSelect.locator("option", { hasText: requirementName })).toHaveCount(1);
    await recordSelect.selectOption({ label: await recordSelect.locator("option", { hasText: requirementName }).innerText() });
    const relationship = dialog.getByLabel("Relationship");
    await expect(relationship).toBeVisible();
    const options = await relationship.locator("option").allTextContents();
    expect(options).toEqual(expect.arrayContaining(["Provides", "Is affected by"]));
    for (const stakeholderOnly of ["Approves", "Reviews"]) expect(options).not.toContain(stakeholderOnly);
  });
});
