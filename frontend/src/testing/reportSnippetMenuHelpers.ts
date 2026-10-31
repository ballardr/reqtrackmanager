/**
 * Module: testing/reportSnippetMenuHelpers
 *
 * Story helpers for the designer's Snippets menu: open it from the toolbar and reach one of its items, which render in
 * a popover outside the story canvas.
 */
import { screen, userEvent, within } from "storybook/test";

/**
 * Opens the Snippets menu in `canvasElement`'s toolbar and returns the item called `name` (Insert snippet, Save as snippet).
 *
 * @param canvasElement The story canvas holding the toolbar.
 * @param name The menu item's name.
 * @returns The menu item button, still in the open menu.
 */
export async function snippetMenuItem(canvasElement: HTMLElement, name: "Insert snippet" | "Save as snippet"): Promise<HTMLElement> {
  await userEvent.click(await within(canvasElement).findByRole("button", { name: "Snippets" }));
  return screen.findByRole("menuitem", { name });
}

/** Opens the Snippets menu and chooses the item called `name`. */
export async function chooseSnippetMenuItem(canvasElement: HTMLElement, name: "Insert snippet" | "Save as snippet"): Promise<void> {
  await userEvent.click(await snippetMenuItem(canvasElement, name));
}
