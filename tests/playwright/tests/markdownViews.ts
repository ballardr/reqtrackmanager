/**
 * Playwright helpers for a Markdown field's view switch (Visual, Write, Preview). The switch is drawn only while the
 * field is in use, so a test works in the field (focuses its editor) before it presses the view's button.
 */
import type { Locator } from "@playwright/test";

export type MarkdownViewName = "Visual" | "Write" | "Preview";

/** The element that takes focus in whichever view the field shows (the editor, the source, or the preview box). */
const FOCUS_TARGET = 'textarea, [contenteditable="true"], [role="region"][tabindex="0"]';

/**
 * @param scope A page or dialog locator holding the field(s).
 * @param index Which Markdown field under `scope` (default the first).
 * @returns The field's frame, holding its caption, view switch, toolbar and view.
 */
export function markdownField(scope: Locator | { locator: (selector: string) => Locator }, index = 0): Locator {
  return scope.locator(".markdown-editor").nth(index);
}

/**
 * Works in the field, then presses the button of `view`.
 *
 * @param field The field's frame (`markdownField`).
 * @param view The view to show.
 */
export async function chooseMarkdownView(field: Locator, view: MarkdownViewName): Promise<void> {
  await field.locator(FOCUS_TARGET).first().focus();
  await field.getByRole("group", { name: "Editor view" }).getByRole("button", { name: view, exact: true }).click();
}

/**
 * @param field The field's frame (`markdownField`).
 * @param view The view expected.
 * @returns A locator that matches once when `view` is the one the field shows; the switch is hidden while the field
 * rests, so this checks the pressed state in the page rather than visibility.
 */
export function shownMarkdownView(field: Locator, view: MarkdownViewName): Locator {
  return field.locator(`.view-switch button[aria-label="${view}"][aria-pressed="true"]`);
}

/** The views a field offers, as a locator over its switch buttons (count and text work while the switch is hidden). */
export function offeredMarkdownViews(field: Locator): Locator {
  return field.locator(".view-switch button");
}
