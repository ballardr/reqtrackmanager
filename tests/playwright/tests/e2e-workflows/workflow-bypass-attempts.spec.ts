import { expect, test } from "@playwright/test";

import { apiHeaders, createDisposableProject, installCleanupHook, loginAs, logout, moveStageToPhase, onCleanup, openRequirementByName, ORG_NAMES, PERSONAS, PROJECT_NAMES, recordActionNames, expectRecordLocked } from "./helpers";

const apiBaseUrl = "http://localhost:8000";

/**
 * Job to be done: the requirement lifecycle's guarantees (edit-after-lock requires a change request; only a PM
 * can approve; archiving does not redefine an identifier) hold against a user deliberately routing around
 * them. Each step is an attempted bypass, confirmed blocked in the UI and, where it matters, at the API.
 *
 * Uses a disposable project inside Alpha (created via the API, as project-admin-structural.spec.ts does), not
 * Alpha-1: approving a stage irreversibly locks every requirement in its project. Grants and then revokes
 * stakeholderAlpha/memberAlphaBeta project roles, and archives the project at the end so no unbounded list
 * growth hides a just-created row from a locator (see docs/decisions.md). Setup, stage approval and
 * archive-and-recreate use the API; the steps need two UI logins. change-request-approval-separation covers
 * the change-request rule.
 */
test.describe("attempts to bypass requirement/change-request workflow guarantees", () => {
  installCleanupHook();

  test("locking a stage, then probing edit/archive/approve boundaries", async ({ page, request }) => {
    const suffix = Date.now();
    const targetReqName = `E2E Bypass Target ${suffix}`;
    const api = `${apiBaseUrl}/api/v1`;

    const project = await createDisposableProject(request, PERSONAS.orgAdminAlphaBeta.email, "E2E Bypass Project", ORG_NAMES.alpha);
    const { projectId, headers: pmHeaders } = project;
    const users: { user_id: string; email: string }[] = await (
      await request.get(`${api}/orgs/${project.organizationId}/users`, { headers: pmHeaders })
    ).json();
    const stakeholderId = users.find((u) => u.email === PERSONAS.stakeholderAlpha.email)!.user_id;
    // A grant on a shared persona: revoked in afterEach (runs even on a
    // timeout); the project itself is archived by createDisposableProject.
    onCleanup(async (cleanupRequest) => {
      await cleanupRequest.delete(`${api}/projects/${projectId}/roles/${stakeholderId}/stakeholder`, {
        headers: await apiHeaders(cleanupRequest, PERSONAS.orgAdminAlphaBeta.email),
      });
    });
    expect((await request.post(`${api}/projects/${projectId}/roles`, {
      headers: pmHeaders, data: { user_id: stakeholderId, role: "stakeholder" },
    })).ok()).toBeTruthy();

    const createRequirement = async (name: string) => {
      const resp = await request.post(`${api}/projects/${projectId}/requirements`, {
        headers: pmHeaders,
        data: { name, component_id: project.components[0].id, category_id: project.categories[0].id },
      });
      expect(resp.ok()).toBeTruthy();
      return (await resp.json()) as { id: string; unique_code: string };
    };
    const target = await createRequirement(targetReqName);

    await test.step("PM approves the project's stage, locking all its requirements", async () => {
      const stages: { id: string }[] = await (await request.get(`${api}/projects/${projectId}/stages`, { headers: pmHeaders })).json();
      for (const phase of ["Review", "Approved"]) {
        const resp = await moveStageToPhase(request, pmHeaders, projectId, stages[0].id, phase);
        expect(resp.ok(), phase).toBeTruthy();
      }
    });

    await test.step("the locked requirement offers no edit form in the UI", async () => {
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.goto(`/projects/${projectId}/requirements/${target.id}`);
      await expect(page.locator(".record-header h1")).toBeVisible();
      await expectRecordLocked(page);
      await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
    });

    await test.step("a raw API edit attempt against the same locked requirement still 409s", async () => {
      const resp = await request.put(`${api}/projects/${projectId}/requirements/${target.id}`, {
        headers: pmHeaders,
        data: {
          name: "Renamed via raw API bypass attempt", reasoning: "x", component_id: "00000000-0000-0000-0000-000000000000",
          category_id: "00000000-0000-0000-0000-000000000000", owner: { type: "user", id: "00000000-0000-0000-0000-000000000000" }, keywords: [],
        },
      });
      expect(resp.status()).toBe(409);
    });

    await test.step("archiving a locked requirement is hidden from a non-PM stakeholder", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.goto(`/projects/${projectId}`);
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await openRequirementByName(page, targetReqName);
      expect(await recordActionNames(page, "Requirement")).not.toContain("Archive");
    });

    await test.step("cross-org ID guessing: a single-org user cannot open another org's project by URL", async () => {
      const projects: { id: string; name: string }[] = await (await request.get(
        `${api}/projects?archived=false&search=${encodeURIComponent(PROJECT_NAMES.beta1)}`, { headers: pmHeaders },
      )).json();
      const beta1 = projects.find((p) => p.name === PROJECT_NAMES.beta1)!;
      const resp = await request.get(`${api}/projects/${beta1.id}`, {
        headers: await apiHeaders(request, PERSONAS.stakeholderAlpha.email),
      });
      expect(resp.status()).toBe(403);

      // Also confirm the UI itself doesn't render Beta-1's content if
      // navigated to directly by URL, not just that the API rejects it.
      await page.goto(`/projects/${beta1.id}`);
      await expect(page.getByText(PROJECT_NAMES.beta1)).toHaveCount(0);
    });

    await test.step("PM archives it, then a same-named recreation gets a distinct identity — no way to 'become' the old one", async () => {
      expect((await request.delete(`${api}/projects/${projectId}/requirements/${target.id}`, { headers: pmHeaders })).ok()).toBeTruthy();
      const recreated = await createRequirement(targetReqName);
      expect(recreated.id).not.toBe(target.id);
      expect(recreated.unique_code).not.toBe(target.unique_code);
    });
  });
});
