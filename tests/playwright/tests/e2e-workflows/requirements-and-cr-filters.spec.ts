import { expect, test } from "@playwright/test";

import { loginAs, openProject, PERSONAS, PROJECT_NAMES, searchChangeRequests } from "./helpers";

/**
 * Job to be done: the requirements list can be narrowed by search (name/ID, U-E-01), status/target-version/category
 * filters, and has-comments/only-watched checkboxes; the tile/list view choice persists across a reload (synced
 * server-side, not only in localStorage).
 *
 * badge-filters.spec.ts covers the status-badge click-to-filter interaction; this spec covers the FilterPanel's
 * remaining controls.
 *
 * RequirementsPage's fetch effect has no request-cancellation guard, so a new filtered fetch while a previous one is
 * in flight can let the older response resolve later and overwrite the newer one. `settled()` waits for the
 * known-unfiltered baseline (both HW-FN-001 and a requirement not matching the previous filter are visible) before
 * the next filter change, so each change starts from a quiescent list.
 */
test.describe("requirements list filters and view-mode persistence", () => {
  test("search, status/category filters, has-comments/watched checkboxes, and view-mode persistence", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

    // A throwaway requirement, guaranteed to start (and stay) `draft`, for the "not approved" side of the status filter
    // check: `workflow-bypass-attempts.spec.ts` approves Alpha-1's whole "Scoping" stage baseline, an irreversible action
    // that locks every requirement in that stage at the time, including the seeded "Must expose a health-check
    // endpoint". A requirement created fresh by this test starts `draft` regardless (a stage approval locks requirements
    // that existed at that moment, not a standing rule), so the spec passes before or after that spec.
    const draftReqName = `E2E Filter Draft Target ${Date.now()}`;
    await page.getByRole("button", { name: "New Requirement" }).click();
    const createPanel = page.getByRole("dialog", { name: "New Requirement" });
    await createPanel.getByPlaceholder("Name", { exact: true }).fill(draftReqName);
    await createPanel.getByRole("button", { name: "Create", exact: true }).click();
    await expect(createPanel).not.toBeVisible();

    async function settled() {
      await expect(page.getByText("HW-FN-001")).toBeVisible();
      await expect(page.getByRole("link", { name: "Must expose a health-check endpoint", exact: true })).toBeVisible();
    }

    await settled();

    await test.step("search narrows by name substring and by unique ID", async () => {
      const searchBox = page.getByPlaceholder("Search by name or ID");
      // Uses "Must expose a health-check endpoint" rather than HW-FN-001's
      // requirement — change-request-approval-separation.spec.ts approves a
      // CR that renames HW-FN-001, so its name isn't stable across the
      // suite. HW-FN-001's *code* is still stable, so it's used for the
      // by-ID half below instead.
      await searchBox.fill("health-check endpoint");
      await expect(page.getByRole("link", { name: "Must expose a health-check endpoint", exact: true })).toBeVisible();
      await expect(page.getByText("HW-FN-001")).toHaveCount(0);

      await searchBox.fill("HW-FN-001");
      await expect(page.getByText("HW-FN-001")).toBeVisible();

      await searchBox.fill("zzz-nothing-matches-zzz");
      await expect(page.getByText("No requirements to show.")).toBeVisible();
      await searchBox.fill("");
      await settled();
    });

    await test.step("status filter narrows the list", async () => {
      await page.getByLabel("Status", { exact: true }).selectOption("approved");
      await expect(page.getByText("HW-FN-001")).toBeVisible();
      await expect(page.getByText(draftReqName)).toHaveCount(0);
      await page.getByLabel("Status", { exact: true }).selectOption("");
      await settled();
    });

    await test.step("completed filter narrows the list independently of status (C-G-11)", async () => {
      // "Completed" is not a status <select> option (it is the separate `Requirement.is_completed` overlay); a dedicated
      // filter checkbox sits beside Status.
      const statusOptionLabels = await page.getByLabel("Status", { exact: true }).locator("option").allTextContents();
      expect(statusOptionLabels).not.toContain("Completed");

      // exact: true — getByLabel does substring matching by default, and a
      // throwaway requirement left behind by change-request-approval-separation.spec.ts
      // is literally named "E2E Completed Target ... (revised)"; its
      // bulk-select row checkbox's accessible name contains that name, which
      // otherwise collides with this filter checkbox's "Completed" label
      // under strict mode whenever that spec has already run in the shared DB.
      const completedFilterCheckbox = page.getByLabel("Completed", { exact: true });
      await completedFilterCheckbox.check();
      await expect(page.getByText(draftReqName)).toHaveCount(0);
      await completedFilterCheckbox.uncheck();
      await settled();
    });

    await test.step("component and category filter narrows the list", async () => {
      await page.getByRole("button", { name: "Component and category", exact: true }).click();
      const choices = page.getByRole("group", { name: "Component and category" });
      const category = choices.getByRole("checkbox", { name: / \/ / }).first();
      if (await category.count()) {
        await category.check();
        await expect(page.getByText("No requirements to show.")).toHaveCount(0);
        await category.uncheck();
        await settled();
      }
      await page.keyboard.press("Escape");
    });

    await test.step("has-comments-only and only-watched checkboxes toggle without erroring", async () => {
      await page.getByLabel("Has comments").check();
      await page.getByLabel("Has comments").uncheck();
      await page.getByLabel("Only watched").check();
      await page.getByLabel("Only watched").uncheck();
      await settled();
    });

    await test.step("switching to list view persists across a reload", async () => {
      // Wait for the PATCH to settle before reloading: a bare click() races the async save (AuthContext.tsx's
      // setUiPreference is fire-and-forget) against the immediate reload, which can observe the pre-save state; as in
      // preferences-and-theme.spec.ts's "pronouns save and persist" step.
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH"),
        page.getByRole("button", { name: "List view" }).click(),
      ]);
      await expect(page.getByRole("button", { name: "List view" })).toHaveAttribute("aria-pressed", "true");
      await page.reload();
      await expect(page.getByRole("button", { name: "List view" })).toHaveAttribute("aria-pressed", "true");
    });

    // Column-header sorting: this list is backend-paginated, so a header click refetches with `sort`/`order` query
    // params. Asserts general sortedness of the ID column's displayed text rather than specific rows, since which
    // requirements exist can shift; ID (`unique_code`) has no null-fallback display (unlike Name on the CR side), so
    // comparing displayed text against its own sorted copy is a faithful check.
    await test.step("column-header sorting: ID ascending then descending", async () => {
      const idHeader = page.getByRole("button", { name: "ID" });
      const idHeaderCell = page.locator("th", { has: idHeader });

      // The first `td.text-muted` in each row is always the ID cell,
      // whether or not the bulk-select checkbox column (a plain `<td>`
      // with no class) is present ahead of it for this manager persona.
      async function visibleIds(): Promise<string[]> {
        return page.locator("table tbody tr").evaluateAll((rows) =>
          rows.map((row) => row.querySelector("td.text-muted")?.textContent?.trim() ?? "")
        );
      }

      // `aria-sort` flips synchronously on click, before the refetch has landed; `toPass()` retries the sortedness check
      // rather than reading the table once after the attribute changes, which can race a still-in-flight response.
      async function assertSorted(reversed: boolean) {
        await expect(async () => {
          const ids = await visibleIds();
          expect(ids.length).toBeGreaterThan(1);
          const sorted = [...ids].sort();
          expect(ids).toEqual(reversed ? sorted.reverse() : sorted);
        }).toPass();
      }

      const [ascResponse] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/requirements?") && r.url().includes("sort=unique_code") && r.url().includes("order=asc")),
        idHeader.click(),
      ]);
      expect(ascResponse.ok()).toBe(true);
      await expect(idHeaderCell).toHaveAttribute("aria-sort", "ascending");
      await assertSorted(false);

      const [descResponse] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/requirements?") && r.url().includes("sort=unique_code") && r.url().includes("order=desc")),
        idHeader.click(),
      ]);
      expect(descResponse.ok()).toBe(true);
      await expect(idHeaderCell).toHaveAttribute("aria-sort", "descending");
      await assertSorted(true);

      // Third click returns to the default (unsorted) order.
      await idHeader.click();
      await expect(idHeaderCell).toHaveAttribute("aria-sort", "none");
      await page.getByRole("button", { name: "Tile view" }).click();
    });
  });
});

/**
 * Change requests list sorting, in a separate `describe` because it needs its own fixtures: `ChangeRequest.proposed_name`
 * is nullable and the list falls back to the linked requirement's name for display (`crTitle()` in
 * ChangeRequestsPage.tsx), a fallback sorting the raw column cannot see (documented on the backend endpoint), so
 * comparing displayed text against an alphabetic sort of seed data would be unreliable. Two change requests with
 * distinct, non-null proposed names avoid that.
 */
test.describe("change requests list sorting", () => {
  test("sort by name ascending and descending via the column header", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Change requests", exact: true }).click();

    const suffix = Date.now();
    const firstName = `AAA Sort Test CR ${suffix}`;
    const secondName = `ZZZ Sort Test CR ${suffix}`;

    async function createChangeRequest(name: string) {
      await page.getByRole("button", { name: /New/ }).click();
      await page.getByRole("radio", { name: "New requirement" }).click();
      await page.getByLabel("Proposed name").fill(name);
      await page.getByLabel("Reason for change").fill("Sort test fixture.");
      // `exact: true` — a bare "Create" substring-matches the "Created"
      // sortable column header too (`SortableHeader`'s button text).
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
    }

    await createChangeRequest(firstName);
    await createChangeRequest(secondName);

    await page.getByRole("button", { name: "List view" }).click();
    // Narrowed to this run's two fixtures first: sorting the whole, ever-
    // growing Alpha-1 list put "ZZZ…" past the first page when ascending
    // (and earlier runs' "AAA…" rows ahead of this one's).
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/change-requests?") && r.url().includes(`search=Sort+Test+CR+${suffix}`)),
      searchChangeRequests(page, `Sort Test CR ${suffix}`),
    ]);
    const nameHeader = page.getByRole("button", { name: "Name" });
    const nameHeaderCell = page.locator("th", { has: nameHeader });

    // Only the two fixture rows' relative order is asserted: other change requests in this shared project have
    // uncontrolled proposed names. `aria-sort` flips synchronously on click, before the refetch has landed, so the test
    // waits on the network response rather than the attribute, to avoid asserting row order against the previous sort's
    // response.
    async function assertOrder(before: string, after: string) {
      await expect(async () => {
        const isOrdered = await page.locator("table tbody tr").evaluateAll((rows, [a, b]) => {
          const indexOf = (needle: string) => rows.findIndex((row) => row.textContent?.includes(needle));
          const ia = indexOf(a);
          const ib = indexOf(b);
          return ia !== -1 && ib !== -1 && ia < ib;
        }, [before, after]);
        expect(isOrdered).toBe(true);
      }).toPass();
    }

    const [ascResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/change-requests?") && r.url().includes("sort=proposed_name") && r.url().includes("order=asc")),
      nameHeader.click(),
    ]);
    expect(ascResponse.ok()).toBe(true);
    await expect(nameHeaderCell).toHaveAttribute("aria-sort", "ascending");
    await assertOrder(firstName, secondName);

    const [descResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/change-requests?") && r.url().includes("sort=proposed_name") && r.url().includes("order=desc")),
      nameHeader.click(),
    ]);
    expect(descResponse.ok()).toBe(true);
    await expect(nameHeaderCell).toHaveAttribute("aria-sort", "descending");
    await assertOrder(secondName, firstName);
  });
});

/**
 * Default active-only status filter: a change request list is usually consulted for what still needs a decision, so
 * the page loads with "Active" selected (sending `active_only=true`) rather than every status. Creates its own
 * dynamically named fixture and withdraws it (a terminal status) rather than mutating shared seed data.
 */
test.describe("change requests default to an active-only status filter", () => {
  test("withdrawn CR is hidden by default and reappears under All statuses", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await openProject(page, PROJECT_NAMES.alpha1);
    await page.getByRole("link", { name: "Change requests", exact: true }).click();

    const name = `Active Filter Test CR ${Date.now()}`;
    await page.getByRole("button", { name: /New/ }).click();
    await page.getByRole("radio", { name: "New requirement" }).click();
    await page.getByLabel("Proposed name").fill(name);
    await page.getByLabel("Reason for change").fill("Active-only filter test fixture.");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await searchChangeRequests(page, name);
    const crLink = page.getByRole("link", { name, exact: true });
    await expect(crLink).toBeVisible();

    // Withdraw it (creator-only action) to reach a terminal, non-active
    // status without needing project-manager decide permission.
    await crLink.click();
    await page.getByRole("button", { name: "Withdraw" }).click();
    await expect(page.getByText("Withdrawn", { exact: true })).toBeVisible();

    // Back on the list: default view ("Active") hides it.
    await page.getByRole("link", { name: "Change requests", exact: true }).click();
    await searchChangeRequests(page, name);
    await expect(page.getByLabel("Status", { exact: true })).toHaveValue("active");
    await expect(page.getByRole("link", { name, exact: true })).toHaveCount(0);

    // Widening to "All statuses" reveals it again.
    await page.getByLabel("Status", { exact: true }).selectOption("");
    await expect(page.getByRole("link", { name, exact: true })).toBeVisible();

    // Narrowing to the specific "Withdrawn" status also finds it.
    await page.getByLabel("Status", { exact: true }).selectOption("withdrawn");
    await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
  });
});
