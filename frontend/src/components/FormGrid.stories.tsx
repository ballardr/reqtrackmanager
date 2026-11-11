import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { FormDivider, FormGrid, FormGridFull } from "./FormGrid";

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

/** A divider spans the whole row between two groups of fields and is hidden from assistive technology. */
export const DividerSpansTheRowBetweenGroups: Story = {
  args: { minColumn: "18rem" },
  render: (args) => (
    <div style={{ width: 760 }}>
      <FormGrid {...args}>
        <label className="stack">Organisation<select className="input" aria-label="Organisation"><option>Acme</option></select></label>
        <FormDivider />
        <label className="stack">Name<input className="input" aria-label="Name" /></label>
        <label className="stack">Code<input className="input" aria-label="Code" /></label>
      </FormGrid>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const rule = canvasElement.querySelector(".form-divider") as HTMLElement;
    await expect(rule).toHaveAttribute("aria-hidden", "true");
    await expect(rule.getBoundingClientRect().width).toBeGreaterThan(canvas.getByLabelText("Name").getBoundingClientRect().width * 1.8);
    await expect(canvas.getByLabelText("Organisation").getBoundingClientRect().bottom).toBeLessThan(rule.getBoundingClientRect().top);
    await expect(rule.getBoundingClientRect().bottom).toBeLessThan(canvas.getByLabelText("Name").getBoundingClientRect().top);
  },
};
