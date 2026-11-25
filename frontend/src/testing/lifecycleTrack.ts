/**
 * Module: testing/lifecycleTrack
 *
 * Storybook `play` helper for the lifecycle track `RecordHeader` draws, so stories of detail pages assert where a
 * record is in its life without repeating the track's markup.
 *
 * External dependencies: `storybook/test`.
 */

import { userEvent, within } from "storybook/test";

/**
 * Reads the current step of the lifecycle track.
 *
 * @param root The story canvas element.
 * @returns The label of the step marked `aria-current="step"`, or `null` when the page draws no track.
 */
export function currentLifecycleStep(root: HTMLElement): string | null {
  return root.querySelector('[aria-current="step"] .lifecycle-step__label')?.textContent?.trim() ?? null;
}

/**
 * Promotes the record through the track: presses the next step, then Promote in the popover it opens. A type's own
 * confirmation dialog is left open for the caller.
 *
 * @param canvas The story canvas queries.
 * @param stepLabel The label of the next step ("Approved").
 */
export async function promoteViaTrack(canvas: ReturnType<typeof within>, stepLabel: string): Promise<void> {
  await userEvent.click(await canvas.findByRole("button", { name: `Next step: ${stepLabel}` }));
  await userEvent.click(await within(document.body).findByRole("button", { name: `Promote to ${stepLabel}` }));
}
