import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";
import { MemoryRouter } from "react-router-dom";

import { buttonHeightViolations } from "../../testing/buttonHeights";
import { iconSizeViolations } from "../../testing/iconSizes";
import { selectionAction } from "./selectionAction";
import { SelectionActions } from "./SelectionActions";

/**
 * The action row of a diagram editor's Selection card: icon buttons named by their tooltip, one overflow menu for a rare
 * action, a link for a destination, and nothing at all when there is nothing to offer.
 */
const meta: Meta<typeof SelectionActions> = {
  title: "Modules/Architecture/SelectionActions",
  component: SelectionActions,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
};
export default meta;

type Story = StoryObj<typeof SelectionActions>;

/** Each common action is an icon-only control with its name, and neighbours share a height and icon size. */
export const IconButtons: Story = {
  args: {
    actions: [
      selectionAction.open("Open element", "/elements/1"),
      selectionAction.edit("Edit element", fn()),
      selectionAction.comment("Comment on this box", fn()),
      selectionAction.remove("Remove from diagram", fn()),
      selectionAction.delete("Delete element…", fn()),
    ],
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Open element" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Edit element" }));
    await expect(args.actions[1]).toMatchObject({ label: "Edit element" });
    for (const control of canvasElement.querySelectorAll("a, button")) await expect(control.textContent?.trim()).toBe("");
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
    await expect(iconSizeViolations(canvasElement)).toEqual([]);
  },
};

/** An action marked `menu` leaves the row for one "More actions" menu with a labelled list. */
export const OverflowMenu: Story = {
  args: {
    actions: [
      selectionAction.edit("Edit element", fn()),
      { ...selectionAction.inside("Open inside as diagram", fn()), menu: true },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Open inside as diagram" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "More actions" }));
    await expect(await within(document.body).findByRole("menuitem", { name: /Open inside as diagram/ })).toBeInTheDocument();
    await expect(buttonHeightViolations(canvasElement)).toEqual([]);
  },
};

/** With nothing to offer (a read-only card) no empty strip is drawn. */
export const NothingToOffer: Story = {
  args: { actions: [false, undefined] },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector("[role=group]")).toBeNull();
  },
};
