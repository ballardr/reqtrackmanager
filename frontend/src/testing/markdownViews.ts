/**
 * Module: testing/markdownViews
 *
 * Storybook helpers for a Markdown field's view switch (Visual, Write, Preview). The switch is drawn only while the
 * field is in use, so a test first works in the field (focuses its editor) and then presses the view's button.
 */
import { userEvent, within } from "storybook/test";

export type MarkdownViewName = "Visual" | "Write" | "Preview";

/** The element that takes focus in whichever view the field shows (the editor, the source, or the preview box). */
const FOCUS_TARGET = 'textarea, [contenteditable="true"], [role="region"][tabindex="0"]';

/**
 * @param root The element holding the field(s).
 * @param index Which Markdown field under `root` (default the first).
 * @returns The field's frame, which holds its caption, view switch, toolbar and view.
 */
export function markdownField(root: HTMLElement, index = 0): HTMLElement {
  const field = root.querySelectorAll<HTMLElement>(".markdown-editor")[index];
  if (!field) throw new Error(`No Markdown field at index ${index}`);
  return field;
}

/**
 * Works in the field (so its view switch is shown) and presses the button of `view`.
 *
 * @param root The element holding the field(s).
 * @param view The view to show.
 * @param index Which Markdown field under `root` (default the first).
 */
export async function chooseMarkdownView(root: HTMLElement, view: MarkdownViewName, index = 0): Promise<void> {
  const field = markdownField(root, index);
  field.querySelector<HTMLElement>(FOCUS_TARGET)?.focus();
  const group = await within(field).findByRole("group", { name: "Editor view" });
  await userEvent.click(within(group).getByRole("button", { name: view }));
}

/**
 * Works in the field (the switch is drawn only then) and reads its view switch.
 *
 * @param root The element holding the field(s).
 * @param index Which Markdown field under `root` (default the first).
 * @returns The names of the views the field offers, in order, and the one shown.
 */
export async function markdownViewState(root: HTMLElement, index = 0): Promise<{ offered: string[]; shown: string | null }> {
  const field = markdownField(root, index);
  field.querySelector<HTMLElement>(FOCUS_TARGET)?.focus();
  const group = await within(field).findByRole("group", { name: "Editor view" });
  const buttons = within(group).getAllByRole("button");
  return {
    offered: buttons.map((button) => button.getAttribute("aria-label") ?? ""),
    shown: buttons.find((button) => button.getAttribute("aria-pressed") === "true")?.getAttribute("aria-label") ?? null,
  };
}
