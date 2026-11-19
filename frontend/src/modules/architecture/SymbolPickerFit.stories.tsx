/**
 * Stories: the symbol picker's panel fits the field it opens from, whatever that field's width.
 *
 * The picker is placed in the Selection card, the type form and the element form, which are different widths. The panel
 * takes the width it is given (never a minimum of its own), so at each width its content lies inside the bubble, the bubble
 * inside the window, and the bubble does not cover the field it opened from when there is room below it.
 */
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { page } from "vitest/browser";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { popoverFitViolations } from "../../testing/popoverFit";
import { withToast } from "../../testing/storybook-helpers";
import { isolateSymbolPickerView, mockArchitectureReads, PROJECT_ID, SYMBOLS } from "./architectureFixtures";
import { SymbolPicker } from "./SymbolPicker";
import type { ArchitectureSymbol } from "./types";

/** A library long enough to scroll, with names that are long and names that cannot break. */
const LONG_LIBRARY: ArchitectureSymbol[] = [
  ...SYMBOLS,
  { id: "sym-long-1", project_id: null, organization_id: "org-1", name: "Programmable logic controller with redundant power supply", builtin_key: null, is_builtin: false, sort_order: 2 },
  { id: "sym-long-2", project_id: null, organization_id: "org-1", name: "Supercalifragilisticexpialidocious_transceiver_module", builtin_key: null, is_builtin: false, sort_order: 3 },
  ...Array.from({ length: 60 }, (_, index): ArchitectureSymbol => ({
    id: `sym-extra-${index}`, project_id: null, organization_id: "org-1", name: `Vendor part ${index + 1}`,
    builtin_key: null, is_builtin: false, sort_order: 4 + index,
  })),
];

/** A picker in a column of the given width, the way a card or a form holds it. */
function Harness({ width, above = 0 }: { width: number; above?: number }) {
  const [value, setValue] = useState<string | null>(null);
  return (
    <div style={{ width, padding: 0, paddingTop: above }}>
      <SymbolPicker
        label="Symbol" help="Which drawing the element uses." symbols={LONG_LIBRARY} value={value} onChange={setValue}
        urlFor={(id) => `/symbols/${id}`} emptyLabel="Use the type's symbol" scope={{ kind: "project", projectId: PROJECT_ID }}
      />
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Modules/Architecture/SymbolPicker/Fit",
  component: Harness,
  decorators: [withToast()],
  beforeEach: () => {
    const restoreStorage = isolateSymbolPickerView();
    const reads = mockArchitectureReads({ canManageTypes: true });
    return () => { reads.mockRestore(); restoreStorage(); };
  },
};
export default meta;

type Story = StoryObj<typeof Harness>;

const body = () => within(document.body);

/** Opens the panel and returns its bubble and the field button it opened from. */
async function openPanel(canvasElement: HTMLElement) {
  const trigger = within(canvasElement).getByRole("button", { name: /Symbol:/ });
  await userEvent.click(trigger);
  const bubble = await body().findByRole("dialog", { name: "Choose symbol" });
  await waitFor(() => expect(bubble.style.visibility).toBe("visible"));
  return { bubble, trigger };
}

/** Chooses a view from the buttons below the symbols. */
async function chooseView(name: "List" | "Gallery" | "Upload") {
  const group = await body().findByRole("group", { name: "Symbol view" });
  await userEvent.click(await within(group).findByRole("button", { name }));
}

/**
 * Opens the picker at a width, shows a view and asserts that everything fits.
 *
 * @param width The field's width in CSS pixels.
 * @param view The view to check.
 */
function fitsAt(width: number, view: "List" | "Gallery" | "Upload"): Story {
  return {
    args: { width },
    play: async ({ canvasElement }) => {
      await page.viewport(Math.max(width + 80, 360), 900);
      const { bubble, trigger } = await openPanel(canvasElement);
      if (view !== "List") await chooseView(view);
      // Let the bubble measure again after the view changed its content.
      await waitFor(() => expect(popoverFitViolations(bubble, trigger)).toEqual([]));
    },
  };
}

export const List280: Story = fitsAt(280, "List");
export const List340: Story = fitsAt(340, "List");
export const List390: Story = fitsAt(390, "List");
export const List520: Story = fitsAt(520, "List");
export const Gallery280: Story = fitsAt(280, "Gallery");
export const Gallery340: Story = fitsAt(340, "Gallery");
export const Gallery390: Story = fitsAt(390, "Gallery");
export const Gallery520: Story = fitsAt(520, "Gallery");
export const Upload280: Story = fitsAt(280, "Upload");
export const Upload390: Story = fitsAt(390, "Upload");
export const Upload520: Story = fitsAt(520, "Upload");

/** With room for a usable panel below (here about 300px of a 900px window), the panel stays below the field and scrolls inside, and the field above it stays uncovered. */
export const StaysBelowWhenThereIsUsableRoom: Story = {
  args: { width: 340, above: 520 },
  play: async ({ canvasElement }) => {
    await page.viewport(800, 900);
    const { bubble, trigger } = await openPanel(canvasElement);
    await waitFor(() => expect(popoverFitViolations(bubble, trigger)).toEqual([]));
    await expect(bubble.getBoundingClientRect().top).toBeGreaterThanOrEqual(trigger.getBoundingClientRect().bottom);
  },
};

/** With almost no room below, the panel opens above (the roomier side) and still fits the window. */
export const OpensAboveWhenThereIsNoRoomBelow: Story = {
  args: { width: 340, above: 700 },
  play: async ({ canvasElement }) => {
    await page.viewport(800, 900);
    const { bubble, trigger } = await openPanel(canvasElement);
    await waitFor(() => expect(popoverFitViolations(bubble, trigger)).toEqual([]));
    await expect(bubble.getBoundingClientRect().bottom).toBeLessThanOrEqual(trigger.getBoundingClientRect().top);
  },
};
