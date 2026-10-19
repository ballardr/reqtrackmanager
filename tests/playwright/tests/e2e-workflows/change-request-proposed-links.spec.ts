import { expect, type APIRequestContext, type Locator, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, openProject, PASSWORD, PERSONAS, PROJECT_NAMES } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: someone who wants an approved requirement traced to other records proposes the
 * links on a change request; the approver sees them in a dialog, merges all by default, can untick
 * any or all, and every outcome is recorded; a link that cannot be merged is shown with the reason
 * and is never silently dropped.
 *
 * Covers: proposing links in the create form (modify and new-requirement kinds); the request page
 * listing them as pending; approving through the dialog with everything ticked (the default), with
 * one unticked and with none; the requirement's Links panel showing only what merged; a link that
 * became unmergeable shown disabled with its reason; an add-link request approved through the same
 * dialog; and nothing appearing as a link before approval.
 *
 * Each test builds its own organisation, so none depends on state left by another test or an
 * earlier run (and the shared seeded projects are never touched).
 */

const apiBaseUrl = "http://localhost:8000";

interface World {
  orgId: string;
  adminEmail: string;
  headers: { Authorization: string };
  projectId: string;
  componentId: string;
  categoryId: string;
}

async function createWorld(request: APIRequestContext, label: string): Promise<World> {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const adminEmail = `e2e-crlinks-${label}-${suffix}@example.com`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `E2E CR Links ${label} ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E CR Links Admin", password: PASSWORD, role: "org_admin" },
  });
  const token = (await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  const project = await (
    await request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers, data: { organization_id: org.id, name: `E2E CR Links Project ${suffix}`, summary: "" },
    })
  ).json();
  const component = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/components`, { headers, data: { name: "Software", prefix: "SW" } })
  ).json();
  const category = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${project.id}/categories`, {
      headers, data: { name: "Functional", prefix: "FN", component_id: component.id },
    })
  ).json();
  return { orgId: org.id, adminEmail, headers, projectId: project.id, componentId: component.id, categoryId: category.id };
}

async function createRequirement(request: APIRequestContext, world: World, name: string, approve = false): Promise<string> {
  const created = await (
    await request.post(`${apiBaseUrl}/api/v1/projects/${world.projectId}/requirements`, {
      headers: world.headers,
      data: { name, reasoning: "e2e", component_id: world.componentId, category_id: world.categoryId, keywords: [] },
    })
  ).json();
  if (approve) {
    const approved = await request.post(`${apiBaseUrl}/api/v1/projects/${world.projectId}/requirements/${created.id}/approve`, { headers: world.headers });
    expect(approved.status()).toBe(200);
  }
  return created.id;
}

/** The organisation's seeded "Related to" link type id. */
async function relatedTypeId(request: APIRequestContext, world: World): Promise<string> {
  const types: { id: string; forward_name: string }[] = await (
    await request.get(`${apiBaseUrl}/api/v1/orgs/${world.orgId}/link-types`, { headers: world.headers })
  ).json();
  return types.find((t) => t.forward_name === "Related to")!.id;
}

/** Creates a submitted modify-requirement request proposing links to `others`, through the API. */
async function submittedModifyRequest(
  request: APIRequestContext, world: World, target: string, typeId: string, others: string[],
): Promise<string> {
  const created = await request.post(`${apiBaseUrl}/api/v1/projects/${world.projectId}/change-requests`, {
    headers: world.headers,
    data: {
      kind: "modify_requirement", requirement_id: target, changed_fields: ["name"], proposed_name: `${Date.now()} renamed`,
      reason: "trace it",
      proposed_links: others.map((id) => ({ link_type_id: typeId, direction: "outgoing", other_type: "requirement", other_id: id })),
    },
  });
  expect(created.status()).toBe(201);
  const cr = await created.json();
  const submitted = await request.post(`${apiBaseUrl}/api/v1/projects/${world.projectId}/change-requests/${cr.id}/submit`, { headers: world.headers });
  expect(submitted.status()).toBe(200);
  return cr.id;
}

async function linksOf(request: APIRequestContext, world: World, requirementId: string): Promise<string[]> {
  const graph = await (
    await request.get(`${apiBaseUrl}/api/v1/projects/${world.projectId}/artefacts/requirement/${requirementId}/link-graph`, { headers: world.headers })
  ).json();
  return graph.nodes.filter((n: { id: string }) => n.id !== requirementId).map((n: { label: string }) => n.label);
}

/** Chooses the record in the "Add a link" dialog's finder: the record type first, then the record by name. */
async function pickRecord(picker: Locator, name: RegExp): Promise<void> {
  await picker.getByLabel("Link to").selectOption({ label: "Requirement" });
  const option = picker.getByRole("option", { name });
  await expect(option).toHaveCount(1);
  await picker.getByLabel("Record").selectOption((await option.getAttribute("value")) as string);
}

async function openRequest(page: Page, world: World, crId: string): Promise<void> {
  await page.goto(`/projects/${world.projectId}/change-requests/${crId}`);
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeVisible();
}

test.describe("change requests: proposed links", () => {
  test("the seeded request lists three proposed links and the approval dialog disables the one that cannot be merged (read-only)", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.zeta1);
    await page.getByRole("link", { name: "Change requests", exact: true }).click();
    await page.getByRole("link", { name: "Must respond to input within 50ms" }).click();
    const section = page.getByLabel("Proposed links");
    await expect(section.getByText("Pending")).toHaveCount(3);

    await page.getByRole("button", { name: "Approve", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Approve change request" });
    await expect(dialog.getByRole("checkbox", { name: /Merge link/ })).toHaveCount(3);
    await expect(dialog.getByRole("checkbox", { name: /Merge link/, checked: true })).toHaveCount(2);
    await expect(dialog.getByText("Already linked, will be skipped")).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();  // read-only: the fixture is never decided
    await expect(dialog).toBeHidden();
  });

  test("links proposed in the create form are listed as pending and become links only when merged", async ({ page }) => {
    const world = await createWorld(page.request, "form");
    const target = await createRequirement(page.request, world, "Target requirement", true);
    await createRequirement(page.request, world, "Alpha related requirement");
    await createRequirement(page.request, world, "Beta related requirement");
    await loginAs(page, world.adminEmail, PASSWORD);

    await test.step("the create form collects links without creating them", async () => {
      await page.goto(`/projects/${world.projectId}/change-requests`);
      await page.getByRole("button", { name: /New change request/ }).click();
      const form = page.getByRole("dialog", { name: "New change request" });
      // The form re-primes its fields once the requirements have loaded; tick a field only after that.
      await expect(form.locator("select").first()).toHaveValue(target);
      await form.getByRole("checkbox", { name: "Reasoning" }).check();
      for (const name of ["Alpha related requirement", "Beta related requirement"]) {
        await form.getByRole("button", { name: "Add a link" }).click();
        const picker = page.getByRole("dialog", { name: "Add a link" });
        await pickRecord(picker, new RegExp(name));
        await picker.getByRole("button", { name: "Add to the request" }).click();
        await expect(form.getByText(new RegExp(name))).toBeVisible();
      }
      expect(await linksOf(page.request, world, target)).toEqual([]);
      await form.getByLabel("Reason for change").fill("Trace both related requirements");
      await form.getByRole("button", { name: "Create" }).click();
      await expect(page.getByText("Change request created")).toBeVisible();
    });

    const crs: { id: string; proposed_link_count: number }[] = await (
      await page.request.get(`${apiBaseUrl}/api/v1/projects/${world.projectId}/change-requests`, { headers: world.headers })
    ).json();
    expect(crs).toHaveLength(1);
    expect(crs[0].proposed_link_count).toBe(2);

    await test.step("the request page lists them as pending, and the requirement shows no link yet", async () => {
      await page.goto(`/projects/${world.projectId}/change-requests/${crs[0].id}`);
      const section = page.getByLabel("Proposed links");
      await expect(section.getByText("Pending")).toHaveCount(2);
      await expect(section.getByText(/Alpha related requirement/)).toBeVisible();
      expect(await linksOf(page.request, world, target)).toEqual([]);
    });
  });

  test("approving through the dialog merges everything by default and records each outcome", async ({ page }) => {
    const world = await createWorld(page.request, "all");
    const target = await createRequirement(page.request, world, "Target requirement", true);
    const a = await createRequirement(page.request, world, "First related requirement");
    const b = await createRequirement(page.request, world, "Second related requirement");
    const crId = await submittedModifyRequest(page.request, world, target, await relatedTypeId(page.request, world), [a, b]);
    await loginAs(page, world.adminEmail, PASSWORD);
    await openRequest(page, world, crId);

    await page.getByRole("button", { name: "Approve", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Approve change request" });
    await expect(dialog.getByRole("checkbox", { name: /Merge link: Related to .*First related/ })).toBeChecked();
    await expect(dialog.getByRole("checkbox", { name: /Merge link: Related to .*Second related/ })).toBeChecked();
    await dialog.getByRole("button", { name: "Approve and merge 2 links" }).click();
    await expect(page.getByText("Change request approved")).toBeVisible();

    const section = page.getByLabel("Proposed links");
    await expect(section.getByText("Merged")).toHaveCount(2);
    expect((await linksOf(page.request, world, target)).sort()).toEqual([
      expect.stringContaining("First related requirement"), expect.stringContaining("Second related requirement"),
    ]);
  });

  test("unticking one link merges the rest, and the unticked one is recorded as left out", async ({ page }) => {
    const world = await createWorld(page.request, "subset");
    const target = await createRequirement(page.request, world, "Target requirement", true);
    const a = await createRequirement(page.request, world, "Kept requirement");
    const b = await createRequirement(page.request, world, "Dropped requirement");
    const crId = await submittedModifyRequest(page.request, world, target, await relatedTypeId(page.request, world), [a, b]);
    await loginAs(page, world.adminEmail, PASSWORD);
    await openRequest(page, world, crId);

    await page.getByRole("button", { name: "Approve", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Approve change request" });
    await dialog.getByRole("checkbox", { name: /Merge link: Related to .*Dropped/ }).uncheck();
    await dialog.getByRole("button", { name: "Approve and merge 1 link" }).click();
    await expect(page.getByText("Change request approved")).toBeVisible();

    const section = page.getByLabel("Proposed links");
    await expect(section.getByText("Merged")).toHaveCount(1);
    await expect(section.getByText("Left out")).toHaveCount(1);
    expect(await linksOf(page.request, world, target)).toEqual([expect.stringContaining("Kept requirement")]);
  });

  test("approving with none ticked still approves the request but creates no link", async ({ page }) => {
    const world = await createWorld(page.request, "none");
    const target = await createRequirement(page.request, world, "Target requirement", true);
    const a = await createRequirement(page.request, world, "Only related requirement");
    const crId = await submittedModifyRequest(page.request, world, target, await relatedTypeId(page.request, world), [a]);
    await loginAs(page, world.adminEmail, PASSWORD);
    await openRequest(page, world, crId);

    await page.getByRole("button", { name: "Approve", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Approve change request" });
    await dialog.getByRole("button", { name: "Select none" }).click();
    await dialog.getByRole("button", { name: "Approve without links" }).click();
    await expect(page.getByText("Change request approved")).toBeVisible();
    await expect(page.getByLabel("Proposed links").getByText("Left out")).toHaveCount(1);
    expect(await linksOf(page.request, world, target)).toEqual([]);
  });

  test("a link that can no longer be merged is shown disabled with its reason, never silently dropped", async ({ page }) => {
    const world = await createWorld(page.request, "invalid");
    const target = await createRequirement(page.request, world, "Target requirement", true);
    const fine = await createRequirement(page.request, world, "Still fine requirement");
    const taken = await createRequirement(page.request, world, "Linked meanwhile requirement");
    const typeId = await relatedTypeId(page.request, world);
    const crId = await submittedModifyRequest(page.request, world, target, typeId, [fine, taken]);
    // After the request was made, someone links the second record directly.
    const direct = await page.request.post(`${apiBaseUrl}/api/v1/projects/${world.projectId}/artefacts/requirement/${target}/links`, {
      headers: world.headers, data: { link_type_id: typeId, direction: "outgoing", other_type: "requirement", other_id: taken },
    });
    expect(direct.status()).toBe(201);
    await loginAs(page, world.adminEmail, PASSWORD);
    await openRequest(page, world, crId);

    await page.getByRole("button", { name: "Approve", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Approve change request" });
    await expect(dialog.getByRole("checkbox", { name: /Merge link: Related to .*Linked meanwhile/ })).toBeDisabled();
    await expect(dialog.getByText("Already linked, will be skipped")).toBeVisible();
    await expect(dialog.getByRole("checkbox", { name: /Merge link: Related to .*Still fine/ })).toBeChecked();
    await dialog.getByRole("button", { name: "Approve and merge 1 link" }).click();
    await expect(page.getByText("Change request approved")).toBeVisible();
    await expect(page.getByLabel("Proposed links").getByText("Merged")).toHaveCount(1);
  });

  test("an add-link request is approved through the same dialog", async ({ page }) => {
    const world = await createWorld(page.request, "addlink");
    const target = await createRequirement(page.request, world, "Target requirement", true);
    const other = await createRequirement(page.request, world, "Other requirement");
    const typeId = await relatedTypeId(page.request, world);
    const locked = await page.request.patch(`${apiBaseUrl}/api/v1/projects/${world.projectId}`, {
      headers: world.headers, data: { require_change_request_for_approved_links: true },
    });
    expect(locked.status()).toBe(200);
    const created = await page.request.post(`${apiBaseUrl}/api/v1/projects/${world.projectId}/change-requests`, {
      headers: world.headers,
      data: {
        kind: "add_link", requirement_id: target, reason: "traceability gap",
        proposed_links: [{ link_type_id: typeId, direction: "outgoing", other_type: "requirement", other_id: other }],
      },
    });
    expect(created.status()).toBe(201);
    const crId = (await created.json()).id;
    await page.request.post(`${apiBaseUrl}/api/v1/projects/${world.projectId}/change-requests/${crId}/submit`, { headers: world.headers });
    await loginAs(page, world.adminEmail, PASSWORD);
    await openRequest(page, world, crId);

    await page.getByRole("button", { name: "Approve", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Approve change request" });
    await dialog.getByRole("button", { name: "Select none" }).click();
    await expect(dialog.getByText(/approving it changes nothing/)).toBeVisible();
    await dialog.getByRole("button", { name: "Select all" }).click();
    await dialog.getByRole("button", { name: "Approve and merge 1 link" }).click();
    await expect(page.getByText("Change request approved")).toBeVisible();
    expect(await linksOf(page.request, world, target)).toEqual([expect.stringContaining("Other requirement")]);
  });

  test("a new-requirement request can propose a link before the requirement exists", async ({ page }) => {
    const world = await createWorld(page.request, "new");
    await createRequirement(page.request, world, "Existing requirement");
    await loginAs(page, world.adminEmail, PASSWORD);
    await page.goto(`/projects/${world.projectId}/change-requests`);
    await page.getByRole("button", { name: /New change request/ }).click();
    const form = page.getByRole("dialog", { name: "New change request" });
    await form.getByRole("radio", { name: /New/ }).check();
    await form.getByLabel("Proposed name").fill("Brand new requirement");
    await form.getByRole("button", { name: "Add a link" }).click();
    const picker = page.getByRole("dialog", { name: "Add a link" });
    await pickRecord(picker, /Existing requirement/);
    await picker.getByRole("button", { name: "Add to the request" }).click();
    await expect(form.getByText(/Existing requirement/)).toBeVisible();
    await form.getByLabel("Reason for change").fill("A new requirement that builds on the existing one");
    await form.getByRole("button", { name: "Create" }).click();
    await expect(page.getByText("Change request created")).toBeVisible();

    const crs: { id: string; kind: string; proposed_link_count: number }[] = await (
      await page.request.get(`${apiBaseUrl}/api/v1/projects/${world.projectId}/change-requests`, { headers: world.headers })
    ).json();
    expect(crs.map((c) => [c.kind, c.proposed_link_count])).toEqual([["new_requirement", 1]]);
  });
});
