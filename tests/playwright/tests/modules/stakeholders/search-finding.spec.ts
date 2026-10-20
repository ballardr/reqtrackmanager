import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./helpers";

// Deletes this file's disposable org after the test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a research finding has no page of its own, so finding one through the global search lands
 * the person on the engagement it came from, and an organisation-owned persona is found and opened through a
 * project that shows it.
 *
 * Builds its own organisation, project and records through the API (see `./helpers.ts`), with run-unique words.
 */
test.describe("global search: Stakeholders & Personas records", () => {
  test("a finding opens its engagement, and a shared persona is found", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "SearchFind");
    const base = `${API_BASE_URL}/api/v1`;
    const word = `ergonomics${suffix.toString(36)}`;

    const extras = await page.request.put(`${base}/orgs/${org.id}/modules/stakeholders/subcomponents/research_extras`, {
      headers: adminHeaders, data: { enabled: true },
    });
    expect(extras.ok(), await extras.text()).toBeTruthy();
    const today = new Date().toISOString().slice(0, 10);
    const engagement = await (
      await page.request.post(`${base}/projects/${project.id}/modules/stakeholders/engagements`, {
        headers: adminHeaders, data: { title: `Discovery session ${suffix}`, channel: "meeting", engagement_date: today },
      })
    ).json();
    const finding = await page.request.post(
      `${base}/projects/${project.id}/modules/stakeholders/engagements/${engagement.id}/findings`,
      { headers: adminHeaders, data: { title: `Poor ${word} on the handset` } },
    );
    expect(finding.ok(), await finding.text()).toBeTruthy();
    const persona = await page.request.post(`${base}/orgs/${org.id}/modules/stakeholders/personas`, {
      headers: adminHeaders, data: { name: `Shared ${word} reviewer`, description: "e2e" },
    });
    expect(persona.ok(), await persona.text()).toBeTruthy();

    await page.goto(`/search?q=${word}`);
    const findingLink = page.getByRole("link", { name: /Poor.*on the handset/ });
    await expect(findingLink).toBeVisible();
    await expect(page.getByRole("link", { name: /Shared.*reviewer/ })).toBeVisible();
    // The persona belongs to the organisation, so its code is qualified by the organisation's.
    await expect(page.getByText("Organisation record")).toBeVisible();

    await findingLink.click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/engagements/${engagement.id}$`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(`Discovery session ${suffix}`);
  });
});
