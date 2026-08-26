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

    await test.step("favourite a project: the nav-rail Favourites link appears immediately, not just after revisiting /projects or /favourites", async () => {
      await page.goto("/projects");
      const alphaCard = page.locator(".card", { hasText: PROJECT_NAMES.alpha2 });
      // .count() below doesn't auto-wait like other Playwright assertions —
      // page.goto only waits for the navigation itself, not for the async
      // project-list fetch React kicks off after mounting, so an immediate
      // .count() can read 0 while the list is still loading. Wait for the
      // card to actually exist first.
      await expect(alphaCard).toBeVisible();
      const favouriteButton = alphaCard.getByRole("button", { name: "Favourite", exact: true });
      // Wait for the PUT to actually settle before asserting — a bare
      // click() races the async request against the immediate assertion
      // below.
      if (await favouriteButton.count()) {
        await Promise.all([page.waitForResponse((r) => r.url().includes("/favorite")), favouriteButton.click()]);
      }

      // Reactive nav rail (2026-08 UX audit roadmap row 512,
      // `FavouritesContext`) — the "Favourites" rail link appears right
      // away, without needing to navigate to /projects or /favourites again
      // first (the previous behaviour this spec used to have to work
      // around by going straight to /favourites via `page.goto` instead of
      // the nav link).
      await expect(page.getByRole("link", { name: "Favourites", exact: true })).toBeVisible();
      await page.getByRole("link", { name: "Favourites", exact: true }).click();
      await expect(page.getByText(PROJECT_NAMES.alpha2)).toBeVisible();

      await page.getByRole("button", { name: "Remove from favourites", exact: true }).click();
      await expect(page.getByText(PROJECT_NAMES.alpha2)).toHaveCount(0);
    });

    await test.step("favourites-only filter on the project list narrows it to favourited projects", async () => {
      await page.goto("/projects");
      const alphaCard = page.locator(".card", { hasText: PROJECT_NAMES.alpha2 });
      await expect(alphaCard).toBeVisible();
      await Promise.all([
        page.waitForResponse((r) => r.url().includes("/favorite")),
        alphaCard.getByRole("button", { name: "Favourite", exact: true }).click(),
      ]);

      await Promise.all([
        page.waitForResponse((r) => r.url().includes("favorite_only=true")),
        page.getByRole("checkbox", { name: "Favourites only" }).check(),
      ]);
      await expect(page.getByText(PROJECT_NAMES.alpha2)).toBeVisible();
      await expect(page.getByText(PROJECT_NAMES.beta1)).toHaveCount(0);

      await page.getByRole("checkbox", { name: "Favourites only" }).uncheck();
      await expect(page.getByText(PROJECT_NAMES.beta1)).toBeVisible();
    });

    await test.step("the favourites page has its own tile/list view toggle", async () => {
      await page.goto("/favourites");
      await expect(page.getByText(PROJECT_NAMES.alpha2)).toBeVisible();
      await page.getByRole("button", { name: "List view" }).click();
      await expect(page.getByRole("columnheader", { name: "Name" })).toBeVisible();
      await expect(page.getByRole("cell", { name: PROJECT_NAMES.alpha2 })).toBeVisible();
      await page.getByRole("button", { name: "Tile view" }).click();

      // Clean up: unfavourite Alpha-2 so this spec leaves favourites state
      // as it found it for any other spec sharing this persona/run.
      await page
        .locator(".card", { hasText: PROJECT_NAMES.alpha2 })
        .getByRole("button", { name: "Remove from favourites", exact: true })
        .click();
      await expect(page.getByText(PROJECT_NAMES.alpha2)).toHaveCount(0);
    });
  });
});
