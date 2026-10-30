import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { selectionFromLines, selectionOfBlock } from "./reportSnippetSelection";

/** Pure-function checks for turning a selection in the designer into the blocks Save as snippet saves, run as stories like the other helpers. */
const meta: Meta = { title: "Utils/ReportSnippetSelection" };
export default meta;

type Story = StoryObj;

// @layout document (1), @heading (3), @group ... (5) with a child (6) and @end (7), a text line (9).
const LINES = { "nodes[0]": 3, "nodes[1]": 5, "nodes[1].children[0]": 6, "nodes[2]": 9 };

export const ABlocksSelectionIsTheOneBlockInItsOwnList: Story = {
  render: () => <div>Selection</div>,
  play: async () => {
    await expect(selectionOfBlock(["nodes", 2])).toEqual({ container: "nodes", start: 2, count: 1 });
    await expect(selectionOfBlock(["nodes", 1, "children", 0])).toEqual({ container: "nodes[1].children", start: 0, count: 1 });
    await expect(selectionOfBlock(["nodes"])).toBeNull();
    await expect(selectionOfBlock(["nodes", 1, "children"])).toBeNull();
  },
};

export const ACaretSelectsTheTopLevelBlockItIsIn: Story = {
  render: () => <div>Selection</div>,
  play: async () => {
    await expect(selectionFromLines(LINES, 3, 3)).toEqual({ container: "nodes", start: 0, count: 1 });
    // Inside a container the caret is in the container block, which is saved with its children.
    await expect(selectionFromLines(LINES, 6, 6)).toEqual({ container: "nodes", start: 1, count: 1 });
    await expect(selectionFromLines(LINES, 7, 7)).toEqual({ container: "nodes", start: 1, count: 1 });
    // The last block runs to the end of the text.
    await expect(selectionFromLines(LINES, 40, 40)).toEqual({ container: "nodes", start: 2, count: 1 });
  },
};

export const ASelectionTakesEveryTopLevelBlockItTouches: Story = {
  render: () => <div>Selection</div>,
  play: async () => {
    await expect(selectionFromLines(LINES, 4, 9)).toEqual({ container: "nodes", start: 0, count: 3 });
    await expect(selectionFromLines(LINES, 6, 9)).toEqual({ container: "nodes", start: 1, count: 2 });
    await expect(selectionFromLines(LINES, 1, 3)).toEqual({ container: "nodes", start: 0, count: 1 });
  },
};

export const LinesBeforeTheFirstBlockOrAnEmptyLayoutTouchNothing: Story = {
  render: () => <div>Selection</div>,
  play: async () => {
    await expect(selectionFromLines(LINES, 1, 2)).toBeNull();
    await expect(selectionFromLines({}, 1, 5)).toBeNull();
  },
};
