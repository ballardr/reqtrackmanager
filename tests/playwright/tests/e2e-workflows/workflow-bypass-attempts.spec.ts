import { expect, test } from "@playwright/test";

import { apiHeaders, createDisposableProject, installCleanupHook, loginAs, logout, onCleanup, openRequirementByName, ORG_NAMES, PERSONAS, PROJECT_NAMES } from "./helpers";

const apiBaseUrl = "http://localhost:8000";

/**
 * Job to be done: the requirement lifecycle's guarantees (edit-after-lock
 * requires a change request; only a PM can approve; archiving isn't a way
 * to quietly redefine an identifier) must hold even against a user
 * deliberately trying to route around them — not just against a well-
 * behaved UI. Each step below is an attempted bypass, followed by
 * confirmation it was actually blocked (both in the UI and, where it
 * matters, at the API directly).
 *
 * Uses a brand-new, disposable project inside the existing Alpha org
 * (created via the API, mirroring project-admin-structural.spec.ts), not
 * Alpha-1 — approving a stage locks *every* requirement in the project it
 * belongs to, which is fine to do once against a disposable project but
 * not safe against Alpha-1 itself: 27 other spec files reference Alpha-1,
 * and the lock is irreversible (no "unapprove" endpoint). Found during
 * Phase 1 of docs/platform-review-2026-09-plan.md (turning on Playwright
 * parallelism) — previously safe only because this suite ran single-
 * worker/serial. Also grants stakeholderAlpha/memberAlphaBeta project
 * roles on this disposable project rather than relying on their existing
 * Alpha-1 roles, revoking both again at the end per this repo's
 * idempotent-test convention (mirrors stage-review-and-completion.spec.ts's
 * own stakeholder-grant cleanup) — and archives the disposable project
 * itself (`POST .../archive`, which excludes it from the default project
 * list) rather than leaving it behind forever, so this spec doesn't add to
 * the same unbounded-list-growth failure mode found in role-display-
 * collapsing.spec.ts (see docs/decisions.md): a table/list that quietly
 * paginates past its default page can hide a just-created row from a
 * locator indefinitely, which reproduces deterministically once enough
 * leftover rows have accumulated — it isn't timing/contention flakiness
 * and isn't fixed by a bigger timeout.
 *
 * Trimmed 2026-10-04 (it took ~18s of its 30s budget alone and timed out
 * under full-suite load): setup, the stage approval and the archive-and-
 * recreate step go through the API (the UI for those is covered by
 * stage-review-and-completion, requirement-archive-confirm and the create
 * specs), the steps are ordered to need two UI logins instead of five, and
 * a change-request step that never ran (this project has none) is gone —
 * change-request-approval-separation covers that rule.
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
      for (const status of ["review", "approved"]) {
        const resp = await request.post(`${api}/projects/${projectId}/stages/${stages[0].id}/transition?new_status=${status}`, {
          headers: pmHeaders,
        });
        expect(resp.ok(), status).toBeTruthy();
      }
    });

    await test.step("the locked requirement offers no edit form in the UI", async () => {
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.goto(`/projects/${projectId}/requirements/${target.id}`);
      // Not exact: the requirement detail page's h1 is "{unique_code} —
      // {name}", not the bare name.
      await expect(page.locator("h1")).toContainText("—");
      await expect(page.getByText("Locked (approved)")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
    });

    await test.step("a raw API edit attempt against the same locked requirement still 409s", async () => {
      const resp = await request.put(`${api}/projects/${projectId}/requirements/${target.id}`, {
        headers: pmHeaders,
        data: {
          name: "Renamed via raw API bypass attempt", reasoning: "x", component_id: "00000000-0000-0000-0000-000000000000",
          category_id: "00000000-0000-0000-0000-000000000000", owner_id: "00000000-0000-0000-0000-000000000000", keywords: [],
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
      await expect(page.getByRole("button", { name: "Archive" })).toHaveCount(0);
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
