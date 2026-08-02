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
  memberAlphaBeta: { email: "e2e-member-ab@example.com", name: "E2E Member AlphaBeta" },
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
