import { expect, test } from "@playwright/test";

import { API_BASE_URL, setUpOrg } from "../modules/stakeholders/helpers";
import { installCleanupHook, loginAs, logout, PASSWORD } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: see and set who is watching a requirement or change request without a block of
 * controls above the record. Watching is a tab of the Links and Activity card: "Watching" with a (+)
 * when empty, "Watching (n)" with the people and groups when not. A project manager adds a user or a
 * group and removes one; a reader sees the tab only when someone is watching, and cannot change it.
 *
 * Disposable org, admin and project via `setUpOrg`; the people, group and records through the API,
 * the watching through the UI.
 */
test.describe("Watching tab on a requirement and a change request", () => {
  test("a manager adds a user and a group, a reader sees them, and removing a watcher updates the count", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "WatchTab");
    const api = `${API_BASE_URL}/api/v1`;
    const post = async (path: string, data: unknown) => {
      const resp = await page.request.post(`${api}${path}`, { headers: adminHeaders, data });
      expect(resp.ok(), await resp.text()).toBeTruthy();
      const body = await resp.text();
      return body ? JSON.parse(body) : null;
    };
    const personName = `Watch Person ${suffix}`;
    const readerEmail = `e2e-watchtab-reader-${suffix}@example.com`;
    const person = await post(`/orgs/${org.id}/users`, {
      email: `e2e-watchtab-person-${suffix}@example.com`, display_name: personName, password: PASSWORD, role: "member",
    });
    const reader = await post(`/orgs/${org.id}/users`, {
      email: readerEmail, display_name: `Watch Reader ${suffix}`, password: PASSWORD, role: "member",
    });
    await post(`/projects/${project.id}/roles`, { user_id: person.user_id, role: "stakeholder" });
    await post(`/projects/${project.id}/roles`, { user_id: reader.user_id, role: "stakeholder" });
    const groupName = `Watch Group ${suffix}`;
    await post(`/orgs/${org.id}/groups`, { name: groupName });
    const component = await post(`/projects/${project.id}/components`, { name: "Watch", prefix: "WT" });
    const category = await post(`/projects/${project.id}/categories`, { name: "Tab", prefix: "TAB", component_id: component.id });
    const base = await post(`/projects/${project.id}/requirements`, { name: `Watched ${suffix}`, component_id: component.id, category_id: category.id });
    await post(`/projects/${project.id}/requirements/${base.id}/approve`, {});
    const cr = await post(`/projects/${project.id}/change-requests`, {
      kind: "modify_requirement", requirement_id: base.id, changed_fields: ["name"], proposed_name: `Watched v2 ${suffix}`, reason: "Watching",
    });
    await post(`/projects/${project.id}/change-requests/${cr.id}/submit`, {});

    for (const path of [`/projects/${project.id}/requirements/${base.id}`, `/projects/${project.id}/change-requests/${cr.id}`]) {
      await page.goto(path);

      // --- Nothing watching: a plain tab, no permanent picker or explanation on the page.
      await page.getByRole("tab", { name: "Watching", exact: true }).click();
      await expect(page.getByText("No one is watching.")).toBeVisible();
      await expect(page.getByRole("combobox", { name: "Add watching user or group" })).toHaveCount(0);

      // --- A user, then a group, from the (+) popover; the count follows.
      await page.getByRole("button", { name: "Add watching user or group" }).click();
      await page.getByRole("combobox", { name: "Add watching user or group" }).fill(personName);
      await page.getByRole("option", { name: new RegExp(personName) }).click();
      await expect(page.getByRole("tab", { name: "Watching (1)" })).toBeVisible();
      await page.getByRole("button", { name: "Add watching user or group" }).click();
      await page.getByRole("combobox", { name: "Add watching user or group" }).fill("Watch Group");
      await page.getByRole("option", { name: new RegExp(groupName) }).click();
      const panel = page.getByRole("tabpanel", { name: "Watching (2)" });
      await expect(panel.getByText(personName)).toBeVisible();
      await expect(panel.getByText(groupName)).toBeVisible();

      // --- A reader sees who is watching, with no way to change it.
      await logout(page);
      await loginAs(page, readerEmail, PASSWORD);
      await page.goto(path);
      await page.getByRole("tab", { name: "Watching (2)" }).click();
      const readerPanel = page.getByRole("tabpanel", { name: "Watching (2)" });
      await expect(readerPanel.getByText(personName)).toBeVisible();
      await expect(page.getByRole("button", { name: "Add watching user or group" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /^Stop watching/ })).toHaveCount(0);

      // --- Back as the manager: remove one, the count drops; remove the last, the reader loses the tab.
      await logout(page);
      await loginAs(page, `e2e-watchtab-admin-${suffix}@example.com`, PASSWORD);
      await page.goto(path);
      await page.getByRole("tab", { name: "Watching (2)" }).click();
      await page.getByRole("button", { name: `Stop watching: ${personName}` }).click();
      await expect(page.getByRole("tab", { name: "Watching (1)" })).toBeVisible();
      await page.getByRole("button", { name: `Stop watching: ${groupName}` }).click();
      await expect(page.getByRole("tab", { name: "Watching", exact: true })).toBeVisible();
      await logout(page);
      await loginAs(page, readerEmail, PASSWORD);
      await page.goto(path);
      await expect(page.getByRole("tab", { name: /^Links/ })).toBeVisible();
      await expect(page.getByRole("tab", { name: /^Watching/ })).toHaveCount(0);
      await logout(page);
      await loginAs(page, `e2e-watchtab-admin-${suffix}@example.com`, PASSWORD);
    }
  });
});
