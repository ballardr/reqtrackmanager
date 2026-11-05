import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { SectionOrderEditor, type SectionOption } from "./SectionOrderEditor";

const SECTIONS: SectionOption[] = [
  { key: "details", label: "Details" }, { key: "scoring", label: "Scoring" }, { key: "demand", label: "Demand" },
];

function Harness({ initial, onReset }: { initial: string[]; onReset?: () => void }) {
  const [order, setOrder] = useState(initial);
  return <SectionOrderEditor sections={SECTIONS} order={order} onChange={setOrder} onReset={onReset} resetLabel="Use the project order" />;
}

const meta: Meta<typeof Harness> = { title: "Components/SectionOrderEditor", component: Harness, args: { initial: ["details", "scoring", "demand"] } };
export default meta;

type Story = StoryObj<typeof Harness>;

const names = (canvas: ReturnType<typeof within>) => canvas.getAllByRole("listitem").map((li: HTMLElement) => li.textContent?.replace(/^\d+/, "").trim());

/** Moving a section swaps it with its neighbour; the first cannot go up and the last cannot go down. */
export const MovesASectionUpAndDown: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Move Details up" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Move Demand down" })).toBeDisabled();
    await userEvent.click(canvas.getByRole("button", { name: "Move Demand up" }));
    await expect(names(canvas)).toEqual(["Details", "Demand", "Scoring"]);
    await userEvent.click(canvas.getByRole("button", { name: "Move Details down" }));
    await expect(names(canvas)).toEqual(["Demand", "Details", "Scoring"]);
  },
};

export const ResetCallsBack: Story = {
  args: { onReset: fn() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Use the project order" }));
    await expect(args.onReset).toHaveBeenCalled();
  },
};
