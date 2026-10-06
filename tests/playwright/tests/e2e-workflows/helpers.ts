import crypto from "node:crypto";

import { type APIRequestContext, type Locator, type Page, expect, test } from "@playwright/test";

import { statBlockViolations } from "../../../../frontend/src/testing/statBlockGeometry";

/**
 * Personas seeded by backend/scripts/seed_e2e_dataset.py (see
 * docs/e2e-workflows.md for the full persona/workflow catalogue). Run the
 * seed script once against a fresh tests/container stack before running
 * this directory's specs.
 */
export const PASSWORD = "E2ePass123!";

export const PERSONAS = {
  serverAdmin: { email: "e2e-serveradmin@example.com", name: "E2E Server Admin Only" },
  orgAdminAlphaBeta: { email: "e2e-orgadmin-ab@example.com", name: "E2E OrgAdmin AlphaBeta" },
  orgAdminGamma: { email: "e2e-orgadmin-g@example.com", name: "E2E OrgAdmin Gamma" },
  stakeholderAlpha: { email: "e2e-stakeholder-a@example.com", name: "E2E Stakeholder AlphaOnly" },
  stakeholderAlpha2: { email: "e2e-stakeholder-a2@example.com", name: "E2E Stakeholder AlphaOnly Two" },
  memberAlphaBeta: { email: "e2e-member-ab@example.com", name: "E2E Member AlphaBeta" },
  orphan: { email: "e2e-orphan@example.com", name: "E2E Orphan Candidate" },
  projectMgrGamma: { email: "e2e-projectmgr-g@example.com", name: "E2E ProjectMgr Gamma Only" },
} as const;

export const ORG_NAMES = {
  alpha: "E2E Alpha Robotics",
  beta: "E2E Beta Software",
  gamma: "E2E Gamma Labs",
} as const;

export const PROJECT_NAMES = {
  alpha1: "Alpha-1 Robotic Arm Controller",
  alpha2: "Alpha-2 Sensor Fusion Platform",
  beta1: "Beta-1 Billing Engine",
  beta2: "Beta-2 Customer Portal",
  gamma1: "Gamma-1 Lab Instrument Suite",
  gamma2: "Gamma-2 Data Pipeline",
  /** Dedicated to the terminology-override spec (terminology-override.spec.ts)
   * — see TERMINOLOGY_PROJECT_NAME/TERMINOLOGY_OVERRIDE in
   * backend/scripts/seed_e2e_dataset.py. No other spec may depend on this
   * project's terminology staying at, or moving away from, that override. */
  delta1: "Delta-1 Terminology Demo",
  /** Fixed hierarchy fixture (see backend/scripts/seed_e2e_dataset.py):
   * gamma4 mirror-all-inherits from gamma3, and gamma3 also consumes
   * members from gamma4 (member-source, reverse). Dedicated solely to
   * project-hierarchy.spec.ts — no other spec may depend on this pair's
   * configuration. */
  gamma3: "Gamma-3 Hierarchy Parent",
  gamma4: "Gamma-4 Hierarchy Child",
  /** Platform review 2026-09, Phase 8 — dedicated to link-and-action-
   * change-request-locking.spec.ts (see LINK_LOCK_PROJECT_NAME in
   * backend/scripts/seed_e2e_dataset.py): `require_change_request_for_
   * approved_links` is on; otherwise given components/categories only —
   * that spec creates, links, and approves its own throwaway requirements
   * each run rather than consuming a fixed seeded fixture (which
   * unlink/remove/approve would make non-idempotent). No other spec may
   * depend on this project's setting. */
  epsilon1: "Epsilon-1 Link Lock Demo",
} as const;

/** Mirrors TERMINOLOGY_OVERRIDE in backend/scripts/seed_e2e_dataset.py — the
 * fixed override PROJECT_NAMES.delta1 is seeded with. */
export const TERMINOLOGY_OVERRIDE = { stage: "Phase", requirement: "Spec", changeRequest: "ECR" } as const;

/** Logs in through the real UI form as the given persona.
 *
 * Waits on the login response itself rather than only on "Sign out"
 * appearing: login is deliberately slow (bcrypt; the app's API client gives
 * it a 45s allowance), so under load it could outlast the 5s assertion and
 * read as a missing button. A rejected login (e.g. another spec deactivated
 * a shared persona) now fails naming the account and status instead. */
export async function loginAs(page: Page, email: string, password: string = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  const loginResponse = page.waitForResponse(
    (r) => r.url().endsWith("/api/v1/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign in" }).click();
  expect((await loginResponse).status(), `login as ${email}`).toBe(200);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

export async function logout(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(/\/login$/);
}

/** CollapsibleSection's expand/collapse choice persists server-side per
 * user (`ui_preferences`) across runs/specs sharing a persona — an
 * unconditional click can toggle an already-expanded section shut on a
 * re-run or from an earlier spec's leftover state, so only click when
 * actually collapsed. */
export async function ensureExpanded(page: Page, sectionTitle: string): Promise<void> {
  const toggle = page.getByRole("button", { name: `${sectionTitle} section` });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") {
    await toggle.click();
  }
}

/**
 * Opens one org group's `SidePanel` on Org Admin's Groups section
 * (`DirectoryTable`, Phase B, follow-up UX batch, 2026-08-31 — replaces the
 * pre-Phase-B always-expanded `CollapsibleSection` accordion this helper
 * used to open a card in instead). A `SidePanel` has no expand/collapse
 * state to race, so this isn't guarded the idempotent way `ensureExpanded`
 * is — clicking the row again while its own panel is already open is a
 * harmless no-op re-render, not a toggle-shut.
 *
 * Returns the panel's own `dialog` locator (its accessible name is
 * `"<group name> details"`), so callers scope every subsequent interaction
 * to it rather than the whole page.
 */
export async function openOrgGroupPanel(page: Page, groupName: string) {
  await page.getByRole("button", { name: new RegExp(`^${groupName}`) }).click();
  return page.getByRole("dialog", { name: `${groupName} details` });
}

/**
 * Opens one project group's `SidePanel` on `ProjectAdminPage`'s Groups
 * section — a `DirectoryTable` row (Phase B, follow-up UX batch,
 * 2026-08-31; before that, Phase 5's own `<button>`-row list, docs/
 * decisions.md). Uses `DirectoryTable`'s `onRowClick` (a real `<button>`),
 * not `rowHref` — found during Phase B verification, not assumed: at the
 * time, every standard project auto-seeded a default group literally named
 * "Members" (`DEFAULT_GROUPS`, `routers/projects.py` — removed in Phase C,
 * 2026-08-31, but the finding that motivated `onRowClick` stands
 * regardless), the exact same accessible name as this page's own
 * `ResourceMenu` "Members" nav link, so a `rowHref` `<Link>` row would
 * collide with it (two `role="link"` elements sharing one accessible name
 * on the same page — a real ambiguity, not just a Playwright artifact, and
 * one any project could still hit today with a manually-named custom
 * group). The existing `?openGroup=` deep link is unaffected
 * either way — it's handled by `ProjectAdminPage.tsx`'s own
 * `useSearchParams` effect, which `onRowClick`'s `setOpenGroupId` call
 * feeds into identically. A `SidePanel` has no expand/collapse state to
 * race the way a `CollapsibleSection` does, so this isn't guarded the same
 * idempotent way `ensureExpanded` is — clicking the row again while its own
 * panel is already open is a harmless no-op re-render, not a toggle-shut.
 *
 * Returns the panel's own `dialog` locator (its accessible name is
 * `"<group name> details"`), so callers scope every subsequent interaction
 * to it rather than the whole page — necessary once more than one group in
 * this run could plausibly match a page-wide selector for the same
 * add-member input/role text.
 *
 * Uses an exact-name match, not a `^groupName` prefix regex: PR7 of the
 * follow-up UX batch (docs/decisions.md) added a per-row role
 * `MultiSelectDropdown` to the Groups tab's own row (`ProjectAdminPage.tsx`),
 * whose trigger button's accessible name is `"<group name>'s roles"` — a
 * prefix match against the row-trigger button's exact `<group name>` text
 * also matched that second button, a genuine two-element strict-mode
 * violation found running the full suite together (not present when a
 * group had no role-picker rendered, e.g. an isolated spec run seeded
 * without this PR's own fixtures). The row-trigger button's own accessible
 * name is exactly `groupName` with no trailing text, so `exact: true`
 * disambiguates correctly without narrowing any real match.
 */
export async function openProjectGroupPanel(page: Page, groupName: string) {
  await page.getByRole("button", { name: groupName, exact: true }).click();
  return page.getByRole("dialog", { name: `${groupName} details` });
}

/**
 * Selects a group in any page built on the shared `ResourceMenu`
 * (`ResourceMenu.tsx`, 2026-08 UX audit "Org Admin resource-menu
 * restructure", later extended to Server Admin/Preferences/Project Admin
 * — see `docs/decisions.md`'s "Admin-tier ResourceMenu consistency"
 * entry). Each group is a real route segment (e.g.
 * `/orgs/:orgId/admin/:group?`), not client-only state — the link's own
 * `aria-current="page"` says whether it's already selected, so this is
 * idempotent the same way `ensureExpanded` is: clicking an already-active
 * group would be a harmless no-op navigation, but the guard keeps this a
 * true no-op instead of an extra history entry. A section within the
 * selected group is otherwise unreachable — unlike `CollapsibleSection`'s
 * own per-user collapse preference, group selection isn't persisted, so
 * this must run before every interaction with a section that isn't in the
 * page's default group.
 */
export async function selectResourceMenuGroup(page: Page, groupLabel: string): Promise<void> {
  const link = page.getByRole("link", { name: groupLabel, exact: true });
  // Below ResourceMenu's own mobile breakpoint (theme.css/useNarrowViewport,
  // 860px) the link list is replaced with a single <select> — same group
  // switch, a different control (platform-review-2026-09, "resource menus
  // wasting space on narrow windows"). Scoped to the specific <select> that
  // actually carries this group as an option, not just "any combobox on the
  // page" — the currently-selected group's own content pane can contain
  // unrelated <select>s.
  const dropdown = page.locator("select").filter({ has: page.getByRole("option", { name: groupLabel, exact: true }) });
  // Race for whichever of the two actually renders rather than a bare
  // `.count()` on the link alone — `.count()` doesn't auto-wait, so right
  // after a navigation (before React has mounted the menu) it can read 0
  // for the link even on a wide viewport where the link list is what's
  // about to render, wrongly falling through to the dropdown branch and
  // then hanging forever waiting for a <select> that was never coming.
  await expect(link.or(dropdown).first()).toBeAttached();
  if ((await link.count()) === 0) {
    await dropdown.selectOption({ label: groupLabel });
    await page.waitForLoadState("networkidle");
    return;
  }
  if ((await link.getAttribute("aria-current")) !== "page") {
    await link.click();
    // The group switch itself is a synchronous route-param change, but the
    // newly-selected group's own content typically fetches its data on
    // mount — a caller that immediately checks for group-specific content
    // right after this call (e.g. `.count()` on a conditional button,
    // which doesn't wait/retry the way `expect(...)` does) can otherwise
    // race the fetch and silently read "not present yet" as "not present
    // at all". Found via workflow-bypass-attempts.spec.ts: without this,
    // its "Start review"/"Approve stage" `.count()` checks right after
    // selecting the Structure group both intermittently read 0 before the
    // stages list had loaded, silently skipping the whole approval and
    // leaving the stage stuck in scoping.
    await page.waitForLoadState("networkidle");
  }
}

/** `selectResourceMenuGroup` for `OrgAdminPage` — kept as its own name
 * since most call sites predate the generic helper above. */
export async function selectOrgAdminGroup(page: Page, groupLabel: string): Promise<void> {
  await selectResourceMenuGroup(page, groupLabel);
}

/** Sets a module's (or, with `moduleName`, a sub-component's) org-level
 * availability on Org Admin's Modules group, which must already be open,
 * via its labelled `<select>` ("<name> availability"), and waits for the
 * confirming toast. Expands the module's collapsed sub-component list
 * first when setting a sub-component. */
export async function setOrgModuleAvailability(
  page: Page,
  name: string,
  availability: "off" | "opt_in" | "default_on",
  moduleName?: string,
): Promise<void> {
  if (moduleName) {
    const disclosure = page
      .locator(".module-settings-row", { has: page.getByText(moduleName, { exact: true }) })
      .getByRole("button", { name: /component/ });
    if ((await disclosure.getAttribute("aria-expanded")) !== "true") await disclosure.click();
  }
  const label = moduleName ? `${name} (${moduleName}) availability` : `${name} availability`;
  const select = page.getByRole("combobox", { name: label, exact: true });
  await select.selectOption(availability);
  await expect(select).toHaveValue(availability);
}

/** `selectResourceMenuGroup` for `ServerManagementPage`
 * (`/server/management/:group?`, converted from `Tabs` — see
 * `docs/decisions.md`). */
export async function selectServerManagementGroup(page: Page, groupLabel: string): Promise<void> {
  await selectResourceMenuGroup(page, groupLabel);
}

/** `selectResourceMenuGroup` for `PreferencesPage` (`/preferences/:group?`,
 * converted from `Tabs` — see `docs/decisions.md`). */
export async function selectPreferencesGroup(page: Page, groupLabel: string): Promise<void> {
  await selectResourceMenuGroup(page, groupLabel);
}

/** `selectResourceMenuGroup` for `OrgOverviewPage`
 * (`/orgs/:orgId/overview/:group?`, compliance-module-plan.md Phase 19) —
 * a module-contributed group only, e.g. Compliance's relocated-from-
 * `OrgAdminPage` "Compliance overview" (previously reached via
 * `selectOrgAdminGroup`). */
export async function selectOrgOverviewGroup(page: Page, groupLabel: string): Promise<void> {
  await selectResourceMenuGroup(page, groupLabel);
}

/** `selectResourceMenuGroup` for `ProjectAdminPage`
 * (`/projects/:projectId/admin/:group?`, converted from `Tabs` — see
 * `docs/decisions.md`). */
export async function selectProjectAdminGroup(page: Page, groupLabel: string): Promise<void> {
  await selectResourceMenuGroup(page, groupLabel);
}

/**
 * Opens a requirement's detail page by its stable `unique_code` (e.g.
 * "HW-FN-001") rather than its `name` — a requirement's name can be
 * changed by an approved change request (see
 * change-request-approval-separation.spec.ts, which does exactly this to
 * Alpha-1's HW-FN-001), so specs that need "the locked seed requirement"
 * specifically must not hard-code its original name. Matches either the
 * tile (`.card`) or list (`tr`) row layout, whichever RequirementsPage's
 * persisted per-user view-mode preference currently renders.
 *
 * Finds the code's own text node first, then walks up to its *nearest*
 * `tr`/`.card` ancestor, rather than a flat `page.locator(".card, tr", {
 * hasText: code })` — that shape has a real bug, not just a tile-view
 * quirk: list view's whole `<table>` is itself wrapped in one outer
 * `<div class="card">` (`RequirementsPage.tsx`'s `overflowX: "auto"`
 * wrapper), which also "has text" matching any code found in any row and
 * sits before every `<tr>` in document order — so `.first()` silently
 * resolved to that outer wrapper, not the specific row, the moment a
 * project had more than one requirement whose text happened to satisfy
 * the match (invisible with few requirements, since the outer wrapper's
 * lone matching link and the correct row's link were then the same
 * element; a real strict-mode violation once a project accumulates
 * enough requirements across a full suite run for the outer wrapper to
 * contain more than one link).
 */
export async function openRequirementByCode(page: Page, code: string): Promise<void> {
  // Search first: the list is paginated (30 per page) and the shared e2e
  // projects grow every run, so a row isn't guaranteed to be on page one —
  // same fix role-display-collapsing.spec.ts got for the groups table.
  await page.getByPlaceholder("Search by name or ID").fill(code);
  await page
    .getByText(code, { exact: true })
    .locator("xpath=ancestor::*[self::tr or contains(concat(' ', normalize-space(@class), ' '), ' card ')][1]")
    .getByRole("link")
    .click();
  // Waits for the detail page's own content to actually render before
  // returning, not just for the URL to change. `waitForURL` alone was
  // tried first and wasn't enough: the route's lazy chunk (or its own
  // requirement fetch, RequirementDetailPage.tsx's `if (!requirement)
  // return <Spinner />`) can still be in flight after the URL/history
  // update lands, and under full-suite CI load that window is wide enough
  // for a caller's very next assertion (e.g. the detail page's own "Locked
  // (approved)" badge) to catch the requirements *list* page's own
  // identically-worded row badge still mounted — a genuine two-element
  // strict-mode violation `expect().toBeVisible()` can't retry past, since
  // ambiguity isn't a "not ready yet" condition. The detail page's `<h1>`
  // always renders as `"<code> — <name>"` (RequirementDetailPage.tsx) while
  // the list page's own `<h1>` is just the (terminology-dependent) page
  // title with no em dash, so waiting for the dash is a reliable,
  // terminology-independent signal that the swap has actually happened.
  await page.waitForURL(/\/requirements\/[0-9a-f-]+(?:[/?#]|$)/);
  await expect(page.locator("h1")).toContainText("—");
}

/** Same idea as `ensureExpanded`, for PreferencesPage's "Two-factor
 * authentication" section specifically — its `title` is a JSX node (embeds
 * the "Enable 2FA" toggle itself), not a plain string, so
 * `CollapsibleSection` can't give its header a fixed aria-label the way
 * every other section gets one, and `ensureExpanded` can't target it by
 * name. Clicks the "Two-factor authentication" text (part of the same
 * clickable header, but not the toggle switch itself) rather than the
 * switch, so this never also fires the switch's own onChange. */
export async function ensureTwoFactorSectionExpanded(page: Page): Promise<void> {
  // "Two-factor authentication" is a bare text node next to the toggle
  // switch and a badge (no wrapping element of its own), so exact text
  // matching can't resolve it — substring match instead, which Playwright
  // resolves to the smallest containing element. The section's own
  // clickable wrapper is a real `<button>` when expanded but a `<div
  // role="button">` when collapsed, so match either.
  const label = page.getByText("Two-factor authentication").first();
  const wrapper = label.locator("xpath=ancestor::*[self::button or @role='button'][1]");
  if ((await wrapper.getAttribute("aria-expanded")) !== "true") {
    await label.click();
  }
}

function base32Decode(base32: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const clean = base32.replace(/=+$/, "").toUpperCase();
  let bits = "";
  for (const char of clean) {
    const val = alphabet.indexOf(char);
    if (val === -1) continue;
    bits += val.toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(parseInt(bits.slice(i, i + 8), 2));
  }
  return Buffer.from(bytes);
}

/**
 * Generates a standard RFC 6238 TOTP code (SHA1, 6 digits, 30s step) for a
 * base32 secret — matching this backend's `services/totp.py` (`pyotp`
 * defaults). Used to drive real 2FA enrollment/login through the UI
 * without a browser-side authenticator app.
 */
export function generateTotpCode(base32Secret: string, forTimeMs: number = Date.now()): string {
  const counter = Math.floor(forTimeMs / 1000 / 30);
  const counterBuffer = Buffer.alloc(8);
  counterBuffer.writeBigUInt64BE(BigInt(counter));
  const key = base32Decode(base32Secret);
  const hmac = crypto.createHmac("sha1", key).update(counterBuffer).digest();
  const offset = hmac[hmac.length - 1] & 0xf;
  const binCode =
    ((hmac[offset] & 0x7f) << 24) | ((hmac[offset + 1] & 0xff) << 16) | ((hmac[offset + 2] & 0xff) << 8) | (hmac[offset + 3] & 0xff);
  return String(binCode % 1_000_000).padStart(6, "0");
}

/**
 * Clicks a save control and waits for the mutating request it triggers to
 * finish, so a following `page.reload()` can't cancel it mid-flight (the
 * cause of intermittent "value didn't persist" failures). Matches the first
 * non-GET response whose URL contains `urlPart`.
 */
export async function clickAndAwaitSave(page: Page, control: Locator, urlPart: string): Promise<void> {
  await Promise.all([
    page.waitForResponse((r) => r.url().includes(urlPart) && r.request().method() !== "GET"),
    control.click(),
  ]);
}

/**
 * Opens a requirement from the project's requirements list by its name,
 * searching first: the list is paginated (30 per page), and shared e2e
 * projects accumulate throwaway requirements across runs, so a freshly
 * created row is not guaranteed to land on the first page (found
 * 2026-10-04 when Alpha-1 passed 30 active requirements and ~10 specs
 * started timing out). Must be called from the requirements list page.
 * Waits for the detail page's `<h1>` ("<code> — <name>") before returning.
 */
export async function openRequirementByName(page: Page, name: string): Promise<void> {
  await page.getByPlaceholder("Search by name or ID").fill(name);
  await page.getByText(name).click();
  await page.waitForURL(/\/requirements\/[0-9a-f-]+(?:[/?#]|$)/);
  await expect(page.locator("h1")).toContainText("—");
}

/**
 * Types `text` into the project list's search box and waits for that exact
 * search's response, so a following assertion (including an absence check)
 * reads the searched result set, not the previous one. The list pages at 30,
 * so checks for a named project should search rather than read page one.
 */
export async function searchProjects(page: Page, text: string): Promise<void> {
  const box = page.getByPlaceholder("Search projects");
  if ((await box.inputValue()) === text) return;
  await Promise.all([
    page.waitForResponse((r) => {
      if (!r.url().includes("/api/v1/projects?")) return false;
      return (new URL(r.url()).searchParams.get("search") ?? "") === text;
    }),
    box.fill(text),
  ]);
}

/**
 * Opens a project from the project list, searching first: the list is
 * paginated (30 per page) and disposable projects accumulate in the shared
 * e2e orgs across runs, so a seeded project isn't guaranteed to be on the
 * first page (found 2026-10-04 when Alpha passed 30 projects). Navigates to
 * `/projects` first if not already there. Takes the first matching link,
 * since a hierarchy parent's row can render its name more than once.
 */
export async function openProject(page: Page, name: string): Promise<void> {
  if (new URL(page.url()).pathname !== "/projects") await page.goto("/projects");
  await page.getByPlaceholder("Search projects").fill(name);
  // Exact: an org merge-import can add a same-named "<name> (imported)" copy.
  await page.getByRole("link", { name, exact: true }).first().click();
  await page.waitForURL(/\/projects\/[0-9a-f-]+/);
}

/**
 * Logs in through the API (not the page) and returns auth headers — for
 * `test.afterEach` cleanup, which Playwright still runs after a test times
 * out (with its own budget and live fixtures), unlike a `finally` inside the
 * test body, whose page is already closed by then. Cleanup that must not
 * leak shared state belongs in `afterEach` using the standalone `request`
 * fixture and these headers.
 */
export async function apiHeaders(
  request: APIRequestContext, email: string, password: string = PASSWORD,
): Promise<Record<string, string>> {
  const resp = await request.post("http://localhost:8000/api/v1/auth/login", { data: { email, password } });
  expect(resp.ok()).toBeTruthy();
  return { Authorization: `Bearer ${(await resp.json()).access_token}` };
}

type Cleanup = (request: APIRequestContext) => Promise<void>;
const pendingCleanups: Cleanup[] = [];

/**
 * Registers API-only cleanup for shared state the current test is about to
 * change; runs (most recent first) in the `afterEach` that
 * `installCleanupHook()` adds — which, unlike a `finally` in the test body,
 * still runs when the test times out. Register *before* making the change,
 * and make the cleanup idempotent (it may run when the change never
 * happened). Use `request` + `apiHeaders`, never `page`.
 */
export function onCleanup(cleanup: Cleanup): void {
  pendingCleanups.push(cleanup);
}

/** Adds the `afterEach` that drains `onCleanup` registrations; call once at
 * the top of a `test.describe` that uses `onCleanup`. A failing cleanup is
 * logged, not thrown, so it can't mask the test's own failure. */
export function installCleanupHook(): void {
  test.afterEach(async ({ request }) => {
    while (pendingCleanups.length) {
      const cleanup = pendingCleanups.pop()!;
      try {
        await cleanup(request);
      } catch (error) {
        console.warn("e2e cleanup failed:", error);
      }
    }
  });
}

/** The bootstrap server admin (`backend/scripts/seed_e2e_dataset.py`). */
export const SERVER_ADMIN_LOGIN = { email: "admin@example.com", password: "ChangeMe123!" } as const;

/**
 * Deletes a disposable organisation after the test (via `onCleanup`, so the
 * describe must call `installCleanupHook`; runs even on timeout). Specs that
 * create their own org call this right after creating it, so throwaway orgs
 * don't pile up across runs (281 had, by 2026-10-05).
 *
 * The org is resolved at cleanup time, as the server admin: by `id`, or by
 * a `nameContains` fragment unique to this run (e.g. the `Date.now()`
 * suffix) for orgs created through the UI, signup or an import, whose id
 * the test never sees. Its current name is read then, since deletion must
 * confirm it and a test may have renamed the org. A fragment matches every
 * org containing it, so it must be unique to the test.
 *
 * Args:
 *   target: `{ id }` or `{ nameContains }`.
 */
export function deleteOrgOnCleanup(target: { id: string } | { nameContains: string }): void {
  // A short fragment could match seeded orgs; those are never deleted.
  if ("nameContains" in target && target.nameContains.length < 10) {
    throw new Error(`deleteOrgOnCleanup: fragment "${target.nameContains}" is too short to be unique to one test.`);
  }
  const protectedNames = new Set<string>([...Object.values(ORG_NAMES), "Default Organization", "Solstice Robotics"]);
  onCleanup(async (request) => {
    const api = "http://localhost:8000/api/v1";
    const headers = await apiHeaders(request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
    const orgs: { id: string; name: string }[] = await (await request.get(`${api}/orgs`, { headers })).json();
    const matches = "id" in target
      ? orgs.filter((o) => o.id === target.id)
      : orgs.filter((o) => o.name.includes(target.nameContains));
    for (const org of matches.filter((o) => !protectedNames.has(o.name))) {
      const resp = await request.delete(`${api}/orgs/${org.id}`, { headers, data: { confirm_name: org.name } });
      if (!resp.ok()) console.warn(`deleteOrgOnCleanup: deleting "${org.name}" returned ${resp.status()}`);
    }
  });
}

/** A disposable project created via the API, with the seeded projects'
 * starting structure. */
export interface DisposableProject {
  projectId: string;
  organizationId: string;
  projectName: string;
  headers: Record<string, string>;
  /** Hardware (HW) and Software (SW). */
  components: { id: string; name: string; prefix: string }[];
  /** Functional (FN, under Hardware) and Performance (PERF, under Software). */
  categories: { id: string; name: string; prefix: string; component_id: string }[];
}

/**
 * Creates a uniquely-named project in `orgName` (default: `email`'s first
 * organisation), with the
 * Hardware/Software + Functional/Performance shape
 * `seed_e2e_dataset.py::seed_project_content` gives every seeded project,
 * and archives it via `onCleanup` (so the describe must call
 * `installCleanupHook`). For specs whose writes would otherwise accumulate
 * in, or reshape, a shared seeded project.
 *
 * Args:
 *   request: An API request context (`page.request` or the `request` fixture).
 *   email: The creating persona; becomes the project's manager.
 *   label: Readable part of the project name.
 *   orgName: The organisation to create it in, if not the first.
 */
export async function createDisposableProject(
  request: APIRequestContext, email: string, label: string, orgName?: string,
): Promise<DisposableProject> {
  const api = "http://localhost:8000/api/v1";
  const headers = await apiHeaders(request, email);
  const projectName = `${label} ${Date.now()}`;
  const orgs: { id: string; name: string }[] = await (await request.get(`${api}/orgs`, { headers })).json();
  const org = orgName ? orgs.find((o) => o.name === orgName)! : orgs[0];
  const projectResp = await request.post(`${api}/projects`, {
    headers, data: { organization_id: org.id, name: projectName, summary: "" },
  });
  expect(projectResp.ok()).toBeTruthy();
  const projectId: string = (await projectResp.json()).id;
  onCleanup(async (cleanupRequest) => {
    await cleanupRequest.post(`${api}/projects/${projectId}/archive`, { headers: await apiHeaders(cleanupRequest, email) });
  });
  const post = async (path: string, data: object) => {
    const resp = await request.post(`${api}/projects/${projectId}/${path}`, { headers, data });
    expect(resp.ok()).toBeTruthy();
    return resp.json();
  };
  const hw = await post("components", { name: "Hardware", prefix: "HW" });
  const sw = await post("components", { name: "Software", prefix: "SW" });
  const fn = await post("categories", { name: "Functional", prefix: "FN", component_id: hw.id });
  const perf = await post("categories", { name: "Performance", prefix: "PERF", component_id: sw.id });
  return { projectId, organizationId: org.id, projectName, headers, components: [hw, sw], categories: [fn, perf] };
}

/**
 * Searches the change-requests list (server-side, matching proposed name,
 * reason, and the target requirement's name/ID) so a change request is
 * found on any page of the paginated list. Must be on that list page.
 * Matched by the placeholder's fixed prefix — its tail uses the project's
 * terminology for "requirement".
 */
export async function searchChangeRequests(page: Page, text: string): Promise<void> {
  await page.getByPlaceholder(/^Search by name, reason or /).fill(text);
}


/** Stat-block widths checked by `expectTidyStatBlocks`: phone, tablet, laptop, desktop. */
export const STAT_BLOCK_WIDTHS = [375, 720, 1024, 1440] as const;

/**
 * Asserts every stat block on the page (flat/grouped `StatBar`, `.grid-metrics`
 * grids of `StatCard`/`MetricTile`) is tidy at phone, tablet, laptop and
 * desktop widths: no horizontal overflow, aligned equal-height columns, no
 * label swamping its number. It runs the same `statBlockViolations` the
 * Storybook stories run (`frontend/src/testing/statBlockGeometry.ts`), against
 * the real page and real data. Every spec that shows a stats block should call
 * it, so a stat layout cannot regress to ragged rows unnoticed.
 *
 * Restores the original viewport afterwards.
 */
export async function expectTidyStatBlocks(page: Page): Promise<void> {
  const original = page.viewportSize() ?? { width: 1280, height: 720 };
  try {
    for (const width of STAT_BLOCK_WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      // Polled, not read once: a resize re-renders responsive chrome (nav rail, resource menu) over a few frames,
      // and a mid-reflow reading is not the settled layout. A real defect stays wrong and still fails.
      await expect
        .poll(() => page.evaluate(statBlockViolations, undefined), { message: `stat blocks at ${width}px`, timeout: 5_000 })
        .toEqual([]);
    }
  } finally {
    await page.setViewportSize(original);
  }
}
