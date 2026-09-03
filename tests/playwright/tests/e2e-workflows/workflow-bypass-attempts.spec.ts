import { expect, test } from "@playwright/test";

import { loginAs, logout, PERSONAS, PROJECT_NAMES, selectProjectAdminGroup } from "./helpers";

/**
 * Job to be done: the requirement lifecycle's guarantees (edit-after-lock
 * requires a change request; only a PM can approve; archiving isn't a way
 * to quietly redefine an identifier) must hold even against a user
 * deliberately trying to route around them — not just against a well-
 * behaved UI. Each step below is an attempted bypass, followed by
 * confirmation it was actually blocked (both in the UI and, where it
 * matters, at the API directly).
 */
test.describe("attempts to bypass requirement/change-request workflow guarantees", () => {
  test("locking a stage, then probing edit/archive/approve boundaries", async ({ page }) => {
    // A throwaway requirement created fresh by this run, rather than the
    // seeded "Must log all state transitions" — this step's own later
    // steps archive it and recreate it under a derived name, which isn't
    // reversible from the UI, so reusing a fixed seeded name would leave
    // this test unable to pass a second time against the same database
    // (the seeded name would already be archived from the prior run). See
    // CLAUDE.md's non-idempotent-test convention.
    const targetReqName = `E2E Bypass Target ${Date.now()}`;

    await test.step("create the throwaway requirement this test will lock and archive", async () => {
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("button", { name: "New Requirement" }).click();
      const createPanel = page.getByRole("dialog", { name: "New Requirement" });
      await expect(createPanel.getByRole("combobox").first()).toContainText("Hardware");
      await page.getByPlaceholder("Name", { exact: true }).fill(targetReqName);
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByText(targetReqName)).toBeVisible();
    });

    await test.step("PM approves Alpha-1's stage, locking all its requirements", async () => {
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
    await test.step("a locked requirement offers no edit form in the UI", async () => {
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("link", { name: "Must support configuration via file" }).click();
      lockedRequirementUrl = page.url();
      // React Router 7 wraps navigation in React's startTransition by
      // default (a behavior change from 6): the URL updates immediately,
      // but the requirements list this just navigated from — now showing
      // every one of Alpha-1's requirements locked by the stage approval
      // above, each with its own "Locked (approved)" badge — can stay
      // mounted for a beat longer, making a bare `getByText` match more
      // than one badge. Waiting for this requirement's own heading first
      // (unique to its detail page) proves the transition has actually
      // landed before checking the — otherwise possibly-transient —
      // lock status.
      // Not exact: the requirement detail page's h1 is "{unique_code} —
      // {name}" (e.g. "SW-PERF-002 — Must support configuration via
      // file"), not the bare name.
      await expect(page.getByRole("heading", { name: "Must support configuration via file" })).toBeVisible();
      await expect(page.getByText("Locked (approved)")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
    });

    await test.step("a raw API edit attempt against the same locked requirement still 409s", async () => {
      const token = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const match = lockedRequirementUrl.match(/projects\/([0-9a-f-]+)\/requirements\/([0-9a-f-]+)/);
      const [, projectId, requirementId] = match!;
      const resp = await page.request.put(
        `http://localhost:8000/api/v1/projects/${projectId}/requirements/${requirementId}`,
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
      await page.getByText(PROJECT_NAMES.alpha1).click();
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
      await page.getByText(PROJECT_NAMES.alpha1).click();
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
      // any CR on the project — the point is the role check, not the status.
      const projectUrl = page.url().match(/projects\/([0-9a-f-]+)/)![1];
      const crsResp = await page.request.get(`http://localhost:8000/api/v1/projects/${projectUrl}/change-requests`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const crs = await crsResp.json();
      if (crs.length > 0) {
        await logout(page);
        await loginAs(page, PERSONAS.memberAlphaBeta.email);
        const memberToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
        const resp = await page.request.post(
          `http://localhost:8000/api/v1/projects/${projectUrl}/change-requests/${crs[0].id}/decide`,
          { headers: { Authorization: `Bearer ${memberToken}` }, data: { approve: true, note: "unauthorized attempt" } }
        );
        expect(resp.status()).toBe(403);
      }
    });

    await test.step("cross-org ID guessing: a single-org user cannot open another org's project by URL", async () => {
      await logout(page);
      await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
      const pmToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const projectsResp = await page.request.get("http://localhost:8000/api/v1/projects?archived=false", {
        headers: { Authorization: `Bearer ${pmToken}` },
      });
      const projects = await projectsResp.json();
      const beta1 = projects.find((p: { name: string }) => p.name === PROJECT_NAMES.beta1);

      await logout(page);
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      const stakeholderToken = await page.evaluate(() => localStorage.getItem("reqtrack_token"));
      const resp = await page.request.get(`http://localhost:8000/api/v1/projects/${beta1.id}`, {
        headers: { Authorization: `Bearer ${stakeholderToken}` },
      });
      expect(resp.status()).toBe(403);

      // Also confirm the UI itself doesn't render Beta-1's content if
      // navigated to directly by URL, not just that the API rejects it.
      await page.goto(`/projects/${beta1.id}`);
      await expect(page.getByText(PROJECT_NAMES.beta1)).toHaveCount(0);
    });
  });
});
