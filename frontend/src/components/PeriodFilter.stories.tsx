import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { PeriodFilter } from "./PeriodFilter";

const meta: Meta<typeof PeriodFilter> = {
  title: "Components/PeriodFilter",
  component: PeriodFilter,
  args: { period: "", since: "", until: "", onPeriod: fn(), onSince: fn(), onUntil: fn() },
};
export default meta;

type Story = StoryObj<typeof PeriodFilter>;

/** Any time shows only the preset select, whose options are the presets and Custom range. */
export const AnyTime: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = canvas.getByLabelText("Period");
    for (const name of ["Any time", "Today", "Last 7 days", "Last 30 days", "Custom range"]) {
      await expect(within(select).getByRole("option", { name })).toBeInTheDocument();
    }
    await expect(canvas.queryByLabelText("From")).not.toBeInTheDocument();
    await userEvent.selectOptions(select, "Today");
    await expect(meta.args?.onPeriod).toHaveBeenCalledWith("today");
  },
};

/** The custom range shows the two date-time inputs. */
export const Custom: Story = {
  args: { period: "custom", since: "2026-02-03T09:00", until: "2026-02-03T17:00" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("From")).toHaveValue("2026-02-03T09:00");
    await expect(canvas.getByLabelText("To")).toHaveValue("2026-02-03T17:00");
  },
};
