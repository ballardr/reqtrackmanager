import { expect, type Page, test } from "@playwright/test";

import {
  apiHeaders,
  deleteOrgOnCleanup,
  installCleanupHook,
  loginAs,
  onCleanup,
  PASSWORD,
  selectOrgAdminGroup,
  selectServerManagementGroup,
  SERVER_ADMIN_LOGIN,
} from "./helpers";

// Deletes this file's disposable orgs and restores the server default after each test.
installCleanupHook();

const apiBaseUrl = "http://localhost:8000";
const SECTION = "Personal data in exports and imports";

interface OrgTag {
  tag: string;
  server_allowed: boolean;
  override: boolean | null;
  effective: boolean;
}

/** A tag's row in the shared settings list, found by its display name. */
function tagRow(page: Page, name: string) {
  return page.locator(".module-settings-row", { has: page.getByText(name, { exact: true }) });
}

/** Opens the section if it is collapsed (sections remember their state per browser). */
async function openSection(page: Page) {
  const header = page.getByRole("button", { name: SECTION });
  if ((await header.getAttribute("aria-expanded")) === "false") await header.click();
}

/** Clicks "Allow" in the widening confirm when it appears (only widening asks). */
async function confirmWidening(page: Page, willWiden: boolean) {
  if (!willWiden) return;
  await page.getByRole("dialog").getByRole("button", { name: "Allow", exact: true }).click();
}

/**
 * Job to be done: an organisation administrator decides for their own organisation whether record
 * columns that hold personal data may leave the application in an export (or be written by an import),
 * seeing the server default it overrides and able to go back to following it. Widening the policy asks
 * first; the change is saved at once.
 *
 * Uses a disposable organisation and admin created via the API; it never touches the server default,
 * which the server-admin test below changes and restores.
 */
test("an org admin overrides the server default for a sensitivity tag and goes back to following it", async ({ page }) => {
  const suffix = Date.now();
  const serverHeaders = await apiHeaders(page.request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  const org = await (
    await page.request.post(`${apiBaseUrl}/api/v1/orgs`, {
      headers: serverHeaders, data: { name: `E2E Personal Data Org ${suffix}` },
    })
  ).json();
  deleteOrgOnCleanup({ id: org.id });
  const adminEmail = `e2e-personal-data-admin-${suffix}@example.com`;
  await page.request.post(`${apiBaseUrl}/api/v1/orgs/${org.id}/users`, {
    headers: serverHeaders, data: { email: adminEmail, display_name: "E2E Personal Data Admin", password: PASSWORD, role: "org_admin" },
  });
  const adminHeaders = await apiHeaders(page.request, adminEmail);
  const read = async (): Promise<OrgTag> =>
    (
      (await (
        await page.request.get(`${apiBaseUrl}/api/v1/orgs/${org.id}/record-sensitivity-policy`, { headers: adminHeaders })
      ).json()) as OrgTag[]
    ).find((row) => row.tag === "contact")!;

  const start = await read();
  expect(start.override).toBeNull();

  await loginAs(page, adminEmail, PASSWORD);
  await page.goto("/orgs");
  await selectOrgAdminGroup(page, "Security");
  await openSection(page);
  const row = tagRow(page, "Contact details");
  await expect(row).toBeVisible();
  await expect(row.getByText("Follows the server")).toBeVisible();

  await test.step("flipping the effective value saves an override of the opposite value", async () => {
    await row.getByRole("switch").click();
    await confirmWidening(page, !start.effective);
    await expect(row.getByText("Custom")).toBeVisible();
    const changed = await read();
    expect(changed.override).toBe(!start.server_allowed);
    expect(changed.effective).toBe(!start.effective);
    await expect(row.getByRole("switch")).toHaveAttribute("aria-checked", String(!start.effective));
  });

  await test.step("following the server again clears the override", async () => {
    // Going back widens the policy when the server default allows the tag and the override excluded it.
    await row.getByRole("button", { name: "Follow the server again" }).click();
    await confirmWidening(page, start.server_allowed && !(await read()).effective);
    await expect(row.getByText("Follows the server")).toBeVisible();
    const restored = await read();
    expect(restored.override).toBeNull();
    expect(restored.effective).toBe(start.server_allowed);
  });
});

/**
 * Job to be done: a server administrator opts the whole deployment in or out of personal-data columns
 * (everything is excluded until allowed). Restores the original value afterwards, because the default is
 * deployment-wide.
 */
test("a server admin changes the server default for a sensitivity tag", async ({ page, request }) => {
  const serverHeaders = await apiHeaders(request, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  const listing = (await (await request.get(`${apiBaseUrl}/api/v1/system/record-sensitivity-policy`, { headers: serverHeaders })).json()) as {
    tag: string;
    allowed: boolean;
  }[];
  const original = listing.find((item) => item.tag === "free_text_people")!.allowed;
  onCleanup(async (cleanup) => {
    const headers = await apiHeaders(cleanup, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
    await cleanup.put(`${apiBaseUrl}/api/v1/system/record-sensitivity-policy/free_text_people`, { headers, data: { allowed: original } });
  });

  await loginAs(page, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  await page.goto("/server/management");
  await selectServerManagementGroup(page, "Data policy");
  await openSection(page);
  const row = tagRow(page, "Free text that can quote people");
  await expect(row).toBeVisible();
  await expect(row.getByText(original ? "Allowed on this server." : "Excluded on this server.")).toBeVisible();

  await row.getByRole("switch").click();
  await confirmWidening(page, !original);
  await expect(row.getByText(original ? "Excluded on this server." : "Allowed on this server.")).toBeVisible();
  const after = (await (await request.get(`${apiBaseUrl}/api/v1/system/record-sensitivity-policy`, { headers: serverHeaders })).json()) as {
    tag: string;
    allowed: boolean;
  }[];
  expect(after.find((item) => item.tag === "free_text_people")!.allowed).toBe(!original);
});
