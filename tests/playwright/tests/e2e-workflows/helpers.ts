import crypto from "node:crypto";

import { type Page, expect } from "@playwright/test";

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
} as const;

/** Mirrors TERMINOLOGY_OVERRIDE in backend/scripts/seed_e2e_dataset.py — the
 * fixed override PROJECT_NAMES.delta1 is seeded with. */
export const TERMINOLOGY_OVERRIDE = { stage: "Phase", requirement: "Spec", changeRequest: "ECR" } as const;

/** Logs in through the real UI form as the given persona. */
export async function loginAs(page: Page, email: string, password: string = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
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
 * Same idea as `ensureExpanded`, for one org group's own card in Org
 * Admin's Groups section (2026-08 UX audit "Directories at scale") — each
 * group renders collapsed by default behind its own `CollapsibleSection`,
 * so its member list, "add member" input, and nesting picker are all
 * unreachable until expanded. Unlike `ensureExpanded`'s exact
 * `"<title> section"` match, each group's title combines its name with a
 * dynamic member count, so this matches by the group's name as a substring
 * instead. Also persists server-side per user across runs/specs sharing a
 * persona, same caveat as `ensureExpanded` — hence the same idempotent
 * "only click if collapsed" guard.
 *
 * Project-scoped groups (`ProjectAdminPage`'s own Groups section) moved off
 * this exact same accordion shape to a per-group `SidePanel` (Phase 5,
 * docs/decisions.md) — use `openProjectGroupPanel` below for those, not
 * this helper.
 */
export async function openGroupCard(page: Page, groupName: string): Promise<void> {
  const toggle = page.getByRole("button", { name: new RegExp(`^${groupName}`) });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") {
    await toggle.click();
  }
}

/**
 * Opens one project group's `SidePanel` on `ProjectAdminPage`'s Groups
 * section (Phase 5, docs/decisions.md) — replaces the pre-Phase-5
 * always-expanded `CollapsibleSection` accordion `openGroupCard` (above)
 * still serves for Org Admin's own group cards. A `SidePanel` has no
 * expand/collapse state to race the way a `CollapsibleSection` does, so
 * this isn't guarded the same idempotent way — clicking the row again while
 * its own panel is already open is a harmless no-op re-render, not a
 * toggle-shut.
 *
 * Returns the panel's own `dialog` locator (its accessible name is
 * `"<group name> details"`), so callers scope every subsequent interaction
 * to it rather than the whole page — necessary once more than one group in
 * this run could plausibly match a page-wide selector for the same
 * add-member input/role text.
 */
export async function openProjectGroupPanel(page: Page, groupName: string) {
  await page.getByRole("button", { name: new RegExp(`^${groupName}`) }).click();
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
  await page
    .getByText(code, { exact: true })
    .locator("xpath=ancestor::*[self::tr or contains(concat(' ', normalize-space(@class), ' '), ' card ')][1]")
    .getByRole("link")
    .click();
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
