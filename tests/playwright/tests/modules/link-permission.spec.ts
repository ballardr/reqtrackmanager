import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook, loginAs, PASSWORD } from "../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: docs/plans/platform-enhancements-2026-10-plan.md Phase 6d — an
 * administrator lets someone trace their project's records with one grant that
 * confers nothing else. A member who is also granted the organisation's preset
 * "Link editor" role adds and removes links on a requirement and on a decision,
 * sees no way to edit the requirement, and is still refused on an approved
 * requirement in a project that needs a change request for links.
 *
 * Builds one disposable org, so it does not depend on state left by another test
 * or an earlier run.
 */
const links = (page: Page) => page.getByRole("region", { name: "Links", exact: true });

async function setUpLinkEditor(page: Page) {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "LinkPerm");
  const enabled = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/decisions`, {
    headers: adminHeaders, data: { enabled: true },
  });
  expect(enabled.ok(), await enabled.text()).toBeTruthy();
  const api = `${API_BASE_URL}/api/v1/projects/${project.id}`;
  const post = async (path: string, data: object) => {
    const resp = await page.request.post(`${api}${path}`, { headers: adminHeaders, data });
    expect(resp.ok(), `${path}: ${await resp.text()}`).toBeTruthy();
    return resp.json();
  };

  const component = await post("/components", { name: "Software", prefix: "SW" });
  const category = await post("/categories", { name: "Performance", prefix: "PERF", component_id: component.id });
  const requirement = await post("/requirements", { name: `Report in 30 seconds ${suffix}`, component_id: component.id, category_id: category.id });
  const decisionTypes = await (await page.request.get(`${api}/modules/decisions/decision-types`, { headers: adminHeaders })).json();
  const decision = await post("/modules/decisions", { title: `Use Postgres ${suffix}`, decision_statement: "We will.", decision_type_id: decisionTypes[0].id });

  // A plain project member, granted the preset Link editor role for this project only.
  const email = `e2e-linker-${suffix}@example.com`;
  const created = await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
    headers: adminHeaders, data: { email, display_name: "E2E Linker", password: PASSWORD, role: "member" },
  });
  expect(created.status()).toBe(201);
  const userId = (await created.json()).user_id;
  const member = await page.request.post(`${api}/roles`, { headers: adminHeaders, data: { user_id: userId, role: "member" } });
  expect(member.ok()).toBeTruthy();
  const roles = await (await page.request.get(`${API_BASE_URL}/api/v1/orgs/${org.id}/custom-roles`, { headers: adminHeaders })).json();
  const preset = roles.find((r: { name: string }) => r.name === "Link editor");
  expect(preset, "a new organisation is seeded with the Link editor preset").toBeTruthy();
  const granted = await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/custom-roles/${preset.id}/users/${userId}`, {
    headers: adminHeaders, data: { project_id: project.id },
  });
  expect(granted.status()).toBe(204);

  const login = await page.request.post(`${API_BASE_URL}/api/v1/auth/login`, { data: { email, password: PASSWORD } });
  const linkerHeaders = { Authorization: `Bearer ${(await login.json()).access_token}` };
  return { suffix, email, project, requirement, decision, adminHeaders, linkerHeaders, api };
}

/** Links the open page's record to `record` (of type `type`) with `relationship` through the panel. */
async function addLink(page: Page, relationship: string, record: { type: string; label: string }) {
  await links(page).getByRole("button", { name: "Add link" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a link" });
  await dialog.getByLabel("Link to").selectOption({ label: record.type });
  const recordSelect = dialog.getByLabel("Record");
  await expect(recordSelect.locator("option", { hasText: record.label })).toHaveCount(1);
  await recordSelect.selectOption({ label: record.label });
  await dialog.getByLabel("Relationship").selectOption({ label: relationship });
  await dialog.getByRole("button", { name: "Add link" }).click();
  await expect(dialog).not.toBeVisible();
}

async function removeFirstLink(page: Page) {
  await links(page).getByRole("button", { name: /^Remove link/ }).first().click();
  await page.getByRole("dialog", { name: "Remove this link?" }).getByRole("button", { name: "Remove link" }).click();
}

test.describe("Link editor: the link permission level", () => {
  test("a member with the Link editor role links and unlinks a requirement and a decision, but cannot edit", async ({ page }) => {
    const { suffix, email, project, requirement, decision, linkerHeaders, api } = await setUpLinkEditor(page);
    await loginAs(page, email, PASSWORD);
    const base = `/projects/${project.id}`;

    await test.step("on the requirement's page the panel offers add and remove, and nothing else is editable", async () => {
      await page.goto(`${base}/requirements/${requirement.id}`);
      await expect(links(page).getByRole("button", { name: "Add link" })).toBeVisible();
      await addLink(page, "Related to", { type: "Decision", label: `${decision.unique_code} Use Postgres ${suffix}` });
      await expect(links(page).getByRole("link", { name: new RegExp(`Use Postgres ${suffix}`) })).toBeVisible();
      await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
      await removeFirstLink(page);
      await expect(links(page).getByText("No links yet.")).toBeVisible();
    });

    await test.step("on the decision's page too, since the preset covers every record type", async () => {
      await page.goto(`${base}/modules/decisions/${decision.id}`);
      await addLink(page, "Related to", { type: "Requirement", label: `${requirement.unique_code} Report in 30 seconds ${suffix}` });
      await expect(links(page).getByRole("link", { name: new RegExp(`Report in 30 seconds ${suffix}`) })).toBeVisible();
      await removeFirstLink(page);
      await expect(links(page).getByText("No links yet.")).toBeVisible();
    });

    await test.step("the grant confers no right to edit the requirement", async () => {
      const edit = await page.request.put(`${api}/requirements/${requirement.id}`, {
        headers: linkerHeaders, data: { name: "Renamed", component_id: requirement.component_id, category_id: requirement.category_id, owner_id: requirement.owner_id },
      });
      expect(edit.status()).toBe(403);
    });
  });

  test("an approved requirement in a project that needs a change request for links still refuses a direct link", async ({ page }) => {
    const { project, requirement, decision, adminHeaders, linkerHeaders, api } = await setUpLinkEditor(page);
    const approved = await page.request.post(`${api}/requirements/${requirement.id}/approve`, { headers: adminHeaders });
    expect(approved.ok()).toBeTruthy();
    const gated = await page.request.patch(`${API_BASE_URL}/api/v1/projects/${project.id}`, {
      headers: adminHeaders, data: { require_change_request_for_approved_links: true },
    });
    expect(gated.ok()).toBeTruthy();

    const types = await (await page.request.get(`${api}/artefacts/requirement/${requirement.id}/link-types`, { headers: linkerHeaders })).json();
    const related = types.find((t: { phrase: string }) => t.phrase === "Related to");
    const refused = await page.request.post(`${api}/artefacts/requirement/${requirement.id}/links`, {
      headers: linkerHeaders,
      data: { link_type_id: related.link_type_id, direction: "outgoing", other_type: "decision", other_id: decision.id },
    });
    expect(refused.status()).toBe(409);
    expect((await refused.json()).detail).toContain("change request");
  });
});
