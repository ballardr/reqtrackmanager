import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: the requirements list can be narrowed by search
 * (name/ID, U-E-01), status/target-version/category filters, and
 * has-comments/only-watched checkboxes; the tile/list view choice persists
 * across a reload (synced server-side, not just localStorage).
 *
 * badge-filters.spec.ts already covers the status-badge click-to-filter
 * interaction specifically — this spec covers the FilterPanel's remaining
 * controls, which aren't covered anywhere else.
 *
 * RequirementsPage's fetch effect has no request-cancellation guard, so
 * firing a new filtered fetch while a previous one is still in flight can
 * let the older response resolve later and overwrite the newer one —
 * `settled()` waits for the known-unfiltered baseline (both HW-FN-001 and
 * a requirement NOT matching the previous filter are visible) before the
 * next filter change, so each change starts from a confirmed-quiescent list.
 */
test.describe("requirements list filters and view-mode persistence", () => {
  test("search, status/category filters, has-comments/watched checkboxes, and view-mode persistence", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.alpha1).click();
    await page.getByRole("link", { name: "Requirements", exact: true }).click();

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
      await page.getByLabel("Status").selectOption("approved");
      await expect(page.getByText("HW-FN-001")).toBeVisible();
      await expect(page.getByText("Must expose a health-check endpoint")).toHaveCount(0);
      await page.getByLabel("Status").selectOption("");
      await settled();
    });

    await test.step("category filter narrows the list", async () => {
      const categorySelect = page.getByLabel("Category");
      const options = await categorySelect.locator("option").allTextContents();
      const firstRealCategory = options.find((o) => o.trim() && o !== "All");
      if (firstRealCategory) {
        await categorySelect.selectOption({ label: firstRealCategory });
        await expect(page.getByText("No requirements to show.")).toHaveCount(0);
        await categorySelect.selectOption("");
        await settled();
      }
    });

    await test.step("has-comments-only and only-watched checkboxes toggle without erroring", async () => {
      await page.getByLabel("Has comments").check();
      await page.getByLabel("Has comments").uncheck();
      await page.getByLabel("Only watched").check();
      await page.getByLabel("Only watched").uncheck();
      await settled();
    });

    await test.step("switching to list view persists across a reload", async () => {
      // Wait for the PATCH to actually settle before reloading — a bare
      // click() races the async save (AuthContext.tsx's setUiPreference is
      // fire-and-forget) against the immediate reload below, which can
      // observe the pre-save state if it wins the race — same fix as
      // preferences-and-theme.spec.ts's "pronouns save and persist" step.
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/auth/me/preferences") && r.request().method() === "PATCH"),
        page.getByRole("button", { name: "List view" }).click(),
      ]);
      await expect(page.getByRole("button", { name: "List view" })).toHaveAttribute("aria-pressed", "true");
      await page.reload();
      await expect(page.getByRole("button", { name: "List view" })).toHaveAttribute("aria-pressed", "true");
    });

    // Column-header sorting (2026-08 UX audit roadmap, "Column-header
    // sorting on data tables") — this list is backend-paginated, so a
    // header click refetches with `sort`/`order` query params. Asserts
    // general sortedness of the ID column's displayed text rather than
    // specific rows, since which requirements exist/how many can shift as
    // the suite evolves; ID (`unique_code`) has no null-fallback-display
    // quirk the way Name (`proposed_name`-equivalent on the CR side) does,
    // so comparing displayed text directly against its own sorted copy is
    // a faithful check here.
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

      // `aria-sort` flips synchronously on click, before the refetch this
      // header click triggers has actually landed — `toPass()` retries the
      // sortedness check rather than reading the table once right after
      // the attribute changes, which can race a still-in-flight response.
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
 * Change requests list sorting (2026-08 UX audit roadmap, "Column-header
 * sorting on data tables") — separate `describe` from the requirements one
 * above since it needs its own fixtures: `ChangeRequest.proposed_name` is
 * nullable, and the list falls back to the linked requirement's own name
 * for display (`crTitle()` in ChangeRequestsPage.tsx) — sorting the raw
 * column can't see that fallback (documented on the backend endpoint
 * itself), so comparing the *displayed* text against a plain alphabetic
 * sort of seed data would be unreliable. Creating two change requests with
 * guaranteed, distinct, non-null proposed names sidesteps that entirely.
 */
test.describe("change requests list sorting", () => {
  test("sort by name ascending and descending via the column header", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);
    await page.getByText(PROJECT_NAMES.alpha1).click();
    await page.getByRole("link", { name: "Change requests", exact: true }).click();

    const suffix = Date.now();
    const firstName = `AAA Sort Test CR ${suffix}`;
    const secondName = `ZZZ Sort Test CR ${suffix}`;

    async function createChangeRequest(name: string) {
      await page.getByRole("button", { name: /New/ }).click();
      await page.getByRole("radio", { name: "New requirement" }).click();
      await page.getByPlaceholder("Proposed name").fill(name);
      await page.getByPlaceholder("Reason for change").fill("Sort test fixture.");
      // `exact: true` — a bare "Create" substring-matches the "Created"
      // sortable column header too (`SortableHeader`'s button text).
      await page.getByRole("button", { name: "Create", exact: true }).click();
      await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
    }

    await createChangeRequest(firstName);
    await createChangeRequest(secondName);

    await page.getByRole("button", { name: "List view" }).click();
    const nameHeader = page.getByRole("button", { name: "Name" });
    const nameHeaderCell = page.locator("th", { has: nameHeader });

    // The two fixture rows' relative order is the only thing asserted —
    // other, unrelated change requests may also be present in this shared
    // project, and their proposed names aren't controlled by this test.
    // `aria-sort` flips synchronously on click, before the refetch this
    // header click triggers has actually landed — waiting on the network
    // response itself (rather than just the attribute) avoids asserting
    // row order against data that's still the *previous* sort's response.
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
