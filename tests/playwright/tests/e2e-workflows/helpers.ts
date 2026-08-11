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
} as const;

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
 * Opens a requirement's detail page by its stable `unique_code` (e.g.
 * "HW-FN-001") rather than its `name` — a requirement's name can be
 * changed by an approved change request (see
 * change-request-approval-separation.spec.ts, which does exactly this to
 * Alpha-1's HW-FN-001), so specs that need "the locked seed requirement"
 * specifically must not hard-code its original name. Matches either the
 * tile (`.card`) or list (`tr`) row layout, whichever RequirementsPage's
 * persisted per-user view-mode preference currently renders.
 */
export async function openRequirementByCode(page: Page, code: string): Promise<void> {
  await page.locator(".card, tr", { hasText: code }).first().getByRole("link").click();
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
