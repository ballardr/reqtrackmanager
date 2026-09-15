import { expect, test } from "@playwright/test";

import { loginAs, logout, PERSONAS, PROJECT_NAMES, selectProjectAdminGroup } from "./helpers";

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
 */
test.describe("attempts to bypass requirement/change-request workflow guarantees", () => {
  test("locking a stage, then probing edit/archive/approve boundaries", async ({ page }) => {
    const suffix = Date.now();
    const projectName = `E2E Bypass Project ${suffix}`;
    const targetReqName = `E2E Bypass Target ${suffix}`;
    let projectId = "";
    let stakeholderId = "";
    let memberId = "";

    // The grants below land on `stakeholderAlpha`/`memberAlphaBeta` — shared
    // personas other specs assert an exact project count for — so the whole
    // body is wrapped in try/finally: an earlier version only revoked them
    // as the test's own last step, with nothing guarding against an earlier
    // step throwing or timing out first and skipping it, leaking the grants
    // past this run. Mirrors project-hierarchy.spec.ts's/stage-review-and-
    // completion.spec.ts's identical fix for the identical shape.
    try {
      await test.step("PM creates a disposable project (with matching Hardware structure) and its throwaway requirement", async () => {
        await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
        const pmToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
        const pmHeaders = { Authorization: `Bearer ${pmToken}` };

        const orgsResp = await page.request.get(`${apiBaseUrl}/api/v1/orgs`, { headers: pmHeaders });
        const orgs: { id: string; name: string }[] = await orgsResp.json();
        const alphaOrgId = orgs.find((o) => o.name === "E2E Alpha Robotics")!.id;

        const project = await (
          await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
            headers: pmHeaders, data: { organization_id: alphaOrgId, name: projectName, summary: "E2E seed project." },
          })
        ).json();
        projectId = project.id;

        // Same Hardware component this project's "New Requirement" panel
        // check below expects, mirroring project-admin-structural.spec.ts's
        // own disposable-project setup.
        const hw = await (
          await page.request.post(`${apiBaseUrl}/api/v1/projects/${projectId}/components`, {
            headers: pmHeaders, data: { name: "Hardware", prefix: "HW" },
          })
        ).json();
        await page.request.post(`${apiBaseUrl}/api/v1/projects/${projectId}/categories`, {
          headers: pmHeaders, data: { name: "Functional", prefix: "FN", component_id: hw.id },
        });

        const usersResp = await page.request.get(`${apiBaseUrl}/api/v1/orgs/${alphaOrgId}/users`, { headers: pmHeaders });
        const users: { user_id: string; email: string }[] = await usersResp.json();
        stakeholderId = users.find((u) => u.email === PERSONAS.stakeholderAlpha.email)!.user_id;
        memberId = users.find((u) => u.email === PERSONAS.memberAlphaBeta.email)!.user_id;
        await page.request.post(`${apiBaseUrl}/api/v1/projects/${projectId}/roles`, {
          headers: pmHeaders, data: { user_id: stakeholderId, role: "stakeholder" },
        });
        await page.request.post(`${apiBaseUrl}/api/v1/projects/${projectId}/roles`, {
          headers: pmHeaders, data: { user_id: memberId, role: "member" },
        });

        await page.goto(`/projects/${projectId}`);
        await page.getByRole("link", { name: "Requirements", exact: true }).click();
        await page.getByRole("button", { name: "New Requirement" }).click();
        const createPanel = page.getByRole("dialog", { name: "New Requirement" });
        await expect(createPanel.getByRole("combobox").first()).toContainText("Hardware");
        await page.getByPlaceholder("Name", { exact: true }).fill(targetReqName);
        await page.getByRole("button", { name: "Create", exact: true }).click();
        await expect(page.getByText(targetReqName)).toBeVisible();
      });

      await test.step("PM approves the disposable project's stage, locking all its requirements", async () => {
        await page.getByRole("link", { name: "Project admin", exact: true }).click();
        // Project stages now lives inside the merged "Structure" tab
        // (2026-08 UX audit roadmap: Project Admin's 8 tabs -> 5).
        await selectProjectAdminGroup(page, "Structure");
        // A stage must be in review before it can be approved — start review
        // first if the stage is still in scoping (idempotent against a
        // re-run: only clicked when the button is actually present).
        const startReviewButton = page.getByRole("button", { name: "Start review" });
        if (await startReviewButton.count()) {
          await startReviewButton.click();
          // Wait for the transition to actually land before looking for
          // "Approve stage" below — it's gated on status === "review", so
          // checking its count() immediately after the click (before the
          // page has refetched/re-rendered) can race and read 0, silently
          // skipping the approval and leaving the stage stuck in review.
          await expect(page.getByText("In review", { exact: true })).toBeVisible();
        }
        const approveButton = page.getByRole("button", { name: "Approve stage" });
        if (await approveButton.count()) {
          await approveButton.click();
        }
        await expect(page.getByRole("button", { name: "Approve stage" })).toHaveCount(0);
        // ProjectAdminPage's reload() after a mutation fires several
        // requests, not just one (same pattern documented in golden-path.
        // spec.ts) — the "Approve stage" button disappearing only proves
        // *this tab's* own status re-render landed, not that every
        // requirement targeting this stage has finished being re-fetched
        // as locked. Without this, the very next step can navigate to a
        // specific requirement and find it still showing its pre-lock,
        // editable state — a genuine intermittent race, not a false
        // positive, reproduced by running this spec repeatedly.
        await page.waitForLoadState("networkidle");
      });

      let lockedRequirementUrl = "";
      await test.step("the locked requirement offers no edit form in the UI", async () => {
        await page.getByRole("link", { name: "Requirements", exact: true }).click();
        await page.getByRole("link", { name: targetReqName, exact: true }).click();
        lockedRequirementUrl = page.url();
        // Not exact: the requirement detail page's h1 is "{unique_code} —
        // {name}", not the bare name.
        await expect(page.locator("h1")).toContainText("—");
        await expect(page.getByText("Locked (approved)")).toBeVisible();
        await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
      });

      await test.step("a raw API edit attempt against the same locked requirement still 409s", async () => {
        const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
        const match = lockedRequirementUrl.match(/projects\/([0-9a-f-]+)\/requirements\/([0-9a-f-]+)/);
        const [, matchedProjectId, requirementId] = match!;
        const resp = await page.request.put(
          `${apiBaseUrl}/api/v1/projects/${matchedProjectId}/requirements/${requirementId}`,
          {
            headers: { Authorization: `Bearer ${token}` },
            data: {
              name: "Renamed via raw API bypass attempt", reasoning: "x", component_id: "00000000-0000-0000-0000-000000000000",
              category_id: "00000000-0000-0000-0000-000000000000", owner_id: "00000000-0000-0000-0000-000000000000", keywords: [],
            },
          }
        );
        expect(resp.status()).toBe(409);
      });

      await test.step("archiving a locked requirement is hidden from a non-PM stakeholder", async () => {
        await logout(page);
        await loginAs(page, PERSONAS.stakeholderAlpha.email);
        await page.goto(`/projects/${projectId}`);
        await page.getByRole("link", { name: "Requirements", exact: true }).click();
        await page.getByRole("link", { name: targetReqName, exact: true }).click();
        await expect(page.getByRole("button", { name: "Archive" })).toHaveCount(0);
      });

      let archivedCode = "";
      let newCode = "";
      const newReqName = `${targetReqName} (recreated)`;
      await test.step("PM archives it, then a same-named recreation gets a distinct identity — no way to 'become' the old one", async () => {
        await logout(page);
        await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
        await page.goto(`/projects/${projectId}`);
        await page.getByRole("link", { name: "Requirements", exact: true }).click();
        await page.getByRole("link", { name: targetReqName, exact: true }).click();
        // Wait for the detail page's own content to land before reading its
        // `<h1>` — a bare click + immediate textContent() read can catch the
        // requirements list page's own `<h1>` (no em dash) during the
        // client-side route transition, same race documented on
        // `openRequirementByCode` in helpers.ts.
        await expect(page.locator("h1")).toContainText("—");
        archivedCode = (await page.locator("h1").textContent())!.split(" — ")[0].trim();
        // Archiving a requirement now confirms first, via the shared
        // ConfirmDialog (2026-08 UX audit fix — see
        // requirement-archive-confirm.spec.ts for the dedicated coverage of
        // that dialog itself).
        await page.getByRole("button", { name: "Archive" }).click();
        const archiveDialog = page.getByRole("dialog", { name: "Archive this requirement?" });
        await archiveDialog.getByRole("button", { name: "Archive", exact: true }).click();
        await page.waitForURL(/\/requirements$/);
        await expect(page.getByText(targetReqName, { exact: true })).toHaveCount(0);

        await page.getByRole("button", { name: "New Requirement" }).click();
        // The create form is a `Modal` portalled to the end of
        // `document.body` — scope to it rather than an unscoped
        // `getByRole("combobox").first()`, which would otherwise resolve to
        // the filter sidebar's own Status select (it precedes the panel in
        // DOM order once the form is a portal instead of an inline block).
        // Component/category selects default asynchronously once project data
        // loads — wait so Create doesn't submit with an empty component_id.
        const panel = page.getByRole("dialog", { name: "New Requirement" });
        await expect(panel.getByRole("combobox").first()).toContainText("Hardware");
        await page.getByPlaceholder("Name", { exact: true }).fill(newReqName);
        await page.getByRole("button", { name: "Create", exact: true }).click();
        await expect(page.getByText(newReqName)).toBeVisible();
        await page.getByText(newReqName).click();
        // Same route-transition race as above.
        await expect(page.locator("h1")).toContainText("—");
        newCode = (await page.locator("h1").textContent())!.split(" — ")[0].trim();

        expect(newCode).not.toBe(archivedCode);
      });

      await test.step("a project member with no PM role cannot decide a change request via a direct API call either", async () => {
        const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
        // fetch an existing submitted/in-review CR to target, or fall back to
        // any CR on the project — the point is the role check, not the
        // status. This disposable project starts with none, so this step is
        // a no-op unless a future revision seeds one — the same behaviour
        // dedicated CR-permission specs (e.g. change-request-approval-
        // separation.spec.ts) already cover independently.
        const crsResp = await page.request.get(`${apiBaseUrl}/api/v1/projects/${projectId}/change-requests`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const crs = await crsResp.json();
        if (crs.length > 0) {
          await logout(page);
          await loginAs(page, PERSONAS.memberAlphaBeta.email);
          const memberToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
          const resp = await page.request.post(
            `${apiBaseUrl}/api/v1/projects/${projectId}/change-requests/${crs[0].id}/decide`,
            { headers: { Authorization: `Bearer ${memberToken}` }, data: { approve: true, note: "unauthorized attempt" } }
          );
          expect(resp.status()).toBe(403);
        }
      });

      await test.step("cross-org ID guessing: a single-org user cannot open another org's project by URL", async () => {
        await logout(page);
        await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
        const pmToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
        const projectsResp = await page.request.get(`${apiBaseUrl}/api/v1/projects?archived=false`, {
          headers: { Authorization: `Bearer ${pmToken}` },
        });
        const projects = await projectsResp.json();
        const beta1 = projects.find((p: { name: string }) => p.name === PROJECT_NAMES.beta1);

        await logout(page);
        await loginAs(page, PERSONAS.stakeholderAlpha.email);
        const stakeholderToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
        const resp = await page.request.get(`${apiBaseUrl}/api/v1/projects/${beta1.id}`, {
          headers: { Authorization: `Bearer ${stakeholderToken}` },
        });
        expect(resp.status()).toBe(403);

        // Also confirm the UI itself doesn't render Beta-1's content if
        // navigated to directly by URL, not just that the API rejects it.
        await page.goto(`/projects/${beta1.id}`);
        await expect(page.getByText(PROJECT_NAMES.beta1)).toHaveCount(0);
      });
    } finally {
      await test.step("clean up: revoke stakeholderAlpha/memberAlphaBeta's grants and archive the disposable project, best-effort so an earlier failure isn't masked", async () => {
        // Both are shared personas other specs assert specific role/project
        // counts for (see stage-review-and-completion.spec.ts's identical
        // cleanup) — the grant itself would otherwise persist on these
        // shared personas past this test. No grant was ever attempted if
        // the very first step (which sets `projectId`/`stakeholderId`/
        // `memberId`) didn't complete.
        if (!projectId) return;
        try {
          await logout(page);
          await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
          const pmToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
          const pmHeaders = { Authorization: `Bearer ${pmToken}` };
          if (stakeholderId) {
            await page.request.delete(`${apiBaseUrl}/api/v1/projects/${projectId}/roles/${stakeholderId}/stakeholder`, {
              headers: pmHeaders,
            });
          }
          if (memberId) {
            await page.request.delete(`${apiBaseUrl}/api/v1/projects/${projectId}/roles/${memberId}/member`, {
              headers: pmHeaders,
            });
          }
          // Archive (not just revoke roles) the disposable project itself
          // so it drops out of the default (archived=false) project list —
          // otherwise it accumulates alongside every other run's, forever.
          await page.request.post(`${apiBaseUrl}/api/v1/projects/${projectId}/archive`, { headers: pmHeaders });
        } catch {
          // Best-effort: a failure here must not replace/mask whatever the
          // `try` block above actually failed with.
        }
      });
    }
  });
});
