import { expect, test } from "@playwright/test";

import { createDocumentLayoutWorld, loginAs, logout, onCleanup, installCleanupHook, PASSWORD, SERVER_ADMIN_LOGIN } from "./helpers";

installCleanupHook();

const API = "http://localhost:8000/api/v1";
const FAMILY_KEY = "x-liberation-mono";

/**
 * Job to be done: a server administrator checks which report fonts are on offer, hides a provided font from
 * authors and brings it back, and sets the name Word and OpenDocument are told for it.
 *
 * The test stack mounts one provided font (`tests/container/report-fonts`, a copy of Liberation Mono). The test
 * leaves the family offered, with its own name, however it ends, so a rerun starts from the same state.
 */
test("a server admin hides a provided report font from authors, renames it for Word, and brings it back", async ({ page }) => {
  const token = (await (await page.request.post(`${API}/auth/login`, { data: SERVER_ADMIN_LOGIN })).json()).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  onCleanup(async (cleanup) => {
    await cleanup.put(`${API}/system/report-fonts/${FAMILY_KEY}`, {
      headers, data: { word_name: "", generic: "sans-serif", enabled: true },
    });
  });
  const choices = async () =>
    ((await (await page.request.get(`${API}/system/report-fonts/choices`, { headers })).json()) as { key: string }[]).map((c) => c.key);

  // An author's Body font picker, in a layout of a disposable organisation: it lists the provided font only while it is offered.
  const world = await createDocumentLayoutWorld(page.request, "fonts-picker");
  const bodyFontOptions = async () => {
    await page.goto(`/projects/${world.project.id}/report-layouts/${world.layout.id}`);
    await page.getByRole("tab", { name: "Blocks" }).click();
    await page.locator(".blocklyText", { hasText: /^Layout$/ }).click();
    const picker = page.getByLabel("Block details").getByRole("combobox", { name: "Body font" });
    await expect(picker.locator("option", { hasText: "Sans" }).first()).toBeAttached();
    return picker.locator("option").allTextContents();
  };

  await loginAs(page, world.adminEmail, PASSWORD);
  expect(await bodyFontOptions()).toContain("Liberation Mono (provided by the server administrator)");

  await logout(page);
  await loginAs(page, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  await page.goto("/server/management/reportFonts");
  const list = page.getByRole("list", { name: "Report fonts" });
  await expect(list.getByText("Unicode Sans")).toBeVisible();
  const row = list.locator(".item-row", { hasText: "Liberation Mono" });
  await expect(row).toContainText("Provided");
  await expect(row).toContainText("Regular (Installable)");
  expect(await choices()).toContain(FAMILY_KEY);

  // Hide it from authors; layouts that already use it are unaffected, but the picker list loses it.
  await row.getByRole("switch", { name: "Offered to authors: Liberation Mono" }).click();
  await expect(page.getByText("Liberation Mono saved.")).toBeVisible();
  await expect.poll(choices).not.toContain(FAMILY_KEY);
  await logout(page);
  await loginAs(page, world.adminEmail, PASSWORD);
  expect(await bodyFontOptions()).not.toContain("Liberation Mono (provided by the server administrator)");
  await logout(page);
  await loginAs(page, SERVER_ADMIN_LOGIN.email, SERVER_ADMIN_LOGIN.password);
  await page.goto("/server/management/reportFonts");

  // Give it a different name for Word and OpenDocument.
  await row.getByRole("button", { name: "Settings: Liberation Mono" }).click();
  const name = page.getByRole("textbox", { name: "Name in Word and OpenDocument" });
  await name.fill("Courier Prime");
  await name.blur();
  await expect(row).toContainText("Word and OpenDocument name: Courier Prime");
  await page.keyboard.press("Escape");

  // A reload shows the saved state, and turning it back on offers it again.
  await page.reload();
  const reloaded = page.getByRole("list", { name: "Report fonts" }).locator(".item-row", { hasText: "Liberation Mono" });
  await expect(reloaded.getByRole("switch", { name: "Offered to authors: Liberation Mono" })).not.toBeChecked();
  await expect(reloaded).toContainText("Courier Prime");
  await reloaded.getByRole("switch", { name: "Offered to authors: Liberation Mono" }).click();
  await expect.poll(choices).toContain(FAMILY_KEY);

  await page.getByRole("button", { name: "Rescan" }).click();
  await expect(page.getByText("Rescanned: 1 provided family found.")).toBeVisible();
});
