/**
 * Module: testing/labelInName
 *
 * Story helper for a control whose accessible name is longer than its visible text (a **Save** button named
 * "Save diagram" for a screen reader). A speech-input user says the words on the screen, so the visible text must
 * appear in the accessible name (WCAG 2.5.3 Label in Name); the helper pins both names at once.
 */
import { expect } from "storybook/test";

/**
 * Asserts a control reads `visible` on the screen and `accessible` to a screen reader, and that the first is part of
 * the second.
 *
 * @param control The rendered control (usually a button).
 * @param visible The text drawn on the control.
 * @param accessible The expected accessible name (its `aria-label`).
 * @throws AssertionError when either name differs, or when the visible text is not part of the accessible name.
 */
export async function expectLabelInName(control: HTMLElement, visible: string, accessible: string): Promise<void> {
  await expect((control.textContent ?? "").trim()).toBe(visible);
  await expect(control).toHaveAccessibleName(accessible);
  await expect(accessible.toLowerCase()).toContain(visible.toLowerCase());
}
