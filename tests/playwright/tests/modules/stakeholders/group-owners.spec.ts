import { expect, test } from "@playwright/test";

import { installCleanupHook, openOrgGroupPanel, selectOrgAdminGroup } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: users and groups on parity — a Persona's owner can be an organisation
 * group and its champion a project group, a Stakeholder and a Need can be owned
 * by a group, an organisation-level record cannot name a project group, and
 * deleting a group that still owns them lets the admin clear or reassign.
 *
 * Disposable org, admin and project via `setUpOrg`; the groups and records are
 * created through the API, the assignments and the group deletion through the UI.
 */
test.describe("Stakeholders & Personas: groups as owners", () => {
  test("a group owns a Persona, Stakeholder and Need, and deleting it hands them to someone else", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "StakeholderGroups");
    const teamName = `Research Team ${suffix}`;
    const squadName = `Field Squad ${suffix}`;
    const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders`;

    const team = await (await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/groups`, { headers: adminHeaders, data: { name: teamName } })).json();
    expect(
      (await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/groups`, { headers: adminHeaders, data: { name: squadName } })).ok(),
    ).toBeTruthy();
    const persona = await (await page.request.post(`${base}/personas`, { headers: adminHeaders, data: { name: `Inspector ${suffix}` } })).json();
    const stakeholder = await (
      await page.request.post(`${base}/stakeholders`, { headers: adminHeaders, data: { name: `Regulator ${suffix}`, owner: { type: "org_group", id: team.id } } })
    ).json();
    const need = await (
      await page.request.post(`${base}/needs`, { headers: adminHeaders, data: { name: `Offline access ${suffix}`, owner: { type: "org_group", id: team.id } } })
    ).json();

    // --- Assign the org group as owner and the project group as champion from the Persona page.
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
    await expect(page.getByRole("heading", { name: `Inspector ${suffix}` })).toBeVisible();
    await page.getByRole("button", { name: /^(Assign|Change): Persona owner$/ }).click();
    await page.getByRole("combobox", { name: "Persona owner" }).fill("Research Team");
    await page.getByRole("option", { name: new RegExp(teamName) }).click();
    await expect(page.getByText("Owner updated.")).toBeVisible();
    await page.getByRole("button", { name: /^(Assign|Change): Persona champion$/ }).click();
    await page.getByRole("combobox", { name: "Persona champion" }).fill("Field Squad");
    await page.getByRole("option", { name: new RegExp(squadName) }).click();
    await expect(page.getByText("Champion updated.")).toBeVisible();

    // The group is named with its kind, and survives a reload.
    await page.reload();
    // (History rows name them too once the persona has several versions, hence `.first()`.)
    await expect(page.getByText(teamName).first()).toBeVisible();
    await expect(page.getByText(/^Org group/).first()).toBeVisible();
    await expect(page.getByText(squadName).first()).toBeVisible();
    await expect(page.getByText(/^Project group/).first()).toBeVisible();

    // The Stakeholder and Need pages show their group owner too.
    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders/${stakeholder.id}`);
    await expect(page.getByText(teamName).first()).toBeVisible();
    await page.goto(`/projects/${project.id}/modules/stakeholders/needs/${need.id}`);
    await expect(page.getByText(teamName).first()).toBeVisible();

    // --- An organisation-level record is shared by every project, so it cannot name a project group.
    const orgPersona = await (
      await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/personas`, { headers: adminHeaders, data: { name: `Shared ${suffix}` } })
    ).json();
    await page.goto(`/orgs/${org.id}/modules/stakeholders/personas/${orgPersona.id}`);
    await page.getByRole("button", { name: /^(Assign|Change): Persona owner$/ }).click();
    await page.getByRole("combobox", { name: "Persona owner" }).fill("Field Squad");
    await expect(page.getByRole("option", { name: new RegExp(squadName) })).toHaveCount(0);

    // --- Deleting the org group is blocked while it owns records; hand them to the admin.
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Groups");
    const panel = await openOrgGroupPanel(page, teamName);
    await panel.getByRole("button", { name: "Delete group" }).click();
    await page.getByRole("dialog", { name: `Delete "${teamName}"?` }).getByRole("button", { name: "Delete group" }).click();

    const inUse = page.getByRole("dialog", { name: `Delete “${teamName}”?` });
    await expect(inUse.getByText(/1 stakeholder owners/)).toBeVisible();
    await expect(inUse.getByText(/1 stakeholder need owners/)).toBeVisible();
    // Every Stakeholders owner is optional, so clearing is offered alongside reassigning.
    await expect(inUse.getByText("Some of these fields are required, so a replacement is needed.")).toHaveCount(0);
    await inUse.getByRole("combobox", { name: "New owner" }).fill("E2E StakeholderGroups Admin");
    await inUse.getByRole("option", { name: /E2E StakeholderGroups Admin/ }).click();
    await inUse.getByRole("button", { name: "Confirm delete" }).click();
    await expect(page.getByText("Group deleted", { exact: true })).toBeVisible();

    // The records now name the admin; the project-group champion is untouched.
    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders/${stakeholder.id}`);
    await expect(page.getByText(/E2E StakeholderGroups Admin/).first()).toBeVisible();
    await expect(page.getByText(teamName)).toHaveCount(0);
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
    await expect(page.getByText(squadName).first()).toBeVisible();
  });
});
