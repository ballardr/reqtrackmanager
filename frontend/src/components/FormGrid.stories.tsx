import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { FormGrid, FormGridFull } from "./FormGrid";

const meta: Meta<typeof FormGrid> = {
  title: "Components/FormGrid",
  component: FormGrid,
  render: (args) => (
    <div style={{ width: 760 }}>
      <FormGrid {...args}>
        <FormGridFull><label className="stack">Title<input className="input" aria-label="Title" /></label></FormGridFull>
        <label className="stack">Channel<select className="input" aria-label="Channel"><option>Email</option></select></label>
        <label className="stack">Date<input className="input" type="date" aria-label="Date" /></label>
        <FormGridFull><label className="stack">Summary<textarea className="input" aria-label="Summary" /></label></FormGridFull>
      </FormGrid>
    </div>
  ),
};
export default meta;

type Story = StoryObj<typeof FormGrid>;

const left = (el: HTMLElement) => el.getBoundingClientRect().left;

/** Short fields share a row; a full-width field spans the whole row and everything shares one left edge. */
export const PairsShortFieldsAndSpansLongOnes: Story = {
  args: { minColumn: "18rem" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const channel = canvas.getByLabelText("Channel");
    const date = canvas.getByLabelText("Date");
    await expect(channel.getBoundingClientRect().top).toBe(date.getBoundingClientRect().top);
    await expect(left(date)).toBeGreaterThan(left(channel));
    await expect(left(canvas.getByLabelText("Title"))).toBe(left(channel));
    await expect(canvas.getByLabelText("Summary").getBoundingClientRect().width).toBeGreaterThan(channel.getBoundingClientRect().width * 1.8);
  },
};

export const LightTheme: Story = { ...PairsShortFieldsAndSpansLongOnes, globals: { theme: "light" } };
export const DarkTheme: Story = { ...PairsShortFieldsAndSpansLongOnes, globals: { theme: "dark" } };
