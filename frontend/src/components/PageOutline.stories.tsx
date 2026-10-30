import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { PageOutline } from "./PageOutline";

/** A small sketch of one page, or a facing pair, with its text area inside the margins and the gutter shaded. */
const meta: Meta<typeof PageOutline> = {
  title: "Components/PageOutline",
  component: PageOutline,
  args: { size: "A4", orientation: "portrait", margins: { top: 2, bottom: 2, left: 2, right: 2 } },
};
export default meta;

type Story = StoryObj<typeof PageOutline>;

/** The sketch is named for assistive technology by its paper and direction. */
export const APortraitPage: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("img", { name: "A4 portrait page with its margins" })).toBeInTheDocument();
  },
};

export const ALandscapeA3PageWithAGutter: Story = {
  args: { size: "A3", orientation: "landscape", margins: { gutter: 2 } },
};

/** Mirrored margins draw the facing pair, the gutter on the inner edge of both. */
export const AMirroredPair: Story = {
  args: { mirror: true, margins: { left: 2, right: 1, gutter: 1.5 } },
  play: async ({ canvasElement }) => {
    const sketch = within(canvasElement).getByRole("img");
    await expect(sketch.querySelectorAll("g")).toHaveLength(2);
  },
};

export const LightTheme: Story = { ...AMirroredPair, globals: { theme: "light" } };
export const DarkTheme: Story = { ...AMirroredPair, globals: { theme: "dark" } };
