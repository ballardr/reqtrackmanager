import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { Spinner } from "./Spinner";

const meta: Meta<typeof Spinner> = {
  title: "Components/Spinner",
  component: Spinner,
};
export default meta;

type Story = StoryObj<typeof Spinner>;

export const Default: Story = {};

export const CustomLabel: Story = {
  args: { label: "Uploading file…" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Uploading file…")).toBeInTheDocument();
  },
};

/** U-U-01: light and dark themes are both first-class — these two stories
 * pin the toolbar's theme global so both render (and get checked by
 * `npm run test-storybook`) on every run, not just whichever theme someone
 * happened to have selected while browsing. */
export const LightTheme: Story = {
  globals: { theme: "light" },
  play: async ({ canvasElement }) => {
    const status = within(canvasElement).getByRole("status");
    await expect(status).toBeVisible();
  },
};

export const DarkTheme: Story = {
  globals: { theme: "dark" },
  play: async ({ canvasElement }) => {
    const status = within(canvasElement).getByRole("status");
    await expect(status).toBeVisible();
  },
};
