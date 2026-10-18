import { expect, test, type Page } from "@playwright/test";

import { chooseRecordAction, installCleanupHook } from "../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: every artefact detail page has one aside with two tabs, Links and Activity. The
 * Activity tab is the record's own timeline (who did what, links added or removed), served by one
 * endpoint whatever the record's type; the version table stays in the page body as "Versions".
 * The selected tab is a per-viewer preference that survives a reload.
 *
 * Builds a disposable org (and so a fresh admin whose tab preference starts at Links), so no other
 * spec's view of the aside depends on what this one selects.
 */
const links = (page: Page) => page.getByRole("region", { name: "Links", exact: true });
const tab = (page: Page, name: "Links" | "Activity") => page.getByRole("tab", { name, exact: true });

test.describe("Aside tabs: Links and Activity", () => {
  test("a requirement's Activity tab lists its history; Versions stay in the body; the tab survives a reload", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "ActivityReq");
    const api = `${API_BASE_URL}/api/v1/projects/${project.id}`;
    const component = await (await page.request.post(`${api}/components`, { headers: adminHeaders, data: { name: "Software", prefix: "SW" } })).json();
    const category = await (
      await page.request.post(`${api}/categories`, { headers: adminHeaders, data: { name: "Performance", prefix: "PERF", component_id: component.id } })
    ).json();
    const name = `Report in 30 seconds ${suffix}`;
    const requirement = await (
      await page.request.post(`${api}/requirements`, { headers: adminHeaders, data: { name, component_id: component.id, category_id: category.id } })
    ).json();
    const me = await (await page.request.get(`${API_BASE_URL}/api/v1/auth/me`, { headers: adminHeaders })).json();
    const edit = await page.request.put(`${api}/requirements/${requirement.id}`, {
      headers: adminHeaders,
      data: {
        name, component_id: component.id, category_id: category.id, owner: { type: "user", id: me.id },
        reasoning: "Users wait too long.", change_note: "Added the reasoning",
      },
    });
    expect(edit.ok(), await edit.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/requirements/${requirement.id}`);

    await test.step("Links is the default tab; the version ledger is a body section", async () => {
      await expect(tab(page, "Links")).toHaveAttribute("aria-selected", "true");
      await expect(links(page)).toBeVisible();
      await expect(page.getByRole("heading", { name: "Versions", level: 2 })).toBeVisible();
      await expect(page.getByRole("cell", { name: "Added the reasoning" })).toBeVisible();
    });

    await test.step("the Activity tab shows the record's own events, newest first", async () => {
      await tab(page, "Activity").click();
      const aside = page.getByRole("complementary");
      await expect(aside.getByText(/updated — Added the reasoning/)).toBeVisible();
      await expect(aside.getByText(/created/)).toBeVisible();
      await expect(links(page)).toBeHidden();
    });

    await test.step("the chosen tab is remembered across a reload", async () => {
      await page.reload();
      await expect(tab(page, "Activity")).toHaveAttribute("aria-selected", "true");
      await expect(page.getByRole("complementary").getByText(/updated — Added the reasoning/)).toBeVisible();
    });

    await test.step("switching back restores the Links panel", async () => {
      await tab(page, "Links").click();
      await expect(links(page)).toBeVisible();
    });
  });

  test("a module record's Activity tab shows its events and the links added to it", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "ActivityPain");
    const enable = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
      headers: adminHeaders, data: { enabled: true },
    });
    expect(enable.ok()).toBeTruthy();
    const api = `${API_BASE_URL}/api/v1/projects/${project.id}`;
    const types = await (await page.request.get(`${api}/modules/context_strategy/pain-point-types`, { headers: adminHeaders })).json();
    const painPoint = await (
      await page.request.post(`${api}/modules/context_strategy/pain-points`, {
        headers: adminHeaders,
        data: {
          title: `Reports arrive late ${suffix}`, description: "d", priority: "high", date_identified: "2026-09-01",
          pain_point_type_id: types[0].id,
        },
      })
    ).json();
    const actionTypes = await (await page.request.get(`${api}/action-types`, { headers: adminHeaders })).json();
    const action = await (
      await page.request.post(`${api}/actions`, { headers: adminHeaders, data: { title: `Review reports ${suffix}`, action_type_id: actionTypes[0].id } })
    ).json();
    const linkTypes = await (await page.request.get(`${API_BASE_URL}/api/v1/orgs/${org.id}/link-types`, { headers: adminHeaders })).json();
    const link = await page.request.post(`${api}/artefacts/pain_point/${painPoint.id}/links`, {
      headers: adminHeaders,
      data: { link_type_id: linkTypes[0].id, direction: "outgoing", other_type: "requirement_action", other_id: action.id },
    });
    expect(link.ok(), await link.text()).toBeTruthy();

    await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points/${painPoint.id}`);
    await tab(page, "Activity").click();
    const aside = page.getByRole("complementary");
    await expect(aside.getByText(/created/)).toBeVisible();
    await expect(aside.getByText(new RegExp(`added a link to .*Review reports ${suffix}`))).toBeVisible();

    await test.step("archiving adds an entry without a reload", async () => {
      await tab(page, "Links").click();
      await chooseRecordAction(page, "Pain Point", "Archive");
      await page.getByRole("dialog", { name: /^Archive this/ }).getByRole("button", { name: "Archive" }).click();
      await tab(page, "Activity").click();
      await expect(aside.getByText(/archived/)).toBeVisible();
    });
  });
});
