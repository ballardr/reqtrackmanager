import { expect, type Page, test } from "@playwright/test";

import { addDefinition, deleteOrgOnCleanup, ensureExpanded, installCleanupHook, PASSWORD, selectOrgAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: an organisation's project statuses and requirement link types are both organisation-wide
 * definition lists with the same add/rename/reorder/delete-with-reassignment contract. For project statuses:
 * deleting a status assigned to projects returns 409 and opens the in-use dialog, reassigning moves those
 * projects, an unused status deletes immediately with no prompt, and once a single status remains its delete
 * control is disabled. Link types get lighter add/rename/direction/delete-unused coverage: the shared
 * reassignment and last-row-disabled path is exercised for statuses and unit-tested against link types in
 * OrgAdminPage.stories.tsx.
 *
 * Uses a disposable organisation (which receives `DEFAULT_PROJECT_STATUSES`: Proposed/Active/Abandoned/Completed)
 * and two throwaway projects created through the API, because `seed_e2e_dataset.py` seeds once and a spec that
 * deletes shared seeded statuses can pass only on its first run.
 */

const apiBaseUrl = "http://localhost:8000";

/** Status/link-type names render as editable `<input>` value attributes
 * (the rename form), not plain text nodes — matches
 * project-admin-structural.spec.ts's own convention. */
function inputWithValue(page: Page, value: string) {
  // `:not([placeholder])`: the "add a new status/link type" row's own
  // input shares the `input.input` class and can transiently hold the
  // same text the test just typed into it — only a *rename* input for an
  // existing row is ever placeholder-less.
  return page.locator(`input.input[value="${value}"]:not([placeholder])`);
}

test.describe("org admin: project statuses and link types", () => {
  test("statuses: reassign-on-delete, plain delete, last-remaining-blocked; link types: add/rename/delete", async ({ page }) => {
    const suffix = Date.now();
    const orgName = `E2E Statuses Org ${suffix}`;
    const adminEmail = `e2e-statuses-admin-${suffix}@example.com`;

    const adminLoginResp = await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: "admin@example.com", password: "ChangeMe123!" },
    });
    const serverAdminToken = (await adminLoginResp.json()).access_token;
    const authHeaders = { Authorization: `Bearer ${serverAdminToken}` };

    const org = await (
      await page.request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: authHeaders, data: { name: orgName } })
    ).json();
    deleteOrgOnCleanup({ id: org.id });
    await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
      headers: authHeaders,
      data: { email: adminEmail, display_name: "E2E Statuses Admin", password: PASSWORD, role: "org_admin" },
    });

    const ownerToken = (
      await (
        await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })
      ).json()
    ).access_token;
    const ownerHeaders = { Authorization: `Bearer ${ownerToken}` };

    // Two throwaway projects — both default to the org's lowest-sort-order
    // status (`get_default_project_status_id`), i.e. "Proposed", the same
    // way Beta-1/Beta-2 did in the version of this spec that relied on
    // shared fixture data.
    const project1Name = `E2E Status Project A ${suffix}`;
    const project2Name = `E2E Status Project B ${suffix}`;
    const project1 = await (
      await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
        headers: ownerHeaders, data: { organization_id: org.id, name: project1Name, summary: "E2E seed project." },
      })
    ).json();
    await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: ownerHeaders, data: { organization_id: org.id, name: project2Name, summary: "E2E seed project." },
    });

    await page.goto("/login");
    await page.getByLabel("Email").fill(adminEmail);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    await test.step("navigate to the org's admin page", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await expect(page.getByRole("heading", { name: orgName })).toBeVisible();
    });

    await test.step("Project statuses: the 4 default statuses are present", async () => {
      // Project statuses and Link types both live in the "Projects &
      // workflow" resource-menu group — selecting the group is a real navigation, not a
      // client-side toggle, and must happen before either section is
      // reachable at all.
      await selectOrgAdminGroup(page, "Projects");
      await ensureExpanded(page, "Project statuses");
      for (const name of ["Proposed", "Active", "Abandoned", "Completed"]) {
        await expect(inputWithValue(page, name)).toBeVisible();
      }
    });

    await test.step("rename Active, then delete Proposed (in use by both throwaway projects) with reassignment to it", async () => {
      // Not chained off `activeInput`: once filled, its selector (matched by the old value) no longer resolves, and only
      // one row is dirty at a time, so the page-wide Rename button is unambiguous (as in project-admin-structural.spec.ts).
      await inputWithValue(page, "Active").fill("Active (E2E)");
      await page.getByRole("button", { name: "Rename" }).click();
      await expect(inputWithValue(page, "Active (E2E)")).toBeVisible();

      const proposedRow = inputWithValue(page, "Proposed").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await proposedRow.getByTitle("Delete this status").click();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByText(/used by \d+ project\(s\)/)).toBeVisible();
      await dialog.getByRole("combobox", { name: "Reassign existing items to" }).selectOption({ label: "Active (E2E)" });
      await dialog.getByRole("button", { name: "Confirm delete" }).click();
      await expect(inputWithValue(page, "Proposed")).toHaveCount(0);
    });

    await test.step("the first project's own settings tab now shows the reassigned status", async () => {
      await page.goto(`/projects/${project1.id}`);
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      // Not getByLabel("Status"): the "Parent project" <select> on this tab sits in an implicit <label> whose accessible
      // name includes every <option> text, and Project B (`E2E Status Project B ...`, a same-organisation sibling) is one
      // of those options, so the name also contains "Status". The Status <select> is located as the one whose options
      // include "Active (E2E)" (a status name, never a project name).
      const statusSelect = page.locator("select").filter({ hasText: "Active (E2E)" });
      await expect(statusSelect.locator("option:checked")).toHaveText("Active (E2E)");
    });

    await test.step("an unused status (Abandoned) deletes immediately, with no reassignment prompt", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Projects");
      await ensureExpanded(page, "Project statuses");

      const abandonedRow = inputWithValue(page, "Abandoned").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await abandonedRow.getByTitle("Delete this status").click();
      await expect(inputWithValue(page, "Abandoned")).toHaveCount(0);
      await expect(page.getByRole("dialog")).toHaveCount(0);

      const completedRow = inputWithValue(page, "Completed").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await completedRow.getByTitle("Delete this status").click();
      await expect(inputWithValue(page, "Completed")).toHaveCount(0);
    });

    await test.step("with only 'Active (E2E)' left, its delete control is disabled", async () => {
      await expect(inputWithValue(page, "Active (E2E)")).toBeVisible();
      await expect(page.getByTitle("This is the only one — create another first so there is something to reassign to.")).toBeDisabled();
    });

    await test.step("Link types: add a new type, rename it, then delete it (unused, no prompt)", async () => {
      await selectOrgAdminGroup(page, "Workflow");
      await ensureExpanded(page, "Link types");
      await expect(inputWithValue(page, "Depends on")).toBeVisible();

      await addDefinition(page, "New link type", { "Forward name": "E2E Precedes", "Reverse name": "E2E Is preceded by" });
      await expect(inputWithValue(page, "E2E Precedes")).toBeVisible();

      await inputWithValue(page, "E2E Precedes").fill("E2E Precedes v2");
      await page.getByRole("button", { name: "Rename" }).click();
      await expect(inputWithValue(page, "E2E Precedes v2")).toBeVisible();

      // Direction: a new type is unclassified; setting it is saved at once
      // (Toast) and survives a reload. Seeded "Derives from" is upstream.
      const direction = page.getByRole("combobox", { name: "Direction: E2E Precedes v2" });
      await expect(direction).toHaveValue("none");
      await expect(page.getByRole("combobox", { name: "Direction: Derives from" })).toHaveValue("forward_is_upstream");
      await direction.selectOption({ label: "Target is downstream" });
      await expect(page.getByText("Link type direction updated.")).toBeVisible();
      await page.reload();
      await selectOrgAdminGroup(page, "Workflow");
      await ensureExpanded(page, "Link types");
      await expect(page.getByRole("combobox", { name: "Direction: E2E Precedes v2" })).toHaveValue(
        "forward_is_downstream"
      );

      const row = inputWithValue(page, "E2E Precedes v2").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await row.getByTitle("Delete this link type").click();
      await expect(inputWithValue(page, "E2E Precedes v2")).toHaveCount(0);
      await expect(page.getByRole("dialog")).toHaveCount(0);
    });
  });
});
