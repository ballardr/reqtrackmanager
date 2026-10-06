import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { statBlockViolations } from "../testing/statBlockGeometry";
import { StatGroups, type StatGroup } from "./StatGroups";

const meta: Meta<typeof StatGroups> = {
  title: "Components/StatGroups",
  component: StatGroups,
};
export default meta;

type Story = StoryObj<typeof StatGroups>;

const longLabel = "Pain Point coverage and ageing: Accepted with no motivated Requirement";

/** Eight cards of 2-5 rows with long titles and labels: the summary report's worst case. */
const groups: StatGroup[] = Array.from({ length: 8 }, (_, g) => ({
  key: `g${g}`,
  title: `Report ${g + 1} with a fairly long title`,
  items: Array.from({ length: 2 + (g % 4) }, (_, i) => ({
    key: `g${g}i${i}`,
    label: i === 0 ? "Open Pain Points (excluding intentional)" : `Measure ${i + 1}`,
    value: i,
    gap: i > 0,
  })),
}));

/** Sizes the container directly: the layout has no viewport media queries, it follows its container. */
const atWidth = (width: number) => (Story: () => React.JSX.Element) => (
  <div style={{ width, maxWidth: "100%", boxSizing: "border-box" }}>
    <Story />
  </div>
);
const tidy = async ({ canvasElement }: { canvasElement: HTMLElement }) => {
  await expect(statBlockViolations(canvasElement)).toEqual([]);
};

/** A card per source, each with a heading, a gap badge and measure/value rows. */
export const Default: Story = {
  args: {
    groups: [
      {
        key: "pp",
        title: "Pain Point prioritisation",
        items: [
          { key: "o", label: "Open Pain Points", value: 3 },
          { key: "b", label: "Blockers", value: 1, gap: true },
          { key: "n", label: "Not scored", value: 0, gap: true },
        ],
      },
      { key: "h", title: "Strategy change history", items: [{ key: "v", label: "Versions in range", value: 29 }] },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = within(canvas.getByRole("region", { name: "Pain Point prioritisation" }));
    await expect(card.getByText("Needs attention · 1")).toBeInTheDocument();
    await expect(card.getByText("needs attention")).toBeInTheDocument(); // the pill's screen-reader text, exact case
    // A card with no gap figures carries no badge at all.
    const plain = within(canvas.getByRole("region", { name: "Strategy change history" }));
    await expect(plain.queryByText(/Needs attention|No gaps/)).not.toBeInTheDocument();
    await expect(statBlockViolations(canvasElement)).toEqual([]);
  },
};

/** Zero-valued gap figures are muted and the card reads "No gaps". */
export const NoGaps: Story = {
  args: { groups: [{ key: "g", title: "Open Question register", items: [{ key: "o", label: "Overdue", value: 0, gap: true }] }] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No gaps")).toBeInTheDocument();
  },
};

export const Desktop: Story = { args: { groups }, play: tidy, decorators: [atWidth(1200)] };
export const Tablet: Story = { args: { groups }, play: tidy, decorators: [atWidth(720)] };
export const Phone: Story = { args: { groups }, play: tidy, decorators: [atWidth(375)] };

/** Long measure names wrap inside the row instead of squeezing the number; this is why such blocks belong here. */
export const LongLabelsWrap: Story = {
  args: { groups: [{ key: "g", title: "Pain Point coverage and ageing", items: [{ key: "x", label: longLabel, value: 1 }] }] },
  decorators: [atWidth(375)],
  play: tidy,
};

export const LightTheme: Story = { ...Default, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Default, globals: { theme: "dark" } };
