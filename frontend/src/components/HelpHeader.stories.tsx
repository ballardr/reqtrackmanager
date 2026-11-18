import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { HelpHeader } from "./HelpHeader";

const HELP = "What triggers the transition, for example \"timeout\" or \"button pressed\".";

/** A table column header that names a domain term and carries its plain-language help. */
const meta: Meta<typeof HelpHeader> = {
  title: "Components/HelpHeader",
  component: HelpHeader,
  args: { label: "Event", help: HELP },
  render: (args) => (
    <table className="table" aria-label="Transitions">
      <thead><tr><th scope="col">From</th><HelpHeader {...args} /></tr></thead>
      <tbody><tr><td>Idle</td><td>start</td></tr></tbody>
    </table>
  ),
};
export default meta;

type Story = StoryObj<typeof HelpHeader>;

const tip = () => within(document.body).queryByRole("tooltip", { hidden: true });

/** The column keeps its name; the help is a button named after it and shows its text on hover. */
export const ShowsTheHelpOnHover: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("columnheader", { name: /Event/ })).toBeInTheDocument();
    const button = canvas.getByRole("button", { name: "Help: Event" });
    await userEvent.hover(button);
    await expect(await within(document.body).findByRole("tooltip", { hidden: true })).toHaveTextContent(HELP);
    await userEvent.unhover(button);
    await waitFor(() => expect(tip()).not.toBeInTheDocument());
  },
};

/** The button is reached by Tab and shows the same text on keyboard focus. */
export const ShowsTheHelpOnKeyboardFocus: Story = {
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Help: Event" });
    await userEvent.tab();
    await expect(button).toHaveFocus();
    await expect(await within(document.body).findByRole("tooltip", { hidden: true })).toHaveTextContent(HELP);
  },
};
