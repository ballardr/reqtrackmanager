import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { ArchitectureStatusControls } from "./ArchitectureStatusControls";
import type { ArchitectureRecordStatus } from "./types";

const meta: Meta<typeof ArchitectureStatusControls> = {
  title: "Modules/Architecture/ArchitectureStatusControls",
  component: ArchitectureStatusControls,
  args: { onMove: fn() },
};
export default meta;
type Story = StoryObj<typeof ArchitectureStatusControls>;

/** Opens the menu and returns the names of its items. */
async function itemsOf(canvasElement: HTMLElement): Promise<string[]> {
  await userEvent.click(within(canvasElement).getByRole("button", { name: "Change status" }));
  const menu = within(document.body).getByRole("menu", { name: "Change status" });
  return within(menu).getAllByRole("menuitem").map((i) => (i.textContent ?? "").trim());
}

const CASES: Array<[ArchitectureRecordStatus, ArchitectureRecordStatus[], string[]]> = [
  ["draft", ["proposed", "active", "rejected"],
    ["Move from Draft to Proposed", "Move from Draft to Active", "Move from Draft to Rejected"]],
  ["proposed", ["active", "draft", "rejected"],
    ["Move from Proposed to Active", "Move from Proposed to Draft", "Move from Proposed to Rejected"]],
  ["active", ["retired"], ["Move from Active to Retired"]],
  ["retired", ["active"], ["Move from Retired to Active"]],
  ["rejected", ["draft"], ["Move from Rejected to Draft"]],
];

/** From Draft: Proposed, Active or Rejected. */
export const FromDraft: Story = {
  args: { status: CASES[0][0], moves: CASES[0][1] },
  play: async ({ canvasElement }) => { await expect(await itemsOf(canvasElement)).toEqual(CASES[0][2]); },
};

/** From Proposed: Active, back to Draft, or Rejected. */
export const FromProposed: Story = {
  args: { status: CASES[1][0], moves: CASES[1][1] },
  play: async ({ canvasElement }) => { await expect(await itemsOf(canvasElement)).toEqual(CASES[1][2]); },
};

/** From Active: Retired. */
export const FromActive: Story = {
  args: { status: CASES[2][0], moves: CASES[2][1] },
  play: async ({ canvasElement }) => { await expect(await itemsOf(canvasElement)).toEqual(CASES[2][2]); },
};

/** From Retired: Active again. Choosing an item reports the target state and closes the menu. */
export const FromRetiredAndChoosing: Story = {
  args: { status: CASES[3][0], moves: CASES[3][1] },
  play: async ({ canvasElement, args }) => {
    await expect(await itemsOf(canvasElement)).toEqual(CASES[3][2]);
    await userEvent.click(within(document.body).getByRole("menuitem", { name: "Move from Retired to Active" }));
    await expect(args.onMove).toHaveBeenCalledWith("active");
  },
};

/** From Rejected: reopened as a Draft. */
export const FromRejected: Story = {
  args: { status: CASES[4][0], moves: CASES[4][1] },
  play: async ({ canvasElement }) => { await expect(await itemsOf(canvasElement)).toEqual(CASES[4][2]); },
};

/** A record with no allowed moves draws no menu. */
export const NoMovesDrawsNothing: Story = {
  args: { status: "active", moves: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: "Change status" })).not.toBeInTheDocument();
  },
};
