import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a record named inside another record's page (a Persona a Stakeholder represents,
 * a Need it has, a group it is in) carries its code, so a reader can tell two records with the same
 * name apart and cite either one. The organisation's Persona reads `ACME-PER-001` (a bare
 * `PER-001` would match the project's own), the project's own records read with the project code.
 *
 * Each test builds its own disposable org through the API (see `./helpers.ts`).
 */

test.describe("Stakeholders: record codes in embedded references", () => {
  test("a Stakeholder's Personas, Needs and groups show their codes, an organisation-owned Persona qualified by the organisation", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "EmbCodes");
    const projectBase = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders`;
    const create = async (url: string, data: object) => {
      const response = await page.request.post(url, { headers: adminHeaders, data });
      expect(response.ok(), `${url}: ${await response.text()}`).toBeTruthy();
      return (await response.json()) as { id: string; unique_code: string };
    };

    const orgPersona = await create(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/personas`, { name: `Shared technician ${suffix}` });
    const localPersona = await create(`${projectBase}/personas`, { name: `Local operator ${suffix}` });
    const stakeholder = await create(`${projectBase}/stakeholders`, { name: `Pat Regulator ${suffix}` });
    const need = await create(`${projectBase}/needs`, { name: `Diagnose faults ${suffix}` });
    const group = await create(`${projectBase}/stakeholder-groups`, { name: `Site contacts ${suffix}` });
    expect([orgPersona.unique_code, localPersona.unique_code, need.unique_code, group.unique_code]).toEqual([
      "PER-001", "PER-001", "NEED-001", "SGP-001",
    ]);
    for (const persona of [orgPersona, localPersona]) {
      await create(`${projectBase}/stakeholders/${stakeholder.id}/personas`, { persona_id: persona.id });
    }
    await create(`${projectBase}/needs/${need.id}/holders`, { kind: "stakeholder", id: stakeholder.id });
    const grouped = await page.request.put(`${projectBase}/stakeholders/${stakeholder.id}/groups`, {
      headers: adminHeaders, data: { group_ids: [group.id] },
    });
    expect(grouped.ok(), await grouped.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders/${stakeholder.id}`);
    await expect(page.locator(".record-header").getByRole("heading")).toContainText(`Pat Regulator ${suffix}`);

    await test.step("the two Personas with one bare code are told apart by their owner", async () => {
      await expect(page.getByText(`${org.code}-PER-001`, { exact: true }).first()).toBeVisible();
      await expect(page.getByText(`${project.code}-PER-001`, { exact: true }).first()).toBeVisible();
      await expect(page.getByRole("link", { name: `Shared technician ${suffix}` }).first()).toBeVisible();
    });

    await test.step("the Need and the group carry their codes", async () => {
      await expect(page.getByText(`${project.code}-NEED-001`, { exact: true }).first()).toBeVisible();
      await expect(page.getByText(`${project.code}-SGP-001`, { exact: true }).first()).toBeVisible();
    });
  });
});
