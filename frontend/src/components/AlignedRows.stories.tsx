import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { AlignedRows } from "./AlignedRows";

const buttons = (name: string) => (
  <>
    <button className="btn btn-sm btn-icon" aria-label={`Edit ${name}`}>E</button>
    <button className="btn btn-sm btn-icon" aria-label={`Delete ${name}`}>D</button>
  </>
);

const meta: Meta<typeof AlignedRows> = {
  title: "Components/AlignedRows",
  component: AlignedRows,
  args: {
    ordered: true,
    ariaLabel: "Prompts",
    rows: [
      { id: "a", lead: "1.", main: "Short", actions: buttons("Short"), detail: "A note under the short row." },
      { id: "b", lead: "2.", main: "A much longer prompt that takes up a lot more of the line than the first one does", actions: buttons("Long") },
      { id: "c", lead: "10.", main: "Medium length prompt", actions: buttons("Medium") },
    ],
  },
  decorators: [(Story) => <div style={{ width: 520 }}><Story /></div>],
};
export default meta;

type Story = StoryObj<typeof AlignedRows>;

/** Rows of different text length keep their action buttons in the same column, and a note sits under its text. */
export const ActionsLineUpAcrossRows: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("listitem")).toHaveLength(3);
    const right = (name: string) => canvas.getByRole("button", { name }).getBoundingClientRect().right;
    await expect(right("Delete Short")).toBe(right("Delete Long"));
    await expect(right("Delete Long")).toBe(right("Delete Medium"));
    await expect(canvas.getByRole("button", { name: "Edit Short" }).getBoundingClientRect().left)
      .toBe(canvas.getByRole("button", { name: "Edit Long" }).getBoundingClientRect().left);
    await expect(canvas.getByText("A note under the short row.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ActionsLineUpAcrossRows, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ActionsLineUpAcrossRows, globals: { theme: "dark" } };
