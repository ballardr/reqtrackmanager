import { expect, test } from "@playwright/test";

import { installCleanupHook, PASSWORD, selectOrgAdminGroup } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg, statusBadge } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: docs/plans/module-02-stakeholders-and-personas-plan.md
 * Phase 1.2's exit criteria — Playwright e2e coverage for the Stakeholder UI
 * (`frontend/src/modules/stakeholders/`) against a real backend: create with
 * Influence/Interest and a cadence (with the suggestion hint), activate, link
 * Personas from both ends, add from an org user, org records read-only in a
 * project, the admin sections, and permanent deletion behind a tier-2 confirm.
 *
 * Each test builds its own disposable org (see `./helpers.ts`), so none depends
 * on seeded state or on another test having run.
 */

test.describe("Stakeholders & Personas: Stakeholder lifecycle", () => {
  test("creates a Stakeholder with levels and a cadence hint, activates it, and shows its position", async ({ page }) => {
    const { suffix, project } = await setUpOrg(page, "Stakeholder");
    const name = `Pat Regulator ${suffix}`;

    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Stakeholders", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/stakeholders$`));

    // --- Create (a Modal layer): the hint appears once both levels are set, and never sets the cadence.
    await page.getByRole("button", { name: "New Stakeholder" }).click();
    const dialog = page.getByRole("dialog", { name: "New Stakeholder (project)" });
    await dialog.getByLabel("Stakeholder name").fill(name);
    await dialog.getByLabel("Type").selectOption({ label: "Regulator" });
    await dialog.getByLabel("Role", { exact: true }).fill("Compliance auditor");
    await dialog.getByLabel("Contact / reference information").fill("pat@authority.example.com");
    await dialog.getByLabel("Influence", { exact: true }).selectOption({ label: "High" });
    await dialog.getByLabel("Interest", { exact: true }).selectOption({ label: "High" });
    await expect(dialog.getByTestId("cadence-hint")).toContainText("Suggested: Monthly (Manage closely)");
    await expect(dialog.getByLabel("Target engagement cadence")).toHaveValue("");
    await dialog.getByLabel("Target engagement cadence").selectOption({ label: "Quarterly" });
    await dialog.getByRole("button", { name: "Save" }).click();

    // --- The list renders label-mapped values, not wire values.
    const row = page.locator("tr", { hasText: name });
    await expect(row.getByText("Regulator", { exact: true })).toBeVisible();
    await expect(row.getByText("Quarterly", { exact: true })).toBeVisible();
    await expect(row.getByText("Draft", { exact: true })).toBeVisible();

    await page.getByRole("button", { name }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/stakeholders/[^/]+$`));
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(statusBadge(page, "Draft")).toBeVisible();
    await expect(page.getByText("pat@authority.example.com")).toBeVisible();
    await expect(page.getByTestId("grid-position")).toHaveText("Influence: High · Interest: High · Manage closely");
    await expect(page.getByTestId("cadence")).toContainText("Target cadence: Quarterly (suggested by their position: Monthly)");

    // --- Activate behind a confirm dialog; no approval step.
    await page.getByRole("button", { name: "Activate" }).click();
    await page.getByRole("dialog", { name: "Activate this Stakeholder?" }).getByRole("button", { name: "Activate" }).click();
    await expect(statusBadge(page, "Active")).toBeVisible();

    // --- Edit as a layer; the change becomes a new version.
    await page.getByRole("button", { name: "Edit" }).click();
    const edit = page.getByRole("dialog", { name: `Edit ${name}` });
    await edit.getByLabel("Priorities").fill("Safety first.");
    await edit.getByLabel("Change note").fill("Added priorities");
    await edit.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Safety first.")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Version history" })).toBeVisible();
    await expect(page.getByText("Added priorities")).toBeVisible();
  });

  test("links Personas from the Stakeholder and sees the link from the Persona", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "Represents");
    const stakeholderName = `Sam Sponsor ${suffix}`;
    const personaName = `Field Technician ${suffix}`;
    const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders`;
    await page.request.post(`${base}/personas`, { headers: adminHeaders, data: { name: personaName } });
    const stakeholder = await (await page.request.post(`${base}/stakeholders`, { headers: adminHeaders, data: { name: stakeholderName } })).json();

    // --- Add the link from the Stakeholder's page.
    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders/${stakeholder.id}`);
    await expect(page.getByText("This Stakeholder doesn't represent any Persona yet.")).toBeVisible();
    await page.getByLabel("Persona to represent").selectOption({ label: personaName });
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByText("Link added.")).toBeVisible();
    await expect(page.getByRole("link", { name: personaName })).toBeVisible();

    // --- The Persona's page lists the Stakeholder, read-only.
    await page.getByRole("link", { name: personaName }).click();
    await expect(page.getByRole("heading", { name: personaName })).toBeVisible();
    await expect(page.getByRole("link", { name: stakeholderName })).toBeVisible();
    await expect(page.getByLabel("Persona to represent")).toHaveCount(0);

    // --- Remove it again from the Stakeholder's side, behind a tier-1 confirm.
    await page.getByRole("link", { name: stakeholderName }).click();
    await page.getByRole("button", { name: `Remove ${personaName}` }).click();
    await page.getByRole("dialog", { name: `Remove ${personaName}?` }).getByRole("button", { name: "Remove" }).click();
    await expect(page.getByText("Link removed.")).toBeVisible();
    await expect(page.getByText("This Stakeholder doesn't represent any Persona yet.")).toBeVisible();
  });

  test("adds a Stakeholder from an organisation user, once", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "FromUser");
    const email = `colleague-${suffix}@example.com`;
    const created = await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
      headers: adminHeaders,
      data: { email, display_name: `Casey Colleague ${suffix}`, password: PASSWORD, role: "member" },
    });
    expect(created.ok()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders`);
    await page.getByRole("button", { name: "Add from org user" }).click();
    const dialog = page.getByRole("dialog", { name: "Add Stakeholder from organisation user (project)" });
    await dialog.getByLabel("Organisation user").fill(`Casey Colleague ${suffix}`);
    await dialog.getByText(`Casey Colleague ${suffix}`).first().click();
    await dialog.getByLabel("Role", { exact: true }).fill("Product owner");
    await dialog.getByRole("button", { name: "Add Stakeholder" }).click();
    await expect(page.getByText("Stakeholder created from user.")).toBeVisible();

    // The name and email were prefilled from the account.
    await page.getByRole("button", { name: `Casey Colleague ${suffix}` }).click();
    await expect(page.getByText(email)).toBeVisible();
    await expect(page.getByText("Platform user")).toBeVisible();

    // A second attempt for the same user is refused with a visible message.
    await page.getByRole("link", { name: "← Stakeholders" }).click();
    await page.getByRole("button", { name: "Add from org user" }).click();
    const again = page.getByRole("dialog", { name: "Add Stakeholder from organisation user (project)" });
    await again.getByLabel("Organisation user").fill(`Casey Colleague ${suffix}`);
    await again.getByText(`Casey Colleague ${suffix}`).first().click();
    await again.getByRole("button", { name: "Add Stakeholder" }).click();
    await expect(again.getByText("A Stakeholder already represents this user.")).toBeVisible();
  });

  test("permanently deletes a Stakeholder only after typing its exact name", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "Erase");
    const name = `Leaving Person ${suffix}`;
    const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders`;
    const stakeholder = await (
      await page.request.post(`${base}/stakeholders`, { headers: adminHeaders, data: { name, contact_info: "leaving@example.com" } })
    ).json();

    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders/${stakeholder.id}`);
    await page.getByRole("button", { name: "Delete permanently" }).click();
    const dialog = page.getByRole("dialog", { name: `Permanently delete ${name}?` });
    await expect(dialog.getByText(/This cannot be undone/)).toBeVisible();
    const confirm = dialog.getByRole("button", { name: "Delete permanently" });
    await expect(confirm).toBeDisabled();
    await dialog.getByPlaceholder(name).fill("not the name");
    await expect(confirm).toBeDisabled();
    await dialog.getByPlaceholder(name).fill(name);
    await confirm.click();

    await expect(page.getByText("Stakeholder permanently deleted.")).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/stakeholders$`));
    await expect(page.getByRole("button", { name })).toHaveCount(0);
    expect((await page.request.get(`${base}/stakeholders/${stakeholder.id}`, { headers: adminHeaders })).status()).toBe(404);
  });
});

test.describe("Stakeholders & Personas: organisation Stakeholders, types and scoring", () => {
  test("an org Stakeholder is read-only inside a project; types and scoring are configured in Org Management", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "OrgStakeholder");
    const name = `Org Stakeholder ${suffix}`;
    const typeName = `Investor ${suffix}`;

    // --- A new org type, added in Org Management > Stakeholder Types.
    await page.goto(`/orgs/${org.id}/admin`);
    await selectOrgAdminGroup(page, "Stakeholder Types");
    await expect(page.locator(`input[value="Customer"]`)).toBeVisible();
    await expect(page.locator(`input[value="Regulator"]`)).toBeVisible();
    await page.getByPlaceholder("Stakeholder type name").fill(typeName);
    await page.getByRole("button", { name: "Add Stakeholder type" }).click();
    await expect(page.getByText("Stakeholder type created.")).toBeVisible();
    await expect(page.locator(`input[value="${typeName}"]`)).toHaveCount(1);

    // --- Influence and Interest levels are configurable under Stakeholder Scoring.
    await selectOrgAdminGroup(page, "Stakeholder Scoring");
    await expect(page.getByText("Influence", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Interest", { exact: true }).first()).toBeVisible();

    // --- Create an org-scoped Stakeholder using the new type, via the API.
    const types: { id: string; name: string }[] = await (
      await page.request.get(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/stakeholder-types`, { headers: adminHeaders })
    ).json();
    await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/stakeholders`, {
      headers: adminHeaders,
      data: { name, stakeholder_type_id: types.find((t) => t.name === typeName)!.id },
    });

    // --- From the project it appears with an Organisation scope badge, and opens read-only.
    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders`);
    const row = page.locator("tr", { hasText: name });
    await expect(row.getByText("Organisation", { exact: true })).toBeVisible();
    await expect(row.getByText(typeName)).toBeVisible();
    await page.getByRole("button", { name }).click();
    await expect(page.getByText(/organisation-wide Stakeholder/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Delete permanently" })).toHaveCount(0);
    await page.getByRole("link", { name: "organisation view" }).click();
    await expect(page).toHaveURL(new RegExp(`/orgs/${org.id}/modules/stakeholders/stakeholders/[^/]+$`));

    // --- In the org view the owner can edit it.
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await page.getByRole("button", { name: "Edit" }).click();
    const editDialog = page.getByRole("dialog", { name: `Edit ${name}` });
    await editDialog.getByLabel("Priorities").fill("Keep the audit trail complete.");
    await editDialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Keep the audit trail complete.")).toBeVisible();
  });
});
