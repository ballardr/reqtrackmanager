import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { withRouter } from "../testing/storybook-helpers";
import { BarChart } from "./BarChart";

const ariaLabel = (label: string, value: string) => `${label}: ${value}`;

const meta: Meta<typeof BarChart> = {
  title: "Components/BarChart",
  component: BarChart,
  decorators: [withRouter("/", "*")],
  args: {
    title: "Requirements by status", ariaLabel,
    rows: [
      { key: "draft", label: "Draft", value: 4, to: "/projects/project-1/requirements?status=draft" },
      { key: "approved", label: "Approved", value: 15, to: "/projects/project-1/requirements?status=approved" },
      { key: "archived", label: "Archived", value: 0 },
    ],
  },
};
export default meta;

type Story = StoryObj<typeof BarChart>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("img", { name: "Approved: 15" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: /Draft/ })).toHaveAttribute("href", "/projects/project-1/requirements?status=draft");
    // A row with no list to open is text, not a link.
    await expect(canvas.queryByRole("link", { name: /Archived/ })).not.toBeInTheDocument();
  },
};

/** The bars are scaled to the largest value; a percentage row shows its own text. */
export const WithValueText: Story = {
  args: {
    title: "Stage progress",
    rows: [{ key: "a", label: "Scoping", value: 100, valueText: "100%" }, { key: "b", label: "Build", value: 30, valueText: "30%" }],
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("img", { name: "Build: 30%" })).toBeInTheDocument();
  },
};

export const Empty: Story = { args: { rows: [] } };
export const LightTheme: Story = { ...Default, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Default, globals: { theme: "dark" } };
