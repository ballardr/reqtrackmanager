import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { chooseColumn, resetColumns } from "../../columnChooser";
import { installCleanupHook } from "../../e2e-workflows/helpers";
import { chooseExport } from "../../listActions";
import { API_BASE_URL, openPeople, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done:
 * A person scanning the People list needs the names readable. The Name column keeps a readable width, Scope is
 * not drawn until chosen (an organisation record is already told apart by its code prefix), and the columns a
 * person chooses are remembered. Choosing columns changes the screen only: Sort by still offers a hidden column
 * and the export still carries it.
 *
 * Each test builds its own disposable org (see `./helpers.ts`), so none depends on seeded state.
 */

test.describe("Stakeholders & Personas: People list columns", () => {
  test("Scope is chosen not default, is remembered, resets, and never changes Sort by or the export", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "PeopleColumns");
    const projectName = `Launch-site customers ${suffix}`;
    const orgName = `Compliance Auditor ${suffix}`;
    const base = `${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders`;
    expect((await page.request.post(`${base}/personas`, { headers: adminHeaders, data: { name: projectName } })).ok()).toBeTruthy();
    expect((await page.request.post(`${base}/stakeholders`, { headers: adminHeaders, data: { name: `Pat Regulator ${suffix}` } })).ok()).toBeTruthy();
    expect((await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/personas`, { headers: adminHeaders, data: { name: orgName } })).ok()).toBeTruthy();

    await openPeople(page, project.id);
    const table = page.getByRole("table", { name: "People" });
    await expect(table.getByText(projectName)).toBeVisible();
    // The export menu groups by kind once every kind has loaded; its Stakeholders chip carries the count.
    await expect(page.getByRole("group", { name: "Kinds of record" }).getByRole("button", { name: /^Stakeholders 1/ })).toBeVisible();

    // --- By default Scope is not a column; the always-on and the other optional columns are.
    for (const header of ["Name", "Code", "Kind", "Details", "Type", "Status"]) await expect(table.getByRole("columnheader", { name: header })).toBeVisible();
    await expect(table.getByRole("columnheader", { name: "Scope" })).toHaveCount(0);

    // --- Name keeps at least its floor width (12rem) beside every other column.
    const nameWidth = (await table.getByRole("columnheader", { name: "Name" }).boundingBox())!.width;
    expect(nameWidth).toBeGreaterThanOrEqual(12 * 16 - 1);

    // --- Hidden or not, Scope stays a Sort by choice, and the export carries it.
    await expect(page.getByLabel("Sort by").locator("option", { hasText: "Scope" })).toHaveCount(1);
    const download = page.waitForEvent("download");
    await chooseExport(page, "CSV", "Personas");
    const csv = fs.readFileSync((await (await download).path())!, "utf-8");
    expect(csv.split("\n")[0]).toContain("scope");
    expect(csv).toContain(orgName);

    // --- Choosing Scope shows it, and a reload keeps the choice (it is stored with the person, not the tab).
    const saved = page.waitForResponse((r) => r.url().includes("/auth/me") && r.request().method() === "PATCH");
    await chooseColumn(page, "Scope");
    await saved;
    await expect(table.getByRole("columnheader", { name: "Scope" })).toBeVisible();
    await expect(table.locator("tr", { hasText: orgName }).getByText("Organisation", { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("table", { name: "People" }).getByRole("columnheader", { name: "Scope" })).toBeVisible();

    // --- The reset returns to the defaults.
    await resetColumns(page);
    await expect(page.getByRole("table", { name: "People" }).getByRole("columnheader", { name: "Scope" })).toHaveCount(0);
    await expect(page.getByRole("table", { name: "People" }).getByRole("columnheader", { name: "Kind" })).toBeVisible();
  });

  test("a narrow list drops the optional columns, keeps Name, Code and Status, and gets them back when the filters collapse", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "PeopleNarrow");
    const name = `Launch-site customers ${suffix}`;
    expect((await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas`, { headers: adminHeaders, data: { name } })).ok()).toBeTruthy();

    await page.setViewportSize({ width: 1000, height: 900 });
    await openPeople(page, project.id);
    const table = page.getByRole("table", { name: "People" });
    await expect(table.getByText(name)).toBeVisible();
    // With the filter panel beside it the list has under 40rem of room.
    const room = () => page.locator(".directory-table-scroll--responsive").evaluate((el) => el.clientWidth);
    expect(await room()).toBeLessThan(40 * 16);
    for (const header of ["Name", "Code", "Status"]) await expect(table.getByRole("columnheader", { name: header })).toBeVisible();
    for (const header of ["Kind", "Details"]) await expect(table.getByRole("columnheader", { name: header })).toHaveCount(0);

    // --- Collapsing the filter panel gives the list the room, and the columns return.
    await page.getByRole("button", { name: "Collapse filters" }).click();
    await expect.poll(room).toBeGreaterThanOrEqual(40 * 16);
    for (const header of ["Kind", "Details"]) await expect(table.getByRole("columnheader", { name: header })).toBeVisible();
  });
});
