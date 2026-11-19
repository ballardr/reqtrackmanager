import { expect, test, type Page } from "@playwright/test";

import { PASSWORD, PERSONAS, loginAs } from "./helpers";

const apiBaseUrl = "http://localhost:8000";

/**
 * Job to be done: a notification opens what it is about, wherever it is opened from — the bell, the notification list
 * or an email link — and a followed email link survives signing in. `e2e-notified@example.com` holds one seeded
 * notification of each target kind (`seed_notification_samples.py`); opening one only marks it read, so the spec
 * repeats on the same data.
 */
test.describe("notification targets", () => {
  /** [seeded title, address the notification opens]. */
  const BELL_TARGETS: [string, RegExp][] = [
    ["New comment on a followed requirement", /\/projects\/[^/]+\/requirements\/[^/]+$/],
    ["A stage phase is overdue", /\/projects\/[^/]+\/stage-phases$/],
    ["Project members were changed", /\/projects\/[^/]+\/admin\/members$/],
    ["Organisation permission granted", /\/orgs\/[^/]+\/overview$/],
    ["Your password was changed", /\/preferences\/security$/],
  ];

  async function openFromBell(page: Page, title: string): Promise<void> {
    await page.goto("/projects");
    await page.getByRole("button", { name: "Notifications", exact: true }).click();
    await page.getByText(title, { exact: true }).click();
  }

  for (const [title, address] of BELL_TARGETS) {
    test(`the bell opens the page for "${title}"`, async ({ page }) => {
      await loginAs(page, PERSONAS.notified.email);
      await openFromBell(page, title);
      await expect(page).toHaveURL(address);
      await expect(page.locator("h1").first()).toBeVisible();
    });
  }

  test("a message with no page of its own opens in full", async ({ page }) => {
    await loginAs(page, PERSONAS.notified.email);
    await openFromBell(page, "Planned maintenance");
    await expect(page).toHaveURL(/\/notifications\/[^/]+$/);
    await expect(page.getByRole("heading", { name: "Planned maintenance" })).toBeVisible();
  });

  test("the notification list opens the same page as the bell", async ({ page }) => {
    await loginAs(page, PERSONAS.notified.email);
    await page.goto("/notifications");
    await page.getByText("A stage phase is overdue", { exact: true }).click();
    await expect(page).toHaveURL(/\/projects\/[^/]+\/stage-phases$/);
  });

  test("an email link opened while signed out signs in, then opens the page", async ({ page, request }) => {
    const login = await request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: PERSONAS.notified.email, password: PASSWORD },
    });
    expect(login.status()).toBe(200);
    const { access_token: token } = await login.json();
    const list = await request.get(`${apiBaseUrl}/api/v1/notifications`, { headers: { Authorization: `Bearer ${token}` } });
    const notifications: { id: string; title: string }[] = await list.json();
    const overdue = notifications.find((n) => n.title === "A stage phase is overdue");
    expect(overdue, "the seeded stage notification").toBeTruthy();

    await page.goto(`/notifications/${overdue!.id}`);
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel("Email").fill(PERSONAS.notified.email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/projects\/[^/]+\/stage-phases$/);
    await expect(page.getByRole("heading", { name: "Delivery status" })).toBeVisible();
  });

  test("Delivery status offers a settings link to a person who may change the stages", async ({ page }) => {
    await loginAs(page, PERSONAS.notified.email);
    await openFromBell(page, "A stage phase is overdue");
    await page.getByRole("link", { name: "Stage and phase settings" }).click();
    await expect(page).toHaveURL(/\/projects\/[^/]+\/admin\/stagesPhases$/);
  });

  test("another person's notification is reported as not found", async ({ page, request }) => {
    const login = await request.post(`${apiBaseUrl}/api/v1/auth/login`, {
      data: { email: PERSONAS.notified.email, password: PASSWORD },
    });
    const { access_token: token } = await login.json();
    const list = await request.get(`${apiBaseUrl}/api/v1/notifications`, { headers: { Authorization: `Bearer ${token}` } });
    const [first]: { id: string }[] = await list.json();

    await loginAs(page, PERSONAS.memberAlphaBeta.email);
    await page.goto(`/notifications/${first.id}`);
    await expect(page.getByRole("alert")).toHaveText("This notification was not found.");
  });
});
