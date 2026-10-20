import { expect, type APIRequestContext, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, recordCodeText } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: every record a person can create or refer to has a short, human-readable code, so
 * it can be named in conversation. Pain points (PP), open questions (OQ), stakeholder needs (NEED),
 * change requests (CR) show theirs in their list and in their record
 * header, and the next record continues the numbering.
 *
 * Covers: the code column of each type's list, the muted code in each detail header (change
 * request, pain point, open question, need), and that a record created
 * through the UI takes the next number.
 *
 * Each test builds its own organisation, so none depends on state left by another test.
 */

const apiBaseUrl = "http://localhost:8000";

interface World {
  orgId: string;
  adminEmail: string;
  headers: { Authorization: string };
}

async function createWorld(request: APIRequestContext, label: string): Promise<World> {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const adminEmail = `e2e-${label}-admin-${suffix}@example.com`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `Record codes ${label} ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Record Codes Admin", password: PASSWORD, role: "org_admin" },
  });
  const token = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })).json()
  ).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  for (const key of ["context_strategy", "stakeholders", "compliance"]) {
    const enabled = await request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/modules/${key}`, { headers, data: { enabled: true } });
    expect(enabled.ok(), `enable ${key}`).toBe(true);
  }
  return { orgId: org.id, adminEmail, headers };
}

async function post(request: APIRequestContext, world: World, path: string, data: unknown) {
  const response = await request.post(`${apiBaseUrl}/api/v1${path}`, { headers: world.headers, data });
  expect(response.status(), `${path}: ${await response.text()}`).toBe(201);
  return response.json();
}

async function createRecords(request: APIRequestContext, world: World) {
  const project = await post(request, world, "/projects", { organization_id: world.orgId, name: "Record Codes Project", summary: "" });
  const pid = project.id as string;
  const types = await (
    await request.get(`${apiBaseUrl}/api/v1/projects/${pid}/modules/context_strategy/pain-point-types`, { headers: world.headers })
  ).json();
  const painPoint = await post(request, world, `/projects/${pid}/modules/context_strategy/pain-points`, {
    title: "Reports arrive late", priority: "high", date_identified: "2026-09-01", pain_point_type_id: types[0].id,
  });
  const question = await post(request, world, `/projects/${pid}/modules/context_strategy/open-questions`, {
    question: "Which regions first?",
  });
  const need = await post(request, world, `/projects/${pid}/modules/stakeholders/needs`, { name: "Diagnose faults quickly" });
  await post(request, world, `/projects/${pid}/modules/compliance/evidence`, { title: "IPX9 Test Certificate" });
  const changeRequest = await post(request, world, `/projects/${pid}/change-requests`, {
    kind: "new_requirement", proposed_name: "Wider doors", reason: "e2e",
  });
  return { pid, painPoint, question, need, changeRequest };
}

test.describe("project-scoped record codes", () => {
  test("each type's list shows the code and its detail header carries it", async ({ page }) => {
    const world = await createWorld(page.request, "lists");
    const { pid, painPoint, question, need, changeRequest } = await createRecords(page.request, world);
    await loginAs(page, world.adminEmail);

    const cases = [
      { list: `/projects/${pid}/modules/context_strategy/pain-points`, code: "PP-001", detail: `${painPoint.id}`, title: "Reports arrive late" },
      { list: `/projects/${pid}/modules/context_strategy/open-questions`, code: "OQ-001", detail: `${question.id}`, title: "Which regions first?" },
      { list: `/projects/${pid}/modules/stakeholders/needs`, code: "NEED-001", detail: `${need.id}`, title: "Diagnose faults quickly" },
      { list: `/projects/${pid}/change-requests`, code: "CR-001", detail: `${changeRequest.id}`, title: "Wider doors" },
    ];
    for (const { list, code, detail, title } of cases) {
      await test.step(`${code}: list then detail`, async () => {
        await page.goto(list);
        await expect(page.getByText(recordCodeText(code)).first()).toBeVisible();
        await page.goto(`${list}/${detail}`);
        const header = page.locator(".record-header");
        await expect(header.getByText(recordCodeText(code))).toBeVisible();
        await expect(header.getByRole("heading")).toContainText(title);
      });
    }
  });

  test("a change request created in the UI takes the next number", async ({ page }) => {
    const world = await createWorld(page.request, "create");
    const { pid } = await createRecords(page.request, world);
    await post(page.request, world, `/projects/${pid}/change-requests`, {
      kind: "new_requirement", proposed_name: "Second request", reason: "e2e",
    });
    await loginAs(page, world.adminEmail);
    await page.goto(`/projects/${pid}/change-requests`);
    await expect(page.getByText(recordCodeText("CR-001")).first()).toBeVisible();
    await expect(page.getByText(recordCodeText("CR-002")).first()).toBeVisible();
    // Searching by the code finds the request.
    await page.getByPlaceholder(/^Search by name, reason or /).fill("cr-002");
    await expect(page.getByRole("link", { name: "Second request" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Wider doors" })).toHaveCount(0);
  });
});
