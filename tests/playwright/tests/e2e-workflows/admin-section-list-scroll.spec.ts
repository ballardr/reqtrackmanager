import { expect, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: on an administration page with more sections than fit the window, the section list scrolls on its
 * own, and choosing a section near its end opens that section at its top instead of leaving the content scrolled
 * past its start.
 *
 * Covers: the list being a bounded, separately scrolling column that stays in view while the page scrolls, and a
 * choice of the last section while the page is scrolled down showing the content pane's top edge below the header.
 *
 * Also covers the first view: before the page is scrolled the list ends inside the window and the page itself does
 * not scroll, because the list's height follows where it starts (below the title), not where it would stop once stuck.
 *
 * Builds its own organisation and administrator, so it depends on no seeded state.
 */
const apiBaseUrl = "http://localhost:8000";

/** Creates a disposable organisation with one administrator (removed after the test) and returns that login. */
async function createAdminOrg(request: import("@playwright/test").APIRequestContext, suffix: string) {
  const adminEmail = `e2e-admin-scroll-${suffix}@example.com`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `Admin scroll ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Scroll Admin", password: PASSWORD, role: "org_admin" },
  });
  return { orgId: org.id as string, adminEmail };
}

for (const windowHeight of [800, 1100]) {
  test(`the section list fits a ${windowHeight}px window from the first view`, async ({ page, request }) => {
    const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
    const { orgId, adminEmail } = await createAdminOrg(request, suffix);
    await page.setViewportSize({ width: 1280, height: windowHeight });
    await loginAs(page, adminEmail);
    await page.goto(`/orgs/${orgId}/admin/overview`);

    const nav = page.locator("nav.resource-menu-nav");
    await expect(nav).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);

    await test.step("unscrolled, the list ends inside the window", async () => {
      await expect
        .poll(() => nav.evaluate((el) => el.getBoundingClientRect().bottom <= window.innerHeight))
        .toBe(true);
    });

    await test.step("its last entry is reached by the list's own scrollbar, with the page unscrolled", async () => {
      await nav.evaluate((el) => {
        el.scrollTop = el.scrollHeight;
      });
      await expect(nav.getByRole("link").last()).toBeInViewport();
      expect(await page.evaluate(() => window.scrollY)).toBe(0);
    });

    await test.step("after the page scrolls the list is still inside the window", async () => {
      await page.evaluate(() => {
        const spacer = document.createElement("div");
        spacer.style.height = "2000px";
        document.querySelector(".resource-menu-content")?.appendChild(spacer);
        window.scrollTo(0, document.documentElement.scrollHeight);
      });
      await expect
        .poll(() => nav.evaluate((el) => el.getBoundingClientRect().bottom <= window.innerHeight))
        .toBe(true);
    });
  });
}

test("the section list scrolls on its own and a chosen section opens at its top", async ({ page, request }) => {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const adminEmail = `e2e-admin-scroll-${suffix}@example.com`;
  const serverToken = (
    await (await request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: "admin@example.com", password: "ChangeMe123!" } })).json()
  ).access_token;
  const serverHeaders = { Authorization: `Bearer ${serverToken}` };
  const org = await (
    await request.post(`${apiBaseUrl}/api/v1/orgs`, { headers: serverHeaders, data: { name: `Admin scroll ${suffix}` } })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders,
    data: { email: adminEmail, display_name: "E2E Scroll Admin", password: PASSWORD, role: "org_admin" },
  });

  // Wide enough for the list column (not the narrow select), too short for every section to fit.
  await page.setViewportSize({ width: 1280, height: 420 });
  await loginAs(page, adminEmail);
  await page.goto(`/orgs/${org.id}/admin/overview`);

  const nav = page.locator("nav.resource-menu-nav");
  await expect(nav).toBeVisible();

  await test.step("the list is a bounded column that scrolls separately", async () => {
    const box = await nav.evaluate((el) => ({
      position: getComputedStyle(el).position,
      scrollable: el.scrollHeight > el.clientHeight,
      height: el.getBoundingClientRect().height,
    }));
    expect(box.position).toBe("sticky");
    expect(box.scrollable).toBe(true);
    expect(box.height).toBeLessThanOrEqual(420);
  });

  await test.step("the list stays in view while the page scrolls", async () => {
    // A sticky column only moves within its container, so give the content pane the height a long section has.
    await page.evaluate(() => {
      const spacer = document.createElement("div");
      spacer.style.height = "2000px";
      document.querySelector(".resource-menu-content")?.appendChild(spacer);
      window.scrollTo(0, 400);
    });
    const top = await nav.evaluate((el) => el.getBoundingClientRect().top);
    const headerBottom = await page.locator(".app-header").evaluate((el) => el.getBoundingClientRect().bottom);
    expect(top).toBeGreaterThanOrEqual(headerBottom - 1);
    expect(top).toBeLessThan(420);
  });

  await test.step("choosing the last section opens its content at the top", async () => {
    await nav.evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });
    const links = nav.getByRole("link");
    const last = links.last();
    const name = (await last.textContent()) ?? "";
    await last.click();
    await expect(last).toHaveAttribute("aria-current", "page");
    expect(name.length).toBeGreaterThan(0);
    await expect
      .poll(async () => {
        const containerTop = await page.locator(".resource-menu").evaluate((el) => el.getBoundingClientRect().top);
        const headerBottom = await page.locator(".app-header").evaluate((el) => el.getBoundingClientRect().bottom);
        return containerTop >= headerBottom - 1;
      })
      .toBe(true);
    await expect(page.locator(".resource-menu-content > *").first()).toBeInViewport();
  });
});
