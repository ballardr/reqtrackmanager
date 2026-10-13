import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import { AddPopoverButton } from "./AddPopoverButton";

const meta: Meta<typeof AddPopoverButton> = {
  title: "Components/AddPopoverButton",
  component: AddPopoverButton,
  args: { label: "Add to Participants" },
  render: (args) => (
    <div style={{ padding: "4rem" }}>
      <AddPopoverButton {...args}>
        {(close) => (
          <div className="stack">
            <input className="input" aria-label="Name" />
            <button className="btn btn-primary" onClick={close}>Add</button>
          </div>
        )}
      </AddPopoverButton>
    </div>
  ),
};
export default meta;

type Story = StoryObj<typeof AddPopoverButton>;

/** Only the (+) shows until it is pressed; the form opens in a labelled popover and `close` dismisses it. */
export const OpensAFormAndCloses: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    const trigger = canvas.getByRole("button", { name: "Add to Participants" });
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(trigger);
    const dialog = within(within(document.body).getByRole("dialog", { name: "Add to Participants" }));
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};

/** Nothing left to add: the button is disabled and cannot open anything. */
export const DisabledWhenNothingToAdd: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", { name: "Add to Participants" });
    await expect(trigger).toBeDisabled();
    await userEvent.click(trigger);
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...OpensAFormAndCloses, globals: { theme: "light" } };
export const DarkTheme: Story = { ...OpensAFormAndCloses, globals: { theme: "dark" } };

