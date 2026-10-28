/**
 * Module: testing/saveVersionHelpers
 *
 * Storybook-only steps for the "Save new version" button (`SaveVersionButton`), which opens a popover asking for an
 * optional note before it saves.
 */
import { screen, userEvent, within } from "storybook/test";

/**
 * Presses the Save new version button and saves from the popover it opens.
 *
 * @param button The "Save new version" button.
 * @param note A note on the change to type first; omit it to save without one.
 */
export async function saveVersion(button: HTMLElement, note?: string): Promise<void> {
  await userEvent.click(button);
  const popover = within(await screen.findByRole("dialog", { name: "Save new version" }));
  if (note !== undefined) await userEvent.type(popover.getByRole("textbox", { name: "Note on this change" }), note);
  await userEvent.click(popover.getByRole("button", { name: "Save" }));
}
