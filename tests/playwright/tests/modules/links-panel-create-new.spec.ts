import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook, loginAs, PASSWORD } from "../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./stakeholders/helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: a person on a record's page creates the other records it relates to without leaving the page. The
 * Links panel's "Create new" offers every record type a link type reaches that the person may create, each through the
 * type's own create form, and links the new record to the page's record. A type the person may not create is not offered.
 *
 * Builds one disposable org with the modules switched on, so it depends on no seeded state and can be repeated.
 */
const links = (page: Page) => page.getByRole("region", { name: "Links", exact: true });

async function setUp(page: Page) {
  const { suffix, org, project, adminHeaders } = await setUpOrg(page, "CreateNew");
  for (const key of ["decisions", "risk_management", "context_strategy"]) {
    const enabled = await page.request.put(`${API_BASE_URL}/api/v1/orgs/${org.id}/modules/${key}`, { headers: adminHeaders, data: { enabled: true } });
    expect(enabled.ok(), await enabled.text()).toBeTruthy();
  }
  const api = `${API_BASE_URL}/api/v1/projects/${project.id}`;
  const post = async (path: string, data: object) => {
    const resp = await page.request.post(`${api}${path}`, { headers: adminHeaders, data });
    expect(resp.ok(), `${path}: ${await resp.text()}`).toBeTruthy();
    return resp.json();
  };
  const component = await post("/components", { name: "Software", prefix: "SW" });
  const category = await post("/categories", { name: "Performance", prefix: "PERF", component_id: component.id });
  const requirement = await post("/requirements", { name: `Report in 30 seconds ${suffix}`, component_id: component.id, category_id: category.id });
  return { suffix, org, project, adminHeaders, api, post, requirement };
}

/** Opens the Create flow's first step from the Links panel. The plain "Add link" button becomes a menu once the panel knows
 * a record can be created, so the click waits for that. */
async function openCreateStep(page: Page) {
  const addLink = links(page).getByRole("button", { name: "Add link" });
  await expect(addLink).toHaveAttribute("aria-haspopup", "menu");
  await addLink.click();
  await page.getByRole("menuitem", { name: "Create a new record" }).click();
  return page.getByRole("dialog", { name: "Create and link a new record" });
}

/** Opens the create flow from the Links panel and chooses `recordType`; the next dialog is the type's own form. */
async function startCreate(page: Page, recordType: string) {
  const step = await openCreateStep(page);
  await step.getByLabel("Record type").selectOption({ label: recordType });
  await step.getByRole("button", { name: "Next" }).click();
}

test("creates and links a Decision, a Risk, a Persona and an Open Question from a requirement's Links panel", async ({ page }) => {
  const { suffix, project, requirement } = await setUp(page);
  await page.goto(`/projects/${project.id}/requirements/${requirement.id}`);

  await test.step("a Decision", async () => {
    await startCreate(page, "Decision");
    const dialog = page.getByRole("dialog", { name: "New decision" });
    await dialog.getByLabel("Decision title").fill(`Use Postgres ${suffix}`);
    await dialog.getByLabel("Decision statement").fill("We will use PostgreSQL.");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Decision created and linked.")).toBeVisible();
    await expect(links(page).getByRole("link", { name: new RegExp(`Use Postgres ${suffix}`) })).toBeVisible();
  });

  await test.step("a Risk", async () => {
    await startCreate(page, "Risk");
    const dialog = page.getByRole("dialog", { name: "New risk" });
    await dialog.getByLabel("Risk title").fill(`Supplier slips ${suffix}`);
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Risk created and linked.")).toBeVisible();
    await expect(links(page).getByRole("link", { name: new RegExp(`Supplier slips ${suffix}`) })).toBeVisible();
  });

  await test.step("a Persona", async () => {
    await startCreate(page, "Persona");
    const dialog = page.getByRole("dialog", { name: /New persona/i });
    await dialog.getByLabel("Persona name").fill(`Field Technician ${suffix}`);
    await dialog.getByLabel("Type").selectOption({ label: "Primary" });
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("Persona created and linked.")).toBeVisible();
    await expect(links(page).getByRole("link", { name: new RegExp(`Field Technician ${suffix}`) })).toBeVisible();
  });

  await test.step("an Open Question", async () => {
    await startCreate(page, "Open Question");
    const dialog = page.getByRole("dialog", { name: "New Open Question" });
    await dialog.getByLabel("Question").fill(`Which vendor ${suffix}?`);
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Open Question created and linked.")).toBeVisible();
    await expect(links(page).getByRole("link", { name: new RegExp(`Which vendor ${suffix}`) })).toBeVisible();
  });
});

test("a quick link chosen in the form is made in addition to the link to the page's record", async ({ page }) => {
  const { suffix, project, requirement, post } = await setUp(page);
  const other = await post("/requirements", {
    name: `Audit trail ${suffix}`, component_id: requirement.component_id, category_id: requirement.category_id,
  });
  await page.goto(`/projects/${project.id}/requirements/${requirement.id}`);
  await startCreate(page, "Open Question");
  const dialog = page.getByRole("dialog", { name: "New Open Question" });
  await dialog.getByLabel("Question").fill(`Who signs off ${suffix}?`);
  await dialog.getByRole("combobox", { name: "Link to" }).fill(`Audit trail ${suffix}`);
  await dialog.getByRole("option", { name: new RegExp(`Audit trail ${suffix}`) }).click();
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Open Question created and linked.")).toBeVisible();

  await test.step("the new question is linked to the page's requirement", async () => {
    await expect(links(page).getByRole("link", { name: new RegExp(`Who signs off ${suffix}`) })).toBeVisible();
  });
  await test.step("and to the requirement chosen in the form", async () => {
    await page.goto(`/projects/${project.id}/requirements/${other.id}`);
    await expect(links(page).getByRole("link", { name: new RegExp(`Who signs off ${suffix}`) })).toBeVisible();
  });
});

test("a type the person may not create is not offered, while one they may create is", async ({ page }) => {
  const { suffix, org, project, adminHeaders, requirement } = await setUp(page);
  const email = `e2e-createnew-member-${suffix}@example.com`;
  const created = await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/users`, {
    headers: adminHeaders, data: { email, display_name: "E2E Member", password: PASSWORD, role: "member" },
  });
  expect(created.status()).toBe(201);
  const role = await page.request.post(`${API_BASE_URL}/api/v1/projects/${project.id}/roles`, {
    headers: adminHeaders, data: { user_id: (await created.json()).user_id, role: "member" },
  });
  expect(role.ok()).toBeTruthy();
  // A member may only link with the "Link editor" role, which confers nothing else, so no type is made creatable by it.
  const roles = await (await page.request.get(`${API_BASE_URL}/api/v1/orgs/${org.id}/custom-roles`, { headers: adminHeaders })).json();
  const preset = roles.find((r: { name: string }) => r.name === "Link editor");
  expect(preset, "a new organisation is seeded with the Link editor preset").toBeTruthy();
  const granted = await page.request.post(`${API_BASE_URL}/api/v1/orgs/${org.id}/custom-roles/${preset.id}/users/${(await created.json()).user_id}`, {
    headers: adminHeaders, data: { project_id: project.id },
  });
  expect(granted.status()).toBe(204);

  await loginAs(page, email, PASSWORD);
  await page.goto(`/projects/${project.id}/requirements/${requirement.id}`);
  const recordType = (await openCreateStep(page)).getByLabel("Record type");
  // The member may propose a Decision, but creating a Persona needs the Persona Owner role.
  await expect(recordType.locator("option", { hasText: "Decision" })).toHaveCount(1);
  await expect(recordType.locator("option", { hasText: "Persona" })).toHaveCount(0);
});
