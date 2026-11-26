import { expect, test } from "@playwright/test";

import { installCleanupHook, selectOrgAdminGroup, selectProjectAdminGroup } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: Playwright e2e coverage of the Governance screens (`frontend/src/modules/traceability/`) against a real
 * backend: an organisation creates governance profiles and gives them policy, a project sees the profiles that reach it,
 * chooses for an opt-in profile and reads the policy that applies with its source, and the project's governance health
 * is reachable from its navigation and kept in the mode the project chooses.
 *
 * Each test builds its own disposable org (see `../stakeholders/helpers.ts`), so none depends on seeded state or on
 * another test having run.
 */

const MODULE_NAME = "Traceability & Governance";
const orgAdminUrl = (orgId: string) => `/orgs/${orgId}/admin`;
const projectAdminUrl = (projectId: string) => `/projects/${projectId}/admin`;

/** Creates a profile through the Profiles section's New profile dialog and returns once its page is open. */
async function createProfile(page: import("@playwright/test").Page, name: string, mode: "Enforced" | "Default" | "Opt-in") {
  await page.getByRole("button", { name: "New profile" }).click();
  const dialog = page.getByRole("dialog", { name: "New profile" });
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByLabel("Mode").selectOption({ label: mode });
  await dialog.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
}

test.describe("Governance", () => {
  test("an organisation's Enforced profile and its review policy reach a project and the project reads them", async ({ page }) => {
    const { org, project } = await setUpOrg(page, "GovPolicy", false, MODULE_NAME);
    const profileName = `Regulated delivery ${Date.now()}`;

    await test.step("create an Enforced profile in the organisation's Profiles section", async () => {
      await page.goto(orgAdminUrl(org.id));
      await selectOrgAdminGroup(page, "Profiles", "Governance");
      await expect(page.getByText("No governance profiles")).toBeVisible();
      await createProfile(page, profileName, "Enforced");
      await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    });

    await test.step("give the profile a review interval for requirements", async () => {
      await page.getByRole("tab", { name: "Review" }).click();
      await page.getByRole("button", { name: "Actions for Requirement" }).click();
      await page.getByRole("menuitem", { name: "Edit review settings" }).click();
      const dialog = page.getByRole("dialog", { name: "Edit review settings: Requirement" });
      await dialog.getByLabel("Review interval (days)").fill("90");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByRole("row", { name: /Requirement/ }).getByText("90")).toBeVisible();
    });

    await test.step("the profile lists the project it binds", async () => {
      await page.getByRole("tab", { name: "Overview" }).click();
      await expect(page.getByRole("row", { name: new RegExp(project.name) }).getByText("Enforced")).toBeVisible();
    });

    await test.step("the project sees the profile as Enforced with no choice to make", async () => {
      await page.goto(projectAdminUrl(project.id));
      await selectProjectAdminGroup(page, "Profiles", "Governance");
      const row = page.getByRole("row", { name: new RegExp(profileName) });
      await expect(row.getByText("Enforced").first()).toBeVisible();
      await expect(row.getByText("Not a choice")).toBeVisible();
    });

    await test.step("the project's review policy shows the interval", async () => {
      await selectProjectAdminGroup(page, "Review policy", "Governance");
      await expect(page.getByRole("heading", { name: "Review policy", level: 2 })).toBeVisible();
      const row = page.getByRole("row", { name: /Requirement/ });
      await expect(row.getByText("90")).toBeVisible();
    });
  });

  test("a project opts in to an Opt-in profile and opts out of a Default profile", async ({ page }) => {
    const { org, project } = await setUpOrg(page, "GovChoice", false, MODULE_NAME);
    const optIn = `Opt-in profile ${Date.now()}`;
    const byDefault = `Default profile ${Date.now()}`;

    await page.goto(orgAdminUrl(org.id));
    await selectOrgAdminGroup(page, "Profiles", "Governance");
    await createProfile(page, optIn, "Opt-in");
    await page.getByRole("link", { name: "Profiles" }).or(page.getByRole("button", { name: "Profiles" })).first().click();
    await createProfile(page, byDefault, "Default");

    // The chevron beside the profile name switches to another profile without returning to the list.
    await page.getByRole("button", { name: "Switch profile" }).click();
    await page.getByRole("link", { name: optIn }).click();
    await expect(page.getByRole("heading", { name: optIn })).toBeVisible();

    await page.goto(projectAdminUrl(project.id));
    await selectProjectAdminGroup(page, "Profiles", "Governance");

    const optInSwitch = page.getByRole("switch", { name: `${optIn} applies to this project` });
    const defaultSwitch = page.getByRole("switch", { name: `${byDefault} applies to this project` });
    await expect(optInSwitch).not.toBeChecked();
    await expect(defaultSwitch).toBeChecked();

    await optInSwitch.click();
    await expect(page.getByText(`The choice for ${optIn} is saved.`)).toBeVisible();
    await defaultSwitch.click();
    await expect(page.getByText(`The choice for ${byDefault} is saved.`)).toBeVisible();

    await page.reload();
    await expect(page.getByRole("switch", { name: `${optIn} applies to this project` })).toBeChecked();
    await expect(page.getByRole("switch", { name: `${byDefault} applies to this project` })).not.toBeChecked();
  });

  test("the project's governance health is in its navigation and refreshes in a snapshot mode", async ({ page }) => {
    const { org, project, adminHeaders } = await setUpOrg(page, "GovHealth", false, MODULE_NAME);

    await test.step("on demand: the page is reachable from the navigation and offers no refresh", async () => {
      await page.goto(`/projects/${project.id}`);
      await page.getByRole("link", { name: "Governance Health", exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/traceability/health$`));
      await expect(page.getByRole("heading", { name: "Governance Health", level: 1 })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Categories", level: 2 })).toBeVisible();
      await expect(page.getByRole("button", { name: "Refresh now" })).toHaveCount(0);
    });

    await test.step("the organisation default is changed in its Health section", async () => {
      await page.goto(orgAdminUrl(org.id));
      await selectOrgAdminGroup(page, "Health", "Governance");
      await page.getByLabel("Default mode").selectOption({ label: "Snapshot on change" });
      await page.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("The governance health default is saved.")).toBeVisible();
      const saved = await page.request.get(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/traceability/health-defaults`, { headers: adminHeaders });
      expect((await saved.json()).mode).toBe("snapshot_on_change");
    });

    await test.step("a snapshot mode stores figures and Refresh now recomputes them", async () => {
      await page.goto(`/projects/${project.id}/modules/traceability/health`);
      const refresh = page.getByRole("button", { name: "Refresh now" });
      await expect(refresh).toBeVisible();
      await refresh.click();
      await expect(page.getByText("Governance health refreshed.")).toBeVisible();
    });
  });
});
