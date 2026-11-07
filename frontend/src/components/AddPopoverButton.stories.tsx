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


/** With `text` the button says what it adds ("+ Field") and still has the same accessible name. */
export const ShowsAWordBesideThePlus: Story = {
  args: { label: "Insert a field into Text", text: "Field" },
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", { name: "Insert a field into Text" });
    await expect(trigger).toHaveTextContent("Field");
    await expect(trigger).not.toHaveClass("btn-icon");
  },
};

/** The panel opens to the right of the (+) with their top edges level, so it does not cover the list the button belongs to. */
export const OpensBesideTheButton: Story = {
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", { name: "Add to Participants" });
    await userEvent.click(trigger);
    const panel = within(document.body).getByRole("dialog", { name: "Add to Participants" });
    const triggerBox = trigger.getBoundingClientRect();
    const panelBox = panel.getBoundingClientRect();
    await expect(panelBox.left).toBeGreaterThanOrEqual(triggerBox.right);
    await expect(Math.abs(panelBox.top - triggerBox.top)).toBeLessThan(1);
  },
};
