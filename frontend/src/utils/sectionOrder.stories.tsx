import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { applySectionOrder, moveSection, resolveSectionOrder } from "./sectionOrder";

const BUILTIN = ["details", "scoring", "demand", "comments"];

/** Pure-function checks for how a record page's section order is resolved, run as stories like the other helpers. */
const meta: Meta = { title: "Utils/SectionOrder" };
export default meta;

type Story = StoryObj;

export const WithoutALayerTheBuiltInOrderStands: Story = {
  render: () => <div>No layer</div>,
  play: async () => {
    await expect(applySectionOrder(BUILTIN, null)).toEqual(BUILTIN);
    await expect(applySectionOrder(BUILTIN, [])).toEqual(BUILTIN);
  },
};

export const NamedKeysComeFirstAndTheRestFollow: Story = {
  render: () => <div>Named first</div>,
  play: async () => {
    await expect(applySectionOrder(BUILTIN, ["demand", "details"])).toEqual(["demand", "details", "scoring", "comments"]);
  },
};

/** A retired section in a saved order, or a repeated one, never breaks the page. */
export const UnknownAndRepeatedKeysAreIgnored: Story = {
  render: () => <div>Unknown keys</div>,
  play: async () => {
    await expect(applySectionOrder(BUILTIN, ["gone", "comments", "comments"])).toEqual(["comments", "details", "scoring", "demand"]);
  },
};

export const TheFirstNonEmptyLayerWinsAndLayersNeverMerge: Story = {
  render: () => <div>Layers</div>,
  play: async () => {
    await expect(resolveSectionOrder(BUILTIN, ["comments"], ["demand"])).toEqual(["comments", "details", "scoring", "demand"]);
    await expect(resolveSectionOrder(BUILTIN, [], ["demand"])).toEqual(["demand", "details", "scoring", "comments"]);
    await expect(resolveSectionOrder(BUILTIN, undefined, null)).toEqual(BUILTIN);
  },
};

export const MovingSwapsWithTheNeighbourAndStopsAtTheEnds: Story = {
  render: () => <div>Move</div>,
  play: async () => {
    await expect(moveSection(BUILTIN, "scoring", -1)).toEqual(["scoring", "details", "demand", "comments"]);
    await expect(moveSection(BUILTIN, "details", -1)).toEqual(BUILTIN);
    await expect(moveSection(BUILTIN, "comments", 1)).toEqual(BUILTIN);
    await expect(moveSection(BUILTIN, "nope", 1)).toEqual(BUILTIN);
  },
};
