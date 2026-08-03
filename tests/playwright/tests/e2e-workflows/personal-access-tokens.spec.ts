import { expect, test } from "@playwright/test";

import { PERSONAS, loginAs } from "./helpers";

/**
 * End-to-end proof that a Personal Access Token created through the real
 * UI is a genuinely working, independently revocable bearer credential —
 * not just correctly rendered. The deep RBAC-scoping/expiry logic (org
 * scope restriction, dynamic expiry, bulk/per-token org- and server-admin
 * revocation) is already exhaustively covered by
 * backend/tests/test_personal_access_tokens.py; this spec's job is the
 * thing only a real browser+API round trip can prove: the token the UI
 * hands the user actually authenticates, and revoking it through the UI
 * actually kills it, immediately, for real.
 */

const apiBaseUrl = "http://localhost:8000";

test("a Personal Access Token created via Preferences authenticates a real API call, and revoking it kills that access immediately", async ({ page }) => {
  await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

  await page.goto("/preferences");
  await page.getByPlaceholder('e.g. "MCP server"').fill("Playwright E2E token");
  await page.getByRole("checkbox", { name: /Organisations this token can access/ }).first().click();
  await page.getByRole("button", { name: "Create token" }).click();

  await expect(page.getByText("Token created")).toBeVisible();
  const token = await page.locator("code").first().textContent();
  expect(token).toBeTruthy();
  expect(token!.startsWith("rtm_pat_")).toBe(true);

  // The token the UI just displayed is a real, working bearer credential.
  const meResponse = await page.request.get(`${apiBaseUrl}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(meResponse.ok()).toBe(true);
  const me = await meResponse.json();
  expect(me.email).toBe(PERSONAS.orgAdminAlphaBeta.email);

  // Revoking it through the UI kills that same credential for real, not
  // just in the UI's own displayed state.
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Revoke", exact: true }).first().click();
  await expect(page.getByText("Playwright E2E token")).not.toBeVisible({ timeout: 10000 });

  const afterRevoke = await page.request.get(`${apiBaseUrl}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(afterRevoke.status()).toBe(401);
});
