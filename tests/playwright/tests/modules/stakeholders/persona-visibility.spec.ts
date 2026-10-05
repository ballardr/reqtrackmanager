import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: docs/plans/module-02-stakeholders-and-personas-plan.md
 * Phase 3b's exit criteria for Personas — a project can hide an organisation
 * Persona from itself (and show it again) without touching the shared record,
 * and a child project inherits its parent's choice but can override it. The
 * Stakeholder half is `stakeholder-visibility.spec.ts`.
 *
 * Each test builds its own disposable org (see `./helpers.ts`), so none depends
 * on seeded state or on another test having run.
 */

async function createOrgPersona(page: Page, orgId: string, headers: Record<string, string>, name: string) {
  const resp = await page.request.post(`${API_BASE_URL}/api/v1/orgs/${orgId}/modules/stakeholders/personas`, { headers, data: { name } });
  expect(resp.ok()).toBeTruthy();
  return (await resp.json()) as { id: string };
}

test.describe("Stakeholders & Personas: project persona visibility", () => {
  test("hides an org Persona from one project, lists it under Show hidden, and shows it again", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "PersonaHide");
    const name = `Hideable Technician ${suffix}`;
    const persona = await createOrgPersona(page, org.id, adminHeaders, name);
    const other = await (
      await page.request.post(`${API_BASE_URL}/api/v1/projects`, {
        headers: adminHeaders, data: { organization_id: org.id, name: `E2E PersonaHide Other ${suffix}`, summary: "" },
      })
    ).json();

    // --- Hide it from the detail page, behind a tier-1 confirm that says nothing is deleted.
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
    await expect(page.getByTestId("project-visibility")).toHaveText("Visible");
    await page.getByRole("button", { name: "Hide from this project" }).click();
    const confirm = page.getByRole("dialog", { name: `Hide ${name} from this project?` });
    await expect(confirm.getByText(/Nothing is deleted/)).toBeVisible();
    await confirm.getByRole("button", { name: "Hide" }).click();
    await expect(page.getByText(`${name} is hidden from this project.`)).toBeVisible();

    // --- It returns to the list, where the Persona is gone...
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/personas$`));
    await expect(page.getByRole("button", { name })).toHaveCount(0);

    // --- ...but another project in the org still sees it.
    await page.goto(`/projects/${other.id}/modules/stakeholders/personas`);
    await expect(page.getByRole("button", { name })).toBeVisible();

    // --- "Show hidden" lists it with who hid it; the row isn't openable, it offers Show.
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas`);
    await page.getByLabel("Show hidden").check();
    const row = page.locator("tr", { hasText: name });
    await expect(row.getByText("Hidden by this project", { exact: true })).toBeVisible();
    await row.getByRole("button", { name: `Show ${name} in this project` }).click();
    await expect(page.getByText(`${name} is shown in this project again.`)).toBeVisible();

    // --- Shown again: it is back in the default list and opens normally.
    await expect(row.getByRole("button", { name: `Show ${name} in this project` })).toHaveCount(0); // list reloaded
    await page.getByLabel("Show hidden").uncheck();
    await page.getByRole("button", { name }).click();
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(page.getByTestId("project-visibility")).toHaveText("Visible");
  });

  test("a child project inherits its parent's hide and can show the Persona itself", async ({ page }) => {
    const { suffix, org, project, child, adminHeaders } = await setUpOrg(page, "PersonaChild", true);
    const name = `Inherited Technician ${suffix}`;
    const persona = await createOrgPersona(page, org.id, adminHeaders, name);
    const parentUrl = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas/${persona.id}/visibility`;
    expect((await page.request.put(parentUrl, { headers: adminHeaders, data: { hidden: true } })).ok()).toBeTruthy();

    // --- The child doesn't list it, but "Show hidden" says the parent hid it.
    await page.goto(`/projects/${child.id}/modules/stakeholders/personas`);
    await expect(page.getByRole("button", { name })).toHaveCount(0);
    await page.getByLabel("Show hidden").check();
    const row = page.locator("tr", { hasText: name });
    await expect(row.getByText("Hidden by a parent project", { exact: true })).toBeVisible();

    // --- Showing it in the child is an override of its own; the parent stays hidden.
    await row.getByRole("button", { name: `Show ${name} in this project` }).click();
    await expect(page.getByText(`${name} is shown in this project again.`)).toBeVisible();
    await expect(row.getByRole("button", { name: `Show ${name} in this project` })).toHaveCount(0); // list reloaded
    await page.getByLabel("Show hidden").uncheck();
    await page.getByRole("button", { name }).click();
    await expect(page.getByTestId("project-visibility")).toHaveText("Shown, although a parent project hides it");

    await page.goto(`/projects/${project.id}/modules/stakeholders/personas`);
    await expect(page.getByRole("button", { name })).toHaveCount(0);

    // --- Reverting the child's override returns it to the parent's decision, so it is hidden again.
    await page.goto(`/projects/${child.id}/modules/stakeholders/personas`);
    await page.getByRole("button", { name }).click();
    await page.getByRole("button", { name: "Use inherited value" }).click();
    await expect(page.getByText("Visibility reverted to the inherited setting.")).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/projects/${child.id}/modules/stakeholders/personas$`));
    await expect(page.getByRole("button", { name })).toHaveCount(0);
  });
});
