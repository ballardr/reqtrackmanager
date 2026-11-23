import { expect, test } from "@playwright/test";

import { addDefinition, installCleanupHook, selectOrgAdminGroup } from "../../e2e-workflows/helpers";
import { API_BASE_URL, openNew, openPeople, setUpOrg, statusBadge } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: e2e coverage of the Persona UI (`frontend/src/modules/stakeholders/`) against a real backend.
 *
 * Each test builds a disposable org + admin (+ project) through the API with `Date.now()`-suffixed names and
 * switches the `default_enabled=False` module on from Org Admin's Modules group. Both seed scripts carry
 * Personas, but these specs do not depend on them. The org admin is the project's `PROJECT_MANAGER`, which
 * composes with the module's `persona_owner` role, so one persona can create, activate and re-weight.
 */
test.describe("Stakeholders & Personas: Persona lifecycle and weight", () => {
  test("creates a project Persona, activates it, overrides its weight and resets it", async ({ page }) => {
    const { suffix, project } = await setUpOrg(page, "Persona");
    const personaName = `Field Technician ${suffix}`;

    await openPeople(page, project.id, "persona");

    // --- Create (a Modal layer, from the New menu) with an own weight of 2.
    await openNew(page, "Persona");
    const dialog = page.getByRole("dialog", { name: "New Persona (project)" });
    await dialog.getByLabel("Persona name").fill(personaName);
    await dialog.getByLabel("Type").selectOption({ label: "Primary" });
    await dialog.getByLabel("Goals").fill("Finish inspections without rework.");
    await dialog.getByLabel("Importance weight").fill("2");
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("button", { name: personaName })).toBeVisible();

    await page.getByRole("button", { name: personaName }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/personas/[^/]+$`));
    await expect(page.getByRole("heading", { name: personaName })).toBeVisible();
    await expect(statusBadge(page, "Draft")).toBeVisible();
    await expect(page.getByText("Finish inspections without rework.")).toBeVisible();
    await expect(page.getByTestId("effective-weight")).toHaveText("2");
    await expect(page.getByText("Persona's own weight", { exact: true })).toBeVisible();

    // --- Activate behind a confirm dialog; there is no approval step.
    await page.getByRole("button", { name: "Activate" }).click();
    await page.getByRole("dialog", { name: "Activate this Persona?" }).getByRole("button", { name: "Activate" }).click();
    await expect(statusBadge(page, "Active")).toBeVisible();

    // --- Override the weight for this project; the pill says it is custom,
    // and "Use inherited value" is the one-click way back.
    await page.getByLabel("Project weight override").fill("9");
    await page.getByRole("button", { name: "Set override" }).click();
    await expect(page.getByTestId("effective-weight")).toHaveText("9");
    await expect(page.getByText("Custom", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Use inherited value" }).click();
    await expect(page.getByTestId("effective-weight")).toHaveText("2");
    await expect(page.getByText("Persona's own weight", { exact: true })).toBeVisible();

    // --- Retire, then reactivate (a retired persona keeps its history).
    await page.getByRole("button", { name: "Retire" }).click();
    await page.getByRole("dialog", { name: "Retire this Persona?" }).getByRole("button", { name: "Retire" }).click();
    await expect(statusBadge(page, "Retired")).toBeVisible();
    await expect(page.getByRole("button", { name: "Reactivate" })).toBeVisible();

    // --- The list shows the final status through its label map.
    await page.getByRole("link", { name: "← People", exact: true }).click();
    const row = page.locator("tr", { hasText: personaName });
    await expect(row.getByText("Retired", { exact: true })).toBeVisible();
  });

  test("a child project inherits its parent's weight override and can override it itself", async ({ page }) => {
    const { suffix, org, project, child, adminHeaders } = await setUpOrg(page, "Inherit", true);
    const personaName = `Shared Persona ${suffix}`;
    await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/personas`, {
      headers: adminHeaders,
      data: { name: personaName, weight: 1 },
    });

    // --- Set the override on the parent project only.
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas`);
    await page.getByRole("button", { name: personaName }).click();
    await page.getByLabel("Project weight override").fill("5");
    await page.getByRole("button", { name: "Set override" }).click();
    await expect(page.getByTestId("effective-weight")).toHaveText("5");

    // --- The child names where its value came from, then overrides it.
    await page.goto(`/projects/${child.id}/modules/stakeholders/personas`);
    await page.getByRole("button", { name: personaName }).click();
    await expect(page.getByTestId("effective-weight")).toHaveText("5");
    await expect(page.getByText("Inherited from parent project")).toBeVisible();
    await page.getByLabel("Project weight override").fill("8");
    await page.getByRole("button", { name: "Set override" }).click();
    await expect(page.getByTestId("effective-weight")).toHaveText("8");
    await expect(page.getByText("Custom", { exact: true })).toBeVisible();
  });
});

test.describe("Stakeholders & Personas: organisation Personas and types", () => {
  test("an org Persona is read-only inside a project, and its types are managed in Org Management", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "OrgPersona");
    const personaName = `Org Persona ${suffix}`;
    const typeName = `Edge case ${suffix}`;

    // --- A new org type, added in Org Management > Persona Types.
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Persona Types", "Personas and Stakeholders");
    await expect(page.locator(`input[value="Primary"]`)).toBeVisible();
    await expect(page.locator(`input[value="Secondary"]`)).toBeVisible();
    await expect(page.locator(`input[value="Negative"]`)).toBeVisible();
    await addDefinition(page, "Add Persona type", { Name: typeName });
    await expect(page.getByText("Persona type created.")).toBeVisible();
    await expect(page.locator(`input[value="${typeName}"]`)).toHaveCount(1);

    // --- Create an org-scoped Persona using it, via the API.
    const types: { id: string; name: string }[] = await (
      await page.request.get(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/persona-types`, { headers: adminHeaders })
    ).json();
    const typeId = types.find((t) => t.name === typeName)!.id;
    await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/personas`, {
      headers: adminHeaders,
      data: { name: personaName, persona_type_id: typeId },
    });

    // --- From the project it appears with an Organisation scope badge...
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas`);
    const row = page.locator("tr", { hasText: personaName });
    await expect(row.getByText("Organisation", { exact: true })).toBeVisible();
    await expect(row.getByText(typeName)).toBeVisible();

    // ...and opens read-only, pointing at the org view for edits.
    await page.getByRole("button", { name: personaName }).click();
    await expect(page.getByText(/organisation-wide Persona/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Retire" })).toHaveCount(0);
    await page.getByRole("link", { name: "organisation view" }).click();
    await expect(page).toHaveURL(new RegExp(`/orgs/${org.id}/modules/stakeholders/personas/[^/]+$`));

    // --- In the org view the owner can edit it.
    await expect(page.getByRole("heading", { name: personaName })).toBeVisible();
    await page.getByRole("button", { name: "Edit" }).click();
    const editDialog = page.getByRole("dialog", { name: `Edit ${personaName}` });
    await editDialog.getByLabel("Goals").fill("Keep the audit trail complete.");
    await editDialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Keep the audit trail complete.")).toBeVisible();
  });
});
