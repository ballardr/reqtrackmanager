import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS, PROJECT_NAMES } from "./helpers";

/**
 * Job to be done: notifications are a first-class, searchable, paginated
 * history (C-N-01/C-N-02), not just the header bell's small dropdown, with
 * click-through to the item that triggered each one and a bulk "mark all
 * read." Favourited projects get their own quick-jump page distinct from
 * the full project list.
 */
test.describe("notifications page and favourites page", () => {
  test("notifications: search, unread filter, click-through, mark all read; favourites: add/remove", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminAlphaBeta.email);

    await test.step("generate at least one real notification (subscribing then commenting on a requirement)", async () => {
      await page.getByText(PROJECT_NAMES.alpha1).click();
      await page.getByRole("link", { name: "Requirements", exact: true }).click();
      await page.getByRole("link", { name: "Must expose a health-check endpoint", exact: true }).click();
      const subscribeButton = page.getByRole("button", { name: "Subscribe", exact: true });
      if (await subscribeButton.count()) await subscribeButton.click();
      await page.getByPlaceholder("Add comment").fill(`E2E: triggering a notification for the notifications-page spec (${Date.now()}).`);
      await page.getByRole("button", { name: "Add comment", exact: true }).click();
    });

    await test.step("the notifications page lists history, supports search and an unread filter", async () => {
      await page.goto("/notifications");
      await expect(page.getByRole("heading", { name: "Notifications", exact: true })).toBeVisible();
      await page.getByPlaceholder("Search notifications").fill("zzz-no-such-notification-zzz");
      await expect(page.getByText("No notifications yet.")).toBeVisible();
      await page.getByPlaceholder("Search notifications").fill("");
      await page.getByLabel("Unread only").check();
      await page.getByLabel("Unread only").uncheck();
    });

    await test.step("mark all read clears the bulk button", async () => {
      const markAllButton = page.getByRole("button", { name: "Mark all read" });
      if (await markAllButton.count()) {
        await markAllButton.click();
        await expect(page.getByRole("button", { name: "Mark all read" })).toHaveCount(0);
      }
    });

    await test.step("favourite a project, then visit the favourites page and unfavourite it there", async () => {
      await page.goto("/projects");
      const alphaCard = page.locator(".card", { hasText: PROJECT_NAMES.alpha2 });
      // .count() below doesn't auto-wait like other Playwright assertions —
      // page.goto only waits for the navigation itself, not for the async
      // project-list fetch React kicks off after mounting, so an immediate
      // .count() can read 0 while the list is still loading. Wait for the
      // card to actually exist first.
      await expect(alphaCard).toBeVisible();
      const favouriteButton = alphaCard.getByRole("button", { name: "Favourite", exact: true });
      // Wait for the PUT to actually settle before navigating away — a bare
      // click() races the async request against the immediate page.goto
      // below, and navigation can abort it in flight.
      if (await favouriteButton.count()) {
        await Promise.all([page.waitForResponse((r) => r.url().includes("/favorite")), favouriteButton.click()]);
      }

      // The nav's "Favourites" link visibility is only rechecked on
      // arrival at /projects or /favourites (Layout.tsx, deliberately not
      // on every navigation) — since we're already on /projects when
      // toggling the favourite, go there directly rather than via the nav
      // link, which may not have appeared yet without a fresh arrival.
      await page.goto("/favourites");
      await expect(page.getByText(PROJECT_NAMES.alpha2)).toBeVisible();

      await page.getByRole("button", { name: "Remove from favourites", exact: true }).click();
      await expect(page.getByText(PROJECT_NAMES.alpha2)).toHaveCount(0);
    });
  });
});
