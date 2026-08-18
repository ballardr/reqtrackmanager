import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { OverridePill } from "./OverridePill";

const meta: Meta<typeof OverridePill> = {
  title: "Components/OverridePill",
  component: OverridePill,
};
export default meta;

type Story = StoryObj<typeof OverridePill>;

export const PlatformDefault: Story = {
  args: { custom: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Platform default")).toBeInTheDocument();
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
};

export const CustomWithReset: Story = {
  args: { custom: true, onReset: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Custom")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Reset to platform default" }));
    await expect(args.onReset).toHaveBeenCalledOnce();
  },
};

/** No `onReset` passed — the pill still states "Custom" but offers no
 * reset action, e.g. while a field's revert path isn't wired up yet. */
export const CustomWithoutReset: Story = {
  args: { custom: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Custom")).toBeInTheDocument();
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
};

/** For overrides with no local edit state to revert to (the org logo and
 * login-background image, which reset via an immediate `DELETE` call
 * rather than a batched Save) — `disabled` prevents a double-submit while
 * that request is in flight. */
export const CustomWithResetDisabledWhileSaving: Story = {
  args: { custom: true, onReset: fn(), disabled: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Reset to platform default" })).toBeDisabled();
  },
};

export const LightTheme: Story = { args: { custom: true, onReset: fn() }, globals: { theme: "light" } };
export const DarkTheme: Story = { args: { custom: true, onReset: fn() }, globals: { theme: "dark" } };
