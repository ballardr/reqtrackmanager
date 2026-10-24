import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { AuthCard } from "./AuthCard";

const meta: Meta<typeof AuthCard> = {
  title: "Components/AuthCard",
  component: AuthCard,
};
export default meta;

type Story = StoryObj<typeof AuthCard>;

export const Plain: Story = {
  args: { children: <p>Content inside a signed-out card.</p> },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Content inside a signed-out card.")).toBeInTheDocument();
    await expect(canvasElement.querySelector("form")).toBeNull();
  },
};

/** With a submit handler the card is a form, so Enter in a field submits it. */
export const AsForm: Story = {
  args: {
    onSubmit: fn((e) => e.preventDefault()),
    children: <input aria-label="Name" />,
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Name"), "x{Enter}");
    await expect(args.onSubmit).toHaveBeenCalled();
  },
};

export const LightTheme: Story = { ...Plain, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Plain, globals: { theme: "dark" } };
