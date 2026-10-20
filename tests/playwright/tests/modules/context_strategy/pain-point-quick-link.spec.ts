import { expect, test } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "../stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a record is rarely meaningful alone, so a create form's "Link to" field links the
 * new record in the same trip. Creating a Pain Point with a Persona chosen in that field leaves the
 * link visible in the Links panel of both records, with the Persona offered first.
 *
 * Disposable org, created through the API and removed afterwards, so the spec depends on no seeded
 * state and can be repeated against the same database.
 */
test("creating a pain point with a persona chosen in 'Link to' links them, visible from both records", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "QuickLink");
  const enable = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers: adminHeaders, data: { enabled: true },
  });
  expect(enable.ok()).toBeTruthy();
  const personaName = `Field Technician ${suffix}`;
  const persona = await (
    await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/modules/stakeholders/personas`, {
      headers: adminHeaders, data: { name: personaName },
    })
  ).json();
  const painPointTitle = `Reports arrive late ${suffix}`;

  await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
  await page.getByRole("button", { name: "New Pain Point" }).click();
  const dialog = page.getByRole("dialog", { name: "New Pain Point" });
  // A new organisation seeds Market, User and Operator pain point types; a type is required to save.
  await dialog.getByLabel("Type", { exact: true }).selectOption({ label: "Operator" });
  await dialog.getByLabel("Pain Point title").fill(painPointTitle);

  await test.step("the Persona is offered as soon as the field is focused", async () => {
    await dialog.getByRole("combobox", { name: "Link to" }).click();
    await dialog.getByRole("option", { name: new RegExp(personaName) }).click();
    const chosen = dialog.getByRole("list", { name: "Records to link" });
    await expect(chosen.getByText(new RegExp(personaName))).toBeVisible();
    // Several link types reach a persona, so the relationship is a select with "Related to" preselected.
    await expect(chosen.locator("option:checked")).toHaveText("Related to");
  });

  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByText("Linked to 1 record.")).toBeVisible();

  await test.step("the Pain Point's Links panel shows the Persona", async () => {
    await page.getByText(painPointTitle).first().click();
    const links = page.getByRole("region", { name: "Links", exact: true });
    await expect(links.getByRole("link", { name: new RegExp(personaName) })).toBeVisible();
  });

  await test.step("the Persona's Links panel shows the Pain Point", async () => {
    await page.goto(`/projects/${project.id}/modules/stakeholders/personas/${persona.id}`);
    const links = page.getByRole("region", { name: "Links", exact: true });
    await expect(links.getByRole("link", { name: new RegExp(painPointTitle) })).toBeVisible();
  });
});

/**
 * Job to be done: the "Link to" field of any create form finds any record the link types allow, by its
 * title or by its code as it is shown elsewhere (`PROJECT-REQ-001`). Checked from two different forms
 * (Pain Point and Persona) against a record of another type (a Requirement), since the field is shared
 * and a gap in it would show on every form.
 */
test("'Link to' on two different create forms finds a requirement by title and by its qualified code", async ({ page }) => {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "QuickLinkAny");
  const enable = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers: adminHeaders, data: { enabled: true },
  });
  expect(enable.ok()).toBeTruthy();
  const post = async (path: string, data: object) => {
    const resp = await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/${path}`, { headers: adminHeaders, data });
    expect(resp.ok(), await resp.text()).toBeTruthy();
    return resp.json();
  };
  const component = await post("components", { name: "Hardware", prefix: "HW" });
  const category = await post("categories", { name: "Functional", prefix: "FN", component_id: component.id });
  const requirementName = `Battery endurance ${suffix}`;
  const requirement = await post("requirements", { name: requirementName, component_id: component.id, category_id: category.id });
  const qualifiedCode = `${project.code}-${requirement.unique_code}`;

  await test.step("a Pain Point form finds it by title", async () => {
    await page.goto(`/projects/${project.id}/modules/context_strategy/pain-points`);
    await page.getByRole("button", { name: "New Pain Point" }).click();
    const dialog = page.getByRole("dialog", { name: "New Pain Point" });
    await dialog.getByRole("combobox", { name: "Link to" }).fill(requirementName.slice(0, 12));
    await expect(dialog.getByRole("option", { name: new RegExp(requirementName) })).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();
  });

  await test.step("a Persona form finds it by the code as displayed elsewhere", async () => {
    await page.goto(`/projects/${project.id}/modules/stakeholders/people`);
    await page.getByRole("button", { name: "New", exact: true }).click();
    await page.getByRole("menuitem", { name: "Persona", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: /New Persona/ });
    await dialog.getByRole("combobox", { name: "Link to" }).fill(qualifiedCode);
    const option = dialog.getByRole("option", { name: new RegExp(requirementName) });
    await expect(option).toBeVisible();
    await option.click();
    await expect(dialog.getByRole("list", { name: "Records to link" }).getByText(new RegExp(requirementName))).toBeVisible();
  });
});
