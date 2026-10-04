import { expect, test } from "@playwright/test";

import { loginAs, logout, PASSWORD, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: a project stage's full lifecycle — scoping, a review
 * period stakeholders can explicitly approve or reject (C-R-05), PM
 * approval (which locks requirements and writes a baseline, C-G-10/C-G-12),
 * and completion, optionally cascaded to the stage's requirements (C-P-02,
 * C-P-03).
 *
 * Uses Alpha-2 (untouched by other specs in this suite) so its stage's
 * lifecycle state doesn't collide with Alpha-1's, which other specs lock
 * via their own "Approve stage" flow. Alpha-2 has no stakeholder seeded, so
 * this test grants one via a direct API call (this codebase's own
 * established pattern for setup steps the seed script doesn't cover)
 * purely to exercise the review-response UI as a real stakeholder.
 *
 * Creates its own dynamically-named stage and two dynamically-named
 * requirements targeting it, rather than reusing Alpha-2's single seeded
 * stage/requirements — a stage transition is one-way (scoping -> review ->
 * approved -> completed is terminal, with no "reopen" endpoint), so a
 * fixed stage exhausted by one run of this test would leave every
 * subsequent run unable to find "Start review" at all. Per this repo's
 * idempotent-test convention (test independence, standalone/repeat-safe),
 * each run gets its own fresh stage to cycle through and its own fresh
 * requirements to lock/complete, rather than mutating shared seed state.
 *
 * The stage itself is left behind permanently on every run, by necessity
 * rather than laziness: once approved it carries a `Baseline` record, and
 * `DELETE /projects/{id}/stages/{id}` refuses to delete any stage with
 * baseline history (C-G-10 — baselines are immutable). The two requirements
 * it creates *are* archived in a `finally` cleanup step below, though —
 * archiving (unlike stage deletion) has no such restriction, and bounding
 * the requirements list matters: an unrelated spec, role-display-collapsing
 * .spec.ts, was found flaking not from timing but from an analogous
 * unbounded-growth bug (its own throwaway project groups piling up past a
 * table's pagination window until a brand-new row landed off-page and a
 * locator waited forever for it) — see docs/decisions.md. Archiving these
 * requirements after each run keeps Alpha-2's active requirements list from
 * growing the same way, even though the stage row itself can't be avoided.
 *
 * Trimmed 2026-10-04: setup (the stage, its two requirements, the member's
 * 403 probe) goes through the API, requirements are opened by URL, and the
 * PM's session headers are captured once — only the PM's review/approve/
 * complete actions and the stakeholder's review response stay in the UI,
 * since those are what this spec tests. The previous all-UI version took
 * ~32s and timed out even against a raised 45s budget under full-suite
 * load. A stakeholder grant or requirements leaked by an interrupted run
 * are swept before starting.
 */
const API = "http://localhost:8000/api/v1";

test.describe("stage review deadlines and completion", () => {
  test("scoping -> review (with a deadline and a stakeholder response) -> approved -> completed, cascaded", async ({
    page,
  }) => {
    // Budget kept from the earlier root-caused decision (docs/decisions.md,
    // "bcrypt login cost under concurrent load"): three real UI logins plus
    // ~20 multi-persona UI round trips at ~0.8s each. The 2026-10-04 trim
    // cut runtime from ~32s to ~25s, so this is now ~20s of headroom, not a
    // blind bump.
    test.setTimeout(45_000);
    const stamp = Date.now();
    const stageName = `E2E Stage Cycle ${stamp}`;
    const reqNameA = `E2E Stage Cycle Req A ${stamp}`;
    const reqNameB = `E2E Stage Cycle Req B ${stamp}`;
    const reqUrl: Record<string, string> = {};

    // Deep-linked rather than via `selectProjectAdminGroup`, whose
    // `networkidle` wait costs ~2s per visit here; every action below
    // auto-waits for the stage row, so nothing relies on that wait.
    let structureUrl = "";

    function stageContainer() {
      // Scoped to this run's own stage row (by its rename `<input>` value):
      // Alpha-2 keeps every earlier run's completed stage alongside it.
      return page.locator(`input[value="${stageName}"]`).locator("xpath=../../..");
    }

    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    const pmHeaders = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem("reqtrack_token"))}` };
    await page.getByText(PROJECT_NAMES.alpha2).click();
    const projectId = page.url().match(/projects\/([0-9a-f-]+)/)![1];
    structureUrl = `/projects/${projectId}/admin/structure`;
    const { organization_id: orgId } = await (await page.request.get(`${API}/projects/${projectId}`, { headers: pmHeaders })).json();
    const users: { user_id: string; email: string }[] = await (
      await page.request.get(`${API}/orgs/${orgId}/users`, { headers: pmHeaders })
    ).json();
    const stakeholderId = users.find((u) => u.email === PERSONAS.stakeholderAlpha.email)!.user_id;

    /** Revokes the stakeholder grant on Alpha-2 and archives every "E2E
     * Stage Cycle Req" requirement — this run's and any leftovers. */
    async function sweep() {
      await page.request.delete(`${API}/projects/${projectId}/roles/${stakeholderId}/stakeholder`, { headers: pmHeaders });
      const reqs: { id: string; name: string }[] = await (
        await page.request.get(`${API}/projects/${projectId}/requirements?search=${encodeURIComponent("E2E Stage Cycle Req")}`, {
          headers: pmHeaders,
        })
      ).json();
      for (const req of reqs.filter((r) => r.name.startsWith("E2E Stage Cycle Req"))) {
        await page.request.delete(`${API}/projects/${projectId}/requirements/${req.id}`, { headers: pmHeaders });
      }
    }

    // `stakeholderAlpha` is a shared persona other specs assert an exact
    // project count for, so the Alpha-2 grant below must never outlive this
    // test — swept up front (an interrupted earlier run) and in `finally`.
    await sweep();
    try {
      await test.step("set up a fresh stage with two requirements targeting it", async () => {
        const stage = await (await page.request.post(`${API}/projects/${projectId}/stages`, {
          headers: pmHeaders, data: { name: stageName },
        })).json();
        const categories: { id: string; component_id: string }[] = await (
          await page.request.get(`${API}/projects/${projectId}/categories`, { headers: pmHeaders })
        ).json();
        for (const name of [reqNameA, reqNameB]) {
          const resp = await page.request.post(`${API}/projects/${projectId}/requirements`, {
            headers: pmHeaders,
            data: { name, component_id: categories[0].component_id, category_id: categories[0].id, target_stage_id: stage.id },
          });
          expect(resp.ok()).toBeTruthy();
          reqUrl[name] = `/projects/${projectId}/requirements/${(await resp.json()).id}`;
        }
      });

      await test.step("PM starts the stage's review and sets a deadline", async () => {
        await page.goto(structureUrl);
        await stageContainer().getByRole("button", { name: "Start review" }).click();
        await expect(stageContainer().getByText("In review", { exact: true })).toBeVisible();

        const future = new Date(Date.now() + 24 * 60 * 60 * 1000);
        await stageContainer().locator('input[type="datetime-local"]').fill(future.toISOString().slice(0, 16));
        await stageContainer().getByRole("button", { name: "Set review deadline" }).click();
        await expect(stageContainer().getByText("Review deadline:")).toBeVisible();
      });

      await test.step("a plain member cannot approve the stage via a direct API call, even while it's in review", async () => {
        const stages: { id: string; name: string }[] = await (
          await page.request.get(`${API}/projects/${projectId}/stages`, { headers: pmHeaders })
        ).json();
        const stageId = stages.find((s) => s.name === stageName)!.id;
        // memberAlphaBeta has no role at all on Alpha-2 — proves the check
        // is a real project-manager gate, not merely UI absence.
        const login = await page.request.post(`${API}/auth/login`, {
          data: { email: PERSONAS.memberAlphaBeta.email, password: PASSWORD },
        });
        const memberToken = (await login.json()).access_token;
        const resp = await page.request.post(
          `${API}/projects/${projectId}/stages/${stageId}/transition?new_status=approved`,
          { headers: { Authorization: `Bearer ${memberToken}` } },
        );
        expect(resp.status()).toBe(403);
      });

      await test.step("a stakeholder responds to the review through the real UI", async () => {
        await page.request.post(`${API}/projects/${projectId}/roles`, {
          headers: pmHeaders, data: { user_id: stakeholderId, role: "stakeholder" },
        });
        await logout(page);
        await loginAs(page, PERSONAS.stakeholderAlpha.email);
        await page.goto(structureUrl);
        await stageContainer().getByRole("button", { name: "Approve", exact: true }).click();
        await expect(stageContainer().getByText("In review", { exact: true })).toBeVisible();
      });

      await test.step("PM approves the stage, which locks its requirements and writes a baseline", async () => {
        await logout(page);
        await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
        await page.goto(structureUrl);
        await stageContainer().getByRole("button", { name: "Approve stage" }).click();
        await expect(stageContainer().getByRole("button", { name: "Approve stage" })).toHaveCount(0);

        await page.goto(reqUrl[reqNameA]);
        await expect(page.getByText("Status: Approved")).toBeVisible();
      });

      await test.step("a locked requirement can be marked completed directly by the PM (no change request needed)", async () => {
        // C-G-11: completion is an overlay marker independent of lifecycle
        // status (`Requirement.is_completed`) — the status badge stays
        // "Approved" throughout; a separate "Completed" badge toggles.
        await page.getByRole("button", { name: "Mark completed" }).click();
        await expect(page.getByText("Status: Approved")).toBeVisible();
        await expect(page.getByText("Completed", { exact: true })).toBeVisible();
        await page.getByRole("button", { name: "Revert completion" }).click();
        await expect(page.getByText("Status: Approved")).toBeVisible();
        await expect(page.getByText("Completed", { exact: true })).toHaveCount(0);
        await page.getByRole("button", { name: "Mark completed" }).click();
        await expect(page.getByText("Completed", { exact: true })).toBeVisible();
      });

      await test.step("PM completes the stage with cascade, which also completes its still-approved requirements", async () => {
        await page.goto(structureUrl);
        await stageContainer().getByLabel("Also mark this stage's approved requirements as completed").check();
        await stageContainer().getByRole("button", { name: "Mark stage completed" }).click();
        await expect(stageContainer().getByText("Implemented", { exact: true })).toBeVisible();

        // reqNameB was never manually completed — only the cascade marked it.
        await page.goto(reqUrl[reqNameB]);
        await expect(page.getByText("Status: Approved")).toBeVisible();
        await expect(page.getByText("Completed", { exact: true })).toBeVisible();
      });
    } finally {
      // Best-effort, with headers captured up front so it doesn't depend on
      // a live page session; must not mask the real failure.
      await sweep().catch(() => {});
    }
  });
});
