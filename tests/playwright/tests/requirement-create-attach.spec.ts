import { expect, test } from "@playwright/test";

/**
 * UX review: files and links could previously only be attached to a
 * requirement after closing the create form and opening the detail page.
 * The create modal's "Create" button behaves exactly as before (closes
 * immediately); a new, separate "Create & attach files/links" action
 * advances the same modal to a second step against the just-created
 * requirement's real id before closing — opt-in, since most creates don't
 * need it and every other workflow (the golden path included) depends on
 * a plain "Create" staying a single, modal-closing action.
 */
test("Create & attach files/links advances to an attach-files-and-links step, then finishes", async ({ page }) => {
  const ADMIN_EMAIL = "admin@example.com";
  const ADMIN_PASSWORD = "ChangeMe123!";
  const projectName = `Attach Flow ${Date.now()}`;

  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/projects(\/|$)/);

  await page.goto("/projects");
  await page.getByRole("button", { name: "New project" }).click();
  const newProjectDialog = page.getByRole("dialog", { name: "New project" });
  await newProjectDialog.getByLabel("Name", { exact: true }).fill(projectName);
  await newProjectDialog.getByRole("button", { name: "Create" }).click();
  await page.waitForURL(/\/projects\/[^/]+$/);

  // Set up a component/category first via Project Admin, matching
  // golden-path.spec.ts's own established pattern — a fresh project has
  // neither yet.
  await page.getByText("Project Admin").click();
  await page.getByRole("tab", { name: "Structure" }).click();
  const componentsSection = page.locator(".card", { has: page.getByRole("button", { name: "Components & categories section" }) });
  await componentsSection.getByPlaceholder("Name").fill("Software");
  await componentsSection.getByPlaceholder("Prefix").fill("SW");
  await componentsSection.getByRole("button", { name: "New component" }).click();
  await expect(page.locator('input[value="Software"]').first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  const softwareRow = page.locator('input[value="Software"]:not([placeholder])').locator("xpath=../../..");
  await softwareRow.getByPlaceholder("Name").fill("Performance");
  await softwareRow.getByPlaceholder("Prefix").fill("PERF");
  await softwareRow.getByRole("button", { name: "New category" }).click();
  // Note: this locator also matches the still-open "New category" name
  // input itself (it too has value="Performance" the instant it's filled,
  // well before the create request resolves) — visible from the moment
  // it's typed, so on its own this assertion proves nothing about the
  // create having finished. The networkidle wait below is what actually
  // closes that gap; without it, Requirements can navigate/reload before
  // the category exists server-side and permanently render its
  // no-components-or-categories fallback instead of the real create form.
  await expect(page.locator('input[value="Performance"]').first()).toBeVisible();
  await page.waitForLoadState("networkidle");

  await page.getByRole("link", { name: "Requirements", exact: true }).click();
  await page.getByRole("button", { name: "New requirement" }).click();
  const createDialog = page.getByRole("dialog", { name: "New requirement" });
  await createDialog.getByPlaceholder("Name", { exact: true }).fill("Password reset");
  await createDialog.getByRole("button", { name: "Create & attach files/links" }).click();

  const step2 = page.getByRole("dialog", { name: /Attach files & links/ });
  await expect(step2).toBeVisible();
  await expect(step2.getByText("Attachments")).toBeVisible();
  await expect(step2.getByText("Traceability links")).toBeVisible();
  // A brand-new project has exactly this one requirement — nothing else to
  // link to yet, so Add Link is greyed out.
  await expect(step2.getByRole("button", { name: "Add link" })).toBeDisabled();

  await step2.getByRole("button", { name: "Finish" }).click();
  await expect(page.getByRole("dialog", { name: /Attach files & links/ })).not.toBeVisible();
  await expect(page.getByText("Password reset")).toBeVisible();
});

test("plain Create closes the modal immediately, unchanged", async ({ page }) => {
  const ADMIN_EMAIL = "admin@example.com";
  const ADMIN_PASSWORD = "ChangeMe123!";
  const projectName = `Plain Create ${Date.now()}`;

  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/projects(\/|$)/);

  await page.goto("/projects");
  await page.getByRole("button", { name: "New project" }).click();
  const newProjectDialog = page.getByRole("dialog", { name: "New project" });
  await newProjectDialog.getByLabel("Name", { exact: true }).fill(projectName);
  await newProjectDialog.getByRole("button", { name: "Create" }).click();
  await page.waitForURL(/\/projects\/[^/]+$/);

  await page.getByText("Project Admin").click();
  await page.getByRole("tab", { name: "Structure" }).click();
  const componentsSection = page.locator(".card", { has: page.getByRole("button", { name: "Components & categories section" }) });
  await componentsSection.getByPlaceholder("Name").fill("Software");
  await componentsSection.getByPlaceholder("Prefix").fill("SW");
  await componentsSection.getByRole("button", { name: "New component" }).click();
  await expect(page.locator('input[value="Software"]').first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  const softwareRow = page.locator('input[value="Software"]:not([placeholder])').locator("xpath=../../..");
  await softwareRow.getByPlaceholder("Name").fill("Performance");
  await softwareRow.getByPlaceholder("Prefix").fill("PERF");
  await softwareRow.getByRole("button", { name: "New category" }).click();
  // See the sibling test above: this locator also matches the still-open
  // "New category" name input (visible with this value the instant it's
  // typed, before the create request resolves), so the networkidle wait
  // is what actually guarantees the category exists before navigating away.
  await expect(page.locator('input[value="Performance"]').first()).toBeVisible();
  await page.waitForLoadState("networkidle");

  await page.getByRole("link", { name: "Requirements", exact: true }).click();
  await page.getByRole("button", { name: "New requirement" }).click();
  const createDialog = page.getByRole("dialog", { name: "New requirement" });
  await createDialog.getByPlaceholder("Name", { exact: true }).fill("Boot fast");
  await createDialog.getByRole("button", { name: "Create", exact: true }).click();

  await expect(page.getByRole("dialog", { name: "New requirement" })).not.toBeVisible();
  await expect(page.getByText("Boot fast")).toBeVisible();
});
