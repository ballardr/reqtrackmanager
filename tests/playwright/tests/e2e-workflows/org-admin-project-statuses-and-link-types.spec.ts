import { expect, type Page, test } from "@playwright/test";

import { ensureExpanded, PASSWORD, selectOrgAdminGroup } from "./helpers";

/**
 * Job to be done: an organisation's project statuses and requirement link
 * types are both org-wide definition lists sharing the same
 * add/rename/reorder/delete-with-reassignment contract (§4.0 of the
 * traceability plan). Covers, for project statuses: deleting a status
 * currently assigned to real projects 409s and opens a reassignment
 * picker, reassigning moves those projects, an unused status deletes
 * immediately with no prompt, and once a single status remains its delete
 * control is disabled outright. Link types get lighter add/rename/delete-
 * unused coverage — the identical shared reassignment/last-row-disabled
 * code path is already exercised end-to-end above (statuses) and unit-
 * tested directly against link types in OrgAdminPage.stories.tsx.
 *
 * Uses a brand-new, disposable organisation + two throwaway projects
 * created via the API, not the shared "E2E Beta Software" org this spec
 * previously ran against. Found and fixed along the way (not part of the
 * 2026-08 UX audit roadmap batch that prompted a look at this file, but a
 * genuine bug per this project's own "fix, don't defer" rule): the
 * previous version deleted 3 of Beta org's 4 seeded default statuses down
 * to a single renamed one, permanently — `seed_e2e_dataset.py` only seeds
 * once ("already seeded, exiting" on a re-run), so this spec could only
 * ever pass the *first* time it ran against a given database, not
 * standalone-repeated or after an earlier full-suite run had already done
 * it once. A dedicated org (which gets the same `DEFAULT_PROJECT_STATUSES`
 * — Proposed/Active/Abandoned/Completed — automatically on creation, same
 * as every org) plus dedicated projects (which default to the org's
 * lowest-sort-order status, i.e. "Proposed", same as Beta-1/Beta-2 did)
 * reproduces the exact same scenario while never touching shared fixture
 * data, so the spec is now idempotent standalone or repeated.
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
      // workflow" resource-menu group (2026-08 UX audit's Org Admin
      // restructure) — selecting the group is a real navigation, not a
      // client-side toggle, and must happen before either section is
      // reachable at all.
      await selectOrgAdminGroup(page, "Projects & workflow");
      await ensureExpanded(page, "Project statuses");
      for (const name of ["Proposed", "Active", "Abandoned", "Completed"]) {
        await expect(inputWithValue(page, name)).toBeVisible();
      }
    });

    await test.step("rename Active, then delete Proposed (in use by both throwaway projects) with reassignment to it", async () => {
      // Not chained off `activeInput`: once filled, its own selector
      // (matched by the *old* value) no longer resolves to anything — only
      // one row is ever "dirty" at a time, so the plain, page-wide Rename
      // button is unambiguous here (same pattern as
      // project-admin-structural.spec.ts).
      await inputWithValue(page, "Active").fill("Active (E2E)");
      await page.getByRole("button", { name: "Rename" }).click();
      await expect(inputWithValue(page, "Active (E2E)")).toBeVisible();

      const proposedRow = inputWithValue(page, "Proposed").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await proposedRow.getByTitle("Delete this status").click();
      await expect(page.getByText(/used by \d+ project\(s\)/)).toBeVisible();
      await page.getByText("Reassign existing items to").locator("xpath=..").getByRole("combobox").selectOption({ label: "Active (E2E)" });
      await page.getByRole("button", { name: "Confirm delete" }).click();
      await expect(inputWithValue(page, "Proposed")).toHaveCount(0);
    });

    await test.step("the first project's own settings tab now shows the reassigned status", async () => {
      await page.goto(`/projects/${project1.id}`);
      await page.getByRole("link", { name: "Project admin", exact: true }).click();
      // Not getByLabel("Status"): hierarchical projects added a "Parent
      // project" <select> to this same tab, wrapped by an implicit
      // <label> the same way the Status field is — a wrapping <label>'s
      // computed accessible name flattens in all descendant text,
      // including every <option>'s text, not just the label's own words.
      // Project B (this test's own reassignment-target fixture, named
      // `E2E Status Project B ...`) is a same-org sibling and so appears
      // as one of "Parent project"'s <option>s, making its accessible
      // name legitimately contain the substring "Status" too — a real,
      // reproducible ambiguity (not stale test debris this time), found
      // and fixed here rather than deferred. Located structurally instead:
      // the Status <select> is the one whose own <option> list contains
      // "Active (E2E)" (a status name, never a project name).
      const statusSelect = page.locator("select").filter({ has: page.locator("option", { hasText: "Active (E2E)" }) });
      await expect(statusSelect.locator("option:checked")).toHaveText("Active (E2E)");
    });

    await test.step("an unused status (Abandoned) deletes immediately, with no reassignment prompt", async () => {
      await page.goto(`/orgs/${org.id}/admin`);
      await selectOrgAdminGroup(page, "Projects & workflow");
      await ensureExpanded(page, "Project statuses");

      const abandonedRow = inputWithValue(page, "Abandoned").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await abandonedRow.getByTitle("Delete this status").click();
      await expect(inputWithValue(page, "Abandoned")).toHaveCount(0);
      await expect(page.getByText("Reassign existing items to")).toHaveCount(0);

      const completedRow = inputWithValue(page, "Completed").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await completedRow.getByTitle("Delete this status").click();
      await expect(inputWithValue(page, "Completed")).toHaveCount(0);
    });

    await test.step("with only 'Active (E2E)' left, its delete control is disabled", async () => {
      await expect(inputWithValue(page, "Active (E2E)")).toBeVisible();
      await expect(page.getByTitle("This is the only one — create another first so there's something to reassign to.")).toBeDisabled();
    });

    await test.step("Link types: add a new type, rename it, then delete it (unused, no prompt)", async () => {
      await selectOrgAdminGroup(page, "Projects & workflow");
      await ensureExpanded(page, "Link types");
      await expect(inputWithValue(page, "Depends on")).toBeVisible();

      const newForward = page.getByPlaceholder("Forward name").last();
      const newReverse = page.getByPlaceholder("Reverse name").last();
      await newForward.fill("E2E Precedes");
      await newReverse.fill("E2E Is preceded by");
      await page.getByRole("button", { name: "New link type" }).click();
      await expect(inputWithValue(page, "E2E Precedes")).toBeVisible();

      await inputWithValue(page, "E2E Precedes").fill("E2E Precedes v2");
      await page.getByRole("button", { name: "Rename" }).click();
      await expect(inputWithValue(page, "E2E Precedes v2")).toBeVisible();

      const row = inputWithValue(page, "E2E Precedes v2").locator("xpath=ancestor::div[contains(@class,'stack')][1]");
      await row.getByTitle("Delete this link type").click();
      await expect(inputWithValue(page, "E2E Precedes v2")).toHaveCount(0);
      await expect(page.getByText("Reassign existing items to")).toHaveCount(0);
    });
  });
});
