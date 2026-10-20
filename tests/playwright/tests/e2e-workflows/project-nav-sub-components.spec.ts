import { expect, type Page, test } from "@playwright/test";

import { deleteOrgOnCleanup, installCleanupHook, loginAs, PASSWORD, selectProjectAdminGroup } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";

const navLink = (page: Page, name: string) => page.getByRole("navigation").getByRole("link", { name, exact: true });

/** Names of the nav rail's Project-section links, top to bottom (the Global section starts at "Projects"). */
async function navLinkNames(page: Page): Promise<string[]> {
  const all = await page
    .getByRole("navigation")
    .getByRole("link")
    .evaluateAll((links) => links.map((link) => link.getAttribute("aria-label") ?? ""));
  return all.slice(0, all.indexOf("Projects"));
}

/**
 * Job to be done: the project nav rail lists only what the project can actually open. Turning a
 * module sub-component off in Project Admin removes its entry at once (no reload) and turning it
 * back on restores it; History and Project admin close the Project section; and the rail's
 * scrollbar never runs under the collapse toggle.
 *
 * Uses Context & Strategy (five sub-components, one nav entry each) in a disposable org, created
 * via the API per the repo's test-idempotency rule.
 */
async function setupProject(page: Page) {
  const suffix = Date.now();
  const adminEmail = `e2e-navsub-admin-${suffix}@example.com`;
  const serverAdminToken = (
    await (
      await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, {
        data: { email: "admin@example.com", password: "ChangeMe123!" },
      })
    ).json()
  ).access_token;
  const serverAdminHeaders = { Authorization: `Bearer ${serverAdminToken}` };
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: serverAdminHeaders, data: { name: `E2E NavSub Org ${suffix}` },
    })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverAdminHeaders,
    data: { email: adminEmail, display_name: "E2E NavSub Admin", password: PASSWORD, role: "org_admin" },
  });
  const adminHeaders = {
    Authorization: `Bearer ${(
      await (
        await page.request.post(`${apiBaseUrl}/api/v1/auth/login`, { data: { email: adminEmail, password: PASSWORD } })
      ).json()
    ).access_token}`,
  };
  await page.request.put(`${apiBaseUrl}/api/v1/orgs/${org.id}/modules/context_strategy`, {
    headers: adminHeaders, data: { enabled: true, default_project_enabled: true },
  });
  const project = await (
    await page.request.post(`${apiBaseUrl}/api/v1/projects`, {
      headers: adminHeaders, data: { organization_id: org.id, name: `E2E NavSub Project ${suffix}`, summary: "" },
    })
  ).json();
  await loginAs(page, adminEmail, PASSWORD);
  return { project };
}

test.describe("project nav: sub-components, order and scrolling", () => {
  test("a disabled sub-component's entry leaves the rail without a reload and returns when re-enabled", async ({ page }) => {
    const { project } = await setupProject(page);
    await page.goto(`/projects/${project.id}/admin`);
    await selectProjectAdminGroup(page, "Modules");
    await expect(navLink(page, "Pain Point")).toBeVisible();

    const moduleRow = page.locator(".module-settings-row", { has: page.getByText("Context & Strategy", { exact: true }) });
    await moduleRow.getByRole("button", { name: /components? ·/ }).click();
    const painPoints = page.getByRole("switch", { name: "Enable Pain Points (Context & Strategy) for this project" });

    await painPoints.click();
    await expect(painPoints).toHaveAttribute("aria-checked", "false");
    await expect(navLink(page, "Pain Point")).toHaveCount(0);
    await expect(navLink(page, "Strategy")).toBeVisible();

    await painPoints.click();
    await expect(painPoints).toHaveAttribute("aria-checked", "true");
    await expect(navLink(page, "Pain Point")).toBeVisible();
  });

  test("module entries come before Project history and Project admin, which close the Project section", async ({ page }) => {
    const { project } = await setupProject(page);
    await page.goto(`/projects/${project.id}`);
    await expect(navLink(page, "Open Question")).toBeVisible();
    const names = await navLinkNames(page);
    expect(names.slice(-2)).toEqual(["Project history", "Project admin"]);
    expect(names.indexOf("Open Question")).toBeLessThan(names.indexOf("Project history"));
    expect(names.indexOf("Requirements due for review")).toBeLessThan(names.indexOf("Strategy"));
  });

  test("the rail list scrolls on its own and keeps clear of the collapse toggle, expanded and collapsed", async ({ page }) => {
    const { project } = await setupProject(page);
    await page.setViewportSize({ width: 1280, height: 420 });
    await page.goto(`/projects/${project.id}`);
    await expect(navLink(page, "Open Question")).toBeVisible();

    for (const state of ["expanded", "collapsed"]) {
      if (state === "collapsed") await page.getByRole("button", { name: "Collapse navigation" }).click();
      const geometry = await page.evaluate(() => {
        const scroll = document.querySelector(".nav-rail-scroll") as HTMLElement;
        const rail = document.querySelector(".nav-rail") as HTMLElement;
        const toggle = document.querySelector(".nav-rail-toggle") as HTMLElement;
        return {
          overflows: scroll.scrollHeight > scroll.clientHeight,
          railScrolls: getComputedStyle(rail).overflowY !== "visible" && rail.scrollHeight > rail.clientHeight,
          scrollTop: scroll.getBoundingClientRect().top,
          railTop: rail.getBoundingClientRect().top,
          scrollRight: scroll.getBoundingClientRect().right,
          toggleLeft: toggle.getBoundingClientRect().left,
        };
      });
      expect(geometry.overflows, state).toBe(true);
      expect(geometry.railScrolls, state).toBe(false);
      // The list starts at the top of the rail (level with the toggle) and leaves the strip under the
      // toggle free, so neither a link nor the scrollbar runs under it.
      expect(geometry.scrollTop, state).toBeLessThanOrEqual(geometry.railTop + 1);
      expect(geometry.scrollRight, state).toBeLessThanOrEqual(geometry.toggleLeft + 1);
    }
  });
});
