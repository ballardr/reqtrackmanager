import crypto from "node:crypto";

import { type APIRequestContext, type Locator, type Page, expect, test } from "@playwright/test";

import { statBlockViolations } from "../../../../frontend/src/testing/statBlockGeometry";

/**
 * Personas seeded by backend/scripts/seed_e2e_dataset.py (docs/e2e-workflows.md has the catalogue). Run the seed
 * script once against a fresh tests/container stack before this directory's specs.
 */
export const PASSWORD = "E2ePass123!";

export const PERSONAS = {
  serverAdmin: { email: "e2e-serveradmin@example.com", name: "E2E Server Admin Only" },
  orgAdminAlphaBeta: { email: "e2e-orgadmin-ab@example.com", name: "E2E OrgAdmin AlphaBeta" },
  orgAdminGamma: { email: "e2e-orgadmin-g@example.com", name: "E2E OrgAdmin Gamma" },
  stakeholderAlpha: { email: "e2e-stakeholder-a@example.com", name: "E2E Stakeholder AlphaOnly" },
  stakeholderAlpha2: { email: "e2e-stakeholder-a2@example.com", name: "E2E Stakeholder AlphaOnly Two" },
  memberAlphaBeta: { email: "e2e-member-ab@example.com", name: "E2E Member AlphaBeta" },
  /** Holds one seeded notification of every target kind (`seed_notification_samples.py`); nothing else uses it. */
  notified: { email: "e2e-notified@example.com", name: "E2E Notified Member" },
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
  /** Dedicated to terminology-override.spec.ts (TERMINOLOGY_PROJECT_NAME/TERMINOLOGY_OVERRIDE in
   * backend/scripts/seed_e2e_dataset.py). No other spec may depend on this project's terminology. */
  delta1: "Delta-1 Terminology Demo",
  /** Fixed hierarchy fixture (backend/scripts/seed_e2e_dataset.py): gamma4 mirror-all-inherits from gamma3, and
   * gamma3 also consumes members from gamma4 (member-source, reverse). Dedicated to project-hierarchy.spec.ts. */
  gamma3: "Gamma-3 Hierarchy Parent",
  gamma4: "Gamma-4 Hierarchy Child",
  /** Dedicated to link-and-action-change-request-locking.spec.ts (LINK_LOCK_PROJECT_NAME in
   * backend/scripts/seed_e2e_dataset.py): `require_change_request_for_approved_links` is on and it has only
   * components and categories, because that spec creates, links and approves its own requirements each run. No other
   * spec may depend on this project's setting. */
  epsilon1: "Epsilon-1 Link Lock Demo",
  /** Holds one submitted change request proposing three links, the last
   * unmergeable (see PROPOSED_LINKS_PROJECT_NAME in backend/scripts/seed_e2e_dataset.py). Read-only: no spec may
   * approve or reject that request; change-request-proposed-links.spec.ts builds its own organisation for that. */
  zeta1: "Zeta-1 Proposed Links Demo",
  /** Fixed System Architecture fixture (see ARCHITECTURE_PROJECT_NAME in backend/scripts/seed_e2e_dataset.py): a service, a
   * board, a connection, a diagram and a state machine. Read-only: seeded-architecture.spec.ts only browses it. */
  eta1: "Eta-1 Flight System Architecture",
} as const;

/** Mirrors TERMINOLOGY_OVERRIDE in backend/scripts/seed_e2e_dataset.py, the override PROJECT_NAMES.delta1 is seeded with. */
export const TERMINOLOGY_OVERRIDE = { stage: "Phase", requirement: "Spec", changeRequest: "ECR" } as const;

const LOGIN_ATTEMPTS = 6;

/** The pause before retrying a sign-in answered 429: the server's `Retry-After` (seconds), at least one second. */
function retryAfterMs(retryAfter: string | null): number {
  const seconds = Number(retryAfter);
  return (Number.isFinite(seconds) && seconds > 0 ? Math.min(seconds, 10) : 1) * 1000 + 200;
}

/**
 * Signs in through the API and returns the token response. The suite signs in as the same few accounts from several
 * workers at once, and the server answers 429 to an attempt that overlaps another on the same account for longer than
 * its short lock wait, so a 429 is retried after the time it states; any other failure is raised naming the account.
 *
 * @param request The API request context to use.
 * @param email The account to sign in as.
 * @param password The account's password.
 * @returns The parsed login response (`access_token`).
 */
export async function apiLogin(
  request: APIRequestContext, email: string, password: string = PASSWORD,
): Promise<{ access_token: string }> {
  let status = 0;
  for (let attempt = 0; attempt < LOGIN_ATTEMPTS; attempt++) {
    const resp = await request.post("http://localhost:8000/api/v1/auth/login", { data: { email, password } });
    status = resp.status();
    if (resp.ok()) return resp.json();
    if (status !== 429) break;
    await new Promise((resolve) => setTimeout(resolve, retryAfterMs(resp.headers()["retry-after"] ?? null)));
  }
  throw new Error(`API login as ${email} failed with status ${status}`);
}

/**
 * Makes every Links panel in this page's session show the relationship labels ("Has participant",
 * "Supersedes"), which are off by default (the viewer's remembered "Show relationships" choice).
 * Call before navigating; for a spec that asserts how a link is phrased.
 */
export async function showLinkRelationships(page: Page): Promise<void> {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("reqtrack.links.showRelationships", "1");
    } catch {
      // Storage unavailable: the labels stay hidden and the spec will say so.
    }
  });
}

/**
 * Logs in through the real UI form as the given persona. Waits on the login response itself, not only on "Sign out":
 * login is deliberately slow (bcrypt; the API client allows 45s), so it can outlast the 5s assertion. A rejected login
 * (for example a deactivated shared persona) fails naming the account and status.
 */
export async function loginAs(page: Page, email: string, password: string = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  let status = 0;
  for (let attempt = 0; attempt < LOGIN_ATTEMPTS; attempt++) {
    const loginResponse = page.waitForResponse(
      (r) => r.url().endsWith("/api/v1/auth/login") && r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Sign in" }).click();
    const response = await loginResponse;
    status = response.status();
    if (status !== 429) break;
    // Another attempt on this account was still in progress: wait the stated time and submit again.
    await page.waitForTimeout(retryAfterMs(await response.headerValue("retry-after")));
  }
  expect(status, `login as ${email}`).toBe(200);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await forgetRememberedSorts(page);
}

/**
 * A list remembers the sort a person last chose (`ui_preferences` key `list_sort_<list>`), and a persona is shared by
 * many specs, so signing in removes every remembered sort (reloading only when one was removed). Best effort: a failure
 * leaves them as they were.
 */
async function forgetRememberedSorts(page: Page): Promise<void> {
  try {
    const removed = await page.evaluate(async () => {
      const token = localStorage.getItem("reqtrack_token");
      if (!token) return false;
      const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
      const me = await (await fetch("http://localhost:8000/api/v1/auth/me", { headers })).json();
      const patch: Record<string, null> = {};
      for (const key of Object.keys(me.ui_preferences ?? {})) if (key.startsWith("list_sort_")) patch[key] = null;
      if (Object.keys(patch).length === 0) return false;
      const resp = await fetch("http://localhost:8000/api/v1/auth/me/preferences", {
        method: "PATCH", headers, body: JSON.stringify({ ui_preferences: patch }),
      });
      return resp.ok;
    });
    if (removed) await page.reload();
  } catch {
    // The page navigated or the call failed: nothing to forget, or nothing that can be.
  }
}

export async function logout(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(/\/login$/);
}

/** CollapsibleSection's choice persists per user (`ui_preferences`) across runs and specs sharing a persona, so an
 * unconditional click could close an open section; click only when collapsed. */
export async function ensureExpanded(page: Page, sectionTitle: string): Promise<void> {
  const toggle = page.getByRole("button", { name: `${sectionTitle} section` });
  // A section that is the only one on its page has no toggle (`collapsible={false}`): it is always open.
  await expect(toggle.or(page.getByRole("heading", { name: sectionTitle, exact: true })).first()).toBeVisible();
  if ((await toggle.count()) === 0) return;
  if ((await toggle.getAttribute("aria-expanded")) !== "true") {
    await toggle.click();
  }
}

/**
 * Opens one row of a collapsible list (`DisclosureRow`: a workflow, a stage's schedule) when it is closed, and returns
 * once it is open. The row's toggle is named by the row title followed by its summary, so it is matched by prefix;
 * a row's own action buttons ("Edit workflow X") do not begin with the title.
 */
export async function ensureRowExpanded(page: Page, rowTitle: string): Promise<void> {
  const escaped = rowTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const toggle = page.getByRole("button", { name: new RegExp(`^${escaped}`) }).and(page.locator("[aria-expanded]"));
  if ((await toggle.getAttribute("aria-expanded")) !== "true") {
    await toggle.click();
  }
}

/**
 * Opens one org group's `SidePanel` on Org Admin's Groups section (a `DirectoryTable` row). A panel has no
 * expand/collapse state, so clicking the row of an open panel is a harmless re-render.
 *
 * @returns The panel's `dialog` locator (accessible name `"<group name> details"`), to scope later interactions.
 */
export async function openOrgGroupPanel(page: Page, groupName: string) {
  await page.getByRole("button", { name: new RegExp(`^${groupName}`) }).click();
  return page.getByRole("dialog", { name: `${groupName} details` });
}

/**
 * Opens one project group's `SidePanel` on `ProjectAdminPage`'s Groups section (a `DirectoryTable` row, through
 * `onRowClick`, a real `<button>`). It is not a `rowHref` link: a link named like the group would share its accessible
 * name with the page's own `ResourceMenu` "Members" link when a group is named "Members". The `?openGroup=` deep
 * link reaches the same state. Clicking the row of an open panel is a harmless re-render.
 *
 * The match is exact, not a `^groupName` prefix: the row also holds a role dropdown whose trigger is named
 * `"<group name>'s roles"`, which a prefix match would also select (a strict-mode violation).
 *
 * @returns The panel's `dialog` locator (accessible name `"<group name> details"`), to scope later interactions.
 */
export async function openProjectGroupPanel(page: Page, groupName: string) {
  await page.getByRole("button", { name: groupName, exact: true }).click();
  return page.getByRole("dialog", { name: `${groupName} details` });
}

/**
 * Selects a group in any page built on the shared `ResourceMenu`. A group is a route segment (for example
 * `/orgs/:orgId/admin/:group?`), and the link's `aria-current="page"` shows whether it is selected, so the call adds no
 * history entry when it already is. The selection is not persisted, so call it before every interaction with a section
 * outside the page's default group. `parentLabel` names the expandable group a sub-page sits under (opened first).
 */
export async function selectResourceMenuGroup(page: Page, groupLabel: string, parentLabel?: string): Promise<void> {
  // A sub-page sits under an expandable group header: open that group first when the menu shows it closed. Below the
  // mobile breakpoint the menu is a <select> with no header button, so there is nothing to open.
  if (parentLabel) {
    const header = page.getByRole("button", { name: parentLabel, exact: true });
    const narrowMenu = page.locator("select").filter({ has: page.getByRole("option", { name: groupLabel, exact: true }) });
    await expect(header.or(narrowMenu).first()).toBeAttached();
    if ((await header.count()) > 0 && (await header.getAttribute("aria-expanded")) !== "true") await header.click();
  }
  // Scoped to the resource menu: the application navigation rail also has links named like a group (Projects).
  const link = page.locator("nav.resource-menu-nav").getByRole("link", { name: groupLabel, exact: true });
  // Below ResourceMenu's mobile breakpoint (theme.css/useNarrowViewport, 860px) the link list is a single <select>.
  // Scoped to the <select> that carries this group as an option, since the content pane can hold unrelated <select>s.
  const dropdown = page.locator("select").filter({ has: page.getByRole("option", { name: groupLabel, exact: true }) });
  // Wait for whichever renders: `.count()` does not auto-wait, so right after a navigation it can read 0 for the link on
  // a wide viewport and wrongly take the dropdown branch.
  await expect(link.or(dropdown).first()).toBeAttached();
  if ((await link.count()) === 0) {
    await dropdown.selectOption({ label: groupLabel });
    await page.waitForLoadState("networkidle");
    return;
  }
  if ((await link.getAttribute("aria-current")) !== "page") {
    await link.click();
    // The new group's content fetches its data on mount; without waiting, a caller's immediate `.count()` on a
    // conditional button (which does not retry like `expect(...)`) can read "not present yet" as "not present".
    await page.waitForLoadState("networkidle");
  }
}

/** `selectResourceMenuGroup` for `OrgAdminPage`. */
export async function selectOrgAdminGroup(page: Page, groupLabel: string, parentLabel?: string): Promise<void> {
  await selectResourceMenuGroup(page, groupLabel, parentLabel);
}

/** Sets a module's (or, with `moduleName`, a sub-component's) org-level availability through its labelled `<select>`
 * ("<name> availability") on Org Admin's Modules group, which must already be open, and expects the new value to show.
 * Expands the module's sub-component list first for a sub-component. */
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

/** `selectResourceMenuGroup` for `ServerManagementPage` (`/server/management/:group?`). */
export async function selectServerManagementGroup(page: Page, groupLabel: string): Promise<void> {
  await selectResourceMenuGroup(page, groupLabel);
}

/** `selectResourceMenuGroup` for `PreferencesPage` (`/preferences/:group?`). */
export async function selectPreferencesGroup(page: Page, groupLabel: string): Promise<void> {
  await selectResourceMenuGroup(page, groupLabel);
}

/** `selectResourceMenuGroup` for `OrgResourcesPage`
 * (`/orgs/:orgId/resources/:group?/:section?`) — a module-contributed section such as Personas or Compliance by
 * standard. */
export async function selectOrgResourcesGroup(page: Page, groupLabel: string): Promise<void> {
  await selectResourceMenuGroup(page, groupLabel);
}

/** `selectResourceMenuGroup` for `ProjectAdminPage` (`/projects/:projectId/admin/:group?`). */
export async function selectProjectAdminGroup(page: Page, groupLabel: string, parentLabel?: string): Promise<void> {
  await selectResourceMenuGroup(page, groupLabel, parentLabel);
}

/**
 * Narrows Report setup's folder list to a report by searching for it (a search opens every folder holding a match, so
 * the report is visible whichever folder it is filed in) and returns the list.
 */
export async function searchReportSetup(page: Page, text: string) {
  await page.getByRole("textbox", { name: "Search reports" }).fill(text);
  const grid = page.getByRole("treegrid", { name: "Reports, packs and tables" });
  await expect(grid).toBeVisible();
  return grid;
}

/** Opens a layout or pack from Report setup by its name (the designer or the pack editor). */
export async function openSetupReport(page: Page, name: string): Promise<void> {
  const grid = await searchReportSetup(page, name);
  await grid.getByRole("button", { name: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`) }).click();
}

/**
 * Matches a record code as the UI may show it: bare (`DEC-001`) or with the project code in
 * front (`ACME-DEC-001`). The display rule depends on the organisation's switch and the
 * person's preference, so a spec must not depend on which form it gets. Use with
 * `getByText(recordCodeText("DEC-001"))`.
 */
export function recordCodeText(code: string): RegExp {
  return new RegExp(`^(?:[A-Z0-9]+-)?${code.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`);
}

/**
 * Opens a requirement's detail page by its stable `unique_code` (for example "HW-FN-001"), not its `name`, which an
 * approved change request can change. Matches the tile (`.card`) or list (`tr`) layout, whichever the persisted
 * view-mode preference renders.
 *
 * Finds the code's text node, then its nearest `tr`/`.card` ancestor, not a flat `locator(".card, tr", { hasText })`:
 * list view wraps the whole table in an outer `div.card` that also matches and precedes every row, so `.first()`
 * would resolve to the wrapper and break strict mode once a project holds several matching requirements.
 */
export async function openRequirementByCode(page: Page, code: string): Promise<void> {
  // Search first: the list is paginated (30 per page) and the shared e2e projects grow every run.
  await page.getByPlaceholder("Search by name or ID").fill(code);
  await page
    .getByText(recordCodeText(code))
    .locator("xpath=ancestor::*[self::tr or contains(concat(' ', normalize-space(@class), ' '), ' card ')][1]")
    .getByRole("link")
    .click();
  // Wait for the detail content, not only the URL: the lazy route chunk or the requirement fetch can still be in
  // flight, and a caller's next assertion (for example the "Locked (approved)" badge) could match the still-mounted
  // list row badge, a strict-mode violation that `toBeVisible()` cannot retry past. The `.record-header` h1 is never
  // rendered by the list page, so it is a terminology-independent signal that the page has swapped.
  await page.waitForURL(/\/requirements\/[0-9a-f-]+(?:[/?#]|$)/);
  await expect(page.locator(".record-header h1")).toBeVisible();
}

/** `ensureExpanded` for PreferencesPage's "Two-factor authentication" section, whose `title` is a JSX node (it embeds
 * the "Enable 2FA" toggle), so its header has no fixed aria-label. Clicks the header text, not the switch, so the
 * switch's onChange never fires. */
export async function ensureTwoFactorSectionExpanded(page: Page): Promise<void> {
  // The label is a bare text node beside the switch and a badge, so exact matching cannot resolve it; a substring match
  // resolves to the smallest containing element. The clickable wrapper is a `<button>` when expanded and a
  // `<div role="button">` when collapsed, so match either.
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
 * Generates an RFC 6238 TOTP code (SHA1, 6 digits, 30s step) for a base32 secret, matching the backend's
 * `services/totp.py` (`pyotp` defaults), to drive 2FA enrolment and login without an authenticator app.
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

const lastTotpStep = new Map<string, number>();

/**
 * A code the server will accept for a secret that has already been used in this run. The server refuses a code for a
 * step at or before the last one it accepted (no replay) and tolerates one step either side of now, so successive
 * calls take the steps one before now, now and one after, and wait for the clock when those are used up.
 *
 * @param base32Secret The authenticator secret shown when 2FA was enrolled.
 * @returns A six-digit code for the earliest step the server can still accept.
 */
export async function nextTotpCode(base32Secret: string): Promise<string> {
  for (;;) {
    const current = Math.floor(Date.now() / 30_000);
    const step = Math.max(current - 1, (lastTotpStep.get(base32Secret) ?? Number.NEGATIVE_INFINITY) + 1);
    if (step <= current + 1) {
      lastTotpStep.set(base32Secret, step);
      return generateTotpCode(base32Secret, step * 30_000);
    }
    await new Promise((resolve) => setTimeout(resolve, (current + 1) * 30_000 - Date.now() + 100));
  }
}

/**
 * Clicks a save control and waits for the mutating request it triggers (the first non-GET response whose URL contains
 * `urlPart`), so a following `page.reload()` cannot cancel it mid-flight.
 */
export async function clickAndAwaitSave(page: Page, control: Locator, urlPart: string): Promise<void> {
  await Promise.all([
    page.waitForResponse((r) => r.url().includes(urlPart) && r.request().method() !== "GET"),
    control.click(),
  ]);
}

/**
 * Adds a component on the Structure page of project administration (the page must be open) through the Add component
 * panel. A prefix left out is taken from the suggestion the form fills in from the name.
 *
 * @param page The page, on the Structure group.
 * @param name The component's name.
 * @param prefix The prefix to type; omit to keep the suggested one.
 * @returns The prefix that was saved.
 */
export async function addStructureComponent(page: Page, name: string, prefix?: string): Promise<string> {
  await page.getByRole("button", { name: "Add component" }).click();
  const panel = page.getByRole("dialog", { name: "Add component" });
  await panel.getByRole("textbox", { name: "Name" }).fill(name);
  const prefixBox = panel.getByRole("textbox", { name: "Prefix" });
  if (prefix === undefined) await expect(prefixBox).not.toHaveValue("");
  else await prefixBox.fill(prefix);
  const saved = await prefixBox.inputValue();
  await clickAndAwaitSave(page, panel.getByRole("button", { name: "Save" }), "/components");
  await expect(panel).toBeHidden();
  return saved;
}

/**
 * Adds a category under a component on the Structure page through the component row's menu and the Add category panel.
 *
 * @param page The page, on the Structure group.
 * @param component The component's name.
 * @param name The category's name.
 * @param prefix The prefix to type; omit to keep the suggested one.
 * @returns The prefix that was saved.
 */
export async function addStructureCategory(page: Page, component: string, name: string, prefix?: string): Promise<string> {
  await page.getByRole("button", { name: `Actions for ${component}`, exact: true }).click();
  await page.getByRole("menuitem", { name: `Add category to ${component}`, exact: true }).click();
  const panel = page.getByRole("dialog", { name: `Add category to ${component}`, exact: true });
  await panel.getByRole("textbox", { name: "Name" }).fill(name);
  const prefixBox = panel.getByRole("textbox", { name: "Prefix" });
  if (prefix === undefined) await expect(prefixBox).not.toHaveValue("");
  else await prefixBox.fill(prefix);
  const saved = await prefixBox.inputValue();
  await clickAndAwaitSave(page, panel.getByRole("button", { name: "Save" }), "/categories");
  await expect(panel).toBeHidden();
  return saved;
}

/** The row of a component or category in the Structure tree, by its name. */
export function structureRow(page: Page, name: string): Locator {
  return page.getByRole("treegrid", { name: "Components and categories" }).getByRole("row").filter({ hasText: name });
}

/**
 * Opens a requirement from the requirements list (the page must be open) by its name, searching first: the list is
 * paginated (30 per page) and shared e2e projects accumulate requirements across runs, so a row may not be on the
 * first page. Waits for the detail page's record header.
 */
export async function openRequirementByName(page: Page, name: string): Promise<void> {
  await page.getByPlaceholder("Search by name or ID").fill(name);
  await page.getByText(name).click();
  await page.waitForURL(/\/requirements\/[0-9a-f-]+(?:[/?#]|$)/);
  await expect(page.locator(".record-header h1")).toBeVisible();
}

/**
 * Types `text` into the project list's search box and waits for that search's response, so a following assertion
 * (including an absence check) reads the searched result set. The list pages at 30, so search for a named project.
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
 * Opens a project from the project list, searching first: the list is paginated (30 per page) and disposable projects
 * accumulate in the shared e2e orgs. Navigates to `/projects` when not there, and takes the first matching link,
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
 * Logs in through the API (not the page) and returns auth headers, for `test.afterEach` cleanup: Playwright still runs
 * it after a timeout, unlike a `finally` in the test body, whose page is already closed. Cleanup of shared state
 * belongs in `afterEach` with the standalone `request` fixture and these headers.
 */
export async function apiHeaders(
  request: APIRequestContext, email: string, password: string = PASSWORD,
): Promise<Record<string, string>> {
  return { Authorization: `Bearer ${(await apiLogin(request, email, password)).access_token}` };
}

/**
 * Moves a stage to the named phase of its own workflow (`POST .../transition`) and returns the response, so a
 * caller can assert a refusal. The phase is found by name in the stage's workflow, whatever the ids are.
 */
export async function moveStageToPhase(
  request: APIRequestContext, headers: Record<string, string>, projectId: string, stageId: string, phaseName: string,
  cascadeToRequirements = false, lookupHeaders: Record<string, string> = headers,
) {
  // The stage and workflow are looked up as `lookupHeaders` (default: the caller), so a refusal can be asserted for a
  // caller with no access to the project at all.
  const base = `http://localhost:8000/api/v1/projects/${projectId}`;
  const stages: { id: string; workflow_id: string }[] = await (await request.get(`${base}/stages`, { headers: lookupHeaders })).json();
  const stage = stages.find((s) => s.id === stageId)!;
  const workflows: { id: string; phases: { id: string; name: string }[] }[] = await (
    await request.get(`${base}/stage-workflows`, { headers: lookupHeaders })
  ).json();
  const phase = workflows.find((w) => w.id === stage.workflow_id)!.phases.find((p) => p.name === phaseName)!;
  return request.post(`${base}/stages/${stageId}/transition`, {
    headers, data: { phase_id: phase.id, cascade_to_requirements: cascadeToRequirements },
  });
}

type Cleanup = (request: APIRequestContext) => Promise<void>;
const pendingCleanups: Cleanup[] = [];

/**
 * Registers API-only cleanup for shared state the test is about to change; it runs (most recent first) in the
 * `afterEach` that `installCleanupHook()` adds, even after a timeout. Register before making the change and make the
 * cleanup idempotent (it may run when the change never happened). Use `request` + `apiHeaders`, never `page`.
 */
export function onCleanup(cleanup: Cleanup): void {
  pendingCleanups.push(cleanup);
}

/** Adds the `afterEach` that drains `onCleanup` registrations; call once at the top of a `test.describe` that uses
 * `onCleanup`. A failing cleanup is logged, not thrown, so it cannot mask the test's own failure. */
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
 * Deletes a disposable organisation after the test (via `onCleanup`, so the describe must call `installCleanupHook`;
 * runs even on timeout). Specs that create their own org call this right after creating it, so throwaway orgs do not
 * accumulate across runs.
 *
 * The org is resolved at cleanup time as the server admin: by `id`, or by a `nameContains` fragment unique to this run
 * (for example the `Date.now()` suffix) for orgs whose id the test never sees. Its current name is read then, since
 * deletion must confirm it and a test may have renamed the org. A fragment matches every org containing it.
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

/** A disposable project created via the API, with the seeded projects' starting structure. */
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
 * Creates a uniquely-named project in `orgName` (default: `email`'s first organisation) with the Hardware/Software +
 * Functional/Performance shape `seed_e2e_dataset.py::seed_project_content` gives every seeded project, and archives it
 * via `onCleanup` (so the describe must call `installCleanupHook`). For specs whose writes would otherwise accumulate
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
 * Searches the change-requests list (server-side, matching proposed name, reason and the target requirement's
 * name/ID) so a change request is found on any page. The list page must be open. The placeholder is matched by its
 * fixed prefix, since its tail uses the project's terminology for "requirement".
 */
export async function searchChangeRequests(page: Page, text: string): Promise<void> {
  await page.getByPlaceholder(/^Search by name, reason or /).fill(text);
}


/** Stat-block widths checked by `expectTidyStatBlocks`: phone, tablet, laptop, desktop. */
export const STAT_BLOCK_WIDTHS = [375, 720, 1024, 1440] as const;

/**
 * Asserts every stat block on the page (flat/grouped `StatBar`, `.grid-metrics` grids of `StatCard`/`MetricTile`) is
 * tidy at phone, tablet, laptop and desktop widths: no horizontal overflow, aligned equal-height columns, no label
 * swamping its number. It runs the `statBlockViolations` of the Storybook stories
 * (`frontend/src/testing/statBlockGeometry.ts`) against the real page. Every spec that shows a stats block calls it.
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

/**
 * Opens a record's object-action menu in its header ("{recordLabel} actions") and picks `item`
 * (Archive, Restore, Delete permanently, Subscribe...). Workflow transitions (Activate, Retire,
 * Approve) are not in the menu; click those directly.
 *
 * Args:
 *   page: The page showing the record detail.
 *   recordLabel: The record's singular label as the page names it ("Persona", "Stakeholder Need").
 *   item: Exact menu item label.
 */
export async function chooseRecordAction(page: Page, recordLabel: string, item: string): Promise<void> {
  await page.getByRole("button", { name: `${recordLabel} actions` }).click();
  await page.getByRole("menu", { name: `${recordLabel} actions` }).getByRole("menuitem", { name: item, exact: true }).click();
}

/**
 * Opens a record's one (+) menu (tags, components, external references) and chooses a row.
 *
 * Args:
 *   page: The page showing the record detail.
 *   row: Exact row name: "Add tag", "Add component or category" or "Add external reference".
 *   scope: Where the (+) is; the record header by default (a page can also show one in a side panel).
 */
export async function chooseRecordAddition(
  page: Page, row: string, scope: Locator = page.locator("header.record-header"),
): Promise<void> {
  await scope.getByRole("button", { name: "Add tag, component or reference" }).click();
  await page.getByRole("menu", { name: "Add tag, component or reference" }).getByRole("menuitem", { name: row, exact: true }).click();
}

/**
 * Approves the requirement on screen through the Approve button and its confirm dialog.
 *
 * Args:
 *   page: A requirement detail page the signed-in project manager can approve on.
 *   comment: Optional approval comment typed into the dialog.
 */
export async function approveRequirementFromDetail(page: Page, comment?: string): Promise<void> {
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Approve this requirement?" });
  if (comment) await dialog.getByLabel("Approval comment").fill(comment);
  await dialog.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(dialog).toHaveCount(0);
}

/**
 * Item labels in a record's object-action menu, or `[]` when the page draws no menu (the
 * user has no object actions there). Closes the menu again.
 */
export async function recordActionNames(page: Page, recordLabel: string): Promise<string[]> {
  const trigger = page.getByRole("button", { name: `${recordLabel} actions` });
  if ((await trigger.count()) === 0) return [];
  await trigger.click();
  const names = (await page.getByRole("menu", { name: `${recordLabel} actions` }).getByRole("menuitem").allTextContents())
    .map((t) => t.trim());
  await page.keyboard.press("Escape");
  return names;
}

/**
 * Picks the option whose label contains `text`. A record's option label leads with its record
 * code (`PP-001 Slow reports`), which a spec cannot know, so it matches on the title alone.
 */
export async function selectOptionContaining(select: Locator, text: string): Promise<void> {
  const label = await select.locator("option", { hasText: text }).first().innerText();
  await select.selectOption({ label });
}

/**
 * Saves an editor that keeps versions (the report layout designer, the report pack editor): presses Save new version,
 * which opens a popover asking for an optional note, then saves from it.
 *
 * @param note A note on the change to type first; omit it to save without one.
 */
export async function saveNewVersion(page: Page, note?: string): Promise<void> {
  // A long layout also has a Save at the foot; the first is the pinned one at the top.
  await page.getByRole("button", { name: "Save new version" }).first().click();
  const popover = page.getByRole("dialog", { name: "Save new version" });
  if (note !== undefined) await popover.getByRole("textbox", { name: "Note on this change" }).fill(note);
  await popover.getByRole("button", { name: "Save", exact: true }).click();
}

/**
 * Opens the report designer's Text view. A layout opens on Blocks, so a spec that edits the layout as text (or uses the
 * Fields and Widgets tabs, which belong to it) switches first; switching to the open view does nothing.
 */
export async function openDesignerTextView(page: Page): Promise<void> {
  await page.getByRole("tab", { name: "Text", exact: true }).click();
}

/**
 * The designer's right-hand panel, which holds the preview: run it with `Run preview`, read the result in the frame
 * titled "Report preview". Use after {@link openDesignerPreview}.
 */
export function designerPreviewPanel(page: Page): Locator {
  return page.getByRole("complementary", { name: "Designer tools" });
}

/**
 * Brings the Preview tab of the designer's right-hand panel forward (works from either view). Selecting a block or closing
 * a popover can bring the Block tab back just after the click, so the click is retried until Preview holds.
 */
export async function openDesignerPreview(page: Page): Promise<void> {
  const tab = designerPreviewPanel(page).getByRole("tab", { name: "Preview", exact: true });
  await expect(async () => {
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true", { timeout: 1500 });
  }).toPass();
}

/** Brings the Block tab of the panel back in the Blocks view (the Text view has no such tab), leaving the editor as it was before the preview. */
export async function closeDesignerPreview(page: Page): Promise<void> {
  const block = designerPreviewPanel(page).getByRole("tab", { name: "Block", exact: true });
  if (await block.count() > 0) await block.click();
}

/**
 * A disposable organisation with an organisation admin, a project and one saved document layout (a heading and a text
 * block), for a spec that needs a layout to open in the designer. The organisation is deleted on cleanup.
 *
 * @returns The admin's email and auth headers, the project and the layout (both as the API returns them).
 */
export async function createDocumentLayoutWorld(request: APIRequestContext, label: string) {
  const api = "http://localhost:8000/api/v1";
  const login = async (email: string, password: string) => ({
    Authorization: `Bearer ${(await apiLogin(request, email, password)).access_token}`,
  });
  const suffix = `${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
  const adminEmail = `e2e-${label}-${suffix}@example.com`;
  const serverHeaders = await login(SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  const org = await (await request.post(`${api}/orgs`, { headers: serverHeaders, data: { name: `E2E ${label} ${suffix}` } })).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${api}/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: adminEmail, display_name: `E2E ${label} Admin`, password: PASSWORD, role: "org_admin" },
  });
  const headers = await login(adminEmail, PASSWORD);
  const project = await (await request.post(`${api}/projects`, { headers, data: { organization_id: org.id, name: `${label} project ${suffix}`, summary: "" } })).json();
  const tree = {
    schema_version: 1, family: "document",
    nodes: [{ type: "heading", text: "A report", level: 1 }, { type: "text", text: "Some body text." }],
  };
  const layout = await (await request.post(`${api}/projects/${project.id}/report-layouts`, {
    headers, data: { name: `E2E ${label} ${suffix}`, description: "", family: "document", tree },
  })).json();
  return { adminEmail, headers, project, layout };
}

/**
 * Leave a form dialog without saving. A dialog has no Cancel: the header's Close button is the only way out, and
 * with unsaved changes it asks first, so this answers "Discard changes" when the prompt appears.
 *
 * @param dialog The dialog to close.
 * @param options.unsaved True when the test changed something, so the discard prompt is expected (and asserted).
 */
export async function closeDialogWithoutSaving(dialog: Locator, options: { unsaved: boolean }): Promise<void> {
  const page = dialog.page();
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  if (options.unsaved) {
    const prompt = page.getByRole("dialog", { name: "Discard unsaved changes?" });
    await expect(prompt).toBeVisible();
    await prompt.getByRole("button", { name: "Discard changes" }).click();
  }
  await expect(dialog).toHaveCount(0);
}

/**
 * Adds an item to a definition list (action types, link types, project statuses, a vocabulary, scoring levels,
 * ports): presses the list's Add button, fills the dialog's fields by caption and presses Add. The list draws no
 * empty fields, so every spec that creates one goes through here (docs/ux-style-guide.md, "Pattern: creation
 * controls on demand").
 *
 * @param page The page.
 * @param addLabel The Add button's name, which is also the dialog's (a string is matched exactly).
 * @param values Field caption (as in the dialog, without the `*`) to the value to type.
 * @param scope Where the Add button is looked for (default: the whole page), for a page with several lists.
 */
export async function addDefinition(
  page: Page, addLabel: string | RegExp, values: Record<string, string>, scope: Page | Locator = page,
): Promise<void> {
  const exact = typeof addLabel === "string";
  await scope.getByRole("button", { name: addLabel, exact }).click();
  const dialog = page.getByRole("dialog", { name: addLabel, exact });
  for (const [caption, value] of Object.entries(values)) await dialog.getByLabel(caption, { exact: true }).fill(value);
  await dialog.getByRole("button", { name: "Add", exact: true }).click();
  await expect(dialog).toHaveCount(0);
}


/**
 * Hovers the row of a disabled choice (the label around a checkbox) and expects the shared tooltip to give its reason.
 * A disabled control gets no pointer events, so the label, not the input, is hovered.
 *
 * @param page The page.
 * @param checkbox The checkbox whose row explains why it cannot be changed.
 * @param reason The tooltip text, or a pattern it must match.
 */
export async function expectReasonTooltip(page: Page, checkbox: Locator, reason: string | RegExp): Promise<void> {
  await checkbox.locator("xpath=ancestor::label[1]").hover();
  await expect(page.getByRole("tooltip")).toHaveText(reason);
  await page.mouse.move(0, 0);
}
