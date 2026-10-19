import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, openNew, openPeople, setUpOrg, statusBadge } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done:
 * Personas, Stakeholders, Needs and Groups are one list ("People") with one New menu, so a person
 * designing for or with people finds them in one place. A record created with "Save and activate" is
 * active at once, created and activated in one step; Save leaves it a draft. The old per-type list
 * routes still work, and a kind whose sub-component is off disappears from the page, the New menu and,
 * when all are off, the nav rail.
 *
 * Each test builds its own disposable org (see `./helpers.ts`), so none depends on seeded state or on
 * another test having run.
 */

test.describe("Stakeholders & Personas: People page", () => {
  test("lists every kind together, narrows by kind chip, and shows a kind's own columns when alone", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "People");
    const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders`;
    const names = {
      persona: `Field Technician ${suffix}`,
      stakeholder: `Pat Regulator ${suffix}`,
      need: `Offline access ${suffix}`,
      group: `Suppliers ${suffix}`,
    };
    await page.request.post(`${base}/personas`, { headers: adminHeaders, data: { name: names.persona } });
    await page.request.post(`${base}/stakeholders`, { headers: adminHeaders, data: { name: names.stakeholder } });
    await page.request.post(`${base}/needs`, { headers: adminHeaders, data: { name: names.need } });
    await page.request.post(`${base}/stakeholder-groups`, { headers: adminHeaders, data: { name: names.group } });

    await openPeople(page, project.id);
    const table = page.getByRole("table", { name: "People" });
    for (const name of Object.values(names)) await expect(table.getByText(name)).toBeVisible();
    // The Kind column goes through its label map.
    const row = table.locator("tr", { hasText: names.need });
    await expect(row.getByText("Stakeholder Need", { exact: true })).toBeVisible();

    // --- Chips narrow the list and write the choice into the URL.
    const chips = page.getByRole("group", { name: "Kinds of record" });
    await chips.getByRole("button", { name: /^Needs/ }).click();
    await chips.getByRole("button", { name: /^Groups/ }).click();
    await expect(page).toHaveURL(/\?kind=persona(,|%2C)stakeholder$/);
    await expect(table.getByText(names.need)).toHaveCount(0);
    await expect(table.getByText(names.persona)).toBeVisible();
    await expect(table.getByText(names.stakeholder)).toBeVisible();

    // --- One kind alone is that kind's own list, with its own columns and filters.
    await chips.getByRole("button", { name: /^Personas/ }).click();
    await expect(page).toHaveURL(/\?kind=stakeholder$/);
    const own = page.getByRole("table", { name: "Stakeholders" });
    await expect(own.getByRole("columnheader", { name: "Influence" })).toBeVisible();
    await expect(own.getByRole("columnheader", { name: "Last engaged" })).toBeVisible();
    await expect(page.getByLabel("Group by")).toBeVisible();

    // --- The last kind cannot be turned off.
    await chips.getByRole("button", { name: /^Stakeholders/ }).click();
    await expect(chips.getByRole("button", { name: /^Stakeholders/ })).toHaveAttribute("aria-pressed", "true");

    // --- A row opens its own detail page.
    await own.getByRole("button", { name: names.stakeholder }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/stakeholders/[^/]+$`));
  });

  test("Save and activate creates an active record in one step; Save leaves a draft", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "Activate");
    const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders`;
    const activeName = `Active Persona ${suffix}`;
    const draftName = `Draft Persona ${suffix}`;

    await openPeople(page, project.id, "persona");

    await openNew(page, "Persona");
    let dialog = page.getByRole("dialog", { name: "New Persona (project)" });
    await dialog.getByLabel("Persona name").fill(activeName);
    await dialog.getByRole("button", { name: "Save and activate" }).click();
    await expect(page.getByText("Persona created.")).toBeVisible();

    await openNew(page, "Persona");
    dialog = page.getByRole("dialog", { name: "New Persona (project)" });
    await dialog.getByLabel("Persona name").fill(draftName);
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("button", { name: draftName })).toBeVisible();

    // --- The list renders the label-mapped statuses.
    await expect(page.locator("tr", { hasText: activeName }).getByText("Active", { exact: true })).toBeVisible();
    await expect(page.locator("tr", { hasText: draftName }).getByText("Draft", { exact: true })).toBeVisible();

    // --- The active one went draft -> active in the same request: two versions, the second active.
    const personas: { id: string; name: string }[] = await (await page.request.get(`${base}/personas`, { headers: adminHeaders })).json();
    const active = personas.find((p) => p.name === activeName)!;
    const versions: { status: string }[] = await (await page.request.get(`${base}/personas/${active.id}/versions`, { headers: adminHeaders })).json();
    expect(versions.map((v) => v.status).sort()).toEqual(["active", "draft"]);

    // --- Its page shows it Active, with no Activate step left.
    await page.getByRole("button", { name: activeName }).click();
    await expect(statusBadge(page, "Active")).toBeVisible();
    await expect(page.getByRole("button", { name: "Activate", exact: true })).toHaveCount(0);
  });

  test("Save and activate is on every create form that can activate, and not on edit", async ({ page }) => {
    const { suffix, project } = await setUpOrg(page, "ActivateForms");
    await openPeople(page, project.id);

    for (const [item, dialogName, nameLabel] of [
      ["Stakeholder", "New Stakeholder (project)", "Stakeholder name"],
      ["Stakeholder Need", "New Stakeholder Need", "Need name"],
    ] as const) {
      await openNew(page, item);
      const dialog = page.getByRole("dialog", { name: dialogName });
      await dialog.getByLabel(nameLabel).fill(`${item} ${suffix}`);
      await dialog.getByRole("button", { name: "Save and activate" }).click();
      await expect(page.getByRole("dialog")).toHaveCount(0);
    }
    const table = page.getByRole("table", { name: "People" });
    for (const item of ["Stakeholder", "Stakeholder Need"]) {
      await expect(table.locator("tr", { hasText: `${item} ${suffix}` }).getByText("Active", { exact: true })).toBeVisible();
    }

    // A group has no lifecycle, so its form has no such button.
    await openNew(page, "Stakeholder Group");
    await expect(page.getByRole("dialog").getByRole("button", { name: "Save and activate" })).toHaveCount(0);
  });

  test("the old per-type list routes redirect to the People page with that kind selected", async ({ page }) => {
    const { project } = await setUpOrg(page, "Redirect");
    for (const [route, kind] of [["personas", "persona"], ["stakeholders", "stakeholder"], ["needs", "need"]] as const) {
      await page.goto(`/projects/${project.id}/modules/stakeholders/${route}`);
      await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/people\\?kind=${kind}$`));
    }
  });

  test("a kind whose sub-component is off leaves the page and the New menu; all off removes People from the nav", async ({ page }) => {
    const { project, adminHeaders } = await setUpOrg(page, "SubComponents");
    const sub = (key: string, enabled: boolean) =>
      page.request.put(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/subcomponents/${key}`, {
        headers: adminHeaders,
        data: { enabled },
      });

    expect((await sub("stakeholder_need", false)).ok()).toBeTruthy();
    await openPeople(page, project.id);
    const chips = page.getByRole("group", { name: "Kinds of record" });
    await expect(chips.getByRole("button", { name: /^Personas/ })).toBeVisible();
    await expect(chips.getByRole("button", { name: /^Needs/ })).toHaveCount(0);
    await page.getByRole("button", { name: "New", exact: true }).click();
    await expect(page.getByRole("menuitem", { name: "Persona", exact: true })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Stakeholder Need", exact: true })).toHaveCount(0);
    await page.keyboard.press("Escape");

    // With every sub-component People serves switched off, its nav entry goes; Engagements stays.
    expect((await sub("persona", false)).ok()).toBeTruthy();
    expect((await sub("stakeholder", false)).ok()).toBeTruthy();
    await page.goto(`/projects/${project.id}`);
    await expect(page.getByRole("link", { name: "Engagements", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "People", exact: true })).toHaveCount(0);
  });
});
