import { expect, test } from "@playwright/test";

import { loginAs, PERSONAS } from "./helpers";

/**
 * Job to be done: anyone, signed in or not, can read what the product is licensed under and which third-party
 * components it contains, from the Policies page, even when no policy is published. Read-only; changes no state.
 */
test.describe("licences", () => {
  test("a signed-out visitor reads the product licence, the components and the fonts from the footer link", async ({ page }) => {
    await test.step("the footer link of the sign-in page opens the Licences group", async () => {
      await page.goto("/login");
      await page.getByLabel("Page footer").getByRole("link", { name: "Policies" }).click();
      await expect(page).toHaveURL(/\/policies/);
      await expect(page.getByRole("heading", { name: "Policies", level: 1 })).toBeVisible();
    });

    await test.step("the product licence names the licence and links to its text and source", async () => {
      await page.goto("/policies/licences/product");
      await expect(page.getByRole("heading", { name: "Product licence", level: 2 })).toBeVisible();
      await expect(page.getByText(/GNU Affero General Public License, version 3/).first()).toBeVisible();
      await expect(page.getByRole("link", { name: "Licence text" })).toHaveAttribute("href", /^https:\/\//);
      await expect(page.getByRole("link", { name: "Source code" })).toHaveAttribute("href", /^https:\/\//);
      await expect(page.getByRole("link", { name: "Commercial licence" })).toHaveAttribute("href", /COMMERCIAL-LICENSE\.md$/);
    });

    await test.step("the component table is searchable and a row shows its licence text on request", async () => {
      await page.getByRole("link", { name: "Third-party components" }).click();
      await expect(page).toHaveURL(/\/policies\/licences\/components$/);
      const libraries = page.getByRole("table", { name: "Libraries" });
      await expect(libraries).toBeVisible();
      await page.getByRole("textbox", { name: "Search libraries" }).fill("react-dom");
      await libraries.getByRole("button", { name: "react-dom", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: /^react-dom .*: licence$/ });
      await expect(dialog.getByText("MIT", { exact: true })).toBeVisible();
      await dialog.getByRole("button", { name: "Licence text" }).click();
      await expect(dialog.getByLabel("Licence text").first()).toContainText("Permission is hereby granted");
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
    });

    await test.step("the programs in the images state why a copyleft program is allowed", async () => {
      await page.getByRole("table", { name: "Programs in the images" }).getByRole("button", { name: "Ghostscript" }).click();
      const dialog = page.getByRole("dialog", { name: "Ghostscript: licence" });
      await expect(dialog.getByText("Separate program, not linked into the product")).toBeVisible();
      await page.keyboard.press("Escape");
    });

    await test.step("the fonts list their licences", async () => {
      await page.goto("/policies/licences/fonts");
      await expect(page.getByRole("article", { name: "Liberation Sans, Serif and Mono" })).toContainText("OFL-1.1");
      await expect(page.getByRole("article", { name: "DejaVu Sans" })).toBeVisible();
    });
  });

  test("a licence deep link opens without a sign-in, and a signed-in member reaches the same group from the footer", async ({ page }) => {
    await test.step("a deep link while signed out opens without a sign-in", async () => {
      await page.goto("/policies/licences/components");
      await expect(page.getByRole("heading", { name: "Third-party components", level: 2 })).toBeVisible();
      await expect(page).toHaveURL(/\/policies\/licences\/components$/);
    });

    await test.step("signed in, the footer link opens the Policies page with the Licences group in its menu", async () => {
      await loginAs(page, PERSONAS.stakeholderAlpha.email);
      await page.getByLabel("Page footer").getByRole("link", { name: "Policies" }).click();
      await expect(page.getByRole("heading", { name: "Policies", level: 1 })).toBeVisible();
      // The group holding the open page is expanded; policies published by other specs change which page opens first, so
      // go to a licence page and choose from its menu.
      await page.goto("/policies/licences/product");
      await page.getByRole("navigation", { name: "Published policies" }).getByRole("link", { name: "Fonts" }).click();
      await expect(page.getByRole("heading", { name: "Fonts", level: 2 })).toBeVisible();
    });
  });
});
