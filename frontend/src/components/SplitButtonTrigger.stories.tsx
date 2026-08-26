import type { Meta, StoryObj } from "@storybook/react-vite";
import { Plus } from "lucide-react";
import { expect, fn, userEvent, within } from "storybook/test";

import { SplitButtonTrigger } from "./SplitButtonTrigger";

const meta: Meta<typeof SplitButtonTrigger> = {
  title: "Components/SplitButtonTrigger",
  component: SplitButtonTrigger,
  args: {
    icon: <Plus size={16} />,
    label: "New requirement",
    menuTitle: "New requirement",
    moreOptionsLabel: "More options",
    onDefaultAction: fn(),
    alternatives: [{ label: "Import from CSV", onSelect: fn() }],
  },
};
export default meta;

type Story = StoryObj<typeof SplitButtonTrigger>;

/** The whole point of a split button (style guide "Pattern: split-button
 * trigger"): clicking the main label performs the common-case action
 * immediately — no menu stop first, unlike the `Popover`-based two-option
 * menu this component replaces on `RequirementsPage`. */
export const ClickingMainButtonPerformsDefaultActionDirectly: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "New requirement" }));
    await expect(args.onDefaultAction).toHaveBeenCalledOnce();
    // No menu ever opened for the common-case click.
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};

/** The chevron is a separate control from the main button — its own
 * accessible name (`moreOptionsLabel`), not "New requirement" again, so
 * `getByRole("button", { name: "New requirement" })` unambiguously
 * resolves to the primary action even though both buttons render inside
 * the same `.split-button` group. Clicking it reveals the alternative(s)
 * without ever firing the default action. */
export const ChevronRevealsAlternativesWithoutFiringDefault: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "More options" }));
    await expect(args.onDefaultAction).not.toHaveBeenCalled();

    const menu = within(document.body).getByRole("dialog", { name: "New requirement" });
    const csvOption = within(menu).getByRole("button", { name: "Import from CSV" });
    await expect(csvOption).toBeInTheDocument();

    await userEvent.click(csvOption);
    await expect(args.alternatives[0].onSelect).toHaveBeenCalledOnce();
    // Selecting an alternative closes the menu and never calls the default
    // action either — the two are mutually exclusive outcomes of one click.
    await expect(args.onDefaultAction).not.toHaveBeenCalled();
    await expect(within(document.body).queryByRole("dialog", { name: "New requirement" })).not.toBeInTheDocument();
  },
};

/** Clicking outside the revealed menu closes it — shared `Popover`
 * outside-click-close behaviour, per this component's own design note
 * that it reuses `Popover`'s positioning/close logic rather than
 * reimplementing it. */
export const OutsideClickClosesTheMenu: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "More options" }));
    await expect(within(document.body).getByRole("dialog", { name: "New requirement" })).toBeInTheDocument();

    await userEvent.click(document.body);
    await expect(within(document.body).queryByRole("dialog", { name: "New requirement" })).not.toBeInTheDocument();
  },
};

export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "New requirement" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "More options" })).toBeDisabled();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
