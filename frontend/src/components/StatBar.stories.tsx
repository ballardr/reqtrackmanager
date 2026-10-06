import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { statBlockViolations } from "../testing/statBlockGeometry";
import { StatBar, StatBarEntry, type StatBarItem } from "./StatBar";

const meta: Meta<typeof StatBar> = {
  title: "Components/StatBar",
  component: StatBar,
};
export default meta;

type Story = StoryObj<typeof StatBar>;

export const Default: Story = {
  args: {
    items: [
      { key: "projects", label: "Projects", value: 7 },
      { key: "requirements", label: "Requirements", value: 36 },
      { key: "members", label: "Members", value: 4 },
      { key: "storage", label: "File storage", value: "121 B" },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Projects")).toBeInTheDocument();
    await expect(canvas.getByText("7")).toBeInTheDocument();
    await expect(canvas.getByText("File storage")).toBeInTheDocument();
    await expect(canvas.getByText("121 B")).toBeInTheDocument();
  },
};

/** A module's own contributed headline stat (e.g.
 * `modules/compliance/ComplianceOrgOverviewTiles.tsx`) renders `StatBarEntry`
 * directly as `children`, splicing into the same row as `items` with
 * identical spacing/dividers rather than a second implementation. */
export const WithContributedEntry: Story = {
  args: {
    items: [
      { key: "projects", label: "Projects", value: 7 },
      { key: "requirements", label: "Requirements", value: 36 },
    ],
    children: <StatBarEntry label="Overall org compliance" value="33%" />,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Projects")).toBeInTheDocument();
    await expect(canvas.getByText("Overall org compliance")).toBeInTheDocument();
    await expect(canvas.getByText("33%")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...Default, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Default, globals: { theme: "dark" } };

/** Worst-case fixtures: these are what the summary report once dumped into one bar. */
const longLabel = "Pain Point coverage and ageing: Accepted with no motivated Requirement";
const manyItems: StatBarItem[] = Array.from({ length: 25 }, (_, i) => ({
  key: `m${i}`,
  label: i % 3 === 0 ? "Accepted, no Requirement" : `Measure ${i + 1}`,
  value: i * 7,
  gap: i % 4 === 0,
}));
/** Pins the geometry at the widths the app is used at; a viewport media query could not do this inside a story,
 * so the container is sized directly (the layouts size to their container, with no viewport media queries). */
const atWidth = (width: number) => (Story: () => React.JSX.Element) => (
  <div style={{ width, maxWidth: "100%", boxSizing: "border-box" }}>
    <Story />
  </div>
);
const tidy = async ({ canvasElement }: { canvasElement: HTMLElement }) => {
  await expect(statBlockViolations(canvasElement)).toEqual([]);
};

/** More entries than the flat budget still lay out in aligned, equal-height columns (budget-length labels). */
export const TwentyFiveEntriesStayTidy: Story = { args: { items: manyItems }, play: tidy, decorators: [atWidth(1200)] };
export const TwentyFiveEntriesNarrow: Story = { args: { items: manyItems }, play: tidy, decorators: [atWidth(375)] };
export const FlatBudgetOnPhone: Story = {
  args: { items: manyItems.slice(0, 8), children: <StatBarEntry label="Overall org compliance" value="33%" /> },
  play: tidy,
  decorators: [atWidth(375)],
};

/** A non-zero gap figure is flagged in words as well as colour; a zero gap is not. */
export const GapFiguresAreFlaggedInWords: Story = {
  args: {
    items: [
      { key: "a", label: "Overdue", value: 2, gap: true },
      { key: "b", label: "Unowned", value: 0, gap: true },
      { key: "c", label: "Total", value: 9 },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByText("Needs attention")).toHaveLength(1);
  },
};

/** The guard has teeth: a 70-character label in a flat bar is a violation (group the block instead), so the
 * assertion every other story runs would fail on the layout that made the summary report unreadable. */
export const GuardRejectsLongLabelsInAFlatBar: Story = {
  args: { items: [{ key: "x", label: longLabel, value: 1 }, ...manyItems.slice(0, 6)] },
  decorators: [atWidth(1200)],
  play: async ({ canvasElement }) => {
    const violations = statBlockViolations(canvasElement);
    await expect(violations.some((v) => v.includes("wraps onto"))).toBe(true);
  },
};
