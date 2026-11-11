import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { Gauge } from "./Gauge";

const levelLabels = { ok: "Within range", warning: "Warning", critical: "Critical" };
const ariaLabel = (label: string, value: string, level: string) => `${label}: ${value}, ${level}`;

const meta: Meta<typeof Gauge> = {
  title: "Components/Gauge",
  component: Gauge,
  args: { label: "Open risks", minimum: 0, maximum: 20, levelLabels, ariaLabel },
};
export default meta;

type Story = StoryObj<typeof Gauge>;

export const WithinRange: Story = {
  args: { value: 4, valueText: "4", warning: 10, critical: 15 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("img", { name: "Open risks: 4, Within range" })).toBeInTheDocument();
    await expect(canvasElement.querySelector("[data-gauge-level]")).toHaveAttribute("data-gauge-level", "ok");
  },
};

/** A level counts as reached when the value equals it. */
export const WarningAtTheLevel: Story = {
  args: { value: 10, valueText: "10", warning: 10, critical: 15 },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("img", { name: "Open risks: 10, Warning" })).toBeInTheDocument();
  },
};

export const Critical: Story = {
  args: { value: 18, valueText: "18", warning: 10, critical: 15 },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("img", { name: "Open risks: 18, Critical" })).toBeInTheDocument();
  },
};

/** For progress, less is worse: the levels are reached at or below. */
export const BelowDirection: Story = {
  args: { value: 15, valueText: "15%", minimum: 0, maximum: 100, warning: 40, critical: 20, direction: "below", label: "Complete" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("img", { name: "Complete: 15%, Critical" })).toBeInTheDocument();
  },
};

/** A value beyond the range is drawn at the end of the dial and still reads as its figure. */
export const BeyondTheRange: Story = {
  args: { value: 50, valueText: "50", warning: 10, critical: 15 },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("50")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...WarningAtTheLevel, globals: { theme: "light" } };
export const DarkTheme: Story = { ...WarningAtTheLevel, globals: { theme: "dark" } };
