import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { StatBar, StatBarEntry } from "./StatBar";

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
