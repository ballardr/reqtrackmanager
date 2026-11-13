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
  await userEvent.click(within(canvasElement).getByRole("button", { name: "Change state" }));
  const menu = within(document.body).getByRole("menu", { name: "Change state" });
  return within(menu).getAllByRole("menuitem").map((i) => (i.textContent ?? "").trim());
}

const CASES: Array<[ArchitectureRecordStatus, ArchitectureRecordStatus[], string[]]> = [
  ["draft", ["planned", "active"], ["Move from Draft to Planned", "Move from Draft to Active"]],
  ["planned", ["active", "draft"], ["Move from Planned to Active", "Move from Planned to Draft"]],
  ["active", ["retired"], ["Move from Active to Retired"]],
  ["retired", ["active"], ["Move from Retired to Active"]],
];

/** From Draft: Planned or Active. */
export const FromDraft: Story = {
  args: { status: CASES[0][0], moves: CASES[0][1] },
  play: async ({ canvasElement }) => { await expect(await itemsOf(canvasElement)).toEqual(CASES[0][2]); },
};

/** From Planned: Active, or back to Draft. */
export const FromPlanned: Story = {
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

/** A record with no allowed moves draws no menu. */
export const NoMovesDrawsNothing: Story = {
  args: { status: "active", moves: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: "Change state" })).not.toBeInTheDocument();
  },
};
