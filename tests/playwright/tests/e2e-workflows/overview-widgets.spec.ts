import { expect, test } from "@playwright/test";

import {
  apiHeaders, createDisposableProject, ensureExpanded, installCleanupHook, loginAs, onCleanup, ORG_NAMES, PASSWORD, PERSONAS, selectOrgAdminGroup,
} from "./helpers";

const API = "http://localhost:8000/api/v1";

/**
 * Job to be done: a project manager arranges the project overview on the page itself (add a gauge on a metric the
 * page does not show today and a text note, hide a tile, drag and resize widgets), saves, and restores the default;
 * the overview reflows for a narrow screen; a person who cannot change the layout has no Customise control; an
 * organisation default applies to a project that has no layout of its own.
 *
 * Each test uses a disposable project (archived by cleanup). The organisation default set in the last test is
 * removed in its cleanup, so no other spec sees it.
 */
test.describe("project overview widgets", () => {
  installCleanupHook();

  test("a manager edits the overview on the page: add, hide, drag, resize, save and restore", async ({ page }) => {
    test.setTimeout(120_000);
    const email = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, email, "E2E Overview Widgets", ORG_NAMES.alpha);
    const headers = await apiHeaders(page.request, email);
    for (const name of ["Widget one", "Widget two"]) {
      const created = await page.request.post(`${API}/projects/${project.projectId}/requirements`, {
        headers, data: { name, component_id: project.components[0].id, category_id: project.categories[0].id },
      });
      expect(created.ok()).toBeTruthy();
    }
    await page.setViewportSize({ width: 1440, height: 900 });

    await test.step("the actions sit on the project name's row, and the five key tiles share one row", async () => {
      await loginAs(page, email);
      await page.goto(`/projects/${project.projectId}`);
      const heading = await page.getByRole("heading", { level: 1 }).boundingBox();
      const customise = await page.getByRole("button", { name: "Customise overview" }).boundingBox();
      expect(Math.abs(customise!.y - heading!.y)).toBeLessThan(heading!.height);
      const tops = await Promise.all(["percent-complete", "file-count", "cr-proposed", "cr-approved", "cr-rejected"].map(
        async (id) => (await page.locator(`[data-widget-id="${id}"]`).boundingBox())!.y,
      ));
      expect(Math.max(...tops) - Math.min(...tops)).toBeLessThan(2);
    });

    await test.step("Customise overview turns the page into the editor, with the actions in a bar that stays on screen", async () => {
      await page.getByRole("button", { name: "Customise overview" }).click();
      const editor = page.locator('[data-overview-editor="project"]');
      await expect(editor.getByRole("button", { name: "Save" })).toBeVisible();
      await expect(editor.getByText("11 of 24 widgets")).toBeVisible();
      // Nothing is edited yet, so there is nothing to restore.
      await expect(editor.getByRole("button", { name: "Restore default" })).toHaveCount(0);
    });

    await test.step("a gauge on the number of requirements, and a text note, are added and set up", async () => {
      const editor = page.locator('[data-overview-editor="project"]');
      await editor.getByRole("combobox", { name: "Add widget" }).selectOption("gauge");
      let panel = page.getByRole("dialog", { name: /^Settings:/ });
      await panel.getByRole("textbox", { name: "Title" }).fill("Requirement load");
      await panel.getByRole("combobox", { name: /Metric/ }).selectOption({ label: "Requirements" });
      await panel.getByRole("spinbutton", { name: /Maximum/ }).fill("10");
      await panel.getByRole("spinbutton", { name: /Warning level/ }).fill("2");
      await panel.getByRole("button", { name: "Done" }).click();

      await editor.getByRole("combobox", { name: "Add widget" }).selectOption("text");
      panel = page.getByRole("dialog", { name: /^Settings:/ });
      await panel.getByRole("textbox", { name: "Title" }).fill("Notes");
      await panel.getByRole("textbox", { name: "Text" }).fill("Code freeze on **Friday**.");
      await panel.getByRole("button", { name: "Done" }).click();
      await expect(editor.getByText("13 of 24 widgets")).toBeVisible();
      await expect(page.locator('[data-widget-type="gauge"]').getByRole("img", { name: "Requirement load: 2, Warning" })).toBeVisible();
      await expect(page.locator('[data-widget-type="text"] strong')).toHaveText("Friday");
    });

    await test.step("a widget is hidden, resized from its corner and dragged to a new place", async () => {
      await page.getByRole("button", { name: "Hide Change requests rejected" }).click();
      await expect(page.locator('[data-widget-id="cr-rejected"]')).toHaveAttribute("data-hidden", "true");

      const gauge = page.locator('[data-widget-type="gauge"]');
      await gauge.scrollIntoViewIfNeeded();
      const before = await gauge.boundingBox();
      const corner = await gauge.getByRole("button", { name: "Resize Requirement load" }).boundingBox();
      await page.mouse.move(corner!.x + corner!.width / 2, corner!.y + corner!.height / 2);
      await page.mouse.down();
      await page.mouse.move(corner!.x + 400, corner!.y + 10, { steps: 8 });
      await page.mouse.up();
      expect((await gauge.boundingBox())!.width).toBeGreaterThan(before!.width + 100);

      await page.evaluate(() => window.scrollTo(0, 0));
      const first = page.locator('[data-widget-id="percent-complete"]');
      const second = page.locator('[data-widget-id="file-count"]');
      const grip = await first.getByRole("button", { name: "Move % Completed", exact: true }).boundingBox();
      const target = await second.boundingBox();
      await page.mouse.move(grip!.x + grip!.width / 2, grip!.y + grip!.height / 2);
      await page.mouse.down();
      await page.mouse.move(target!.x + target!.width * 0.8, target!.y + target!.height / 2, { steps: 10 });
      await page.mouse.up();
      await expect(page.locator(".overview-widget").first()).toHaveAttribute("data-widget-id", "file-count");
    });

    await test.step("the keyboard moves and resizes too", async () => {
      const note = page.locator('[data-widget-type="text"]');
      await note.getByRole("button", { name: "Move Notes", exact: true }).focus();
      await page.keyboard.press("ArrowLeft");
      await expect(page.getByText(/Notes moved to position \d+ of 13/)).toBeAttached();
      const corner = note.getByRole("button", { name: "Resize Notes" });
      const width = (await note.boundingBox())!.width;
      await corner.focus();
      await page.keyboard.press("ArrowRight");
      expect((await note.boundingBox())!.width).toBeGreaterThan(width);
    });

    await test.step("saving shows the layout to everyone: the tiles swapped, the note, and no rejected-change-requests tile", async () => {
      await page.locator('[data-overview-editor="project"]').getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Overview saved.")).toBeVisible();
      await expect(page.locator(".overview-widget").first()).toHaveAttribute("data-widget-id", "file-count");
      await expect(page.locator('[data-widget-id="cr-rejected"]')).toHaveCount(0);
      await page.reload();
      await expect(page.locator(".overview-widget").first()).toHaveAttribute("data-widget-id", "file-count");
      await expect(page.locator('[data-widget-type="text"]')).toContainText("Code freeze on Friday.");
    });

    await test.step("restoring the default brings the built-in overview back", async () => {
      await page.getByRole("button", { name: "Customise overview" }).click();
      await page.getByRole("button", { name: "Restore default" }).click();
      await page.getByRole("dialog", { name: "Restore the default overview?" }).getByRole("button", { name: "Restore default" }).click();
      await expect(page.getByText("Overview restored to the default.")).toBeVisible();
      await expect(page.locator('[data-widget-id="cr-rejected"]')).toBeVisible();
      await expect(page.locator('[data-widget-type="gauge"]')).toHaveCount(0);
    });
  });

  test("the overview reflows: two tiles to a row on a phone and one row of tiles on a laptop", async ({ page }) => {
    test.setTimeout(60_000);
    const email = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, email, "E2E Overview Reflow", ORG_NAMES.alpha);
    await loginAs(page, email);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/projects/${project.projectId}`);
    const box = async (id: string) => (await page.locator(`[data-widget-id="${id}"]`).boundingBox())!;
    await expect(page.locator('[data-widget-id="percent-complete"]')).toBeVisible();
    const [first, second, third] = [await box("percent-complete"), await box("file-count"), await box("cr-proposed")];
    expect(Math.abs(first.y - second.y)).toBeLessThan(2);
    expect(third.y).toBeGreaterThan(first.y + first.height - 1);
    // The page never scrolls sideways, and a chart takes the full width.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
    const chart = await box("requirements-by-status");
    expect(chart.width).toBeGreaterThan(first.width * 1.8);
  });

  test("a person who cannot change the layout has no Customise control, and the server refuses a write", async ({ page }) => {
    test.setTimeout(60_000);
    const adminEmail = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, adminEmail, "E2E Overview Member", ORG_NAMES.alpha);
    const memberEmail = `e2e-overview-member-${Date.now()}@example.com`;
    const created = await page.request.post(`${API}/orgs/${project.organizationId}/users`, {
      headers: project.headers, data: { email: memberEmail, display_name: "E2E Overview Member", password: PASSWORD, role: "member" },
    });
    expect(created.ok()).toBeTruthy();
    const member = await created.json();
    const granted = await page.request.post(`${API}/projects/${project.projectId}/roles`, {
      headers: project.headers, data: { user_id: member.user_id, role: "member" },
    });
    expect(granted.ok()).toBeTruthy();

    await loginAs(page, memberEmail);
    await page.goto(`/projects/${project.projectId}`);
    await expect(page.locator('[data-widget-id="file-count"]')).toBeVisible();
    await expect(page.getByRole("button", { name: "Customise overview" })).toHaveCount(0);
    const memberHeaders = await apiHeaders(page.request, memberEmail);
    const refused = await page.request.put(`${API}/projects/${project.projectId}/overview-layout`, { headers: memberHeaders, data: { widgets: [] } });
    expect(refused.status()).toBe(403);
  });

  test("an organisation default applies to a project with no layout of its own", async ({ page }) => {
    test.setTimeout(90_000);
    const email = PERSONAS.orgAdminAlphaBeta.email;
    const project = await createDisposableProject(page.request, email, "E2E Overview Default", ORG_NAMES.alpha);
    const orgUrl = `${API}/orgs/${project.organizationId}/overview-layout`;
    onCleanup(async (request) => {
      await request.delete(orgUrl, { headers: await apiHeaders(request, email) });
    });
    await page.setViewportSize({ width: 1440, height: 900 });

    await test.step("the organisation administrator hides the Files tile in the default overview", async () => {
      await loginAs(page, email);
      await page.goto(`/orgs/${project.organizationId}/admin`);
      await selectOrgAdminGroup(page, "Projects");
      await ensureExpanded(page, "Default overview");
      // The section is a compact row; the editor opens in a dialog.
      await expect(page.getByText("Built-in layout")).toBeVisible();
      await page.getByRole("button", { name: "Edit overview default" }).click();
      const dialog = page.getByRole("dialog", { name: "Default overview" });
      const editor = dialog.locator('[data-overview-editor="organisation"]');
      // The default has no data of its own: each widget is a labelled block.
      await expect(editor.locator("[data-placeholder]").first()).toBeVisible();
      await editor.getByRole("button", { name: "Hide Files", exact: true }).click();
      // Closing with unsaved changes asks first; keeping the edits leaves the dialog open.
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog", { name: /Discard/ })).toBeVisible();
      await page.getByRole("dialog", { name: /Discard/ }).getByRole("button", { name: "Keep editing" }).click();
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText("Overview saved.")).toBeVisible();
      await expect(dialog).toBeHidden();
      await expect(page.getByText(/^Customised: \d+ widgets?$/)).toBeVisible();
    });

    await test.step("a project with no layout of its own shows the default", async () => {
      await page.goto(`/projects/${project.projectId}`);
      await expect(page.locator('[data-widget-id="percent-complete"]')).toBeVisible();
      await expect(page.locator('[data-widget-id="file-count"]')).toHaveCount(0);
    });
  });
});
