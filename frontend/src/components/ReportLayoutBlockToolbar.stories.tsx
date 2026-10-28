import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, within } from "storybook/test";

import { ReportLayoutBlockToolbar } from "./ReportLayoutBlockToolbar";

/** The icon row above the text view that inserts a block's starter text; every icon has a tooltip and an accessible name. */
const meta: Meta<typeof ReportLayoutBlockToolbar> = {
  title: "Components/ReportLayoutBlockToolbar",
  component: ReportLayoutBlockToolbar,
  args: { family: "document", onInsert: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportLayoutBlockToolbar>;

/** Headings are offered by level, one icon each. */
export const OffersHeadingsByLevelAndTheOtherBlocks: Story = {
  play: async ({ canvasElement, args }) => {
    const toolbar = within(within(canvasElement).getByRole("toolbar", { name: "Insert block" }));
    for (const name of ["Heading 1", "Heading 2", "Heading 3", "Text with placeholders", "For each record", "Group records", "Table of records", "If … otherwise", "Equation", "Page break"]) {
      await expect(toolbar.getByRole("button", { name: `Insert block: ${name}` })).toBeInTheDocument();
    }
    await expect(toolbar.queryByRole("button", { name: "Insert block: Sheet" })).not.toBeInTheDocument();
    await userEvent.click(toolbar.getByRole("button", { name: "Insert block: Heading 3" }));
    await expect(args.onInsert).toHaveBeenCalledWith("@heading level=3 Heading");
  },
};

/** The buttons carry no words: the tooltip names the block on hover. */
export const AHoverNamesTheBlock: Story = {
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Insert block: Equation" });
    await expect(button).toHaveTextContent("");
    await userEvent.hover(button);
    await expect(await screen.findByText("Equation")).toBeInTheDocument();
  },
};

export const ATableLayoutOffersSheets: Story = {
  args: { family: "table" },
  play: async ({ canvasElement, args }) => {
    const toolbar = within(canvasElement);
    await expect(toolbar.getAllByRole("button")).toHaveLength(1);
    await userEvent.click(toolbar.getByRole("button", { name: "Insert block: Sheet" }));
    await expect(args.onInsert).toHaveBeenCalledWith(expect.stringContaining("@sheet"));
  },
};

export const LightTheme: Story = { ...OffersHeadingsByLevelAndTheOtherBlocks, globals: { theme: "light" } };
export const DarkTheme: Story = { ...OffersHeadingsByLevelAndTheOtherBlocks, globals: { theme: "dark" } };
