import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook, selectOrgOverviewGroup } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: docs/plans/module-02-stakeholders-and-personas-plan.md
 * Phase 3c's exit criteria — stakeholders can be classified into a tree of
 * groups (several at once, nested, "one branch per stakeholder" where a group
 * behaves like a single column), managed from the organisation overview and
 * from a project, and the Stakeholder list can filter and group by them.
 * Each test builds its own disposable org (see `./helpers.ts`).
 */

type Headers = Record<string, string>;

const orgBase = (orgId: string) => `${API_BASE_URL}/api/v1/orgs/${orgId}/modules/stakeholders`;

async function post<T>(page: Page, url: string, headers: Headers, data: object): Promise<T> {
  const resp = await page.request.post(url, { headers, data });
  expect(resp.ok(), await resp.text()).toBeTruthy();
  return (await resp.json().catch(() => ({}))) as T;
}

const createStakeholder = (page: Page, orgId: string, headers: Headers, name: string) =>
  post<{ id: string }>(page, `${orgBase(orgId)}/stakeholders`, headers, { name });

const createGroup = (page: Page, orgId: string, headers: Headers, name: string, parent?: string, exclusive = false) =>
  post<{ id: string }>(page, `${orgBase(orgId)}/stakeholder-groups`, headers, {
    name, parent_group_id: parent ?? null, exclusive_children: exclusive,
  });

const addMember = (page: Page, orgId: string, headers: Headers, groupId: string, stakeholderId: string) =>
  post(page, `${orgBase(orgId)}/stakeholder-groups/${groupId}/members`, headers, { stakeholder_id: stakeholderId });

async function openOrgGroups(page: Page) {
  await page.goto("/org-overview");
  await selectOrgOverviewGroup(page, "Stakeholder Groups");
}

test.describe("Stakeholders & Personas: Stakeholder groups", () => {
  test("builds a nested tree in the organisation overview, edits it and deletes a group keeping its stakeholder", async ({ page }) => {
    const { suffix, org, adminHeaders } = await setUpOrg(page, "GroupTree");
    const client = `Client ${suffix}`;
    const acme = `Acme ${suffix}`;
    const person = await createStakeholder(page, org.id, adminHeaders, `Alex ${suffix}`);

    await openOrgGroups(page);
    await expect(page.getByText(/No Stakeholder groups yet/)).toBeVisible();

    // --- Create a top-level group flagged "one branch per stakeholder", then a child under it.
    await page.getByRole("button", { name: "New group" }).click();
    let dialog = page.getByRole("dialog", { name: "New Stakeholder group" });
    await dialog.getByLabel("Group name").fill(client);
    await dialog.getByLabel("One branch per stakeholder").check();
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Group created.")).toBeVisible();
    await expect(page.getByText("One branch", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: `Add a group under ${client}` }).click();
    dialog = page.getByRole("dialog", { name: "New Stakeholder group" });
    await expect(dialog.getByLabel("Parent group")).toHaveValue(/.+/);
    await dialog.getByLabel("Group name").fill(acme);
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("button", { name: acme, exact: true })).toBeVisible();

    // --- A sibling name clash is rejected in the dialog, which stays open.
    await page.getByRole("button", { name: `Add a group under ${client}` }).click();
    dialog = page.getByRole("dialog", { name: "New Stakeholder group" });
    await dialog.getByLabel("Group name").fill(acme.toUpperCase());
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(dialog.getByText(/already exists here/)).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();

    // --- Rename it, and add a stakeholder to it from the members section.
    await page.getByRole("button", { name: `Edit ${acme}` }).click();
    dialog = page.getByRole("dialog", { name: `Edit ${acme}` });
    await dialog.getByLabel("Group name").fill(`${acme} Ltd`);
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Group updated.")).toBeVisible();
    await page.getByRole("button", { name: `${acme} Ltd`, exact: true }).click();
    const members = page.getByRole("region", { name: `Members of ${acme} Ltd` });
    await expect(members.getByText("No stakeholders in this group yet.")).toBeVisible();
    await members.getByLabel("Stakeholder to add").selectOption({ label: `Alex ${suffix}` });
    await members.getByRole("button", { name: "Add" }).click();
    await expect(page.getByText("Added to the group.")).toBeVisible();
    await expect(members.getByText(`Alex ${suffix}`)).toBeVisible();

    // --- Deleting the parent states what goes, keeps the child (moved up) and the stakeholder.
    await page.getByRole("button", { name: `Delete ${client}` }).click();
    const confirm = page.getByRole("dialog", { name: `Delete ${client}?` });
    await expect(confirm.getByText(/moves its 1 child group up one level\. No stakeholder is deleted/)).toBeVisible();
    await confirm.getByRole("button", { name: "Delete group" }).click();
    await expect(page.getByText("Group deleted.")).toBeVisible();
    await expect(page.getByRole("button", { name: client, exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: `${acme} Ltd`, exact: true })).toBeVisible();

    const listed = await (await page.request.get(`${orgBase(org.id)}/stakeholders`, { headers: adminHeaders })).json();
    expect(listed.map((s: { name: string }) => s.name)).toContain(`Alex ${suffix}`);
    expect(listed[0].groups.map((g: { name: string }) => g.name)).toEqual([`${acme} Ltd`]);
    expect(person.id).toBe(listed[0].id);
  });

  test("puts a stakeholder in several groups from its detail page, and 'one branch' refuses a second branch", async ({ page }) => {
    const { suffix, org, adminHeaders } = await setUpOrg(page, "GroupMulti");
    const person = await createStakeholder(page, org.id, adminHeaders, `Multi ${suffix}`);
    const clientRoot = await createGroup(page, org.id, adminHeaders, `Client ${suffix}`, undefined, true);
    await createGroup(page, org.id, adminHeaders, `North ${suffix}`, clientRoot.id);
    await createGroup(page, org.id, adminHeaders, `South ${suffix}`, clientRoot.id);
    await createGroup(page, org.id, adminHeaders, `Operations ${suffix}`);

    await page.goto(`/orgs/${org.id}/modules/stakeholders/stakeholders/${person.id}`);
    await expect(page.getByText("Not in any group.")).toBeVisible();

    // --- Two groups in different roots are fine and are saved together.
    await page.getByRole("button", { name: "Organisation groups" }).click();
    await page.getByRole("checkbox", { name: `North ${suffix}`, exact: true }).check();
    await page.getByRole("checkbox", { name: `Operations ${suffix}`, exact: true }).check();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Save groups" }).click();
    await expect(page.getByText("Groups updated.")).toBeVisible();
    await expect(page.locator("span.badge", { hasText: `North ${suffix}` })).toBeVisible();
    await expect(page.locator("span.badge", { hasText: `Operations ${suffix}` })).toBeVisible();

    // --- Adding a second branch of the exclusive Client group is refused, naming the branch they are already in.
    await page.getByRole("button", { name: "Organisation groups" }).click();
    await page.getByRole("checkbox", { name: `South ${suffix}`, exact: true }).check();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Save groups" }).click();
    await expect(page.getByText(new RegExp(`already in 'North ${suffix}'`))).toBeVisible();
    // The refused change saved nothing: still only the original two badges.
    await page.reload();
    await expect(page.locator("span.badge", { hasText: `South ${suffix}` })).toHaveCount(0);
    await expect(page.locator("span.badge", { hasText: `North ${suffix}` })).toBeVisible();
  });

  test("the Stakeholder list filters by a group (with its descendants) and groups by a top-level group", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "GroupList");
    const clientRoot = await createGroup(page, org.id, adminHeaders, `Client ${suffix}`);
    const acme = await createGroup(page, org.id, adminHeaders, `Acme ${suffix}`, clientRoot.id);
    const acmeFinance = await createGroup(page, org.id, adminHeaders, `Acme Finance ${suffix}`, acme.id);
    const beta = await createGroup(page, org.id, adminHeaders, `Beta ${suffix}`, clientRoot.id);
    const fran = await createStakeholder(page, org.id, adminHeaders, `Fran ${suffix}`);
    const alex = await createStakeholder(page, org.id, adminHeaders, `Alex ${suffix}`);
    const bea = await createStakeholder(page, org.id, adminHeaders, `Bea ${suffix}`);
    await createStakeholder(page, org.id, adminHeaders, `Nobody ${suffix}`);
    await addMember(page, org.id, adminHeaders, acmeFinance.id, fran.id);
    await addMember(page, org.id, adminHeaders, acme.id, alex.id);
    await addMember(page, org.id, adminHeaders, beta.id, bea.id);

    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders`);
    await expect(page.getByRole("button", { name: `Nobody ${suffix}` })).toBeVisible();

    // --- Filtering by a group includes the people in its descendants.
    await page.getByLabel("Group", { exact: true }).selectOption({ label: `Acme ${suffix}` });
    await expect(page.getByRole("button", { name: `Fran ${suffix}` })).toBeVisible();
    await expect(page.getByRole("button", { name: `Alex ${suffix}` })).toBeVisible();
    await expect(page.getByRole("button", { name: `Bea ${suffix}` })).toHaveCount(0);
    await expect(page.getByRole("button", { name: `Nobody ${suffix}` })).toHaveCount(0);

    // --- "Directly in the group only" drops the descendant's member.
    await page.getByLabel("Directly in the group only").check();
    await expect(page.getByRole("button", { name: `Fran ${suffix}` })).toHaveCount(0);
    await expect(page.getByRole("button", { name: `Alex ${suffix}` })).toBeVisible();
    await page.getByLabel("Directly in the group only").uncheck();
    await page.getByLabel("Group", { exact: true }).selectOption("");

    // --- Group by the root adds a column named for it showing each person's branch, ordered by branch.
    await page.getByLabel("Group by").selectOption({ label: `Client ${suffix}` });
    await expect(page.getByRole("columnheader", { name: `Client ${suffix}` })).toBeVisible();
    const rows = page.locator("tbody tr");
    // Alex (directly) and Fran (via Acme Finance) share the Acme branch, so they come first in either order.
    await expect(rows.nth(0)).toContainText(new RegExp(`(Alex|Fran) ${suffix}`));
    await expect(rows.nth(1)).toContainText(new RegExp(`(Alex|Fran) ${suffix}`));
    await expect(rows.nth(0)).not.toContainText(`Beta ${suffix}`);
    await expect(rows.nth(1)).not.toContainText(`Beta ${suffix}`);
    await expect(rows.nth(2)).toContainText(`Bea ${suffix}`); // Beta
    await expect(rows.nth(3)).toContainText(`Nobody ${suffix}`); // unassigned sorts last

    // --- Clicking a group badge in the Groups column filters to that group.
    await page.getByLabel("Group by").selectOption("");
    await page.getByRole("button", { name: `Beta ${suffix}`, exact: true }).first().click();
    await expect(page.getByRole("button", { name: `Alex ${suffix}` })).toHaveCount(0);
    await expect(page.getByRole("button", { name: `Bea ${suffix}` })).toBeVisible();
  });

  test("a project manages its own groups under an organisation group, which stays read-only there", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "GroupProject");
    const orgGroup = await createGroup(page, org.id, adminHeaders, `Client ${suffix}`);
    const shared = await createStakeholder(page, org.id, adminHeaders, `Shared ${suffix}`);
    await addMember(page, org.id, adminHeaders, orgGroup.id, shared.id);

    await page.goto(`/projects/${project.id}/modules/stakeholders/groups`);
    await expect(page.getByRole("heading", { name: "Stakeholder groups" })).toBeVisible();
    // The organisation's group is listed, marked as the organisation's, with no edit controls.
    await expect(page.getByRole("button", { name: `Client ${suffix}`, exact: true })).toBeVisible();
    await expect(page.getByRole("tree", { name: "Stakeholder groups" }).getByText("Organisation", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: `Edit Client ${suffix}` })).toHaveCount(0);

    // --- A project group can be created under it.
    await page.getByRole("button", { name: "New group" }).click();
    const dialog = page.getByRole("dialog", { name: "New Stakeholder group" });
    await dialog.getByLabel("Group name").fill(`Pilot ${suffix}`);
    await dialog.getByLabel("Parent group").selectOption({ label: `Client ${suffix}` });
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Group created.")).toBeVisible();
    await expect(page.getByRole("button", { name: `Edit Pilot ${suffix}` })).toBeVisible();

    // --- The org stakeholder can be put in the project group from the project's own detail page.
    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders/${shared.id}`);
    await page.getByRole("button", { name: "Project groups" }).click();
    await expect(page.getByRole("checkbox", { name: `Client ${suffix}`, exact: true })).toBeDisabled();
    await page.getByRole("checkbox", { name: `Pilot ${suffix}`, exact: true }).check();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Save groups" }).click();
    await expect(page.getByText("Groups updated.")).toBeVisible();
    await expect(page.locator("span.badge", { hasText: `Pilot ${suffix}` })).toBeVisible();
    await expect(page.locator("span.badge", { hasText: `Client ${suffix}` })).toBeVisible(); // the org group still shows

    // --- The project group is invisible from the organisation's view of the same stakeholder.
    await page.goto(`/orgs/${org.id}/modules/stakeholders/stakeholders/${shared.id}`);
    await expect(page.locator("span.badge", { hasText: `Client ${suffix}` })).toBeVisible();
    await expect(page.locator("span.badge", { hasText: `Pilot ${suffix}` })).toHaveCount(0);
  });

  test("creates groups from the free-text Organisation / group values", async ({ page }) => {
    const { suffix, org, adminHeaders } = await setUpOrg(page, "GroupText");
    for (const [name, group] of [[`Ann ${suffix}`, `Acme ${suffix}`], [`Al ${suffix}`, `Acme ${suffix}`], [`Bea ${suffix}`, `Beta ${suffix}`]]) {
      await post(page, `${orgBase(org.id)}/stakeholders`, adminHeaders, { name, organisation_group: group });
    }

    await openOrgGroups(page);
    await page.getByRole("button", { name: "Create from Organisation / group text" }).click();
    const dialog = page.getByRole("dialog", { name: "Create groups from Organisation / group text" });
    await expect(dialog.getByText("2 stakeholders")).toBeVisible();
    await dialog.getByLabel(`Beta ${suffix}`).uncheck();
    await dialog.getByRole("button", { name: "Create groups" }).click();
    await expect(page.getByText("Created 1 group, 2 added.")).toBeVisible();

    await expect(page.getByRole("button", { name: "Organisation / group", exact: true })).toBeVisible();
    await page.getByRole("button", { name: `Acme ${suffix}`, exact: true }).click();
    const members = page.getByRole("region", { name: `Members of Acme ${suffix}` });
    await expect(members.getByText(`Ann ${suffix}`)).toBeVisible();
    await expect(members.getByText(`Al ${suffix}`)).toBeVisible();
    await expect(page.getByRole("button", { name: `Beta ${suffix}`, exact: true })).toHaveCount(0);
  });
});
