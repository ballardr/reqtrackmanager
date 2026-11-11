import { expect, test, type APIRequestContext } from "@playwright/test";

import { apiHeaders, installCleanupHook, loginAs, logout, onCleanup, PERSONAS, selectServerManagementGroup } from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Registers cleanup that unpublishes every server policy and deletes the ones this spec created (a built-in policy
 * cannot be deleted, only unpublished), so no policy stays visible on the login page for another spec. Idempotent.
 */
async function unpublishServerPolicies(request: APIRequestContext, marker: string): Promise<void> {
  const headers = await apiHeaders(request, PERSONAS.serverAdmin.email);
  const listed = await request.get(`${API}/system/policies`, { headers });
  if (!listed.ok()) return;
  for (const item of (await listed.json()) as { id: string | null; key: string | null; title: string; state: string }[]) {
    if (item.id === null) continue;
    if (item.state === "published") await request.post(`${API}/system/policies/${item.id}/unpublish`, { headers });
    if (item.title.includes(marker)) await request.delete(`${API}/system/policies/${item.id}`, { headers });
  }
}

function removePoliciesOnCleanup(marker: string): void {
  onCleanup((request: APIRequestContext) => unpublishServerPolicies(request, marker));
}

/**
 * Job to be done: a server administrator publishes a policy that anyone can read before signing in, changes it
 * as a new version, and can take it off the page again; the older "Data policy" address still reaches the renamed
 * personal data group.
 */
test.describe("server policies", () => {
  installCleanupHook();

  test("a published policy is readable signed out, linked from the login page and removed when unpublished", async ({ page }) => {
    test.setTimeout(120_000);
    const marker = `E2E Acceptable use ${Date.now()}`;
    removePoliciesOnCleanup(marker);
    // The seeded datasets publish the built-in Privacy and Data policies; this test starts from none published.
    await unpublishServerPolicies(page.request, marker);

    await test.step("the server administrator writes a policy in the visual editor", async () => {
      await loginAs(page, PERSONAS.serverAdmin.email);
      await page.goto("/server/management");
      await selectServerManagementGroup(page, "Policies");
      await expect(page.getByRole("table", { name: "Policies" })).toBeVisible();
      await page.getByRole("button", { name: "New policy" }).click();
      const dialog = page.getByRole("dialog", { name: "New policy" });
      await dialog.getByRole("textbox", { name: /^Title/ }).fill(marker);
      await dialog.getByRole("textbox", { name: "Policy text" }).click();
      await dialog.getByRole("button", { name: "Heading 1" }).click();
      await page.keyboard.type("Scope");
      await page.keyboard.press("Enter");
      await page.keyboard.type("Use the service responsibly.");
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Policy created.")).toBeVisible();
      await expect(page.getByRole("table", { name: "Policies" }).getByRole("row", { name: new RegExp(marker) })).toContainText("Not published");
    });

    await test.step("a draft is not on the public page", async () => {
      await logout(page);
      await page.goto("/policies");
      await expect(page.getByText(marker)).toHaveCount(0);
      await expect(page).toHaveURL(/\/login$/);
    });

    await test.step("publishing makes it readable without signing in", async () => {
      await loginAs(page, PERSONAS.serverAdmin.email);
      await page.goto("/server/management/policies");
      await page.getByRole("button", { name: `Publish ${marker}` }).click();
      const dialog = page.getByRole("dialog", { name: `Publish "${marker}"?` });
      await dialog.getByRole("textbox", { name: "Change note" }).fill("First version");
      await dialog.getByRole("button", { name: "Publish" }).click();
      await expect(page.getByText("Policy published.")).toBeVisible();
      await logout(page);
      await page.goto("/policies");
      // A single published policy has no side menu; the page shows it at once.
      await expect(page.getByRole("heading", { name: marker, level: 2 })).toBeVisible();
      await expect(page.getByText("Use the service responsibly.")).toBeVisible();
      await expect(page.getByText(/Version 1, published/)).toBeVisible();
    });

    await test.step("the login page links to the Policies page", async () => {
      await page.goto("/login");
      await page.getByRole("link", { name: "Policies" }).click();
      await expect(page).toHaveURL(/\/policies/);
      await expect(page.getByRole("heading", { name: marker, level: 2 })).toBeVisible();
    });

    await test.step("the sign-up and forgot-password pages carry the footer link", async () => {
      for (const path of ["/signup", "/forgot-password"]) {
        await page.goto(path);
        const footer = page.getByRole("contentinfo", { name: "Page footer" });
        await expect(footer.getByRole("link", { name: "Policies" })).toHaveAttribute("href", "/policies");
        await expect(footer.getByText(/^Version: v\S+$/)).toBeVisible();
      }
    });

    await test.step("a signed-in member finds the footer link with the navigation rail collapsed", async () => {
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.getByRole("button", { name: "Collapse navigation" }).click();
      // Signed in, the footer sits inside the main region, so it is found by its label, not the contentinfo role.
      const footer = page.getByLabel("Page footer");
      await expect(footer.getByText(/^Version: v\S+\/v\S+$/)).toBeVisible();
      await footer.getByRole("link", { name: "Policies" }).click();
      await expect(page.getByText("Use the service responsibly.")).toBeVisible();
      // Restore the preference so no later step starts with a collapsed rail.
      await page.getByRole("button", { name: "Expand navigation" }).click();
    });

    await test.step("unpublishing removes it from the page", async () => {
      await loginAs(page, PERSONAS.serverAdmin.email);
      await page.goto("/server/management/policies");
      await page.getByRole("button", { name: `Unpublish ${marker}` }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Unpublish" }).click();
      await expect(page.getByText("Policy unpublished.")).toBeVisible();
      await logout(page);
      await page.goto("/policies");
      await expect(page.getByText(marker)).toHaveCount(0);
      await expect(page).toHaveURL(/\/login$/);
      await expect(page.getByRole("link", { name: "Policies" })).toHaveCount(0);
      // The footer stays (it carries the version) but has no policies link.
      await expect(page.getByLabel("Page footer").getByText(/^Version: v\S+$/)).toBeVisible();
    });
  });

  test("the older Data policy address reaches the renamed Personal data in exports group", async ({ page }) => {
    await loginAs(page, PERSONAS.serverAdmin.email);
    await page.goto("/server/management/dataPolicy");
    await expect(page).toHaveURL(/\/server\/management\/personalDataExport$/);
    await expect(page.getByRole("link", { name: "Personal data in exports" })).toBeVisible();
    await expect(page.getByLabel("Server management sections").getByRole("link", { name: "Policies", exact: true })).toBeVisible();
  });
});
