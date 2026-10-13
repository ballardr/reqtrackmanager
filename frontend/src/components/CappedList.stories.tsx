import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import { CappedList } from "./CappedList";

const NAMES = Array.from({ length: 14 }, (_, i) => `Stakeholder ${i + 1}`);

const meta: Meta<typeof CappedList<string>> = {
  title: "Components/CappedList",
  component: CappedList<string>,
  args: {
    items: NAMES, noun: "Stakeholders", modalTitle: "Manage closely",
    renderList: (items) => <ul>{items.map((n) => <li key={n}>{n}</li>)}</ul>,
  },
};
export default meta;

type Story = StoryObj<typeof CappedList<string>>;

/** More than ten items: ten show, the rest sit behind "Show all N", which opens the whole list in a modal. */
export const CapsAtTenAndShowsAllInAModal: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("listitem")).toHaveLength(10);
    await expect(canvas.queryByText("Stakeholder 11")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Show all 14 Stakeholders" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Manage closely" }));
    await expect(dialog.getAllByRole("listitem")).toHaveLength(14);
    await expect(dialog.getByText("Stakeholder 14")).toBeInTheDocument();
  },
};

/** Ten or fewer: everything shows and there is no button. */
export const NoButtonWithinTheCap: Story = {
  args: { items: NAMES.slice(0, 10) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("listitem")).toHaveLength(10);
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
};

/** The cap is adjustable. */
export const CustomLimit: Story = {
  args: { limit: 3 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("listitem")).toHaveLength(3);
    await expect(canvas.getByRole("button", { name: "Show all 14 Stakeholders" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...CapsAtTenAndShowsAllInAModal, globals: { theme: "light" } };
export const DarkTheme: Story = { ...CapsAtTenAndShowsAllInAModal, globals: { theme: "dark" } };
