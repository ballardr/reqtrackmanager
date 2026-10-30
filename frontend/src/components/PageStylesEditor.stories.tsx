import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import type { PageStyleSetup } from "../utils/reportPageSetup";
import { PageStylesEditor } from "./PageStylesEditor";

const BASE = { size: "A4", orientation: "portrait", margins: {}, mirror: false } as const;

function Host({ initial = [], disabled = false }: { initial?: PageStyleSetup[]; disabled?: boolean }) {
  const [styles, setStyles] = useState(initial);
  return (
    <>
      <PageStylesEditor value={styles} onChange={setStyles} base={BASE} disabled={disabled} />
      <pre aria-label="Styles">{JSON.stringify(styles)}</pre>
    </>
  );
}

/** The list of a layout's named page styles: name, paper, orientation and margins each, with a sketch of the page. */
const meta: Meta<typeof Host> = { title: "Components/PageStylesEditor", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

const value = (el: HTMLElement) => JSON.parse(within(el).getByLabelText("Styles").textContent ?? "null");

export const NoStylesYet: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No page styles yet.")).toBeInTheDocument();
  },
};

/** A new style is named and then given only what differs; a choice set back to "same as the layout" is removed. */
export const AddingAndEditingAStyle: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add page style" }));
    await expect(value(canvasElement)).toEqual([{ name: "Style 1" }]);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Page size" }), "A3");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Orientation" }), "landscape");
    await expect(value(canvasElement)).toEqual([{ name: "Style 1", size: "A3", orientation: "landscape" }]);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Page size" }), "");
    await expect(value(canvasElement)).toEqual([{ name: "Style 1", orientation: "landscape" }]);
    await userEvent.type(canvas.getByRole("spinbutton", { name: "Gutter" }), "1");
    await expect(value(canvasElement)).toEqual([{ name: "Style 1", orientation: "landscape", margins: { gutter: 1 } }]);
  },
};

export const RemovingAStyle: Story = {
  render: () => <Host initial={[{ name: "A" }, { name: "B" }]} />,
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Remove page style A" }));
    await expect(value(canvasElement)).toEqual([{ name: "B" }]);
  },
};

/** Read-only: nothing can be added, removed or typed. */
export const ReadOnly: Story = {
  render: () => <Host initial={[{ name: "Wide", size: "A3" }]} disabled />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Add page style" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("textbox", { name: "Name" })).toBeDisabled();
  },
};

export const LightTheme: Story = { render: () => <Host initial={[{ name: "Wide", size: "A3", orientation: "landscape" }]} />, globals: { theme: "light" } };
export const DarkTheme: Story = { ...LightTheme, globals: { theme: "dark" } };
