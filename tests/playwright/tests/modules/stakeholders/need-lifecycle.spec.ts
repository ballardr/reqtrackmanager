import { expect, test } from "@playwright/test";

import { installCleanupHook, chooseRecordAction, recordActionNames } from "../../e2e-workflows/helpers";
import { API_BASE_URL, openNeeds, setUpOrg, statusBadge } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done:
 * Playwright e2e coverage for the Stakeholder Need UI
 * (`frontend/src/modules/stakeholders/`) against a real backend: create, activate
 * and edit a need; link it to a Stakeholder, a Persona and a Requirement and see
 * it from the Stakeholder's and Persona's own pages; archive and unarchive.
 *
 * Each test builds its own disposable org (see `./helpers.ts`), so none depends
 * on seeded state or on another test having run.
 */

test.describe("Stakeholders & Personas: Stakeholder Need", () => {
  test("creates, activates and edits a need, keeping a version history", async ({ page }) => {
    const { suffix, project } = await setUpOrg(page, "Need");
    const name = `Diagnose faults ${suffix}`;

    await openNeeds(page, project.id);
    await expect(page.getByText("No Stakeholder Needs recorded for this project yet.")).toBeVisible();

    // --- Create (a Modal layer), from the Needs tab's own New button.
    await page.getByRole("button", { name: "New Stakeholder Need" }).click();
    const dialog = page.getByRole("dialog", { name: "New Stakeholder Need" });
    await dialog.getByLabel("Need name").fill(name);
    await dialog.getByLabel("Need", { exact: true }).fill("Find out what is wrong without a laptop.");
    await dialog.getByLabel("Rationale").fill("Each delay costs an hour.");
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("Stakeholder Need created.")).toBeVisible();

    // --- The list renders the label-mapped status.
    const row = page.locator("tr", { hasText: name });
    await expect(row.getByText("Draft", { exact: true })).toBeVisible();

    await page.getByRole("button", { name }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/needs/[^/]+$`));
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(statusBadge(page, "Draft")).toBeVisible();
    await expect(page.getByText("Each delay costs an hour.")).toBeVisible();

    // --- Activate behind a confirm dialog; no approval step.
    await page.getByRole("button", { name: "Activate" }).click();
    await page.getByRole("dialog", { name: "Activate this Stakeholder Need?" }).getByRole("button", { name: "Activate" }).click();
    await expect(statusBadge(page, "Active")).toBeVisible();

    // --- Edit as a layer; the change becomes a new version.
    await page.getByRole("button", { name: "Edit" }).click();
    const edit = page.getByRole("dialog", { name: `Edit ${name}` });
    await edit.getByLabel("Rationale").fill("Observed on three site visits.");
    await edit.getByLabel("Change note").fill("Added evidence");
    await edit.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Observed on three site visits.")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Versions" })).toBeVisible();
    await expect(page.getByText("Added evidence")).toBeVisible();
  });

  test("links a need to a Stakeholder, a Persona and a Requirement, and shows it from their pages", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "NeedLinks");
    const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders`;
    const stakeholderName = `Pat Technician ${suffix}`;
    const personaName = `Field Technician ${suffix}`;
    const needName = `Work offline ${suffix}`;
    const stakeholder = await (await page.request.post(`${base}/stakeholders`, { headers: adminHeaders, data: { name: stakeholderName } })).json();
    const persona = await (await page.request.post(`${base}/personas`, { headers: adminHeaders, data: { name: personaName } })).json();
    const need = await (await page.request.post(`${base}/needs`, { headers: adminHeaders, data: { name: needName } })).json();
    const component = await (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/components`, { headers: adminHeaders, data: { name: "Software", prefix: "SW" } })).json();
    const category = await (
      await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/categories`, { headers: adminHeaders, data: { name: "Performance", prefix: "PERF", component_id: component.id } })
    ).json();
    const requirementName = `Work without a network ${suffix}`;
    const requirement = await (
      await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/requirements`, {
        headers: adminHeaders, data: { name: requirementName, component_id: component.id, category_id: category.id },
      })
    ).json();

    await page.goto(`/projects/${project.id}/modules/stakeholders/needs/${need.id}`);
    await expect(page.getByText("No Stakeholder has this need yet.")).toBeVisible();

    // --- Link a Stakeholder, a Persona and a Requirement from the need's page.
    await page.getByRole("button", { name: "Add to Stakeholders with this need" }).click();
    await page.getByRole("dialog", { name: "Add to Stakeholders with this need" }).getByLabel("Stakeholder with this need").selectOption({ label: stakeholderName });
    await page.getByRole("dialog", { name: "Add to Stakeholders with this need" }).getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByRole("link", { name: stakeholderName })).toBeVisible();
    await page.getByRole("button", { name: "Add to Personas with this need" }).click();
    await page.getByRole("dialog", { name: "Add to Personas with this need" }).getByLabel("Persona with this need").selectOption({ label: personaName });
    await page.getByRole("dialog", { name: "Add to Personas with this need" }).getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByRole("link", { name: personaName })).toBeVisible();
    await page.getByRole("button", { name: "Add to Requirements it gave rise to" }).click();
    await page.getByRole("dialog", { name: "Add to Requirements it gave rise to" }).getByLabel("Requirement it gave rise to").selectOption({ label: `${requirement.unique_code} ${requirementName}` });
    await page.getByRole("dialog", { name: "Add to Requirements it gave rise to" }).getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByRole("link", { name: requirementName })).toBeVisible();

    // --- The Stakeholder's and the Persona's pages list the need, read-only, with its status label.
    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders/${stakeholder.id}`);
    await expect(page.getByRole("link", { name: `${needName} (Draft)` })).toBeVisible();
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
    await page.getByRole("link", { name: `${needName} (Draft)` }).click();
    await expect(page.getByRole("heading", { name: needName })).toBeVisible();

    // --- Remove the Stakeholder link, behind a tier-1 confirm.
    await page.getByRole("button", { name: `Remove ${stakeholderName}` }).click();
    await page.getByRole("dialog", { name: `Remove ${stakeholderName}?` }).getByRole("button", { name: "Remove" }).click();
    await expect(page.getByText("Link removed.")).toBeVisible();
    await expect(page.getByText("No Stakeholder has this need yet.")).toBeVisible();
  });

  test("archives and unarchives a need, hiding it from the default list", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "NeedArchive");
    const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders`;
    const name = `Archivable need ${suffix}`;
    const need = await (await page.request.post(`${base}/needs`, { headers: adminHeaders, data: { name } })).json();

    await page.goto(`/projects/${project.id}/modules/stakeholders/needs/${need.id}`);
    await chooseRecordAction(page, "Stakeholder Need", "Archive");
    await page.getByRole("dialog", { name: "Archive this Stakeholder Need?" }).getByRole("button", { name: "Archive" }).click();
    await expect(page.getByText("Stakeholder Need archived.")).toBeVisible();
    await expect.poll(() => recordActionNames(page, "Stakeholder Need")).toContain("Unarchive");

    await page.goto(`/projects/${project.id}/modules/stakeholders/needs`);
    await expect(page.getByText("No Stakeholder Needs recorded for this project yet.")).toBeVisible();
    await page.getByLabel("Show archived").check();
    await expect(page.getByRole("button", { name })).toBeVisible();
  });
});
