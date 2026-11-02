import { expect, test } from "@playwright/test";

import { createDocumentLayoutWorld, installCleanupHook, loginAs, openDesignerTextView, PASSWORD, saveNewVersion } from "./helpers";

/**
 * Job to be done: open a layout on its Blocks, switch to the Text view, and use the JSON view (the raw layout, for
 * advanced use) to inspect and repair it, with the same checks as the other views.
 *
 * Works in its own disposable organisation, so it passes alone, in any order and repeated.
 */
test.describe("Report layout designer views", () => {
  installCleanupHook();

  test("a layout opens on Blocks, then Text, then JSON, and JSON edits are checked, saved and read back", async ({ page, request }) => {
    const { adminEmail, project, layout } = await createDocumentLayoutWorld(request, "views");
    await loginAs(page, adminEmail, PASSWORD);
    await page.goto(`/projects/${project.id}/report-layouts/${layout.id}`);

    await test.step("the views are Blocks, Text and JSON in that order and the layout opens on Blocks", async () => {
      const tabs = page.getByRole("tablist").filter({ has: page.getByRole("tab", { name: "JSON", exact: true }) }).getByRole("tab");
      await expect(tabs).toHaveText(["Blocks", "Text", "JSON"]);
      await expect(page.getByRole("tab", { name: "Blocks", exact: true })).toHaveAttribute("aria-selected", "true");
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveCount(0);
    });

    await test.step("the JSON view is the raw layout with a note and no helpers", async () => {
      await page.getByRole("tab", { name: "JSON", exact: true }).click();
      const json = page.getByRole("textbox", { name: "Layout JSON" });
      await expect(json).toHaveValue(/"text": "A report"/);
      await expect(page.getByRole("note")).toContainText("For advanced use only.");
      await expect(page.getByRole("complementary", { name: "Designer tools" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Snippets" })).toHaveCount(0);
      await expect(page.getByText("No problems.")).toBeVisible();
    });

    await test.step("JSON that is not JSON, or that the checker refuses, blocks Save and the switch", async () => {
      const json = page.getByRole("textbox", { name: "Layout JSON" });
      const good = await json.inputValue();
      await json.fill("{ nope");
      await expect(page.getByText("1 problem to fix")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save new version" }).first()).toBeDisabled();
      await page.getByRole("tab", { name: "Text", exact: true }).click();
      await expect(page.getByRole("tab", { name: "JSON", exact: true })).toHaveAttribute("aria-selected", "true");
      await expect(page.getByRole("alert").first()).toBeVisible();

      await json.fill(good.replace('"text": "A report"', '"text": ""'));
      await expect(page.getByText("nodes[0].text:")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save new version" }).first()).toBeDisabled();
      await json.fill(good);
    });

    await test.step("an edit in the JSON saves, and the Text and Blocks views show it after a reload", async () => {
      const json = page.getByRole("textbox", { name: "Layout JSON" });
      await json.fill((await json.inputValue()).replace('"text": "A report"', '"text": "Repaired in JSON"'));
      await expect(page.getByText("Unsaved changes")).toBeVisible();
      await expect(page.getByText("No problems.")).toBeVisible();
      await saveNewVersion(page);
      await page.reload();
      await expect(page.getByRole("tab", { name: "Blocks", exact: true })).toHaveAttribute("aria-selected", "true");
      await openDesignerTextView(page);
      await expect(page.getByRole("textbox", { name: "Layout text" })).toHaveValue(/Repaired in JSON/);
    });
  });
});
