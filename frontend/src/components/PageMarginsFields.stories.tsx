import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import type { PageMargins } from "../utils/reportPageSetup";
import { PageMarginsFields } from "./PageMarginsFields";

function Host({ initial = {}, inherited, mirror = false }: { initial?: PageMargins; inherited?: PageMargins; mirror?: boolean }) {
  const [margins, setMargins] = useState(initial);
  return (
    <>
      <PageMarginsFields value={margins} onChange={setMargins} inherited={inherited} mirror={mirror} />
      <pre aria-label="Margins">{JSON.stringify(margins)}</pre>
    </>
  );
}

/** The five margin fields (top, bottom, left, right, gutter) in cm; an emptied side is removed so it falls back. */
const meta: Meta<typeof Host> = { title: "Components/PageMarginsFields", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

const value = (el: HTMLElement) => JSON.parse(within(el).getByLabelText("Margins").textContent ?? "null");

/** A side is set when typed and removed when emptied. */
export const TypingSetsASideAndEmptyingRemovesIt: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("spinbutton", { name: "Top" }), "2.5");
    await expect(value(canvasElement)).toEqual({ top: 2.5 });
    await userEvent.clear(canvas.getByRole("spinbutton", { name: "Top" }));
    await expect(value(canvasElement)).toEqual({});
  },
};

/** Inside a page style an empty side shows the layout's value as its placeholder. */
export const AnEmptySideShowsTheInheritedValue: Story = {
  args: { inherited: { top: 3, gutter: 1 } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("spinbutton", { name: "Top" })).toHaveAttribute("placeholder", "3");
    await expect(canvas.getByRole("spinbutton", { name: "Gutter" })).toHaveAttribute("placeholder", "1");
    await expect(canvas.getByRole("spinbutton", { name: "Left" })).toHaveAttribute("placeholder", "1.5");
  },
};

/** While margins mirror, left and right are the inner and outer edge. */
export const MirroredMarginsNameTheInnerAndOuterEdge: Story = {
  args: { mirror: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("spinbutton", { name: "Left (inner)" })).toBeInTheDocument();
    await expect(canvas.getByRole("spinbutton", { name: "Right (outer)" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...MirroredMarginsNameTheInnerAndOuterEdge, globals: { theme: "light" } };
export const DarkTheme: Story = { ...MirroredMarginsNameTheInnerAndOuterEdge, globals: { theme: "dark" } };
